"""Real silhouette geometry, local cache, import choices and basal tree anchors."""

import json
import struct

import numpy as np
import pytest
from PySide6.QtWidgets import QMessageBox
from shapely import Polygon
from test_alchemist import sample as sample
from test_alchemist_interaction import editor as editor
from test_alchemist_terrain import terrain_payload

from dale.alchemist import (
    DISPLAY_CATEGORIES,
    AlchemistCancelled,
    DAData,
    import_map,
    surface_projection,
)
from dale.alchemist_library import AlchemistLibrary
from dale.alchemist_mesh import (
    NativeModels,
    build_profile,
    glb_meshes,
    layer_anchor,
    outlines,
    preview_image,
    project,
    transform,
    transformed,
)
from dale.datasets import DatasetCatalog
from dale.project_io import load_project, save_project


def leaning_tree():
    vertices = np.array(
        [
            (x + shift, y, z)
            for y, shift, radius in ((0, 2, 0.2), (5, 3, 0.2), (10, 5, 3))
            for x, z in ((-radius, -radius), (radius, -radius), (radius, radius), (-radius, radius))
        ]
    )
    triangles = [(0, 1, 2), (0, 2, 3), (8, 10, 9), (8, 11, 10)]
    for level in (0, 4):
        for i in range(4):
            a, b = level + i, level + (i + 1) % 4
            triangles.extend(((a, b, b + 4), (a, b + 4, a + 4)))
    return [(vertices, triangles)]


def test_ground_band_uses_trunk_or_crown_and_retains_real_base():
    profile = build_profile(leaning_tree())
    assert len(profile.layers) == 10
    base, index = profile.at_surface(0, 0, 1)
    crown, crown_index = profile.at_surface(8, 0, 1)
    assert index == 0 and crown_index == 8
    assert base.bounds == pytest.approx((1.8, -0.2, 2.4, 0.2), abs=1e-6)
    assert layer_anchor(base) == pytest.approx((2.1, 0), abs=1e-6)
    assert crown.area > base.area * 10
    assert profile.at_surface(18, 2, 2)[1] == 8
    assert profile.at_surface(2, 20, -2)[1] == 9
    assert profile.at_surface(30, 0, 1) == (None, None)
    assert profile.at_surface(-5, 0, 1)[1] == 0


def test_two_surfaces_select_different_bands_and_survive_import_reopen(
    sample, monkeypatch, tmp_path
):
    session, library, raw, _ = sample
    data = json.loads(raw)
    data.update(width=16, height=16)
    data["terrainLayers"] = [
        {"terrain": terrain_payload((8,) * 4)},
        {"terrain": terrain_payload((0,) * 4)},
    ]
    data["foundations"].append({"id": "underground", "layer": -1, "height": -2.2})
    data["objects"][1]["foundationId"] = "underground"
    for instance in data["buildingBlockInstances"]:
        instance.update(scale=1, height=0, rotation=180)
    profile = build_profile(leaning_tree())
    monkeypatch.setattr(library, "profiles", lambda *_: {"tree": profile})
    imported, geometry = import_map(
        json.dumps(data).encode(), "Two surfaces.dam", session, library, load_geometry=True
    )
    assert [o.layer for o in imported.objects] == [0, -1]
    assert [o.original_height_ft for o in imported.objects] == [0, 10]
    widths = []
    for obj in imported.objects:
        points = [
            point
            for edge, record in zip(geometry.walls, geometry.lineage, strict=True)
            if record.id in obj.roots
            for point in edge
        ]
        widths.append(max(p[0] for p in points) - min(p[0] for p in points))
    assert widths[0] > widths[1] * 5
    session.alchemist = imported
    session.add(geometry)
    target = tmp_path / "surfaces.dale"
    save_project(session, target)
    with load_project(target) as loaded:
        assert loaded.session.alchemist == imported
        assert loaded.session.geometry().walls == geometry.walls


def test_vertical_trunk_bands_have_solid_caps():
    meshes = leaning_tree()
    vertices = meshes[0][0].copy()
    for level in range(3):
        vertices[level * 4 : (level + 1) * 4, 0] = [-0.2, 0.2, 0.2, -0.2]
        vertices[level * 4 : (level + 1) * 4, 2] = [-0.2, -0.2, 0.2, 0.2]
    profile = build_profile([(vertices, meshes[0][1])])
    assert all(s.area == pytest.approx(0.16, abs=1e-6) for s in profile.layers)


def test_relief_is_sampled_at_real_contour_base_instead_of_model_origin():
    class Slope:
        def for_layer(self, layer):
            return self

        def at(self, x, y):
            return x

    profile = build_profile(leaning_tree())
    instance = {"center": {"x": 1, "y": 1}, "scale": 1, "rotation": 180}
    shape, ground = surface_projection(profile, Slope(), instance, {"height": 0}, {}, 0, 1)
    assert 3 < ground < 4
    assert shape == profile.layers[3]


