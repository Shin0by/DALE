"""Shared project/DA progress with background calculations and GUI-thread publication."""

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event, Lock

from PySide6.QtCore import QEventLoop, QRect, QSize, Qt, QThread, Signal, Slot
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QLabel, QProgressDialog
from shiboken6 import isValid

from dale.alchemist import AlchemistCancelled


class _Task(QThread):
    progress = Signal(int, str)
    preview_ready = Signal()

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation
        self.result = None
        self.error = None
        self.preview_lock = Lock()
        self.latest_preview = None
        self.preview_queued = False
        self.cancel_requested = Event()

    def request_cancel(self):
        self.cancel_requested.set()

    def check_cancel(self):
        if self.cancel_requested.is_set():
            raise AlchemistCancelled()

    def preview(self, value):
        self.check_cancel()
        with self.preview_lock:
            self.latest_preview = value
            if self.preview_queued:
                return
            self.preview_queued = True
        self.preview_ready.emit()

    def __call__(self, value, label):
        self.check_cancel()
        self.progress.emit(value, label)

    @Slot()
    def deliver_preview(self):
        with self.preview_lock:
            value = self.latest_preview
            self.latest_preview = None
            self.preview_queued = False
        dialog = getattr(self.parent(), "_operation_progress_dialog", None)
        if dialog is not None and value is not None:
            dialog.update_preview(value)

    def run(self):
        try:
            self.result = self.operation(self)
            self.check_cancel()
        except Exception as exc:
            self.error = exc


