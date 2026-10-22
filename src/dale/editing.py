"""Point editing on immutable working geometry; source files are never modified."""

from __future__ import annotations

import math
from bisect import bisect_left, insort
from collections import OrderedDict
from dataclasses import dataclass
from itertools import combinations, pairwise
from typing import Literal

from shapely import STRtree
from shapely.geometry import LineString, box
from shapely.geometry import Point as ShapePoint

from dale.provenance import LineageBuilder, LineRecord, edge_key, geometry_edges
from dale.scene import Point, Segment
from dale.session import GeometryEdit

EPSILON = 1e-7


class StationaryTargets:
    """Frozen stationary edges with spatially bounded contact queries during a drag."""

    def __init__(self, geometry):
        self.edges = geometry_edges(geometry.walls, geometry.closures)
        self.shapes = tuple(LineString(edge) for edge in self.edges)
        self.tree = STRtree(self.shapes)

    def nearby(self, point, tolerance):
        x, y = point
        area = box(x - tolerance, y - tolerance, x + tolerance, y + tolerance)
        cursor = ShapePoint(point)
        return tuple(
            self.edges[int(i)]
            for i in sorted(self.tree.query(area))
            if self.shapes[int(i)].distance(cursor) <= tolerance
        )


def align_along_vector(point, edge, tolerance):
    """Extend or shorten a free end along its original noncollapsed forward ray."""
    start, end = edge
    delta = tuple(end[i] - start[i] for i in (0, 1))
    length_squared = sum(value * value for value in delta)
    if length_squared <= EPSILON * EPSILON:
        return None
    fraction = sum((point[i] - start[i]) * delta[i] for i in (0, 1)) / length_squared
    target = tuple(start[i] + fraction * delta[i] for i in (0, 1))
    if (
        fraction > 0
        and math.dist(start, target) > EPSILON
        and math.dist(point, target) <= tolerance
    ):
        return target
    return None


def right_angle_contact(point, anchors, edges, tolerance_deg, guides=()):
    """Use a nearby stationary edge as a virtual perpendicular leg without joining it."""
    candidates = []
    for edge in edges:
        nearest, _ = project(point, edge)
        for anchor in anchors:
            target, _ = project(anchor, edge)
            if math.dist(anchor, target) <= EPSILON:
                continue
            other = max(edge, key=lambda end: math.dist(end, target))
            if not _satisfies_right_angle((anchor, target, other), target, target):
                continue
            if _right_angle_deviation((anchor, nearest, other), nearest, nearest) > tolerance_deg:
                continue
            if any(abs(target[axis] - guide[axis]) > EPSILON for axis, guide in guides):
                continue
            candidates.append((math.dist(point, target), target, (anchor, target, other)))
    return (min(candidates)[1:]) if candidates else None


