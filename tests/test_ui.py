"""Exercise actual Qt pointer events offscreen, without controlling the owner's desktop."""

import json
import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEventLoop, QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QContextMenuEvent,
    QImage,
    QKeySequence,
    QPainter,
    QPainterPath,
    QTransform,
    QWheelEvent,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QDialogButtonBox, QMessageBox
from shapely.affinity import rotate

from dale.canvas import GEOMETRY_TOOLS, HANDLE_DIAMETER, REGION_TOOLS, MapView
from dale.editing import add_line, circle_points, vertices
from dale.project_io import load_project, save_project
from dale.raster import load_preview
from dale.session import RasterSelectionEdit, Session, Stroke
from dale.ui import MainWindow, configure_application


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    configure_application(application)
    return application


@pytest.fixture(autouse=True)
def isolated_preferences(monkeypatch, tmp_path):
    monkeypatch.setenv("DALE_SETTINGS_PATH", str(tmp_path / "settings.json"))


@pytest.mark.parametrize(
    "mode",
    [
        "Pan",
        "Erase",
        "Restore",
        "Auto-close",
        "Edit points",
        "New line",
        "New circle",
        "Erase lines",
        "Erase vertices",
        "Select regions",
        "Move regions",
        "Rotate regions",
    ],
)
@pytest.mark.parametrize("zoomed", [False, True])
def test_right_drag_pans_in_every_mode_without_editing(app, pair_factory, mode, zoomed):
    source = pair_factory()
    view = MapView()
    view.resize(500, 400)
    view.show()
    view.assign(Session(source), load_preview(source))
    if zoomed:
        view.setTransform(QTransform.fromScale(12, 12))
        view.centerOn(40, 150)
    view.set_mode(mode)
    app.processEvents()
    before = view.horizontalScrollBar().value(), view.verticalScrollBar().value()
    point = QPoint(200, 160)
    QTest.mousePress(view.viewport(), Qt.MouseButton.RightButton, pos=point)
    QTest.mouseMove(view.viewport(), point + QPoint(40, 30))
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.RightButton, pos=point + QPoint(40, 30))
    after = view.horizontalScrollBar().value(), view.verticalScrollBar().value()
    assert after == (before[0] - 40, before[1] - 30)
    assert not view.session.operations
    assert not view.panning
    view.close()


@pytest.mark.parametrize("zoom", [2, 5])
def test_auto_close_hover_click_and_undo_extend_existing_lines(app, pair_factory, zoom):
    source = pair_factory(
        size=(300, 200),
        walls=[
            {"c": [20, 20, 120, 20]},
            {"c": [120, 20, 120, 120]},
            {"c": [120, 120, 20, 120]},
            {"c": [20, 120, 20, 26]},
            {"c": [200, 20, 240, 20]},
        ],
    )
    view = MapView()
    view.resize(600, 500)
    view.show()
    view.assign(Session(source), load_preview(source))
    original = view.session.geometry()
    view.setTransform(QTransform.fromScale(zoom, zoom))
    view.centerOn(80, 60)
    view.auto_close_distance = 6 * zoom
    view.snap_enabled = False  # This tool has its own independent distance.
    view.set_mode("Auto-close")
    app.processEvents()
    point = view.mapFromScene(70, 20)
    QTest.mouseMove(view.viewport(), point + QPoint(2, 2))
    QTest.mouseMove(view.viewport(), point)
    assert len(view.auto_close_plan.segments) == 4
    assert view.auto_close_plan.extensions == (((20, 26), (20, 20)),)
    assert not view.hover_path.isEmpty()
    assert not view.auto_join_path.isEmpty()
    assert not view.session.operations
    image = view.viewport().grab().toImage()
    sample = view.mapFromScene(90, 20)
    colors = [image.pixelColor(sample.x(), sample.y() + dy).name() for dy in range(-3, 4)]
    assert any(colors[i : i + 3] == ["#ffffff", "#ff0000", "#ffffff"] for i in range(5))
    requested = []
    view.auto_close_requested.connect(requested.append)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert not view.session.operations
    view.session.add(requested[0].apply(view.session.geometry()))
    view.refresh()
    assert len(view.session.operations) == 1
    assert len(view.session.walls) == len(original.walls)
    assert view.session.walls[3] == ((20, 120), (20, 20))
    assert view.analysis.faces == 1
    assert not view.auto_close_plan.extensions
    view.session.undo()
    view.refresh()
    assert view.session.geometry() == original
    view.close()


@pytest.mark.parametrize("zoom", [2, 5])
@pytest.mark.parametrize("safe", [False, True])
def test_close_all_trims_overshoot_with_screen_tolerance_and_one_undo(
    app, pair_factory, zoom, safe, monkeypatch
):
    from dale.json_repair import repaired_json_bytes

    walls = [{"c": [20, 60, 124, 60]}, {"c": [120, 20, 120, 64]}]
    if safe:
        for wall in walls:
            wall["flags"] = {"wall-height": {"bottom": 0, "top": 10}}
    source = pair_factory(size=(300, 200), walls=walls)
    window = MainWindow()
    window.show()
    assert window.load_sources(source.image_path, source.json_path)
    view = window.view
    view.setTransform(QTransform.fromScale(zoom, zoom))
    view.centerOn(100, 60)
    window.global_close_control.setValue(4 * zoom)
    original = view.session.geometry()
    seen = []

    def approve():
        dialog = app.activeModalWidget()
        seen.append(dialog.text())
        assert "Укорочений концов: 2" in dialog.text()
        assert not view.auto_join_path.isEmpty()
        dialog.button(QMessageBox.StandardButton.Yes).click()

    QTimer.singleShot(0, approve)
    window.close_all_contours()
    assert seen and view.safe_json_repair is safe
    assert len(view.session.operations) == 1
    expected = (((20, 60), (120, 60)), ((120, 20), (120, 60)))
    assert view.session.walls == expected
    if safe:
        assert repaired_json_bytes(view.session)[1] == (0, 1)
    window.history(False)
    assert view.session.geometry() == original
    window.history(True)
    assert view.session.walls == expected
    monkeypatch.setattr(window, "can_discard", lambda: True)
    window.close()


def test_cancelled_global_trim_keeps_source_and_history(app, pair_factory):
    source = pair_factory(
        size=(300, 200), walls=[{"c": [20, 60, 124, 60]}, {"c": [120, 20, 120, 64]}]
    )
    window = MainWindow()
    window.show()
    assert window.load_sources(source.image_path, source.json_path)
    window.view.resetTransform()
    window.global_close_control.setValue(4)
    original = window.view.session.geometry()

    def cancel():
        dialog = app.activeModalWidget()
        assert "Укорочений концов: 2" in dialog.text()
        dialog.button(QMessageBox.StandardButton.Cancel).click()

    QTimer.singleShot(0, cancel)
    window.close_all_contours()
    assert window.view.session.geometry() == original and not window.view.session.operations
    window.close()


def test_retired_closure_mode_is_not_migrated(pair_factory, tmp_path):
    path = tmp_path / "retired-mode.dale"
    save_project(Session(pair_factory()), path, {"mode": "Closure"})
    with pytest.raises(ValueError, match="editing mode"):
        load_project(path)


def test_circle_drag_shrinks_ctrl_wheel_cancels_and_round_trips(app, pair_factory, tmp_path):
    source = pair_factory(size=(400, 400), walls=[], grid={"size": 100})
    view = MapView()
    view.resize(600, 600)
    view.show()
    view.assign(Session(source), load_preview(source))
    view.setTransform(QTransform.fromScale(1, 1))
    view.centerOn(200, 200)
    view.show_walls = False
    view.set_mode("New circle")
    app.processEvents()
    center = view.mapFromScene(200, 200)
    far = view.mapFromScene(350, 200)
    near = view.mapFromScene(250, 200)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=center)
    QTest.mouseMove(view.viewport(), far)
    assert view.circle_radius == pytest.approx(150)
    QTest.mouseMove(view.viewport(), near)
    assert view.circle_radius == pytest.approx(50)
    assert view.active_gesture and not view.session.operations
    wheel = QWheelEvent(
        QPointF(near),
        QPointF(near),
        QPoint(),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    app.sendEvent(view.viewport(), wheel)
    assert view.circle_radius == pytest.approx(51)
    QTest.keyClick(view, Qt.Key.Key_Escape)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=near)
    assert not view.session.operations and not view.active_gesture
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=center)
    assert not view.session.operations
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=center)
    QTest.mouseMove(view.viewport(), near)
    preview = view.viewport().grab().toImage()
    vertex = near
    assert any(preview.pixelColor(vertex.x() + dx, vertex.y()).green() > 150 for dx in range(-1, 2))
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=near)
    assert len(view.session.operations) == 1 and len(view.session.walls) == 6
    assert view.session.analysis().faces == 1
    original = view.session.geometry()
    project = tmp_path / "circle.dale"
    save_project(view.session, project, {"mode": "New circle", "tool_set": "geometry"})
    with load_project(project) as loaded:
        assert loaded.ui_state["mode"] == "New circle"
        assert loaded.session.geometry() == original
        assert loaded.session.geometry().lineage == original.lineage
        loaded.session.undo()
        assert not loaded.session.walls
        loaded.session.redo()
        assert loaded.session.geometry() == original
    view.close()


def test_circle_paint_changes_edges_during_drag_in_both_directions(app, pair_factory, monkeypatch):
    source = pair_factory(size=(500, 500), walls=[], grid=100)
    view = MapView()
    view.resize(600, 600)
    view.show()
    view.assign(Session(source), load_preview(source))
    view.setTransform(QTransform.fromScale(1, 1))
    view.centerOn(250, 250)
    view.set_mode("New circle")
    app.processEvents()
    painted = []

    def record_points(*args, **kwargs):
        result = circle_points(*args, **kwargs)
        painted.append(result)
        return result

    monkeypatch.setattr("dale.canvas.circle_points", record_points)
    center = view.mapFromScene(250, 250)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=center)
    for radius, count in ((25, 4), (50, 6), (100, 8), (50, 6), (25, 4)):
        point = view.mapFromScene(250 + radius, 250)
        QTest.mouseMove(view.viewport(), point)
        view.viewport().grab()
        assert len(painted[-1]) - 1 == count
        assert not view.session.operations
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert view.session.walls == tuple(zip(painted[-1], painted[-1][1:], strict=False))
    assert len(view.session.operations) == 1
    view.close()


def test_menu_grouping_replaces_general_toolbar_and_about_is_localized(app):
    window = MainWindow()
    window.show()
    assert [menu.text() for menu in window.menuBar().actions()] == ["Файл", "Правка", "О программе"]

    def keys(menu):
        return [
            action.property("dale_tool_key")
            for action in menu.actions()
            if not action.isSeparator()
        ]

    assert keys(window.file_menu) == [
        "New project",
        "Open project",
        "Recent projects",
        "Save project",
        "Save project as…",
        "Export PNGs",
        "Export JSON…",
        "Close project",
        "Exit",
    ]
    assert keys(window.edit_menu) == [
        "Undo",
        "Redo",
        "Select all contour lines",
        "Clear selection",
        "Copy region contours",
        "Paste region contours",
        "Delete region",
        "Delete contours",
    ]
    assert window.clear_selection_action in window.basic_toolbar.actions()
    assert len(window.toolbars) == 14
    assert window.toolbars[0] == window.tool_set_toolbar
    assert "New circle" in window.mode_actions
    for language in ("en", "ru"):
        window.set_language(language, persist=False)
        assert window.file_menu.actions()[0] == window.new_project_action
        assert window.new_project_action.text() == (
            "Новый проект" if language == "ru" else "New project"
        )
        assert window.new_project_action.shortcut() == QKeySequence(QKeySequence.StandardKey.New)
        assert window.new_project_action.toolTip().splitlines()[0] == (
            window.new_project_action.text()
        )
        assert "Ctrl+N:" in window.new_project_action.toolTip()
        assert window.manager_action not in window.file_menu.actions()
        assert window.manager_action in window.actions()
        assert window.manager_action.shortcut() == QKeySequence("Ctrl+I")
        save_as = next(
            a
            for a in window.file_menu.actions()
            if a.property("dale_tool_key") == "Save project as…"
        )
        native_shortcut = save_as.shortcut().toString(QKeySequence.SequenceFormat.NativeText)
        assert "Ctrl" in native_shortcut and "Shift" in native_shortcut
        seen = []

        def close_about(seen=seen):
            dialog = app.activeModalWidget()
            seen.append(dialog.objectName())
            assert dialog.text() == window.windowTitle()
            assert dialog.standardButtons() == QMessageBox.StandardButton.Close
            assert "Escape" in dialog.button(QMessageBox.StandardButton.Close).toolTip()
            QTest.mouseClick(
                dialog.button(QMessageBox.StandardButton.Close), Qt.MouseButton.LeftButton
            )

        QTimer.singleShot(0, close_about)
        window.about_menu.actions()[0].trigger()
        assert seen == ["aboutDALE"]
        assert ("Правка" if language == "ru" else "Edit") == window.edit_menu.title()
        window.activate_mode("New circle")
        assert "Ctrl" in window.mode_actions["New circle"].toolTip()
        assert "Escape" in window.mode_help.text()
    window.close()


