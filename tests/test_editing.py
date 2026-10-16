from dale.editing import delete_vertex, hit_edge, insert_vertex, move_vertex, vertices
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
