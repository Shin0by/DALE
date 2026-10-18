"""Explicit editing connections; extraction continues using the global geometric graph."""

from dataclasses import replace
from uuid import uuid4

from shapely import STRtree
from shapely.geometry import LineString, Point

from dale.editing import EPSILON, node_geometry
from dale.geometry import contour_components
from dale.provenance import geometry_edges


def groups(geometry):
    return tuple(record.connection_group for record in geometry.lineage)


def components(geometry):
    return contour_components(
        geometry_edges(geometry.walls, geometry.closures),
        tuple(record.id for record in geometry.lineage),
        groups(geometry),
    )


def regroup(geometry, identifiers, group):
    identifiers = set(identifiers)
    return replace(
        geometry,
        lineage=tuple(
            replace(record, connection_group=group) if record.id in identifiers else record
            for record in geometry.lineage
        ),
    )


def isolate(geometry, identifiers):
    return regroup(geometry, identifiers, "contour:" + uuid4().hex)


def join(geometry, identifiers, points):
    geometry = isolate(geometry, identifiers)
    return node_geometry(geometry, points)


def cut_contacts(original, edited):
    """Return new cut contacts, original-component survivors, and participating live IDs."""
    old_edges = geometry_edges(original.walls, original.closures)
    old = {record.id: edge for record, edge in zip(original.lineage, old_edges, strict=True)}
    membership = {
        identifier: frozenset(component.line_ids)
        for component in components(original)
        for identifier in component.line_ids
    }
    owners = {
        record.id: record.id
        if record.id in old
        else next((parent for parent in record.parents if parent in old), None)
        for record in edited.lineage
    }
    survivors = {}
    for identifier, owner in owners.items():
        if owner is not None:
            survivors.setdefault(membership[owner], set()).add(identifier)
    edges = geometry_edges(edited.walls, edited.closures)
    shapes = tuple(LineString(edge) for edge in edges)
    tree = STRtree(shapes)
    contacts, separate, participating = set(), {}, set()
    for edge, record in zip(edges, edited.lineage, strict=True):
        owner = owners[record.id]
        if owner is None or record.id in old:
            continue
        for point in edge:
            if point in old[owner]:
                continue
            shape = Point(point)
            for hit in tree.query(shape.buffer(EPSILON)):
                other = edited.lineage[int(hit)].id
                other_owner = owners[other]
                if (
                    other_owner is None
                    or membership[owner] == membership[other_owner]
                    or shapes[int(hit)].distance(shape) > EPSILON
                ):
                    continue
                contacts.add(point)
                separate[membership[owner]] = survivors[membership[owner]]
                participating.update(survivors[membership[owner]])
                participating.update(survivors[membership[other_owner]])
    return tuple(sorted(contacts)), tuple(separate.values()), participating


def point_contacts(geometry, moving_ids, point):
    moving_ids = set(moving_ids)
    hit = {
        record.id
        for record, edge in zip(
            geometry.lineage, geometry_edges(geometry.walls, geometry.closures), strict=True
        )
        if record.id not in moving_ids and LineString(edge).distance(Point(point)) <= EPSILON
    }
    return {
        identifier
        for component in components(geometry)
        if hit.intersection(component.line_ids)
        for identifier in component.line_ids
    }
