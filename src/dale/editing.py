"""Point editing on immutable working geometry; source files are never modified."""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

from shapely.geometry import LineString
from shapely.geometry import Point as ShapePoint

from dale.provenance import LineageBuilder, LineRecord, edge_key, geometry_edges
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
    geometry = node_geometry(geometry, (start, end))
    builder = LineageBuilder(geometry)
    walls = list(geometry.walls)
    overrides = {}
    if tuple(sorted((start, end))) not in {tuple(sorted(edge)) for edge in walls}:
        walls.append((start, end))
        overrides[edge_key((start, end))] = LineRecord.child(
            builder.contacts((start, end)), (start, end), manual=True
        )
    closures = tuple(
        tuple(_expanded_path(tuple(_expanded_path(path, start)), end)) for path in geometry.closures
    )
    return builder.build(walls, closures, overrides)


def circle_points(center: Point, radius: float, cell_pixels: float = 100) -> tuple[Point, ...]:
    """Closed editable polygon, with density based on diameter in map cells."""
    if (
        type(radius) not in (int, float)
        or not math.isfinite(radius)
        or radius <= 0
        or type(cell_pixels) not in (int, float)
        or not math.isfinite(cell_pixels)
        or cell_pixels <= 0
        or len(center) != 2
        or any(type(v) not in (int, float) or not math.isfinite(v) for v in center)
        or any(abs(v) + radius > 1e9 for v in center)
    ):
        raise ValueError("Circle center and radius must be finite and within coordinate limits.")
    diameter = min(5112, 2 * radius / cell_pixels)  # Cap before ceil, including overflow to inf.
    count = (
        4
        if diameter <= 0.5
        else 6
        if diameter <= 1
        else 8
        if diameter <= 2
        else min(4096, 8 + 2 * math.ceil((diameter - 2) / 2.5))
    )
    cx, cy = center
    points = [
        (cx + radius * math.cos(math.tau * i / count), cy + radius * math.sin(math.tau * i / count))
        for i in range(count)
    ]
    # Exact opposing vertices avoid floating-point gaps at ordinary contacts.
    points[0], points[count // 2] = (cx + radius, cy), (cx - radius, cy)
    if count % 4 == 0:
        points[count // 4], points[3 * count // 4] = (cx, cy + radius), (cx, cy - radius)
    return (*points, points[0])


def add_circle(
    geometry: GeometryEdit, center: Point, radius: float, cell_pixels: float = 100
) -> GeometryEdit:
    points = circle_points(center, radius, cell_pixels)
    geometry = node_geometry(geometry, points[:-1])
    builder = LineageBuilder(geometry)
    walls = list(geometry.walls)
    existing = {edge_key(edge) for edge in geometry_edges(geometry.walls, geometry.closures)}
    overrides = {}
    for edge in pairwise(points):
        key = edge_key(edge)
        if key not in existing:
            walls.append(edge)
            overrides[key] = LineRecord.child(builder.contacts(edge), edge, manual=True)
            existing.add(key)
    return builder.build(walls, geometry.closures, overrides)


def geometry_targets(geometry, start, end, radius, target):
    """Use the same circle/capsule hit test for hover previews and deletion."""
    sweep = ShapePoint(start) if _same(start, end) else LineString((start, end))
    if target == "vertices":
        return tuple(p for p in vertices(geometry) if sweep.distance(ShapePoint(p)) <= radius)
    if target != "lines":
        raise ValueError("Unknown geometry eraser target.")
    edges = (*geometry.walls, *(edge for path in geometry.closures for edge in pairwise(path)))
    return tuple(edge for edge in edges if sweep.distance(LineString(edge)) <= radius)


def erase_geometry(geometry, start, end, radius, target):
    """Erase touched edges or vertices across a swept circular brush, including fast drags."""
    selected = geometry_targets(geometry, start, end, radius, target)
    if target == "vertices":
        for point in selected:
            if hit_vertex(geometry, point, EPSILON) is not None:
                geometry = delete_vertex(geometry, point)
        return geometry
    selected = set(selected)

    def touched(edge):
        return edge in selected

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
    return LineageBuilder(geometry).build(walls, closures)


def insert_vertex(geometry: GeometryEdit, hit: EdgeHit) -> GeometryEdit:
    if hit.kind == "wall":
        walls = list(geometry.walls)
        a, b = walls[hit.path_index]
        if _same(a, hit.point) or _same(b, hit.point):
            return geometry
        walls[hit.path_index : hit.path_index + 1] = [(a, hit.point), (hit.point, b)]
        return LineageBuilder(geometry).build(walls, geometry.closures)
    closures = list(geometry.closures)
    points = list(closures[hit.path_index])
    a, b = points[hit.edge_index : hit.edge_index + 2]
    if _same(a, hit.point) or _same(b, hit.point):
        return geometry
    points.insert(hit.edge_index + 1, hit.point)
    closures[hit.path_index] = tuple(points)
    return LineageBuilder(geometry).build(geometry.walls, closures)


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

    geometry = node_geometry(geometry, (point,))

    walls = [(replace(a), replace(b)) for a, b in _split_at(geometry.walls, point)]
    closures = []
    for path in geometry.closures:
        points = [replace(value) for value in _expanded_path(path, point)]
        clean = [points[0]]
        clean.extend(p for a, p in pairwise(points) if not _same(a, p))
        if len(clean) >= 2:
            closures.append(tuple(clean))
    moved = tuple(
        (replace(a), replace(b)) for a, b in geometry_edges(geometry.walls, geometry.closures)
    )
    builder = LineageBuilder(geometry)
    contacts = tuple(
        record
        for edge, record in zip(builder.edges, geometry.lineage, strict=True)
        if not any(_same(p, point) for p in edge)
        and _same(project(destination, edge)[0], destination)
    )
    overrides = {
        edge_key(edge): (
            LineRecord.child((record, *contacts), edge)
            if contacts
            and any(_same(p, destination) for p in edge)
            and edge_key(edge) != edge_key(old)
            else record
        )
        for old, edge, record in zip(builder.edges, moved, geometry.lineage, strict=True)
        if not _same(*edge)
    }
    result = builder.build(
        tuple((a, b) for a, b in walls if not _same(a, b)), tuple(closures), overrides
    )
    return node_geometry(result, (destination,))


def extend_lines(geometry: GeometryEdit, extensions: tuple[Segment, ...]) -> GeometryEdit:
    """Move free ends simultaneously, then node their destinations into target lines."""
    destinations = dict(extensions)
    walls = tuple((destinations.get(a, a), destinations.get(b, b)) for a, b in geometry.walls)
    closures = tuple(
        tuple(destinations.get(point, point) for point in path) for path in geometry.closures
    )
    return node_geometry(
        GeometryEdit(walls, closures, geometry.lineage, geometry.ancestry), destinations.values()
    )


def node_geometry(geometry: GeometryEdit, points) -> GeometryEdit:
    """Materialize shared connections without changing the drawn line shapes."""
    walls, closures = geometry.walls, geometry.closures
    for destination in sorted(set(points)):
        walls = tuple(_split_at(walls, destination))
        closures = tuple(tuple(_expanded_path(path, destination)) for path in closures)
    return LineageBuilder(geometry).build(walls, closures)


def delete_vertex(geometry: GeometryEdit, point: Point) -> GeometryEdit:
    geometry = node_geometry(geometry, (point,))
    builder = LineageBuilder(geometry)
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
    overrides = {}
    incident = tuple(
        record
        for edge, record in zip(
            geometry_edges(geometry.walls, geometry.closures), geometry.lineage, strict=True
        )
        if any(_same(p, point) for p in edge)
    )
    for edge in geometry_edges(tuple(unique), closures):
        if edge_key(edge) not in builder.exact:
            parents = tuple(
                record
                for record in incident
                if any(record in builder.exact.get(edge_key((p, point)), ()) for p in edge)
            )
            overrides[edge_key(edge)] = LineRecord.child(parents, edge)
    return builder.build(tuple(unique), closures, overrides)
