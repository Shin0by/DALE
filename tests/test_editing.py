import math

import pytest

from dale.editing import (
    LineEraser,
    add_circle,
    add_line,
    align_orthogonal_point,
    alignment_points,
    circle_points,
    delete_vertex,
    erase_geometry,
    geometry_targets,
    hit_edge,
    insert_vertex,
    move_vertex,
    right_angle_point,
    snap_point,
    vertices,
)
from dale.geometry import open_contour_count
from dale.session import Closure, GeometryEdit, Session


def test_alignment_uses_both_neighbours_and_farther_points_in_same_contour():
    geometry = GeometryEdit(
        (
            ((40, 40), (140, 120)),
            ((140, 120), (160, 160)),
            ((160, 160), (210, 40)),
            ((158, 43), (158, 90)),
        )
    )
    anchors = alignment_points(geometry, (140, 120))
    assert set(anchors) == {(40, 40), (160, 160), (210, 40)}
    destination, guides = align_orthogonal_point((157, 43), anchors, 4)
    assert destination == (160, 40)
    assert set(guides) == {(0, (160, 160)), (1, (40, 40))}
    assert align_orthogonal_point((208, 80), anchors, 4)[0] == (210, 80)


def test_alignment_without_nearby_anchors_is_free():
    assert align_orthogonal_point((170, 140), (), 4) == ((170, 140), ())


@pytest.mark.parametrize("rotation", [0, 27, 81])
def test_right_angle_is_relative_to_adjacent_segments_not_map(rotation):
    def rotated(p):
        angle = math.radians(rotation)
        return (
            p[0] * math.cos(angle) - p[1] * math.sin(angle),
            p[0] * math.sin(angle) + p[1] * math.cos(angle),
        )

    a, vertex, b, cursor = map(rotated, ((40, 40), (140, 120), (160, 160), (157, 43)))
    geometry = GeometryEdit(((a, vertex), (vertex, b)))
    target, joint = right_angle_point(cursor, cursor, vertex, (a, b), geometry, 5)
    assert joint is not None and math.dist(cursor, target) <= 5
    assert sum((a[i] - target[i]) * (b[i] - target[i]) for i in (0, 1)) == pytest.approx(
        0, abs=1e-8
    )
    assert right_angle_point(cursor, cursor, vertex, (a, b), geometry, 1) == (cursor, None)


def test_terminal_right_angle_follows_stationary_adjacent_line():
    geometry = GeometryEdit((((0, 0), (20, 20)), ((20, 20), (39, 2))))
    target, joint = right_angle_point((39, 2), (39, 2), (39, 2), ((20, 20),), geometry, 2)
    assert target == pytest.approx((38.5, 1.5)) and joint is not None


def test_alignment_can_follow_t_contacts_but_not_disjoint_height_contacts():
    geometry = GeometryEdit((((0, 0), (20, 0)), ((10, 0), (10, 20)), ((10, 20), (40, 25))))
    assert (40, 25) in alignment_points(geometry, (0, 0))
    assert set(alignment_points(geometry, (0, 0), ((0, 10), (10, 20), (10, 20)))) == {(20, 0)}
    assert (40, 25) in alignment_points(geometry, (0, 0), ((0, 20), (10, 20), (10, 20)))


@pytest.mark.parametrize(
    "diameter,count",
    [
        (0.1, 4),
        (0.5, 4),
        (0.51, 6),
        (1, 6),
        (1.01, 8),
        (2, 8),
        (2.01, 10),
        (4.5, 10),
        (5, 12),
        (10, 16),
        (15, 20),
        (20, 24),
        (100, 88),
    ],
)
def test_circular_contour_vertex_density_uses_map_cells(diameter, count):
    radius = diameter * 150
    points = circle_points((100, 200), radius, 300)
    assert len(points) == count + 1 and points[0] == points[-1]
    assert len(set(points[:-1])) == count
    assert all(math.dist(p, (100, 200)) == pytest.approx(radius) for p in points)
    assert circle_points((100, 200), radius, 300) == points


@pytest.mark.parametrize(
    "radius,cell",
    [(0, 100), (-1, 100), (float("nan"), 100), (10, 0), (True, 100), (10, float("inf"))],
)
def test_circular_contour_rejects_invalid_dimensions(radius, cell):
    with pytest.raises(ValueError, match="Circle"):
        circle_points((0, 0), radius, cell)


