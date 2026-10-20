"""Synthetic arbitrary-angle guides, virtual common centers and immutable placement."""

import math
import os
from dataclasses import replace
from itertools import pairwise

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QTransform
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shapely.geometry import box

from dale.canvas import FIGURE_TOOLS, GEOMETRY_TOOLS, RASTER_TRANSFORM_TOOLS, REGION_TOOLS
from dale.extension_guides import ExtensionGuides, connected_targets
from dale.project_io import _load_ui
from dale.session import GeometryEdit
from dale.ui import MainWindow, configure_application


@pytest.mark.parametrize("angle", [0, 30, 90, 135, 240])
@pytest.mark.parametrize("along", [-100, 5, 100])
def test_supporting_line_projects_anchor_without_a_collinear_moving_wall(angle, along):
    radians = math.radians(angle)
    vector = math.cos(radians), math.sin(radians)
    normal = -vector[1], vector[0]
    geometry = GeometryEdit((((0, 0), (10 * vector[0], 10 * vector[1])),))
    guides = ExtensionGuides(geometry)
    point = tuple(along * vector[i] + 4 * normal[i] for i in (0, 1))
    snapped, edge = guides.snap(point, 4.001)
    assert snapped == pytest.approx(tuple(along * v for v in vector), abs=1e-10)
    assert edge == geometry.walls[0]
    assert guides.snap(point, 3.999) == (point, None)
    assert guides.snap(point, 0) == (point, None)


def test_connected_targets_follow_touching_chain_but_respect_independence():
    geometry = GeometryEdit(
        (
            ((0, 0), (10, 0)),
            ((10, 0), (10, 20)),
            ((0, 10), (30, 10)),
            ((30, 10), (50, 25)),
            ((100, 100), (150, 150)),
        )
    )
    ids = tuple(r.id for r in geometry.lineage)
    assert connected_targets(geometry, ids[:1]) == frozenset(ids[:4])
    assert connected_targets(geometry, ("not-in-this-scene",)) == frozenset()
    separate = replace(
        geometry,
        lineage=tuple(
            replace(r, connection_group="separate") if i == 2 else r
            for i, r in enumerate(geometry.lineage)
        ),
    )
    assert connected_targets(separate, ids[:1]) == frozenset(ids[:2])
    assert ExtensionGuides(geometry, frozenset()).snap((110, 112), 10)[1] is None


@pytest.fixture
def window(tmp_path, monkeypatch, pair_factory):
    app = QApplication.instance() or QApplication([])
    if not app.property("catalog_test_style"):
        configure_application(app)
        app.setProperty("catalog_test_style", True)
    monkeypatch.setenv("DALE_SETTINGS_PATH", str(tmp_path / "settings.json"))
    w = MainWindow()
    w.can_discard = lambda: True
    w.warning = lambda *args: pytest.fail(str(args))
    w.resize(1224, 768)
    w.show()
    source = pair_factory(
        size=(600, 400),
        walls=[{"c": [*a, *b]} for a, b in pairwise(box(30, 30, 90, 90).exterior.coords)]
        + [{"c": [160, 100, 200, 120]}],
    )
    assert w.load_sources(source.image_path, source.json_path)
    w.select_tool_set("figures")
    w.view.figure_line_ids = tuple(r.id for r in w.view.session.geometry().lineage[:4])
    w.update_map_info()
    w.activate_mode("Move figures")
    w.view.setTransform(QTransform.fromScale(1, 1))
    w.view.centerOn(300, 200)
    app.processEvents()
    yield w
    w.close()
    w.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.mark.parametrize("zoom", [0.5, 1, 2])
