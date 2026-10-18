"""Synthetic Qt manager transactions, asset ownership, transfer dialogs and export names."""

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PySide6.QtCore import QCoreApplication, QEvent, QMimeData, QPointF, Qt, QTimer
from PySide6.QtGui import QDropEvent, QTransform
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox, QPushButton

from dale.dataset_manager import MIME, DatasetManager
from dale.project_io import load_project, save_project
from dale.session import Session, Stroke
from dale.ui import MainWindow, configure_application


@pytest.fixture
def window(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    if not app.property("dataset_manager_test_style"):
        configure_application(app)
        app.setProperty("dataset_manager_test_style", True)
    w = MainWindow(preferences_path=tmp_path / "preferences.json")
    w.resize(1224, 768)
    w.show()
    monkeypatch.setattr(w, "warning", lambda *args: pytest.fail(str(args)))
    monkeypatch.setattr(w, "information", lambda *args: None)
    monkeypatch.setattr(w, "can_discard", lambda: True)
    app.processEvents()
    yield w
    w.close()
    w.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_manager_opens_from_left_square_button_and_cancel_keeps_editor(window):
    assert window.manager_button.x() < window.dataset_control.x()
    assert window.manager_button.size().width() == window.manager_button.size().height() == 36
    assert window.manager_button.isEnabled()

    def inspect():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, DatasetManager)
        dialog.new_dataset()
        assert len(dialog.catalog.views) == 2
        dialog.reject()

    QTimer.singleShot(0, inspect)
    window.manager_button.click()
    assert window.catalog is None and window.view.session is None


def test_apply_empty_datasets_rename_and_open_without_changing_original_sources(
    window, pair_factory, tmp_path
):
    source = pair_factory(size=(400, 400))
    assert window.load_sources(source.image_path, source.json_path)
    image, document = source.image_path.read_bytes(), source.json_path.read_bytes()
    original = window.view.session
    manager = DatasetManager(window)
    manager.new_dataset()
    empty_id = manager.selected
    manager.name_edit.setText("Upper floor")
    manager.rename_dataset()
    manager.new_dataset()
    manager.name_edit.setText("Basement")
    manager.rename_dataset()
    assert len(window.catalog.views) == 1
    manager.selected = empty_id
    manager.rebuild()
    manager.apply(True)
    assert window.catalog.active_key == empty_id and window.catalog.name == "Upper floor"
    assert window.dataset_control.count() == 3
    assert not window.mode_actions["New line"].isEnabled()
    first_id = window.catalog.base_key
    window.dataset_control.setCurrentIndex(window.dataset_control.findData(first_id))
    assert window.view.session.walls == original.walls
    assert source.image_path.read_bytes() == image and source.json_path.read_bytes() == document
    window.project_path = tmp_path / "manager.dale"
    assert window.save_project_file()
    assert window.load_project_file(window.project_path)
    assert window.catalog.active_key == first_id
    assert [v.name for v in window.catalog.views.values()] == ["source", "Upper floor", "Basement"]


