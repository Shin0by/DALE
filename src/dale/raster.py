"""Shared alpha renderer and bounded-memory, atomic RGBA PNG export."""

from __future__ import annotations

import math
import os
import struct
import tempfile
import zlib
from collections.abc import Callable, Sequence
from itertools import pairwise
from pathlib import Path

import psutil
from PIL import Image, ImageChops, ImageDraw

from dale.placement import Placement
from dale.scene import SceneInput, open_source
from dale.session import ContourMask, Operation, Stroke

PREVIEW_SIDE = 2048
STRIPE_ROWS = 128


class ExportCancelled(Exception):
    pass


def load_preview(source: SceneInput) -> Image.Image:
    with open_source(source.image_path) as image:
        image.draft("RGB", (PREVIEW_SIDE, PREVIEW_SIDE))
        image.thumbnail((PREVIEW_SIDE, PREVIEW_SIDE), Image.Resampling.LANCZOS)
        return image.convert("RGB")


def _polygon_mask(size, area, sx, sy, top):
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    polygons = [area] if area.geom_type == "Polygon" else list(area.geoms)
    for polygon in polygons:
        if polygon.is_empty or polygon.geom_type != "Polygon":
            continue
        if polygon.bounds[3] * sy < top or polygon.bounds[1] * sy > top + size[1]:
            continue

        def project(ring):
            return [(math.floor(x * sx), math.floor(y * sy) - top) for x, y in ring.coords]

        draw.polygon(project(polygon.exterior), fill=255)
        for ring in polygon.interiors:
            draw.polygon(project(ring), fill=0)
    return mask


def render_alpha(
    size: tuple[int, int],
    native_size: tuple[int, int],
    operations: Sequence[Operation],
    top: int = 0,
    scale: tuple[float, float] | None = None,
) -> Image.Image:
    """Render a preview or export stripe; top is measured in output pixels."""
    sx, sy = scale or (size[0] / native_size[0], size[1] / native_size[1])
    alpha = Image.new("L", size, 255)
    for operation in operations:
        if isinstance(operation, ContourMask):
            region = _polygon_mask(size, operation.area, sx, sy, top)
            if operation.mode == "inside":
                region = ImageChops.invert(region)
            alpha = ImageChops.multiply(alpha, region)
        elif isinstance(operation, Stroke) and operation.points:
            rx, ry = max(0.5, operation.radius * sx), max(0.5, operation.radius * sy)
            points = [(x * sx, y * sy - top) for x, y in operation.points]
            if max(p[1] for p in points) + ry < 0 or min(p[1] for p in points) - ry > size[1]:
                continue
            draw = ImageDraw.Draw(alpha)
            value = 255 if operation.restore else 0
            # Polygonal segments and elliptical caps prevent gaps even with sparse events.
            for a, b in pairwise(points):
                dx, dy = (b[0] - a[0]) / sx, (b[1] - a[1]) / sy
                length = (dx * dx + dy * dy) ** 0.5
                if length:
                    nx, ny = -dy / length * rx, dx / length * ry
                    corners = [
                        (a[0] + nx, a[1] + ny),
                        (b[0] + nx, b[1] + ny),
                        (b[0] - nx, b[1] - ny),
                        (a[0] - nx, a[1] - ny),
                    ]
                    draw.polygon([(math.floor(x), math.floor(y)) for x, y in corners], fill=value)
            for x, y in points:
                draw.ellipse(
                    tuple(math.floor(v) for v in (x - rx, y - ry, x + rx, y + ry)), fill=value
                )
    return alpha


def render_preview(source: Image.Image, native_size, operations) -> Image.Image:
    result = source.convert("RGBA")
    result.putalpha(render_alpha(source.size, native_size, operations))
    return result


def _chunk(stream, kind: bytes, data: bytes):
    stream.write(struct.pack(">I", len(data)))
    stream.write(kind)
    stream.write(data)
    stream.write(struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))


def export_png(
    source: SceneInput,
    operations: Sequence[Operation],
    destination: Path,
    progress: Callable[[int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    placement: Placement | None = None,
):
    destination = destination.resolve()
    if destination in (source.image_path.resolve(), source.json_path.resolve()):
        raise ValueError("Export cannot replace an imported source file.")
    if destination.suffix.lower() != ".png":
        raise ValueError("Export destination must have a .png extension.")
    if destination.exists() and any(
        os.path.samefile(destination, path) for path in (source.image_path, source.json_path)
    ):
        raise ValueError("Export cannot replace a hard-linked source file.")
    width, height = source.size
    required = width * height * 4 + 256 * 1024 * 1024
    if psutil.virtual_memory().available < required:
        raise MemoryError(f"Export needs approximately {required / 1024**3:.1f} GiB free RAM.")

    def check_cancel():
        if cancelled and cancelled():
            raise ExportCancelled("PNG export cancelled.")

    check_cancel()
    temporary = None
    try:
        with open_source(source.image_path) as image:
            if image.size != source.size:
                raise ValueError("Source image dimensions changed; reopen the pair.")
            descriptor, name = tempfile.mkstemp(
                prefix=".dale-", suffix=".tmp", dir=destination.parent
            )
            temporary = Path(name)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(b"\x89PNG\r\n\x1a\n")
                _chunk(stream, b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
                if placement:
                    for key, value in placement.metadata().items():
                        _chunk(
                            stream,
                            b"tEXt",
                            key.encode("latin-1") + b"\x00" + value.encode("latin-1"),
                        )
                compressor = zlib.compressobj(level=3)
                for top in range(0, height, STRIPE_ROWS):
                    check_cancel()
                    bottom = min(height, top + STRIPE_ROWS)
                    stripe = image.crop((0, top, width, bottom)).convert("RGBA")
                    stripe.putalpha(
                        render_alpha(stripe.size, source.size, operations, top=top, scale=(1, 1))
                    )
                    pixels = stripe.tobytes()
                    stride = width * 4
                    for row in range(bottom - top):
                        data = compressor.compress(
                            b"\x00" + pixels[row * stride : (row + 1) * stride]
                        )
                        if data:
                            _chunk(stream, b"IDAT", data)
                    if progress:
                        progress(min(99, bottom * 100 // height))
                _chunk(stream, b"IDAT", compressor.flush())
                _chunk(stream, b"IEND", b"")
                stream.flush()
                os.fsync(stream.fileno())
        check_cancel()
        os.replace(temporary, destination)
        temporary = None
        if progress:
            progress(100)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
