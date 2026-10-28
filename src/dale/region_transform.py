"""Affine editing of selected contour cells, independently of image pixels."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from shapely.affinity import affine_transform
from shapely.geometry import LineString
from shapely.ops import unary_union

from dale.editing import EPSILON
from dale.provenance import LineageBuilder, LineRecord, edge_key, geometry_edges
from dale.session import GeometryEdit


@dataclass(frozen=True)
class RegionTransformPlan:
    original: GeometryEdit
    fixed: tuple
    moving: tuple
    polygons: tuple
    pivot: tuple
    noded: GeometryEdit

    def apply(self, dx=0.0, dy=0.0, scale=1.0, angle=0.0, mirror=None):
        if not all(math.isfinite(v) for v in (dx, dy, scale, angle)) or scale <= 0:
            raise ValueError("Region transforms require finite coordinates and a positive scale.")
        if mirror not in (None, "vertical", "horizontal"):
            raise ValueError("Choose a vertical or horizontal mirror axis.")
        if dx == dy == angle == 0 and scale == 1 and mirror is None:
            return self.original, self.polygons
        cx, cy = self.pivot
        radians = math.radians(angle)
        a, b = scale * math.cos(radians), -scale * math.sin(radians)
        d, e = -b, a
        if mirror == "vertical":
            a, b = -a, -b
        elif mirror == "horizontal":
            d, e = -d, -e
        tx, ty = cx - a * cx - b * cy + dx, cy - d * cx - e * cy + dy

        def transform(point):
            return (point[0] * a + point[1] * b + tx, point[0] * d + point[1] * e + ty)

        records = self.noded.lineage
        walls = (*self.fixed, *(tuple(transform(p) for p in edge) for edge in self.moving))
        polygons = tuple(affine_transform(p, [a, b, d, e, tx, ty]) for p in self.polygons)
        return GeometryEdit(
            walls,
            lineage=records,
            ancestry=self.noded.ancestry,
            wall_styles=self.noded.wall_styles,
        ), polygons


@dataclass(frozen=True)
class RegionCopy:
    """Frozen selected boundaries; pixels and stationary branches are excluded."""

    geometry: GeometryEdit
    edges: tuple
    polygons: tuple
    anchor: tuple
    records: tuple = ()
    pivot: tuple | None = None

    @property
    def center(self):
        return self.pivot if self.pivot is not None else contour_center(self.edges)

    @property
    def points(self):
        return tuple(sorted({point for edge in self.edges for point in edge}))

    def paste(self, target, dx, dy):
        if not all(math.isfinite(v) and abs(v) <= 1e9 for v in (dx, dy)):
            raise ValueError("Region placement must be finite and within coordinate limits.")
        from dale.wall_styles import geometry_styles

        builder = LineageBuilder(target)
        source = LineageBuilder(self.geometry)
        source_records = self.records or tuple(source.record(e) for e in self.edges)
        existing = {
            (edge_key(edge), builder.styles[record.id])
            for edge, record in zip(
                geometry_edges(target.walls, target.closures), target.lineage, strict=True
            )
        }
        moved_edges = tuple(tuple((x + dx, y + dy) for x, y in edge) for edge in self.edges)
        if all(
            (edge_key(edge), source.styles[record.id]) in existing
            for edge, record in zip(moved_edges, source_records, strict=True)
        ):
            return target
        walls = list(geometry_edges(target.walls, target.closures))
        records = list(target.lineage)
        styles = geometry_styles(target)
        ancestry = {
            r.id: r
            for r in (
                *target.ancestry,
                *target.lineage,
                *self.geometry.ancestry,
                *self.geometry.lineage,
            )
        }
        for edge, record in zip(moved_edges, source_records, strict=True):
            if any(abs(v) > 1e9 for p in edge for v in p):
                raise ValueError("Region placement exceeds coordinate limits.")
            # A user-created copy retains ancestry/properties, not group membership.
            copied = LineRecord.child((record, *builder.contacts(edge)), edge, manual=True)
            copied = replace(copied, connection_group=record.connection_group)
            walls.append(edge)
            records.append(copied)
            styles[copied.id] = source.styles[record.id]
        return GeometryEdit(
            tuple(walls),
            lineage=tuple(records),
            ancestry=tuple(ancestry.values()),
            wall_styles=tuple(styles.items()),
        )


def copy_regions(geometry, selected, cells, joins=(), selection_ids=(), active_ids=None):
    plan = plan_region_transform(
        geometry,
        selected,
        cells,
        False,
        0,
        joins,
        selection_ids=selection_ids,
        active_ids=active_ids,
    )
    x0, y0, _, _ = unary_union(selected).bounds
    return RegionCopy(
        plan.noded, plan.moving, tuple(selected), (x0, y0), plan.noded.lineage[len(plan.fixed) :]
    )


def contour_center(edges):
    """Return the center of the complete selected line bounds, independent of grab anchors."""
    points = [point for edge in edges for point in edge]
    return tuple((min(p[i] for p in points) + max(p[i] for p in points)) / 2 for i in (0, 1))


def plan_figure_transform(geometry, line_ids, pivot=None, *, include_polygons=True):
    """Transform the exact selected lines, including open and disconnected contours."""
    from dale.geometry import structural_regions

    ids = set(line_ids)
    edges = geometry_edges(geometry.walls, geometry.closures)
    if not ids or not ids.issubset({record.id for record in geometry.lineage}):
        raise ValueError("Select at least one current contour line.")
    fixed, moving, fixed_records, moving_records = [], [], [], []
    for edge, record in zip(edges, geometry.lineage, strict=True):
        (moving if record.id in ids else fixed).append(edge)
        (moving_records if record.id in ids else fixed_records).append(record)
    noded = GeometryEdit(
        (*fixed, *moving),
        lineage=(*fixed_records, *moving_records),
        ancestry=geometry.ancestry,
        wall_styles=geometry.wall_styles,
    )
    return RegionTransformPlan(
        geometry,
        tuple(fixed),
        tuple(moving),
        structural_regions(tuple(moving)) if include_polygons else (),
        pivot if pivot is not None else contour_center(moving),
        noded,
    )


def copy_figures(geometry, line_ids):
    plan = plan_figure_transform(geometry, line_ids)
    points = [point for edge in plan.moving for point in edge]
    return RegionCopy(
        plan.noded,
        plan.moving,
        plan.polygons,
        tuple(min(p[i] for p in points) for i in (0, 1)),
        plan.noded.lineage[len(plan.fixed) :],
    )


def delete_figures(geometry, line_ids):
    """Delete exact selected IDs, without polygonization or changing neighbours."""
    from dale.wall_styles import geometry_styles

    ids = set(line_ids)
    if not ids:
        return geometry
    if not ids.issubset({record.id for record in geometry.lineage}):
        raise ValueError("Select at least one current contour line.")
    kept = tuple(
        (edge, record)
        for edge, record in zip(
            geometry_edges(geometry.walls, geometry.closures), geometry.lineage, strict=True
        )
        if record.id not in ids
    )
    return GeometryEdit(
        tuple(edge for edge, _ in kept),
        lineage=tuple(record for _, record in kept),
        ancestry=tuple({r.id: r for r in (*geometry.ancestry, *geometry.lineage)}.values()),
        wall_styles=tuple(geometry_styles(geometry).items()),
    )


def delete_regions(geometry, selected, *, selection_ids=(), active_ids=None):
    """Remove selected boundary pieces, retaining interior and unrelated edges."""
    # Deletion removes shared boundaries rather than cloning them for a neighbour.
    # Detached membership protects coincident surroundings after movement/paste.
    plan = plan_region_transform(
        geometry, selected, selected, selection_ids=selection_ids, active_ids=active_ids
    )
    return GeometryEdit(
        plan.fixed,
        lineage=plan.noded.lineage[: len(plan.fixed)],
        ancestry=plan.noded.ancestry,
        wall_styles=plan.noded.wall_styles,
    )


def plan_region_transform(
    geometry,
    selected,
    cells,
    include_related=False,
    tolerance=0,
    joins=(),
    pivot=None,
    selection_ids=(),
    active_ids=None,
):
    """Freeze only the selected figure; never node or merge stationary surroundings."""
    from dale.editing import _split_at
    from dale.wall_styles import geometry_styles

    if not selected:
        raise ValueError("Select at least one closed region on the scene image.")
    if not math.isfinite(tolerance) or tolerance < 0:
        raise ValueError("Related-line distance must be finite and nonnegative.")
    selected = tuple(selected)
    area = unary_union(selected)
    boundary_zone = unary_union([p.boundary for p in selected]).buffer(EPSILON)
    other_zone = unary_union(
        [p.boundary for p in cells if not area.covers(p.representative_point())]
    ).buffer(EPSILON)
    edges = geometry_edges(geometry.walls, geometry.closures)
    styles = geometry_styles(geometry)
    fixed, moving, fixed_records, moving_records = [], [], [], []
    ancestry = {r.id: r for r in (*geometry.ancestry, *geometry.lineage)}
    selected_ids = set(selection_ids)
    if selected_ids and not selected_ids.issubset({r.id for r in geometry.lineage}):
        raise ValueError("The selected figure is no longer current.")
    anchors = tuple(
        tuple(p)
        for polygon in selected
        for ring in (polygon.exterior, *polygon.interiors)
        for p in ring.coords
    )
    for edge, record in zip(edges, geometry.lineage, strict=True):
        if active_ids is not None and record.id not in active_ids:
            fixed.append(edge)
            fixed_records.append(record)
            continue
        if selected_ids:
            parts = (edge,)
            chosen = [record.id in selected_ids]
        else:
            parts = (edge,)
            for point in anchors:
                parts = tuple(_split_at(parts, point))
            chosen = [boundary_zone.covers(LineString(part)) for part in parts]
        if not any(chosen):
            fixed.append(edge)
            fixed_records.append(record)
            continue
        shared = not selected_ids and any(
            yes and other_zone.covers(LineString(part))
            for part, yes in zip(parts, chosen, strict=True)
        )
        if shared:
            fixed.append(edge)
            fixed_records.append(record)
        for part, yes in zip(parts, chosen, strict=True):
            if not yes and shared:
                continue
            child = record if len(parts) == 1 and not shared else LineRecord.child((record,), part)
            ancestry[child.id] = child
            styles[child.id] = styles[record.id]
            if yes:
                moving.append(part)
                moving_records.append(child)
            else:
                fixed.append(part)
                fixed_records.append(child)
    # Existing virtual joins may complete the chosen figure, but never repair neighbours.
    if not selected_ids:
        for edge in joins:
            if boundary_zone.covers(LineString(edge)):
                record = LineRecord.child((), edge, manual=True)
                moving.append(edge)
                moving_records.append(record)
                ancestry[record.id] = record
    if not moving:
        raise ValueError("The selected region no longer has an editable boundary.")
    noded = GeometryEdit(
        (*fixed, *moving),
        lineage=(*fixed_records, *moving_records),
        ancestry=tuple(ancestry.values()),
        wall_styles=tuple(styles.items()),
    )
    x0, y0, x1, y1 = area.bounds
    return RegionTransformPlan(
        geometry,
        tuple(fixed),
        tuple(moving),
        selected,
        pivot if pivot is not None else ((x0 + x1) / 2, (y0 + y1) / 2),
        noded,
    )