@pytest.mark.parametrize("language", ["ru", "en"])
@pytest.mark.parametrize("save_only", [False, True])
def test_current_contours_can_be_imported_or_saved_without_losing_original(
    app, pair_factory, tmp_path, monkeypatch, language, save_only
):
    source = pair_factory()
    session = Session(source)
    session.add(add_line(session.geometry(), (2, 3), (4, 5)))
    project = tmp_path / "edits.dale"
    save_project(session, project)
    before = project.read_bytes()
    original = source.json_path.read_bytes()
    destination = tmp_path / "selected.json"
    window = MainWindow()
    window.set_language(language, persist=False)
    window.load_sources(source.image_path, source.json_path)
    current = window.view.session
    from dale.dataset_manager import DatasetManager

    manager = DatasetManager(window)
    monkeypatch.setattr(
        "dale.dataset_manager.QFileDialog.getOpenFileName", lambda *args: (str(project), "")
    )
    monkeypatch.setattr("dale.ui.QFileDialog.getSaveFileName", lambda *args: (str(destination), ""))

    def choose_document():
        dialog = app.activeModalWidget()
        listing = dialog.findChild(QComboBox)
        assert listing.count() == 2 and listing.currentIndex() == 1
        expected = "Исправленные контуры" if language == "ru" else "Current contours"
        assert expected in listing.currentText()
        buttons = dialog.findChild(QDialogButtonBox)
        if save_only:
            button = next(b for b in buttons.buttons() if b.objectName() == "saveSelectedJson")
            assert button.toolTip()
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            assert dialog.isVisible() and destination.is_file()
        button = (
            buttons.button(QDialogButtonBox.StandardButton.Cancel)
            if save_only
            else next(b for b in buttons.buttons() if b.objectName() == "importSelectedJson")
        )
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)

    errors = []

    def choose():
        try:
            choose_document()
        except Exception as exc:
            errors.append(exc)
            app.activeModalWidget().reject()

    QTimer.singleShot(0, choose)
    manager.import_component("json")
    assert not errors, errors
    if save_only:
        assert window.view.session is current
        assert len(json.loads(destination.read_bytes())["walls"]) == len(session.walls)
    else:
        manager.apply(False)
        assert window.view.session.walls == session.walls
    manager.close()
    assert project.read_bytes() == before and source.json_path.read_bytes() == original
    monkeypatch.setattr(window, "can_discard", lambda: True)
    window.close()


def test_region_move_isolated_geometry_gestures_and_project_selection(app, pair_factory, tmp_path):
    source = pair_factory(
        size=(500, 400),
        walls=[
            {"c": [80, 80, 180, 80]},
            {"c": [180, 80, 180, 180]},
            {"c": [180, 180, 80, 180]},
            {"c": [80, 180, 80, 80]},
            {"c": [180, 130, 200, 130]},
        ],
    )
    window = MainWindow()
    window.show()
    window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Select regions")
    window.toggle_region_at((130, 130))
    original = window.view.session.geometry()
    original_pixels = window.view.item.pixmap().toImage()

    window.remembered_move_related = True
    window.view.move_related = True
    window.activate_mode("Move regions")
    assert window.view.mode == "Move regions"
    view = window.view
    app.processEvents()
    start = view.mapFromScene(QPointF(130, 130))
    end = start + QPoint(20, 10)
    before = view.mapToScene(start)
    after = view.mapToScene(end)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(view.viewport(), end)
    assert view.active_gesture
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
    assert len(view.session.operations) == 1
    assert len(window.selected_regions) == 1
    assert view.region_pivot == pytest.approx(
        (130 + after.x() - before.x(), 130 + after.y() - before.y())
    )
    assert ((180, 130), (200, 130)) in view.session.walls
    pivot = view.region_pivot
    shape = view.region_polygons[0]
    for mode, modifiers, expected_area in (
        ("Move regions", Qt.KeyboardModifier.ControlModifier, shape.area * 1.05**2),
        ("Rotate regions", Qt.KeyboardModifier.NoModifier, shape.area * 1.05**2),
    ):
        window.activate_mode(mode)
        wheel = QWheelEvent(
            QPointF(200, 150),
            QPointF(200, 150),
            QPoint(),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            modifiers,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        app.sendEvent(view.viewport(), wheel)
        assert view.region_polygons[0].area == pytest.approx(expected_area)
        assert view.region_pivot == pivot
    assert len(view.session.operations) == 3
    assert view.item.pixmap().toImage() == original_pixels
    window.project_path = tmp_path / "moving.dale"
    assert window.save_project_file()
    second = MainWindow()
    assert second.load_project_file(window.project_path)  # No question during restoration.
    assert second.view.mode == "Rotate regions" and second.view.move_related
    assert len(second.selected_regions) == 1
    assert second.view.session.geometry().lineage == view.session.geometry().lineage
    second.close()
    for _ in range(3):
        window.history(False)
    assert view.session.geometry() == original
    window.saved_state = window.document_state()
    window.close()


@pytest.mark.parametrize("accept", [False, True])
def test_auto_close_requires_cancel_or_yes_before_changing_geometry(app, pair_factory, accept):
    source = pair_factory(
        size=(200, 200),
        walls=[
            {"c": [20, 100, 180, 100]},
            {"c": [100, 100, 100, 180]},
        ],
    )
    window = MainWindow()
    window.show()
    window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Auto-close")
    app.processEvents()
    original = window.view.session.geometry()
    seen = []

    def answer():
        dialog = app.activeModalWidget()
        assert dialog.objectName() == "autoCloseConfirmation"
        assert sorted(button.text() for button in dialog.buttons()) == ["Да", "Отмена"]
        assert window.view.session.geometry() == original
        assert dialog.button(QMessageBox.StandardButton.Yes).isEnabled()
        seen.append(dialog.text())
        QTest.mouseClick(
            dialog.button(
                QMessageBox.StandardButton.Yes if accept else QMessageBox.StandardButton.Cancel
            ),
            Qt.MouseButton.LeftButton,
        )

    QTimer.singleShot(0, answer)
    QTest.mouseClick(
        window.view.viewport(), Qt.MouseButton.LeftButton, pos=window.view.mapFromScene(60, 100)
    )
    assert len(seen) == 1
    assert len(window.view.session.operations) == int(accept)
    if accept:
        assert len(window.view.session.walls) == 3
        window.history(False)
    assert window.view.session.geometry() == original
    assert not window.view.toolTip()
    assert not window.view.viewport().toolTip()
    window.saved_state = window.document_state()
    window.close()


def test_whole_map_close_uses_its_own_distance_and_one_confirmed_undo_step(app, pair_factory):
    source = pair_factory(
        size=(300, 200),
        walls=[
            {"c": [20, 30, 100, 30]},
            {"c": [104, 30, 180, 30]},
            {"c": [20, 140, 100, 140]},
            {"c": [104, 140, 180, 140]},
        ],
    )
    window = MainWindow()
    window.show()
    window.load_sources(source.image_path, source.json_path)
    window.global_close_control.setValue(20)
    window.auto_close_control.setValue(1)
    original = window.view.session.geometry()
    seen = []

    def answer():
        dialog = app.activeModalWidget()
        seen.append(dialog.text())
        assert not window.view.session.operations
        QTest.mouseClick(dialog.button(QMessageBox.StandardButton.Yes), Qt.MouseButton.LeftButton)

    QTimer.singleShot(0, answer)
    QTest.mouseClick(
        window.sized_tools["Close all contours"], Qt.MouseButton.LeftButton, pos=QPoint(24, 24)
    )
    assert len(seen) == 1
    assert len(window.view.session.operations) == 1
    walls = window.view.session.walls
    assert walls[0][1] == walls[1][0]
    assert walls[2][1] == walls[3][0]
    window.history(False)
    assert window.view.session.geometry() == original
    assert not window.statusBar().isVisible()
    assert window.information_group.title() == "Информация"
    assert window.settings_group.title() == "Настройки"
    assert window.map_info.parentWidget() == window.project_info_group
    window.saved_state = window.document_state()
    window.close()


@pytest.mark.parametrize("mode", ["Erase lines", "Erase vertices"])
@pytest.mark.parametrize("show_walls", [False, True])
def test_geometry_erasers_preview_exact_targets_in_white(app, pair_factory, mode, show_walls):
    source = pair_factory(
        size=(220, 200),
        walls=[
            {"c": [100, 50, 100, 150]},
            {"c": [160, 50, 160, 150]},
        ],
    )
    view = MapView()
    view.resize(600, 500)
    view.show()
    view.assign(Session(source), load_preview(source))
    view.setTransform(QTransform.fromScale(2, 2))
    view.centerOn(110, 100)
    view.set_mode(mode)
    view.show_walls = show_walls
    view.cursor_point = (100, 100) if mode == "Erase lines" else (100, 50)
    view.update_hover()
    assert not view.session.operations
    image = view.viewport().grab().toImage()
    if not show_walls:
        source_color = view.item.pixmap().toImage().pixelColor(0, 0).name()
        assert image.pixelColor(view.mapFromScene(160, 130)).name() == source_color
    if mode == "Erase lines":
        assert view.hover_path.boundingRect().left() == 100
        assert view.hover_path.boundingRect().right() == 100
        sample = view.mapFromScene(100, 130)
        colors = [image.pixelColor(sample.x() + dx, sample.y()).name() for dx in range(-3, 4)]
        assert any(colors[i : i + 3] == ["#ffffff", "#ff0000", "#ffffff"] for i in range(5))
    else:
        assert view.eraser_vertices == ((100, 50),)
        sample = view.mapFromScene(100, 50)
        assert image.pixelColor(sample).name() == "#ffffff"
    view.close()


@pytest.mark.parametrize("mode", ["Pan", *GEOMETRY_TOOLS, *REGION_TOOLS, "Erase", "Restore"])
def test_walls_off_hides_inactive_lines_and_handles_in_every_tool(app, pair_factory, mode):
    source = pair_factory(
        size=(220, 200),
        walls=[
            {"c": [20, 20, 100, 20]},
            {"c": [100, 20, 100, 100]},
            {"c": [100, 100, 20, 100]},
            {"c": [20, 100, 20, 20]},
            {"c": [140, 20, 200, 20]},
            {"c": [200, 20, 200, 100]},
            {"c": [200, 100, 140, 100]},
            {"c": [140, 100, 140, 20]},
            {"c": [30, 140, 100, 140]},
        ],
    )
    view = MapView()
    view.resize(600, 500)
    view.show()
    view.assign(Session(source), load_preview(source))
    view.setTransform(QTransform.fromScale(2, 2))
    view.centerOn(110, 100)
    view.set_mode(mode)
    view.show_walls = False
    source_color = view.item.pixmap().toImage().pixelColor(0, 0).name()

    def image_color(point):
        return view.viewport().grab().toImage().pixelColor(view.mapFromScene(*point)).name()

    for point in ((60, 20), (20, 20), (170, 20), (140, 20), (60, 140)):
        assert image_color(point) == source_color
    if mode in REGION_TOOLS:
        view.selected_path.addRect(QRectF(20, 20, 80, 80))
        assert image_color((60, 20)) == "#58d9ec"
        assert image_color((60, 60)) != source_color
        assert image_color((170, 20)) == source_color
    elif mode == "Edit points":
        view.cursor_point = (60, 20)
        view.update_hover()
        assert image_color((60, 20)) == "#58d9ec"
        assert image_color((170, 20)) == source_color
        assert image_color((140, 20)) == source_color
        view.cursor_point = None
        view.update_hover()
        assert image_color((60, 20)) == source_color
    view.show_walls = True
    assert image_color((170, 20)) == "#58d9ec"
    assert image_color((60, 140)) == "#ff0000"
    view.close()


def test_rotate_button_uses_plain_wheel_without_zoom_and_keeps_move_alt_free(
    app, pair_factory, tmp_path
):
    window = MainWindow()
    window.show()
    source = pair_factory()
    window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Select regions")
    window.toggle_region_at((30, 100))
    window.remembered_move_related = False
    original = window.view.session.geometry()
    image = window.view.item.pixmap().toImage()
    QTest.mouseClick(window.rotate_button, Qt.MouseButton.LeftButton)
    assert window.view.mode == "Rotate regions"
    assert window.current_tool_set == "regions"
    for language, token in (("ru", "Колесо"), ("en", "Wheel"), ("ru", "Колесо")):
        window.set_language(language, persist=False)
        assert token in window.rotate_button.toolTip()
        assert "Alt" in window.rotate_button.toolTip()
        assert "Alt" not in window.move_button.toolTip()
    view = window.view
    zoom = view.transform().m11()
    original_shape = view.region_polygons[0]
    for delta in (120, -120):
        wheel = QWheelEvent(
            QPointF(100, 100),
            QPointF(100, 100),
            QPoint(),
            QPoint(0, delta),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        app.sendEvent(view.viewport(), wheel)
        assert view.transform().m11() == zoom
        assert view.region_polygons[0].area == pytest.approx(original_shape.area)
        expected = rotate(original_shape, 0.1 if delta > 0 else 0, origin="center")
        assert view.region_polygons[0].hausdorff_distance(expected) < 1e-7
    assert len(view.session.operations) == 1
    assert view.region_polygons[0].hausdorff_distance(original_shape) < 1e-8
    assert view.item.pixmap().toImage() == image
    window.project_path = tmp_path / "rotate-mode.dale"
    assert window.save_project_file()
    second = MainWindow()
    assert second.load_project_file(window.project_path)
    assert second.view.mode == "Rotate regions" and second.rotate_button.isChecked()
    second.close()
    window.activate_mode("Move regions")
    before = view.session.geometry()
    wheel = QWheelEvent(
        QPointF(100, 100),
        QPointF(100, 100),
        QPoint(),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.AltModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    app.sendEvent(view.viewport(), wheel)
    assert view.session.geometry() == before and len(view.session.operations) == 1
    window.history(False)
    assert view.session.geometry() == original
    window.saved_state = window.document_state()
    window.close()


def test_auto_close_without_possible_changes_has_only_close(app, pair_factory):
    source = pair_factory()
    window = MainWindow()
    window.show()
    window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Auto-close")
    seen = []

    def answer():
        dialog = app.activeModalWidget()
        seen.append(dialog.text())
        assert dialog.objectName() == "autoCloseInformation"
        assert dialog.standardButtons() == QMessageBox.StandardButton.Close
        QTest.mouseClick(dialog.button(QMessageBox.StandardButton.Close), Qt.MouseButton.LeftButton)

    QTimer.singleShot(0, answer)
    QTest.mouseClick(
        window.view.viewport(), Qt.MouseButton.LeftButton, pos=window.view.mapFromScene(30, 20)
    )
    assert len(seen) == 1
    assert not window.view.session.operations
    window.close()


@pytest.mark.parametrize(
    "start,end,cursor,constrained",
    [
        ((50, 100), (150, 100), (190, 120), (190, 120)),
        ((50, 50), (150, 100), (170, 140), (170, 140)),
    ],
)
def test_alt_does_not_force_map_axes_without_adjacent_angle(
    app, pair_factory, start, end, cursor, constrained
):
    source = pair_factory(size=(250, 200), walls=[{"c": [*start, *end]}])
    view = MapView()
    view.resize(650, 500)
    view.show()
    view.assign(Session(source), load_preview(source))
    view.setTransform(QTransform.fromScale(2, 2))
    view.centerOn(125, 100)
    view.snap_enabled = False
    view.right_angle_alignment = True
    view.set_mode("Edit points")
    app.processEvents()
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(*end))
    QTest.mouseMove(view.viewport(), view.mapFromScene(*cursor))
    assert view.edit_preview.walls[0][1] == cursor
    QTest.keyPress(view, Qt.Key.Key_Alt)
    assert view.edit_preview.walls[0][1] == pytest.approx(constrained)
    QTest.keyRelease(view, Qt.Key.Key_Alt)
    assert view.edit_preview.walls[0][1] == cursor
    QTest.keyPress(view, Qt.Key.Key_Alt)
    QTest.mouseRelease(
        view.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.AltModifier,
        view.mapFromScene(*cursor),
    )
    QTest.keyRelease(view, Qt.Key.Key_Alt)
    assert view.session.walls[0][1] == pytest.approx(constrained)
    assert view.session.walls[0][0] == start
    assert len(view.session.operations) == 1
    view.close()


@pytest.mark.parametrize("zoom", [1, 3])
@pytest.mark.parametrize("side", [-1, 1])
def test_alt_drag_squares_both_neighbour_corners_and_previews_actual_joint(
    app, pair_factory, zoom, side
):
    source = pair_factory(
        size=(300, 220),
        walls=[
            {"c": c}
            for c in (
                [100, 80, 120, 100],
                [120, 100, 140, 80],
                [140, 80, 160, 100],
                [160, 100, 180, 80],
            )
        ],
    )
    view = MapView()
    view.resize(900, 750)
    view.assign(Session(source), load_preview(source))
    view.show()
    view.setTransform(QTransform.fromScale(zoom, zoom))
    view.centerOn(140, 100)
    view.set_mode("Edit points")
    view.snap_enabled = False
    view.right_angle_alignment = True
    view.right_angle_tolerance_deg = 3
    app.processEvents()
    initial = view.session.geometry()
    cursor = (140 + side, 82)
    target = (140 + side * 1.5, 81.5)
    for cancel in (True, False):
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(140, 80))
        QTest.mouseMove(view.viewport(), view.mapFromScene(*cursor))
        QTest.keyPress(view, Qt.Key.Key_Alt)
        assert view.angle_joint[1] == ((120, 100) if side < 0 else (160, 100))
        assert view.edit_preview.walls[1][1] == pytest.approx(target)
        assert view.edit_preview.walls[2][0] == pytest.approx(target)
        assert view.edit_preview.walls[0] == initial.walls[0]
        assert view.edit_preview.walls[3] == initial.walls[3]
        if cancel:
            QTest.keyClick(view, Qt.Key.Key_Escape)
            assert view.session.geometry() == initial and view.angle_joint is None
        QTest.mouseRelease(
            view.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.AltModifier,
            pos=view.mapFromScene(*cursor),
        )
        QTest.keyRelease(view, Qt.Key.Key_Alt)
    assert len(view.session.operations) == 1 and view.alignment_geometry is None
    assert view.session.walls[1][1] == pytest.approx(target)
    view.session.undo()
    assert view.session.geometry() == initial
    view.close()


def test_neighbour_angle_does_not_use_an_independent_coincident_contour(app, pair_factory):
    from dataclasses import replace

    source = pair_factory(
        size=(300, 220),
        walls=[{"c": c} for c in ([120, 100, 140, 80], [140, 80, 160, 100], [100, 80, 120, 100])],
    )
    session = Session(source)
    geometry = session.geometry()
    geometry = replace(
        geometry,
        lineage=tuple(
            replace(r, connection_group="own" if i < 2 else "other")
            for i, r in enumerate(geometry.lineage)
        ),
    )
    session.add(geometry)
    view = MapView()
    view.resize(900, 750)
    view.assign(session, load_preview(source))
    view.show()
    view.setTransform(QTransform.fromScale(2, 2))
    view.centerOn(140, 100)
    view.set_mode("Edit points")
    view.snap_enabled = False
    view.right_angle_alignment = True
    view.right_angle_tolerance_deg = 2
    app.processEvents()
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(140, 80))
    QTest.mouseMove(view.viewport(), view.mapFromScene(139, 82))
    QTest.keyPress(view, Qt.Key.Key_Alt)
    assert len(view.alignment_geometry.walls) == 2
    assert view.angle_joint is None and view.edit_preview.walls[0][1] == (139, 82)
    assert view.edit_preview.walls[2] == geometry.walls[2]
    QTest.keyClick(view, Qt.Key.Key_Escape)
    QTest.keyRelease(view, Qt.Key.Key_Alt)
    assert session.geometry() == geometry
    view.close()


