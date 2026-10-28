"""Topology-checked outward simplification of an individual closed silhouette."""

from collections import OrderedDict
from math import ulp
from threading import RLock

import numpy as np
from shapely import Polygon

from dale.alchemist_fit import FIT_FAILED, ContourComplexityError, build_outline

_cache = OrderedDict()
_cache_vertices = 0
_cache_lock = RLock()


def clear_outline_cache():
    from dale.alchemist_merge import clear_merge_cache

    global _cache_vertices
    with _cache_lock:
        _cache.clear()
        _cache_vertices = 0
    clear_merge_cache()


def _covers(shape, polygon):
    x0, y0, x1, y1 = polygon.bounds
    tolerance = max(1.0, x1 - x0, y1 - y0) * 1e-10 + 8 * max(map(ulp, polygon.bounds))
    return shape.is_valid and shape.buffer(tolerance).covers(polygon)


def _checked_build(points, polygon, target, check_cancel):
    result, indices = build_outline(points, polygon, target, check_cancel)
    if not 4 <= len(result) <= target or len(indices) != len(result):
        raise ContourComplexityError(FIT_FAILED)
    return result, indices


def outer_outline(points, polygon, target, check_cancel=None):
    """Reuse identical silhouettes independently of position, rotation and uniform size."""
    global _cache_vertices
    if check_cancel:
        check_cancel()
    target = max(4, target)
    if len(points) <= target:
        return points, tuple(range(len(points)))
    array = np.asarray(points)
    origin = array[0]
    vector = array[len(points) // 2] - origin
    length_squared = float(vector @ vector)
    if length_squared <= 1e-24:
        return _checked_build(points, polygon, target, check_cancel)
    sign = 1 if polygon.exterior.is_ccw else -1
    x, y = vector
    basis = np.array(((x, -sign * y), (y, sign * x)))
    normalized = (array - origin) @ basis / length_squared
    # Rounding is restricted to the lookup key; cached coordinates come from the
    # exact first calculation, and each placed result is checked against its mask.
    key = target, tuple(map(tuple, np.round(normalized, 10)))
    with _cache_lock:
        cached = _cache.get(key)
        candidates = [(key, cached)] if cached is not None else []
        # Rounded hashes alone split identical placed masks at rounding-cell
        # boundaries. Compare retained normalized coordinates within numeric
        # noise as well, then validate containment in actual scene coordinates.
        tolerance = 2e-10 * max(1.0, float(np.abs(normalized).max()))
        candidates.extend(
            (other_key, value)
            for other_key, value in reversed(_cache.items())
            if other_key != key
            and other_key[0] == target
            and len(other_key[1]) == len(points)
            and np.max(np.abs(value[2] - normalized)) <= tolerance
        )
    for matched_key, cached in candidates:
        template, indices, _ = cached
        if template is not None and 4 <= len(template) <= target:
            placed = np.asarray(template) @ basis.T + origin
            result = tuple(map(tuple, placed))
            if _covers(Polygon(result), polygon):
                with _cache_lock:
                    if matched_key in _cache:
                        _cache.move_to_end(matched_key)
                return result, indices
    result, indices = _checked_build(points, polygon, target, check_cancel)
    if check_cancel:
        check_cancel()
    template = tuple(map(tuple, (np.asarray(result) - origin) @ basis / length_squared))
    if len(points) <= 200000:
        with _cache_lock:
            if key not in _cache:
                _cache_vertices += len(points)
            _cache[key] = template, indices, normalized.copy()
            _cache.move_to_end(key)
            while len(_cache) > 128 or _cache_vertices > 200000:
                old_key, _ = _cache.popitem(last=False)
                _cache_vertices -= len(old_key[1])
    return result, indices
