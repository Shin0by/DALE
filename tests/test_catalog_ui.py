"""Offscreen interaction with synthetic project sets and reusable contour placement."""

import json
import math
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QTransform
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

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
from dale.session import RasterSelectionEdit, Session
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


@pytest.mark.parametrize("zoom", [1, 2])
@pytest.mark.parametrize(
    "scenario",
    ["horizontal", "vertical", "connected", "rotated", "branch", "interior", "combined"],
)
def test_new_line_alt_angles_and_guides_preview_commit_and_undo(
    window, pair_factory, zoom, scenario
):
    walls = [[100, 100, 180, 160]]
    start, cursor, expected = (100, 100), (280, 105), (280, 100)
    guides = scenario in ("horizontal", "vertical", "connected", "combined")
    angles = scenario in ("rotated", "branch", "interior", "combined")
    snapping = scenario in ("interior", "combined")
    if scenario == "vertical":
        cursor, expected = (105, 280), (100, 280)
    elif scenario == "connected":
        walls = [[100, 100, 300, 160], [300, 160, 400, 250]]
        cursor, expected = (305, 280), (300, 280)
    elif scenario in ("rotated", "interior"):
        if scenario == "interior":
            walls = [[20, 40, 180, 160]]
        cursor, expected = (43, 180), (41.08, 178.56)
    elif scenario == "branch":
        walls += [[100, 100, 100, 20], [100, 100, 180, 100]]
    elif scenario == "combined":
        walls = [[100, 100, 100, 20], [280, 0, 280, 250]]
        cursor = (275, 105)
    source = pair_factory(
        size=(600, 450),
        walls=[{"_id": f"wall{i:012d}", "c": c, "door": 1} for i, c in enumerate(walls)],
        lights=[{"keep": "light"}],
        tiles=[{"texture": {"src": "keep.webp"}}],
    )
    assert window.load_sources(source.image_path, source.json_path)
    window.configure_json_repair(True)
    window.activate_mode("New line")
    window.snap_action.setChecked(snapping)
    window.alignment_actions["contour_alignment"].setChecked(guides)
    window.alignment_actions["right_angle_alignment"].setChecked(angles)
    view = window.view
    view.setTransform(QTransform.fromScale(zoom, zoom))
    view.centerOn(210, 200)
    QApplication.processEvents()
    original = view.session.geometry()
    raster = view.item.pixmap().toImage()
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(*start))
    QTest.mouseMove(view.viewport(), view.mapFromScene(*cursor))
    from dale.editing import snap_point

    ordinary = snap_point(original, cursor, 14 / zoom) if snapping else None
    assert view.line_end == pytest.approx(ordinary or cursor)
    QTest.keyPress(view, Qt.Key.Key_Alt)
    assert view.line_start == start
    assert view.line_end == pytest.approx(expected)
    assert bool(view.alignment_guides) == guides
    assert bool(view.angle_joint) == angles
    assert view.session.geometry() == original and not view.session.operations
    if angles:
        a, joint, b = view.angle_joint
        assert joint == start
        assert sum((a[i] - joint[i]) * (b[i] - joint[i]) for i in (0, 1)) == pytest.approx(
            0, abs=1e-7
        )
    QTest.mouseRelease(
        view.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.AltModifier,
        pos=view.mapFromScene(*cursor),
    )
    QTest.keyRelease(view, Qt.Key.Key_Alt)
    assert view.session.geometry().walls[: len(walls)] == original.walls
    assert view.session.geometry().walls[-1][0] == start
    assert view.session.geometry().walls[-1][1] == pytest.approx(expected)
    assert len(view.session.operations) == 1
    assert view.angle_joint is None and not view.alignment_guides and view.guide_targets is None
    assert view.item.pixmap().toImage() == raster
    result = json.loads(repaired_json_bytes(view.session)[0])
    assert result["lights"] == source.raw["lights"] and result["tiles"] == source.raw["tiles"]
    assert result["walls"][: len(walls)] == source.raw["walls"]
    assert result["walls"][-1]["door"] == 0
    view.session.undo()
    assert view.session.geometry() == original
    view.session.redo()
    assert view.session.geometry().walls[-1][1] == pytest.approx(expected)
    assert source.json_path.read_bytes() == source.json_bytes


@pytest.mark.parametrize("rule", ["right_angle_alignment", "contour_alignment"])
@pytest.mark.parametrize("hold_before_press", [False, True])
def test_new_line_alignment_requires_enabled_button_and_alt_and_escape_clears_preview(
    window, pair_factory, rule, hold_before_press
):
    source = pair_factory(size=(500, 400), walls=[{"c": [100, 20, 100, 100]}])
    window.load_sources(source.image_path, source.json_path)
    window.activate_mode("New line")
    window.snap_action.setChecked(False)
    window.alignment_actions[rule].setChecked(True)
    view = window.view
    # This checkbox controls extra corners for moved vertices, not a new line's sole corner.
    view.right_angle_neighbours = False
    view.resetTransform()
    view.centerOn(200, 180)
    QApplication.processEvents()
    original = view.session.geometry()
    mods = Qt.KeyboardModifier.AltModifier if hold_before_press else Qt.KeyboardModifier.NoModifier
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, mods, view.mapFromScene(100, 100))
    point = view.mapFromScene(280, 105)
    QTest.mouseMove(view.viewport(), point)
    QTest.keyPress(view, Qt.Key.Key_Alt)
    assert view.line_end == (280, 100)
    QTest.keyRelease(view, Qt.Key.Key_Alt)
    assert view.line_end == (280, 105)
    window.alignment_actions[rule].setChecked(False)
    QTest.keyPress(view, Qt.Key.Key_Alt)
    assert view.line_end == (280, 105)
    assert not view.angle_joint and not view.alignment_guides
    window.alignment_actions[rule].setChecked(True)
    QApplication.sendEvent(
        view.viewport(),
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(point),
            QPointF(view.viewport().mapToGlobal(point)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.AltModifier,
        ),
    )
    assert view.line_end == (280, 100)
    QTest.keyClick(view, Qt.Key.Key_Escape)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    QTest.keyRelease(view, Qt.Key.Key_Alt)
    assert view.line_start is None and view.angle_joint is None
    assert view.alignment_geometry is None and view.guide_targets is None
    assert not view.alignment_guides and not view.session.operations
    assert view.session.geometry() == original


def test_new_line_guides_align_detached_start_and_keep_vertex_priority(window, pair_factory):
    source = pair_factory(
        size=(500, 400),
        walls=[{"c": [100, 100, 104, 50]}, {"c": [108, 110, 200, 150]}],
    )
    window.load_sources(source.image_path, source.json_path)
    window.activate_mode("New line")
    window.alignment_actions["contour_alignment"].setChecked(True)
    view = window.view
    view.resetTransform()
    view.centerOn(200, 180)
    QApplication.processEvents()
    alt = Qt.KeyboardModifier.AltModifier
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, alt, view.mapFromScene(101, 102))
    assert view.line_start == (100, 100)  # Never replace a vertex hit with mixed x/y guides.
    QTest.keyClick(view, Qt.Key.Key_Escape)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton)
    window.snap_action.setChecked(False)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, alt, view.mapFromScene(103, 250))
    assert view.line_start == (104, 250)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, alt, view.mapFromScene(280, 255))
    assert view.session.geometry().walls[-1] == ((104, 250), (280, 250))
    assert len(view.session.operations) == 1


@pytest.mark.parametrize("rule", ["right_angle_alignment", "contour_alignment"])
def test_new_line_alignment_ignores_hidden_height_references(window, pair_factory, rule):
    source = pair_factory(
        size=(500, 400),
        walls=[
            {"c": [100, 100, 180, 160], "flags": {"wall-height": {"bottom": 0, "top": 10}}},
            {"c": [100, 100, 100, 20], "flags": {"wall-height": {"bottom": 10, "top": 20}}},
            {"c": [275, 105, 350, 105], "flags": {"wall-height": {"bottom": 10, "top": 20}}},
        ],
    )
    window.load_sources(source.image_path, source.json_path)
    from dale.source_editing import source_layers

    view = window.view
    layer = next(
        layer
        for layer in source_layers(view.session.source, view.session.geometry())
        if layer.kind == "band" and layer.bottom == 0 and layer.top == 10
    )
    view.source_layer = layer.key
    window.activate_mode("New line")
    window.alignment_actions[rule].setChecked(True)
    view.resetTransform()
    view.centerOn(200, 180)
    QApplication.processEvents()
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(100, 100))
    QTest.mouseMove(view.viewport(), view.mapFromScene(275, 105))
    QTest.keyPress(view, Qt.Key.Key_Alt)
    expected = (275, 100) if rule == "contour_alignment" else (275, 105)
    assert view.line_end == expected
    assert view.angle_joint is None
    assert (275, 105) not in view.guide_targets.point_set
    QTest.keyClick(view, Qt.Key.Key_Escape)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton)
    QTest.keyRelease(view, Qt.Key.Key_Alt)
    assert not view.session.operations


@pytest.mark.parametrize("zoom", [1, 2])
@pytest.mark.parametrize("hold_before_press", [False, True])
@pytest.mark.parametrize("target", ["vertex", "segment"])
@pytest.mark.parametrize("snapping", [False, True])
@pytest.mark.parametrize("rule", ["guides", "angles", "both"])
def test_vertex_alt_guides_keep_enabled_snapping_when_no_axis_matches(
    window, pair_factory, zoom, hold_before_press, target, snapping, rule
):
    source = pair_factory(
        size=(600, 400),
        lights=[{"x": 5, "y": 7}],
        walls=[{"c": c} for c in ([40, 40, 100, 80], [100, 80, 150, 140], [300, 200, 360, 200])],
    )
    assert window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Edit points")
    window.snap_action.setChecked(snapping)
    window.snap_distance.setValue(14)
    window.alignment_actions["contour_alignment"].setChecked(rule != "angles")
    window.alignment_actions["right_angle_alignment"].setChecked(rule != "guides")
    view = window.view
    view.setTransform(QTransform.fromScale(zoom, zoom))
    view.centerOn(200, 140)
    QApplication.processEvents()
    original = view.session.geometry()
    point = (300 - 9 / zoom, 200 - 9 / zoom) if target == "vertex" else (330, 200 - 9 / zoom)
    expected = ((300, 200) if target == "vertex" else (330, 200)) if snapping else point
    if hold_before_press:
        QTest.keyPress(view, Qt.Key.Key_Alt)
    QTest.mousePress(
        view.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.AltModifier if hold_before_press else Qt.KeyboardModifier.NoModifier,
        view.mapFromScene(100, 80),
    )
    position = view.mapFromScene(*point)
    QApplication.sendEvent(
        view.viewport(),
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(position),
            QPointF(view.viewport().mapToGlobal(position)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.AltModifier
            if hold_before_press
            else Qt.KeyboardModifier.NoModifier,
        ),
    )
    if not hold_before_press:
        assert view.snap == (expected if snapping else None)
        QTest.keyPress(view, Qt.Key.Key_Alt)
    assert view.axis_constrained
    assert not view.alignment_guides and not view.angle_joint
    assert view.snap == (expected if snapping else None)
    assert view.edit_preview.walls[0][1] == expected
    if not hold_before_press:
        QTest.keyClick(view, Qt.Key.Key_Escape)
    QTest.mouseRelease(
        view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier, position
    )
    QTest.keyRelease(view, Qt.Key.Key_Alt)
    if not hold_before_press:
        assert view.session.geometry() == original and not view.session.operations
    else:
        assert len(view.session.operations) == 1
        assert view.session.geometry().walls[0][1] == expected
        assert view.session.geometry().walls[2] == original.walls[2]
        assert json.loads(repaired_json_bytes(view.session)[0])["lights"] == source.raw["lights"]
        view.session.undo()
        assert view.session.geometry() == original
        view.session.redo()
        assert view.session.geometry().walls[0][1] == expected
    assert source.json_path.read_bytes() == source.json_bytes


@pytest.mark.parametrize("height_scope", [False, True])
@pytest.mark.parametrize("alt", [False, True])
@pytest.mark.parametrize("zoom", [1, 3])
def test_vertex_line_snapping_keeps_preview_closed_through_fractional_slide(
    window, pair_factory, tmp_path, height_scope, alt, zoom
):
    from shapely.geometry import LineString, Point

    target = ((8039.9832, 9182.7731), (9101.3927, 9519.2221))
    corner, tip = (8334.2481, 9702.3419), (8400.35, 9500.87)
    source = pair_factory(
        size=(100, 100),
        width=12000,
        height=12000,
        walls=[
            {
                "_id": f"NativeWall{i:06}",
                "c": [*a, *b],
                "door": i % 2,
                "flags": {"wall-height": {"bottom": 0, "top": 10}},
            }
            for i, (a, b) in enumerate((target, (target[0], corner), (corner, tip)))
        ],
        lights=[{"keep": "light"}],
        tiles=[{"keep": "tile"}],
    )
    assert window.load_sources(None, source.json_path)
    window.set_json_repair(height_scope)
    window.activate_mode("Edit points")
    window.snap_action.setChecked(True)
    window.snap_distance.setValue(14)
    for action in window.alignment_actions.values():
        action.setChecked(False)
    view = window.view
    view.setTransform(QTransform.fromScale(zoom, zoom))
    view.centerOn(*tip)
    QApplication.processEvents()
    original = view.session.geometry()
    assert view.analysis.faces == 0
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(*tip))
    modifiers = Qt.KeyboardModifier.AltModifier if alt else Qt.KeyboardModifier.NoModifier
    direction = tuple(target[1][i] - target[0][i] for i in (0, 1))
    normal = (-direction[1] / math.hypot(*direction), direction[0] / math.hypot(*direction))
    for index in range(40, 161, 3):
        cursor = tuple(
            target[0][i] + direction[i] * index / 200 + normal[i] * 3 / zoom for i in (0, 1)
        )
        view.centerOn(*cursor)
        point = view.mapFromScene(*cursor)
        QApplication.sendEvent(
            view.viewport(),
            QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(point),
                QPointF(view.viewport().mapToGlobal(point)),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,
                modifiers,
            ),
        )
        assert view.snap is not None
        assert LineString(target).distance(Point(view.snap)) < 1e-7
        assert view.edit_preview.walls[2][1] == view.snap
        assert view.analysis.faces == 1, (index, view.snap)
        assert len(view.analysis.unresolved) == 1
        assert view.edit_preview.walls[:2] == original.walls[:2]
        assert view.edit_preview.lineage == original.lineage
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, modifiers, point)
    assert len(view.session.operations) == 1 and view.analysis.faces == 1
    current = view.session.geometry()
    assert json.loads(repaired_json_bytes(view.session)[0])["lights"] == source.raw["lights"]
    window.history(False)
    assert view.session.geometry() == original and view.analysis.faces == 0
    window.history(True)
    assert view.session.geometry() == current and view.analysis.faces == 1
    window.project_path = tmp_path / "Sliding snapped vertex.dale"
    assert window.save_project_file() and window.load_project_file(window.project_path)
    assert view.session.geometry() == current and view.analysis.faces == 1
    assert source.json_path.read_bytes() == source.json_bytes