@pytest.mark.parametrize("zoom", [1, 3])
def test_alt_drag_aligns_corner_on_two_guides_with_one_undo_and_escape(app, pair_factory, zoom):
    source = pair_factory(
        size=(300, 220),
        walls=[
            {"c": [40, 40, 140, 120]},
            {"c": [140, 120, 160, 160]},
            {"c": [157, 43, 157, 90]},
        ],
    )
    view = MapView()
    view.resize(900, 750)
    view.assign(Session(source), load_preview(source))
    view.show()
    view.setTransform(QTransform.fromScale(zoom, zoom))
    view.centerOn(140, 100)
    view.set_mode("Edit points")
    view.snap_distance = 5 * zoom
    view.right_angle_tolerance_deg = 5
    view.contour_alignment_distance_px = 5 * zoom
    view.right_angle_alignment = True
    view.contour_alignment = True
    app.processEvents()
    original = view.session.geometry()
    for cancel in (True, False):
        QTest.mousePress(
            view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(140, 120)
        )
        QTest.mouseMove(view.viewport(), view.mapFromScene(157, 43))
        QTest.keyPress(view, Qt.Key.Key_Alt)
        assert view.edit_preview.walls[:2] == (((40, 40), (160, 40)), ((160, 40), (160, 160)))
        assert len(view.alignment_guides) == 2
        assert view.angle_joint[1] == (160, 40)
        assert {view.angle_joint[0], view.angle_joint[2]} == {(40, 40), (160, 160)}
        assert view.edit_preview.walls[2] == original.walls[2]
        if cancel:
            QTest.keyClick(view, Qt.Key.Key_Escape)
            assert view.session.geometry() == original and not view.alignment_guides
        QTest.mouseRelease(
            view.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.AltModifier,
            view.mapFromScene(157, 43),
        )
        QTest.keyRelease(view, Qt.Key.Key_Alt)
    assert len(view.session.operations) == 1
    assert not view.alignment_guides
    view.session.undo()
    assert view.session.geometry() == original
    view.session.redo()
    assert view.session.walls[0][1] == (160, 40)
    view.close()


def test_safe_alt_drag_never_uses_hidden_floor_alignment_points(app, native_json_source):
    from dale.editing import alignment_points

    window = MainWindow()
    window.load_sources(None, native_json_source)
    index = next(
        i
        for i in range(window.layer_control.count())
        if window.layer_control.itemData(i) == "band:0.0:10.0"
    )
    window.layer_control.setCurrentIndex(index)
    view = window.view
    assert (12, 5) not in alignment_points(view.editing_geometry(), (10, 0))
    window.close()


@pytest.mark.parametrize(
    "right_angles,contour", [(False, False), (True, False), (False, True), (True, True)]
)
@pytest.mark.parametrize("alt", [False, True])
def test_alignment_buttons_are_independent_and_require_alt(
    app, pair_factory, right_angles, contour, alt
):
    source = pair_factory(
        size=(320, 220),
        walls=[
            {"c": [40, 40, 140, 120]},
            {"c": [140, 120, 160, 160]},
            {"c": [160, 160, 210, 80]},
        ],
    )
    window = MainWindow()
    window.load_sources(source.image_path, source.json_path)
    view = window.view
    view.setTransform(QTransform.fromScale(2, 2))
    view.centerOn(140, 100)
    window.activate_mode("Edit points")
    window.snap_action.setChecked(False)
    window.snap_distance.setValue(10)
    assert not view.right_angle_alignment and not view.contour_alignment
    for key, enabled in (("right_angle_alignment", right_angles), ("contour_alignment", contour)):
        action = window.alignment_actions[key]
        assert not action.icon().isNull() and action.toolTip()
        if enabled:
            action.trigger()
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(140, 120))
    QTest.mouseMove(view.viewport(), view.mapFromScene(208, 70))
    if alt:
        QTest.keyPress(view, Qt.Key.Key_Alt)
    expected = (210, 70) if alt and contour else (208, 70)
    assert view.edit_preview.walls[0][1] == expected
    assert bool(view.alignment_guides) == bool(alt and contour)
    QTest.keyClick(view, Qt.Key.Key_Escape)
    QTest.keyRelease(view, Qt.Key.Key_Alt)
    assert not view.session.operations
    window.close()


def test_alignment_switches_roundtrip_with_project_ui(app, pair_factory, tmp_path):
    window = MainWindow()
    window.load_sources(pair_factory().image_path, None)
    window.alignment_actions["contour_alignment"].trigger()
    window.project_path = tmp_path / "alignment.dale"
    assert window.save_project_file()
    second = MainWindow()
    assert second.load_project_file(window.project_path)
    assert second.view.contour_alignment and not second.view.right_angle_alignment
    assert second.alignment_actions["contour_alignment"].isChecked()
    second.close()
    window.close()


