"""Offscreen interaction with synthetic project sets and reusable contour placement."""

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QTransform
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from dale.canvas import MapView
from dale.editing import add_line, vertices
from dale.json_repair import repaired_json_bytes
from dale.project_io import (
    append_project_document,
    current_contours_document,
    load_project,
    save_project,
)
from dale.raster import load_preview
from dale.scene import load_pair
from dale.session import Session
from dale.ui import MainWindow, configure_application


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    if not app.property("catalog_test_style"):
        configure_application(app)
        app.setProperty("catalog_test_style", True)
    monkeypatch.setenv("DALE_SETTINGS_PATH", str(tmp_path / "settings.json"))
    window = MainWindow()
    monkeypatch.setattr(window.view, "connection_prompt", lambda tool: False)
    monkeypatch.setattr(window, "warning", lambda *args: pytest.fail(str(args)))
    monkeypatch.setattr(window, "can_discard", lambda: True)
    window.resize(1224, 768)
    window.show()
    app.processEvents()
    yield window
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def selection_scene(window, pair_factory, mode, zoom=1):
    from itertools import pairwise

    from shapely.geometry import box

    source = pair_factory(
        size=(400, 240),
        walls=[
            {"c": [*a, *b]}
            for polygon in (box(30, 30, 100, 100), box(140, 30, 210, 100), box(250, 30, 320, 100))
            for a, b in pairwise(polygon.exterior.coords)
        ],
    )
    assert window.load_sources(source.image_path, source.json_path)
    window.activate_mode(mode)
    view = window.view
    view.setTransform(QTransform.fromScale(zoom, zoom))
    view.centerOn(180, 100)
    QApplication.processEvents()
    return source, view


@pytest.mark.parametrize("language", ["ru", "en"])
def test_selected_export_question_remember_restart_cancel_and_right_click(window, language):
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtWidgets import QMessageBox

    from dale.preferences import load_merge_selected_regions

    window.set_language(language, persist=False)
    seen = []

    def choose(kind, remember):
        dialog = QApplication.activeModalWidget()
        assert dialog.objectName() == "mergeSelectedRegionsQuestion"
        assert dialog.text() == window.t("Export adjacent regions as one?")
        if seen:
            assert dialog.informativeText().endswith(
                window.t("Choose the answer for export. Clear the checkbox to ask on every export.")
            )
        assert dialog.checkBox().text() == window.t("Do not ask again")
        dialog.checkBox().setChecked(remember)
        seen.append(kind)
        dialog.button(kind).click()

    QTimer.singleShot(0, lambda: choose(QMessageBox.StandardButton.Yes, True))
    assert window.confirm_merge_selected_regions() is True
    assert load_merge_selected_regions(window.preferences_path) is True
    assert window.confirm_merge_selected_regions() is True and len(seen) == 1
    reopened = MainWindow(preferences_path=window.preferences_path)
    assert reopened.remembered_merge_selected_regions is True and reopened.merge_selected_regions
    reopened.close()
    reopened.deleteLater()

    QTimer.singleShot(0, lambda: choose(QMessageBox.StandardButton.Cancel, False))
    assert window.confirm_merge_selected_regions(settings=True) is None
    assert load_merge_selected_regions(window.preferences_path) is True
    QTimer.singleShot(0, lambda: choose(QMessageBox.StandardButton.No, False))
    button = window.export_regions_button
    position = button.rect().center()
    event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, position, button.mapToGlobal(position)
    )
    QApplication.sendEvent(button, event)
    assert len(seen) == 3 and load_merge_selected_regions(window.preferences_path) is None
    assert not window.merge_selected_regions
    tip = window.export_regions_action.toolTip()
    assert tip.startswith(window.t("Export selected regions"))
    assert ("Правый клик" if language == "ru" else "Right-click") in tip


@pytest.mark.parametrize("merge", [True, False])
def test_selected_export_actual_button_question_worker_png_and_sidebar(
    window, pair_factory, tmp_path, monkeypatch, merge
):
    from itertools import pairwise

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox
    from shapely.geometry import box

    from dale.overlay_export import selected_export_regions

    source = pair_factory(
        size=(240, 160),
        walls=[
            {"c": [*a, *b]}
            for p in (box(30, 30, 100, 100), box(100, 30, 170, 100))
            for a, b in pairwise(p.exterior.coords)
        ],
    )
    assert window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Select regions")
    window.toggle_region_at((50, 50))
    window.toggle_region_at((150, 50))
    assert len(window.view.region_polygons) == 2
    window.contour_offset.setValue(-3)
    geometry, operations = window.view.session.geometry(), tuple(window.view.session.operations)
    source_bytes = source.image_path.read_bytes(), source.json_path.read_bytes()
    monkeypatch.setattr("dale.ui.QFileDialog.getExistingDirectory", lambda *args: str(tmp_path))
    dialogs = []

    def choose():
        dialog = QApplication.activeModalWidget()
        assert dialog.objectName() == "mergeSelectedRegionsQuestion"
        dialogs.append(dialog.text())
        dialog.checkBox().setChecked(True)
        dialog.button(
            QMessageBox.StandardButton.Yes if merge else QMessageBox.StandardButton.No
        ).click()

    QTimer.singleShot(0, choose)
    QTest.mouseClick(window.export_regions_button, Qt.MouseButton.LeftButton)
    assert window.worker is not None and window.worker.merge_adjacent is merge
    for _ in range(500):
        if window.worker is None:
            break
        QTest.qWait(10)
    assert window.worker is None and len(dialogs) == 1
    (folder,) = tmp_path.glob("*-overlays")
    manifest = json.loads((folder / "placement.json").read_text())
    assert len(manifest["items"]) == (1 if merge else 2)
    bounds = window.bounds_preview.request(
        window.view.session,
        tuple(
            p
            for _, p in selected_export_regions(
                window.view.region_polygons, -3, merge_adjacent=merge
            )
        ),
    )
    assert tuple(tuple(item["content_bounds"]) for item in manifest["items"]) == bounds.bounds
    assert ("PNG: 2" in window.map_info.text()) is (not merge)
    assert window.view.session.geometry() == geometry
    assert tuple(window.view.session.operations) == operations
    assert source_bytes == (source.image_path.read_bytes(), source.json_path.read_bytes())


def test_selected_export_cancel_stops_before_folder_dialog(window, pair_factory, monkeypatch):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox

    selection_scene(window, pair_factory, "Select regions")
    window.toggle_region_at((50, 50))
    monkeypatch.setattr(
        "dale.ui.QFileDialog.getExistingDirectory",
        lambda *args: pytest.fail("Unexpected folder dialog"),
    )
    QTimer.singleShot(
        0,
        lambda: QApplication.activeModalWidget().button(QMessageBox.StandardButton.Cancel).click(),
    )
    window.export(selected_only=True)
    assert window.worker is None and window.progress is None and window.output_directory is None


@pytest.mark.parametrize("zoom", [1, 2])
@pytest.mark.parametrize("show_contours", [False, True])
def test_line_eraser_preview_and_commit_stop_at_unnoded_intersection(
    window, pair_factory, zoom, show_contours
):
    source = pair_factory(
        size=(400, 340),
        walls=[
            {"c": c, "door": int(i == 0), "flags": {"custom": {"kept": i}}}
            for i, c in enumerate(
                (
                    [40, 50, 300, 50],
                    [40, 240, 300, 240],
                    [40, 50, 40, 240],
                    [120, 10, 120, 300],
                )
            )
        ],
        lights=[{"unchanged": True}],
        tiles=[{"texture": {"src": "original.png"}}],
    )
    assert window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Erase lines")
    view = window.view
    view.setTransform(QTransform.fromScale(zoom, zoom))
    view.centerOn(180, 150)
    view.show_walls = show_contours
    window.geometry_brush_control.setValue(8)
    original = view.session.geometry()
    artwork = view.item.pixmap().cacheKey()
    view.cursor_point = (250, 50)
    view.update_hover()
    assert view.highlighted_edges == (((120, 50), (300, 50)),)
    point = view.mapFromScene(250, 50)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    edited = view.session.geometry()
    assert edited.walls == (((40, 50), (120, 50)), *original.walls[1:])
    assert edited.lineage[1:] == original.lineage[1:]
    assert edited.lineage[0].parents == (original.lineage[0].id,)
    assert len(view.session.operations) == 1 and view.item.pixmap().cacheKey() == artwork
    data = json.loads(repaired_json_bytes(view.session)[0])
    assert data["lights"] == source.raw["lights"] and data["tiles"] == source.raw["tiles"]
    retained = next(w for w in data["walls"] if w["c"] == [40, 50, 120, 50])
    assert retained["door"] == 1 and retained["flags"] == source.raw["walls"][0]["flags"]
    assert source.json_path.read_bytes() == source.json_bytes
    window.history(False)
    assert view.session.geometry() == original
    window.history(True)
    assert view.session.geometry() == edited


def test_line_eraser_frozen_stroke_cancel_undo_and_archive(window, pair_factory, tmp_path):
    source = pair_factory(
        size=(240, 220),
        walls=[
            {"c": [20, 100, 180, 100]},
            {"c": [80, 20, 80, 100]},
        ],
    )
    assert window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Erase lines")
    view = window.view
    view.setTransform(QTransform.fromScale(2, 2))
    view.centerOn(120, 110)
    window.geometry_brush_control.setValue(4)
    original = view.session.geometry()
    a, b = view.mapFromScene(80, 40), view.mapFromScene(140, 100)
    for cancel in (True, False):
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=a)
        assert view.edit_preview.walls == (original.walls[0],)
        QTest.mouseMove(view.viewport(), b)
        assert view.edit_preview.walls == (((20, 100), (80, 100)),)
        if cancel:
            QTest.keyClick(view, Qt.Key.Key_Escape)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=b)
        if cancel:
            assert view.session.geometry() == original and not view.session.operations
        assert view.line_eraser_stroke is None and not view.line_eraser_hits
    assert len(view.session.operations) == 1
    edited = view.session.geometry()
    window.history(False)
    window.project_path = tmp_path / "line-eraser-redo.dale"
    assert window.save_project_file() and window.load_project_file(window.project_path)
    assert view.session.geometry() == original
    window.history(True)
    assert view.session.geometry() == edited
    assert view.session.geometry().lineage == edited.lineage


