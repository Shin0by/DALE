"""Synthetic native-pixel cut transforms, history and actual Raster gestures."""

import json
import os
from dataclasses import replace
from itertools import pairwise

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PIL import Image, ImageChops
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QTransform
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shapely.affinity import affine_transform
from shapely.geometry import box

from dale.project_io import _decode, _encode, load_project, save_project
from dale.raster import alpha_bounds, export_png, raster_operations, render_preview
from dale.raster_transform import affine_matrix, crop_reader, image_reader, render_layered
from dale.session import RasterSelectionEdit, RasterTransform, RegionSelection, Session, Stroke
from dale.ui import MainWindow, configure_application


@pytest.mark.parametrize("action", ["rotate", "move", "scale"])
def test_raster_objects_replace_old_selection_without_editing_shared_scene_lines(
    window, pair_factory, tmp_path, action
):
    w, view = window, window.view
    # Two adjacent cells sharing a divider, plus a narrow corridor attached below.
    edges = [
        ((30, 30), (150, 30)),
        ((150, 30), (150, 150)),
        ((150, 150), (110, 150)),
        ((110, 150), (110, 230)),
        ((110, 230), (90, 230)),
        ((90, 230), (90, 150)),
        ((90, 150), (30, 150)),
        ((30, 150), (30, 30)),
        ((70, 30), (70, 150)),
        ((70, 150), (90, 150)),
        ((90, 150), (110, 150)),
    ]
    source = pair_factory(size=(400, 300), walls=[{"c": [*a, *b]} for a, b in edges])
    assert w.load_sources(source.image_path, source.json_path)
    view.setTransform(QTransform.fromScale(1, 1))
    view.centerOn(200, 150)
    QApplication.processEvents()
    w.select_tool_set("regions")
    w.select_all_elements()
    original_regions = view.region_polygons
    before_selection = w.region_selection_state()
    original = view.session.geometry()
    w.select_tool_set("pixels")
    w.select_all_elements()
    before_count = len(view.selectable_regions())
    mode = {
        "rotate": "Rotate raster regions",
        "move": "Move raster regions",
        "scale": "Scale raster regions",
    }[action]
    w.activate_mode(mode)
    pivot = view.selection_center()
    if action == "rotate":
        view.rotate_by_wheel(1, Qt.KeyboardModifier.AltModifier)
        view.rotate_by_wheel(1, Qt.KeyboardModifier.AltModifier)
        matrix = affine_matrix(pivot, angle=90)
    elif action == "scale":
        view.transform_regions(scale=0.75)
        matrix = affine_matrix(pivot, scale=0.75)
    else:
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(*pivot))
        QTest.mouseRelease(
            view.viewport(),
            Qt.MouseButton.LeftButton,
            pos=view.mapFromScene(pivot[0] + 80, pivot[1]),
        )
        matrix = affine_matrix(pivot, dx=80)
    operation = view.session.operations[-1]
    assert operation.raster is not None and len(operation.raster.cells) == before_count
    assert operation.walls == original.walls and operation.lineage == original.lineage
    assert len(view.selectable_regions()) == before_count
    expected = tuple(affine_transform(p, matrix) for p in original_regions)
    assert all(any(p.equals_exact(q, 1e-7) for q in view.selectable_regions()) for p in expected)
    assert view.session.source.json_bytes == source.json_bytes
    # Actual pixmap must already contain the transform, before toggling preview/refresh.
    actual = view.item.pixmap().toImage()
    rendered = render_preview(view.preview, source.size, view.display_raster_operations())
    assert actual.pixelColor(40, 40).alpha() == rendered.getpixel((40, 40))[3]
    w.select_tool_set("regions")
    assert view.region_polygons == original_regions
    assert w.selected_regions == before_selection["selected"]
    assert view.session.geometry().walls == original.walls
    w.select_tool_set("pixels")
    w.history(False)
    assert all(any(p.equals(q) for q in view.selectable_regions()) for p in original_regions)
    w.history(True)
    assert len(view.selectable_regions()) == before_count
    assert all(any(p.equals_exact(q, 1e-7) for q in view.selectable_regions()) for p in expected)
    path = tmp_path / (action + ".dale")
    w.project_path = path
    assert w.save_project_file() and w.load_project_file(path)
    assert view.session.geometry().walls == original.walls
    assert len(view.selectable_regions()) == before_count
    assert source.json_path.read_bytes() == source.json_bytes


