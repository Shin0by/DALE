"""Dataset-local selection groups, independent of Qt and native scene JSON."""

import math
import re
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from itertools import pairwise
from uuid import uuid4

from shapely import STRtree
from shapely.geometry import LineString, box

from dale.provenance import EPSILON, geometry_edges

GROUP_SECTIONS = ("geometry", "figures", "regions", "pixels")


def group_ui_state(value):
    """Validate scoped metadata; existing unscoped groups belong to Regions."""
    groups = decode_groups(value.get("groups", []))
    identifiers = {g.id for g in groups}
    sections = value.get("group_sections", {})
    if not isinstance(sections, dict) or any(
        key not in identifiers or section not in GROUP_SECTIONS for key, section in sections.items()
    ):
        raise ValueError("Invalid selection group sections.")
    sections = {g.id: sections.get(g.id, "regions") for g in groups}
    active = value.get("active_group")
    if active is not None and (not isinstance(active, str) or active not in identifiers):
        raise ValueError("Invalid active selection group.")
    choices = value.get("section_active_groups", {})
    if not isinstance(choices, dict) or any(
        section not in GROUP_SECTIONS
        or (
            identifier is not None
            and (not isinstance(identifier, str) or sections.get(identifier) != section)
        )
        for section, identifier in choices.items()
    ):
        raise ValueError("Invalid section active selection groups.")
    choices = {
        section: choices.get(section, active if active and sections[active] == section else None)
        for section in GROUP_SECTIONS
    }
    return {
        "groups": [g.encode() for g in groups],
        "active_group": active,
        "group_sections": sections,
        "section_active_groups": choices,
    }


@dataclass(frozen=True)
class SelectionGroup:
    id: str
    name: str
    color: str
    lines: tuple[str, ...] = ()
    excluded: tuple[str, ...] = ()
    priority: int = 0
    cells: tuple | None = None

    @classmethod
    def create(cls, name, color="#e6b450"):
        return cls("group-" + uuid4().hex, name, color)

    def assign(self, identifiers, add=True):
        identifiers = set(identifiers)
        included, excluded = set(self.lines), set(self.excluded)
        if add:
            included.update(identifiers)
            excluded.difference_update(identifiers)
        else:
            included.difference_update(identifiers)
            excluded.update(identifiers)
        return replace(self, lines=tuple(sorted(included)), excluded=tuple(sorted(excluded)))

    def encode(self):
        value = asdict(self)
        value.update(lines=list(self.lines), excluded=list(self.excluded))
        if self.cells is None:
            value.pop("cells")
        else:
            value["cells"] = [cell.encode() for cell in self.cells]
        return value


def decode_groups(value):
    """Bound editor metadata even when its historical members are currently deleted."""
    if not isinstance(value, list) or len(value) > 256:
        raise ValueError("Invalid selection groups.")
    result, ids, count = [], set(), 0
    for item in value:
        if not isinstance(item, dict) or set(item) - {"cells"} != {
            "id",
            "name",
            "color",
            "lines",
            "excluded",
            "priority",
        }:
            raise ValueError("Invalid selection group fields.")
        identifier, name, color = (item[key] for key in ("id", "name", "color"))
        if (
            not isinstance(identifier, str)
            or not re.fullmatch(r"group-[0-9a-f]{32}", identifier)
            or identifier in ids
            or not isinstance(name, str)
            or not 1 <= len(name) <= 80
            or name != name.strip()
            or any(ord(c) < 32 for c in name)
            or not isinstance(color, str)
            or not re.fullmatch(r"#[0-9a-fA-F]{6}", color)
            or type(item["priority"]) is not int
            or not 0 <= item["priority"] <= 1_000_000_000
        ):
            raise ValueError("Invalid selection group identity, name or color.")
        for key in ("lines", "excluded"):
            members = item[key]
            if (
                not isinstance(members, list)
                or len(members) > 100_000
                or any(not isinstance(i, str) or not 1 <= len(i) <= 256 for i in members)
                or len(set(members)) != len(members)
            ):
                raise ValueError("Invalid selection group members.")
            count += len(members)
        from dale.region_groups import decode_cells

        cells = decode_cells(item["cells"]) if "cells" in item else None
        count += sum(len(r) for c in cells or () for r in (c.shell, *c.holes))
        if count > 100_000 or set(item["lines"]) & set(item["excluded"]):
            raise ValueError("Invalid or excessive selection group membership.")
        ids.add(identifier)
        result.append(
            SelectionGroup(
                identifier,
                name,
                color.lower(),
                tuple(item["lines"]),
                tuple(item["excluded"]),
                item["priority"],
                cells,
            )
        )
    return tuple(result)


