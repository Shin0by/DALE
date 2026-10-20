"""Actual alignment panel order, painted Alt captions and Raster isolation."""

import os
from itertools import pairwise

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QTransform
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QToolButton
from shapely.geometry import box

from dale.ui import MainWindow, configure_application


@pytest.fixture
def window(tmp_path, monkeypatch, pair_factory):
    app = QApplication.instance() or QApplication([])
    configure_application(app)
    app.setProperty("catalog_test_style", True)
    monkeypatch.setenv("DALE_SETTINGS_PATH", str(tmp_path / "preferences.json"))
    w = MainWindow()
    w.can_discard = lambda: True
    w.warning = lambda *args: pytest.fail(str(args))
    w.resize(1224, 768)
    w.show()
    source = pair_factory(
        size=(400, 300),
        walls=[{"c": [*a, *b]} for a, b in pairwise(box(30, 30, 90, 90).exterior.coords)]
        + [{"c": [200, 200, 240, 200]}],
    )
    assert w.load_sources(source.image_path, source.json_path)
    app.processEvents()
    yield w
    w.close()
    w.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.mark.parametrize("language", ["ru", "en"])
def test_panels_follow_primary_tools_and_have_matching_order(window, language):
    w = window
    w.set_language(language, persist=False)
    expected = {
        "geometry": ["Right-angle alignment", "Contour alignment", "Snapping (px)"],
        "figures": [
            "Figure guide alignment",
            "Figure extension alignment",
            "Figure point alignment",
        ],
        "regions": ["Region guide alignment", "Region point alignment"],
    }
    assert set(w.alignment_toolbars) == set(expected)
    for section in (*expected, "pixels"):
        w.select_tool_set(section)
        QApplication.processEvents()
        column = w.mode_tool_pages[section].layout()
        primary = column.itemAt(0).widget()
        assert primary.orientation() == Qt.Orientation.Vertical
        assert primary.width() == 60
        if section == "pixels":
            assert column.count() == 2
            assert column.itemAt(1).widget() == w.raster_output_toolbar
        else:
            panel = w.alignment_toolbars[section]
            assert panel.windowTitle() == w.t(
                {
                    "geometry": "Vertices alignment",
                    "figures": "Contours alignment",
                    "regions": "Regions alignment",
                }[section]
            )
            assert column.itemAt(1).widget() == panel
            assert panel.width() == primary.width()
            assert panel.y() - primary.geometry().bottom() - 1 == 4
            buttons = [panel.widgetForAction(action) for action in panel.actions()]
            assert all(isinstance(button, QToolButton) for button in buttons)
            assert [b.defaultAction().property("dale_tool_key") for b in buttons] == expected[
                section
            ]
            for key, button in zip(expected[section], buttons, strict=True):
                assert button.isVisibleTo(w) and button.size().toTuple() == (48, 60)
                assert not button.editor().isVisible()
                assert button.activation_hint == ("" if key == "Snapping (px)" else "Alt")
            if section == "regions":
                assert column.itemAt(2).widget() == w.region_output_toolbar
                assert column.count() == 3
            else:
                assert column.count() == 2


@pytest.mark.parametrize("section", ["geometry", "figures", "regions"])
def test_alt_is_painted_on_button_and_lower_caption_clicks_toggle(window, section):
    w = window
    w.select_tool_set(section)
    panel = w.alignment_toolbars[section]
    for action in panel.actions():
        button = panel.widgetForAction(action)
        caption = button.activation_hint
        if not caption:
            continue
        before = button.defaultAction().isChecked()
        labelled = button.grab().toImage().copy(QRect(9, 41, 30, 16))
        button.activation_hint = ""
        blank = button.grab().toImage().copy(QRect(9, 41, 30, 16))
        button.activation_hint = caption
        button.update()
        assert labelled != blank
        QTest.mouseClick(button, Qt.MouseButton.LeftButton, pos=QPoint(24, 48))
        assert button.defaultAction().isChecked() != before
        assert not button.editor().isVisible()


@pytest.mark.parametrize("point", [False, True])
@pytest.mark.parametrize("guides", [False, True])
def test_raster_alt_drag_has_no_hidden_dependency_or_snap(window, point, guides):
    w, view = window, window.view
    w.snap_action.setChecked(point)
    w.alignment_actions["contour_alignment"].setChecked(guides)
    w.alignment_actions["right_angle_alignment"].setChecked(True)
    w.select_tool_set("pixels")
    w.selected_regions = (0,)
    w.update_map_info()
    w.activate_mode("Move raster regions")
    assert not view.snap_enabled and not view.contour_alignment and not view.right_angle_alignment
    view.setTransform(QTransform.fromScale(1, 1))
    view.centerOn(200, 150)
    QApplication.processEvents()
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(40, 40))
    assert view.region_grab_vertex == (30, 30)
    QTest.mouseMove(view.viewport(), view.mapFromScene(213, 215))
    assert view.region_anchor == pytest.approx((203, 205))
    QTest.keyPress(view, Qt.Key.Key_Alt)
    assert view.region_anchor == pytest.approx((203, 205))
    assert view.snap is None and not view.placement_guides
    QTest.mouseRelease(
        view.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.AltModifier,
        pos=view.mapFromScene(213, 215),
    )
    QTest.keyRelease(view, Qt.Key.Key_Alt)
    assert view.detached_selection is None
    assert view.region_polygons[0].bounds == pytest.approx((203, 205, 263, 265))
    w.select_tool_set("geometry")
    assert (view.snap_enabled, view.contour_alignment, view.right_angle_alignment) == (
        point,
        guides,
        True,
    )