def test_raster_group_keeps_its_cell_after_rotation_and_new_assignment(window):
    from dale.selection_groups import SelectionGroup

    w, view = window, window.view
    group = SelectionGroup.create("Raster cut", "#e0b040")
    w.store_selection_groups((group,))
    w.assign_selection_group(group.id, True)
    w.activate_mode("Rotate raster regions")
    view.rotate_by_wheel(1, Qt.KeyboardModifier.AltModifier)
    rotated = view.region_polygons
    w.clear_selection()
    w.select_selection_group(group.id)
    assert view.region_polygons == rotated
    group2 = SelectionGroup.create("After rotation", "#e040b0")
    w.store_selection_groups((*w.selection_groups(), group2))
    w.assign_selection_group(group2.id, True)
    w.clear_selection()
    w.select_selection_group(group2.id)
    assert view.region_polygons == rotated
    view.cursor_point = view.selection_center()
    assert view.copy_selected_regions()
    assert all(p.equals(q) for p, q in zip(view.region_clipboard.polygons, rotated, strict=True))
    assert all(not r.sources for r in view.region_clipboard.records)


@pytest.mark.parametrize("invalid", ["count", "unknown", "empty", "bad_polygon"])
def test_independent_raster_objects_validate_archive_metadata(window, tmp_path, invalid):
    w, view = window, window.view
    w.activate_mode("Rotate raster regions")
    view.rotate_by_wheel(1, Qt.KeyboardModifier.AltModifier)
    operation = view.session.operations[-1]
    encoded = json.loads(json.dumps(_encode(operation)))
    raster = encoded["raster_transform"]
    if invalid == "count":
        raster["regions"] *= 2
    elif invalid == "unknown":
        raster["cells"][0]["shell"] = ["unknown-line"]
        view.session.operations[-1] = _decode(encoded)
        path = tmp_path / "invalid.dale"
        save_project(view.session, path, w.ui_state())
        with pytest.raises(ValueError, match="unknown lines"):
            load_project(path)
        return
    elif invalid == "empty":
        raster["regions"] = []
    else:
        raster["regions"][0] = {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}
    with pytest.raises(ValueError):
        _decode(encoded)


def artwork(size=(160, 120)):
    image = Image.new("RGBA", size)
    image.putdata(
        [(x % 256, y % 256, (x + y) % 256, 255) for y in range(size[1]) for x in range(size[0])]
    )
    return image


@pytest.mark.parametrize("angle,scale", [(0, 1), (90, 1), (35, 0.7), (-45, 1.4)])
def test_native_pixels_geometry_history_archive_and_export(pair_factory, tmp_path, angle, scale):
    source = pair_factory(size=(160, 120))
    image = artwork()
    image_path = tmp_path / "exact.png"
    image.save(image_path)
    source = replace(source, image_path=image_path)
    session = Session(source)
    original = session.geometry()
    transform = RasterTransform(
        box(10, 10, 40, 40).wkb, affine_matrix((25, 25), dx=70, dy=30, angle=angle, scale=scale)
    )
    session.add(replace(original, raster=transform))
    ops = raster_operations(session.operations)
    expected = render_layered(
        image_reader(image, source.size), source.size, ops, (0, 0, *source.size), source.size
    )
    assert expected.getpixel((20, 20))[3] == 0
    assert expected.getpixel((140, 100)) == image.getpixel((140, 100))
    assert expected.getpixel((95, 55))[:3] == pytest.approx(image.getpixel((25, 25))[:3], abs=2)
    # Independent stripe/tile reads must not move the source sampling phase.
    striped = Image.new("RGBA", source.size)
    for y in range(0, 120, 17):
        stripe = render_layered(
            crop_reader(image, source.size),
            source.size,
            ops,
            (0, y, 160, min(y + 17, 120)),
            (160, min(17, 120 - y)),
        )
        striped.paste(stripe, (0, y))
    assert ImageChops.difference(expected, striped).getbbox(alpha_only=False) is None
    destination = tmp_path / "transformed.png"
    export_png(source, ops, destination)
    with Image.open(destination) as actual:
        assert ImageChops.difference(expected, actual).getbbox(alpha_only=False) is None
    assert (
        alpha_bounds(source.size, ops, (0, 0, *source.size), source_path=image_path)
        == expected.getbbox()
    )
    assert _decode(json.loads(json.dumps(_encode(session.operations[-1])))).raster == transform
    project = tmp_path / "transformed.dale"
    save_project(session, project, {})
    with load_project(project) as loaded:
        assert raster_operations(loaded.session.operations) == ops
    session.undo()
    assert not raster_operations(session.operations)
    session.redo()
    assert raster_operations(session.operations) == ops
    for _ in range(110):
        session.add(Stroke(((150, 110),), 1))
    assert raster_operations(session.operations)[0] == transform
    assert sum(op.raster is not None for op in session.operations if hasattr(op, "raster")) == 1