@pytest.mark.parametrize("zoom", [1, 3, 12.8])
@pytest.mark.parametrize("distance_px", [2, 8, 13, 15, 25])
def test_vertex_line_snap_tolerance_is_screen_distance(window, pair_factory, zoom, distance_px):
    from shapely.geometry import LineString, Point

    target = ((100.371, 100.721), (400.761, 180.923))
    corner, tip = (100.371, 300.37), (250.21, 250.76)
    source = pair_factory(
        size=(600, 400),
        walls=[{"c": [*a, *b]} for a, b in (target, (target[0], corner), (corner, tip))],
    )
    assert window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Edit points")
    window.snap_action.setChecked(True)
    window.snap_distance.setValue(14)
    for action in window.alignment_actions.values():
        action.setChecked(False)
    view = window.view
    view.setTransform(QTransform.fromScale(zoom, zoom))
    view.centerOn(*tip)
    QApplication.processEvents()
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(*tip))
    delta = tuple(target[1][i] - target[0][i] for i in (0, 1))
    normal = (-delta[1] / math.hypot(*delta), delta[0] / math.hypot(*delta))
    cursor = tuple(
        (target[0][i] + target[1][i]) / 2 + normal[i] * distance_px / zoom for i in (0, 1)
    )
    view.centerOn(*cursor)
    point = view.mapFromScene(*cursor)
    raw = view.mapToScene(point)
    destination = raw.x() + view.drag_offset[0], raw.y() + view.drag_offset[1]
    expected = LineString(target).distance(Point(destination)) * zoom <= 14
    QApplication.sendEvent(
        view.viewport(),
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(point),
            QPointF(view.viewport().mapToGlobal(point)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert (view.snap is not None) == expected
    assert view.analysis.faces == int(expected)
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert not view.session.operations


def schedule_dialog(callback):
    """Close a modal on assertion failure so a Qt callback cannot hang the suite."""
    from PySide6.QtCore import QTimer

    errors = []

    def run():
        try:
            callback()
        except BaseException as exc:
            errors.append(exc)
            dialog = QApplication.activeModalWidget() or QApplication.activePopupWidget()
            if dialog:
                dialog.reject()

    QTimer.singleShot(0, run)
    return errors


@pytest.mark.parametrize("language", ["ru", "en"])
@pytest.mark.parametrize("accepted", [False, True])
def test_color_dialog_custom_palette_survives_cancel_save_and_other_dataset(
    window, pair_factory, tmp_path, monkeypatch, language, accepted
):
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QColorDialog

    source = pair_factory()
    assert window.load_sources(source.image_path, source.json_path)
    window.set_language(language, persist=False)
    window.create_selection_group()
    group = window.selection_groups()[0]
    window.custom_colors = tuple(f"#ff{i:06x}" for i in range(16))
    window.saved_state = window.document_state()
    before = window.view.session.geometry(), tuple(window.view.session.operations)

    def edit_palette():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QColorDialog)
        assert QColorDialog.customColor(15).name(QColor.NameFormat.HexArgb) == "#ff00000f"
        QColorDialog.setCustomColor(0, QColor("#ff123456"))
        QColorDialog.setCustomColor(15, QColor("#ffabcdef"))
        dialog.setCurrentColor(QColor("#34aa65"))
        dialog.accept() if accepted else dialog.reject()

    errors = schedule_dialog(edit_palette)
    window.change_group_color(group.id)
    assert not errors, errors
    assert window.custom_colors[0] == "#ff123456" and window.custom_colors[15] == "#ffabcdef"
    assert window.selection_groups()[0].color == ("#34aa65" if accepted else group.color)
    assert window.document_state() != window.saved_state
    assert (window.view.session.geometry(), tuple(window.view.session.operations)) == before
    questions = []
    monkeypatch.setattr(
        window,
        "question",
        lambda *args: questions.append(args) or QMessageBox.StandardButton.Cancel,
    )
    assert not MainWindow.can_discard(window) and questions
    first = window.catalog.active_key
    other = window.catalog.create("Other colors")
    window.rebuild_dataset_controls()
    window.dataset_control.setCurrentIndex(window.dataset_control.findData(other.id))
    assert window.custom_colors[0] == "#ff123456"
    window.project_path = tmp_path / "Shared project colors.dale"
    assert window.save_project_file() and window.load_project_file(window.project_path)
    assert window.custom_colors[15] == "#ffabcdef"
    window.dataset_control.setCurrentIndex(window.dataset_control.findData(first))
    assert window.custom_colors[0] == "#ff123456"
    errors = schedule_dialog(lambda: QApplication.activeModalWidget().reject())
    window.choose_project_color(QColor("white"), "Palette restored")
    assert not errors and QColorDialog.customColor(0).name() == "#123456"


def test_project_palettes_are_isolated_between_windows_and_new_projects(
    window, pair_factory, tmp_path, monkeypatch
):
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QColorDialog

    from dale.project_io import DEFAULT_CUSTOM_COLORS

    source = pair_factory()
    assert window.load_sources(source.image_path, source.json_path)
    window.custom_colors = ("#ff123456",) * 16
    other = MainWindow()
    monkeypatch.setattr(other, "can_discard", lambda: True)
    assert other.load_sources(source.image_path, source.json_path)
    for owner, expected in ((window, "#123456"), (other, "#ffffff"), (window, "#123456")):

        def inspect(expected=expected):
            assert QColorDialog.customColor(0).name() == expected
            QApplication.activeModalWidget().reject()

        errors = schedule_dialog(inspect)
        owner.choose_project_color(QColor("white"), "Isolated palette")
        assert not errors, errors
    window.project_path = tmp_path / "With colors.dale"
    assert window.save_project_file()
    assert window.load_sources(source.image_path, source.json_path)
    assert window.custom_colors == DEFAULT_CUSTOM_COLORS
    assert window.load_project_file(tmp_path / "With colors.dale")
    assert window.custom_colors == ("#ff123456",) * 16
    window.close_document()
    assert window.custom_colors == DEFAULT_CUSTOM_COLORS
    other.close()
    other.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize("zoom", [1, 2])
@pytest.mark.parametrize("snapping", [False, True])
@pytest.mark.parametrize("scenario", ["horizontal", "vertical", "neighbour_angle", "moving_angle"])
def test_vertex_alt_combines_axis_and_right_angles_with_line_snapping(
    window, pair_factory, zoom, snapping, scenario
):
    if scenario == "horizontal":
        walls = [[100, 100, 400, 100], [300, 0, 300, 200]]
        start, cursor, guided, snapped = (100, 100), (295, 99), (295, 100), (300, 100)
    elif scenario == "vertical":
        walls = [[100, 100, 100, 400], [0, 300, 200, 300]]
        start, cursor, guided, snapped = (100, 100), (99, 295), (100, 295), (100, 300)
    elif scenario == "neighbour_angle":
        walls = [[100, 100, 120, 100], [100, 100, 100, 0], [300, 0, 300, 200]]
        start, cursor, guided, snapped = (120, 100), (295, 101), (295, 100), (300, 100)
    else:
        walls = [[90, 100, 100, 110], [100, 110, 110, 100], [106, 100, 106, 120]]
        start, cursor, snapped = (100, 110), (101, 110), (106, 108)
        guided = (100 + 10 / math.sqrt(101), 100 + 100 / math.sqrt(101))
    source = pair_factory(size=(600, 450), walls=[{"c": c} for c in walls], lights=[{"keep": True}])
    window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Edit points")
    window.snap_action.setChecked(snapping)
    window.snap_distance.setValue(14)
    for action in window.alignment_actions.values():
        action.setChecked(True)
    view = window.view
    view.setTransform(QTransform.fromScale(zoom, zoom))
    view.centerOn(200, 200)
    QApplication.processEvents()
    original = view.session.geometry()
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(*start))
    point = view.mapFromScene(*cursor)
    QApplication.sendEvent(
        view.viewport(),
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(point),
            QPointF(view.viewport().mapToGlobal(point)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.AltModifier,
        ),
    )
    expected = snapped if snapping else guided
    assert view.snap == pytest.approx(expected)
    assert bool(view.angle_joint) == ("angle" in scenario)
    assert bool(view.alignment_guides) == (scenario != "moving_angle")
    if view.angle_joint:
        a, joint, b = view.angle_joint
        assert sum((a[i] - joint[i]) * (b[i] - joint[i]) for i in (0, 1)) == pytest.approx(
            0, abs=1e-7
        )
        assert any(math.dist(p, expected) < 1e-7 for p in view.angle_joint)
    assert view.edit_preview.walls[-1] == original.walls[-1]
    QTest.mouseRelease(
        view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier, point
    )
    assert len(view.session.operations) == 1
    assert json.loads(repaired_json_bytes(view.session)[0])["lights"] == source.raw["lights"]
    view.session.undo()
    assert view.session.geometry() == original
    view.session.redo()
    assert any(
        math.dist(expected, p) < 1e-7 for edge in view.session.geometry().walls[:-1] for p in edge
    )
    assert source.json_path.read_bytes() == source.json_bytes


@pytest.mark.parametrize("zoom", [1, 2])
@pytest.mark.parametrize("snapping", [False, True])
def test_independent_vertex_alt_uses_stationary_contact_for_right_angle(
    window, pair_factory, zoom, snapping
):
    from dale.connections import isolate

    source = pair_factory(
        size=(640, 480),
        walls=[
            {"c": [50, 50, 250, 200]},
            {"c": [350, 100, 150, 300]},
        ],
    )
    assert window.load_sources(source.image_path, source.json_path)
    view = window.view
    original = view.session.geometry()
    view.session.add(isolate(original, (original.lineage[0].id,)))
    window.refresh()
    window.activate_mode("Edit points")
    window.snap_action.setChecked(snapping)
    for action in window.alignment_actions.values():
        action.setChecked(True)
    view.setTransform(QTransform.fromScale(zoom, zoom))
    view.centerOn(250, 200)
    QApplication.processEvents()
    before = view.session.geometry()
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(250, 200))
    position = view.mapFromScene(228, 223)
    for modifiers in (
        Qt.KeyboardModifier.AltModifier,
        Qt.KeyboardModifier.NoModifier,
        Qt.KeyboardModifier.AltModifier,
    ):
        QApplication.sendEvent(
            view.viewport(),
            QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(position),
                QPointF(view.viewport().mapToGlobal(position)),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,
                modifiers,
            ),
        )
        if modifiers:
            assert view.snap == pytest.approx((225, 225))
            assert view.angle_joint is not None
        else:
            assert view.angle_joint is None
        assert view.edit_preview.walls[1] == before.walls[1]
        assert view.session.geometry() == before
    QTest.mouseRelease(
        view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier, position
    )
    changed = view.session.geometry()
    assert changed.walls[1] == before.walls[1] and changed.lineage[1] == before.lineage[1]
    assert (225, 225) in changed.walls[0] and len(view.session.operations) == 2
    view.session.undo()
    assert view.session.geometry() == before
    view.session.redo()
    assert view.session.geometry() == changed
    assert source.json_path.read_bytes() == source.json_bytes


@pytest.mark.parametrize("zoom", [1, 2])
def test_isolated_free_vertex_alt_follows_original_vector_only_within_tolerance(
    window, pair_factory, zoom
):
    from dale.editing import align_along_vector

    source = pair_factory(size=(640, 480), walls=[{"c": [100, 100, 200, 150]}])
    assert window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Edit points")
    window.alignment_actions["contour_alignment"].setChecked(True)
    view = window.view
    view.setTransform(QTransform.fromScale(zoom, zoom))
    view.centerOn(250, 200)
    QApplication.processEvents()
    original = view.session.geometry()
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(200, 150))
    for cursor, alt in (
        ((300, 198), True),
        ((300, 198), False),
        ((300, 230), True),
        ((300, 198), True),
    ):
        position = view.mapFromScene(*cursor)
        QApplication.sendEvent(
            view.viewport(),
            QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(position),
                QPointF(view.viewport().mapToGlobal(position)),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.AltModifier if alt else Qt.KeyboardModifier.NoModifier,
            ),
        )
        expected = align_along_vector(cursor, ((100, 100), (200, 150)), 14 / zoom) if alt else None
        assert bool(view.vector_guide) == (expected is not None)
        assert view.edit_preview.walls[0][0] == original.walls[0][0]
        assert view.edit_preview.walls[0][1] == pytest.approx(expected or cursor)
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert not view.session.operations and view.session.geometry() == original
    assert view.vector_guide is None and view.point_snap_targets is None


@pytest.mark.parametrize("zoom", [1, 2])
def test_independent_vertex_acquires_external_xy_guide_with_alt(window, pair_factory, zoom):
    source = pair_factory(
        size=(640, 480),
        walls=[
            {"c": [100, 100, 200, 150]},
            {"c": [300, 200, 400, 250]},
        ],
    )
    assert window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Edit points")
    window.alignment_actions["contour_alignment"].setChecked(True)
    view = window.view
    view.setTransform(QTransform.fromScale(zoom, zoom))
    view.centerOn(250, 200)
    QApplication.processEvents()
    original = view.session.geometry()
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(200, 150))
    for cursor in ((300, 200), (350, 203)):
        position = view.mapFromScene(*cursor)
        QApplication.sendEvent(
            view.viewport(),
            QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(position),
                QPointF(view.viewport().mapToGlobal(position)),
                Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.AltModifier,
            ),
        )
    assert view.snap == pytest.approx((350, 200))
    assert view.alignment_guides and view.edit_preview.walls[1] == original.walls[1]
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert view.session.geometry() == original and not view.session.operations


@pytest.mark.parametrize("language", ["ru", "en"])
@pytest.mark.parametrize("answer", ["dataset", "group", None])
@pytest.mark.parametrize("remember", [False, True])
def test_group_export_name_question_remembers_only_confirmed_choices(
    window, language, answer, remember
):
    from PySide6.QtWidgets import QMessageBox

    from dale.preferences import load_export_group_naming
    from dale.selection_groups import SelectionGroup

    window.set_language(language, persist=False)
    group = SelectionGroup.create("Room A")

    def choose():
        dialog = QApplication.activeModalWidget()
        assert dialog.objectName() == "exportGroupNamingQuestion"
        assert "Room A" in dialog.informativeText() and "Floor" in dialog.informativeText()
        dialog.checkBox().setChecked(remember)
        text = window.t("Dataset name" if answer == "dataset" else "Group name")
        button = (
            dialog.button(QMessageBox.StandardButton.Cancel)
            if answer is None
            else next(b for b in dialog.buttons() if b.text() == text)
        )
        button.click()

    errors = schedule_dialog(choose)
    assert window.confirm_export_group_naming("Floor", (group,)) == answer
    assert not errors
    expected = answer if remember else None
    assert load_export_group_naming(window.preferences_path) == expected
    reopened = MainWindow(preferences_path=window.preferences_path)
    assert reopened.export_group_naming == expected
    reopened.close()
    reopened.deleteLater()
    if expected:
        assert window.confirm_export_group_naming("Floor", (group,)) == expected


@pytest.mark.parametrize("language", ["ru", "en"])
def test_export_group_naming_settings_reflect_question_and_apply_or_cancel(window, language):
    from PySide6.QtWidgets import QDialogButtonBox

    from dale.preferences import load_export_group_naming

    window.set_language(language, persist=False)
    for choice in ("group", "dataset", None):
        dialog = window.show_tool_settings("Export selected regions")
        assert dialog.naming_action.currentData() == window.export_group_naming
        dialog.naming_action.setCurrentIndex(dialog.naming_action.findData(choice))
        dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).click()
        assert window.export_group_naming == choice
        assert load_export_group_naming(window.preferences_path) == choice
        QApplication.processEvents()
    dialog = window.show_tool_settings("Export selected regions")
    dialog.naming_action.setCurrentIndex(2)
    dialog.reject()
    assert load_export_group_naming(window.preferences_path) is None


@pytest.mark.parametrize("exact", [False, True])
def test_png_export_asks_group_naming_only_for_exact_exported_boundary(
    window, pair_factory, monkeypatch, exact
):
    from dale.selection_groups import SelectionGroup, boundary_members

    selection_scene(window, pair_factory, "Select regions")
    window.toggle_region_at((50, 50))
    ids = boundary_members(window.view.session.geometry(), (window.regions[0],))
    group = SelectionGroup.create("Room A").assign(ids if exact else tuple(ids)[:1])
    window.catalog.current.ui["groups"] = [group.encode()]
    window.remembered_merge_selected_regions = False
    seen, suggestions = [], []
    monkeypatch.setattr(
        window, "confirm_export_group_naming", lambda stem, groups: seen.append(groups) or "group"
    )
    monkeypatch.setattr(
        "dale.ui.choose_export_directory", lambda owner, folder, name: suggestions.append(name)
    )
    window.export(selected_only=True)
    assert bool(seen) is exact
    assert suggestions[0].startswith("Room A-" if exact else window.catalog.name + "-")
    assert window.worker is None


