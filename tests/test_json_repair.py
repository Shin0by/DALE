"""Layered canonical-wall repair and byte-exact preservation outside coordinate tokens."""

import json
import os
from dataclasses import replace

import pytest
from PIL import Image
from shapely.geometry import LineString, Point

from dale.json_repair import JsonCoordinateDocument, export_repaired_json, repaired_json_bytes
from dale.layer_repair import LayerRepairIndex, infer_layers
from dale.project_io import load_project, save_project
from dale.scene import load_pair
from dale.session import GeometryEdit, Session, SourceRepairEdit
from dale.source_editing import add_source_wall, move_source_vertex, source_layers


def wall(coords, bottom=None, top=None, **settings):
    return {
        "c": coords,
        "flags": {"wall-height": {"bottom": bottom, "top": top}},
        "door": 0,
        "dir": 0,
        **settings,
    }


@pytest.fixture
def scene(tmp_path):
    def create(walls, **extra):
        for i, value in enumerate(walls):
            value.setdefault("_id", f"original{i:08d}")
        raw = {
            "name": "Сцена",
            "width": 100,
            "height": 80,
            "walls": walls,
            "regions": [{"_id": "portal", "system": {"destination": "Scene.A.Region.B"}}],
            "tokens": [{"actorId": "opaque", "unknown": [None, True, 1e-20]}],
            "lights": [{"config": {"bright": 5}}],
            "tiles": [{"texture": {"src": "x.png"}}],
            "opaque": {"escaped": '"c": [1,2,3,4]', "null": None},
            **extra,
        }
        path = tmp_path / "source.json"
        data = (
            "\ufeff" + json.dumps(raw, ensure_ascii=False, indent=3).replace("\n", "\r\n") + "\r\n"
        ).encode("utf-8")
        path.write_bytes(data)
        return Session(load_pair(None, path))

    return create


def repair(session, distance=5, point=None):
    index = LayerRepairIndex(session.source, session.geometry(), distance)
    plan = index.at(point) if point is not None else index.all()
    result = plan.apply(session.geometry())
    if result != session.geometry():
        session.add(result)
    return plan


def test_shared_wall_is_one_object_and_one_coordinate_patch(scene):
    session = scene(
        [wall([0, 0, 10, 0], 0, 20), wall([12, -5, 12, 5], 0, 10), wall([12, -5, 12, 5], 10, 20)]
    )
    before = session.source.json_bytes
    plan = repair(session)
    assert not plan.conflicts and len(plan.extensions) == 1
    assert len(session.walls) == 3
    assert session.walls[0] == ((0, 0), (12, 0))
    assert session.geometry().lineage == Session(session.source).geometry().lineage
    payload, changed = repaired_json_bytes(session)
    assert changed == (0,)
    old, new = JsonCoordinateDocument(before), JsonCoordinateDocument(payload)
    a, b = old.coordinates[0]
    c, d = new.coordinates[0]
    assert before == (new.text[:c] + old.text[a:b] + new.text[d:]).encode("utf-8")
    assert len(new.raw["walls"]) == 3
    for key in old.raw.keys() - {"walls"}:
        assert new.raw[key] == old.raw[key]
    for previous, current in zip(old.raw["walls"], new.raw["walls"], strict=True):
        assert {k: v for k, v in previous.items() if k != "c"} == {
            k: v for k, v in current.items() if k != "c"
        }


def test_conflicting_layers_do_not_overwrite_or_duplicate_common_wall(scene):
    session = scene(
        [wall([0, 0, 10, 0], 0, 20), wall([12, -5, 12, 5], 0, 10), wall([14, -5, 14, 5], 10, 20)]
    )
    original = session.geometry()
    plan = repair(session)
    assert plan.conflicts and not plan.extensions
    assert session.geometry().walls == original.walls
    assert repaired_json_bytes(session) == (session.source.json_bytes, ())


def test_shared_extension_cannot_introduce_unrequested_contact_in_another_layer(scene):
    session = scene(
        [
            wall([0, 0, 10, 0], 0, 20),
            wall([12, -5, 12, 5], 0, 10),
            wall([10, 0, 10, 5], 10, 20),
            wall([11, -5, 11, 5], 10, 20),
        ]
    )
    plan = repair(session)
    assert plan.conflicts
    assert session.walls[0] == ((0, 0), (10, 0))


