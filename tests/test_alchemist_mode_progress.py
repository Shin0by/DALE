"""DA mode entry covers cold computation and GUI publication with one progress dialog."""

import threading

import pytest
from PySide6.QtCore import QTimer
from test_alchemist import sample as sample
from test_alchemist_interaction import editor as editor


@pytest.mark.parametrize("safe", [False, True])
def test_da_action_prepares_in_worker_and_keeps_progress_until_publication(
    editor, monkeypatch, safe
):
    import dale.alchemist_progress as progress
    import dale.alchemist_render as render

    editor.select_tool_set("geometry")
    editor.view.safe_json_repair = safe
    editor.view._alchemist_contour_analysis_cache = None
    editor.show()
    session = editor.view.session
    before, history = session.geometry(), tuple(session.operations)
    release, started = threading.Event(), threading.Event()
    main_thread = threading.get_ident()
    observed, analyses, published = [], [], []
    prepare, analyze, refresh = (
        progress.prepare_da_mode,
        render.display_analysis,
        editor.refresh_display,
    )

    def work(*args, **kwargs):
        assert threading.get_ident() != main_thread
        started.set()
        assert release.wait(5), "Progress did not paint while the worker was running"
        return prepare(*args, **kwargs)

    def analysis(*args, **kwargs):
        analyses.append(threading.get_ident())
        return analyze(*args, **kwargs)

    def publish():
        dialog = editor._operation_progress_dialog
        assert dialog and dialog.isVisible() and dialog.value() >= 90
        assert threading.get_ident() == main_thread
        published.append(True)
        return refresh()

    def heartbeat():
        dialog = getattr(editor, "_operation_progress_dialog", None)
        if started.is_set() and dialog and dialog.isVisible():
            observed.append(dialog.objectName())
            release.set()

    monkeypatch.setattr(progress, "prepare_da_mode", work)
    monkeypatch.setattr(render, "display_analysis", analysis)
    monkeypatch.setattr(editor, "refresh_display", publish)
    timer = QTimer(editor)
    timer.timeout.connect(heartbeat)
    timer.start(5)
    editor.tool_set_actions["alchemist"].trigger()
    timer.stop()
    assert observed and set(observed) == {"alchemistModeProgress"}
    assert analyses and all(thread != main_thread for thread in analyses)
    assert published and editor.current_tool_set == "alchemist"
    assert editor._operation_progress_dialog is None and not editor._alchemist_task_active
    assert editor.view.session is session
    assert session.geometry() == before and session.geometry().lineage == before.lineage
    assert tuple(session.operations) == history


def test_failed_da_preparation_keeps_previous_section_and_selection(editor, monkeypatch):
    import dale.alchemist_progress as progress

    editor.select_tool_set("figures")
    session = editor.view.session
    before, history = session.geometry(), tuple(session.operations)
    selection = tuple(r.id for r in editor.view.editing_geometry().lineage)
    editor.view.figure_line_ids = selection
    warnings = []

    def fail(*_, **kwargs):
        raise ValueError("Test preparation failure")

    monkeypatch.setattr(progress, "prepare_da_mode", fail)
    monkeypatch.setattr(editor, "warning", lambda *args: warnings.append(args))
    editor.tool_set_actions["alchemist"].trigger()
    assert warnings and editor.current_tool_set == "figures"
    assert editor.tool_set_actions["figures"].isChecked()
    assert editor.view.figure_line_ids == selection
    assert session.geometry() == before and tuple(session.operations) == history
    assert editor._operation_progress_dialog is None and not editor._entering_da_mode


def test_repeat_entry_reuses_analysis_but_geometry_change_invalidates_it(editor, monkeypatch):
    from dataclasses import replace

    import dale.alchemist_render as render

    calls = []
    original = render.display_analysis

    def analyze(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(render, "display_analysis", analyze)
    editor.select_tool_set("geometry")
    editor.select_tool_set("alchemist")
    assert not calls
    editor.select_tool_set("geometry")
    session = editor.view.session
    geometry = session.geometry()
    session.add(
        replace(
            geometry, walls=tuple(tuple((x + 1, y) for x, y in edge) for edge in geometry.walls)
        )
    )
    editor.select_tool_set("alchemist")
    assert len(calls) == 1


def test_manager_apply_has_its_own_worker_progress_through_publication(editor, monkeypatch):
    import dale.alchemist_progress as progress
    import dale.alchemist_render as render
    from dale.datasets import DatasetCatalog

    editor.show()
    editor.catalog = DatasetCatalog(editor.view.session, editor.project_ui_state())
    staged = editor.catalog.fork()
    geometry = staged.current.session.geometry()
    main_thread = threading.get_ident()
    started, release = threading.Event(), threading.Event()
    observed, calculations, published = [], [], []
    prepare, analyze, show = (
        progress.prepare_project_view,
        render.display_analysis,
        editor.show_catalog_view,
    )

    def work(*args, **kwargs):
        assert threading.get_ident() != main_thread
        started.set()
        assert release.wait(5), "Apply blocked the GUI event loop"
        return prepare(*args, **kwargs)

    def analysis(*args, **kwargs):
        calculations.append(threading.get_ident())
        return analyze(*args, **kwargs)

    def publish(*args, **kwargs):
        dialog = editor._operation_progress_dialog
        assert dialog and dialog.isVisible() and dialog.value() >= 90
        assert threading.get_ident() == main_thread
        published.append(True)
        return show(*args, **kwargs)

    def heartbeat():
        dialog = getattr(editor, "_operation_progress_dialog", None)
        if started.is_set() and dialog and dialog.isVisible():
            observed.append(dialog.objectName())
            release.set()

    monkeypatch.setattr(progress, "prepare_project_view", work)
    monkeypatch.setattr(render, "display_analysis", analysis)
    monkeypatch.setattr(editor, "show_catalog_view", publish)
    timer = QTimer(editor)
    timer.timeout.connect(heartbeat)
    timer.start(5)
    try:
        assert editor.apply_dataset_manager(staged)
    finally:
        timer.stop()
    assert observed and set(observed) == {"datasetApplyProgress"}
    assert calculations and all(thread != main_thread for thread in calculations)
    assert published == [True]
    assert editor.view.session.geometry() is geometry
    assert editor._operation_progress_dialog is None and not editor._alchemist_task_active


def test_manager_prepare_failure_keeps_live_catalog_selection_and_geometry(editor, monkeypatch):
    from dale.datasets import DatasetCatalog

    editor.catalog = DatasetCatalog(editor.view.session, editor.project_ui_state())
    catalog, session, preview = editor.catalog, editor.view.session, editor.view.preview
    editor.view.figure_line_ids = session.alchemist.objects[0].roots
    selection, geometry = editor.view.figure_line_ids, session.geometry()
    warnings = []

    def fail(*args, **kwargs):
        raise ValueError("Deliberate dataset preparation failure")

    monkeypatch.setattr("dale.alchemist_progress.prepare_project_view", fail)
    monkeypatch.setattr(editor, "warning", lambda *args: warnings.append(args))
    assert not editor.apply_dataset_manager(catalog.fork())
    assert warnings and editor.catalog is catalog and editor.view.session is session
    assert editor.view.preview is preview and session.geometry() is geometry
    assert editor.view.figure_line_ids == selection
    assert editor._operation_progress_dialog is None
