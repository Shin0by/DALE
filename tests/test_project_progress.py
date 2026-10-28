"""Project loading keeps Qt alive and publishes only validated, prepared inputs."""

import os
import threading
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QProgressDialog

import dale.ui as ui
from dale.alchemist_progress import run_task
from dale.project_io import load_project, save_project
from dale.session import Session


def test_save_project_progress_uses_detached_worker_state(project_window, monkeypatch, tmp_path):
    app, window, path = project_window
    assert window.load_project_file(path)
    live, main = window.view.session, threading.get_ident()
    release = threading.Event()
    observed = []

    def heartbeat():
        dialogs = [
            d
            for d in window.findChildren(QProgressDialog)
            if d.isVisible() and d.objectName() == "projectSaveProgress"
        ]
        if dialogs:
            observed.append(dialogs[0].value())
            release.set()

    def writing(session, destination, settings, **kwargs):
        assert threading.get_ident() != main
        assert session is not live
        assert kwargs["catalog"] is not window.catalog
        assert all(
            view.session is not window.catalog.views[key].session
            for key, view in kwargs["catalog"].views.items()
        )
        kwargs["progress"](20, "Serializing project datasets")
        assert release.wait(5)
        return save_project(session, destination, settings, **kwargs)

    timer = QTimer(window)
    timer.timeout.connect(heartbeat)
    timer.start(5)
    monkeypatch.setattr(ui, "save_project", writing)
    window.project_path = tmp_path / "saved.dale"
    assert window.save_project_file()
    timer.stop()
    assert observed
    with load_project(window.project_path) as loaded:
        assert loaded.session.geometry().walls == live.geometry().walls


def test_json_preparation_runs_off_thread(project_window, monkeypatch, tmp_path):
    _, window, path = project_window
    assert window.load_project_file(path)
    main, calls = threading.get_ident(), []
    original = ui.repaired_json_bytes

    def prepare(*args, **kwargs):
        calls.append(threading.get_ident())
        return original(*args, **kwargs)

    destination = tmp_path / "standalone.json"
    monkeypatch.setattr(ui, "repaired_json_bytes", prepare)
    monkeypatch.setattr(ui.QFileDialog, "getSaveFileName", lambda *args: (str(destination), ""))
    monkeypatch.setattr(window, "information", lambda *args: None)
    monkeypatch.setattr(window, "warning", lambda *args: pytest.fail(str(args)))
    window.export_json()
    assert destination.exists()
    assert calls and all(thread != main for thread in calls)


@pytest.fixture
def project_window(tmp_path, pair_factory):
    app = QApplication.instance() or QApplication([])
    source = pair_factory()
    path = tmp_path / "Input.dale"
    save_project(Session(source), path)
    window = ui.MainWindow(preferences_path=tmp_path / "preferences.json")
    window.can_discard = lambda: True
    yield app, window, path
    window.close()
    window.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("language", ["ru", "en"])
def test_open_project_progress_reads_off_thread_and_publishes_on_gui(
    project_window, monkeypatch, language
):
    app, window, path = project_window
    window.set_language(language, persist=False)
    expected_title = window.t("Opening DALE project")
    original = path.read_bytes()
    main = threading.get_ident()
    release = threading.Event()
    observed = []
    publish_threads = []
    original_publish = window.publish_loaded_project

    def heartbeat():
        dialogs = [d for d in window.findChildren(QProgressDialog) if d.isVisible()]
        if dialogs:
            assert len(dialogs) == 1
            assert dialogs[0].objectName() == "projectProgress"
            observed.append((dialogs[0].value(), dialogs[0].windowTitle()))
            release.set()

    def reading(path, *, progress=None):
        assert threading.get_ident() != main
        assert release.wait(5)
        return load_project(path, progress=progress)

    def publishing(*args):
        publish_threads.append(threading.get_ident())
        assert window._operation_progress_dialog.isVisible()
        return original_publish(*args)

    timer = QTimer(window)
    timer.timeout.connect(heartbeat)
    timer.start(5)
    monkeypatch.setattr(ui, "load_project", reading)
    monkeypatch.setattr(window, "publish_loaded_project", publishing)
    assert window.load_project_file(path)
    timer.stop()
    assert observed
    assert observed[0][1] == expected_title
    assert publish_threads == [main]
    assert window.project_path == path
    assert path.read_bytes() == original
    assert window._operation_progress_dialog is None
    assert not window._alchemist_task_active
    assert not any(d.isVisible() for d in window.findChildren(QProgressDialog))
    app.processEvents()


