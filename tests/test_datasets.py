"""Synthetic independent datasets, exact source preservation and explicit JSON append."""

import json
from zipfile import ZipFile

import pytest
from PIL import Image

from dale.datasets import DatasetCatalog, append_dataset
from dale.editing import add_line
from dale.json_repair import repaired_json_bytes
from dale.project_io import load_project, read_json_documents, save_project
from dale.scene import load_pair
from dale.session import Session, Stroke


def incoming(tmp_path, walls, **other):
    path = tmp_path / "incoming.json"
    path.write_text(
        json.dumps({"width": 400, "height": 400, "padding": 0, "walls": walls, **other}),
        encoding="utf-8",
    )
    return Session(load_pair(None, path))


def test_dataset_append_keeps_the_target_projects_custom_palette(tmp_path):
    target = DatasetCatalog()
    path = tmp_path / "Target colors.dale"
    palette = ["#ff123456"] * 16
    save_project(target.current.session, path, catalog=target, custom_colors=palette)
    source = DatasetCatalog()
    append_dataset(path, source, source.base_key)
    with load_project(path) as loaded:
        assert loaded.custom_colors == tuple(palette)
        assert len(loaded.catalog.views) == 2


def test_multiple_empty_datasets_stable_ids_rename_and_default_roundtrip(tmp_path):
    catalog = DatasetCatalog()
    first = catalog.base_key
    second = catalog.create("Second")
    third = catalog.create("Third")
    catalog.rename("First", first)
    catalog.activate(third.id)
    path = tmp_path / "empty.dale"
    save_project(catalog.current.session, path, catalog=catalog)
    with load_project(path) as loaded:
        assert list(loaded.catalog.views) == [first, second.id, third.id]
        assert loaded.catalog.active_key == third.id
        assert [v.name for v in loaded.catalog.views.values()] == ["First", "Second", "Third"]
        assert all(not v.has_json and not v.has_image for v in loaded.catalog.views.values())
        loaded.catalog.remove(first)
        loaded.catalog.remove(second.id)
        loaded.catalog.remove(third.id)
        assert len(loaded.catalog.views) == 1 and loaded.catalog.base_key != first
        save_project(loaded.catalog.current.session, path, catalog=loaded.catalog)
    assert read_json_documents(path) == ()


def test_appending_and_removing_datasets_preserves_or_repairs_reopening_choice(tmp_path):
    catalog = DatasetCatalog()
    first = catalog.base_key
    selected = catalog.create("Selected")
    catalog.activate(selected.id)
    path = tmp_path / "selected.dale"
    save_project(catalog.current.session, path, catalog=catalog)
    incoming = DatasetCatalog()
    appended, _ = append_dataset(path, incoming, incoming.base_key)
    with load_project(path) as loaded:
        assert loaded.catalog.active_key == selected.id
        assert loaded.catalog.base_key == first
        assert appended in loaded.catalog.views
        loaded.catalog.remove(selected.id)
        assert loaded.catalog.active_key == first
        save_project(loaded.session, path, catalog=loaded.catalog)
    with load_project(path) as loaded:
        assert loaded.catalog.active_key == first and selected.id not in loaded.catalog.views


@pytest.mark.parametrize("invalid", [None, True, [], {}, "set-" + "f" * 32])
def test_saved_dataset_default_must_reference_an_existing_stable_identity(invalid):
    catalog = DatasetCatalog()
    value = json.loads(json.dumps(catalog.encode()))
    value["default"] = invalid
    with pytest.raises(ValueError, match="default dataset"):
        DatasetCatalog.restore(catalog.base_session, {}, (), (), value)


