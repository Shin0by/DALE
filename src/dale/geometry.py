"""Geometry in native image pixels; no scene mutation or Qt dependency."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from itertools import pairwise

from shapely import STRtree
from shapely.geometry import GeometryCollection, LineString, MultiPoint, Point, box
from shapely.ops import polygonize_full, snap, unary_union

from dale.scene import Point as PixelPoint
from dale.scene import Segment


def nearest_source(
    point: PixelPoint, segments: tuple[Segment, ...], tolerance: float
) -> PixelPoint | None:
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
    joins: tuple[Segment, ...] = ()
    cells: tuple = ()


@dataclass(frozen=True)
class ContourComponent:
    line_ids: tuple[str, ...]
    edges: tuple
    area: object


@lru_cache(maxsize=8)
def contour_components(edges, line_ids, groups=()):
    """Group current lines only by shared stored vertices, without geometric noding."""
    parents = list(range(len(edges)))

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    vertices = {}
    for i, edge in enumerate(edges):
        for point in edge:
            key = point, groups[i] if groups else None
            if key in vertices:
                parents[root(i)] = root(vertices[key])
            else:
                vertices[key] = i
    groups = {}
    for i in range(len(edges)):
        groups.setdefault(root(i), []).append(i)
    result = []
    for indices in groups.values():
        lines = tuple(edges[i] for i in indices)
        result.append(
            ContourComponent(
                tuple(line_ids[i] for i in indices),
                lines,
                unary_union(structural_regions(lines)),
            )
        )
    return tuple(result)


def open_contour_count(segments: tuple[Segment, ...]) -> int:
    """Count connected unresolved groups, without guessing how missing edges should join them."""
    if not segments:
        return 0
    noded = unary_union([LineString(edge) for edge in segments])
    lines = list(noded.geoms) if hasattr(noded, "geoms") else [noded]
    parent = {}

    def find(point):
        parent.setdefault(point, point)
        while parent[point] != point:
            parent[point] = parent[parent[point]]
            point = parent[point]
        return point

    for line in lines:
        a, b = tuple(line.coords[0]), tuple(line.coords[-1])
        parent[find(a)] = find(b)
    return len({find(point) for point in parent})


def _gap_joins(noded, tolerance: float) -> tuple[Segment, ...]:
    lines = list(noded.geoms) if hasattr(noded, "geoms") else [noded]
    degree = Counter(tuple(p) for line in lines for p in (line.coords[0], line.coords[-1]))
    tips = sorted(point for point, count in degree.items() if count == 1)
    if not tips:
        return ()
    direct_edges = {
        tuple(sorted((tuple(line.coords[0]), tuple(line.coords[-1])))) for line in lines
    }
    tip_tree = STRtree([Point(point) for point in tips])
    proposals = set()
    for index, p in enumerate(tips):
        candidates = []
        bounds = box(p[0] - tolerance, p[1] - tolerance, p[0] + tolerance, p[1] + tolerance)
        for other in tip_tree.query(bounds):
            q = tips[int(other)]
            if index == other or tuple(sorted((p, q))) in direct_edges:
                continue
            distance = math.dist(p, q)
            if 0 < distance <= tolerance:
                candidates.append((distance, *sorted((p, q))))
        if candidates:
            proposals.add(min(candidates))
    joins, used = [], set()
    # Prefer endpoint pairs to projections so a small corner gap gets one bridge,
    # rather than two projections that create an artificial sliver polygon.
    for _, p, q in sorted(proposals):
        if p not in used and q not in used:
            joins.append((p, q))
            used.update((p, q))

    line_tree = STRtree(lines)
    projections = []
    for p in tips:
        if p in used:
            continue
        point = Point(p)
        candidates = []
        bounds = box(p[0] - tolerance, p[1] - tolerance, p[0] + tolerance, p[1] + tolerance)
        for index in line_tree.query(bounds):
            line = lines[int(index)]
            distance = line.distance(point)
            if distance <= 1e-7 or distance > tolerance:
                continue
            target = line.interpolate(line.project(point))
            q = (target.x, target.y)
            if q in used:
                continue
            candidates.append((distance, p, q))
        if candidates:
            projections.append(min(candidates))
    for _, p, q in sorted(projections):
        if p not in used and q not in used:
            joins.append((p, q))
            used.update((p, q))
    return tuple(joins)


def offset_region(area, offset: float):
    if not math.isfinite(offset):
        raise ValueError("Contour offset must be finite.")
    result = area.buffer(offset, join_style="mitre") if offset else area
    if result.is_empty:
        raise ValueError("No enclosed area remains. Reduce the inward offset or close a boundary.")
    return result


def invert_regions_in_box(polygons, selected, bounds):
    """Toggle intersected cells against one frozen selection, never cumulatively per move."""
    x0, y0, x1, y1 = bounds
    hits = (
        {i for i, polygon in enumerate(polygons) if polygon.intersects(box(x0, y0, x1, y1))}
        if x1 > x0 and y1 > y0
        else set()
    )
    return tuple(sorted(set(selected).symmetric_difference(hits)))


@lru_cache(maxsize=8)
def structural_regions(walls, closures=(), joins=()):
    """Closed editing figures, connected at authored vertices rather than crossings.

    Polygonization for masks/export remains global in analyze_regions. Here an
    unrelated crossing or nested contour must not cut a figure into extraction
    cells. A vertex lying on another edge is an actual T contact and does connect.
    Derive choices from current geometry without changing edges or provenance.
    """
    edges = tuple(
        edge
        for edge in (*walls, *(e for path in closures for e in pairwise(path)), *joins)
        if edge[0] != edge[1]
    )
    if not edges:
        return ()
    lines = [LineString(edge) for edge in edges]
    tree = STRtree(lines)
    parents = list(range(len(edges)))

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for index, edge in enumerate(edges):
        for endpoint in edge:
            point = Point(endpoint)
            for hit in tree.query(point.buffer(1e-7)):
                other = int(hit)
                if other != index and lines[other].distance(point) <= 1e-7:
                    parents[root(index)] = root(other)
    groups = {}
    for index, line in enumerate(lines):
        groups.setdefault(root(index), []).append(line)
    polygons = []
    for group in groups.values():
        cells, _, _, _ = polygonize_full(unary_union(group))
        polygons.extend(cells.geoms)
    return tuple(sorted(polygons, key=lambda p: (p.bounds[1], p.bounds[0], p.area, p.wkb)))


def analyze_regions(
    source: tuple[Segment, ...], closures: tuple = (), gap_tolerance: float = 0.0
) -> RegionAnalysis:
    if not math.isfinite(gap_tolerance) or gap_tolerance < 0:
        raise ValueError("Gap tolerance must be finite and nonnegative.")
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
    joins = _gap_joins(noded, gap_tolerance) if gap_tolerance else ()
    if joins:
        reference = MultiPoint([point for join in joins for point in join])
        reconciled = [snap(line, reference, 1e-7) for line in lines]
        noded = unary_union(reconciled + [LineString(join) for join in joins])
    polygons, cuts, dangles, invalid = polygonize_full(noded)
    unresolved = []
    for collection in (cuts, dangles, invalid):
        for line in collection.geoms:
            coords = list(line.coords)
            unresolved.extend((tuple(a), tuple(b)) for a, b in pairwise(coords))
    return RegionAnalysis(
        unary_union(list(polygons.geoms)),
        len(polygons.geoms),
        tuple(unresolved),
        joins,
        tuple(sorted(polygons.geoms, key=lambda p: (p.bounds[1], p.bounds[0], p.area))),
    )
