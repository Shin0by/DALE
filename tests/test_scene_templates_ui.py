"""Actual Qt dialogs, visibility groups and project/template transfer behavior."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QGraphicsRectItem,
    QMessageBox,
    QPushButton,
)

from dale.project_io import read_project_templates
from dale.scene_templates import LevelTemplate, SceneTemplates, WallPreset, load_template_file
from dale.scene_templates_ui import ColorPaletteDialog, LevelDialog, WallPresetDialog
from dale.ui import MainWindow, configure_application


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    configure_application(instance)
    return instance


@pytest.fixture(autouse=True)
def isolated_preferences(monkeypatch, tmp_path):
    monkeypatch.setenv("DALE_SETTINGS_PATH", str(tmp_path / "preferences.json"))


@pytest.mark.parametrize("language", ["ru", "en"])
def test_level_dialog_empty_bounds_rgb_and_integer_normalization(app, language, monkeypatch):
    original = LevelTemplate(name="Upper")
    dialog = LevelDialog(original, language)
    assert dialog.bottom.text() == dialog.top.text() == ""
    palette = ColorPaletteDialog(original.color, language)
    assert len(palette.swatches) == 16

    def accept_rgb(picker):
        picker.setCurrentColor(QColor("#0123ef"))
        picker.accept()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr("dale.scene_templates_ui.QColorDialog.exec", accept_rgb)
    palette.choose_full()
    assert palette.color == "#0123ef" and palette.result() == QDialog.DialogCode.Accepted
    dialog.color = palette.color
    dialog.bottom.setText("25")
    dialog.top.setText("-10")
    dialog.accept()
    assert (dialog.result_level.bottom_ft, dialog.result_level.top_ft) == (-10, 25)
    assert dialog.result_level.color == "#0123ef"
    assert original.bottom_ft is None and original.color != "#0123ef"
    empty = LevelDialog(original, language)
    empty.accept()
    assert empty.result_level.bottom_ft is None and empty.result_level.top_ft is None
    invalid = LevelDialog(original, language)
    invalid.bottom.setText("1.5")
    invalid.accept()
    assert invalid.result_level is None and invalid.error.text()


@pytest.mark.parametrize("language", ["ru", "en"])
def test_wall_preset_dynamic_distances_doors_animations_and_no_heights(app, language):
    dialog = WallPresetDialog(WallPreset(name="Custom"), language)
    dialog.show()
    app.processEvents()
    assert not dialog.thresholds["sight"].isVisible()
    assert not dialog.state.isVisible() and not dialog.animation_group.isVisible()
    dialog.senses["sight"].setCurrentIndex(dialog.senses["sight"].findData(30))
    dialog.senses["light"].setCurrentIndex(dialog.senses["light"].findData(40))
    assert dialog.thresholds["sight"].isVisible() and dialog.thresholds["light"].isVisible()
    dialog.thresholds["sight"].setText("2.5")
    dialog.attenuation.setChecked(True)
    dialog.door.setCurrentIndex(dialog.door.findData(2))
    assert dialog.state.isVisible()
    dialog.state.setCurrentIndex(dialog.state.findData(2))
    dialog.animation.setCurrentIndex(dialog.animation.findData("swing"))
    assert dialog.animation_group.isVisible()
    dialog.texture.setText("doors/example.png")
    dialog.double.setChecked(True)
    dialog.duration.setValue(900)
    dialog.icon.setCurrentIndex(dialog.icon.findData("window_locked"))
    dialog.senses["sight"].setCurrentIndex(dialog.senses["sight"].findData(20))
    assert not dialog.thresholds["sight"].isVisible()
    dialog.senses["sight"].setCurrentIndex(dialog.senses["sight"].findData(30))
    assert dialog.thresholds["sight"].text() == "2.5"
    dialog.accept()
    result = dialog.result_preset
    assert result.icon == "window_locked" and result.properties["door"] == 2
    assert result.properties["ds"] == 2 and result.properties["light"] == 40
    assert result.properties["threshold"]["sight"] == 2.5
    assert result.properties["threshold"]["light"] is None
    assert result.properties["animation"]["duration"] == 900
    assert "height" not in result.properties and "bottom_ft" not in result.properties


def test_level_eye_hides_group_contents_without_hiding_source_and_survives_reassignment(
    app, pair_factory
):
    source = pair_factory()
    window = MainWindow()
    window.load_sources(source.image_path, source.json_path)
    library = SceneTemplates((LevelTemplate(name="Ground"), LevelTemplate(name="Upper")))
    window.set_scene_templates(library)
    window.activate_mode("Edit points")
    window.select_scene_levels()
    window.show()
    app.processEvents()
    assert window.left_panel.isVisible() and window.view.mode == "Edit points"
    group = window.view.level_groups[library.levels[0].id]
    child = QGraphicsRectItem(0, 0, 5, 5)
    group.addToGroup(child)
    assert child.isVisible()
    listing = window.templates_panel.levels_list
    rect = listing.visualItemRect(listing.item(0))
    QTest.mouseClick(
        listing.viewport(),
        Qt.MouseButton.LeftButton,
        pos=QPoint(rect.right() - 15, rect.center().y()),
    )
    assert not child.isVisible() and window.view.item.isVisible()
    assert window.view.level_groups[library.levels[1].id].isVisible()
    assert not window.scene_templates.levels[0].visible
    assert window.view.session.operations == []
    window.activate_mode("New line")
    assert window.scene_section_active and window.scene_group.isVisible()
    assert window.view.mode == "New line"
    # A new map deletes old QGraphicsItems and rebuilds groups from definitions safely.
    window.load_sources(source.image_path, source.json_path)
    assert not window.view.level_groups[library.levels[0].id].isVisible()
    window.saved_templates = window.scene_templates
    window.saved_state = window.document_state()
    window.close()


def test_add_edit_delete_cards_through_actual_dialogs(app):
    window = MainWindow()
    panel = window.templates_panel
    window.select_scene_levels()
    window.show()
    outcomes = []

    def reply():
        dialog = app.activeModalWidget()
        try:
            dialog.name.setText("Named definition")
            dialog.accept()
            outcomes.append(dialog.result())
        finally:
            if dialog.isVisible():
                dialog.reject()

    for title in ("Add level", "Add preset"):
        QTimer.singleShot(0, reply)
        next(
            button
            for button in panel.findChildren(QPushButton)
            if button.property("dale_original_text") == title
        ).click()
    assert outcomes == [QDialog.DialogCode.Accepted] * 2
    assert panel.levels_list.count() == panel.presets_list.count() == 1
    panel.levels_list.setCurrentRow(0)
    panel.presets_list.setCurrentRow(0)
    QTimer.singleShot(0, reply)
    panel.edit_level(panel.levels_list.currentItem())
    panel.delete_level()
    panel.delete_preset()
    assert not window.scene_templates.levels and not window.scene_templates.wall_presets
    window.close()


def test_templates_save_restore_and_import_without_placed_geometry(
    app, pair_factory, tmp_path, monkeypatch
):
    source = pair_factory()
    window = MainWindow()
    window.load_sources(source.image_path, source.json_path)
    expected = SceneTemplates(
        (LevelTemplate(name="Floor", top_ft=15, visible=False),),
        (WallPreset(name="Door", icon="door_locked"),),
    )
    window.set_scene_templates(expected)
    window.project_path = tmp_path / "source.dale"
    assert window.save_project_file()
    assert read_project_templates(window.project_path) == expected
    restored = MainWindow()
    assert restored.load_project_file(window.project_path)
    assert restored.scene_templates == expected
    assert not restored.view.level_groups[expected.levels[0].id].isVisible()
    baseline = restored.view.session.geometry()
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *args: (str(window.project_path), "")
    )
    restored.import_scene_templates()
    assert len(restored.scene_templates.levels) == 2
    assert restored.scene_templates.levels[0].id != restored.scene_templates.levels[1].id
    assert restored.view.session.geometry() == baseline
    output = tmp_path / "shared.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(output), ""))
    assert restored.export_scene_templates()
    assert load_template_file(output) == restored.scene_templates
    warnings = []
    monkeypatch.setattr(restored, "warning", lambda *args: warnings.append(args))
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args: (str(restored.view.session.source.json_path), ""),
    )
    before = restored.view.session.source.json_path.read_bytes()
    assert not restored.export_scene_templates()
    assert warnings and restored.view.session.source.json_path.read_bytes() == before
    restored.saved_state = restored.document_state()
    restored.saved_templates = restored.scene_templates
    window.close()
    restored.close()


def test_unsaved_template_only_work_prompts_and_can_save_without_scene(app, tmp_path, monkeypatch):
    window = MainWindow()
    window.set_scene_templates(SceneTemplates((LevelTemplate(name="Draft"),)))
    monkeypatch.setattr(window, "question", lambda *args: QMessageBox.StandardButton.Cancel)
    assert not window.can_discard()
    monkeypatch.setattr(window, "question", lambda *args: QMessageBox.StandardButton.Save)
    path = tmp_path / "draft.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(path), ""))
    assert window.can_discard() and load_template_file(path) == window.scene_templates
    window.close()


@pytest.mark.parametrize("height", [0, 1, 2, 10, 100])
def test_level_heights_preserve_whole_feet_including_zero(app, height):
    dialog = LevelDialog(LevelTemplate(), "ru")
    dialog.bottom.setText(str(height))
    dialog.top.setText("")
    dialog.accept()
    assert dialog.result_level.bottom_ft == height
    assert type(dialog.result_level.bottom_ft) is int
    assert dialog.result_level.top_ft is None
