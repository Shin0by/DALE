"""Exact DA types, individual pivots and editing without export preparation or modal progress."""

import json
from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication
from test_alchemist import sample as sample

from dale.alchemist import (
    DAData,
    export_session,
    register_pasted_objects,
    same_type_lines,
    scoped_geometry,
    transform_individual_objects,
)
from dale.datasets import DatasetCatalog
from dale.json_repair import repaired_json_bytes
from dale.project_io import load_project, save_project
from dale.region_transform import copy_figures
from dale.ui import MainWindow, configure_application


@pytest.fixture
def editor(sample, tmp_path):
    app = QApplication.instance() or QApplication([])
    configure_application(app)
    session, _, _, source = sample
    window = MainWindow(preferences_path=tmp_path / "preferences.json")
    window.can_discard = lambda: True
    window.load_sources(source.image_path, source.json_path)
    window.view.session.alchemist = session.alchemist
    window.view.session.add(session.geometry())
    window.configure_json_repair(True)
    window.select_tool_set("alchemist")
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()


def object_center(session, obj):
    roots = set(obj.roots)
    points = [
        p
        for edge, record in zip(session.geometry().walls, session.geometry().lineage, strict=True)
        if record.id in roots
        for p in edge
    ]
    return tuple((min(p[i] for p in points) + max(p[i] for p in points)) / 2 for i in (0, 1))


def test_da_click_and_marquee_select_whole_objects_and_cancel_restores(editor):
    view, session = editor.view, editor.view.session
    obj, other = session.alchemist.objects
    index = next(i for i, r in enumerate(session.geometry().lineage) if r.id == obj.roots[0])
    a, b = session.geometry().walls[index]
    point = tuple((a[i] + b[i]) / 2 for i in (0, 1))
    editor.select_figure_at({"point": point})
    assert set(view.figure_line_ids) == set(obj.roots)
    editor.select_figure_at({"point": point})
    assert not view.figure_line_ids
    view.figure_line_ids = other.roots
    editor.select_figures_in_box({"phase": "begin"})
    editor.select_figures_in_box(
        {"phase": "preview", "bounds": (point[0] - 1, point[1] - 1, point[0] + 1, point[1] + 1)}
    )
    assert set(view.figure_line_ids) == set(obj.roots + other.roots)
    editor.select_figures_in_box({"phase": "cancel"})
    assert set(view.figure_line_ids) == set(other.roots)


def test_da_disconnected_islands_belong_to_one_object(editor):
    view, session = editor.view, editor.view.session
    first, second = session.alchemist.objects
    session.alchemist = replace(
        session.alchemist, objects=(replace(first, roots=first.roots + second.roots),)
    )
    editor.refresh()
    assert len(view.contour_figures()) == 1
    assert set(view.whole_da_selection((first.roots[0],))) == set(first.roots + second.roots)
    assert view.contour_figures()[0].area.geom_type == "MultiPolygon"


@pytest.mark.parametrize("mode", ["Move figures", "Edit points", "New line", "Erase lines"])
def test_da_rejects_retired_edit_modes_and_leaves_ordinary_tools_available(editor, mode):
    view, session = editor.view, editor.view.session
    geometry, history = session.geometry(), tuple(session.operations)
    editor.activate_mode(mode, prompt=False)
    assert view.mode == "Select figures"
    view.set_mode(mode)
    assert view.mode == "Select figures"
    assert "Move figures" not in editor.alchemist_tool_buttons
    view.figure_line_ids = session.alchemist.objects[0].roots
    editor.delete_selected_contours()
    editor.mirror_contours("vertical")
    assert not view.copy_selected_regions() and not view.begin_paste_regions()
    assert session.geometry() is geometry and tuple(session.operations) == history
    editor.select_tool_set("figures")
    editor.activate_mode("Move figures", prompt=False)
    assert view.mode == "Move figures"


