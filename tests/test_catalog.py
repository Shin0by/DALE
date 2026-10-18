"""Synthetic catalog append, independent drafts, exact assets and rectangle evidence."""

import hashlib
import json
from dataclasses import replace
from zipfile import ZipFile

import pytest
from PIL import Image

from dale.catalog import SceneCatalog
from dale.editing import add_line, add_rectangle, rectangle_points
from dale.project_io import (
    JsonDocument,
    append_project_document,
    current_contours_document,
    load_project,
    read_json_documents,
    save_project,
)
from dale.region_transform import copy_regions
from dale.scene import load_pair
from dale.session import Session, Stroke


def payloads(path):
    with ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def extra_set(tmp_path):
    image = tmp_path / "second-floor.png"
    Image.new("RGBA", (150, 120), (30, 80, 210, 180)).save(image)
    session = Session(load_pair(image))
    session.add(add_rectangle(session.geometry(), (15, 20), (85, 100)))
    return session


def test_append_preserves_every_existing_payload_and_exact_image(pair_factory, tmp_path):
    base = Session(pair_factory())
    base.add(Stroke(((35, 60),), 4))
    path = tmp_path / "target.dale"
    save_project(base, path, {"mode": "Erase", "zoom": 1.25})
    before = payloads(path)
    incoming = extra_set(tmp_path)
    doc, added = append_project_document(path, current_contours_document(incoming))
    assert added and doc.name == "second-floor.json"
    after = payloads(path)
    assert all(after[key] == data for key, data in before.items() if key != "manifest.json")
    assert after[doc.image_member] == incoming.source.image_path.read_bytes()
    assert hashlib.sha256(after[doc.image_member]).hexdigest() in doc.image_member
    with load_project(path) as loaded:
        assert loaded.session.operations == base.operations
        assert loaded.session.source.json_name == "source.json"
        assert loaded.session.source.image_name == "source.jpg"
        assert loaded.catalog.active_key == loaded.catalog.base_key == ("source", "source-image")
        assert loaded.session.json_documents[0].name == doc.name
    exact = path.read_bytes()
    assert append_project_document(path, current_contours_document(incoming))[1] is False
    assert path.read_bytes() == exact
    incoming.add(add_line(incoming.geometry(), (5, 5), (12, 8)))
    assert append_project_document(path, current_contours_document(incoming))[1]
    with ZipFile(path) as archive:
        assert len([n for n in archive.namelist() if n.startswith("sources/images/")]) == 1


def test_independent_drafts_rename_redo_and_creation_pair_roundtrip(pair_factory, tmp_path):
    path = tmp_path / "catalog.dale"
    save_project(Session(pair_factory()), path)
    doc, _ = append_project_document(path, current_contours_document(extra_set(tmp_path)))
    with load_project(path) as loaded:
        catalog = loaded.catalog
        image_id = next(key for key in catalog.images if key != "source-image")
        view = catalog.activate(doc.id, image_id)
        view.session.add(add_line(view.session.geometry(), (4, 5), (9, 10)))
        view.session.add(Stroke(((30, 40),), 5))
        view.session.undo()
        catalog.rename("Second floor draft")
        edited, future = list(view.session.operations), list(view.session.future)
        assert catalog.activate(None, image_id).session.source.json_bytes is None
        assert catalog.activate(doc.id, None).session.source.image_path is None
        assert catalog.activate(doc.id, image_id).session.operations == edited
        save_project(view.session, path, {"mode": "New rectangle"}, catalog=catalog)
    with load_project(path) as loaded:
        catalog = loaded.catalog
        assert catalog.active_key == catalog.base_key
        assert catalog.current.session.source.name == "source.json"
        view = catalog.activate(doc.id, image_id)
        assert view.name == "Second floor draft"
        assert view.session.operations == edited and view.session.future == future
        assert view.ui["mode"] == "New rectangle"
        view.session.redo()
        assert len(view.session.operations) == len(edited) + 1
        assert catalog.snapshot().name == "Second floor draft.json"
    snapshots = read_json_documents(path)
    assert any(d.name == "Second floor draft.json" and d.is_current for d in snapshots)


@pytest.mark.parametrize("kind", ["image", "json"])
def test_single_creation_asset_remains_default(pair_factory, tmp_path, kind):
    source = pair_factory()
    source = load_pair(source.image_path) if kind == "image" else load_pair(None, source.json_path)
    path = tmp_path / f"{kind}.dale"
    save_project(Session(source), path)
    append_project_document(path, current_contours_document(extra_set(tmp_path)))
    with load_project(path) as loaded:
        assert loaded.catalog.base_key == (
            (None, "source-image") if kind == "image" else ("source", None)
        )
        loaded.catalog.activate(None, None)
        save_project(loaded.catalog.current.session, path, catalog=loaded.catalog)
    with load_project(path) as loaded:
        assert bool(loaded.session.source.image_path) == (kind == "image")
        assert bool(loaded.session.source.json_bytes) == (kind == "json")