@pytest.mark.parametrize("answer", [True, False, None])
def test_line_eraser_connection_answer_is_one_atomic_edit(window, pair_factory, answer):
    source = pair_factory(
        size=(340, 320),
        walls=[
            {"c": [40, 50, 300, 50]},
            {"c": [40, 240, 300, 240]},
            {"c": [40, 50, 40, 240]},
            {"c": [120, 10, 120, 300]},
        ],
    )
    assert window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Erase lines")
    view = window.view
    view.setTransform(QTransform.fromScale(2, 2))
    view.centerOn(170, 160)
    window.geometry_brush_control.setValue(8)
    original = view.session.geometry()
    calls = []
    view.connection_prompt = lambda tool: calls.append(tool) or answer
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(250, 50))
    assert calls == ["Erase lines"]
    if answer is None:
        assert not view.session.operations and view.session.geometry() == original
    else:
        assert len(view.session.operations) == 1
        assert len(view.session.walls) == (5 if answer else 4)
        assert len(view.contour_figures()) == (1 if answer else 2)
        window.history(False)
        assert view.session.geometry() == original
        window.history(True)
        assert len(view.contour_figures()) == (1 if answer else 2)


@pytest.mark.parametrize("filtered", [False, True])
def test_line_eraser_uses_only_visible_height_scope(window, pair_factory, filtered):
    source = pair_factory(
        size=(240, 220),
        walls=[
            {"c": [20, 100, 180, 100], "flags": {"wall-height": {"bottom": 0, "top": 10}}},
            {"c": [80, 20, 80, 180], "flags": {"wall-height": {"bottom": 10, "top": 20}}},
        ],
    )
    assert window.load_sources(source.image_path, source.json_path)
    view = window.view
    assert view.safe_json_repair
    if filtered:
        from dale.source_editing import source_layers

        lower = next(p for p in source_layers(source, view.session.geometry()) if p.bottom == 0)
        window.layer_control.setCurrentIndex(window.layer_control.findData(lower.key))
    window.activate_mode("Erase lines")
    view.setTransform(QTransform.fromScale(2, 2))
    view.centerOn(120, 110)
    window.geometry_brush_control.setValue(4)
    original = view.session.geometry()
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(140, 100))
    live = dict(
        zip((r.id for r in view.session.geometry().lineage), view.session.walls, strict=True)
    )
    assert live[original.lineage[1].id] == original.walls[1]
    assert len(live) == (1 if filtered else 2)
    if not filtered:
        assert ((20, 100), (80, 100)) in live.values()


@pytest.mark.parametrize("answer", [True, False, None])
@pytest.mark.parametrize("endpoint", [False, True])
def test_point_contact_can_join_leave_coincident_vertices_independent_or_cancel(
    window, pair_factory, answer, endpoint
):
    from dale.connections import groups

    source = pair_factory(
        size=(280, 240),
        walls=[
            {"c": [40, 40, 80, 40]},
            {"c": [80, 40, 80, 80]},
            {"c": [160, 40, 160, 180]},
        ],
    )
    assert window.load_sources(source.image_path, source.json_path)
    view = window.view
    calls = []
    view.connection_prompt = lambda tool: calls.append(tool) or answer
    window.activate_mode("Edit points")
    view.setTransform(QTransform.fromScale(2, 2))
    view.centerOn(140, 120)
    view.snap_enabled = False
    original = view.session.geometry()
    point = (160, 40) if endpoint else (160, 100)
    a, b = view.mapFromScene(80, 40), view.mapFromScene(*point)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=a)
    QTest.mouseMove(view.viewport(), b)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=b)
    assert calls == ["Edit points"]
    if answer is None:
        assert not view.session.operations and view.session.geometry() == original
        return
    assert len(view.session.operations) == 1
    assert len(view.contour_figures()) == (1 if answer else 2)
    if answer:
        assert len(view.session.walls) == (3 if endpoint else 4)
    else:
        assert view.session.walls[2] == original.walls[2]
        assert groups(view.session.geometry())[0] != groups(view.session.geometry())[2]
        # Approach the moved figure's own leg, then move the coincident node again.
        view.hover_edge = view.session.walls[0]
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=b)
        QTest.mouseMove(view.viewport(), view.mapFromScene(120, 120))
        QTest.mouseRelease(
            view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(120, 120)
        )
        assert view.session.walls[2] == original.walls[2]
        assert len(calls) == 1


@pytest.mark.parametrize("tool", ["Erase lines", "Edit points"])
@pytest.mark.parametrize("language", ["ru", "en"])
def test_connection_question_remember_cancel_and_tool_right_click(window, tool, language):
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtWidgets import QMessageBox

    from dale.preferences import load_connection_choice

    window.set_language(language, persist=False)
    seen = []

    def choose(kind, remember):
        dialog = QApplication.activeModalWidget()
        assert dialog.objectName() == "contourConnectionQuestion"
        assert dialog.text() == window.t(
            "Connect new cut endpoints to intersecting contours with shared vertices?"
            if tool == "Erase lines"
            else "Connect this point to the other contour with a shared vertex?"
        )
        if len(seen) == 1:
            assert dialog.informativeText() == window.t(
                "Choose the answer for this tool. Clear the checkbox to ask on each contact."
            )
        assert dialog.checkBox().text() == window.t("Do not ask again")
        dialog.checkBox().setChecked(remember)
        seen.append(kind)
        dialog.button(kind).click()

    QTimer.singleShot(0, lambda: choose(QMessageBox.StandardButton.No, True))
    assert window.confirm_contour_connection(tool) is False
    assert load_connection_choice(window.preferences_path, tool) is False
    assert window.confirm_contour_connection(tool) is False and len(seen) == 1
    button = (
        window.geometry_eraser_tiles[tool]
        if tool == "Erase lines"
        else window.geometry_toolbar.widgetForAction(window.mode_actions[tool])
    )
    QTimer.singleShot(0, lambda: choose(QMessageBox.StandardButton.Yes, False))
    position = button.rect().center()
    event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, position, button.mapToGlobal(position)
    )
    QApplication.sendEvent(button, event)
    assert len(seen) == 2 and load_connection_choice(window.preferences_path, tool) is None
    QTimer.singleShot(0, lambda: choose(QMessageBox.StandardButton.Cancel, True))
    assert window.confirm_contour_connection(tool) is None
    assert load_connection_choice(window.preferences_path, tool) is None


@pytest.mark.parametrize("section", ["regions", "figures"])
def test_rotation_wheel_series_is_one_history_entry_then_next_action_starts_another(
    window, pair_factory, tmp_path, section
):
    selection_scene(window, pair_factory, "Select regions")
    window.select_tool_set(section)
    if section == "figures":
        window.select_figure_at({"point": (30, 70), "double": True})
    else:
        window.toggle_region_at((50, 50))
    view = window.view
    initial = view.session.geometry()
    fixed = {r.id: edge for r, edge in zip(initial.lineage[4:], initial.walls[4:], strict=True)}
    window.activate_mode("Rotate figures" if section == "figures" else "Rotate regions")
    before = len(view.session.operations)
    for _ in range(120):
        view.transform_regions(angle=0.1)
    final = view.session.geometry()
    assert len(view.session.operations) == before + 1
    live = dict(zip((r.id for r in final.lineage), final.walls, strict=True))
    assert all(live[key] == edge for key, edge in fixed.items())
    window.history(False)
    assert view.session.geometry() == initial
    window.history(True)
    assert view.session.geometry() == final
    if section == "regions":
        window.toggle_region_at((65, 65))
    view.transform_regions(angle=0.1)
    assert len(view.session.operations) == before + 2  # Undo/redo ended the first series.
    view.transform_regions(angle=0.1)
    assert len(view.session.operations) == before + 2
    window.project_path = tmp_path / f"rotation-{section}.dale"
    assert window.save_project_file()
    saved = view.session.geometry()
    view.transform_regions(angle=0.1)
    assert len(view.session.operations) == before + 3  # Saving is another action.
    window.history(False)
    assert view.session.geometry() == saved
    assert window.load_project_file(window.project_path)
    window.history(False)
    assert view.session.geometry() == final