@pytest.mark.parametrize("kind", ["json", "image"])
@pytest.mark.parametrize("move", [False, True])
def test_drag_component_asks_copy_or_move_and_editor_changes_only_on_apply(
    window, pair_factory, kind, move
):
    source = pair_factory(size=(400, 400))
    window.load_sources(source.image_path, source.json_path)
    window.catalog.current.session.add(Stroke(((20, 30),), 3))
    manager = DatasetManager(window)
    manager.resize(980, 660)
    manager.show()
    manager.new_dataset()
    target = manager.selected
    source_id = manager.catalog.base_key
    original = window.document_state()

    def choose():
        dialog = QApplication.activeModalWidget()
        assert dialog.objectName() == "datasetTransfer"
        buttons = dialog.findChildren(QPushButton)
        text = manager.t("Move" if move else "Copy")
        next(b for b in buttons if b.text() == text).click()

    mime = QMimeData()
    mime.setData(MIME, json.dumps([manager.tree.token, source_id, kind]).encode())
    item = next(
        manager.tree.topLevelItem(i)
        for i in range(manager.tree.topLevelItemCount())
        if manager.tree.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)[0] == target
    )
    QApplication.processEvents()
    point = manager.tree.visualItemRect(item).center()
    event = QDropEvent(
        QPointF(point),
        Qt.DropAction.CopyAction | Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    guard = QTimer()
    guard.setSingleShot(True)
    guard.timeout.connect(
        lambda: (
            QApplication.activeModalWidget().reject() if QApplication.activeModalWidget() else None
        )
    )
    guard.start(2000)
    QTimer.singleShot(0, choose)
    manager.tree.dropEvent(event)
    guard.stop()
    assert event.isAccepted()
    destination = manager.catalog.views[target]
    assert destination.has_json if kind == "json" else destination.has_image
    left = manager.catalog.views[source_id]
    assert (left.has_json if kind == "json" else left.has_image) is (not move)
    assert window.document_state() == original
    manager.apply(False)
    assert len(window.catalog.views) == 2
    manager.close()


def test_replace_json_freezes_import_and_keeps_archive_image_lifetime(
    window, pair_factory, tmp_path, monkeypatch
):
    source = pair_factory(size=(400, 400))
    project = tmp_path / "original.dale"
    save_project(Session(source), project)
    window.load_project_file(project)
    image = window.view.session.source.image_path
    replacement = tmp_path / "new.json"
    replacement.write_text(
        json.dumps(dict(source.raw, walls=[{"_id": "new", "c": [1, 2, 30, 40]}])), encoding="utf-8"
    )
    manager = DatasetManager(window)
    monkeypatch.setattr(
        "dale.dataset_manager.QFileDialog.getOpenFileName", lambda *args: (str(replacement), "")
    )
    manager.import_component("json")
    imported = manager.catalog.current.session.source.json_path
    assert imported != replacement and imported.is_file()
    manager.apply(False)
    assert window.view.session.source.image_path == image and image.is_file()
    assert window.view.session.walls == (((1, 2), (30, 40)),)
    replacement.write_text("changed outside", encoding="utf-8")
    window.project_path = tmp_path / "updated.dale"
    assert window.save_project_file()
    with load_project(window.project_path) as loaded:
        assert loaded.session.walls == window.view.session.walls
    manager.close()


def test_add_json_button_appends_and_keeps_existing_contours(
    window, pair_factory, tmp_path, monkeypatch
):
    source = pair_factory(size=(400, 400))
    window.load_sources(source.image_path, source.json_path)
    manager = DatasetManager(window)
    addition = tmp_path / "extra.json"
    addition.write_text(
        json.dumps(
            dict(source.raw, walls=[source.raw["walls"][0], {"c": [150, 100, 200, 100], "door": 1}])
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "dale.dataset_manager.QFileDialog.getOpenFileName", lambda *args: (str(addition), "")
    )
    manager.add_json_button.click()
    assert len(manager.catalog.current.session.walls) == 5
    assert len(window.view.session.walls) == 4
    manager.apply(False)
    assert len(window.view.session.walls) == 5
    manager.close()


def test_rename_labels_export_uses_set_name_and_safe_json_values_unchanged(
    window, pair_factory, tmp_path, monkeypatch
):
    source = pair_factory(size=(400, 400), name="Keep original", background={"src": "old/old.png"})
    window.load_sources(None, source.json_path)
    manager = DatasetManager(window)
    manager.name_edit.setText("Physical name")
    manager.rename_dataset()
    field = manager.file_fields["json"]
    field.setText("Internal label")
    manager.rename_file("json")
    assert manager.export_names.text() == "Physical name.json"
    manager.apply(False)
    output = tmp_path / "export.json"
    suggested = []

    def choose(*args):
        suggested.append(Path(args[2]).name)
        return str(output), ""

    monkeypatch.setattr("dale.ui.QFileDialog.getSaveFileName", choose)
    window.export_json_action.trigger()
    assert suggested == ["Physical name.json"]
    assert output.read_bytes() == source.json_path.read_bytes()
    assert window.catalog.current.filename("json") == "Internal label.json"
    manager.close()


@pytest.mark.parametrize("language", ["ru", "en"])
def test_manager_localization_and_minimum_window_fit(window, pair_factory, language):
    source = pair_factory()
    window.load_sources(source.image_path, source.json_path)
    window.set_language(language, persist=False)
    manager = DatasetManager(window)
    manager.show()
    QApplication.processEvents()
    assert manager.windowTitle() == window.t("Dataset manager")
    assert manager.add_json_button.text() == window.t("Merge contours")
    assert manager.width() <= window.width() and manager.height() <= window.height()
    for widget in (manager.tree, manager.name_edit, manager.add_json_button, manager.open_button):
        assert widget.isVisible()
        assert manager.rect().contains(widget.mapTo(manager, widget.rect().topLeft()))
        assert manager.rect().contains(widget.mapTo(manager, widget.rect().bottomRight()))
    manager.close()


def test_export_into_open_project_survives_later_manager_apply_and_save(
    window, pair_factory, tmp_path, monkeypatch
):
    source = pair_factory()
    window.load_sources(source.image_path, source.json_path)
    project = tmp_path / "open.dale"
    window.project_path = project
    assert window.save_project_file()
    manager = DatasetManager(window)
    manager.name_edit.setText("New name")
    manager.rename_dataset()
    monkeypatch.setattr("dale.ui.QFileDialog.getOpenFileName", lambda *args: (str(project), ""))
    manager.export_project()
    assert len(window.catalog.views) == len(manager.catalog.views) == 2
    manager.apply(False)
    assert window.save_project_file()
    with load_project(project) as loaded:
        assert len(loaded.catalog.views) == 2
        assert [v.name for v in loaded.catalog.views.values()] == ["New name", "New name (2)"]
    manager.close()


def test_image_import_in_empty_set_loads_same_stem_json_only_once(
    window, pair_factory, monkeypatch
):
    source = pair_factory()
    manager = DatasetManager(window)
    monkeypatch.setattr(
        "dale.dataset_manager.QFileDialog.getOpenFileName",
        lambda *args: (str(source.image_path), ""),
    )
    manager.import_component("image")
    assert manager.catalog.current.has_image and manager.catalog.current.has_json
    assert manager.catalog.current.session.walls == source.walls
    manager.close()


@pytest.mark.parametrize("kind", ["image", "json"])
@pytest.mark.parametrize("existing", [False, True])
def test_component_add_replace_buttons_keep_their_kind(
    window, pair_factory, tmp_path, monkeypatch, kind, existing
):
    source = pair_factory()
    if existing:
        window.load_sources(source.image_path, source.json_path)
    image = tmp_path / "new-image.png"
    Image.new("RGB", (160, 120), (30, 60, 90)).save(image)
    document = tmp_path / "new-scene.json"
    document.write_text(
        json.dumps({"width": 160, "height": 120, "walls": [{"c": [10, 20, 80, 20]}]}),
        encoding="utf-8",
    )
    selected = image if kind == "image" else document
    monkeypatch.setattr(
        "dale.dataset_manager.QFileDialog.getOpenFileName", lambda *args: (str(selected), "")
    )
    manager = DatasetManager(window)
    manager.component_buttons[kind][0].click()
    view = manager.catalog.views[manager.selected]
    assert view.filename(kind) == selected.name
    if kind == "image":
        assert view.has_image and view.session.source.size == (160, 120)
        assert view.has_json is existing
    else:
        assert view.has_json and len(view.session.walls) == 1
        assert view.has_image is existing
    assert manager.apply(False) is None
    assert window.catalog.current.filename(kind) == selected.name
    manager.close()


@pytest.mark.parametrize("kind", ["image", "json"])
def test_component_transfer_button_keeps_its_kind(window, pair_factory, kind):
    source = pair_factory()
    window.load_sources(source.image_path, source.json_path)
    manager = DatasetManager(window)
    source_id = manager.selected
    target = manager.catalog.create("Destination").id
    manager.rebuild()

    def copy_component():
        dialog = QApplication.activeModalWidget()
        assert dialog.windowTitle() == window.t(
            "Transfer image" if kind == "image" else "Transfer JSON"
        )
        copy = next(
            button
            for button in dialog.findChildren(QPushButton)
            if button.text() == window.t("Copy")
        )
        copy.click()

    QTimer.singleShot(0, copy_component)
    manager.component_buttons[kind][1].click()
    view = manager.catalog.views[target]
    assert view.has_image is (kind == "image")
    assert view.has_json is (kind == "json")
    assert manager.catalog.views[source_id].has_json and manager.catalog.views[source_id].has_image
    manager.close()


@pytest.mark.parametrize("kind", ["image", "json"])
def test_component_delete_button_keeps_its_kind(window, pair_factory, monkeypatch, kind):
    source = pair_factory()
    window.load_sources(source.image_path, source.json_path)
    manager = DatasetManager(window)
    questions = []
    monkeypatch.setattr(manager, "confirm", lambda title, text: questions.append(text) or True)
    manager.component_buttons[kind][2].click()
    view = manager.catalog.current
    assert view.has_image is (kind != "image")
    assert view.has_json is (kind != "json")
    assert len(questions) == 1
    assert ("Delete JSON" in questions[0]) is (kind == "json")
    assert window.catalog.current.has_image and window.catalog.current.has_json
    manager.close()


def test_add_image_button_to_json_only_dataset_keeps_existing_contours_and_safe_mode(
    window, pair_factory, tmp_path, monkeypatch
):
    source = pair_factory()
    window.load_sources(None, source.json_path)
    before = window.view.session.geometry()
    image = tmp_path / "background.png"
    Image.new("RGB", (160, 120), (30, 60, 90)).save(image)
    monkeypatch.setattr(
        "dale.dataset_manager.QFileDialog.getOpenFileName", lambda *args: (str(image), "")
    )
    manager = DatasetManager(window)
    assert manager.catalog.current.has_json and not manager.catalog.current.has_image
    manager.component_buttons["image"][0].click()
    assert manager.catalog.current.session.source.json_bytes == source.json_bytes
    manager.apply(False)
    assert window.view.safe_json_repair
    current = window.view.session.geometry()
    assert (current.walls, current.lineage) == (before.walls, before.lineage)
    assert window.catalog.current.has_json and window.catalog.current.has_image
    manager.close()


def test_occupied_transfer_cancel_keeps_both_components(window, pair_factory):
    source = pair_factory()
    window.load_sources(source.image_path, source.json_path)
    manager = DatasetManager(window)
    source_id = manager.selected
    target = manager.catalog.create("Occupied").id
    manager.catalog.transfer(source_id, target, "json")
    before = manager.catalog.state()

    def cancel():
        dialog = QApplication.activeModalWidget()
        assert dialog.objectName() == "datasetTransfer"
        assert any(
            button.text() == window.t("Replace and move")
            for button in dialog.findChildren(QPushButton)
        )
        dialog.reject()

    QTimer.singleShot(0, cancel)
    manager.transfer(source_id, target, "json")
    assert manager.catalog.state() == before
    manager.close()


@pytest.mark.parametrize("language", ["ru", "en", "ru"])
def test_standard_discard_button_and_dismiss_translation(window, language):
    window.set_language(language, persist=False)
    dialog = QMessageBox(window)
    dialog.setStandardButtons(
        QMessageBox.StandardButton.Save
        | QMessageBox.StandardButton.Discard
        | QMessageBox.StandardButton.Cancel
    )
    discard = dialog.button(QMessageBox.StandardButton.Discard).text().replace("&", "")
    assert discard == ("Не сохранять" if language == "ru" else "Discard")
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Discard)
    assert (
        buttons.button(QDialogButtonBox.StandardButton.Discard).text().replace("&", "") == discard
    )
    translator = QApplication.instance().dale_translator
    assert translator.translate("QDialogButtonBox", "Dismiss") == (
        "Закрыть" if language == "ru" else "Dismiss"
    )


def test_unsaved_empty_manager_project_prompts_before_discard(window, monkeypatch):
    manager = DatasetManager(window)
    manager.new_dataset()
    manager.apply(False)
    asked = []
    monkeypatch.setattr(
        window, "question", lambda *args: asked.append(args) or QMessageBox.StandardButton.Cancel
    )
    assert not MainWindow.can_discard(window)
    assert len(asked) == 1
    manager.close()


@pytest.mark.parametrize("language", ["ru", "en"])
@pytest.mark.parametrize("loaded", [False, True])
def test_manager_button_tooltips_start_with_their_actual_names(
    window, pair_factory, language, loaded
):
    from PySide6.QtWidgets import QPushButton

    if loaded:
        source = pair_factory()
        window.load_sources(source.image_path, source.json_path)
    window.set_language(language, persist=False)
    manager = DatasetManager(window)
    for button in manager.findChildren(QPushButton):
        lines = button.toolTip().splitlines()
        assert lines[0] == button.text()
        assert lines[1].startswith("Назначение:" if language == "ru" else "Purpose:")
        assert len(lines) == len(set(lines))
        assert button.toolTip().count("Условие:" if language == "ru" else "Condition:") == 1
    manager.close()


def test_right_panel_toggle_releases_canvas_and_survives_restart(window, pair_factory):
    source = pair_factory()
    window.load_sources(source.image_path, source.json_path)
    before = window.document_state()
    canvas_width = window.view.width()
    assert window.sidebar_toggle.arrowType() == Qt.ArrowType.RightArrow
    window.sidebar_toggle.click()
    QApplication.processEvents()
    assert window.sidebar_scroll.isHidden() and not window.right_panel_visible
    assert window.sidebar_toggle.arrowType() == Qt.ArrowType.LeftArrow
    assert window.view.width() >= canvas_width + 300
    assert window.document_state() == before
    window.set_language("en", persist=False)
    assert window.sidebar_toggle.toolTip().splitlines()[0] == "Show right panel"
    restored = MainWindow(preferences_path=window.preferences_path)
    assert not restored.right_panel_visible and restored.sidebar_scroll.isHidden()
    restored.close()
    restored.deleteLater()
    window.show_sidebar("settings")
    assert window.right_panel_visible and not window.sidebar_scroll.isHidden()
    assert window.sidebar_toggle.toolTip().splitlines()[0] == "Hide right panel"


@pytest.mark.parametrize("with_image", [False, True])
def test_dataset_open_centers_camera_but_apply_retains_pan(window, pair_factory, with_image):
    source = pair_factory(size=(600, 400))
    assert window.load_sources(source.image_path if with_image else None, source.json_path)
    window.view.setTransform(QTransform.fromScale(2, 2))
    window.view.centerOn(40, 70)
    window.catalog.capture(window.project_ui_state())
    base = window.catalog.base_key
    other = window.catalog.create("Other", ui={**window.project_ui_state(), "zoom": 3})
    window.catalog.transfer(base, other.id, "json")
    if with_image:
        window.catalog.transfer(base, other.id, "image")
    window.rebuild_dataset_controls()
    for identifier, zoom in ((other.id, 3), (base, 2), (other.id, 3)):
        window.dataset_control.setCurrentIndex(window.dataset_control.findData(identifier))
        QApplication.processEvents()
        view = window.view
        center = view.mapFromScene(view.image_rect.center())
        assert (center - view.viewport().rect().center()).manhattanLength() <= 2
        assert view.transform().m11() == zoom
        view.centerOn(40, 70)
    before = window.view.mapToScene(window.view.viewport().rect().center())
    manager = DatasetManager(window)
    manager.apply(False)
    after = window.view.mapToScene(window.view.viewport().rect().center())
    assert (after - before).manhattanLength() <= 1
    manager.apply(True)
    QApplication.processEvents()
    center = window.view.mapFromScene(window.view.image_rect.center())
    assert (center - window.view.viewport().rect().center()).manhattanLength() <= 2
    assert window.view.transform().m11() == 3


def test_project_reopen_centers_first_dataset_without_changing_saved_assets(
    window, pair_factory, tmp_path
):
    source = pair_factory(size=(600, 400))
    window.load_sources(source.image_path, source.json_path)
    window.view.setTransform(QTransform.fromScale(2, 2))
    window.view.centerOn(40, 70)
    window.project_path = tmp_path / "off-center.dale"
    assert window.save_project_file()
    original = window.project_path.read_bytes()
    assert window.load_project_file(window.project_path)
    QApplication.processEvents()
    center = window.view.mapFromScene(window.view.image_rect.center())
    assert (center - window.view.viewport().rect().center()).manhattanLength() <= 2
    assert window.view.transform().m11() == 2
    assert window.project_path.read_bytes() == original
    assert window.document_state() == window.saved_state
