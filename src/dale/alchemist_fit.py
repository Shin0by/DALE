"""Budget-specific global construction of enclosing closed polygons."""

import numpy as np
from shapely import Point, Polygon, distance
from shapely import points as point_shapes
from shapely.ops import nearest_points


class ContourComplexityError(ValueError):
    """The requested budget cannot safely replace the last complete contours."""


FIT_FAILED = "The requested contour complexity could not be built. The previous contours were kept."


def _intersections(normals, offsets):
    previous, prior = np.roll(normals, 1, axis=0), np.roll(offsets, 1)
    determinant = previous[:, 0] * normals[:, 1] - previous[:, 1] * normals[:, 0]
    if np.any(np.abs(determinant) < 1e-12):
        return None
    return np.column_stack(
        (
            (prior * normals[:, 1] - offsets * previous[:, 1]) / determinant,
            (offsets * previous[:, 0] - prior * normals[:, 0]) / determinant,
        )
    )


def _frame(raw, polygon):
    center = np.asarray(polygon.centroid.coords[0])
    points = raw - center
    following = np.roll(points, -1, axis=0)
    x, y = points.T
    xx, yy = following.T
    cross = x * yy - xx * y
    total = cross.sum()
    covariance = np.array(
        (
            (
                np.sum(cross * (x * x + x * xx + xx * xx)) / (6 * total),
                np.sum(cross * (2 * x * y + x * yy + xx * y + 2 * xx * yy)) / (12 * total),
            ),
            (0, np.sum(cross * (y * y + y * yy + yy * yy)) / (6 * total)),
        )
    )
    covariance[1, 0] = covariance[0, 1]
    values, vectors = np.linalg.eigh(covariance)
    values = np.maximum(values, max(values[-1], 1e-12) * 1e-12)
    basis = (vectors * np.sqrt(values)) @ vectors.T
    return center, basis, np.linalg.solve(basis, points.T).T


def _support(arc, sign):
    vector = arc[-1] - arc[0]
    length = np.linalg.norm(vector)
    if length < 1e-12:
        return None
    normal = sign * np.array((vector[1], -vector[0])) / length
    projection = arc @ normal
    offset = projection.max()
    distances = offset - projection
    lengths = np.linalg.norm(np.diff(arc, axis=0), axis=1)
    error = np.sum((distances[:-1] ** 2 + distances[1:] ** 2) * lengths) / 2
    return normal, offset, error


