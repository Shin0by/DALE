"""Grid appearance and the shared, project-owned color-dialog palette."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QTransform
from PySide6.QtWidgets import QApplication, QColorDialog

from dale.project_io import load_project, save_project
from dale.raster import load_preview
from dale.ui import MainWindow, configure_application


@pytest.fixture
def window(tmp_path, monkeypatch, pair_factory):
    app = QApplication.instance() or QApplication([])
    if not app.property("catalog_test_style"):
        configure_application(app)
        app.setProperty("catalog_test_style", True)
    monkeypatch.setenv("DALE_SETTINGS_PATH", str(tmp_path / "preferences.json"))
    w = MainWindow()
    w.can_discard = lambda: True
    w.warning = lambda *args: pytest.fail(str(args))
    w.resize(1224, 768)
    w.show()
    source = pair_factory(size=(300, 300), grid=75)
    assert w.load_sources(source.image_path, source.json_path)
    app.processEvents()
    yield w
    w.close()
    w.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def choose_color(open_picker, expected, changed, selected, accepted):
    errors = []

    def answer():
        dialog = QApplication.activeModalWidget()
        try:
            assert isinstance(dialog, QColorDialog)
            assert QColorDialog.customColor(0).name() == expected
            QColorDialog.setCustomColor(0, QColor(changed))
            QColorDialog.setCustomColor(15, QColor("#abcdef"))
            dialog.setCurrentColor(QColor(selected))
            dialog.accept() if accepted else dialog.reject()
        except BaseException as exc:
            errors.append(exc)
            if dialog:
                dialog.reject()

    QTimer.singleShot(0, answer)
    open_picker()
    assert not errors, errors


@pytest.mark.parametrize("language", ["ru", "en"])
@pytest.mark.parametrize("accepted", [False, True])
@pytest.mark.parametrize("applied", [False, True])
def test_grid_background_groups_share_palette_even_when_color_or_settings_cancelled(
    window, tmp_path, language, accepted, applied
):
    w = window
    w.set_language(language, persist=False)
    w.create_selection_group()
    group = w.selection_groups()[0]
    before = w.view.session.geometry(), tuple(w.view.session.operations)
    choose_color(lambda: w.change_group_color(group.id), "#ffffff", "#123456", "#34aa65", True)
    popup = w.show_tool_settings("Canvas background")
    popup.background_kind.setCurrentIndex(1)
    choose_color(popup.background_color_button.click, "#123456", "#2184ac", "#aabbcc", False)
    assert popup.isVisible() and popup.background_color == "#303030"
    popup.reject()
    w.saved_state = w.document_state()
    popup = w.show_tool_settings("Scene grid")
    assert popup.grid_color == "#e5bd78"
    choose_color(popup.grid_color_button.click, "#2184ac", "#be3050", "#00ff00", accepted)
    assert popup.isVisible() and w.tool_settings_popup is popup
    assert popup.grid_color == ("#00ff00" if accepted else "#e5bd78")
    assert w.view.raster_aids.settings["export_grid_color"] == "#e5bd78"
    popup.accept() if applied else popup.reject()
    color = "#00ff00" if accepted and applied else "#e5bd78"
    assert w.view.raster_aids.settings["export_grid_color"] == color
    assert w.custom_colors[0] == "#ffbe3050" and w.custom_colors[15] == "#ffabcdef"
    assert w.document_state() != w.saved_state
    first = w.catalog.active_key
    w.catalog.capture(w.project_ui_state())
    other = w.catalog.create("Another")
    w.catalog.activate(other.id)
    w.show_catalog_view(other, load_preview(other.session.source), False)
    assert w.view.raster_aids.settings["export_grid_color"] == "#e5bd78"
    choose_color(
        lambda: w.choose_project_color(QColor("white"), "Shared colors"),
        "#be3050",
        "#be3050",
        "#ffffff",
        False,
    )
    draft = w.catalog.activate(first)
    w.show_catalog_view(draft, load_preview(draft.session.source), True)
    assert w.view.raster_aids.settings["export_grid_color"] == color
    w.project_path = tmp_path / "Shared palette.dale"
    assert w.save_project_file() and w.load_project_file(w.project_path)
    assert w.view.raster_aids.settings["export_grid_color"] == color
    choose_color(
        lambda: w.change_group_color(w.selection_groups()[0].id),
        "#be3050",
        "#be3050",
        "#ffffff",
        False,
    )
    assert (w.view.session.geometry(), tuple(w.view.session.operations)) == before


@pytest.mark.parametrize("transparency", [0, 56, 100])
@pytest.mark.parametrize("width", [1, 4])
@pytest.mark.parametrize("zoom", [0.5, 2])
def test_grid_color_renders_in_every_mode_without_tinting_image_or_changing_export(
    window, transparency, width, zoom
):
    from dale.overlay_export import prepare_overlay

    w, view = window, window.view
    w.grid_action.trigger()
    view.setTransform(QTransform.fromScale(zoom, zoom))
    view.centerOn(150, 150)
    view.raster_aids.configure(
        export_grid_color="#00ff00", export_grid_transparency=transparency, export_grid_width=width
    )
    before = view.item.pixmap().toImage()
    original = (
        view.session.source.image_path.read_bytes(),
        view.session.source.json_path.read_bytes(),
    )
    polygon = view.session.analysis().area
    bounds = prepare_overlay(view.session, polygon, size_to_grid=True)
    for section in ("geometry", "figures", "regions", "pixels"):
        w.select_tool_set(section)
        QApplication.processEvents()
        image = QImage(view.viewport().size(), QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        view.raster_aids.draw(painter)
        painter.end()
        point = view.mapFromScene(75, 70)
        pixels = [image.pixelColor(point.x() + dx, point.y()) for dx in range(-6, 7)]
        visible = [color for color in pixels if color.alpha()]
        alpha = round(255 * (100 - transparency) / 100)
        assert len(visible) == (width if alpha else 0)
        assert all(color.getRgb() == (0, 255, 0, alpha) for color in visible)
        assert view.item.pixmap().toImage() == before
        assert prepare_overlay(view.session, polygon, size_to_grid=True) == bounds
    assert original == (
        view.session.source.image_path.read_bytes(),
        view.session.source.json_path.read_bytes(),
    )


@pytest.mark.parametrize("language", ["ru", "en"])
def test_grid_appearance_is_staged_and_restored_per_dataset_and_project(window, tmp_path, language):
    w, aids = window, window.view.raster_aids
    w.set_language(language, persist=False)
    popup = w.show_tool_settings("Scene grid")
    popup.grid_transparency.setValue(75)
    popup.grid_width.setValue(4)
    popup.reject()
    assert aids.settings["export_grid_transparency"] == 56
    assert aids.settings["export_grid_width"] == 1
    popup = w.show_tool_settings("Scene grid")
    popup.grid_transparency_slider.setValue(25)
    assert popup.grid_transparency.value() == 25
    popup.grid_transparency.setValue(37)
    assert popup.grid_transparency_slider.value() == 37
    popup.grid_width.setValue(3)
    popup.accept()
    assert aids.settings["export_grid_transparency"] == 37
    assert aids.settings["export_grid_width"] == 3
    first = w.catalog.active_key
    w.catalog.capture(w.project_ui_state())
    other = w.catalog.create("Other appearance")
    w.catalog.activate(other.id)
    w.show_catalog_view(other, load_preview(other.session.source), False)
    assert aids.settings["export_grid_transparency"] == 56
    assert aids.settings["export_grid_width"] == 1
    draft = w.catalog.activate(first)
    w.show_catalog_view(draft, load_preview(draft.session.source), True)
    w.project_path = tmp_path / "Grid appearance.dale"
    assert w.save_project_file() and w.load_project_file(w.project_path)
    popup = w.show_tool_settings("Scene grid")
    assert popup.grid_transparency.value() == 37
    assert popup.grid_transparency_slider.value() == 37
    assert popup.grid_width.value() == 3
    popup.reject()


@pytest.mark.parametrize(
    "key,value",
    [
        ("export_grid_transparency", -1),
        ("export_grid_transparency", 101),
        ("export_grid_transparency", True),
        ("export_grid_width", 0),
        ("export_grid_width", 17),
        ("export_grid_width", 1.5),
    ],
)
def test_invalid_grid_appearance_is_rejected_when_opening_project(window, tmp_path, key, value):
    path = tmp_path / "Invalid grid appearance.dale"
    save_project(window.view.session, path, {"raster_aids": {key: value}})
    with pytest.raises(ValueError, match="grid appearance"):
        load_project(path)


@pytest.mark.parametrize("color", [None, False, "red", "#1234", "#ff112233", "#gg1234"])
def test_invalid_grid_color_is_rejected_when_opening_project(window, tmp_path, color):
    path = tmp_path / "Protected.dale"
    save_project(window.view.session, path, {"raster_aids": {"export_grid_color": color}})
    before = path.read_bytes()
    with pytest.raises(ValueError, match="grid color"):
        load_project(path)
    assert path.read_bytes() == before
