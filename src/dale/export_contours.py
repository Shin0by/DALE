"""Remove selected groups' interior lines from an immutable export-only snapshot."""

from dataclasses import replace

import numpy as np
from shapely import STRtree, get_parts, linestrings, union_all

from dale.provenance import LineRecord, geometry_edges
from dale.raster import ExportCancelled
from dale.session import GeometryEdit
from dale.wall_styles import geometry_styles


def merge_selected_perimeters(session, groups, cancelled=None):
    areas = [union_all(group) for group in groups if len(group) > 1]
    if not areas:
        return session
    area = union_all(areas)
    boundary = area.boundary
    geometry = session.geometry()
    edges = geometry_edges(geometry.walls, geometry.closures)
    if not edges:
        return session
    shapes = linestrings(np.asarray(edges))
    candidates = set(map(int, STRtree(shapes).query(area, predicate="intersects")))
    walls, records = [], []
    styles = dict(geometry.wall_styles)
    resolved = geometry_styles(geometry)
    changed = False
    for index, (edge, record) in enumerate(zip(edges, geometry.lineage, strict=True)):
        if index % 256 == 0 and cancelled and cancelled():
            raise ExportCancelled("Separate PNG export cancelled.")
        if index not in candidates:
            walls.append(edge)
            records.append(record)
            continue
        line = shapes[index]
        kept = union_all((line.difference(area), line.intersection(boundary)))
        if kept.equals(line):
            walls.append(edge)
            records.append(record)
            continue
        changed = True
        for part in get_parts(kept):
            if part.geom_type != "LineString" or not part.length:
                continue
            points = tuple(part.coords)
            for a, b in zip(points, points[1:], strict=False):
                child = LineRecord.child((record,), (a, b))
                walls.append((a, b))
                records.append(child)
                if record.id in resolved:
                    styles[child.id] = resolved[record.id]
    if not changed:
        return session
    live = {record.id for record in records}
    ancestry = {
        record.id: record
        for record in (*geometry.ancestry, *geometry.lineage)
        if record.id not in live
    }
    result = GeometryEdit(
        tuple(walls),
        lineage=tuple(records),
        ancestry=tuple(ancestry.values()),
        wall_styles=tuple(styles.items()),
    )
    return replace(session, operations=[*session.operations, result], future=[])