def test_same_model_instances_choose_different_ground_bands(sample, monkeypatch):
    session, library, raw, _ = sample
    entry = library.resolve(["tree"])["tree"]
    entry["model"]["Id"] = "NATIVE#test"
    with library._connect() as db:
        db.execute("UPDATE metadata SET payload=? WHERE id=?", (json.dumps(entry), "tree"))
    monkeypatch.setattr(NativeModels, "__init__", lambda *_: None)
    monkeypatch.setattr(NativeModels, "meshes", lambda *_: leaning_tree())
    data = json.loads(raw)
    data.update(width=16, height=16)
    data["buildingBlockInstances"][0]["height"] = -8
    for instance in data["buildingBlockInstances"]:
        instance["rotation"] = 180  # Keep the leaning mesh inside this synthetic map.
    imported, geometry = import_map(
        json.dumps(data).encode(), "Buried.dam", session, library, load_geometry=True
    )
    areas = []
    for obj in imported.objects:
        points = [
            edge[0]
            for edge, r in zip(geometry.walls, geometry.lineage, strict=True)
            if r.id in obj.roots
        ]
        areas.append(Polygon(points).area)
    assert imported.objects[0].block_id == imported.objects[1].block_id
    assert areas[0] > areas[1]


def test_projection_retains_concavity_detached_parts_and_simplifies():
    vertices = [
        (0, 0, 0),
        (3, 0, 0),
        (3, 0, 1),
        (1, 0, 1),
        (1, 0, 3),
        (0, 0, 3),
        (5, 0, 0),
        (6, 0, 0),
        (5, 0, 1),
    ]
    shape = project([(vertices, [(0, 1, 3), (1, 2, 3), (0, 3, 5), (3, 4, 5), (6, 7, 8)])])
    assert shape.geom_type == "MultiPolygon"
    assert shape.area == pytest.approx(5.5)
    rings = outlines(shape, 0.5)
    assert len(rings) == 2
    assert sum(Polygon(r).area for r in rings) == pytest.approx(shape.area)
    assert all(len(r) < 10 for r in rings)


def test_simplification_removes_numeric_seam_holes_but_keeps_visible_holes():
    shape = Polygon(
        [(0, 0), (10, 0), (10, 10), (0, 10)],
        [
            [(1, 1), (1.000001, 1), (1.000001, 1.000001), (1, 1.000001)],
            [(3, 3), (5, 3), (5, 5), (3, 5)],
        ],
    )
    rings = outlines(shape, 10)
    assert len(rings) == 2
    assert Polygon(rings[1]).area == 4


def make_glb(path, *, uri=None):
    vertices = np.array([(0, 0, 0), (2, 0, 0), (1, 0, 1), (0, 0, 2)], dtype="<f4")
    indices = np.array([0, 1, 2, 0, 2, 3], dtype="<u2")
    binary = vertices.tobytes() + indices.tobytes()
    doc = dict(
        asset={"version": "2.0"},
        buffers=[{"byteLength": len(binary)}],
        bufferViews=[
            {"buffer": 0, "byteLength": 48},
            {"buffer": 0, "byteOffset": 48, "byteLength": 12},
        ],
        accessors=[
            {"bufferView": 0, "componentType": 5126, "count": 4, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5123, "count": 6, "type": "SCALAR"},
        ],
        meshes=[{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        nodes=[{"mesh": 0, "translation": [1, 0, 0]}],
        scenes=[{"nodes": [0]}],
        scene=0,
    )
    if uri:
        doc["buffers"][0]["uri"] = uri
    data = json.dumps(doc).encode()
    data += b" " * ((-len(data)) % 4)
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, 28 + len(data) + len(binary))
        + struct.pack("<II", len(data), 0x4E4F534A)
        + data
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )


def test_glb_node_and_native_transforms_without_external_access(tmp_path):
    path = tmp_path / "shape.glb"
    make_glb(path)
    shape = project(glb_meshes(path, {"x": 4}, 2))
    assert shape.bounds == pytest.approx((-2, 0, 2, 4))
    assert shape.area == pytest.approx(8)
    make_glb(path, uri="https://invalid.example/model.bin")
    with pytest.raises(ValueError, match="External"):
        glb_meshes(path)


def test_model_transforms_reject_invalid_geometry():
    with pytest.raises(ValueError):
        transform(rotation=(0, 0, 0, 0))
    with pytest.raises(ValueError):
        transformed([[float("nan"), 0, 0]], np.eye(4))
    with pytest.raises(ValueError):
        project([([(0, 0, 0)], [(0, 1, 2)])])