class GuideTargets:
    """Frozen stationary vertices and cursor-acquired axis references for one gesture."""

    def __init__(self, points):
        self.points = tuple(sorted(set(points)))
        self.point_set = frozenset(self.points)
        self.tree = STRtree([ShapePoint(p) for p in self.points])
        self.axes = tuple(tuple(sorted((p[axis], p) for p in self.points)) for axis in (0, 1))
        self.acquired = set()
        self.acquired_axes = ([], [])
        self.last = None

    def nearest(self, point, tolerance):
        candidates = (
            (math.dist(point, self.points[int(i)]), self.points[int(i)])
            for i in self.tree.query(
                box(
                    point[0] - tolerance,
                    point[1] - tolerance,
                    point[0] + tolerance,
                    point[1] + tolerance,
                )
            )
        )
        return min((hit for hit in candidates if hit[0] <= tolerance), default=(None, None))[1]

    def acquire(self, cursor, tolerance):
        point = self.nearest(cursor, tolerance)
        if point is not None:
            if point not in self.acquired:
                self.acquired.add(point)
                for axis in (0, 1):
                    insort(self.acquired_axes[axis], (point[axis], point))
            self.last = point
        return point

    def align(self, point, tolerance, *, acquired_only=False):
        destination, guides = list(point), []
        for axis in (0, 1):
            for anchors in (
                self.acquired_axes[axis],
                *(() if acquired_only else (self.axes[axis],)),
            ):
                at = bisect_left(anchors, (point[axis], (-float("inf"), -float("inf"))))
                candidates = [
                    (abs(anchors[i][0] - point[axis]), anchors[i][1])
                    for i in (at - 1, at)
                    if 0 <= i < len(anchors) and abs(anchors[i][0] - point[axis]) <= tolerance
                ]
                if candidates:
                    _, anchor = min(candidates)
                    # The most recently visited vertex identifies coincident axis references.
                    if self.last is not None and anchor[axis] == self.last[axis]:
                        anchor = self.last
                    destination[axis] = anchor[axis]
                    guides.append((axis, anchor))
                    break
        return tuple(destination), tuple(guides)


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
    geometry: GeometryEdit, point: Point, tolerance: float, exclude=None, *, anchors=()
) -> Point | None:
    """Prefer vertices over projections; a dragged node cannot snap to its own edges."""
    if tolerance <= 0:
        return None
    candidates = [
        (math.dist(point, vertex), vertex)
        for vertex in (*vertices(geometry), *anchors)
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


def _satisfies_right_angle(guide, moving, candidate):
    a, joint, b = tuple(candidate if _same(p, moving) else p for p in guide)
    u, v = tuple(a[i] - joint[i] for i in (0, 1)), tuple(b[i] - joint[i] for i in (0, 1))
    lengths = math.hypot(*u), math.hypot(*v)
    return min(lengths) > EPSILON and abs(sum(u[i] * v[i] for i in (0, 1))) <= EPSILON * math.prod(
        lengths
    )


def _right_angle_deviation(guide, moving, candidate):
    a, joint, b = tuple(candidate if _same(p, moving) else p for p in guide)
    u, v = tuple(a[i] - joint[i] for i in (0, 1)), tuple(b[i] - joint[i] for i in (0, 1))
    if min(math.hypot(*u), math.hypot(*v)) <= EPSILON:
        return math.inf
    return abs(math.degrees(math.atan2(u[0] * v[0] + u[1] * v[1], abs(u[0] * v[1] - u[1] * v[0]))))


def snap_constrained_point(
    geometry, point, tolerance, *, exclude=None, guides=(), angle=None, angles=(), anchors=()
):
    """Snap to stationary geometry without leaving accepted axes or a right-angle locus."""
    if tolerance <= 0:
        return None
    angles = tuple(angles)
    if angle is None and angles:
        angle, angles = angles[0], angles[1:]
    if not guides and angle is None:
        return snap_point(geometry, point, tolerance, exclude=exclude, anchors=anchors)

    def cross(a, b):
        return a[0] * b[1] - a[1] * b[0]

    def compatible(candidate):
        if any(abs(candidate[axis] - anchor[axis]) > EPSILON for axis, anchor in guides):
            return False
        return all(
            _satisfies_right_angle(guide, point, candidate)
            for guide in ((angle,) if angle is not None else ()) + angles
        )

    candidates = [
        (math.dist(point, vertex), vertex)
        for vertex in (*vertices(geometry), *anchors)
        if (exclude is None or not _same(vertex, exclude))
        and math.dist(point, vertex) <= tolerance
        and compatible(vertex)
    ]
    if candidates:
        return min(candidates)[1]

    circle = None
    if angle is not None:
        a, joint, b = angle
        if _same(joint, point):
            circle = tuple((a[i] + b[i]) / 2 for i in (0, 1)), math.dist(a, b) / 2
        else:
            fixed = b if _same(a, point) else a
            origin = joint
            vector = (-(fixed[1] - joint[1]), fixed[0] - joint[0])
    else:
        axis, anchor = guides[0]
        origin = anchor
        vector = (0, 1) if axis == 0 else (1, 0)

    for edge in geometry_edges(geometry.walls, geometry.closures):
        if exclude is not None and _same(project(exclude, edge)[0], exclude):
            continue
        a, b = edge
        delta = tuple(b[i] - a[i] for i in (0, 1))
        length = math.hypot(*delta)
        if length <= EPSILON:
            continue
        positions = []
        if circle is not None:
            center, radius = circle
            unit = tuple(value / length for value in delta)
            offset = tuple(center[i] - a[i] for i in (0, 1))
            along = sum(offset[i] * unit[i] for i in (0, 1))
            height_squared = radius * radius - cross(offset, unit) ** 2
            if height_squared >= -EPSILON * max(radius, 1):
                height = math.sqrt(max(0, height_squared))
                positions = [(along - height) / length, (along + height) / length]
        else:
            offset = tuple(origin[i] - a[i] for i in (0, 1))
            denominator = cross(delta, vector)
            if abs(denominator) > EPSILON * length * math.hypot(*vector):
                positions = [cross(offset, vector) / denominator]
            elif abs(cross(offset, vector)) <= EPSILON * math.hypot(*vector):
                positions = [project(point, edge)[1]]
        for fraction in positions:
            if -EPSILON / length <= fraction <= 1 + EPSILON / length:
                fraction = max(0, min(1, fraction))
                candidate = tuple(a[i] + fraction * delta[i] for i in (0, 1))
                distance = math.dist(point, candidate)
                if distance <= tolerance and compatible(candidate):
                    candidates.append((distance, candidate))
    return min(candidates)[1] if candidates else None


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


def right_angle_line(
    point, preferred, start, geometry, tolerance_deg, *, own_priority=True, guides=()
):
    """Square a new line against existing legs at its fixed start, without editing them."""
    references = tuple(
        (start, endpoint)
        for edge in geometry_edges(geometry.walls, geometry.closures)
        if _same(project(start, edge)[0], start)
        for endpoint in edge
        if not _same(endpoint, start)
    )
    target, angles = _right_angle_point(
        point,
        preferred,
        None,
        (start,),
        references,
        tolerance_deg,
        own_priority=own_priority,
        guides=guides,
    )
    return target, angles[0] if angles else None


def right_angle_point(
    point,
    preferred,
    vertex,
    neighbours,
    geometry,
    tolerance_deg,
    *,
    include_neighbours=True,
    own_priority=True,
    guides=(),
):
    """Square a joint within angular tolerance; return its closest exact guide legs."""
    target, angles = right_angle_constraints(
        point,
        preferred,
        vertex,
        neighbours,
        geometry,
        tolerance_deg,
        include_neighbours=include_neighbours,
        own_priority=own_priority,
        guides=guides,
    )
    return target, angles[0] if angles else None


def right_angle_constraints(
    point,
    preferred,
    vertex,
    neighbours,
    geometry,
    tolerance_deg,
    *,
    include_neighbours=True,
    own_priority=True,
    guides=(),
):
    """Keep the closest angle locus and combine nearby compatible affected corners."""
    references = geometry_edges(geometry.walls, geometry.closures) if include_neighbours else ()
    return _right_angle_point(
        point,
        preferred,
        vertex,
        neighbours,
        references,
        tolerance_deg,
        own_priority=own_priority,
        guides=guides,
    )


def _angle_locus(guide, moving):
    a, joint, b = guide
    if _same(joint, moving):
        return "circle", tuple((a[i] + b[i]) / 2 for i in (0, 1)), math.dist(a, b) / 2
    fixed = b if _same(a, moving) else a
    length = math.dist(fixed, joint)
    return "line", joint, (-(fixed[1] - joint[1]) / length, (fixed[0] - joint[0]) / length)


def _angle_intersections(first, second):
    """Exact intersections of two infinite right-angle loci, without extending geometry."""

    def cross(a, b):
        return a[0] * b[1] - a[1] * b[0]

    if first[0] == "circle" and second[0] == "line":
        first, second = second, first
    if first[0] == "line":
        _, origin, vector = first
        _, other, value = second
        offset = tuple(other[i] - origin[i] for i in (0, 1))
        if second[0] == "line":
            denominator = cross(vector, value)
            if abs(denominator) <= EPSILON:
                return ()
            positions = (cross(offset, value) / denominator,)
        else:
            along = sum(offset[i] * vector[i] for i in (0, 1))
            height_squared = value * value - cross(offset, vector) ** 2
            if height_squared < -EPSILON * max(value, 1):
                return ()
            height = math.sqrt(max(0, height_squared))
            positions = along - height, along + height
        return tuple(tuple(origin[i] + t * vector[i] for i in (0, 1)) for t in positions)
    _, a, ra = first
    _, b, rb = second
    distance = math.dist(a, b)
    if distance <= EPSILON or distance > ra + rb + EPSILON or distance < abs(ra - rb) - EPSILON:
        return ()
    unit = tuple((b[i] - a[i]) / distance for i in (0, 1))
    along = (ra * ra - rb * rb + distance * distance) / (2 * distance)
    height_squared = ra * ra - along * along
    if height_squared < -EPSILON * max(ra, 1):
        return ()
    height = math.sqrt(max(0, height_squared))
    center = tuple(a[i] + along * unit[i] for i in (0, 1))
    normal = -unit[1], unit[0]
    return tuple(tuple(center[i] + sign * height * normal[i] for i in (0, 1)) for sign in (-1, 1))


@dataclass(frozen=True)
class _AngleRule:
    kind: str
    target: Point
    guide: tuple | None
    locus: tuple
    allowance: float
    deviation: float

    def key(self, point, preferred, own_priority):
        priority = (
            {"own": 0, "adjacent": 1, "guide": 2}[self.kind] if own_priority else self.kind == "own"
        )
        return (
            priority,
            math.dist(point, self.target),
            math.dist(preferred, self.target),
            self.target,
            self.guide or (),
        )

    def accepts(self, candidate):
        if self.guide is not None:
            return _satisfies_right_angle(self.guide, self.target, candidate)
        _, origin, vector = self.locus
        offset = tuple(candidate[i] - origin[i] for i in (0, 1))
        return abs(offset[0] * vector[1] - offset[1] * vector[0]) <= EPSILON

    def deviation_at(self, candidate):
        return _right_angle_deviation(self.guide, self.target, candidate) if self.guide else 0

    def moved_guide(self, target):
        return tuple(target if _same(p, self.target) else p for p in self.guide)


def _right_angle_point(
    point, preferred, vertex, neighbours, references, tolerance_deg, *, own_priority=True, guides=()
):
    neighbours = tuple(sorted(set(neighbours)))
    rules = []

    def consider(target, guide, raw_joint):
        a, joint, b = raw_joint
        u = tuple(a[i] - joint[i] for i in (0, 1))
        v = tuple(b[i] - joint[i] for i in (0, 1))
        if min(math.hypot(*u), math.hypot(*v)) <= EPSILON:
            return
        deviation = abs(
            math.degrees(math.atan2(u[0] * v[0] + u[1] * v[1], abs(u[0] * v[1] - u[1] * v[0])))
        )
        if min(math.dist(guide[0], guide[1]), math.dist(guide[1], guide[2])) <= EPSILON:
            return
        distance = math.dist(point, target)
        allowance = distance + math.sin(math.radians(tolerance_deg)) * min(
            math.hypot(*u), math.hypot(*v)
        )
        kind = "own" if vertex is None or _same(guide[1], target) else "adjacent"
        rules.append(
            _AngleRule(kind, target, guide, _angle_locus(guide, target), allowance, deviation)
        )

    for a, b in combinations(neighbours, 2):
        center = tuple((a[i] + b[i]) / 2 for i in (0, 1))
        radius = math.dist(a, b) / 2
        direction = tuple(preferred[i] - center[i] for i in (0, 1))
        length = math.hypot(*direction)
        target = (
            tuple(center[i] + direction[i] * radius / length for i in (0, 1))
            if length > EPSILON
            else None
        )
        if target is None or min(math.dist(target, a), math.dist(target, b)) <= EPSILON:
            # Axis guides can land on the circle center or collapse one angle leg.
            direction = tuple(point[i] - center[i] for i in (0, 1))
            length = math.hypot(*direction)
        if length <= EPSILON:
            continue
        target = tuple(center[i] + direction[i] * radius / length for i in (0, 1))
        consider(target, (a, target, b), (a, point, b))

    # Every incident segment also changes the angle at its fixed endpoint.
    adjacent = set(neighbours)
    for edge in references:
        if vertex in edge:
            continue
        for joint, other in (edge, edge[::-1]):
            if joint not in adjacent:
                continue
            length = math.dist(other, joint)
            if length <= EPSILON:
                continue
            normal = (-(other[1] - joint[1]) / length, (other[0] - joint[0]) / length)
            distance = sum((preferred[i] - joint[i]) * normal[i] for i in (0, 1))
            target = tuple(joint[i] + distance * normal[i] for i in (0, 1))
            consider(target, (other, joint, target), (other, joint, point))
    for axis, anchor in () if own_priority else guides:
        rules.append(
            _AngleRule(
                "guide",
                preferred,
                None,
                ("line", anchor, (0, 1) if axis == 0 else (1, 0)),
                math.inf,
                0,
            )
        )

    def order(rule):
        return rule.key(point, preferred, own_priority)

    eligible = sorted((rule for rule in rules if rule.deviation <= tolerance_deg + 1e-9), key=order)
    if not eligible:
        return preferred, ()
    first = eligible[0]
    if not own_priority and first.kind == "own":
        approached = [
            rule
            for rule in rules
            if rule.kind != "own" and rule.deviation_at(first.target) <= tolerance_deg + 1e-9
        ]
        if approached:
            first = min(approached, key=order)
    # Secondary corners are also approached along the accepted primary arc/line,
    # rather than only at the unconstrained cursor position.
    rules = [
        first,
        *sorted(
            (
                rule
                for rule in rules
                if rule != first
                and (
                    rule.deviation <= tolerance_deg + 1e-9
                    or rule.deviation_at(first.target) <= tolerance_deg + 1e-9
                )
            ),
            key=order,
        ),
    ]
    targets = {first.target}
    for rule in rules[1:]:
        targets.update(_angle_intersections(first.locus, rule.locus))
    candidates = []
    for target in targets:
        if math.dist(point, target) > first.allowance + EPSILON or not first.accepts(target):
            continue
        matched = tuple(
            rule
            for rule in rules
            if math.dist(point, target) <= rule.allowance + EPSILON and rule.accepts(target)
        )
        angles = tuple(dict.fromkeys(rule.moved_guide(target) for rule in matched if rule.guide))
        own = sum(rule.kind == "own" for rule in matched)
        external = sum(rule.kind != "own" for rule in matched)
        axes = sum(rule.kind == "guide" for rule in matched)
        priorities = (-own, -external, -axes) if own_priority else (-external, -axes, -own)
        candidates.append(
            (priorities, math.dist(point, target), math.dist(preferred, target), target, angles)
        )
    best = min(candidates)
    return best[3], best[4]


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


def circle_points(
    center: Point, radius: float, cell_pixels: float = 100, *, detail_steps: int = 0
) -> tuple[Point, ...]:
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
    if type(detail_steps) is not int or not 0 <= detail_steps <= 95:
        raise ValueError("Circle detail must be an integer from 0 to 95.")
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
    # Each step adds 20% of automatic detail; retain exact opposite vertices and the cap.
    count = min(4096, 2 * ((count * (5 + detail_steps) + 9) // 10))
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
    geometry: GeometryEdit,
    center: Point,
    radius: float,
    cell_pixels: float = 100,
    *,
    detail_steps: int = 0,
) -> GeometryEdit:
    points = circle_points(center, radius, cell_pixels, detail_steps=detail_steps)
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

        for hit in self.tree.query(shape.buffer(EPSILON)):
            other = int(hit)
            if other != index:
                other_shape = self.shapes[other]
                add_intersection(shape.intersection(other_shape))
                delta = tuple(edge[1][i] - edge[0][i] for i in (0, 1))
                other_edge = self.edges[other]
                direction = tuple(other_edge[1][i] - other_edge[0][i] for i in (0, 1))
                # A separate parallel edge is not a T contact.
                if abs(delta[0] * direction[1] - delta[1] * direction[0]) <= (
                    1e-12 * math.hypot(*delta) * math.hypot(*direction)
                ):
                    continue
                for endpoint in other_edge:
                    if shape.distance(ShapePoint(endpoint)) <= EPSILON:
                        target, _ = project(endpoint, edge)
                        add_point(target)
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
