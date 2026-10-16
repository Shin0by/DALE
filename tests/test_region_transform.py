import math
from itertools import pairwise

import pytest
from shapely.geometry import LineString, box

from dale.editing import add_line
from dale.geometry import analyze_regions
from dale.provenance import edge_key
from dale.region_transform import plan_region_transform
from dale.session import GeometryEdit


def adjacent_cells():
    cells = (box(20, 20, 120, 120), box(120, 20, 220, 120))
    edges = tuple(
        dict.fromkeys(edge_key(edge) for p in cells for edge in pairwise(p.exterior.coords))
    )
    geometry = add_line(GeometryEdit(edges), (70, 20), (70, 0))
    return geometry, cells


def test_only_selected_boundaries_move_while_neighbors_and_branches_stay():
    geometry, cells = adjacent_cells()
    plan = plan_region_transform(geometry, (cells[0],), cells)
    moved, selected = plan.apply(dx=-10, dy=5)
    edges = {edge_key(edge) for edge in moved.walls}
    assert edge_key(((70, 20), (70, 0))) in edges
    assert edge_key(((120, 20), (120, 120))) in edges  # Stationary shared wall.
    assert edge_key(((110, 25), (110, 125))) in edges  # Moved copy.
    assert selected[0].equals(box(10, 25, 110, 125))
    analysis = analyze_regions(moved.walls)
    assert any(p.equals(cells[1]) for p in analysis.cells)
    assert plan.apply()[0] is geometry


def test_related_lines_include_nearby_transitive_connections():
    geometry, cells = adjacent_cells()
    geometry = add_line(geometry, (225, 120), (245, 120))
    geometry = add_line(geometry, (250, 120), (270, 120))
    plan = plan_region_transform(geometry, (cells[0],), cells, True, 5)
    assert not plan.fixed
    moved, _ = plan.apply(dx=10)
    assert edge_key(((260, 120), (280, 120))) in {edge_key(e) for e in moved.walls}
    disconnected = plan_region_transform(geometry, (cells[0],), cells, True, 4)
    assert len(disconnected.fixed) == 2


def test_multi_selection_uses_one_stable_pivot_for_tenth_degree_rotation_and_scale():
    geometry, cells = adjacent_cells()
    plan = plan_region_transform(geometry, cells, cells)
    assert plan.pivot == (120, 70)
    rotated, polygons = plan.apply(angle=0.1)
    angle = math.radians(0.1)
    expected = (
        120 + 100 * math.cos(angle) - 50 * math.sin(angle),
        70 + 100 * math.sin(angle) + 50 * math.cos(angle),
    )
    assert any(math.dist(p, expected) < 1e-8 for e in rotated.walls for p in e)
    second = plan_region_transform(rotated, polygons, polygons, pivot=plan.pivot)
    scaled, _ = second.apply(scale=2)
    assert second.pivot == plan.pivot
    before = LineString(rotated.walls[-1]).length
    after = LineString(scaled.walls[-1]).length
    assert after == pytest.approx(before * 2)


@pytest.mark.parametrize("kwargs", [{"scale": 0}, {"scale": -1}, {"angle": float("nan")}])
def test_invalid_affine_parameters_are_rejected(kwargs):
    geometry, cells = adjacent_cells()
    with pytest.raises(ValueError, match="finite"):
        plan_region_transform(geometry, cells, cells).apply(**kwargs)
