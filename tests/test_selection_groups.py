"""Synthetic group identity, archive safety and real nonmodal map interactions."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QTransform, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox
from shapely.geometry import box

from dale.datasets import DatasetCatalog
from dale.editing import hit_edge, insert_vertex, move_vertex
from dale.json_repair import repaired_json_bytes
from dale.project_io import _load_ui, load_project, save_project
from dale.provenance import LineRecord
from dale.raster import load_preview
from dale.region_transform import copy_figures, copy_regions, plan_figure_transform
from dale.selection_groups import (
    SelectionGroup,
    boundary_members,
    decode_groups,
    group_members,
    group_ui_state,
    grouped_regions,
    matching_export_groups,
)
from dale.session import GeometryEdit, RasterSelectionEdit, Session
from dale.ui import MainWindow, configure_application


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    configure_application(app)
    monkeypatch.setenv("DALE_SETTINGS_PATH", str(tmp_path / "prefs.json"))
    owner = MainWindow()
    monkeypatch.setattr(owner, "can_discard", lambda: True)
    monkeypatch.setattr(owner, "warning", lambda *args: pytest.fail(str(args)))
    owner.show()
    app.processEvents()
    yield owner
    owner.close()
    owner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def scene(window, pair_factory):
    source = pair_factory()
    assert window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Select figures")
    QApplication.processEvents()
    ids = tuple(r.id for r in window.view.session.geometry().lineage)
    return source, ids


def viewport_position(manager):
    return manager.owner.view.viewport().mapFromGlobal(manager.mapToGlobal(QPoint()))


def populated_scroll_manager(window, pair_factory, section, fraction):
    from dataclasses import replace

    _, ids = scene(window, pair_factory)
    window.select_tool_set(section)
    groups = tuple(
        replace(SelectionGroup.create(f"Group {i:02}"), lines=ids if i % 2 else ())
        for i in range(24)
    )
    window.store_selection_groups(groups)
    window.toggle_group_manager()
    manager = window.group_manager
    manager.set_user_size(QSize(318, 190))
    QApplication.processEvents()
    bar = manager.scroll.verticalScrollBar()
    assert bar.maximum() > 500
    bar.setValue(round(bar.maximum() * fraction))
    QApplication.processEvents()
    visible = [
        group
        for group in groups
        if manager.scroll.viewport()
        .rect()
        .contains(manager.row_controls[group.id][1].mapTo(manager.scroll.viewport(), QPoint()))
        and manager.scroll.viewport()
        .rect()
        .contains(
            manager.row_controls[group.id][1].mapTo(
                manager.scroll.viewport(), manager.row_controls[group.id][1].rect().bottomRight()
            )
        )
    ]
    assert len(visible) >= 2
    return manager, groups, visible, ids


def move_group_handle(manager, identifier, destination):
    handle = manager.row_controls[identifier][0]
    QTest.mousePress(handle, Qt.MouseButton.LeftButton)
    QTest.mouseMove(handle, handle.mapFromGlobal(destination))
    return handle


@pytest.mark.parametrize("section", ["geometry", "figures", "regions", "pixels"])
def test_sorting_grip_reorders_without_editing_selection_members_or_scene(
    window, pair_factory, section, tmp_path, monkeypatch
):
    from dataclasses import replace

    source, ids = scene(window, pair_factory)
    window.select_tool_set(section)
    groups = tuple(
        replace(SelectionGroup.create(f"Order {i}"), lines=ids, priority=i + 4) for i in range(3)
    )
    window.store_selection_groups(groups)
    window.select_selection_group(groups[1].id)
    window.rebuild_group_controls()
    window.toggle_group_manager()
    manager = window.group_manager
    QApplication.processEvents()
    state = window.catalog.state()
    geometry = window.view.session.geometry()
    operations = tuple(window.view.session.operations)
    native = repaired_json_bytes(window.view.session)
    image = source.image_path.read_bytes()
    selection = window.group_selection_ids()
    monkeypatch.setattr(window, "change_group_color", lambda *a: pytest.fail("Color dialog opened"))
    assert manager.sort_button.width() == manager.sort_button.height()
    assert manager.sort_button.geometry().right() < manager.new_button.geometry().left()
    assert manager.new_button.width() > manager.sort_button.width()
    QTest.mouseClick(manager.sort_button, Qt.MouseButton.LeftButton)
    assert manager.sorting
    for handle, *buttons in manager.row_controls.values():
        assert handle.isEnabled() and not handle.styleSheet()
        assert all(not button.isEnabled() for button in buttons)
    handle = manager.row_controls[groups[0].id][0]
    QTest.keyClick(handle, Qt.Key.Key_Space)
    QTest.mouseClick(handle, Qt.MouseButton.LeftButton)
    assert window.catalog.state() == state
    last_row = manager.row_controls[groups[-1].id][0].parentWidget()
    destination = last_row.mapToGlobal(QPoint(12, last_row.height() - 2))
    handle = move_group_handle(manager, groups[0].id, destination)
    assert manager.drop_indicator.isVisible() and manager.drop_index == 2
    assert window.selection_groups() == groups
    QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=handle.mapFromGlobal(destination))
    QApplication.processEvents()
    expected = groups[1:] + groups[:1]
    assert window.selection_groups() == expected
    assert tuple(manager.row_controls) == tuple(g.id for g in expected)
    assert not manager.drop_indicator.isVisible()
    assert window.active_selection_group() == groups[1].id
    assert window.group_selection_ids() == selection
    assert window.view.session.geometry() == geometry
    assert tuple(window.view.session.operations) == operations
    assert repaired_json_bytes(window.view.session) == native
    assert source.image_path.read_bytes() == image
    assert window.catalog.state() != state
    path = tmp_path / "sorted.dale"
    save_project(window.view.session, path, window.project_ui_state(), catalog=window.catalog)
    loaded = load_project(path)
    try:
        assert decode_groups(loaded.catalog.current.ui["groups"]) == expected
    finally:
        loaded.close()
    QTest.mouseClick(manager.sort_button, Qt.MouseButton.LeftButton)
    assert not manager.sorting
    assert all(controls[1].isEnabled() for controls in manager.row_controls.values())
    assert all(g.color in manager.row_controls[g.id][0].styleSheet() for g in groups)


@pytest.mark.parametrize("cancel", ["escape", "outside", "toggle", "hide", "section"])
def test_sorting_cancel_does_not_move_a_group(window, pair_factory, cancel):
    _, ids = scene(window, pair_factory)
    window.view.figure_line_ids = ids
    groups = tuple(SelectionGroup.create(f"Order {i}") for i in range(3))
    window.store_selection_groups(groups)
    window.toggle_group_manager()
    manager = window.group_manager
    QTest.mouseClick(manager.sort_button, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    row = manager.row_controls[groups[0].id][0].parentWidget()
    destination = row.mapToGlobal(QPoint(12, 1))
    handle = move_group_handle(manager, groups[-1].id, destination)
    assert manager.drop_indicator.isVisible()
    if cancel == "escape":
        QTest.keyClick(handle, Qt.Key.Key_Escape)
    elif cancel == "outside":
        destination = manager.mapToGlobal(QPoint(-20, -20))
    elif cancel == "toggle":
        manager.sort_button.setChecked(False)
    elif cancel == "hide":
        manager.hide()
    else:
        window.activate_mode("Select regions")
    if cancel != "section":
        QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=handle.mapFromGlobal(destination))
    QApplication.processEvents()
    assert manager.drag_group is None
    assert not manager.drop_indicator.isVisible() and not manager.drag_scroll.isActive()
    if cancel == "section":
        assert not manager.sorting
        window.activate_mode("Select figures")
    assert window.selection_groups() == groups
    assert window.view.figure_line_ids == ids


def test_sorting_scrolls_at_list_edges_and_keeps_the_new_scroll_position(window, pair_factory):
    manager, groups, visible, _ = populated_scroll_manager(window, pair_factory, "figures", 0.5)
    QTest.mouseClick(manager.sort_button, Qt.MouseButton.LeftButton)
    viewport = manager.scroll.viewport()
    destination = viewport.mapToGlobal(QPoint(12, viewport.height() - 3))
    handle = move_group_handle(manager, visible[0].id, destination)
    bar = manager.scroll.verticalScrollBar()
    before = bar.value()
    assert manager.drag_scroll.isActive()
    QTest.qWait(120)
    assert bar.value() > before
    index = manager.drop_index
    scrolled = bar.value()
    QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=handle.mapFromGlobal(destination))
    QApplication.processEvents()
    assert window.selection_groups()[index].id == visible[0].id
    assert bar.value() == scrolled
    assert len(window.selection_groups()) == len(groups)
    assert not manager.drag_scroll.isActive()


def test_sorted_order_is_scoped_to_dataset_and_section(window, pair_factory):
    scene(window, pair_factory)
    figures = tuple(SelectionGroup.create(f"Contours {i}") for i in range(3))
    window.store_selection_groups(figures)
    window.activate_mode("Select regions")
    regions = tuple(SelectionGroup.create(f"Regions {i}") for i in range(3))
    window.store_selection_groups(regions)
    window.reorder_selection_group(regions[-1].id, 0)
    assert window.selection_groups() == regions[-1:] + regions[:-1]
    window.activate_mode("Select figures")
    assert window.selection_groups() == figures
    original = window.catalog.active_key
    window.catalog.capture(window.project_ui_state())
    other = window.catalog.create("Other order")
    window.catalog.activate(other.id)
    window.show_catalog_view(other, load_preview(other.session.source), False)
    assert not window.selection_groups()
    window.reorder_selection_group(figures[-1].id, 0)
    assert not window.selection_groups()
    window.catalog.activate(original)
    window.show_catalog_view(
        window.catalog.current, load_preview(window.catalog.current.session.source), True
    )
    window.activate_mode("Select figures")
    assert window.selection_groups() == figures
    window.activate_mode("Select regions")
    assert window.selection_groups() == regions[-1:] + regions[:-1]


@pytest.mark.parametrize("section", ["geometry", "figures", "regions", "pixels"])
@pytest.mark.parametrize("fraction", [0, 0.5, 1])
def test_group_click_keeps_list_scroll_and_row_identity(window, pair_factory, section, fraction):
    manager, _, visible, _ = populated_scroll_manager(window, pair_factory, section, fraction)
    bar = manager.scroll.verticalScrollBar()
    before = bar.value()
    group = visible[0]
    button = manager.row_controls[group.id][1]
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()
    assert window.active_selection_group() == group.id
    assert bar.value() == before
    assert manager.row_controls[group.id][1] is button


@pytest.mark.parametrize("action", ["add", "exclude", "rename", "color", "create", "delete"])
@pytest.mark.parametrize("fraction", [0.3, 1])
def test_group_actions_keep_list_scroll(window, pair_factory, monkeypatch, action, fraction):
    manager, groups, visible, ids = populated_scroll_manager(
        window, pair_factory, "figures", fraction
    )
    window.view.figure_line_ids = ids
    window.update_map_info()
    group = next(g for g in visible if bool(g.lines) == (action == "exclude"))
    before = manager.scroll.verticalScrollBar().value()
    if action in ("add", "exclude"):
        button = manager.row_controls[group.id][2 if action == "add" else 3]
        assert button.isEnabled()
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    elif action == "rename":
        monkeypatch.setattr("dale.ui.QInputDialog.getText", lambda *a, **k: ("Renamed", True))
        QTest.mouseDClick(manager.row_controls[group.id][1], Qt.MouseButton.LeftButton)
    elif action == "color":
        from PySide6.QtGui import QColor

        monkeypatch.setattr(window, "choose_project_color", lambda *a: QColor("#42aabb"))
        QTest.mouseClick(manager.row_controls[group.id][0], Qt.MouseButton.LeftButton)
    elif action == "create":
        QTest.mouseClick(manager.new_button, Qt.MouseButton.LeftButton)
    else:
        monkeypatch.setattr(window, "question", lambda *a: QMessageBox.StandardButton.Yes)
        QTest.mouseClick(manager.row_controls[group.id][4], Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()
    bar = manager.scroll.verticalScrollBar()
    assert bar.value() == min(before, bar.maximum())
    assert len(window.selection_groups()) == len(groups) + (
        1 if action == "create" else -1 if action == "delete" else 0
    )


@pytest.mark.parametrize("placement", ["free", "top-left", "bottom-right"])
def test_group_manager_uses_viewport_pixels_during_pan_zoom_fit_and_dataset_switch(
    window, pair_factory, placement
):
    source, _ = scene(window, pair_factory)
    window.toggle_group_manager()
    manager, view = window.group_manager, window.view
    manager.constrain_position(
        {"free": QPoint(80, 140), "top-left": QPoint(3, 4), "bottom-right": QPoint(9999, 9999)}[
            placement
        ]
    )
    fixed = viewport_position(manager)
    original = repaired_json_bytes(view.session)
    image = source.image_path.read_bytes()
    start = QPoint(20, view.viewport().height() - 180)
    before = view.camera_center()
    QTest.mousePress(view.viewport(), Qt.MouseButton.RightButton, pos=start)
    QTest.mouseMove(view.viewport(), start + QPoint(37, 29))
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.RightButton, pos=start + QPoint(37, 29))
    assert view.camera_center() != before
    assert viewport_position(manager) == fixed
    for delta in (120, -240):
        event = QWheelEvent(
            QPointF(start),
            QPointF(view.viewport().mapToGlobal(start)),
            QPoint(),
            QPoint(0, delta),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(view.viewport(), event)
        assert viewport_position(manager) == fixed
    view.centerOn(-5000, 5000)
    assert viewport_position(manager) == fixed
    view.fit_map()
    assert viewport_position(manager) == fixed
    window.move(window.pos() + QPoint(33, 27))
    QApplication.processEvents()
    assert viewport_position(manager) == fixed
    window.catalog.capture(window.project_ui_state())
    draft = window.catalog.create("Different frame")
    window.rebuild_dataset_controls()
    window.dataset_control.setCurrentIndex(window.dataset_control.findData(draft.id))
    assert viewport_position(manager) == fixed
    window.dataset_control.setCurrentIndex(0)
    assert viewport_position(manager) == fixed
    assert repaired_json_bytes(view.session) == original
    assert source.image_path.read_bytes() == image
    assert not view.session.operations
    assert manager.isVisible() and window.group_manager_button.isChecked()


@pytest.mark.parametrize(
    "dock_x,dock_y", [(0, 0), (-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, -1), (-1, 1), (1, 1)]
)
def test_group_manager_resize_preserves_intentional_sides_and_free_panel_moves_left(
    window, pair_factory, dock_x, dock_y
):
    scene(window, pair_factory)
    window.toggle_group_manager()
    manager = window.group_manager
    assert (manager.dock_x, manager.dock_y) == (0, 0)
    manager.constrain_position(
        QPoint({-1: 2, 0: 75, 1: 9999}[dock_x], {-1: 2, 0: 140, 1: 9999}[dock_y])
    )
    assert (manager.dock_x, manager.dock_y) == (dock_x, dock_y)
    for size in (QSize(1224, 768), QSize(1400, 940)):
        window.resize(size)
        QApplication.processEvents()
        bounds = window.view.viewport().size() - manager.size()
        expected_x = (
            0 if dock_x == -1 or not (dock_x or dock_y) else bounds.width() if dock_x == 1 else 75
        )
        expected_y = 0 if dock_y == -1 else bounds.height() if dock_y == 1 else 140
        assert viewport_position(manager) == QPoint(expected_x, expected_y)
        assert (manager.dock_x, manager.dock_y) == (dock_x, dock_y)
    window.create_selection_group()
    if dock_y:
        expected_y = 0 if dock_y < 0 else window.view.viewport().height() - manager.height()
        assert viewport_position(manager).y() == expected_y
    assert not window.view.session.operations


def test_group_manager_grip_resizes_only_overlay_and_retains_custom_dimensions(
    window, pair_factory
):
    scene(window, pair_factory)
    window.toggle_group_manager()
    manager, view = window.group_manager, window.view
    manager.constrain_position(QPoint(50, 60))
    old_window, old_size = window.size(), manager.size()
    grip = manager.size_grip
    assert grip.isVisible()
    start = grip.rect().center()
    target = grip.mapToGlobal(start) + QPoint(55, 70)
    QTest.mousePress(grip, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(grip, grip.mapFromGlobal(target))
    QTest.mouseRelease(grip, Qt.MouseButton.LeftButton, pos=grip.mapFromGlobal(target))
    assert manager.size() == old_size + QSize(55, 70)
    assert viewport_position(manager) == QPoint(50, 60)
    assert window.size() == old_window
    custom = manager.size()
    window.create_selection_group()
    assert manager.size() == custom
    manager.hide()
    window.toggle_group_manager()
    assert manager.size() == custom
    manager.set_user_size(QSize(9999, 9999))
    assert manager.size() == view.viewport().size()
    assert viewport_position(manager) == QPoint()
    assert not (manager.dock_x or manager.dock_y)
    manager.set_user_size(QSize(1, 1))
    assert manager.size() == manager.minimumSize()
    assert not view.session.operations


def test_group_manager_grip_stays_available_when_main_window_is_maximized(window, pair_factory):
    scene(window, pair_factory)
    window.toggle_group_manager()
    window.showMaximized()
    QApplication.processEvents()
    assert window.group_manager.size_grip.isVisible()


def test_scrollbar_visibility_does_not_dock_or_reset_a_free_manager(window, pair_factory):
    scene(window, pair_factory)
    window.toggle_group_manager()
    manager, view = window.group_manager, window.view
    manager.constrain_position(QPoint(80, 140))
    original = view.size()
    for policy in (Qt.ScrollBarPolicy.ScrollBarAlwaysOff, Qt.ScrollBarPolicy.ScrollBarAlwaysOn):
        view.setHorizontalScrollBarPolicy(policy)
        view.setVerticalScrollBarPolicy(policy)
        QApplication.processEvents()
        assert view.size() == original
        assert viewport_position(manager) == QPoint(80, 140)
        assert not (manager.dock_x or manager.dock_y)


def test_empty_manager_space_cannot_pan_zoom_or_clear_scene_selection(window, pair_factory):
    _, ids = scene(window, pair_factory)
    window.toggle_group_manager()
    window.view.figure_line_ids = ids
    manager, view = window.group_manager, window.view
    manager.set_user_size(QSize(380, 260))
    blank = manager.scroll.viewport()
    point = blank.rect().center()
    camera, zoom = view.camera_center(), view.transform()
    QTest.mousePress(blank, Qt.MouseButton.RightButton, pos=point)
    QTest.mouseMove(blank, point + QPoint(20, 20))
    QTest.mouseRelease(blank, Qt.MouseButton.RightButton, pos=point + QPoint(20, 20))
    QTest.mouseClick(blank, Qt.MouseButton.LeftButton, pos=point)
    event = QWheelEvent(
        QPointF(point),
        QPointF(blank.mapToGlobal(point)),
        QPoint(),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(blank, event)
    assert view.camera_center() == camera and view.transform() == zoom
    assert view.figure_line_ids == ids and not view.panning


def test_groups_follow_identity_splits_transform_exclusion_and_undo(pair_factory):
    session = Session(pair_factory())
    geometry = session.geometry()
    group = SelectionGroup.create("Room").assign((geometry.lineage[0].id,))
    divided = insert_vertex(geometry, hit_edge(geometry, (35, 20), 1))
    members = group_members(group, divided)
    assert len(members) == 2
    assert group_members(group, geometry) == {geometry.lineage[0].id}
    result, _ = plan_figure_transform(divided, members).apply(dx=20, angle=45)
    assert group_members(group, result) == members
    excluded = group.assign(members, False)
    assert not group_members(excluded, result)
    assert group_members(excluded, geometry) == {geometry.lineage[0].id}
    assert group_members(excluded.assign(members), result) == members
    manual = LineRecord.child((geometry.lineage[0],), ((0, 0), (10, 10)), manual=True)
    contact = GeometryEdit((((0, 0), (10, 10)),), lineage=(manual,), ancestry=geometry.lineage)
    assert not group_members(group, contact)


def test_deep_lineage_is_iterative():
    root = LineRecord("root")
    records = [root]
    for i in range(2000):
        records.append(LineRecord(f"split-{i}", (records[-1].id,), origin="derived"))
    geometry = GeometryEdit((((0, 0), (1, 1)),), lineage=(records[-1],), ancestry=tuple(records))
    assert group_members(SelectionGroup.create("Deep").assign((root.id,)), geometry) == {
        records[-1].id
    }


@pytest.mark.parametrize("kind", ["contours", "regions"])
def test_clipboard_copies_keep_ancestry_but_do_not_inherit_groups(pair_factory, tmp_path, kind):
    session = Session(pair_factory())
    geometry = session.geometry()
    ids = tuple(r.id for r in geometry.lineage)
    group = SelectionGroup.create("Original").assign(ids)
    clip = (
        copy_figures(geometry, ids)
        if kind == "contours"
        else copy_regions(geometry, session.analysis().cells[:1], session.analysis().cells)
    )
    pasted = clip.paste(geometry, 100, 0)
    assert group_members(group, pasted) == set(ids)
    copied = pasted.lineage[len(ids) :]
    assert all(r.origin == "editor" and r.parents and r.sources for r in copied)
    assert not group_members(group, clip.paste(GeometryEdit(()), 100, 0))
    divided = insert_vertex(pasted, hit_edge(pasted, (135, 20), 1))
    assert group_members(group, divided) == set(ids)
    added_group = group.assign(r.id for r in copied)
    assert len(group_members(added_group, divided)) == len(ids) + len(copied) + 1
    session.add(pasted)
    catalog = DatasetCatalog(session, ui={"groups": [group.encode()]})
    path = tmp_path / "independent-copies.dale"
    save_project(session, path, catalog=catalog)
    with load_project(path) as loaded:
        assert group_members(group, loaded.session.geometry()) == set(ids)
        loaded.session.undo()
        loaded.session.redo()
        assert group_members(group, loaded.session.geometry()) == set(ids)


def test_export_group_match_is_exact_and_uses_active_then_assignment_priority(pair_factory):
    from dataclasses import replace

    geometry = Session(pair_factory()).geometry()
    ids = tuple(r.id for r in geometry.lineage)
    first = SelectionGroup.create("First").assign(ids)
    latest = replace(SelectionGroup.create("Latest").assign(ids), priority=3)
    region = box(10, 20, 60, 270)
    assert matching_export_groups(geometry, (first, latest), ((region,),)) == (latest,)
    assert matching_export_groups(geometry, (first, latest), ((region,),), first.id) == (first,)
    assert matching_export_groups(geometry, (first,), ((box(10.000001, 20, 60, 270),),)) == (None,)
    assert matching_export_groups(geometry, (first.assign((ids[0],), False),), ((region,),)) == (
        None,
    )


@pytest.mark.parametrize("separate", [False, True])
@pytest.mark.parametrize("changed", ["none", "missing", "branch", "extended", "other-cell"])
def test_export_group_matches_all_cell_boundaries_without_extra_or_missing_lines(
    pair_factory, separate, changed
):
    from itertools import pairwise

    areas = (box(10, 20, 80, 110), box(160, 20, 200, 100))
    session = Session(
        pair_factory(
            size=(240, 160),
            walls=[{"c": [*a, *b]} for p in areas for a, b in pairwise(p.exterior.coords)]
            + [{"c": [40, 20, 40, 110]}, {"c": [220, 40, 230, 40]}],
        )
    )
    geometry = session.geometry()
    cells = session.analysis().cells
    ids = boundary_members(geometry, cells)
    group = SelectionGroup.create("Complete rooms").assign(ids)
    selected = tuple((p,) for p in cells) if separate else (cells,)
    if changed == "missing":
        group = group.assign((geometry.lineage[0].id,), False)
    elif changed == "branch":
        group = group.assign((geometry.lineage[-1].id,))
    elif changed == "extended":
        geometry = move_vertex(geometry, (220, 40), (200, 20))
        group = group.assign((geometry.lineage[-1].id,))
    elif changed == "other-cell":
        selected = (
            tuple(s for s in selected if s[0].centroid.x < 100)
            if separate
            else (tuple(p for p in cells if p.centroid.x < 100),)
        )
    expected = group if changed == "none" else None
    assert matching_export_groups(geometry, (group,), selected) == (expected,) * len(selected)


def test_export_group_match_retains_contact_tolerance_for_angled_noded_cells(pair_factory):
    a, b = (25.1232, 15.7731), (260.3927, 115.2221)
    corner = (60.2481, 180.3419)
    t = 0.575
    contact = tuple(a[i] + (b[i] - a[i]) * t for i in (0, 1))
    source = pair_factory(
        size=(300, 220),
        walls=[{"c": [*a, *b]}, {"c": [*a, *corner]}, {"c": [*corner, *contact]}],
    )
    session = Session(source)
    cells = session.analysis().cells
    assert len(cells) == 1
    # The original line extends beyond the cell. Such a group is deliberately not exact.
    group = SelectionGroup.create("Whole edge").assign(r.id for r in session.geometry().lineage)
    assert matching_export_groups(session.geometry(), (group,), (cells,)) == (None,)
    # Both cells cover the diagonal's full length despite projection arithmetic noise.
    source = pair_factory(
        size=(300, 220),
        walls=[
            {"c": [*a, *b]},
            {"c": [*a, *corner]},
            {"c": [*corner, *b]},
            {"c": [*corner, *contact]},
        ],
    )
    session = Session(source)
    assert len(session.analysis().cells) == 2
    group = SelectionGroup.create("Triangle").assign(r.id for r in session.geometry().lineage)
    assert matching_export_groups(session.geometry(), (group,), (session.analysis().cells,)) == (
        group,
    )


def test_region_membership_uses_whole_boundary_not_crossing_lines(pair_factory):
    geometry = Session(
        pair_factory(
            walls=[
                {"c": c}
                for c in (
                    [10, 20, 60, 20],
                    [60, 20, 60, 270],
                    [60, 270, 10, 270],
                    [10, 270, 10, 20],
                    [0, 100, 70, 100],
                )
            ]
        )
    ).geometry()
    polygon = box(10, 20, 60, 270)
    members = boundary_members(geometry, (polygon,))
    assert members == {r.id for r in geometry.lineage[:4]}
    assert grouped_regions(geometry, members, (polygon,)) == (0,)
    assert not grouped_regions(geometry, members - {geometry.lineage[0].id}, (polygon,))


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", ""),
        ("name", " x "),
        ("name", "x" * 81),
        ("name", "x\n"),
        ("color", "red"),
        ("color", "#000000ff"),
        ("id", "unsafe"),
        ("lines", [1]),
        ("lines", ["x", "x"]),
        ("excluded", None),
        ("priority", True),
        ("priority", -1),
        ("priority", 1_000_000_001),
    ],
)
def test_group_archive_fields_are_strict(field, value):
    encoded = SelectionGroup.create("Room").encode()
    encoded[field] = value
    with pytest.raises(ValueError):
        _load_ui({"groups": [encoded]})


def test_archive_defaults_duplicates_overlap_and_active_validation():
    group = SelectionGroup.create("Room")
    assert _load_ui({})["groups"] == []
    for value in ([group.encode()] * 2, [{**group.encode(), "lines": ["x"], "excluded": ["x"]}]):
        with pytest.raises(ValueError):
            decode_groups(value)
    with pytest.raises(ValueError):
        _load_ui({"active_group": "unknown"})


def test_per_dataset_archive_dirty_state_and_component_replacement(pair_factory, tmp_path):
    session = Session(pair_factory())
    catalog = DatasetCatalog(session)
    before = catalog.state()
    group = SelectionGroup.create("Room").assign((session.geometry().lineage[0].id,))
    catalog.current.ui.update(groups=[group.encode()], active_group=group.id)
    assert catalog.state() != before
    second = catalog.create("Empty")
    assert second.ui["groups"] == [] and second.ui["active_group"] is None
    path = tmp_path / "groups.dale"
    save_project(session, path, catalog.current.ui, catalog=catalog)
    with load_project(path) as loaded:
        assert decode_groups(loaded.catalog.current.ui["groups"]) == (group,)
        assert loaded.catalog.views[second.id].ui["groups"] == []
    original = repaired_json_bytes(session)
    assert b"group-" not in original
    catalog.replace_component(catalog.base_key, "json")
    assert catalog.current.ui["groups"] == []


def test_compact_blocks_outside_click_toggle_drag_and_confirm_delete(
    window, pair_factory, monkeypatch
):
    _, ids = scene(window, pair_factory)
    QTest.mouseClick(window.group_manager_button, Qt.MouseButton.LeftButton)
    manager = window.group_manager
    assert manager.isVisible() and window.group_manager_button.isChecked()
    assert not manager.findChildren(QDialogButtonBox)
    assert manager.new_button.text() == "+"
    QTest.mouseClick(manager.new_button, Qt.MouseButton.LeftButton)
    group = window.selection_groups()[0]
    controls = manager.row_controls[group.id]
    assert all(c.parentWidget() is controls[0].parentWidget() for c in controls)
    assert not controls[2].isEnabled()
    window.view.figure_line_ids = ids
    window.update_map_info()
    assert manager.row_controls[group.id][2].isEnabled()
    QTest.mouseClick(manager.row_controls[group.id][2], Qt.MouseButton.LeftButton)
    assert window.resolved_group_members(group.id) == set(ids)
    QTest.mouseClick(window.view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(5, 400))
    assert manager.isVisible() and window.group_manager_button.isChecked()
    manager.constrain_position(QPoint(50, 80))
    camera = window.view.camera_center()
    QTest.mousePress(manager.header, Qt.MouseButton.LeftButton, pos=QPoint(15, 10))
    QTest.mouseMove(manager.header, QPoint(-32, -66))
    QTest.mouseRelease(manager.header, Qt.MouseButton.LeftButton, pos=QPoint(-32, -66))
    assert viewport_position(manager) == QPoint(0, 0)
    assert window.view.camera_center() == camera
    manager.constrain_position(QPoint(10000, 10000))
    assert viewport_position(manager).x() + manager.width() == window.view.viewport().width()
    monkeypatch.setattr(window, "question", lambda *args: QMessageBox.StandardButton.No)
    window.delete_selection_group(group.id)
    assert len(window.selection_groups()) == 1
    monkeypatch.setattr(window, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.delete_selection_group(group.id)
    assert not window.selection_groups() and len(window.view.session.geometry().lineage) == 4
    QTest.mouseClick(manager.close_button, Qt.MouseButton.LeftButton)
    assert not manager.isVisible() and not window.group_manager_button.isChecked()
    QTest.mouseClick(window.group_manager_button, Qt.MouseButton.LeftButton)
    QTest.mouseClick(window.group_manager_button, Qt.MouseButton.LeftButton)
    assert not manager.isVisible()


def test_multiple_groups_color_priority_selection_fill_and_native_safety(window, pair_factory):
    source, ids = scene(window, pair_factory)
    original = repaired_json_bytes(window.view.session)
    pixels = source.image_path.read_bytes()
    window.toggle_group_manager()
    window.group_manager.constrain_position(QPoint(400, 20))
    window.create_selection_group()
    first = window.selection_groups()[0].id
    window.update_selection_group(first, color="#cc3355")
    window.view.figure_line_ids = ids
    window.assign_selection_group(first, True)
    window.create_selection_group()
    second = window.selection_groups()[1].id
    window.update_selection_group(second, color="#55aa22")
    window.assign_selection_group(second, True)
    assert all(window.resolved_group_members(i) == set(ids) for i in (first, second))
    window.select_selection_group(first)
    assert {c for _, c in window.group_overlay()[0]} == {"#cc3355"}
    window.select_selection_group(None)
    assert {c for _, c in window.group_overlay()[0]} == {"#55aa22"}
    window.activate_mode("Select regions")
    assert window.selection_groups() == ()
    window.create_selection_group()
    region_group = window.selection_groups()[0].id
    window.update_selection_group(region_group, color="#cc3355")
    window.selected_regions = (0,)
    window.update_map_info()
    window.assign_selection_group(region_group, True)
    window.select_selection_group(region_group)
    assert len(window.selected_regions) == 1
    assert {c for _, c in window.group_overlay()[1]} == {"#cc3355"}
    window.view.setTransform(QTransform.fromScale(2, 2))
    window.view.centerOn(35, 145)
    QApplication.processEvents()
    sample = window.view.mapFromScene(35, 130)
    assert window.view.viewport().grab().toImage().pixelColor(sample).name() == "#cc3355"
    window.group_manager.hide()
    assert window.group_overlay() == ((), ())
    assert window.view.viewport().grab().toImage().pixelColor(sample).name() != "#cc3355"
    assert repaired_json_bytes(window.view.session) == original
    assert source.image_path.read_bytes() == pixels
    assert not window.view.session.operations


def test_native_double_click_toggles_complete_contour_and_retains_other_lines(window, pair_factory):
    _, ids = scene(window, pair_factory)
    view = window.view
    view.figure_line_ids = ids
    window.update_map_info()
    point = view.mapFromScene(35, 20)
    for expected in (set(), set(ids), set()):
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
        assert set(view.figure_line_ids) == expected
    assert not view.session.operations


def test_group_only_empty_project_saves_without_source_assets(window, tmp_path):
    assert window.catalog is None and window.view.session is None
    window.toggle_group_manager()
    QTest.mouseClick(window.group_manager.new_button, Qt.MouseButton.LeftButton)
    assert len(window.selection_groups()) == 1
    assert window.view.session is window.catalog.current.session
    path = tmp_path / "group-only.dale"
    save_project(window.view.session, path, window.project_ui_state(), catalog=window.catalog)
    with load_project(path) as loaded:
        assert loaded.ui_state["groups"] == [window.selection_groups()[0].encode()]
        assert not loaded.session.source.json_bytes and not loaded.session.source.image_path


def test_project_save_suggests_stem_and_appends_extension(
    window, pair_factory, tmp_path, monkeypatch
):
    source = pair_factory()
    assert window.load_sources(source.image_path, source.json_path)

    def choose(parent, title, initial, file_filter):
        assert not initial.endswith(".dale")
        return str(tmp_path / "saved-work"), file_filter

    monkeypatch.setattr("dale.ui.QFileDialog.getSaveFileName", choose)
    assert window.save_project_file()
    assert window.project_path == tmp_path / "saved-work.dale"
    assert window.save_project_file(save_as=True)


def test_existing_unscoped_groups_belong_only_to_regions():
    group = SelectionGroup.create("Existing").assign(("wall",))
    state = group_ui_state({"groups": [group.encode()], "active_group": group.id})
    assert state["groups"] == [group.encode()]
    assert state["group_sections"] == {group.id: "regions"}
    assert state["section_active_groups"] == {
        "geometry": None,
        "figures": None,
        "regions": group.id,
        "pixels": None,
    }
    assert group_ui_state(state) == state


@pytest.mark.parametrize(
    "field,value",
    [
        ("group_sections", []),
        ("group_sections", {"unknown": "regions"}),
        ("group_sections", {"GROUP": "unknown"}),
        ("group_sections", {"GROUP": None}),
        ("group_sections", {"GROUP": ["regions"]}),
        ("section_active_groups", []),
        ("section_active_groups", {"unknown": None}),
        ("section_active_groups", {"regions": "unknown"}),
        ("section_active_groups", {"geometry": "GROUP"}),
        ("section_active_groups", {"regions": []}),
    ],
)
def test_scoped_group_metadata_validation(field, value):
    group = SelectionGroup.create("Room")
    if isinstance(value, dict):
        value = {
            group.id if k == "GROUP" else k: group.id if v == "GROUP" else v
            for k, v in value.items()
        }
    with pytest.raises(ValueError):
        _load_ui({"groups": [group.encode()], field: value})


def test_sections_have_independent_group_lists_members_colors_and_active_choice(
    window,
    pair_factory,
    monkeypatch,
    tmp_path,
):
    source, ids = scene(window, pair_factory)
    native, image = repaired_json_bytes(window.view.session), source.image_path.read_bytes()
    window.toggle_group_manager()
    modes = {
        "geometry": "Edit points",
        "figures": "Select figures",
        "regions": "Select regions",
        "pixels": "Select raster regions",
    }
    colors = ("#cc3355", "#55aa22", "#2255cc", "#bb77aa")
    expected = {}
    for (section, mode), color in zip(modes.items(), colors, strict=True):
        window.activate_mode(mode)
        assert window.selection_groups() == ()
        assert not window.group_manager.row_controls
        assert window.active_selection_group() is None
        window.create_selection_group()
        group = window.selection_groups()[0]
        window.update_selection_group(group.id, name="Same name", color=color)
        if section == "geometry":
            window.view.contour_line_ids = ids[:1]
        elif section == "figures":
            window.view.figure_line_ids = ids[:2]
        else:
            window.selected_regions = (0,)
            window.update_map_info()
        window.assign_selection_group(group.id, True)
        expected[section] = (
            window.selection_groups()[0],
            frozenset(
                ids[:1] if section == "geometry" else ids[:2] if section == "figures" else ids
            ),
        )
    for section, mode in modes.items():
        window.activate_mode(mode)
        group, members = expected[section]
        assert window.selection_groups() == (group,)
        assert window.active_selection_group() == group.id
        assert set(window.group_manager.row_controls) == {group.id}
        assert window.group_control.count() == 2
        assert window.group_manager.title.text().endswith(window.tool_set_actions[section].text())
        window.select_selection_group(group.id)
        assert window.resolved_group_members(group.id) == members
        assert {c for _, c in window.group_overlay()[0]} == {group.color}
        foreign = next(g.id for key, (g, _) in expected.items() if key != section)
        window.select_selection_group(foreign)
        assert window.active_selection_group() == group.id
        window.select_selection_group(None)
        assert window.active_selection_group() is None
        window.select_selection_group(group.id)
    path = tmp_path / "scoped-groups.dale"
    state = window.project_ui_state()
    save_project(window.view.session, path, state, catalog=window.catalog)
    with load_project(path) as loaded:
        assert loaded.ui_state["group_sections"] == state["group_sections"]
        assert loaded.ui_state["section_active_groups"] == state["section_active_groups"]
        assert len(loaded.ui_state["groups"]) == 4
    window.activate_mode("Select figures")
    removed = expected["figures"][0].id
    monkeypatch.setattr(window, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.delete_selection_group(removed)
    assert not window.selection_groups()
    for section in ("geometry", "regions", "pixels"):
        window.activate_mode(modes[section])
        assert window.selection_groups() == (expected[section][0],)
        assert window.active_selection_group() == expected[section][0].id
    assert repaired_json_bytes(window.view.session) == native
    assert source.image_path.read_bytes() == image
    assert not window.view.session.operations


def test_scoped_groups_survive_capture_dataset_switch_and_reopen(window, pair_factory, tmp_path):
    scene(window, pair_factory)
    window.activate_mode("Select regions")
    window.create_selection_group()
    first = window.selection_groups()[0]
    window.activate_mode("Select figures")
    window.create_selection_group()
    second = window.selection_groups()[0]
    window.catalog.capture(window.project_ui_state())
    original = window.catalog.active_key
    other = window.catalog.create("Other")
    assert other.ui["group_sections"] == {} and other.ui["section_active_groups"] == {}
    window.catalog.activate(other.id)
    window.show_catalog_view(other, load_preview(other.session.source), False)
    assert not window.all_selection_groups()
    window.activate_mode("Select regions")
    window.create_selection_group()
    third = window.selection_groups()[0]
    window.catalog.capture(window.project_ui_state())
    window.catalog.activate(original)
    window.show_catalog_view(
        window.catalog.current, load_preview(window.catalog.current.session.source), True
    )
    window.activate_mode("Select regions")
    assert window.selection_groups() == (first,)
    window.activate_mode("Select figures")
    assert window.selection_groups() == (second,)
    path = tmp_path / "reopened.dale"
    window.project_path = path
    assert window.save_project_file()
    assert window.load_project_file(path)
    window.activate_mode("Select regions")
    assert window.selection_groups() == (first,)
    assert third.id not in {g.id for g in window.all_selection_groups()}


def test_section_metadata_dirty_detection_and_json_replacement(pair_factory):
    catalog = DatasetCatalog(Session(pair_factory()))
    group = SelectionGroup.create("Room")
    catalog.current.ui.update(groups=[group.encode()])
    before = catalog.state()
    catalog.current.ui["group_sections"] = {group.id: "figures"}
    assert catalog.state() != before
    catalog.current.ui["section_active_groups"] = {"figures": group.id}
    catalog.replace_component(catalog.base_key, "json")
    assert catalog.current.ui["groups"] == []
    assert catalog.current.ui["group_sections"] == {}
    assert catalog.current.ui["section_active_groups"] == {}


@pytest.mark.parametrize("kind", ["line", "rectangle", "circle", "contour_copy", "region_copy"])
@pytest.mark.parametrize("touching", [False, True])
def test_new_geometry_and_copies_never_acquire_existing_groups(pair_factory, kind, touching):
    from dale.editing import add_circle, add_line, add_rectangle

    session = Session(pair_factory(size=(700, 500)))
    original = session.geometry()
    ids = frozenset(r.id for r in original.lineage)
    group = SelectionGroup.create("Original").assign(ids)
    start = (60, 20) if touching else (200, 40)
    if kind == "line":
        edited = add_line(original, start, (start[0] + 70, start[1]))
    elif kind == "rectangle":
        edited = add_rectangle(original, start, (start[0] + 70, start[1] + 70))
    elif kind == "circle":
        edited = add_circle(original, (start[0] + 30, start[1]), 30)
    elif kind == "contour_copy":
        edited = copy_figures(original, ids).paste(original, 50 if touching else 200, 0)
    else:
        cells = session.analysis().cells
        edited = copy_regions(original, cells, cells).paste(original, 50 if touching else 200, 0)
    session.add(edited)
    members = group_members(group, edited)
    from shapely.geometry import LineString
    from shapely.ops import unary_union

    assert unary_union(
        [
            LineString(edge)
            for edge, record in zip(edited.walls, edited.lineage, strict=True)
            if record.id in members
        ]
    ).equals(unary_union([LineString(edge) for edge in original.walls]))
    new_ids = {r.id for r in edited.lineage if r.origin == "editor"} - ids
    assert new_ids and not members & new_ids
    second = SelectionGroup.create("New").assign(new_ids)
    assert group_members(second, edited) == new_ids
    assert group_members(group, edited) == members
    session.undo()
    assert group_members(group, session.geometry()) == ids
    assert not group_members(second, session.geometry())
    session.redo()
    assert group_members(group, session.geometry()) == members
    assert group_members(second, session.geometry()) == new_ids


def test_group_membership_tracks_edits_not_cell_indices_and_does_not_reappear_at_old_coordinates(
    window,
    pair_factory,
    tmp_path,
):
    from dale.editing import add_line, add_rectangle

    source, ids = scene(window, pair_factory)
    window.activate_mode("Select regions")
    window.selected_regions = (0,)
    window.update_map_info()
    window.create_selection_group()
    group = window.selection_groups()[0]
    window.assign_selection_group(group.id, True)
    before = window.view.session.geometry()
    moving, _ = plan_figure_transform(before, ids).apply(dx=200)
    window.view.session.add(moving)
    window.view.refresh(render_image=False)
    # Recreate the original shape as unrelated new lines, then subdivide the moved room.
    changed = add_rectangle(moving, (10, 20), (60, 270))
    changed = add_line(changed, (210, 100), (260, 100))
    window.view.session.add(changed)
    window.view.refresh(render_image=False)
    window.select_selection_group(group.id)
    assert all(p.bounds[0] >= 210 for p in window.view.region_polygons)
    assert window.resolved_group_members(group.id).isdisjoint(
        r.id
        for edge, r in zip(changed.walls, changed.lineage, strict=True)
        if max(p[0] for p in edge) < 100
    )
    path = tmp_path / "edited-groups.dale"
    save_project(window.view.session, path, window.project_ui_state(), catalog=window.catalog)
    with load_project(path) as loaded:
        assert group_members(
            window.selection_groups()[0], loaded.session.geometry()
        ) == window.resolved_group_members(group.id)


@pytest.mark.parametrize("delete_parent", [False, True])
def test_explicit_add_excludes_existing_parallel_copies_and_preserves_splits(
    pair_factory,
    delete_parent,
):
    from dale.selection_groups import assign_group

    session = Session(pair_factory())
    original = session.geometry()
    root = original.lineage[0]
    edge = tuple((x + 200, y) for x, y in original.walls[0])
    copied = LineRecord.child((root,), edge)
    parallel = GeometryEdit(
        (*original.walls, edge), lineage=(*original.lineage, copied), ancestry=original.lineage
    )
    session.add(parallel)
    group = assign_group(SelectionGroup.create("Original"), parallel, (root.id,))
    assert group_members(group, parallel) == {root.id}
    assert copied.id in group.excluded
    if delete_parent:
        session.add(GeometryEdit((edge,), lineage=(copied,), ancestry=parallel.lineage))
        assert not group_members(group, session.geometry())
    explicitly_added = assign_group(group, session.geometry(), (copied.id,))
    assert copied.id in group_members(explicitly_added, session.geometry())
    session.operations = []
    session.add(insert_vertex(original, hit_edge(original, (35, 20), 1)))
    assert len(group_members(group, session.geometry())) == 2


def test_existing_groups_unchanged_until_explicit_reassignment(window, pair_factory, tmp_path):
    source, ids = scene(window, pair_factory)
    original = window.view.session.geometry()
    root = original.lineage[0]
    edge = tuple((x + 200, y) for x, y in original.walls[0])
    copied = LineRecord.child((root,), edge)
    window.view.session.add(
        GeometryEdit(
            (*original.walls, edge), lineage=(*original.lineage, copied), ancestry=original.lineage
        )
    )
    existing = SelectionGroup.create("Existing").assign((root.id,))
    window.catalog.current.ui.update(
        groups=[existing.encode()],
        active_group=existing.id,
        group_sections={existing.id: "figures"},
        section_active_groups={},
    )
    window.view.refresh(render_image=False)
    assert window.all_selection_groups() == (existing,)
    assert window.project_ui_state()["groups"] == [existing.encode()]
    # A new group gets exactly the selected object through +, not its old parallel copy.
    window.store_selection_groups(())
    window.create_selection_group()
    group = window.selection_groups()[0]
    window.view.figure_line_ids = (root.id,)
    window.assign_selection_group(group.id, True)
    assert window.resolved_group_members(group.id) == {root.id}
    ui = window.project_ui_state()
    assert ui["groups"][0]["excluded"] == [copied.id]
    path = tmp_path / "explicit-members.dale"
    save_project(window.view.session, path, ui, catalog=window.catalog)
    with load_project(path) as loaded:
        stored = decode_groups(loaded.ui_state["groups"])[0]
        assert group_members(stored, loaded.session.geometry()) == {root.id}
    assert window.view.session.source.json_bytes == source.json_bytes


def test_reimported_deleted_line_gets_fresh_identity_and_requires_group_assignment(pair_factory):
    from dale.region_transform import delete_figures

    session = Session(pair_factory())
    before = session.geometry()
    removed = before.lineage[0].id
    group = SelectionGroup.create("Deleted member").assign((removed,))
    catalog = DatasetCatalog(session, {"groups": [group.encode()]})
    session.add(delete_figures(before, (removed,)))
    assert catalog.add_json(catalog.base_key, Session(session.source)) == 1
    geometry = session.geometry()
    assert removed not in {r.id for r in geometry.lineage}
    new = geometry.lineage[-1]
    assert new.origin == "editor" and removed in new.parents
    assert not group_members(group, geometry)
    assert group_members(group.assign((new.id,)), geometry) == {new.id}


@pytest.mark.parametrize("zoom", [1, 2])
@pytest.mark.parametrize(
    "selected,hover,show",
    [
        (False, False, True),
        (False, True, True),
        (True, False, True),
        (True, False, False),
    ],
)
def test_group_color_replaces_center_with_three_pixel_total_width(
    window,
    pair_factory,
    zoom,
    selected,
    hover,
    show,
):
    from dale.canvas import line_path

    scene(window, pair_factory)
    view = window.view
    ids = tuple(r.id for r in view.session.geometry().lineage)
    window.create_selection_group()
    group = window.selection_groups()[0]
    window.update_selection_group(group.id, color="#b276e2")
    view.figure_line_ids = ids
    window.assign_selection_group(group.id, True)
    view.figure_line_ids = ids if selected else ()
    view.show_walls = show
    view.setTransform(QTransform.fromScale(zoom, zoom))
    view.centerOn(35, 145)
    window.toggle_group_manager()
    window.group_manager.constrain_position(QPoint(400, 20))
    window.update_map_info()
    if hover:
        view.hover_path = line_path((((10, 20), (60, 20)),))
    else:
        view.hover_path.clear()
    QApplication.processEvents()
    point = view.mapFromScene(35, 20)
    pixels = view.viewport().grab().toImage()
    assert pixels.pixelColor(point).name() == "#b276e2"
    assert pixels.pixelColor(point + QPoint(0, -1)).name() in ("#000000", "#ffffff")
    assert pixels.pixelColor(point + QPoint(0, 1)).name() in ("#000000", "#ffffff")
    background = pixels.pixelColor(point + QPoint(0, -5)).name()
    assert pixels.pixelColor(point + QPoint(0, -2)).name() == background
    assert pixels.pixelColor(point + QPoint(0, 2)).name() == background
    window.group_manager.hide()
    if show or selected:
        assert view.viewport().grab().toImage().pixelColor(point).name() == "#58d9ec"


@pytest.mark.parametrize("ordinary_history", [False, True])
def test_appending_derived_contours_requires_explicit_group_assignment(
    pair_factory, ordinary_history
):
    session = Session(pair_factory())
    before = session.geometry()
    if ordinary_history:
        session.add(before)
    group = SelectionGroup.create("Original").assign((before.lineage[0].id,))
    catalog = DatasetCatalog(session, {"groups": [group.encode()]})
    incoming = Session(session.source)
    incoming.add(insert_vertex(before, hit_edge(before, (35, 20), 1)))
    assert catalog.add_json(catalog.base_key, incoming) == 2
    added = session.geometry().lineage[len(before.lineage) :]
    assert all(record.origin == "editor" for record in added)
    assert group_members(group, session.geometry()) == {before.lineage[0].id}


def _angled_group_geometry(angle=13, offset=(1234.56, 7890.12), size=(1200, 800)):
    from itertools import pairwise

    from shapely.affinity import rotate, translate

    width, height = size
    half = min(size) / 32
    positions = (
        (0, 0),
        (width, 0),
        (width, height),
        (0, height),
        (0, height / 2),
        (width, height / 2),
    )
    shapes = [
        box(0, 0, width, height),
        *(box(x - half, y - half, x + half, y + half) for x, y in positions),
    ]
    shapes = [translate(rotate(p, angle, origin=(width / 2, height / 2)), *offset) for p in shapes]
    return GeometryEdit(tuple(e for p in shapes for e in pairwise(p.exterior.coords)))


@pytest.mark.parametrize("angle", [0, 13, 31, 72])
@pytest.mark.parametrize("offset", [(0, 0), (1234.56, 7890.12), (1_000_000.125, -3_000_000.75)])
def test_every_rotated_closed_cell_is_groupable_after_numerical_noding(angle, offset):
    from dale.geometry import analyze_regions

    geometry = _angled_group_geometry(angle, offset)
    cells = analyze_regions(geometry.walls).cells
    assert len(cells) == 13
    for polygon in cells:
        identifiers = boundary_members(geometry, (polygon,))
        assert grouped_regions(geometry, identifiers, (polygon,)) == (0,)
    assert geometry == _angled_group_geometry(angle, offset)


def test_boundary_assignment_excludes_crossings_point_contacts_and_nearby_parallel_lines():
    geometry = GeometryEdit(
        (
            ((0, 0), (100, 0)),
            ((100, 0), (100, 100)),
            ((100, 100), (0, 100)),
            ((0, 100), (0, 0)),
            ((-10, 50), (110, 50)),
            ((100, 100), (130, 130)),
            ((100, 0), (130, 0)),
            ((0, -0.00001), (100, -0.00001)),
        )
    )
    identifiers = boundary_members(geometry, (box(0, 0, 100, 100),))
    assert identifiers == {r.id for r in geometry.lineage[:4]}
    assert grouped_regions(geometry, identifiers, (box(0, 0, 100, 100),)) == (0,)
    assert (
        grouped_regions(geometry, identifiers - {geometry.lineage[0].id}, (box(0, 0, 100, 100),))
        == ()
    )


def test_group_coverage_preserves_holes_and_rejects_real_boundary_gaps():
    from itertools import pairwise

    from shapely.geometry import Polygon

    polygon = Polygon(
        [(0, 0), (100, 0), (100, 100), (0, 100)], holes=[[(25, 25), (25, 75), (75, 75), (75, 25)]]
    )
    geometry = GeometryEdit(
        tuple(
            edge
            for ring in (polygon.exterior, *polygon.interiors)
            for edge in pairwise(ring.coords)
        )
    )
    ids = boundary_members(geometry, (polygon,))
    assert len(ids) == 8 and grouped_regions(geometry, ids, (polygon,)) == (0,)
    redundant = Polygon([(0, 0), (100, 0), (100, 0), (100, 100), (0, 100)])
    assert grouped_regions(geometry, ids, (redundant,)) == (0,)
    assert grouped_regions(geometry, ids - {geometry.lineage[4].id}, (polygon,)) == ()
    broken = GeometryEdit((((0, 0), (49.99999, 0)), ((50.00001, 0), (100, 0)), *geometry.walls[1:]))
    assert grouped_regions(broken, {r.id for r in broken.lineage}, (polygon,)) == ()


@pytest.mark.parametrize("mode", ["Select regions", "Select raster regions"])
def test_real_marquee_plus_colors_all_rotated_cells_including_largest(
    window,
    pair_factory,
    tmp_path,
    mode,
):
    geometry = _angled_group_geometry(31, (140.56, 160.12), (240, 160))
    source = pair_factory(size=(600, 500), walls=[{"c": [*a, *b]} for a, b in geometry.walls])
    assert window.load_sources(source.image_path, source.json_path)
    window.activate_mode(mode)
    view = window.view
    before = view.session.geometry()
    native = repaired_json_bytes(view.session)
    pixels = source.image_path.read_bytes()
    window.create_selection_group()
    group = window.selection_groups()[0]
    window.update_selection_group(group.id, color="#dcb54b")
    window.toggle_group_manager()
    window.group_manager.constrain_position(QPoint(10000, 10000))
    view.setTransform(QTransform())
    view.centerOn(300, 250)
    QApplication.processEvents()
    points = [p for edge in geometry.walls for p in edge]
    start = view.mapFromScene(min(p[0] for p in points) - 10, min(p[1] for p in points) - 10)
    end = view.mapFromScene(max(p[0] for p in points) + 10, max(p[1] for p in points) + 10)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(view.viewport(), end)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
    assert len(window.selected_regions) == len(window.regions) == 13
    largest = max(view.region_polygons, key=lambda p: p.area)
    sample = view.mapFromScene(*largest.representative_point().coords[0])
    assert view.viewport().grab().toImage().pixelColor(sample).name() != "#dcb54b"
    add = window.group_manager.row_controls[group.id][2]
    assert add.isEnabled()
    QTest.mouseClick(add, Qt.MouseButton.LeftButton)
    assert len(window.group_overlay()[1]) == 13
    assert view.viewport().grab().toImage().pixelColor(sample).name() == "#dcb54b"
    window.select_selection_group(group.id)
    assert len(window.selected_regions) == 13
    view.show_walls = False
    assert view.viewport().grab().toImage().pixelColor(sample).name() == "#dcb54b"
    path = tmp_path / "angled-selection.dale"
    window.project_path = path
    assert window.save_project_file() and window.load_project_file(path)
    window.toggle_group_manager() if not window.group_manager.isVisible() else None
    assert len(window.selected_regions) == 13 and len(window.group_overlay()[1]) == 13
    assert window.view.session.geometry().lineage == before.lineage
    assert window.view.session.geometry().walls == before.walls
    assert repaired_json_bytes(window.view.session) == native
    assert source.image_path.read_bytes() == pixels
    assert all(isinstance(op, RasterSelectionEdit) for op in window.view.session.operations)
    assert len(window.view.session.operations) == (1 if mode == "Select raster regions" else 0)
