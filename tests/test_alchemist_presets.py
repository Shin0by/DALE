"""Per-type portable defaults, explicit relative transforms and import choices."""

from dataclasses import replace

import numpy as np
import pytest
from PySide6.QtWidgets import QMessageBox
from shapely import LineString, Polygon, polygonize, union_all
from test_alchemist import sample as sample
from test_alchemist_detail import round_profiles
from test_alchemist_interaction import editor as editor
from test_alchemist_slices import object_edges
from test_alchemist_slices import projected as projected
from test_alchemist_window import panel as panel

from dale.alchemist import memberships, transform_individual_objects
from dale.alchemist_library import AlchemistLibrary, cache_path
from dale.alchemist_presets import apply_settings, transforms_for, validate_settings
from dale.alchemist_slices import change_slice, object_value
from dale.datasets import DatasetCatalog
from dale.project_io import load_project, save_project


def test_local_database_merges_only_changed_fields_and_clear_removes_defaults(sample):
    session, library, _, _ = sample
    before = session.geometry()
    library.remember_item_settings({"tree": {"scale": 1.2, "rotation": 15}})
    library.remember_item_settings({"tree": {"slice": (2, 8, True), "complexity": 8}})
    library.remember_item_settings({"tree": {"rotation": 30}})
    offline = AlchemistLibrary(library.path)
    assert offline.item_settings(["tree", "unknown"]) == {
        "tree": {"scale": 1.2, "rotation": 30, "slice": (2, 8, True), "complexity": 8}
    }
    offline.clear()
    assert offline.item_settings(["tree"]) == {}
    assert session.geometry() == before


@pytest.mark.parametrize(
    "value",
    [
        {"scale": True},
        {"scale": 0},
        {"scale": float("nan")},
        {"rotation": 180},
        {"rotation": float("inf")},
        {"slice": [8, 2, True]},
        {"complexity": 3},
        {"unknown": 1},
    ],
)
def test_saved_parameters_are_strictly_validated(value):
    with pytest.raises(ValueError):
        validate_settings(value)


def test_panel_remembers_final_scale_slice_complexity_and_rotation(panel, tmp_path):
    session = panel.session
    round_profiles(session)
    panel.owner.refresh()
    panel.choose_all()
    panel.scale.setValue(125)
    panel.flush()
    panel.scale.setValue(150)
    panel.lower.setValue(2)
    panel.upper.setValue(7)
    panel.between.setChecked(True)
    panel.complexity.setValue(8)
    panel.flush()
    panel.hide()
    view = panel.owner.view
    assert view.figure_line_ids, "Closing slices must retain selected objects"
    panel.owner.activate_mode("Rotate figures")
    assert view.mode == "Rotate figures"
    assert view.whole_da_selection(view.figure_line_ids), "Slice ancestry must retain ownership"
    view.transform_regions(angle=15)
    view.transform_regions(angle=15)
    library = AlchemistLibrary(cache_path(panel.owner.preferences_path))
    assert library.item_settings(["tree"])["tree"] == {
        "scale": 1.5,
        "rotation": 30,
        "slice": (2, 7, True),
        "complexity": 8,
    }
    path = tmp_path / "parameters.dale"
    save_project(session, path)
    with load_project(path) as loaded:
        assert transforms_for(loaded.session) == transforms_for(session)
        assert all(value == (1.5, 30) for value in transforms_for(loaded.session).values())
    panel.owner.question = lambda title, *args: (
        QMessageBox.StandardButton.Yes
        if title == "Clear Alchemist cache"
        else QMessageBox.StandardButton.No
    )
    panel.owner.clear_alchemist_cache()
    assert library.item_settings(["tree"]) == {}
    assert set(transforms_for(session).values()) == {(1.5, 30)}


def test_presets_apply_relative_to_each_original_instance_and_preserve_other_lines(projected):
    session, _ = projected
    round_profiles(session)
    original = session.geometry()
    settings = {"tree": {"scale": 1.7, "rotation": 35, "slice": (3, 8, True)}}
    frozen = replace(session, operations=list(session.operations), future=[])
    sliced = change_slice(frozen, "tree", 3, upper=8, between=True, apply_detail=False)
    frozen.operations.append(sliced)
    selected = tuple(
        r.id
        for r, owners in zip(sliced.lineage, memberships(frozen.alchemist, sliced), strict=True)
        if owners
    )
    expected, _ = transform_individual_objects(frozen, selected, scale=1.7, angle=35)
    result = apply_settings(session, settings, lambda *_: None)
    assert np.asarray(result.walls) == pytest.approx(np.asarray(expected.walls))
    assert session.geometry() == original
    session.add(result)
    assert set(transforms_for(session).values()) == {(1.7, 35)}
    assert all(object_value(session, obj) == (3, 8, True) for obj in session.alchemist.objects)
    second = apply_settings(
        replace(session, operations=[original]),
        {"tree": {**settings["tree"], "complexity": 8}},
        lambda *_: None,
    )
    reduced = replace(session, operations=[second])
    for obj in session.alchemist.objects:
        shape = union_all(polygonize([LineString(e) for e in object_edges(reduced, obj)]))
        source = union_all(polygonize([LineString(e) for e in object_edges(session, obj)]))
        assert isinstance(shape, Polygon) and len(shape.exterior.coords) <= 9
        assert shape.buffer(1e-7).covers(source)


