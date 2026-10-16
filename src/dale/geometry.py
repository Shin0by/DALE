"""Geometry in native image pixels; no scene mutation or Qt dependency."""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise

from shapely.geometry import GeometryCollection, LineString, MultiPoint
from shapely.ops import polygonize_full, snap, unary_union

from dale.scene import Point, Segment


def nearest_source(point: Point, segments: tuple[Segment, ...], tolerance: float) -> Point | None:
    best = None
    best_distance = tolerance
    for a, b in segments:
        dx, dy = b[0] - a[0], b[1] - a[1]
        length2 = dx * dx + dy * dy
        if not length2:
            continue
        t = max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length2))
        candidate = (a[0] + t * dx, a[1] + t * dy)
        distance = math.dist(candidate, point)
        if distance <= best_distance:
            best, best_distance = candidate, distance
    return best


@dataclass(frozen=True)
class RegionAnalysis:
    area: object
    faces: int
    unresolved: tuple[Segment, ...]


def analyze_regions(source: tuple[Segment, ...], closures: tuple = ()) -> RegionAnalysis:
    lines = [LineString(segment) for segment in source if segment[0] != segment[1]]
    anchors = [point for path in closures if path for point in (path[0], path[-1])]
    if anchors:
        # A projected point can miss an angled source line by floating-point epsilon.
        # Insert the exact editor anchors into nearby source segments before noding.
        reference = MultiPoint(anchors)
        lines = [snap(line, reference, 1e-7) for line in lines]
    for path in closures:
        lines.extend(LineString(segment) for segment in pairwise(path) if segment[0] != segment[1])
    if not lines:
        return RegionAnalysis(GeometryCollection(), 0, ())
    # Noding is essential when a closure ends on the middle of a source wall.
    noded = unary_union(lines)
    polygons, cuts, dangles, invalid = polygonize_full(noded)
    unresolved = []
    for collection in (cuts, dangles, invalid):
        for line in collection.geoms:
            coords = list(line.coords)
            unresolved.extend((tuple(a), tuple(b)) for a, b in pairwise(coords))
    return RegionAnalysis(unary_union(list(polygons.geoms)), len(polygons.geoms), tuple(unresolved))