@pytest.mark.parametrize("language", ["ru", "en"])
@pytest.mark.parametrize("merge", [False, True])
@pytest.mark.parametrize("naming", ["group", "dataset"])
def test_region_group_button_exports_complete_group_with_internal_edges(
    window, pair_factory, tmp_path, monkeypatch, language, merge, naming
):
    from itertools import pairwise

    from PySide6.QtCore import QTimer
    from shapely.geometry import box

    from dale.export_names import selection_number
    from dale.selection_groups import SelectionGroup, boundary_members

    window.set_language(language, persist=False)
    source = pair_factory(
        size=(320, 200),
        walls=[
            {"c": [*a, *b]}
            for p in (box(20, 20, 140, 120), box(200, 30, 280, 110))
            for a, b in pairwise(p.exterior.coords)
        ]
        + [{"c": [80, 20, 80, 120]}],
    )
    assert window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Select regions")
    session = window.view.session
    original = session.geometry(), tuple(session.operations), source.json_bytes
    cells = window.available_regions()
    group = SelectionGroup.create("Rooms A and B").assign(
        boundary_members(session.geometry(), cells)
    )
    window.store_selection_groups((group,))
    window.group_manager_button.click()
    QApplication.processEvents()
    QTest.mouseClick(window.group_manager.row_controls[group.id][1], Qt.MouseButton.LeftButton)
    assert len(window.selected_regions) == len(cells) == 3
    window.remembered_merge_selected_regions = merge
    window.export_group_naming = None
    window.include_json = True
    window.contour_offset.setValue(3)
    destination = tmp_path / "Exported group"
    suggestions, questions = [], []

    def directory(owner, folder, name):
        suggestions.append(name)
        return destination

    monkeypatch.setattr("dale.ui.choose_export_directory", directory)

    def choose_name():
        dialog = QApplication.activeModalWidget()
        assert dialog.objectName() == "exportGroupNamingQuestion"
        questions.append(dialog.text())
        dialog.checkBox().setChecked(True)
        caption = "Group name" if naming == "group" else "Dataset name"
        next(b for b in dialog.buttons() if b.text() == window.t(caption)).click()

    QTimer.singleShot(0, choose_name)
    QTest.mouseClick(window.export_regions_button, Qt.MouseButton.LeftButton)
    assert window.worker is not None
    from PySide6.QtCore import QEventLoop

    loop, deadline = QEventLoop(), QTimer()
    deadline.setSingleShot(True)
    deadline.timeout.connect(loop.quit)
    window.worker.finished.connect(loop.quit)
    deadline.start(15000)
    loop.exec()
    deadline.stop()
    QApplication.processEvents()
    assert window.worker is None and len(questions) == 1
    number = selection_number(cells)
    stem = group.name if naming == "group" else window.catalog.name
    assert suggestions == [f"{stem}-{number}"]
    files = list(destination.iterdir())
    assert all(p.name.startswith(f"{stem}-{number}") for p in files)
    manifest = json.loads(next(destination.glob("*-placement.json")).read_text())
    assert manifest["selection_id"] == number
    assert len(manifest["items"]) == (2 if merge else 3)
    for item in manifest["items"]:
        with Image.open(destination / item["file"]) as image:
            assert item["file"].endswith(f"-{image.width}x{image.height}px.png")
            assert image.mode == "RGBA" and image.getchannel("A").getbbox()
    assert (
        session.geometry(),
        tuple(session.operations),
        source.json_path.read_bytes(),
    ) == original


def test_png_export_preflight_failure_shows_error_and_keeps_button_available(
    window, pair_factory, monkeypatch
):
    selection_scene(window, pair_factory, "Select regions")
    window.toggle_region_at((50, 50))
    window.remembered_merge_selected_regions = True
    errors = []
    monkeypatch.setattr(window, "warning", lambda *args: errors.append(args))

    def fail(*args):
        raise OSError("The export folder is unavailable.")

    monkeypatch.setattr("dale.ui.choose_export_directory", fail)
    QTest.mouseClick(window.export_regions_button, Qt.MouseButton.LeftButton)
    assert errors == [("Export failed", "The export folder is unavailable.")]
    assert window.worker is None and window.export_regions_button.isEnabled()


@pytest.mark.parametrize("section", ["geometry", "figures", "regions", "pixels"])
@pytest.mark.parametrize("sidebar", [False, True])
def test_editor_panels_have_no_outer_gutters(window, section, sidebar):
    window.select_tool_set(section)
    window.set_sidebar_visible(sidebar, persist=False)
    QApplication.processEvents()
    root = window.centralWidget()
    assert root.layout().contentsMargins().isNull() and root.layout().spacing() == 0
    assert window.left_panel.geometry().topLeft() == root.rect().topLeft()
    assert window.left_panel.geometry().bottom() == root.rect().bottom()
    assert window.view.geometry().left() == window.left_panel.geometry().right() + 1
    assert window.view.geometry().top() == root.rect().top()
    assert window.view.geometry().bottom() == root.rect().bottom()
    assert window.tool_stack.width() == 60
    bar = window.tool_scroll.verticalScrollBar()
    assert window.tool_scroll.width() == 60 + (10 if bar.maximum() > 0 else 0)
    assert window.sidebar_toggle.geometry().right() == (
        window.sidebar_scroll.geometry().left() - 1 if sidebar else root.rect().right()
    )


@pytest.mark.parametrize("language", ["ru", "en"])
@pytest.mark.parametrize(
    "choice", ["default", "new", "existing", "selected", "entered", "empty", "cancel"]
)
def test_export_folder_chooser_uses_edited_name_as_final_destination(
    window, tmp_path, language, choice
):
    from PySide6.QtWidgets import QDialogButtonBox, QFileDialog, QLineEdit, QListView

    from dale.export_directory import ExportDirectoryDialog

    window.set_language(language, persist=False)
    directory = tmp_path / "Exports"
    directory.mkdir()
    existing = directory / "First floor"
    existing.mkdir()
    (directory / "Map-overlays").mkdir()
    (existing / "Scene.json").write_bytes(b"untouched")
    dialog = ExportDirectoryDialog(window, directory, "Map")
    dialog.setViewMode(QFileDialog.ViewMode.List)
    dialog.show()
    QApplication.processEvents()
    editor = dialog.findChild(QLineEdit, "fileNameEdit")
    assert Path(dialog.directory().absolutePath()) == directory
    assert editor.text() == "Map-overlays-2"
    assert dialog.export_button.text() == window.t("Export")
    if choice in ("new", "existing", "empty"):
        editor.setText({"new": "Second floor", "existing": "First floor", "empty": ""}[choice])
    elif choice in ("selected", "entered"):
        listing = dialog.findChild(QListView, "listView")
        assert listing.isVisible()
        for _ in range(100):
            index = listing.model().index(str(existing))
            if index.isValid() and not listing.visualRect(index).isEmpty():
                break
            QTest.qWait(10)
        listing.scrollTo(index)
        QTest.mouseClick(
            listing.viewport(), Qt.MouseButton.LeftButton, pos=listing.visualRect(index).center()
        )
        assert editor.text() == "First floor"
        if choice == "entered":
            QTest.mouseDClick(
                listing.viewport(),
                Qt.MouseButton.LeftButton,
                pos=listing.visualRect(index).center(),
            )
            QApplication.processEvents()
            assert Path(dialog.directory().absolutePath()) == existing
    QApplication.processEvents()
    assert dialog.export_button.isEnabled() and dialog.export_button.text() == window.t("Export")
    if choice == "cancel":
        QTest.mouseClick(
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Cancel),
            Qt.MouseButton.LeftButton,
        )
        assert dialog.destination is None
    else:
        QTest.mouseClick(dialog.export_button, Qt.MouseButton.LeftButton)
        expected = {
            "default": directory / "Map-overlays-2",
            "empty": directory / "Map-overlays-2",
            "new": directory / "Second floor",
            "existing": existing,
            "selected": existing,
            "entered": existing,
        }[choice]
        assert dialog.destination == expected and not dialog.isVisible()
    assert (existing / "Scene.json").read_bytes() == b"untouched"
    assert set(directory.iterdir()) == {existing, directory / "Map-overlays"}
    dialog.deleteLater()


@pytest.mark.parametrize("language", ["ru", "en"])
@pytest.mark.parametrize("asset", ["png", "json"])
@pytest.mark.parametrize("choice", ["Overwrite", "Create copy", "Cancel"])
def test_export_conflict_real_question_worker_and_json_preserve_assets(
    window, pair_factory, tmp_path, monkeypatch, language, asset, choice
):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox

    from dale.overlay_export import export_overlays
    from dale.session import Stroke

    source = pair_factory()
    assert window.load_sources(source.image_path, source.json_path)
    window.set_language(language, persist=False)
    destination = tmp_path / "Floor assets"
    destination.mkdir()
    if asset == "png":
        export_overlays(
            window.view.session,
            tmp_path,
            target_directory=destination,
            export_name=window.catalog.name,
        )
        window.view.session.add(Stroke(((30, 50),), 8))
        monkeypatch.setattr("dale.ui.choose_export_directory", lambda *args: destination)
    else:
        (destination / "Floor.json").write_bytes(b"old exported JSON")
        monkeypatch.setattr(
            "dale.ui.QFileDialog.getSaveFileName",
            lambda *args: (str(destination / "Floor.json"), ""),
        )
        monkeypatch.setattr(window, "information", lambda *args: None)
    (destination / "Other asset.png").write_bytes(b"unrelated asset")
    before = {p.name: p.read_bytes() for p in destination.iterdir()}
    original = source.image_path.read_bytes(), source.json_path.read_bytes()
    errors, questions = [], []
    timer = QTimer()

    def answer():
        dialog = QApplication.activeModalWidget()
        if not isinstance(dialog, QMessageBox) or dialog.objectName() != "exportFileConflict":
            return
        try:
            questions.append(dialog.text())
            assert str(tmp_path) not in dialog.text() + dialog.informativeText()
            assert dialog.informativeText() == window.t("Folder: {folder}", folder=destination.name)
            assert {b.text() for b in dialog.buttons()} == {
                window.t("Overwrite"),
                window.t("Create copy"),
                window.t("Cancel"),
            }
            next(b for b in dialog.buttons() if b.text() == window.t(choice)).click()
        except BaseException as exc:
            errors.append(exc)
            dialog.reject()

    timer.timeout.connect(answer)
    timer.start(5)
    try:
        if asset == "png":
            window.export()
            for _ in range(500):
                if window.worker is None:
                    break
                QTest.qWait(10)
            assert window.worker is None
        else:
            window.export_json()
    finally:
        timer.stop()
    assert not errors, errors
    assert len(questions) == (3 if asset == "png" and choice != "Cancel" else 1)
    after = {p.name: p.read_bytes() for p in destination.iterdir()}
    assert after["Other asset.png"] == before["Other asset.png"]
    if choice == "Cancel":
        assert after == before
    elif choice == "Create copy":
        assert all(after[name] == data for name, data in before.items())
        assert len(after) == len(before) + (3 if asset == "png" else 1)
    else:
        assert set(after) == set(before) and after != before
    assert original == (source.image_path.read_bytes(), source.json_path.read_bytes())
    assert not list(tmp_path.glob(".dale-export-*"))