def test_region_selection_picks_minimal_cell_not_touching_neighbors_and_persists(
    app, pair_factory, tmp_path
):
    walls = [
        {"c": [10, 10, 190, 10]},
        {"c": [190, 10, 190, 190]},
        {"c": [190, 190, 10, 190]},
        {"c": [10, 190, 10, 10]},
        {"c": [100, 10, 100, 190]},
        {"c": [30, 30, 60, 30]},
        {"c": [60, 30, 60, 60]},
        {"c": [60, 60, 30, 60]},
        {"c": [30, 60, 30, 30]},
    ]
    source = pair_factory(size=(200, 200), walls=walls)
    window = MainWindow()
    window.show()
    window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Select regions")
    app.processEvents()
    assert len(window.regions) == 3
    QTest.mouseClick(
        window.view.viewport(), Qt.MouseButton.LeftButton, pos=window.view.mapFromScene(45, 45)
    )
    assert len(window.selected_regions) == 1
    assert window.regions[window.selected_region].bounds == (30, 30, 60, 60)
    assert window.view.selected_path.contains(QPointF(45, 45))
    assert not window.view.selected_path.contains(QPointF(140, 70))
    QTest.mouseClick(
        window.view.viewport(), Qt.MouseButton.LeftButton, pos=window.view.mapFromScene(140, 70)
    )
    assert len(window.selected_regions) == 2
    assert window.view.selected_path.contains(QPointF(140, 70))
    assert not window.view.selected_path.contains(QPointF(70, 100))
    window.contour_offset.setValue(500)
    assert "200 × 200" in window.map_info.text()
    window.brush_control.setValue(31)
    window.restore_brush_control.setValue(79)
    window.project_path = tmp_path / "selected-cells.dale"
    assert window.save_project_file()
    restored = MainWindow()
    assert restored.load_project_file(window.project_path)
    assert restored.selected_regions == window.selected_regions
    assert restored.current_tool_set == "regions"
    assert restored.contour_offset.value() == 500
    assert restored.view.raster_diameters == {
        "Erase": 31,
        "Restore": 79,
        "Erase square": 40,
        "Restore square": 40,
    }
    assert restored.tool_set_actions["geometry"].text() == "Вершины"
    assert restored.tool_set_actions["regions"].text() == "Области"
    assert restored.tool_set_actions["pixels"].text() == "Растр"
    restored.select_tool_set("pixels")
    assert not restored.snap_tile.isVisible()
    restored.saved_state = restored.document_state()
    window.close()
    restored.close()


def test_brush_drag_is_one_undo_step(app, pair_factory):
    source = pair_factory()
    view = MapView()
    view.resize(500, 700)
    view.show()
    view.assign(Session(source), load_preview(source))
    view.set_mode("Erase")
    app.processEvents()
    start, end = view.mapFromScene(20, 40), view.mapFromScene(50, 70)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(view.viewport(), end)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
    assert len(view.session.operations) == 1
    assert isinstance(view.session.operations[0], Stroke)
    view.session.undo()
    assert not view.session.operations
    view.close()


def test_contour_controls_update_topology_and_offset_preview_at_any_zoom(app, pair_factory):
    source = pair_factory(
        walls=[
            {"c": [10, 20, 60, 20]},
            {"c": [60, 20, 60, 270]},
            {"c": [60, 270, 10, 270]},
            {"c": [10, 270, 10, 23]},
        ]
    )
    window = MainWindow()
    window.view.assign(Session(source), load_preview(source))
    assert window.view.analysis.faces == 0
    window.gap_tolerance.setValue(3)
    assert window.view.analysis.faces == 1
    assert len(window.view.analysis.joins) == 1
    window.contour_offset.setValue(5)
    assert window.view.offset_path.boundingRect().left() == 5
    assert window.view.offset_path.boundingRect().right() == 65
    window.view.setTransform(QTransform.fromScale(12, 12))
    window.refresh()
    assert window.view.session.make_mask("outside").area.bounds == (5, 15, 65, 275)
    window.gap_tolerance.setValue(0)
    assert window.view.analysis.faces == 0
    window.close()


@pytest.mark.parametrize("zoom", [2, 5])
def test_edit_point_spacing_uses_fixed_screen_diameter(app, pair_factory, zoom):
    source = pair_factory(size=(200, 200), walls=[{"c": [50, 100, 150, 100]}])
    view = MapView()
    view.resize(500, 500)
    view.show()
    view.assign(Session(source), load_preview(source))
    view.setTransform(QTransform.fromScale(zoom, zoom))
    view.centerOn(100, 100)
    view.set_mode("Edit points")
    app.processEvents()
    assert view._handle_tolerance() * zoom == HANDLE_DIAMETER
    near = view.mapFromScene(50, 100) + QPoint(HANDLE_DIAMETER - 1, 0)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=near)
    assert len(vertices(view.session.geometry())) == 2
    assert not view.session.operations
    view.close()


def test_edit_points_click_drag_double_click_and_undo(app, pair_factory):
    source = pair_factory(size=(200, 200), walls=[{"c": [50, 100, 150, 100]}])
    view = MapView()
    view.resize(500, 500)
    view.show()
    view.assign(Session(source), load_preview(source))
    view.setTransform(QTransform.fromScale(2, 2))
    view.centerOn(100, 100)
    view.set_mode("Edit points")
    app.processEvents()
    middle = view.mapFromScene(100, 100)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=middle)
    assert len(vertices(view.session.geometry())) == 3
    assert len(view.session.operations) == 1
    point = next(point for point in vertices(view.session.geometry()) if 75 < point[0] < 125)
    start = view.mapFromScene(*point)
    end = start + QPoint(20, -20)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(view.viewport(), end)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
    assert len(view.session.operations) == 2
    point = next(point for point in vertices(view.session.geometry()) if 75 < point[0] < 125)
    assert point[1] == 90
    end = view.mapFromScene(*point)
    QTest.mouseMove(view.viewport(), end)
    assert view.cursor().shape() == Qt.CursorShape.PointingHandCursor
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
    assert len(vertices(view.session.geometry())) == 2
    view.session.undo()
    assert len(vertices(view.session.geometry())) == 3
    view.close()


@pytest.mark.parametrize("mode", ["Edit points", "Erase vertices"])
def test_branch_point_deletion_uses_standard_tools_and_undo(app, pair_factory, mode):
    source = pair_factory(
        size=(200, 200),
        walls=[{"c": [50, 100, 150, 100]}, {"c": [100, 100, 100, 150]}],
    )
    view = MapView()
    view.resize(500, 500)
    view.show()
    view.assign(Session(source), load_preview(source))
    original = view.session.geometry()
    view.setTransform(QTransform.fromScale(2, 2))
    view.centerOn(100, 100)
    view.set_mode(mode)
    app.processEvents()
    point = view.mapFromScene(100, 100)
    if mode == "Edit points":
        QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    else:
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert not view.session.geometry().walls
    assert len(view.session.operations) == 1
    view.session.undo()
    assert view.session.geometry() == original
    view.close()


def test_project_save_and_load_through_window_preserves_editing_state(app, pair_factory, tmp_path):
    source = pair_factory()
    first = MainWindow()
    first.load_sources(source.image_path, source.json_path)
    first.gap_tolerance.setValue(3)
    first.contour_offset.setValue(2)
    first.set_language("en")
    first.geometry_brush_control.setValue(37)
    first.vertex_brush_control.setValue(61)
    first.snap_distance.setValue(21)
    first.snap_action.setChecked(False)
    first.set_snapping(False)
    first.view.session.add(Stroke(((20, 30), (30, 40)), 3))
    first.auto_close_control.setValue(31)
    first.activate_mode("Auto-close")
    first.project_path = tmp_path / "ui-session.dale"
    assert first.save_project_file()
    assert first.can_discard()
    second = MainWindow()
    assert second.load_project_file(first.project_path)
    assert second.view.session.operations == first.view.session.operations
    assert second.gap_tolerance.value() == 3
    assert second.contour_offset.value() == 2
    assert second.view.mode == "Auto-close"
    assert second.view.auto_close_distance == 31
    assert second.language == "en"
    assert second.view.geometry_diameter == 37
    assert second.view.geometry_diameters == {"Erase lines": 37, "Erase vertices": 61}
    assert second.vertex_brush_control.value() == 61
    assert second.view.snap_distance == 21
    assert not second.view.snap_enabled
    assert second.can_discard()
    with load_project(first.project_path) as project:
        assert project.ui_state["auto_close_distance_px"] == 31
    first.close()
    second.close()


def test_image_only_png_project_opens_saves_and_reopens_without_semantic_pages(app, tmp_path):
    from PIL import Image

    image_path = tmp_path / "artwork.png"
    Image.new("RGBA", (80, 60), (40, 80, 120, 128)).save(image_path)
    first = MainWindow()
    assert first.load_sources(image_path, None)
    assert set(first.sidebar_pages) == {"project", "settings"}
    assert set(first.tool_set_actions) == {"geometry", "figures", "regions", "pixels"}
    assert not {"Select walls", "Paint wall properties", "Reset wall properties"}.intersection(
        first.mode_actions
    )
    assert first.view.session.source.size == (80, 60)
    first.project_path = tmp_path / "image-only.dale"
    assert first.save_project_file()
    second = MainWindow()
    assert second.load_project_file(first.project_path)
    assert second.view.session.source.json_path is None
    assert second.view.session.source.size == (80, 60)
    first.close()
    second.close()


