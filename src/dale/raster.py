"""Shared alpha renderer and bounded-memory, atomic RGBA PNG export."""

from __future__ import annotations

import math
import os
import struct
import tempfile
import zlib
from collections.abc import Callable, Sequence
from contextlib import nullcontext
from functools import lru_cache
from pathlib import Path

import psutil
from PIL import Image, ImageChops, ImageDraw

from dale.raster_brush import stroke_coverage
from dale.scene import SceneInput, open_source
from dale.session import ContourMask, Operation, RasterTransform, Stroke

PREVIEW_SIDE = 2048
STRIPE_ROWS = 128
ALPHA_FILTER_HALO = 2


class ExportCancelled(InterruptedError):
    pass


def load_preview(source: SceneInput) -> Image.Image:
    if source.image_path is None:
        return Image.new("RGBA", (1, 1))
    with open_source(source.image_path) as image:
        image.draft("RGB", (PREVIEW_SIDE, PREVIEW_SIDE))
        image.thumbnail((PREVIEW_SIDE, PREVIEW_SIDE), Image.Resampling.LANCZOS)
        return image.convert("RGBA")


def _polygon_mask(size, area, sx, sy, top, left=0):
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    polygons = [area] if area.geom_type == "Polygon" else list(area.geoms)
    for polygon in polygons:
        if polygon.is_empty or polygon.geom_type != "Polygon":
            continue
        if polygon.bounds[3] * sy < top or polygon.bounds[1] * sy > top + size[1]:
            continue

        def project(ring):
            return [(math.floor(x * sx) - left, math.floor(y * sy) - top) for x, y in ring.coords]

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
    left: int = 0,
) -> Image.Image:
    """Render a preview or export stripe; top is measured in output pixels."""
    sx, sy = scale or (size[0] / native_size[0], size[1] / native_size[1])
    alpha = Image.new("L", size, 255)
    for operation in operations:
        if isinstance(operation, ContourMask):
            region = _polygon_mask(size, operation.area, sx, sy, top, left)
            if operation.mode == "inside":
                region = ImageChops.invert(region)
            alpha = ImageChops.multiply(alpha, region)
        elif isinstance(operation, Stroke) and operation.points:
            ry = max(0.5, operation.radius * sy)
            points = [(x * sx - left, y * sy - top) for x, y in operation.points]
            if max(p[1] for p in points) + ry < 0 or min(p[1] for p in points) - ry > size[1]:
                continue
            mask = stroke_coverage(size, operation, sx, sy, left, top)
            if operation.opacity != 1:
                mask = mask.point([round(i * operation.opacity) for i in range(256)])
            alpha = (
                Image.composite(Image.new("L", size, 255), alpha, mask)
                if operation.restore
                else ImageChops.multiply(alpha, ImageChops.invert(mask))
            )
    return alpha


def render_preview(source: Image.Image, native_size, operations) -> Image.Image:
    if any(isinstance(op, RasterTransform) for op in operations):
        from dale.raster_transform import image_reader, render_layered

        return render_layered(
            image_reader(source, native_size),
            native_size,
            operations,
            (0, 0, *native_size),
            source.size,
        )
    result = source.convert("RGBA")
    alpha = ImageChops.multiply(
        result.getchannel("A"),
        render_export_alpha(
            source.size,
            native_size,
            operations,
            scale=(source.width / native_size[0], source.height / native_size[1]),
        ),
    )
    result.putalpha(alpha)
    result.paste((0, 0, 0, 0), mask=alpha.point([255] + [0] * 255))
    return result


def raster_operations(operations, artwork_offset=0):
    """Resolve live offsets from immutable mask boundaries for preview and PNG export."""
    if not math.isfinite(artwork_offset):
        raise ValueError("Contour offset must be finite.")
    return tuple(
        ContourMask(
            operation.boundary.buffer(artwork_offset, join_style="mitre")
            if artwork_offset
            else operation.boundary,
            operation.mode,
            operation.boundary,
        )
        if isinstance(operation, ContourMask) and operation.boundary is not None
        else getattr(operation, "raster", None) or operation
        for operation in operations
        if isinstance(operation, (ContourMask, Stroke, RasterTransform))
        or getattr(operation, "raster", None) is not None
    )


@lru_cache(maxsize=128)
def _alpha_tile(native_size, operations, top, left, scale):
    """Fixed output blocks make clipped polygon scan conversion deterministic."""
    width = height = 256
    halo = ALPHA_FILTER_HALO
    padded = (width + 2 * halo, height + 2 * halo)
    alpha = render_alpha(
        (padded[0] * 2, padded[1] * 2),
        native_size,
        operations,
        top=(top - halo) * 2,
        left=(left - halo) * 2,
        scale=(2 * scale[0], 2 * scale[1]),
    )
    alpha = alpha.resize(padded, Image.Resampling.BICUBIC)
    return alpha.crop((halo, halo, halo + width, halo + height))


def render_export_alpha(
    size, native_size, operations, top=0, left=0, *, scale=(1, 1), cancelled=None
):
    """Shared globally anchored 2x/bicubic alpha for previews, crops and stripes."""
    result = Image.new("L", size)
    for y in range(math.floor(top / 256) * 256, math.ceil((top + size[1]) / 256) * 256, 256):
        for x in range(math.floor(left / 256) * 256, math.ceil((left + size[0]) / 256) * 256, 256):
            if cancelled and cancelled():
                raise ExportCancelled("PNG export cancelled.")
            tile = _alpha_tile(tuple(native_size), tuple(operations), y, x, tuple(scale))
            result.paste(tile, (round(x - left), round(y - top)))
    if cancelled and cancelled():
        raise ExportCancelled("PNG export cancelled.")
    return result


