import json
import zipfile

import pytest

from dale.editing import add_line, hit_edge, insert_vertex
from dale.project_io import LIMITS, JsonDocument, load_project, read_json_documents, save_project
from dale.raster import render_alpha
from dale.session import Closure, Session, Stroke


@pytest.mark.parametrize(
    "key",
    [
        "figure_point_alignment",
        "figure_guide_alignment",
        "region_point_alignment",
        "region_guide_alignment",
    ],
)
def test_section_alignment_booleans_are_validated_and_roundtrip(pair_factory, tmp_path, key):
    from dale.project_io import _load_ui

    session = Session(pair_factory())
    path = tmp_path / "alignment.dale"
    for value in (False, True):
        save_project(session, path, {key: value})
        with load_project(path) as loaded:
            assert loaded.ui_state[key] is value
            for section in ("figure", "region"):
                for kind in ("point", "guide"):
                    other = f"{section}_{kind}_alignment"
                    if other != key:
                        assert loaded.ui_state[other] is (kind == "point")
    for invalid in (0, "yes", None):
        with pytest.raises(ValueError, match="alignment preference"):
            _load_ui({key: invalid})


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
    with pytest.raises(ValueError, match="expected"):
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
    monkeypatch.setitem(LIMITS, "sources/map.image", 1)
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


def _without_cached_contours(members):
    manifest = json.loads(members["manifest.json"])
    identifier = manifest.pop("current_contours_id")
    manifest["json_documents"] = [d for d in manifest["json_documents"] if d["id"] != identifier]
    member = f"sources/json/{identifier}.json"
    members.pop(member)
    manifest["sha256"].pop(member)
    members["manifest.json"] = json.dumps(manifest).encode()


@pytest.mark.parametrize("cached", [True, False])
def test_applied_contours_catalog_recovers_edits_without_decoding_image(
    pair_factory, tmp_path, monkeypatch, cached
):
    from PIL import Image

    from dale.provenance import geometry_edges
    from dale.scene import load_pair

    source = pair_factory(width=160, height=600, background={"offsetX": 7, "offsetY": 9})
    session = Session(source, origin=(3, 5), contour_offset=11)
    session.add(insert_vertex(session.geometry(), hit_edge(session.geometry(), (10, 3), 5)))
    session.add(add_line(session.geometry(), (15, 16), (17, 18)))
    session.add(add_line(session.geometry(), (21, 22), (23, 24)))
    session.undo()
    path = tmp_path / "edited.dale"
    save_project(session, path)
    if not cached:
        _rewrite(path, _without_cached_contours)
    before = path.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(Image.Image, "load", lambda *args: pytest.fail("Decoded raster pixels"))
        documents = read_json_documents(path)
    assert path.read_bytes() == before
    assert documents[0].data == source.json_bytes
    snapshot = documents[-1]
    assert snapshot.kind == "updated" and len(documents) == 2
    destination = tmp_path / "contours.json"
    destination.write_bytes(snapshot.data)
    current = load_pair(source.image_path, destination)
    assert current.image_walls() == geometry_edges(session.walls, session.closures)
    assert current.size == source.size and current.cell_pixels == source.cell_pixels
    with load_project(path) as loaded:
        assert loaded.session.operations == session.operations
        assert loaded.session.future == session.future
        assert loaded.session.json_documents == ()
        resaved = tmp_path / "resaved.dale"
        save_project(loaded.session, resaved)
    assert read_json_documents(resaved)[-1] == snapshot


def test_contours_cache_tracks_undo_redo_and_keeps_explicit_catalog_entries(pair_factory, tmp_path):
    stored = JsonDocument("current-contours", "User snapshot.json", "updated", b'{"walls":[]}')
    session = Session(pair_factory(), json_documents=(stored,))
    session.add(add_line(session.geometry(), (2, 3), (4, 5)))
    path = tmp_path / "current.dale"
    save_project(session, path)
    documents = read_json_documents(path)
    assert documents[1] == stored and documents[-1].id == "current-contours-1"
    with load_project(path) as loaded:
        loaded.session.undo()
        save_project(loaded.session, path)
        assert read_json_documents(path)[1:] == (stored,)
        loaded.session.redo()
        save_project(loaded.session, path)
    assert read_json_documents(path)[-1] == documents[-1]


def test_contours_cache_cannot_disagree_with_history_even_with_valid_checksum(
    pair_factory, tmp_path
):
    import hashlib

    session = Session(pair_factory())
    session.add(add_line(session.geometry(), (2, 3), (4, 5)))
    path = tmp_path / "mismatched.dale"
    save_project(session, path)

    def tamper(members):
        manifest = json.loads(members["manifest.json"])
        member = f"sources/json/{manifest['current_contours_id']}.json"
        members[member] = b'{"walls":[]}'
        manifest["sha256"][member] = hashlib.sha256(members[member]).hexdigest()
        members["manifest.json"] = json.dumps(manifest).encode()

    _rewrite(path, tamper)
    for reader in (load_project, read_json_documents):
        with pytest.raises(ValueError, match="does not match"):
            reader(path)


def test_current_schema_catalog_checks_history_when_deriving_contours(pair_factory, tmp_path):
    session = Session(pair_factory())
    session.add(add_line(session.geometry(), (2, 3), (4, 5)))
    path = tmp_path / "bad-history.dale"
    save_project(session, path)
    _rewrite(path, _without_cached_contours)
    _rewrite(path, lambda members: members.update({"history.json": b"{}"}))
    with pytest.raises(ValueError, match="checksum"):
        read_json_documents(path)


@pytest.mark.parametrize("field", ["right_angle_distance_px", "contour_alignment_distance_px"])
@pytest.mark.parametrize("value", [0, 10000, 1.5, True])
def test_alignment_tolerances_reject_invalid_values(pair_factory, tmp_path, field, value):
    path = tmp_path / "bad-alignment.dale"
    save_project(Session(pair_factory()), path, {field: value})
    with pytest.raises(ValueError):
        load_project(path)
