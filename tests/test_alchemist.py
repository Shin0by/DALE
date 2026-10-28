"""Synthetic DA import, offline metadata, filtering, history and native JSON composition."""

import json
import os
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from dale.alchemist import (
    DISPLAY_CATEGORIES,
    DAData,
    _import_bounds,
    _outside_import_bounds,
    export_session,
    import_map,
    memberships,
    scale_category,
    scoped_geometry,
)
from dale.alchemist_library import (
    DATABASE,
    AlchemistLibrary,
    MissingAlchemistItems,
    steam_libraries,
)
from dale.datasets import DatasetCatalog
from dale.json_repair import repaired_json_bytes
from dale.project_io import load_project, save_project
from dale.session import Session
from dale.ui import MainWindow


@pytest.mark.parametrize(
    "rings,outside",
    [
        ([[(1, 1), (2, 1), (2, 2), (1, 1)]], False),
        ([[(-3, 1), (-2, 1), (-2, 2), (-3, 1)]], True),
        ([[(-2, 1), (1, -2), (-2, -2), (-2, 1)]], True),
        ([[(-2, 5), (12, 5)]], False),
        ([[(-2, 0), (0, 0)]], False),
        ([[(-2, -2), (12, -2), (12, 12), (-2, 12), (-2, -2)]], False),
        (
            [
                [(-2, -2), (12, -2), (12, 12), (-2, 12), (-2, -2)],
                [(-1, -1), (11, -1), (11, 11), (-1, 11), (-1, -1)],
            ],
            True,
        ),
        ([[(-3, 1), (-2, 1)], [(9, 5), (12, 5)]], False),
    ],
)
def test_import_bounds_use_whole_shape_and_preserve_crossing_touching_objects(rings, outside):
    assert _outside_import_bounds(rings, (0, 0, 10, 10)) is outside


def test_import_automatically_omits_only_fully_outside_objects(sample, tmp_path):
    session, library, raw, _ = sample
    data = json.loads(raw)
    data["buildingBlockInstances"][0]["center"] = {"x": -2, "y": 1}
    data["buildingBlockInstances"][1]["center"] = {"x": 4.25, "y": 3}
    imported, geometry = import_map(json.dumps(data).encode(), "Bounds.dam", session, library)
    assert [o.id for o in imported.objects] == ["large"]
    assert len(imported.objects[0].roots) == 24
    assert max(p[0] for edge in geometry.walls for p in edge) == pytest.approx(475)
    assert geometry.walls[0] == session.geometry().walls[0]  # Ordinary contours are not filtered.
    session.alchemist = imported
    session.add(geometry)
    path = tmp_path / "filtered.dale"
    save_project(session, path)
    with load_project(path) as loaded:
        assert loaded.session.alchemist == imported
        assert loaded.session.geometry().walls == geometry.walls


def test_json_bounds_take_priority_over_image_and_respect_export_coordinates(sample):
    session, library, raw, _ = sample
    session.source = replace(session.source, scene_size=(800, 800), background_offset=(100, 200))
    session.origin = (20, 0)
    assert _import_bounds(session) == (-60, -100, 340, 300)
    data = json.loads(raw)
    data["buildingBlockInstances"][0]["center"] = {"x": 3.8, "y": 2}
    imported, _ = import_map(json.dumps(data).encode(), "JSON bounds.dam", session, library)
    assert [o.id for o in imported.objects] == ["large"]
    session.source = replace(session.source, json_bytes=None)
    assert _import_bounds(session) == (0, 0, 400, 400)
    imported, _ = import_map(json.dumps(data).encode(), "Image bounds.dam", session, library)
    assert [o.id for o in imported.objects] == ["small", "large"]