@pytest.mark.parametrize("language", ["ru", "en"])
@pytest.mark.parametrize("dismiss", ["outside", "x", "escape", "cancel"])
def test_tool_settings_popup_closes_without_applying_and_keeps_nested_choices(
    window, pair_factory, language, dismiss
):
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtWidgets import QDialogButtonBox, QFrame, QLabel

    selection_scene(window, pair_factory, "Select figures")
    window.set_language(language, persist=False)
    window.activate_mode("Pan")
    geometry = window.view.session.geometry()
    original = window.geometry_brush_control.value()
    popup = window.show_tool_settings("Erase lines")
    QApplication.processEvents()
    assert window.tool_settings_popup is popup and popup.isVisible()
    assert QApplication.activeModalWidget() is None and not popup.isModal()
    assert popup.width() == 416 and popup.close_button.text() == "X"
    assert (
        popup.findChild(QLabel, "toolSettingsTitle").text()
        == window.mode_actions["Erase lines"].text()
    )
    assert not popup.findChildren(QFrame, "settingsSeparator")
    apply_button = popup.buttons.button(QDialogButtonBox.StandardButton.Ok)
    cancel_button = popup.buttons.button(QDialogButtonBox.StandardButton.Cancel)
    assert apply_button.text() == window.t("Apply")
    assert cancel_button.text() == window.t("Cancel")
    assert apply_button.size() == cancel_button.size()
    assert apply_button.x() < cancel_button.x()
    assert popup.layout().itemAt(popup.layout().count() - 1).widget() is popup.buttons
    viewport = window.view.viewport()
    map_bounds = QRect(viewport.mapToGlobal(QPoint()), viewport.size())
    assert map_bounds.contains(popup.geometry())
    button = window.tool_settings_buttons["Erase lines"]
    assert popup.x() > button.mapToGlobal(button.rect().topRight()).x()
    popup.value.setValue(original + 10)
    # The combo opens its own Qt popup; choosing an action must keep the container open.
    popup.default_action.showPopup()
    QApplication.processEvents()
    choices = popup.default_action.view()
    option = choices.visualRect(choices.model().index(2, 0)).center()
    QTest.mouseClick(choices.viewport(), Qt.MouseButton.LeftButton, pos=option)
    assert window.tool_settings_popup is popup and popup.isVisible()
    assert popup.default_action.currentData() is False
    if dismiss == "outside":
        QTest.mouseClick(
            viewport, Qt.MouseButton.LeftButton, pos=viewport.rect().bottomRight() - QPoint(5, 5)
        )
    elif dismiss == "x":
        QTest.mouseClick(popup.close_button, Qt.MouseButton.LeftButton)
    elif dismiss == "cancel":
        QTest.mouseClick(cancel_button, Qt.MouseButton.LeftButton)
    else:
        QTest.keyClick(popup, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert window.tool_settings_popup is None
    assert window.geometry_brush_control.value() == original
    assert window.connection_choices["Erase lines"] is None
    assert window.view.session.geometry() == geometry and not window.view.session.operations
    # Replacing a popup also discards its staged value, leaving only one live container.
    first = window.show_tool_settings("Erase lines")
    first.value.setValue(original + 20)
    second = window.show_tool_settings("Edit points")
    assert window.tool_settings_popup is second and second.isVisible()
    second.reject()
    assert window.tool_settings_popup is None and window.geometry_brush_control.value() == original


@pytest.mark.parametrize(
    "tool",
    [
        "Erase lines",
        "Erase vertices",
        "Auto-close",
        "Close all contours",
        "Erase",
        "Restore",
        "Snapping (px)",
        "Right-angle alignment",
        "Contour alignment",
        "Artwork offset (px)",
        "Figure point alignment",
        "Figure guide alignment",
        "Region point alignment",
        "Region guide alignment",
    ],
)
def test_standard_numeric_settings_typing_arrows_cancel_and_corner(window, pair_factory, tool):
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtTest import QSignalSpy
    from PySide6.QtWidgets import (
        QAbstractSpinBox,
        QDialogButtonBox,
        QSpinBox,
        QStyle,
        QStyleOptionSpinBox,
    )

    selection_scene(window, pair_factory, "Select figures")
    section = (
        "regions"
        if tool.startswith("Region") or tool == "Artwork offset (px)"
        else "figures"
        if tool.startswith("Figure")
        else "pixels"
        if tool in ("Erase", "Restore")
        else "geometry"
    )
    window.select_tool_set(section)
    button = window.tool_settings_buttons[tool]
    control = button.editor()
    original = control.value()
    geometry = window.view.session.geometry()
    flags = window.alignment_ui_state()
    triggered = QSignalSpy(button.defaultAction().triggered)
    assert button.width() == 48
    assert button.height() == (
        60 if tool in ("Erase", "Restore") or button.activation_hint is not None else 48
    )
    assert control.isVisible() == (tool in ("Erase", "Restore"))
    marker = button.findChild(QWidget, "toolSettingsCorner")
    assert marker and marker.isVisible()
    assert marker.pos().x() + marker.width() == button.width()
    assert marker.pos().y() + marker.height() == button.height()
    assert marker.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    values = []

    def edit(accept):
        dialog = window.tool_settings_popup
        assert dialog.objectName() == "toolSettingsDialog"
        assert dialog.minimumWidth() < dialog.maximumWidth()
        assert dialog.windowFlags() & Qt.WindowType.FramelessWindowHint
        assert not dialog.isModal() and QApplication.activeModalWidget() is None
        spin = dialog.findChild(QSpinBox, "toolSettingsValue")
        assert spin.buttonSymbols() == QAbstractSpinBox.ButtonSymbols.UpDownArrows
        assert spin.value() == original
        target = spin.maximum() - 1
        spin.setFocus()
        spin.selectAll()
        QTest.keyClicks(spin, str(target))
        spin.interpretText()
        option = QStyleOptionSpinBox()
        spin.initStyleOption(option)
        up = spin.style().subControlRect(
            QStyle.ComplexControl.CC_SpinBox, option, QStyle.SubControl.SC_SpinBoxUp, spin
        )
        QTest.mouseClick(spin, Qt.MouseButton.LeftButton, pos=up.center())
        assert spin.value() == spin.maximum()
        down = spin.style().subControlRect(
            QStyle.ComplexControl.CC_SpinBox, option, QStyle.SubControl.SC_SpinBoxDown, spin
        )
        QTest.mouseClick(spin, Qt.MouseButton.LeftButton, pos=down.center())
        assert spin.value() == target
        values.append(target)
        if accept:
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()
        else:
            QTest.keyClick(dialog, Qt.Key.Key_Escape)

    for accept in (False, True):
        errors = schedule_dialog(lambda accept=accept: edit(accept))
        position = button.rect().center()
        QApplication.sendEvent(
            button,
            QContextMenuEvent(
                QContextMenuEvent.Reason.Mouse, position, button.mapToGlobal(position)
            ),
        )
        QApplication.processEvents()
        if errors:
            raise errors[0]
        assert control.value() == (values[-1] if accept else original)
    assert not triggered.count() and window.alignment_ui_state() == flags
    assert window.view.session.geometry() == geometry and not window.view.session.operations


@pytest.mark.parametrize("language", ["ru", "en"])
@pytest.mark.parametrize("tool", ["Edit points", "Erase lines", "Export selected regions"])
def test_settings_default_action_dropdown_roundtrips_all_three_states(window, tool, language):
    from PySide6.QtWidgets import QCheckBox, QComboBox, QDialogButtonBox, QLabel

    from dale.preferences import (
        load_connection_choice,
        load_merge_selected_regions,
        load_size_to_grid,
    )

    window.set_language(language, persist=False)
    for index, expected in ((1, True), (2, False), (0, None)):

        def choose(index=index):
            dialog = window.tool_settings_popup
            combo = dialog.findChild(QComboBox, "defaultAction")
            assert combo.count() == 3
            assert combo.itemText(0) == window.t("Ask every time")
            assert dialog.findChild(QLabel, "defaultActionQuestion").text().endswith("?")
            combo.setCurrentIndex(index)
            if tool == "Export selected regions":
                assert not load_size_to_grid(window.preferences_path)
                dialog.findChild(QCheckBox, "sizeToGrid").setChecked(index != 0)
            else:
                assert not dialog.findChildren(QCheckBox)
            dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()

        # Keep the grid choice independent while changing the remembered answer.
        from dale.preferences import save_size_to_grid

        save_size_to_grid(window.preferences_path, False)
        window.size_to_grid = False
        errors = schedule_dialog(choose)
        window.show_tool_settings(tool)
        QApplication.processEvents()
        if errors:
            raise errors[0]
        assert window.tool_settings_popup is None
        actual = (
            load_merge_selected_regions(window.preferences_path)
            if tool == "Export selected regions"
            else load_connection_choice(window.preferences_path, tool)
        )
        assert actual is expected
        if tool == "Export selected regions":
            reopened = MainWindow(preferences_path=window.preferences_path)
            assert reopened.size_to_grid is (index != 0)
            reopened.close()
            reopened.deleteLater()


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

    def settings(index, accept):
        from PySide6.QtWidgets import QComboBox, QDialogButtonBox, QLabel

        dialog = window.tool_settings_popup
        assert dialog.objectName() == "toolSettingsDialog"
        assert dialog.findChild(QLabel, "defaultActionQuestion").text() == window.t(
            "Export adjacent regions as one?"
        )
        combo = dialog.findChild(QComboBox, "defaultAction")
        assert combo.currentData() is True
        combo.setCurrentIndex(index)
        kind = (
            QDialogButtonBox.StandardButton.Ok if accept else QDialogButtonBox.StandardButton.Cancel
        )
        dialog.findChild(QDialogButtonBox).button(kind).click()

    QTimer.singleShot(0, lambda: settings(2, False))
    window.show_tool_settings("Export selected regions")
    QApplication.processEvents()
    assert window.tool_settings_popup is None
    assert load_merge_selected_regions(window.preferences_path) is True
    QTimer.singleShot(0, lambda: settings(0, True))
    button = window.export_regions_button
    position = button.rect().center()
    event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, position, button.mapToGlobal(position)
    )
    QApplication.sendEvent(button, event)
    QApplication.processEvents()
    assert len(seen) == 1 and load_merge_selected_regions(window.preferences_path) is None
    assert not window.merge_selected_regions
    tip = window.export_regions_action.toolTip()
    assert tip.startswith(window.t("Export selected regions"))
    assert ("Правый клик" if language == "ru" else "Right-click") in tip


@pytest.mark.parametrize("merge", [True, False])
@pytest.mark.parametrize("size_to_grid", [False, True])
def test_selected_export_actual_button_question_worker_png_and_sidebar(
    window, pair_factory, tmp_path, monkeypatch, merge, size_to_grid
):
    from itertools import pairwise

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox
    from shapely.geometry import box

    from dale.overlay_export import selected_export_regions

    source = pair_factory(
        size=(240, 160),
        grid={"size": 40, "type": 1},
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
    window.size_to_grid = size_to_grid
    geometry, operations = window.view.session.geometry(), tuple(window.view.session.operations)
    source_bytes = source.image_path.read_bytes(), source.json_path.read_bytes()
    destination = tmp_path / "Chosen export"
    monkeypatch.setattr("dale.ui.choose_export_directory", lambda *args: destination)
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
    assert window.worker.size_to_grid is size_to_grid
    window.size_to_grid = not size_to_grid  # Worker owns the frozen export choice.
    for _ in range(500):
        if window.worker is None:
            break
        QTest.qWait(10)
    assert window.worker is None and len(dialogs) == 1
    folder = destination
    assert folder.is_dir() and not list(folder.glob("*-overlays*"))
    manifest = json.loads(next(folder.glob("*-placement.json")).read_text())
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
    window.size_to_grid = size_to_grid
    window.update_map_info()
    if size_to_grid:
        padded_bounds = window.bounds_preview.request(
            window.view.session,
            tuple(
                p
                for _, p in selected_export_regions(
                    window.view.region_polygons, -3, merge_adjacent=merge
                )
            ),
            size_to_grid=True,
        )
        actual = tuple(
            (item["x"], item["y"], item["x"] + item["width"], item["y"] + item["height"])
            for item in manifest["items"]
        )
        assert actual == padded_bounds.bounds
        assert all(item["width"] % 40 == item["height"] % 40 == 0 for item in manifest["items"])
    assert ("PNG: 2 ·" in window.map_info.text()) is (not merge)
    assert window.view.session.geometry() == geometry
    assert tuple(window.view.session.operations) == operations
    assert source_bytes == (source.image_path.read_bytes(), source.json_path.read_bytes())


def test_selected_export_cancel_stops_before_folder_dialog(window, pair_factory, monkeypatch):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QMessageBox

    selection_scene(window, pair_factory, "Select regions")
    window.toggle_region_at((50, 50))
    monkeypatch.setattr(
        "dale.ui.choose_export_directory",
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

    def settings():
        from PySide6.QtWidgets import QComboBox, QDialogButtonBox, QLabel

        dialog = window.tool_settings_popup
        assert dialog.objectName() == "toolSettingsDialog"
        assert dialog.findChild(QLabel, "defaultActionQuestion").text().endswith("?")
        combo = dialog.findChild(QComboBox, "defaultAction")
        assert combo.currentData() is False
        assert combo.itemText(0) == window.t("Ask every time")
        combo.setCurrentIndex(0)
        dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok).click()

    QTimer.singleShot(0, settings)
    position = button.rect().center()
    event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, position, button.mapToGlobal(position)
    )
    QApplication.sendEvent(button, event)
    QApplication.processEvents()
    assert len(seen) == 1 and load_connection_choice(window.preferences_path, tool) is None
    QTimer.singleShot(0, lambda: choose(QMessageBox.StandardButton.Cancel, True))
    assert window.confirm_contour_connection(tool) is None
    assert load_connection_choice(window.preferences_path, tool) is None


@pytest.mark.parametrize("section", ["regions", "figures"])
@pytest.mark.parametrize("anchor", [(30, 30), (100, 100)])
def test_pasted_contours_rotate_about_bounds_center_instead_of_grabbed_vertex(
    window, pair_factory, section, anchor
):
    selection_scene(window, pair_factory, "Select regions")
    window.select_tool_set(section)
    if section == "figures":
        window.select_figure_at({"point": (30, 70), "double": True})
    else:
        window.toggle_region_at((50, 50))
    view = window.view
    original = view.session.geometry()
    view.cursor_point = anchor
    assert view.copy_selected_regions() and view.region_clipboard.anchor == anchor
    assert view.begin_paste_regions()
    target = (310, 160)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(*target))
    plan = view._region_plan()
    expected = tuple(65 + target[i] - anchor[i] for i in (0, 1))
    assert plan.pivot == pytest.approx(expected)
    pasted = view.session.geometry()
    window.activate_mode("Rotate figures" if section == "figures" else "Rotate regions")
    view.transform_regions(angle=90)
    result = view._region_plan()
    points = [p for edge in result.moving for p in edge]
    center = tuple((min(p[i] for p in points) + max(p[i] for p in points)) / 2 for i in (0, 1))
    assert center == pytest.approx(expected) and result.pivot == pytest.approx(expected)
    assert view.session.geometry().walls[: len(original.walls)] == original.walls
    window.history(False)
    assert view.session.geometry() == pasted


@pytest.mark.parametrize("action", ["undo_move", "reopen"])
def test_contour_center_is_recomputed_after_geometry_change_or_project_reopen(
    window, pair_factory, tmp_path, action
):
    selection_scene(window, pair_factory, "Select figures")
    window.select_figure_at({"point": (30, 70), "double": True})
    view = window.view
    if action == "undo_move":
        window.activate_mode("Move figures")
        start, end = view.mapFromScene(50, 30), view.mapFromScene(170, 50)
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(view.viewport(), end)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
        assert view._region_plan().pivot == pytest.approx((185, 85))
        window.history(False)
    else:
        # A valid current-schema project can contain the former misplaced grab-anchor cache.
        view.figure_pivot = (30, 30)
        window.project_path = tmp_path / "Contour pivot.dale"
        assert window.save_project_file() and window.load_project_file(window.project_path)
    window.activate_mode("Rotate figures")
    assert view._region_plan().pivot == pytest.approx((65, 65))
    view.transform_regions(angle=90)
    assert view._region_plan().pivot == pytest.approx((65, 65))


@pytest.mark.parametrize("disconnected", [False, True])
def test_asymmetric_contour_rotation_keeps_one_common_bounds_center(
    window, pair_factory, disconnected
):
    import math

    edges = [((40, 40), (140, 40)), ((140, 40), (40, 100)), ((40, 100), (40, 40))]
    if disconnected:
        edges.append(((230, 10), (260, 10)))
    stationary = ((20, 180), (300, 180))
    source = pair_factory(size=(400, 240), walls=[{"c": [*a, *b]} for a, b in (*edges, stationary)])
    assert window.load_sources(source.image_path, source.json_path)
    window.select_tool_set("figures")
    view = window.view
    initial = view.session.geometry()
    view.figure_line_ids = tuple(r.id for r in initial.lineage[: len(edges)])
    window.update_map_info()
    expected = (150, 55) if disconnected else (90, 70)
    assert view._region_plan().pivot == expected
    window.activate_mode("Rotate figures")
    for _ in range(120):
        view.transform_regions(angle=0.1)
        assert view._region_plan().pivot == expected
    result = view._region_plan()
    assert len(view.session.operations) == 1
    assert result.fixed == (stationary,)
    assert math.dist(result.moving[0][0], expected) == pytest.approx(
        math.dist(edges[0][0], expected)
    )


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
        assert view.session.geometry() == before
        assert all(isinstance(op, RasterSelectionEdit) for op in view.session.operations)
        assert bool(view.session.operations) == (section == "pixels")
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
        assert button.isVisible() and (button.width(), button.height()) == (48, 60)
        assert action.toolTip().splitlines()[0] == action.text()
        assert "Alt" in action.toolTip() and "Ctrl" in button.toolTip()
    window.figure_guide_distance.setValue(9999)
    assert window.contour_alignment_distance.value() == window.region_guide_distance.value() == 9999
    assert not window.figure_guide_distance.isVisible()
    window.activate_mode("Move figures")
    assert view.mode == "Move figures"  # Double-click can select the first contour.
    view.figure_move_double_click = False
    window.activate_mode("Move figures")
    assert view.mode == "Select figures"  # No modal when the selection is empty.


@pytest.mark.parametrize("zoom", [1, 2])
@pytest.mark.parametrize("prior", ["none", "other", "first"])
@pytest.mark.parametrize("mode", ["Select figures", "Move figures"])
def test_contour_double_click_locks_first_hit_and_does_not_accumulate_jittered_second_hit(
    window, pair_factory, zoom, prior, mode
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
    window.activate_mode(mode)
    assert view.mode == mode
    pixels = view.item.pixmap().toImage()
    # Native Qt double-click sequence: first press/release, double press, release.
    # Both contours cross here, but have no shared stored vertex.
    crossing = view.mapFromScene(80, 80)
    first, second = crossing + QPoint(-1, 0), crossing + QPoint(0, -1)
    if mode == "Move figures":
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=first)
        QTest.mouseMove(view.viewport(), first + QPoint(1, 0))
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=first + QPoint(1, 0))
        assert view.figure_line_ids == prior_ids
        assert view.session.geometry() == original and not view.session.operations
    else:
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=first)
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=second)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=second)
    assert view.session.geometry() == original
    assert tuple(r.id for r in view.session.geometry().lineage) == ids
    assert not view.session.operations and not view.session.future
    assert view.item.pixmap().toImage() == pixels
    expected = set(ids[:4]) if mode == "Move figures" else set(prior_ids) ^ set(ids[:4])
    assert set(view.figure_line_ids) == expected
    assert view.region_clipboard is not None and view.paste_delta is None
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=second)
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=first)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=first)
    expected = set(ids[4:8]) if mode == "Move figures" else expected | set(ids[4:8])
    assert set(view.figure_line_ids) == expected
    assert view.session.geometry() == original and not view.session.operations


@pytest.mark.parametrize("zoom", [1, 2])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("near_edge", [False, True])
def test_move_contour_double_click_empty_clears_all_selection(
    window, pair_factory, zoom, enabled, near_edge
):
    from PySide6.QtCore import QPoint

    source = pair_factory(
        size=(400, 300),
        walls=[{"c": c} for c in ([40, 60, 100, 60], [100, 60, 100, 110], [200, 60, 260, 60])],
    )
    assert window.load_sources(source.image_path, source.json_path)
    view = window.view
    window.activate_mode("Select figures")
    original = view.session.geometry()
    ids = tuple(r.id for r in original.lineage)
    view.figure_line_ids = ids
    view.figure_move_double_click = enabled
    window.update_map_info()
    window.activate_mode("Move figures")
    view.setTransform(QTransform.fromScale(zoom, zoom))
    view.centerOn(180, 140)
    QApplication.processEvents()
    # The first click misses by seven screen pixels. Jitter then reaches the line.
    # A paired empty first hit must still clear rather than select the second hit.
    first = view.mapFromScene(60, 60) + QPoint(0, 7) if near_edge else view.mapFromScene(300, 220)
    second = first + QPoint(0, -2)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=first)
    assert view.figure_line_ids == ids
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=second)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=second)
    assert view.figure_line_ids == (() if enabled else ids)
    assert view.mode == "Move figures"
    assert view.session.geometry() == original and not view.session.operations
    assert not view.session.future


