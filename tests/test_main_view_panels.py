"""Real Qt copy anchors and the ordered Main/View toolbars."""

import os
from itertools import pairwise

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QCursor, QTransform, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel
from shapely.geometry import box

from dale.ui import MainWindow, configure_application


@pytest.fixture
def window(tmp_path, monkeypatch, pair_factory):
    app = QApplication.instance() or QApplication([])
    if not app.property("catalog_test_style"):
        configure_application(app)
        app.setProperty("catalog_test_style", True)
    monkeypatch.setenv("DALE_SETTINGS_PATH", str(tmp_path / "preferences.json"))
    w = MainWindow()
    w.can_discard = lambda: True
    w.warning = lambda *args: pytest.fail(str(args))
    w.resize(1224, 768)
    w.show()
    source = pair_factory(
        size=(600, 400),
        grid=100,
        walls=[
            {"c": [*a, *b]}
            for p in (box(30, 30, 90, 90), box(170, 30, 230, 90))
            for a, b in pairwise(p.exterior.coords)
        ],
    )
    assert w.load_sources(source.image_path, source.json_path)
    app.processEvents()
    yield w
    w.close()
    w.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def select_square(w):
    w.select_tool_set("figures")
    w.view.figure_line_ids = tuple(r.id for r in w.view.session.geometry().lineage[:4])
    w.update_map_info()
    w.view.setTransform(QTransform.fromScale(1, 1))
    w.view.centerOn(300, 200)
    QApplication.processEvents()


@pytest.mark.parametrize("language", ["ru", "en"])
def test_main_and_view_order_and_responsive_visibility_in_every_mode(window, language):
    w = window
    w.set_language(language, persist=False)
    for width in (1024, 1224, 1800, 1024):
        w.resize(width, 768)
        QApplication.processEvents()
        w.update_top_toolbar_geometry()
        QApplication.processEvents()
        assert w.width() == width
        for section in ("geometry", "figures", "regions", "pixels"):
            w.select_tool_set(section)
            w.select_all_elements()
            QApplication.processEvents()
            assert [
                a.property("dale_tool_key")
                for a in w.basic_toolbar.actions()
                if a.property("dale_tool_key")
            ] == [
                "Pan",
                "Select all contour lines",
                "Clear selection",
                "Copy region contours",
                "Delete contours" if section == "figures" else "Delete region",
                "Settings",
            ]
            assert [
                a.property("dale_tool_key")
                for a in w.view_toolbar.actions()
                if a.property("dale_tool_key")
            ] == [
                "Fit",
                "Show contours",
                "Raster crosshair",
                "Raster rulers",
                "Move guides",
                "Scene grid",
                "Canvas background",
                "Native raster resolution",
            ]
            assert w.view_toolbar.windowTitle() == w.t("View")
            assert w.view_toolbar.y() == w.basic_toolbar.y() == w.tool_set_toolbar.y()
            assert w.view_toolbar.x() >= w.basic_toolbar.geometry().right()
            for panel in (w.basic_toolbar, w.view_toolbar):
                for action in panel.actions():
                    if not action.property("dale_tool_key"):
                        continue
                    button = panel.widgetForAction(action)
                    assert button.isVisibleTo(w), action.text()
                    assert panel.rect().contains(button.geometry()), action.text()
                    assert button.size().toTuple() == (36, 36)
                    assert not button.icon().isNull() and button.toolTip()
            assert w.group_control.isVisibleTo(w) and w.dataset_control.isVisibleTo(w)
            assert w.copy_regions_action.isEnabled() == (section in ("figures", "regions"))
            assert w.main_delete_action.isEnabled() == (section in ("figures", "regions"))
        bar = w.top_panels_scroll.horizontalScrollBar()
        assert (bar.maximum() > 0) == (width < 1800)
        assert all(panel.y() == w.basic_toolbar.y() for panel in w.top_panels)
        if bar.maximum() > 0:
            assert bar.height() == 3