@pytest.fixture
def sample(tmp_path, pair_factory):
    source = pair_factory(
        size=(400, 400), walls=[{"_id": "ordinarywall0001", "c": [20, 20, 80, 20]}]
    )
    executable = tmp_path / "Steam/steamapps/common/Dungeon Alchemist/Dungeon Alchemist.exe"
    database = executable.parent / DATABASE
    database.mkdir(parents=True)
    executable.touch()
    category = next(k for k, v in DISPLAY_CATEGORIES.items() if v == "tree")
    (database / "BuildingBlocks.json").write_text(
        json.dumps(
            [
                {
                    "Id": "tree",
                    "name": "Synthetic tree",
                    "modelId": "tree-model",
                    "displayCategoryIds": [category],
                },
            ]
        )
    )
    (database / "ModelStaticData.json").write_text(
        json.dumps(
            [
                {
                    "Id": "tree-model",
                    "colliderBounds": [
                        {"center": {"y": 1}, "extents": {"x": 0.25, "z": 0.25, "y": 1}}
                    ],
                },
            ]
        )
    )
    data = {
        "Version": 11,
        "width": 4,
        "height": 4,
        "foundations": [{"id": "ground", "height": 0, "layer": 0}],
        "walls": [],
        "objects": [
            {"id": "small", "foundationId": "ground", "buildingBlockInstanceId": "a"},
            {"id": "large", "foundationId": "ground", "buildingBlockInstanceId": "b"},
        ],
        "buildingBlockInstances": [
            {"id": "a", "blockId": "tree", "center": {"x": 1, "y": 1}, "scale": 1},
            {"id": "b", "blockId": "tree", "center": {"x": 3, "y": 3}, "scale": 2, "height": 2.4},
        ],
    }
    raw = json.dumps(data).encode()
    library = AlchemistLibrary(tmp_path / "cache.sqlite3", executable, workshop_roots=())
    session = Session(source)
    metadata, geometry = import_map(raw, "Synthetic.dam", session, library)
    session.alchemist = metadata
    session.add(geometry)
    return session, library, raw, source


def test_all_ids_resolve_from_cache_without_installation(sample):
    _, library, _, _ = sample
    offline = AlchemistLibrary(library.path)
    assert offline.resolve(["tree"])["tree"]["block"]["name"] == "Synthetic tree"
    offline.clear()
    with pytest.raises(MissingAlchemistItems):
        offline.resolve(["tree"])


def test_missing_workshop_does_not_change_the_dataset(sample):
    session, library, raw, _ = sample
    original = session.geometry()
    data = json.loads(raw)
    data["buildingBlockInstances"][0]["blockId"] = "absent"
    with pytest.raises(MissingAlchemistItems):
        import_map(json.dumps(data).encode(), "Missing.dam", session, library)
    assert session.geometry() == original


def test_steam_library_discovery_reads_vdf_without_write(tmp_path):
    steam = tmp_path / "Steam"
    (steam / "steamapps").mkdir(parents=True)
    vdf = steam / "steamapps/libraryfolders.vdf"
    vdf.write_text('"libraryfolders" { "0" { "path" "D:\\\\Maps\\\\SteamLibrary" } }')
    before = vdf.read_bytes()
    found = steam_libraries((steam,))
    assert str(found[1]) == r"D:\Maps\SteamLibrary"
    assert vdf.read_bytes() == before


def test_original_size_filter_is_reversible_and_independent_of_edits(sample):
    session, _, _, _ = sample
    data = session.alchemist
    assert [o.original_size for o in data.objects] == [0.5, 1.0]
    session.add(scale_category(session, "tree", 3))
    edited = session.geometry()
    settings = list(data.settings)
    settings[1] = (True, 0.75)
    session.alchemist = replace(data, settings=tuple(settings))
    assert len(scoped_geometry(session, scope="alchemist").walls) == 24
    session.alchemist = data
    assert len(scoped_geometry(session, scope="alchemist").walls) == 48
    assert session.geometry() == edited
    session.undo()
    assert session.geometry() != edited
    session.redo()
    assert session.geometry() == edited


def test_each_object_scales_around_its_own_current_center(sample):
    session, _, _, _ = sample
    before = session.geometry()
    after = scale_category(session, "tree", 2)
    assert after.walls[0] == before.walls[0]
    ownership = memberships(session.alchemist, before)
    for obj in session.alchemist.objects:
        indices = [i for i, owned in enumerate(ownership) if obj.id in owned]
        pts = [p for i in indices for p in before.walls[i]]
        center = tuple((min(p[a] for p in pts) + max(p[a] for p in pts)) / 2 for a in (0, 1))
        for i in indices:
            for a, b in zip(after.walls[i], before.walls[i], strict=True):
                assert a == pytest.approx(tuple(center[j] + 2 * (b[j] - center[j]) for j in (0, 1)))