@pytest.mark.parametrize("language", ["en", "ru"])
def test_move_contour_double_click_settings_stage_and_persist(
    window, pair_factory, tmp_path, language
):
    from dale.project_io import _load_ui

    source = pair_factory()
    assert window.load_sources(source.image_path, source.json_path)
    window.set_language(language, persist=False)
    window.activate_mode("Move figures")
    view = window.view
    before_settings = window.document_state()
    popup = window.show_tool_settings("Move figures")
    checkbox = popup.figure_double_click
    assert checkbox.isChecked() and view.figure_move_double_click
    assert checkbox.text() == (
        "Выделять контур двойным кликом" if language == "ru" else "Select contour by double-click"
    )
    assert checkbox.toolTip().splitlines()[0] == checkbox.text()
    checkbox.setChecked(False)
    popup.reject()
    assert view.figure_move_double_click
    assert window.document_state() == before_settings
    popup = window.show_tool_settings("Move figures")
    popup.figure_double_click.setChecked(False)
    popup.accept()
    assert not view.figure_move_double_click
    assert window.document_state() != before_settings
    view.figure_line_ids = (view.session.geometry().lineage[0].id,)
    window.update_map_info()
    selected = view.figure_line_ids
    view.setTransform(QTransform.fromScale(1, 1))
    view.centerOn(40, 150)
    QApplication.processEvents()
    point = view.mapFromScene(30, 20)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert view.figure_line_ids == selected and not view.session.operations
    window.project_path = tmp_path / "move-double-click.dale"
    assert window.save_project_file()
    assert window.load_project_file(window.project_path)
    assert not view.figure_move_double_click
    assert _load_ui({})["figure_move_double_click"] is True
    assert _load_ui({"figure_move_double_click": False})["figure_move_double_click"] is False


@pytest.mark.parametrize("value", [1, 0, "yes", None, []])
def test_move_contour_double_click_project_flag_is_strict(value):
    from dale.project_io import _load_ui

    with pytest.raises(ValueError, match="double-click preference"):
        _load_ui({"figure_move_double_click": value})


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
    items = json.loads(next(folder.glob("*-placement.json")).read_text())["items"]
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
    assert all(isinstance(op, RasterSelectionEdit) for op in view.session.operations)
    assert len(view.session.operations) == (4 if mode == "Select raster regions" else 0)
    window.selected_regions = ()
    window.update_map_info()
    assert (window.document_state() == before[0]) == (mode == "Select regions")


@pytest.mark.parametrize("mode", ["Select regions", "Select raster regions"])
@pytest.mark.parametrize("zoom", [1, 3])
def test_selection_threshold_empty_click_and_escape_are_screen_based(
    window, pair_factory, mode, zoom, monkeypatch
):
    from PySide6.QtCore import QPoint

    _, view = selection_scene(window, pair_factory, mode, zoom)
    monkeypatch.setattr(window, "question", lambda *args: QMessageBox.StandardButton.Yes)
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
    assert all(isinstance(op, RasterSelectionEdit) for op in view.session.operations)
    assert len(view.session.operations) == (2 if mode == "Select raster regions" else 0)


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
            assert view.detached_selection is None and not window.selected_regions
            assert not view.region_polygons
            window.select_tool_set("regions")
        else:
            QTest.keyClick(view, Qt.Key.Key_Escape)
        assert not view.active_gesture and window.marquee_selection is None
        assert view.detached_selection == frozen and window.selected_regions == original
        assert view.region_polygons == frozen["polygons"]
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=b)
    assert len(view.session.operations) == 1


@pytest.mark.parametrize("section", ["geometry", "figures", "regions", "pixels"])
@pytest.mark.parametrize("show_contours", [False, True])
def test_section_selection_painting_is_isolated_and_restored(
    window, pair_factory, section, show_contours
):
    source, view = selection_scene(window, pair_factory, "Select regions")
    original = view.session.geometry(), tuple(view.session.operations), view.preview.tobytes()
    source_bytes = source.image_path.read_bytes(), source.json_path.read_bytes()
    view.show_walls = show_contours

    def frame():
        window.activate_mode("Pan")
        view.cursor_point = None
        view.update_hover()
        QApplication.processEvents()
        return view.viewport().grab().toImage()

    baseline = {}
    for key in ("geometry", "figures", "regions", "pixels"):
        window.select_tool_set(key)
        baseline[key] = frame()
    window.select_tool_set(section)
    window.select_all_elements()
    selected = frame()
    assert selected != baseline[section]
    for other in baseline:
        if other == section:
            continue
        window.select_tool_set(other)
        assert frame() == baseline[other], (section, other, show_contours)
        # Clearing another section must not discard this section's retained selection.
        window.clear_selection()
        window.select_tool_set(section)
        assert frame() == selected
    assert (
        view.session.geometry(),
        tuple(op for op in view.session.operations if not isinstance(op, RasterSelectionEdit)),
        view.preview.tobytes(),
    ) == original
    assert len(view.session.operations) == (1 if section == "pixels" else 0)
    assert (source.image_path.read_bytes(), source.json_path.read_bytes()) == source_bytes


def test_regions_and_raster_keep_distinct_selections_and_masks(window, pair_factory):
    from dale.session import ContourMask

    _, view = selection_scene(window, pair_factory, "Select regions")
    window.toggle_region_at((60, 60))
    regular = view.region_polygons
    window.select_tool_set("pixels")
    assert not window.selected_regions and not view.region_polygons
    window.toggle_region_at((175, 60))
    raster = view.region_polygons
    assert raster != regular
    window.mask("inside")
    assert isinstance(view.session.operations[-1], ContourMask)
    assert view.session.operations[-1].boundary.equals(raster[0])
    window.select_tool_set("regions")
    assert view.region_polygons == regular
    window.clear_selection()
    assert not window.selected_regions
    window.select_tool_set("pixels")
    assert view.region_polygons == raster


@pytest.mark.parametrize("active", ["geometry", "figures", "regions", "pixels"])
def test_section_region_selections_and_detached_shape_roundtrip(
    window, pair_factory, tmp_path, active
):
    _, view = selection_scene(window, pair_factory, "Select regions")
    window.toggle_region_at((60, 60))
    assert view.copy_selected_regions()
    assert view.begin_paste_regions()
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(175, 170))
    frozen = view.detached_selection
    assert frozen
    window.select_tool_set("pixels")
    window.toggle_region_at((280, 60))
    raster = view.region_polygons
    window.select_tool_set(active)
    window.project_path = tmp_path / f"Selection {active}.dale"
    assert window.save_project_file() and window.load_project_file(window.project_path)
    assert window.current_tool_set == active
    window.select_tool_set("pixels")
    assert view.region_polygons == raster and view.detached_selection is None
    window.select_tool_set("regions")
    assert view.region_polygons == frozen["polygons"]
    assert view.detached_selection["line_ids"] == frozen["line_ids"]
    assert len(view.session.operations) == 2
    assert isinstance(view.session.operations[-1], RasterSelectionEdit)


def test_hidden_section_selections_cannot_reveal_group_lines(window, pair_factory):
    _, view = selection_scene(window, pair_factory, "Select figures")
    window.select_all_elements()
    ids = view.figure_line_ids
    window.select_tool_set("geometry")
    window.create_selection_group()
    group = window.selection_groups()[0]
    # Use identical live IDs in this section's group, without selecting them here.
    window.update_selection_group(group.id, lines=ids)
    window.toggle_group_manager()
    view.show_walls = False
    assert view.figure_line_ids == ids and not view.contour_line_ids
    assert window.group_overlay() == ((), ())
    window.select_all_elements()
    assert window.group_overlay()[0]
    window.select_tool_set("figures")
    assert not window.group_overlay()[0]  # No groups from Vertices in Contours.


def test_json_only_vertex_view_preserves_hidden_region_selection(window, pair_factory):
    source = pair_factory()
    assert window.load_sources(None, source.json_path)
    window.select_tool_set("regions")
    window.select_all_elements()
    selected = window.selected_regions
    assert selected
    window.select_tool_set("geometry")
    assert window.selected_regions == selected
    assert window.view.selected_path.isEmpty()
    window.select_tool_set("regions")
    assert window.selected_regions == selected and window.view.region_polygons


def test_section_region_selections_do_not_leak_across_datasets(window, pair_factory, tmp_path):
    path, _ = make_catalog(pair_factory(size=(400, 400)), tmp_path)
    assert window.load_project_file(path)
    base = window.catalog.base_key
    other = next(key for key in window.catalog.views if key != base)
    window.select_tool_set("regions")
    window.select_all_elements()
    regular = window.selected_regions
    window.select_tool_set("pixels")
    assert not window.selected_regions
    window.select_all_elements()
    raster = window.selected_regions
    window.dataset_control.setCurrentIndex(window.dataset_control.findData(other))
    window.clear_selection()
    window.dataset_control.setCurrentIndex(window.dataset_control.findData(base))
    assert window.selected_regions == raster
    window.select_tool_set("regions")
    assert window.selected_regions == regular


def test_inactive_cell_indices_are_not_reused_after_topology_changes(window, pair_factory):
    from dale.editing import add_rectangle

    _, view = selection_scene(window, pair_factory, "Select regions")
    window.toggle_region_at((60, 60))
    window.select_tool_set("pixels")
    window.toggle_region_at((175, 60))
    window.select_tool_set("figures")
    view.session.add(add_rectangle(view.session.geometry(), (5, 5), (20, 20)))
    window.refresh()
    assert window.ui_state()["section_region_selections"] == {"regions": (), "pixels": ()}
    for section in ("regions", "pixels"):
        window.select_tool_set(section)
        assert not window.selected_regions and not view.region_polygons


def test_vertex_commit_also_clears_inactive_raster_cell_selection(window, pair_factory):
    _, view = selection_scene(window, pair_factory, "Select raster regions")
    window.toggle_region_at((60, 60))
    window.select_tool_set("regions")
    window.toggle_region_at((175, 60))
    window.activate_mode("New line")
    a, b = view.mapFromScene(120, 160), view.mapFromScene(220, 180)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=a)
    QTest.mouseMove(view.viewport(), b)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=b)
    assert len(view.session.operations) == 2
    assert isinstance(view.session.operations[0], RasterSelectionEdit)
    for section in ("regions", "pixels"):
        window.select_tool_set(section)
        assert not window.selected_regions and not view.region_polygons


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
    assert len(view.session.operations) == 2
    assert isinstance(view.session.operations[0], RasterSelectionEdit)
    mask = view.session.operations[1]
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
        assert loaded.session.operations[1].boundary.equals(mask.boundary)
        assert loaded.session.contour_offset == 5
        loaded.session.undo()
        assert loaded.session.operations[-1] == mask  # Undo the later selection first.
        loaded.session.undo()
        assert not raster_operations(loaded.session.operations)
        loaded.session.undo()
        assert not loaded.session.operations
        loaded.session.redo()
        assert isinstance(loaded.session.operations[-1], RasterSelectionEdit)
        loaded.session.redo()
        assert loaded.session.operations[-1] == mask
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


@pytest.mark.parametrize("via_manager", [False, True])
def test_last_dataset_reopens_after_navigation_without_saving_project(
    window, pair_factory, tmp_path, via_manager
):
    from dale.preferences import load_project_dataset

    path, _ = make_catalog(pair_factory(size=(400, 400)), tmp_path)
    assert window.load_project_file(path)
    base = window.catalog.base_key
    other = next(key for key in window.catalog.views if key != base)
    archive = path.read_bytes()
    if via_manager:
        assert window.apply_dataset_manager(window.catalog.fork(), other)
    else:
        window.dataset_control.setCurrentIndex(window.dataset_control.findData(other))
    expected = window.view.session.geometry()
    assert window.catalog.active_key == other
    assert window.document_state() == window.saved_state
    assert load_project_dataset(window.preferences_path, path) == other
    assert path.read_bytes() == archive
    with load_project(path) as project:
        assert project.catalog.active_key == project.catalog.base_key
    reopened = MainWindow(preferences_path=window.preferences_path)
    reopened.can_discard = lambda: True
    try:
        assert reopened.load_project_file(path)
        assert reopened.catalog.active_key == other
        assert reopened.dataset_control.currentData() == other
        assert reopened.view.session.geometry() == expected
        assert reopened.view.session is reopened.catalog.current.session
        assert path.read_bytes() == archive
    finally:
        reopened.close()
        reopened.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_last_dataset_is_independent_for_two_projects_with_the_same_dataset_ids(
    window, pair_factory, tmp_path
):
    path, _ = make_catalog(pair_factory(size=(400, 400)), tmp_path)
    copied = tmp_path / "Copy.dale"
    copied.write_bytes(path.read_bytes())
    assert window.load_project_file(path)
    base = window.catalog.base_key
    other = next(key for key in window.catalog.views if key != base)
    window.dataset_control.setCurrentIndex(window.dataset_control.findData(other))
    assert window.load_project_file(copied) and window.catalog.active_key == base
    assert window.load_project_file(path) and window.catalog.active_key == other
    assert window.load_project_file(copied) and window.catalog.active_key == base


def test_last_dataset_archive_choice_survives_save_as_and_stale_local_choice(
    window, pair_factory, tmp_path, monkeypatch
):
    from PySide6.QtWidgets import QFileDialog

    from dale.preferences import load_project_dataset, save_project_dataset

    path, _ = make_catalog(pair_factory(size=(400, 400)), tmp_path)
    assert window.load_project_file(path)
    base = window.catalog.base_key
    other = next(key for key in window.catalog.views if key != base)
    original = path.read_bytes()
    window.dataset_control.setCurrentIndex(window.dataset_control.findData(other))
    target = tmp_path / "Save As.dale"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    assert window.save_project_file(save_as=True)
    assert path.read_bytes() == original
    assert load_project_dataset(window.preferences_path, target) == other
    with load_project(target) as project:
        assert project.catalog.active_key == other and project.catalog.base_key == base
        assert project.session is project.catalog.current.session
    save_project_dataset(window.preferences_path, target, "set-" + "f" * 32)
    saved = target.read_bytes()
    assert window.load_project_file(target) and window.catalog.active_key == other
    assert target.read_bytes() == saved
    assert load_project_dataset(window.preferences_path, target) == other


def test_deleted_last_dataset_falls_back_to_first_and_updates_local_choice(
    window, pair_factory, tmp_path
):
    from dale.preferences import load_project_dataset, save_project_dataset

    path, _ = make_catalog(pair_factory(size=(400, 400)), tmp_path)
    assert window.load_project_file(path)
    base = window.catalog.base_key
    other = next(key for key in window.catalog.views if key != base)
    window.dataset_control.setCurrentIndex(window.dataset_control.findData(other))
    fork = window.catalog.fork()
    fork.remove(other)
    assert window.apply_dataset_manager(fork) and window.catalog.active_key == base
    assert window.save_project_file()
    save_project_dataset(window.preferences_path, path, other)
    saved = path.read_bytes()
    assert window.load_project_file(path) and window.catalog.active_key == base
    assert load_project_dataset(window.preferences_path, path) == base
    assert path.read_bytes() == saved


def test_last_dataset_preference_failure_does_not_block_navigation_or_save(
    window, pair_factory, tmp_path, monkeypatch
):
    path, _ = make_catalog(pair_factory(size=(400, 400)), tmp_path)
    assert window.load_project_file(path)
    other = next(key for key in window.catalog.views if key != window.catalog.base_key)

    def fail(*args):
        raise OSError("Synthetic preference failure")

    monkeypatch.setattr("dale.ui.save_project_dataset", fail)
    window.dataset_control.setCurrentIndex(window.dataset_control.findData(other))
    assert window.catalog.active_key == other and window.save_project_file()
    with load_project(path) as project:
        assert project.catalog.active_key == other