def _member_flags(group, records, identifiers):
    memo = {i: True for i in group.lines}
    memo.update({i: False for i in group.excluded})
    for identifier in identifiers:
        stack, visiting = [(identifier, False)], set()
        while stack:
            identifier, finish = stack.pop()
            if identifier in memo:
                continue
            record = records.get(identifier)
            if not record or record.origin != "derived" or not record.parents:
                memo[identifier] = False
            elif finish:
                memo[identifier] = all(memo.get(p, False) for p in record.parents)
                visiting.discard(identifier)
            elif identifier in visiting:
                memo[identifier] = False
            else:
                visiting.add(identifier)
                stack.append((identifier, True))
                stack.extend((p, False) for p in record.parents if p not in memo)
    return memo


def group_members(group, geometry):
    """Exact IDs follow explicit derived lineage; manual contacts do not acquire groups."""
    return _group_members(group.lines, group.excluded, geometry.lineage, geometry.ancestry)


@lru_cache(maxsize=128)
def _group_members(lines, excluded, lineage, ancestry):
    records = {r.id: r for r in (*ancestry, *lineage)}
    memo = _member_flags(
        SelectionGroup("", "", "", lines, excluded), records, (r.id for r in lineage)
    )
    return frozenset(r.id for r in lineage if memo[r.id])


def assign_group(group, geometry, identifiers, add=True):
    """Only the explicit selection may add new live members through the + action."""
    identifiers = frozenset(identifiers)
    if not identifiers.issubset({r.id for r in geometry.lineage}):
        raise ValueError("The group selection is no longer current.")
    before = group_members(group, geometry)
    wanted = before | identifiers if add else before - identifiers
    result = group.assign(identifiers, add)
    # Historical descendants can already coexist elsewhere before this assignment.
    # Exclude only unintended additions; retain explicit prior members and split identity.
    unwanted = group_members(result, geometry) - wanted
    return result.assign(unwanted, False) if unwanted else result


class _LineIndex:
    """Compare positive collinear intervals without fragile thin polygon buffers."""

    def __init__(self, edges):
        self.edges = tuple(edges)
        self.tree = STRtree([LineString(edge) for edge in self.edges])
        self.coverage = {}

    def overlaps(self, edge):
        a, b = edge
        length = math.dist(a, b)
        if length == 0:
            return
        ux, uy = ((b[i] - a[i]) / length for i in (0, 1))
        bounds = box(
            min(a[0], b[0]) - EPSILON,
            min(a[1], b[1]) - EPSILON,
            max(a[0], b[0]) + EPSILON,
            max(a[1], b[1]) + EPSILON,
        )
        for index in self.tree.query(bounds):
            c, d = self.edges[int(index)]
            cx, cy = c[0] - a[0], c[1] - a[1]
            dx, dy = d[0] - c[0], d[1] - c[1]
            start, delta = cx * ux + cy * uy, dx * ux + dy * uy
            if delta == 0:
                continue
            lo, hi = max(0.0, min(start, start + delta)), min(length, max(start, start + delta))
            if hi <= lo:
                continue
            offset, change = ux * cy - uy * cx, ux * dy - uy * dx
            if max(abs(offset + (value - start) * change / delta) for value in (lo, hi)) <= EPSILON:
                yield int(index), lo, hi

    def covers(self, edge):
        if edge not in self.coverage:
            if len(self.coverage) >= 4096:
                self.coverage.clear()
            self.coverage[edge] = self._covers(edge)
        return self.coverage[edge]

    def _covers(self, edge):
        length, reached = math.dist(*edge), 0.0
        intervals = sorted((lo, hi) for _, lo, hi in self.overlaps(edge))
        if not intervals:
            return False
        for lo, hi in intervals:
            if lo > reached + EPSILON:
                return False
            reached = max(reached, hi)
            if reached >= length - EPSILON:
                return True
        return False