@pytest.fixture
def native_json_source(tmp_path):
    path = tmp_path / "native.json"
    path.write_text(
        json.dumps(
            {
                "name": "Native repair",
                "width": 100,
                "height": 80,
                "walls": [
                    {
                        "_id": "shared",
                        "c": [0, 0, 10, 0],
                        "flags": {"wall-height": {"bottom": 0, "top": 20}},
                    },
                    {
                        "_id": "lower",
                        "c": [12, -5, 12, 5],
                        "flags": {"wall-height": {"bottom": 0, "top": 10}},
                    },
                    {
                        "_id": "upper",
                        "c": [12, -5, 12, 5],
                        "flags": {"wall-height": {"bottom": 10, "top": 20}},
                    },
                ],
                "regions": [{"behaviors": [{"system": {"destination": "Scene.A.Region.B"}}]}],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_json_opens_without_image_and_safe_close_export_keeps_native_records(
    app, native_json_source, tmp_path, monkeypatch
):
    from dale.session import SourceRepairEdit

    window = MainWindow()
    window.show()
    original = native_json_source.read_bytes()
    monkeypatch.setattr(
        "dale.ui.QFileDialog.getOpenFileName", lambda *_: (str(native_json_source), "")
    )
    assert window.load_sources(None, native_json_source)
    app.processEvents()
    assert window.view.session.source.image_path is None
    assert window.view.safe_json_repair and window.json_repair_control.isVisible()
    assert window.export_json_action.isEnabled() and not window.export_action.isEnabled()
    assert window.mode_actions["New line"].isEnabled()
    assert window.mode_actions["Edit points"].isEnabled()
    window.view.resetTransform()
    window.global_close_control.setValue(5)

    def approve():
        dialog = QApplication.activeModalWidget()
        assert dialog.objectName() == "autoCloseConfirmation"
        dialog.button(QMessageBox.StandardButton.Yes).click()

    QTimer.singleShot(0, approve)
    window.close_all_contours()
    assert len(window.view.session.operations) == 1
    assert isinstance(window.view.session.operations[0], SourceRepairEdit)
    assert len(window.view.session.walls) == 3
    destination = tmp_path / "repaired.json"
    monkeypatch.setattr("dale.ui.QFileDialog.getSaveFileName", lambda *_: (str(destination), ""))
    messages = []
    monkeypatch.setattr(window, "information", lambda *args: messages.append(args))
    window.export_json_action.trigger()
    assert messages[0][0] == "JSON exported"
    updated = json.loads(destination.read_text(encoding="utf-8"))
    assert updated["walls"][0]["c"] == [0, 0, 12, 0]
    assert [wall["_id"] for wall in updated["walls"]] == ["shared", "lower", "upper"]
    from dale.json_repair import export_repaired_json

    native_destination = tmp_path / "native-repaired.json"
    export_repaired_json(window.view.session, native_destination)
    assert destination.read_bytes() == native_destination.read_bytes()
    assert native_json_source.read_bytes() == original
    window.project_path = tmp_path / "repair.dale"
    assert window.save_project_file()
    second = MainWindow()
    assert second.load_project_file(window.project_path)
    assert second.view.safe_json_repair and second.view.session.source.image_path is None
    second.history(False)
    assert second.view.session.walls[0][1] == (10, 0)
    second.history(True)
    assert second.view.session.walls[0][1] == (12, 0)
    assert second.can_discard()
    window.close()
    second.close()


@pytest.mark.parametrize("language", ["ru", "en"])
def test_safe_json_controls_and_shortcuts_are_localized(app, native_json_source, language):
    window = MainWindow()
    assert window.load_sources(None, native_json_source)
    window.set_language(language, persist=False)
    assert window.json_repair_control.text() == window.t("Edit contours by height layers")
    assert "Ctrl+Shift+J" in window.mode_help.text()
    assert window.export_json_action.text() == window.t("Export JSON…")
    window.json_repair_control.setChecked(False)
    assert window.mode_actions["New line"].isEnabled()
    window.json_repair_control.setChecked(True)
    assert window.view.safe_json_repair and window.mode_actions["New line"].isEnabled()
    assert window.view.mode in ("Pan", "Auto-close", "Edit points", "New line")
    window.close()


def test_native_erasers_remain_enabled_with_collapsed_panel(app, native_json_source, pair_factory):
    window = MainWindow()
    source = pair_factory(size=(400, 400))
    assert window.load_sources(source.image_path, native_json_source)
    assert window.view.safe_json_repair
    window.set_sidebar_visible(False, persist=False)
    original = window.view.session.source.json_bytes
    for language in ("ru", "en", "ru"):
        window.set_language(language, persist=False)
        for mode in ("Erase lines", "Erase vertices"):
            action = window.mode_actions[mode]
            tile = window.geometry_eraser_tiles[mode]
            assert action.isEnabled() and tile.isEnabled()
            assert window.t("Preserve JSON when joining contours") not in tile.toolTip()
            assert tile.toolTip().count("Escape") == 1
        assert not window.right_panel_visible
    window.show_sidebar("project")
    window.json_repair_control.setChecked(False)
    assert not window.view.safe_json_repair
    assert all(window.mode_actions[mode].isEnabled() for mode in ("Erase lines", "Erase vertices"))
    assert "стрелкой" not in window.geometry_eraser_tiles["Erase lines"].toolTip()
    window.json_repair_control.setChecked(True)
    assert window.view.safe_json_repair
    assert window.view.session.source.json_bytes == original
    window.close()


def test_conflicting_layer_repair_reports_without_creating_history(
    app, native_json_source, monkeypatch
):
    raw = json.loads(native_json_source.read_text())
    raw["walls"][2]["c"] = [14, -5, 14, 5]
    native_json_source.write_text(json.dumps(raw), encoding="utf-8")
    window = MainWindow()
    assert window.load_sources(None, native_json_source)
    window.view.resetTransform()
    window.global_close_control.setValue(5)
    before = window.view.session.geometry()

    def close_report():
        dialog = QApplication.activeModalWidget()
        assert dialog.objectName() == "autoCloseInformation"
        assert (
            window.t(
                "Height bands: {layers}. Conflict groups left unchanged: {conflicts}.",
                layers=2,
                conflicts=1,
            )
            in dialog.text()
        )
        dialog.button(QMessageBox.StandardButton.Close).click()

    QTimer.singleShot(0, close_report)
    window.close_all_contours()
    assert window.view.session.geometry() == before and not window.view.session.operations
    window.close()


def choose_height(window, bottom=0, top=10, kind="band"):
    from dale.source_editing import source_layers

    layer = next(
        candidate
        for candidate in source_layers(window.view.session.source, window.view.session.geometry())
        if candidate.bottom == bottom and candidate.top == top and candidate.kind == kind
    )
    window.layer_control.setCurrentIndex(window.layer_control.findData(layer.key))
    return layer


def native_window(app, path):
    window = MainWindow()
    window.show()
    assert window.load_sources(None, path)
    window.view.setTransform(QTransform.fromScale(8, 8))
    window.view.centerOn(50, 40)
    app.processEvents()
    return window


def test_height_dropdown_shares_common_wall_and_exact_range_filters_without_edits(
    app, native_json_source
):
    window = native_window(app, native_json_source)
    original = window.view.session.geometry()
    assert window.layer_control.isVisible() and not window.region_control.isVisible()
    assert len(window.view.walls) == 3
    choose_height(window)
    assert window.view.walls == original.walls[:2]
    choose_height(window, 10, 20)
    assert window.view.walls == (original.walls[0], original.walls[2])
    choose_height(window, 0, 20, "range")
    assert window.view.walls == (original.walls[0],)
    assert window.view.session.geometry() == original and not window.view.session.operations
    for language in ("en", "ru", "en"):
        window.set_language(language, persist=False)
        assert window.regions_group.title() == window.t("Height layers")
        assert window.layer_control.currentData() == window.view.source_layer
        assert window.layer_control.count() == 4
    window.close()


def test_native_point_pointer_drag_moves_only_selected_independent_floor(
    app, native_json_source, monkeypatch
):
    from dale.json_repair import repaired_json_bytes

    raw = json.loads(native_json_source.read_text())
    raw["walls"] = [raw["walls"][1], raw["walls"][2]]
    raw["walls"][0]["c"] = raw["walls"][1]["c"] = [0, 0, 10, 0]
    native_json_source.write_text(json.dumps(raw), encoding="utf-8")
    window = native_window(app, native_json_source)
    choose_height(window)
    window.activate_mode("Edit points")
    window.view.snap_enabled = False
    view = window.view
    start, end = view.mapFromScene(10, 0), view.mapFromScene(12, 3)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(view.viewport(), end)
    assert view.edit_preview.walls[0][1] == (12, 3)
    assert view.edit_preview.walls[1][1] == (10, 0)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
    assert len(view.session.operations) == 1 and repaired_json_bytes(view.session)[1] == (0,)
    choose_height(window, 10, 20)
    assert view.walls == (((0, 0), (10, 0)),)
    window.history(False)
    assert view.session.walls[0][1] == (10, 0)
    window.history(True)
    assert view.session.walls[0][1] == (12, 3)
    monkeypatch.setattr(window, "can_discard", lambda: True)
    window.close()


def test_native_manual_line_pointer_export_and_project_restore_layer(
    app, native_json_source, tmp_path, monkeypatch
):
    window = native_window(app, native_json_source)
    layer = choose_height(window)
    window.activate_mode("New line")
    view = window.view
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(30, 30))
    QTest.mouseMove(view.viewport(), view.mapFromScene(50, 30))
    assert view.active_gesture and not view.session.operations
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(50, 30))
    assert len(view.session.operations) == 1 and len(view.session.walls) == 4
    assert view.session.walls[-1] == ((30, 30), (50, 30))
    path = tmp_path / "new-wall.json"
    monkeypatch.setattr("dale.ui.QFileDialog.getSaveFileName", lambda *_: (str(path), ""))
    monkeypatch.setattr(window, "information", lambda *_: None)
    window.export_json_action.trigger()
    data = json.loads(path.read_text())
    assert len(data["walls"]) == 4
    assert data["walls"][-1]["c"] == [30, 30, 50, 30]
    from dale.json_repair import export_repaired_json

    native_path = tmp_path / "native-new-wall.json"
    export_repaired_json(view.session, native_path)
    assert path.read_bytes() == native_path.read_bytes()
    added = data["walls"][-1]
    assert added["flags"]["wall-height"] == {"bottom": 0, "top": 10}
    assert added["move"] == added["sight"] == added["light"] == added["sound"] == 20
    assert added["door"] == added["ds"] == added["dir"] == 0
    assert data["walls"][:3] == json.loads(native_json_source.read_text())["walls"]
    window.project_path = tmp_path / "manual.dale"
    assert window.save_project_file()
    second = MainWindow()
    assert second.load_project_file(window.project_path)
    assert second.layer_control.currentData() == layer.key
    assert second.view.mode == "New line" and len(second.view.walls) == 3
    assert second.view.session.geometry().additions[0].native_id == added["_id"]
    second.close()
    window.close()


def test_native_layer_switch_cancels_new_line_and_zero_length_is_a_noop(app, native_json_source):
    window = native_window(app, native_json_source)
    window.activate_mode("New line")
    view = window.view
    messages = []
    view.message.connect(messages.append)
    point = view.mapFromScene(30, 30)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert messages == []
    choose_height(window)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseMove(view.viewport(), view.mapFromScene(50, 30))
    assert view.active_gesture
    choose_height(window, 10, 20)
    assert not view.active_gesture and not view.session.operations
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(50, 30))
    assert not view.session.operations
    window.close()


def test_native_point_tool_splits_and_deletes_with_scene_preservation(
    app, native_json_source, monkeypatch
):
    from dale.json_repair import repaired_json_bytes

    window = native_window(app, native_json_source)
    monkeypatch.setattr(window, "can_discard", lambda: True)
    choose_height(window)
    window.activate_mode("Edit points")
    view = window.view
    original = view.session.geometry()
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(5, 0))
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(10, 0))
    assert view.session.geometry() != original and len(view.session.operations) == 2
    exported = json.loads(repaired_json_bytes(view.session)[0])
    assert len(exported["walls"]) == 3
    assert {k: v for k, v in exported.items() if k != "walls"} == {
        k: v for k, v in view.session.source.raw.items() if k != "walls"
    }
    for language in ("ru", "en", "ru"):
        window.set_language(language, persist=False)
        assert window.t(
            "Click a line: add a point. Drag a point: move it. Double-click: delete it."
        ) in " ".join(window.mode_actions["Edit points"].toolTip().split())
        assert window.mode_actions["Edit points"].toolTip().count("Escape") == 1
    window.close()


def test_native_new_line_does_not_snap_to_hidden_floor(app, native_json_source, monkeypatch):
    raw = json.loads(native_json_source.read_text())
    raw["walls"][2]["c"] = [50, 31, 60, 31]
    native_json_source.write_text(json.dumps(raw))
    window = native_window(app, native_json_source)
    choose_height(window)
    window.activate_mode("New line")
    view = window.view
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(30, 30))
    QTest.mouseMove(view.viewport(), view.mapFromScene(50, 30))
    assert view.line_end == (50, 30)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(50, 30))
    assert view.session.walls[-1] == ((30, 30), (50, 30))
    monkeypatch.setattr(window, "can_discard", lambda: True)
    window.close()


def test_scoped_native_eraser_after_split_does_not_erase_other_floor(
    app, pair_factory, monkeypatch
):
    from dale.json_repair import repaired_json_bytes

    walls = [
        {
            "_id": f"Floor{i:011d}",
            "c": [20, 80, 220, 80],
            "door": i,
            "flags": {"wall-height": {"bottom": i * 10, "top": (i + 1) * 10}},
        }
        for i in (0, 1)
    ]
    source = pair_factory(size=(400, 400), walls=walls, lights=[{"opaque": [None, 2]}])
    window = MainWindow()
    window.show()
    monkeypatch.setattr(window, "can_discard", lambda: True)
    assert window.load_sources(source.image_path, source.json_path)
    view = window.view
    choose_height(window)
    view.setTransform(QTransform.fromScale(2, 2))
    view.centerOn(150, 100)
    app.processEvents()
    window.activate_mode("Edit points")
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(120, 80))
    result = json.loads(repaired_json_bytes(view.session)[0])
    assert len(result["walls"]) == 3 and walls[1] in result["walls"]
    window.activate_mode("Erase lines")
    for x in (70, 170):
        point = view.mapFromScene(x, 80)
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    result = json.loads(repaired_json_bytes(view.session)[0])
    assert result["walls"] == [walls[1]]
    assert result["lights"] == source.raw["lights"]
    assert view.source_layer == "all" and window.layer_control.currentData() == "all"
    window.history(False)
    assert len(json.loads(repaired_json_bytes(view.session)[0])["walls"]) == 2
    window.close()


def test_selected_band_diagnostics_ignore_open_graph_on_other_floor(app, native_json_source):
    raw = json.loads(native_json_source.read_text())
    shared = {"c": [20, 20, 20, 60], "flags": {"wall-height": {"bottom": 0, "top": 20}}}
    raw["walls"] = [
        shared,
        *[
            {"c": c, "flags": {"wall-height": {"bottom": 0, "top": 10}}}
            for c in ([20, 60, 60, 60], [60, 60, 60, 20], [60, 20, 20, 20])
        ],
    ]
    native_json_source.write_text(json.dumps(raw))
    window = native_window(app, native_json_source)
    choose_height(window)
    assert window.view.analysis.faces == 1 and not window.view.analysis.unresolved
    choose_height(window, 10, 20)
    assert window.view.analysis.faces == 0
    assert window.view.analysis.unresolved == (((20, 20), (20, 60)),)
    window.close()


