import hashlib
import json
import zipfile

import pytest

from dale.autoclose import AutoCloseIndex
from dale.editing import add_line, delete_vertex, hit_edge, insert_vertex, move_vertex
from dale.project_io import load_project, save_project
from dale.provenance import edge_key
from dale.region_transform import plan_region_transform
from dale.session import Session


def test_exact_json_identity_keeps_original_array_indices_and_foundry_ids(pair_factory):
    source = pair_factory(
        walls=[
            {"c": [1, 1, 1, 1]},
            {"_id": "wallA", "c": [0, 0, 100, 0]},
            {"c": [100, 0, 100, 200]},
        ]
    )
    geometry = Session(source).geometry()
    digest = hashlib.sha256(source.json_path.read_bytes()).hexdigest()
    first, second = geometry.lineage
    assert first.sources[0].pointer == "/walls/1"
    assert first.sources[0].json_sha256 == digest
    assert first.sources[0].foundry_id == "wallA"
    assert first.id == f"sha256:{digest}#/walls/1"
    assert second.sources[0].wall_index == 2
    assert geometry.lineage == Session(source).geometry().lineage


def test_splits_moves_merges_and_contact_nodes_keep_parent_graph(pair_factory):
    source = pair_factory(walls=[{"c": [0, 0, 100, 0]}])
    original = Session(source).geometry()
    root = original.lineage[0]
    split = insert_vertex(original, hit_edge(original, (40, 0), 1))
    assert all(r.parents == (root.id,) and r.sources == root.sources for r in split.lineage)
    node = next(v for v in split.vertex_lineage if v["point"] == (40, 0))
    assert root.id in node["parents"]
    moved = move_vertex(split, (40, 0), (40, 20))
    assert moved.lineage == split.lineage
    merged = delete_vertex(moved, (40, 20))
    assert set(merged.lineage[0].parents) == {r.id for r in split.lineage}
    assert merged.lineage[0].sources == root.sources
    catalog = {r.id: r for r in merged.ancestry}
    assert root.id in catalog and all(r.id in catalog for r in split.lineage)


def test_new_lines_inherit_both_contact_parents_and_descendants(pair_factory):
    geometry = Session(
        pair_factory(walls=[{"c": [0, 0, 100, 0]}, {"c": [0, 100, 100, 100]}])
    ).geometry()
    added = add_line(geometry, (40, 0), (40, 100))
    record = added.lineage[-1]
    assert record.origin == "editor" and len(record.parents) == 4
    assert {s.wall_index for s in record.sources} == {0, 1}
    split = insert_vertex(added, hit_edge(added, (40, 50), 1))
    descendants = [r for r in split.lineage if record.id in r.parents]
    assert len(descendants) == 2
    assert all(r.sources == record.sources for r in descendants)
    node = next(v for v in added.vertex_lineage if v["point"] == (40, 0))
    assert len(node["lines"]) == 3
    assert {s["wall_index"] for s in node["sources"]} == {0, 1}
    detached = add_line(added, (200, 200), (300, 200)).lineage[-1]
    assert detached.origin == "editor" and not detached.parents and not detached.sources


def test_later_point_contact_inherits_parent_and_materializes_contact_node(pair_factory):
    geometry = Session(pair_factory(walls=[{"c": [0, 0, 100, 0]}])).geometry()
    root = geometry.lineage[0]
    detached = add_line(geometry, (40, 40), (40, 80))
    moved = move_vertex(detached, (40, 40), (40, 0))
    record = moved.lineage[-1]
    assert record.sources == root.sources and root.id in record.parents
    node = next(v for v in moved.vertex_lineage if v["point"] == (40, 0))
    assert len(node["lines"]) == 3


@pytest.mark.parametrize("mutation", ["missing", "source", "parent"])
def test_current_archive_rejects_missing_or_invalid_provenance(pair_factory, tmp_path, mutation):
    session = Session(pair_factory())
    session.add(add_line(session.geometry(), (10, 40), (60, 40)))
    destination = tmp_path / "invalid-provenance.dale"
    save_project(session, destination)
    with zipfile.ZipFile(destination) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    history = json.loads(members["history.json"])
    operation = history["operations"][0]
    if mutation == "missing":
        operation.pop("lineage")
    elif mutation == "source":
        operation["lineage"][0]["sources"][0]["json_sha256"] = "0" * 64
    else:
        operation["lineage"][-1]["parents"].append("nonexistent")
        operation["ancestry"][-1]["parents"].append("nonexistent")
    members["history.json"] = json.dumps(history).encode()
    manifest = json.loads(members["manifest.json"])
    manifest["sha256"]["history.json"] = hashlib.sha256(members["history.json"]).hexdigest()
    members["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(destination, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    with pytest.raises(ValueError, match="provenance"):
        load_project(destination)


def test_autoclose_and_affine_transform_preserve_source_identity(pair_factory):
    source = pair_factory(
        size=(200, 200),
        walls=[
            {"c": [20, 20, 120, 20]},
            {"c": [120, 20, 120, 120]},
            {"c": [120, 120, 20, 120]},
            {"c": [20, 120, 20, 23]},
        ],
    )
    session = Session(source)
    original = session.geometry()
    closed = AutoCloseIndex(original, 5).all().apply(original)
    assert closed.lineage == original.lineage
    session.add(closed)
    cells = session.analysis().cells
    moved, _ = plan_region_transform(closed, cells, cells).apply(dx=10, angle=0.1)
    assert {r.id for r in moved.lineage} == {r.id for r in closed.lineage}
    assert {s.id for r in moved.lineage for s in r.sources} == {r.id for r in original.lineage}


def test_lineage_and_vertex_contacts_survive_zip_undo_redo(pair_factory, tmp_path):
    source = pair_factory()
    session = Session(source)
    session.add(add_line(session.geometry(), (10, 40), (60, 40)))
    session.add(move_vertex(session.geometry(), (10, 40), (15, 45)))
    future = session.geometry()
    session.undo()
    current = session.geometry()
    destination = tmp_path / "lineage.dale"
    save_project(session, destination)
    with zipfile.ZipFile(destination) as archive:
        history = json.loads(archive.read("history.json"))
        assert history["operations"][0]["vertices"]
    with load_project(destination) as loaded:
        assert loaded.session.geometry().lineage == current.lineage
        assert loaded.session.geometry().vertex_lineage == current.vertex_lineage
        loaded.session.redo()
        assert loaded.session.geometry().lineage == future.lineage
        assert loaded.session.geometry().ancestry == future.ancestry
        assert loaded.session.geometry().vertex_lineage == future.vertex_lineage
        assert all(edge_key(edge) for edge in loaded.session.walls)


@pytest.mark.parametrize("version", [0, 1, 999])
def test_old_and_unknown_project_formats_are_rejected(pair_factory, tmp_path, version):
    destination = tmp_path / "unsupported.dale"
    save_project(Session(pair_factory()), destination)
    with zipfile.ZipFile(destination) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(members["manifest.json"])
    manifest["schema_version"] = version
    members["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(destination, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    with pytest.raises(ValueError, match="Older projects are not supported"):
        load_project(destination)