@pytest.mark.parametrize("section", ["geometry", "figures", "regions", "pixels"])
@pytest.mark.parametrize("filtered", [False, True])
def test_ctrl_a_selects_current_section_and_height_scope(window, pair_factory, section, filtered):
    from itertools import pairwise

    from shapely.geometry import box

    from dale.source_editing import source_layers

    source = pair_factory(
        size=(400, 300),
        walls=[
            {"c": [*a, *b], "flags": {"wall-height": {"bottom": bottom, "top": bottom + 10}}}
            for bottom, shape in ((0, box(30, 30, 120, 130)), (10, box(170, 40, 280, 150)))
            for a, b in pairwise(shape.exterior.coords)
        ],
    )
    assert window.load_sources(source.image_path, source.json_path)
    if filtered:
        lower = next(
            p for p in source_layers(source, window.view.session.geometry()) if p.bottom == 0
        )
        window.layer_control.setCurrentIndex(window.layer_control.findData(lower.key))
    window.select_tool_set(section)
    view = window.view
    before = view.session.geometry()
    view.setFocus()
    QApplication.processEvents()
    assert window.select_all_action.isEnabled()
    for language in ("ru", "en"):
        window.set_language(language, persist=False)
        button = window.basic_toolbar.widgetForAction(window.select_all_action)
        assert button.isVisible() and (button.width(), button.height()) == (36, 36)
        assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
        if language == "ru":
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        else:
            QTest.keyClick(view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        assert window.select_all_action.toolTip().splitlines()[0] == window.select_all_action.text()
        assert "Ctrl+A" in window.mode_help.text()
        if section == "geometry":
            assert (
                len(view.contour_line_ids) == len(view.highlighted_edges) == (4 if filtered else 8)
            )
        elif section == "figures":
            assert len(view.figure_line_ids) == (4 if filtered else 8)
        else:
            assert len(view.region_polygons) == (1 if filtered else 2)
            assert window.selected_regions == tuple(range(len(window.regions)))
        assert view.session.geometry() == before and not view.session.operations
        QTest.keyClick(
            view,
            Qt.Key.Key_A,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )
        assert not view.contour_line_ids and not view.figure_line_ids and not view.region_polygons
    editor = {
        "geometry": window.snap_distance,
        "figures": window.figure_point_distance,
        "regions": window.region_point_distance,
        "pixels": window.brush_control,
    }[section].lineEdit()
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert editor.selectedText() == editor.text()
    assert not view.contour_line_ids and not view.figure_line_ids and not view.region_polygons


@pytest.mark.parametrize("zoom", [1, 2])
def test_figures_click_double_click_marquee_ctrl_a_and_clear(window, pair_factory, zoom):
    source = pair_factory(
        size=(400, 400),
        walls=[
            {"c": c}
            for c in (
                [40, 60, 100, 60],
                [100, 60, 100, 110],
                [100, 60, 140, 30],
                [70, 20, 70, 140],
                [200, 60, 260, 60],
            )
        ],
    )
    assert window.load_sources(source.image_path, source.json_path)
    window.tool_set_actions["figures"].trigger()
    view = window.view
    view.setTransform(QTransform.fromScale(zoom, zoom))
    view.centerOn(160, 160)
    ids = tuple(r.id for r in view.session.geometry().lineage)
    assert list(window.tool_set_actions) == ["geometry", "figures", "regions", "pixels"]
    assert view.figure_selection and view.mode == "Select figures"
    assert len(view.contour_figures()) == 3
    p = view.mapFromScene(55, 60)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=p)
    assert view.figure_line_ids == (ids[0],)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=p)
    assert not view.figure_line_ids
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(100, 90))
    assert set(view.figure_line_ids) == set(ids[:3])
    assert ids[3] not in view.figure_line_ids  # A crossing has no shared stored vertex.
    view.setFocus()
    QTest.keyClick(view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert set(view.figure_line_ids) == set(ids)
    window.clear_selection_action.trigger()
    assert not view.figure_line_ids
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=p)
    a, b, c = (view.mapFromScene(*p) for p in ((50, 45), (90, 80), (120, 80)))
    for cancel in (True, False):
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=a)
        QTest.mouseMove(view.viewport(), b)
        assert set(view.figure_line_ids) == {ids[3]}
        QTest.mouseMove(view.viewport(), c)
        assert set(view.figure_line_ids) == set(ids[1:4])
        QTest.mouseMove(view.viewport(), b)
        assert set(view.figure_line_ids) == {ids[3]}
        if cancel:
            QTest.keyClick(view, Qt.Key.Key_Escape)
            assert view.figure_line_ids == (ids[0],)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=b)
    assert set(view.figure_line_ids) == {ids[3]}
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(300, 300))
    assert not view.figure_line_ids and not view.session.operations
    for title, action in window.figure_alignment_actions.items():
        button = window.sized_tools[title]
        assert button.isVisible() and (button.width(), button.height()) == (48, 72)
        assert action.toolTip().splitlines()[0] == action.text()
        assert "Alt" in action.toolTip() and "Ctrl" in button.toolTip()
    window.figure_guide_distance.setValue(9999)
    assert window.contour_alignment_distance.value() == window.region_guide_distance.value() == 9999
    editor = window.figure_guide_distance.lineEdit()
    editor.setFocus()
    QTest.keyClick(editor, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert editor.selectedText() == "9999" and not view.figure_line_ids
    window.activate_mode("Move figures")
    assert view.mode == "Select figures"  # No modal when the selection is empty.


@pytest.mark.parametrize("zoom", [1, 2])
@pytest.mark.parametrize("prior", ["none", "other", "first"])
def test_contour_double_click_locks_first_hit_and_does_not_accumulate_jittered_second_hit(
    window, pair_factory, zoom, prior
):
    from itertools import pairwise

    from PySide6.QtCore import QPoint
    from shapely.geometry import box

    source = pair_factory(
        size=(400, 300),
        walls=[
            {"c": [*a, *b]}
            for shape in (box(30, 80, 170, 180), box(80, 30, 200, 140))
            for a, b in pairwise(shape.exterior.coords)
        ]
        + [{"c": [260, 40, 320, 40]}],
    )
    assert window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Select figures")
    view = window.view
    view.setTransform(QTransform.fromScale(zoom, zoom))
    view.centerOn(180, 140)
    QApplication.processEvents()
    original = view.session.geometry()
    ids = tuple(r.id for r in original.lineage)
    view.figure_line_ids = ids[:4]
    window.update_map_info()
    assert view.copy_selected_regions()  # A populated clipboard must not create a copy.
    prior_ids = () if prior == "none" else ids[8:] if prior == "other" else ids[:4]
    view.figure_line_ids = prior_ids
    window.update_map_info()
    pixels = view.item.pixmap().toImage()
    # Native Qt double-click sequence: first press/release, double press, release.
    # Both contours cross here, but have no shared stored vertex.
    crossing = view.mapFromScene(80, 80)
    first, second = crossing + QPoint(-1, 0), crossing + QPoint(0, -1)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=first)
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=second)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=second)
    assert view.session.geometry() == original
    assert tuple(r.id for r in view.session.geometry().lineage) == ids
    assert not view.session.operations and not view.session.future
    assert view.item.pixmap().toImage() == pixels
    assert set(view.figure_line_ids) == set(prior_ids) | set(ids[:4])
    assert view.region_clipboard is not None and view.paste_delta is None
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=second)
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=first)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=first)
    assert set(view.figure_line_ids) == set(prior_ids) | set(ids[:8])
    assert view.session.geometry() == original and not view.session.operations


@pytest.mark.parametrize("interrupt", ["timeout", "clear", "mode"])
def test_double_click_does_not_reuse_an_unrelated_previous_click(window, pair_factory, interrupt):
    from PySide6.QtCore import QPoint

    source = pair_factory(
        size=(300, 200),
        walls=[
            {"c": [30, 80, 180, 80]},
            {"c": [80, 30, 80, 140]},
            {"c": [80, 140, 180, 140]},
        ],
    )
    assert window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Select figures")
    view = window.view
    view.setTransform(QTransform.fromScale(1, 1))
    view.centerOn(150, 100)
    QApplication.processEvents()
    ids = tuple(r.id for r in view.session.geometry().lineage)
    cross = view.mapFromScene(80, 80)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=cross + QPoint(-1, 0))
    assert view.figure_line_ids == (ids[0],)
    if interrupt == "timeout":
        QTest.qWait(QApplication.instance().styleHints().mouseDoubleClickInterval() + 15)
    elif interrupt == "clear":
        window.clear_selection_action.trigger()
    else:
        window.activate_mode("Edit points")
        window.activate_mode("Select figures")
    before = set(view.figure_line_ids)
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=cross + QPoint(0, -1))
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=cross + QPoint(0, -1))
    assert set(view.figure_line_ids) == before | set(ids[1:])
    assert not view.session.operations


def test_open_disconnected_figure_lines_transform_copy_paste_and_archive(
    window, pair_factory, tmp_path
):
    from dale.region_transform import plan_figure_transform

    source = pair_factory(
        size=(400, 400),
        walls=[
            {"_id": f"Wall{i:012d}", "c": c, "door": int(i == 0), "flags": {"custom": {"kept": i}}}
            for i, c in enumerate(([40, 60, 100, 60], [100, 60, 100, 110], [200, 60, 260, 60]))
        ],
        lights=[{"preserved": True}],
        tiles=[{"texture": {"src": "unchanged.png"}}],
    )
    assert window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Select figures")
    view = window.view
    original = view.session.geometry()
    chosen = (original.lineage[0].id, original.lineage[2].id)
    view.figure_line_ids = chosen
    window.update_map_info()
    pixels = view.item.pixmap().toImage()
    view.setTransform(QTransform.fromScale(1, 1))
    view.centerOn(200, 200)
    window.activate_mode("Move figures")
    a, b = view.mapFromScene(60, 60), view.mapFromScene(80, 80)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=a)
    QTest.mouseMove(view.viewport(), b)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=b)
    assert len(view.figure_line_ids) == 2 and len(view.session.walls) == 3
    live = dict(
        zip((r.id for r in view.session.geometry().lineage), view.session.walls, strict=True)
    )
    assert live[chosen[0]] == ((60, 80), (120, 80))
    assert live[original.lineage[1].id] == original.walls[1]
    view.transform_regions(scale=1.05)
    view.transform_regions(angle=15)
    assert len(view.figure_line_ids) == 2 and view.item.pixmap().toImage() == pixels
    payload, _ = repaired_json_bytes(view.session)
    document = json.loads(payload)
    assert document["lights"] == source.raw["lights"] and document["tiles"] == source.raw["tiles"]
    assert all(
        w["flags"] == source.raw["walls"][i]["flags"] for i, w in enumerate(document["walls"])
    )
    window.project_path = tmp_path / "open-figures.dale"
    assert window.save_project_file() and window.load_project_file(window.project_path)
    assert set(view.figure_line_ids) == set(chosen) and window.current_tool_set == "figures"
    view.cursor_point = (65, 85)
    window.copy_regions_action.trigger()
    assert len(view.region_clipboard.edges) == 2
    assert not view.region_clipboard.polygons
    before = len(view.session.operations)
    window.paste_regions_action.trigger()
    assert view.paste_delta is not None
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(200, 230))
    assert len(view.session.operations) == before + 1 and len(view.session.walls) == 5
    assert len(view.figure_line_ids) == 2
    window.history(False)
    assert len(view.session.walls) == 3
    window.history(True)
    assert len(view.session.walls) == 5
    window.select_all_action.trigger()
    assert plan_figure_transform(view.session.geometry(), view.figure_line_ids).moving