def test_other_layer_existing_t_contact_remains_after_shared_wall_extension(scene):
    session = scene(
        [wall([0, 0, 10, 0], 0, 20), wall([12, -5, 12, 5], 0, 10), wall([10, 0, 10, 5], 10, 20)]
    )
    plan = repair(session)
    assert not plan.conflicts and session.walls[0][1] == (12, 0)
    assert LineString(session.walls[0]).covers(Point(10, 0))
    assert session.walls[2] == ((10, 0), (10, 5))


def test_cross_floor_door_is_not_split_at_xy_intersection(scene):
    session = scene(
        [
            wall([7017, 9170, 7125, 8888], 10, 20, door=1, ds=2),
            wall([7021, 9172, 7124, 8890], 0, 10),
        ]
    )
    plan = repair(session, 14, (7071, 9029))
    assert not plan.extensions and not plan.conflicts
    assert len(session.walls) == 2
    assert repaired_json_bytes(session)[0] == session.source.json_bytes


def test_corner_extensions_commit_both_original_wall_ids_without_splitting(scene):
    session = scene([wall([0, 0, 9, 0], 0, 10), wall([10, 1, 10, 10], 0, 10)])
    plan = repair(session)
    assert len(plan.extensions) == 2 and not plan.conflicts
    assert len(session.walls) == 2
    assert session.walls[0][1] == session.walls[1][0] == (10, 0)


def test_fractional_and_unbounded_layers_are_references_not_clones(scene):
    session = scene(
        [wall([0, 0, 10, 0]), wall([20, 0, 30, 0], -0.01, 9.99), wall([40, 0, 50, 0], 9.99, 19.99)]
    )
    layers, ambiguous = infer_layers(session.source)
    assert not ambiguous
    assert len(layers) == 4 and all(0 in layer.indices for layer in layers)
    assert not any(1 in layer.indices and 2 in layer.indices for layer in layers)


@pytest.mark.parametrize("bottom,top", [(10, 10), (20, 0), (False, 20), ("0", 20)])
def test_ambiguous_bounds_remain_unchanged_and_are_reported(scene, bottom, top):
    session = scene([wall([0, 0, 10, 0], bottom, top)])
    plan = repair(session)
    assert plan.conflicts and not plan.extensions
    assert repaired_json_bytes(session)[0] == session.source.json_bytes


def test_noncanonical_working_geometry_updates_only_walls(scene):
    session = scene([wall([0, 0, 10, 0])])
    session.add(GeometryEdit((((0, 0), (20, 0)),)))
    updated = json.loads(repaired_json_bytes(session)[0])
    assert len(updated["walls"]) == 1 and updated["walls"][0]["c"] == [0, 0, 20, 0]
    assert {k: v for k, v in updated.items() if k != "walls"} == {
        k: v for k, v in session.source.raw.items() if k != "walls"
    }
    geometry = session.geometry()
    assert LayerRepairIndex(session.source, geometry, 14).geometry is geometry


def test_byte_patch_handles_escaped_keys_whitespace_utf8_and_opaque_decimals():
    data = (
        b'\xef\xbb\xbf{ "w\\u0061lls" : [{"c": [0, 0, 10, 0], '
        b'"opaque":1.23000000000000000009}], "x":"\\u0430" }\r\n'
    )
    doc = JsonCoordinateDocument(data)
    patched = doc.patch({0: [0, 0, 12.5, 0]})
    assert b'"opaque":1.23000000000000000009' in patched
    assert b'"x":"\\u0430" }\r\n' in patched
    assert patched.startswith(b'\xef\xbb\xbf{ "w\\u0061lls"')


@pytest.mark.parametrize("data", [b'{"walls":[],"x":1,"x":2}', b'{"walls":[],"x":NaN}'])
def test_ambiguous_json_rejected_instead_of_normalized(data):
    with pytest.raises(ValueError):
        JsonCoordinateDocument(data)


def test_inverse_image_transform_preserves_native_wall_coordinates(scene, tmp_path):
    session = scene(
        [wall([100, 200, 110, 200], 0, 20), wall([112, 195, 112, 205], 0, 20)],
        background={"offsetX": 100, "offsetY": 200},
    )
    image = tmp_path / "image.png"
    Image.new("RGB", (200, 160)).save(image)
    session = Session(load_pair(image, session.source.json_path), origin=(1, 2))
    repair(session, 10)
    payload, changed = repaired_json_bytes(session)
    assert changed == (0,)
    assert json.loads(payload.decode("utf-8-sig"))["walls"][0]["c"] == [100, 200, 112, 200]


