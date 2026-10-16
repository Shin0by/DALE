import json
import zipfile

import pytest

from dale.editing import hit_edge, insert_vertex
from dale.project_io import LIMITS, load_project, save_project
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
            "pending_closure": [[10, 20]],
            "junction_policy": "remove",
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
        assert loaded.ui_state["pending_closure"] == ((10, 20),)
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
    with pytest.raises(ValueError, match="four expected"):
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
