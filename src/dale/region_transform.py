"""Affine editing of selected contour cells, independently of image pixels."""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise

from shapely import STRtree
from shapely.affinity import affine_transform
from shapely.geometry import LineString, box
from shapely.ops import unary_union

from dale.editing import EPSILON
from dale.provenance import LineageBuilder, LineRecord, edge_key
from dale.session import GeometryEdit


@dataclass(frozen=True)
class RegionTransformPlan:
    original: GeometryEdit
    fixed: tuple
    moving: tuple
    polygons: tuple
    pivot: tuple
    noded: GeometryEdit

    def apply(self, dx=0.0, dy=0.0, scale=1.0, angle=0.0):
        if not all(math.isfinite(v) for v in (dx, dy, scale, angle)) or scale <= 0:
            raise ValueError("Region transforms require finite coordinates and a positive scale.")
        if dx == dy == angle == 0 and scale == 1:
            return self.original, self.polygons
        cx, cy = self.pivot
        radians = math.radians(angle)
        a, b = scale * math.cos(radians), -scale * math.sin(radians)
        d, e = -b, a
        tx, ty = cx - a * cx - b * cy + dx, cy - d * cx - e * cy + dy

        def transform(point):
            return (point[0] * a + point[1] * b + tx, point[0] * d + point[1] * e + ty)

        builder = LineageBuilder(self.noded)
        fixed_keys = {edge_key(edge) for edge in self.fixed}
        walls, records = list(self.fixed), {}
        for edge in self.fixed:
            records[edge_key(edge)] = builder.record(edge)
        for edge in self.moving:
            moved = (transform(edge[0]), transform(edge[1]))
            record = builder.record(edge)
            if edge_key(edge) in fixed_keys:
                record = LineRecord.child((record,), moved)
            if edge_key(moved) in records and records[edge_key(moved)] != record:
                record = LineRecord.child((records[edge_key(moved)], record), moved)
            records[edge_key(moved)] = record
            walls.append(moved)
        walls = tuple(dict.fromkeys(edge_key(edge) for edge in walls))
        polygons = tuple(affine_transform(p, [a, b, d, e, tx, ty]) for p in self.polygons)
        return builder.build(walls, overrides=records), polygons


def plan_region_transform(
    geometry, selected, cells, include_related=False, tolerance=0, joins=(), pivot=None
):
    """Detach unselected branches, or include all lines reachable within tolerance.

    Shared contours are retained for stationary neighboring cells when related
    geometry is excluded. History stores the exact original graph for undo.
    """
    if not selected:
        raise ValueError("Select at least one closed region on the scene image.")
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("Related-line distance must be finite and nonnegative.")
    selected = tuple(selected)
    area = unary_union(selected)
    boundary_zone = unary_union([p.boundary for p in selected]).buffer(EPSILON)
    edges = (
        *geometry.walls,
        *joins,
        *(edge for path in geometry.closures for edge in pairwise(path)),
    )
    network = unary_union([LineString(edge) for edge in edges if edge[0] != edge[1]])
    lines = list(network.geoms) if hasattr(network, "geoms") else [network]
    segments = tuple((tuple(a), tuple(b)) for line in lines for a, b in pairwise(line.coords))
    noded = LineageBuilder(geometry).build(segments)
    shapes = [LineString(edge) for edge in segments]
    moving = {i for i, line in enumerate(shapes) if boundary_zone.covers(line)}
    if not moving:
        raise ValueError("The selected region no longer has an editable boundary.")
    if include_related:
        tree = STRtree(shapes)
        pending = list(sorted(moving))
        while pending:
            index = pending.pop()
            line = shapes[index]
            x0, y0, x1, y1 = line.bounds
            distance = tolerance + EPSILON
            for candidate in tree.query(
                box(x0 - distance, y0 - distance, x1 + distance, y1 + distance)
            ):
                candidate = int(candidate)
                if candidate not in moving and line.distance(shapes[candidate]) <= distance:
                    moving.add(candidate)
                    pending.append(candidate)
        shared = set()
    else:
        other_boundaries = [p.boundary for p in cells if not area.covers(p.representative_point())]
        other_zone = unary_union(other_boundaries).buffer(EPSILON)
        shared = {i for i in moving if other_zone.covers(shapes[i])}
    fixed = tuple(edge for i, edge in enumerate(segments) if i not in moving or i in shared)
    x0, y0, x1, y1 = area.bounds
    return RegionTransformPlan(
        geometry,
        fixed,
        tuple(edge for i, edge in enumerate(segments) if i in moving),
        selected,
        pivot if pivot is not None else ((x0 + x1) / 2, (y0 + y1) / 2),
        noded,
    )
