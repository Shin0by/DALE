"""World rulers, source-anchored guides and independent dataset aid settings."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QTransform
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from dale.canvas import FIGURE_TOOLS, GEOMETRY_TOOLS, RASTER_TRANSFORM_TOOLS, REGION_TOOLS
from dale.measurement import grid_positions, measurement_scale, measurement_settings
from dale.ui import MainWindow, configure_application


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    if not app.property("catalog_test_style"):
        configure_application(app)
        app.setProperty("catalog_test_style", True)
    monkeypatch.setenv("DALE_SETTINGS_PATH", str(tmp_path / "prefs.json"))
    w = MainWindow()
    w.can_discard = lambda: True
    w.resize(1224, 768)
    w.show()
    monkeypatch.setattr(w, "warning", lambda *a: pytest.fail(str(a)))
    app.processEvents()
    yield w
    w.close()
    w.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.mark.parametrize(
    "unit,factor", [("px", 1), ("ft", 20), ("cm", 20 / 30.48), ("mm", 2 / 30.48)]
)
@pytest.mark.parametrize("legacy", [False, True])
def test_declared_world_scale_and_integer_snapping(pair_factory, unit, factor, legacy):
    grid = (
        {"grid": 100, "gridDistance": 5, "gridUnits": "ft"}
        if legacy
        else {"grid": {"size": 100, "distance": 5, "units": "ft"}}
    )
    source = pair_factory(size=(400, 300), **grid)
    scale = measurement_scale(source, unit)
    assert scale.pixels_per_unit == pytest.approx((factor, factor))
    assert scale.position(3, 0) == pytest.approx(3 * factor)
    assert scale.snap(factor * 3.2, 0) == pytest.approx(factor * 3)


@pytest.mark.parametrize(
    "grid",
    [
        None,
        {},
        100,
        {"size": 100, "distance": 5, "units": "unknown"},
        {"size": 100, "distance": False, "units": "ft"},
    ],
)
def test_world_scale_never_guesses_missing_metadata(pair_factory, grid):
    source = pair_factory(grid=grid)
    assert measurement_scale(source, "px").pixels_per_unit == (1, 1)
    with pytest.raises(ValueError):
        measurement_scale(source, "ft")


@pytest.mark.parametrize("step,zoom", [(0.000001, 0.005), (0.3, 0.1), (20, 1), (5, 16)])
def test_dense_grid_remains_bounded_at_exact_multiples(step, zoom):
    positions = grid_positions(0, 16384, step, zoom)
    assert len(positions) <= 4096
    assert all(abs(p / step - round(p / step)) < 1e-5 for p in positions)
    assert all((b - a) * zoom >= 8 - 1e-7 for a, b in zip(positions, positions[1:], strict=False))


@pytest.mark.parametrize(
    "value",
    [
        {"step": 0},
        {"step": True},
        {"crosshair": 1},
        {"move_guides": 1},
        {"isolate_regions": "true"},
        {"raster_offset": 4097},
        {"raster_offset": True},
        {"preview_grid": 1},
        {"preview_merge": 1},
        {"preview_naming": "unknown"},
        {"background_color": "white"},
        {"background_kind": "unknown"},
        {"selection": {"lines": [], "polygons": [], "pivot": [0, 0]}},
        {"unit": "in"},
        {"guides": [{"axis": "z", "position": 2}]},
        {"guides": [{"axis": "x", "position": float("nan")}]},
        {"guides": [{"axis": "x", "position": True}]},
        {"extra": True},
    ],
)
def test_invalid_aid_state_rejected(value):
    with pytest.raises(ValueError):
        measurement_settings(value)


def drag(widget, start, target, modifiers=Qt.KeyboardModifier.NoModifier):
    QTest.mousePress(widget, Qt.MouseButton.LeftButton, modifiers, pos=start)
    local = widget.mapFromGlobal(target)
    QApplication.sendEvent(
        widget,
        QMouseEvent(
            QEvent.Type.MouseMove,
            QPointF(local),
            QPointF(target),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton,
            modifiers,
        ),
    )
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, modifiers, pos=local)
    QApplication.processEvents()


@pytest.mark.parametrize("axis", [0, 1])
@pytest.mark.parametrize("zoom", [1, 2])
def test_real_ruler_drag_snap_move_cancel_delete_without_editing_image(
    window, pair_factory, axis, zoom
):
    source = pair_factory(size=(400, 300), grid={"size": 100, "distance": 5, "units": "ft"})
    assert window.load_sources(source.image_path, source.json_path)
    window.select_tool_set("pixels")
    window.rulers_action.trigger()
    view = window.view
    aids = view.raster_aids
    aids.configure(unit="ft", snap=True)
    view.setTransform(QTransform.fromScale(zoom, zoom))
    view.centerOn(200, 150)
    QApplication.processEvents()
    before = view.session.geometry(), tuple(view.session.operations), view.preview.tobytes()
    ruler = aids.rulers[1 - axis]
    target = view.viewport().mapToGlobal(view.mapFromScene(117, 87))
    drag(ruler, ruler.rect().center(), target)
    assert aids.settings["guides"] == [
        {"axis": "x" if axis == 0 else "y", "position": 120.0 if axis == 0 else 80.0}
    ]
    saved = aids.snapshot()
    position = saved["guides"][0]["position"]
    point = view.mapFromScene(position, 150) if axis == 0 else view.mapFromScene(200, position)
    QTest.mousePress(
        view.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, pos=point
    )
    assert aids.pending is not None and view.active_gesture
    QTest.keyClick(view, Qt.Key.Key_Escape)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert aids.snapshot() == saved
    point = view.mapFromScene(position, 150) if axis == 0 else view.mapFromScene(200, position)
    delete_target = ruler.mapToGlobal(ruler.rect().center())
    drag(view.viewport(), point, delete_target, Qt.KeyboardModifier.ControlModifier)
    assert aids.settings["guides"] == []
    assert (
        view.session.geometry(),
        tuple(view.session.operations),
        view.preview.tobytes(),
    ) == before


def test_ruler_popup_is_staged_and_aids_work_in_all_sections(window, pair_factory):
    source = pair_factory(size=(300, 300), grid={"size": 100, "distance": 5, "units": "ft"})
    assert window.load_sources(source.image_path, source.json_path)
    window.select_tool_set("pixels")
    window.rulers_action.trigger()
    window.crosshair_action.trigger()
    before = window.view.raster_aids.snapshot()
    dialog = window.show_tool_settings("Raster rulers")
    dialog.ruler_units.setCurrentIndex(dialog.ruler_units.findData("mm"))
    dialog.ruler_step.setValue(3)
    dialog.ruler_grid.setChecked(True)
    dialog.reject()
    QApplication.processEvents()
    assert window.view.raster_aids.snapshot() == before
    dialog = window.show_tool_settings("Raster rulers")
    dialog.ruler_units.setCurrentIndex(dialog.ruler_units.findData("mm"))
    dialog.ruler_step.setValue(3)
    dialog.ruler_grid.setChecked(True)
    dialog.accept()
    QApplication.processEvents()
    assert window.view.raster_aids.settings["unit"] == "mm"
    assert window.view.raster_aids.settings["step"] == 3
    assert window.view.viewportMargins().top() == 24 and window.view.viewportMargins().left() == 48
    for section in ("geometry", "figures", "regions", "pixels"):
        window.select_tool_set(section)
        assert window.view.viewportMargins().top() == 24
        assert all(b.isVisible() for b in window.view.raster_aids.rulers)
        assert window.view_toolbar.widgetForAction(window.crosshair_action).height() == 36
        assert window.view_toolbar.widgetForAction(window.rulers_action).height() == 36
    assert window.view.raster_aids.settings["grid"] and window.crosshair_action.isChecked()


@pytest.mark.parametrize("section", ["geometry", "figures", "regions", "pixels"])
@pytest.mark.parametrize("axis", [0, 1])
@pytest.mark.parametrize("unit", ["px", "ft", "cm", "mm"])
def test_guide_edit_mode_snaps_moves_cancels_deletes_without_map_edits(
    window, pair_factory, section, axis, unit
):
    source = pair_factory(size=(400, 300), grid={"size": 100, "distance": 5, "units": "ft"})
    assert window.load_sources(source.image_path, source.json_path)
    window.select_tool_set(section)
    window.rulers_action.trigger()
    dialog = window.show_tool_settings("Raster rulers")
    dialog.ruler_units.setCurrentIndex(dialog.ruler_units.findData(unit))
    dialog.ruler_snap.setChecked(True)
    dialog.accept()
    window.move_guides_action.trigger()
    view, aids = window.view, window.view.raster_aids
    view.setTransform(QTransform.fromScale(2, 2))
    view.centerOn(200, 150)
    aids.configure(guides=[{"axis": "x" if axis == 0 else "y", "position": 60.25}])
    QApplication.processEvents()
    before = tuple(view.session.operations), view.session.geometry(), window.selected_regions
    point = view.mapFromScene(60.25, 150) if axis == 0 else view.mapFromScene(200, 60.25)
    saved = aids.snapshot()
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert aids.pending is not None
    QTest.keyClick(view, Qt.Key.Key_Escape)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert aids.snapshot() == saved
    target = view.viewport().mapToGlobal(view.mapFromScene(117, 87))
    drag(view.viewport(), point, target)
    position = aids.settings["guides"][0]["position"]
    assert aids.scale().value(position, axis) == pytest.approx(
        round(aids.scale().value(117 if axis == 0 else 87, axis))
    )
    point = view.mapFromScene(position, 150) if axis == 0 else view.mapFromScene(200, position)
    # Match the native click/release/double-click sequence, not only the helper event.
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert not aids.settings["guides"]
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(250, 200))
    assert (
        tuple(view.session.operations),
        view.session.geometry(),
        window.selected_regions,
    ) == before
    commands = window.view_toolbar.actions()
    assert commands.index(window.move_guides_action) == commands.index(window.rulers_action) + 1


def wait_for(predicate):
    from time import monotonic, sleep

    end = monotonic() + 8
    while not predicate() and monotonic() < end:
        QTest.qWait(10)
        sleep(0.001)
    assert predicate()


@pytest.mark.parametrize("section", ["geometry", "figures", "regions", "pixels"])
def test_native_tiles_keep_real_pixels_alpha_camera_and_export(window, pair_factory, section):
    from PIL import Image, ImageChops

    from dale.raster import render_export_alpha
    from dale.session import Stroke

    source = pair_factory(size=(400, 300))
    assert window.load_sources(source.image_path, source.json_path)
    view = window.view
    view.preview = view.preview.resize((40, 30))
    window.select_tool_set(section)
    button = window.view_toolbar.widgetForAction(window.native_resolution_action)
    assert button.isVisibleTo(window) and button.size().toTuple() == (36, 36)
    assert window.view_toolbar.rect().contains(button.geometry())
    view.setTransform(QTransform.fromScale(2, 2))
    view.centerOn(200, 150)
    camera = view.camera_center(), view.transform()
    geometry = view.session.geometry()
    stroke = Stroke(((200, 150),), 70, False, "square", 0.4, 0.65)
    view.session.add(stroke)
    view.update_image()
    window.native_resolution_action.trigger()
    controller = view.native_preview
    wait_for(lambda: bool(controller.items) and not view.item.isVisible())
    assert (view.camera_center(), view.transform()) == camera
    assert view.session.geometry() == geometry and view.session.operations == [stroke]
    with Image.open(source.image_path) as original:
        expected = original.convert("RGBA")
    expected.putalpha(render_export_alpha(source.size, source.size, (stroke,)))
    width, height, data = controller.cache[(0, 0)]
    assert (
        ImageChops.difference(expected, Image.frombytes("RGBA", (width, height), data)).getbbox(
            alpha_only=False
        )
        is None
    )
    assert controller.items[(0, 0)].pixmap().width() == 400
    # Native alpha replaces the base image; transparent edits must not reveal its old preview.
    assert not view.item.isVisible()
    window.select_tool_set("regions")
    assert not view.item.isVisible() and all(i.isVisible() for i in controller.items.values())
    window.select_tool_set("pixels")
    wait_for(lambda: not view.item.isVisible())
    window.activate_mode("Erase")
    view.stroke = [(100, 100)]
    view.update_image()
    assert view.item.isVisible()
    assert not any(i.isVisible() for i in controller.items.values())
    controller.request()
    assert view.item.isVisible()
    view.cancel_pending()
    wait_for(lambda: not view.item.isVisible())
    view.session.undo()
    view.update_image()
    wait_for(
        lambda: bool(controller.cache) and controller.base[-1] == () and not view.item.isVisible()
    )
    assert controller.cache[(0, 0)][2][3::4] == bytes([255]) * (400 * 300)
    view.clear_map()
    assert not controller.items and controller.worker is None and controller.decoded is None


@pytest.mark.parametrize("mode", ["Erase", "Erase square", "Restore", "Restore square"])
def test_real_brush_gesture_popup_and_modified_wheel(window, pair_factory, mode):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QWheelEvent

    source = pair_factory(size=(400, 300))
    assert window.load_sources(source.image_path, source.json_path)
    window.activate_mode(mode)
    tile = window.sized_tools[mode]
    assert tile.width() == 48 and tile.height() == 60 and tile.editor().isVisible()
    assert tile.editor().size().toTuple() == (30, 16)
    assert tile.editor().geometry().center().x() == tile.rect().center().x()
    assert tile.rect().contains(tile.editor().geometry())
    assert tile.editor().rect().contains(tile.editor().lineEdit().geometry())
    from dale.toolbar import ToolSettingsCorner

    corner = tile.findChild(ToolSettingsCorner)
    assert not tile.editor().geometry().intersects(corner.geometry())
    editor = tile.editor().lineEdit()
    assert editor.fontMetrics().horizontalAdvance("4096") <= editor.width()
    dialog = window.show_tool_settings(mode)
    dialog.value.setValue(60)
    dialog.brush_feather.setValue(40)
    dialog.brush_opacity.setValue(55)
    dialog.accept()
    assert window.view.raster_brushes[mode] == {"feather": 40, "opacity": 55}
    dialog = window.show_tool_settings(mode)
    dialog.brush_feather.setValue(90)
    dialog.reject()
    assert window.view.raster_brushes[mode]["feather"] == 40
    view = window.view
    view.setTransform(QTransform.fromScale(1, 1))
    view.centerOn(200, 150)
    QApplication.processEvents()
    start = view.mapFromScene(160, 150)
    end = view.viewport().mapToGlobal(view.mapFromScene(220, 150))
    drag(view.viewport(), start, end)
    operation = view.session.operations[-1]
    assert operation.radius == 30 and operation.feather == 0.4 and operation.opacity == 0.55
    assert operation.shape == ("square" if mode.endswith("square") else "circle")
    assert operation.restore == mode.startswith("Restore")
    for modifier, delta in (
        (Qt.KeyboardModifier.ControlModifier, QPoint(0, 120)),
        (Qt.KeyboardModifier.AltModifier, QPoint(120, 0)),
    ):
        event = QWheelEvent(
            QPointF(start),
            QPointF(view.viewport().mapToGlobal(start)),
            QPoint(),
            delta,
            Qt.MouseButton.NoButton,
            modifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        QApplication.sendEvent(view.viewport(), event)
    assert view.raster_diameters[mode] > 60 and view.raster_brushes[mode]["feather"] == 45


def test_dataset_aids_profiles_and_guides_save_independently(window, pair_factory, tmp_path):
    source = pair_factory(size=(400, 300), grid={"size": 100, "distance": 5, "units": "ft"})
    assert window.load_sources(source.image_path, source.json_path)
    window.select_tool_set("pixels")
    first = window.catalog.active_key
    aids = window.view.raster_aids
    aids.configure(
        rulers=True,
        crosshair=True,
        move_guides=True,
        raster_offset=9,
        preview_grid=True,
        preview_merge=False,
        preview_json=False,
        preview_naming="group",
        background_kind="solid",
        background_color="#a3b4c5",
        unit="cm",
        grid=True,
        step=3,
        guides=[{"axis": "x", "position": 123.25}],
    )
    window.view.raster_brushes["Erase square"] = {"feather": 73, "opacity": 31}
    expected = aids.snapshot()
    window.catalog.capture(window.project_ui_state())
    other = window.catalog.create("Another")
    window.catalog.activate(other.id)
    from dale.raster import load_preview

    window.show_catalog_view(other, load_preview(other.session.source), False)
    assert not aids.settings["rulers"] and not aids.settings["guides"]
    assert window.view.raster_brushes["Erase square"] == {"feather": 0, "opacity": 100}
    window.catalog.capture(window.project_ui_state())
    draft = window.catalog.activate(first)
    window.show_catalog_view(draft, load_preview(draft.session.source), True)
    assert aids.snapshot() == expected
    assert window.view.raster_brushes["Erase square"] == {"feather": 73, "opacity": 31}
    window.project_path = tmp_path / "Raster aids.dale"
    assert window.save_project_file() and window.load_project_file(window.project_path)
    assert aids.snapshot() == expected
    assert window.view.raster_brushes["Erase square"] == {"feather": 73, "opacity": 31}


def test_selection_only_reuses_analysis_and_layer_cache(window, pair_factory, monkeypatch):
    import dale.canvas
    import dale.session
    from dale.editing import add_line

    source = pair_factory(size=(400, 300))
    assert window.load_sources(source.image_path, source.json_path)
    view = window.view
    first = view.session.analysis()
    view.selected_source_layer()
    counts = {"analysis": 0, "layers": 0}
    analyze, layers = dale.session.analyze_regions, dale.canvas.source_layers

    def count_analysis(*args, **kwargs):
        counts["analysis"] += 1
        return analyze(*args, **kwargs)

    def count_layers(*args, **kwargs):
        counts["layers"] += 1
        return layers(*args, **kwargs)

    monkeypatch.setattr(dale.session, "analyze_regions", count_analysis)
    monkeypatch.setattr(dale.canvas, "source_layers", count_layers)
    for _ in range(5):
        assert view.session.analysis() is first
        view.selected_source_layer()
    assert counts == {"analysis": 0, "layers": 0}
    view.session.add(add_line(view.session.geometry(), (100, 50), (200, 50)))
    assert view.session.analysis() is not first
    view.selected_source_layer()
    assert counts == {"analysis": 1, "layers": 1}
    view.session.undo()
    assert view.session.analysis() == first
    view.selected_source_layer()
    assert counts == {"analysis": 2, "layers": 2}


def test_native_cache_survives_geometry_drag_and_cleans_on_source_switch(window, pair_factory):
    from pathlib import Path

    source = pair_factory(size=(400, 300))
    assert window.load_sources(source.image_path, source.json_path)
    view = window.view
    view.preview = view.preview.resize((40, 30))
    view.setTransform(QTransform.fromScale(2, 2))
    view.centerOn(200, 150)
    window.native_resolution_action.trigger()
    controller = view.native_preview
    wait_for(lambda: bool(controller.items) and not view.item.isVisible())
    directory = Path(controller.decoded.workspace.name)
    view.drag_base = view.session.geometry()
    controller.request()
    assert not view.item.isVisible() and directory.exists()
    view.drag_base = None
    view.assign(view.session, view.preview)
    assert not directory.exists() and controller.worker is None and controller.decoded is None


@pytest.mark.parametrize("route", ["center", "scrollbars", "zoom"])
def test_native_tiles_follow_viewport_while_new_line_is_held(window, pair_factory, route):
    source = pair_factory(size=(1800, 1200))
    assert window.load_sources(source.image_path, source.json_path)
    view = window.view
    view.preview = view.preview.resize((180, 120))
    view.setTransform(QTransform.fromScale(1, 1))
    view.centerOn(250, 250)
    window.native_resolution_action.trigger()
    native = view.native_preview
    wait_for(lambda: bool(native.items) and not view.item.isVisible())
    original_tiles = native.wanted
    original = view.session.geometry()
    window.activate_mode("New line")
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(200, 200))
    assert view.line_start is not None and view.active_gesture
    if route == "center":
        view.centerOn(1400, 800)
        assert view.item.isVisible()  # Never expose an uncovered native tile while loading.
    elif route == "scrollbars":
        horizontal, vertical = view.horizontalScrollBar(), view.verticalScrollBar()
        horizontal.setValue(horizontal.value() + 1100)
        vertical.setValue(vertical.value() + 650)
    else:
        view.setTransform(QTransform.fromScale(0.4, 0.4))
    wait_for(
        lambda: (
            native.wanted != original_tiles
            and bool(native.items)
            and not view.item.isVisible()
            and all(tile in native.items for tile in native.wanted)
        )
    )
    assert view.line_start is not None and view.active_gesture
    assert view.session.geometry() == original and not view.session.operations
    QTest.keyClick(view, Qt.Key.Key_Escape)


@pytest.mark.parametrize(
    "mode",
    [
        "Pan",
        *GEOMETRY_TOOLS,
        *FIGURE_TOOLS,
        *REGION_TOOLS,
        "Select raster regions",
        *RASTER_TRANSFORM_TOOLS,
        "Erase",
        "Erase square",
        "Restore",
        "Restore square",
    ],
)
def test_native_tiles_load_during_right_pan_in_every_tool(window, pair_factory, mode):
    source = pair_factory(
        size=(1800, 1200),
        walls=[
            {"c": c}
            for c in (
                [100, 100, 500, 100],
                [500, 100, 500, 500],
                [500, 500, 100, 500],
                [100, 500, 100, 100],
            )
        ],
    )
    assert window.load_sources(source.image_path, source.json_path)
    view = window.view
    view.preview = view.preview.resize((180, 120))
    if mode in FIGURE_TOOLS:
        window.activate_mode("Select figures")
        view.figure_line_ids = tuple(r.id for r in view.session.geometry().lineage)
    elif mode in (*REGION_TOOLS, *RASTER_TRANSFORM_TOOLS):
        window.activate_mode(
            "Select raster regions" if mode in RASTER_TRANSFORM_TOOLS else "Select regions"
        )
        window.selected_regions = (0,)
    window.update_map_info()
    window.activate_mode(mode)
    assert view.mode == mode
    view.setTransform(QTransform.fromScale(1, 1))
    view.centerOn(250, 250)
    window.native_resolution_action.trigger()
    native = view.native_preview
    wait_for(lambda: bool(native.items) and not view.item.isVisible())
    original_tiles = native.wanted
    original = view.session.geometry()
    if mode not in (
        "Auto-close",
        "Rotate figures",
        "Rotate regions",
        "Rotate raster regions",
        "Scale raster regions",
    ):
        point = (
            (100, 100) if mode in ("Edit points", "Erase lines", "Erase vertices") else (200, 200)
        )
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=view.mapFromScene(*point))
    gesture = view.active_gesture
    start = view.viewport().rect().center()
    QTest.mousePress(view.viewport(), Qt.MouseButton.RightButton, pos=start)
    position = QPointF(-1500, -750)
    QApplication.sendEvent(
        view.viewport(),
        QMouseEvent(
            QEvent.Type.MouseMove,
            position,
            QPointF(view.viewport().mapToGlobal(position.toPoint())),
            Qt.MouseButton.NoButton,
            Qt.MouseButton.RightButton | Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    wait_for(
        lambda: (
            native.wanted != original_tiles
            and bool(native.items)
            and not view.item.isVisible()
            and all(tile in native.items for tile in native.wanted)
        )
    )
    assert view.panning and view.active_gesture == gesture
    assert native.base[-1] == view.preview_raster_operations()
    assert view.session.geometry() == original and not view.session.operations
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.RightButton, pos=start)
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert view.session.geometry() == original and not view.session.operations


def test_native_latest_request_restarts_after_zoom_changes(window, pair_factory, monkeypatch):
    from threading import Event

    import dale.native_preview

    original = dale.native_preview.NativeImageSource
    started, release = Event(), Event()

    def delayed(*args):
        started.set()
        assert release.wait(4)
        return original(*args)

    monkeypatch.setattr(dale.native_preview, "NativeImageSource", delayed)
    source = pair_factory(size=(400, 300))
    assert window.load_sources(source.image_path, source.json_path)
    view = window.view
    view.preview = view.preview.resize((40, 30))
    view.setTransform(QTransform.fromScale(2, 2))
    view.centerOn(200, 150)
    window.native_resolution_action.trigger()
    controller = view.native_preview
    wait_for(started.is_set)
    view.setTransform(QTransform.fromScale(0.4, 0.4))
    controller.request()
    release.set()
    wait_for(lambda: bool(controller.items) and not view.item.isVisible())
    assert controller.base[2] == 2
    assert controller.items[(0, 0)].pixmap().width() == 200


def test_wide_viewport_limits_native_worker_payload(window, pair_factory):
    from dale.native_preview import MAX_BATCH_TILES

    source = pair_factory(size=(5000, 3000))
    assert window.load_sources(source.image_path, source.json_path)
    window.resize(3300, 2300)
    QApplication.processEvents()
    window.view.setTransform(QTransform.fromScale(0.51, 0.51))
    window.view.centerOn(2500, 1500)
    window.native_resolution_action.trigger()
    native = window.view.native_preview
    native.request()
    assert len(native.wanted) > MAX_BATCH_TILES
    assert native.worker is not None and len(native.worker.tiles) == MAX_BATCH_TILES
    window.native_resolution_action.trigger()