def test_language_switch_updates_actions_tooltips_and_keeps_mode_keys(app, tmp_path):
    window = MainWindow(preferences_path=tmp_path / "language.json")
    assert window.language == "ru"
    assert window.mode_actions["Edit points"].text() == "Вершины контура"
    assert "Клик" in window.mode_actions["Edit points"].toolTip()
    assert "Escape" in window.mode_actions["Edit points"].toolTip()
    assert "Ctrl" in window.geometry_eraser_tiles["Erase lines"].toolTip()
    assert "Escape" in window.geometry_eraser_tiles["Erase vertices"].toolTip()
    assert "Ctrl" in window.geometry_eraser_tiles["Erase vertices"].toolTip()
    assert "Ctrl+E" in window.export_action.toolTip()
    assert "Клавиши:" in window.export_action.toolTip()
    window.language_control.setCurrentIndex(0)
    assert window.mode_actions["Edit points"].text() == "Edit contour vertices"
    assert "Click a line" in window.mode_actions["Edit points"].toolTip()
    assert "- Ctrl+E:" in window.export_action.toolTip()
    window.mode_actions["Edit points"].trigger()
    assert window.view.mode == "Edit points"
    window.language_control.setCurrentIndex(1)
    assert window.view.mode == "Edit points"
    assert window.menuBar().actions()[0].text() == "Файл"
    window.language_control.setCurrentIndex(0)
    assert window.menuBar().actions()[0].text() == "File"
    reopened = MainWindow(preferences_path=tmp_path / "language.json")
    assert reopened.language == "en"
    window.close()
    reopened.close()


def test_russian_review_dialog_and_standard_buttons(app, pair_factory, monkeypatch):
    source = pair_factory(
        walls=[
            {"c": [10, 20, 60, 20]},
            {"c": [60, 20, 60, 270]},
            {"c": [60, 270, 10, 270]},
            {"c": [10, 270, 10, 20]},
            {"c": [1, 1, 5, 5]},
        ]
    )
    window = MainWindow()
    window.load_sources(source.image_path, source.json_path)
    messages = []
    monkeypatch.setattr(
        window,
        "question",
        lambda title, text, *options: messages.append(text) or QMessageBox.StandardButton.No,
    )
    window.activate_mode("Select raster regions")
    window.toggle_region_at((30, 60))
    window.mask("outside")
    assert "Осталось незамкнутых" in messages[0]
    assert len(window.view.session.operations) == 1
    assert isinstance(window.view.session.operations[0], RasterSelectionEdit)
    dialog = QMessageBox(window)
    dialog.setStandardButtons(QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel)
    assert "Сохранить" in dialog.button(QMessageBox.StandardButton.Save).text()
    window.saved_state = window.document_state()
    window.close()


def test_new_line_press_release_and_later_vertex_drag_snap_to_existing_geometry(app, pair_factory):
    source = pair_factory(
        size=(200, 200),
        walls=[
            {"c": [50, 50, 150, 50]},
            {"c": [150, 50, 150, 150]},
        ],
    )
    view = MapView()
    view.resize(500, 500)
    view.show()
    view.assign(Session(source), load_preview(source))
    view.setTransform(QTransform.fromScale(2, 2))
    view.centerOn(100, 100)
    view.set_mode("New line")
    app.processEvents()
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(51, 51))
    assert view.line_start == (50, 50)
    assert not view.session.operations
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(149, 120))
    assert len(view.session.operations) == 1
    assert ((50, 50), (150, 120)) in view.session.walls
    view.set_mode("Edit points")
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(150, 120))
    QTest.mouseMove(view.viewport(), view.mapFromScene(149, 135))
    assert view.snap is None  # A moving T leg cannot snap to its own old supporting line.
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(149, 149))
    assert ((50, 50), (150, 150)) in view.session.walls
    view.session.undo()
    assert ((50, 50), (150, 120)) in view.session.walls
    view.close()


def test_geometry_eraser_drag_is_one_undo_step_and_escape_discards_preview(app, pair_factory):
    source = pair_factory(
        size=(200, 200),
        walls=[
            {"c": [50, 30, 50, 170]},
            {"c": [150, 30, 150, 170]},
        ],
    )
    view = MapView()
    view.resize(500, 500)
    view.show()
    view.assign(Session(source), load_preview(source))
    view.setTransform(QTransform.fromScale(2, 2))
    view.centerOn(100, 100)
    view.set_mode("Erase lines")
    app.processEvents()
    start, end = view.mapFromScene(30, 100), view.mapFromScene(170, 100)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(view.viewport(), end)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
    assert not view.session.walls
    assert len(view.session.operations) == 1
    view.session.undo()
    view.refresh()
    assert len(view.session.walls) == 2
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(50, 100))
    assert len(view.edit_preview.walls) == 1
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert len(view.session.walls) == 2
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    assert not view.session.operations
    view.close()


