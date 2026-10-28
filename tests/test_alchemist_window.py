"""Selection scope, temporary isolation and transaction boundaries in the slice window."""

from dataclasses import replace

import pytest
from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from test_alchemist import sample as sample
from test_alchemist_interaction import editor as editor
from test_alchemist_slices import object_edges
from test_alchemist_slices import projected as projected

from dale.alchemist import memberships
from dale.alchemist_slices import object_value
from dale.project_io import load_project, save_project


@pytest.fixture
def panel(editor, projected):
    editor.view.session = projected[0]
    editor.show()
    editor.refresh()
    editor.view.figure_line_ids = projected[0].alchemist.objects[0].roots
    editor.toggle_slice_window(True)
    QApplication.processEvents()
    return editor.slice_window


def test_window_selection_scope_history_and_reopen(panel, tmp_path):
    window, session = panel.owner, panel.session
    obj, other = session.alchemist.objects[:2]
    old_other = object_edges(session, other)
    window.view.figure_line_ids = obj.roots
    window.update_map_info()
    start = len(session.operations)
    for value in (3, 6, 8):
        panel.lower.setValue(value)
        panel.flush()
    assert len(session.operations) == start + 1
    assert object_value(session, obj) == (8, 10, False)
    assert object_edges(session, other) == old_other
    selected = window.view.figure_line_ids
    assert selected
    panel.hide()
    assert window.view.figure_line_ids == selected
    assert window.view.alchemist_isolated_category is None
    path = tmp_path / "window.dale"
    save_project(session, path, {"figure_lines": list(selected)})
    with load_project(path) as loaded:
        assert set(loaded.ui_state["figure_lines"]) == set(selected)
        assert object_value(loaded.session, obj) == (8, 10, False)
        loaded.session.undo()
        assert loaded.session.geometry().walls == session.geometry().walls
        assert not loaded.session.future


@pytest.mark.parametrize("selection_change", ["add", "remove", "clear", "clear_reselect"])
@pytest.mark.parametrize("pending", [False, True])
def test_manager_after_slice_edits_and_selection_changes(panel, selection_change, pending):
    from dale.dataset_manager import DatasetManager
    from dale.datasets import DatasetCatalog

    window, session = panel.owner, panel.session
    window.catalog = DatasetCatalog(session)
    first, second = session.alchemist.objects[:2]
    panel.lower.setValue(6)
    if pending:
        panel.apply()
    else:
        panel.flush()
    if selection_change == "add":
        window.view.figure_line_ids = (*window.view.figure_line_ids, *second.roots)
        window.update_map_info()
    elif selection_change == "remove":
        panel.flush()
        panel.choose_all()
        owners = memberships(session.alchemist, session.geometry())
        window.view.figure_line_ids = tuple(
            r.id
            for r, own in zip(session.geometry().lineage, owners, strict=True)
            if first.id in own
        )
        window.update_map_info()
    else:
        window.clear_selection()
        assert not panel.isVisible()
        if selection_change == "clear_reselect":
            window.view.figure_line_ids = second.roots
            window.update_map_info()
            window.toggle_slice_window(True)
            panel.lower.setValue(4)
    shown = []

    def dismiss():
        dialog = QApplication.activeModalWidget()
        if isinstance(dialog, DatasetManager):
            shown.append(True)
            dialog.reject()

    timer = QTimer()
    timer.timeout.connect(dismiss)
    timer.start(5)
    try:
        window.manager_button.click()
    finally:
        timer.stop()
    assert shown
    assert not panel.busy and not panel.dirty
    assert window.catalog.current.session is session


def test_slice_window_height_stops_at_content(panel):
    panel.owner.resize(1600, 1400)
    QApplication.processEvents()
    panel.set_user_size(QSize(460, 1300))
    QApplication.processEvents()
    assert panel.height() == panel.maximumHeight() < 1100
    bottom = panel.cleanup.mapTo(panel, QPoint(0, panel.cleanup.height())).y()
    assert 0 < panel.height() - bottom < 65


