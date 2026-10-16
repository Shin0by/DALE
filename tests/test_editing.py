from dale.editing import (
    add_line,
    delete_vertex,
    erase_geometry,
    hit_edge,
    insert_vertex,
    move_vertex,
    snap_point,
    vertices,
)
from dale.geometry import open_contour_count
from dale.session import Closure, GeometryEdit, Session


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


def test_both_junction_deletion_policies_are_explicit():
    geometry = GeometryEdit((((0, 0), (100, 0)), ((50, 0), (50, 80))))
    assert delete_vertex(geometry, (50, 0), "continue").walls == (((0, 0), (100, 0)),)
    assert not delete_vertex(geometry, (50, 0), "remove").walls


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


def test_vertex_eraser_keeps_unselected_neighbors_and_open_count_uses_connected_groups():
    geometry = GeometryEdit((((0, 0), (50, 20)), ((50, 20), (100, 0))))
    edited = erase_geometry(geometry, (50, 20), (50, 20), 4, "vertices")
    assert edited.walls == (((0, 0), (100, 0)),)
    assert open_contour_count((((0, 0), (20, 0)), ((10, 0), (10, 20)), ((100, 0), (110, 0)))) == 2
