"""Frozen affine references for outward-simplified DA contours."""

import math
from dataclasses import replace

import numpy as np

from dale.provenance import geometry_edges
from dale.session import GeometryEdit


def frames_for(session):
    return {
        identifier: (matrix, anchors)
        for identifier, matrix, anchors in next(
            (
                op.alchemist_detail_frames
                for op in reversed(session.operations)
                if isinstance(op, GeometryEdit) and op.alchemist_detail_frames is not None
            ),
            (),
        )
    }


def decode_frames(value):
    from dale.alchemist_slices import decode_placement

    if not isinstance(value, list) or len(value) > 100000:
        raise ValueError("Invalid contour detail frames.")
    result, seen = [], set()
    for entry in value:
        if (
            not isinstance(entry, list)
            or len(entry) != 3
            or not isinstance(entry[0], str)
            or not 1 <= len(entry[0]) <= 128
            or entry[0] in seen
            or not isinstance(entry[2], list)
            or len(entry[2]) != 3
        ):
            raise ValueError("Invalid contour detail frame.")
        matrix = decode_placement((0, entry[1], False))[1]
        anchors = []
        for anchor in entry[2]:
            if (
                not isinstance(anchor, list)
                or len(anchor) != 4
                or not isinstance(anchor[0], str)
                or not 1 <= len(anchor[0]) <= 256
                or type(anchor[1]) is not int
                or anchor[1] not in (0, 1)
                or any(
                    type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e9
                    for v in anchor[2:]
                )
            ):
                raise ValueError("Invalid contour detail anchor.")
            anchors.append(tuple(anchor))
        points = np.asarray([anchor[2:] for anchor in anchors])
        if np.linalg.matrix_rank(points[1:] - points[0]) != 2:
            raise ValueError("Degenerate contour detail frame.")
        seen.add(entry[0])
        result.append((entry[0], matrix, tuple(anchors)))
    return tuple(result)


def frame_placement(frame, actual):
    """Compose the saved raw placement with subsequent exact anchor transforms."""
    if frame is None:
        return None
    from dale.alchemist_slices import _affine

    matrix, anchors = frame
    edges = {record.id: edge for record, edge in actual}
    if any(anchor[0] not in edges for anchor in anchors):
        return None
    source = np.asarray([anchor[2:] for anchor in anchors])
    target = np.asarray([edges[anchor[0]][anchor[1]] for anchor in anchors])
    basis = source[1:] - source[0]
    try:
        delta = np.linalg.solve(basis, target[1:] - target[0])
    except np.linalg.LinAlgError:
        return None
    if abs(np.linalg.det(delta)) < 1e-12:
        return None
    original = _affine(matrix)
    return lambda point: tuple((np.asarray(original(point)) - source[0]) @ delta + target[0])


def placements_for(session, geometry, identifiers):
    from dale.alchemist import memberships
    from dale.alchemist_slices import _fit, object_value, object_values_for, profile_edges

    current = replace(session, operations=[*session.operations, geometry], future=[])
    grouped = {}
    for record, edge, owners in zip(
        geometry.lineage,
        geometry_edges(geometry.walls, geometry.closures),
        memberships(session.alchemist, geometry),
        strict=True,
    ):
        if len(owners) == 1:
            identifier = next(iter(owners))
            if identifier in identifiers:
                grouped.setdefault(identifier, []).append((record, edge))
    profiles, cache = dict(session.alchemist.profiles), {}
    choices = object_values_for(current)
    frames = frames_for(current)
    ancestry = {record.id: record for record in (*geometry.ancestry, *geometry.lineage)}
    result = {}
    for obj in session.alchemist.objects:
        actual = grouped.get(obj.id)
        if not actual or obj.projection is None or obj.block_id not in profiles:
            continue
        placement = frame_placement(frames.get(obj.id), actual)
        if placement is None:
            baseline = profile_edges(
                obj,
                profiles,
                object_value(current, obj),
                cache,
                alpha=session.alchemist.alpha_projection,
                separate_parts=session.alchemist.separate_projection_parts or obj.id in choices,
            )
            if not baseline:
                continue
            placement = _fit(obj, baseline, actual, ancestry)
        result[obj.id] = placement
    return result


def capture_frames(data, geometry, placements, frames):
    from dale.alchemist import memberships
    from dale.alchemist_slices import _coefficients

    grouped = {}
    for record, edge, owners in zip(
        geometry.lineage,
        geometry_edges(geometry.walls, geometry.closures),
        memberships(data, geometry),
        strict=True,
    ):
        if len(owners) == 1:
            identifier = next(iter(owners))
            if identifier in placements:
                grouped.setdefault(identifier, []).extend(
                    (record.id, endpoint, *point) for endpoint, point in enumerate(edge)
                )
    result = dict(frames)
    for identifier, placement in placements.items():
        anchors = grouped.get(identifier, ())
        if len(anchors) < 3:
            result.pop(identifier, None)
            continue
        points = np.asarray([anchor[2:] for anchor in anchors])
        first = 0
        second = int(np.argmax(np.sum((points - points[first]) ** 2, axis=1)))
        vector = points[second] - points[first]
        areas = abs(
            vector[0] * (points[:, 1] - points[first, 1])
            - vector[1] * (points[:, 0] - points[first, 0])
        )
        third = int(np.argmax(areas))
        if areas[third] <= 1e-12:
            result.pop(identifier, None)
            continue
        result[identifier] = (
            _coefficients(placement),
            tuple(anchors[i] for i in (first, second, third)),
        )
    return tuple((identifier, *frame) for identifier, frame in sorted(result.items()))