def test_circle_contact_keeps_source_parents_and_is_one_undoable_geometry(pair_factory):
    source = pair_factory(size=(400, 400), walls=[{"c": [0, 0, 200, 0]}], grid={"size": 200})
    before = source.json_path.read_bytes()
    session = Session(source)
    original = session.geometry()
    circle = add_circle(original, (100, 50), 50, source.cell_pixels)
    assert len(circle.walls) == 6  # Four polygon edges and two pieces of the source wall.
    assert all(record.parents == (original.lineage[0].id,) for record in circle.lineage[:2])
    contacting = [record for record in circle.lineage[2:] if record.sources]
    assert len(contacting) == 2
    assert all(record.sources == original.lineage[0].sources for record in contacting)
    assert add_circle(circle, (100, 50), 50, 200) == circle
    session.add(circle)
    assert session.analysis().faces == 1
    session.undo()
    assert session.geometry() == original
    session.redo()
    assert session.geometry().lineage == circle.lineage
    assert source.json_path.read_bytes() == before


@pytest.mark.parametrize(
    "grid,expected",
    [(300, 300), ({"size": 300}, 300), (None, 100), ({"size": 0}, 100), ({"size": True}, 100)],
)
def test_circle_uses_imported_grid_or_explicit_pixel_fallback(pair_factory, grid, expected):
    assert pair_factory(grid=grid).cell_pixels == expected


def test_circle_density_scales_with_source_grid_and_has_a_safe_vertex_cap(pair_factory):
    source = pair_factory(size=(200, 200), width=400, height=400, grid={"size": 100})
    assert source.cell_pixels == 50
    assert len(circle_points((100, 100), 12.5, source.cell_pixels)) == 5
    assert len(circle_points((0, 0), 16000, 1)) == 4097
    assert len(circle_points((0, 0), 16000, 1e-300)) == 4097


def test_insert_drag_and_remove_wall_vertex_preserves_its_neighbors():
    geometry = GeometryEdit((((0, 0), (100, 0)),))
    inserted = insert_vertex(geometry, hit_edge(geometry, (40, 2), 5))
    assert inserted.walls == (((0, 0), (40, 0)), ((40, 0), (100, 0)))
    moved = move_vertex(inserted, (40, 0), (40, 30))
    assert moved.walls == (((0, 0), (40, 30)), ((40, 30), (100, 0)))
    assert delete_vertex(moved, (40, 30)).walls == geometry.walls
    assert geometry.walls == (((0, 0), (100, 0)),)


def test_point_editing_also_handles_temporary_polylines():
    geometry = GeometryEdit((), (((0, 0), (100, 0), (100, 100)),))
    hit = hit_edge(geometry, (30, 1), 5)
    inserted = insert_vertex(geometry, hit)
    assert inserted.closures[0] == ((0, 0), (30, 0), (100, 0), (100, 100))
    moved = move_vertex(inserted, (30, 0), (30, 20))
    assert moved.closures[0][1] == (30, 20)
    assert delete_vertex(moved, (30, 20)).closures == geometry.closures


def test_dragging_t_node_splits_and_moves_the_long_wall_too():
    geometry = GeometryEdit((((0, 0), (100, 0)), ((50, 0), (50, 80))))
    moved = move_vertex(geometry, (50, 0), (55, 10))
    assert moved.walls == (((0, 0), (55, 10)), ((55, 10), (100, 0)), ((55, 10), (50, 80)))


@pytest.mark.parametrize("extra_edges", [(), (((50, 0), (50, -80)),)])
def test_removing_branch_vertex_does_not_choose_a_main_wall(extra_edges):
    untouched = ((200, 0), (300, 0))
    geometry = GeometryEdit((((0, 0), (100, 0)), ((50, 0), (50, 80)), untouched) + extra_edges)
    assert delete_vertex(geometry, (50, 0)).walls == (untouched,)
    erased = erase_geometry(geometry, (50, 0), (50, 0), 4, "vertices")
    assert erased.walls == (untouched,)


def test_geometry_edit_history_is_undoable_and_never_writes_source_json(pair_factory):
    source = pair_factory()
    before = source.json_path.read_bytes()
    session = Session(source)
    session.add(Closure(((10, 20), (30, 40), (60, 20))))
    original = session.geometry()
    session.add(move_vertex(original, (30, 40), (35, 45)))
    assert (35, 45) in vertices(session.geometry())
    session.undo()
    assert session.geometry() == original
    session.redo()
    assert (35, 45) in vertices(session.geometry())
    assert source.json_path.read_bytes() == before


def test_snapping_prioritizes_vertices_over_closer_lines_and_ignores_dragged_edges():
    geometry = GeometryEdit((((0, 0), (100, 0)), ((50, 8), (50, 50))))
    assert snap_point(geometry, (50, 1), 10) == (50, 8)
    assert snap_point(geometry, (25, 1), 10) == (25, 0)
    assert snap_point(geometry, (25, 1), 0) is None
    assert snap_point(geometry, (1, 1), 10, exclude=(0, 0)) is None


def test_new_line_can_connect_two_segment_interiors_without_mutating_the_original():
    geometry = GeometryEdit((((0, 0), (100, 0)), ((0, 100), (100, 100))))
    edited = add_line(geometry, (40, 0), (40, 100))
    assert len(edited.walls) == 5
    assert ((40, 0), (40, 100)) in edited.walls
    assert len(geometry.walls) == 2
    assert add_line(edited, (40, 0), (40, 100)) == edited