@pytest.fixture
def window(tmp_path, monkeypatch, pair_factory):
    app = QApplication.instance() or QApplication([])
    configure_application(app)
    app.setProperty("catalog_test_style", True)
    monkeypatch.setenv("DALE_SETTINGS_PATH", str(tmp_path / "prefs.json"))
    w = MainWindow()
    w.can_discard = lambda: True
    w.warning = lambda *args: pytest.fail(str(args))
    w.resize(1224, 768)
    w.show()
    region = box(30, 30, 90, 90)
    source = pair_factory(
        size=(400, 300),
        grid={"size": 100, "distance": 5, "units": "ft"},
        walls=[{"c": [*a, *b]} for a, b in pairwise(region.exterior.coords)],
    )
    assert w.load_sources(source.image_path, source.json_path)
    w.select_tool_set("pixels")
    w.selected_regions = (0,)
    w.update_map_info()
    w.view.setTransform(QTransform.fromScale(1, 1))
    w.view.centerOn(200, 150)
    app.processEvents()
    yield w
    w.close()
    w.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_raster_drag_cancel_rotation_batch_scale_and_independent_offset(window, tmp_path):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent

    w, view = window, window.view
    w.activate_mode("Move raster regions")
    assert w.current_tool_set == "pixels"
    popup = w.show_tool_settings("Raster artwork offset")
    popup.value.setValue(4)
    popup.accept()
    assert w.raster_contour_offset.value() == view.raster_aids.settings["raster_offset"] == 4
    assert w.contour_offset.value() == view.session.contour_offset == 0
    start, target = view.mapFromScene(60, 60), view.mapFromScene(120, 100)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QApplication.sendEvent(
        view.viewport(),
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(target),
            QPointF(view.viewport().mapToGlobal(target)),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    assert view.edit_preview.raster is not None
    QTest.keyClick(view, Qt.Key.Key_Escape)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=target)
    assert not view.session.operations
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=target)
    operation = view.session.operations[-1]
    assert operation.raster.matrix == (1, 0, 0, 1, 60, 40)
    from dale.raster_transform import area_of

    assert area_of(operation.raster.area_wkb).bounds == (26, 26, 94, 94)
    result = render_preview(
        view.preview, view.session.source.size, raster_operations(view.session.operations)
    )
    assert result.getpixel((60, 60))[3] == 0
    assert view.region_polygons[0].bounds == (90, 70, 150, 130)
    w.activate_mode("Rotate raster regions")
    for _ in range(3):
        view.rotate_by_wheel(1, Qt.KeyboardModifier.AltModifier)
    assert len(view.session.operations) == 2 and view.rotation_caption() == "135.00°"
    assert view.session.operations[-1].raster.matrix == pytest.approx(
        affine_matrix(view.region_pivot, angle=135)
    )
    w.activate_mode("Scale raster regions")
    view.transform_regions(scale=1.2)
    assert len(view.session.operations) == 3
    assert view.session.operations[-1].raster is not None
    polygons = tuple(p.wkb for p in view.region_polygons)
    w.project_path = tmp_path / "Raster selection.dale"
    assert w.save_project_file() and w.load_project_file(w.project_path)
    assert view.detached_selection is None
    assert tuple(p.wkb for p in view.region_polygons) == polygons
    assert view.raster_aids.settings["raster_offset"] == 4


