"""Whole-object overlap thinning, restoration, export scope and UI publication."""

from dataclasses import replace
from threading import Event

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shapely import Point, box, union_all
from test_alchemist import sample as sample
from test_alchemist_interaction import editor as editor

from dale.alchemist import DAObject, export_session, scoped_geometry
from dale.alchemist_thinning import decode_state, state_for, thin_objects, thin_shapes
from dale.project_io import load_project, save_project
from dale.provenance import LineRecord
from dale.session import GeometryEdit


def configure(session):
    shapes = [box(10, 10, 30, 30), box(10, 10, 30, 30), box(50, 10, 60, 20)]
    edges, records, objects = [], [], []
    for i, (shape, category) in enumerate(zip(shapes, ("tree", "rock", "bush"), strict=True)):
        identifier = f"thin-{i}"
        points = tuple(shape.exterior.coords)
        parts = tuple(zip(points, points[1:], strict=False))
        roots = tuple(f"{identifier}:{j}" for j in range(len(parts)))
        edges.extend(parts)
        records.extend(LineRecord(root, connection_group=f"da:{identifier}") for root in roots)
        objects.append(DAObject(identifier, category, 1, roots))
    session.alchemist = replace(session.alchemist, objects=tuple(objects))
    session.operations = [GeometryEdit(tuple(edges), lineage=tuple(records))]
    session.future = []
    session.history_floor = 0
    return tuple(obj.id for obj in objects)


def test_disjoint_dense_objects_survive_and_duplicates_thin():
    shapes = {str(i): box(i * 0.02, 0, i * 0.02 + 0.01, 0.01) for i in range(100)}
    assert not thin_shapes(shapes, 10)
    shapes["duplicate"] = shapes["10"]
    assert len(thin_shapes(shapes, 1)) == 1
    assert len(thin_shapes(shapes, 10)) == 1
    assert thin_shapes(shapes, 0) == frozenset()


def test_strength_is_nested_and_ten_leaves_no_contacts():
    shapes = {
        str(i): Point(i * 0.6, j * 0.6).buffer(1) for i, j in enumerate([0, 1, 2, 1, 0, 1, 2, 1, 0])
    }
    previous = set()
    for level in range(11):
        hidden = thin_shapes(shapes, level)
        assert previous <= hidden
        previous = hidden
    kept = [p for name, p in shapes.items() if name not in previous]
    assert kept
    assert all(a.disjoint(b) for i, a in enumerate(kept) for b in kept[i + 1 :])
    touching = {"a": box(0, 0, 1, 1), "b": box(1, 0, 2, 1)}
    assert not thin_shapes(touching, 9)
    assert len(thin_shapes(touching, 10)) == 1


def test_midlevel_preserves_coverage_of_redundant_cluster():
    shapes = {f"{x}:{y}": Point(x * 0.25, y * 0.25).buffer(1) for x in range(6) for y in range(6)}
    hidden = thin_shapes(shapes, 5)
    assert hidden
    before = union_all(list(shapes.values()))
    after = union_all([p for name, p in shapes.items() if name not in hidden])
    assert after.area / before.area > 0.9


def test_selection_cross_categories_undo_export_and_archive(sample, tmp_path):
    session, *_ = sample
    identifiers = configure(session)
    original = session.geometry()
    operation = thin_objects(session, identifiers, 5)
    assert len(operation.alchemist_thinning[2]) == 1
    session.add(operation)
    assert session.geometry().walls == original.walls
    assert len(scoped_geometry(session).walls) == 8
    assert len(export_session(session).geometry().walls) == 8
    assert len(scoped_geometry(session, scope="alchemist_all").walls) == 12
    path = tmp_path / "thinned.dale"
    save_project(session, path)
    with load_project(path) as opened:
        assert state_for(opened.session) == state_for(session)
        assert len(scoped_geometry(opened.session).walls) == 8
        opened.session.add(thin_objects(opened.session, identifiers, 0))
        assert scoped_geometry(opened.session).walls == original.walls
    session.undo()
    assert scoped_geometry(session).walls == original.walls
    session.redo()
    assert len(scoped_geometry(session).walls) == 8


def test_partial_scope_never_hides_unselected_objects(sample):
    session, *_ = sample
    identifiers = configure(session)
    assert not thin_objects(session, identifiers[1:], 10).alchemist_thinning[2]


@pytest.mark.parametrize(
    "bad", [(11, [], []), (True, [], []), (5, ["a"], ["b"]), (0, ["a"], ["a"]), (5, ["a", "a"], [])]
)
def test_invalid_state_rejected(bad):
    with pytest.raises(ValueError, match="thinning"):
        decode_state(bad)


def test_button_restores_hidden_scope_after_selection_pruning(editor):
    window, session = editor, editor.view.session
    configure(session)
    window.select_tool_set("alchemist")
    window.view.figure_line_ids = tuple(r.id for r in session.geometry().lineage)
    window.refresh()
    window.thinning_value.setValue(5)
    window.thinning.flush()
    assert window.thinning.action.isChecked()
    assert len(window.view.figure_line_ids) == 8
    assert len(state_for(session)[2]) == 1
    window.thinning_value.setValue(0)
    window.thinning.flush()
    assert not state_for(session)[2]
    assert len(scoped_geometry(session).walls) == 12
    assert not window.thinning.action.isChecked()
    assert set(window.view.figure_line_ids) == {r.id for r in session.geometry().lineage}


