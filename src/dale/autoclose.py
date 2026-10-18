"""Indexed directional endpoint repair on working geometry; independent of Qt."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import pairwise

from shapely import STRtree
from shapely.geometry import LineString, MultiPoint, Point, box
from shapely.ops import snap, unary_union

from dale.editing import EPSILON, extend_lines, node_geometry
from dale.scene import Segment
from dale.session import GeometryEdit


@dataclass(frozen=True)
class AutoClosePlan:
    segments: tuple[Segment, ...] = ()
    extensions: tuple[Segment, ...] = ()
    connections: tuple = ()
    retractions: tuple[Segment, ...] = ()

    @property
    def endpoint_moves(self):
        return (*self.extensions, *self.retractions)

    def apply(self, geometry: GeometryEdit) -> GeometryEdit:
        extended = extend_lines(geometry, self.endpoint_moves) if self.endpoint_moves else geometry
        return node_geometry(extended, self.connections)


class AutoCloseIndex:
    """Trace cursor seeds through existing edges and eligible directional continuations.

    Only dangling endpoints initiate repairs. Meet paired line vectors, then
    project remaining tips onto existing segments. Shortening stops at the first
    existing contact and never collapses/reverses a raw segment.
    """

    def __init__(self, geometry: GeometryEdit, tolerance: float):
        if not math.isfinite(tolerance) or tolerance < 0:
            raise ValueError("Auto-close distance must be finite and nonnegative.")
        self.tolerance = tolerance
        edges = (*geometry.walls, *(edge for path in geometry.closures for edge in pairwise(path)))
        self.raw_edges = edges
        lines = [LineString(edge) for edge in edges if math.dist(*edge) > EPSILON]
        network = unary_union(lines)
        parts = list(network.geoms) if hasattr(network, "geoms") else [network]
        self.segments = tuple(
            (tuple(a), tuple(b)) for part in parts for a, b in pairwise(part.coords)
        )
        self.lines = [LineString(edge) for edge in self.segments]
        self.tree = STRtree(self.lines)
        extensions, retractions = self._propose_moves() if tolerance else ((), ())
        moves = (*extensions, *retractions)
        # Node continuations as well: crossing a third line really connects it.
        anchors = MultiPoint([point for edge in moves for point in edge])
        joined = unary_union(
            [
                *(snap(line, anchors, EPSILON) for line in self.lines),
                *(LineString(edge) for edge in moves),
            ]
        )
        parts = list(joined.geoms) if hasattr(joined, "geoms") else [joined]
        parent = {}

        def find(point):
            parent.setdefault(point, point)
            while parent[point] != point:
                parent[point] = parent[parent[point]]
                point = parent[point]
            return point

        degree = Counter()
        for part in parts:
            for a, b in pairwise(part.coords):
                parent[find(tuple(a))] = find(tuple(b))
                degree.update((tuple(a), tuple(b)))
        # Numerical reconciliation may replace a projected tip by a nearby
        # intersection. Keep its original coordinate in the same traced group.
        graph_points = sorted(parent)
        point_tree = STRtree([Point(point) for point in graph_points])
        for point in {p for edge in (*self.segments, *moves) for p in edge}:
            if point not in parent:
                x, y = point
                nearby = [
                    graph_points[int(i)]
                    for i in point_tree.query(
                        box(x - EPSILON, y - EPSILON, x + EPSILON, y + EPSILON)
                    )
                ]
                nearest = min(nearby, key=lambda p: math.dist(p, point), default=None)
                if nearest is not None and math.dist(nearest, point) <= EPSILON:
                    parent[point] = find(nearest)
        self.groups = defaultdict(list)
        self.extensions = defaultdict(list)
        self.retractions = defaultdict(list)
        self.connections = defaultdict(list)
        self.roots = []
        for edge in self.segments:
            root = find(edge[0])
            self.roots.append(root)
            self.groups[root].append(edge)
        for edge in extensions:
            self.extensions[find(edge[0])].append(edge)
        for edge in retractions:
            self.retractions[find(edge[0])].append(edge)
        for point, count in sorted(degree.items()):
            if count >= 3:
                self.connections[find(point)].append(point)

    def _bounds(self, point):
        x, y = point
        return box(x - self.tolerance, y - self.tolerance, x + self.tolerance, y + self.tolerance)

    def _propose_moves(self):
        degree = Counter(point for edge in self.segments for point in edge)
        neighbors = {}
        for a, b in self.segments:
            neighbors[a], neighbors[b] = b, a
        tips = sorted(point for point in degree if degree[point] == 1)
        tip_tree = STRtree([Point(point) for point in tips])
        directions = {}
        limits = {}
        raw_incident = defaultdict(list)
        for a, b in self.raw_edges:
            raw_incident[a].append(b)
            raw_incident[b].append(a)
        for tip in tips:
            neighbor = neighbors[tip]
            length = math.dist(tip, neighbor)
            directions[tip] = ((tip[0] - neighbor[0]) / length, (tip[1] - neighbor[1]) / length)
            limits[tip] = length  # First inward graph node: never trim past another contact.

        def permitted(tip, end):
            delta = end[0] - tip[0], end[1] - tip[1]
            travel = sum(a * b for a, b in zip(delta, directions[tip], strict=True))
            if travel < -limits[tip] - EPSILON:
                return False
            if travel < 0 and any(
                other in directions and math.dist(other, end) <= -travel + EPSILON
                for other in raw_incident[tip]
            ):
                # An open target crossing the meeting point has two possible
                # retained halves. Only its uniquely nearer free end may trim;
                # a midpoint tie stays a T contact instead of choosing a half.
                return False
            return all(math.dist(tip, other) + travel > EPSILON for other in raw_incident[tip])

        pairs, projections = [], []
        for index, tip in enumerate(tips):
            direction = directions[tip]
            # Both endpoints may need to travel the full tolerance to a corner.
            reach = 2 * self.tolerance
            bounds = box(tip[0] - reach, tip[1] - reach, tip[0] + reach, tip[1] + reach)
            for other in tip_tree.query(bounds):
                if int(other) <= index:
                    continue
                target = tips[int(other)]
                meet = _ray_meeting(tip, direction, target, directions[target], self.tolerance)
                if meet is not None and all(permitted(start, end) for start, end in meet[0]):
                    edges, travel = meet
                    pairs.append((max(travel), sum(travel), tip, target, edges))
            for line_index in self.tree.query(self._bounds(tip)):
                a, b = self.segments[int(line_index)]
                if tip in (a, b):
                    continue
                delta = b[0] - a[0], b[1] - a[1]
                denominator = _cross(direction, delta)
                if abs(denominator) <= 1e-10 * math.dist(a, b):
                    continue
                offset = a[0] - tip[0], a[1] - tip[1]
                travel = _cross(offset, delta) / denominator
                fraction = _cross(offset, direction) / denominator
                if 0 < abs(travel) <= self.tolerance and -1e-10 <= fraction <= 1 + 1e-10:
                    # Preserve target endpoints exactly when the intersection is one.
                    target = (
                        a
                        if fraction <= 0
                        else b
                        if fraction >= 1
                        else (a[0] + fraction * delta[0], a[1] + fraction * delta[1])
                    )
                    if permitted(tip, target):
                        projections.append((abs(travel), tip, target))
        groups, used = [], set()
        # Prefer full corner repairs over two projections that invent a sliver.
        for _, _, tip, target, edges in sorted(pairs):
            if tip not in used and target not in used:
                groups.append(edges)
                used.update((tip, target))
        for _, tip, target in sorted(projections):
            if tip not in used:
                groups.append(((tip, target),))
                used.add(tip)
        # Opposite-end moves are individually valid but may together collapse
        # or reverse a short segment. Reject both complete dependent corners.
        rejected = set()
        while True:
            destinations = {a: b for i, g in enumerate(groups) if i not in rejected for a, b in g}
            bad = set()
            for a, b in self.raw_edges:
                new_a, new_b = destinations.get(a, a), destinations.get(b, b)
                if (new_a, new_b) == (a, b):
                    continue
                length = math.dist(a, b)
                if (
                    length <= EPSILON
                    or sum((new_b[k] - new_a[k]) * (b[k] - a[k]) for k in (0, 1))
                    <= EPSILON * length
                ):
                    bad.update(
                        i
                        for i, group in enumerate(groups)
                        if any(start in (a, b) for start, _ in group)
                    )
            if not bad - rejected:
                break
            rejected.update(bad)
        moves = sorted(
            edge for i, group in enumerate(groups) if i not in rejected for edge in group
        )
        extending, shortening = [], []
        for start, end in moves:
            travel = sum((end[k] - start[k]) * directions[start][k] for k in (0, 1))
            (shortening if travel < 0 else extending).append((start, end))
        return tuple(extending), tuple(shortening)

    def at(self, point) -> AutoClosePlan:
        if not self.tolerance:
            return AutoClosePlan()
        cursor = Point(point)
        roots = {
            self.roots[int(index)]
            for index in self.tree.query(self._bounds(point))
            if self.lines[int(index)].distance(cursor) <= self.tolerance
        }
        return AutoClosePlan(
            tuple(edge for root in sorted(roots) for edge in self.groups[root]),
            tuple(edge for root in sorted(roots) for edge in self.extensions[root]),
            tuple(point for root in sorted(roots) for point in self.connections[root]),
            tuple(edge for root in sorted(roots) for edge in self.retractions[root]),
        )

    def all(self) -> AutoClosePlan:
        """Use the same repair plan across the complete map."""
        return AutoClosePlan(
            self.segments,
            tuple(edge for root in sorted(self.extensions) for edge in self.extensions[root]),
            tuple(point for root in sorted(self.connections) for point in self.connections[root]),
            tuple(edge for root in sorted(self.retractions) for edge in self.retractions[root]),
        )


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _ray_meeting(p, u, q, v, tolerance):
    """Meet signed line vectors; callers constrain inward travel and retained length."""
    offset = q[0] - p[0], q[1] - p[1]
    denominator = _cross(u, v)
    if abs(denominator) <= 1e-10:
        distance = math.dist(p, q)
        if (
            0 < distance <= tolerance
            and abs(_cross(offset, u)) <= EPSILON
            and sum(a * b for a, b in zip(offset, u, strict=True)) > 0
            and sum(a * b for a, b in zip(offset, v, strict=True)) < 0
        ):
            midpoint = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
            return ((p, midpoint), (q, midpoint)), (distance / 2, distance / 2)
        return None
    first = _cross(offset, v) / denominator
    second = _cross(offset, u) / denominator
    if not -tolerance <= first <= tolerance or not -tolerance <= second <= tolerance:
        return None
    intersection = (p[0] + first * u[0], p[1] + first * u[1])
    edges = tuple((tip, intersection) for tip in (p, q) if tip != intersection)
    return (edges, (abs(first), abs(second))) if edges else None