@pytest.mark.parametrize("native", [False, True])
def test_figure_rectangles_remain_whole_after_reselection_and_reopen(
    window, pair_factory, tmp_path, native
):
    from shapely.affinity import translate
    from shapely.geometry import box

    from dale.geometry import structural_regions
    from dale.overlay_export import export_overlays, export_regions

    source = pair_factory(
        size=(600, 600),
        walls=(
            [{"c": [460, 450, 490, 450], "flags": {"wall-height": {"bottom": 0, "top": 10}}}]
            if native
            else []
        ),
        lights=[{"unchanged": True}],
        tiles=[{"texture": {"src": "unchanged.png"}}],
    )
    assert window.load_sources(source.image_path, source.json_path)
    view = window.view
    view.setTransform(QTransform.fromScale(1, 1))
    view.centerOn(280, 280)
    shapes = [
        box(*bounds)
        for bounds in (
            (30, 30, 60, 60),
            (150, 30, 170, 55),
            (345, 30, 375, 60),
            (20, 180, 55, 230),
            (345, 190, 375, 240),
            (30, 340, 50, 360),
            (350, 340, 370, 360),
            (30, 485, 60, 515),
            (345, 485, 375, 515),
            (90, 90, 130, 130),
            (40, 40, 360, 500),
        )
    ]
    window.mode_actions["New rectangle"].trigger()
    for shape in shapes:
        x0, y0, x1, y1 = shape.bounds
        a, b = view.mapFromScene(x0, y0), view.mapFromScene(x1, y1)
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=a)
        QTest.mouseMove(view.viewport(), b)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=b)
    original = view.session.geometry()
    assert len(original.walls) == 44 + int(native)
    fixed = dict(zip((r.id for r in original.lineage[:-4]), original.walls[:-4], strict=True))
    source_bytes = source.image_path.read_bytes(), source.json_path.read_bytes()
    window.activate_mode("Select figures")
    assert len(view.contour_figures()) == 11 + int(native)
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(40, 270))
    assert len(view.figure_line_ids) == 4

    def selected_shape():
        return structural_regions(view.selected_figure_edges())[0]

    assert selected_shape().equals(shapes[-1]) and not selected_shape().interiors
    window.project_path = tmp_path / "figure-before.dale"
    assert window.save_project_file() and window.load_project_file(window.project_path)
    assert len(view.figure_line_ids) == 4 and selected_shape().equals(shapes[-1])
    view.setTransform(QTransform.fromScale(1, 1))
    view.centerOn(280, 280)
    window.activate_mode("Move figures")
    a, b = view.mapFromScene(200, 270), view.mapFromScene(217, 278)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=a)
    QTest.mouseMove(view.viewport(), b)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=b)
    assert selected_shape().equals(translate(shapes[-1], xoff=17, yoff=8))
    assert view.copy_selected_regions() and len(view.region_clipboard.edges) == 4
    view.transform_regions(scale=1.05)
    view.transform_regions(angle=15)
    transformed = selected_shape()
    assert transformed.area == pytest.approx(shapes[-1].area * 1.05**2)
    window.clear_selection()
    window.activate_mode("Select figures")
    point = transformed.exterior.interpolate(0.3, normalized=True)
    window.select_figure_at({"point": (point.x, point.y), "double": True})
    assert len(view.figure_line_ids) == 4 and selected_shape().equals(transformed)
    live = dict(
        zip((r.id for r in view.session.geometry().lineage), view.session.walls, strict=True)
    )
    assert all(live[key] == edge for key, edge in fixed.items())
    payload, _ = repaired_json_bytes(view.session)
    assert json.loads(payload)["lights"] == source.raw["lights"]
    assert json.loads(payload)["tiles"] == source.raw["tiles"]
    window.project_path = tmp_path / "figure-after.dale"
    assert window.save_project_file() and window.load_project_file(window.project_path)
    assert window.current_tool_set == "figures" and len(view.figure_line_ids) == 4
    assert selected_shape().equals(transformed) and repaired_json_bytes(view.session)[0] == payload
    window.select_tool_set("regions")
    assert window.regions == view.analysis.cells
    assert not any(p.equals(transformed) for p in window.regions)
    window.select_tool_set("pixels")
    assert window.regions == view.analysis.cells
    assert len(export_regions(view.session, individual=True)) > len(shapes)
    (tmp_path / "png").mkdir()
    folder = export_overlays(view.session, tmp_path / "png")
    items = json.loads((folder / "placement.json").read_text())["items"]
    assert len(items) == len(export_regions(view.session))
    assert source_bytes == (source.image_path.read_bytes(), source.json_path.read_bytes())


def test_raster_selection_requires_scene_image_from_initial_empty_window(window, pair_factory):
    action = window.mode_actions["Select raster regions"]
    assert not action.isEnabled()
    source = pair_factory()
    assert window.load_sources(None, source.json_path)
    assert not action.isEnabled()
    assert window.load_sources(source.image_path, source.json_path)
    assert action.isEnabled()
    window.close_document()
    assert not action.isEnabled()


@pytest.mark.parametrize("mode", ["Select regions", "Select raster regions"])
@pytest.mark.parametrize("zoom", [1, 2])
def test_selection_marquee_toggles_frozen_baseline_in_both_directions(
    window, pair_factory, mode, zoom
):
    source, view = selection_scene(window, pair_factory, mode, zoom)
    window.toggle_region_at((60, 60))
    window.toggle_region_at((280, 60))
    before = window.document_state(), view.session.geometry(), view.preview.tobytes()
    original = window.selected_regions
    points = [view.mapFromScene(*p) for p in ((20, 20), (220, 110), (110, 110))]
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=points[0])
    assert view.active_gesture and not window.delete_regions_action.isEnabled()
    QTest.mouseMove(view.viewport(), points[1])
    assert set(window.selected_regions) == {1, 2}
    QTest.mouseMove(view.viewport(), points[2])
    assert set(window.selected_regions) == {2}
    QTest.mouseMove(view.viewport(), points[1])
    assert set(window.selected_regions) == {1, 2}  # Always compare with press-time state.
    assert all(not command.isEnabled() for command in window.mask_actions.values())
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=points[1])
    assert not view.active_gesture and window.marquee_selection is None
    assert all(command.isEnabled() for command in window.mask_actions.values())
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=points[1])
    QTest.mouseMove(view.viewport(), points[0])
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=points[0])
    assert window.selected_regions == original
    assert view.session.geometry() == before[1] and view.preview.tobytes() == before[2]
    assert not view.session.operations
    window.selected_regions = ()
    window.update_map_info()
    assert window.document_state() == before[0]  # Selection is UI state, never geometry history.


@pytest.mark.parametrize("mode", ["Select regions", "Select raster regions"])
@pytest.mark.parametrize("zoom", [1, 3])
def test_selection_threshold_empty_click_and_escape_are_screen_based(
    window, pair_factory, mode, zoom
):
    from PySide6.QtCore import QPoint

    _, view = selection_scene(window, pair_factory, mode, zoom)
    start = view.mapFromScene(60, 60)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(view.viewport(), start + QPoint(6, 8))  # Exactly10px remains a click.
    assert view.selection_rect is None and window.selected_regions == ()
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=start + QPoint(6, 8))
    assert window.selected_regions == (0,)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(view.viewport(), start + QPoint(9, 8))
    assert view.selection_rect is not None and window.selected_regions == ()
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert window.selected_regions == (0,) and not view.active_gesture
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=start + QPoint(9, 8))
    assert window.selected_regions == (0,)
    # Empty marquee preserves the baseline; empty stationary click clears it and highlights.
    a, b = view.mapFromScene(110, 140), view.mapFromScene(140, 180)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=a)
    QTest.mouseMove(view.viewport(), b)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=b)
    assert window.selected_regions == (0,)
    view.highlighted_edges = view.session.walls[:1]
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=a)
    assert window.selected_regions == () and not view.highlighted_edges
    assert not view.session.operations


def test_marquee_escape_restores_frozen_pasted_figure_and_switch_cancels(window, pair_factory):
    _, view = selection_scene(window, pair_factory, "Select regions")
    window.toggle_region_at((60, 60))
    view.cursor_point = (60, 60)
    assert view.copy_selected_regions() and view.begin_paste_regions()
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(150, 70))
    frozen = view.detached_selection
    assert frozen
    original = window.selected_regions
    a, b = view.mapFromScene(20, 20), view.mapFromScene(220, 110)
    for switch in (False, True):
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=a)
        QTest.mouseMove(view.viewport(), b)
        assert view.detached_selection is None
        if switch:
            window.select_tool_set("pixels")
        else:
            QTest.keyClick(view, Qt.Key.Key_Escape)
        assert not view.active_gesture and window.marquee_selection is None
        assert view.detached_selection == frozen and window.selected_regions == original
        assert view.region_polygons == frozen["polygons"]
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=b)
    assert len(view.session.operations) == 1


@pytest.mark.parametrize("mode", ["inside", "outside"])
def test_raster_selection_is_first_and_masks_only_selected_immutable_cells(
    window, pair_factory, tmp_path, mode
):
    from shapely.geometry import box

    from dale.raster import raster_operations, render_preview
    from dale.session import ContourMask

    source, view = selection_scene(window, pair_factory, "Select raster regions")
    # Locate the actual Raster bar independently of its index in the top/left bar list.
    raster_bar = next(
        bar for bar in window.toolbars if bar.widgetForAction(window.mode_actions[view.mode])
    )
    first = next(action for action in raster_bar.actions() if not action.isSeparator())
    assert first == window.mode_actions["Select raster regions"]
    button = raster_bar.widgetForAction(first)
    assert button.isVisible() and (button.width(), button.height()) == (48, 48)
    assert first.toolTip().splitlines()[0] == first.text()
    assert "10" in first.toolTip() and "Escape" in first.toolTip()
    assert "Alt:" not in window.mode_help.text() and "Ctrl+C:" not in window.mode_help.text()
    for selection in (None, ()):
        window.selected_regions = selection
        window.update_map_info()
        assert all(not command.isEnabled() for command in window.mask_actions.values())
        window.mask(mode)
        assert not view.session.operations
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(60, 60))
    assert window.selected_regions == (0,)
    assert all(command.isEnabled() for command in window.mask_actions.values())
    image_before, json_before = source.image_path.read_bytes(), source.json_path.read_bytes()
    window.mask_actions[mode].trigger()
    assert len(view.session.operations) == 1
    mask = view.session.operations[0]
    assert isinstance(mask, ContourMask) and mask.boundary.equals(box(30, 30, 100, 100))
    assert mask.mode == mode
    alpha = view.item.pixmap().toImage()
    assert alpha.pixelColor(60, 60).alpha() == (0 if mode == "inside" else 255)
    assert alpha.pixelColor(170, 60).alpha() == (255 if mode == "inside" else 0)
    window.contour_offset.setValue(5)
    expected = render_preview(
        view.preview, source.size, raster_operations(view.session.operations, 5)
    )
    assert view.item.pixmap().toImage().pixelColor(26, 60).alpha() == expected.getpixel((26, 60))[3]
    # Changing selection cannot retarget an existing mask.
    window.toggle_region_at((170, 60))
    assert mask.boundary.equals(box(30, 30, 100, 100))
    path = tmp_path / "selected-raster.dale"
    save_project(view.session, path, window.ui_state())
    with load_project(path) as loaded:
        assert loaded.ui_state["mode"] == "Select raster regions"
        assert loaded.session.operations[0].boundary.equals(mask.boundary)
        assert loaded.session.contour_offset == 5
        loaded.session.undo()
        assert not loaded.session.operations
        loaded.session.redo()
        assert loaded.session.operations[0] == mask
    assert (
        image_before == source.image_path.read_bytes()
        and json_before == source.json_path.read_bytes()
    )