def test_real_map_click_deselection_reslicing_and_manager(panel):
    from dale.dataset_manager import DatasetManager
    from dale.datasets import DatasetCatalog

    window, session = panel.owner, panel.session
    window.catalog = DatasetCatalog(session)
    window.activate_mode("Select figures", prompt=False)
    panel.constrain_position(QPoint(10000, 0))
    panel.lower.setValue(4)
    panel.flush()
    window.view.fit_map()
    geometry = window.view.editing_geometry()
    selected = set(window.view.figure_line_ids)
    indices = [
        next(i for i, r in enumerate(geometry.lineage) if (r.id in selected) == flag)
        for flag in (True, False)
    ]
    for index in indices:
        a, b = geometry.walls[index]
        position = window.view.mapFromScene((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        QTest.mouseClick(window.view.viewport(), Qt.MouseButton.LeftButton, pos=position)
        QApplication.processEvents()
        assert not window.view.active_gesture
    panel.lower.setValue(7)
    panel.flush()
    shown = []

    def dismiss():
        dialog = QApplication.activeModalWidget()
        if isinstance(dialog, DatasetManager):
            shown.append(True)
            dialog.reject()

    timer = QTimer()
    timer.timeout.connect(dismiss)
    timer.start(5)
    try:
        QTest.mouseClick(window.manager_button, Qt.MouseButton.LeftButton)
    finally:
        timer.stop()
    assert shown


def test_switch_tab_deselects_hidden_types_and_close_restores_toggles(panel):
    window, session = panel.owner, panel.session
    objects = session.alchemist.objects
    session.alchemist = replace(
        session.alchemist, objects=(replace(objects[0], category="rock"), *objects[1:])
    )
    panel.choose_all()
    assert window.view.figure_line_ids
    settings = session.alchemist.settings
    panel.tabs.setCurrentIndex(3)
    assert not window.view.figure_line_ids
    assert not panel.isVisible()
    assert window.view.alchemist_isolated_category is None
    window.view.figure_line_ids = objects[0].roots
    window.toggle_slice_window(True)
    selected = window.view.figure_line_ids
    assert selected
    visible_owners = memberships(session.alchemist, window.view.editing_geometry())
    assert all(own == frozenset((objects[0].id,)) for own in visible_owners)
    panel.hide()
    assert session.alchemist.settings == settings
    assert window.view.figure_line_ids == selected
    assert len(window.view.editing_geometry().lineage) > len(selected)


def test_empty_selection_blocks_open_and_deselection_closes_with_one_undo(panel):
    window, session = panel.owner, panel.session
    panel.lower.setValue(6)
    panel.flush()
    applied = session.geometry()
    count = len(session.operations)
    window.clear_selection()
    assert not panel.isVisible() and not window.alchemist_window_action.isChecked()
    assert window.view.alchemist_isolated_category is None
    assert not window.alchemist_window_action.isEnabled()
    window.toggle_slice_window(True)
    assert not panel.isVisible()
    assert session.geometry() == applied and len(session.operations) == count


def test_close_keeps_selected_category_visible_if_its_switch_was_off(panel):
    session = panel.session
    session.alchemist = replace(
        session.alchemist, settings=((False, 0), (False, 0), (False, 0), (True, 0))
    )
    panel.choose_all()
    selected = panel.owner.view.figure_line_ids
    assert selected
    panel.hide()
    assert panel.owner.view.figure_line_ids == selected
    assert session.alchemist.settings == ((False, 0), (True, 0), (False, 0), (True, 0))


def test_pending_slice_finishes_before_discard_check_and_dataset_capture(panel, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from dale.datasets import DatasetCatalog
    from dale.ui import MainWindow

    window, session = panel.owner, panel.session
    window.catalog = DatasetCatalog(session)
    panel.choose_all()
    window.saved_state = window.document_state()
    questions = []

    def cancel(*args):
        questions.append(args)
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(window, "question", cancel)
    panel.lower.setValue(7)
    assert not MainWindow.can_discard(window)
    assert questions and not panel.busy and not panel.dirty
    panel.lower.setValue(4)
    settings = window.project_ui_state()
    assert not panel.busy and not panel.dirty
    assert set(settings["figure_lines"]) == set(window.view.figure_line_ids)
    assert all(object_value(session, obj)[0] == 4 for obj in session.alchemist.objects)


def test_selection_change_starts_a_new_undo_segment(panel):
    window, session = panel.owner, panel.session
    one, two = session.alchemist.objects[:2]
    window.view.figure_line_ids = one.roots
    window.update_map_info()
    start = len(session.operations)
    panel.lower.setValue(7)
    panel.flush()
    window.view.figure_line_ids = two.roots
    window.update_map_info()
    panel.lower.setValue(4)
    panel.flush()
    panel.lower.setValue(6)
    panel.flush()
    assert len(session.operations) == start + 2
    session.undo()
    assert object_value(session, two)[0] == -1
    assert object_value(session, one)[0] == 7
    session.undo()
    assert object_value(session, one)[0] == -1


def test_panel_docks_and_category_popup_contains_global_filters_and_json(panel):
    panel.constrain_position(QPoint(3, 4))
    assert panel.dock_x == panel.dock_y == -1
    panel.owner.show_alchemist_category_settings("tree")
    popup = panel.owner.tool_settings_popup
    assert hasattr(popup, "wall_export")
    assert hasattr(popup, "alchemist_minimum") and hasattr(popup, "alchemist_height")
    assert not hasattr(popup, "alchemist_scale")
    assert not hasattr(popup, "alchemist_slice")
    popup.reject()


def test_category_filters_without_selection_cancel_apply_and_restore(editor, tmp_path):
    window, session = editor, editor.view.session
    small, large = session.alchemist.objects
    session.alchemist = replace(
        session.alchemist,
        objects=(
            replace(small, original_size=0.5, original_height_ft=2),
            replace(large, original_size=2, original_height_ft=8),
        ),
    )
    window.view.figure_line_ids = ()
    window.refresh()
    before, count = session.geometry(), len(session.operations)
    window.show_alchemist_category_settings("tree")
    popup = window.tool_settings_popup
    popup.alchemist_minimum.setValue(1)
    popup.alchemist_height.setValue(4)
    popup.reject()
    assert session.alchemist.settings[1][1] == 0
    assert session.alchemist.minimum_heights_ft[1] == 0
    window.show_alchemist_category_settings("tree")
    popup = window.tool_settings_popup
    popup.alchemist_minimum.setValue(1)
    popup.alchemist_height.setValue(4)
    popup.accept()
    assert not window.view.figure_line_ids
    assert {r.id for r in window.view.editing_geometry().lineage} == set(large.roots)
    assert session.geometry() == before and len(session.operations) == count
    path = tmp_path / "filters.dale"
    save_project(session, path)
    with load_project(path) as loaded:
        assert loaded.session.alchemist.settings[1][1] == 1
        assert loaded.session.alchemist.minimum_heights_ft[1] == 4
    window.show_alchemist_category_settings("tree")
    popup = window.tool_settings_popup
    popup.alchemist_minimum.setValue(0)
    popup.alchemist_height.setValue(0)
    popup.accept()
    assert {r.id for r in window.view.editing_geometry().lineage} == set(small.roots + large.roots)
    assert session.geometry() == before


def test_slice_edits_keep_category_filters_and_hidden_selection_is_cleared(panel):
    session, window = panel.session, panel.owner
    panel.choose_all()
    window.show_alchemist_category_settings("tree")
    popup = window.tool_settings_popup
    popup.alchemist_minimum.setValue(0.1)
    popup.accept()
    assert panel.isVisible()
    panel.lower.setValue(6)
    panel.flush()
    assert session.alchemist.settings[1][1] == 0.1
    window.show_alchemist_category_settings("tree")
    popup = window.tool_settings_popup
    popup.alchemist_minimum.setValue(10000)
    popup.accept()
    assert not window.view.figure_line_ids and not panel.isVisible()
    assert session.alchemist.settings[1][1] == 10000


def test_latest_worker_values_coalesce_and_stale_result_is_rejected(panel):
    from concurrent.futures import Future

    panel.choose_all()
    session = panel.session
    count = len(session.operations)
    panel.lower.setValue(2)
    panel.apply()
    panel.lower.setValue(8)
    for _ in range(200):
        QTest.qWait(10)
        if not panel.busy and not panel.dirty:
            break
    assert not panel.busy and not panel.dirty
    assert len(session.operations) == count + 1
    assert all(object_value(session, obj)[0] == 8 for obj in session.alchemist.objects)
    panel.lower.setValue(6)
    panel.apply()
    panel.future.result()
    result = panel.future.result()
    late = Future()
    late.set_result(result)
    panel.future = late
    unrelated = replace(
        session.geometry(),
        walls=tuple(tuple((x + 15, y) for x, y in edge) for edge in session.geometry().walls),
    )
    session.add(unrelated)
    panel.finish()
    assert session.operations[-1] is unrelated


def test_slice_field_wheel_never_transforms_map(panel):
    from test_alchemist_slices import send_wheel

    panel.choose_all()
    panel.owner.activate_mode("Scale figures")
    before = panel.session.geometry()
    scale_step = panel.owner.figure_scale_control.value()
    send_wheel(panel.owner, panel.lower)
    assert panel.session.geometry() is before
    assert panel.owner.figure_scale_control.value() == scale_step
    panel.flush()


def test_range_union_and_per_object_choices_roundtrip(panel, tmp_path):
    from shapely import from_wkb, union_all
    from shapely.ops import polygonize

    session = panel.session
    panel.choose_all()
    panel.lower.setValue(2)
    panel.upper.setValue(7)
    panel.between.setChecked(True)
    panel.flush()
    obj = session.alchemist.objects[0]
    assert object_value(session, obj) == (2, 7, True)
    rings = list(polygonize(object_edges(session, obj)))
    a, b, c, d, _, _ = obj.projection[1]
    profiles = dict(session.alchemist.profiles)[obj.block_id]
    expected = union_all([from_wkb(raw) for raw in profiles[2:7]]).area * abs(a * d - b * c)
    assert sum(p.area for p in rings) == pytest.approx(expected, rel=0.02)
    panel.hide()
    path = tmp_path / "range.dale"
    save_project(session, path)
    with load_project(path) as loaded:
        assert object_value(loaded.session, obj) == (2, 7, True)
        assert loaded.session.geometry().walls == session.geometry().walls


def test_long_calculation_displays_progress(panel, monkeypatch):
    from threading import Event

    release = Event()

    def slow(*args, progress, **kwargs):
        progress(1, 2)
        assert release.wait(5)
        return None

    monkeypatch.setattr("dale.alchemist_window.change_slice", slow)
    panel.choose_all()
    panel.lower.setValue(4)
    panel.apply()
    try:
        QTest.qWait(400)
        assert panel.progress.isVisible()
        assert "1/2" in panel.progress.format()
    finally:
        release.set()
        panel.flush()
    assert not panel.progress.isVisible()


def test_panel_scale_preserves_existing_closure_and_reversed_change_is_noop(panel):
    from dale.provenance import geometry_edges
    from dale.session import Closure

    session = panel.session
    session.add(Closure(((10, 10), (20, 10), (20, 20), (10, 10))))
    panel.owner.refresh()
    panel.choose_all()
    before = session.geometry()
    edges = geometry_edges(before.walls, before.closures)
    count = len(session.operations)
    panel.scale.setValue(150)
    panel.flush()
    after = session.geometry()
    assert len(after.walls) == len(edges)
    assert set(before.lineage) == set(after.lineage)
    regular = {
        r.id: edge
        for r, edge, own in zip(
            before.lineage, edges, memberships(session.alchemist, before), strict=True
        )
        if not own
    }
    assert all(
        edge == regular[r.id]
        for r, edge in zip(after.lineage, after.walls, strict=True)
        if r.id in regular
    )
    panel.scale.setValue(100)
    panel.flush()
    assert len(session.operations) == count
    assert session.geometry() == before
    assert session.geometry().lineage == before.lineage
    assert session.geometry().ancestry == before.ancestry


@pytest.mark.parametrize("size", [(320, 260), (180, 500), (600, 180)])
def test_illustration_marks_follow_model_extrema(panel, size):
    picture = panel.picture
    picture.setMinimumSize(1, 1)
    picture.setMaximumSize(1000, 1000)
    picture.resize(*size)
    for category in ("tree", "bush", "rock", "wall"):
        picture.category = category
        model = picture.model_rect()
        assert picture.level_y(0) == pytest.approx(model.bottom())
        assert picture.level_y(10) == pytest.approx(model.top())
        assert model.top() > 0 and model.bottom() < picture.height()


def test_compact_slider_labels_order_default_and_range_picture(panel):
    from PySide6.QtWidgets import QSlider, QSpinBox

    panel.choose_all()
    panel.owner.set_language("ru", persist=False)
    QApplication.processEvents()
    assert panel.upper.value() == 10
    assert panel.upper_box.y() < panel.lower_box.y()
    assert all(
        isinstance(value, QSlider)
        for value in (panel.upper, panel.lower, panel.scale, panel.complexity)
    )
    assert not panel.fields.findChildren(QSpinBox)
    assert not hasattr(panel, "minimum") and not hasattr(panel, "minimum_height")
    assert panel.upper_box.maximumWidth() == 320
    assert panel.between.text() == "Диапазон нарезки"
    assert panel.value_labels[panel.upper].text() == "10"
    assert panel.picture.minimumHeight() == 270
    panel.picture.resize(440, 270)
    assert panel.picture.model_rect().top() == pytest.approx(12)
    assert panel.picture.height() - panel.picture.model_rect().bottom() == pytest.approx(12)
    panel.picture.value, panel.picture.upper = 2, 7
    panel.picture.between = False
    plain = panel.picture.grab().toImage()
    panel.picture.between = True
    shaded = panel.picture.grab().toImage()
    point = QPoint(panel.picture.width() - 20, round(panel.picture.level_y(4.5)))
    assert shaded.pixelColor(point).blue() > plain.pixelColor(point).blue()
    assert panel.picture.range_rect().top() == pytest.approx(panel.picture.level_y(7))
    assert panel.picture.range_rect().bottom() == pytest.approx(panel.picture.level_y(2))


def test_slider_drag_updates_label_without_starting_calculation(panel):
    panel.choose_all()
    before = panel.session.geometry()
    operations = len(panel.session.operations)
    slider = panel.lower
    slider.setSliderDown(True)
    slider.setSliderPosition(6)
    QTest.qWait(400)
    assert panel.value_labels[slider].text() == "6"
    assert not panel.dirty and panel.future is None
    assert panel.session.geometry() == before
    assert len(panel.session.operations) == operations
    slider.setSliderDown(False)
    panel.flush()
    assert object_value(panel.session, panel.session.alchemist.objects[0])[0] == 6
    assert len(panel.session.operations) == operations + 1


@pytest.mark.parametrize("docked", [False, True])
def test_window_geometry_survives_new_panel(panel, docked):
    from PySide6.QtCore import QSize

    from dale.alchemist_window import SliceWindow
    from dale.preferences import load_slice_window_geometry

    owner = panel.owner
    owner.resize(1450, 1000)
    QApplication.processEvents()
    panel.set_user_size(QSize(380, 600))
    point = QPoint(95, 65)
    if docked:
        point = QPoint(panel.map_viewport.width(), panel.map_viewport.height())
    panel.constrain_position(point)
    expected = (
        panel.viewport_anchor.x(),
        panel.viewport_anchor.y(),
        panel.requested_size.width(),
        panel.requested_size.height(),
        panel.dock_x,
        panel.dock_y,
    )
    panel.hide()
    assert load_slice_window_geometry(owner.preferences_path) == expected
    replacement = SliceWindow(owner)
    try:
        replacement.show()
        QApplication.processEvents()
        assert replacement.viewport_anchor == QPoint(*expected[:2])
        assert replacement.requested_size == QSize(*expected[2:4])
        assert (replacement.dock_x, replacement.dock_y) == expected[4:]
        owner.resize(1024, 768)
        QApplication.processEvents()
        position = replacement.viewport_position()
        assert 0 <= position.x() <= max(0, replacement.map_viewport.width() - replacement.width())
        assert 0 <= position.y() <= max(0, replacement.map_viewport.height() - replacement.height())
    finally:
        replacement.hide()
        replacement.executor.shutdown(wait=True)
        replacement.deleteLater()


@pytest.mark.parametrize(
    "value", [None, [], [True, 0, 360, 650, 0, 0], [-1, 0, 360, 650, 0, 0], [0, 0, 360, 650, 2, 0]]
)
def test_invalid_saved_panel_geometry_is_ignored(tmp_path, value):
    import json

    from dale.preferences import load_slice_window_geometry

    path = tmp_path / "preferences.json"
    path.write_text(json.dumps({"slice_window_geometry": value}), encoding="utf-8")
    assert load_slice_window_geometry(path) is None
