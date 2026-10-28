"""Full wall edits preserve all unrelated native Scene bytes and wall properties."""

import json
from itertools import pairwise

import pytest
from shapely.geometry import box

from dale.editing import add_line, erase_geometry, hit_edge, insert_vertex, move_vertex
from dale.json_repair import JsonCoordinateDocument, repaired_json_bytes
from dale.project_io import load_project, save_project
from dale.region_transform import plan_region_transform
from dale.scene import load_pair
from dale.session import Session


@pytest.fixture
def native(tmp_path):
    wall = {
        "_id": "OriginalWall0001",
        "c": [20, 20, 120, 20],
        "door": 1,
        "ds": 2,
        "dir": 1,
        "move": 20,
        "sight": 10,
        "light": 0,
        "sound": 20,
        "threshold": {"sight": 12.75},
        "flags": {"wall-height": {"bottom": 0, "top": 10}, "unknown": {"keep": [None, 3]}},
    }
    data = {
        "_id": "OriginalScene001",
        "name": "Native scene",
        "width": 400,
        "height": 400,
        "background": {"src": "assets/original.webp"},
        "walls": [wall],
        "lights": [{"_id": "light", "config": {"color": "#ff3300", "dim": 7.5}}],
        "tiles": [{"texture": {"src": "assets/floor.png"}, "elevation": 9.99}],
        "regions": [
            {
                "name": "Original portal",
                "behaviors": [{"system": {"destination": "Scene.A.Region.B"}}],
            }
        ],
        "tokens": [{"actorId": "Actor001", "elevation": 20}],
        "flags": {"module": {"unknown": [False, None, "value"]}},
    }
    path = tmp_path / "native.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=3) + "\n", encoding="utf-8")
    return Session(load_pair(None, path))


def assert_scene_preserved(session):
    payload, _ = repaired_json_bytes(session)
    original = JsonCoordinateDocument(session.source.json_bytes)
    updated = JsonCoordinateDocument(payload)
    assert updated.text[: updated.walls_start] == original.text[: original.walls_start]
    assert updated.text[updated.walls_end + 1 :] == original.text[original.walls_end + 1 :]
    assert session.source.json_path.read_bytes() == session.source.json_bytes
    return updated.raw


def test_split_move_delete_add_and_archive_preserve_scene_and_wall_settings(native, tmp_path):
    initial = native.source.raw["walls"][0]
    geometry = native.geometry()
    geometry = insert_vertex(geometry, hit_edge(geometry, (60, 20), 1))
    geometry = move_vertex(geometry, (60, 20), (60, 45))
    native.add(geometry)
    exported = assert_scene_preserved(native)
    assert len(exported["walls"]) == 2
    expected = {k: v for k, v in initial.items() if k not in ("_id", "c")}
    for wall in exported["walls"]:
        assert {k: v for k, v in wall.items() if k not in ("_id", "c")} == expected
    assert len({w["_id"] for w in exported["walls"]}) == 2
    assert initial["_id"] in {w["_id"] for w in exported["walls"]}
    native.add(erase_geometry(native.geometry(), (40, 32.5), (40, 32.5), 3, "lines"))
    native.add(add_line(native.geometry(), (250, 250), (300, 300)))
    exported = assert_scene_preserved(native)
    assert len(exported["walls"]) == 2
    manual = next(w for w in exported["walls"] if w["c"] == [250, 250, 300, 300])
    assert manual["door"] == 0 and manual["move"] == manual["light"] == 20
    path = tmp_path / "edited.dale"
    save_project(native, path)
    with load_project(path) as loaded:
        assert repaired_json_bytes(loaded.session)[0] == repaired_json_bytes(native)[0]
        loaded.session.undo()
        assert len(assert_scene_preserved(loaded.session)["walls"]) == 2
        assert not loaded.session.future
        loaded.session.redo()
        assert repaired_json_bytes(loaded.session)[0] == repaired_json_bytes(native)[0]


def test_delete_every_wall_preserves_lights_tiles_regions_and_unknown_data(native):
    native.add(erase_geometry(native.geometry(), (20, 20), (120, 20), 10, "lines"))
    assert assert_scene_preserved(native)["walls"] == []
    native.undo()
    assert repaired_json_bytes(native)[0] == native.source.json_bytes


