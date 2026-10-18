import math
from itertools import pairwise

import pytest
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

from dale.editing import add_line
from dale.geometry import analyze_regions, contour_components, structural_regions
from dale.provenance import edge_key
from dale.region_transform import (
    copy_figures,
    copy_regions,
    delete_figures,
    delete_regions,
    plan_figure_transform,
    plan_region_transform,
)
from dale.session import GeometryEdit


def test_delete_exact_selected_ids_retains_coincident_crossing_and_unselected_neighbours():
    from dataclasses import replace

    from dale.wall_styles import geometry_styles

    geometry = GeometryEdit(
        (
            ((0, 0), (40, 0)),
            ((40, 0), (40, 30)),
            ((20, -10), (20, 40)),
            ((0, 0), (40, 0)),
            ((100, 0), (130, 0)),
        ),
        (((200, 0), (220, 0), (220, 20), (200, 0)),),
    )
    geometry = replace(
        geometry,
        lineage=tuple(
            replace(r, connection_group=f"group-{i}") for i, r in enumerate(geometry.lineage)
        ),
    )
    ids = tuple(r.id for r in geometry.lineage)
    deleted = {ids[0], ids[4], ids[-1]}
    result = delete_figures(geometry, deleted)
    from dale.provenance import geometry_edges

    expected = [
        (e, r)
        for e, r in zip(
            geometry_edges(geometry.walls, geometry.closures), geometry.lineage, strict=True
        )
        if r.id not in deleted
    ]
    assert list(zip(result.walls, result.lineage, strict=True)) == expected
    assert {r.id for r in result.ancestry}.issuperset(ids)
    assert geometry_styles(result) == geometry_styles(geometry)
    assert delete_figures(geometry, ()) is geometry
    assert not delete_figures(geometry, ids).walls
    with pytest.raises(ValueError, match="current contour line"):
        delete_figures(geometry, ("missing",))


def test_figure_components_and_exact_open_selection_do_not_node_or_expand():
    geometry = GeometryEdit(
        (
            ((0, 0), (40, 0)),
            ((40, 0), (40, 30)),
            ((20, -10), (20, 40)),
            ((100, 0), (130, 0)),
        )
    )
    ids = tuple(r.id for r in geometry.lineage)
    groups = contour_components(geometry.walls, ids)
    assert [g.line_ids for g in groups] == [ids[:2], ids[2:3], ids[3:]]
    selected = (ids[0], ids[3])
    plan = plan_figure_transform(geometry, selected)
    assert not plan.polygons and len(plan.moving) == len(plan.fixed) == 2
    transformed, _ = plan.apply(dx=5, dy=8, angle=30, scale=1.2)
    live = dict(zip((r.id for r in transformed.lineage), transformed.walls, strict=True))
    assert live[ids[1]] == geometry.walls[1] and live[ids[2]] == geometry.walls[2]
    assert set(live) == set(ids) and transformed.ancestry == geometry.ancestry
    copy = copy_figures(geometry, selected)
    assert not copy.polygons and len(copy.edges) == 2
    pasted = copy.paste(geometry, 0, 80)
    assert len(pasted.walls) == 6 and pasted.walls[:4] == geometry.walls
    with pytest.raises(ValueError, match="current contour line"):
        plan_figure_transform(geometry, ("missing",))


def test_crossing_and_nested_objects_keep_structural_loops_but_extraction_still_nodes():
    shapes = (
        box(40, 40, 360, 500),
        box(30, 30, 60, 60),
        box(150, 30, 170, 55),
        box(345, 30, 375, 60),
        box(20, 180, 55, 230),
        box(345, 190, 375, 240),
        box(30, 340, 50, 360),
        box(350, 340, 370, 360),
        box(30, 485, 60, 515),
        box(345, 485, 375, 515),
        box(90, 90, 130, 130),
    )
    edges = tuple(edge for p in shapes for edge in pairwise(p.exterior.coords))
    crossing = ((0, 300), (400, 320))
    geometry = GeometryEdit((*edges, crossing))
    objects = structural_regions(geometry.walls)
    assert len(objects) == len(shapes)
    assert all(any(p.equals(shape) for p in objects) for shape in shapes)
    big = next(p for p in objects if p.equals(shapes[0]))
    assert not big.interiors
    standard = analyze_regions(geometry.walls)
    assert len(standard.cells) > len(objects)
    assert standard.area.equals(unary_union(shapes))
    plan = plan_region_transform(geometry, (big,), objects)
    assert len(plan.moving) == 4 and len(plan.fixed) == len(edges) - 4 + 1
    moved, _ = plan.apply(dx=17, dy=-8)
    original_fixed = dict(
        zip((r.id for r in geometry.lineage[4:]), geometry.walls[4:], strict=True)
    )
    live = dict(zip((r.id for r in moved.lineage), moved.walls, strict=True))
    assert all(live[identifier] == edge for identifier, edge in original_fixed.items())
    clip = copy_regions(geometry, (big,), objects)
    assert len(clip.edges) == 4 and clip.polygons[0].equals(big)
    pasted = clip.paste(GeometryEdit(()), 500, 0)
    assert len(structural_regions(pasted.walls)) == 1