def test_repair_project_undo_redo_reopens_without_image_or_external_json(scene, tmp_path):
    session = scene([wall([0, 0, 10, 0]), wall([12, -5, 12, 5])])
    repair(session)
    expected = repaired_json_bytes(session)
    session.undo()
    path = tmp_path / "repair.dale"
    save_project(session, path, {"safe_json_repair": True})
    session.source.json_path.unlink()
    with load_project(path) as project:
        assert project.session.source.image_path is None
        assert project.ui_state["safe_json_repair"] is True
        assert repaired_json_bytes(project.session)[1] == ()
        project.session.redo()
        assert isinstance(project.session.operations[-1], SourceRepairEdit)
        assert repaired_json_bytes(project.session) == expected


def test_export_new_copy_protects_source_hardlinks_and_external_changes(scene, tmp_path):
    session = scene([wall([0, 0, 10, 0]), wall([12, -5, 12, 5])])
    repair(session)
    original = session.source.json_bytes
    with pytest.raises(ValueError, match="replace"):
        export_repaired_json(session, session.source.json_path)
    linked = tmp_path / "linked.json"
    os.link(session.source.json_path, linked)
    with pytest.raises(ValueError, match="replace"):
        export_repaired_json(session, linked)
    output = tmp_path / "repaired.json"
    assert export_repaired_json(session, output) == (0,)
    assert session.source.json_path.read_bytes() == original
    session.source.json_path.write_bytes(original + b" ")
    with pytest.raises(ValueError, match="changed outside"):
        export_repaired_json(session, output)


def test_failed_atomic_json_export_keeps_existing_destination(scene, tmp_path, monkeypatch):
    session = scene([wall([0, 0, 10, 0]), wall([12, -5, 12, 5])])
    repair(session)
    output = tmp_path / "repaired.json"
    output.write_bytes(b"existing")

    def fail(*_):
        raise OSError("synthetic publish failure")

    monkeypatch.setattr("dale.json_repair.os.replace", fail)
    with pytest.raises(OSError, match="publish failure"):
        export_repaired_json(session, output)
    assert output.read_bytes() == b"existing"
    assert not list(tmp_path.glob(".dale-json-*"))


def test_source_snapshot_is_frozen_at_import(scene, tmp_path):
    session = scene([wall([0, 0, 10, 0])])
    source = replace(session.source, raw={**session.source.raw, "unexpected": 1})
    with pytest.raises(ValueError, match="snapshot"):
        repaired_json_bytes(Session(source))