def test_da_partial_saved_selection_expands_before_scaling(editor):
    view, session = editor.view, editor.view.session
    first, second = session.alchemist.objects
    geometry = session.geometry()
    center = object_center(session, first)
    view.figure_line_ids = (first.roots[0],)
    editor.update_map_info()
    assert set(view.figure_line_ids) == set(first.roots)
    editor.activate_mode("Scale figures", prompt=False)
    view.transform_regions(scale=1.2)
    assert object_center(session, first) == pytest.approx(center)
    for old, new, record in zip(
        geometry.walls, session.geometry().walls, geometry.lineage, strict=True
    ):
        if record.id in second.roots:
            assert old == new
    session.undo()
    assert session.geometry().walls == geometry.walls


def test_visibility_reuses_height_layers_and_preserves_geometry(editor, monkeypatch):
    view, session = editor.view, editor.view.session
    view.selected_source_layer()
    choices = view._source_layers_cache[2]
    geometry, operations = session.geometry(), tuple(session.operations)
    visible = view.walls
    monkeypatch.setattr(
        "dale.canvas.source_layers",
        lambda *args, **kwargs: pytest.fail("Visibility must not recalculate unchanged heights"),
    )
    editor.set_alchemist_category("tree", False)
    assert not view.walls and view._source_layers_cache[2] is choices
    editor.set_alchemist_category("tree", True)
    assert view.walls == visible and view._source_layers_cache[2] is choices
    assert session.geometry() is geometry and tuple(session.operations) == operations


def test_height_cache_invalidates_when_object_floor_changes(editor, monkeypatch):
    import dale.canvas as canvas

    view, session = editor.view, editor.view.session
    view.selected_source_layer()
    original = canvas.source_layers
    calls = []
    monkeypatch.setattr(
        canvas,
        "source_layers",
        lambda *args, **kwargs: calls.append(True) or original(*args, **kwargs),
    )
    session.alchemist = replace(
        session.alchemist, objects=tuple(replace(obj, layer=3) for obj in session.alchemist.objects)
    )
    view.selected_source_layer()
    assert calls == [True]
    assert any(layer.key == "da-layer:3" for layer in view._source_layers_cache[2])


def test_ownership_cache_uses_immutable_identity_and_invalidates_new_lineage(sample, monkeypatch):
    from dale.alchemist import _memberships, memberships
    from dale.provenance import LineRecord

    session = sample[0]
    data, geometry = session.alchemist, session.geometry()
    _memberships.cache_clear()
    expected = memberships(data, geometry)
    monkeypatch.setattr(
        LineRecord,
        "__hash__",
        lambda self: pytest.fail("Cache lookup must not hash individual lines"),
    )
    assert memberships(replace(data, settings=((False, 0),) * 4), geometry) is expected
    assert _memberships.cache_info().hits == 1
    changed = replace(geometry, lineage=tuple(reversed(geometry.lineage)))
    assert memberships(data, changed) == tuple(reversed(expected))
    assert _memberships.cache_info().misses == 2
    _memberships.cache_clear()


def test_json_only_da_information_reuses_floor_choices(editor, monkeypatch):
    window = editor
    window.view.session.source = replace(window.view.session.source, image_path=None)
    monkeypatch.setattr(
        "dale.ui.infer_layers",
        lambda *_: pytest.fail("DA object tips must not produce ordinary height bands."),
    )
    window.select_tool_set("geometry")
    window.update_map_info()
    assert any(layer.kind == "alchemist" for layer in window.view._source_layers_cache[2])
    assert window.map_info.text()


def test_import_type_and_existing_archive_without_optional_fields(sample):
    session = sample[0]
    assert {o.block_id for o in session.alchemist.objects} == {"tree"}
    encoded = json.loads(json.dumps(session.alchemist.encode()))
    encoded.pop("individual_transforms")
    for obj in encoded["objects"]:
        obj.pop("block_id")
    restored = DAData.decode(encoded)
    assert {o.block_id for o in restored.objects} == {"tree"}
    assert not restored.individual_transforms


