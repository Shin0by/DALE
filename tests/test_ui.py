"""Exercise actual Qt pointer events offscreen, without controlling the owner's desktop."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QTransform, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from dale.canvas import HANDLE_DIAMETER, MapView
from dale.editing import vertices
from dale.project_io import load_project
from dale.raster import load_preview
from dale.session import Closure, Session, Stroke
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
        "Closure",
        "Edit points",
        "New line",
        "Erase lines",
        "Erase vertices",
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


def test_closure_click_modifiers_and_escape(app, pair_factory):
    source = pair_factory(walls=[{"c": [10, 20, 60, 20]}, {"c": [60, 20, 60, 270]}])
    view = MapView()
    view.resize(500, 700)
    view.show()
    view.assign(Session(source), load_preview(source))
    view.set_mode("Closure")
    app.processEvents()

    def click(point, modifiers=Qt.KeyboardModifier.NoModifier):
        QTest.mouseClick(
            view.viewport(), Qt.MouseButton.LeftButton, modifiers, view.mapFromScene(*point)
        )

    click((30, 21))
    assert len(view.pending) == 1
    assert view.pending[0][1] == 20
    click((15, 130), Qt.KeyboardModifier.AltModifier)
    click((25, 220), Qt.KeyboardModifier.AltModifier)
    click((59, 250))
    assert isinstance(view.session.operations[0], Closure)
    assert len(view.session.operations[0].points) == 4
    assert view.session.operations[0].points[-1][0] == 60
    click((30, 20))
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert not view.pending
    assert len(view.session.operations) == 1
    view.close()


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


def test_project_save_and_load_through_window_preserves_editing_state(app, pair_factory, tmp_path):
    source = pair_factory()
    first = MainWindow()
    first.load_sources(source.image_path, source.json_path)
    first.gap_tolerance.setValue(3)
    first.contour_offset.setValue(2)
    first.elevation.setCurrentText("17")
    first.set_language("en")
    first.geometry_brush_control.setValue(37)
    first.snap_distance.setValue(21)
    first.snap_action.setChecked(False)
    first.set_snapping(False)
    first.version.setCurrentIndex(1)
    first.view.session.add(Stroke(((20, 30), (30, 40)), 3))
    first.view.pending = [(10, 20), (30, 40)]
    first.view.set_mode("Closure")
    first.view.pending = [(10, 20), (30, 40)]
    first.project_path = tmp_path / "ui-session.dale"
    assert first.save_project_file()
    assert first.can_discard()
    second = MainWindow()
    assert second.load_project_file(first.project_path)
    assert second.view.session.operations == first.view.session.operations
    assert second.view.pending == first.view.pending
    assert second.gap_tolerance.value() == 3
    assert second.contour_offset.value() == 2
    assert second.placement().elevation_ft == 17
    assert second.placement().foundry_major == 13
    assert second.view.mode == "Closure"
    assert second.language == "en"
    assert second.view.geometry_diameter == 37
    assert second.view.snap_distance == 21
    assert not second.view.snap_enabled
    assert second.can_discard()
    with load_project(first.project_path) as project:
        assert project.ui_state["pending_closure"] == ((10, 20), (30, 40))
    first.close()
    second.close()


def test_language_switch_updates_actions_tooltips_and_keeps_mode_keys(app, tmp_path):
    window = MainWindow(preferences_path=tmp_path / "language.json")
    assert window.language == "ru"
    assert window.mode_actions["Edit points"].text() == "Точки"
    assert "Клик" in window.mode_actions["Edit points"].toolTip()
    window.language_control.setCurrentIndex(0)
    assert window.mode_actions["Edit points"].text() == "Edit points"
    assert "Click a line" in window.mode_actions["Edit points"].toolTip()
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
    assert window.language == "ru"
    wheel(window.snap_distance)
    assert window.view.snap_distance == 15
    assert window.view.transform().m11() == zoom
    window.close()


def test_footer_selection_shows_exact_guarded_export_dimensions_and_language(app, pair_factory):
    source = pair_factory()
    window = MainWindow()
    window.load_sources(source.image_path, source.json_path)
    window.region_control.setCurrentIndex(1)
    assert window.selected_region == 0
    assert "80 × 300" in window.footer_label.text()
    assert "57 × 257" in window.footer_label.text()
    assert "Замкнутых: 1" in window.footer_label.text()
    assert "Незамкнутых: 0" in window.footer_label.text()
    assert not window.view.selected_path.isEmpty()
    assert window.language_control.parentWidget() == window.statusBar()
    window.set_language("en", persist=False)
    assert "Closed: 1" in window.footer_label.text()
    assert window.selected_region == 0
    window.project_path = source.json_path.with_suffix(".dale")
    assert window.save_project_file()
    restored = MainWindow()
    assert restored.load_project_file(window.project_path)
    assert restored.selected_region == 0
    assert "57 × 257" in restored.footer_label.text()
    window.close()
    restored.close()