def test_json_only_import_rejects_missing_canvas_dimensions(tmp_path):
    path = tmp_path / "no-dimensions.json"
    path.write_text('{"walls": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="explicit scene width and height"):
        load_pair(None, path)


def test_coincident_source_ids_and_zero_length_record_are_not_removed(scene):
    session = scene(
        [
            wall([1, 1, 1, 1]),
            wall([0, 0, 10, 0], 0, 10, door=1, ds=2),
            wall([0, 0, 10, 0], 0, 10, door=0),
            wall([12, -5, 12, 5], 0, 10),
        ]
    )
    repair(session)
    payload, changed = repaired_json_bytes(session)
    assert changed == (1, 2)
    result = json.loads(payload.decode("utf-8-sig"))["walls"]
    assert len(result) == 4
    assert [w["_id"] for w in result] == [w["_id"] for w in session.source.raw["walls"]]
    assert result[0] == session.source.raw["walls"][0]
    assert result[1]["c"] == result[2]["c"] == [0, 0, 12, 0]
    assert result[1]["door"] == 1 and result[1]["ds"] == 2 and result[2]["door"] == 0


def choose(session, bottom=0, top=10, kind="band"):
    return next(
        layer
        for layer in source_layers(session.source, session.geometry())
        if layer.bottom == bottom and layer.top == top and layer.kind == kind
    )


def test_source_layer_choices_share_walls_and_offer_exact_common_range(scene):
    session = scene(
        [
            wall([0, 0, 10, 0], 0, 20),
            wall([20, 0, 30, 0], 0, 10),
            wall([40, 0, 50, 0], 10, 20),
            wall([60, 0, 70, 0]),
        ]
    )
    assert choose(session).indices == (0, 1, 3)
    assert choose(session, 10, 20).indices == (0, 2, 3)
    assert choose(session, 0, 20, "range").indices == (0,)
    assert len(session.walls) == 4


def test_manual_point_move_does_not_move_coincident_independent_floor(scene):
    session = scene([wall([0, 0, 10, 0], 0, 10, door=1, ds=2), wall([0, 0, 10, 0], 10, 20)])
    result = move_source_vertex(
        session.source, session.geometry(), (10, 0), (12, 3), choose(session).indices
    )
    session.add(result)
    assert session.walls == (((0, 0), (12, 3)), ((0, 0), (10, 0)))
    payload, changed = repaired_json_bytes(session)
    assert changed == (0,)
    current = JsonCoordinateDocument(payload).raw
    assert current["walls"][0]["door"] == 1 and current["walls"][0]["ds"] == 2
    assert current["walls"][1] == session.source.raw["walls"][1]


def test_shared_manual_contact_follows_common_wall_across_bands(scene):
    session = scene(
        [wall([0, 0, 10, 0], 0, 20), wall([10, 0, 15, 5], 0, 10), wall([10, 0, 15, -5], 10, 20)]
    )
    original = session.geometry()
    session.add(
        move_source_vertex(session.source, original, (10, 0), (12, 1), choose(session).indices)
    )
    assert session.walls[0][1] == session.walls[1][0] == session.walls[2][0] == (12, 1)
    assert session.geometry().lineage == original.lineage
    assert repaired_json_bytes(session)[1] == (0, 1, 2)


def test_manual_t_contact_does_not_split_native_wall_and_collapse_is_rejected(scene):
    session = scene([wall([0, 0, 10, 0], 0, 10), wall([12, -5, 12, 5], 0, 10)])
    original = session.geometry()
    with pytest.raises(ValueError, match="collapse"):
        move_source_vertex(session.source, original, (10, 0), (0, 0), (0, 1))
    assert session.geometry() == original
    session.add(move_source_vertex(session.source, original, (10, 0), (12, 0), (0, 1)))
    assert len(session.walls) == 2 and session.walls[1] == original.walls[1]
    assert repaired_json_bytes(session)[1] == (0,)


def test_new_native_wall_appends_ordinary_defaults_preserving_all_original_bytes(scene):
    session = scene([wall([0, 0, 10, 0], 0, 10, door=1), wall([5, -5, 5, 5], 0, 10)])
    before = JsonCoordinateDocument(session.source.json_bytes)
    session.add(
        add_source_wall(session.source, session.geometry(), (2, 2), (8, -2), choose(session))
    )
    payload, changed = repaired_json_bytes(session)
    after = JsonCoordinateDocument(payload)
    assert changed == (2,) and len(after.raw["walls"]) == 3
    assert after.raw["walls"][:2] == before.raw["walls"]
    assert payload.startswith(before.text[: before.walls_end].encode("utf-8"))
    assert payload.endswith(before.text[before.walls_end :].encode("utf-8"))
    new = after.raw["walls"][-1]
    assert len(new["_id"]) == 16 and new["door"] == new["ds"] == new["dir"] == 0
    assert new["move"] == new["sight"] == new["light"] == new["sound"] == 20
    assert new["flags"]["wall-height"] == {"bottom": 0, "top": 10}
    assert not session.geometry().lineage[-1].parents


def test_manual_creation_in_empty_scene_and_exact_duplicate_policy(scene):
    session = scene([])
    layer = choose(session, None, None)
    all_layers = add_source_wall(
        session.source,
        session.geometry(),
        (0, 0),
        (10, 0),
        source_layers(session.source, session.geometry())[0],
    )
    assert all_layers.additions[0].bottom is None and all_layers.additions[0].top is None
    session.add(add_source_wall(session.source, session.geometry(), (0, 0), (10, 0), layer))
    assert (
        add_source_wall(session.source, session.geometry(), (10, 0), (0, 0), layer)
        == session.geometry()
    )
    assert len(JsonCoordinateDocument(repaired_json_bytes(session)[0]).raw["walls"]) == 1


def test_same_xy_manual_walls_on_distinct_ranges_remain_separate(scene):
    session = scene([wall([40, 0, 50, 0], 0, 10), wall([60, 0, 70, 0], 10, 20)])
    session.add(
        add_source_wall(session.source, session.geometry(), (0, 0), (10, 0), choose(session))
    )
    session.add(
        add_source_wall(
            session.source, session.geometry(), (0, 0), (10, 0), choose(session, 10, 20)
        )
    )
    assert len(session.walls) == 4
    assert session.geometry().additions[0].native_id != session.geometry().additions[1].native_id
    assert repaired_json_bytes(session)[1] == (2, 3)


def test_manual_creation_move_auto_close_archive_undo_redo_keeps_new_ids(scene, tmp_path):
    session = scene(
        [wall([0, 0, 10, 0], 0, 20), wall([12, -5, 12, 5], 0, 10), wall([12, -5, 12, 5], 10, 20)]
    )
    layer = choose(session)
    session.add(add_source_wall(session.source, session.geometry(), (20, 20), (30, 20), layer))
    session.add(
        move_source_vertex(
            session.source, session.geometry(), (30, 20), (30, 22), layer.indices + (3,)
        )
    )
    repair(session)
    expected = repaired_json_bytes(session)
    native_id = session.geometry().additions[0].native_id
    path = tmp_path / "manual.dale"
    session.undo()
    save_project(session, path, {"safe_json_repair": True, "source_layer": layer.key})
    session.source.json_path.unlink()
    with load_project(path) as project:
        assert project.ui_state["source_layer"] == layer.key
        project.session.redo()
        assert repaired_json_bytes(project.session) == expected
        assert project.session.geometry().additions[0].native_id == native_id
        project.session.undo()
        project.session.undo()
        project.session.undo()
        assert repaired_json_bytes(project.session) == (session.source.json_bytes, ())


def test_filtered_auto_close_does_not_repair_unrelated_hidden_floor(scene):
    session = scene(
        [
            wall([0, 0, 10, 0], 0, 10),
            wall([12, -5, 12, 5], 0, 10),
            wall([40, 0, 50, 0], 10, 20),
            wall([52, -5, 52, 5], 10, 20),
        ]
    )
    geometry = session.geometry()
    index = LayerRepairIndex(session.source, geometry, 5, choose(session).indices)
    assert not index.at((45, 0)).extensions
    session.add(index.all().apply(geometry))
    assert session.walls[0][1] == (12, 0) and session.walls[2][1] == (50, 0)


def test_append_and_coordinate_patch_together_preserve_opaque_source_tokens(scene):
    session = scene([wall([0, 0, 10, 0], 0, 10), wall([12, -5, 12, 5], 0, 10)])
    session.add(
        add_source_wall(session.source, session.geometry(), (40, 20), (50, 20), choose(session))
    )
    repair(session)
    payload, changed = repaired_json_bytes(session)
    assert changed == (0, 2)
    before, after = (
        JsonCoordinateDocument(session.source.json_bytes),
        JsonCoordinateDocument(payload),
    )
    assert after.raw["walls"][0]["c"] == [0, 0, 12, 0]
    assert after.raw["regions"] == before.raw["regions"]
    assert after.raw["opaque"] == before.raw["opaque"]


def test_new_common_wall_is_one_record_in_each_covered_band(scene):
    session = scene(
        [wall([0, 0, 10, 0], 0, 20), wall([20, 0, 30, 0], 0, 10), wall([40, 0, 50, 0], 10, 20)]
    )
    common = choose(session, 0, 20, "range")
    session.add(add_source_wall(session.source, session.geometry(), (60, 20), (70, 20), common))
    assert choose(session).indices.count(3) == choose(session, 10, 20).indices.count(3) == 1
    assert choose(session, 0, 20, "range").indices == (0, 3)
    assert len(JsonCoordinateDocument(repaired_json_bytes(session)[0]).raw["walls"]) == 4


def test_new_native_wall_uses_inverse_source_alignment_without_changing_height(scene, tmp_path):
    session = scene(
        [wall([100, 200, 110, 200], 0, 10)], background={"offsetX": 100, "offsetY": 200}
    )
    image = tmp_path / "scaled.png"
    Image.new("RGB", (200, 160)).save(image)
    session = Session(load_pair(image, session.source.json_path), origin=(1, 2))
    session.add(
        add_source_wall(session.source, session.geometry(), (20, 20), (40, 40), choose(session))
    )
    new = JsonCoordinateDocument(repaired_json_bytes(session)[0]).raw["walls"][-1]
    assert new["c"] == [111, 212, 121, 222]
    assert new["flags"]["wall-height"] == {"bottom": 0, "top": 10}


@pytest.mark.parametrize(
    "change",
    [{"native_id": "original00000000"}, {"native_id": "bad"}, {"bottom": False}, {"bottom": 10}],
)
def test_invalid_added_wall_metadata_cannot_be_exported_as_source_repair(scene, change):
    session = scene([wall([0, 0, 10, 0], 0, 10)])
    geometry = add_source_wall(
        session.source, session.geometry(), (20, 0), (30, 0), choose(session)
    )
    session.add(replace(geometry, additions=(replace(geometry.additions[0], **change),)))
    with pytest.raises(ValueError):
        repaired_json_bytes(session)


def test_automatic_trim_keeps_native_wall_count_ids_properties_and_coordinate_only_diff(scene):
    session = scene(
        [wall([0, 0, 12, 0], 0, 10, door=1, ds=2), wall([10, -10, 10, 2], 0, 10, dir=1)]
    )
    original = session.geometry()
    plan = repair(session, 2)
    assert not plan.extensions and len(plan.retractions) == 2
    assert session.walls == (((0, 0), (10, 0)), ((10, -10), (10, 0)))
    assert session.geometry().lineage == original.lineage
    payload, changed = repaired_json_bytes(session)
    assert changed == (0, 1)
    old, new = JsonCoordinateDocument(session.source.json_bytes), JsonCoordinateDocument(payload)
    restored = new.text
    for i in reversed(changed):
        start, end = new.coordinates[i]
        a, b = old.coordinates[i]
        restored = restored[:start] + old.text[a:b] + restored[end:]
    assert restored.encode("utf-8") == session.source.json_bytes
    assert new.raw["walls"][0]["door"] == 1 and new.raw["walls"][0]["ds"] == 2
    assert new.raw["walls"][1]["dir"] == 1


def test_shared_wall_trim_and_extension_remain_one_canonical_state_in_all_bands(scene):
    session = scene([wall([0, 0, 10, 0], 0, 20), wall([6, 4, 6, 100], 0, 10)])
    plan = repair(session, 4)
    assert plan.retractions == (((10, 0), (6, 0)),)
    assert plan.extensions == (((6, 4), (6, 0)),)
    assert not plan.conflicts and len(session.walls) == 2
    assert session.walls[0] == ((0, 0), (6, 0))
    assert 0 in choose(session).indices and 0 in choose(session, 10, 20).indices


def test_trim_cannot_break_existing_joint_in_an_unendorsed_floor(scene):
    session = scene(
        [wall([0, 0, 10, 0], 0, 20), wall([6, 4, 6, 100], 0, 10), wall([10, 0, 10, 5], 10, 20)]
    )
    original = session.geometry()
    plan = repair(session, 4)
    assert plan.conflicts and not plan.endpoint_moves
    assert session.geometry() == original
    assert repaired_json_bytes(session) == (session.source.json_bytes, ())


def test_trim_cannot_discard_contact_with_ambiguous_height_wall(scene):
    session = scene(
        [wall([0, 0, 10, 0], 0, 10), wall([6, 4, 6, 100], 0, 10), wall([8, -10, 8, 10], 10, 0)]
    )
    original = session.geometry()
    plan = repair(session, 4)
    assert plan.conflicts and not plan.endpoint_moves
    assert session.geometry() == original


def test_coincident_native_walls_trim_together_without_merging_records(scene):
    session = scene(
        [
            wall([0, 0, 12, 0], 0, 10, door=1),
            wall([0, 0, 12, 0], 0, 10, door=0),
            wall([10, -10, 10, 2], 0, 10),
        ]
    )
    plan = repair(session, 2)
    assert len(plan.retractions) == 3 and len(session.walls) == 3
    assert session.walls[0] == session.walls[1] == ((0, 0), (10, 0))
    payload, changed = repaired_json_bytes(session)
    assert changed == (0, 1, 2)
    result = JsonCoordinateDocument(payload).raw["walls"]
    assert len({w["_id"] for w in result}) == 3
    assert result[0]["door"] == 1 and result[1]["door"] == 0


def test_trim_survives_project_redo_with_new_manual_wall_identity(scene, tmp_path):
    session = scene([wall([0, 0, 12, 0], 0, 10), wall([10, -10, 10, 2], 0, 10)])
    session.add(
        add_source_wall(session.source, session.geometry(), (50, 50), (60, 50), choose(session))
    )
    native_id = session.geometry().additions[0].native_id
    plan = repair(session, 2)
    assert len(plan.retractions) == 2
    expected = repaired_json_bytes(session)
    session.undo()
    path = tmp_path / "trim.dale"
    save_project(session, path, {"safe_json_repair": True})
    with load_project(path) as loaded:
        loaded.session.redo()
        assert repaired_json_bytes(loaded.session) == expected
        assert loaded.session.geometry().additions[0].native_id == native_id
        assert (
            not LayerRepairIndex(loaded.session.source, loaded.session.geometry(), 2)
            .all()
            .endpoint_moves
        )