@pytest.mark.parametrize("anchor", [(90, 90), (30, 90), (60, 60)])
@pytest.mark.parametrize("mode", ["Select figures", "Move figures", "Rotate figures"])
def test_copy_button_retains_hover_anchor_after_cursor_leaves_map(window, anchor, mode):
    w, view = window, window.view
    select_square(w)
    w.activate_mode(mode)
    QTest.mouseMove(view.viewport(), view.mapFromScene(40, 40))
    QTest.mouseMove(view.viewport(), view.mapFromScene(*anchor))
    before = view.session.geometry()
    copy = w.basic_toolbar.widgetForAction(w.copy_regions_action)
    QTest.mouseMove(copy, copy.rect().center())
    assert view.cursor_point is None
    QTest.mouseClick(copy, Qt.MouseButton.LeftButton)
    assert view.region_clipboard.anchor == anchor
    assert view.session.geometry() == before
    destination = (290, 180)
    QTest.mouseMove(view.viewport(), view.mapFromScene(*destination))
    QTest.keyClick(view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert view.paste_delta == pytest.approx(tuple(destination[i] - anchor[i] for i in (0, 1)))
    assert view.region_anchor == pytest.approx(destination)
    assert view.region_clipboard.anchor == anchor
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert view.session.geometry() == before


@pytest.mark.parametrize("anchor", [(90, 90), (60, 60)])
def test_paste_uses_stationary_pointer_after_camera_change_without_mouse_move(window, anchor):
    w, view = window, window.view
    select_square(w)
    QTest.mouseMove(view.viewport(), view.mapFromScene(40, 40))
    QTest.mouseMove(view.viewport(), view.mapFromScene(*anchor))
    QTest.keyClick(view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert view.region_clipboard.anchor == anchor
    QTest.mouseMove(view.viewport(), view.mapFromScene(280, 160))
    cached = view.cursor_point
    view.setTransform(QTransform.fromScale(2, 2))
    view.centerOn(300, 220)
    pointer = view.viewport().mapFromGlobal(QCursor.pos())
    expected = view.mapToScene(pointer)
    destination = (expected.x(), expected.y())
    assert destination != cached
    QTest.keyClick(view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert view.region_anchor == pytest.approx(destination)
    assert view.paste_delta == pytest.approx(tuple(destination[i] - anchor[i] for i in (0, 1)))
    QTest.keyClick(view, Qt.Key.Key_Escape)


def test_keyboard_copy_uses_current_camera_coordinates_at_the_copy_moment(window):
    w, view = window, window.view
    select_square(w)
    QTest.mouseMove(view.viewport(), view.mapFromScene(40, 40))
    QTest.mouseMove(view.viewport(), view.mapFromScene(90, 90))
    assert view.cursor_point == (90, 90)
    view.setTransform(QTransform.fromScale(2, 2))
    view.centerOn(135, 85)
    QTest.keyClick(view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert view.region_clipboard.anchor == (30, 30)


@pytest.mark.parametrize("section", ["figures", "regions"])
def test_main_delete_reuses_existing_subject_action_and_one_undo(window, section):
    w, view = window, window.view
    w.select_tool_set(section)
    w.select_all_elements()
    before = view.session.geometry()
    pixels = view.item.pixmap().toImage()
    target = w.delete_contours_action if section == "figures" else w.delete_regions_action
    assert target == w.main_delete_action and target in w.edit_menu.actions()
    button = w.basic_toolbar.widgetForAction(target)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert len(view.session.operations) == 1
    assert not view.session.geometry().walls
    assert pixels == view.item.pixmap().toImage()
    w.history(False)
    assert view.session.geometry() == before


@pytest.mark.parametrize("target", ["button", "groups", "datasets", "viewport"])
def test_top_wheel_scrolls_in_both_directions_without_editing_or_switching(window, target):
    w, view = window, window.view
    w.resize(1024, 768)
    select_square(w)
    w.activate_mode("Rotate figures")
    scroll = w.top_panels_scroll
    widget = {
        "button": w.basic_toolbar.widgetForAction(w.copy_regions_action),
        "groups": w.group_control,
        "datasets": w.dataset_control,
        "viewport": scroll.viewport(),
    }[target]
    before = (
        view.session.geometry(),
        view.transform(),
        w.catalog.active_key,
        w.group_control.currentData(),
    )
    bar = scroll.horizontalScrollBar()
    bar.setValue(0)
    for direction, expected in ((-120, 120), (120, 0)):
        event = QWheelEvent(
            QPointF(10, 10),
            QPointF(widget.mapToGlobal(QPoint(10, 10))),
            QPoint(),
            QPoint(0, direction),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(widget, event)
        assert bar.value() == min(expected, bar.maximum())
        assert event.isAccepted()
        assert (
            view.session.geometry(),
            view.transform(),
            w.catalog.active_key,
            w.group_control.currentData(),
        ) == before
    scroll.ensureWidgetVisible(w.dataset_control)
    QApplication.processEvents()
    assert (
        scroll.viewport()
        .rect()
        .contains(w.dataset_control.mapTo(scroll.viewport(), w.dataset_control.rect().center()))
    )


@pytest.mark.parametrize("language", ["ru", "en"])
def test_view_grid_settings_recalculate_export_labels_and_remain_dataset_local(
    window, language, tmp_path
):
    from dale.export_grid import export_grid
    from dale.raster import load_preview

    w, view = window, window.view
    w.set_language(language, persist=False)
    w.select_tool_set("regions")
    w.select_all_elements()
    before = view.session.geometry(), tuple(view.session.operations)
    aids = view.raster_aids
    rulers = aids.snapshot()
    w.grid_action.trigger()
    assert w.grid_action.isChecked() and view.export_grid_frame == export_grid(view.session)
    for size in (25, 75):
        dialog = w.show_tool_settings("Scene grid")
        dialog.grid_size.setValue(size)
        dialog.accept()
        QApplication.processEvents()
        assert view.export_grid_frame == export_grid(view.session, size)
        for tool in ("Export selected regions", "Preview selected regions"):
            dialog = w.show_tool_settings(tool)
            assert dialog.grid_size is None  # One shared control in View.
            assert f"{size} × {size}" in dialog.findChild(QLabel, "gridInfo").text()
            dialog.reject()
    for section in ("geometry", "figures", "regions", "pixels"):
        w.select_tool_set(section)
        QApplication.processEvents()
        assert view.export_grid_frame.cell == (75, 75)
        assert not view.viewport().grab().isNull()
    assert before == (view.session.geometry(), tuple(view.session.operations))
    assert aids.settings["rulers"] == rulers["rulers"]
    first = w.catalog.active_key
    w.catalog.capture(w.project_ui_state())
    other = w.catalog.create("Another")
    w.catalog.activate(other.id)
    w.show_catalog_view(other, load_preview(other.session.source), False)
    assert not w.grid_action.isChecked() and view.export_grid_frame is None
    draft = w.catalog.activate(first)
    w.show_catalog_view(draft, load_preview(draft.session.source), True)
    assert w.grid_action.isChecked() and view.export_grid_frame.cell == (75, 75)
    w.project_path = tmp_path / "Grid settings.dale"
    assert w.save_project_file() and w.load_project_file(w.project_path)
    assert w.grid_action.isChecked() and view.export_grid_frame.cell == (75, 75)
    w.grid_action.trigger()
    assert view.export_grid_frame is None


def test_export_worker_freezes_the_current_view_grid(window, tmp_path, monkeypatch):
    import json
    import time

    w = window
    w.select_tool_set("regions")
    w.select_all_elements()
    w.size_to_grid = True
    w.remembered_merge_selected_regions = True
    w.view.raster_aids.configure(export_grid_size=75)
    destination = tmp_path / "Export"
    monkeypatch.setattr("dale.ui.choose_export_directory", lambda *args: destination)
    w.export(selected_only=True)
    assert w.worker is not None and w.worker.grid_size == 75
    w.view.raster_aids.configure(export_grid_size=25)
    deadline = time.monotonic() + 15
    while w.worker is not None and time.monotonic() < deadline:
        QTest.qWait(10)
    assert w.worker is None
    manifest = json.loads(next(destination.glob("*-placement.json")).read_text())
    assert manifest["grid"]["cell_pixels"] == [75, 75]
    assert all(i["width"] % 75 == i["height"] % 75 == 0 for i in manifest["items"])