def test_transaction_fork_keeps_original_and_copy_components_independent(pair_factory, tmp_path):
    original = DatasetCatalog(Session(pair_factory(size=(400, 400))))
    original.current.session.add(Stroke(((30, 50),), 4))
    source = original.base_key
    copy = original.create("Copy")
    draft = original.fork()
    draft.transfer(source, copy.id, "json")
    draft.transfer(source, copy.id, "image")
    assert not original.views[copy.id].has_json and not original.views[copy.id].has_image
    assert draft.views[copy.id].session.walls == draft.views[source].session.walls
    assert draft.views[copy.id].session.operations[-1] == original.current.session.operations[-1]
    draft.views[copy.id].session.add(
        add_line(draft.views[copy.id].session.geometry(), (200, 200), (250, 200))
    )
    assert len(draft.views[source].session.walls) == 4
    assert len(draft.views[copy.id].session.walls) == 5
    draft.rename_file(copy.id, "json", "Separate contours")
    draft.rename_file(copy.id, "image", "Separate image")
    path = tmp_path / "copy.dale"
    save_project(draft.current.session, path, catalog=draft)
    with load_project(path) as loaded:
        view = loaded.catalog.views[copy.id]
        assert view.filename("json") == "Separate contours.json"
        assert view.filename("image") == "Separate image.jpg"
        assert len(view.session.walls) == 5
        assert loaded.catalog.snapshot(copy.id).name == "Copy.json"
        assert loaded.catalog.snapshot(copy.id).image_name == "Copy.jpg"


@pytest.mark.parametrize("kind", ["json", "image"])
def test_component_move_clears_only_source_component_and_preserves_other(
    pair_factory, tmp_path, kind
):
    catalog = DatasetCatalog(Session(pair_factory(size=(400, 400))))
    source = catalog.base_key
    target = catalog.create("Target")
    before = catalog.current.session.source.image_path.read_bytes()
    catalog.transfer(source, target.id, kind, move=True)
    left, right = catalog.views[source], catalog.views[target.id]
    assert left.has_json == (kind == "image")
    assert left.has_image == (kind == "json")
    assert right.has_json == (kind == "json")
    assert right.has_image == (kind == "image")
    path = tmp_path / "moved.dale"
    save_project(catalog.current.session, path, catalog=catalog)
    with load_project(path) as loaded:
        image_view = loaded.catalog.views[source if kind == "json" else target.id]
        assert image_view.session.source.image_path.read_bytes() == before
        assert (
            len(loaded.catalog.views[source if kind == "image" else target.id].session.walls) == 4
        )


def test_native_json_append_keeps_unknown_scene_data_and_incoming_wall_properties(
    pair_factory, tmp_path
):
    source = pair_factory(
        size=(400, 400),
        name="Original Scene",
        background={"src": "old/path/original.png"},
        flags={"private-module": {"a": 9}},
        walls=[
            {
                "_id": "same",
                "c": [10, 10, 50, 10],
                "door": 1,
                "flags": {"wall-height": {"bottom": 0, "top": 10}},
            }
        ],
    )
    catalog = DatasetCatalog(Session(source))
    original = source.json_path.read_bytes()
    new_wall = {
        "_id": "same",
        "c": [10, 10, 50, 10],
        "door": 2,
        "flags": {"wall-height": {"bottom": 10, "top": 20}, "unknown": True},
    }
    added = incoming(
        tmp_path,
        [source.raw["walls"][0], new_wall],
        name="Must not replace scene",
        background={"src": "wrong.png"},
    )
    assert catalog.add_json(catalog.base_key, added) == 1
    payload = repaired_json_bytes(catalog.current.session)[0]
    result = json.loads(payload)
    assert result["name"] == "Original Scene" and result["background"] == source.raw["background"]
    assert result["flags"] == source.raw["flags"]
    assert result["walls"][0] == source.raw["walls"][0]
    assert result["walls"][1]["door"] == 2 and result["walls"][1]["flags"] == new_wall["flags"]
    assert result["walls"][1]["_id"] != "same"
    assert catalog.add_json(catalog.base_key, added) == 0
    assert source.json_path.read_bytes() == original
    catalog.rename("Exported name")
    path = tmp_path / "merged.dale"
    save_project(catalog.current.session, path, {"safe_json_repair": True}, catalog=catalog)
    with load_project(path) as loaded:
        assert repaired_json_bytes(loaded.session)[0] == payload
        assert loaded.catalog.snapshot().name == "Exported name.json"
        assert loaded.session.source.raw["background"]["src"] == "old/path/original.png"