def test_preview_contains_mask_color_overlay_and_basal_marker():
    import io

    from PIL import Image

    meshes = leaning_tree()
    meshes = [(v, faces, (0.1, 0.7, 0.2)) for v, faces in meshes]
    shape = build_profile(meshes).layers[0]
    anchor = layer_anchor(shape)
    image = Image.open(io.BytesIO(preview_image(shape, anchor, meshes)))
    assert image.size == (384, 256)
    pixels = np.asarray(image)
    assert np.any(
        (pixels[:, :, 1] > pixels[:, :, 0] + 20) & (pixels[:, :, 1] > pixels[:, :, 2] + 20)
    )
    assert np.any(np.all(pixels == (255, 180, 0), axis=2))


def test_profile_cache_import_and_offline_project(sample, monkeypatch, tmp_path):
    session, library, raw, _ = sample
    data = {**json.loads(raw), "width": 16, "height": 16}
    for instance in data["buildingBlockInstances"]:
        instance["rotation"] = 180
    raw = json.dumps(data).encode()
    entry = library.resolve(["tree"])["tree"]
    entry["model"]["Id"] = "NATIVE#test"
    with library._connect() as db:
        db.execute("UPDATE metadata SET payload=? WHERE id=?", (json.dumps(entry), "tree"))
    calls = []
    monkeypatch.setattr(NativeModels, "__init__", lambda self, path: calls.append(path))
    monkeypatch.setattr(NativeModels, "meshes", lambda self, identifier: leaning_tree())
    imported, geometry = import_map(raw, "Tree.dam", session, library, load_geometry=True)
    assert len(calls) == 1
    assert len(imported.objects[0].roots) < 24
    assert [o.original_size for o in imported.objects] == [0.5, 1]
    offline = AlchemistLibrary(library.path)
    again, other = import_map(raw, "Tree.dam", session, offline, load_geometry=True)
    assert again == imported and other.walls == geometry.walls and len(calls) == 1
    session.alchemist = imported
    session.add(geometry)
    path = tmp_path / "geometry.dale"
    save_project(session, path)
    with load_project(path) as restored:
        assert restored.session.geometry().walls == geometry.walls
    assert DAData.decode(json.loads(json.dumps(imported.encode()))) == imported
    offline.clear()
    with offline._connect() as db:
        assert db.execute("SELECT count(*) FROM model_profiles").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM model_previews").fetchone()[0] == 0


@pytest.mark.parametrize("category", ["bush", "rock"])
def test_plants_and_rocks_use_surface_band(sample, monkeypatch, category):
    session, library, raw, _ = sample
    entry = library.resolve(["tree"])["tree"]
    entry["model"]["Id"] = "NATIVE#test"
    entry["block"]["displayCategoryIds"] = [
        next(k for k, v in DISPLAY_CATEGORIES.items() if v == category)
    ]
    with library._connect() as db:
        db.execute("UPDATE metadata SET payload=? WHERE id=?", (json.dumps(entry), "tree"))
    monkeypatch.setattr(NativeModels, "__init__", lambda *_: None)
    monkeypatch.setattr(NativeModels, "meshes", lambda *_: leaning_tree())
    profiles = library.profiles({"tree": entry}, {}, lambda *_: None)
    assert profiles["tree"].layers[9].bounds[2] == 8
    data = json.loads(raw)
    for instance in data["buildingBlockInstances"]:
        instance["rotation"] = 180
    raw = json.dumps(data).encode()
    imported, geometry = import_map(raw, "Plant.dam", session, library, load_geometry=True)
    assert imported.objects[0].category == category
    assert max(p[0] for e in geometry.walls for p in e) < 1000


def test_optional_geometry_falls_back_without_rejecting_import(sample, monkeypatch):
    session, library, raw, _ = sample
    monkeypatch.setattr(
        library,
        "_workshop_meshes",
        lambda *_: (_ for _ in ()).throw(ValueError("Model is unavailable.")),
    )
    data, geometry = import_map(raw, "Fallback.dam", session, library, load_geometry=True)
    assert len(data.objects[0].roots) == 24
    assert geometry.walls == session.geometry().walls
    assert library.geometry_unavailable


