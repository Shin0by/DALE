"""Height-aware directional repair of canonical source walls, without native splits."""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass

from shapely import STRtree
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from dale.autoclose import AutoCloseIndex
from dale.provenance import LineRecord
from dale.scene import number
from dale.session import GeometryEdit, SourceRepairEdit

EPSILON = 1e-7


def flat_geometry(geometry):
    """Expose path edges to height-scoped tools without discarding their identities."""
    if not geometry.closures:
        return geometry
    from dale.provenance import geometry_edges
    from dale.wall_styles import geometry_styles

    return GeometryEdit(
        geometry_edges(geometry.walls, geometry.closures),
        lineage=geometry.lineage,
        ancestry=geometry.ancestry,
        wall_styles=tuple(geometry_styles(geometry).items()),
    )


def contact_retained(before, after):
    return (
        before.is_empty
        or after.buffer(EPSILON).covers(before)
        or (before.length > EPSILON and after.length > EPSILON)
    )


@dataclass(frozen=True)
class RepairLayer:
    bottom: float
    top: float
    indices: tuple[int, ...]


def wall_bounds(wall):
    flags = wall.get("flags", {})
    flags = flags if isinstance(flags, dict) else {}
    values = flags.get("wall-height", {})
    if not isinstance(values, dict):
        raise ValueError("Invalid wall height bounds.")
    bottom, top = values.get("bottom"), values.get("top")
    bottom = -math.inf if bottom is None else number(bottom, "Wall bottom")
    top = math.inf if top is None else number(top, "Wall top")
    if bottom >= top:
        raise ValueError("Ambiguous wall height bounds; retained without repair.")
    return bottom, top


def wall_intervals(source, geometry=None, documents=()):
    if geometry is not None and not is_canonical(source, geometry):
        from dale.wall_styles import geometry_styles, resolve_style, source_documents

        styles, documents = geometry_styles(geometry), source_documents(source, documents)
        bounds, ambiguous = [], []
        for i, record in enumerate(geometry.lineage):
            try:
                ranges = [
                    wall_bounds(resolve_style(style, documents)) for style in styles[record.id]
                ]
                ranges.sort()
                bottom, top = ranges[0]
                for next_bottom, next_top in ranges[1:]:
                    if next_bottom > top:
                        raise ValueError("Disjoint wall height ranges require separate walls.")
                    top = max(top, next_top)
                bounds.append((bottom, top))
            except ValueError:
                bounds.append(None)
                ambiguous.append(i)
        return tuple(bounds), tuple(ambiguous)
    bounds, ambiguous = [], []
    for index, ref in enumerate(source.wall_sources):
        try:
            bounds.append(wall_bounds(source.raw["walls"][ref.wall_index]))
        except ValueError:
            bounds.append(None)
            ambiguous.append(index)
    if geometry is not None:
        for addition in getattr(geometry, "additions", ()):
            if addition.properties_json is None:
                bounds.append(
                    (
                        -math.inf if addition.bottom is None else addition.bottom,
                        math.inf if addition.top is None else addition.top,
                    )
                )
            else:
                try:
                    bounds.append(wall_bounds(json.loads(addition.properties_json)))
                except ValueError:
                    ambiguous.append(len(bounds))
                    bounds.append(None)
    return tuple(bounds), tuple(ambiguous)


def is_canonical(source, geometry):
    if source.json_bytes is None:
        return False
    try:
        canonical_geometry(source, geometry)
    except ValueError:
        return False
    return True


def infer_layers(source, geometry=None, documents=()):
    bounds, ambiguous = wall_intervals(source, geometry, documents)
    limits = sorted({v for interval in bounds if interval for v in interval if math.isfinite(v)})
    cuts = [-math.inf, *limits, math.inf]
    layers = tuple(
        RepairLayer(
            bottom,
            top,
            tuple(
                i
                for i, interval in enumerate(bounds)
                if interval and interval[0] < top and interval[1] > bottom
            ),
        )
        for bottom, top in zip(cuts, cuts[1:], strict=False)
    )
    return tuple(layer for layer in layers if layer.indices), tuple(ambiguous)


