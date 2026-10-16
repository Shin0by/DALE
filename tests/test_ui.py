"""Exercise actual Qt pointer events offscreen, without controlling the owner's desktop."""

import json
import os
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QKeySequence, QTransform, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QListWidget, QMessageBox
from shapely.affinity import rotate

from dale.canvas import GEOMETRY_TOOLS, HANDLE_DIAMETER, REGION_TOOLS, MapView
from dale.editing import circle_points, vertices
from dale.project_io import JsonDocument, load_project, save_project
from dale.raster import load_preview
from dale.session import Session, Stroke
from dale.ui import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


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

    def record_points(*args):
        result = circle_points(*args)
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
        "Open scene",
        "JSON",
        "Open project",
        "Recent projects",
        "Save project",
        "Save project as…",
        "Export PNGs",
        "Close scene",
        "Exit",
    ]
    assert keys(window.edit_menu) == ["Undo", "Redo", "Clear selection"]
    assert window.clear_selection_action in window.basic_toolbar.actions()
    assert len(window.toolbars) == 6
    assert window.toolbars[0] == window.tool_set_toolbar
    assert "New circle" in window.mode_actions
    for language in ("en", "ru"):
        window.set_language(language, persist=False)
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


@pytest.mark.parametrize("aliased_workspace", [False, True])
def test_json_command_replaces_walls_without_choosing_jpg_and_keeps_archive_image_alive(
    app, pair_factory, tmp_path, monkeypatch, aliased_workspace
):
    source = pair_factory()
    project = tmp_path / "source.dale"
    save_project(Session(source), project)
    json_dir = tmp_path / "json-input"
    json_dir.mkdir()
    alternative = json_dir / "alternate.json"
    raw = dict(source.raw, walls=[{"_id": "alternate", "c": [1, 2, 30, 40]}])
    alternative.write_text(json.dumps(raw), encoding="utf-8")
    window = MainWindow()
    assert window.load_project_file(project)
    workspace = window.loaded_project.workspace
    canonical_root = Path(workspace.name).resolve()
    if aliased_workspace:
        workspace.name = str(
            canonical_root.parent / ".." / canonical_root.parent.name / canonical_root.name
        )
        assert Path(workspace.name).resolve() == canonical_root
    image = window.view.session.source.image_path
    opened = []

    def choose(*args):
        opened.append(args)
        return str(alternative), ""

    monkeypatch.setattr("dale.ui.QFileDialog.getOpenFileName", choose)
    window.open_json()
    assert len(opened) == 1
    assert window.view.session.source.image_path == image and image.is_file()
    assert window.view.session.walls == (((1, 2), (30, 40)),)
    assert window.view.session.geometry().lineage[0].sources[0].foundry_id == "alternate"
    assert window.input_directory == json_dir
    output = tmp_path / "output"
    output.mkdir()
    window.project_path = output / "changed.dale"
    assert window.save_project_file()
    second = MainWindow()
    assert second.input_directory == json_dir and second.output_directory == output
    assert second.load_project_file(window.project_path)
    assert second.view.session.source.image_path.is_file()
    second.close()
    workspace.name = str(canonical_root)
    window.close()
    assert not image.exists()


@pytest.mark.parametrize("accept", [False, True])
def test_json_import_from_dale_shows_all_documents_and_uses_chosen_one(
    app, pair_factory, tmp_path, monkeypatch, accept
):
    source = pair_factory()
    updated = json.dumps(dict(source.raw, walls=[{"_id": "updated", "c": [5, 6, 70, 80]}])).encode()
    archive = tmp_path / "versions.dale"
    save_project(
        Session(
            source,
            json_documents=(JsonDocument("edit-1", "Updated contours.json", "updated", updated),),
        ),
        archive,
    )
    window = MainWindow()
    window.load_sources(source.image_path, source.json_path)
    original = window.view.session
    release = window.release_json_workspaces

    def release_with_alias(keep_current=False):
        for workspace in window.json_workspaces:
            root = Path(workspace.name).resolve()
            workspace.name = str(root.parent / ".." / root.parent.name / root.name)
            assert Path(workspace.name).resolve() == root
        release(keep_current)

    monkeypatch.setattr(window, "release_json_workspaces", release_with_alias)
    monkeypatch.setattr("dale.ui.QFileDialog.getOpenFileName", lambda *args: (str(archive), ""))

    def choose():
        dialog = app.activeModalWidget()
        assert dialog.objectName() == "jsonDocumentSelection"
        listing = dialog.findChild(QListWidget)
        assert listing.count() == 2
        assert "Исходный" in listing.item(0).text()
        assert "Обновлённый" in listing.item(1).text()
        listing.setCurrentRow(1)
        buttons = dialog.findChild(QDialogButtonBox)
        button = buttons.button(
            QDialogButtonBox.StandardButton.Ok if accept else QDialogButtonBox.StandardButton.Cancel
        )
        assert button.toolTip()
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)

    QTimer.singleShot(0, choose)
    window.open_json()
    assert window.view.session.source.image_path == source.image_path
    assert window.input_directory == archive.parent
    if accept:
        assert window.view.session.walls == (((5, 6), (70, 80)),)
        assert window.view.session.source.json_path.is_file()
        window.project_path = tmp_path / "imported.dale"
        assert window.save_project_file()
        with load_project(window.project_path) as loaded:
            assert loaded.session.source.json_path.read_bytes() == updated
    else:
        assert window.view.session is original
    window.close()