def test_preview_independent_settings_selection_and_no_export_edits(window):
    w, view = window, window.view
    before = tuple(view.session.operations)
    w.isolate_raster_action.trigger()
    assert view.item.pixmap().toImage().pixelColor(200, 200).alpha() == 0
    assert view.item.pixmap().toImage().pixelColor(60, 60).alpha() == 255
    popup = w.show_tool_settings("Preview selected regions")
    popup.grid.setChecked(True)
    popup.json_export.setChecked(False)
    popup.accept()
    assert not w.size_to_grid and w.include_json
    assert (
        view.raster_aids.settings["preview_grid"] and not view.raster_aids.settings["preview_json"]
    )
    popup = w.show_tool_settings("Export selected regions")
    assert not popup.grid.isChecked() and popup.json_export.isChecked()
    popup.reject()
    w.clear_selection()
    assert view.item.pixmap().toImage().pixelColor(200, 200).alpha() == 255
    assert tuple(view.session.operations[:-1]) == before
    assert isinstance(view.session.operations[-1], RasterSelectionEdit)


def test_ctrl_wheel_on_raster_offset_changes_only_its_own_value(window):
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent

    w = window
    w.activate_mode("Move raster regions")
    button = w.raster_offset_button
    local = button.rect().center()
    event = QWheelEvent(
        QPointF(local),
        QPointF(button.mapToGlobal(local)),
        QPoint(),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(button, event)
    assert w.raster_contour_offset.value() == 1 and w.contour_offset.value() == 0
    assert not w.view.session.operations


@pytest.mark.parametrize("offset", [-4, 0, 4])
@pytest.mark.parametrize("grid", [False, True])
def test_preview_native_tile_and_png_are_identical_after_cut_rotation(
    window, tmp_path, offset, grid
):
    from dale.native_preview import NativeTileWorker
    from dale.overlay_export import prepare_overlay, selected_export_regions

    w, view = window, window.view
    w.activate_mode("Move raster regions")
    view.raster_aids.configure(raster_offset=offset)
    view.transform_regions(angle=35)
    w.isolate_raster_action.trigger()
    view.raster_aids.configure(preview_grid=grid)
    w.update_map_info()
    operations = view.display_raster_operations()
    expected = render_preview(view.preview, view.session.source.size, operations)
    polygon = selected_export_regions(view.region_polygons, offset)[0][1]
    bounds, exported_operations, _ = prepare_overlay(view.session, polygon, size_to_grid=grid)
    path = tmp_path / "exact-preview.png"
    export_png(view.session.source, exported_operations, path, crop=bounds)
    with Image.open(path) as exported:
        assert (
            ImageChops.difference(expected.crop(bounds), exported).getbbox(alpha_only=False) is None
        )
    worker = NativeTileWorker(
        view.session.source, operations, (None, None, 1), [(0, 0)], None, view
    )
    try:
        worker.run()
        assert not worker.error
        width, height, pixels = worker.frames[(0, 0)]
        native = Image.frombytes("RGBA", (width, height), pixels)
        assert ImageChops.difference(expected, native).getbbox(alpha_only=False) is None
    finally:
        if worker.decoded is not None:
            worker.decoded.close()


def test_background_staged_color_choice_and_dataset_project_restore(window, tmp_path, monkeypatch):
    from PySide6.QtGui import QColor

    w = window
    popup = w.show_tool_settings("Canvas background")
    popup.background_kind.setCurrentIndex(1)
    popup.background_color = "#aabbcc"
    popup.reject()
    assert w.view.raster_aids.settings["background_kind"] == "checker"
    popup = w.show_tool_settings("Canvas background")
    popup.background_kind.setCurrentIndex(1)
    monkeypatch.setattr(w, "choose_project_color", lambda *a: QColor("#aabbcc"))
    popup.background_color_button.click()
    assert popup.isVisible()
    popup.accept()
    assert w.view.backgroundBrush().color().name() == "#aabbcc"
    w.project_path = tmp_path / "Background.dale"
    assert w.save_project_file() and w.load_project_file(w.project_path)
    assert w.view.backgroundBrush().color().name() == "#aabbcc"


def test_real_background_color_dialog_keeps_the_settings_popup_staged(window):
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QColorDialog

    popup = window.show_tool_settings("Canvas background")
    popup.background_kind.setCurrentIndex(1)

    def accept_color():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QColorDialog)
        dialog.setCurrentColor(QColor("#123456"))
        dialog.accept()

    QTimer.singleShot(0, accept_color)
    popup.background_color_button.click()
    assert popup.isVisible() and popup.background_color == "#123456"
    assert window.view.raster_aids.settings["background_kind"] == "checker"
    popup.reject()


