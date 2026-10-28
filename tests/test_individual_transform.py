"""Independent centers, staged settings and DA paired double-click questions."""

import json

import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from shapely.geometry import box
from shapely.ops import unary_union
from test_alchemist_interaction import editor as editor
from test_alchemist_interaction import sample as sample
from test_contour_scale import window as window

from dale.individual_transform import settings
from dale.preferences import load_alchemist_same_type
from dale.project_io import _decode, _encode, _load_ui, load_project, save_project
from dale.raster_transform import affine_matrix, image_reader, render_layered
from dale.session import RasterTransform


@pytest.mark.parametrize(
    "section,rotate,scale",
    [
        ("figures", "Rotate figures", "Scale figures"),
        ("regions", "Rotate regions", "Move regions"),
        ("pixels", "Rotate raster regions", "Scale raster regions"),
    ],
)
def test_staged_independent_options_and_project(editor, tmp_path, section, rotate, scale):
    editor.warning = lambda *args: pytest.fail(str(args))
    editor.information = lambda *args: pytest.fail(str(args))
    editor.select_tool_set(section)
    assert not hasattr(editor, "alchemist_individual_action")
    for tool, kind in ((rotate, "rotate"), (scale, "scale")):
        for apply in (False, True):
            popup = editor.show_tool_settings(tool)
            assert not popup.individual_centers.isChecked()
            popup.individual_centers.setChecked(True)
            assert not editor.view.individual_transform_enabled(tool)
            popup.accept() if apply else popup.reject()
            assert editor.view.individual_transform_enabled(tool) == apply
        assert editor.view.individual_transform_settings[f"{section}_{kind}"]
        if kind == "rotate":
            assert not editor.view.individual_transform_enabled(scale)
    state = editor.project_ui_state()
    assert _load_ui(json.loads(json.dumps(state)))["individual_transform_settings"] == {
        f"{section}_rotate": True,
        f"{section}_scale": True,
    }
    path = tmp_path / "centers.dale"
    editor.project_path = path
    assert editor.save_project_file()
    assert editor.load_project_file(path)
    assert editor.view.individual_transform_settings == state["individual_transform_settings"]
    editor.select_tool_set("figures" if section != "figures" else "regions")
    assert not editor.view.individual_transform_enabled(
        "Rotate figures" if section != "figures" else "Rotate regions"
    )