def test_region_move_dialog_remember_right_click_and_geometry_only_gestures(
    app, pair_factory, tmp_path
):
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

    def choose(yes, remember, rotation=False):
        dialog = app.activeModalWidget()
        assert dialog.objectName() == "regionMoveConfiguration"
        assert "Правый клик" in dialog.informativeText()
        assert ("Вращать" if rotation else "Перемещать") in dialog.text()
        dialog.checkBox().setChecked(remember)
        assert dialog.checkBox().toolTip()
        QTest.mouseClick(
            dialog.button(QMessageBox.StandardButton.Yes if yes else QMessageBox.StandardButton.No),
            Qt.MouseButton.LeftButton,
        )

    QTimer.singleShot(0, lambda: choose(False, True))
    window.activate_mode("Move regions")
    assert window.view.mode == "Move regions" and not window.view.move_related
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
    QTimer.singleShot(0, lambda: choose(True, True, rotation=True))
    window.rotate_button.customContextMenuRequested.emit(QPoint(20, 20))
    assert view.move_related and window.remembered_move_related
    window.project_path = tmp_path / "moving.dale"
    assert window.save_project_file()
    second = MainWindow()
    assert second.remembered_move_related is True
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
        assert "Alt" not in window.rotate_button.toolTip()
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
    assert len(view.session.operations) == 2
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
    assert view.session.geometry() == before and len(view.session.operations) == 2
    window.history(False)
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
        ((50, 100), (150, 100), (170, 130), (170, 100)),
        ((50, 50), (150, 100), (170, 140), (182, 116)),
    ],
)
def test_alt_point_drag_projects_to_line_and_can_toggle_mid_gesture(
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
    assert restored.view.raster_diameters == {"Erase": 31, "Restore": 79}
    assert restored.tool_set_actions["geometry"].text() == "Контуры"
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


def test_version_and_integer_elevation_controls(app):
    window = MainWindow()
    assert [window.elevation.itemText(i) for i in range(4)] == ["-20", "-15", "-10", "-5"]
    window.elevation.setCurrentText("17")
    window.version.setCurrentIndex(1)
    assert window.placement().foundry_major == 13
    assert window.placement().elevation_ft == 17
    window.version.setCurrentIndex(0)
    assert window.placement().foundry_major == 14
    window.elevation.setCurrentText("1.5")
    with pytest.raises(ValueError, match="whole"):
        window.placement()
    window.close()


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
    first.elevation.setCurrentText("17")
    first.set_language("en")
    first.geometry_brush_control.setValue(37)
    first.vertex_brush_control.setValue(61)
    first.snap_distance.setValue(21)
    first.snap_action.setChecked(False)
    first.set_snapping(False)
    first.version.setCurrentIndex(1)
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
    assert second.placement().elevation_ft == 17
    assert second.placement().foundry_major == 13
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


def test_language_switch_updates_actions_tooltips_and_keeps_mode_keys(app, tmp_path):
    window = MainWindow(preferences_path=tmp_path / "language.json")
    assert window.language == "ru"
    assert window.mode_actions["Edit points"].text() == "Точки контура"
    assert "Клик" in window.mode_actions["Edit points"].toolTip()
    assert "Escape" in window.mode_actions["Edit points"].toolTip()
    assert "Ctrl" in window.geometry_eraser_tiles["Erase lines"].toolTip()
    assert "Escape" in window.geometry_eraser_tiles["Erase vertices"].toolTip()
    assert "Ctrl" in window.geometry_eraser_tiles["Erase vertices"].increase_button.toolTip()
    assert "Ctrl+E" in window.export_action.toolTip()
    assert "Горячие клавиши" in window.export_action.toolTip()
    window.language_control.setCurrentIndex(0)
    assert window.mode_actions["Edit points"].text() == "Edit contour points"
    assert "Click a line" in window.mode_actions["Edit points"].toolTip()
    assert "Shortcut: Ctrl+E" in window.export_action.toolTip()
    window.mode_actions["Edit points"].trigger()
    assert window.view.mode == "Edit points"
    window.language_control.setCurrentIndex(1)
    assert window.view.mode == "Edit points"
    window.elevation.setCurrentText("17")
    assert "17 футов" in window.placement_hint.text()
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
    window.mask("outside")
    assert "Осталось незамкнутых" in messages[0]
    assert not window.view.session.operations
    dialog = QMessageBox(window)
    dialog.setStandardButtons(QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel)
    assert "Сохранить" in dialog.button(QMessageBox.StandardButton.Save).text()
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
            assert len(lines) == 3  # Name, source-artwork meaning, Ctrl+wheel.
            assert "Ctrl" in lines[-1]
            assert "3 px" not in control.toolTip()
        assert ("изображения сцены" if language == "ru" else "scene image") in tile.toolTip()
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
        "line_eraser_diameter": 31,
        "vertex_eraser_diameter": 47,
        "raster_erase_diameter": 59,
        "raster_restore_diameter": 83,
        "auto_close_distance_px": 29,
        "global_close_distance_px": 61,
        "snap_distance_px": 17,
        "artwork_offset_px": -4,
    }
    assert not window.global_tools_control.isChecked()
    for key, value in expected.items():
        window.tool_value_controls[key].setValue(value)
    window.global_tools_control.setChecked(True)
    assert json.loads(path.read_text())["tool_values"] == expected
    QTest.mouseClick(
        window.sized_tools["Close all contours"].increase_button, Qt.MouseButton.LeftButton
    )
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
    }
    assert restored.view.geometry_diameters == {"Erase lines": 31, "Erase vertices": 47}
    assert restored.view.snap_distance == 17 and restored.view.auto_close_distance == 29
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