def test_exact_bounds_cache_includes_raster_changes_even_with_unchanged_contours(window):
    w, view = window, window.view
    w.update_map_info()
    key = w.bounds_preview.current_key
    geometry = view.session.geometry()
    view.session.add(
        replace(geometry, raster=RasterTransform(box(30, 30, 90, 90).wkb, (1, 0, 0, 1, 100, 0)))
    )
    w.update_map_info()
    assert view.session.geometry() == geometry
    assert w.bounds_preview.current_key != key
    assert any(isinstance(op, RasterTransform) for op in w.bounds_preview.current_key[5])


@pytest.mark.parametrize("language", ["ru", "en"])
def test_empty_tooltip_sections_are_omitted(language):
    from dale.localization import format_tooltip

    tooltip = format_tooltip(["Run this command."], language, title="Apply")
    assert len(tooltip.splitlines()) == 2


def test_repeated_cut_moves_reuse_bounded_immutable_prefixes():
    image = artwork()
    operations = tuple(
        RasterTransform(box(10 + i, 10, 40 + i, 40).wkb, (1, 0, 0, 1, 1, 0)) for i in range(20)
    )
    reads = []
    original = crop_reader(image, image.size)

    def read(bounds, size):
        reads.append(size)
        return original(bounds, size)

    result = render_layered(read, image.size, operations, (0, 0, *image.size), image.size)
    assert result.getpixel((45, 25))[:3] == image.getpixel((25, 25))[:3]
    assert len(reads) < 1000


def test_long_raster_state_and_cancellation_do_not_use_python_recursion():
    image = artwork((64, 64))
    transform = RasterTransform(box(10, 10, 40, 40).wkb, (1, 0, 0, 1, 0, 0))
    operations = (transform,) * 600
    result = render_layered(
        crop_reader(image, image.size), image.size, operations, (0, 0, 64, 64), image.size
    )
    assert result.getpixel((25, 25)) == image.getpixel((25, 25))
    checks = []

    def cancelled():
        checks.append(True)
        return len(checks) > 5

    with pytest.raises(InterruptedError):
        render_layered(
            crop_reader(image, image.size),
            image.size,
            operations,
            (0, 0, 64, 64),
            image.size,
            cancelled,
        )


def test_disk_reader_downsamples_before_allocating_source_pixels(window, monkeypatch):
    from dale.native_image import NativeImageSource

    decoded = NativeImageSource(window.view.session.source)
    try:
        monkeypatch.setattr(decoded, "crop", lambda *a: pytest.fail("Unbounded native crop"))
        result = crop_reader(decoded, window.view.session.source.size)((0, 0, 400, 300), (20, 15))
        assert result.size == (20, 15) and result.getpixel((10, 10))[3] == 255
    finally:
        decoded.close()


@pytest.mark.parametrize(
    "section,selection,move,rotate",
    [
        ("figures", "Select figures", "Move figures", "Rotate figures"),
        ("regions", "Select regions", "Move regions", "Rotate regions"),
        ("pixels", "Select raster regions", "Move raster regions", "Rotate raster regions"),
    ],
)
def test_mode_shortcuts_are_scoped_and_tabs_bottom_aligned(
    window, section, selection, move, rotate
):
    w = window
    w.select_tool_set(section)
    if section == "figures":
        w.view.figure_line_ids = tuple(r.id for r in w.view.session.geometry().lineage)
    else:
        w.selected_regions = (0,)
        w.update_map_info()
    for key, mode in ((Qt.Key.Key_M, move), (Qt.Key.Key_R, rotate), (Qt.Key.Key_S, selection)):
        w.view.setFocus()
        QTest.keyClick(w.view, key)
        assert w.view.mode == mode
    active = w.tool_set_toolbar.widgetForAction(w.tool_set_actions[section])
    assert active.height() == 36
    QApplication.processEvents()
    w.tool_set_toolbar.repaint()
    assert not hasattr(w.tool_set_toolbar, "indicator")
    assert all(
        w.tool_set_toolbar.widgetForAction(a).height() == 32
        for key, a in w.tool_set_actions.items()
        if key != section
    )
    assert w.region_output_toolbar.widgetForAction(w.export_regions_action).width() == 48
    assert w.raster_offset_button.width() == 48


