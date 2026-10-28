"""Bounded, transient texture alpha and UV-aware horizontal-band projection."""

from dataclasses import dataclass

import numpy as np
from PIL import Image
from shapely import Polygon, box, union_all

MAX_TEXTURE_PIXELS = 4096 * 4096
MAX_TEXTURE_BYTES = 32 * 1024 * 1024
MAX_ALPHA_BYTES = 16 * 1024 * 1024
ALPHA_SIZE = 1024
PROJECTION_SIZE = 768


def alpha_channel(image):
    """Keep one bounded channel; callers close the decoded source immediately."""
    if not 0 < image.width * image.height <= MAX_TEXTURE_PIXELS:
        raise ValueError("Model texture exceeds the supported size.")
    if "A" in image.getbands():
        channel = image.getchannel("A")
    elif "transparency" in image.info:
        with image.convert("RGBA") as rgba:
            channel = rgba.getchannel("A")
    else:
        channel = Image.new("L", image.size, 255)
    try:
        channel.thumbnail((ALPHA_SIZE, ALPHA_SIZE), Image.Resampling.BOX)
        return np.array(channel, dtype=np.uint8)
    finally:
        channel.close()


@dataclass(frozen=True)
class AlphaSurface:
    uv: np.ndarray
    alpha: np.ndarray
    cutoff: float = 0.5
    opacity: float = 1.0
    wrap: tuple = ("repeat", "repeat")

    def validate(self, count):
        if (
            self.uv.shape != (count, 2)
            or not np.isfinite(self.uv).all()
            or np.abs(self.uv).max(initial=0) > 1e6
            or self.alpha.ndim != 2
            or not self.alpha.size
            or self.alpha.size > ALPHA_SIZE**2
            or not 0 <= self.cutoff <= 1
            or not 0 <= self.opacity <= 1
            or any(w not in ("repeat", "clamp", "mirror") for w in self.wrap)
        ):
            raise ValueError("Invalid model texture coordinates or alpha material.")

    def visible(self, uv):
        coords = []
        for axis, size in enumerate((self.alpha.shape[1], self.alpha.shape[0])):
            value = uv[..., axis]
            if self.wrap[axis] == "repeat":
                value = value % 1
            elif self.wrap[axis] == "mirror":
                value = 1 - np.abs(value % 2 - 1)
            coords.append(np.clip((value * size).astype(np.int64), 0, size - 1))
        alpha = self.alpha[coords[1], coords[0]].astype(float) * (self.opacity / 255)
        return (alpha > 0) & (alpha >= self.cutoff)


def mask_shape(mask, origin, step, check_cancel=None):
    """Merge equal horizontal runs before union; never allocate a box per pixel."""
    rectangles, active = [], {}
    for y, row in enumerate(mask):
        if check_cancel and y % 32 == 0:
            check_cancel()
        changes = np.flatnonzero(np.diff(np.pad(row.astype(np.int8), (1, 1))))
        runs = set(zip(changes[::2].tolist(), changes[1::2].tolist(), strict=True))
        for run in active.keys() - runs:
            start = active[run]
            rectangles.append((run[0], start, run[1], y))
        active = {run: active.get(run, y) for run in runs}
    rectangles.extend((a, start, b, len(mask)) for (a, b), start in active.items())
    if not rectangles:
        return Polygon()
    bounds = np.asarray(rectangles, dtype=float) * step + np.tile(origin, 2)
    result = union_all(box(*bounds.T))
    if check_cancel:
        check_cancel()
    return result.simplify(step * 0.6, preserve_topology=True)


def project_alpha(meshes, floor, ceiling, check_cancel=None):
    """Sample UV alpha only inside triangles and the requested height slab.

    Opaque meshes/cut caps stay on the exact vector path. Alpha cards never
    produce solid caps that could fill their transparent portions back in.
    """
    vertices = np.concatenate([m[0] for m in meshes])
    origin = vertices[:, (0, 2)].min(axis=0)
    extent = np.ptp(vertices[:, (0, 2)], axis=0)
    step = float(extent.max()) / PROJECTION_SIZE
    if step <= 1e-12 or extent.min() <= 1e-12:
        return Polygon()
    width, height = np.maximum(1, np.ceil(extent / step).astype(int))
    mask = np.zeros((height, width), dtype=bool)
    work = 0
    for vertices, triangles, _color, surface in meshes:
        surface.validate(len(vertices))
        for index, face in enumerate(triangles):
            if check_cancel and index % 64 == 0:
                check_cancel()
            points = vertices[face]
            if (floor is not None and points[:, 1].max() < floor) or (
                ceiling is not None and points[:, 1].min() > ceiling
            ):
                continue
            p = (points[:, (0, 2)] - origin) / step
            a, b, c = p
            determinant = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            if abs(determinant) < 1e-10:
                continue
            x0, y0 = np.maximum(0, np.floor(p.min(axis=0)).astype(int))
            x1, y1 = np.minimum((width, height), np.ceil(p.max(axis=0)).astype(int))
            work += (x1 - x0) * (y1 - y0)
            if work > 128 * 1024 * 1024:
                raise ValueError("Textured model projection exceeds the supported work budget.")
            for row in range(y0, y1, 64):
                if check_cancel:
                    check_cancel()
                y, x = np.mgrid[row : min(row + 64, y1), x0:x1].astype(float) + 0.5
                u = ((x - a[0]) * (c[1] - a[1]) - (y - a[1]) * (c[0] - a[0])) / determinant
                v = ((b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])) / determinant
                inside = (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9)
                elevation = (
                    points[0, 1]
                    + u * (points[1, 1] - points[0, 1])
                    + v * (points[2, 1] - points[0, 1])
                )
                if floor is not None:
                    inside &= elevation >= floor - 1e-9
                if ceiling is not None:
                    inside &= elevation <= ceiling + 1e-9
                uv = surface.uv[face]
                samples = uv[0] + u[..., None] * (uv[1] - uv[0]) + v[..., None] * (uv[2] - uv[0])
                mask[row : row + len(y), x0:x1] |= inside & surface.visible(samples)
    return mask_shape(mask, origin, step, check_cancel)