def test_real_shared_vertices_and_t_contacts_still_form_standard_connected_cells():
    geometry, cells = adjacent_cells()
    # Existing shared walls/vertices remain one connected graph with two cells.
    objects = structural_regions(geometry.walls)
    assert len(objects) == 2
    assert all(any(p.equals(cell) for p in objects) for cell in cells)
    outer = box(0, 0, 100, 100)
    edges = tuple(pairwise(outer.exterior.coords))
    # Endpoint-to-edge T contacts are real connections, unlike an unanchored crossing.
    divider = ((50, 0), (50, 100))
    divided = structural_regions((*edges, divider))
    assert len(divided) == 2 and all(p.area == 5000 for p in divided)
    crossed = structural_regions((*edges, ((50, -10), (50, 110))))
    assert len(crossed) == 1 and crossed[0].equals(outer)
    assert len(analyze_regions((*edges, ((50, -10), (50, 110)))).cells) == 2


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


def test_surrounding_lines_stay_fixed_even_with_old_related_preference():
    geometry, cells = adjacent_cells()
    geometry = add_line(geometry, (225, 120), (245, 120))
    geometry = add_line(geometry, (250, 120), (270, 120))
    plan = plan_region_transform(geometry, (cells[0],), cells, True, 9999)
    moved, selected = plan.apply(dx=10)
    edges = {edge_key(e) for e in moved.walls}
    assert edge_key(((225, 120), (245, 120))) in edges
    assert edge_key(((250, 120), (270, 120))) in edges
    assert selected[0].equals(box(30, 20, 130, 120))
    assert edge_key(((260, 120), (280, 120))) not in edges


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


def test_delete_region_only_boundary_holes_and_partial_edges_preserves_inside_and_branches():
    selected = Polygon(box(20, 20, 120, 120).exterior.coords, [box(45, 45, 65, 65).exterior.coords])
    # The bottom source edge extends past both corners and must retain both tails.
    boundary = [
        ((0, 20), (140, 20)),
        ((120, 20), (120, 120)),
        ((120, 120), (20, 120)),
        ((20, 120), (20, 20)),
        *pairwise(box(45, 45, 65, 65).exterior.coords),
    ]
    untouched = [
        ((30, 80), (100, 80)),
        ((20, 70), (50, 70)),
        ((50, 50), (60, 50)),
        ((160, 20), (160, 120)),
    ]
    original = GeometryEdit(tuple([*boundary, *untouched]))
    result = delete_regions(original, (selected,))
    assert {edge_key(e) for e in result.walls} == {
        edge_key(e) for e in [*untouched, ((0, 20), (20, 20)), ((120, 20), (140, 20))]
    }
    live = {r.id: e for r, e in zip(result.lineage, result.walls, strict=True)}
    for record, edge in zip(original.lineage[len(boundary) :], untouched, strict=True):
        assert live[record.id] == edge
    for edge, record in zip(result.walls, result.lineage, strict=True):
        if edge_key(edge) in {edge_key(((0, 20), (20, 20))), edge_key(((120, 20), (140, 20)))}:
            assert record.parents == (original.lineage[0].id,)


def test_delete_adjacent_selected_region_shared_boundary_and_multiple_figures():
    original, cells = adjacent_cells()
    result = delete_regions(original, (cells[0],))
    edges = {edge_key(e) for e in result.walls}
    assert edge_key(((120, 20), (120, 120))) not in edges
    assert edge_key(((70, 20), (70, 0))) in edges
    assert edge_key(((220, 20), (220, 120))) in edges
    result = delete_regions(original, cells)
    assert result.walls == (((70, 20), (70, 0)),)


def test_delete_pasted_region_uses_membership_and_keeps_coincident_surroundings():
    selected = box(20, 20, 120, 120)
    original = GeometryEdit(tuple(pairwise(selected.exterior.coords)))
    clip = copy_regions(original, (selected,), (selected,))
    target = GeometryEdit(tuple(pairwise(box(220, 20, 320, 120).exterior.coords)))
    # Properties differ from the source, so these fully coincident figures coexist.
    from dale.wall_styles import property_style

    target = GeometryEdit(
        target.walls,
        lineage=target.lineage,
        wall_styles=tuple((r.id, (property_style({"door": 1}),)) for r in target.lineage),
    )
    pasted = clip.paste(target, 200, 0)
    assert len(pasted.walls) == 8
    result = delete_regions(
        pasted, (box(220, 20, 320, 120),), selection_ids=tuple(r.id for r in pasted.lineage[4:])
    )
    assert result.walls == target.walls
    assert result.lineage == target.lineage


def test_delete_region_respects_height_scope_and_path_edge_lineage():
    selected = box(20, 20, 120, 120)
    edges = tuple(pairwise(selected.exterior.coords))
    from dale.provenance import LineRecord

    original = GeometryEdit(
        edges,
        (tuple(selected.exterior.coords),),
        lineage=tuple(LineRecord.child((), e, manual=True) for e in (*edges, *edges)),
    )
    ids = {r.id for r in original.lineage[4:]}
    result = delete_regions(original, (selected,), active_ids=ids)
    assert result.walls == edges and result.lineage == original.lineage[:4]
