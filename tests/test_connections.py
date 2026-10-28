"""Synthetic editing independence does not alter geometric extraction or native data."""

from itertools import pairwise

from shapely.geometry import box

from dale.connections import components, cut_contacts, groups, isolate, join
from dale.editing import erase_geometry, move_vertex
from dale.geometry import analyze_regions
from dale.project_io import load_project, save_project
from dale.scene import load_pair
from dale.session import GeometryEdit, Session


def test_cut_contact_yes_nodes_target_no_preserves_independent_coincident_endpoint():
    original = GeometryEdit(
        (
            ((40, 50), (300, 50)),
            ((40, 240), (300, 240)),
            ((40, 50), (40, 240)),
            ((120, 10), (120, 300)),
        )
    )
    edited = erase_geometry(original, (250, 50), (250, 50), 3, "lines")
    points, independent, participants = cut_contacts(original, edited)
    assert points == ((120, 50),) and len(independent) == 1
    separate = isolate(edited, independent[0])
    connected = join(edited, participants, points)
    assert len(components(separate)) == 2 and len(components(connected)) == 1
    assert len(separate.walls) == 4 and len(connected.walls) == 5
    assert analyze_regions(separate.walls).area.equals(analyze_regions(connected.walls).area)
    assert separate.lineage[3].id == original.lineage[3].id
    assert all(r.parents == (original.lineage[3].id,) for r in connected.lineage[3:])


def test_independent_point_move_archive_redo_and_global_cells(pair_factory, tmp_path):
    shapes = (box(20, 20, 80, 80), box(140, 20, 200, 80))
    source = pair_factory(
        size=(240, 240),
        walls=[{"c": [*a, *b]} for shape in shapes for a, b in pairwise(shape.exterior.coords)],
    )
    session = Session(load_pair(source.image_path, source.json_path))
    original = session.geometry()
    selected = tuple(r.id for r in original.lineage[:4])
    moved = move_vertex(original, (80, 20), (140, 20), connect=False)
    separate = isolate(moved, selected)
    assert len(components(separate)) == 2
    connected = join(separate, tuple(r.id for r in separate.lineage), ((140, 20),))
    assert len(components(connected)) == 1
    assert analyze_regions(separate.walls).area.equals(analyze_regions(connected.walls).area)
    group = separate.lineage[0].connection_group
    again = move_vertex(separate, (140, 20), (120, 40), connect=False, connection_group=group)
    assert again.walls[4:] == original.walls[4:]
    assert again.lineage[4:] == original.lineage[4:]
    session.add(separate)
    session.add(connected)
    session.undo()
    archive = tmp_path / "independent-vertices.dale"
    save_project(session, archive)
    with load_project(archive) as loaded:
        assert groups(loaded.session.geometry()) == groups(separate)
        assert len(components(loaded.session.geometry())) == 2
        loaded.session.redo()
        assert len(components(loaded.session.geometry())) == 2
        assert not loaded.session.future
        loaded.session.undo()
        assert len(components(loaded.session.geometry())) == 2
    session.redo()
    assert len(components(session.geometry())) == 1
