"""Qt remains responsive while background work runs; publication is atomic and on the GUI."""

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QProgressDialog, QWidget

from dale.alchemist import AlchemistCancelled
from dale.alchemist_progress import run_task


@pytest.mark.parametrize("action", ["close", "reject", "escape"])
def test_close_requests_cancellation_without_partial_publication(action):
    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    owner.t = lambda text: text
    ready = threading.Event()
    released = threading.Event()
    requested = []
    published = []
    timer = QTimer(owner)

    def cancel():
        dialog = getattr(owner, "_operation_progress_dialog", None)
        if ready.is_set() and dialog and not requested:
            requested.append(True)
            if action == "escape":
                QTest.keyClick(dialog, Qt.Key.Key_Escape)
            else:
                getattr(dialog, action)()
            assert dialog.isVisible() and dialog.cancel_pending
            assert not dialog.wasCanceled()  # No QProgressDialog reset/hide side effect.
            released.set()

    def work(report):
        ready.set()
        assert released.wait(5)
        # Even a worker that returns before its next checkpoint must not publish.
        return "partial contours"

    timer.timeout.connect(cancel)
    timer.start(5)
    with pytest.raises(AlchemistCancelled):
        run_task(owner, "Loading Dungeon Alchemist", work, published.append, cancellable=True)
    timer.stop()
    assert requested and not published
    assert not owner._alchemist_task_active and owner._operation_progress_dialog is None
    owner.deleteLater()
    app.processEvents()


def test_preview_mailbox_delivers_last_frame_before_publication_and_keeps_it_in_final_phase():
    import io

    from PIL import Image

    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    owner.t = lambda text: text
    stream = io.BytesIO()
    Image.new("RGB", (384, 256), "green").save(stream, format="PNG")
    pixels = stream.getvalue()
    observed = []

    def work(report):
        for index in range(200):
            report.preview((pixels, str(index), index % 2 == 0))
        report(80, "Models ready. Building placed object contours")
        return 42

    def publish(value):
        dialog = owner._operation_progress_dialog
        assert value == 42
        assert dialog.projection_label.caption.startswith("199 -")
        previous = dialog.projection_label.projection.cacheKey()
        dialog.update_progress(96, "Updating the display")
        dialog.update_preview((b"invalid png", "bad frame", False))
        assert dialog.projection_label.caption.startswith("199 -")
        assert dialog.projection_label.projection.cacheKey() == previous
        observed.append(True)

    run_task(owner, "Loading Dungeon Alchemist", work, publish)
    assert observed
    owner.deleteLater()
    app.processEvents()


def test_progress_worker_gui_heartbeat_and_publication():
    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    owner.t = lambda text: text
    main_thread = threading.get_ident()
    release = threading.Event()
    observed = []
    timer = QTimer(owner)

    def heartbeat():
        dialogs = owner.findChildren(QProgressDialog)
        if dialogs and dialogs[0].isVisible():
            observed.append(threading.get_ident())
            release.set()

    def work(report):
        assert threading.get_ident() != main_thread
        report(30, "Preparing contour categories")
        assert release.wait(5), "Qt heartbeat did not run during the calculation"
        return 42

    published = []
    timer.timeout.connect(heartbeat)
    timer.start(5)
    assert (
        run_task(
            owner,
            "Loading Dungeon Alchemist",
            work,
            lambda value: published.append((value, threading.get_ident())),
        )
        == 42
    )
    assert observed and set(observed) == {main_thread}
    assert published == [(42, main_thread)]
    assert not owner._alchemist_task_active
    assert not any(d.isVisible() for d in owner.findChildren(QProgressDialog))
    timer.stop()
    owner.deleteLater()
    app.processEvents()


def test_failure_does_not_publish_and_closes_progress():
    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    owner.t = lambda text: text
    published = []

    def work(report):
        report(20, "Reading the Dungeon Alchemist map")
        raise ValueError("Invalid map")

    with pytest.raises(ValueError, match="Invalid map"):
        run_task(owner, "Loading Dungeon Alchemist", work, published.append)
    assert not published
    assert not owner._alchemist_task_active
    assert not any(d.isVisible() for d in owner.findChildren(QProgressDialog))
    owner.deleteLater()
    app.processEvents()


def test_completed_worker_releases_python_payloads_before_deferred_qt_deletion():
    import weakref

    from dale.alchemist_progress import _Task

    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    owner.t = lambda text: text

    class Payload:
        pass

    result = run_task(owner, "Loading Dungeon Alchemist", lambda report: Payload())
    reference = weakref.ref(result)
    tasks = owner.findChildren(_Task)
    assert all(t.result is None and t.operation is None and t.latest_preview is None for t in tasks)
    del result
    assert reference() is None
    owner.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("attempt_close", [False, True])
def test_projection_preview_stays_visible_until_next_model_is_ready(attempt_close):
    import io

    from PIL import Image

    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    owner.t = lambda text: text
    shown = threading.Event()
    updated = threading.Event()
    observed = []
    timer = QTimer(owner)

    def inspect():
        dialog = getattr(owner, "_operation_progress_dialog", None)
        if dialog and dialog.projection_label.projection is not None:
            observed.append(dialog.projection_label.caption)
            if attempt_close and len(observed) == 1:
                dialog.close()
                dialog.reject()
                assert dialog.isVisible() and not dialog.wasCanceled()
            shown.set()
            if dialog.projection_label.caption.startswith("Second"):
                updated.set()

    timer.timeout.connect(inspect)
    timer.start(5)

    def work(report):
        stream = io.BytesIO()
        Image.new("RGB", (384, 256), "white").save(stream, format="PNG")
        report.preview((stream.getvalue(), "First", False))
        assert shown.wait(5)
        report(40, "Reading local object geometry")
        assert observed[-1].startswith("First")
        report.preview((stream.getvalue(), "Second", True))
        assert updated.wait(5)

    run_task(owner, "Loading Dungeon Alchemist", work)
    assert observed[0].startswith("First") and observed[-1].startswith("Second")
    timer.stop()
    owner.deleteLater()
    app.processEvents()
