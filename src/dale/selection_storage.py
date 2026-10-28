"""Compact complete contour selections without widening partial selections."""

import hashlib
import json

from dale.connections import groups
from dale.geometry import contour_components
from dale.provenance import geometry_edges


def components(session):
    geometry = session.geometry()
    return contour_components(
        geometry_edges(geometry.walls, geometry.closures),
        tuple(r.id for r in geometry.lineage),
        groups(geometry),
        simple_rings=True,
    )


def fingerprint(identifiers):
    return hashlib.sha256(
        json.dumps(sorted(identifiers), separators=(",", ":")).encode()
    ).hexdigest()


def pack_selection(settings, session):
    result = dict(settings)
    selected = set(settings.get("figure_lines", ()))
    if not selected:
        return result
    packed = []
    for component in components(session):
        identifiers = set(component.line_ids)
        if len(identifiers) >= 4 and identifiers.issubset(selected):
            packed.append((min(identifiers), len(identifiers), fingerprint(identifiers)))
            selected.difference_update(identifiers)
    if packed:
        result["figure_lines"] = sorted(selected)
        result["figure_components"] = packed
    return result


def unpack_selection(settings, session):
    if not isinstance(settings, dict) or "figure_components" not in settings:
        return settings
    packed = settings["figure_components"]
    partial = settings.get("figure_lines", [])
    if not isinstance(packed, list) or not isinstance(partial, list):
        raise ValueError("Invalid compact contour selection.")
    by_anchor = {min(c.line_ids): c.line_ids for c in components(session) if c.line_ids}
    expanded, seen = list(partial), set()
    for item in packed:
        if (
            not isinstance(item, list)
            or len(item) != 3
            or not isinstance(item[0], str)
            or type(item[1]) is not int
            or not isinstance(item[2], str)
            or item[0] in seen
        ):
            raise ValueError("Invalid compact contour selection.")
        anchor, count, digest = item
        identifiers = by_anchor.get(anchor, ())
        if not identifiers or len(identifiers) != count or fingerprint(identifiers) != digest:
            raise ValueError("Compact contour selection does not match geometry.")
        seen.add(anchor)
        expanded.extend(identifiers)
    return {**settings, "figure_lines": expanded}