@pytest.mark.parametrize("center", [False, True])
def test_alt_drag_projects_vertex_or_common_center_rigidly_with_undo(window, zoom, center):
    w, view = window, window.view
    w.figure_alignment_actions["Figure point alignment"].setChecked(False)
    w.figure_alignment_actions["Figure extension alignment"].setChecked(True)
    w.extension_distance.setValue(8)
    view.setTransform(QTransform.fromScale(zoom, zoom))
    view.centerOn(100, 100)
    QApplication.processEvents()
    before = view.session.geometry()
    source_bytes = view.session.source.json_path.read_bytes()
    start = (60, 60) if center else (30, 30)
    QTest.mouseMove(view.viewport(), view.mapFromScene(250, 250))
    QTest.mouseMove(view.viewport(), view.mapFromScene(*start))
    assert view.region_anchor == start
    assert view.object_center == (60, 60)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(*start))
    assert view.region_grab_vertex == start
    cursor = (300, 174)  # Supporting line y=x/2+20; physical source ends at x200.
    view._preview_region_move(cursor, Qt.KeyboardModifier.NoModifier)
    assert view.region_anchor == cursor and view.extension_guide is None
    view.cursor_point = cursor
    QTest.keyPress(view, Qt.Key.Key_Alt)
    assert view.region_anchor == pytest.approx((301.6, 170.8))
    assert view.extension_guide == ((160, 100), (200, 120))
    preview = view.edit_preview
    assert preview.walls[0] == before.walls[-1]
    delta = (301.6 - start[0], 170.8 - start[1])
    assert preview.walls[1:] == tuple(
        tuple((x + delta[0], y + delta[1]) for x, y in edge) for edge in before.walls[:4]
    )
    assert view.session.geometry() == before
    # Render while dragging, including the source highlight and virtual center.
    assert not view.viewport().grab().isNull()
    QTest.mouseRelease(
        view.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.AltModifier,
        pos=view.mapFromScene(*cursor),
    )
    QTest.keyRelease(view, Qt.Key.Key_Alt)
    assert len(view.session.operations) == 1
    assert view.extension_guide is None
    w.history(False)
    assert view.session.geometry() == before
    assert view.session.source.json_path.read_bytes() == source_bytes


def test_connected_filter_freezes_initial_selection_and_excludes_disconnected_targets(window):
    w, view = window, window.view
    w.figure_alignment_actions["Figure extension alignment"].setChecked(True)
    view.extension_connected = True
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(30, 30))
    view._preview_region_move((300, 174), Qt.KeyboardModifier.AltModifier)
    assert view.extension_guide is None
    assert view.region_anchor == (300, 174)
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert view.extension_targets is None


@pytest.mark.parametrize("section", ["figures", "regions", "pixels"])
def test_hover_move_copy_and_rotation_share_one_common_center(window, section):
    w, view = window, window.view
    w.select_tool_set(section)
    w.select_all_elements()
    mode = {"figures": "Move figures", "regions": "Move regions", "pixels": "Move raster regions"}[
        section
    ]
    w.activate_mode(mode)
    center = view.selection_center()
    if section != "figures":
        assert center == (60, 60)
    QTest.mouseMove(view.viewport(), view.mapFromScene(35, 35))
    QTest.mouseMove(view.viewport(), view.mapFromScene(*center))
    assert view.object_center == center and view.region_anchor == center
    assert view.copy_selected_regions() and view.region_clipboard.anchor == center
    assert view.begin_paste_regions()
    view._preview_paste((250, 250), Qt.KeyboardModifier.NoModifier)
    assert view.paste_delta == pytest.approx((250 - center[0], 250 - center[1]))
    QTest.keyClick(view, Qt.Key.Key_Escape)
    rotation = {
        "figures": "Rotate figures",
        "regions": "Rotate regions",
        "pixels": "Rotate raster regions",
    }[section]
    w.activate_mode(rotation)
    view.rotate_by_wheel(1, Qt.KeyboardModifier.AltModifier)
    assert view.rotation_pivot == center
    assert view.selection_center() == pytest.approx(center)
    assert not view.viewport().grab().isNull()
    if section == "pixels":
        assert not view.extension_alignment and not view.snap_enabled


def test_settings_are_staged_independent_and_persist_with_project(window, tmp_path):
    w, view = window, window.view
    tool = "Figure extension alignment"
    w.figure_alignment_actions[tool].setChecked(True)
    old = w.contour_alignment_distance.value()
    dialog = w.show_tool_settings(tool)
    dialog.value.setValue(37)
    dialog.connected_contours.setChecked(True)
    dialog.reject()
    assert view.extension_distance_px == 14 and not view.extension_connected
    dialog = w.show_tool_settings(tool)
    dialog.value.setValue(37)
    dialog.connected_contours.setChecked(True)
    dialog.accept()
    assert view.extension_distance_px == 37 and view.extension_connected
    assert w.contour_alignment_distance.value() == old
    w.project_path = tmp_path / "extensions.dale"
    assert w.save_project_file()
    assert w.load_project_file(w.project_path)
    assert view.extension_alignment and view.extension_distance_px == 37
    assert view.extension_connected
    for section in ("geometry", "regions", "pixels"):
        w.select_tool_set(section)
        assert not view.extension_alignment
    w.select_tool_set("figures")
    assert view.extension_alignment


