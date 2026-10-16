import json
import zipfile

import pytest

from dale.editing import hit_edge, insert_vertex
from dale.project_io import LIMITS, JsonDocument, load_project, read_json_documents, save_project
from dale.raster import render_alpha
from dale.session import Closure, Session, Stroke


def test_portable_archive_preserves_sources_operations_redo_and_settings(pair_factory, tmp_path):
    source = pair_factory()
    original = source.image_path.read_bytes(), source.json_path.read_bytes()
    session = Session(source, gap_tolerance=3, contour_offset=2)
    session.add(Closure(((10, 20), (30, 40), (60, 20))))
    session.add(insert_vertex(session.geometry(), hit_edge(session.geometry(), (35, 20), 1)))
    session.add(session.make_mask("outside"))
    session.add(Stroke(((20, 30), (30, 40)), 3))
    session.add(Stroke(((25, 35),), 1, restore=True))
    session.undo()
    expected_alpha = render_alpha(source.size, source.size, session.operations).tobytes()
    path = tmp_path / "portable.dale"
    save_project(
        session,
        path,
        {
            "foundry_major": 13,
            "elevation_ft": 17,
            "mode": "Edit points",
            "line_eraser_diameter": 37,
            "vertex_eraser_diameter": 61,
        },
    )
    source.image_path.unlink()
    source.json_path.unlink()
    with load_project(path) as loaded:
        assert loaded.session.source.image_path.read_bytes() == original[0]
        assert loaded.session.source.json_path.read_bytes() == original[1]
        assert loaded.session.operations == session.operations
        assert loaded.session.future == session.future
        assert loaded.session.gap_tolerance == 3
        assert loaded.session.contour_offset == 2
        assert loaded.ui_state["elevation_ft"] == 17
        assert loaded.ui_state["mode"] == "Edit points"
        assert loaded.ui_state["line_eraser_diameter"] == 37
        assert loaded.ui_state["vertex_eraser_diameter"] == 61
        assert (
            render_alpha(source.size, source.size, loaded.session.operations).tobytes()
            == expected_alpha
        )
        loaded.session.redo()
        assert len(loaded.session.operations) == 5
        extracted = loaded.session.source.image_path
    assert not extracted.exists()


def _rewrite(path, modify):
    with zipfile.ZipFile(path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    modify(members)
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)


@pytest.mark.parametrize("field", ["line_eraser_diameter", "vertex_eraser_diameter"])
@pytest.mark.parametrize("diameter", [0, 513])
def test_independent_eraser_sizes_reject_out_of_range_archives(
    pair_factory, tmp_path, field, diameter
):
    path = tmp_path / "invalid-size.dale"
    save_project(Session(pair_factory()), path, {field: diameter})
    with pytest.raises(ValueError, match="tool sizes"):
        load_project(path)


@pytest.mark.parametrize("distance", [0, 257, 1.5])
def test_auto_close_distance_rejects_invalid_archives(pair_factory, tmp_path, distance):
    path = tmp_path / "invalid-auto-close.dale"
    save_project(Session(pair_factory()), path, {"auto_close_distance_px": distance})
    with pytest.raises(ValueError, match="tool sizes"):
        load_project(path)


def test_archive_checksum_rejects_corrupted_history(pair_factory, tmp_path):
    path = tmp_path / "bad.dale"
    save_project(Session(pair_factory()), path)
    _rewrite(path, lambda members: members.update({"history.json": b"{}"}))
    with pytest.raises(ValueError, match="checksum"):
        load_project(path)


def test_archive_rejects_unexpected_path_without_extracting(pair_factory, tmp_path):
    path = tmp_path / "bad.dale"
    save_project(Session(pair_factory()), path)
    _rewrite(path, lambda members: members.update({"../escaped.txt": b"no"}))
    with pytest.raises(ValueError, match="five expected"):
        load_project(path)
    assert not (tmp_path.parent / "escaped.txt").exists()


def test_unknown_project_version_fails_without_guessing(pair_factory, tmp_path):
    path = tmp_path / "future.dale"
    save_project(Session(pair_factory()), path)

    def change(members):
        manifest = json.loads(members["manifest.json"])
        manifest["schema_version"] = 999
        members["manifest.json"] = json.dumps(manifest).encode()

    _rewrite(path, change)
    with pytest.raises(ValueError, match="version"):
        load_project(path)


def test_failed_save_is_atomic_and_source_files_are_protected(pair_factory, tmp_path, monkeypatch):
    session = Session(pair_factory())
    path = tmp_path / "existing.dale"
    path.write_bytes(b"existing project")
    monkeypatch.setitem(LIMITS, "sources/map.jpg", 1)
    with pytest.raises(ValueError, match="limit"):
        save_project(session, path)
    assert path.read_bytes() == b"existing project"
    assert not list(tmp_path.glob(".dale-project-*.tmp"))
    with pytest.raises(ValueError, match="source"):
        save_project(session, session.source.image_path)


def test_json_catalog_preserves_original_and_multiple_updated_documents(pair_factory, tmp_path):
    source = pair_factory()
    updated = json.dumps(dict(source.raw, name="Updated")).encode()
    session = Session(
        source,
        json_documents=(
            JsonDocument("edit-1", "Edited contours.json", "updated", updated),
            JsonDocument("edit-2", "Second edit.json", "updated", updated + b"\n"),
        ),
    )
    path = tmp_path / "versions.dale"
    save_project(session, path)
    documents = read_json_documents(path)
    assert len(documents) == 3
    assert documents[0].data == source.json_path.read_bytes()
    assert documents[0].kind == "original"
    assert documents[1:] == session.json_documents
    with load_project(path) as loaded:
        assert loaded.session.json_documents == session.json_documents
        save_project(loaded.session, tmp_path / "resaved.dale")
    assert [d.data for d in read_json_documents(tmp_path / "resaved.dale")] == [
        d.data for d in documents
    ]
    _rewrite(path, lambda members: members.update({"sources/json/edit-1.json": b"{}"}))
    with pytest.raises(ValueError, match="checksum"):
        read_json_documents(path)


def test_json_catalog_rejects_unexpected_paths_atomically(pair_factory, tmp_path):
    path = tmp_path / "protected.dale"
    path.write_bytes(b"existing")
    session = Session(
        pair_factory(), json_documents=(JsonDocument("../escape", "bad.json", "updated", b"{}"),)
    )
    with pytest.raises(ValueError, match="catalog"):
        save_project(session, path)
    assert path.read_bytes() == b"existing"
    assert not (tmp_path / "escape.json").exists()
