"""Large valid project JSON is preserved without prototype byte-size ceilings."""

import hashlib
import json
from dataclasses import replace
from zipfile import ZipFile

import pytest

from dale.datasets import DatasetCatalog
from dale.project_io import (
    JsonDocument,
    _archive_manifest,
    append_project_document,
    load_project,
    save_project,
)
from dale.provenance import LineRecord
from dale.scene import scene_from_json
from dale.session import GeometryEdit, Session


def test_generated_snapshot_over_32_mib_saves_and_reopens_exactly(tmp_path, monkeypatch):
    from dale.project_io import LIMITS

    session = Session(
        replace(
            scene_from_json(b'{"width":1000,"height":1000,"walls":[]}'),
            json_name="Source.json",
        )
    )
    count = 120_000
    walls = tuple(((float(i), 0.0), (float(i), 1.0)) for i in range(count))
    records = tuple(LineRecord(f"editor:{i:06d}:" + "x" * 240) for i in range(count))
    session.add(GeometryEdit(walls, lineage=records))
    catalog = DatasetCatalog(session)
    path = tmp_path / "large-contours.dale"
    path.write_bytes(b"previous destination")
    # Reproduce the previous save failure with the exact former cap.
    with monkeypatch.context() as patch:
        patch.setitem(LIMITS, "sources/scene.json", 32 * 1024 * 1024)
        with pytest.raises(ValueError, match="current-contours.json"):
            save_project(session, path, catalog=catalog)
    assert path.read_bytes() == b"previous destination"
    assert len(session.operations) == 1
    save_project(session, path, catalog=catalog)
    assert len(session.operations) == 1 and session.history_floor == 0
    with ZipFile(path) as archive:
        assert archive.getinfo("sources/json/current-contours.json").file_size > 32 * 1024 * 1024
    with load_project(path) as loaded:
        actual = loaded.session.geometry()
        assert actual.walls == walls
        assert actual.lineage == records
        assert loaded.session.history_floor == len(loaded.session.operations)
        assert loaded.session.future == []


def test_catalog_over_128_mib_and_large_append_preserve_exact_bytes(pair_factory, tmp_path):
    session = Session(pair_factory())
    payload = b'{"width":80,"height":300,"walls":[]}' + b" " * (27 * 1024 * 1024)
    session.json_documents = tuple(
        JsonDocument(f"saved-{i}", f"Saved {i}.json", "updated", payload) for i in range(5)
    )
    path = tmp_path / "large-catalog.dale"
    save_project(session, path)
    incoming = payload + b" " * (6 * 1024 * 1024)
    added, changed = append_project_document(
        path, JsonDocument("incoming", "Large.json", "updated", incoming)
    )
    assert changed
    with load_project(path) as loaded:
        documents = {d.id: d.data for d in loaded.session.json_documents}
        assert documents[added.id] == incoming
        assert all(documents[f"saved-{i}"] == payload for i in range(5))
    with ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        member = f"sources/json/{added.id}.json"
        assert manifest["sha256"][member] == hashlib.sha256(incoming).hexdigest()


def test_encryption_validation_remains(pair_factory, tmp_path):
    path = tmp_path / "protected.dale"
    save_project(Session(pair_factory()), path)
    with ZipFile(path) as archive:
        archive.getinfo("sources/scene.json").flag_bits |= 1
        with pytest.raises(ValueError, match="Encrypted project member: sources/scene.json"):
            _archive_manifest(archive)