def test_ctrl_wheel_resizes_tools_globally_without_zooming_or_changing_language(app, pair_factory):
    source = pair_factory()
    window = MainWindow()
    window.show()
    window.load_sources(source.image_path, source.json_path)
    app.processEvents()

    def wheel(widget):
        event = QWheelEvent(
            QPointF(10, 10),
            QPointF(10, 10),
            QPoint(),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.ControlModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(widget, event)

    zoom = window.view.transform().m11()
    window.mode_actions["Erase"].trigger()
    wheel(window.info)
    assert window.view.diameter > 40
    assert window.brush_control.value() == window.view.diameter
    window.mode_actions["Erase lines"].trigger()
    wheel(window.language_control)
    assert window.view.geometry_diameter > 24
    line_size = window.view.geometry_diameter
    assert window.view.geometry_diameters["Erase vertices"] == 24
    window.mode_actions["Erase vertices"].trigger()
    wheel(window.info)
    assert window.view.geometry_diameter > 24
    assert window.vertex_brush_control.value() == window.view.geometry_diameter
    assert window.view.geometry_diameters["Erase lines"] == line_size
    window.mode_actions["Auto-close"].trigger()
    radius = window.view.auto_close_distance
    wheel(window.info)
    assert window.view.auto_close_distance == radius + 1
    assert window.auto_close_control.value() == radius + 1
    assert window.view.snap_distance == 14
    assert window.view.geometry_diameters["Erase lines"] == line_size
    assert window.language == "ru"
    wheel(window.snap_distance)
    assert window.view.snap_distance == 15
    assert window.view.transform().m11() == zoom
    window.close()


def test_sidebar_selection_shows_margin_dimensions_and_language(app, pair_factory):
    source = pair_factory()
    window = MainWindow()
    window.load_sources(source.image_path, source.json_path)
    window.region_control.setCurrentIndex(1)
    assert window.selected_region == 0
    assert "80 × 300" in window.map_info.text()
    assert "52 × 252" in window.map_info.text()
    assert "Замкнутых: 1" in window.map_info.text()
    assert "Незамкнутых: 0" in window.map_info.text()
    assert not window.view.selected_path.isEmpty()
    assert window.language_control.parentWidget() == window.settings_group
    window.set_language("en", persist=False)
    assert "Closed: 1" in window.map_info.text()
    assert window.selected_region == 0
    window.project_path = source.json_path.with_suffix(".dale")
    assert window.save_project_file()
    restored = MainWindow()
    assert restored.load_project_file(window.project_path)
    assert restored.selected_region == 0
    assert "52 × 252" in restored.map_info.text()
    window.close()
    restored.close()


def test_export_margin_tooltip_has_one_description_and_keeps_wheel_help(app):
    window = MainWindow()
    tile = window.sized_tools["Artwork offset (px)"]
    for language in ("ru", "en", "ru"):
        window.set_language(language, persist=False)
        for control in (tile, tile.editor(), tile.editor().lineEdit()):
            lines = control.toolTip().splitlines()
            assert len(lines) == len(set(lines))
            assert 5 <= len(lines) <= 12
            assert lines[0] == tile.defaultAction().text()
            assert lines[1].startswith("Назначение:" if language == "ru" else "Purpose:")
            assert control.toolTip().count("Ctrl") == 1
            assert "Ctrl" in lines[-1]
            assert "3 px" not in control.toolTip()
        assert ("изображения сцены" if language == "ru" else "scene image") in tile.toolTip()
    window.close()


def test_tooltip_sections_stay_stable_and_use_actual_shortcuts(app, tmp_path):
    window = MainWindow(preferences_path=tmp_path / "help.json")
    original = {}
    window.export_action.setShortcut("Ctrl+Alt+E")
    for language in ("ru", "en", "ru", "en", "ru"):
        window.set_language(language, persist=False)
        window.update_size_help()
        controls = [
            *(
                a
                for a in window.findChildren(QAction)
                if a.property("dale_tool_key") and not a.menu()
            ),
            window.manager_button,
            window.sidebar_toggle,
        ]
        for tile in window.sized_tools.values():
            controls.extend((tile, tile.editor(), tile.editor().lineEdit()))
            assert tile.toolTip().count("Ctrl") == 1
            assert tile.toolTip().count("Escape") <= 1
        snapshot = []
        for control in controls:
            tip = control.toolTip()
            assert not tip.startswith("Назначение:" if language == "ru" else "Purpose:")
            assert tip.splitlines()[1].startswith("Назначение:" if language == "ru" else "Purpose:")
            assert tip.count("Условие:" if language == "ru" else "Condition:") <= 1
            assert tip.count("Клавиши:" if language == "ru" else "Keys:") <= 1
            assert "No additional conditions." not in tip
            assert "no dedicated shortcut" not in tip
            lines = tip.splitlines()
            if isinstance(control, QAction):
                assert lines[0] == control.text().replace("&", "")
            assert len(lines) == len(set(lines))
            assert all(len(line) <= 68 for line in lines)
            snapshot.append(tip)
        if language in original:
            assert snapshot == original[language]
        else:
            original[language] = snapshot
        assert window.export_action.toolTip().count("Ctrl+Alt+E") == 1
        assert "Ctrl+E" not in window.export_action.toolTip()
        angle_tip = window.sized_tools["Right-angle alignment"].toolTip()
        assert angle_tip.count("Alt") == 1
        assert (
            "degrees" in window.right_angle_tolerance.toolTip()
            if language == "en"
            else "градусах" in window.right_angle_tolerance.toolTip()
        )
    window.close()


def test_artwork_control_is_left_and_global_padding_is_absent(app, pair_factory):
    source = pair_factory()
    window = MainWindow()
    window.load_sources(source.image_path, source.json_path)
    window.select_tool_set("regions")
    tile = window.sized_tools["Artwork offset (px)"]
    assert tile.editor() is window.contour_offset
    assert not hasattr(window, "export_padding_control")
    assert "export_padding_px" not in window.ui_state()
    window.region_control.setCurrentIndex(1)
    window.contour_offset.setValue(5)
    assert "62 × 262" in window.map_info.text()
    window.saved_state = window.document_state()
    window.close()


def test_global_tool_values_copy_and_restore_every_numeric_button_after_restart(app, tmp_path):
    path = tmp_path / "global.json"
    window = MainWindow(preferences_path=path)
    expected = {
        "circle_detail_steps": 7,
        "figure_scale_step_percent": 12,
        "line_eraser_diameter": 31,
        "vertex_eraser_diameter": 47,
        "raster_erase_diameter": 59,
        "raster_restore_diameter": 83,
        "raster_erase_square_diameter": 61,
        "raster_restore_square_diameter": 87,
        "auto_close_distance_px": 29,
        "global_close_distance_px": 61,
        "snap_distance_px": 17,
        "right_angle_tolerance_deg": 45,
        "contour_alignment_distance_px": 4321,
        "extension_distance_px": 26,
        "artwork_offset_px": -4,
        "figure_rotation_step_cdeg": 1,
        "figure_alt_rotation_step_cdeg": 725,
        "region_rotation_step_cdeg": 23,
        "region_alt_rotation_step_cdeg": 9000,
    }
    assert not window.global_tools_control.isChecked()
    for key, value in expected.items():
        window.tool_value_controls[key].setValue(value)
    window.global_tools_control.setChecked(True)
    assert json.loads(path.read_text())["tool_values"] == expected

    def increase_in_settings():
        from PySide6.QtWidgets import QDialogButtonBox, QSpinBox

        dialog = window.tool_settings_popup
        QTest.keyClick(dialog.findChild(QSpinBox, "toolSettingsValue"), Qt.Key.Key_Up)
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()

    QTimer.singleShot(0, increase_in_settings)
    window.show_tool_settings("Close all contours")
    QApplication.processEvents()
    expected["global_close_distance_px"] += 1
    assert json.loads(path.read_text())["tool_values"] == expected
    window.activate_mode("Erase")
    wheel = QWheelEvent(
        QPointF(10, 10),
        QPointF(10, 10),
        QPoint(),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(window.view.viewport(), wheel)
    expected["raster_erase_diameter"] = window.brush_control.value()
    assert expected["raster_erase_diameter"] > 59
    assert json.loads(path.read_text())["tool_values"] == expected
    window.close()
    restored = MainWindow(preferences_path=path)
    assert restored.global_tools_control.isChecked()
    assert restored.current_tool_values() == expected
    assert restored.view.raster_diameters == {
        "Erase": expected["raster_erase_diameter"],
        "Restore": 83,
        "Erase square": 61,
        "Restore square": 87,
    }
    assert restored.view.geometry_diameters == {"Erase lines": 31, "Erase vertices": 47}
    assert restored.view.snap_distance == 17 and restored.view.auto_close_distance == 29
    assert restored.view.circle_detail_steps == 7
    assert restored.view.rotation_steps == {
        "Rotate figures": (0.01, 7.25),
        "Rotate regions": (0.23, 90.0),
        "Rotate raster regions": (0.23, 90.0),
    }
    restored.close()


def test_global_settings_override_project_until_unchecked_and_do_not_overwrite_it(
    app, pair_factory, tmp_path
):
    source = pair_factory()
    project = MainWindow(preferences_path=tmp_path / "project-settings.json")
    project.load_sources(source.image_path, source.json_path)
    for i, control in enumerate(project.tool_value_controls.values()):
        control.setValue(i + 21 if control is not project.contour_offset else 2)
    expected_project = project.current_tool_values()
    project.project_path = tmp_path / "values.dale"
    assert project.save_project_file()
    project.close()

    path = tmp_path / "global-settings.json"
    window = MainWindow(preferences_path=path)
    for i, control in enumerate(window.tool_value_controls.values()):
        control.setValue(i + 41 if control is not window.contour_offset else 7)
    expected_global = window.current_tool_values()
    window.global_tools_control.setChecked(True)
    assert window.load_project_file(project.project_path)
    assert window.current_tool_values() == expected_global
    assert window.view.session.contour_offset == 7
    assert window._project_tool_values == expected_project
    window.project_path = tmp_path / "saved-with-globals.dale"
    assert window.save_project_file()
    with load_project(window.project_path) as saved:
        assert saved.session.contour_offset == 2
        for key, value in expected_project.items():
            if key != "artwork_offset_px":
                assert saved.ui_state[key] == value
    window.global_tools_control.setChecked(False)
    assert window.current_tool_values() == expected_project
    assert window.view.session.contour_offset == 2
    assert json.loads(path.read_text())["tool_values"] == expected_global
    assert json.loads(path.read_text())["global_tool_settings"] is False
    window.saved_state = window.document_state()
    window.close()


def test_main_selection_buttons_follow_hand_and_clear_regions_and_contour_highlights(
    app, pair_factory
):
    source = pair_factory()
    window = MainWindow()
    window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Select regions")
    window.toggle_region_at((30, 100))
    assert window.selected_regions
    # QAction order, independent of localized labels or viewport width.
    actions = window.basic_toolbar.actions()
    assert actions.index(window.select_all_action) == actions.index(window.mode_actions["Pan"]) + 1
    assert (
        actions.index(window.clear_selection_action) == actions.index(window.select_all_action) + 1
    )
    assert window.select_all_action not in window.figure_toolbar.actions()
    before = window.view.session.geometry(), tuple(window.view.session.operations)
    window.clear_selection_action.trigger()
    assert window.selected_regions == () and window.view.selected_path.isEmpty()
    window.activate_mode("Edit points")
    window.view.cursor_point = (10, 100)
    window.view.update_hover()
    assert window.view.highlighted_edges
    window.clear_selection_action.trigger()
    assert not window.view.highlighted_edges and window.view.cursor_point is None
    assert before == (window.view.session.geometry(), tuple(window.view.session.operations))
    assert window.view.mode == "Edit points"
    window.close()


@pytest.mark.parametrize("language", ["ru", "en"])
def test_sidebar_order_and_context_help_list_actual_available_window_shortcuts(
    app, language, pair_factory
):
    window = MainWindow()
    source = pair_factory()
    assert window.load_sources(source.image_path, source.json_path)
    window.view.raster_aids.configure(rulers=True)
    window.set_language(language, persist=False)
    groups = [
        window.sidebar_layout.itemAt(i).widget()
        for i in range(window.sidebar_layout.count())
        if window.sidebar_layout.itemAt(i).widget() is not None
    ]
    assert groups == [
        window.project_group,
        window.information_group,
    ]
    assert window.region_control.parentWidget() == window.regions_group
    assert window.map_info.parentWidget() == window.project_info_group
    assert window.project_group.layout().itemAt(0).widget() == window.regions_group
    assert window.project_group.layout().itemAt(1).widget() == window.project_info_group
    form = window.settings_group.layout()
    assert (
        form.getWidgetPosition(window.language_control)[0]
        < form.getWidgetPosition(window.global_tools_control)[0]
    )
    assert window.information_group.isAncestorOf(window.mode_help)
    for mode in window.mode_actions:
        window.activate_mode(mode, prompt=False)
        help_text = window.mode_help.text()
        assert window.mode_actions[mode].text() in help_text
        for keys in (
            "Ctrl+I",
            "Ctrl+O",
            "Ctrl+S",
            "Ctrl+Shift+S",
            "Ctrl+E",
            "Ctrl+Z",
            "Ctrl+Y",
            "Ctrl+Shift+A",
            "F:",
        ):
            assert keys in help_text
        if mode == "Rotate regions":
            assert ("Колесо: вращение" if language == "ru" else "Wheel: rotate") in help_text
            assert (
                "Правый клик по кнопке" if language == "ru" else "Right-click the tool button"
            ) not in help_text
            assert "Wheel: zoom" not in help_text and "Колесо: масштаб" not in help_text
    window.export_action.setEnabled(False)
    assert "Ctrl+E:" not in window.mode_help.text()
    window.export_action.setEnabled(True)
    assert "Ctrl+E:" in window.mode_help.text()
    window.close()


@pytest.mark.parametrize("language", ["ru", "en"])
def test_png_editor_sections_settings_and_shared_information_panels(app, language):
    window = MainWindow()
    window.resize(1224, 768)
    window.set_language(language, persist=False)
    window.show()
    app.processEvents()
    assert [bar.windowTitle() for bar in window.toolbars[:2]] == (
        ["Режимы", "Основное"] if language == "ru" else ["Modes", "Main"]
    )
    for action in window.basic_toolbar.actions():
        if action.property("dale_tool_key"):
            button = window.basic_toolbar.widgetForAction(action)
            assert button.width() == button.height() == 36
            assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
            assert not button.icon().isNull() and button.toolTip()
            assert button.isVisible()
            assert window.basic_toolbar.rect().contains(button.geometry())
    assert window.tool_stack.currentWidget().parentWidget() == window.tool_stack
    page = window.tool_stack.currentWidget()
    assert page.layout().itemAt(0).widget() == window.geometry_toolbar
    assert page.layout().itemAt(1).widget() == window.alignment_toolbars["geometry"]
    assert window.project_group.isVisible() and not window.settings_group.isVisible()
    assert set(window.sidebar_pages) == {"project", "settings"}
    window.activate_mode("Edit points")
    window.settings_action.trigger()
    assert window.settings_group.isVisible() and not window.project_group.isVisible()
    assert window.view.mode == "Edit points" and window.left_panel.isVisible()
    window.settings_action.trigger()
    assert window.project_group.isVisible()
    window.tool_set_actions["regions"].trigger()
    assert window.project_group.isVisible() and window.left_panel.isVisible()
    assert len({label.text() for label in window.mode_help_labels.values()}) == 1
    for key, group in window.information_groups.items():
        assert group.parentWidget() == window.sidebar_pages[key]
        assert group.title() == ("Информация" if language == "ru" else "Information")
    window.close()


def test_recent_projects_persist_reorder_cancel_and_keep_missing_entries(
    app, pair_factory, tmp_path, monkeypatch
):
    window = MainWindow()
    assert window.recent_menu.title() == "Последние проекты"
    assert not window.recent_menu.actions()[0].isEnabled()
    source = pair_factory()
    window.load_sources(source.image_path, source.json_path)
    first, second = tmp_path / "first.dale", tmp_path / "second.dale"
    window.project_path = first
    assert window.save_project_file()
    window.project_path = second
    assert window.save_project_file()
    assert window.recent_projects == [second, first]
    window.close()
    restored = MainWindow()
    assert restored.recent_projects == [second, first]
    restored.recent_menu.actions()[1].trigger()
    assert restored.project_path == first and restored.recent_projects == [first, second]
    monkeypatch.setattr(restored, "can_discard", lambda: False)
    restored.recent_menu.actions()[1].trigger()
    assert restored.project_path == first and restored.recent_projects == [first, second]
    second.unlink()
    restored.set_language("en", persist=False)
    missing = restored.recent_menu.actions()[1]
    assert not missing.isEnabled() and "unavailable" in missing.toolTip()
    assert str(second) in missing.toolTip()
    restored.recent_menu.actions()[-1].trigger()
    assert restored.recent_projects == [] and first.is_file()
    assert json.loads(restored.preferences_path.read_text())["recent_projects"] == []
    monkeypatch.setattr(restored, "can_discard", lambda: True)
    restored.close()


def test_large_png_bounds_do_not_block_ui_and_only_latest_snapshot_is_applied(
    app, pair_factory, monkeypatch
):
    from dale.bounds_preview import calculate_bounds
    from dale.overlay_export import export_regions, prepare_overlay
    from dale.raster import ExportCancelled

    started, release = threading.Event(), threading.Event()
    calls = []

    def delayed(session, polygons, cancelled=None, *, size_to_grid=False, grid_size=None):
        started.set()
        while not release.wait(0.005):
            if cancelled and cancelled():
                raise ExportCancelled()
        calls.append(session.contour_offset)
        return calculate_bounds(
            session, polygons, cancelled, size_to_grid=size_to_grid, grid_size=grid_size
        )

    monkeypatch.setattr("dale.bounds_preview.calculate_bounds", delayed)
    source = pair_factory(
        size=(1600, 1600),
        walls=[
            {"c": [*a, *b]}
            for a, b in [
                ((100, 100), (1400, 100)),
                ((1400, 100), (1400, 1400)),
                ((1400, 1400), (100, 1400)),
                ((100, 1400), (100, 100)),
            ]
        ],
    )
    w = MainWindow()
    w.show()
    w.load_sources(source.image_path, source.json_path)
    assert started.wait(2)
    assert "расчёт" in w.map_info.text()
    ticks = []
    QTimer.singleShot(0, lambda: ticks.append(True))
    QTest.qWait(15)
    assert ticks  # The UI loop runs while exact native alpha is deliberately held.
    w.contour_offset.setValue(10)
    w.contour_offset.setValue(20)
    w.activate_mode("New circle")
    QTest.mousePress(
        w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(800, 800)
    )
    release.set()

    def wait_until(predicate):
        loop, timeout, poll = QEventLoop(), QTimer(), QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        poll.timeout.connect(lambda: loop.quit() if predicate() else None)
        poll.start(20)
        timeout.start(15000)
        if not predicate():
            loop.exec()
        timeout.stop()
        poll.stop()
        assert predicate()

    wait_until(lambda: w.bounds_preview.worker is None)
    assert w.bounds_preview.worker is None
    assert w.view.active_gesture and "расчёт" in w.map_info.text()
    QTest.keyClick(w.view, Qt.Key.Key_Escape)
    wait_until(lambda: "расчёт" not in w.map_info.text())
    assert "расчёт" not in w.map_info.text() and "PNG:" in w.map_info.text()
    assert calls[-1] == 20 and 10 not in calls
    polygon = export_regions(w.view.session)[0]
    expected = prepare_overlay(w.view.session, polygon)[0]
    assert f"{expected[2] - expected[0]} × {expected[3] - expected[1]}" in w.map_info.text()
    w.saved_state = w.document_state()
    w.close()


def test_contour_edits_reuse_raster_but_raster_undo_redraws_it(app, pair_factory, monkeypatch):
    from dale.editing import add_line
    from dale.raster import render_preview

    view = MapView()
    source = pair_factory()
    view.assign(Session(source), load_preview(source))
    calls = []

    def rendered(*args):
        calls.append(True)
        return render_preview(*args)

    monkeypatch.setattr("dale.canvas.render_preview", rendered)
    view.session.add(add_line(view.session.geometry(), (5, 5), (20, 5)))
    view.refresh()
    assert not calls
    view.session.add(Stroke(((30, 100),), 10))
    view.refresh()
    assert len(calls) == 1
    view.session.undo()
    view.refresh()
    assert len(calls) == 2
    view.close()


@pytest.mark.parametrize("language", ["ru", "en"])
def test_scene_and_contour_terminology_in_all_visible_control_text(app, pair_factory, language):
    import re

    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QAbstractButton, QComboBox, QGroupBox, QLabel

    w = MainWindow()
    source = pair_factory(padding=0.25)
    w.load_sources(source.image_path, source.json_path)
    w.set_language(language, persist=False)
    for mode in w.mode_actions:
        w.activate_mode(mode, prompt=False)
        texts = []
        for c in [
            w,
            *w.findChildren(QLabel),
            *w.findChildren(QAbstractButton),
            *w.findChildren(QAction),
            *w.findChildren(QComboBox),
            *w.findChildren(QGroupBox),
        ]:
            texts.append(c.toolTip())
            if hasattr(c, "text"):
                texts.append(c.text())
            if hasattr(c, "title"):
                texts.append(c.title())
            if isinstance(c, QComboBox):
                texts.extend(c.itemText(i) for i in range(c.count()))
        unexpected = [
            text
            for text in texts
            if re.search(
                r"стен|\bwall(?:s)?\b|(?<!\.)\bJPG\b|(?<!\.)\bJPEG\b|другой JSON|another.*JSON",
                text,
                re.I,
            )
        ]
        assert not unexpected, (mode, unexpected)
    command = next(
        a for a in w.findChildren(QAction) if a.property("dale_tool_key") == "Dataset manager…"
    )
    assert ("Менеджер наборов" if language == "ru" else "Dataset manager") in command.toolTip()
    assert ("Показывать контуры" if language == "ru" else "Show contours") == w.walls_action.text()
    assert (
        "Проверьте совмещение" if language == "ru" else "Verify contour alignment"
    ) in w.info.text()
    w.close()


@pytest.mark.parametrize("language", ["en", "ru"])
def test_right_angle_popup_stages_degrees_and_neighbours_and_reopens(
    app, pair_factory, tmp_path, language
):
    window = MainWindow()
    window.can_discard = lambda: True
    source = pair_factory()
    assert window.load_sources(source.image_path, source.json_path)
    window.set_language(language, persist=False)
    window.show()
    app.processEvents()
    view = window.view
    assert view.right_angle_tolerance_deg == 5 and view.right_angle_neighbours
    button = window.sized_tools["Right-angle alignment"]
    position = button.rect().center()
    QApplication.sendEvent(
        button,
        QContextMenuEvent(QContextMenuEvent.Reason.Mouse, position, button.mapToGlobal(position)),
    )
    dialog = window.tool_settings_popup
    assert dialog and dialog.neighbours.isChecked()
    assert dialog.own_angle_priority.isChecked() and view.right_angle_own_priority
    assert dialog.own_angle_priority.text() == (
        "Own right-angle priority" if language == "en" else "Приоритет собственного прямого угла"
    )
    assert dialog.neighbours.text() == (
        "At adjacent vertices" if language == "en" else "По соседним вершинам"
    )
    assert (dialog.value.minimum(), dialog.value.maximum(), dialog.value.suffix()) == (1, 90, "°")
    dialog.neighbours.setChecked(False)
    dialog.own_angle_priority.setChecked(False)
    dialog.value.setValue(8)
    QTest.mouseClick(
        dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel), Qt.MouseButton.LeftButton
    )
    assert view.right_angle_neighbours and view.right_angle_tolerance_deg == 5
    assert view.right_angle_own_priority
    dialog = window.show_tool_settings("Right-angle alignment")
    dialog.neighbours.setChecked(False)
    dialog.own_angle_priority.setChecked(False)
    dialog.value.setValue(8)
    QTest.mouseClick(
        dialog.buttons.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton
    )
    assert not view.right_angle_neighbours and view.right_angle_tolerance_deg == 8
    assert not view.right_angle_own_priority
    assert not window.alignment_actions["right_angle_alignment"].isChecked()
    window.project_path = tmp_path / "Angle options.dale"
    assert window.save_project_file() and window.load_project_file(window.project_path)
    assert not view.right_angle_neighbours and view.right_angle_tolerance_deg == 8
    dialog = window.show_tool_settings("Right-angle alignment")
    assert not dialog.neighbours.isChecked() and dialog.value.value() == 8
    assert not dialog.own_angle_priority.isChecked() and not view.right_angle_own_priority
    dialog.reject()
    window.close()


@pytest.mark.parametrize("priority", [False, True])
@pytest.mark.parametrize("external", ["neighbour", "guide"])
def test_real_alt_drag_respects_own_angle_priority(app, pair_factory, priority, external):
    source = pair_factory(
        size=(500, 400),
        walls=[
            {"c": c}
            for c in (
                [0, 100, 100, 100],
                [100, 100, 140, 160],
                [140, 160, 300, 100],
            )
        ],
    )
    view = MapView()
    view.resize(800, 600)
    view.assign(Session(source), load_preview(source))
    view.show()
    view.setTransform(QTransform())
    view.centerOn(250, 200)
    view.set_mode("Edit points")
    view.snap_enabled = False
    view.right_angle_alignment = True
    view.right_angle_tolerance_deg = 6
    view.right_angle_own_priority = priority
    view.right_angle_neighbours = external == "neighbour"
    view.contour_alignment = external == "guide"
    view.contour_alignment_distance_px = 5
    app.processEvents()
    cursor = view.mapFromScene(102, 120)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(140, 160))
    QTest.mouseMove(view.viewport(), cursor)
    QTest.keyPress(view, Qt.Key.Key_Alt)
    target = view.edit_preview.walls[1][1]
    if priority:
        assert target[0] > 101
        assert view.angle_joint[1] == target
        assert not view.alignment_guides
    else:
        assert target == pytest.approx((100, 120))
        if external == "guide":
            assert not view.angle_joints and view.alignment_guides == ((0, (100, 100)),)
        else:
            assert len(view.angle_joints) == 1 and view.angle_joint[1] == (100, 100)
    QTest.keyRelease(view, Qt.Key.Key_Alt)
    assert view.edit_preview.walls[1][1] == (102, 120)
    QTest.keyPress(view, Qt.Key.Key_Alt)
    QTest.mouseRelease(
        view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier, pos=cursor
    )
    QTest.keyRelease(view, Qt.Key.Key_Alt)
    assert view.session.walls[1][1] == pytest.approx(target)
    assert len(view.session.operations) == 1
    view.session.undo()
    assert view.session.walls == Session(source).walls
    view.close()