def _boundary_edges(polygons):
    return (
        edge
        for polygon in polygons
        for ring in (polygon.exterior, *polygon.interiors)
        for edge in pairwise(ring.coords)
        if edge[0] != edge[1]
    )


def boundary_members(geometry, polygons):
    """Assign only actual perimeter lines, excluding lines crossing a selected cell."""
    if not polygons:
        return frozenset()
    boundary = _LineIndex(_boundary_edges(polygons))
    return frozenset(
        record.id
        for edge, record in zip(
            geometry_edges(geometry.walls, geometry.closures), geometry.lineage, strict=True
        )
        if any(hi - lo > EPSILON for _, lo, hi in boundary.overlaps(edge))
    )


def grouped_regions(geometry, identifiers, polygons):
    """A polygonized cell belongs only when all of its perimeter is in the group."""
    lines = [
        e
        for e, r in zip(
            geometry_edges(geometry.walls, geometry.closures), geometry.lineage, strict=True
        )
        if r.id in identifiers
    ]
    if not lines:
        return ()
    boundary = _boundary_line_index(tuple(lines))
    return tuple(
        i
        for i, polygon in enumerate(polygons)
        if all(boundary.covers(edge) for edge in _boundary_edges((polygon,)))
    )


@lru_cache(maxsize=32)
def _boundary_line_index(lines):
    return _LineIndex(lines)


def matching_export_groups(geometry, groups, region_sets, active=None):
    """Match complete cell linework, retaining internal edges and disconnected parts."""
    edges = {
        record.id: edge
        for edge, record in zip(
            geometry_edges(geometry.walls, geometry.closures), geometry.lineage, strict=True
        )
    }
    ordered = sorted(
        enumerate(groups),
        key=lambda item: (item[1].id == active, item[1].priority, item[0]),
        reverse=True,
    )
    boundaries = []
    from dale.region_groups import matched_cells

    region_sets = tuple(tuple(regions) for regions in region_sets)
    all_regions = tuple(dict.fromkeys(p for regions in region_sets for p in regions))
    for _, group in ordered:
        lines = tuple(edges[i] for i in group_members(group, geometry))
        if lines:
            boundaries.append((group, lines, _LineIndex(lines)))
    selections = [tuple(_boundary_edges(regions)) for regions in region_sets]
    whole = tuple(edge for selection in selections for edge in selection)
    whole_index = _LineIndex(whole)

    def matches(lines, index, selection, selection_index):
        return (
            bool(selection)
            and all(index.covers(edge) for edge in selection)
            and all(selection_index.covers(edge) for edge in lines)
        )

    complete = {
        group.id for group, lines, index in boundaries if matches(lines, index, whole, whole_index)
    }
    result = []
    cell_members = {
        group.id: frozenset(all_regions[i] for i in matched_cells(group, geometry, all_regions))
        for _, group in ordered
        if group.cells is not None
    }
    for part, selection in enumerate(selections):
        selection_index = _LineIndex(selection)
        result.append(
            next(
                (
                    group
                    for group, lines, index in boundaries
                    if selection
                    and (
                        group.cells is None
                        or (
                            len(cell_members[group.id]) == len(group.cells)
                            and set(region_sets[part]).issubset(cell_members[group.id])
                        )
                    )
                    and (group.id in complete or matches(lines, index, selection, selection_index))
                ),
                None,
            )
        )
    return tuple(result)