@pytest.mark.parametrize("authored", [False, True])
def test_merge_current_split_or_image_only_authored_source_preserves_properties_and_ancestry(
    pair_factory, tmp_path, authored
):
    from dale.datasets import empty_source
    from dale.editing import hit_edge, insert_vertex

    catalog = DatasetCatalog(Session(pair_factory(size=(400, 400))))
    session = catalog.current.session
    if authored:
        addition = Session(empty_source((400, 400)))
        addition.add(add_line(addition.geometry(), (150, 150), (180, 150)))
    else:
        addition = incoming(
            tmp_path, [{"c": [150, 150, 180, 150], "door": 2, "flags": {"custom": 9}}]
        )
        addition.add(
            insert_vertex(addition.geometry(), hit_edge(addition.geometry(), (165, 150), 1))
        )
    before = addition.geometry()
    count = len(before.lineage)
    assert catalog.add_json(catalog.base_key, addition) == count
    assert addition.geometry() == before
    assert session.geometry().walls[-count:] == before.walls
    payload = json.loads(repaired_json_bytes(session)[0])
    added = [wall for wall in payload["walls"] if wall["c"][0] >= 150]
    assert len(added) == count
    assert all(w["door"] == (0 if authored else 2) for w in added)
    if not authored:
        assert all(w["flags"] == {"custom": 9} for w in added)
    assert catalog.add_json(catalog.base_key, addition) == 0
    path = tmp_path / "current-merged.dale"
    save_project(session, path, catalog=catalog)
    with load_project(path) as loaded:
        assert json.loads(repaired_json_bytes(loaded.session)[0]) == payload
        assert loaded.session.geometry().lineage == session.geometry().lineage


def test_general_json_append_keeps_old_geometry_and_different_properties(pair_factory, tmp_path):
    catalog = DatasetCatalog(Session(pair_factory(size=(400, 400))))
    session = catalog.current.session
    session.add(add_line(session.geometry(), (150, 150), (170, 150)))
    previous = session.geometry()
    existing = dict(session.source.raw["walls"][0])
    variant = dict(existing, door=1)
    assert catalog.add_json(catalog.base_key, incoming(tmp_path, [existing, variant])) == 1
    current = catalog.current.session.geometry()
    assert current.walls[: len(previous.walls)] == previous.walls
    assert current.lineage[: len(previous.lineage)] == previous.lineage
    assert len(current.walls) == 6
    path = tmp_path / "general.dale"
    save_project(catalog.current.session, path, catalog=catalog)
    with load_project(path) as loaded:
        assert loaded.session.geometry().lineage == current.lineage
        assert loaded.session.walls == current.walls


def test_native_append_preserves_previous_repair_and_full_undo_redo(pair_factory, tmp_path):
    from dale.source_editing import SourceLayer, add_source_wall

    catalog = DatasetCatalog(Session(pair_factory(size=(400, 400))))
    session = catalog.current.session
    operation = add_source_wall(
        session.source,
        session.geometry(),
        (150, 100),
        (180, 100),
        SourceLayer("band:0:10", "band", 0, 10, ()),
    )
    session.add(operation)
    before = session.geometry()
    previous_history = tuple(session.operations)
    original_identities = tuple(r.id for r in before.lineage)
    added = incoming(
        tmp_path,
        [{"c": [20, 30, 70, 30], "door": 2, "flags": {"wall-height": {"bottom": 10, "top": 20}}}],
    )
    assert catalog.add_json(catalog.base_key, added) == 1
    assert tuple(session.operations[:-1]) == previous_history
    assert tuple(r.id for r in session.geometry().lineage[:-1]) == original_identities
    payload = repaired_json_bytes(session)[0]
    session.undo()
    assert session.geometry() == before
    path = tmp_path / "undo-append.dale"
    save_project(session, path, catalog=catalog)
    with load_project(path) as loaded:
        assert loaded.session.geometry() == before
        loaded.session.redo()
        assert repaired_json_bytes(loaded.session)[0] == payload