def make_catalog(source, tmp_path):
    path = tmp_path / "many.dale"
    save_project(Session(source), path)
    image = tmp_path / "upper.png"
    Image.new("RGBA", source.size, (30, 90, 120, 180)).save(image)
    additional = Session(load_pair(image))
    additional.add(add_line(additional.geometry(), (100, 120), (200, 120)))
    doc, _ = append_project_document(path, current_contours_document(additional))
    return path, doc


def test_export_json_uses_active_unsaved_draft_alias_and_applied_history(
    window, pair_factory, tmp_path, monkeypatch
):
    path, document = make_catalog(pair_factory(size=(400, 400)), tmp_path)
    assert window.load_project_file(path)
    original_project = path.read_bytes()
    other_id = next(key for key in window.catalog.views if key != window.catalog.base_key)
    window.dataset_control.setCurrentIndex(window.dataset_control.findData(other_id))
    session = window.view.session
    session.add(add_line(session.geometry(), (25, 30), (50, 30)))
    session.add(add_line(session.geometry(), (25, 50), (50, 50)))
    session.undo()
    window.catalog.rename("Active draft")
    destination = tmp_path / "current"
    dialogs = []

    def save_dialog(*args):
        dialogs.append(args)
        return str(destination), ""

    monkeypatch.setattr("dale.ui.QFileDialog.getSaveFileName", save_dialog)
    monkeypatch.setattr(window, "information", lambda *args: None)
    before = window.document_state(), window.saved_state, window.catalog.active_key
    window.export_json_action.trigger()
    exported = destination.with_suffix(".json")
    assert exported.read_bytes() == repaired_json_bytes(window.view.session)[0]
    assert load_pair(None, exported).walls == session.walls
    assert len(session.walls) == 2 and len(session.future) == 1
    assert Path(dialogs[0][2]).name == "Active draft.json"
    assert dialogs[0][1] == window.t("Export JSON…")
    assert (window.document_state(), window.saved_state, window.catalog.active_key) == before
    assert path.read_bytes() == original_project
    session.redo()
    window.export_json_action.trigger()
    assert len(load_pair(None, exported).walls) == 3
    window.dataset_control.setCurrentIndex(window.dataset_control.findData(window.catalog.base_key))
    window.export_json_action.trigger()
    assert exported.read_bytes() == repaired_json_bytes(window.view.session)[0]
    assert Path(dialogs[-1][2]).name == "source.json"
    assert len(load_pair(None, exported).walls) == 4


def test_export_json_from_image_only_and_cancel(window, pair_factory, tmp_path, monkeypatch):
    source = pair_factory()
    assert not window.export_json_action.isEnabled()
    assert window.load_sources(source.image_path, None)
    assert window.export_json_action.isEnabled()
    session = window.view.session
    session.add(add_line(session.geometry(), (1, 2), (3, 4)))
    before = window.document_state()
    monkeypatch.setattr("dale.ui.QFileDialog.getSaveFileName", lambda *args: ("", ""))
    window.export_json_action.trigger()
    assert window.document_state() == before
    destination = tmp_path / "image-contours.json"

    def save_dialog(*args):
        assert Path(args[2]).name == "source.json"
        return str(destination), ""

    monkeypatch.setattr("dale.ui.QFileDialog.getSaveFileName", save_dialog)
    monkeypatch.setattr(window, "information", lambda *args: None)
    window.export_json_action.trigger()
    assert load_pair(None, destination).walls == session.walls
    assert window.document_state() == before
    window.close_document()
    assert not window.export_json_action.isEnabled()


@pytest.mark.parametrize("target", ["source", "image", "inactive-image", "project", "hardlink"])
def test_export_json_cannot_overwrite_catalog_inputs(
    window, pair_factory, tmp_path, monkeypatch, target
):
    source = pair_factory(size=(400, 400))
    path, document = make_catalog(source, tmp_path)
    assert window.load_project_file(path)
    # Keep the root draft inactive while exporting another set.
    other_id = next(key for key in window.catalog.views if key != window.catalog.base_key)
    window.dataset_control.setCurrentIndex(window.dataset_control.findData(other_id))
    root = window.catalog.base_session.source
    image_id = next(key for key in window.catalog.images if key != "source-image")
    targets = {
        "source": root.json_path,
        "image": root.image_path,
        "inactive-image": window.catalog.images[image_id].path,
        "project": path,
    }
    destination = tmp_path / "protected.json"
    os.link(targets.get(target, path), destination)
    before = destination.read_bytes(), window.document_state()
    warnings = []
    monkeypatch.setattr(window, "warning", lambda *args: warnings.append(args))
    monkeypatch.setattr("dale.ui.QFileDialog.getSaveFileName", lambda *args: (str(destination), ""))
    window.export_json_action.trigger()
    assert warnings and "imported source" in warnings[0][1]
    assert (destination.read_bytes(), window.document_state()) == before


@pytest.mark.parametrize("language", ["en", "ru"])
def test_dedicated_top_panel_and_scrollable_rectangle_below_circle(window, language):
    window.set_language(language, persist=False)
    QApplication.processEvents()
    bar = window.dataset_toolbar
    assert bar.isVisible()
    assert bar.geometry().top() == window.basic_toolbar.geometry().top()
    for control in (window.dataset_control, window.manager_button):
        assert control.isVisible() and bar.rect().contains(control.geometry())
    actions = window.geometry_toolbar.actions()
    assert (
        actions.index(window.mode_actions["New rectangle"])
        == actions.index(window.mode_actions["New circle"]) + 1
    )
    assert (
        window.geometry_toolbar.widgetForAction(window.mode_actions["New rectangle"]).size().width()
        == 48
    )
    assert window.tool_scroll.height() == window.left_panel.height()
    assert window.tool_scroll.verticalScrollBar().maximum() > 0
    window.tool_scroll.verticalScrollBar().setValue(
        window.tool_scroll.verticalScrollBar().maximum()
    )
    assert window.global_close_control.isVisible()


@pytest.mark.parametrize("enabled,alt", [(True, True), (False, True), (True, False)])
def test_rectangle_both_corners_alt_align_to_distant_vertices(pair_factory, enabled, alt):
    app = QApplication.instance() or QApplication([])
    source = pair_factory(size=(400, 400), walls=[{"c": [20, 20, 100, 100]}])
    view = MapView()
    view.resize(600, 600)
    view.show()
    view.assign(Session(source), load_preview(source))
    view.setTransform(QTransform.fromScale(1, 1))
    view.centerOn(200, 200)
    view.set_mode("New rectangle")
    view.contour_alignment = enabled
    view.contour_alignment_distance_px = 5
    view.snap_enabled = enabled
    view.snap_distance = 5
    app.processEvents()
    modifier = Qt.KeyboardModifier.AltModifier if alt else Qt.KeyboardModifier.NoModifier
    start, end = view.mapFromScene(22, 65), view.mapFromScene(150, 102)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, modifier, start)
    assert view.rectangle_start == ((20, 65) if enabled and alt else (22, 65))
    QTest.mouseMove(view.viewport(), end)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, modifier, end)
    assert len(view.session.operations) == 1
    points = vertices(view.session.geometry())
    assert ((20, 100) if enabled and alt else (22, 102)) in points
    assert not view.active_gesture
    view.session.undo()
    view.set_mode("New rectangle")
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(view.viewport(), end)
    QTest.keyClick(view, Qt.Key.Key_Escape)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
    assert not view.session.operations
    view.close()


@pytest.mark.parametrize("section", ["regions", "figures"])
def test_common_clipboard_paste_between_sets_keeps_sources_and_undo(
    window, pair_factory, tmp_path, section
):
    source = pair_factory(size=(400, 400))
    assert window.load_sources(source.image_path, source.json_path)
    window.select_tool_set(section)
    window.select_all_action.trigger()
    assert window.copy_regions_action.isEnabled()
    window.copy_regions_action.trigger()
    clip = window.view.region_clipboard
    assert clip and len(clip.edges) == 4
    other = tmp_path / "other.png"
    Image.new("RGB", (400, 400), (20, 50, 90)).save(other)
    assert window.load_sources(other, None)
    window.select_tool_set(section)
    assert window.paste_regions_action.isEnabled()
    view = window.view
    view.setTransform(QTransform.fromScale(1, 1))
    view.centerOn(200, 200)
    view.cursor_point = (150, 70)
    before = view.item.pixmap().toImage()
    window.paste_regions_action.trigger()
    assert view.paste_delta is not None and not view.session.operations
    point = view.mapFromScene(150, 70)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert len(view.session.operations) == 1 and len(view.session.walls) == 4
    assert before == view.item.pixmap().toImage()
    assert len(window.catalog.base_session.json_documents) == 1
    assert all(record.sources for record in view.session.geometry().lineage)
    window.project_path = tmp_path / "copied.dale"
    assert window.save_project_file()
    with load_project(window.project_path) as loaded:
        assert loaded.session.geometry().lineage == view.session.geometry().lineage
        loaded.session.undo()
        assert not loaded.session.walls
        loaded.session.redo()
        assert len(loaded.session.walls) == 4
    window.paste_regions_action.trigger()
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert view.paste_delta is None and len(view.session.operations) == 1