def double_click(editor, point):
    target = editor.view.viewport()
    point = editor.view.mapFromScene(*point)
    QTest.mousePress(target, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseRelease(target, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseDClick(target, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseRelease(target, Qt.MouseButton.LeftButton, pos=point)


@pytest.mark.parametrize("answer", [True, False, None])
@pytest.mark.parametrize("mode", ["Select figures"])
def test_da_double_click_question_remember_cancel_and_reset(editor, monkeypatch, answer, mode):
    editor.show()
    editor.activate_mode(mode, prompt=False)
    QApplication.processEvents()
    view, session = editor.view, editor.view.session
    obj, other = session.alchemist.objects
    # First click must be undone on cancellation; an unrelated prior selection survives Yes.
    view.figure_line_ids = other.roots if mode == "Select figures" else ()
    editor.update_map_info()
    before = view.figure_line_ids
    geometry = session.geometry()
    edges = dict(zip((r.id for r in geometry.lineage), geometry.walls, strict=True))
    a, b = edges[obj.roots[0]]
    point = tuple((x + y) / 2 for x, y in zip(a, b, strict=True))
    calls = []

    def respond(dialog):
        assert dialog.objectName() == "alchemistSameTypeQuestion"
        calls.append(True)
        dialog.checkBox().setChecked(True)
        return {
            True: QMessageBox.StandardButton.Yes,
            False: QMessageBox.StandardButton.No,
            None: QMessageBox.StandardButton.Cancel,
        }[answer]

    monkeypatch.setattr(QMessageBox, "exec", respond)
    double_click(editor, point)
    assert len(calls) == 1
    assert load_alchemist_same_type(editor.preferences_path) is answer
    if answer is None:
        assert set(view.figure_line_ids) == set(before)
    elif answer:
        assert set(view.figure_line_ids) == set(obj.roots + other.roots)
    else:
        assert set(obj.roots).issubset(view.figure_line_ids)
        assert set(other.roots).issubset(view.figure_line_ids)  # Preserve prior whole objects.
    assert session.geometry() == geometry
    if answer is not None:
        view.figure_click = None
        double_click(editor, point)
        assert len(calls) == 1
        popup = editor.show_tool_settings("Select figures")
        popup.default_action.setCurrentIndex(0)
        popup.reject()
        assert load_alchemist_same_type(editor.preferences_path) is answer
        popup = editor.show_tool_settings("Select figures")
        popup.default_action.setCurrentIndex(0)
        popup.accept()
        assert load_alchemist_same_type(editor.preferences_path) is None
    # Ordinary contours do not show a DA question.
    editor.select_tool_set("figures")
    editor.activate_mode("Select figures", prompt=False)
    double_click(editor, (50, 10))
    assert len(calls) == 1


@pytest.mark.parametrize(
    "section,mode,kind",
    [
        ("figures", "Scale figures", "scale"),
        ("figures", "Rotate figures", "rotate"),
        ("regions", "Move regions", "scale"),
        ("regions", "Rotate regions", "rotate"),
        ("pixels", "Scale raster regions", "scale"),
        ("pixels", "Rotate raster regions", "rotate"),
    ],
)
def test_each_center_fixed_with_undo_and_serialization(window, tmp_path, section, mode, kind):
    window.select_tool_set(section)
    window.select_all_elements()
    view, session = window.view, window.view.session
    original = session.geometry()
    window.activate_mode(mode, prompt=False)
    popup = window.show_tool_settings(mode)
    popup.individual_centers.setChecked(True)
    popup.accept()
    count = len(session.operations)
    if kind == "rotate":
        view.transform_regions(angle=10)
        view.transform_regions(angle=15)
    else:
        view.transform_regions(scale=0.5)
    assert len(session.operations) == count + 1
    result = session.geometry()
    if section == "pixels":
        assert result.walls == original.walls
        polygons = [p for _, p in view.raster_region_entries()]
        assert len(result.raster.parts) == 2
        encoded = json.loads(json.dumps(_encode(result)))
        assert _decode(encoded).raster == result.raster
        path = tmp_path / "raster.dale"
        save_project(session, path, window.project_ui_state())
        with load_project(path) as project:
            assert [
                op.raster
                for op in project.session.operations
                if getattr(op, "raster", None) is not None
            ] == [result.raster]
    else:
        polygons = (
            list(view.contour_figures()[i].area for i in range(2))
            if section == "figures"
            else list(view.region_polygons)
        )
    centers = sorted(
        ((p.bounds[0] + p.bounds[2]) / 2, (p.bounds[1] + p.bounds[3]) / 2) for p in polygons
    )
    for actual, expected in zip(centers, ((60, 60), (200, 60)), strict=True):
        assert actual == pytest.approx(expected)
    session.undo()
    assert session.geometry().walls == original.walls
    session.redo()
    assert session.geometry() == result


def test_raster_parts_capture_same_original_before_any_placement():
    first, second = box(10, 10, 30, 30), box(40, 10, 60, 30)
    image = Image.new("RGBA", (80, 40), (0, 0, 0, 0))
    image.paste((255, 0, 0, 255), (10, 10, 30, 30))
    image.paste((0, 255, 0, 255), (40, 10, 60, 30))
    # Swap the two objects: sequential recapture would copy the first over the second.
    parts = (
        (first.wkb, affine_matrix((20, 20), dx=30)),
        (second.wkb, affine_matrix((50, 20), dx=-30)),
    )
    operation = RasterTransform(
        unary_union((first, second)).wkb, affine_matrix((0, 0)), parts=parts
    )
    result = render_layered(
        image_reader(image, image.size), image.size, (operation,), (0, 0, *image.size), image.size
    )
    assert result.getpixel((20, 20)) == (0, 255, 0, 255)
    assert result.getpixel((50, 20)) == (255, 0, 0, 255)


@pytest.mark.parametrize("value", [{"figures_scale": 1}, {"unknown": True}, [], False])
def test_individual_settings_reject_invalid(value):
    with pytest.raises(ValueError):
        settings(value)


@pytest.mark.parametrize("invalid", ["count", "singular", "boolean", "unknown", "coordinate"])
def test_independent_raster_archive_validation(window, invalid):
    window.select_tool_set("pixels")
    window.select_all_elements()
    window.activate_mode("Scale raster regions", prompt=False)
    window.view.individual_transform_settings["pixels_scale"] = True
    window.view.transform_regions(scale=0.5)
    value = json.loads(json.dumps(_encode(window.view.session.geometry())))
    parts = value["raster_transform"]["parts"]
    if invalid == "count":
        parts.pop()
    elif invalid == "singular":
        parts[0]["matrix"] = [0, 0, 0, 0, 0, 0]
    elif invalid == "boolean":
        parts[0]["matrix"][0] = True
    elif invalid == "unknown":
        parts[0]["unknown"] = 1
    else:
        parts[0]["matrix"][4] = 1e12
    with pytest.raises(ValueError):
        _decode(value)


def test_empty_raster_captures_and_vector_edit_do_not_replay_raster(window, pair_factory):
    from itertools import pairwise

    source = pair_factory(
        size=(400, 300),
        walls=[
            {"c": [*a, *b]}
            for p in (box(30, 30, 50, 50), box(170, 30, 250, 110))
            for a, b in pairwise(p.exterior.coords)
        ],
    )
    assert window.load_sources(source.image_path, source.json_path)
    window.select_tool_set("pixels")
    window.select_all_elements()
    view = window.view
    window.activate_mode("Scale raster regions", prompt=False)
    view.individual_transform_settings["pixels_scale"] = True
    window.set_raster_offset(-15)
    view.transform_regions(scale=0.5)
    raster = view.session.geometry().raster
    assert _decode(json.loads(json.dumps(_encode(view.session.geometry())))).raster == raster
    window.select_tool_set("figures")
    window.select_all_elements()
    window.activate_mode("Scale figures", prompt=False)
    view.individual_transform_settings["figures_scale"] = True
    view.transform_regions(scale=0.5)
    assert view.session.geometry().raster is None


def test_asymmetric_connected_contours_keep_series_pivot():

    from dale.individual_transform import transform_contours
    from dale.region_transform import plan_figure_transform
    from dale.session import GeometryEdit

    geometry = GeometryEdit((((0, 0), (18, 0)), ((18, 0), (2, 7)), ((2, 7), (0, 0))))
    ids = tuple(r.id for r in geometry.lineage)
    expected, _, _ = transform_contours(
        plan_figure_transform(geometry, ids), figures=True, angle=25
    )
    first, _, pivots = transform_contours(
        plan_figure_transform(geometry, ids), figures=True, angle=10
    )
    result, _, final_pivots = transform_contours(
        plan_figure_transform(first, ids), figures=True, angle=15, centers=pivots
    )
    assert pivots == final_pivots
    for actual, wanted in zip(result.walls, expected.walls, strict=True):
        for point, reference in zip(actual, wanted, strict=True):
            assert point == pytest.approx(reference)
