"""Cached model slabs, per-category selection and reversible profile replacement."""

import base64
import math
from dataclasses import replace
from uuid import uuid4

import numpy as np
from shapely import from_wkb, get_num_coordinates, union_all
from shapely.errors import GEOSException

from dale.alchemist_mesh import outlines
from dale.provenance import LineRecord, geometry_edges
from dale.session import GeometryEdit
from dale.wall_styles import geometry_styles


def validate_values(values):
    if (
        not isinstance(values, (tuple, list))
        or len(values) != 4
        or any(type(v) is not int or not -1 <= v <= 10 for v in values)
    ):
        raise ValueError("Invalid Dungeon Alchemist slice levels.")
    return tuple(values)


def values_for(session):
    return next(
        (
            op.alchemist_slices
            for op in reversed(session.operations)
            if isinstance(op, GeometryEdit) and op.alchemist_slices is not None
        ),
        (-1, -1, -1, -1),
    )


def object_values_for(session):
    return dict(
        next(
            (
                op.alchemist_object_slices
                for op in reversed(session.operations)
                if isinstance(op, GeometryEdit) and op.alchemist_object_slices is not None
            ),
            (),
        )
    )


def object_value(session, obj):
    from dale.alchemist import CATEGORIES

    return object_values_for(session).get(
        obj.id, (values_for(session)[CATEGORIES.index(obj.category)], 10, False)
    )


def decode_object_values(values):
    if not isinstance(values, list):
        raise ValueError("Invalid object slice settings.")
    result, seen = [], set()
    for entry in values:
        if (
            not isinstance(entry, list)
            or len(entry) != 2
            or not isinstance(entry[0], str)
            or not 1 <= len(entry[0]) <= 128
            or entry[0] in seen
            or not isinstance(entry[1], list)
            or len(entry[1]) != 3
        ):
            raise ValueError("Invalid object slice settings.")
        low, high, enabled = entry[1]
        if (
            type(low) is not int
            or type(high) is not int
            or type(enabled) is not bool
            or not -1 <= low <= 10
            or not 0 <= high <= 10
            or (enabled and not 0 <= low <= high)
        ):
            raise ValueError("Invalid object slice settings.")
        seen.add(entry[0])
        result.append((entry[0], (low, high, enabled)))
    return tuple(result)


def decode_placement(value):
    if value is None:
        return None
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 3
        or type(value[0]) is not int
        or not 0 <= value[0] <= 9
        or type(value[2]) is not bool
        or not isinstance(value[1], (list, tuple))
        or len(value[1]) != 6
        or any(
            type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e9 for v in value[1]
        )
    ):
        raise ValueError("Invalid Dungeon Alchemist projection placement.")
    a, b, c, d, _, _ = value[1]
    if abs(a * d - b * c) < 1e-12:
        raise ValueError("Invalid Dungeon Alchemist projection placement.")
    return value[0], tuple(value[1]), value[2]


def decode_profiles(value):
    if not isinstance(value, list) or len(value) > 100000:
        raise ValueError("Invalid Dungeon Alchemist projection catalog.")
    result, keys, total, vertices = [], set(), 0, 0
    try:
        for entry in value:
            if (
                not isinstance(entry, list)
                or len(entry) != 2
                or not isinstance(entry[0], str)
                or not 1 <= len(entry[0]) <= 256
                or entry[0] in keys
                or not isinstance(entry[1], list)
                or len(entry[1]) != 10
            ):
                raise ValueError("Invalid Dungeon Alchemist projection profile.")
            key, encoded = entry
            layers = []
            for text in encoded:
                if not isinstance(text, str) or len(text) > 24 * 1024 * 1024:
                    raise ValueError("Invalid Dungeon Alchemist projection size.")
                raw = base64.b64decode(text, validate=True)
                total += len(raw)
                if total > 64 * 1024 * 1024:
                    raise ValueError("Dungeon Alchemist projections exceed the size limit.")
                shape = from_wkb(raw)
                vertices += get_num_coordinates(shape)
                if (
                    shape.geom_type not in ("Polygon", "MultiPolygon")
                    or not shape.is_valid
                    or vertices > 2_000_000
                    or (
                        not shape.is_empty
                        and any(not math.isfinite(v) or abs(v) > 1e6 for v in shape.bounds)
                    )
                ):
                    raise ValueError("Invalid Dungeon Alchemist projection geometry.")
                layers.append(raw)
            keys.add(key)
            result.append((key, tuple(layers)))
    except (GEOSException, TypeError) as exc:
        raise ValueError("Invalid Dungeon Alchemist projection geometry.") from exc
    return tuple(result)