def test_same_exact_type_respects_original_size_and_height_filters(sample):
    session = sample[0]
    data = session.alchemist
    first, second = data.objects
    assert (
        len(same_type_lines(data, scoped_geometry(session, scope="alchemist"), (first.roots[0],)))
        == 48
    )
    data = replace(data, objects=(first, replace(second, block_id="oak")))
    session.alchemist = data
    visible = scoped_geometry(session, scope="alchemist")
    assert set(same_type_lines(data, visible, (first.roots[0],))) == set(first.roots)
    assert len(same_type_lines(data, visible, (first.roots[0], second.roots[0]))) == 48
    session.alchemist = replace(data, minimum_heights_ft=(0, 20, 0, 0))
    visible = scoped_geometry(session, scope="alchemist")
    assert not same_type_lines(session.alchemist, visible, first.roots)
    assert set(same_type_lines(session.alchemist, visible, second.roots)) == set(second.roots)


def test_copy_and_project_keep_exact_type_and_individual_setting(sample, tmp_path):
    session = sample[0]
    before = session.geometry()
    obj = session.alchemist.objects[0]
    clip = copy_figures(before, obj.roots)
    copied = register_pasted_objects(session, before, clip.paste(before, 50, 0), clip)
    session.add(copied)
    assert session.alchemist.objects[-1].block_id == obj.block_id
    session.alchemist = replace(session.alchemist, individual_transforms=True)
    path = tmp_path / "types.dale"
    save_project(session, path, catalog=DatasetCatalog(session))
    with load_project(path) as loaded:
        restored = loaded.catalog.current.session
        assert restored.alchemist.individual_transforms
        assert len(same_type_lines(restored.alchemist, restored.geometry(), obj.roots)) == 72


@pytest.mark.parametrize("individual", [False, True])
def test_da_scaling_keeps_individual_centers_even_with_old_shared_preference(editor, individual):
    view = editor.view
    session = view.session
    objects = session.alchemist.objects
    original = session.geometry()
    centers = [object_center(session, obj) for obj in objects]
    view.figure_line_ids = objects[0].roots + objects[1].roots
    editor.set_alchemist_individual_transforms(individual)
    editor.activate_mode("Scale figures", prompt=False)
    view.transform_regions(scale=2)
    assert session.geometry().walls[0] == original.walls[0]
    for old, obj in zip(centers, objects, strict=True):
        assert object_center(session, obj) == pytest.approx(old)
    session.undo()
    assert session.geometry().walls == original.walls


def test_individual_rotation_series_keeps_each_pivot_and_one_undo(editor):
    view = editor.view
    session = view.session
    original = session.geometry()
    objects = session.alchemist.objects
    view.figure_line_ids = objects[0].roots + objects[1].roots
    editor.set_alchemist_individual_transforms(True)
    editor.activate_mode("Rotate figures", prompt=False)
    centers = [object_center(session, obj) for obj in objects]
    count = len(session.operations)
    view.transform_regions(angle=10)
    frozen = dict(view.individual_rotation_centers)
    view.transform_regions(angle=15)
    assert view.individual_rotation_centers == frozen
    assert len(session.operations) == count + 1
    for old, obj in zip(centers, objects, strict=True):
        assert object_center(session, obj) == pytest.approx(old)
    assert session.geometry().walls[0] == original.walls[0]
    session.undo()
    assert session.geometry().walls == original.walls


def test_individual_partial_selection_keeps_unselected_ids_unchanged(sample):
    session = sample[0]
    original = session.geometry()
    selected = session.alchemist.objects[0].roots[0]
    changed, _ = transform_individual_objects(session, (selected,), scale=2, angle=15)
    for old, new, record in zip(original.walls, changed.walls, original.lineage, strict=True):
        assert (old != new) == (record.id == selected)
    assert changed.lineage == original.lineage
    assert changed.wall_styles == original.wall_styles