def test_existing_project_keeps_applied_values_without_import_question(
    editor, tmp_path, monkeypatch
):
    view = editor.view
    view.figure_line_ids = view.session.alchemist.objects[0].roots
    view.transform_regions(scale=1.5)
    before = view.session.geometry()
    path = tmp_path / "existing.dale"
    save_project(view.session, path)
    library = AlchemistLibrary(cache_path(editor.preferences_path))
    library.remember_item_settings({"tree": {"scale": 3, "rotation": 80}})
    monkeypatch.setattr(editor, "question", lambda *args: pytest.fail("Unexpected import question"))
    assert editor.load_project_file(path)
    assert editor.view.session.geometry().walls == before.walls
    assert list(transforms_for(editor.view.session).values()) == [(1.5, 0)]


def test_cache_clear_finishes_pending_parameter_write_before_deleting_it(panel):
    from PySide6.QtTest import QTest

    panel.lower.setValue(6)
    panel.apply()
    panel.owner.question = lambda title, *args: (
        QMessageBox.StandardButton.Yes
        if title == "Clear Alchemist cache"
        else QMessageBox.StandardButton.No
    )
    panel.owner.clear_alchemist_cache()
    library = AlchemistLibrary(cache_path(panel.owner.preferences_path))
    assert not panel.busy and not panel.dirty
    assert object_value(panel.session, panel.session.alchemist.objects[0])[0] == 6
    QTest.qWait(100)
    assert library.item_settings(["tree"]) == {}
    panel.scale.setValue(120)
    panel.flush()
    assert library.item_settings(["tree"]) == {"tree": {"scale": 1.2}}