def decode_empty_frames(values):
    if not isinstance(values, list) or len(values) > 100000:
        raise ValueError("Invalid Dungeon Alchemist empty-slice placements.")
    result, seen = [], set()
    for item in values:
        if (
            not isinstance(item, list)
            or len(item) != 3
            or not isinstance(item[0], str)
            or not 1 <= len(item[0]) <= 128
            or item[0] in seen
            or not isinstance(item[2], str)
            or not 1 <= len(item[2]) <= 256
        ):
            raise ValueError("Invalid Dungeon Alchemist empty-slice placement.")
        matrix = decode_placement((0, item[1], False))[1]
        result.append((item[0], matrix, item[2]))
        seen.add(item[0])
    return tuple(result)


def _affine(matrix):
    a, b, c, d, x, y = matrix
    return lambda p: (a * p[0] + b * p[1] + x, c * p[0] + d * p[1] + y)


def _coefficients(placement):
    x, y = placement((0, 0))
    ax, ay = placement((1, 0))
    bx, by = placement((0, 1))
    return ax - x, bx - x, ay - y, by - y, x, y


def profile_edges(obj, profiles, value, cache, *, alpha=False, separate_parts=False):
    # Values are normalized height positions. At the upper endpoint use the final
    # cached slab, since there is no slab above the model's highest point.
    low, high, enabled = value if isinstance(value, tuple) else (value, 10, False)
    indices = (
        tuple(range(min(low, 9), max(min(low, 9) + 1, high)))
        if enabled
        else (obj.projection[0] if low == -1 else min(low, 9),)
    )
    if low != -1 and obj.projection[2]:
        indices = tuple(9 - i for i in indices)
    foliage = obj.category in ("tree", "bush")
    key = (
        obj.block_id,
        None if alpha and foliage else obj.original_size,
        obj.category,
        indices,
        alpha,
        separate_parts,
    )
    if key not in cache:
        shape_key = "shape", obj.block_id, indices
        if shape_key not in cache:
            cache[shape_key] = union_all([from_wkb(profiles[obj.block_id][i]) for i in indices])
        shape = cache[shape_key]
        cache[key] = (
            ()
            if shape.is_empty
            else outlines(
                shape, obj.original_size, foliage, alpha=alpha, separate_parts=separate_parts
            )
        )
    a, b, c, d, tx, ty = obj.projection[1]
    return tuple(
        ((a * x + b * y + tx, c * x + d * y + ty), (a * xx + b * yy + tx, c * xx + d * yy + ty))
        for ring in cache[key]
        for (x, y), (xx, yy) in zip(ring, ring[1:], strict=False)
    )


def raw_vertex_limit(session, identifiers):
    """Read the available detail from model profiles, never the simplified display."""
    from dale.alchemist import CATEGORIES

    data = session.alchemist
    profiles, cache, counts = dict(data.profiles), {}, {}
    choices, category_values = object_values_for(session), values_for(session)
    maximum = 4
    for obj in data.objects:
        if obj.id not in identifiers or obj.projection is None or obj.block_id not in profiles:
            continue
        choice = choices.get(obj.id, (category_values[CATEGORIES.index(obj.category)], 10, False))
        key = (
            obj.block_id,
            obj.category,
            obj.original_size,
            choice,
            obj.projection[0],
            obj.projection[2],
        )
        if key in counts:
            maximum = max(maximum, counts[key])
            continue
        edges = profile_edges(
            obj,
            profiles,
            choice,
            cache,
            alpha=data.alpha_projection,
            separate_parts=True,
        )
        start, count, local_maximum = None, 0, 4
        for a, b in edges:
            if start is None:
                start = a
            count += 1
            if b == start:
                local_maximum = max(local_maximum, count)
                start, count = None, 0
        counts[key] = local_maximum
        maximum = max(maximum, local_maximum)
    return maximum


