"""Retained paint paths and exact pointer answers across slow non-editing events."""

from dataclasses import replace
from math import dist

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shapely import GeometryCollection, LineString, union_all
from test_alchemist import sample as sample
from test_alchemist_interaction import editor as editor

from dale.canvas import line_path
from dale.provenance import LineRecord
from dale.selection_display import SelectionDisplay
from dale.session import GeometryEdit


def test_nearest_vertex_and_center_keep_exact_original_tie_order():
    edges = (
        ((-2, 0), (0, 2)),
        ((0, 2), (2, 0)),
        ((2, 0), (0, -2)),
        ((0, -2), (-2, 0)),
        ((10, 2), (10, 5)),
    )
    geometry = GeometryEdit(edges)
    display = SelectionDisplay(geometry, tuple(r.id for r in geometry.lineage))
    candidates = (*[p for edge in edges for p in edge], display.center)
    for point in ((0, 0), (1, 1), (2, 3), (100, 80), (-2, -4), (5, 2)):
        assert display.nearest_vertex(point, display.center) == min(
            candidates, key=lambda p: (dist(p, point), p)
        )
    assert display.path == line_path(edges)


def test_empty_warning_never_nodes_selection_and_nonempty_warning_remains_exact(monkeypatch):
    import dale.selection_display as module

    geometry = GeometryEdit((((0, 0), (10, 0)), ((5, -5), (5, 5))))
    display = SelectionDisplay(geometry, tuple(r.id for r in geometry.lineage))
    original = module.union_all
    monkeypatch.setattr(module, "union_all", lambda *_: pytest.fail("Unexpected noding"))
    assert display.warning_path(GeometryCollection()).isEmpty()
    monkeypatch.setattr(module, "union_all", original)
    warning = LineString(((3, 0), (8, 0)))
    path = display.warning_path(warning)
    assert path == line_path((((5, 0), (8, 0)), ((3, 0), (5, 0))))
    monkeypatch.setattr(module, "union_all", lambda *_: pytest.fail("Repeated warning noding"))
    assert display.warning_path(warning) is path


def test_focus_resize_delayed_repaint_reuse_selection_without_fitting(editor, monkeypatch):
    import dale.alchemist_render as render
    import dale.selection_display as module

    view = editor.view
    editor.show()
    view.figure_line_ids = tuple(r.id for r in view.editing_geometry().lineage)
    editor.update_map_info()
    QApplication.processEvents()
    display, geometry = view.selection_display(), view.session.geometry()
    path = display.path
    monkeypatch.setattr(module, "union_all", lambda *_: pytest.fail("Unexpected noding"))
    monkeypatch.setattr(render, "display_analysis", lambda *_: pytest.fail("Repeated analysis"))
    for event in (QEvent.Type.FocusOut, QEvent.Type.FocusIn):
        QApplication.sendEvent(view, QFocusEvent(event))
        QTest.qWait(600)
        view.viewport().repaint()
    editor.resize(editor.width() + 20, editor.height() + 10)
    QTest.mouseClick(editor.map_info, Qt.MouseButton.LeftButton)
    QTest.qWait(1200)
    editor.update_map_info()
    assert view.selection_display() is display
    assert view.figure_path() is path
    assert view.session.geometry() is geometry
    view.figure_line_ids = view.session.alchemist.objects[0].roots
    assert view.selection_display() is not display


def test_selection_cache_invalidates_on_geometry_even_with_same_ids(editor):
    view = editor.view
    view.figure_line_ids = view.session.alchemist.objects[0].roots
    before = view.selection_display()
    geometry = view.session.geometry()
    changed = replace(
        geometry, walls=tuple(tuple((x + 2, y - 3) for x, y in edge) for edge in geometry.walls)
    )
    view.session.add(changed)
    after = view.selection_display()
    assert after is not before
    assert after.center == pytest.approx((before.center[0] + 2, before.center[1] - 3))
    view.session.undo()
    assert view.selection_display().edges == before.edges
    view.figure_line_ids = ()
    assert view.figure_path().isEmpty()


def test_da_hover_outside_selected_objects_never_builds_general_components(editor, monkeypatch):
    import dale.canvas as module

    view = editor.view
    view.figure_line_ids = view.session.alchemist.objects[0].roots
    editor.activate_mode("Select figures")
    editor.update_map_info()
    monkeypatch.setattr(module, "components", lambda *_: pytest.fail("Whole-map connectivity"))
    for point in ((-10000, -10000), (10000, 10000), (200, 200)):
        view.hover_object_center(point)
        view._hover_region_anchor(point)
        assert view.region_anchor is not None


def test_ambiguous_crossing_warning_matches_geometric_intersection():
    geometry = GeometryEdit(
        (((0, 0), (10, 10)), ((0, 10), (10, 0))), lineage=(LineRecord("a"), LineRecord("b"))
    )
    display = SelectionDisplay(geometry, ("a",))
    warning = union_all([LineString(e) for e in geometry.walls])
    path = display.warning_path(warning)
    assert path == line_path((((5, 5), (10, 10)), ((0, 0), (5, 5))))