@pytest.mark.parametrize("selection", ["all", "hidden_only", "none", "unrelated"])
def test_thinning_uses_all_objects_and_restores_only_user_selection(editor, selection):
    session = editor.view.session
    identifiers = configure(session)
    hidden = set(thin_objects(session, identifiers, 10).alchemist_thinning[2])
    editor.select_tool_set("alchemist")
    from dale.alchemist import memberships

    owners = memberships(session.alchemist, session.geometry())
    original = tuple(
        r.id
        for r, own in zip(session.geometry().lineage, owners, strict=True)
        if selection == "all"
        or (selection == "hidden_only" and own & hidden)
        or (selection == "unrelated" and identifiers[2] in own)
    )
    editor.view.figure_line_ids = original
    editor.refresh()
    assert editor.thinning.action.isEnabled() and editor.thinning_value.isEnabled()
    for level in (10, 9, 5, 1, 0):
        editor.thinning_value.setValue(level)
        editor.thinning.flush()
        assert set(state_for(session)[1]) == set(identifiers)
        visible = {r.id for r in scoped_geometry(session).lineage}
        assert set(editor.view.figure_line_ids) == set(original) & visible
    assert set(editor.view.figure_line_ids) == set(original)
    assert len(session.operations) == 2


@pytest.mark.parametrize("clear", [False, True])
def test_user_selection_changes_during_thinning_are_preserved(editor, clear):
    session = editor.view.session
    configure(session)
    editor.select_tool_set("alchemist")
    original = {r.id for r in session.geometry().lineage}
    editor.view.figure_line_ids = tuple(original)
    editor.refresh()
    editor.thinning_value.setValue(10)
    editor.thinning.flush()
    visible_before = set(editor.view.figure_line_ids)
    if clear:
        editor.clear_selection()
        expected = set()
    else:
        removed = set(session.alchemist.objects[2].roots)
        editor.view.figure_line_ids = tuple(visible_before - removed)
        editor.update_map_info()
        expected = original - removed
    editor.thinning_value.setValue(0)
    editor.thinning.flush()
    assert set(editor.view.figure_line_ids) == expected


def test_remembered_selection_does_not_leak_to_another_dataset(editor):
    session = editor.view.session
    configure(session)
    editor.select_tool_set("alchemist")
    editor.view.figure_line_ids = tuple(r.id for r in session.geometry().lineage)
    editor.refresh()
    editor.thinning_value.setValue(10)
    editor.thinning.flush()
    # A copied dataset can share the same persistent IDs but has its own selection.
    other = replace(session, operations=list(session.operations), future=[])
    editor.view.session = other
    editor.view.figure_line_ids = ()
    editor.refresh()
    editor.thinning_value.setValue(0)
    editor.thinning.flush()
    assert not editor.view.figure_line_ids
    assert not state_for(other)[2]
    assert state_for(session)[2]


def test_ctrl_wheel_and_newest_request_replace_running_calculation(editor, monkeypatch):
    import dale.alchemist_thinning_ui as module

    session = editor.view.session
    configure(session)
    editor.select_tool_set("alchemist")
    editor.view.figure_line_ids = tuple(r.id for r in session.geometry().lineage)
    editor.refresh()
    entered = Event()
    calls = []
    original = module.thin_objects

    def controlled(frozen, scope, level, check, progress):
        calls.append(level)
        if level == 5:
            entered.set()
            while True:
                check()
                Event().wait(0.005)
        return original(frozen, scope, level, check, progress)

    monkeypatch.setattr(module, "thin_objects", controlled)
    editor.thinning_value.setValue(5)
    editor.thinning.start()
    assert entered.wait(5)
    # A user's newer choice wins even while an obsolete worker is being cancelled.
    chosen = session.alchemist.objects[2].roots
    editor.view.figure_line_ids = chosen
    editor.update_map_info()
    for target in (editor.thinning_value.lineEdit(), editor.view.viewport()):
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
        QApplication.sendEvent(target, wheel)
    assert editor.thinning_value.value() == 7
    editor.thinning.flush()
    assert calls == [5, 7]
    assert state_for(session)[0] == 7
    assert len(session.operations) == 2
    assert not editor.thinning.progress.isVisible()
    QTest.qWait(60)
    assert state_for(session)[0] == 7
    assert set(editor.view.figure_line_ids) == set(chosen)
    editor.thinning_value.setValue(0)
    editor.thinning.flush()
    assert set(editor.view.figure_line_ids) == set(chosen)


def test_wall_objects_excluded_and_thinning_survives_checkpoint(sample, tmp_path):
    session, *_ = sample
    identifiers = configure(session)
    session.alchemist = replace(
        session.alchemist,
        objects=(
            session.alchemist.objects[0],
            replace(session.alchemist.objects[1], category="wall"),
            session.alchemist.objects[2],
        ),
    )
    assert not thin_objects(session, identifiers, 10).alchemist_thinning[2]
    session.alchemist = replace(
        session.alchemist,
        objects=(
            session.alchemist.objects[0],
            replace(session.alchemist.objects[1], category="rock"),
            session.alchemist.objects[2],
        ),
    )
    session.add(thin_objects(session, identifiers, 5))
    session.trim_history(0)
    assert len(state_for(session)[2]) == 1
    # Removing the attached DAM must not make an ordinary project unreadable.
    session.alchemist = None
    path = tmp_path / "removed-dam.dale"
    save_project(session, path)
    with load_project(path) as loaded:
        assert loaded.session.alchemist is None
