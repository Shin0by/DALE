"""Point editing on immutable working geometry; source files are never modified."""

from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

from shapely import STRtree
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


def alignment_points(
    geometry: GeometryEdit, vertex: Point, intervals=None, *, neighbours_only=False
):
    """Freeze guide anchors in this connected contour, respecting optional height intervals."""
    edges = geometry_edges(geometry.walls, geometry.closures)
    shapes = [LineString(edge) for edge in edges]
    tree = STRtree(shapes)
    seed = ShapePoint(vertex)
    pending = [
        int(i) for i in tree.query(seed.buffer(EPSILON)) if shapes[int(i)].distance(seed) <= EPSILON
    ]
    visited = set(pending)
    neighbours = {p for i in pending for p in edges[i] if not _same(p, vertex)}
    if neighbours_only:
        return tuple(sorted(neighbours, key=lambda p: (math.dist(p, vertex), p)))
    while pending:
        index = pending.pop()
        for other in tree.query(shapes[index].buffer(EPSILON)):
            other = int(other)
            if other in visited or shapes[index].distance(shapes[other]) > EPSILON:
                continue
            if intervals is not None and (
                intervals[index] is None
                or intervals[other] is None
                or max(intervals[index][0], intervals[other][0])
                >= min(intervals[index][1], intervals[other][1])
            ):
                continue
            visited.add(other)
            pending.append(other)
    return tuple(
        sorted(
            {p for i in visited for p in edges[i] if not _same(p, vertex)},
            key=lambda p: (p not in neighbours, math.dist(p, vertex), p),
        )
    )


def align_orthogonal_point(point: Point, anchors, tolerance: float):
    """Snap x/y independently to fixed vertices in the connected contour."""
    guides = []
    destination = list(point)
    for axis in (0, 1):
        candidates = [
            (abs(point[axis] - anchor[axis]), rank, anchor)
            for rank, anchor in enumerate(anchors)
            if abs(point[axis] - anchor[axis]) <= tolerance
        ]
        if candidates:
            anchor = min(candidates)[2]
            destination[axis] = anchor[axis]
            guides.append((axis, anchor))
    return tuple(destination), tuple(guides)


def right_angle_point(point, preferred, vertex, neighbours, geometry, tolerance):
    """Snap a joint to 90 degrees, independent of map axes; return its two guide legs."""
    if len(neighbours) >= 2:
        a, b = neighbours[:2]
        center = tuple((a[i] + b[i]) / 2 for i in (0, 1))
        radius = math.dist(a, b) / 2
        direction = tuple(preferred[i] - center[i] for i in (0, 1))
        length = math.hypot(*direction)
        if length <= EPSILON:
            return preferred, None
        target = tuple(center[i] + direction[i] * radius / length for i in (0, 1))
        if (
            math.dist(point, target) <= tolerance
            and min(math.dist(target, a), math.dist(target, b)) > EPSILON
        ):
            return target, (a, target, b)
    elif neighbours:
        # A terminal handle may square its incident segment with the stationary
        # continuation at its neighbour, rather than with a global map axis.
        joint = neighbours[0]
        candidates = []
        for edge in geometry_edges(geometry.walls, geometry.closures):
            if joint not in edge or vertex in edge:
                continue
            other = edge[1] if edge[0] == joint else edge[0]
            length = math.dist(other, joint)
            if length <= EPSILON:
                continue
            normal = (-(other[1] - joint[1]) / length, (other[0] - joint[0]) / length)
            distance = sum((preferred[i] - joint[i]) * normal[i] for i in (0, 1))
            target = tuple(joint[i] + distance * normal[i] for i in (0, 1))
            delta = math.dist(point, target)
            if delta <= tolerance and math.dist(target, joint) > EPSILON:
                candidates.append((delta, target, other))
        if candidates:
            _, target, other = min(candidates)
            return target, (other, joint, target)
    return preferred, None


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


def rectangle_points(start: Point, end: Point) -> tuple[Point, ...]:
    """A closed axis-aligned rectangle from opposite corners, without snapping."""
    if any(not math.isfinite(v) or abs(v) > 1e9 for p in (start, end) for v in p):
        raise ValueError("Rectangle corners must be finite and within coordinate limits.")
    return (start, (end[0], start[1]), end, (start[0], end[1]), start)


def add_rectangle(geometry: GeometryEdit, start: Point, end: Point) -> GeometryEdit:
    if start[0] == end[0] or start[1] == end[1]:
        return geometry
    for a, b in pairwise(rectangle_points(start, end)):
        geometry = add_line(geometry, a, b)
    return geometry


