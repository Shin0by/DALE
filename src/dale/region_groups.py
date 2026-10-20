"""Exact region-group cells identified by persistent boundary lines, never cell indices."""

from dataclasses import dataclass, replace
from functools import lru_cache
from itertools import pairwise

from dale.provenance import EPSILON, geometry_edges


@dataclass(frozen=True, order=True)
class RegionCell:
    shell: tuple[str, ...]
    holes: tuple[tuple[str, ...], ...] = ()

    def encode(self):
        return {"shell": list(self.shell), "holes": [list(ring) for ring in self.holes]}


def decode_cells(value):
    if not isinstance(value, list) or len(value) > 100_000:
        raise ValueError("Invalid group region cells.")
    result, count = [], 0
    for cell in value:
        if not isinstance(cell, dict) or set(cell) != {"shell", "holes"}:
            raise ValueError("Invalid group region cell fields.")
        holes = cell["holes"]
        if not isinstance(holes, list) or len(holes) > 100_000:
            raise ValueError("Invalid group region holes.")
        rings = []
        for ring in (cell["shell"], *holes):
            if (
                not isinstance(ring, list)
                or not 1 <= len(ring) <= 100_000
                or any(not isinstance(i, str) or not 1 <= len(i) <= 256 for i in ring)
                or len(set(ring)) != len(ring)
            ):
                raise ValueError("Invalid group region boundary references.")
            count += len(ring)
            if count > 100_000:
                raise ValueError("Excessive group region references.")
            rings.append(tuple(sorted(ring)))
        result.append(RegionCell(rings[0], tuple(sorted(rings[1:]))))
    if len(set(result)) != len(result):
        raise ValueError("Duplicate group region cells.")
    return tuple(result)


def cell_references(geometry, polygons):
    return _cell_references(
        geometry_edges(geometry.walls, geometry.closures),
        tuple(r.id for r in geometry.lineage),
        tuple(polygons),
    )


@lru_cache(maxsize=16)
def _cell_references(edges, identifiers, polygons):
    index = _geometry_index(edges)

    return tuple(
        RegionCell(
            _ring_ids(index, identifiers, tuple(p.exterior.coords)),
            tuple(sorted(_ring_ids(index, identifiers, tuple(r.coords)) for r in p.interiors)),
        )
        for p in polygons
    )


@lru_cache(maxsize=8)
def _geometry_index(edges):
    from dale.selection_groups import _LineIndex

    return _LineIndex(edges)


@lru_cache(maxsize=4096)
def _ring_ids(index, identifiers, coordinates):
    return tuple(
        sorted(
            {
                identifiers[i]
                for edge in pairwise(coordinates)
                for i, lo, hi in index.overlaps(edge)
                if hi - lo > EPSILON
            }
        )
    )


def matched_cells(group, geometry, polygons):
    """Resolve cells through exact IDs and explicit split ancestry, excluding copies."""
    from dale.selection_groups import group_members, grouped_regions

    if group.cells is None:
        return grouped_regions(geometry, group_members(group, geometry), polygons)
    references = cell_references(geometry, polygons)
    return _matched_cells(group.cells, geometry, geometry.lineage, geometry.ancestry, references)


@lru_cache(maxsize=16)
def _matched_cells(cells, geometry, lineage, ancestry, references):
    from dale.selection_groups import SelectionGroup, group_members

    exact = set(cells)
    live = {r.id for r in lineage}
    evolving = tuple(c for c in cells if any(i not in live for r in (c.shell, *c.holes) for i in r))
    expanded = {}

    def ring_matches(stored, current):
        if stored == current:
            return True
        if stored not in expanded:
            expanded[stored] = group_members(SelectionGroup("", "", "", stored), geometry)
        if not current or not set(current).issubset(expanded[stored]):
            return False
        # A split long line may have children outside this cell. Require each
        # original boundary identity to contribute, without borrowing coordinates.
        return all(
            set(current) & group_members(SelectionGroup("", "", "", (identifier,)), geometry)
            for identifier in stored
        )

    def matches(stored, current):
        if len(stored.holes) != len(current.holes) or not ring_matches(stored.shell, current.shell):
            return False
        remaining = list(current.holes)
        for ring in stored.holes:
            hit = next((i for i, r in enumerate(remaining) if ring_matches(ring, r)), None)
            if hit is None:
                return False
            remaining.pop(hit)
        return True

    return tuple(
        i
        for i, current in enumerate(references)
        if current in exact or any(matches(stored, current) for stored in evolving)
    )


def assign_region_cells(group, geometry, selected, available, add=True):
    from dale.selection_groups import group_members

    current = tuple(available[i] for i in matched_cells(group, geometry, available))
    cells = set(cell_references(geometry, current))
    selected_cells = set(cell_references(geometry, selected))
    cells = cells | selected_cells if add else cells - selected_cells
    if any(not c.shell or any(not h for h in c.holes) for c in cells):
        raise ValueError("The selected region boundary is no longer available.")
    members = {i for c in cells for r in (c.shell, *c.holes) for i in r}
    before = group_members(group, geometry)
    return replace(
        group,
        lines=tuple(sorted(members)),
        excluded=tuple(sorted((set(group.excluded) | before) - members)),
        cells=tuple(sorted(cells)),
    )