def test_native_batch_releases_each_mesh_but_reuses_reader(sample, monkeypatch):
    import weakref

    from dale.alchemist_library import _NativeBatch

    library = sample[1]
    entry = library.resolve(["tree"])["tree"]
    entries = {
        key: {"block": entry["block"], "model": {**entry["model"], "Id": "NATIVE#" + key}}
        for key in ("one", "two")
    }
    readers, arrays, closed = [], [], []

    class Reader:
        def __init__(self, path):
            readers.append(self)

        def meshes(self, key):
            assert all(reference() is None for reference in arrays)
            meshes = leaning_tree()
            arrays.append(weakref.ref(meshes[0][0]))
            return meshes

        def close(self):
            closed.append(self)

    def memory():
        assert all(reference() is None for reference in arrays)
        return 100 * 1024**2, 1024**3

    monkeypatch.setattr("dale.alchemist_mesh.NativeModels", Reader)
    monkeypatch.setattr(_NativeBatch, "memory", staticmethod(memory))
    profiles = library.profiles(entries, {}, lambda *_: None)
    assert set(profiles) == set(entries)
    assert len(readers) == 1 and closed == readers
    assert all(reference() is None for reference in arrays)
    assert library.geometry_reader_restarts == 0


def test_native_batch_restarts_only_for_retained_growth(monkeypatch):
    from dale.alchemist_library import _NativeBatch

    readers, closed = [], []

    class Reader:
        def __init__(self, path):
            readers.append(self)

        def meshes(self, key):
            return key

        def close(self):
            closed.append(self)

    # Stable, two growing models, still high after GC, then a fresh reader baseline.
    values = iter((100, 100, 180, 260, 260, 110, 110))
    monkeypatch.setattr("dale.alchemist_mesh.NativeModels", Reader)
    monkeypatch.setattr(
        _NativeBatch, "memory", staticmethod(lambda: (next(values) * 1024**2, 1024**3))
    )
    with _NativeBatch(None) as batch:
        for key in ("first", "second", "third", "fourth"):
            assert batch.meshes(key) == key
            batch.release_model()
        assert batch.restarts == 1
    assert len(readers) == 2 and closed == readers


def test_projection_cancellation_closes_reader_and_is_not_a_model_fallback(sample, monkeypatch):
    library = sample[1]
    entry = library.resolve(["tree"])["tree"]
    entry["model"]["Id"] = "NATIVE#cancel-test"
    closed = []

    class Reader:
        def __init__(self, path):
            pass

        def meshes(self, key):
            return leaning_tree()

        def close(self):
            closed.append(True)

    class Report:
        checks = 0

        def __call__(self, *_):
            pass

        def check_cancel(self):
            self.checks += 1
            if self.checks == 4:
                raise AlchemistCancelled()

    monkeypatch.setattr("dale.alchemist_mesh.NativeModels", Reader)
    with pytest.raises(AlchemistCancelled):
        library.profiles({"tree": entry}, {}, Report())
    assert closed == [True]
    with library._connect() as db:
        assert db.execute("SELECT count(*) FROM model_profiles").fetchone()[0] == 0


def test_cancelled_import_leaves_dataset_unchanged(editor, sample, monkeypatch, tmp_path):
    path = tmp_path / "Cancel.dam"
    path.write_bytes(sample[2])
    catalog = DatasetCatalog(editor.view.session)
    view = catalog.current
    before, data = view.session.geometry(), view.session.alchemist
    protected = set(catalog.protected_inputs)
    editor.question = lambda *_: QMessageBox.StandardButton.Yes

    def cancel(*_):
        raise AlchemistCancelled()

    monkeypatch.setattr(editor, "load_alchemist_with_progress", cancel)
    assert not editor.import_alchemist(catalog, catalog.active_key, path)
    assert view.session.geometry() == before and view.session.alchemist == data
    assert catalog.protected_inputs == protected


@pytest.mark.parametrize(
    "answer",
    [
        QMessageBox.StandardButton.Yes,
        QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Cancel,
    ],
)
def test_import_question_is_independent_and_cancellation_is_atomic(
    editor, sample, monkeypatch, tmp_path, answer
):
    _, _, raw, _ = sample
    path = tmp_path / "Input.dam"
    path.write_bytes(raw)
    window = editor
    catalog = DatasetCatalog(window.view.session)
    identifier = catalog.active_key
    view = catalog.views[identifier]
    before = view.session.geometry()
    data = view.session.alchemist
    calls = []
    window.question = lambda *_: answer
    monkeypatch.setattr(
        window,
        "load_alchemist_with_progress",
        lambda raw, path, session, library, flag: calls.append(flag) or (data, before),
    )
    monkeypatch.setattr("dale.alchemist_ui.discover_installations", lambda *_: ())
    result = window.import_alchemist(catalog, identifier, path)
    assert calls == (
        []
        if answer == QMessageBox.StandardButton.Cancel
        else [answer == QMessageBox.StandardButton.Yes]
    )
    assert result == (answer != QMessageBox.StandardButton.Cancel)
    assert view.session.geometry() == before