def test_line_eraser_sweeps_fast_drags_and_splits_closure_paths():
    geometry = GeometryEdit(
        (((10, 0), (10, 100)), ((80, 0), (80, 100)), ((200, 0), (200, 100))),
        (((20, 20), (20, 80), (60, 80), (60, 20)),),
    )
    edited = erase_geometry(geometry, (0, 50), (100, 50), 2, "lines")
    assert edited.walls == (((200, 0), (200, 100)),)
    assert edited.closures == (((20, 80), (60, 80)),)
    assert geometry.closures[0][0] == (20, 20)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("crossing", [((30, -20), (30, 20)), ((30, 0), (60, 30))])
def test_line_eraser_stops_at_crossings_and_t_contacts_without_splitting_other_edges(
    reverse, crossing
):
    edge = ((0, 0), (100, 0))
    if reverse:
        edge = edge[::-1]
    untouched = ((0, 80), (100, 80))
    geometry = GeometryEdit((edge, crossing, untouched))
    expected = ((100, 0), (30, 0)) if reverse else ((30, 0), (100, 0))
    assert geometry_targets(geometry, (80, 0), (80, 0), 3, "lines") == (expected,)
    edited = erase_geometry(geometry, (80, 0), (80, 0), 3, "lines")
    retained = ((30, 0), (0, 0)) if reverse else ((0, 0), (30, 0))
    assert edited.walls == (retained, crossing, untouched)
    assert edited.lineage[1:] == geometry.lineage[1:]
    assert edited.lineage[0].parents == (geometry.lineage[0].id,)
    assert not geometry_targets(geometry, (200, 200), (200, 200), 1, "lines")
    assert erase_geometry(geometry, (200, 200), (200, 200), 1, "lines") is geometry


def test_line_eraser_removes_middle_between_multiple_intersections_and_coalesces_survivors():
    crossing = (((30, -20), (30, 20)), ((70, -20), (70, 20)))
    geometry = GeometryEdit((((0, 0), (100, 0)), *crossing))
    edited = erase_geometry(geometry, (50, 0), (50, 0), 2, "lines")
    assert edited.walls == (((0, 0), (30, 0)), ((70, 0), (100, 0)), *crossing)
    assert edited.lineage[2:] == geometry.lineage[1:]
    assert all(r.parents == (geometry.lineage[0].id,) for r in edited.lineage[:2])
    # Collinear overlap boundaries count, but unused cuts never become extra edges.
    overlap = GeometryEdit((((0, 0), (100, 0)), ((30, 0), (70, 0))))
    tail = erase_geometry(overlap, (85, 0), (85, 0), 2, "lines")
    assert tail.walls == (((0, 0), (70, 0)), overlap.walls[1])
    middle = erase_geometry(overlap, (50, 0), (50, 0), 2, "lines")
    assert middle.walls == (((0, 0), (30, 0)), ((70, 0), (100, 0)))


def test_line_eraser_closure_uses_the_same_partition_and_explicit_source_parent():
    path = ((0, 0), (100, 0), (100, 80), (0, 80))
    crossing = ((30, -20), (30, 100))
    geometry = GeometryEdit((crossing,), (path,))
    edited = erase_geometry(geometry, (70, 0), (70, 0), 2, "lines")
    assert edited.walls == (crossing,)
    assert edited.closures == (((0, 0), (30, 0)), ((100, 0), (100, 80), (0, 80)))
    assert edited.lineage[0] == geometry.lineage[0]
    assert edited.lineage[1].parents == (geometry.lineage[1].id,)
    assert edited.lineage[2:] == geometry.lineage[2:]


def test_line_eraser_stroke_keeps_deleted_intersection_as_a_frozen_boundary():
    geometry = GeometryEdit((((20, 100), (180, 100)), ((80, 20), (80, 100))))
    index = LineEraser(geometry)
    hits = set(index.targets((80, 40), (80, 40), 2))
    assert index.erase(hits).walls == (geometry.walls[0],)
    hits.update(index.targets((80, 40), (140, 100), 2))
    assert index.erase(hits).walls == (((20, 100), (80, 100)),)


def test_vertex_eraser_keeps_unselected_neighbors_and_open_count_uses_connected_groups():
    geometry = GeometryEdit((((0, 0), (50, 20)), ((50, 20), (100, 0))))
    edited = erase_geometry(geometry, (50, 20), (50, 20), 4, "vertices")
    assert edited.walls == (((0, 0), (100, 0)),)
    assert open_contour_count((((0, 0), (20, 0)), ((10, 0), (10, 20)), ((100, 0), (110, 0)))) == 2
