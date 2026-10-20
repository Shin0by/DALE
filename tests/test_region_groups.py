"""Region groups retain selected cells and holes through explicit boundary identities."""

import json
from itertools import pairwise

import pytest
from PIL import Image
from shapely.geometry import box

from dale.editing import hit_edge, insert_vertex, move_vertex
from dale.overlay_export import export_group_matches, export_overlays, overlay_region_plan
from dale.project_io import load_project, save_project
from dale.region_groups import assign_region_cells, matched_cells
from dale.selection_groups import SelectionGroup, decode_groups, group_members
from dale.session import Session


def nested_session(pair_factory):
    return Session(
        pair_factory(
            size=(240, 200),
            grid={"size": 20, "type": 1},
            walls=[
                {"c": [*a, *b]}
                for p in (box(20, 20, 220, 180), box(80, 60, 160, 140))
                for a, b in pairwise(p.exterior.coords)
            ],
        )
    )


def test_group_stores_ring_without_selecting_its_inner_cell(pair_factory, tmp_path):
    session = nested_session(pair_factory)
    cells = session.analysis().cells
    outer = next(p for p in cells if p.interiors)
    group = assign_region_cells(
        SelectionGroup.create("Courtyard"), session.geometry(), (outer,), cells
    )
    assert len(group.cells) == 1 and len(group.cells[0].holes) == 1
    assert matched_cells(group, session.geometry(), cells) == (cells.index(outer),)
    assert decode_groups([group.encode()]) == (group,)
    folder = export_overlays(
        session, tmp_path, selected_polygons=(outer,), merge_adjacent=True, export_groups=(group,)
    )
    manifest = json.loads(next(folder.glob("*-placement.json")).read_text())
    item = manifest["items"][0]
    assert item["file"].startswith("Courtyard-")
    with Image.open(folder / item["file"]) as image:
        assert image.getpixel((100 - item["x"], 100 - item["y"]))[3] == 0
        assert image.getpixel((40 - item["x"], 100 - item["y"]))[3] == 255


def test_excluding_cell_retains_common_boundary_and_can_be_added_back(pair_factory):
    session = nested_session(pair_factory)
    geometry, cells = session.geometry(), session.analysis().cells
    outer = next(p for p in cells if p.interiors)
    inner = next(p for p in cells if not p.interiors)
    group = assign_region_cells(SelectionGroup.create("Rooms"), geometry, cells, cells)
    before = group_members(group, geometry)
    excluded = assign_region_cells(group, geometry, (inner,), cells, False)
    assert group_members(excluded, geometry) == before
    assert matched_cells(excluded, geometry, cells) == (cells.index(outer),)
    plan = overlay_region_plan(session, selected_polygons=(outer,), merge_adjacent=True)
    assert export_group_matches(session, (excluded,), plan) == (excluded,)
    assert export_group_matches(session, (group,), plan) == (None,)
    restored = assign_region_cells(excluded, geometry, (inner,), cells)
    assert matched_cells(restored, geometry, cells) == tuple(range(len(cells)))
    assert session.geometry() == geometry and not session.operations


@pytest.mark.parametrize("edit", ["move", "split", "copy", "new-line", "delete"])
def test_cell_references_follow_changes_without_new_objects_acquiring_group(pair_factory, edit):
    from dale.editing import add_line, delete_vertex
    from dale.geometry import analyze_regions
    from dale.region_transform import copy_figures

    session = nested_session(pair_factory)
    geometry, cells = session.geometry(), session.analysis().cells
    inner = next(p for p in cells if not p.interiors)
    group = assign_region_cells(SelectionGroup.create("Inner"), geometry, (inner,), cells)
    if edit == "move":
        edited = move_vertex(geometry, (80, 60), (70, 55))
    elif edit == "split":
        edited = insert_vertex(geometry, hit_edge(geometry, (120, 60), 1))
    elif edit == "copy":
        edited = copy_figures(geometry, group.lines).paste(geometry, 300, 0)
    elif edit == "new-line":
        edited = add_line(geometry, (120, 60), (120, 140))
    else:
        edited = delete_vertex(geometry, (80, 60))
    current = analyze_regions(edited.walls, edited.closures).cells
    indices = matched_cells(group, edited, current)
    assert len(indices) == (0 if edit in ("new-line", "delete") else 1)
    assert all(current[i].centroid.x < 240 for i in indices)
    assert matched_cells(group, geometry, cells) == (cells.index(inner),)  # Undo restores IDs.


def test_region_group_archive_preserves_exact_cell_choice(pair_factory, tmp_path):
    from dale.datasets import DatasetCatalog

    session = nested_session(pair_factory)
    cells = session.analysis().cells
    outer = next(p for p in cells if p.interiors)
    group = assign_region_cells(SelectionGroup.create("Ring"), session.geometry(), (outer,), cells)
    catalog = DatasetCatalog(session, ui={"groups": [group.encode()]})
    path = tmp_path / "Ring.dale"
    save_project(session, path, catalog=catalog)
    with load_project(path) as loaded:
        saved = decode_groups(loaded.ui_state["groups"])[0]
        assert saved == group
        current = loaded.session.analysis().cells
        assert matched_cells(saved, loaded.session.geometry(), current) == (cells.index(outer),)


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        [None],
        [{"shell": [], "holes": []}],
        [{"shell": [True], "holes": []}],
        [{"shell": ["id"], "holes": [None]}],
        [{"shell": ["id", "id"], "holes": []}],
        [{"shell": ["id"], "holes": [], "extra": 1}],
    ],
)
def test_invalid_cell_metadata_is_rejected(value):
    encoded = SelectionGroup.create("Invalid").encode()
    encoded["cells"] = value
    with pytest.raises(ValueError):
        decode_groups([encoded])