def _partitions(raw, count, sign, check):
    """Solve the complete cyclic partition anew for this exact side budget.

    Every dynamic-programming row represents a final segment count, not a chain
    of vertex deletions. The bounded cyclic grid includes prominent original
    corners; corners are ownership/arc candidates, never fixed output vertices.
    """
    if count > 48:
        return
    if len(raw) > 2048:
        previous, following = np.roll(raw, 1, axis=0), np.roll(raw, -1, axis=0)
        a, b = raw - previous, following - raw
        importance = np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0])
        selected = np.unique(
            np.r_[
                np.linspace(0, len(raw), 1024, endpoint=False).astype(int),
                np.argsort(importance, kind="stable")[-1024:],
            ]
        )
        raw = raw[selected]  # Proposal grid only; publication checks the exact source.
    size = len(raw)
    if size <= 128:
        grid = np.arange(size)
    else:
        # Reserve half the grid for spatial coverage and half for large features.
        previous, following = np.roll(raw, 1, axis=0), np.roll(raw, -1, axis=0)
        a, b = raw - previous, following - raw
        importance = np.abs(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0])
        features = np.argsort(importance, kind="stable")[-64:]
        grid = np.unique(np.r_[np.linspace(0, size, 64, endpoint=False).astype(int), features])
    m = len(grid)
    if count >= m:
        return
    normals = np.zeros((m, m, 2))
    offsets = np.zeros((m, m))
    costs = np.full((m, m), np.inf)
    for i in range(m):
        check()
        for j in range(m):
            span = (grid[j] - grid[i]) % size
            if not span:
                continue
            arc = raw[np.arange(grid[i], grid[i] + span + 1) % size]
            fitted = _support(arc, sign)
            if fitted is not None:
                normals[i, j], offsets[i, j], costs[i, j] = fitted
    for start in np.linspace(0, m, min(8, m), endpoint=False).astype(int):
        check()
        order = (np.arange(m + 1) + start) % m
        matrix = costs[order[:, None], order[None, :]]
        distance = np.full((m + 1, m + 1), np.inf)
        distance[0, 1:] = matrix[0, 1:]
        parent = np.zeros((count + 1, m + 1, m + 1), dtype=int)
        joins = {}
        for begin in range(1, m):
            check()
            left = normals[order[:begin], order[begin]][:, None, :]
            right = normals[order[begin], order[begin + 1 :]][None, :, :]
            h = offsets[order[:begin], order[begin]][:, None]
            hh = offsets[order[begin], order[begin + 1 :]][None, :]
            determinant = left[:, :, 0] * right[:, :, 1] - left[:, :, 1] * right[:, :, 0]
            valid = np.abs(determinant) > 1e-12
            divisor = np.where(valid, determinant, 1)
            x = (h * right[:, :, 1] - hh * left[:, :, 1]) / divisor
            y = (hh * left[:, :, 0] - h * right[:, :, 0]) / divisor
            junction = raw[grid[order[begin]]]
            penalty = 4.0 * ((x - junction[0]) ** 2 + (y - junction[1]) ** 2)
            joins[begin] = np.where(valid, penalty, np.inf)
        for level in range(2, count + 1):
            check()
            following = np.full_like(distance, np.inf)
            for begin in range(level - 1, m):
                values = distance[:begin, begin, None] + joins[begin]
                chosen = values.argmin(axis=0)
                following[begin, begin + 1 :] = (
                    values[chosen, np.arange(m - begin)] + matrix[begin, begin + 1 :]
                )
                parent[level, begin, begin + 1 :] = chosen
            distance = following
        begin = int(distance[:, m].argmin())
        if not np.isfinite(distance[begin, m]):
            continue
        chunks, end = [], m
        for level in range(count, 0, -1):
            chunks.append((order[begin], order[end]))
            begin, end = parent[level, begin, end], begin
        chunks.reverse()
        yield _intersections(
            np.asarray([normals[i, j] for i, j in chunks]),
            np.asarray([offsets[i, j] for i, j in chunks]),
        )


def _resampled(raw, count, sign, check):
    """Reconstruct all sides simultaneously from budget-specific perimeter arcs."""
    lengths = np.linalg.norm(np.roll(raw, -1, axis=0) - raw, axis=1)
    positions = np.r_[0, np.cumsum(lengths)]
    perimeter = positions[-1]
    extended = np.r_[positions[:-1], positions[:-1] + perimeter]
    for phase in (0.0, 0.25, 0.5, 0.75):
        check()
        cuts = (np.arange(count + 1) + phase) * perimeter / count
        normals, offsets, anchors = [], [], []
        for start, end in zip(cuts[:-1], cuts[1:], strict=True):
            check()
            first = np.searchsorted(extended, start, side="right")
            last = np.searchsorted(extended, end, side="left")
            inside = extended[first:last]
            samples = np.r_[start, inside, end] % perimeter
            arc = np.column_stack(
                [
                    np.interp(samples, positions, np.r_[raw[:, axis], raw[0, axis]])
                    for axis in (0, 1)
                ]
            )
            fitted = _support(arc, sign)
            if fitted is None:
                break
            normal, offset, _ = fitted
            normals.append(normal)
            offsets.append(offset)
            anchors.append(arc[0])
        if len(normals) == count:
            normals, offsets, anchors = map(np.asarray, (normals, offsets, anchors))
            previous = np.roll(normals, 1, axis=0)
            bisectors = normals + previous
            lengths = np.linalg.norm(bisectors, axis=1)
            bisectors /= np.maximum(lengths[:, None], 1e-12)
            denominator = np.sum(normals * bisectors, axis=1)
            distance = np.maximum(
                offsets - np.sum(anchors * normals, axis=1),
                np.roll(offsets, 1) - np.sum(anchors * previous, axis=1),
            )
            # A joint can cut a tiny source wedge even when each fitted side
            # supports its own arc. Rebuild the complete offset-line system;
            # validity/containment and valley checks still decide publication.
            for padding in (0.0, 0.005, 0.02, 0.08):
                check()
                yield _intersections(normals, offsets + padding * perimeter / count)
                if np.all(denominator > 1e-10):
                    yield (
                        anchors
                        + bisectors
                        * ((distance + padding * perimeter / count) / denominator)[:, None]
                    )


