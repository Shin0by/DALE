"""Archives contain applied state; old undo/redo geometry is never deserialized."""

import hashlib
import json
from zipfile import ZipFile

import pytest

from dale.editing import add_line
from dale.project_io import _encode, load_project, save_project
from dale.session import Session, Stroke


def test_save_keeps_live_undo_redo_but_open_has_only_current_state(pair_factory, tmp_path):
    session = Session(pair_factory())
    session.add(add_line(session.geometry(), (1, 2), (3, 4)))
    session.add(Stroke(((30, 40),), 5))
    session.add(add_line(session.geometry(), (10, 20), (30, 40)))
    session.undo()
    before = list(session.operations), list(session.future), session.history_floor
    path = tmp_path / "state.dale"
    save_project(session, path)
    assert (session.operations, session.future, session.history_floor) == before
    with ZipFile(path) as archive:
        state = json.loads(archive.read("history.json"))
        assert state["redo"] == []
        assert state["undo_floor"] == len(state["operations"])
        assert len([op for op in state["operations"] if op["type"] == "geometry"]) == 1
    with load_project(path) as loaded:
        current = loaded.session.geometry()
        assert current.walls == session.geometry().walls
        assert current.lineage == session.geometry().lineage
        loaded.session.undo()
        loaded.session.redo()
        assert loaded.session.geometry() == current and not loaded.session.future
        loaded.session.add(add_line(current, (50, 50), (70, 70)))
        loaded.session.undo()
        assert loaded.session.geometry() == current


def test_old_schema7_skips_obsolete_geometry_and_redo_before_decode(
    pair_factory, tmp_path, monkeypatch
):
    import dale.project_io as io

    session = Session(pair_factory())
    session.add(add_line(session.geometry(), (1, 2), (3, 4)))
    path = tmp_path / "old-history.dale"
    save_project(session, path)
    with ZipFile(path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    history = json.loads(members["history.json"])
    obsolete = {**_encode(Session(session.source).geometry()), "obsolete_test_marker": True}
    history["operations"].insert(0, obsolete)
    history["redo"] = [obsolete]
    history["undo_floor"] = 0
    members["history.json"] = json.dumps(history).encode()
    manifest = json.loads(members["manifest.json"])
    manifest["sha256"]["history.json"] = hashlib.sha256(members["history.json"]).hexdigest()
    members["manifest.json"] = json.dumps(manifest).encode()
    with ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    decode = io._decode

    def current_only(value):
        assert not value.get("obsolete_test_marker")
        return decode(value)

    monkeypatch.setattr(io, "_decode", current_only)
    with load_project(path) as loaded:
        assert loaded.session.geometry().walls == session.geometry().walls
        assert not loaded.session.future
        assert loaded.session.history_floor == len(loaded.session.operations)


def test_mapped_reader_skips_old_coordinate_payloads_and_keeps_escaped_text(tmp_path, monkeypatch):
    from dale.project_state_reader import StateReader, read_state_file

    path = tmp_path / "state.json"
    old = {"type": "geometry", "walls": [[[987654, 1], [2, 3]]], "lineage": []}
    current = {"type": "geometry", "walls": [[[1, 2], [3, 4]]], "lineage": []}
    state = {
        "operations": [old, current],
        "redo": [old],
        "undo_floor": 0,
        "ui": {"name": 'quoted " bracket ] slash \\ text'},
    }
    path.write_text(json.dumps(state), encoding="utf-8")
    decode = StateReader.decode

    def no_old_coordinates(self, span):
        assert b"987654" not in self.data[span[0] : span[1]]
        return decode(self, span)

    monkeypatch.setattr(StateReader, "decode", no_old_coordinates)
    loaded = read_state_file(path)
    assert loaded["operations"][0]["walls"] == current["walls"]
    assert loaded["ui"] == state["ui"]
    assert loaded["redo"] == []


@pytest.mark.parametrize(
    "payload",
    [
        b"{} trailing",
        b'{"operations":[]',
        b'{"operations":[],}',
        b'{"a":1,"a":2}',
        b'{"operations":[],"undo_floor":1}',
    ],
)
def test_state_reader_rejects_malformed_structure(tmp_path, payload):
    from dale.project_state_reader import read_state_file

    path = tmp_path / "invalid.json"
    path.write_bytes(payload)
    with pytest.raises(ValueError):
        read_state_file(path)