def _fit(obj, baseline, actual, ancestry=None):
    """Retain current affine placement when regenerating a model's contour shape."""
    source, target = [], []
    roots = {root: i for i, root in enumerate(obj.roots)}
    known = ancestry or {}
    candidates = {}

    def indices_for(record):
        found, pending, seen = set(), [record], set()
        while pending:
            item = pending.pop()
            if item.id in seen:
                continue
            seen.add(item.id)
            index = roots.get(item.id)
            if index is None and item.id.startswith("da-slice:"):
                index = int(item.id.rsplit(":", 1)[1])
            if index is not None and index < len(baseline):
                found.add(index)
            else:
                pending.extend(known[parent] for parent in item.parents if parent in known)
        return found

    for record, edge in actual:
        degree = {}
        for index in indices_for(record):
            for point in baseline[index]:
                degree[point] = degree.get(point, 0) + 1
        ends = {point for point, count in degree.items() if count == 1}
        if len(ends) == 2:
            for point in edge:
                candidates[point] = candidates.get(point, ends) & ends
    for point, matching in candidates.items():
        if len(matching) == 1:
            source.append(next(iter(matching)))
            target.append(point)
    # Exact stored identities remain useful for unmodified rings and arbitrary
    # edits where adjacent simplified arcs no longer identify enough vertices.
    if len(source) < 3:
        source, target = [], []
        for record, edge in actual:
            index = roots.get(record.id)
            if index is None and record.id.startswith("da-slice:"):
                index = int(record.id.rsplit(":", 1)[1])
            if index is not None and index < len(baseline):
                source.extend(baseline[index])
                target.extend(edge)
    if len(source) >= 3:
        center = np.mean(source, axis=0)
        matrix = np.column_stack((np.asarray(source) - center, np.ones(len(source))))
        fit, _, rank, _ = np.linalg.lstsq(matrix, np.asarray(target), rcond=None)
        if rank == 3 and abs(np.linalg.det(fit[:2])) > 1e-12:
            return lambda p: tuple((np.asarray(p) - center) @ fit[:2] + fit[2])
    # Arbitrary edited topology may no longer have matching vertices. Keep its
    # current center; selecting a different slab intentionally replaces its shape.
    old = np.asarray([p for edge in baseline for p in edge])
    new = np.asarray([p for _, edge in actual for p in edge])
    shift = (new.min(axis=0) + new.max(axis=0) - old.min(axis=0) - old.max(axis=0)) / 2
    return lambda p: tuple(np.asarray(p) + shift)