def _envelopes(raw, count, sign, check):
    """Independent enclosing support candidates for every shape, not a type branch."""
    step = 2 * np.pi / count
    anchor = np.arctan2(raw[0, 1], raw[0, 0])
    hull = Polygon(raw).convex_hull
    vertices = np.asarray(hull.exterior.coords[:-1])
    if not hull.exterior.is_ccw:
        vertices = vertices[::-1]
    if len(vertices) <= count:
        # The control is a maximum count. An exact enclosing hull with fewer
        # sides is preferable to adding a distant intersection just to spend it.
        yield vertices if sign > 0 else vertices[::-1]
    edges = np.roll(vertices, -1, axis=0) - vertices
    edge_angles = np.arctan2(-edges[:, 0], edges[:, 1]) % (2 * np.pi)
    ordered = np.argsort(edge_angles, kind="stable")
    phases = 32 if count <= 128 else 8
    for phase in np.arange(phases) * step / phases:
        check()
        angles = anchor + phase + np.arange(count) * step
        normals = np.column_stack((np.cos(angles), np.sin(angles)))
        # Convex support lookup replaces a source-by-side matrix. This stays
        # bounded when both the mask and requested contour have many vertices.
        indices = np.searchsorted(edge_angles[ordered], angles % (2 * np.pi)) % len(vertices)
        offsets = np.sum(vertices[ordered[indices]] * normals, axis=1)
        result = _intersections(normals, offsets)
        yield result if sign > 0 else result[::-1]


def _trim_excess(candidate, reference, check):
    """Remove long intersection spikes without changing the requested side count."""
    from dale.alchemist_outline import _covers

    if len(candidate) > 48:
        return candidate
    targets = np.asarray(
        [nearest_points(Point(point), reference.exterior)[1].coords[0] for point in candidate]
    )
    distances = np.linalg.norm(candidate - targets, axis=1)
    threshold = max(3 * np.median(distances), 2 * np.sqrt(reference.area) / len(candidate))
    result = candidate.copy()
    if np.any(distances > threshold) and Polygon(targets).is_valid:
        center = np.asarray(reference.centroid.coords[0])
        low = 1.0
        for high in (1.01, 1.03, 1.06, 1.12, 1.25, 1.5):
            check()
            proposal = center + (targets - center) * high
            if _covers(Polygon(proposal), reference):
                for _ in range(12):
                    check()
                    middle = (low + high) / 2
                    trial = center + (targets - center) * middle
                    if _covers(Polygon(trial), reference):
                        high = middle
                    else:
                        low = middle
                proposal = center + (targets - center) * high
                if Polygon(proposal).area < Polygon(result).area:
                    result = proposal
                break
            low = high
    for i in np.flatnonzero(distances > threshold):
        check()
        original = result[i].copy()
        low, high = 0.0, 1.0
        for _ in range(12):
            check()
            fraction = (low + high) / 2
            result[i] = original + fraction * (targets[i] - original)
            if _covers(Polygon(result), reference):
                low = fraction
            else:
                high = fraction
        result[i] = original + low * (targets[i] - original)
    return result