def test_failed_append_leaves_target_unchanged_and_cleans_staging(pair_factory, tmp_path):
    path = tmp_path / "target.dale"
    save_project(Session(pair_factory()), path)
    before = path.read_bytes()
    doc = current_contours_document(extra_set(tmp_path))
    with pytest.raises((ValueError, json.JSONDecodeError)):
        append_project_document(path, replace(doc, data=b"invalid JSON"))
    assert path.read_bytes() == before
    data = payloads(path)
    data["history.json"] += b" "
    with ZipFile(path, "w") as archive:
        for member, content in data.items():
            archive.writestr(member, content)
    corrupt = path.read_bytes()
    with pytest.raises(ValueError, match="checksum"):
        append_project_document(path, doc)
    assert path.read_bytes() == corrupt
    assert not list(tmp_path.glob(".dale-append-*"))


def test_rectangle_four_sides_lineage_undo_and_degenerate(pair_factory):
    session = Session(pair_factory(walls=[]))
    initial = session.geometry()
    corners = rectangle_points((65, 90), (15, 30))
    geometry = add_rectangle(initial, corners[0], corners[2])
    assert geometry.walls == tuple(zip(corners, corners[1:], strict=False))
    assert len(geometry.lineage) == 4
    assert all(not record.sources for record in geometry.lineage)
    session.add(geometry)
    assert session.analysis().faces == 1
    session.undo()
    assert session.geometry() == initial
    session.redo()
    assert session.geometry() == geometry
    assert add_rectangle(initial, (1, 2), (1, 8)) == initial


def test_catalog_rejects_unknown_selection_names_and_view_keys(pair_factory):
    catalog = SceneCatalog(Session(pair_factory()))
    with pytest.raises(ValueError):
        catalog.activate("unknown", None)
    for name in (" ", "x" * 252):
        with pytest.raises(ValueError):
            catalog.rename(name)
    with pytest.raises(ValueError, match="Invalid|Duplicate"):
        catalog.restore({"version": 1, "views": [{"json": "source", "image": "source-image"}]})


def test_copy_minimum_cells_excludes_branches_and_preserves_stationary_records(pair_factory):
    session = Session(pair_factory())
    session.add(add_line(session.geometry(), (10, 270), (5, 290)))
    analysis = session.analysis()
    clip = copy_regions(session.geometry(), analysis.cells, analysis.cells, analysis.joins)
    assert len(clip.edges) == 4
    before = session.geometry()
    pasted = clip.paste(before, 75, 0)
    assert pasted.walls[: len(before.walls)] == before.walls
    assert pasted.lineage[: len(before.lineage)] == before.lineage
    assert len(pasted.walls) == len(before.walls) + 4
    assert clip.paste(pasted, 75, 0) == pasted
    assert all(r.parents for r in pasted.lineage[-4:])


def test_concurrently_changed_append_target_is_not_replaced(pair_factory, tmp_path, monkeypatch):
    import dale.project_io as io

    path = tmp_path / "concurrent.dale"
    save_project(Session(pair_factory()), path)
    document = current_contours_document(extra_set(tmp_path))
    original_hash, calls = io._hash, 0

    def concurrent_hash(target):
        nonlocal calls
        if target == path:
            calls += 1
            if calls == 2:
                path.write_bytes(b"external writer owns this newer file")
        return original_hash(target)

    monkeypatch.setattr(io, "_hash", concurrent_hash)
    with pytest.raises(ValueError, match="changed during export"):
        append_project_document(path, document)
    assert path.read_bytes() == b"external writer owns this newer file"
    assert not list(tmp_path.glob(".dale-append-*"))


def test_save_detects_an_image_changed_during_writing(pair_factory, tmp_path, monkeypatch):
    path = tmp_path / "existing.dale"
    source = pair_factory()
    save_project(Session(source), path)
    before = path.read_bytes()
    original_write = ZipFile.write

    def write_changed(archive, filename, *args, **kwargs):
        if filename == source.image_path:
            Image.new("RGB", source.size, (9, 10, 11)).save(filename)
        return original_write(archive, filename, *args, **kwargs)

    monkeypatch.setattr(ZipFile, "write", write_changed)
    with pytest.raises(ValueError, match="changed while saving"):
        save_project(Session(source), path)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob(".dale-project-*"))


def test_copied_ancestry_accepts_exact_dimensionless_json_with_its_image(pair_factory, tmp_path):
    source = pair_factory()
    raw = dict(source.raw)
    del raw["width"], raw["height"]
    source.json_path.write_text(json.dumps(raw), encoding="utf-8")
    source = load_pair(source.image_path, source.json_path)
    original = Session(source)
    analysis = original.analysis()
    clip = copy_regions(original.geometry(), analysis.cells, analysis.cells)
    target = Session(
        load_pair(source.image_path),
        json_documents=(
            JsonDocument("origin", "dimensionless.json", "original", source.json_bytes),
        ),
    )
    target.add(clip.paste(target.geometry(), 0, 0))
    path = tmp_path / "dimensionless-ancestry.dale"
    save_project(target, path)
    with load_project(path) as loaded:
        assert loaded.session.geometry().lineage == target.geometry().lineage
    assert len(read_json_documents(path)) == 2