@pytest.mark.parametrize("enabled,alt", [(True, True), (False, True), (True, False)])
def test_paste_aligns_whole_copy_and_alt_toggle_keeps_rigid_dimensions(
    window, pair_factory, enabled, alt
):
    source = pair_factory(size=(400, 400))
    window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Select regions")
    window.toggle_region_at((30, 80))
    window.view.setFocus()
    QTest.keyClick(window.view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    view = window.view
    assert view.region_clipboard
    view.contour_alignment = enabled
    view.contour_alignment_distance_px = 5
    view.setTransform(QTransform.fromScale(1, 1))
    view.cursor_point = (13, 290)
    QTest.keyClick(view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert view.paste_delta is not None
    modifier = Qt.KeyboardModifier.AltModifier if alt else Qt.KeyboardModifier.NoModifier
    view._preview_paste((13, 290), modifier)
    assert view.paste_delta[0] == (0 if enabled and alt else 3)
    assert bool(view.placement_guides) == (enabled and alt)
    # Releasing Alt restores the unconstrained cursor translation.
    QTest.keyRelease(view, Qt.Key.Key_Alt)
    assert view.paste_delta == (3, 270)
    before = view.session.geometry()
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert view.session.geometry() == before


@pytest.mark.parametrize("zoom", [1, 3])
@pytest.mark.parametrize("enabled,alt", [(True, True), (False, True), (True, False)])
def test_alt_paste_vertex_priority_screen_tolerance_and_whole_shape(
    window, pair_factory, zoom, enabled, alt
):
    source = pair_factory(size=(700, 600))
    window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Select regions")
    window.toggle_region_at((30, 80))
    view = window.view
    assert view.copy_selected_regions()
    clip = view.region_clipboard
    # Distracting X and Y guides are individually nearer than the actual target.
    target = (200, 350)
    distance = 3 / zoom
    geometry = add_line(view.session.geometry(), target, (215, 380))
    geometry = add_line(geometry, (200 + distance, 550), (450, 350 + distance))
    view.session.add(geometry)
    view.refresh(render_image=False)
    view.contour_alignment = enabled
    view.contour_alignment_distance_px = 5
    view.snap_enabled = enabled
    view.snap_distance = 5
    view.setTransform(QTransform.fromScale(zoom, zoom))
    point = (target[0] + distance, target[1] + distance)
    view.cursor_point = point
    assert view.begin_paste_regions()
    modifier = Qt.KeyboardModifier.AltModifier if alt else Qt.KeyboardModifier.NoModifier
    view._preview_paste(point, modifier)
    expected = target if enabled and alt else point
    assert view.paste_delta == pytest.approx(tuple(expected[i] - clip.anchor[i] for i in (0, 1)))
    assert view.snap == (target if enabled and alt else None)
    assert bool(view.placement_guides) == (enabled and alt)
    placed = clip.paste(geometry, *view.paste_delta)
    assert len(placed.walls) == len(geometry.walls) + len(clip.edges)
    assert placed.walls[: len(geometry.walls)] == geometry.walls
    for before, after in zip(clip.edges, placed.walls[-len(clip.edges) :], strict=True):
        assert tuple(after[1][i] - after[0][i] for i in (0, 1)) == pytest.approx(
            tuple(before[1][i] - before[0][i] for i in (0, 1))
        )
    # The tolerance is measured in screen pixels; a diagonal outside it is not a point hit.
    view._preview_paste((target[0] + 4 / zoom, target[1] + 4 / zoom), modifier)
    assert view.snap is None
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert view.snap is None and view.paste_delta is None
    assert view.session.geometry() == geometry


@pytest.mark.parametrize("section", ["regions", "figures"])
@pytest.mark.parametrize(
    "points,guides,alt,expected",
    [
        (True, True, True, (200, 350)),
        (False, True, True, (203, 353)),
        (True, False, True, (200, 350)),
        (False, False, True, (203, 353)),
        (True, True, False, (203, 353)),
    ],
)
def test_region_grabbed_vertex_hover_drag_copy_and_two_controls(
    window, pair_factory, points, guides, alt, expected, section
):
    from dale.geometry import structural_regions

    source = pair_factory(size=(600, 650))
    window.load_sources(source.image_path, source.json_path)
    window.select_tool_set(section)
    window.select_all_action.trigger()
    view = window.view
    initial_shape = (
        structural_regions(view.selected_figure_edges())[0]
        if section == "figures"
        else view.region_polygons[0]
    )
    initial = view.session.geometry()
    geometry = add_line(initial, (200, 350), (215, 380))
    geometry = add_line(geometry, (203, 550), (450, 353))
    view.session.add(geometry)
    window.refresh()
    window.activate_mode("Move figures" if section == "figures" else "Move regions")
    view.setTransform(QTransform.fromScale(1, 1))
    view.centerOn(200, 300)
    QCoreApplication.processEvents()
    actions, prefix = (
        (window.figure_alignment_actions, "Figure")
        if section == "figures"
        else (window.region_alignment_actions, "Region")
    )
    actions[f"{prefix} point alignment"].setChecked(points)
    actions[f"{prefix} guide alignment"].setChecked(guides)
    window.region_point_distance.setValue(5)
    window.region_guide_distance.setValue(5)
    assert window.snap_distance.value() == 5 and window.contour_alignment_distance.value() == 5
    assert actions[f"{prefix} point alignment"].isChecked() == points
    assert actions[f"{prefix} guide alignment"].isChecked() == guides
    assert window.snap_action.isChecked()
    assert not window.alignment_actions["contour_alignment"].isChecked()
    for title in (
        window.figure_alignment_actions if section == "figures" else window.region_alignment_actions
    ):
        tile = window.sized_tools[title]
        assert tile.isVisible() and (tile.width(), tile.height()) == (48, 72)
        assert "Alt" in tile.toolTip() and "Ctrl" in tile.toolTip()
    # The bottom-right corner is nearest, although the old clipboard anchor was top-left.
    start = (55, 265)
    QTest.mouseMove(view.viewport(), view.mapFromScene(40, 240))
    QTest.mouseMove(view.viewport(), view.mapFromScene(*start))
    assert view.region_anchor == (60, 270)
    assert view.copy_selected_regions() and view.region_clipboard.anchor == (60, 270)
    modifier = Qt.KeyboardModifier.AltModifier if alt else Qt.KeyboardModifier.NoModifier
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(*start))
    assert view.region_grab_vertex == (60, 270)
    destination = (198, 348)  # Original cursor-to-vertex offset remains5,5.
    view.cursor_point = destination
    view._preview_region_move(destination, modifier)
    assert view.region_anchor == expected
    delta = tuple(expected[i] - (60, 270)[i] for i in (0, 1))
    assert view.region_translation == delta
    fixed_ids = {r.id: e for r, e in zip(geometry.lineage[4:], geometry.walls[4:], strict=True)}
    preview = dict(
        zip((r.id for r in view.edit_preview.lineage), view.edit_preview.walls, strict=True)
    )
    assert all(preview[k] == e for k, e in fixed_ids.items())
    # Actual release recomputes snapping and commits the same rigid translation.
    QTest.mouseRelease(
        view.viewport(), Qt.MouseButton.LeftButton, modifier, pos=view.mapFromScene(*destination)
    )
    from shapely.affinity import translate

    transformed = (
        structural_regions(view.selected_figure_edges())[0]
        if section == "figures"
        else view.region_polygons[0]
    )
    assert transformed.equals(translate(initial_shape, xoff=delta[0], yoff=delta[1]))
    assert len(view.session.walls) == len(geometry.walls)
    assert view.begin_paste_regions()
    view.cursor_point = (203, 353)
    view._preview_paste((203, 353), modifier)
    assert view.region_anchor == expected
    QTest.keyRelease(view, Qt.Key.Key_Alt)
    assert view.region_anchor == (203, 353)
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert view.region_anchor is None and view.paste_delta is None


@pytest.mark.parametrize("language", ["ru", "en"])
def test_alignment_toggles_are_independent_and_follow_section_after_project_reopen(
    window, pair_factory, tmp_path, language
):
    from PySide6.QtCore import QPoint

    source, view = selection_scene(window, pair_factory, "Select figures")
    window.set_language(language, persist=False)
    original = view.session.geometry()
    groups = {
        "geometry": (window.snap_action, window.alignment_actions["contour_alignment"]),
        "figures": (
            window.figure_alignment_actions["Figure point alignment"],
            window.figure_alignment_actions["Figure guide alignment"],
        ),
        "regions": (
            window.region_alignment_actions["Region point alignment"],
            window.region_alignment_actions["Region guide alignment"],
        ),
    }
    # Change each real button independently; other sections keep their states.
    for section, (point, guide) in groups.items():
        window.select_tool_set(section)
        before = window.alignment_ui_state()
        toolbar = (
            window.geometry_toolbar
            if section == "geometry"
            else window.figure_toolbar
            if section == "figures"
            else window.toolbars[4]
        )
        for action in (point, guide):
            name = action.property("dale_tool_key")
            button = window.sized_tools[name]
            QTest.mouseClick(button, Qt.MouseButton.LeftButton, pos=QPoint(24, 20))
            for other, pair in groups.items():
                if other != section:
                    keys = (
                        ("snap_enabled", "contour_alignment")
                        if other == "geometry"
                        else (
                            f"{'figure' if other == 'figures' else 'region'}_point_alignment",
                            f"{'figure' if other == 'figures' else 'region'}_guide_alignment",
                        )
                    )
                    assert tuple(a.isChecked() for a in pair) == tuple(before[k] for k in keys)
        assert not point.isChecked() and guide.isChecked()
        assert not view.snap_enabled and view.contour_alignment
        assert toolbar.isVisible()
    # Distinct final profiles must survive every section switch and .dale reopening.
    groups["geometry"][0].setChecked(True)
    groups["geometry"][1].setChecked(False)
    groups["figures"][0].setChecked(False)
    groups["figures"][1].setChecked(True)
    groups["regions"][0].setChecked(True)
    groups["regions"][1].setChecked(True)
    expected = window.alignment_ui_state()
    for section in ("geometry", "figures", "regions", "figures", "geometry"):
        window.select_tool_set(section)
        assert (view.snap_enabled, view.contour_alignment) == tuple(
            a.isChecked() for a in groups[section]
        )
        assert window.alignment_ui_state() == expected
    window.select_tool_set("figures")
    window.project_path = tmp_path / "independent-alignment.dale"
    assert window.save_project_file() and window.load_project_file(window.project_path)
    assert window.alignment_ui_state() == expected
    assert not view.snap_enabled and view.contour_alignment
    assert view.session.geometry() == original and not view.session.operations
    assert source.json_path.read_bytes() == source.json_bytes


@pytest.mark.parametrize("keyboard", [False, True])
@pytest.mark.parametrize("native", [False, True])
def test_delete_region_button_and_del_remove_only_selected_boundary_with_undo(
    window, pair_factory, keyboard, native
):
    from itertools import pairwise

    from shapely.geometry import box

    perimeter = list(pairwise(box(20, 20, 120, 120).exterior.coords))
    inside = ((40, 60), (80, 60))
    walls = [
        {
            "_id": f"Wall{i:012d}",
            "c": [*a, *b],
            "door": int(i == 0),
            "flags": {"wall-height": {"bottom": 0, "top": 10}} if native else {},
        }
        for i, (a, b) in enumerate([*perimeter, inside])
    ]
    if native:
        walls.extend(
            {
                "_id": f"Upper{i:011d}",
                "c": [*a, *b],
                "door": 1,
                "flags": {"wall-height": {"bottom": 10, "top": 20}},
            }
            for i, (a, b) in enumerate(perimeter)
        )
    source = pair_factory(
        size=(400, 400),
        walls=walls,
        lights=[{"preserved": [None, 3]}],
        tiles=[{"texture": {"src": "unchanged.png"}}],
    )
    assert window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Select regions")
    action = window.delete_regions_action
    assert not action.isEnabled()
    if native:
        from dale.source_editing import source_layers

        lower = next(
            p for p in source_layers(source, window.view.session.geometry()) if p.bottom == 0
        )
        window.layer_control.setCurrentIndex(window.layer_control.findData(lower.key))
    window.toggle_region_at((30, 30))
    view = window.view
    assert action.isEnabled()
    for language, label in (
        ("ru", "Удалить область"),
        ("en", "Delete region"),
        ("ru", "Удалить область"),
    ):
        window.set_language(language, persist=False)
        assert action.text() == label and "Del" in action.toolTip()
        assert "Del:" in window.mode_help.text()
        button = window.toolbars[4].widgetForAction(action)
        assert button.isVisible() and (button.width(), button.height()) == (48, 48)
        assert not button.icon().isNull()
    original = view.session.geometry()
    pixels = view.item.pixmap().toImage()
    view.setFocus()
    if keyboard:
        QTest.keyClick(view, Qt.Key.Key_Delete)
    else:
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert len(view.session.operations) == 1
    assert len(view.session.walls) == (5 if native else 1)
    assert inside in view.session.walls
    result = json.loads(repaired_json_bytes(view.session)[0])
    assert result["walls"] == walls[4:]
    assert result["lights"] == source.raw["lights"] and result["tiles"] == source.raw["tiles"]
    assert view.item.pixmap().toImage() == pixels
    assert not window.selected_regions and not action.isEnabled()
    view.setFocus()
    QTest.keyClick(view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert view.session.geometry() == original
    QTest.keyClick(view, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    assert json.loads(repaired_json_bytes(view.session)[0])["walls"] == walls[4:]


def test_delete_region_keeps_coincident_pasted_surroundings_after_project_reopen(
    window, pair_factory, tmp_path
):
    from itertools import pairwise

    from shapely.geometry import box

    edges = [
        *pairwise(box(20, 20, 120, 120).exterior.coords),
        *pairwise(box(170, 20, 270, 120).exterior.coords),
        ((185, 60), (250, 60)),
    ]
    source = pair_factory(
        size=(400, 400),
        walls=[
            {"_id": f"Wall{i:012d}", "c": [*a, *b], "door": int(i >= 4)}
            for i, (a, b) in enumerate(edges)
        ],
    )
    window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Select regions")
    window.toggle_region_at((30, 30))
    view = window.view
    view.cursor_point = (22, 22)
    assert view.copy_selected_regions()
    original = view.session.geometry()
    view.setTransform(QTransform.fromScale(1, 1))
    view.centerOn(200, 200)
    assert view.begin_paste_regions()
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(170, 20))
    assert view.detached_selection and len(view.session.walls) == 13
    window.project_path = tmp_path / "copied.dale"
    assert window.save_project_file() and window.load_project_file(window.project_path)
    view.setFocus()
    QTest.keyClick(view, Qt.Key.Key_Delete)
    assert view.session.walls == original.walls
    assert view.session.geometry().lineage == original.lineage
    assert json.loads(repaired_json_bytes(view.session)[0]) == json.loads(source.json_bytes)
    assert source.json_path.read_bytes() == source.json_bytes
    assert window.save_project_file() and window.load_project_file(window.project_path)
    assert view.session.walls == original.walls
    window.history(False)
    assert len(view.session.walls) == 13


def test_delete_region_does_not_take_delete_from_text_input_or_active_paste(window, pair_factory):
    source = pair_factory(size=(400, 400))
    window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Select regions")
    window.toggle_region_at((30, 30))
    view = window.view
    original = view.session.geometry()
    editor = window.region_point_distance.lineEdit()
    editor.setFocus()
    editor.setText("123")
    editor.setCursorPosition(0)
    QTest.keyClick(editor, Qt.Key.Key_Delete)
    assert editor.text() == "23" and view.session.geometry() == original
    view.setFocus()
    assert view.copy_selected_regions() and view.begin_paste_regions()
    QTest.keyClick(view, Qt.Key.Key_Delete)
    assert view.session.geometry() == original and view.paste_delta is not None
    QTest.keyClick(view, Qt.Key.Key_Escape)
    window.select_tool_set("geometry")
    assert not window.delete_regions_action.isEnabled()


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("mode", ["Select figures", "Move figures", "Rotate figures"])
def test_delete_contours_shortcut_exact_ids_native_properties_and_archive(
    window, pair_factory, tmp_path, native, mode
):
    from dale.source_editing import source_layers

    coordinates = (
        [30, 40, 130, 40],
        [130, 40, 130, 120],
        [80, 20, 80, 150],
        [30, 40, 130, 40],
        [200, 40, 260, 40],
    )
    walls = [
        {
            "_id": f"Wall{i:012d}",
            "c": c,
            "door": int(i == 3),
            "flags": {
                "wall-height": {"bottom": 10 if i == 3 else 0, "top": 20 if i == 3 else 10},
                "custom": {"kept": i},
            }
            if native
            else {"custom": {"kept": i}},
        }
        for i, c in enumerate(coordinates)
    ]
    source = pair_factory(
        size=(400, 260),
        walls=walls,
        lights=[{"kept": True}],
        tiles=[{"texture": {"src": "keep.webp"}}],
    )
    assert window.load_sources(source.image_path, source.json_path)
    if native:
        layer = next(
            p for p in source_layers(source, window.view.session.geometry()) if p.bottom == 0
        )
        window.layer_control.setCurrentIndex(window.layer_control.findData(layer.key))
    window.select_tool_set("figures")
    view = window.view
    initial = view.session.geometry()
    # Delete disconnected open segments; keep the connected leg, crossing and duplicate.
    view.figure_line_ids = (initial.lineage[0].id, initial.lineage[4].id)
    window.update_map_info()
    window.activate_mode(mode)
    action = window.delete_contours_action
    assert action.isEnabled() and not window.delete_regions_action.isEnabled()
    for language in ("ru", "en", "ru"):
        window.set_language(language, persist=False)
        assert action.text() == window.t("Delete contours")
        assert action.toolTip().splitlines()[0] == action.text()
        assert "Del" in action.toolTip() and "Del:" in window.mode_help.text()
    original_bytes = source.json_path.read_bytes(), source.image_path.read_bytes()
    pixels = view.item.pixmap().toImage()
    view.setFocus()
    QTest.keyClick(view, Qt.Key.Key_Delete)
    assert len(view.session.operations) == 1
    assert tuple(r.id for r in view.session.geometry().lineage) == tuple(
        initial.lineage[i].id for i in (1, 2, 3)
    )
    assert view.session.walls == tuple(initial.walls[i] for i in (1, 2, 3))
    assert not view.figure_line_ids and not action.isEnabled()
    assert view.item.pixmap().toImage() == pixels
    output = json.loads(repaired_json_bytes(view.session)[0])
    assert output["walls"] == [walls[i] for i in (1, 2, 3)]
    assert output["lights"] == source.raw["lights"] and output["tiles"] == source.raw["tiles"]
    assert original_bytes == (source.json_path.read_bytes(), source.image_path.read_bytes())
    window.history(False)
    assert view.session.geometry() == initial
    window.history(True)
    window.project_path = tmp_path / "deleted-contours.dale"
    assert window.save_project_file() and window.load_project_file(window.project_path)
    assert json.loads(repaired_json_bytes(view.session)[0]) == output
    window.history(False)
    assert view.session.geometry() == initial


def test_delete_contours_respects_text_focus_active_gestures_and_empty_selection(
    window, pair_factory
):
    selection_scene(window, pair_factory, "Select figures")
    window.select_all_action.trigger()
    view = window.view
    original = view.session.geometry()
    editor = window.figure_point_distance.lineEdit()
    editor.setFocus()
    editor.setText("123")
    editor.setCursorPosition(0)
    QTest.keyClick(editor, Qt.Key.Key_Delete)
    assert editor.text() == "23" and view.session.geometry() == original
    view.setFocus()
    assert view.copy_selected_regions() and view.begin_paste_regions()
    window.update_clipboard_actions()
    assert not window.delete_contours_action.isEnabled()
    QTest.keyClick(view, Qt.Key.Key_Delete)
    window.delete_selected_contours()
    assert view.session.geometry() == original and view.paste_delta is not None
    QTest.keyClick(view, Qt.Key.Key_Escape)
    window.activate_mode("Select figures")
    window.select_all_action.trigger()
    view.setFocus()
    QTest.keyClick(view, Qt.Key.Key_Delete)
    assert not view.session.walls
    QTest.keyClick(view, Qt.Key.Key_Delete)
    assert len(view.session.operations) == 1  # Empty selection is a no-op.
    window.select_tool_set("regions")
    assert not window.delete_contours_action.isEnabled()


@pytest.mark.parametrize("remembered_mode", ["Move regions", "Rotate regions"])
def test_regions_tab_without_selection_never_opens_select_region_dialog(
    window, pair_factory, monkeypatch, remembered_mode
):
    source = pair_factory(size=(400, 400))
    window.load_sources(source.image_path, source.json_path)
    monkeypatch.setattr(
        window, "information", lambda *args: pytest.fail(f"Unexpected dialog: {args}")
    )
    for _ in range(3):
        window.last_tool_modes["regions"] = remembered_mode
        window.selected_regions = ()
        window.tool_set_actions["geometry"].trigger()
        window.tool_set_actions["regions"].trigger()
        assert window.current_tool_set == "regions" and window.view.mode == "Select regions"
        window.mode_actions[remembered_mode].trigger()
        assert window.view.mode == "Select regions"
    window.toggle_region_at((30, 30))
    window.mode_actions[remembered_mode].trigger()
    assert window.view.mode == remembered_mode and window.selected_regions


@pytest.mark.parametrize("mode,edges", [("New line", 1), ("New rectangle", 4), ("New circle", 8)])
@pytest.mark.parametrize("selected_band", [False, True])
@pytest.mark.parametrize("with_image", [False, True])
def test_native_creation_buttons_commit_in_all_layers_and_selected_band(
    window, pair_factory, tmp_path, mode, edges, selected_band, with_image
):
    walls = [
        {
            "_id": f"Wall{i:012d}",
            "c": [10, 10 + i * 20, 20, 10 + i * 20],
            "door": 1,
            "flags": {"wall-height": {"bottom": i * 10, "top": (i + 1) * 10}},
        }
        for i in (0, 1)
    ]
    source = pair_factory(size=(400, 400), walls=walls, lights=[{"preserved": True}])
    window.load_sources(source.image_path if with_image else None, source.json_path)
    view = window.view
    assert view.safe_json_repair and window.layer_control.currentData() == "all"
    if selected_band:
        from dale.source_editing import source_layers

        lower = next(p for p in source_layers(source, view.session.geometry()) if p.bottom == 0)
        window.layer_control.setCurrentIndex(window.layer_control.findData(lower.key))
    button = window.geometry_toolbar.widgetForAction(window.mode_actions[mode])
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert view.mode == mode
    view.setTransform(QTransform.fromScale(1, 1))
    view.centerOn(200, 200)
    start, end = view.mapFromScene(200, 180), view.mapFromScene(260, 260)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(view.viewport(), end)
    assert view.active_gesture and not view.session.operations
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
    assert not view.active_gesture and len(view.session.operations) == 1
    assert len(view.session.walls) == 2 + edges
    payload, _ = repaired_json_bytes(view.session)
    data = json.loads(payload)
    assert data["walls"][:2] == walls and data["lights"] == source.raw["lights"]
    bounds = {"bottom": 0 if selected_band else None, "top": 10 if selected_band else None}
    assert all(w["flags"]["wall-height"] == bounds for w in data["walls"][2:])
    assert all(w["door"] == 0 and w["move"] == 20 for w in data["walls"][2:])
    window.project_path = tmp_path / "shape.dale"
    assert window.save_project_file() and window.load_project_file(window.project_path)
    assert repaired_json_bytes(view.session)[0] == payload
    window.history(False)
    assert len(view.session.walls) == 2
    window.history(True)
    assert repaired_json_bytes(view.session)[0] == payload


def test_safe_rectangle_creates_four_default_native_walls_in_one_history_step(window, tmp_path):
    from dale.json_repair import repaired_json_bytes

    path = tmp_path / "native.json"
    original = {
        "width": 400,
        "height": 400,
        "walls": [
            {
                "_id": "original",
                "c": [10, 10, 20, 10],
                "flags": {"wall-height": {"bottom": 0, "top": 10}},
            }
        ],
        "custom": {"preserve": True},
    }
    path.write_text(json.dumps(original), encoding="utf-8")
    assert window.load_sources(None, path)
    assert window.mode_actions["New rectangle"].isEnabled()
    index = next(
        i for i in range(window.layer_control.count()) if window.layer_control.itemData(i) != "all"
    )
    window.layer_control.setCurrentIndex(index)
    window.activate_mode("New rectangle")
    view = window.view
    view.setTransform(QTransform.fromScale(1, 1))
    a, b = view.mapFromScene(100, 120), view.mapFromScene(180, 210)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=a)
    QTest.mouseMove(view.viewport(), b)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=b)
    assert len(view.session.operations) == 1 and len(view.session.geometry().additions) == 4
    result = json.loads(repaired_json_bytes(view.session)[0])
    assert result["walls"][0] == original["walls"][0] and result["custom"] == original["custom"]
    assert len(result["walls"]) == 5
    assert all(w["door"] == 0 and w["move"] == 20 for w in result["walls"][1:])