def test_individual_rotation_uses_frozen_pivot_for_asymmetric_contour(editor):
    from dale.alchemist_progress import snapshot

    view, session = editor.view, editor.view.session
    obj = session.alchemist.objects[0]
    original = session.geometry()
    # An asymmetric triangle's bounds center changes after rotation, unlike a circle's.
    corners = ((80, 260), (140, 260), (90, 300))
    points = tuple(
        (a[0] + (b[0] - a[0]) * step / 8, a[1] + (b[1] - a[1]) * step / 8)
        for a, b in zip(corners, (*corners[1:], corners[0]), strict=True)
        for step in range(8)
    )
    edges = tuple(zip(points, (*points[1:], points[0]), strict=True))
    replacement = dict(zip(obj.roots, edges, strict=True))
    original = replace(
        original,
        walls=tuple(
            replacement.get(record.id, edge)
            for record, edge in zip(original.lineage, original.walls, strict=True)
        ),
    )
    session.add(original)
    expected, _ = transform_individual_objects(snapshot(session), obj.roots, angle=25)
    editor.refresh()
    view.figure_line_ids = obj.roots
    editor.set_alchemist_individual_transforms(True)
    editor.activate_mode("Rotate figures", prompt=False)
    view.transform_regions(angle=10)
    view.transform_regions(angle=15)
    for actual, wanted in zip(session.geometry().walls, expected.walls, strict=True):
        for a, b in zip(actual, wanted, strict=True):
            assert a == pytest.approx(b)
    session.undo()
    assert session.geometry().walls == original.walls


def test_buttons_and_actions_do_not_prepare_exports_or_open_progress(editor, monkeypatch):
    import dale.alchemist_ui as module

    view, session = editor.view, editor.view.session
    obj = session.alchemist.objects[0]
    view.figure_line_ids = (obj.roots[0],)
    editor.update_map_info()
    select_button = editor.alchemist_tool_buttons["Select figures"]
    actions = select_button.parentWidget().actions()
    assert actions[actions.index(editor.mode_actions["Select figures"]) + 1] is (
        editor.alchemist_same_type_action
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Editing attempted modal progress or export preparation")

    monkeypatch.setattr(module, "run_task", forbidden)
    monkeypatch.setattr(session, "analysis", forbidden)
    monkeypatch.setattr(editor.bounds_preview, "request", forbidden)
    raster = view.raster_key
    editor.alchemist_same_type_action.trigger()
    assert len(view.figure_line_ids) == 48
    for language in ("en", "ru", "en"):
        editor.set_language(language, persist=False)
        command = editor.alchemist_same_type_action
        assert command.toolTip().splitlines()[0] == command.text()
    editor.set_alchemist_individual_transforms(True)
    assert "own contour centers" in " ".join(
        editor.mode_actions["Rotate figures"].toolTip().split()
    )
    assert "own contour centers" in " ".join(editor.mode_actions["Scale figures"].toolTip().split())
    for mode in ("Rotate figures", "Scale figures"):
        editor.activate_mode(mode, prompt=False)
        for _ in range(4):
            view.transform_regions(
                angle=2 if mode == "Rotate figures" else 0,
                scale=1.1 if mode == "Scale figures" else 1,
            )
    editor.set_alchemist_category("tree", False)
    editor.set_alchemist_category("tree", True)
    assert view.raster_key == raster
    assert "PNG" in editor.map_info.text()


def test_individual_help_clears_when_opening_an_ordinary_project(editor, tmp_path, sample):
    from dale.session import Session

    editor.set_alchemist_individual_transforms(True)
    path = tmp_path / "ordinary.dale"
    save_project(Session(sample[3]), path)
    assert editor.load_project_file(path)
    assert editor.view.session.alchemist is None
    editor.set_language("en", persist=False)
    assert "common center" in " ".join(editor.mode_actions["Rotate figures"].toolTip().split())


def test_global_regions_only_recalculate_on_changes_and_export_is_current(editor, monkeypatch):
    import dale.geometry as module

    original = module.analyze_regions
    calls = []

    def tracked(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "analyze_regions", tracked)
    view, session = editor.view, editor.view.session
    editor.select_tool_set("regions")
    assert len(calls) == 1
    editor.select_tool_set("alchemist")
    editor.select_tool_set("pixels")
    editor.select_tool_set("regions")
    assert len(calls) == 1
    editor.select_tool_set("alchemist")
    view.figure_line_ids = session.alchemist.objects[0].roots
    editor.activate_mode("Scale figures", prompt=False)
    view.transform_regions(scale=1.5)
    assert len(calls) == 1
    editor.select_tool_set("regions")
    assert len(calls) == 2
    payload = json.loads(repaired_json_bytes(export_session(session))[0])
    assert len(payload["walls"]) == 49
    assert payload["walls"][0]["c"] == [20, 20, 80, 20]
    assert session.analysis().area.equals(original(scoped_geometry(session).walls).area)