def test_export_to_existing_project_keeps_datasets_and_raw_image_bytes(pair_factory, tmp_path):
    source = DatasetCatalog(Session(pair_factory(size=(400, 400))))
    source.rename("First")
    source.current.session.add(Stroke(((25, 30),), 3))
    destination = tmp_path / "target.dale"
    save_project(source.current.session, destination, catalog=source)
    before = source.state()
    identifier, name = append_dataset(destination, source, source.base_key)
    assert name == "First (2)" and source.state() == before
    with load_project(destination) as loaded:
        assert len(loaded.catalog.views) == 2
        copied = loaded.catalog.views[identifier]
        assert copied.session.operations == source.current.session.operations
        assert (
            copied.session.source.image_path.read_bytes()
            == source.current.session.source.image_path.read_bytes()
        )
        assert copied.filename("image") == "First (2).jpg"
    with ZipFile(destination) as archive:
        assert sum(n.endswith(".image") for n in archive.namelist()) == 1


def test_dataset_image_replacement_preserves_pixel_geometry_without_scaling(pair_factory, tmp_path):
    from dale.layer_repair import repair_history_is_safe

    catalog = DatasetCatalog(Session(pair_factory(size=(400, 400))))
    before = catalog.current.session.geometry()
    image = tmp_path / "different.png"
    Image.new("RGB", (200, 300)).save(image)
    catalog.replace_component(catalog.base_key, "image", Session(load_pair(image)))
    current = catalog.current.session.geometry()
    assert (current.walls, current.lineage, current.ancestry) == (
        before.walls,
        before.lineage,
        before.ancestry,
    )
    assert catalog.current.session.source.size == (200, 300)
    assert repair_history_is_safe(catalog.current.session)
    native = json.loads(repaired_json_bytes(catalog.current.session)[0])
    assert [{k: v for k, v in wall.items() if k != "c"} for wall in native["walls"]] == [
        {k: v for k, v in wall.items() if k != "c"}
        for wall in catalog.current.session.source.raw["walls"]
    ]
    path = tmp_path / "dimensions.dale"
    save_project(catalog.current.session, path, catalog=catalog)
    with load_project(path) as loaded:
        current = loaded.session.geometry()
        assert (current.walls, current.lineage, current.ancestry) == (
            before.walls,
            before.lineage,
            before.ancestry,
        )
        assert repair_history_is_safe(loaded.session)


@pytest.mark.parametrize("name", ["", " ", "a/b", "CON", "bad.", "x" * 241])
def test_dataset_names_reject_unsafe_filesystem_values(name):
    catalog = DatasetCatalog()
    with pytest.raises(ValueError):
        catalog.rename(name)


def test_add_first_json_to_empty_dataset_keeps_its_frame_and_native_properties(tmp_path):
    catalog = DatasetCatalog()
    source = incoming(
        tmp_path, [{"c": [10, 20, 100, 20], "door": 2}], background={"src": "original.png"}
    )
    assert catalog.add_json(catalog.base_key, source) == 1
    assert catalog.current.session.source.size == (400, 400)
    assert repaired_json_bytes(catalog.current.session)[0] == source.source.json_bytes
    path = tmp_path / "first.dale"
    save_project(catalog.current.session, path, catalog=catalog)
    with load_project(path) as loaded:
        assert loaded.session.source.size == (400, 400)
        assert loaded.session.walls == source.walls


def test_native_append_uses_exact_original_indices_after_degenerate_records(pair_factory, tmp_path):
    catalog = DatasetCatalog(Session(pair_factory(size=(400, 400))))
    addition = incoming(
        tmp_path, [{"c": [1, 1, 1, 1], "door": 0}, {"c": [90, 90, 100, 90], "door": 2}]
    )
    assert catalog.add_json(catalog.base_key, addition) == 1
    assert json.loads(repaired_json_bytes(catalog.current.session)[0])["walls"][-1]["door"] == 2
    assert catalog.current.session.geometry().additions[-1].source_ref.wall_index == 1
    path = tmp_path / "indices.dale"
    save_project(catalog.current.session, path, catalog=catalog)
    with load_project(path) as loaded:
        assert json.loads(repaired_json_bytes(loaded.session)[0])["walls"][-1]["door"] == 2