@pytest.mark.parametrize(
    "changes",
    [
        {"extension_distance_px": 0},
        {"extension_distance_px": 10000},
        {"extension_distance_px": True},
        {"extension_distance_px": 1.5},
        {"extension_connected": 1},
        {"figure_extension_alignment": "yes"},
    ],
)
def test_project_rejects_invalid_extension_settings(changes):
    with pytest.raises(ValueError):
        _load_ui(changes)


@pytest.mark.parametrize(
    "mode",
    [
        *GEOMETRY_TOOLS,
        *FIGURE_TOOLS,
        *REGION_TOOLS,
        "Select raster regions",
        *RASTER_TRANSFORM_TOOLS,
        "Erase",
        "Restore",
        "Erase square",
        "Restore square",
    ],
)
def test_guide_editing_is_exclusive_with_every_left_tool(window, mode):
    w, view = window, window.view
    w.select_all_elements()
    view.raster_aids.configure(rulers=True)
    w.activate_mode(mode)
    if mode in (*REGION_TOOLS, *RASTER_TRANSFORM_TOOLS):
        w.select_all_elements()
        w.activate_mode(mode)
    tool = w.mode_actions[mode]
    assert tool.isChecked()
    button = w.view_toolbar.widgetForAction(w.move_guides_action)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert view.mode == "Move guides" and view.raster_aids.editing_guides
    assert [key for key, action in w.mode_actions.items() if action.isChecked()] == ["Move guides"]
    original = view.session.geometry()
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(400, 300))
    assert view.session.geometry() == original
    tool.trigger()
    assert tool.isChecked() and not w.move_guides_action.isChecked()
    assert view.mode == mode and not view.raster_aids.settings["move_guides"]
    assert not view.raster_aids.editing_guides


def test_guide_mode_survives_save_and_exits_when_rulers_hidden(window, tmp_path):
    w, view = window, window.view
    view.raster_aids.configure(rulers=True)
    w.move_guides_action.trigger()
    assert view.mode == "Move guides"
    w.project_path = tmp_path / "guide-mode.dale"
    assert w.save_project_file() and w.load_project_file(w.project_path)
    assert view.mode == "Move guides" and view.raster_aids.editing_guides
    assert [key for key, action in w.mode_actions.items() if action.isChecked()] == ["Move guides"]
    w.rulers_action.trigger()
    assert not view.raster_aids.editing_guides and not w.move_guides_action.isChecked()
    assert view.mode != "Move guides"


def test_copy_keeps_stable_common_pivot_after_rotating_asymmetric_selection(window):
    w, view = window, window.view
    w.select_all_elements()
    pivot = view.selection_center()
    w.activate_mode("Rotate figures")
    view.rotate_by_wheel(1, Qt.KeyboardModifier.AltModifier)
    view.cursor_point = pivot
    assert view.copy_selected_regions()
    assert view.region_clipboard.anchor == pivot
    assert view.region_clipboard.center == pivot
    assert view.begin_paste_regions()
    view._preview_paste((300, 250), Qt.KeyboardModifier.NoModifier)
    assert tuple(view.region_clipboard.center[i] + view.paste_delta[i] for i in (0, 1)) == (
        300,
        250,
    )
    QTest.keyClick(view, Qt.Key.Key_Escape)


@pytest.mark.parametrize("mode", [*RASTER_TRANSFORM_TOOLS, "Select raster regions"])
def test_raster_help_does_not_advertise_unavailable_alt_guides(window, mode):
    window.activate_mode(mode)
    window.set_language("en", persist=False)
    window.update_mode_help()
    assert all("X/Y guides" not in label.text() for label in window.mode_help_labels.values())


def test_guide_mode_is_not_restored_without_a_scene_image(window):
    w = window
    scene_json = w.view.session.source.json_path
    assert w.load_sources(None, scene_json)
    w.view.raster_aids.configure(rulers=True, move_guides=True)
    assert not w.move_guides_action.isEnabled()
    w.activate_mode("Move guides", prompt=False)
    assert w.view.mode != "Move guides"
    assert not w.move_guides_action.isChecked()
