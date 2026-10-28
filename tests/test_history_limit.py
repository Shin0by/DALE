"""Checkpoint old actions without changing current schema, pixels or source ownership."""

import json
from zipfile import ZipFile

import pytest
from shapely.geometry import box

from dale.datasets import DatasetCatalog
from dale.editing import add_line
from dale.json_repair import repaired_json_bytes
from dale.project_io import LIMITS, SCHEMA_VERSION, _encode, load_project, save_project
from dale.raster import render_export_alpha
from dale.region_transform import plan_figure_transform
from dale.session import ContourMask, Session, Stroke


def test_large_snapshot_keeps_exact_provenance_without_repeated_vertex_diagnostics(
    pair_factory, tmp_path
):
    from dale.provenance import LineRecord
    from dale.session import GeometryEdit

    session = Session(pair_factory())
    walls = tuple(((float(i), 0.0), (float(i), 1.0)) for i in range(10_001))
    records = tuple(
        LineRecord(f"obstacle:{i}", connection_group=f"object:{i}") for i in range(len(walls))
    )
    geometry = GeometryEdit(walls, lineage=records)
    session.add(geometry)
    encoded = _encode(geometry)
    assert "vertices" not in encoded
    assert len(encoded["lineage"]) == len(walls)
    path = tmp_path / "large.dale"
    save_project(session, path)
    with load_project(path) as loaded:
        actual = loaded.session.geometry()
        assert actual.walls == walls
        assert actual.lineage == records
        assert actual.connection_state == geometry.connection_state
        assert actual.vertex_lineage == geometry.vertex_lineage
        loaded.session.undo()
        loaded.session.redo()
        assert loaded.session.geometry().walls == walls


def many_edits(source, count=160):
    session = Session(source)
    for _ in range(count):
        geometry = session.geometry()
        session.operations.append(
            plan_figure_transform(geometry, [geometry.lineage[0].id]).apply(dx=1)[0]
        )
    return session


def test_one_hundred_actions_retain_exact_baseline_and_new_branch(pair_factory):
    session = Session(pair_factory())
    for _ in range(160):
        geometry = session.geometry()
        session.add(plan_figure_transform(geometry, [geometry.lineage[0].id]).apply(dx=1)[0])
    assert len(session.operations) - session.history_floor == 100
    assert session.history_floor == 1
    final = _encode(session.geometry())
    for _ in range(101):
        session.undo()
    assert len(session.future) == 100 and len(session.operations) == session.history_floor
    checkpoint = _encode(session.geometry())
    assert checkpoint != final
    for _ in range(100):
        session.redo()
    assert _encode(session.geometry()) == final
    for _ in range(60):
        session.undo()
    session.add(add_line(session.geometry(), (0, 0), (5, 5)))
    assert not session.future
    assert len(session.operations) - session.history_floor == 41
    for _ in range(100):
        session.undo()
    assert _encode(session.geometry()) == checkpoint


@pytest.mark.parametrize("catalogued", [False, True])
def test_old_long_history_and_raster_roundtrip_without_schema_change(
    pair_factory, tmp_path, catalogued
):
    source = pair_factory()
    session = many_edits(source)
    session.operations[1:1] = [
        ContourMask(box(5, 10, 70, 290), "outside", box(5, 10, 70, 290)),
        Stroke(((15, 30), (45, 70)), 5),
        Stroke(((20, 35),), 2, True),
    ]
    session.undo()
    session.undo()
    native = repaired_json_bytes(session)
    pixels = render_export_alpha(source.size, source.size, session.operations).tobytes()
    geometry = _encode(session.geometry())
    catalog = DatasetCatalog(session) if catalogued else None
    if catalog:
        other = catalog.create("Inactive")
        other.session = many_edits(source, 190)
    path = tmp_path / "old-work.dale"
    save_project(session, path, catalog=catalog)
    with ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["schema_version"] == SCHEMA_VERSION == 7
        assert json.loads(archive.read("history.json"))["undo_floor"] > 0
    assert repaired_json_bytes(session) == native
    assert _encode(session.geometry()) == geometry
    assert render_export_alpha(source.size, source.size, session.operations).tobytes() == pixels
    with load_project(path) as loaded:
        restored = loaded.session
        assert _encode(restored.geometry()) == geometry
        assert repaired_json_bytes(restored) == native
        assert (
            render_export_alpha(source.size, source.size, restored.operations).tobytes() == pixels
        )
        assert len(restored.operations) - restored.history_floor + len(restored.future) == 0
        if catalogued:
            other_session = loaded.catalog.views[other.id].session
            assert len(other_session.operations) - other_session.history_floor == 0
        for _ in range(20):
            restored.undo()
        restored.add(add_line(restored.geometry(), (0, 0), (5, 5)))
        # A partial undo followed by another action must retain the checkpoint across reopen.
        save_project(restored, tmp_path / "branched.dale")
        with load_project(tmp_path / "branched.dale") as branched:
            assert branched.session.history_floor == restored.history_floor
            for _ in range(101):
                branched.session.undo()
            assert len(branched.session.operations) == branched.session.history_floor


def test_catalog_keeps_history_without_byte_limit_and_failed_save_keeps_live_history(
    pair_factory, tmp_path, monkeypatch
):
    session = many_edits(pair_factory(), 140)
    catalog = DatasetCatalog(session)
    assert LIMITS["history.json"] is None
    catalog.views[catalog.base_key].ui["large_test_payload"] = "a" * (65 * 1024 * 1024)
    path = tmp_path / "bounded.dale"
    native = repaired_json_bytes(session)
    save_project(session, path, catalog=catalog)
    assert len(session.operations) - session.history_floor == 100
    assert repaired_json_bytes(session) == native
    with ZipFile(path) as archive:
        assert archive.getinfo("datasets.json").file_size > 64 * 1024 * 1024
    with load_project(path) as loaded:
        assert repaired_json_bytes(loaded.session) == native
        assert len(loaded.session.operations) - loaded.session.history_floor == 0
    initial = list(session.operations)
    floor = session.history_floor
    monkeypatch.setattr(
        "dale.project_io.os.replace", lambda *_: (_ for _ in ()).throw(OSError("synthetic failure"))
    )
    original = path.read_bytes()
    with pytest.raises(OSError):
        save_project(session, path, catalog=catalog)
    assert session.operations == initial and session.history_floor == floor
    assert path.read_bytes() == original


def test_image_replacement_recounts_filtered_raster_checkpoint(pair_factory, tmp_path):
    from dale.raster import load_preview

    source = pair_factory()
    session = Session(source)
    session.operations = [Stroke(((20, 30),), 3)] * 120
    session.operations.extend(many_edits(source, 150).operations)
    session.trim_history()
    assert session.history_floor > 100
    catalog = DatasetCatalog(session)
    catalog.replace_component(catalog.base_key, "image", Session(source))
    restored = catalog.current.session
    assert restored.history_floor == 1
    path = tmp_path / "replaced.dale"
    save_project(restored, path, catalog=catalog)
    with load_project(path) as loaded:
        assert loaded.session.history_floor == 1
        assert load_preview(loaded.session.source).size == source.size
