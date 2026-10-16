"""Point editing on immutable working geometry; source files are never modified."""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

from shapely.geometry import LineString
from shapely.geometry import Point as ShapePoint

from dale.scene import Point, Segment
from dale.session import GeometryEdit

EPSILON = 1e-7


def _same(a: Point, b: Point) -> bool:
    return math.dist(a, b) <= EPSILON


def project(point: Point, segment: Segment) -> tuple[Point, float]:
    a, b = segment
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = (
        max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length2))
        if length2
        else 0
    )
    return (a[0] + t * dx, a[1] + t * dy), t


def vertices(geometry: GeometryEdit) -> tuple[Point, ...]:
    return tuple(
        sorted(
            {point for edge in geometry.walls for point in edge}
            | {point for path in geometry.closures for point in path}
        )
    )


def hit_vertex(geometry: GeometryEdit, point: Point, tolerance: float) -> Point | None:
    hits = [(math.dist(point, vertex), vertex) for vertex in vertices(geometry)]
    return min(hits)[1] if hits and min(hits)[0] <= tolerance else None


@dataclass(frozen=True)
class EdgeHit:
    kind: Literal["wall", "closure"]
    path_index: int
    edge_index: int
    point: Point


def hit_edge(geometry: GeometryEdit, point: Point, tolerance: float) -> EdgeHit | None:
    best, distance = None, tolerance
    for index, segment in enumerate(geometry.walls):
        projected, _ = project(point, segment)
        value = math.dist(point, projected)
        if value <= distance:
            best, distance = EdgeHit("wall", index, 0, projected), value
    for path_index, path in enumerate(geometry.closures):
        for edge_index, segment in enumerate(pairwise(path)):
            projected, _ = project(point, segment)
            value = math.dist(point, projected)
            if value <= distance:
                best, distance = EdgeHit("closure", path_index, edge_index, projected), value
    return best


def snap_point(
    geometry: GeometryEdit, point: Point, tolerance: float, exclude=None
) -> Point | None:
    """Prefer vertices over projections; a dragged node cannot snap to its own edges."""
    if tolerance <= 0:
        return None
    candidates = [
        (math.dist(point, vertex), vertex)
        for vertex in vertices(geometry)
        if (exclude is None or not _same(vertex, exclude)) and math.dist(point, vertex) <= tolerance
    ]
    if candidates:
        return min(candidates)[1]
    edges = list(geometry.walls)
    edges.extend(edge for path in geometry.closures for edge in pairwise(path))
    if exclude is not None:
        edges = [edge for edge in edges if math.dist(project(exclude, edge)[0], exclude) > EPSILON]
    hit = hit_edge(GeometryEdit(tuple(edges)), point, tolerance)
    return hit.point if hit else None


def add_line(geometry: GeometryEdit, start: Point, end: Point) -> GeometryEdit:
    if _same(start, end):
        return geometry
    walls = _split_at(_split_at(geometry.walls, start), end)
    if tuple(sorted((start, end))) not in {tuple(sorted(edge)) for edge in walls}:
        walls.append((start, end))
    closures = tuple(
        tuple(_expanded_path(tuple(_expanded_path(path, start)), end)) for path in geometry.closures
    )
    return GeometryEdit(tuple(walls), closures)


def erase_geometry(geometry, start, end, radius, target):
    """Erase touched edges or vertices across a swept circular brush, including fast drags."""
    sweep = ShapePoint(start) if _same(start, end) else LineString((start, end))
    if target == "vertices":
        selected = [p for p in vertices(geometry) if sweep.distance(ShapePoint(p)) <= radius]
        for point in selected:
            if hit_vertex(geometry, point, EPSILON) is not None:
                geometry = delete_vertex(geometry, point)
        return geometry
    if target != "lines":
        raise ValueError("Unknown geometry eraser target.")

    def touched(edge):
        return sweep.distance(LineString(edge)) <= radius

    walls = tuple(edge for edge in geometry.walls if not touched(edge))
    closures = []
    for path in geometry.closures:
        run = []
        for a, b in pairwise(path):
            if touched((a, b)):
                if len(run) >= 2:
                    closures.append(tuple(run))
                run = []
            else:
                if not run:
                    run.append(a)
                run.append(b)
        if len(run) >= 2:
            closures.append(tuple(run))
    return GeometryEdit(walls, tuple(closures))


def insert_vertex(geometry: GeometryEdit, hit: EdgeHit) -> GeometryEdit:
    if hit.kind == "wall":
        walls = list(geometry.walls)
        a, b = walls[hit.path_index]
        if _same(a, hit.point) or _same(b, hit.point):
            return geometry
        walls[hit.path_index : hit.path_index + 1] = [(a, hit.point), (hit.point, b)]
        return GeometryEdit(tuple(walls), geometry.closures)
    closures = list(geometry.closures)
    points = list(closures[hit.path_index])
    a, b = points[hit.edge_index : hit.edge_index + 2]
    if _same(a, hit.point) or _same(b, hit.point):
        return geometry
    points.insert(hit.edge_index + 1, hit.point)
    closures[hit.path_index] = tuple(points)
    return GeometryEdit(geometry.walls, tuple(closures))


def _split_at(segments, point):
    result = []
    for a, b in segments:
        projected, t = project(point, (a, b))
        if not _same(a, point) and not _same(b, point) and 0 < t < 1 and _same(point, projected):
            result.extend(((a, point), (point, b)))
        else:
            result.append((a, b))
    return result


def _expanded_path(path, point):
    return [segment[0] for segment in _split_at(pairwise(path), point)] + [path[-1]]


def move_vertex(geometry: GeometryEdit, point: Point, destination: Point) -> GeometryEdit:
    if _same(point, destination):
        return geometry

    def replace(value):
        return destination if _same(value, point) else value

    walls = [(replace(a), replace(b)) for a, b in _split_at(geometry.walls, point)]
    closures = []
    for path in geometry.closures:
        points = [replace(value) for value in _expanded_path(path, point)]
        clean = [points[0]]
        clean.extend(p for a, p in pairwise(points) if not _same(a, p))
        if len(clean) >= 2:
            closures.append(tuple(clean))
    return GeometryEdit(tuple((a, b) for a, b in walls if not _same(a, b)), tuple(closures))


def delete_vertex(geometry: GeometryEdit, point: Point) -> GeometryEdit:
    walls, neighbors = [], set()
    for a, b in _split_at(geometry.walls, point):
        if _same(a, point):
            neighbors.add(b)
        elif _same(b, point):
            neighbors.add(a)
        else:
            walls.append((a, b))
    if len(neighbors) == 2:
        walls.append(tuple(sorted(neighbors)))
    closures = []
    for path in geometry.closures:
        points = tuple(value for value in _expanded_path(path, point) if not _same(value, point))
        if len(points) >= 2:
            closures.append(points)
    # Keep duplicate edges out of the working graph after a merge.
    unique = dict.fromkeys(tuple(sorted(edge)) for edge in walls if not _same(*edge))
    return GeometryEdit(tuple(unique), tuple(closures))
