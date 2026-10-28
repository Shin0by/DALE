"""Height-filtered contour views and native-aware manual creation/editing."""

from __future__ import annotations

import math
import secrets
from dataclasses import dataclass

from shapely.geometry import LineString, Point

from dale.layer_repair import EPSILON, flat_geometry, infer_layers, is_canonical, wall_intervals
from dale.provenance import LineRecord
from dale.scene import number
from dale.session import AddedSourceWall, GeometryEdit, SourceRepairEdit


@dataclass(frozen=True)
class SourceLayer:
    key: str
    kind: str
    bottom: float | None
    top: float | None
    indices: tuple[int, ...]

    @property
    def range_text(self):
        def label(value, default):
            return default if value is None else format(value, ".15g")

        return f"{label(self.bottom, '-∞')} - {label(self.top, '+∞')}"


def source_layers(source, geometry, documents=(), *, alchemist=None):
    if alchemist is not None:
        from dale.alchemist import height_layers

        return height_layers(source, flat_geometry(geometry), documents, alchemist)
    geometry = flat_geometry(geometry)
    intervals, ambiguous = wall_intervals(source, geometry, documents)
    bands, _ = infer_layers(source, geometry, documents)
    choices = [SourceLayer("all", "all", None, None, tuple(range(len(geometry.walls))))]
    band_ranges = {(b.bottom, b.top) for b in bands}
    if not band_ranges:
        band_ranges.add((-math.inf, math.inf))
    for kind, ranges in (
        ("band", sorted(band_ranges)),
        ("range", sorted(set(i for i in intervals if i) - band_ranges)),
    ):
        for bottom, top in ranges:
            choices.append(
                SourceLayer(
                    f"{kind}:{bottom!r}:{top!r}",
                    kind,
                    bottom if math.isfinite(bottom) else None,
                    top if math.isfinite(top) else None,
                    tuple(
                        i
                        for i, interval in enumerate(intervals)
                        if interval
                        and (
                            interval == (bottom, top)
                            if kind == "range"
                            else interval[0] < top and interval[1] > bottom
                        )
                    ),
                )
            )
    if ambiguous:
        choices.append(SourceLayer("ambiguous", "ambiguous", None, None, ambiguous))
    return tuple(choices)


def layer_geometry(geometry, indices):
    geometry = flat_geometry(geometry)
    return GeometryEdit(
        tuple(geometry.walls[i] for i in indices),
        lineage=tuple(geometry.lineage[i] for i in indices),
        ancestry=geometry.ancestry,
        wall_styles=geometry.wall_styles,
    )


def replace_layer_geometry(original, indices, edited):
    from dale.wall_styles import geometry_styles

    original, edited = flat_geometry(original), flat_geometry(edited)
    indices = set(indices)
    fixed = tuple(i for i in range(len(original.walls)) if i not in indices)
    ancestry = {r.id: r for r in (*original.ancestry, *original.lineage, *edited.ancestry)}
    styles = {**geometry_styles(original), **geometry_styles(edited)}
    return GeometryEdit(
        (*[original.walls[i] for i in fixed], *edited.walls),
        lineage=(*[original.lineage[i] for i in fixed], *edited.lineage),
        ancestry=tuple(ancestry.values()),
        wall_styles=tuple(styles.items()),
    )


def move_source_vertex(
    source,
    geometry,
    vertex,
    destination,
    active_indices,
    documents=(),
    *,
    group_filter=False,
    connection_group=None,
):
    destination = tuple(number(v, "Repair coordinate") for v in destination)
    if destination == vertex:
        return geometry
    geometry = flat_geometry(geometry)
    intervals, _ = wall_intervals(source, geometry, documents)
    incident = {
        i
        for i, edge in enumerate(geometry.walls)
        if vertex in edge
        and (not group_filter or geometry.lineage[i].connection_group == connection_group)
    }
    moving = incident.intersection(active_indices)
    # Contacts follow shared walls into every overlapping band. Merely coincident
    # XY endpoints on independent floors are not a shared node.
    while True:
        related = {
            i
            for i in incident - moving
            if intervals[i]
            and any(
                intervals[j]
                and max(intervals[i][0], intervals[j][0]) < min(intervals[i][1], intervals[j][1])
                for j in moving
            )
        }
        if not related:
            break
        moving.update(related)
    if not moving:
        return geometry
    walls = tuple(
        tuple(destination if p == vertex and i in moving else p for p in edge)
        for i, edge in enumerate(geometry.walls)
    )
    if any(math.dist(*walls[i]) <= EPSILON for i in moving):
        raise ValueError("Moving this point would collapse a contour. The move was not applied.")
    canonical = is_canonical(source, geometry)
    return (SourceRepairEdit if canonical else GeometryEdit)(
        walls,
        lineage=geometry.lineage,
        ancestry=geometry.ancestry,
        wall_styles=geometry.wall_styles,
        **({"additions": getattr(geometry, "additions", ())} if canonical else {}),
    )


def add_source_wall(source, geometry, start, end, layer, documents=()):
    geometry = flat_geometry(geometry)
    canonical = is_canonical(source, geometry)
    if layer.kind not in ("all", "band", "range"):
        raise ValueError("Choose a height range before drawing a new contour.")
    edge = tuple(tuple(number(v, "Repair coordinate") for v in p) for p in (start, end))
    if math.dist(*edge) <= EPSILON:
        return geometry
    intervals, _ = wall_intervals(source, geometry, documents)
    bounds = (
        -math.inf if layer.bottom is None else layer.bottom,
        math.inf if layer.top is None else layer.top,
    )
    # Only a complete same-range copy of an ordinary editor-created wall is a no-op.
    # Original walls with equal XY but different opaque settings always coexist.
    count = len(source.wall_sources)
    for i in range(count, len(geometry.walls)) if canonical else ():
        if (
            geometry.additions[i - count].source_ref is None
            and intervals[i] == bounds
            and set(geometry.walls[i]) == set(edge)
        ):
            return geometry
    parents = tuple(
        geometry.lineage[i]
        for i in layer.indices
        if any(LineString(geometry.walls[i]).distance(Point(p)) <= EPSILON for p in edge)
    )
    record = LineRecord.child(parents, edge, manual=True)
    identifiers = {str(w.get("_id", w.get("id"))) for w in source.raw["walls"]}
    additions = getattr(geometry, "additions", ())
    identifiers.update(a.native_id for a in additions)
    native_id = secrets.token_hex(8)
    while native_id in identifiers:
        native_id = secrets.token_hex(8)
    if not canonical:
        from dale.wall_styles import geometry_styles, ordinary_wall, property_style

        styles = geometry_styles(geometry)
        properties = ordinary_wall(layer.bottom, layer.top)
        properties["_id"] = native_id
        styles[record.id] = (property_style(properties),)
        ancestry = {r.id: r for r in (*geometry.ancestry, *geometry.lineage)}
        return GeometryEdit(
            (*geometry.walls, edge),
            geometry.closures,
            (*geometry.lineage, record),
            tuple(ancestry.values()),
            wall_styles=tuple(styles.items()),
        )
    return SourceRepairEdit(
        (*geometry.walls, edge),
        lineage=(*geometry.lineage, record),
        ancestry=geometry.ancestry,
        additions=(*additions, AddedSourceWall(native_id, layer.bottom, layer.top)),
        wall_styles=geometry.wall_styles,
    )