def test_erase_middle_at_intersections_preserves_each_wall_property_owner_and_redo(
    native, tmp_path
):
    raw = native.source.raw.copy()
    raw["walls"] = [
        raw["walls"][0],
        *[
            {**raw["walls"][0], "_id": f"CrossingWall000{i}", "c": [x, 0, x, 40], "door": 0}
            for i, x in enumerate((50, 90))
        ],
    ]
    path = tmp_path / "crossing.json"
    path.write_text(json.dumps(raw, indent=3), encoding="utf-8")
    session = Session(load_pair(None, path))
    initial = session.geometry()
    session.add(erase_geometry(initial, (70, 20), (70, 20), 2, "lines"))
    data = assert_scene_preserved(session)
    fragments = [w for w in data["walls"] if w["door"] == 1]
    assert sorted(w["c"] for w in fragments) == [[20, 20, 50, 20], [90, 20, 120, 20]]
    expected = {k: v for k, v in raw["walls"][0].items() if k not in ("c", "_id")}
    assert all({k: v for k, v in w.items() if k not in ("c", "_id")} == expected for w in fragments)
    for wall in raw["walls"][1:]:
        assert next(w for w in data["walls"] if w["_id"] == wall["_id"]) == wall
    assert len({w["_id"] for w in data["walls"]}) == 4
    payload = repaired_json_bytes(session)[0]
    edited = session.geometry()
    assert all(r.parents == (initial.lineage[0].id,) for r in edited.lineage[:2])
    session.undo()
    session.redo()
    assert repaired_json_bytes(session)[0] == payload
    archive = tmp_path / "eraser-redo.dale"
    save_project(session, archive)
    with load_project(archive) as loaded:
        assert loaded.session.geometry().lineage == edited.lineage
        loaded.session.redo()
        assert repaired_json_bytes(loaded.session)[0] == payload
        assert loaded.session.geometry().lineage == edited.lineage


def test_region_transform_preserves_directed_wall_settings_and_native_data(native):
    raw = native.source.raw.copy()
    raw["walls"] = [
        {**raw["walls"][0], "_id": f"OriginalWall000{i}", "c": [*a, *b]}
        for i, (a, b) in enumerate(pairwise(box(20, 20, 120, 120).exterior.coords))
    ]
    from dale.scene import scene_from_json

    session = Session(scene_from_json(json.dumps(raw).encode()))
    selected = session.analysis().cells
    plan = plan_region_transform(session.geometry(), selected, selected)
    geometry, _ = plan.apply(dx=120, dy=30, angle=20)
    session.add(geometry)
    result = json.loads(repaired_json_bytes(session)[0])
    assert len(result["walls"]) == 4
    assert {w["_id"] for w in result["walls"]} == {w["_id"] for w in raw["walls"]}
    assert all(w["door"] == 1 and w["flags"] == raw["walls"][0]["flags"] for w in result["walls"])
    assert {k: v for k, v in result.items() if k != "walls"} == {
        k: v for k, v in raw.items() if k != "walls"
    }


def test_height_tools_retain_closure_edges_and_exact_coincident_wall_properties(native):
    from dale.layer_repair import LayerRepairIndex
    from dale.scene import scene_from_json
    from dale.session import Closure
    from dale.source_editing import layer_geometry, replace_layer_geometry, source_layers

    raw = native.source.raw.copy()
    first = raw["walls"][0]
    second = {
        **first,
        "_id": "OtherFloor000001",
        "door": 0,
        "flags": {"wall-height": {"bottom": 10, "top": 20}},
    }
    raw["walls"] = [first, second]
    session = Session(scene_from_json(json.dumps(raw).encode()))
    session.add(Closure(((200, 200), (220, 200), (220, 220), (200, 200))))
    original = session.geometry()
    lower = next(p for p in source_layers(session.source, original) if p.bottom == 0)
    scoped = layer_geometry(original, lower.indices)
    scoped = insert_vertex(scoped, hit_edge(scoped, (60, 20), 1))
    session.add(replace_layer_geometry(original, lower.indices, scoped))
    data = json.loads(repaired_json_bytes(session)[0])
    assert next(w for w in data["walls"] if w["_id"] == second["_id"]) == second
    parts = [w for w in data["walls"] if w.get("door") == 1]
    assert len(parts) == 2 and all(w["flags"] == first["flags"] for w in parts)
    assert len(data["walls"]) == 6  # Two lower pieces, upper original, three closure sides.
    assert len(LayerRepairIndex(session.source, original, 1).geometry.walls) == 5
    assert LayerRepairIndex(session.source, original, 1).all().apply(original) is original


def test_ordinary_shared_point_move_keeps_distinct_coincident_source_owners(native):
    from dale.scene import scene_from_json

    raw = native.source.raw.copy()
    first = raw["walls"][0]
    second = {**first, "_id": "OtherWall0000001", "door": 0, "dir": 2}
    raw["walls"] = [first, second]
    session = Session(scene_from_json(json.dumps(raw).encode()))
    session.add(move_vertex(session.geometry(), (120, 20), (130, 40)))
    data = json.loads(repaired_json_bytes(session)[0])
    assert len(data["walls"]) == 2
    for expected in (first, second):
        wall = next(w for w in data["walls"] if w["_id"] == expected["_id"])
        assert wall == {**expected, "c": [20, 20, 130, 40]}