class _ProjectionLabel(QLabel):
    def __init__(self, parent):
        super().__init__(parent)
        self.projection = None
        self.caption = ""

    def sizeHint(self):
        return QSize(420, 340) if self.projection is not None else super().sizeHint()

    def paintEvent(self, event):
        if self.projection is None:
            return super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(self.palette().windowText().color())
        flags = Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap
        painter.drawText(QRect(0, 0, self.width(), 40), flags, self.text())
        painter.drawImage(QRect((self.width() - 384) // 2, 44, 384, 256), self.projection)
        painter.drawText(QRect(0, 304, self.width(), 36), flags, self.caption)


class _Progress(QProgressDialog):
    cancellation_requested = Signal()

    def __init__(self, owner, title, object_name, cancellable=False):
        super().__init__(owner.t(title), "", 0, 100, owner)
        self.owner = owner
        self.finished_task = False
        self.cancellable = cancellable
        self.cancel_pending = False
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, cancellable)
        self.setObjectName(object_name)
        self.setWindowTitle(owner.t(title))
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.setCancelButton(None)
        self.setAutoClose(False)
        self.setAutoReset(False)
        self.setMinimumDuration(0)
        self.setMinimumWidth(380)
        self.projection_label = _ProjectionLabel(self)
        self.projection_label.setText(owner.t(title))
        self.setLabel(self.projection_label)

    def update_preview(self, value):
        pixels, name, cached = value
        image = QImage.fromData(pixels, "PNG")
        if image.isNull():
            return
        self.projection_label.projection = image
        status = self.owner.t("Cached projection" if cached else "Computed projection")
        self.projection_label.caption = f"{name} - {status}"
        self.projection_label.updateGeometry()
        self.setMinimumSize(444, 400)
        self.resize(self.sizeHint())
        self.projection_label.update()

    @Slot(int, str)
    def update_progress(self, value, label):
        self.setLabelText(self.owner.t("Cancelling import..." if self.cancel_pending else label))
        self.setValue(max(self.value(), value))

    def request_cancel(self):
        if self.cancellable and not self.cancel_pending:
            self.cancel_pending = True
            self.setLabelText(self.owner.t("Cancelling import..."))
            self.cancellation_requested.emit()

    def reject(self):
        # QDialog rejection must not reset QProgressDialog while its worker is alive.
        if self.finished_task:
            super().reject()
        else:
            self.request_cancel()

    def closeEvent(self, event):
        if self.finished_task:
            super().closeEvent(event)
        else:
            self.request_cancel()
            event.ignore()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.request_cancel()
            event.accept()
        else:
            super().keyPressEvent(event)


def run_task(
    owner,
    title,
    operation,
    publish=None,
    *,
    object_name="alchemistProgress",
    publish_refresh=False,
    cancellable=False,
):
    """Keep Qt responsive; commit results only after successful computation."""
    existing = getattr(owner, "_operation_progress_dialog", None)
    previous_window = QApplication.activeWindow()
    dialog = existing or _Progress(owner, title, object_name, cancellable)
    previous_cancellable = dialog.cancellable
    owner._operation_progress_dialog = dialog
    previous_active = getattr(owner, "_alchemist_task_active", False)
    worker = _Task(operation, owner)
    loop = QEventLoop(owner)
    worker.progress.connect(dialog.update_progress, Qt.ConnectionType.QueuedConnection)
    worker.preview_ready.connect(worker.deliver_preview, Qt.ConnectionType.QueuedConnection)
    worker.finished.connect(loop.quit)
    dialog.cancellation_requested.connect(worker.request_cancel)
    owner._alchemist_task_active = True
    try:
        if existing is None:
            dialog.setValue(0)
            dialog.show()
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        worker.start()
        loop.exec()
        worker.wait()
        if worker.error is not None:
            raise worker.error
        worker.deliver_preview()
        dialog.update_progress(95, "Updating the display")
        worker.check_cancel()
        dialog.cancellable = False
        if publish:
            if publish_refresh:
                owner._alchemist_task_active = previous_active
            publish(worker.result)
        if existing is None:
            dialog.setValue(100)
        return worker.result
    finally:
        if existing is not None:
            dialog.cancellable = previous_cancellable
        # Qt defers QObject deletion; release large Python snapshots immediately.
        worker.result = None
        worker.operation = None
        worker.error = None
        with worker.preview_lock:
            worker.latest_preview = None
        owner._alchemist_task_active = previous_active
        if existing is None:
            owner._operation_progress_dialog = None
            dialog.finished_task = True
            dialog.close()
            dialog.deleteLater()
            target = (
                previous_window
                if previous_window is not None
                and isValid(previous_window)
                and previous_window.isVisible()
                else owner
            )
            if target.isVisible():
                target.activateWindow()
                QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
        worker.progress.disconnect(dialog.update_progress)
        dialog.cancellation_requested.disconnect(worker.request_cancel)
        worker.deleteLater()
        loop.deleteLater()


def snapshot(session):
    return replace(session, operations=list(session.operations), future=list(session.future))


def prepare_project_view(session, section, documents, report, preview_loader, *, parallel=None):
    """Decode one image alongside independent contour preparation, with bounded workers."""
    from dale.alchemist import scoped_geometry
    from dale.alchemist_render import display_key

    if parallel is None:
        parallel = (os.cpu_count() or 1) > 1 and session.source.image_path is not None

    def contours():
        prepared, da_cache = None, None
        if session.alchemist:
            geometry = session.geometry()
            prepared = prepare_display(
                session,
                geometry,
                section,
                "all",
                False,
                documents,
                (),
                lambda value, label: report(78 + value // 10, label),
            )
            if section == "alchemist":
                working = scoped_geometry(session, geometry, "alchemist")
                da_cache = (
                    display_key(session.alchemist, working, session.gap_tolerance),
                    prepared[0][1],
                )
        else:
            session.analysis()
        return prepared, da_cache

    report(75, "Preparing project image and contours")
    if parallel:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="DALE-project-image") as pool:
            image_task = pool.submit(preview_loader, session.source)
            prepared, da_cache = contours()
            report(90, "Finishing project image")
            preview = image_task.result()
    else:
        preview = preview_loader(session.source)
        prepared, da_cache = contours()
    report(92, "Updating the display")
    return preview, prepared, da_cache


def prepare_da_mode(
    session,
    layer_key,
    safe,
    documents,
    report,
    *,
    cached_analysis=None,
    cached_layers=None,
    category=None,
):
    """Prepare DA navigation without touching live Qt widgets or mutable history."""
    from dale.alchemist import scoped_geometry
    from dale.alchemist_render import display_analysis, display_key, object_figures
    from dale.object_index import indexed_layer
    from dale.source_editing import source_layers

    report(5, "Preparing contour categories")
    geometry = session.geometry()
    working = scoped_geometry(session, geometry, "alchemist", category=category)
    report(20, "Preparing height layers")
    layer_cache_key = (
        None,
        geometry.lineage,
        geometry.ancestry,
        geometry.wall_styles,
        documents,
        session.alchemist.objects,
    )
    choices = (
        cached_layers[2]
        if cached_layers
        and cached_layers[0] is session.source
        and cached_layers[1] == layer_cache_key
        else source_layers(session.source, geometry, documents, alchemist=session.alchemist)
    )
    if safe:
        layer = next(
            (value for value in choices if value.key == layer_key),
            choices[0] if layer_key == "all" else replace(choices[0], indices=()),
        )
        allowed = {geometry.lineage[i].id for i in layer.indices}
        working = indexed_layer(
            session.alchemist,
            working,
            tuple(i for i, r in enumerate(working.lineage) if r.id in allowed),
        )
    report(40, "Calculating DA contours")
    key = display_key(session.alchemist, working, session.gap_tolerance)
    analysis = (
        cached_analysis[1]
        if cached_analysis and cached_analysis[0] == key
        else display_analysis(session.alchemist, working, session.gap_tolerance, report)
    )
    report(85, "Preparing contour selection")
    object_figures(session.alchemist, working, session.gap_tolerance)
    report(90, "Updating the display")
    return geometry, working, choices, analysis


def prepare_display(
    session, geometry, section, layer_key, safe, documents, cached, report, choices=None
):
    from dale.alchemist import scoped_geometry
    from dale.geometry import analyze_regions
    from dale.object_index import indexed_layer
    from dale.source_editing import layer_geometry, source_layers

    report(10, "Preparing contour categories")
    scope = (
        "alchemist"
        if section == "alchemist"
        else "combined"
        if section in ("regions", "pixels")
        else "regular"
    )
    working = scoped_geometry(session, geometry, scope)
    report(25, "Preparing height layers")
    if choices is None:
        choices = source_layers(session.source, geometry, documents, alchemist=session.alchemist)
    if safe:
        layer = next(
            (layer for layer in choices if layer.key == layer_key),
            choices[0] if layer_key == "all" else replace(choices[0], indices=()),
        )
        allowed = {geometry.lineage[i].id for i in layer.indices}
        indices = [i for i, r in enumerate(working.lineage) if r.id in allowed]
        working = (
            indexed_layer(session.alchemist, working, indices)
            if session.alchemist
            else layer_geometry(working, indices)
        )
    analyses = list(cached)

    def analyze(value):
        key = value.walls, value.closures, session.gap_tolerance
        for known, analysis in analyses:
            if key == known:
                return key, analysis
        analysis = analyze_regions(*key)
        analyses.append((key, analysis))
        return key, analysis

    report(40, "Calculating visible regions")
    if section == "alchemist":
        from dale.alchemist_render import display_analysis

        key = working.walls, working.closures, session.gap_tolerance
        visible = key, display_analysis(session.alchemist, working, session.gap_tolerance)
    else:
        visible = analyze(working)
    # Only an unfiltered combined view is also a complete export-region analysis.
    combined_analysis = visible if scope == "combined" and layer_key == "all" else None
    return visible, combined_analysis, tuple(analyses[-3:]), choices