def test_native_json_adds_only_enabled_da_preserves_original_fields(sample):
    session, _, _, _ = sample
    raw = json.loads(session.source.json_bytes)
    exported = json.loads(repaired_json_bytes(export_session(session))[0])
    assert len(exported["walls"]) == 49
    assert exported["walls"][0] == raw["walls"][0]
    assert {k: v for k, v in exported.items() if k != "walls"} == {
        k: v for k, v in raw.items() if k != "walls"
    }
    regular = json.loads(repaired_json_bytes(export_session(session, False))[0])
    assert regular == raw
    settings = list(session.alchemist.settings)
    settings[1] = (False, 0)
    session.alchemist = replace(session.alchemist, settings=tuple(settings))
    hidden = json.loads(repaired_json_bytes(export_session(session))[0])
    assert hidden == raw


def test_exact_dam_and_filters_survive_project_roundtrip_offline(sample, tmp_path):
    session, library, raw, _ = sample
    session.add(scale_category(session, "tree", 1.5))
    catalog = DatasetCatalog(session)
    path = tmp_path / "alchemist.dale"
    save_project(session, path, catalog=catalog)
    library.clear()
    with load_project(path) as loaded:
        restored = loaded.catalog.current.session
        assert restored.alchemist.source == raw
        assert restored.alchemist == session.alchemist
        assert restored.geometry().walls == session.geometry().walls
        assert restored.geometry().lineage == session.geometry().lineage
        assert len(scoped_geometry(restored, scope="alchemist").walls) == 48