class LineEraser:
    """Lazily partition hit source edges at exact intersections, without global noding."""

    def __init__(self, geometry):
        self.geometry = geometry
        self.edges = geometry_edges(geometry.walls, geometry.closures)
        self.shapes = tuple(LineString(edge) for edge in self.edges)
        self.tree = STRtree(self.shapes)
        self.parts = OrderedDict()

    def _parts(self, index):
        if index in self.parts:
            self.parts.move_to_end(index)
            return self.parts[index]
        edge, shape = self.edges[index], self.shapes[index]
        cuts = [(0.0, edge[0]), (1.0, edge[1])]

        def add_point(point):
            point = tuple(point)
            if not any(_same(point, end) for end in edge):
                _, position = project(point, edge)
                cuts.append((position, point))

        def add_intersection(intersection):
            if intersection.is_empty:
                return
            if intersection.geom_type == "Point":
                add_point(intersection.coords[0])
            elif intersection.geom_type == "LineString":
                for point in (intersection.coords[0], intersection.coords[-1]):
                    add_point(point)
            elif hasattr(intersection, "geoms"):
                for part in intersection.geoms:
                    add_intersection(part)

        for hit in self.tree.query(shape):
            other = int(hit)
            if other != index:
                add_intersection(shape.intersection(self.shapes[other]))
        points = []
        for _, point in sorted(cuts):
            if not points or not _same(points[-1], point):
                points.append(point)
        result = tuple(pairwise(points))
        self.parts[index] = result
        if len(self.parts) > 128:
            self.parts.popitem(last=False)
        return result

    def targets(self, start, end, radius):
        """Owner index and atomic piece for every part touched by the circular sweep."""
        from shapely.geometry import box

        sweep = ShapePoint(start) if _same(start, end) else LineString((start, end))
        x0, y0, x1, y1 = sweep.bounds
        bounds = box(x0 - radius, y0 - radius, x1 + radius, y1 + radius)
        result = []
        for hit in sorted(self.tree.query(bounds)):
            index = int(hit)
            if sweep.distance(self.shapes[index]) <= radius:
                result.extend(
                    (index, piece)
                    for piece in self._parts(index)
                    if sweep.distance(LineString(piece)) <= radius
                )
        return tuple(result)

    def erase(self, targets):
        """Keep untouched owners exact; surviving partial edges inherit only their own parent."""
        from dale.wall_styles import geometry_styles

        selected = {}
        for index, edge in targets:
            selected.setdefault(index, set()).add(edge)
        if not selected:
            return self.geometry
        geometry = self.geometry
        styles = geometry_styles(geometry)
        ancestry = {r.id: r for r in (*geometry.ancestry, *geometry.lineage)}
        records = []

        def remaining(index):
            parent = geometry.lineage[index]
            if index not in selected:
                records.append(parent)
                return (self.edges[index],)
            runs = []
            for piece in self._parts(index):
                if piece in selected[index]:
                    continue
                if runs and runs[-1][1] == piece[0]:
                    runs[-1] = (runs[-1][0], piece[1])
                else:
                    runs.append(piece)
            for edge in runs:
                record = LineRecord.child((parent,), edge)
                records.append(record)
                ancestry[record.id] = record
                styles[record.id] = styles[parent.id]
            return tuple(runs)

        walls = tuple(edge for i in range(len(geometry.walls)) for edge in remaining(i))
        closures = []
        index = len(geometry.walls)
        for path in geometry.closures:
            run = []
            for _ in pairwise(path):
                edges = remaining(index)
                index += 1
                if not edges:
                    if len(run) > 1:
                        closures.append(tuple(run))
                    run = []
                for a, b in edges:
                    if run and run[-1] != a:
                        closures.append(tuple(run))
                        run = []
                    if not run:
                        run.append(a)
                    run.append(b)
            if len(run) > 1:
                closures.append(tuple(run))
        return GeometryEdit(
            walls,
            tuple(closures),
            tuple(records),
            tuple(ancestry.values()),
            wall_styles=tuple(styles.items()),
        )


def geometry_targets(geometry, start, end, radius, target):
    """Use the same circle/capsule hit test for hover previews and deletion."""
    sweep = ShapePoint(start) if _same(start, end) else LineString((start, end))
    if target == "vertices":
        return tuple(p for p in vertices(geometry) if sweep.distance(ShapePoint(p)) <= radius)
    if target != "lines":
        raise ValueError("Unknown geometry eraser target.")
    return tuple(piece for _, piece in LineEraser(geometry).targets(start, end, radius))


def erase_geometry(geometry, start, end, radius, target):
    """Erase touched edges or vertices across a swept circular brush, including fast drags."""
    if target == "vertices":
        selected = geometry_targets(geometry, start, end, radius, target)
        for point in selected:
            if hit_vertex(geometry, point, EPSILON) is not None:
                geometry = delete_vertex(geometry, point)
        return geometry
    if target != "lines":
        raise ValueError("Unknown geometry eraser target.")
    index = LineEraser(geometry)
    return index.erase(index.targets(start, end, radius))


