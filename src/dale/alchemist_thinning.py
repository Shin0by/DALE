"""Reversible, selection-scoped thinning of overlapping whole DA objects."""

import heapq
from dataclasses import replace

from shapely import STRtree, union_all

from dale.alchemist_detail import closed_paths


def state_for(session):
    return next(
        (
            op.alchemist_thinning
            for op in reversed(session.operations)
            if getattr(op, "alchemist_thinning", None) is not None
        ),
        (0, (), ()),
    )


def decode_state(value):
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 3
        or type(value[0]) is not int
        or not 0 <= value[0] <= 10
    ):
        raise ValueError("Invalid object thinning settings.")
    level, scope, hidden = value
    for identifiers in (scope, hidden):
        if (
            not isinstance(identifiers, (list, tuple))
            or len(identifiers) > 100000
            or any(not isinstance(i, str) or not 1 <= len(i) <= 128 for i in identifiers)
            or len(set(identifiers)) != len(identifiers)
        ):
            raise ValueError("Invalid object thinning settings.")
    if not set(hidden).issubset(scope) or (level == 0 and hidden):
        raise ValueError("Invalid object thinning settings.")
    return level, tuple(scope), tuple(hidden)


def hidden_objects(session):
    return frozenset(state_for(session)[2])


def object_shapes(session, identifiers, check):
    from dale.alchemist import memberships

    geometry = session.geometry()
    ownership = memberships(session.alchemist, geometry)
    wanted = set(identifiers)
    parts = {}
    for _, indices, _, polygon in closed_paths(geometry, check)[1]:
        check()
        owners = set.intersection(*(set(ownership[i]) for i in indices))
        # Shared/ambiguous boundaries cannot be safely hidden as one object.
        if len(owners) == 1 and owners <= wanted:
            parts.setdefault(next(iter(owners)), []).append(polygon)
    return {identifier: union_all(polygons) for identifier, polygons in parts.items()}


def thin_shapes(shapes, level, check=lambda: None, progress=lambda *_: None):
    """Greedily remove redundant coverage, preserving isolated and exposed objects.

    The ranking is independent of the requested level, giving nested results.
    Area coverage drives redundancy; exposed boundary and lost area favor outer
    silhouettes and uniform filling. Only real intersections supply neighbours.
    Stale heap scores are upper bounds because removing neighbours lowers coverage.
    """
    if type(level) is not int or not 0 <= level <= 10:
        raise ValueError("Invalid object thinning level.")
    if level == 0 or len(shapes) < 2:
        return frozenset()
    names = sorted(shapes)
    polygons = [shapes[name] for name in names]
    tree = STRtree(polygons)
    active, versions = set(range(len(names))), [0] * len(names)
    heap = [(-2.0, 0.0, names[i], i, -1) for i in active]
    heapq.heapify(heap)
    removed = set()
    threshold = 1 - level / 10

    def neighbours(i):
        return [
            int(j)
            for j in tree.query(polygons[i], predicate="intersects")
            if j != i and int(j) in active
        ]

    while heap:
        check()
        negative, lost, _, i, version = heapq.heappop(heap)
        if i not in active:
            continue
        adjacent = neighbours(i)
        if not adjacent:
            continue
        if version != versions[i]:
            other = union_all([polygons[j] for j in adjacent])
            check()
            shape = polygons[i]
            covered = min(1.0, max(0.0, shape.intersection(other).area / shape.area))
            exposed = shape.boundary.difference(other).length / shape.length
            score = covered * (1 - 0.5 * exposed)
            lost = shape.area * (1 - covered)
            heapq.heappush(heap, (-score, lost, names[i], i, versions[i]))
            continue
        if -negative + 1e-12 < threshold:
            break
        active.remove(i)
        removed.add(names[i])
        for j in adjacent:
            versions[j] += 1
        progress(len(removed), len(names))
    return frozenset(removed)


def thin_objects(session, identifiers, level, check=lambda: None, progress=lambda *_: None):
    allowed = {obj.id for obj in session.alchemist.objects if obj.category != "wall"}
    scope = set(identifiers) & allowed
    shapes = object_shapes(session, scope, check) if level else {}
    hidden = thin_shapes(shapes, level, check, progress)
    check()
    return replace(
        session.geometry(), alchemist_thinning=(level, tuple(sorted(scope)), tuple(sorted(hidden)))
    )
