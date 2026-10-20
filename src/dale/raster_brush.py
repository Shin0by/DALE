"""Bounded-memory raster brush coverage with a solid core and feathered border."""

import math
from itertools import pairwise

import numpy as np
from PIL import Image, ImageChops, ImageDraw

RASTER_BRUSHES = ("Erase", "Erase square", "Restore", "Restore square")


def brush_settings(value=None):
    value = {} if value is None else value
    if not isinstance(value, dict) or set(value) - set(RASTER_BRUSHES):
        raise ValueError("Invalid raster brush settings.")
    result = {}
    for mode in RASTER_BRUSHES:
        profile = value.get(mode, {"feather": 0, "opacity": 100})
        if (
            not isinstance(profile, dict)
            or set(profile) != {"feather", "opacity"}
            or any(type(v) is not int or not 0 <= v <= 100 for v in profile.values())
        ):
            raise ValueError("Invalid raster brush feather or pressure.")
        result[mode] = dict(profile)
    return result


def _hard_circle(size, points, rx, ry, sx, sy):
    mask = Image.new("L", size)
    draw = ImageDraw.Draw(mask)
    for a, b in pairwise(points):
        dx, dy = (b[0] - a[0]) / sx, (b[1] - a[1]) / sy
        length = math.hypot(dx, dy)
        if length:
            nx, ny = -dy / length * rx, dx / length * ry
            corners = (
                (a[0] + nx, a[1] + ny),
                (b[0] + nx, b[1] + ny),
                (b[0] - nx, b[1] - ny),
                (a[0] - nx, a[1] - ny),
            )
            draw.polygon([(math.floor(x), math.floor(y)) for x, y in corners], fill=255)
    for x, y in points:
        draw.ellipse(tuple(math.floor(v) for v in (x - rx, y - ry, x + rx, y + ry)), fill=255)
    return mask


def stroke_coverage(size, operation, sx, sy, left=0, top=0):
    points = tuple((x * sx - left, y * sy - top) for x, y in operation.points)
    rx, ry = max(0.5, operation.radius * sx), max(0.5, operation.radius * sy)
    if operation.shape == "circle" and operation.feather == 0:
        return _hard_circle(size, points, rx, ry, sx, sy)
    mask = Image.new("L", size)
    radius = operation.radius
    inner = radius * (1 - operation.feather)
    segments = tuple(pairwise(operation.points)) or ((operation.points[0], operation.points[0]),)
    for a, b in segments:
        x0 = max(0, math.floor(min(a[0], b[0]) * sx - left - rx - 1))
        y0 = max(0, math.floor(min(a[1], b[1]) * sy - top - ry - 1))
        x1 = min(size[0], math.ceil(max(a[0], b[0]) * sx - left + rx + 1))
        y1 = min(size[1], math.ceil(max(a[1], b[1]) * sy - top + ry + 1))
        dx, dy = b[0] - a[0], b[1] - a[1]
        for y in range(y0, y1, 128):
            height = min(128, y1 - y)
            qy = (np.arange(y, y + height, dtype=float)[:, None] + top + 0.5) / sy - a[1]
            for x in range(x0, x1, 256):
                width = min(256, x1 - x)
                qx = (np.arange(x, x + width, dtype=float)[None, :] + left + 0.5) / sx - a[0]
                if operation.shape == "circle":
                    length2 = dx * dx + dy * dy
                    t = np.clip((qx * dx + qy * dy) / length2, 0, 1) if length2 else 0
                    distance = np.hypot(qx - t * dx, qy - t * dy)
                else:
                    distance = np.minimum(
                        np.maximum(abs(qx), abs(qy)), np.maximum(abs(qx - dx), abs(qy - dy))
                    )
                    for denominator, numerator in ((dx - dy, qx - qy), (dx + dy, qx + qy)):
                        if denominator:
                            t = np.clip(numerator / denominator, 0, 1)
                            distance = np.minimum(
                                distance, np.maximum(abs(qx - t * dx), abs(qy - t * dy))
                            )
                if operation.feather:
                    coverage = np.clip((radius - distance) / (radius - inner), 0, 1)
                    coverage = coverage * coverage * (3 - 2 * coverage)
                else:
                    coverage = distance <= radius
                patch = Image.fromarray(np.rint(coverage * 255).astype(np.uint8))
                bounds = (x, y, x + width, y + height)
                mask.paste(ImageChops.lighter(mask.crop(bounds), patch), (x, y))
    return mask