def test_failed_project_open_does_not_change_remembered_dataset(
    window, pair_factory, tmp_path, monkeypatch
):
    path, _ = make_catalog(pair_factory(size=(400, 400)), tmp_path)
    assert window.load_project_file(path)
    previous = window.catalog.active_key
    settings = window.preferences_path.read_bytes()
    corrupt = tmp_path / "Corrupt.dale"
    corrupt.write_bytes(b"Synthetic invalid archive")
    monkeypatch.setattr(window, "warning", lambda *args: None)
    assert not window.load_project_file(corrupt)
    assert window.catalog.active_key == previous
    assert window.preferences_path.read_bytes() == settings


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
    monkeypatch.setattr(window, "confirm_export_file", lambda path: "overwrite")
    monkeypatch.setattr(window, "information", lambda *args: None)
    before = window.document_state(), window.saved_state, window.catalog.active_key
    window.export_json_action.trigger()
    exported = destination.with_suffix(".json")
    assert exported.read_bytes() == repaired_json_bytes(window.view.session)[0]
    assert load_pair(None, exported).walls == session.walls
    assert len(session.walls) == 2 and len(session.future) == 1
    assert Path(dialogs[0][2]).name == f"Active draft-{window.export_identity()}.json"
    assert dialogs[0][1] == window.t("Export JSON…")
    assert (window.document_state(), window.saved_state, window.catalog.active_key) == before
    assert path.read_bytes() == original_project
    session.redo()
    window.export_json_action.trigger()
    assert len(load_pair(None, exported).walls) == 3
    window.dataset_control.setCurrentIndex(window.dataset_control.findData(window.catalog.base_key))
    window.export_json_action.trigger()
    assert exported.read_bytes() == repaired_json_bytes(window.view.session)[0]
    assert Path(dialogs[-1][2]).name == f"source-{window.export_identity()}.json"
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
        assert Path(args[2]).name == f"source-{window.export_identity()}.json"
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
    assert window.tool_scroll.verticalScrollBar().maximum() == 0
    button = window.sized_tools["Close all contours"]
    assert button.isVisible() and not window.global_close_control.isVisible()
    bottom = button.mapTo(window.tool_scroll.viewport(), button.rect().bottomRight())
    assert window.tool_scroll.viewport().rect().contains(bottom)


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