def canonical_geometry(source, geometry):
    expected = tuple(LineRecord.source(ref) for ref in source.wall_sources)
    additions = getattr(geometry, "additions", ())
    count = len(expected)
    if (
        geometry.closures
        or len(geometry.walls) != count + len(additions)
        or geometry.lineage[:count] != expected
    ):
        raise ValueError(
            "JSON repair requires original wall identities. Undo geometry edits or reopen the JSON."
        )
    identifiers = {str(w.get("_id", w.get("id"))) for w in source.raw["walls"]}
    records = {r.id for r in expected}
    for addition, record in zip(additions, geometry.lineage[count:], strict=True):
        if (
            not isinstance(addition.native_id, str)
            or not re.fullmatch(r"[A-Za-z0-9]{16}", addition.native_id)
            or addition.native_id in identifiers
            or record.id in records
            or (record.origin != "editor" and addition.source_ref is None)
        ):
            raise ValueError("Invalid authored contour identity.")
        if addition.source_ref is not None:
            if addition.source_ref not in record.sources or not isinstance(
                addition.properties_json, bytes
            ):
                raise ValueError("Invalid imported contour provenance.")
            properties = json.loads(addition.properties_json)
            if not isinstance(properties, dict) or any(
                key in properties for key in ("_id", "id", "c")
            ):
                raise ValueError("Invalid imported contour properties.")
        elif addition.properties_json is not None:
            raise ValueError("Imported contour properties require an exact source reference.")
        identifiers.add(addition.native_id)
        records.add(record.id)
        bottom = -math.inf if addition.bottom is None else number(addition.bottom, "Wall bottom")
        top = math.inf if addition.top is None else number(addition.top, "Wall top")
        if bottom >= top:
            raise ValueError("Invalid authored contour height range.")
    if any(len(edge) != 2 or edge[0] == edge[1] for edge in geometry.walls):
        raise ValueError("Invalid source wall coordinates.")
    for edge in geometry.walls:
        for point in edge:
            for value in point:
                number(value, "Repair coordinate")
    return geometry


@dataclass(frozen=True)
class LayerRepairPlan:
    original: GeometryEdit
    result: SourceRepairEdit
    segments: tuple = ()
    extensions: tuple = ()
    connections: tuple = ()
    conflicts: tuple = ()
    layer_count: int = 0
    retractions: tuple = ()

    @property
    def endpoint_moves(self):
        return (*self.extensions, *self.retractions)

    def apply(self, geometry):
        if (
            geometry.walls != self.original.walls
            or geometry.closures != self.original.closures
            or geometry.lineage != self.original.lineage
            or geometry.ancestry != self.original.ancestry
            or getattr(geometry, "additions", ()) != getattr(self.original, "additions", ())
        ):
            raise ValueError("The repair preview is no longer current. Analyze connections again.")
        return self.result if self.result.walls != flat_geometry(self.original).walls else geometry


