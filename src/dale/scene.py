"""Validate local source pairs and make scene-to-image coordinates explicit."""

from __future__ import annotations

import json
import math
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

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
        if image.format != "JPEG":
            raise ValueError("The source image must be a JPG/JPEG file.")
        if max(image.size) > MAX_SIDE:
            raise ValueError(f"Image exceeds the {MAX_SIDE:,}-pixel per-side limit.")
        if image.getexif().get(274, 1) != 1:
            raise ValueError("EXIF-rotated JPGs need a coordinate-aware import adapter.")
        yield image
    finally:
        image.close()


@dataclass(frozen=True)
class SceneInput:
    image_path: Path
    json_path: Path
    size: tuple[int, int]
    raw: dict
    walls: tuple[Segment, ...]
    scene_size: tuple[float, float]
    background_offset: Point
    warnings: tuple[str, ...]

    def image_walls(self, origin: Point = (0.0, 0.0)) -> tuple[Segment, ...]:
        sx = self.size[0] / self.scene_size[0]
        sy = self.size[1] / self.scene_size[1]
        dx = number(origin[0], "Origin X") + self.background_offset[0]
        dy = number(origin[1], "Origin Y") + self.background_offset[1]
        return tuple(
            (((a[0] - dx) * sx, (a[1] - dy) * sy), ((b[0] - dx) * sx, (b[1] - dy) * sy))
            for a, b in self.walls
        )


def load_pair(image_path: Path, json_path: Path) -> SceneInput:
    image_path, json_path = image_path.resolve(), json_path.resolve()
    with open_source(image_path) as image:
        size = image.size
    if json_path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("JSON exceeds the 32 MiB prototype input limit.")
    raw = json.loads(json_path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict) or not isinstance(raw.get("walls"), list):
        raise ValueError("Expected a Foundry scene object with a walls array.")
    if len(raw.get("walls", [])) > 100_000:
        raise ValueError("More than 100,000 source walls are not supported yet.")
    width = number(raw.get("width", size[0]), "Scene width")
    height = number(raw.get("height", size[1]), "Scene height")
    if width <= 0 or height <= 0:
        raise ValueError("Scene dimensions must be positive.")
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
    for i, wall in enumerate(raw.get("walls", [])):
        c = wall.get("c") if isinstance(wall, dict) else None
        if not isinstance(c, list) or len(c) != 4:
            raise ValueError(f"Wall {i}: expected c: [x1, y1, x2, y2].")
        x1, y1, x2, y2 = [number(v, f"Wall {i} coordinate") for v in c]
        if (x1, y1) != (x2, y2):
            walls.append(((x1, y1), (x2, y2)))
    warnings = []
    if max(size) > COMPATIBILITY_SIDE:
        warnings.append("Above 8,192 pixels: check the texture limit of every Foundry client.")
    if raw.get("padding", 0):
        warnings.append("Nonzero scene padding: review wall alignment and set Scene origin X/Y.")
    if not walls:
        warnings.append(
            "No usable walls found. Brush editing is available; contour masking is not."
        )
    if "width" not in raw or "height" not in raw:
        warnings.append("Scene dimensions absent: using JPG dimensions; verify alignment.")
    if "levels" in raw:
        warnings.append("Scene levels detected. This prototype uses only top-level walls.")
    return SceneInput(
        image_path, json_path, size, raw, tuple(walls), (width, height), offset, tuple(warnings)
    )