def build_outline(points, polygon, target, check_cancel=None):
    """Build complete candidates from the immutable source at the requested budget."""
    from dale.alchemist_outline import _covers

    def check():
        if check_cancel:
            check_cancel()

    check()
    count = max(4, target)
    if len(points) <= count:
        return points, tuple(range(len(points)))
    raw = np.asarray(points, dtype=float)
    origin = raw[0]
    extent = float(np.ptp(raw, axis=0).max())
    local = (raw - origin) / extent
    center, basis, normalized = _frame(local, Polygon(local))
    reference = Polygon(normalized)
    # Remove only numerically collinear samples from the proposal grid. This is
    # the same geometric boundary, not an intermediate simplification level.
    normalized = np.asarray(reference.simplify(1e-10).exterior.coords[:-1])
    sign = 1 if reference.exterior.is_ccw else -1
    # Fix fidelity samples from the source, independently of the requested
    # budget. Arc samples measure broad errors; source corners retain narrow
    # notches that uniform sampling alone could miss. Bound the scoring work.
    edges = np.roll(normalized, -1, axis=0) - normalized
    lengths = np.linalg.norm(edges, axis=1)
    positions = np.r_[0, np.cumsum(lengths)]
    samples = np.linspace(0, positions[-1], 256, endpoint=False)
    sampled = np.column_stack(
        [
            np.interp(samples, positions, np.r_[normalized[:, axis], normalized[0, axis]])
            for axis in (0, 1)
        ]
    )
    corners = normalized
    if len(corners) > 512:
        previous = np.roll(edges, 1, axis=0)
        importance = np.abs(previous[:, 0] * edges[:, 1] - previous[:, 1] * edges[:, 0])
        selected = np.unique(
            np.r_[
                np.linspace(0, len(corners), 256, endpoint=False).astype(int),
                np.argsort(importance, kind="stable")[-256:],
            ]
        )
        corners = corners[selected]
    fidelity_points = point_shapes(np.vstack((sampled, corners)))
    best, score = None, np.inf
    for generator in (_partitions, _resampled, _envelopes):
        for candidate in generator(normalized, count, sign, check):
            check()
            if candidate is None or not np.all(np.isfinite(candidate)):
                continue
            # Several supporting sides can meet at the same sharp source tip.
            # Remove only numerically zero sides of this newly fitted polygon;
            # this is not a hierarchy of deletions from earlier slider values.
            candidate = _nonzero_sides(candidate)
            if len(candidate) < 4:
                continue
            shape = Polygon(candidate)
            if not _covers(shape, reference):
                continue
            candidate = _trim_excess(candidate, reference, check)
            compact = _nonzero_sides(candidate)
            if len(compact) < 4 or (
                len(compact) != len(candidate) and not _covers(Polygon(compact), reference)
            ):
                continue
            candidate = compact
            shape = Polygon(candidate)
            vectors = np.roll(candidate, -1, axis=0) - candidate
            lengths = np.linalg.norm(vectors, axis=1)
            if lengths.min() < 1e-10:
                continue
            following = np.roll(vectors, -1, axis=0)
            turns = sign * np.arctan2(
                vectors[:, 0] * following[:, 1] - vectors[:, 1] * following[:, 0],
                np.sum(vectors * following, axis=1),
            )
            absolute_turns = np.abs(turns)
            excess = float(distance(point_shapes(candidate), reference).max())
            # One continuous fidelity measure for every shape and budget. Deep
            # bays matter through their boundary error, not a gap-count trigger.
            boundary_error = float(distance(fidelity_points, shape.exterior).max())
            quality = (
                shape.area / reference.area
                + 4 * excess**2 / reference.area
                + 16 * boundary_error**2 / reference.area
                + 2 * np.mean((absolute_turns / absolute_turns.mean() - 1) ** 2)
                + 0.1 * np.mean((lengths / lengths.mean() - 1) ** 2)
            )
            if quality < score:
                best, score = candidate, quality
    if best is None:
        raise ContourComplexityError(FIT_FAILED)
    # Cyclic source intervals record provenance only. They do not determine the
    # output coordinates and cannot force corners to retain an earlier position.
    shift = int(np.linalg.norm(best - normalized[0], axis=1).argmin())
    best = np.roll(best, -shift, axis=0)
    result = tuple(map(tuple, (best @ basis.T + center) * extent + origin))
    if not _covers(Polygon(result), polygon):
        raise ContourComplexityError(FIT_FAILED)
    indices = tuple(np.linspace(0, len(points), len(result), endpoint=False).astype(int).tolist())
    return result, indices


def _nonzero_sides(candidate):
    lengths = np.linalg.norm(candidate - np.roll(candidate, 1, axis=0), axis=1)
    return candidate[lengths >= 1e-10]