@pytest.mark.parametrize("language", ["ru", "en"])
def test_mode_tab_accent_is_clipped_and_leaves_no_ghosts(window, language):
    w = window
    w.set_language(language, persist=False)
    QTest.mouseMove(w.view.viewport(), w.view.viewport().rect().center())
    toolbar = w.tool_set_toolbar
    for section in w.tool_set_actions:
        w.select_tool_set(section)
        QApplication.processEvents()
        reference = toolbar.grab().toImage()
        active = toolbar.widgetForAction(w.tool_set_actions[section])
        image = active.grab().toImage()
        # The accent is below the label and reaches both bottom corners.
        background = image.pixelColor(active.width() // 2, 3)
        for x in (active.width() // 4, active.width() // 2, 3 * active.width() // 4):
            assert image.pixelColor(x, active.height() - 3).lightness() > background.lightness()
        assert image.pixelColor(0, 0) != image.pixelColor(0, active.height() - 1)
        for other in (*w.tool_set_actions, *reversed(w.tool_set_actions)):
            w.select_tool_set(other)
            QApplication.processEvents()
        w.select_tool_set(section)
        QApplication.processEvents()
        assert toolbar.grab().toImage() == reference
    for bar, control in (
        (w.dataset_toolbar, w.dataset_control),
        (w.groups_toolbar, w.group_control),
    ):
        assert control.isVisibleTo(bar)
        assert control.geometry().right() < bar.width()


@pytest.mark.parametrize("command", ["click", "marquee", "all", "dropdown", "group", "clear"])
def test_raster_selection_commands_are_single_undoable_steps(window, command):
    w, session = window, window.view.session
    if command != "clear":
        w.selected_regions = ()
        w.update_map_info()
    if command == "group":
        from dale.selection_groups import SelectionGroup

        group = SelectionGroup(
            "group-" + "1" * 32,
            "Raster",
            "#ff0000",
            tuple(r.id for r in session.geometry().lineage),
        )
        w.store_selection_groups((group,))
    before, count = w.raster_selection_snapshot(), len(session.operations)
    if command == "click":
        w.activate_mode("Select raster regions")
        QTest.mouseClick(
            w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(60, 60)
        )
    elif command == "marquee":
        w.select_regions_in_box({"phase": "begin"})
        for bounds in ((0, 0, 50, 50), (0, 0, 100, 100), (0, 0, 110, 110)):
            w.select_regions_in_box({"phase": "preview", "bounds": bounds})
        assert len(session.operations) == count
        w.select_regions_in_box({"phase": "finish"})
    elif command == "all":
        w.select_all_elements()
    elif command == "dropdown":
        w.select_region(1)
    elif command == "group":
        w.select_selection_group(group.id)
    else:
        w.clear_selection_action.trigger()
    after = w.raster_selection_snapshot()
    assert after != before
    assert len(session.operations) == count + 1
    assert isinstance(session.operations[-1], RasterSelectionEdit)
    w.history(False)
    assert w.raster_selection_snapshot() == before
    w.history(True)
    assert w.raster_selection_snapshot() == after
    assert session.geometry().walls == session.source.image_walls(session.origin)
    assert raster_operations(session.operations) == ()


def test_raster_empty_click_question_cancel_confirm_and_keyboard_history(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    w, session = window, window.view.session
    w.activate_mode("Select raster regions")
    calls = []

    def question(*args):
        calls.append(args)
        assert w.t(args[1]) == "Желаете отменить выделение всех областей?"
        return _answer

    w.set_language("ru", persist=False)
    monkeypatch.setattr(w, "question", question)
    before, geometry = w.raster_selection_snapshot(), session.geometry()
    for _answer in (QMessageBox.StandardButton.No, QMessageBox.StandardButton.Cancel):
        QTest.mouseClick(
            w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(200, 200)
        )
        assert w.raster_selection_snapshot() == before
        assert not session.operations
    _answer = QMessageBox.StandardButton.Yes
    QTest.mouseClick(
        w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(200, 200)
    )
    assert not w.view.region_polygons and len(session.operations) == 1
    QTest.mouseClick(
        w.view.viewport(), Qt.MouseButton.LeftButton, pos=w.view.mapFromScene(200, 200)
    )
    assert len(calls) == 3 and len(session.operations) == 1
    w.view.setFocus()
    QTest.keyClick(w.view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert w.raster_selection_snapshot() == before
    QTest.keyClick(w.view, Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    assert not w.view.region_polygons
    assert session.geometry() == geometry


def test_raster_marquee_cancel_noop_and_redo_branch(window):
    w, session = window, window.view.session
    before = w.raster_selection_snapshot()
    for finish in ("cancel", "finish"):
        w.select_regions_in_box({"phase": "begin"})
        w.select_regions_in_box({"phase": "preview", "bounds": (0, 0, 100, 100)})
        if finish == "finish":
            w.select_regions_in_box({"phase": "preview", "bounds": (200, 200, 250, 250)})
        w.select_regions_in_box({"phase": finish})
        assert w.raster_selection_snapshot() == before
        assert not session.operations
    w.clear_selection()
    w.history(False)
    assert len(session.future) == 1
    session.add(Stroke(((200, 200),), 3))
    assert not session.future


def test_raster_selection_interleaves_with_raster_edits_and_persists_redo(window, tmp_path):
    w, session = window, window.view.session
    selected = w.raster_selection_snapshot()
    stroke = Stroke(((200, 200),), 3)
    session.add(stroke)
    w.clear_selection()
    w.history(False)
    assert w.raster_selection_snapshot() == selected
    assert raster_operations(session.operations) == (stroke,)
    w.history(False)
    assert not raster_operations(session.operations)
    path = tmp_path / "selection-history.dale"
    save_project(session, path, w.ui_state())
    with load_project(path) as loaded:
        assert loaded.session.future == session.future
        loaded.session.redo()
        assert raster_operations(loaded.session.operations) == (stroke,)
        loaded.session.redo()
        assert loaded.session.operations[-1].after == RegionSelection()
    w.history(True)
    w.history(True)
    assert not w.view.region_polygons
    for _ in range(105):
        w.toggle_region_at((60, 60))
    assert len(session.operations) - session.history_floor == 100
    assert raster_operations(session.operations) == (stroke,)
    save_project(session, path, w.ui_state())
    with load_project(path) as loaded:
        assert len(loaded.session.operations) - loaded.session.history_floor == 100


def test_raster_selection_undo_restores_detached_shape_and_isolates_other_sections(
    window, tmp_path
):
    from dale.region_transform import plan_region_transform

    w, session = window, window.view.session
    plan = plan_region_transform(session.geometry(), w.view.region_polygons, w.regions)
    geometry, polygons = plan.apply(dx=40, dy=10)
    session.add(geometry)
    w.view.refresh()
    w.select_transformed_regions(
        {
            "polygons": polygons,
            "line_ids": tuple(r.id for r in geometry.lineage),
            "pivot": (100, 70),
        }
    )
    before = w.raster_selection_snapshot()
    assert before.detached
    w.clear_selection()
    w.select_tool_set("regions")
    w.selected_regions = (0,)
    w.update_map_info()
    regions = w.region_selection_state()
    w.history(False)
    assert w.current_tool_set == "pixels" and w.view.mode == "Select raster regions"
    assert w.raster_selection_snapshot() == before
    assert w._region_selection_states["regions"] == regions
    path = tmp_path / "detached-selection-history.dale"
    save_project(session, path, w.ui_state())
    with load_project(path) as loaded:
        assert loaded.session.future[-1].before == before
        assert loaded.session.geometry().walls == geometry.walls
    w.history(True)
    assert not w.view.region_polygons


@pytest.mark.parametrize("invalid", ["boolean", "polygon", "range", "lines", "unknown"])
def test_raster_selection_history_validation(invalid):
    value = json.loads(
        json.dumps(
            _encode(RasterSelectionEdit(RegionSelection(), RegionSelection((box(1, 1, 2, 2).wkb,))))
        )
    )
    if invalid == "boolean":
        value["after"]["detached"] = 1
    elif invalid == "polygon":
        value["after"]["polygons"] = [{"type": "LineString", "coordinates": [[0, 0], [1, 1]]}]
    elif invalid == "range":
        value["after"]["polygons"] = [
            json.loads(json.dumps(box(1e10, 1e10, 2e10, 2e10).__geo_interface__))
        ]
    elif invalid == "lines":
        value["after"]["lines"] = ["unknown"]
    else:
        value["extra"] = True
    with pytest.raises(ValueError):
        _decode(value)