@pytest.mark.parametrize("section", ["regions", "figures"])
@pytest.mark.parametrize("destination", ["geometry", "pixels"])
def test_keyboard_clipboard_survives_dataset_switch_to_another_section(
    window, pair_factory, tmp_path, section, destination
):
    source = pair_factory(size=(400, 400))
    assert window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Select figures" if section == "figures" else "Select regions")
    app = QApplication.instance()
    window.activateWindow()
    window.view.setFocus()
    app.processEvents()
    QTest.keyClick(window.view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(window.view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    clipboard = window.view.region_clipboard
    assert clipboard and len(clipboard.edges) == 4
    image = tmp_path / "Target.png"
    Image.new("RGB", (400, 400), "#254c62").save(image)
    target = window.catalog.create(
        "Target",
        ui={
            "tool_set": destination,
            "mode": "Edit points" if destination == "geometry" else "Select raster regions",
        },
    )
    window.catalog.replace_component(target.id, "image", Session(load_pair(image, None)))
    target.ui["mode"] = "Edit points" if destination == "geometry" else "Select raster regions"
    window.rebuild_dataset_controls()
    window.dataset_control.setCurrentIndex(window.dataset_control.findData(target.id))
    assert window.current_tool_set == destination
    assert window.view.region_clipboard is clipboard and window.paste_regions_action.isEnabled()
    assert window.paste_regions_action.text() == window.t(
        "Paste contours" if section == "figures" else "Paste region contours"
    )
    view = window.view
    view.setTransform(QTransform())
    view.centerOn(200, 200)
    view.cursor_point = (150, 70)
    view.setFocus()
    app.processEvents()
    QTest.keyClick(view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert window.current_tool_set == section and view.paste_delta is not None
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert view.region_clipboard is clipboard and not view.session.operations
    QTest.keyClick(view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(150, 70))
    assert len(view.session.walls) == 4 and len(view.session.operations) == 1
    assert clipboard is view.region_clipboard
    assert not source.image_path.read_bytes() == image.read_bytes()
    window.project_path = tmp_path / "Pasted.dale"
    assert window.save_project_file() and window.load_project_file(window.project_path)
    assert len(window.view.session.walls) == 4


@pytest.mark.parametrize("section", ["figures", "regions"])
def test_application_clipboard_survives_source_project_window_and_extraction_close(
    window, pair_factory, tmp_path, section
):
    source = pair_factory(size=(400, 400))
    assert window.load_sources(source.image_path, source.json_path)
    window.project_path = tmp_path / "Source project.dale"
    assert window.save_project_file() and window.load_project_file(window.project_path)
    window.activate_mode("Select figures" if section == "figures" else "Select regions")
    target = MainWindow(preferences_path=tmp_path / "other-settings.json")
    target.can_discard = lambda: True
    target.warning = lambda *args: pytest.fail(str(args))
    target.show()
    image = tmp_path / "Other project.png"
    Image.new("RGB", (400, 400), "#254c62").save(image)
    assert target.load_sources(image, None)
    target.activate_mode("Edit points")
    app = QApplication.instance()
    app.processEvents()
    window.activateWindow()
    window.view.setFocus()
    app.processEvents()
    QTest.keyClick(window.view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert window.copy_regions_action.isEnabled()
    QTest.keyClick(window.view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    clipboard = window.view.region_clipboard
    assert clipboard and target.view.region_clipboard is clipboard
    assert window._clipboard_section == section
    window.close()
    assert not window._clipboard_connected
    target.activateWindow()
    target.view.setTransform(QTransform())
    target.view.centerOn(200, 200)
    target.view.cursor_point = (180, 90)
    target.view.setFocus()
    app.processEvents()
    QTest.keyClick(target.view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert target.view.paste_delta is not None and target.current_tool_set == section
    QTest.mouseClick(
        target.view.viewport(), Qt.MouseButton.LeftButton, pos=target.view.mapFromScene(180, 90)
    )
    assert len(target.view.session.walls) == 4
    assert all(r.sources and r.origin == "editor" for r in target.view.session.geometry().lineage)
    target.project_path = tmp_path / "Other project.dale"
    assert target.save_project_file()
    with load_project(target.project_path) as loaded:
        assert loaded.session.geometry().lineage == target.view.session.geometry().lineage
        assert any(d.data == source.json_bytes for d in loaded.session.json_documents)
        loaded.session.undo()
        assert not loaded.session.walls
    target.close()
    target.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


@pytest.mark.parametrize(
    "operation",
    [
        "insert",
        "move",
        "delete",
        "line",
        "circle",
        "rectangle",
        "erase_lines",
        "erase_vertices",
    ],
)
def test_vertex_geometry_commits_clear_contour_and_region_selection_but_keep_clipboard(
    window, pair_factory, operation
):
    source = pair_factory(size=(500, 400))
    assert window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Select figures")
    window.select_all_elements()
    window.copy_region_contours()
    clipboard = window.view.region_clipboard
    original = window.view.session.geometry()
    window.activate_mode("Edit points")
    window.selected_regions = (0,)
    window.update_map_info()
    assert window.selected_regions and window.view.figure_line_ids
    window.view.detached_selection = {
        "geometry": original,
        "polygons": window.view.region_polygons,
        "line_ids": tuple(r.id for r in original.lineage),
    }
    view = window.view
    view.snap_enabled = False
    view.setTransform(QTransform())
    view.centerOn(250, 200)
    modes = {
        "insert": "Edit points",
        "move": "Edit points",
        "delete": "Edit points",
        "line": "New line",
        "circle": "New circle",
        "rectangle": "New rectangle",
        "erase_lines": "Erase lines",
        "erase_vertices": "Erase vertices",
    }
    window.activate_mode(modes[operation])
    QApplication.processEvents()
    if operation == "delete":
        QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(10, 20))
    else:
        start, end = {
            "insert": ((35, 20), (35, 20)),
            "move": ((10, 20), (20, 35)),
            "line": ((180, 100), (260, 150)),
            "circle": ((200, 200), (230, 230)),
            "rectangle": ((180, 100), (260, 150)),
            "erase_lines": ((35, 20), (35, 20)),
            "erase_vertices": ((10, 20), (10, 20)),
        }[operation]
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(*start))
        QTest.mouseMove(view.viewport(), view.mapFromScene(*end))
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(*end))
    assert view.session.geometry() != original
    assert len(view.session.operations) == 1
    assert not window.selected_regions and not view.figure_line_ids
    assert not view.region_polygons and view.selected_path.isEmpty()
    assert view.detached_selection is None
    assert view.region_clipboard is clipboard
    for mode in ("Select figures", "Select regions"):
        window.activate_mode(mode)
        assert not window.selected_regions and not view.figure_line_ids


@pytest.mark.parametrize("cancel", [False, True])
def test_vertex_noop_or_cancel_keeps_other_section_selections(window, pair_factory, cancel):
    source = pair_factory(size=(500, 400))
    assert window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Select figures")
    window.select_all_elements()
    ids = window.view.figure_line_ids
    window.activate_mode("New rectangle")
    window.selected_regions = (0,)
    window.update_map_info()
    view = window.view
    view.setTransform(QTransform())
    view.centerOn(250, 200)
    QApplication.processEvents()
    point = view.mapFromScene(200, 100)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    if cancel:
        QTest.mouseMove(view.viewport(), view.mapFromScene(250, 160))
        QTest.keyClick(view, Qt.Key.Key_Escape)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    window.history(False)  # No operation available: this is also a no-op.
    assert not view.session.operations
    assert view.figure_line_ids == ids and window.selected_regions == (0,)


def test_vertex_history_clears_selections_only_when_geometry_changes(window, pair_factory):
    source = pair_factory(size=(500, 400))
    assert window.load_sources(source.image_path, source.json_path)
    view = window.view
    view.session.add(add_line(view.session.geometry(), (200, 100), (250, 160)))
    for redo in (False, True):
        window.activate_mode("Select figures")
        window.select_all_elements()
        window.activate_mode("Edit points")
        window.selected_regions = (0,)
        window.update_map_info()
        window.history(redo)
        assert not view.figure_line_ids and not window.selected_regions


@pytest.mark.parametrize("accept", [False, True])
def test_confirmed_vertex_auto_close_resets_selection_only_after_acceptance(
    window, pair_factory, monkeypatch, accept
):
    coordinates = (
        [10, 20, 60, 20],
        [60, 20, 60, 270],
        [60, 270, 10, 270],
        [10, 270, 10, 20],
        [100, 300, 150, 300],
        [154, 300, 220, 300],
    )
    source = pair_factory(size=(500, 400), walls=[{"c": c} for c in coordinates])
    assert window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Select figures")
    window.select_all_elements()
    ids = window.view.figure_line_ids
    window.activate_mode("Auto-close")
    window.selected_regions = (0,)
    window.update_map_info()
    window.global_close_control.setValue(10)
    window.view.setTransform(QTransform())
    monkeypatch.setattr(
        QMessageBox,
        "exec",
        lambda dialog: (
            QMessageBox.StandardButton.Yes if accept else QMessageBox.StandardButton.Cancel
        ),
    )
    window.close_all_contours()
    if accept:
        assert len(window.view.session.operations) == 1
        assert not window.view.figure_line_ids and not window.selected_regions
    else:
        assert not window.view.session.operations
        assert window.view.figure_line_ids == ids and window.selected_regions == (0,)


@pytest.mark.parametrize("enabled,alt", [(True, True), (False, True), (True, False)])
def test_paste_aligns_whole_copy_and_alt_toggle_keeps_rigid_dimensions(
    window, pair_factory, enabled, alt
):
    source = pair_factory(size=(400, 400))
    window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Select regions")
    window.toggle_region_at((30, 80))
    window.view.setFocus()
    QTest.mouseMove(window.view.viewport(), window.view.mapFromScene(30, 80))
    QTest.mouseMove(window.view.viewport(), window.view.mapFromScene(10, 20))
    QTest.keyClick(window.view, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    view = window.view
    assert view.region_clipboard
    view.contour_alignment = enabled
    view.contour_alignment_distance_px = 5
    view.setTransform(QTransform.fromScale(1, 1))
    view.cursor_point = (13, 290)
    QTest.keyClick(view, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
    assert view.paste_delta is not None
    view.cursor_point = (13, 290)
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
        (False, True, True, (200, 350)),
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
        assert tile.isVisible() and (tile.width(), tile.height()) == (48, 60)
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
        toolbar = window.alignment_toolbars[section]
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
        button = window.basic_toolbar.widgetForAction(action)
        assert button.isVisible() and (button.width(), button.height()) == (36, 36)
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
        assert loaded.catalog.base_session.contour_offset == 2
        assert loaded.catalog.active_key == other_id and loaded.session.contour_offset == 4
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
    view.contour_alignment_distance_px = 9999
    view.right_angle_tolerance_deg = 90
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
    item = json.loads(next(folder.glob("*-placement.json")).read_text())["items"][0]
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


@pytest.mark.parametrize("zoom", [1, 3])
@pytest.mark.parametrize(
    "tool",
    ["vertex", "contours", "regions", "paste_contours", "paste_regions", "line", "rectangle"],
)
def test_hover_acquires_external_axis_guides_for_all_placement_gestures(
    window, pair_factory, zoom, tool
):
    from itertools import pairwise

    from shapely.geometry import box

    edges = [
        *pairwise(box(30, 30, 80, 90).exterior.coords),
        ((250, 180), (280, 200)),
        ((247, 350), (249, 350)),
        ((252, 350), (260, 350)),
    ]
    source = pair_factory(
        size=(600, 500),
        walls=[{"c": [*a, *b]} for a, b in edges],
        lights=[{"keep": "light"}],
        tiles=[{"texture": {"src": "keep.webp"}}],
    )
    assert window.load_sources(source.image_path, source.json_path)
    view = window.view
    section = "figures" if "contours" in tool else "regions" if "regions" in tool else "geometry"
    window.select_tool_set(section)
    if section == "figures":
        window.select_figure_at({"point": (30, 50), "double": True})
        window.activate_mode("Move figures")
    elif section == "regions":
        window.toggle_region_at((45, 45))
        window.activate_mode("Move regions")
    else:
        window.activate_mode(
            {"vertex": "Edit points", "line": "New line", "rectangle": "New rectangle"}[tool]
        )
    window.contour_alignment_distance.setValue(6 * zoom)
    if section == "geometry":
        window.snap_action.setChecked(False)
        window.alignment_actions["contour_alignment"].setChecked(True)
    else:
        prefix = "Figure" if section == "figures" else "Region"
        actions = (
            window.figure_alignment_actions
            if section == "figures"
            else window.region_alignment_actions
        )
        actions[f"{prefix} point alignment"].setChecked(False)
        actions[f"{prefix} guide alignment"].setChecked(True)
    view.setTransform(QTransform.fromScale(zoom, zoom))
    view.centerOn(230, 230)
    QApplication.processEvents()
    original = view.session.geometry()
    raster = view.item.pixmap().toImage()
    before_bytes = source.json_path.read_bytes(), source.image_path.read_bytes()
    paste = tool.startswith("paste_")
    start = (78, 88) if tool == "vertex" else (75, 85) if section != "geometry" else (20, 20)
    for cancel in (True, False):
        if paste:
            view.cursor_point = start
            assert view.copy_selected_regions() and view.begin_paste_regions()
        else:
            QTest.mousePress(
                view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(*start)
            )
        # Acquire by the actual cursor even when the grabbed vertex has an offset.
        QTest.mouseMove(view.viewport(), view.mapFromScene(250, 180))
        assert (250, 180) in view.guide_targets.acquired
        acquired = set(view.guide_targets.acquired)
        QTest.mouseMove(view.viewport(), view.mapFromScene(247, 280))
        QTest.keyPress(view, Qt.Key.Key_Alt)
        expected = (
            250,
            280 if paste or tool in ("line", "rectangle") else 282 if tool == "vertex" else 285,
        )
        actual = (
            view.line_end
            if tool == "line"
            else view.rectangle_end
            if tool == "rectangle"
            else view.snap
            if tool == "vertex"
            else view.region_anchor
        )
        assert actual == pytest.approx(expected)
        guides = (
            view.alignment_guides
            if section == "geometry"
            else tuple((0, p) for p, _ in view.placement_guides)
        )
        assert (0, (250, 180)) in guides
        assert view.guide_targets.last == (250, 180)
        # Alt release removes the constraint but retains references for this gesture.
        QTest.keyRelease(view, Qt.Key.Key_Alt)
        assert view.guide_targets.acquired == acquired
        QTest.keyPress(view, Qt.Key.Key_Alt)
        if cancel:
            QTest.keyClick(view, Qt.Key.Key_Escape)
        elif paste:
            QTest.mouseClick(
                view.viewport(),
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.AltModifier,
                pos=view.mapFromScene(247, 280),
            )
        else:
            QTest.mouseRelease(
                view.viewport(),
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.AltModifier,
                pos=view.mapFromScene(247, 280),
            )
        QTest.keyRelease(view, Qt.Key.Key_Alt)
        assert view.guide_targets is None
        assert view.item.pixmap().toImage() == raster
        assert before_bytes == (source.json_path.read_bytes(), source.image_path.read_bytes())
        if cancel:
            assert view.session.geometry() == original and not view.session.operations
    assert len(view.session.operations) == 1
    result = json.loads(repaired_json_bytes(view.session)[0])
    assert result["lights"] == source.raw["lights"] and result["tiles"] == source.raw["tiles"]
    fixed = {r.id: e for r, e in zip(original.lineage[4:], original.walls[4:], strict=True)}
    current = {
        r.id: e
        for r, e in zip(view.session.geometry().lineage, view.session.geometry().walls, strict=True)
    }
    assert all(current[i] == e for i, e in fixed.items())
    view.session.undo()
    assert view.session.geometry() == original


@pytest.mark.parametrize("enabled", [False, True])
def test_external_guide_tracking_excludes_hidden_floor_and_moving_vertex(
    window, pair_factory, enabled
):
    walls = [
        {"c": c, "flags": {"wall-height": {"bottom": bottom, "top": bottom + 10}}}
        for bottom, c in ((0, [40, 40, 80, 90]), (0, [80, 90, 120, 40]), (10, [250, 180, 280, 200]))
    ]
    source = pair_factory(size=(600, 500), walls=walls)
    assert window.load_sources(source.image_path, source.json_path)
    from dale.source_editing import source_layers

    lower = next(
        c
        for c in source_layers(source, window.view.session.geometry())
        if c.kind == "band" and c.bottom == 0
    )
    window.layer_control.setCurrentIndex(window.layer_control.findData(lower.key))
    window.activate_mode("Edit points")
    window.snap_action.setChecked(False)
    window.alignment_actions["contour_alignment"].setChecked(enabled)
    view = window.view
    view.setTransform(QTransform.fromScale(1, 1))
    view.centerOn(220, 230)
    QApplication.processEvents()
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(80, 90))
    assert (80, 90) not in view.guide_targets.point_set
    QTest.mouseMove(view.viewport(), view.mapFromScene(250, 180))
    assert not view.guide_targets.acquired
    QTest.mouseMove(view.viewport(), view.mapFromScene(40, 40))
    assert bool(view.guide_targets.acquired) is enabled
    window.clear_selection()
    assert view.guide_targets is None and not view.session.operations


@pytest.mark.parametrize("language", ["ru", "en"])
def test_selected_export_json_checkbox_stages_persists_and_controls_real_worker(
    window, pair_factory, tmp_path, monkeypatch, language
):
    from PySide6.QtWidgets import QDialogButtonBox

    from dale.preferences import load_include_json

    source, view = selection_scene(window, pair_factory, "Select regions")
    window.set_language(language, persist=False)
    window.toggle_region_at((45, 45))
    window.remembered_merge_selected_regions = False
    assert window.include_json and load_include_json(window.preferences_path)
    dialog = window.show_tool_settings("Export selected regions")
    QApplication.processEvents()
    QApplication.processEvents()  # Deliver child LanguageChange after translator replacement.
    assert dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).text() == (
        "Применить" if language == "ru" else "Apply"
    )
    assert dialog.json_export.text() == (
        "Выгружать JSON" if language == "ru" else "Export JSON files"
    )
    assert dialog.json_export.isChecked()
    dialog.json_export.setChecked(False)
    dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel).click()
    assert window.include_json and load_include_json(window.preferences_path)
    for include in (False, True):
        dialog = window.show_tool_settings("Export selected regions")
        dialog.json_export.setChecked(include)
        dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).click()
        assert (
            window.include_json is include and load_include_json(window.preferences_path) is include
        )
        output = tmp_path / ("With JSON" if include else "PNG only")
        monkeypatch.setattr("dale.ui.choose_export_directory", lambda *args, output=output: output)
        window.export_regions_action.trigger()
        assert window.worker is not None and window.worker.include_json is include
        for _ in range(500):
            if window.worker is None:
                break
            QTest.qWait(10)
        assert window.worker is None
        assert len(tuple(output.glob("*.png"))) == 1
        assert len(tuple(output.glob("*.json"))) == (2 if include else 0)
        if include:
            family = f"{window.catalog.name}-{window.export_identity()}"
            assert (output / f"{family}.json").read_bytes() == repaired_json_bytes(view.session)[0]
            assert (output / f"{family}-placement.json").exists()
    assert not view.session.operations
    assert source.json_path.read_bytes() == source.json_bytes


def test_scene_json_chooser_matches_png_family_and_uses_png_basename_without_touching_it(
    window, pair_factory, tmp_path, monkeypatch
):
    source, view = selection_scene(window, pair_factory, "Select regions")
    window.toggle_region_at((45, 45))
    family = f"{window.catalog.name}-{window.export_identity()}"
    image = tmp_path / f"{family}-72x72px.png"
    image.write_bytes(b"existing exported image bytes")
    suggested = []

    def choose(*args):
        suggested.append(Path(args[2]).name)
        assert "*.png" in args[3] and "*.json" in args[3]
        return str(image), ""

    monkeypatch.setattr("dale.ui.QFileDialog.getSaveFileName", choose)
    monkeypatch.setattr(window, "information", lambda *args: None)
    monkeypatch.setattr(window, "confirm_export_file", lambda path: pytest.fail(str(path)))
    window.export_json()
    assert suggested == [family + ".json"]
    assert image.with_suffix(".json").read_bytes() == repaired_json_bytes(view.session)[0]
    assert image.read_bytes() == b"existing exported image bytes"
    assert not (tmp_path / (image.name + ".json")).exists()


@pytest.mark.parametrize("section", ["figures", "regions"])
@pytest.mark.parametrize("target", ["canvas", "sidebar", "direct"])
@pytest.mark.parametrize("wheel_axis", ["vertical", "windows-alt-horizontal"])
def test_alt_wheel_rotates_by_45_and_plain_wheel_remains_precise(
    window, pair_factory, section, target, wheel_axis
):
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent
    from shapely.affinity import rotate
    from shapely.geometry import MultiLineString

    source, view = selection_scene(window, pair_factory, "Select figures")
    window.select_tool_set(section)
    if section == "figures":
        window.select_figure_at({"point": (30, 70), "double": True})
    else:
        window.toggle_region_at((50, 50))
    window.activate_mode("Rotate figures" if section == "figures" else "Rotate regions")
    original = view.session.geometry()
    initial = view._region_plan()
    moving = MultiLineString(initial.moving)
    fixed = initial.fixed
    pivot = initial.pivot
    pixels = view.item.pixmap().toImage()
    zoom = view.transform()
    angle = 0
    for delta, modifiers, expected in (
        (120, Qt.KeyboardModifier.NoModifier, 0.1),
        (120, Qt.KeyboardModifier.AltModifier, 45),
        (240, Qt.KeyboardModifier.AltModifier, 90),
        (-120, Qt.KeyboardModifier.AltModifier, -45),
        (-120, Qt.KeyboardModifier.NoModifier, -0.1),
        (-60, Qt.KeyboardModifier.AltModifier, -45),
        (0, Qt.KeyboardModifier.AltModifier, 0),
    ):
        event = QWheelEvent(
            QPointF(20, 20),
            QPointF(20, 20),
            QPoint(),
            QPoint(delta, 0)
            if wheel_axis == "windows-alt-horizontal"
            and modifiers & Qt.KeyboardModifier.AltModifier
            else QPoint(0, delta),
            Qt.MouseButton.NoButton,
            modifiers,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        if target == "direct":
            view.wheelEvent(event)
        else:
            QApplication.sendEvent(view.viewport() if target == "canvas" else window.info, event)
        angle += expected
        plan = view._region_plan()
        assert plan.pivot == pivot and plan.fixed == fixed
        assert (
            MultiLineString(plan.moving).hausdorff_distance(rotate(moving, angle, origin=pivot))
            < 1e-7
        )
        assert view.transform() == zoom and view.item.pixmap().toImage() == pixels
        assert len(view.session.operations) == 1
    assert "Alt" in window.mode_help.text()
    assert source.json_path.read_bytes() == source.json_bytes
    final = view.session.geometry()
    window.history(False)
    assert view.session.geometry() == original
    window.history(True)
    assert view.session.geometry() == final


@pytest.mark.parametrize("axis", ["vertical", "horizontal"])
@pytest.mark.parametrize("disconnected", [False, True])
@pytest.mark.parametrize("height_layers", [False, True])
def test_mirror_contour_button_uses_common_center_keeps_properties_and_roundtrips(
    window, pair_factory, tmp_path, axis, disconnected, height_layers
):
    from itertools import pairwise

    edges = list(pairwise(((40, 40), (160, 40), (90, 130), (40, 40))))
    if disconnected:
        edges.append(((260, 180), (280, 200)))
    fixed = [((100, 10), (100, 180))]
    if height_layers:
        fixed.extend(edges[:3])
    walls = [
        {
            "_id": f"Wall{i:012d}",
            "c": [*a, *b],
            "door": int(i == 1),
            "flags": {"kept": i, "wall-height": {"bottom": 10 if i > len(edges) else 0, "top": 20}}
            if height_layers
            else {"kept": i},
        }
        for i, (a, b) in enumerate((*edges, *fixed))
    ]
    source = pair_factory(
        size=(400, 300), walls=walls, lights=[{"keep": "light"}], tiles=[{"keep": "tile"}]
    )
    assert window.load_sources(source.image_path, source.json_path)
    window.select_tool_set("figures")
    view = window.view
    original = view.session.geometry()
    view.figure_line_ids = tuple(r.id for r in original.lineage[: len(edges)])
    window.update_map_info()
    selected = tuple(view.figure_line_ids)
    pivot = (160, 120) if disconnected else (100, 85)
    assert view._region_plan().pivot == pivot
    expected = {
        record.id: tuple(
            (2 * pivot[0] - x, y) if axis == "vertical" else (x, 2 * pivot[1] - y) for x, y in edge
        )
        if record.id in selected
        else edge
        for record, edge in zip(original.lineage, original.walls, strict=True)
    }
    pixels = view.item.pixmap().toImage()
    before_native = repaired_json_bytes(view.session)[0]
    action = window.mirror_contour_actions[axis]
    assert action.isEnabled()
    button = window.figure_toolbar.widgetForAction(action)
    assert button.size().width() == button.size().height() == 48
    assert not button.isCheckable() and not action.icon().isNull()
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    first = view.session.geometry()
    assert len(view.session.operations) == 1
    assert dict(zip((r.id for r in first.lineage), first.walls, strict=True)) == expected
    assert set(first.lineage) == set(original.lineage)
    assert dict(first.wall_styles) == dict(original.wall_styles)
    assert view.figure_line_ids == selected and view._region_plan().pivot == pivot
    assert view.item.pixmap().toImage() == pixels
    exported = json.loads(repaired_json_bytes(view.session)[0])
    for key in ("lights", "tiles"):
        assert exported[key] == source.raw[key]
    for old, new in zip(source.raw["walls"], exported["walls"], strict=True):
        assert {k: v for k, v in old.items() if k != "c"} == {
            k: v for k, v in new.items() if k != "c"
        }
    window.project_path = tmp_path / f"Mirror {axis}.dale"
    assert window.save_project_file() and window.load_project_file(window.project_path)
    assert view.session.geometry() == first and view.figure_line_ids == selected
    window.mirror_contour_actions[axis].trigger()
    assert len(view.session.operations) == 2
    assert json.loads(repaired_json_bytes(view.session)[0]) == json.loads(before_native)
    window.history(False)
    assert view.session.geometry() == first
    window.history(False)
    assert view.session.geometry() == original
    window.history(True)
    window.history(True)
    assert json.loads(repaired_json_bytes(view.session)[0]) == json.loads(before_native)
    assert source.json_path.read_bytes() == source.json_bytes


@pytest.mark.parametrize("language", ["ru", "en"])
def test_mirror_controls_are_contextual_and_end_rotation_history(window, pair_factory, language):
    source, view = selection_scene(window, pair_factory, "Select figures")
    window.set_language(language, persist=False)
    assert all(not a.isEnabled() for a in window.mirror_contour_actions.values())
    window.select_figure_at({"point": (30, 70), "double": True})
    window.activate_mode("Rotate figures")
    view.transform_regions(angle=12)
    before = view.session.geometry()
    for axis in ("vertical", "horizontal"):
        action = window.mirror_contour_actions[axis]
        assert action.isEnabled()
        tip = action.toolTip()
        assert tip.startswith(action.text() + "\n")
        assert ("Назначение:" if language == "ru" else "Purpose:") in tip
    window.mirror_contour_actions["vertical"].trigger()
    assert len(view.session.operations) == 2 and view.mode == "Rotate figures"
    view.transform_regions(angle=0.1)
    assert len(view.session.operations) == 3
    window.history(False)
    window.history(False)
    assert view.session.geometry() == before
    # Gesture controls are tested using a real pending paste.
    assert view.copy_selected_regions() and view.begin_paste_regions()
    window.update_clipboard_actions()
    assert all(not a.isEnabled() for a in window.mirror_contour_actions.values())
    original = view.session.geometry()
    window.mirror_contours("horizontal")
    assert view.session.geometry() == original
    window.clear_selection()
    window.select_tool_set("regions")
    assert all(not a.isEnabled() for a in window.mirror_contour_actions.values())
    assert source.json_path.read_bytes() == source.json_bytes


@pytest.mark.parametrize("section", ["figures", "regions"])
@pytest.mark.parametrize("zoom,dpr", [(1, 1), (3, 2)])
def test_rotation_caption_is_cumulative_signed_centered_and_has_one_pixel_shadow(
    window, pair_factory, section, zoom, dpr
):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QFontMetricsF, QImage, QPainter

    class RecordingPainter(QPainter):
        def drawText(self, point, text):
            self.calls.append((QPointF(point), text, self.pen().color().name(), self.font()))
            return super().drawText(point, text)

    source, view = selection_scene(window, pair_factory, "Select figures", zoom)
    window.select_tool_set(section)
    if section == "figures":
        window.select_figure_at({"point": (30, 70), "double": True})
    else:
        window.toggle_region_at((50, 50))
    window.activate_mode("Rotate figures" if section == "figures" else "Rotate regions")
    original = view.session.geometry()
    pixels = view.item.pixmap().toImage()
    pivot = view._region_plan().pivot
    view.centerOn(*pivot)
    assert view.rotation_caption() is None
    for steps, modifier, caption in (
        (1, Qt.KeyboardModifier.AltModifier, "45.00°"),
        (1, Qt.KeyboardModifier.AltModifier, "90.00°"),
        (-3, Qt.KeyboardModifier.AltModifier, "-45.00°"),
        (1, Qt.KeyboardModifier.NoModifier, "-44.90°"),
        (-1, Qt.KeyboardModifier.NoModifier, "-45.00°"),
    ):
        view.rotate_by_wheel(steps, modifier)
        assert view.rotation_caption() == caption and view.rotation_pivot == pivot
        assert len(view.session.operations) == 1
    view.transform_regions(angle=0.01)
    assert view.rotation_caption() == "-44.99°"
    view.transform_regions(angle=-0.02)
    assert view.rotation_caption() == "-45.01°"
    image = QImage(
        view.viewport().width() * dpr, view.viewport().height() * dpr, QImage.Format.Format_ARGB32
    )
    image.setDevicePixelRatio(dpr)
    image.fill(Qt.GlobalColor.transparent)
    painter = RecordingPainter(image)
    painter.calls = []
    painter.setWorldTransform(view.viewportTransform())
    center = painter.worldTransform().map(QPointF(*pivot))
    view.draw_rotation_caption(painter)
    painter.end()
    shadow, text = painter.calls
    assert shadow[1:3] == ("-45.01°", "#000000") and text[1:3] == ("-45.01°", "#ffffff")
    assert (shadow[0].x() - text[0].x()) * dpr == pytest.approx(-1)
    assert (shadow[0].y() - text[0].y()) * dpr == pytest.approx(1)
    assert text[3].pixelSize() == 14
    assert (
        text[0] + QFontMetricsF(text[3]).boundingRect(text[1]).center() - center
    ).manhattanLength() < 1e-6
    assert any(
        image.pixelColor(x, y).alpha() for x in range(image.width()) for y in range(image.height())
    )
    assert view.item.pixmap().toImage() == pixels
    view.finish_rotation()
    assert view.rotation_caption() is None and view.rotation_angle == 0
    window.history(False)
    assert view.session.geometry() == original
    window.history(True)
    assert view.rotation_caption() is None
    if section == "regions":
        window.toggle_region_at(pivot)
        window.activate_mode("Rotate regions")
    view.rotate_by_wheel(-1, Qt.KeyboardModifier.AltModifier)
    assert view.rotation_caption() == "-45.00°" and len(view.session.operations) == 2
    window.activate_mode("Move figures" if section == "figures" else "Move regions")
    assert view.rotation_caption() is None
    assert source.json_path.read_bytes() == source.json_bytes


@pytest.mark.parametrize("language", ["ru", "en"])
def test_circle_detail_slider_stages_keyboard_changes_and_roundtrips(
    window, pair_factory, tmp_path, language
):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtWidgets import QDialogButtonBox

    source, view = selection_scene(window, pair_factory, "New circle")
    window.set_language(language, persist=False)
    button = window.tool_settings_buttons["New circle"]
    assert button.size().width() == button.size().height() == 48
    assert button.findChild(QWidget, "toolSettingsCorner") is not None
    QApplication.sendEvent(
        button,
        QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse, QPoint(24, 24), button.mapToGlobal(QPoint(24, 24))
        ),
    )
    popup = window.tool_settings_popup
    slider = popup.circle_detail
    assert slider.minimum() == 0 and slider.maximum() == 95
    assert slider.singleStep() == 1 and slider.value() == 0
    assert slider.pageStep() == 1
    assert popup.circle_detail_label.text() == window.t(
        "Multiplier: ×{factor}", factor="1,0" if language == "ru" else "1.0"
    )
    assert not popup.isModal()
    original = view.session.geometry()
    QTest.keyClick(slider, Qt.Key.Key_Right)
    assert slider.value() == 1 and view.circle_detail_steps == 0
    assert ("1,2" if language == "ru" else "1.2") in popup.circle_detail_label.text()
    QTest.keyClick(slider, Qt.Key.Key_End)
    assert slider.value() == 95
    assert ("20,0" if language == "ru" else "20.0") in popup.circle_detail_label.text()
    popup.buttons.button(QDialogButtonBox.StandardButton.Cancel).click()
    assert (
        view.circle_detail_steps == 0 and window.current_tool_values()["circle_detail_steps"] == 0
    )
    popup = window.show_tool_settings("New circle")
    popup.circle_detail.setValue(2)
    popup.buttons.button(QDialogButtonBox.StandardButton.Ok).click()
    assert view.circle_detail_steps == 2
    assert view.session.geometry() == original and not view.session.operations
    window.project_path = tmp_path / "Circle detail.dale"
    assert window.save_project_file() and window.load_project_file(window.project_path)
    assert view.circle_detail_steps == 2 and window.circle_detail_control.value() == 2
    assert (
        view.session.geometry() == original and source.json_path.read_bytes() == source.json_bytes
    )
    assert (
        window.t("Right-click: open tool settings.") in window.mode_actions["New circle"].toolTip()
    )


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("zoom", [1, 2])
@pytest.mark.parametrize("detail_steps", [1, 95])
def test_circle_detail_preview_equals_commit_and_cancel_preserves_source(
    window, pair_factory, monkeypatch, native, zoom, detail_steps
):
    from dale.editing import circle_points

    source = pair_factory(size=(600, 500), walls=[], grid={"size": 100}, lights=[{"keep": True}])
    assert window.load_sources(source.image_path, source.json_path)
    window.configure_json_repair(native)
    window.activate_mode("New circle")
    window.circle_detail_control.setValue(detail_steps)
    view = window.view
    view.setTransform(QTransform.fromScale(zoom, zoom))
    view.centerOn(250, 250)
    QApplication.processEvents()
    original = view.session.geometry()
    image = view.item.pixmap().toImage()
    painted = []

    def capture(*args, **kwargs):
        result = circle_points(*args, **kwargs)
        painted.append(result)
        return result

    monkeypatch.setattr("dale.canvas.circle_points", capture)
    start, end = view.mapFromScene(250, 250), view.mapFromScene(325, 250)
    for cancel in (True, False):
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(view.viewport(), end)
        view.viewport().grab()
        expected = painted[-1]
        count = 10 if detail_steps == 1 else 160
        assert len(expected) == count + 1
        assert view.circle_radius == 75 and not view.session.operations
        assert view.session.geometry() == original
        if cancel:
            QTest.keyClick(view, Qt.Key.Key_Escape)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
        if cancel:
            assert not view.session.operations and view.session.geometry() == original
    assert view.session.geometry().walls == tuple(zip(expected, expected[1:], strict=False))
    assert len(view.session.operations) == 1
    assert view.item.pixmap().toImage() == image
    assert json.loads(repaired_json_bytes(view.session)[0])["lights"] == source.raw["lights"]
    assert source.json_path.read_bytes() == source.json_bytes
    view.session.undo()
    assert view.session.geometry() == original
    view.session.redo()
    assert len(view.session.geometry().walls) == count


def test_circle_detail_project_values_survive_global_overrides(window, pair_factory, tmp_path):
    from dale.preferences import load_tool_values

    selection_scene(window, pair_factory, "New circle")
    window.circle_detail_control.setValue(2)
    window.set_global_tool_settings(True)
    window.circle_detail_control.setValue(5)
    assert window.view.circle_detail_steps == 5
    assert load_tool_values(window.preferences_path)["circle_detail_steps"] == 5
    window.project_path = tmp_path / "Local and global circle detail.dale"
    assert window.save_project_file()
    with load_project(window.project_path) as project:
        assert project.ui_state["circle_detail_steps"] == 2
    assert window.load_project_file(window.project_path)
    assert window.view.circle_detail_steps == 5
    window.set_global_tool_settings(False)
    assert window.view.circle_detail_steps == 2


@pytest.mark.parametrize("invalid", [-1, 96, True, 1.5, float("nan"), float("inf"), "1", None])
def test_circle_detail_rejects_invalid_project_and_preference_values(invalid, tmp_path):
    from dale.preferences import load_tool_values, save_tool_value
    from dale.project_io import _load_ui

    with pytest.raises(ValueError):
        _load_ui({"circle_detail_steps": invalid})
    with pytest.raises(ValueError):
        save_tool_value(tmp_path / "settings.json", "circle_detail_steps", invalid)
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"tool_values": {"circle_detail_steps": invalid}}))
    assert load_tool_values(settings)["circle_detail_steps"] == 0
    assert _load_ui({})["circle_detail_steps"] == 0


