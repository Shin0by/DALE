"""Contour scaling wheel routes, persistent step and selection-aware move cursor."""

import os
from itertools import pairwise

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QTransform, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSpinBox
from shapely.geometry import box

from dale.preferences import load_tool_values, save_tool_value
from dale.project_io import _load_ui, load_project
from dale.ui import MainWindow, configure_application


@pytest.fixture
def window(tmp_path, pair_factory):
    app = QApplication.instance() or QApplication([])
    if not app.property("catalog_test_style"):
        configure_application(app)
        app.setProperty("catalog_test_style", True)
    w = MainWindow(preferences_path=tmp_path / "settings.json")
    w.can_discard = lambda: True
    w.warning = lambda *args: pytest.fail(str(args))
    w.show()
    source = pair_factory(
        size=(400, 300),
        walls=[
            {"c": [*a, *b]}
            for shape in (box(30, 30, 90, 90), box(170, 30, 230, 90))
            for a, b in pairwise(shape.exterior.coords)
        ],
    )
    assert w.load_sources(source.image_path, source.json_path)
    w.select_tool_set("figures")
    w.view.figure_line_ids = tuple(r.id for r in w.view.session.geometry().lineage[:4])
    w.update_map_info()
    w.view.setTransform(QTransform.fromScale(1, 1))
    w.view.centerOn(200, 150)
    app.processEvents()
    yield w
    w.close()
    w.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def wheel(window, route="viewport", delta=120, ctrl=False):
    target = {
        "viewport": window.view.viewport(),
        "canvas": window.view,
        "sidebar": window.map_info,
        "button": window.sized_tools["Scale figures"],
        "field": window.figure_scale_control.lineEdit(),
    }[route]
    point = target.rect().center()
    event = QWheelEvent(
        QPointF(point),
        QPointF(target.mapToGlobal(point)),
        QPoint(),
        QPoint(0, delta),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ControlModifier if ctrl else Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    if route == "canvas":
        window.view.wheelEvent(event)
    else:
        QApplication.sendEvent(target, event)


@pytest.mark.parametrize("route", ["viewport", "canvas", "sidebar", "button", "field"])
def test_contour_scale_wheel_routes_and_shared_move_step(window, route):
    view = window.view
    original = view.session.geometry()
    pixels = view.item.pixmap().toImage()
    camera = view.transform()
    ids = view.figure_line_ids
    window.activate_mode("Scale figures")
    wheel(window, route, ctrl=True)
    assert view.figure_scale_step_percent == window.figure_scale_control.value() == 6
    assert view.session.geometry() == original and not view.session.operations
    wheel(window, route)
    scaled = view.session.geometry()
    by_id = dict(zip((r.id for r in scaled.lineage), scaled.walls, strict=True))
    for record, edge in zip(original.lineage, original.walls, strict=True):
        if record.id in ids:
            for actual, point in zip(by_id[record.id], edge, strict=True):
                assert actual == pytest.approx(tuple(60 + (v - 60) * 1.06 for v in point))
        else:
            assert by_id[record.id] == edge
    assert {r.id: r for r in scaled.lineage} == {r.id: r for r in original.lineage}
    assert view.figure_line_ids == ids
    assert len(view.session.operations) == 1
    assert view.item.pixmap().toImage() == pixels and view.transform() == camera
    window.history(False)
    assert view.session.geometry() == original
    window.history(True)
    assert view.session.geometry() == scaled
    window.activate_mode("Move figures")
    wheel(window, "viewport", delta=-120, ctrl=True)
    restored = dict(
        zip(
            (r.id for r in view.session.geometry().lineage),
            view.session.geometry().walls,
            strict=True,
        )
    )
    for record, edge in zip(original.lineage, original.walls, strict=True):
        for actual, point in zip(restored[record.id], edge, strict=True):
            assert actual == pytest.approx(point)
    assert view.figure_scale_step_percent == 6 and view.transform() == camera
    assert len(view.session.operations) == 2


@pytest.mark.parametrize("language", ["ru", "en"])
def test_contour_scale_inline_field_popup_and_language(window, language):
    window.set_language(language, persist=False)
    window.activate_mode("Scale figures")
    button = window.sized_tools["Scale figures"]
    field = window.figure_scale_control
    assert button.isVisible() and button.size().toTuple() == (48, 60)
    assert field.isVisible() and field.size().toTuple() == (30, 16)
    assert field.y() > 24 and button.rect().contains(field.geometry())
    assert not button.icon().isNull()
    assert window.mode_actions["Scale figures"].text() == window.t("Scale contours")
    assert field.toolTip().splitlines()[0] == window.t("Scale contours")
    assert window.t("Wheel: zoom at cursor.") not in window.mode_help.text()
    for apply in (False, True):
        popup = window.show_tool_settings("Scale figures")
        editor = popup.findChild(QSpinBox, "toolSettingsValue")
        editor.setValue(23)
        popup.accept() if apply else popup.reject()
        assert field.value() == (23 if apply else 5)
    window.set_language("en" if language == "ru" else "ru", persist=False)
    window.set_language(language, persist=False)
    assert button.toolTip().splitlines()[0] == window.t("Scale contours")
    assert button.toolTip().count(window.t("Ctrl+wheel: change this value.")) == 1
    window.figure_scale_control.setValue(100)
    wheel(window, ctrl=True)
    assert field.value() == 100
    field.setValue(1)
    wheel(window, delta=-120, ctrl=True)
    assert field.value() == 1
    assert not window.view.session.operations


def test_contour_scale_project_and_global_precedence(window, tmp_path):
    window.activate_mode("Scale figures")
    window.figure_scale_control.setValue(13)
    window.set_global_tool_settings(True)
    window.figure_scale_control.setValue(27)
    assert load_tool_values(window.preferences_path)["figure_scale_step_percent"] == 27
    window.project_path = tmp_path / "scaling.dale"
    assert window.save_project_file()
    with load_project(window.project_path) as project:
        assert project.ui_state["figure_scale_step_percent"] == 13
        assert project.ui_state["mode"] == "Scale figures"
    assert window.load_project_file(window.project_path)
    assert window.view.mode == "Scale figures"
    assert window.view.figure_scale_step_percent == 27
    window.set_global_tool_settings(False)
    assert window.view.figure_scale_step_percent == window.figure_scale_control.value() == 13


def test_contour_scale_step_switches_with_datasets(window):
    window.figure_scale_control.setValue(9)
    window.catalog.capture(window.project_ui_state())
    first = window.catalog.base_key
    other = window.catalog.create(
        "Other", ui={**window.project_ui_state(), "figure_scale_step_percent": 31}
    )
    window.catalog.transfer(first, other.id, "json")
    window.rebuild_dataset_controls()
    for identifier, step in ((other.id, 31), (first, 9), (other.id, 31)):
        window.dataset_control.setCurrentIndex(window.dataset_control.findData(identifier))
        QApplication.processEvents()
        assert window.figure_scale_control.value() == window.view.figure_scale_step_percent == step


def test_contour_scale_hovered_field_changes_step_while_move_stays_active(window):
    window.activate_mode("Move figures")
    original = window.view.session.geometry()
    wheel(window, "field", ctrl=True)
    assert window.view.mode == "Move figures"
    assert window.figure_scale_control.value() == window.view.figure_scale_step_percent == 6
    assert window.view.session.geometry() == original and not window.view.session.operations


@pytest.mark.parametrize("invalid", [0, 101, -1, 1.5, True, "5", None])
def test_contour_scale_step_strict_validation(tmp_path, invalid):
    with pytest.raises(ValueError):
        _load_ui({"figure_scale_step_percent": invalid})
    with pytest.raises(ValueError):
        save_tool_value(tmp_path / "settings.json", "figure_scale_step_percent", invalid)
    assert _load_ui({})["figure_scale_step_percent"] == 5


def test_move_contour_cursor_tracks_selection_and_pan(window):
    view = window.view
    window.activate_mode("Move figures")
    assert view.cursor().shape() == Qt.CursorShape.OpenHandCursor
    point = view.mapFromScene(30, 30)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert view.cursor().shape() == Qt.CursorShape.ClosedHandCursor
    QTest.keyClick(view, Qt.Key.Key_Escape)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert view.cursor().shape() == Qt.CursorShape.OpenHandCursor
    window.clear_selection()
    assert view.cursor().shape() == Qt.CursorShape.PointingHandCursor
    QTest.mousePress(view.viewport(), Qt.MouseButton.RightButton, pos=point)
    assert view.cursor().shape() == Qt.CursorShape.ClosedHandCursor
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.RightButton, pos=point)
    assert view.cursor().shape() == Qt.CursorShape.PointingHandCursor
    for scene_point, cursor in (
        ((30, 60), Qt.CursorShape.OpenHandCursor),
        ((300, 220), Qt.CursorShape.PointingHandCursor),
    ):
        point = view.mapFromScene(*scene_point)
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        assert view.cursor().shape() == cursor
    assert not view.session.operations


def test_scale_empty_selection_and_active_drag_do_not_edit(window):
    window.activate_mode("Scale figures")
    window.clear_selection()
    original = window.view.session.geometry()
    camera = window.view.transform()
    wheel(window)
    assert window.view.session.geometry() == original
    assert window.view.transform() == camera
    window.select_all_elements()
    window.activate_mode("Move figures")
    point = window.view.mapFromScene(30, 30)
    QTest.mousePress(window.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    wheel(window, ctrl=True)
    assert window.view.session.geometry() == original and not window.view.session.operations
    QTest.keyClick(window.view, Qt.Key.Key_Escape)
    QTest.mouseRelease(window.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