def insert_vertex(geometry: GeometryEdit, hit: EdgeHit) -> GeometryEdit:
    builder = LineageBuilder(geometry)
    records = list(geometry.lineage)
    styles = dict(builder.styles)
    if hit.kind == "wall":
        walls = list(geometry.walls)
        a, b = walls[hit.path_index]
        if _same(a, hit.point) or _same(b, hit.point):
            return geometry
        walls[hit.path_index : hit.path_index + 1] = [(a, hit.point), (hit.point, b)]
        closures = geometry.closures
        index = hit.path_index
    else:
        walls = geometry.walls
        closures = list(geometry.closures)
        points = list(closures[hit.path_index])
        a, b = points[hit.edge_index : hit.edge_index + 2]
        if _same(a, hit.point) or _same(b, hit.point):
            return geometry
        points.insert(hit.edge_index + 1, hit.point)
        closures[hit.path_index] = tuple(points)
        index = len(walls) + sum(len(p) - 1 for p in closures[: hit.path_index]) + hit.edge_index
    parent = records[index]
    children = tuple(LineRecord.child((parent,), edge) for edge in ((a, hit.point), (hit.point, b)))
    records[index : index + 1] = children
    for record in children:
        styles[record.id] = styles[parent.id]
    ancestry = {r.id: r for r in (*geometry.ancestry, *geometry.lineage, *children)}
    return GeometryEdit(
        tuple(walls),
        tuple(closures),
        tuple(records),
        tuple(ancestry.values()),
        wall_styles=tuple(styles.items()),
    )


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


def move_vertex(
    geometry: GeometryEdit, point: Point, destination: Point, *, connect=True, connection_group=None
) -> GeometryEdit:
    if _same(point, destination):
        return geometry

    def replace(value):
        return destination if _same(value, point) else value

    if connect:
        geometry = node_geometry(geometry, (point,))

    builder = LineageBuilder(geometry)
    contacts = tuple(
        record
        for edge, record in zip(builder.edges, geometry.lineage, strict=True)
        if connect
        and not any(_same(p, point) for p in edge)
        and _same(project(destination, edge)[0], destination)
    )
    styles = dict(builder.styles)
    ancestry = {r.id: r for r in (*geometry.ancestry, *geometry.lineage)}
    records = []

    def move_edge(edge, record):
        moved = (
            tuple(replace(p) for p in edge)
            if connect or record.connection_group == connection_group
            else edge
        )
        if _same(*moved):
            return None
        current = (
            LineRecord.child((record, *contacts), moved)
            if contacts and any(_same(p, destination) for p in moved) and moved != edge
            else record
        )
        records.append(current)
        ancestry[current.id] = current
        styles[current.id] = builder.styles[record.id]
        return moved

    source_records = iter(geometry.lineage)
    walls = tuple(moved for e in geometry.walls if (moved := move_edge(e, next(source_records))))
    closures = []
    for path in geometry.closures:
        edges = [moved for e in pairwise(path) if (moved := move_edge(e, next(source_records)))]
        if edges:
            closures.append((edges[0][0], *(e[1] for e in edges)))
    result = GeometryEdit(
        walls,
        tuple(closures),
        tuple(records),
        tuple(ancestry.values()),
        wall_styles=tuple(styles.items()),
    )
    return node_geometry(result, (destination,)) if connect else result


def extend_lines(geometry: GeometryEdit, extensions: tuple[Segment, ...]) -> GeometryEdit:
    """Extend/shorten free ends simultaneously, then node their target contacts."""
    destinations = dict(extensions)
    walls = tuple((destinations.get(a, a), destinations.get(b, b)) for a, b in geometry.walls)
    closures = tuple(
        tuple(destinations.get(point, point) for point in path) for path in geometry.closures
    )
    return node_geometry(
        GeometryEdit(
            walls, closures, geometry.lineage, geometry.ancestry, wall_styles=geometry.wall_styles
        ),
        destinations.values(),
    )


def node_geometry(geometry: GeometryEdit, points) -> GeometryEdit:
    """Materialize shared connections without changing the drawn line shapes."""
    from dale.wall_styles import geometry_styles

    points = sorted(set(points))
    records, styles = [], geometry_styles(geometry)
    ancestry = {r.id: r for r in (*geometry.ancestry, *geometry.lineage)}
    source_records = iter(geometry.lineage)

    def split(edge):
        parent = next(source_records)
        pieces = [edge]
        for point in points:
            pieces = _split_at(pieces, point)
        children = (
            [parent] if len(pieces) == 1 else [LineRecord.child((parent,), e) for e in pieces]
        )
        for record in children:
            records.append(record)
            ancestry[record.id] = record
            styles[record.id] = styles[parent.id]
        return pieces

    walls = tuple(e for edge in geometry.walls for e in split(edge))
    closures = []
    for path in geometry.closures:
        edges = [e for edge in pairwise(path) for e in split(edge)]
        closures.append((edges[0][0], *(e[1] for e in edges)))
    return GeometryEdit(
        walls,
        tuple(closures),
        tuple(records),
        tuple(ancestry.values()),
        wall_styles=tuple(styles.items()),
    )


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