def test_circle_detail_restores_independent_dataset_values(window, pair_factory, tmp_path):
    path, _ = make_catalog(pair_factory(size=(400, 400)), tmp_path)
    assert window.load_project_file(path)
    base = window.catalog.base_key
    other = next(key for key in window.catalog.views if key != base)
    window.circle_detail_control.setValue(2)
    window.dataset_control.setCurrentIndex(window.dataset_control.findData(other))
    assert window.view.circle_detail_steps == 0
    window.circle_detail_control.setValue(5)
    window.dataset_control.setCurrentIndex(window.dataset_control.findData(base))
    assert window.view.circle_detail_steps == 2
    assert window.save_project_file() and window.load_project_file(path)
    assert window.view.circle_detail_steps == 2
    window.dataset_control.setCurrentIndex(window.dataset_control.findData(other))
    assert window.view.circle_detail_steps == 5


@pytest.mark.parametrize("section", ["figures", "regions"])
@pytest.mark.parametrize("language", ["ru", "en"])
def test_rotation_settings_stage_decimal_steps_and_roundtrip(
    window, pair_factory, tmp_path, section, language
):
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QContextMenuEvent, QWheelEvent
    from PySide6.QtWidgets import QDialogButtonBox

    source, view = selection_scene(window, pair_factory, "Select figures")
    window.select_tool_set(section)
    if section == "figures":
        window.select_figure_at({"point": (30, 70), "double": True})
    else:
        window.toggle_region_at((50, 50))
    mode = "Rotate figures" if section == "figures" else "Rotate regions"
    window.activate_mode(mode)
    window.set_language(language, persist=False)
    button = window.tool_settings_buttons[mode]
    QApplication.sendEvent(
        button,
        QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse, QPoint(24, 24), button.mapToGlobal(QPoint(24, 24))
        ),
    )
    dialog = window.tool_settings_popup
    assert dialog is not None and dialog.width() == 416
    assert [c.value() for c in dialog.rotation_values] == [0.1, 45]
    assert all(c.decimals() == 2 and c.minimum() == 0.01 for c in dialog.rotation_values)
    dialog.rotation_values[0].setValue(0.01)
    dialog.rotation_values[1].setValue(7.25)
    dialog.reject()
    assert view.rotation_steps[mode] == (0.1, 45)
    dialog = window.show_tool_settings(mode)
    dialog.rotation_values[0].setValue(0.01)
    dialog.rotation_values[1].setValue(7.25)
    dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).click()
    assert view.rotation_steps[mode] == (0.01, 7.25)
    other = "Rotate regions" if section == "figures" else "Rotate figures"
    assert view.rotation_steps[other] == (0.1, 45)
    for delta, modifiers in (
        (QPoint(0, 120), Qt.KeyboardModifier.NoModifier),
        (QPoint(120, 0), Qt.KeyboardModifier.AltModifier),
    ):
        event = QWheelEvent(
            QPointF(20, 20),
            QPointF(20, 20),
            QPoint(),
            delta,
            Qt.MouseButton.NoButton,
            modifiers,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(view.viewport(), event)
    assert view.rotation_caption() == "7.26°" and len(view.session.operations) == 1
    window.project_path = tmp_path / f"Decimal rotation {section}.dale"
    assert window.save_project_file() and window.load_project_file(window.project_path)
    assert view.rotation_steps[mode] == (0.01, 7.25) and view.rotation_steps[other] == (0.1, 45)
    assert source.json_path.read_bytes() == source.json_bytes


def test_rotation_project_steps_stay_separate_from_numeric_global_overrides(
    window, pair_factory, tmp_path
):
    from dale.preferences import load_tool_values

    selection_scene(window, pair_factory, "Select figures")
    key = "figure_rotation_step_cdeg"
    window.rotation_value_controls[key].setValue(125)
    window.set_global_tool_settings(True)
    window.rotation_value_controls[key].setValue(250)
    assert window.view.rotation_steps["Rotate figures"][0] == 2.5
    assert load_tool_values(window.preferences_path)[key] == 250
    window.project_path = tmp_path / "Project and global rotation.dale"
    assert window.save_project_file()
    with load_project(window.project_path) as project:
        assert project.ui_state[key] == 125
    assert window.load_project_file(window.project_path)
    assert window.view.rotation_steps["Rotate figures"][0] == 2.5
    window.set_global_tool_settings(False)
    assert window.view.rotation_steps["Rotate figures"][0] == 1.25


@pytest.mark.parametrize("invalid", [0, 36001, True, 1.5, float("nan"), float("inf"), "100", None])
def test_rotation_centidegree_fields_reject_invalid_project_values(invalid):
    from dale.preferences import ROTATION_VALUE_RANGES
    from dale.project_io import _load_ui

    for key in ROTATION_VALUE_RANGES:
        with pytest.raises(ValueError):
            _load_ui({key: invalid})


def test_own_angle_priority_is_independent_per_dataset_with_global_numbers_enabled(
    window, pair_factory, tmp_path
):
    source = pair_factory(size=(400, 400))
    assert window.load_sources(source.image_path, source.json_path)
    first = window.catalog.active_key
    window.set_global_tool_settings(True)
    dialog = window.show_tool_settings("Right-angle alignment")
    dialog.own_angle_priority.setChecked(False)
    dialog.accept()
    assert not window.view.right_angle_own_priority
    other = window.catalog.create("Other", ui=window.project_ui_state())
    other.ui.update(right_angle_own_priority=True, mode="Edit points")
    window.rebuild_dataset_controls()
    window.dataset_control.setCurrentIndex(window.dataset_control.findData(other.id))
    assert window.view.right_angle_own_priority
    dialog = window.show_tool_settings("Right-angle alignment")
    assert dialog.own_angle_priority.isChecked()
    dialog.reject()
    window.dataset_control.setCurrentIndex(window.dataset_control.findData(first))
    assert not window.view.right_angle_own_priority
    window.project_path = tmp_path / "Angle priority.dale"
    assert window.save_project_file() and window.load_project_file(window.project_path)
    assert not window.view.right_angle_own_priority
    window.dataset_control.setCurrentIndex(window.dataset_control.findData(other.id))
    assert window.view.right_angle_own_priority
    window.set_global_tool_settings(False)
    assert window.view.right_angle_own_priority


def test_contour_guide_toggle_survives_editing_and_restores_per_dataset_state(
    window, pair_factory, tmp_path
):
    source, view = selection_scene(window, pair_factory, "Select figures")
    guide = window.figure_alignment_actions["Figure guide alignment"]
    guide.setChecked(True)
    transitions = []
    guide.toggled.connect(transitions.append)
    for section in ("geometry", "regions", "pixels", "figures"):
        window.select_tool_set(section)
        assert guide.isEnabled() and guide.isChecked()
    for language in ("en", "ru", "en", "ru"):
        window.set_language(language, persist=False)
    for apply in (False, True):
        dialog = window.show_tool_settings("Figure guide alignment")
        dialog.value.setValue(17)
        dialog.accept() if apply else dialog.reject()
        assert guide.isChecked() and view.contour_alignment
    window.select_figure_at({"point": (30, 70), "double": True})
    window.activate_mode("Move figures")
    view.transform_regions(scale=1.05)
    window.history(False)
    window.history(True)
    window.clear_selection()
    window.refresh()
    window.show_sidebar("settings")
    window.show_sidebar("project")
    assert guide.isEnabled() and guide.isChecked() and not transitions
    window.catalog.capture(window.project_ui_state())
    first = window.catalog.active_key
    second = window.catalog.create("Independent settings")
    window.catalog.activate(second.id)
    # Each dataset deliberately owns its own flags. Restoring a saved false value
    # is the only non-click path that should turn this independent toggle off.
    second.ui = {**window.project_ui_state(), "figure_guide_alignment": False}
    window.show_catalog_view(second, load_preview(second.session.source), True)
    assert not guide.isChecked()
    window.catalog.capture(window.project_ui_state())
    draft = window.catalog.activate(first)
    window.show_catalog_view(draft, load_preview(draft.session.source), True)
    assert guide.isChecked() and view.contour_alignment
    window.project_path = tmp_path / "Guide states.dale"
    assert window.save_project_file() and window.load_project_file(window.project_path)
    assert guide.isChecked() and view.contour_alignment
    assert source.json_path.read_bytes() == source.json_bytes