def test_clear_selection_follows_hand_and_clears_regions_and_contour_highlights(app, pair_factory):
    source = pair_factory()
    window = MainWindow()
    window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Select regions")
    window.toggle_region_at((30, 100))
    assert window.selected_regions
    # QAction order, independent of localized labels or viewport width.
    actions = window.basic_toolbar.actions()
    assert (
        actions.index(window.clear_selection_action)
        == actions.index(window.mode_actions["Pan"]) + 1
    )
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
def test_sidebar_order_and_context_help_list_actual_available_window_shortcuts(app, language):
    window = MainWindow()
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
            ) in help_text
            assert "Wheel: zoom" not in help_text and "Колесо: масштаб" not in help_text
    window.export_action.setEnabled(False)
    assert "Ctrl+E:" not in window.mode_help.text()
    window.export_action.setEnabled(True)
    assert "Ctrl+E:" in window.mode_help.text()
    window.close()


@pytest.mark.parametrize("language", ["ru", "en"])
def test_sections_scene_settings_and_shared_information_panels(app, language):
    window = MainWindow()
    window.resize(1024, 768)
    window.set_language(language, persist=False)
    window.show()
    app.processEvents()
    assert [bar.windowTitle() for bar in window.toolbars[:3]] == (
        ["Разделы", "Сцена", "Основное"] if language == "ru" else ["Sections", "Scene", "Main"]
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
    assert window.tool_stack.currentWidget().orientation() == Qt.Orientation.Vertical
    assert window.project_group.isVisible() and not window.settings_group.isVisible()
    window.levels_action.trigger()
    app.processEvents()
    assert window.scene_group.isVisible() and window.scene_levels_group.isVisible()
    assert not window.project_group.isVisible() and not window.settings_group.isVisible()
    assert window.left_panel.isVisible()
    assert window.view.mode == "Pan"
    assert window.t("Left-drag: pan the scene image.") in window.mode_help.text()
    window.settings_action.trigger()
    assert window.settings_group.isVisible() and not window.scene_group.isVisible()
    assert not window.project_info_group.isVisible() and not window.regions_group.isVisible()
    window.settings_action.trigger()
    assert window.scene_group.isVisible()
    window.tool_set_actions["regions"].trigger()
    assert window.project_group.isVisible() and not window.scene_group.isVisible()
    assert window.left_panel.isVisible() and not window.levels_action.isChecked()
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

    def delayed(session, polygons, cancelled=None):
        started.set()
        while not release.wait(0.005):
            if cancelled and cancelled():
                raise ExportCancelled()
        calls.append(session.contour_offset)
        return calculate_bounds(session, polygons, cancelled)

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
    deadline = time.monotonic() + 4
    while w.bounds_preview.worker is not None and time.monotonic() < deadline:
        QTest.qWait(10)
    assert w.bounds_preview.worker is None
    assert w.view.active_gesture and "расчёт" in w.map_info.text()
    QTest.keyClick(w.view, Qt.Key.Key_Escape)
    while "расчёт" in w.map_info.text() and time.monotonic() < deadline:
        QTest.qWait(10)
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
            # Semantic wall presets are explicitly named walls by the owner.
            if not isinstance(c, QAction) and (
                c == w.templates_panel or w.templates_panel.isAncestorOf(c)
            ):
                continue
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
    command = next(a for a in w.findChildren(QAction) if a.property("dale_tool_key") == "JSON")
    assert (
        "Загрузить JSON сцены" if language == "ru" else "Load a scene JSON"
    ) in command.toolTip()
    assert ("Показывать контуры" if language == "ru" else "Show contours") == w.walls_action.text()
    assert (
        "Проверьте совмещение" if language == "ru" else "Verify contour alignment"
    ) in w.info.text()
    w.close()
