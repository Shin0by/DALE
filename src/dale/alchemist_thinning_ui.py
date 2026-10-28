"""Latest-only background thinning with a reversible dataset-local scope."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication, QProgressBar

from dale.alchemist import AlchemistCancelled
from dale.alchemist_progress import prepare_da_mode, snapshot
from dale.alchemist_thinning import state_for, thin_objects


class ThinningController(QObject):
    def __init__(self, owner, action, editor):
        super().__init__(owner)
        self.owner, self.action, self.editor = owner, action, editor
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="DA-thinning")
        self.future = self.cancel = self.last_edit = self.last_session = None
        self.last_scope = ()
        self.selection_session = None
        self.remembered_selection = set()
        self.published_selection = set()
        self.dirty = False
        self.percent = 0
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.start)
        self.poll = QTimer(self)
        self.poll.setInterval(40)
        self.poll.timeout.connect(self.finish)
        self.progress = QProgressBar(owner)
        self.progress.setObjectName("alchemistThinningProgress")
        self.progress.setFixedWidth(190)
        self.progress.hide()
        owner.statusBar().addPermanentWidget(self.progress)
        editor.valueChanged.connect(self.request)
        action.triggered.connect(self.toggle)

    def toggle(self, enabled):
        value = max(1, self.editor.value() or 5) if enabled else 0
        if value == self.editor.value():
            self.request()
        else:
            self.editor.setValue(value)

    def request(self, *_):
        if self.cancel:
            self.cancel.set()
        self.dirty = True
        self.action.setChecked(self.editor.value() > 0)
        self.timer.start(180)

    def start(self):
        if self.future is not None or not self.dirty:
            return
        view, owner = self.owner.view, self.owner
        session = view.session
        if not session or not session.alchemist or owner.current_tool_set != "alchemist":
            self.dirty = False
            self.sync()
            return
        panel = owner.slice_window
        if owner.worker or view.active_gesture or (panel and (panel.busy or panel.dirty)):
            self.timer.start(100)
            return
        level = self.editor.value()
        scope = {obj.id for obj in session.alchemist.objects if obj.category != "wall"}
        if not scope:
            self.dirty = False
            self.sync()
            owner.statusBar().showMessage(owner.t("No objects to thin."), 8000)
            return
        self.remember_selection()
        self.dirty = False
        frozen = snapshot(session)
        cancel = self.cancel = Event()
        operations = tuple(session.operations)
        layer, safe = view.source_layer, view.safe_json_repair
        documents = tuple(view.property_documents)
        category = view.alchemist_isolated_category
        self.percent = 0
        self.progress.setValue(0)
        self.progress.setFormat(owner.t("Thinning objects") + " (%p%)")
        self.progress.show()

        def check():
            if cancel.is_set():
                raise AlchemistCancelled()

        def report(percent, _):
            check()
            self.percent = 80 + percent * 19 // 100

        def calculate():
            geometry = thin_objects(
                frozen,
                scope,
                level,
                check,
                lambda done, total: setattr(self, "percent", int(80 * done / max(1, total))),
            )
            frozen.operations.append(geometry)
            prepared = prepare_da_mode(frozen, layer, safe, documents, report, category=category)
            check()
            return geometry, prepared

        self.request_state = session, operations, tuple(sorted(scope))
        self.future = self.pool.submit(calculate)
        self.poll.start()

    def finish(self):
        self.progress.setValue(self.percent)
        if self.future is None or not self.future.done():
            return
        future, self.future = self.future, None
        self.poll.stop()
        session, operations, scope = self.request_state
        try:
            if self.cancel.is_set():
                raise AlchemistCancelled()
            geometry, prepared = future.result()
            if (
                self.owner.view.session is not session
                or len(session.operations) != len(operations)
                or any(a is not b for a, b in zip(session.operations, operations, strict=True))
            ):
                return
            if (
                self.last_session is session
                and self.last_scope == scope
                and session.operations
                and session.operations[-1] is self.last_edit
            ):
                session.operations[-1] = geometry
            else:
                session.add(geometry)
            session.future.clear()
            self.last_edit, self.last_session, self.last_scope = geometry, session, scope
            view = self.owner.view
            raw, working, choices, analysis = prepared
            from dale.alchemist_render import display_key

            view._source_layers_cache = (session.source, view.source_layer_cache_key(raw), choices)
            view._alchemist_contour_analysis_cache = (
                display_key(session.alchemist, working, session.gap_tolerance),
                analysis,
            )
            # Include user changes made while the worker was running. Selection
            # pruning caused by our last result must not erase hidden members.
            self.remember_selection()
            allowed = {r.id for r in working.lineage}
            view.figure_line_ids = tuple(sorted(self.remembered_selection & allowed))
            self.published_selection = set(view.figure_line_ids)
            self.owner.reset_region_selections()
            self.owner.refresh()
            self.owner.statusBar().showMessage(
                self.owner.t(
                    "Thinning: hidden {count} of {total} objects.",
                    count=len(geometry.alchemist_thinning[2]),
                    total=len(scope),
                ),
                10000,
            )
        except AlchemistCancelled:
            pass
        except Exception as exc:
            self.dirty = False
            self.owner.warning("Thinning objects", str(exc))
        finally:
            self.cancel = None
            self.progress.hide()
            if self.dirty:
                self.timer.start(0)
            else:
                self.sync()

    def sync(self):
        if self.future is not None or self.dirty:
            return
        session = self.owner.view.session
        level, _, _ = state_for(session) if session else (0, (), ())
        if self.selection_session is not session:
            self.selection_session = session
            self.remembered_selection = set(self.owner.view.figure_line_ids)
            self.published_selection = set(self.remembered_selection)
        self.editor.blockSignals(True)
        self.editor.setValue(level)
        self.editor.blockSignals(False)
        self.action.setChecked(level > 0)
        enabled = bool(
            session
            and session.alchemist
            and any(obj.category != "wall" for obj in session.alchemist.objects)
        )
        self.action.setEnabled(enabled)
        self.editor.setEnabled(enabled)

    def remember_selection(self):
        view = self.owner.view
        current = set(view.figure_line_ids)
        if self.selection_session is not view.session:
            self.selection_session = view.session
            self.remembered_selection = current.copy()
        else:
            self.remembered_selection.difference_update(self.published_selection - current)
            self.remembered_selection.update(current - self.published_selection)
        live = {r.id for r in view.session.geometry().lineage}
        self.remembered_selection.intersection_update(live)
        self.published_selection = current

    def clear_selection(self):
        """An explicit user clear also clears temporarily hidden selections."""
        self.selection_session = self.owner.view.session
        self.remembered_selection.clear()
        self.published_selection.clear()

    def clear_document(self):
        """Release references to the closed document after pending work was flushed."""
        self.clear_selection()
        self.selection_session = None
        self.last_edit = self.last_session = None
        self.last_scope = ()
        self.request_state = None

    def flush(self):
        self.timer.stop()
        while self.future is not None or self.dirty:
            if self.future is None:
                self.start()
                if self.future is None:
                    break
            try:
                self.future.result(timeout=0.05)
            except TimeoutError:
                QApplication.processEvents()
                continue
            except Exception:
                pass
            self.finish()
        self.timer.stop()

    def close(self):
        self.dirty = False
        self.timer.stop()
        if self.cancel:
            self.cancel.set()
        self.pool.shutdown(wait=False, cancel_futures=True)
