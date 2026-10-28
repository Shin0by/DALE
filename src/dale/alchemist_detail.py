"""Vertex targets for selected closed contours, with explicit merged-edge ancestry."""

from dataclasses import replace

from shapely import Polygon

from dale.alchemist_fit import FIT_FAILED, ContourComplexityError
from dale.alchemist_outline import outer_outline
from dale.provenance import LineRecord, geometry_edges
from dale.session import GeometryEdit
from dale.wall_styles import geometry_styles


def values_for(session):
    return dict(
        next(
            (
                op.alchemist_complexity
                for op in reversed(session.operations)
                if isinstance(op, GeometryEdit) and op.alchemist_complexity is not None
            ),
            (),
        )
    )


def decode_values(values):
    if not isinstance(values, list):
        raise ValueError("Invalid contour complexity settings.")
    result, seen = [], set()
    for entry in values:
        if (
            not isinstance(entry, list)
            or len(entry) != 2
            or not isinstance(entry[0], str)
            or not 1 <= len(entry[0]) <= 128
            or entry[0] in seen
            or type(entry[1]) is not int
            or not 4 <= entry[1] <= 2147483647
        ):
            raise ValueError("Invalid contour complexity settings.")
        seen.add(entry[0])
        result.append(tuple(entry))
    return tuple(result)


def closed_paths(geometry, check_cancel=None, *, selected=None):
    """Walk stored-vertex cycles only; leave open, branched and shared joints intact."""
    edges = geometry_edges(geometry.walls, geometry.closures)
    selected = set(selected) if selected is not None else None
    wanted = (
        {r.connection_group for r in geometry.lineage if r.id in selected}
        if selected is not None
        else None
    )
    adjacency = {}
    for i, (edge, record) in enumerate(zip(edges, geometry.lineage, strict=True)):
        if check_cancel and i % 256 == 0:
            check_cancel()
        if wanted is not None and record.connection_group not in wanted:
            continue
        for point in edge:
            adjacency.setdefault((record.connection_group, point), []).append(i)
    visited, result = set(), []
    for first, (a, _) in enumerate(edges):
        if check_cancel and first % 256 == 0:
            check_cancel()
        if first in visited:
            continue
        group = geometry.lineage[first].connection_group
        if wanted is not None and group not in wanted:
            continue
        indices, points, current, point = [], [], first, a
        while current not in visited:
            if check_cancel and len(visited) % 256 == 0:
                check_cancel()
            visited.add(current)
            indices.append(current)
            points.append(point)
            edge = edges[current]
            point = edge[1] if point == edge[0] else edge[0]
            incident = adjacency[(group, point)]
            if len(incident) != 2:
                break
            following = incident[0] if incident[1] == current else incident[1]
            if following == first and point == a:
                if len(points) >= 3:
                    polygon = Polygon(points)
                    if polygon.is_valid and polygon.area > 0:
                        result.append((group, tuple(indices), tuple(points), polygon))
                break
            current = following
    return edges, result


def _candidate(points, polygon, target):
    return outer_outline(points, polygon, target)[0]


def restore_failed_objects(data, geometry, applied, identifiers):
    """Restore complete failed objects and their per-object settings atomically."""
    from dale.alchemist import memberships

    previous = applied.geometry()
    old = [
        (edge, record)
        for edge, record, own in zip(
            geometry_edges(previous.walls, previous.closures),
            previous.lineage,
            memberships(data, previous),
            strict=True,
        )
        if own & identifiers
    ]
    kept = [
        (edge, record)
        for edge, record, own in zip(
            geometry_edges(geometry.walls, geometry.closures),
            geometry.lineage,
            memberships(data, geometry),
            strict=True,
        )
        if not own & identifiers
    ]
    result = (*kept, *old)
    live = {record.id for _, record in result}
    ancestors = {
        r.id: r
        for r in (*geometry.ancestry, *geometry.lineage, *previous.ancestry, *previous.lineage)
        if r.id not in live
    }
    styles = dict(geometry.wall_styles)
    styles.update(previous.wall_styles)
    metadata = {}
    for name in (
        "alchemist_complexity",
        "alchemist_object_slices",
        "alchemist_transforms",
        "alchemist_detail_frames",
        "alchemist_empty_frames",
    ):
        latest = next(
            (
                getattr(op, name)
                for op in reversed(applied.operations)
                if getattr(op, name, None) is not None
            ),
            (),
        )
        values = {
            entry[0]: entry
            for entry in (getattr(geometry, name) or ())
            if entry[0] not in identifiers
        }
        values.update((entry[0], entry) for entry in latest if entry[0] in identifiers)
        metadata[name] = tuple(values[key] for key in sorted(values))
    return replace(
        geometry,
        walls=tuple(e for e, _ in result),
        closures=(),
        lineage=tuple(r for _, r in result),
        ancestry=tuple(ancestors.values()),
        wall_styles=tuple(styles.items()),
        **metadata,
    )


