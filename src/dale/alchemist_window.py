"""A dataset-local slicing panel with selection-scoped, coalesced geometry edits."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Event
from time import monotonic

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from dale.alchemist import CATEGORIES, AlchemistCancelled, memberships, scale_category
from dale.alchemist_detail import closed_paths, simplify_contours
from dale.alchemist_detail import values_for as complexity_values
from dale.alchemist_indicator import SliceIndicator
from dale.alchemist_progress import prepare_da_mode, snapshot
from dale.alchemist_slices import change_slice, object_value, raw_vertex_limit
from dale.group_manager import GroupSizeGrip
from dale.map_panel import MapPanel


class SliceWindow(MapPanel):
    def __init__(self, owner):
        super().__init__(owner.view)
        self.owner = owner
        self.map_viewport = owner.view.viewport()
        self.viewport_anchor = QPoint(12, 12)
        self.requested_size = QSize(360, 650)
        self.user_sized = False
        self.drag_offset = None
        self.dock_x = self.dock_y = 0
        self.position_ready = False
        self.position_timer = QTimer(self)
        self.position_timer.setSingleShot(True)
        self.position_timer.timeout.connect(self.remember_geometry)
        self.session = self.baseline = self.last_edit = None
        self.selection = ()
        self.objects = frozenset()
        self.loading = self.busy = False
        self.dirty = False
        self.flushing = False
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="DA-slice-window")
        self.future = None
        self.cancel_event = None
        self.poll = QTimer(self)
        self.poll.setInterval(40)
        self.poll.timeout.connect(self.finish)
        self.deferred = None
        self.setObjectName("alchemistSliceWindow")
        self.setStyleSheet(
            "#alchemistSliceWindow { background: palette(window); border: 1px solid #606060; }"
        )
        self.setAttribute(Qt.WidgetAttribute.WA_NoMousePropagation)
        self.setMinimumSize(300, 360)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        self.header = QWidget(self)
        self.header.setCursor(Qt.CursorShape.SizeAllCursor)
        row = QHBoxLayout(self.header)
        row.setContentsMargins(2, 0, 0, 0)
        self.title = QLabel(self)
        self.title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(self.title, 1)
        self.close_button = QToolButton(self)
        self.close_button.setText("X")
        self.close_button.clicked.connect(self.hide)
        row.addWidget(self.close_button)
        layout.addWidget(self.header)
        self.tabs = QTabBar(self)
        for category in CATEGORIES:
            self.tabs.addTab(category)
        self.tabs.setExpanding(True)
        self.tabs.setUsesScrollButtons(False)
        layout.addWidget(self.tabs)
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.content = QWidget()
        body = QVBoxLayout(self.content)
        self.picture = SliceIndicator(owner, self.content)
        body.addWidget(self.picture)
        self.selection_label = QLabel(self)
        self.selection_label.setWordWrap(True)
        body.addWidget(self.selection_label)
        self.select_all = QPushButton(self)
        self.select_all.clicked.connect(self.choose_all)
        body.addWidget(self.select_all)
        self.fields = QWidget(self)
        form = QFormLayout(self.fields)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setContentsMargins(0, 0, 0, 0)
        self.labels = []
        self.value_labels = {}

        def field(title, low, high):
            box = QWidget(self)
            box.setMaximumWidth(320)
            stack = QVBoxLayout(box)
            stack.setContentsMargins(0, 0, 0, 0)
            editor = QSlider(Qt.Orientation.Horizontal, box)
            editor.setTracking(False)
            value_label = QLabel(box)
            self.value_labels[editor] = value_label
            stack.addWidget(editor)
            stack.addWidget(value_label)
            editor.valueChanged.connect(self.update_value_labels)
            editor.sliderMoved.connect(self.update_value_labels)
            editor.setRange(low, high)
            caption = QLabel(self)
            self.labels.append((caption, title))
            form.addRow(caption, box)
            purpose = {
                "Height slice": (
                    "Normalized model height: 0 is the lowest point, 10 the highest; -1 "
                    "uses local ground."
                ),
                "Upper slice boundary": (
                    "Upper model height for the combined slice range, from 0 to 10."
                ),
                "Size": (
                    "Size as a percentage of the selected objects at the start of this "
                    "editing segment."
                ),
                "Contour complexity": "Maximum vertices per selected closed contour; minimum 4.",
            }[title]
            editor.setProperty("slice_help", (title, purpose))
            editor.setToolTip(owner.control_help(purpose, title=title))
            editor.valueChanged.connect(self.changed)
            editor.sliderPressed.connect(self.supersede)
            editor.sliderReleased.connect(self.release_slider)
            return editor, box

        self.upper, self.upper_box = field("Upper slice boundary", 0, 10)
        self.upper.setValue(10)
        self.lower, self.lower_box = field("Height slice", -1, 10)
        self.between = QCheckBox(self)
        form.addRow(self.between)
        self.between.toggled.connect(self.changed)
        self.scale, _ = field("Size", 1, 1000)
        self.scale.setValue(100)
        self.complexity, self.complexity_box = field("Contour complexity", 4, 4)
        body.addWidget(self.fields)
        self.note = QLabel(self)
        self.note.setWordWrap(True)
        body.addWidget(self.note)
        self.cleanup = QPushButton(self)
        self.cleanup.clicked.connect(self.remove_outside)
        body.addWidget(self.cleanup)
        self.scroll.setWidget(self.content)
        layout.addWidget(self.scroll, 1)
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.hide()
        layout.addWidget(self.progress)
        self.progress_state = (0, 0, 0)
        self.progress_label = None
        footer = QHBoxLayout()
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        footer.addWidget(self.status, 1)
        self.size_grip = GroupSizeGrip(self)
        footer.addWidget(self.size_grip)
        layout.addLayout(footer)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.apply)
        self.header.installEventFilter(self)
        self.map_viewport.installEventFilter(self)
        owner.view.installEventFilter(self)
        self.tabs.currentChanged.connect(self.change_tab)
        self.translate()

    @property
    def category(self):
        return CATEGORIES[self.tabs.currentIndex()]

    def translate(self):
        t = self.owner.t
        self.title.setText(t("Object slices"))
        for i, text in enumerate(("Walls", "Trees", "Bushes", "Rocks")):
            self.tabs.setTabText(i, t(text))
        for label, text in self.labels:
            label.setText(t(text))
        for editor in (
            self.lower,
            self.upper,
            self.scale,
            self.complexity,
        ):
            title, purpose = editor.property("slice_help")
            editor.setAccessibleName(t(title))
            editor.setToolTip(self.owner.control_help(purpose, title=title))
        self.update_value_labels()
        self.between.setText(t("Slice range"))
        self.select_all.setText(t("Select all objects of this category"))
        self.cleanup.setText(t("Remove assets outside map"))
        self.cleanup.setToolTip(
            self.owner.control_help(
                "Remove whole assets of all categories outside the map. "
                "Touching and crossing assets stay.",
                title="Remove assets outside map",
            )
        )
        self.note.setText(
            t(
                "Size and slices affect selected objects. Changes form one undo step until "
                "the selection changes or this window closes."
            )
        )
        self.close_button.setToolTip(
            self.owner.control_help(
                "Close the slicing window and restore category visibility.", title="Close"
            )
        )
        if self.isVisible():
            self.fit_size()

    def update_value_labels(self, *_):
        for editor, label in self.value_labels.items():
            help_parts = editor.property("slice_help")
            if help_parts is None:
                continue
            title = help_parts[0]
            value = editor.sliderPosition() if editor.isSliderDown() else editor.value()
            text = (
                self.owner.t("-1 Ground (automatic)")
                if title == "Height slice" and value == -1
                else str(value)
            )
            if title == "Size":
                text += " %"
            label.setText(text)

    def selected_objects(self, session, selection):
        wanted = set(selection)
        category_ids = {o.id for o in session.alchemist.objects if o.category == self.category}
        return frozenset(
            identifier
            for record, own in zip(
                session.geometry().lineage,
                memberships(session.alchemist, session.geometry()),
                strict=True,
            )
            if record.id in wanted
            for identifier in own & category_ids
        )

    def begin(self):
        self.session = self.owner.view.session
        self.selection = tuple(self.owner.view.figure_line_ids)
        self.baseline_selection = self.selection
        self.baseline = snapshot(self.session)
        self.objects = self.selected_objects(self.session, self.selection)
        self.last_edit = None
        self.load_fields()

    def load_fields(self):
        self.loading = True
        try:
            data = self.session.alchemist
            choices = {
                object_value(self.session, obj) for obj in data.objects if obj.id in self.objects
            }
            low, high, enabled = next(iter(choices)) if len(choices) == 1 else (-1, 10, False)
            self.lower.setValue(low)
            self.upper.setValue(high)
            self.between.setChecked(enabled)
            self.scale.setValue(100)
            geometry = self.baseline.geometry()
            selected = set(self.baseline_selection)
            counts = [
                len(points)
                for _, indices, points, _ in closed_paths(geometry, selected=selected)[1]
                if all(geometry.lineage[i].id in selected for i in indices)
            ]
            limits = complexity_values(self.baseline)
            saved = {limits[o] for o in self.objects if o in limits}
            maximum = max([4, *counts, *saved])
            if saved:
                maximum = max(maximum, raw_vertex_limit(self.baseline, self.objects))
            self.complexity.setRange(4, maximum)
            self.complexity.setValue(next(iter(saved)) if len(saved) == 1 else maximum)
            self.complexity_changed = False
            self.complexity_box.setEnabled(bool(counts))
            self.status.setText(self.owner.t("Mixed slice settings") if len(choices) > 1 else "")
            self.slice_changed = False
            self.scale_changed = False
            self.remember_fields = set()
            self.dirty = False
        finally:
            self.loading = False
        self.capture_applied_fields()
        self.update_controls()

    def capture_applied_fields(self):
        self.applied_fields = (
            self.lower.value(),
            self.upper.value(),
            self.between.isChecked(),
            self.scale.value(),
            self.complexity.value(),
            self.slice_changed,
            self.scale_changed,
            self.complexity_changed,
        )

    def restore_applied_fields(self):
        low, high, between, scale, complexity, sliced, scaled, detailed = self.applied_fields
        self.loading = True
        try:
            self.lower.setValue(low)
            self.upper.setValue(high)
            self.between.setChecked(between)
            self.scale.setValue(scale)
            self.complexity.setValue(complexity)
            self.slice_changed = sliced
            self.scale_changed = scaled
            self.complexity_changed = detailed
            self.remember_fields.clear()
        finally:
            self.loading = False
        self.update_controls()

    def update_controls(self):
        self.fields.setEnabled(bool(self.objects))
        self.select_all.setVisible(not self.objects)
        selection_text = self.owner.t("Selected objects: {count}", count=len(self.objects))
        warning = self.owner.t("Select at least one contour to change slicing.")
        self.selection_label.setText(
            selection_text if self.objects else selection_text + "\n" + warning
        )
        self.fields.setToolTip("" if self.objects else warning)
        profiles = dict(self.session.alchemist.profiles) if self.session else {}
        supported = bool(
            self.session
            and any(
                o.id in self.objects and o.projection is not None and o.block_id in profiles
                for o in self.session.alchemist.objects
            )
        )
        self.lower_box.setEnabled(supported)
        self.between.setEnabled(supported)
        self.upper_box.setEnabled(supported and self.between.isChecked())
        self.picture.category, self.picture.value = self.category, self.lower.value()
        self.picture.upper, self.picture.between = self.upper.value(), self.between.isChecked()
        self.picture.update()

    def dragging_slider(self):
        return any(
            control.isSliderDown()
            for control in (self.lower, self.upper, self.scale, self.complexity)
        )

    def supersede(self):
        if self.loading:
            return
        if self.cancel_event is not None:
            self.cancel_event.set()
            self.dirty = True
        self.timer.stop()

    def release_slider(self):
        if self.dirty:
            self.timer.start(180)

    def changed(self, *_):
        if self.loading or self.session is None or not self.objects:
            return
        self.supersede()
        if self.sender() in (self.lower, self.upper, self.between):
            self.slice_changed = True
            self.remember_fields.add("slice")
        if self.sender() is self.complexity:
            self.complexity_changed = True
            self.remember_fields.add("complexity")
        if self.sender() is self.scale:
            self.scale_changed = True
            self.remember_fields.add("scale")
        if self.between.isChecked():
            self.loading = True
            self.lower.setValue(max(0, self.lower.value()))
            self.upper.setValue(max(self.lower.value(), self.upper.value()))
            self.loading = False
        self.dirty = True
        self.update_controls()
        self.timer.start(180)

    def apply(self):
        self.timer.stop()
        if (
            self.busy
            or not self.dirty
            or not self.objects
            or not self.session
            or self.dragging_slider()
        ):
            return
        self.busy = True
        self.started = monotonic()
        self.progress_state = (0, 0, len(self.objects))
        self.progress_label = None
        session = self.session
        # Recompute from the segment's immutable baseline, never from intermediate
        # slider states. This also avoids accumulating temporary ancestry chains.
        baseline = self.baseline
        applied = snapshot(session)
        low, high, between = self.lower.value(), self.upper.value(), self.between.isChecked()
        scale = self.scale.value() / 100
        category, identifiers = self.category, self.objects
        changed_slice = self.slice_changed
        changed_complexity = self.complexity_changed
        changed_scale = self.scale_changed
        complexity = self.complexity.value()
        selected_ids = self.baseline_selection
        layer, safe = self.owner.view.source_layer, self.owner.view.safe_json_repair
        documents = tuple(self.owner.view.property_documents)
        operations = tuple(session.operations)
        self.dirty = False
        cancel = self.cancel_event = Event()

        def check_cancel():
            if cancel.is_set():
                raise AlchemistCancelled()

        def report_progress(percent, done, total):
            check_cancel()
            self.report_progress(percent, done, total)

        def report_display_progress(percent, label):
            check_cancel()
            self.report_display_progress(percent, label)

        def report_contour_progress(done, total):
            check_cancel()
            self.progress_label = "Simplifying contour parts: {done}/{total}"
            report_progress(80 + int(10 * done / max(1, total)), done, total)

        def calculate(report):
            check_cancel()
            frozen = snapshot(baseline)
            failed_objects = set()
            geometry = None
            selection = selected_ids
            limits = complexity_values(frozen)
            if changed_complexity:
                limits.update(dict.fromkeys(identifiers, complexity))
            profiles = dict(frozen.alchemist.profiles)
            rebuild = changed_complexity and any(
                obj.id in identifiers and obj.projection is not None and obj.block_id in profiles
                for obj in frozen.alchemist.objects
            )
            if changed_slice or rebuild:
                geometry = change_slice(
                    frozen,
                    category,
                    low,
                    object_ids=identifiers,
                    upper=high,
                    between=between,
                    apply_detail=False,
                    rebuild_current=not changed_slice,
                    cancel=cancel,
                    progress=lambda done, total: report_progress(
                        int(75 * done / max(1, total)), done, total
                    ),
                )
                if geometry is not None:
                    frozen.operations.append(geometry)
                    selection = tuple(
                        r.id
                        for r, own in zip(
                            geometry.lineage, memberships(frozen.alchemist, geometry), strict=True
                        )
                        if own & identifiers
                    )
            if scale != 1:
                scaled = scale_category(
                    frozen,
                    category,
                    scale,
                    progress=lambda percent, _: report_progress(
                        75 + percent // 5, len(identifiers), len(identifiers)
                    ),
                    object_ids=identifiers,
                )
                geometry = replace(
                    geometry or frozen.geometry(),
                    walls=scaled.walls,
                    closures=(),
                    lineage=scaled.lineage,
                    ancestry=scaled.ancestry,
                    wall_styles=scaled.wall_styles,
                )
            raw_maximum = None
            if (changed_slice or rebuild) and geometry is not None:
                selected_set = set(selection)
                raw_maximum = max(
                    [
                        4,
                        *(
                            len(points)
                            for _, indices, points, _ in closed_paths(
                                geometry, check_cancel, selected=selected_set
                            )[1]
                            if all(geometry.lineage[i].id in selected_set for i in indices)
                        ),
                    ]
                )
            if limits and (changed_slice or changed_complexity):
                from dale.alchemist_detail_frames import capture_frames, frames_for, placements_for

                working = geometry or frozen.geometry()
                placements = placements_for(frozen, working, identifiers)
                targets = {
                    r.id: min(limits[o] for o in own if o in limits)
                    for r, own in zip(
                        working.lineage, memberships(frozen.alchemist, working), strict=True
                    )
                    if own & identifiers & limits.keys()
                }
                failed_groups = set()
                working, selection, _ = simplify_contours(
                    working,
                    selection,
                    targets,
                    report_contour_progress,
                    check_cancel=check_cancel,
                    failures=failed_groups,
                )
                if failed_groups:
                    failed_objects = {
                        identifier
                        for record, own in zip(
                            working.lineage, memberships(frozen.alchemist, working), strict=True
                        )
                        if record.connection_group in failed_groups
                        for identifier in own & identifiers
                    }
                    if failed_objects == set(identifiers):
                        from dale.alchemist_fit import FIT_FAILED, ContourComplexityError

                        raise ContourComplexityError(FIT_FAILED)
                geometry = replace(
                    working,
                    alchemist_complexity=tuple(sorted(limits.items())),
                    alchemist_detail_frames=capture_frames(
                        frozen.alchemist, working, placements, frames_for(frozen)
                    ),
                )
            if geometry is not None:
                if changed_scale:
                    from dale.alchemist_presets import transform_settings

                    geometry = replace(
                        geometry,
                        alchemist_transforms=transform_settings(baseline, identifiers, scale),
                    )
                if failed_objects:
                    from dale.alchemist_detail import restore_failed_objects

                    geometry = restore_failed_objects(
                        frozen.alchemist, geometry, applied, failed_objects
                    )
                    selection = tuple(
                        r.id
                        for r, own in zip(
                            geometry.lineage, memberships(frozen.alchemist, geometry), strict=True
                        )
                        if own & identifiers
                    )
                frozen.operations.append(geometry)
            check_cancel()
            prepared = prepare_da_mode(
                frozen, layer, safe, documents, report_display_progress, category=category
            )
            check_cancel()
            return geometry, selection, raw_maximum, prepared, failed_objects

        self.request = (session, baseline, identifiers, operations)
        self.future = self.executor.submit(calculate, lambda *_: None)
        self.poll.start()

    def report_progress(self, percent, done, total):
        self.progress_state = percent, done, total

    def report_display_progress(self, percent, label):
        self.progress_label = label
        self.progress_state = 95 + percent * 4 // 100, 0, 0

    def update_progress(self):
        percent, done, total = self.progress_state
        self.progress.setValue(percent)
        label = (
            self.owner.t(self.progress_label, done=done, total=total)
            if self.progress_label
            else self.owner.t("Processing objects: {done}/{total}", done=done, total=total)
        )
        self.progress.setFormat(label + " (%p%)")
        self.progress.setVisible(self.busy and monotonic() - self.started >= 0.3)

    def finish(self):
        if self.busy:
            self.update_progress()
        if not self.flushing and (self.owner.view.active_gesture or self.owner.worker):
            return
        if self.future is None or not self.future.done():
            return
        self.poll.stop()
        future, self.future = self.future, None
        session, baseline, identifiers, operations = self.request
        try:
            # A finished worker can still be obsolete before the GUI publishes it.
            if self.cancel_event is not None and self.cancel_event.is_set():
                raise AlchemistCancelled()
            geometry, selection, raw_maximum, prepared, failed_objects = future.result()
            if len(session.operations) != len(operations) or any(
                a is not b for a, b in zip(session.operations, operations, strict=False)
            ):
                self.dirty = False
                self.last_edit = None
                return
            same_view = self.owner.view.session is session
            current_selection = tuple(self.owner.view.figure_line_ids) if same_view else ()
            retain_selection = same_view and current_selection == self.selection
            restore_only = geometry is None and self.last_edit is not None
            if restore_only:
                geometry = baseline.geometry()
                if session.operations and session.operations[-1] is self.last_edit:
                    session.operations.pop()
                    session.future[:] = baseline.future
                self.last_edit = None
            if geometry is not None and not restore_only:
                if (
                    self.last_edit is not None
                    and session.operations
                    and session.operations[-1] is self.last_edit
                ):
                    session.operations[-1] = geometry
                else:
                    session.add(geometry)
                self.last_edit = geometry
            if retain_selection and geometry is not None:
                self.owner.view.figure_line_ids = tuple(selection)
                self.selection = self.owner.view.figure_line_ids
            if raw_maximum is not None:
                self.loading = True
                maximum = max(raw_maximum, self.complexity.maximum())
                self.complexity.setMaximum(maximum)
                if (
                    not self.complexity_changed
                    and not identifiers & complexity_values(baseline).keys()
                ):
                    self.complexity.setValue(raw_maximum)
                self.complexity_box.setEnabled(bool(selection))
                self.loading = False
            self.status.clear()
            if failed_objects:
                self.status.setText(
                    self.owner.t(
                        "Updated {done} objects. Kept {failed} objects at their previous "
                        "complexity "
                        "because their requested outlines could not be built.",
                        done=len(identifiers) - len(failed_objects),
                        failed=len(failed_objects),
                    )
                )
            self.capture_applied_fields()
            self.owner.remember_alchemist_parameters(
                session, identifiers - failed_objects, self.remember_fields
            )
            self.remember_fields.clear()
            if same_view:
                from dale.alchemist_render import display_key

                prepared_geometry, working, choices, analysis = prepared
                view = self.owner.view
                view._source_layers_cache = (
                    session.source,
                    view.source_layer_cache_key(prepared_geometry),
                    choices,
                )
                view._alchemist_contour_analysis_cache = (
                    display_key(session.alchemist, working, session.gap_tolerance),
                    analysis,
                )
                self.owner.refresh()
        except AlchemistCancelled:
            pass  # The latest controls remain pending; no partial state is published.
        except Exception as exc:
            self.dirty = False
            self.restore_applied_fields()
            self.status.setText(self.owner.t(str(exc)))
        finally:
            self.busy = False
            self.cancel_event = None
            self.progress.hide()
        if self.dirty and not self.dragging_slider():
            self.timer.start(0)
        elif not self.dirty and not self.flushing:
            self.sync()
            if self.deferred:
                session, callback = self.deferred
                self.deferred = None
                if self.owner.view.session is session:
                    QTimer.singleShot(0, callback)

    def flush(self):
        for control in (self.lower, self.upper, self.scale, self.complexity):
            if control.isSliderDown():
                control.setValue(control.sliderPosition())
                control.setSliderDown(False)
        self.flushing = True
        self.timer.stop()
        try:
            while self.busy or self.dirty:
                if self.future is not None:
                    self.poll.stop()
                    try:
                        self.future.result(timeout=0.15)
                    except TimeoutError:
                        from dale.alchemist_progress import run_task

                        pending = self.future

                        def wait_for_result(report, pending=pending):
                            while True:
                                report(
                                    self.progress_state[0], "Updating Dungeon Alchemist contours"
                                )
                                try:
                                    return pending.result(timeout=0.1)
                                except TimeoutError:
                                    continue

                        try:
                            run_task(
                                self.owner, "Updating Dungeon Alchemist contours", wait_for_result
                            )
                        except Exception:
                            pass  # finish reports computation failures in the panel.
                    except Exception:
                        pass  # finish reports the error in the panel.
                    self.finish()
                elif self.dirty and self.objects:
                    self.apply()
                else:
                    break
        finally:
            self.flushing = False
            self.timer.stop()

    def sync(self):
        if not self.isVisible():
            return
        view = self.owner.view
        if not view.figure_line_ids and (not self.busy or self.future is not None):
            self.hide()
            return
        if self.busy:
            return
        if (
            not view.session
            or not view.session.alchemist
            or self.owner.current_tool_set != "alchemist"
            or not view.figure_line_ids
        ):
            self.hide()
            return
        changed = view.session is not self.session or tuple(view.figure_line_ids) != self.selection
        expected = (
            [*self.baseline.operations, self.last_edit]
            if self.last_edit is not None and self.baseline
            else self.baseline.operations
            if self.baseline
            else None
        )
        external_edit = (
            expected is None
            or len(expected) != len(self.session.operations)
            or any(a is not b for a, b in zip(expected, self.session.operations, strict=False))
        )
        if changed or external_edit:
            if not external_edit:
                self.flush()
            self.begin()
        self.translate()

    def isolate(self):
        view = self.owner.view
        view.cancel_pending()
        view.alchemist_isolated_category = self.category
        allowed = {r.id for r in view.editing_geometry().lineage}
        view.figure_line_ids = tuple(i for i in view.figure_line_ids if i in allowed)
        view.figure_pivot = None
        self.owner.refresh()

    def change_tab(self, *_):
        if not self.isVisible():
            return
        # The signal arrives after Qt changes the index; apply the previous tab
        # using its stored category before changing the temporary display scope.
        new = self.tabs.currentIndex()
        old = CATEGORIES.index(self.owner.view.alchemist_isolated_category)
        self.tabs.blockSignals(True)
        self.tabs.setCurrentIndex(old)
        self.flush()
        self.tabs.setCurrentIndex(new)
        self.tabs.blockSignals(False)
        self.busy = True
        self.isolate()
        self.busy = False
        if not self.owner.view.figure_line_ids:
            self.hide()
            return
        self.begin()

    def choose_all(self):
        self.flush()
        view = self.owner.view
        view.figure_line_ids = tuple(r.id for r in view.editing_geometry().lineage)
        view.figure_pivot = None
        self.begin()
        frames = next(
            (
                op.alchemist_empty_frames
                for op in reversed(self.session.operations)
                if getattr(op, "alchemist_empty_frames", None) is not None
            ),
            (),
        )
        empty_ids = {entry[0] for entry in frames}
        data, index = self.session.alchemist, CATEGORIES.index(self.category)
        self.objects |= frozenset(
            obj.id
            for obj in data.objects
            if obj.id in empty_ids
            and obj.category == self.category
            and obj.original_size >= data.settings[index][1]
            and (
                not data.minimum_heights_ft[index]
                or (
                    obj.original_height_ft is not None
                    and obj.original_height_ft + 1e-6 >= data.minimum_heights_ft[index]
                )
            )
        )
        self.load_fields()
        self.owner.update_map_info()

    def remove_outside(self):
        from dale.alchemist import remove_outside_objects
        from dale.alchemist_progress import run_task

        self.flush()
        frozen = snapshot(self.session)
        geometry, count = run_task(
            self.owner, "Checking map bounds", lambda report: remove_outside_objects(frozen, report)
        )
        if geometry is not None:
            self.session.add(geometry)
            live = {r.id for r in geometry.lineage}
            self.owner.view.figure_line_ids = tuple(
                i for i in self.owner.view.figure_line_ids if i in live
            )
        self.begin()
        self.owner.refresh()
        self.status.setText(self.owner.t("Removed outside assets: {count}", count=count))

    def showEvent(self, event):
        from dale.preferences import load_slice_window_geometry

        super().showEvent(event)
        self.owner.alchemist_window_action.setChecked(True)
        self.busy = True
        self.isolate()
        self.busy = False
        self.begin()
        stored = load_slice_window_geometry(self.owner.preferences_path)
        if stored is not None:
            x, y, width, height, self.dock_x, self.dock_y = stored
            self.requested_size = QSize(width, height)
            self.viewport_anchor = QPoint(x, y)
        self.fit_size()
        self.reposition()
        self.position_ready = True

    def clear_document(self):
        """Release a flushed document without destroying the reusable panel."""
        self.hide()
        self.session = self.baseline = self.last_edit = None
        self.request = self.deferred = self.cancel_event = None
        self.selection = ()
        self.objects = frozenset()

    def hideEvent(self, event):
        self.remember_geometry()
        self.flush()
        self.timer.stop()
        view = self.owner.view
        if (
            view.session is self.session
            and self.session
            and self.session.alchemist
            and self.selected_objects(self.session, view.figure_line_ids)
        ):
            # Keep the selected working category visible on close. Other category
            # switches retain their values throughout temporary isolation.
            data = self.session.alchemist
            index = CATEGORIES.index(self.category)
            if not data.settings[index][0]:
                settings = list(data.settings)
                settings[index] = True, settings[index][1]
                self.session.alchemist = replace(data, settings=tuple(settings))
        self.owner.view.alchemist_isolated_category = None
        self.owner.alchemist_window_action.setChecked(False)
        super().hideEvent(event)
        self.owner.refresh()

    def wheelEvent(self, event):
        event.accept()

    def remember_geometry(self):
        from dale.preferences import load_slice_window_geometry, save_slice_window_geometry

        self.position_timer.stop()
        if not self.position_ready:
            return
        value = (
            self.viewport_anchor.x(),
            self.viewport_anchor.y(),
            self.requested_size.width(),
            self.requested_size.height(),
            self.dock_x,
            self.dock_y,
        )
        if value != load_slice_window_geometry(self.owner.preferences_path):
            try:
                save_slice_window_geometry(self.owner.preferences_path, value)
            except OSError:
                self.owner.statusBar().showMessage(
                    self.owner.t("Preferences could not be written."), 7000
                )

    def set_user_size(self, size):
        super().set_user_size(size)
        self.position_timer.start(300)

    def fit_size(self):
        if hasattr(self, "content"):
            width = max(
                self.minimumWidth(), min(self.requested_size.width(), self.map_viewport.width())
            )
            layout = self.layout()
            margins = layout.contentsMargins()
            content_width = max(
                1,
                width
                - margins.left()
                - margins.right()
                - 2 * self.scroll.frameWidth()
                - self.scroll.verticalScrollBar().sizeHint().width(),
            )
            body = self.content.layout()
            body.activate()
            height = body.totalHeightForWidth(content_width)
            if height < 0:
                height = body.totalSizeHint().height()
            visible = [
                layout.itemAt(i)
                for i in range(layout.count())
                if not (layout.itemAt(i).widget() and layout.itemAt(i).widget().isHidden())
            ]
            height += sum(
                item.sizeHint().height() for item in visible if item.widget() is not self.scroll
            )
            height += (
                margins.top()
                + margins.bottom()
                + 2 * self.scroll.frameWidth()
                + max(0, len(visible) - 1) * layout.spacing()
            )
            self.setMaximumHeight(max(self.minimumHeight(), height))
            self.requested_size.setHeight(min(self.requested_size.height(), self.maximumHeight()))
        super().fit_size()

    def eventFilter(self, watched, event):
        if watched is self.owner.view and event.type() == QEvent.Type.Resize:
            # Preserve a freely placed panel's X coordinate when sidebars change width.
            self.reposition()
            return False
        released = (
            watched is self.header
            and event.type() == QEvent.Type.MouseButtonRelease
            and self.drag_offset is not None
        )
        result = super().eventFilter(watched, event)
        if released:
            self.remember_geometry()
        return result