def change_slice(
    session,
    category,
    value,
    cancel=None,
    *,
    object_ids=None,
    upper=10,
    between=False,
    progress=None,
    apply_detail=True,
    rebuild_current=False,
):
    from dale.alchemist import CATEGORIES, memberships
    from dale.alchemist_detail_frames import capture_frames, frame_placement, frames_for

    selected = list(values_for(session))
    index = CATEGORIES.index(category)
    validate_values([value] * 4)
    choice = (value, upper, between)
    decode_object_values([["check", list(choice)]])
    choices = object_values_for(session)
    data, geometry = session.alchemist, session.geometry()
    detail_frames = frames_for(session)
    placements = {}
    empty_frames = {
        identifier: (matrix, anchor)
        for identifier, matrix, anchor in next(
            (
                op.alchemist_empty_frames
                for op in reversed(session.operations)
                if isinstance(op, GeometryEdit) and op.alchemist_empty_frames is not None
            ),
            (),
        )
    }
    profiles = dict(data.profiles)
    candidates = [
        obj
        for obj in data.objects
        if obj.category == category
        and obj.projection is not None
        and obj.block_id in profiles
        and (object_ids is None or obj.id in object_ids)
    ]
    if not candidates:
        raise ValueError("Import the DAM with object geometry to change its slice level.")
    owned = memberships(data, geometry)
    edges = geometry_edges(geometry.walls, geometry.closures)
    by_object = {}
    for i, owners in enumerate(owned):
        for identifier in owners:
            by_object.setdefault(identifier, []).append(i)
    removed, additions, records, cache = set(), [], [], {}
    resolved = geometry_styles(geometry)
    styles = dict(geometry.wall_styles)
    ancestry = {r.id: r for r in (*geometry.ancestry, *geometry.lineage)}
    for position, obj in enumerate(candidates):
        if progress:
            progress(position, len(candidates))
        previous = choices.get(obj.id, (selected[index], 10, False))
        if rebuild_current:
            choice = previous
        separate_before = data.separate_projection_parts or obj.id in choices
        if previous == choice and separate_before and not rebuild_current:
            continue
        if cancel is not None and cancel.is_set():
            from dale.alchemist import AlchemistCancelled

            raise AlchemistCancelled()
        indices = by_object.get(obj.id, [])
        if any(len(owned[i]) != 1 for i in indices):
            continue  # A manually merged object must not modify another category.
        baseline = profile_edges(
            obj,
            profiles,
            previous,
            cache,
            alpha=data.alpha_projection,
            separate_parts=separate_before,
        )
        actual = [(geometry.lineage[i], edges[i]) for i in indices]
        saved_frame = empty_frames.get(obj.id)
        placement = None
        saved_anchor = None
        if not actual:
            if baseline:
                continue  # Deleted objects stay deleted.
            if saved_frame:
                placement = _affine(saved_frame[0])
                saved_anchor = ancestry.get(saved_frame[1])
                if saved_anchor is None:
                    raise ValueError("Missing Dungeon Alchemist empty-slice ancestry.")
            # An empty slab is not deletion. Recover the previous placement from
            # history so returning to a nonempty slab preserves moves and rotation.
            prior = replace(session, operations=list(session.operations), future=[])
            while prior.operations and not actual and placement is None:
                prior.operations.pop()
                old = prior.geometry()
                baseline = profile_edges(
                    obj,
                    profiles,
                    object_value(prior, obj),
                    cache,
                    alpha=data.alpha_projection,
                    separate_parts=data.separate_projection_parts
                    or obj.id in object_values_for(prior),
                )
                actual = [
                    (r, edge)
                    for r, edge, owners in zip(
                        old.lineage,
                        geometry_edges(old.walls, old.closures),
                        memberships(data, old),
                        strict=True,
                    )
                    if owners == frozenset((obj.id,))
                ]
            if placement is None and (not actual or not baseline):
                continue
        if placement is None:
            placement = frame_placement(detail_frames.get(obj.id), actual)
        if placement is None:
            placement = _fit(obj, baseline, actual, ancestry)
        placements[obj.id] = placement
        next_edges = profile_edges(
            obj,
            profiles,
            choice,
            cache,
            alpha=data.alpha_projection,
            separate_parts=True,
        )
        parents = (saved_anchor.id,) if saved_anchor else tuple(r.id for r, _ in actual)
        first = saved_anchor or actual[0][0]
        group = first.connection_group
        inherited = resolved.get(first.id, resolved.get(obj.roots[0], ()))
        token = uuid4().hex
        # One explicit object-level parent avoids repeating all contour IDs on
        # every new edge while retaining group and ownership ancestry.
        anchor = LineRecord(
            f"da-slice-owner:{token}", parents, origin="derived", connection_group=group
        )
        ancestry[anchor.id] = anchor
        if inherited:
            styles[anchor.id] = inherited
        if not next_edges:
            empty_frames[obj.id] = _coefficients(placement), anchor.id
        else:
            empty_frames.pop(obj.id, None)
        for j, edge in enumerate(next_edges):
            record = LineRecord(
                f"da-slice:{token}:{j}", (anchor.id,), origin="derived", connection_group=group
            )
            additions.append(tuple(placement(p) for p in edge))
            records.append(record)
        removed.update(indices)
        choices[obj.id] = choice
    if progress:
        progress(len(candidates), len(candidates))
    if not removed and not records:
        return None
    if object_ids is None and not rebuild_current:
        selected[index] = value
    kept = [i for i in range(len(edges)) if i not in removed]
    lineage = tuple(geometry.lineage[i] for i in kept) + tuple(records)
    live = {r.id for r in lineage}
    result = GeometryEdit(
        tuple(edges[i] for i in kept) + tuple(additions),
        lineage=lineage,
        ancestry=tuple(r for key, r in ancestry.items() if key not in live),
        wall_styles=tuple(styles.items()),
        alchemist_slices=tuple(selected),
        alchemist_object_slices=tuple(choices.items()),
        alchemist_empty_frames=tuple((key, *entry) for key, entry in empty_frames.items()),
    )
    from dale.alchemist_detail import simplify_contours
    from dale.alchemist_detail import values_for as complexity_values

    complexity = complexity_values(session)
    if apply_detail and complexity and records:
        generated = {record.id for record in records}
        targets = {
            record.id: min(complexity[o] for o in own if o in complexity)
            for record, own in zip(result.lineage, memberships(data, result), strict=True)
            if record.id in generated and own & complexity.keys()
        }
        result, _, _ = simplify_contours(result, generated, targets)
    if placements:
        result = replace(
            result, alchemist_detail_frames=capture_frames(data, result, placements, detail_frames)
        )
    return result