class LayerRepairIndex:
    """Per-band proposals with one canonical coordinate state and conservative conflicts."""

    def __init__(self, source, geometry, tolerance, active_indices=None, documents=()):
        if not math.isfinite(tolerance) or tolerance < 0:
            raise ValueError("Auto-close distance must be finite and nonnegative.")
        self.source = source
        self.original = geometry
        self.geometry = geometry = flat_geometry(geometry)
        self.canonical = is_canonical(source, geometry)
        self.tolerance = tolerance
        self.layers, self.ambiguous = infer_layers(source, geometry, documents)
        self.active = frozenset(
            range(len(geometry.walls)) if active_indices is None else active_indices
        )
        self.indices = tuple(
            AutoCloseIndex(GeometryEdit(tuple(geometry.walls[i] for i in layer.indices)), tolerance)
            for layer in self.layers
        )

    def at(self, point):
        if not any(
            LineString(self.geometry.walls[i]).distance(Point(point)) <= self.tolerance
            for i in self.active
        ):
            return self._plan(())
        return self._plan(tuple(index.at(point) for index in self.indices))

    def all(self):
        return self._plan(tuple(index.all() for index in self.indices))

    def _plan(self, plans):
        original = self.geometry
        endpoints = defaultdict(list)
        for i, edge in enumerate(original.walls):
            for side, point in enumerate(edge):
                endpoints[point].append((i, side))
        # Each event is one signed endpoint move endorsed in one processing layer.
        events = []
        highlighted = set()
        for band, (layer, plan) in enumerate(zip(self.layers, plans, strict=False)):
            highlighted.update(plan.segments)
            active = set(layer.indices)
            for start, end in plan.endpoint_moves:
                keys = tuple(key for key in endpoints[start] if key[0] in active)
                if keys:
                    events.append((keys, end, band))
        parent = list(range(len(events)))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def union(a, b):
            parent[find(a)] = find(b)

        owners, destinations = {}, {}
        for event, (keys, end, _) in enumerate(events):
            for key in keys:
                if key in owners:
                    union(event, owners[key])
                owners[key] = event
            # Both vectors of a corner must commit or be rejected together.
            if end in destinations:
                union(event, destinations[end])
            destinations[end] = event
        groups = defaultdict(list)
        for i in range(len(events)):
            groups[find(i)].append(i)
        accepted, conflicts, endorsements = {}, [], defaultdict(set)
        for group in groups.values():
            if not any(key[0] in self.active for event in group for key in events[event][0]):
                continue
            proposals = defaultdict(list)
            for event in group:
                keys, end, band = events[event]
                for key in keys:
                    proposals[key].append(end)
                    endorsements[key].add(band)
            if any(
                any(math.dist(points[0], p) > EPSILON for p in points[1:])
                for points in proposals.values()
            ):
                conflicts.append(("different layer destinations", tuple(sorted(proposals))))
                continue
            for key, points in proposals.items():
                accepted[key] = min(points)

        # Validate whole dependent groups against all layers, including those
        # without an extension proposal. Existing segments/contacts must remain.
        group_for_key = {
            key: root
            for root, group in groups.items()
            for event in group
            for key in events[event][0]
        }
        rejected = set()
        for key, destination in accepted.items():
            i, side = key
            start, other = original.walls[i][side], original.walls[i][1 - side]
            distance, length = math.dist(start, destination), math.dist(start, other)
            outward = ((start[0] - other[0]) / length, (start[1] - other[1]) / length)
            delta = (destination[0] - start[0], destination[1] - start[1])
            if (
                distance > self.tolerance + EPSILON
                or length + delta[0] * outward[0] + delta[1] * outward[1] <= EPSILON
                or abs(delta[0] * outward[1] - delta[1] * outward[0]) > EPSILON
            ):
                rejected.add(group_for_key[key])

        def candidate(excluded):
            return tuple(
                tuple(
                    accepted.get((i, side), point)
                    if group_for_key.get((i, side)) not in excluded
                    else point
                    for side, point in enumerate(edge)
                )
                for i, edge in enumerate(original.walls)
            )

        # Re-evaluate after removing a dependency group so a rejected corner
        # cannot leave another group relying on its uncommitted continuation.
        while True:
            updated = candidate(rejected)
            newly_rejected = set()
            for i, (old, new) in enumerate(zip(original.walls, updated, strict=True)):
                if old == new:
                    continue
                length = math.dist(*old)
                if (
                    sum((new[1][k] - new[0][k]) * (old[1][k] - old[0][k]) for k in (0, 1))
                    <= EPSILON * length
                ):
                    newly_rejected.update(
                        group_for_key[i, side] for side in (0, 1) if (i, side) in accepted
                    )
            if newly_rejected - rejected:
                rejected.update(newly_rejected)
                continue
            for band, layer in enumerate(self.layers):
                old_shapes = [LineString(original.walls[i]) for i in layer.indices]
                new_shapes = [LineString(updated[i]) for i in layer.indices]
                tree = STRtree(new_shapes)
                old_tree = STRtree(old_shapes)
                for local, i in enumerate(layer.indices):
                    if updated[i] == original.walls[i]:
                        continue
                    # Retain every existing point contact in every covered band.
                    # Coincident overlapping walls may shorten together while
                    # retaining a nonempty shared segment; branches are checked
                    # independently as point contacts with their incident wall.
                    for hit in old_tree.query(old_shapes[local]):
                        other = int(hit)
                        j = layer.indices[other]
                        if i == j:
                            continue
                        contact = old_shapes[local].intersection(old_shapes[other])
                        if contact.is_empty:
                            continue
                        kept = new_shapes[local].intersection(new_shapes[other])
                        if not contact_retained(contact, kept):
                            newly_rejected.update(
                                group_for_key[k, side]
                                for k in (i, j)
                                for side in (0, 1)
                                if (k, side) in accepted
                            )
                    for side in (0, 1):
                        key = i, side
                        if key not in accepted or group_for_key[key] in rejected:
                            continue
                        if band in endorsements[key]:
                            continue
                        extra = LineString((original.walls[i][side], updated[i][side]))
                        for hit in tree.query(extra.buffer(EPSILON)):
                            j = layer.indices[int(hit)]
                            if i == j:
                                continue
                            intersection = extra.intersection(new_shapes[int(hit)])
                            if not intersection.is_empty and not old_shapes[local].buffer(
                                EPSILON
                            ).covers(intersection):
                                newly_rejected.add(group_for_key[key])
            # Unknown/degenerate height data is retained and never used as an
            # invented layer. A repair may not introduce contacts with it either.
            for key, destination in accepted.items():
                if group_for_key[key] in rejected:
                    continue
                i, side = key
                extra = LineString((original.walls[i][side], destination))
                previous = LineString(original.walls[i]).buffer(EPSILON)
                if any(
                    not (hit := extra.intersection(LineString(original.walls[j]))).is_empty
                    and not previous.covers(hit)
                    for j in self.ambiguous
                ):
                    newly_rejected.add(group_for_key[key])
                if any(
                    not contact_retained(
                        LineString(original.walls[i]).intersection(LineString(original.walls[j])),
                        LineString(updated[i]).intersection(LineString(original.walls[j])),
                    )
                    for j in self.ambiguous
                ):
                    newly_rejected.add(group_for_key[key])
            newly_rejected -= rejected
            if not newly_rejected:
                break
            rejected.update(newly_rejected)
        for root in sorted(rejected):
            keys = tuple(sorted({key for event in groups[root] for key in events[event][0]}))
            conflicts.append(("connection conflicts in another layer", keys))
        ambiguous = tuple((i, 0) for i in self.ambiguous if i in self.active)
        if ambiguous:
            conflicts.append(("ambiguous height bounds", ambiguous))
        extensions, retractions = [], []
        for i, side in sorted(accepted):
            start, end = original.walls[i][side], updated[i][side]
            if start == end:
                continue
            travel = sum(
                (end[k] - start[k]) * (start[k] - original.walls[i][1 - side][k]) for k in (0, 1)
            )
            (retractions if travel < 0 else extensions).append((start, end))
        result = (SourceRepairEdit if self.canonical else GeometryEdit)(
            updated,
            lineage=original.lineage,
            ancestry=original.ancestry,
            wall_styles=original.wall_styles,
            **({"additions": getattr(original, "additions", ())} if self.canonical else {}),
        )
        network = unary_union([LineString(edge) for edge in highlighted])
        highlighted = tuple(
            original.walls[i]
            for i in sorted(self.active)
            if LineString(original.walls[i]).intersection(network).length > EPSILON
        )
        return LayerRepairPlan(
            self.original,
            result,
            highlighted,
            tuple(extensions),
            conflicts=tuple(conflicts),
            layer_count=len(self.layers),
            retractions=tuple(retractions),
        )


def repair_history_is_safe(session):
    return all(
        not isinstance(op, GeometryEdit) or isinstance(op, SourceRepairEdit)
        for op in session.operations
    )
