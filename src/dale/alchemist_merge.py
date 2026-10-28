"""Union contacting parts of one asset and refit each resulting outer perimeter."""

from collections import OrderedDict
from threading import RLock

import numpy as np
from shapely import Polygon, STRtree, union_all

from dale.alchemist_fit import FIT_FAILED, ContourComplexityError
from dale.alchemist_outline import _covers, outer_outline

_cache = OrderedDict()
_cache_lock = RLock()
_cache_vertices = 0


def clear_merge_cache():
    global _cache_vertices
    with _cache_lock:
        _cache.clear()
        _cache_vertices = 0


def merge_outlines(shapes, target, check_cancel=None):
    """Share a complete merged construction across equivalent placed assets."""
    global _cache_vertices
    if check_cancel:
        check_cancel()
    if len(shapes) < 2:
        return [((i,), shape) for i, shape in enumerate(shapes)]
    rings = [np.asarray(shape.exterior.coords[:-1]) for shape in shapes]
    origin = rings[0][0]
    vector = rings[0][len(rings[0]) // 2] - origin
    length_squared = float(vector @ vector)
    if length_squared <= 1e-24:
        return _merge_outlines(shapes, target, check_cancel)
    x, y = vector
    sign = 1 if shapes[0].exterior.is_ccw else -1
    basis = np.array(((x, -sign * y), (y, sign * x)))
    normalized = (np.concatenate(rings) - origin) @ basis / length_squared
    counts = tuple(map(len, rings))
    key = target, counts, tuple(map(tuple, np.round(normalized, 10)))
    tolerance = 2e-10 * max(1.0, float(np.abs(normalized).max()))
    with _cache_lock:
        matches = [
            (k, value)
            for k, value in reversed(_cache.items())
            if k[:2] == key[:2] and np.max(np.abs(value[0] - normalized)) <= tolerance
        ]
    for matched, (_, templates) in matches:
        if check_cancel:
            check_cancel()
        parts = [(members, Polygon(points @ basis.T + origin)) for members, points in templates]
        if all(
            len(shape.exterior.coords) - 1 <= target
            and all(_covers(shape, shapes[i]) for i in members)
            for members, shape in parts
        ):
            with _cache_lock:
                if matched in _cache:
                    _cache.move_to_end(matched)
            return parts
    result = _merge_outlines(shapes, target, check_cancel)
    if check_cancel:
        check_cancel()
    if len(result) < len(shapes) and len(normalized) <= 100000:
        templates = [
            (members, (np.asarray(shape.exterior.coords[:-1]) - origin) @ basis / length_squared)
            for members, shape in result
        ]
        with _cache_lock:
            if key not in _cache:
                _cache_vertices += len(normalized)
            _cache[key] = normalized, templates
            _cache.move_to_end(key)
            while len(_cache) > 64 or _cache_vertices > 100000:
                _, (removed, _) = _cache.popitem(last=False)
                _cache_vertices -= len(removed)
    return result


def _merge_outlines(shapes, target, check_cancel):
    """Return (source part indices, polygon), retaining genuinely disconnected parts.

    Each pass merges at least two components. Refitting may reach another part,
    so repeat until stable; no earlier slider value participates in construction.
    Point-only contacts have no single polygon perimeter and stay separate.
    """
    parts = [((i,), shape) for i, shape in enumerate(shapes)]
    while len(parts) > 1:
        tree = STRtree([shape for _, shape in parts])
        parents = list(range(len(parts)))

        def root(i, parents=parents):
            while parents[i] != i:
                parents[i] = parents[parents[i]]
                i = parents[i]
            return i

        for i, (_, shape) in enumerate(parts):
            if check_cancel:
                check_cancel()
            for j in map(int, tree.query(shape, predicate="intersects")):
                if j <= i or root(i) == root(j):
                    continue
                contact = shape.intersection(parts[j][1])
                if contact.area > 0 or contact.length > 0:
                    parents[root(j)] = root(i)
        clusters = {}
        for i in range(len(parts)):
            clusters.setdefault(root(i), []).append(i)
        if len(clusters) == len(parts):
            break
        following = []
        for cluster in clusters.values():
            if check_cancel:
                check_cancel()
            if len(cluster) == 1:
                following.append(parts[cluster[0]])
                continue
            merged = union_all([parts[i][1] for i in cluster])
            if merged.geom_type != "Polygon" or not merged.is_valid:
                raise ContourComplexityError(FIT_FAILED)
            exterior = Polygon(merged.exterior)
            points = tuple(exterior.exterior.coords[:-1])
            candidate, _ = outer_outline(points, exterior, target, check_cancel)
            result = Polygon(candidate)
            if len(candidate) > target or not _covers(result, exterior):
                raise ContourComplexityError(FIT_FAILED)
            members = tuple(sorted(j for i in cluster for j in parts[i][0]))
            following.append((members, result))
        parts = following
    return parts
