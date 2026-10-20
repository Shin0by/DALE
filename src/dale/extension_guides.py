"""Frozen, virtual supporting lines for rigid contour placement."""

import math

from shapely import STRtree
from shapely.geometry import LineString

from dale.editing import EPSILON
from dale.provenance import geometry_edges


def connected_targets(geometry, moving_ids):
    """Find current touching chains, respecting explicitly independent contours."""
    edges = geometry_edges(geometry.walls, geometry.closures)
    shapes = tuple(LineString(edge) for edge in edges)
    tree = STRtree(shapes)
    identifiers = {record.id: i for i, record in enumerate(geometry.lineage)}
    pending = [identifiers[key] for key in moving_ids if key in identifiers]
    seen = set(pending)
    while pending:
        index = pending.pop()
        for hit in tree.query(shapes[index].buffer(EPSILON)):
            hit = int(hit)
            if (
                hit not in seen
                and geometry.lineage[index].connection_group
                == geometry.lineage[hit].connection_group
                and shapes[index].distance(shapes[hit]) <= EPSILON
            ):
                seen.add(hit)
                pending.append(hit)
    return frozenset(geometry.lineage[i].id for i in seen)


class ExtensionGuides:
    """Project one anchor onto the nearest infinite stationary supporting line.

    Precompute unit normals once per gesture. The perpendicular capture distance
    does not limit how far a guide can extend beyond either segment endpoint.
    No geometry, connection or lineage is written by a guide.
    """

    def __init__(self, geometry, allowed_ids=None):
        self.lines = []
        for edge, record in zip(
            geometry_edges(geometry.walls, geometry.closures), geometry.lineage, strict=True
        ):
            if allowed_ids is not None and record.id not in allowed_ids:
                continue
            a, b = edge
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = math.hypot(dx, dy)
            if length > EPSILON:
                nx, ny = -dy / length, dx / length
                self.lines.append((edge, nx, ny, nx * a[0] + ny * a[1], record.id))

    def snap(self, point, tolerance):
        if tolerance <= 0:
            return point, None
        best = None
        for edge, nx, ny, offset, identifier in self.lines:
            distance = nx * point[0] + ny * point[1] - offset
            if abs(distance) <= tolerance:
                candidate = (abs(distance), min(math.dist(point, p) for p in edge), identifier)
                if best is None or candidate < best[0]:
                    best = candidate, (point[0] - distance * nx, point[1] - distance * ny), edge
        return (best[1], best[2]) if best else (point, None)