@pytest.mark.parametrize("neighbours", [False, True])
def test_neighbour_option_controls_real_alt_drag(app, pair_factory, neighbours):
    source = pair_factory(
        size=(320, 220),
        walls=[{"c": c} for c in ([100, 80, 120, 100], [120, 100, 140, 80], [140, 80, 160, 100])],
    )
    view = MapView()
    view.resize(800, 600)
    view.assign(Session(source), load_preview(source))
    view.show()
    view.setTransform(QTransform.fromScale(2, 2))
    view.centerOn(140, 100)
    view.set_mode("Edit points")
    view.snap_enabled = False
    view.right_angle_alignment = True
    view.right_angle_tolerance_deg = 3
    view.right_angle_neighbours = neighbours
    app.processEvents()
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(140, 80))
    QTest.mouseMove(view.viewport(), view.mapFromScene(139, 82))
    QTest.keyPress(view, Qt.Key.Key_Alt)
    assert (view.angle_joint is not None) is neighbours
    assert view.edit_preview.walls[1][1] == ((138.5, 81.5) if neighbours else (139, 82))
    QTest.keyClick(view, Qt.Key.Key_Escape)
    QTest.keyRelease(view, Qt.Key.Key_Alt)
    assert not view.session.operations
    view.close()


@pytest.mark.parametrize("neighbours", [False, True])
@pytest.mark.parametrize("commit", [False, True])
def test_vertex_alt_drag_combines_three_angles_and_draws_all_guides(
    app, pair_factory, neighbours, commit
):
    source = pair_factory(
        size=(500, 450),
        walls=[
            {"c": c}
            for c in (
                [100, 100, 100, 300],
                [100, 300, 260, 240],
                [260, 240, 300, 100],
                [300, 100, 100, 100],
            )
        ],
    )
    view = MapView()
    view.resize(800, 600)
    view.assign(Session(source), load_preview(source))
    view.show()
    view.setTransform(QTransform())
    view.centerOn(250, 225)
    view.set_mode("Edit points")
    view.snap_enabled = False
    view.show_walls = False
    view.right_angle_alignment = True
    view.right_angle_tolerance_deg = 2
    view.right_angle_neighbours = neighbours
    app.processEvents()
    cursor = view.mapFromScene(300, 299)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(260, 240))
    QTest.mouseMove(view.viewport(), cursor)
    QTest.keyPress(view, Qt.Key.Key_Alt)
    assert len(view.angle_joints) == (3 if neighbours else 1)
    assert view.angle_joint == view.angle_joints[0]
    target = view.edit_preview.walls[1][1]
    if neighbours:
        assert target == pytest.approx((300, 300))
        for point in ((100, 200), (200, 100), (200, 300), (300, 200)):
            pixel = view.mapFromScene(*point)
            image = view.viewport().grab().toImage()
            assert any(
                image.pixelColor(pixel + QPoint(dx, dy)).name() == "#ffffff"
                for dx in (-1, 0, 1)
                for dy in (-1, 0, 1)
            )
    else:
        assert target != (300, 300)
    # Ordinary target snapping must preserve every accepted angle.
    view.snap_enabled = True
    QTest.keyRelease(view, Qt.Key.Key_Alt)
    assert not view.angle_joints
    QTest.keyPress(view, Qt.Key.Key_Alt)
    assert len(view.angle_joints) == (3 if neighbours else 1)
    if commit:
        QTest.mouseRelease(
            view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier, pos=cursor
        )
        assert len(view.session.operations) == 1
        assert view.session.walls[1][1] == pytest.approx(target)
    else:
        QTest.keyClick(view, Qt.Key.Key_Escape)
        assert not view.session.operations
    QTest.keyRelease(view, Qt.Key.Key_Alt)
    assert view.angle_joint is None and not view.angle_joints
    view.close()


@pytest.mark.parametrize("offscreen", [False, True])
def test_angle_highlight_draws_only_chosen_legs_even_with_offscreen_joint(
    app, pair_factory, offscreen
):
    if offscreen:
        coordinates = ([20, 300, 20, 100], [20, 100, 520, 100])
        vertex, cursor = (520, 100), (520, 110)
        probes, untouched = ((300, 100),), None
    else:
        coordinates = ([100, 200, 300, 200], [300, 200, 500, 200], [300, 200, 300, 600])
        vertex, cursor = (300, 200), (405, 305)
        probes, untouched = ((250, 250), (350, 350)), (450, 250)
    source = pair_factory(size=(1000, 700), walls=[{"c": c} for c in coordinates])
    view = MapView()
    view.resize(800, 600)
    view.assign(Session(source), load_preview(source))
    view.show()
    view.setTransform(QTransform.fromScale(1, 1))
    view.centerOn(550 if offscreen else 350, 250)
    view.set_mode("Edit points")
    view.snap_enabled = False
    view.right_angle_alignment = True
    view.right_angle_tolerance_deg = 3
    view.show_walls = False
    app.processEvents()
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(*vertex))
    QTest.mouseMove(view.viewport(), view.mapFromScene(*cursor))
    QTest.keyPress(view, Qt.Key.Key_Alt)
    guide = view.angle_joint
    assert guide is not None
    if offscreen:
        assert not view.viewport().rect().contains(view.mapFromScene(*guide[1]))
    else:
        assert {guide[0], guide[2]} == {(100, 200), (300, 600)}
        # Probe midpoints of the actual two highlighted legs and the excluded third leg.
        probes = tuple(
            tuple((p[i] + guide[1][i]) / 2 for i in (0, 1)) for p in (guide[0], guide[2])
        )
        untouched = tuple((p + q) / 2 for p, q in zip((500, 200), guide[1], strict=True))
    # Isolate guide paint from the ordinary point-drag hover overlay.
    hover, hover_warning = view.hover_path, view.hover_warning_path
    view.hover_path = view.hover_warning_path = QPainterPath()

    def foreground():
        image = QImage(view.viewport().size(), QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setWorldTransform(view.viewportTransform())
        view.drawForeground(painter, view.mapToScene(view.viewport().rect()).boundingRect())
        painter.end()
        return image

    image = foreground()
    view.angle_joint = None
    plain = foreground()

    def difference(point):
        p = view.mapFromScene(*point)
        return sum(
            image.pixelColor(x, y) != plain.pixelColor(x, y)
            for x in range(p.x() - 3, p.x() + 4)
            for y in range(p.y() - 3, p.y() + 4)
        )

    assert all(difference(p) > 0 for p in probes)
    if untouched:
        assert difference(untouched) == 0
    view.angle_joint = guide
    view.hover_path, view.hover_warning_path = hover, hover_warning
    if untouched:
        complete = foreground()
        p = view.mapFromScene(*untouched)
        assert not any(
            complete.pixelColor(x, y).name() == "#ffffff"
            for x in range(p.x() - 3, p.x() + 4)
            for y in range(p.y() - 3, p.y() + 4)
        )
    QTest.keyClick(view, Qt.Key.Key_Escape)
    QTest.keyRelease(view, Qt.Key.Key_Alt)
    view.close()