def test_preparation_failure_cleans_extraction_and_preserves_current_project(
    project_window, monkeypatch
):
    _, window, path = project_window
    assert window.load_project_file(path)
    previous = window.loaded_project
    session = window.view.session
    candidates = []
    warnings = []

    def reading(path, *, progress=None):
        candidate = load_project(path, progress=progress)
        candidates.append(candidate)
        return candidate

    def broken_preview(source):
        raise ValueError("Preview unavailable")

    monkeypatch.setattr(ui, "load_project", reading)
    monkeypatch.setattr(ui, "load_preview", broken_preview)
    monkeypatch.setattr(window, "warning", lambda *args: warnings.append(args))
    assert not window.load_project_file(path)
    assert warnings == [("Cannot open project", "Preview unavailable")]
    assert window.loaded_project is previous
    assert window.view.session is session
    assert Path(previous.workspace.name).exists()
    assert not Path(candidates[0].workspace.name).exists()
    assert window._operation_progress_dialog is None


def test_nested_preparation_uses_one_project_dialog(project_window):
    _, window, _ = project_window
    seen = []

    def publish(value):
        outer = window._operation_progress_dialog
        assert not window._alchemist_task_active

        def commit(result):
            assert window._operation_progress_dialog is outer
            assert len([d for d in window.findChildren(QProgressDialog) if d.isVisible()]) == 1
            assert outer.value() == 95
            seen.append(result)

        run_task(window, "Updating Dungeon Alchemist contours", lambda report: value + 1, commit)
        assert outer.isVisible()
        assert not window._alchemist_task_active

    run_task(
        window,
        "Opening DALE project",
        lambda report: 1,
        publish,
        object_name="projectProgress",
        publish_refresh=True,
    )
    assert seen == [2]
    assert window._operation_progress_dialog is None


def test_archive_progress_is_ordered_and_optional(project_window):
    _, _, path = project_window
    stages = []
    with load_project(path, progress=lambda value, text: stages.append((value, text))) as loaded:
        assert loaded.session.source.image_path.exists()
    values = [value for value, _ in stages]
    assert values == sorted(values)
    assert values[0] == 5 and values[-1] == 65
    assert len({text for _, text in stages}) == 5


def test_repeated_load_errors_release_modality_and_manager_import_errors_are_visible(
    project_window, monkeypatch
):
    import builtins
    import zlib

    app, window, path = project_window
    window.show()
    assert window.load_project_file(path)
    original, warnings = ui.load_project, []
    previous = window.view.session
    monkeypatch.setattr(window, "warning", lambda *args: warnings.append(args))

    def broken(*args, **kwargs):
        raise zlib.error("Error -3 while decompressing data: incorrect header check")

    monkeypatch.setattr(ui, "load_project", broken)
    for _ in range(3):
        assert not window.load_project_file(path)
        assert window.view.session is previous
        assert window._operation_progress_dialog is None
        assert not window._alchemist_task_active
    native_import = builtins.__import__

    def importing(name, *args, **kwargs):
        if name == "dale.dataset_manager":
            raise zlib.error("Error -3 while decompressing data: incorrect header check")
        return native_import(name, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "__import__", importing)
        window.manage_datasets()
    assert warnings[-1][0] == "Dataset manager"
    monkeypatch.setattr(ui, "load_project", original)
    assert window.load_project_file(path)
    seen = []

    def inspect():
        dialog = QApplication.activeModalWidget()
        if dialog is not None and dialog.objectName() == "datasetManager":
            seen.append(dialog.isVisible())
            dialog.reject()

    timer = QTimer(window)
    timer.timeout.connect(inspect)
    timer.start(10)
    window.manage_datasets()
    timer.stop()
    app.processEvents()
    assert seen == [True]