def simplify_contours(
    geometry, selected, targets, progress=None, *, check_cancel=None, failures=None
):
    """targets maps selected line IDs to maximum vertices for their complete ring."""
    selected = set(selected)
    if check_cancel:
        check_cancel()
    edges, paths = closed_paths(geometry, check_cancel, selected=selected)
    from dale.alchemist_merge import merge_outlines

    groups = {}
    for path in paths:
        groups.setdefault(path[0], []).append(path)
    accepted, selection = [], set(selected)
    failed, extra_ancestry = set(), []
    styles = dict(geometry.wall_styles)
    resolved = geometry_styles(geometry)
    changed, position = 0, 0
    for group, rings in groups.items():
        candidates, eligible, limits_by_ring, ancestry_indices = [], [], [], []
        try:
            for _, indices, points, polygon in rings:
                if check_cancel:
                    check_cancel()
                if progress:
                    progress(position, len(paths))
                position += 1
                ids = {geometry.lineage[i].id for i in indices}
                limits = [targets[i] for i in ids if i in targets]
                active = ids.issubset(selected) and bool(limits)
                eligible.append(active)
                limit = min(limits) if active else len(points)
                limits_by_ring.append(limit)
                candidate, kept = (
                    outer_outline(points, polygon, limit, check_cancel)
                    if active and len(points) > limit
                    else (points, tuple(range(len(points))))
                )
                if active and len(candidate) > limit:
                    raise ContourComplexityError(FIT_FAILED)
                candidates.append(Polygon(candidate))
                ancestry_indices.append(kept)
            changed_rings = {
                i
                for i, ring in enumerate(rings)
                if eligible[i] and len(ring[2]) > limits_by_ring[i]
            }
            if not changed_rings:
                continue
            if all(eligible):
                outputs = merge_outlines(candidates, min(limits_by_ring), check_cancel)
            else:
                # Partial ordinary selections cannot absorb unselected geometry.
                for i in changed_rings:
                    for j, ring in enumerate(rings):
                        if (
                            i != j
                            and rings[i][3].disjoint(ring[3])
                            and not candidates[i].disjoint(candidates[j])
                        ):
                            raise ContourComplexityError(FIT_FAILED)
                outputs = [((i,), shape) for i, shape in enumerate(candidates)]
            for members, shape in outputs:
                if len(members) == 1 and members[0] not in changed_rings:
                    continue
                indices = tuple(i for member in members for i in rings[member][1])
                ids = {geometry.lineage[i].id for i in indices}
                candidate = tuple(shape.exterior.coords[:-1])
                replacements = []
                merged_parent = None
                if len(members) > 1:
                    # One shared ancestry node avoids repeating all raw parents on
                    # every new side and keeps exact object/style ownership.
                    merged_parent = LineRecord.child(
                        [geometry.lineage[i] for i in indices], (candidate[0], candidate[1])
                    )
                    extra_ancestry.append(merged_parent)
                for index, (a, b) in enumerate(
                    zip(candidate, (*candidate[1:], candidate[0]), strict=True)
                ):
                    if merged_parent is not None:
                        arc = indices
                        record = LineRecord.child([merged_parent], (a, b))
                    else:
                        kept = ancestry_indices[members[0]]
                        start, end = kept[index], kept[(index + 1) % len(kept)]
                        arc, cursor = [], start
                        while cursor != end:
                            arc.append(indices[cursor])
                            cursor = (cursor + 1) % len(rings[members[0]][2])
                        record = (
                            geometry.lineage[arc[0]]
                            if len(arc) == 1
                            else LineRecord.child([geometry.lineage[i] for i in arc], (a, b))
                        )
                    inherited = tuple(
                        sorted(
                            {
                                style
                                for i in arc
                                for style in resolved.get(geometry.lineage[i].id, ())
                            }
                        )
                    )
                    if inherited:
                        styles[record.id] = inherited
                    replacements.append(((a, b), record))
                new_ids = {record.id for _, record in replacements}
                accepted.append((group, indices, ids, new_ids, replacements))
        except ContourComplexityError:
            if failures is None:
                raise
            failed.add(group)
            failures.add(group)
    if progress:
        progress(len(paths), len(paths))
    if check_cancel:
        check_cancel()
    replacements, removed = [], set()
    for group, indices, ids, new_ids, parts in accepted:
        if group not in failed:
            removed.update(indices)
            replacements.extend(parts)
            selection.difference_update(ids)
            selection.update(new_ids)
            changed += 1
    if not removed:
        return geometry, tuple(selected), changed
    kept = [
        (edge, record)
        for i, (edge, record) in enumerate(zip(edges, geometry.lineage, strict=True))
        if i not in removed
    ]
    updated = [*kept, *replacements]
    live = {r.id for _, r in updated}
    ancestors = {
        r.id: r
        for r in (*geometry.ancestry, *geometry.lineage, *extra_ancestry)
        if r.id not in live
    }
    return (
        replace(
            geometry,
            walls=tuple(edge for edge, _ in updated),
            closures=(),
            lineage=tuple(record for _, record in updated),
            ancestry=tuple(ancestors.values()),
            wall_styles=tuple(styles.items()),
        ),
        tuple(sorted(selection & live)),
        changed,
    )