def alpha_bounds(native_size, operations, crop, cancelled=None, source_path=None):
    """Find the exact nonzero-alpha box without decoding RGB or allocating a full mask."""
    with open_source(source_path) if source_path else nullcontext(None) as original:
        return _alpha_bounds_rows(native_size, operations, crop, cancelled, original)


def _alpha_bounds_rows(native_size, operations, crop, cancelled, original):
    left, top, right, bottom = crop
    result = None
    for row in range(top, bottom, STRIPE_ROWS):
        if cancelled and cancelled():
            raise ExportCancelled("PNG export cancelled.")
        transformed = any(isinstance(op, RasterTransform) for op in operations)
        if transformed:
            from dale.raster_transform import crop_reader, render_layered

            if original is None:
                raise ValueError("Raster transform bounds require the scene image.")
            alpha = render_layered(
                crop_reader(original, native_size),
                native_size,
                operations,
                (left, row, right, min(bottom, row + STRIPE_ROWS)),
                (right - left, min(STRIPE_ROWS, bottom - row)),
                cancelled=cancelled,
            ).getchannel("A")
        else:
            alpha = render_export_alpha(
                (right - left, min(STRIPE_ROWS, bottom - row)),
                native_size,
                operations,
                top=row,
                left=left,
                cancelled=cancelled,
            )
        if (
            not transformed
            and original is not None
            and ("A" in original.getbands() or "transparency" in original.info)
        ):
            source_alpha = (
                original.crop((left, row, right, row + alpha.height))
                .convert("RGBA")
                .getchannel("A")
            )
            alpha = ImageChops.multiply(alpha, source_alpha)
        found = alpha.getbbox()
        if found is not None:
            x0, y0, x1, y1 = found
            found = (left + x0, row + y0, left + x1, row + y1)
            result = (
                found
                if result is None
                else (
                    min(result[0], found[0]),
                    min(result[1], found[1]),
                    max(result[2], found[2]),
                    max(result[3], found[3]),
                )
            )
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
    crop: tuple[int, int, int, int] | None = None,
    metadata: dict[str, str] | None = None,
):
    destination = destination.resolve()
    sources = tuple(path for path in (source.image_path, source.json_path) if path)
    if source.image_path is None:
        raise ValueError("An image is required for PNG export.")
    if destination in (path.resolve() for path in sources):
        raise ValueError("Export cannot replace an imported source file.")
    if destination.suffix.lower() != ".png":
        raise ValueError("Export destination must have a .png extension.")
    if destination.exists() and any(os.path.samefile(destination, path) for path in sources):
        raise ValueError("Export cannot replace a hard-linked source file.")
    left, origin_y, right, bottom_y = crop or (0, 0, *source.size)
    width, height = right - left, bottom_y - origin_y
    if width <= 0 or height <= 0:
        raise ValueError("PNG crop dimensions must be positive.")
    required = source.size[0] * source.size[1] * 4 + 256 * 1024 * 1024
    if psutil.virtual_memory().available < required:
        raise MemoryError(f"Export needs approximately {required / 1024**3:.1f} GiB free RAM.")

    def check_cancel():
        if cancelled and cancelled():
            raise ExportCancelled("PNG export cancelled.")

    check_cancel()
    temporary = None
    visible = False
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
                text_metadata = metadata or {}
                if text_metadata:
                    for key, value in text_metadata.items():
                        _chunk(
                            stream,
                            b"tEXt",
                            key.encode("latin-1") + b"\x00" + value.encode("latin-1"),
                        )
                compressor = zlib.compressobj(level=3)
                for top in range(0, height, STRIPE_ROWS):
                    check_cancel()
                    bottom = min(height, top + STRIPE_ROWS)
                    stripe_box = (left, origin_y + top, right, origin_y + bottom)
                    if (
                        left >= 0
                        and stripe_box[1] >= 0
                        and right <= source.size[0]
                        and stripe_box[3] <= source.size[1]
                    ):
                        stripe = image.crop(stripe_box).convert("RGBA")
                    else:
                        stripe = Image.new("RGBA", (width, bottom - top), (0, 0, 0, 0))
                        visible_box = (
                            max(0, left),
                            max(0, stripe_box[1]),
                            min(source.size[0], right),
                            min(source.size[1], stripe_box[3]),
                        )
                        if visible_box[0] < visible_box[2] and visible_box[1] < visible_box[3]:
                            stripe.paste(
                                image.crop(visible_box).convert("RGBA"),
                                (visible_box[0] - left, visible_box[1] - stripe_box[1]),
                            )
                    if any(isinstance(op, RasterTransform) for op in operations):
                        from dale.raster_transform import crop_reader, render_layered

                        stripe = render_layered(
                            crop_reader(image, source.size),
                            source.size,
                            operations,
                            stripe_box,
                            stripe.size,
                            cancelled=cancelled,
                        )
                        alpha = stripe.getchannel("A")
                    else:
                        alpha = render_export_alpha(
                            stripe.size,
                            source.size,
                            operations,
                            top=origin_y + top,
                            left=left,
                            cancelled=cancelled,
                        )
                        alpha = ImageChops.multiply(alpha, stripe.getchannel("A"))
                    visible = visible or alpha.getextrema()[1] > 0
                    stripe.putalpha(alpha)
                    stripe.paste((0, 0, 0, 0), mask=alpha.point([255] + [0] * 255))
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
        return visible
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