def test_global_artwork_values_do_not_replace_per_set_values(window, pair_factory, tmp_path):
    path, document = make_catalog(pair_factory(size=(400, 400)), tmp_path)
    window.load_project_file(path)
    window.contour_offset.setValue(2)
    other_id = next(key for key in window.catalog.views if key != window.catalog.base_key)
    window.dataset_control.setCurrentIndex(window.dataset_control.findData(other_id))
    window.contour_offset.setValue(4)
    window.global_tools_control.setChecked(True)
    window.contour_offset.setValue(9)
    window.dataset_control.setCurrentIndex(window.dataset_control.findData(window.catalog.base_key))
    assert window.contour_offset.value() == 9
    assert window._project_tool_values["artwork_offset_px"] == 2
    other_id = next(key for key in window.catalog.views if key != window.catalog.base_key)
    window.dataset_control.setCurrentIndex(window.dataset_control.findData(other_id))
    assert window._project_tool_values["artwork_offset_px"] == 4
    assert window.contour_offset.value() == 9
    assert window.save_project_file()
    with load_project(path) as loaded:
        assert loaded.session.contour_offset == 2
        view = loaded.catalog.activate(other_id)
        assert view.session.contour_offset == 4


@pytest.mark.parametrize("height_layers", [False, True])
def test_region_stays_whole_over_surroundings_repeated_transforms_and_reopen(
    window, pair_factory, tmp_path, height_layers
):
    from itertools import pairwise

    from shapely.affinity import translate
    from shapely.geometry import box

    from dale.overlay_export import export_overlays

    edges = [
        *pairwise(box(20, 20, 120, 120).exterior.coords),
        *pairwise(box(200, 20, 360, 180).exterior.coords),
        ((280, 20), (280, 180)),
    ]
    walls = [
        {
            "_id": f"Wall{i:012d}",
            "c": [*a, *b],
            "door": 1 if i == 0 else 0,
            "flags": {"wall-height": {"bottom": 0, "top": 10}} if height_layers else {},
        }
        for i, (a, b) in enumerate(edges)
    ]
    source = pair_factory(
        size=(500, 400),
        walls=walls,
        lights=[{"_id": "light", "config": {"color": "#ff8800"}}],
        tiles=[{"texture": {"src": "unchanged.png"}, "elevation": 9.99}],
    )
    assert window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Select regions")
    window.toggle_region_at((70, 70))
    view = window.view
    original = view.session.geometry()
    initial = view.region_polygons[0]
    fixed = {r.id: edge for edge, r in zip(original.walls[4:], original.lineage[4:], strict=True)}
    pixels = view.item.pixmap().toImage()
    window.remembered_move_related = True
    view.move_related = True
    view.snap_distance = 256
    view.contour_alignment = view.right_angle_alignment = True
    view.contour_alignment_distance_px = view.right_angle_distance_px = 9999
    window.activate_mode("Move regions")
    view.setTransform(QTransform.fromScale(1, 1))
    view.centerOn(250, 200)
    for start, delta in (((70, 70), (230, 50)), ((300, 120), (15, 0))):
        a = view.mapFromScene(*start)
        b = a + type(a)(*delta)
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=a)
        QTest.mouseMove(view.viewport(), b)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=b)
    assert view.region_polygons[0].equals(translate(initial, xoff=245, yoff=50))
    assert len(view.session.walls) == len(original.walls)
    folder = export_overlays(view.session, tmp_path, selected_polygons=view.region_polygons)
    item = json.loads((folder / "placement.json").read_text())["items"][0]
    assert (item["x"], item["y"], item["width"], item["height"]) == (264, 69, 102, 102)
    with Image.open(folder / item["file"]) as image:
        assert image.getpixel((362 - item["x"], 100 - item["y"]))[3] == 255
    view.transform_regions(scale=1.05)
    view.transform_regions(angle=30)
    assert view.region_polygons[0].area == pytest.approx(initial.area * 1.05**2)
    assert len(view.region_polygons) == 1
    current = dict(
        zip((r.id for r in view.session.geometry().lineage), view.session.walls, strict=True)
    )
    assert all(current[identifier] == edge for identifier, edge in fixed.items())
    assert view.item.pixmap().toImage() == pixels
    payload, _ = repaired_json_bytes(view.session)
    exported = json.loads(payload)
    assert exported["lights"] == source.raw["lights"] and exported["tiles"] == source.raw["tiles"]
    window.project_path = tmp_path / "overlap.dale"
    assert window.save_project_file()
    shape = view.region_polygons[0]
    assert window.load_project_file(window.project_path)
    assert view.region_polygons[0].equals_exact(shape, 1e-8)
    assert repaired_json_bytes(view.session)[0] == payload
    for _ in range(4):
        window.history(False)
    assert view.session.walls == original.walls
    for _ in range(4):
        window.history(True)
    assert repaired_json_bytes(view.session)[0] == payload
