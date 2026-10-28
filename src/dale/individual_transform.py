"""Independent object pivots and strict dataset-local transform preferences."""

import math
from dataclasses import replace

from shapely import STRtree
from shapely.affinity import affine_transform
from shapely.geometry import LineString, shape

from dale.provenance import geometry_edges
from dale.raster_transform import affine_matrix
from dale.region_transform import contour_center

SECTIONS = ("figures", "alchemist", "regions", "pixels")


def settings(value=None):
    if value is None:
        return {}
    keys = {f"{section}_{kind}" for section in SECTIONS for kind in ("rotate", "scale")}
    if (
        not isinstance(value, dict)
        or set(value) - keys
        or any(type(enabled) is not bool for enabled in value.values())
    ):
        raise ValueError("Invalid individual transform settings.")
    return dict(value)


def tool_key(section, tool):
    if section not in SECTIONS:
        return None
    if tool.startswith("Rotate "):
        return f"{section}_rotate"
    if tool in ("Scale figures", "Scale raster regions", "Move figures", "Move regions"):
        return f"{section}_scale"
    return None


def raster_parts(value, count):
    if value is None:
        return ()
    if not isinstance(value, list) or not value or len(value) != count:
        raise ValueError("Invalid independent raster parts.")
    result = []
    for part in value:
        if not isinstance(part, dict) or set(part) != {"area", "matrix"}:
            raise ValueError("Invalid independent raster part.")
        area, matrix = shape(part["area"]), part["matrix"]
        if (
            area.geom_type not in ("Polygon", "MultiPolygon")
            or not area.is_valid
            or (
                not area.is_empty
                and not all(math.isfinite(v) and abs(v) <= 1e9 for v in area.bounds)
            )
            or not isinstance(matrix, list)
            or len(matrix) != 6
            or any(
                type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e9 for v in matrix
            )
        ):
            raise ValueError("Invalid independent raster geometry.")
        a, b, d, e, x, y = matrix
        if abs(a * e - b * d) < 1e-12 or (
            not area.is_empty
            and any(
                abs(a * px + b * py + x) > 1e9 or abs(d * px + e * py + y) > 1e9
                for px in (area.bounds[0], area.bounds[2])
                for py in (area.bounds[1], area.bounds[3])
            )
        ):
            raise ValueError("Invalid independent raster matrix.")
        result.append((area.wkb, tuple(matrix)))
    return tuple(result)


def transform_contours(plan, *, figures, scale=1, angle=0, centers=None):
    """Keep exact moving records; connected boundaries form one physical object."""
    geometry = plan.original if figures else plan.noded
    edges = geometry_edges(geometry.walls, geometry.closures)
    records = geometry.lineage
    parents = list(range(len(edges)))

    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i

    vertices = {}
    for i, (edge, record) in enumerate(zip(edges, records, strict=True)):
        if not figures and i < len(plan.fixed):
            continue
        for point in edge:
            key = point, record.connection_group
            if key in vertices:
                parents[root(i)] = root(vertices[key])
            else:
                vertices[key] = i
    # A region's hole outlines share its outer outline's pivot.
    polygon_indices = []
    moving_lines = (
        tuple(LineString(edge) for edge in edges[len(plan.fixed) :]) if not figures else ()
    )
    index = STRtree(moving_lines) if moving_lines else None
    for polygon in () if figures else plan.polygons:
        indices = (
            {
                int(i) + len(plan.fixed)
                for i in index.query(polygon.boundary, predicate="dwithin", distance=1e-7)
            }
            if index is not None
            else set()
        )
        if indices:
            first = min(indices)
            for i in indices:
                parents[root(i)] = root(first)
        polygon_indices.append(min(indices) if indices else None)
    groups = {}
    for i in range(len(edges)):
        groups.setdefault(root(i), []).append(i)
    selected = {r.id for r in plan.noded.lineage[len(plan.fixed) :]}
    result = list(edges)
    pivots, matrices = dict(centers or {}), {}
    for group, indices in groups.items():
        if not any(records[i].id in selected for i in indices):
            continue
        key = min(records[i].id for i in indices)
        pivot = pivots.setdefault(key, contour_center(tuple(edges[i] for i in indices)))
        matrix = matrices[group] = affine_matrix(pivot, scale=scale, angle=angle)
        a, b, d, e, x, y = matrix
        for i in indices:
            if records[i].id in selected:
                result[i] = tuple((a * px + b * py + x, d * px + e * py + y) for px, py in edges[i])
    polygons = (
        tuple(
            affine_transform(p, matrices[root(i)]) if i is not None else p
            for p, i in zip(plan.polygons, polygon_indices, strict=True)
        )
        if not figures
        else ()
    )
    return replace(geometry, walls=tuple(result), closures=(), raster=None), polygons, pivots
