"""Validate local source pairs and make scene-to-image coordinates explicit."""

from __future__ import annotations

import hashlib
import json
import math
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from dale.provenance import SourceWall

MAX_SIDE = 16_384
COMPATIBILITY_SIDE = 8_192
_image_open_lock = threading.Lock()
Point = tuple[float, float]
Segment = tuple[Point, Point]


def number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number.")
    if not math.isfinite(value) or abs(value) > 1_000_000_000:
        raise ValueError(f"{field} is outside the supported coordinate range.")
    return float(value)


@contextmanager
def open_source(path: Path):
    # Pillow's default threshold is below the explicitly supported 16k square.
    with _image_open_lock:
        previous = Image.MAX_IMAGE_PIXELS
        try:
            Image.MAX_IMAGE_PIXELS = MAX_SIDE * MAX_SIDE
            image = Image.open(path)
        finally:
            Image.MAX_IMAGE_PIXELS = previous
    try:
        if image.format not in {"JPEG", "PNG", "WEBP", "BMP", "TIFF"}:
            raise ValueError("Unsupported scene image format.")
        if getattr(image, "n_frames", 1) != 1:
            raise ValueError("Animated or multipage scene images are not supported.")
        if max(image.size) > MAX_SIDE:
            raise ValueError(f"Image exceeds the {MAX_SIDE:,}-pixel per-side limit.")
        if image.getexif().get(274, 1) != 1:
            raise ValueError("EXIF-rotated scene images require a coordinate-aware import adapter.")
        yield image
    finally:
        image.close()


@dataclass(frozen=True)
class SceneInput:
    image_path: Path | None
    json_path: Path | None
    size: tuple[int, int]
    raw: dict
    walls: tuple[Segment, ...]
    scene_size: tuple[float, float]
    background_offset: Point
    warnings: tuple[str, ...]
    wall_sources: tuple[SourceWall, ...] = ()
    json_bytes: bytes | None = None
    image_name: str | None = None
    json_name: str | None = None

    @property
    def name(self):
        return (
            self.json_name
            or self.image_name
            or (
                (self.json_path or self.image_path).name
                if self.json_path or self.image_path
                else "Contours.json"
            )
        )

    @property
    def cell_pixels(self) -> float:
        """Grid size in source pixels; absent/invalid grid uses 100 source pixels."""
        grid = self.raw.get("grid")
        value = grid.get("size") if isinstance(grid, dict) else grid
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            return 100.0
        pixels = value * min(self.size[i] / self.scene_size[i] for i in (0, 1))
        return pixels if math.isfinite(pixels) and pixels > 0 else 100.0

    def image_walls(self, origin: Point = (0.0, 0.0)) -> tuple[Segment, ...]:
        sx = self.size[0] / self.scene_size[0]
        sy = self.size[1] / self.scene_size[1]
        dx = number(origin[0], "Origin X") + self.background_offset[0]
        dy = number(origin[1], "Origin Y") + self.background_offset[1]
        return tuple(
            (((a[0] - dx) * sx, (a[1] - dy) * sy), ((b[0] - dx) * sx, (b[1] - dy) * sy))
            for a, b in self.walls
        )


def load_pair(image_path: Path | None, json_path: Path | None = None) -> SceneInput:
    image_path = image_path.resolve() if image_path else None
    json_path = json_path.resolve() if json_path else None
    if image_path is None and json_path is None:
        raise ValueError("Open a scene image or scene JSON.")
    size = (1, 1)
    if image_path:
        with open_source(image_path) as image:
            size = image.size
    if json_path is None:
        return SceneInput(
            image_path, None, size, {}, (), size, (0, 0), (), image_name=image_path.name
        )
    if json_path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("JSON exceeds the 32 MiB prototype input limit.")
    source_bytes = json_path.read_bytes()
    return scene_from_json(
        source_bytes, size if image_path else None, image_path=image_path, json_path=json_path
    )


def scene_from_json(source_bytes, image_size=None, *, image_path=None, json_path=None):
    """Parse frozen JSON with an optional image header size, without decoding raster pixels."""
    if len(source_bytes) > 32 * 1024 * 1024:
        raise ValueError("JSON exceeds the 32 MiB prototype input limit.")
    size = image_size or (1, 1)
    digest = hashlib.sha256(source_bytes).hexdigest()
    raw = json.loads(source_bytes.decode("utf-8-sig"))
    if not isinstance(raw, dict) or not isinstance(raw.get("walls"), list):
        raise ValueError("Scene JSON must contain a `walls` array.")
    if len(raw.get("walls", [])) > 100_000:
        raise ValueError("More than 100,000 source contour segments are not supported yet.")
    if image_size is None and ("width" not in raw or "height" not in raw):
        raise ValueError("JSON-only editing requires explicit scene width and height.")
    width = number(raw.get("width", size[0]), "Scene width")
    height = number(raw.get("height", size[1]), "Scene height")
    if width <= 0 or height <= 0:
        raise ValueError("Scene dimensions must be positive.")
    if image_size is None:
        size = (math.ceil(width), math.ceil(height))
    background = raw.get("background") or {}
    if not isinstance(background, dict):
        raise ValueError("Scene background must be an object.")
    for field, identity in (("rotation", 0), ("scaleX", 1), ("scaleY", 1)):
        if number(background.get(field, identity), f"Background {field}") != identity:
            raise ValueError(f"Background {field} requires an unsupported transform adapter.")
    offset = (
        number(background.get("offsetX", 0), "Background offsetX"),
        number(background.get("offsetY", 0), "Background offsetY"),
    )
    walls = []
    references = []
    for i, wall in enumerate(raw.get("walls", [])):
        c = wall.get("c") if isinstance(wall, dict) else None
        if not isinstance(c, list) or len(c) != 4:
            raise ValueError(f"Contour segment {i}: expected c: [x1, y1, x2, y2].")
        x1, y1, x2, y2 = [number(v, f"Contour segment {i} coordinate") for v in c]
        if (x1, y1) != (x2, y2):
            walls.append(((x1, y1), (x2, y2)))
            wall_id = wall.get("_id", wall.get("id"))
            if wall_id is not None and len(str(wall_id)) > 256:
                raise ValueError(f"Contour segment {i}: identifier exceeds 256 characters.")
            references.append(SourceWall(digest, i, str(wall_id) if wall_id is not None else None))
    warnings = []
    if image_path and max(size) > COMPATIBILITY_SIDE:
        warnings.append("Above 8,192 pixels: check the texture limit of every Foundry client.")
    if raw.get("padding", 0):
        warnings.append("Scene padding is nonzero. Verify contour alignment before editing.")
    if not walls:
        warnings.append(
            "No contour segments found in the scene JSON. Draw contours or edit raster pixels."
        )
    if "width" not in raw or "height" not in raw:
        warnings.append("Scene dimensions absent: using scene image dimensions; verify alignment.")
    if "levels" in raw:
        warnings.append(
            "Scene levels detected. Only the scene-level contour collection is imported."
        )
    return SceneInput(
        image_path,
        json_path,
        size,
        raw,
        tuple(walls),
        (width, height),
        offset,
        tuple(warnings),
        tuple(references),
        source_bytes,
        image_path.name if image_path else None,
        json_path.name if json_path else None,
    )