def test_saved_slices_load_local_geometry_after_initial_circle_choice(
    editor, projected, tmp_path, monkeypatch
):
    session, _ = projected
    path = tmp_path / "profiled.dam"
    path.write_bytes(session.alchemist.source)
    library = AlchemistLibrary(cache_path(editor.preferences_path))
    library.remember_item_settings({"tree": {"slice": (2, 7, True), "scale": 1.2}})
    catalog = DatasetCatalog(editor.view.session)
    answers = iter((QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(editor, "question", lambda *args: next(answers))
    monkeypatch.setattr("dale.alchemist_ui.discover_installations", lambda *_: ())
    requests = []

    def load(raw, path, target, library, load_geometry):
        requests.append(load_geometry)
        data = (
            session.alchemist
            if load_geometry
            else replace(
                session.alchemist,
                profiles=(),
                objects=tuple(replace(obj, projection=None) for obj in session.alchemist.objects),
            )
        )
        return data, session.geometry()

    monkeypatch.setattr(editor, "load_alchemist_with_progress", load)
    assert editor.import_alchemist(catalog, catalog.base_key, path)
    assert requests == [False, True]
    assert all(
        object_value(catalog.current.session, obj) == (2, 7, True)
        for obj in catalog.current.session.alchemist.objects
    )


def test_missing_models_keep_original_shape_and_apply_other_parameters(sample):
    session, _, _, _ = sample
    selected = tuple(
        r.id
        for r, owners in zip(
            session.geometry().lineage,
            memberships(session.alchemist, session.geometry()),
            strict=True,
        )
        if owners
    )
    expected, _ = transform_individual_objects(session, selected, scale=1.2)
    result = apply_settings(
        session, {"tree": {"slice": (2, 8, True), "scale": 1.2}}, lambda *_: None
    )
    assert np.asarray(result.walls) == pytest.approx(np.asarray(expected.walls))


@pytest.mark.parametrize("attached,confirmed", [(True, True), (True, False), (False, True)])
def test_cache_clear_only_offers_slices_after_success_with_attachment(
    editor, monkeypatch, attached, confirmed
):
    library = AlchemistLibrary(cache_path(editor.preferences_path))
    library.remember_item_settings({"tree": {"scale": 2}})
    if not attached:
        editor.view.session.alchemist = None
    prompts = []

    def answer(title, *args):
        prompts.append(title)
        if title == "Clear Alchemist cache" and confirmed:
            return QMessageBox.StandardButton.Yes
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(editor, "question", answer)
    monkeypatch.setattr(editor, "choose_alchemist", lambda: pytest.fail("No reload requested"))
    editor.clear_alchemist_cache()
    assert prompts == (
        ["Clear Alchemist cache", "Load object geometry"]
        if attached and confirmed
        else ["Clear Alchemist cache"]
    )
    assert library.item_settings(["tree"]) == ({} if confirmed else {"tree": {"scale": 2}})


def test_cache_clear_failure_does_not_offer_reload(editor, monkeypatch):
    import sqlite3

    prompts, warnings = [], []
    monkeypatch.setattr(
        editor,
        "question",
        lambda title, *args: prompts.append(title) or QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(editor, "warning", lambda *args: warnings.append(args))

    def fail(_):
        raise sqlite3.OperationalError("locked")

    monkeypatch.setattr(AlchemistLibrary, "clear", fail)
    editor.clear_alchemist_cache()
    assert prompts == ["Clear Alchemist cache"] and len(warnings) == 1


@pytest.mark.parametrize("cancelled", [False, True])
def test_cache_reload_builds_local_slices_off_thread_without_reimport(
    editor, sample, monkeypatch, cancelled
):
    from PySide6.QtCore import QThread
    from test_alchemist_mesh import leaning_tree

    from dale.alchemist import AlchemistCancelled
    from dale.alchemist_mesh import cached_profile

    library = AlchemistLibrary(cache_path(editor.preferences_path))
    library.remember_item_settings({"tree": {"scale": 2}})
    view = editor.view
    view.figure_line_ids = view.session.alchemist.objects[0].roots
    view.transform_regions(scale=1.3)
    before = view.session.geometry(), view.session.alchemist, tuple(view.session.operations)
    selection = view.figure_line_ids
    calls, prompts = [], []

    def answer(title, *args):
        prompts.append(title)
        if title == "Load object geometry":
            assert library.item_settings(["tree"]) == {}
        return QMessageBox.StandardButton.Yes

    def meshes(_library, identifier, model, workshop):
        assert QThread.currentThread() != editor.thread()
        calls.append(identifier)
        if cancelled:
            raise AlchemistCancelled()
        return leaning_tree()

    monkeypatch.setattr(editor, "question", answer)
    monkeypatch.setattr(
        "dale.alchemist_ui.discover_installations", lambda *_: (sample[1].executable,)
    )
    monkeypatch.setattr(AlchemistLibrary, "_workshop_meshes", meshes)
    monkeypatch.setattr(
        editor,
        "load_alchemist_with_progress",
        lambda *args: pytest.fail("Cache reload must not reimport contours"),
    )
    editor.clear_alchemist_cache()
    assert calls == ["tree"] and prompts == ["Clear Alchemist cache", "Load object geometry"]
    assert (
        view.session.geometry(),
        view.session.alchemist,
        tuple(view.session.operations),
    ) == before
    assert view.figure_line_ids == selection and library.item_settings(["tree"]) == {}
    with library._connect() as connection:
        profile = cached_profile(connection, "tree-model")
    assert (profile is None) is cancelled
    if not cancelled:
        assert len(profile.layers) == 10


def test_cache_reload_can_cancel_installation_picker(editor, monkeypatch):
    library = AlchemistLibrary(cache_path(editor.preferences_path))
    library.remember_item_settings({"tree": {"scale": 2}})
    before = editor.view.session.geometry()
    monkeypatch.setattr(editor, "question", lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr("dale.alchemist_ui.discover_installations", lambda *_: ())
    monkeypatch.setattr(editor, "choose_alchemist", lambda: None)
    editor.clear_alchemist_cache()
    assert library.item_settings(["tree"]) == {}
    assert editor.view.session.geometry() == before


@pytest.mark.parametrize("choice", ["Yes", "No", "Cancel"])
def test_new_import_offers_saved_or_original_and_cancel_preserves_session(
    editor, sample, tmp_path, monkeypatch, choice
):
    original_session, _, raw, _ = sample
    path = tmp_path / "new.dam"
    path.write_bytes(raw)
    library = AlchemistLibrary(cache_path(editor.preferences_path))
    library.remember_item_settings({"tree": {"scale": 2, "rotation": 20}})
    catalog = DatasetCatalog(editor.view.session)
    session = catalog.current.session
    before = session.geometry()
    answers = iter((QMessageBox.StandardButton.No, getattr(QMessageBox.StandardButton, choice)))
    prompts = []

    def answer(title, *args):
        prompts.append(title)
        return next(answers)

    monkeypatch.setattr(editor, "question", answer)
    monkeypatch.setattr("dale.alchemist_ui.discover_installations", lambda *_: ())
    monkeypatch.setattr(
        editor,
        "load_alchemist_with_progress",
        lambda *args: (original_session.alchemist, original_session.geometry()),
    )
    assert editor.import_alchemist(catalog, catalog.base_key, path) is (choice != "Cancel")
    assert prompts == ["Load object geometry", "Saved object settings"]
    if choice == "Yes":
        assert set(transforms_for(session).values()) == {(2, 20)}
        assert session.geometry().walls != before.walls
    else:
        assert session.geometry().walls == before.walls
        assert not transforms_for(session)