def test_corrupt_embedded_dam_rejected(sample):
    data = sample[0].alchemist.encode()
    data["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="checksum"):
        DAData.decode(data)


def test_alchemist_mode_edits_only_da_and_switches_keep_regular_geometry(sample, tmp_path):
    session, _, _, source = sample
    app = QApplication.instance() or QApplication([])
    window = MainWindow(preferences_path=tmp_path / "preferences.json")
    window.can_discard = lambda: True
    try:
        assert window.load_sources(source.image_path, source.json_path)
        target = window.view.session
        target.alchemist = session.alchemist
        target.add(session.geometry())
        window.configure_json_repair(True)
        window.select_tool_set("alchemist")
        assert window.current_tool_set == "alchemist"
        assert window.json_repair_control.isChecked()
        assert not window.json_repair_control.isEnabled()
        assert len(window.view.editing_geometry().walls) == 48
        window.view.figure_line_ids = tuple(r.id for r in window.view.editing_geometry().lineage)
        window.view.transform_regions(scale=2)
        assert target.geometry().walls[0] == session.geometry().walls[0]
        window.select_tool_set("figures")
        assert len(window.view.editing_geometry().walls) == 1
        window.select_tool_set("regions")
        assert len(window.view.editing_geometry().walls) == 49
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_paste_creates_independent_category_membership_and_prunes_abandoned_redo(sample, tmp_path):
    from dale.alchemist import register_pasted_objects
    from dale.region_transform import copy_figures

    session, _, _, _ = sample
    before = session.geometry()
    obj = session.alchemist.objects[0]
    clip = copy_figures(before, obj.roots)
    after = register_pasted_objects(session, before, clip.paste(before, 30, 0), clip)
    session.add(after)
    pasted = session.alchemist.objects[-1]
    assert pasted.id != obj.id
    assert pasted.category == obj.category
    assert pasted.original_size == obj.original_size
    ownership = memberships(session.alchemist, after)
    assert all(own == {pasted.id} for own in ownership[-24:])
    session.undo()
    path = tmp_path / "undo-copy.dale"
    save_project(session, path, catalog=DatasetCatalog(session))
    with load_project(path) as loaded:
        restored = loaded.catalog.current.session
        restored.redo()
        assert len(scoped_geometry(restored, scope="alchemist").walls) == 48
        assert pasted not in restored.alchemist.objects
        assert not restored.future
    session.add(scale_category(session, "tree", 2))
    assert pasted not in session.alchemist.objects
    assert len(session.alchemist.objects) == 2


def test_json_replacement_preserves_hidden_da_and_immutable_source(sample, pair_factory):
    session, _, raw, _ = sample
    settings = list(session.alchemist.settings)
    settings[1] = (False, 2)
    session.alchemist = replace(session.alchemist, settings=tuple(settings))
    before = scoped_geometry(session, scope="alchemist_all")
    catalog = DatasetCatalog(session)
    incoming = Session(pair_factory(size=(400, 400), walls=[{"c": [10, 10, 10, 90]}]))
    catalog.replace_component(catalog.active_key, "json", incoming)
    updated = catalog.current.session
    assert updated.alchemist.source == raw
    assert scoped_geometry(updated, scope="alchemist_all").walls == before.walls
    assert len(scoped_geometry(updated, scope="combined").walls) == 1
    assert scoped_geometry(updated, scope="regular").walls == incoming.geometry().walls


@pytest.mark.parametrize("version", [6, 11])
def test_mirrored_scale_and_floor_height(sample, version):
    from dale.source_editing import source_layers
    from dale.wall_styles import geometry_styles, resolve_style

    session, library, raw, source = sample
    data = json.loads(raw)
    data["Version"] = version
    data["foundations"][0]["layer"] = -1
    data["buildingBlockInstances"][0]["scale"] = -1
    metadata, geometry = import_map(
        json.dumps(data).encode(), "Mirrored.dam", Session(source), library
    )
    session.alchemist = metadata
    session.add(geometry)
    assert metadata.objects[0].original_size == 0.5
    assert {o.layer for o in metadata.objects} == {-1}
    assert any(
        layer.key == "da-layer:-1" for layer in source_layers(source, geometry, alchemist=metadata)
    )
    styles = geometry_styles(geometry)
    wall = resolve_style(styles[metadata.objects[1].roots[0]][0], {})
    assert wall["flags"]["wall-height"]["bottom"] == pytest.approx(12)
    assert wall["flags"]["wall-height"]["top"] == pytest.approx(32)


def test_png_bytes_independent_of_json_source_choice(sample, tmp_path):
    from dale.overlay_export import export_overlays

    session = sample[0]
    first = export_overlays(session, tmp_path, json_contours="regular")
    second = export_overlays(session, tmp_path, json_contours="combined")
    assert {p.name: p.read_bytes() for p in first.glob("*.png")} == {
        p.name: p.read_bytes() for p in second.glob("*.png")
    }
    scenes = []
    for directory in (first, second):
        scenes.append(
            next(
                json.loads(p.read_bytes())
                for p in directory.glob("*.json")
                if "walls" in json.loads(p.read_bytes())
            )
        )
    assert len(scenes[0]["walls"]) == 1
    assert len(scenes[1]["walls"]) == 49


def test_sidebar_analysis_excludes_hidden_obstacles(sample):
    session = sample[0]
    assert len(session.analysis().cells) == 2
    settings = list(session.alchemist.settings)
    settings[1] = (False, 0)
    session.alchemist = replace(session.alchemist, settings=tuple(settings))
    assert not session.analysis().cells


def test_da_help_survives_repeated_language_switches(sample, tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(preferences_path=tmp_path / "preferences.json")
    try:
        for language in ("en", "ru", "en", "ru", "en"):
            window.set_language(language, persist=False)
            for action in (
                window.tool_set_actions["alchemist"],
                *window.alchemist_category_actions.values(),
            ):
                help_text = action.toolTip()
                assert help_text.splitlines()[0] == action.text()
                if language == "en":
                    assert help_text.count("Purpose:") == 1
                    assert not any("\u0400" <= c <= "\u04ff" for c in help_text)
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_locally_installed_workshop_metadata_is_cached(sample, tmp_path):
    _, library, _, _ = sample
    root = tmp_path / "workshop"
    directory = root / "123456/model"
    directory.mkdir(parents=True)
    metadata = library.resolve(["tree"])["tree"]
    block = dict(metadata["block"], Id="custom-tree")
    item = directory / "model.json"
    item.write_text(json.dumps({"configs": [block], "staticData": metadata["model"]}))
    before = item.read_bytes()
    local = AlchemistLibrary(library.path, library.executable, (root,))
    descriptions = {"custom-tree": {"description": {"publishedWorkshopId": 123456}}}
    assert local.resolve(["custom-tree"], descriptions)["custom-tree"]["block"] == block
    assert item.read_bytes() == before
    assert AlchemistLibrary(library.path).resolve(["custom-tree"])["custom-tree"]["block"] == block


def test_category_popup_cancel_apply_and_stationary_references(sample, tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(preferences_path=tmp_path / "preferences.json")
    window.can_discard = lambda: True
    session, _, _, source = sample
    try:
        window.load_sources(source.image_path, source.json_path)
        target = window.view.session
        target.alchemist = session.alchemist
        target.add(session.geometry())
        window.configure_json_repair(True)
        window.select_tool_set("alchemist")
        before = target.geometry()
        assert len(window.view.snapping_geometry(before).walls) == 49
        from dale.source_editing import layer_geometry

        da = window.view.editing_geometry()
        moving_point = da.walls[0][0]
        window.view._freeze_placement_targets(layer_geometry(da, range(24, 48)))
        assert window.view.guide_targets.nearest(moving_point, 0.01) is None
        assert window.view.guide_targets.nearest(before.walls[0][0], 0.01) == before.walls[0][0]
        window.set_alchemist_reference_display(False)
        assert len(window.view.snapping_geometry(before).walls) == 48
        window.show_alchemist_category_settings("tree")
        popup = window.tool_settings_popup
        assert hasattr(popup, "wall_export")
        assert not hasattr(popup, "alchemist_scale")
        popup.reject()
        assert target.geometry() == before
        window.show()
        window.view.figure_line_ids = target.alchemist.objects[0].roots
        window.toggle_slice_window(True)
        panel = window.slice_window
        panel.choose_all()
        panel.scale.setValue(200)
        panel.flush()
        window.show_alchemist_category_settings("tree")
        popup = window.tool_settings_popup
        popup.alchemist_minimum.setValue(0.75)
        popup.alchemist_height.setValue(4)
        popup.accept()
        assert target.alchemist.minimum_heights_ft == (0, 4, 0, 0)
        assert target.geometry().walls[0] == before.walls[0]
        assert len(window.view.editing_geometry().walls) == 24
        target.undo()
        assert target.geometry() == before
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_invalid_map_references_fail_before_library_access(sample):
    from dale.alchemist import read_map

    data = json.loads(sample[2])
    data["objects"][0]["foundationId"] = "missing"
    with pytest.raises(ValueError, match="reference"):
        read_map(json.dumps(data).encode())


def test_height_normalization_affects_all_exported_walls_only(sample, tmp_path):
    from dale.overlay_export import export_overlays

    session = sample[0]
    before = session.geometry()
    data = session.alchemist
    normal = export_overlays(session, tmp_path, height_normalization=(False, 0, 10))
    normalized = export_overlays(session, tmp_path, height_normalization=(True, -5, 19))
    assert {p.name: p.read_bytes() for p in normal.glob("*.png")} == {
        p.name: p.read_bytes() for p in normalized.glob("*.png")
    }
    result = next(
        json.loads(p.read_bytes())
        for p in normalized.glob("*.json")
        if "walls" in json.loads(p.read_bytes())
    )
    assert len(result["walls"]) == 49
    assert all(
        w["flags"]["wall-height"]["bottom"] == -5 and w["flags"]["wall-height"]["top"] == 19
        for w in result["walls"]
    )
    assert session.geometry() == before
    assert session.alchemist == data
    settings = list(data.settings)
    settings[1] = (False, 0)
    session.alchemist = replace(data, settings=tuple(settings))
    from dale.export_height import normalize_wall_heights

    hidden = json.loads(
        normalize_wall_heights(repaired_json_bytes(export_session(session))[0], (True, -5, 19))
    )
    assert len(hidden["walls"]) == 1
    assert hidden["walls"][0]["flags"]["wall-height"] == {"bottom": -5, "top": 19}


def test_da_groups_have_independent_members_order_colors_and_archive_state(sample, tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(preferences_path=tmp_path / "preferences.json")
    window.can_discard = lambda: True
    session, _, _, source = sample
    try:
        window.load_sources(source.image_path, source.json_path)
        target = window.view.session
        target.alchemist = session.alchemist
        target.add(session.geometry())
        window.configure_json_repair(True)
        window.select_tool_set("figures")
        window.create_selection_group()
        regular = window.selection_groups()[0]
        window.view.figure_line_ids = (target.geometry().lineage[0].id,)
        window.assign_selection_group(regular.id, True)
        window.select_tool_set("alchemist")
        assert not window.selection_groups()
        window.create_selection_group()
        first = window.selection_groups()[0]
        window.update_selection_group(first.id, name="Trees", color="#55aa22")
        window.view.figure_line_ids = session.alchemist.objects[0].roots
        window.assign_selection_group(first.id, True)
        window.create_selection_group()
        second = window.selection_groups()[1]
        window.reorder_selection_group(second.id, 0)
        window.select_selection_group(first.id)
        assert set(window.view.figure_line_ids) == set(session.alchemist.objects[0].roots)
        assert [g.id for g in window.selection_groups()] == [second.id, first.id]
        window.select_tool_set("figures")
        assert [g.id for g in window.selection_groups()] == [regular.id]
        window.select_tool_set("alchemist")
        assert window.active_selection_group() == first.id
        path = tmp_path / "da-groups.dale"
        window.project_path = path
        assert window.save_project_file()
        assert window.load_project_file(path)
        window.select_tool_set("alchemist")
        assert [g.id for g in window.selection_groups()] == [second.id, first.id]
        assert window.selection_groups()[1].color == "#55aa22"
        assert window.resolved_group_members(first.id) == set(session.alchemist.objects[0].roots)
        window.select_tool_set("figures")
        assert [g.id for g in window.selection_groups()] == [regular.id]
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_standalone_json_export_normalizes_and_worker_freezes_settings(
    sample, tmp_path, monkeypatch
):
    from PySide6.QtWidgets import QFileDialog

    from dale.ui import ExportWorker

    app = QApplication.instance() or QApplication([])
    window = MainWindow(preferences_path=tmp_path / "preferences.json")
    window.can_discard = lambda: True
    session, _, _, source = sample
    try:
        window.load_sources(source.image_path, source.json_path)
        target = window.view.session
        target.alchemist = session.alchemist
        target.add(session.geometry())
        window.configure_json_repair(True)
        window.height_normalization = (True, -4, 25)
        worker = ExportWorker(target, tmp_path / "bundle", window)
        window.height_normalization = (True, 2, 30)
        assert worker.height_normalization == (True, -4, 25)
        path = tmp_path / "exported.json"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: (str(path), ""))
        monkeypatch.setattr(window, "information", lambda *a: None)
        window.export_json()
        result = json.loads(path.read_bytes())
        assert len(result["walls"]) == 49
        assert all(
            w["flags"]["wall-height"]["bottom"] == 2 and w["flags"]["wall-height"]["top"] == 30
            for w in result["walls"]
        )
        assert target.geometry() == session.geometry()
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_manager_dam_row_name_and_mode_panel_resize_on_apply(sample, tmp_path):
    from PySide6.QtCore import Qt

    from dale.dataset_manager import DatasetManager

    app = QApplication.instance() or QApplication([])
    window = MainWindow(preferences_path=tmp_path / "preferences.json")
    window.can_discard = lambda: True
    session, _, raw, source = sample
    try:
        window.resize(1280, 850)
        window.show()
        window.load_sources(source.image_path, source.json_path)
        app.processEvents()
        app.processEvents()
        initial_width = window.tool_set_toolbar.width()
        manager = DatasetManager(window)
        staged = manager.catalog.current.session
        staged.alchemist = session.alchemist
        staged.add(session.geometry())
        manager.rebuild()
        root = manager.tree.topLevelItem(0)
        child = root.child(2)
        assert root.childCount() == 3
        assert child.text(0) == "Synthetic.dam"
        assert child.data(0, Qt.ItemDataRole.UserRole) == (manager.selected, "alchemist")
        manager.tree.setCurrentItem(child)
        field = manager.file_fields["alchemist"]
        assert field.isEnabled() and field.text() == "Synthetic"
        field.setText("Renamed obstacles")
        field.editingFinished.emit()
        assert manager.tree.topLevelItem(0).child(2).text(0) == "Renamed obstacles.dam"
        assert window.view.session.alchemist is None
        manager.apply(False)
        app.processEvents()
        app.processEvents()
        assert window.tool_set_toolbar.width() > initial_width
        for action in window.tool_set_actions.values():
            button = window.tool_set_toolbar.widgetForAction(action)
            assert button.geometry().right() < window.tool_set_toolbar.width()
        assert window.view.session.alchemist.source == raw
        path = tmp_path / "renamed.dale"
        save_project(window.view.session, path, catalog=window.catalog)
        with load_project(path) as restored:
            assert restored.catalog.current.session.alchemist.name == "Renamed obstacles.dam"
        manager.confirm = lambda *args: True
        manager.alchemist_remove_button.click()
        assert manager.tree.topLevelItem(0).childCount() == 2
        assert not manager.file_fields["alchemist"].isEnabled()
        assert not manager.alchemist_remove_button.isEnabled()
        assert window.view.session.alchemist is not None
        manager.apply(False)
        app.processEvents()
        app.processEvents()
        assert window.tool_set_toolbar.width() == initial_width
        assert not window.tool_set_actions["alchemist"].isVisible()
        manager.reject()
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("version", [6, 11])
def test_original_height_above_surface_filter_roundtrip(sample, tmp_path, version):
    from test_alchemist_terrain import terrain_payload

    from dale.alchemist import with_estimated_heights

    session, library, raw, source = sample
    data = json.loads(raw)
    data["Version"] = version
    data["terrain"] = terrain_payload((1.6, 1.6, 1.6, 1.6), version)
    metadata, geometry = import_map(
        json.dumps(data).encode(), "Height.dam", Session(source), library
    )
    session.alchemist = metadata
    session.add(geometry)
    # Small tree top2 minus local terrain1.6 is approximately2 feet, not10 feet.
    assert metadata.objects[0].original_height_ft == pytest.approx(2, abs=1e-6)
    assert metadata.objects[1].original_height_ft == pytest.approx(24, abs=1e-6)
    session.alchemist = replace(metadata, minimum_heights_ft=(0, 3, 0, 0))
    assert len(scoped_geometry(session).walls) == 25
    session.add(scale_category(session, "tree", 2))
    assert len(scoped_geometry(session).walls) == 25
    assert session.alchemist.objects == metadata.objects
    path = tmp_path / "height.dale"
    save_project(session, path, catalog=DatasetCatalog(session))
    with load_project(path) as loaded:
        restored = loaded.catalog.current.session
        assert restored.alchemist.minimum_heights_ft == (0, 3, 0, 0)
        assert len(scoped_geometry(restored).walls) == 25
        restored.alchemist = replace(restored.alchemist, minimum_heights_ft=(0, 0, 0, 0))
        assert len(scoped_geometry(restored).walls) == 49
    # Existing schema7 data can recover measurements offline from exact embedded DAM and styles.
    session.alchemist = replace(
        session.alchemist,
        objects=tuple(replace(o, original_height_ft=None) for o in metadata.objects),
    )
    library.clear()
    recovered = with_estimated_heights(session)
    assert [o.original_height_ft for o in recovered.objects] == pytest.approx([2, 24], abs=1e-6)


def test_floor_height_filter_is_relative_and_boundary_inclusive(sample):
    session, library, raw, source = sample
    data = json.loads(raw)
    data["foundations"][0].update(type=1, layer=2, height=50)
    data["buildingBlockInstances"][0]["height"] = 48.6  # top50.6:3 feet above floor
    data["buildingBlockInstances"][1]["height"] = 45  # top49:fully below floor
    metadata, geometry = import_map(
        json.dumps(data).encode(), "Floor.dam", Session(source), library
    )
    session.alchemist = metadata
    session.add(geometry)
    assert [o.original_height_ft for o in metadata.objects] == pytest.approx([3, 0])
    session.alchemist = replace(metadata, minimum_heights_ft=(0, 3, 0, 0))
    assert len(scoped_geometry(session).walls) == 25
    session.alchemist = replace(metadata, minimum_heights_ft=(0, 4, 0, 0))
    assert len(scoped_geometry(session).walls) == 1
    session.alchemist = replace(metadata, minimum_heights_ft=(0, 0, 0, 0))
    assert len(scoped_geometry(session).walls) == 49
