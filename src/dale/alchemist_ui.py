"""Local library setup and dataset-local Dungeon Alchemist controls."""

import sqlite3
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from dale.alchemist import (
    CATEGORIES,
    AlchemistCancelled,
    import_map,
    same_type_lines,
    scoped_geometry,
)
from dale.alchemist_library import (
    AlchemistLibrary,
    MissingAlchemistItems,
    cache_path,
    discover_installations,
    installation,
)
from dale.alchemist_progress import prepare_display, run_task, snapshot
from dale.preferences import load_alchemist_path, save_alchemist_path
from dale.tool_settings import ToolSettingsDialog
from dale.toolbar import (
    ModeTabButton,
    SizedToolButton,
    ToolSettingsCorner,
    ToolSpinBox,
    make_toolbar,
    tool_icon,
)

CATEGORY_TITLES = {"wall": "DA walls", "tree": "DA trees", "bush": "DA bushes", "rock": "DA rocks"}


class AlchemistUI:
    def alchemist_help(self, control, text, *, title=None, keys=()):
        control.setProperty("dale_tooltip_parts", [text])
        control.setProperty("dale_tooltip_keys", list(keys))
        control.setProperty("dale_tooltip_title", title)
        return self.control_help(text, title=title, keys=keys)

    def setup_alchemist(self):
        self.slice_window = None
        form = self.settings_group.layout()
        self.alchemist_path = QLineEdit(load_alchemist_path(self.preferences_path))
        self.alchemist_path.setObjectName("alchemistExecutable")
        self.alchemist_path.setReadOnly(True)
        self.alchemist_path.setToolTip(
            self.alchemist_help(
                self.alchemist_path,
                (
                    "Path to Dungeon Alchemist.exe. Read local object libraries without "
                    "administrator rights or downloads."
                ),
                title="Dungeon Alchemist executable",
            )
        )
        form.addRow("Dungeon Alchemist executable", self.alchemist_path)
        choose = QPushButton("Choose Dungeon Alchemist")
        choose.setObjectName("chooseAlchemistExecutable")
        choose.clicked.connect(self.choose_alchemist)
        choose.setToolTip(
            self.alchemist_help(
                choose,
                "Choose the installed Dungeon Alchemist.exe to resolve missing object metadata.",
                title="Choose Dungeon Alchemist",
            )
        )
        form.addRow(choose)
        clear = QPushButton("Clear Alchemist cache")
        clear.setObjectName("clearAlchemistCache")
        clear.clicked.connect(self.clear_alchemist_cache)
        clear.setToolTip(
            self.alchemist_help(
                clear,
                (
                    "Confirm removal of cached model descriptions. Existing project contours "
                    "and Dungeon Alchemist files are kept."
                ),
                title="Clear Alchemist cache",
            )
        )
        form.addRow(clear)

        action = QWidgetAction(self)
        action.setText("DA contours")
        action.setProperty("dale_tool_key", "DA contours")
        action.setCheckable(True)
        action.setActionGroup(self.tool_set_actions["figures"].actionGroup())
        action.setToolTip(
            self.alchemist_help(
                action,
                (
                    "Dungeon Alchemist contours. Edit additional walls and obstacles from the "
                    "attached DAM file."
                ),
                title="DA contours",
            )
        )
        button = ModeTabButton(self.tool_set_toolbar)
        button.setDefaultAction(action)
        action.setDefaultWidget(button)
        self.tool_set_toolbar.insertAction(self.tool_set_actions["regions"], action)
        action.triggered.connect(lambda: self.select_tool_set("alchemist"))
        self.tool_set_actions["alchemist"] = action
        self.last_tool_modes["alchemist"] = "Select figures"
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.alchemist_categories = make_toolbar(self, "Dungeon Alchemist", vertical=True)
        layout.addWidget(self.alchemist_categories)
        self.alchemist_category_actions = {}
        display = QAction(tool_icon("Show contours"), "Display contours", self)
        display.setCheckable(True)
        display.setChecked(True)
        display.setProperty("dale_tool_key", "Display contours")
        display.setToolTip(
            self.alchemist_help(
                display,
                "Show ordinary contours as stationary snapping references with 30% transparency.",
                title="Display contours",
            )
        )
        display.triggered.connect(self.set_alchemist_reference_display)
        self.alchemist_categories.addAction(display)
        self.alchemist_display_action = display
        command = QAction(tool_icon("Object slices"), "Object slices", self)
        command.setCheckable(True)
        command.setProperty("dale_tool_key", "Object slices")
        command.setToolTip(
            self.alchemist_help(
                command,
                "Open the movable slicing window for selected objects.",
                title="Object slices",
            )
        )
        command.triggered.connect(self.toggle_slice_window)
        self.alchemist_categories.addAction(command)
        self.alchemist_window_action = command
        for category in CATEGORIES:
            title = CATEGORY_TITLES[category]
            command = QAction(self)
            command.setIcon(tool_icon(title))
            command.setText(title)
            command.setCheckable(True)
            command.setChecked(True)
            command.setProperty("dale_tool_key", title)
            command.setToolTip(
                self.alchemist_help(
                    command,
                    (
                        "Show or hide this category in DA contours, Regions, Raster and exported "
                        "Scene JSON."
                    ),
                    title=title,
                    keys=("Right-click: open tool settings.",),
                )
            )
            command.triggered.connect(
                lambda enabled, category=category: self.set_alchemist_category(category, enabled)
            )
            self.alchemist_categories.addAction(command)
            control = self.alchemist_categories.widgetForAction(command)
            control.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            control.customContextMenuRequested.connect(
                lambda _, category=category: self.show_alchemist_category_settings(category)
            )
            ToolSettingsCorner(control)
            self.alchemist_category_actions[category] = command
        controls = make_toolbar(self, "DA contours", vertical=True)
        layout.addWidget(controls)
        from dale.alchemist_thinning_ui import ThinningController

        thinning = QAction(tool_icon("Thin objects"), "Thin objects", self)
        thinning.setCheckable(True)
        thinning.setProperty("dale_tool_key", "Thin objects")
        thinning.setToolTip(
            self.alchemist_help(
                thinning,
                "Thin overlapping trees, bushes and rocks in the current dataset, "
                "independently of selection. Hidden objects are excluded from exports; "
                "zero restores them. Preserve the user selection.",
                title="Thin objects",
                keys=(
                    "Click: enable or disable thinning.",
                    "Ctrl+wheel: change thinning strength, 0..10.",
                ),
            )
        )
        self.thinning_value = ToolSpinBox()
        self.thinning_value.setRange(0, 10)
        self.thinning_button = SizedToolButton(self.thinning_value, thinning, inline=True)
        controls.addWidget(self.thinning_button)
        self.thinning = ThinningController(self, thinning, self.thinning_value)
        self.alchemist_tool_buttons = {}
        same_type = QAction(tool_icon("Select same object type"), "Select same object type", self)
        same_type.setCheckable(False)
        same_type.setProperty("dale_tool_key", "Select same object type")
        purpose = "Select visible objects of the same exact type."
        condition = (
            "DA contours is active and a visible object with a known source type is selected."
        )
        keys = ("Click: select visible objects of the same type.",)
        same_type.setProperty("dale_tooltip_parts", [purpose])
        same_type.setProperty("dale_tooltip_condition", condition)
        same_type.setProperty("dale_tooltip_keys", list(keys))
        same_type.setToolTip(
            self.control_help(
                purpose, title="Select same object type", condition=condition, keys=keys
            )
        )
        same_type.triggered.connect(self.select_same_alchemist_type)
        self.alchemist_same_type_action = same_type
        for name in (
            "Select figures",
            "Rotate figures",
            "Scale figures",
        ):
            if name == "Scale figures":
                editor = ToolSpinBox()
                editor.setRange(1, 100)
                editor.setValue(self.figure_scale_control.value())
                editor.valueChanged.connect(self.figure_scale_control.setValue)
                self.figure_scale_control.valueChanged.connect(editor.setValue)
                button = SizedToolButton(editor, self.mode_actions[name], inline=True)
                controls.addWidget(button)
                self.alchemist_tool_buttons[name] = button
            else:
                controls.addAction(self.mode_actions[name])
                self.alchemist_tool_buttons[name] = controls.widgetForAction(
                    self.mode_actions[name]
                )
            if name == "Select figures":
                controls.addAction(same_type)
        for bar in (self.alchemist_categories, controls):
            self.removeToolBar(bar)
            for command in bar.actions():
                widget = bar.widgetForAction(command)
                if not isinstance(widget, SizedToolButton):
                    widget.setFixedSize(48, 48)
                for corner in widget.findChildren(ToolSettingsCorner):
                    corner.move(widget.width() - 9, widget.height() - 9)
            bar.show()
        for name, button in self.alchemist_tool_buttons.items():
            if name in self.tool_settings_buttons or name == "Select figures":
                button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                button.customContextMenuRequested.connect(
                    lambda _, name=name: self.show_tool_settings(name)
                )
                ToolSettingsCorner(button)
        self.mode_tool_pages["alchemist"] = page
        self.tool_stack.addWidget(page)
        self.toolbars = (*self.toolbars, self.alchemist_categories, controls)
        self.sync_alchemist_controls()

    def choose_alchemist(self):
        candidates = discover_installations(load_alchemist_path(self.preferences_path))
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.t("Choose Dungeon Alchemist"),
            str(candidates[0]) if candidates else self.alchemist_path.text(),
            self.t("Dungeon Alchemist executable (*.exe)"),
        )
        if not path:
            return None
        try:
            executable = installation(path)
            save_alchemist_path(self.preferences_path, str(executable))
            self.alchemist_path.setText(str(executable))
            return executable
        except (OSError, ValueError, sqlite3.Error) as exc:
            self.warning("Dungeon Alchemist", str(exc))
            return None

    def clear_alchemist_cache(self):
        self.flush_slice_window()
        if (
            self.question(
                "Clear Alchemist cache",
                (
                    "Clear cached Dungeon Alchemist models and saved object settings "
                    "(size, rotation, slices and complexity)? Project contours and installed "
                    "game files are kept."
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            AlchemistLibrary(cache_path(self.preferences_path)).clear()
        except (OSError, ValueError, sqlite3.Error) as exc:
            self.warning("Dungeon Alchemist", str(exc))
            return
        data = self.view.session.alchemist if self.view.session else None
        if data is not None:
            self.reload_alchemist_slices(data)

    def reload_alchemist_slices(self, data):
        if (
            self.question(
                "Load object geometry",
                "Load object slices again for the attached Dungeon Alchemist file? "
                "Read local models and rebuild the cache. Current project contours and "
                "their edits are kept.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        candidates = discover_installations(load_alchemist_path(self.preferences_path))
        executable = candidates[0] if candidates else self.choose_alchemist()
        if executable is None:
            return
        library = AlchemistLibrary(cache_path(self.preferences_path), executable)

        def rebuild(report):
            from dale.alchemist import read_map

            report(5, "Reading the Dungeon Alchemist map")
            source = read_map(data.source)
            workshop = source.get("usedWorkshopItems", {})
            report(15, "Reading local object descriptions")
            entries = library.resolve(
                {obj.block_id for obj in data.objects if obj.block_id}, workshop
            )
            library.profiles(entries, workshop, report)
            report(100, "Reading local object geometry")

        try:
            run_task(self, "Loading Dungeon Alchemist", rebuild, cancellable=True)
        except AlchemistCancelled:
            return
        except MissingAlchemistItems as exc:
            self.report_missing_alchemist(exc)
            return
        except (OSError, ValueError, sqlite3.Error) as exc:
            self.warning("Dungeon Alchemist", str(exc))
            return
        if library.geometry_unavailable:
            self.information(
                "Dungeon Alchemist",
                self.t(
                    "Object slices are unavailable for {count} types. "
                    "Current project contours are kept.",
                    count=len(library.geometry_unavailable),
                ),
            )

    def remember_alchemist_parameters(self, session, identifiers, fields):
        from dale.alchemist_presets import settings_for

        if not session.alchemist or not fields:
            return
        try:
            values = settings_for(session, identifiers, fields)
            if values:
                AlchemistLibrary(cache_path(self.preferences_path)).remember_item_settings(values)
        except (OSError, ValueError, sqlite3.Error) as exc:
            self.statusBar().showMessage(
                self.t("Object settings could not be saved: {error}", error=str(exc)), 7000
            )

    def import_alchemist(self, catalog, identifier, path):
        view = catalog.views[identifier]
        if not (view.has_image or view.has_json):
            raise ValueError(
                "Attach a scene image or Scene JSON before importing Dungeon Alchemist contours."
            )
        from dale.alchemist import MAX_SOURCE

        answer = self.question(
            "Load object geometry",
            "Load object geometry? Cache local models in 10-percent height layers and select "
            "the layer at the ground or floor for each object. The first import may take longer. "
            "No keeps circular contours. Unavailable models also keep circles.",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        load_geometry = answer == QMessageBox.StandardButton.Yes
        with Path(path).open("rb") as stream:
            raw = stream.read(MAX_SOURCE + 1)
        candidates = discover_installations(load_alchemist_path(self.preferences_path))
        executable = candidates[0] if candidates else None
        library = AlchemistLibrary(cache_path(self.preferences_path), executable)
        try:
            data, geometry = self.load_alchemist_with_progress(
                raw, path, view.session, library, load_geometry
            )
        except AlchemistCancelled:
            return False
        except MissingAlchemistItems as exc:
            if executable is None:
                self.information(
                    "Dungeon Alchemist",
                    "Choose Dungeon Alchemist.exe to read locally installed object descriptions.",
                )
                executable = self.choose_alchemist()
                if executable is None:
                    return False
                library = AlchemistLibrary(cache_path(self.preferences_path), executable)
                try:
                    data, geometry = self.load_alchemist_with_progress(
                        raw, path, view.session, library, load_geometry
                    )
                except AlchemistCancelled:
                    return False
                except MissingAlchemistItems as missing:
                    self.report_missing_alchemist(missing)
                    return False
            else:
                self.report_missing_alchemist(exc)
                return False
        unavailable = getattr(library, "geometry_unavailable", ())
        if load_geometry and unavailable:
            self.information(
                "Dungeon Alchemist",
                self.t(
                    "Object geometry is unavailable for {count} types. Their circular contours "
                    "are kept. For missing Workshop items, open this map in Dungeon Alchemist "
                    "and install the items there, then attach the DAM again.",
                    count=len(unavailable),
                ),
            )
        if executable:
            save_alchemist_path(self.preferences_path, str(executable))
            self.alchemist_path.setText(str(executable))
        saved = library.item_settings(obj.block_id for obj in data.objects if obj.block_id)
        if saved:
            answer = self.question(
                "Saved object settings",
                self.t(
                    "Use saved size, rotation, slices and complexity for {count} object types? "
                    "Saved slices use local model geometry. No keeps the original settings "
                    "from Dungeon Alchemist.",
                    count=len(saved),
                ),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return False
            if answer == QMessageBox.StandardButton.Yes:
                from dale.alchemist_presets import apply_settings

                if not load_geometry and any("slice" in value for value in saved.values()):
                    try:
                        data, geometry = self.load_alchemist_with_progress(
                            raw, path, view.session, library, True
                        )
                    except AlchemistCancelled:
                        return False
                if any(
                    "slice" in saved.get(obj.block_id, {}) and obj.projection is None
                    for obj in data.objects
                ):
                    self.information(
                        "Saved object settings",
                        "Some saved slices require unavailable local models. "
                        "Their original contours and other saved parameters are kept.",
                    )
                frozen = snapshot(view.session)
                frozen.alchemist = data
                frozen.operations.append(geometry)
                try:
                    geometry = run_task(
                        self,
                        "Applying saved object settings",
                        lambda report: apply_settings(frozen, saved, report),
                        cancellable=True,
                    )
                except AlchemistCancelled:
                    return False
        replaced = view.session.alchemist is not None
        view.session.alchemist = data
        view.session.add(geometry)
        if replaced:
            view.session.trim_history(0)
        view.ui["safe_json_repair"] = True
        catalog.protected_inputs.add(Path(path).resolve())
        return True

    def load_alchemist_with_progress(self, raw, path, session, library, load_geometry=False):
        frozen = snapshot(session)
        return run_task(
            self,
            "Loading Dungeon Alchemist",
            lambda report: import_map(
                raw, Path(path).name, frozen, library, progress=report, load_geometry=load_geometry
            ),
            cancellable=True,
        )

    def enter_alchemist_mode(self, activate=True):
        from dale.alchemist_progress import prepare_da_mode
        from dale.alchemist_render import display_key

        view, session = self.view, self.view.session
        view.cancel_pending()
        frozen = snapshot(session)
        documents = tuple(self.catalog.documents if self.catalog else ())
        layer, safe = view.source_layer, view.safe_json_repair
        cached_analysis = getattr(view, "_alchemist_contour_analysis_cache", None)
        cached_layers = getattr(view, "_source_layers_cache", None)
        previous_section = self.current_tool_set

        def publish(result):
            geometry, working, choices, analysis = result
            if (
                view.session is not session
                or session.alchemist is not frozen.alchemist
                or len(session.operations) != len(frozen.operations)
                or any(
                    a is not b for a, b in zip(session.operations, frozen.operations, strict=False)
                )
                or view.source_layer != layer
                or view.safe_json_repair != safe
            ):
                self.tool_set_actions[self.current_tool_set].setChecked(True)
                return
            view.property_documents = documents
            view._source_layers_cache = (
                session.source,
                view.source_layer_cache_key(geometry),
                choices,
            )
            view._alchemist_contour_analysis_cache = (
                display_key(session.alchemist, working, session.gap_tolerance),
                analysis,
            )
            self.select_tool_set("alchemist", activate)

        self._entering_da_mode = True
        try:
            run_task(
                self,
                "Opening DA contours",
                lambda report: prepare_da_mode(
                    frozen,
                    layer,
                    safe,
                    documents,
                    report,
                    cached_analysis=cached_analysis,
                    cached_layers=cached_layers,
                ),
                publish,
                object_name="alchemistModeProgress",
                publish_refresh=True,
            )
        except Exception as exc:
            self.tool_set_actions[previous_section].setChecked(True)
            self.warning("Opening DA contours", str(exc))
        finally:
            self._entering_da_mode = False

    def prepare_alchemist_display(self):
        """Precompute immutable geometry off-thread before publishing the Qt view."""
        view = self.view
        session = view.session
        if not session or not session.alchemist or view.edit_preview or view.active_gesture:
            return False
        if view.selection_section not in ("regions", "pixels"):
            return False
        geometry = session.geometry()
        documents = tuple(view.property_documents)
        key = (
            id(session),
            geometry,
            geometry.lineage,
            geometry.ancestry,
            geometry.wall_styles,
            session.alchemist,
            view.selection_section,
            view.source_layer,
            view.safe_json_repair,
            session.gap_tolerance,
            documents,
        )
        if key == getattr(self, "_alchemist_display_key", None):
            return False
        frozen = snapshot(session)
        section, layer, safe = view.selection_section, view.source_layer, view.safe_json_repair
        cached = getattr(view, "_alchemist_prepared_analyses", ())

        def publish(result):
            visible, combined, analyses, choices = result
            view._alchemist_analysis_cache = visible
            view._alchemist_prepared_analyses = analyses
            if combined is not None:
                session._analysis_cache = combined
            view._source_layers_cache = (
                session.source,
                view.source_layer_cache_key(geometry),
                choices,
            )
            self._alchemist_display_key = key
            self.refresh_display()

        if not getattr(self, "_alchemist_navigation", False):
            return False
        view.selected_source_layer(geometry)
        # A section change needs region cells, but editing does not prepare export geometry.
        result = prepare_display(
            frozen,
            geometry,
            section,
            layer,
            safe,
            documents,
            cached,
            lambda *_: None,
            choices=view._source_layers_cache[2],
        )
        publish(result)
        return True

    def select_same_alchemist_type(self):
        view = self.view
        if (
            self.current_tool_set != "alchemist"
            or not view.session
            or not view.session.alchemist
            or self.worker
            or view.active_gesture
        ):
            return
        identifiers = same_type_lines(
            view.session.alchemist, view.editing_geometry(), view.figure_line_ids
        )
        if identifiers:
            view.finish_rotation()
            view.figure_line_ids = identifiers
            view.figure_pivot = None
            view.figure_pivot_edges = ()
            self.update_map_info()

    def set_alchemist_individual_transforms(self, enabled):
        if self.view.session and self.view.session.alchemist and not self.view.active_gesture:
            self.view.finish_rotation()
            self.view.session.alchemist = replace(
                self.view.session.alchemist, individual_transforms=enabled
            )
            self.view.individual_transform_settings.update(
                alchemist_rotate=enabled, alchemist_scale=enabled
            )
            self.view.figure_pivot = None
            self.view.figure_pivot_edges = ()
            self.view.update_hover()
            self.view.viewport().update()
        self.sync_alchemist_controls()
        self.update_mode_help()

    def alchemist_double_click_peers(self, identifier):
        from dale.preferences import load_alchemist_same_type, save_alchemist_same_type

        peers = same_type_lines(
            self.view.session.alchemist, self.view.editing_geometry(), (identifier,)
        )
        if not peers:
            return ()
        choice = load_alchemist_same_type(self.preferences_path)
        if choice is not None:
            return peers if choice else ()
        dialog = QMessageBox(
            QMessageBox.Icon.Question,
            self.t("Select same object type"),
            self.t("Select visible objects of this same type?"),
            parent=self,
        )
        dialog.setObjectName("alchemistSameTypeQuestion")
        checkbox = QCheckBox(self.t("Do not ask again"), dialog)
        checkbox.setToolTip(
            self.control_help(
                "Remember this answer. Right-click Select contours to change it.",
                title="Do not ask again",
            )
        )
        dialog.setCheckBox(checkbox)
        for kind, caption, purpose in (
            (
                QMessageBox.StandardButton.Yes,
                "Yes",
                "Select visible objects of the same exact type.",
            ),
            (QMessageBox.StandardButton.No, "No", "Use ordinary connected contour selection."),
            (
                QMessageBox.StandardButton.Cancel,
                "Cancel",
                "Keep the selection from before the double-click.",
            ),
        ):
            button = dialog.addButton(kind)
            button.setText(self.t(caption))
            button.setToolTip(self.control_help(purpose, title=caption))
        dialog.setDefaultButton(QMessageBox.StandardButton.Yes)
        dialog.setEscapeButton(QMessageBox.StandardButton.Cancel)
        answer = dialog.exec()
        if answer == QMessageBox.StandardButton.Cancel:
            return None
        choice = answer == QMessageBox.StandardButton.Yes
        if checkbox.isChecked():
            try:
                save_alchemist_same_type(self.preferences_path, choice)
            except OSError:
                self.statusBar().showMessage(self.t("Preferences could not be written."), 7000)
        return peers if choice else ()

    def report_missing_alchemist(self, missing):
        message = self.t(
            "Open this DAM project in Dungeon Alchemist, wait for its resources to "
            "download there, then retry importing. DALE does not download Workshop "
            "items."
        )
        dialog = QMessageBox(
            QMessageBox.Icon.Warning,
            self.t("Missing Dungeon Alchemist objects"),
            message,
            QMessageBox.StandardButton.Close,
            self,
        )
        dialog.setDetailedText("\n".join(missing.items))
        dialog.exec()

    def toggle_slice_window(self, enabled):
        if (
            not self.view.session
            or not self.view.session.alchemist
            or self.worker
            or self.view.active_gesture
            or (enabled and not self.view.figure_line_ids)
        ):
            self.alchemist_window_action.setChecked(False)
            return
        if self.slice_window is None:
            from dale.alchemist_window import SliceWindow

            self.slice_window = SliceWindow(self)
            self.slice_window.tabs.setCurrentIndex(1)
        if enabled:
            from dale.alchemist import memberships

            session = self.view.session
            selected = set(self.view.figure_line_ids)
            objects = {o.id: o for o in session.alchemist.objects}
            category = next(
                (
                    objects[i].category
                    for r, own in zip(
                        session.geometry().lineage,
                        memberships(session.alchemist, session.geometry()),
                        strict=True,
                    )
                    if r.id in selected
                    for i in sorted(own)
                ),
                None,
            )
            if category:
                self.slice_window.tabs.setCurrentIndex(CATEGORIES.index(category))
            else:
                self.alchemist_window_action.setChecked(False)
                return
        self.slice_window.setVisible(enabled)

    def sync_slice_window(self):
        if hasattr(self, "thinning"):
            self.thinning.sync()
        if hasattr(self, "alchemist_window_action"):
            self.alchemist_window_action.setEnabled(
                bool(self.view.figure_line_ids)
                or bool(self.slice_window and self.slice_window.isVisible())
            )
        if getattr(self, "slice_window", None) is not None:
            self.slice_window.sync()

    def flush_slice_window(self):
        panel = getattr(self, "slice_window", None)
        if (
            panel
            and not panel.flushing
            and (panel.future is not None or (panel.dirty and not panel.busy))
        ):
            panel.flush()
        if hasattr(self, "thinning"):
            self.thinning.flush()

    def sync_alchemist_controls(self):
        if not hasattr(self, "alchemist_category_actions"):
            return
        data = self.view.session.alchemist if self.view.session else None
        action = self.tool_set_actions["alchemist"]
        if action.isVisible() != bool(data):
            action.setVisible(bool(data))
            self.tool_set_toolbar.refresh_tabs()
            self.tool_set_toolbar.layout().invalidate()
            self.top_panels_timer.start(0)
        for index, category in enumerate(CATEGORIES):
            command = self.alchemist_category_actions[category]
            command.setChecked(data.settings[index][0] if data else True)
        self.alchemist_display_action.setChecked(data.show_regular if data else True)
        self.thinning.sync()

    def defer_slice_action(self, callback):
        if self.slice_window and (self.slice_window.dirty or self.slice_window.busy):
            self.slice_window.deferred = self.view.session, callback
            self.slice_window.apply()
            return True
        return False

    def close_slice_controls(self):
        if self.slice_window:
            self.slice_window.flush()
            self.slice_window.executor.shutdown(wait=False, cancel_futures=True)
        self.thinning.close()

    def set_alchemist_reference_display(self, enabled):
        if self.view.session and self.view.session.alchemist:
            self.view.session.alchemist = replace(self.view.session.alchemist, show_regular=enabled)
            self.refresh()

    def set_alchemist_category(self, category, enabled):
        if (
            not self.view.session
            or not self.view.session.alchemist
            or self.worker
            or self.view.active_gesture
        ):
            self.sync_alchemist_controls()
            return
        self.view.cancel_pending()
        data = self.view.session.alchemist
        settings = list(data.settings)
        index = CATEGORIES.index(category)
        settings[index] = enabled, settings[index][1]
        self.view.session.alchemist = replace(data, settings=tuple(settings))
        self.view.figure_line_ids = ()
        self.reset_region_selections()
        self.refresh()

    def show_alchemist_category_settings(self, category):
        if (
            not self.view.session
            or not self.view.session.alchemist
            or self.worker
            or self.view.active_gesture
        ):
            return
        if self.tool_settings_popup:
            self.tool_settings_popup.reject()
        self.flush_slice_window()
        index = CATEGORIES.index(category)
        from dale.alchemist_export import category_settings, encode_settings

        dialog = ToolSettingsDialog(
            self,
            self.t(CATEGORY_TITLES[category]),
            alchemist_minimum=self.view.session.alchemist.settings[index][1],
            alchemist_height=self.view.session.alchemist.minimum_heights_ft[index],
            alchemist_export=category_settings(self.view.session.alchemist, category),
        )
        self.tool_settings_popup = dialog
        session = self.view.session

        def apply():
            if self.view.session is not session or not session.alchemist:
                return
            self.flush_slice_window()
            data = session.alchemist
            json_walls = list(data.json_walls)
            json_walls[index] = encode_settings(dialog.wall_export.values())
            minimum, height = dialog.alchemist_minimum.value(), dialog.alchemist_height.value()
            if (minimum, height) == (data.settings[index][1], data.minimum_heights_ft[index]):
                session.alchemist = replace(data, json_walls=tuple(json_walls))
                if (
                    self.slice_window
                    and self.slice_window.session is session
                    and self.slice_window.baseline
                ):
                    self.slice_window.baseline.alchemist = session.alchemist
                return
            from dale.alchemist import with_estimated_heights
            from dale.alchemist_progress import prepare_da_mode
            from dale.alchemist_render import display_key

            frozen = snapshot(session)
            view = self.view
            layer, safe = view.source_layer, view.safe_json_repair
            documents = tuple(view.property_documents)
            isolated = view.alchemist_isolated_category

            def calculate(report):
                report(1, "Preparing contour categories")
                updated = with_estimated_heights(frozen) if height else frozen.alchemist
                settings, heights = list(updated.settings), list(updated.minimum_heights_ft)
                settings[index] = settings[index][0], minimum
                heights[index] = height
                frozen.alchemist = replace(
                    updated,
                    settings=tuple(settings),
                    minimum_heights_ft=tuple(heights),
                    json_walls=tuple(json_walls),
                )
                prepared = prepare_da_mode(
                    frozen, layer, safe, documents, report, category=isolated
                )
                return frozen.alchemist, prepared

            def publish(result):
                if view.session is not session or session.alchemist is not data:
                    return
                updated, (geometry, working, choices, analysis) = result
                session.alchemist = updated
                if (
                    self.slice_window
                    and self.slice_window.session is session
                    and self.slice_window.baseline
                ):
                    self.slice_window.baseline.alchemist = updated
                view._source_layers_cache = (
                    session.source,
                    view.source_layer_cache_key(geometry),
                    choices,
                )
                view._alchemist_contour_analysis_cache = (
                    display_key(updated, working, session.gap_tolerance),
                    analysis,
                )
                self.refresh()
                self.sync_slice_window()

            try:
                run_task(
                    self, "Preparing contour categories", calculate, publish, publish_refresh=True
                )
            except Exception as exc:
                self.warning("Dungeon Alchemist", str(exc))

        dialog.accepted.connect(apply)
        dialog.destroyed.connect(lambda: self.clear_tool_settings_popup(dialog))
        button = self.alchemist_categories.widgetForAction(
            self.alchemist_category_actions[category]
        )
        point = button.mapToGlobal(QPoint(button.width(), 0))
        screen = button.screen().availableGeometry().adjusted(8, 8, -8, -8)
        content = dialog.alchemist_scroll.widget()
        content.layout().activate()
        desired_height = max(dialog.sizeHint().height(), content.sizeHint().height() + 100)
        minimum_height = min(dialog.minimumSizeHint().height(), screen.height())
        point.setY(max(screen.top(), min(point.y(), screen.bottom() - minimum_height + 1)))
        available_height = screen.bottom() - point.y() + 1
        dialog.setMaximumHeight(screen.height())
        dialog.resize(416, min(desired_height, available_height))
        point.setX(max(screen.left(), min(point.x(), screen.right() - dialog.width() + 1)))
        dialog.move(point)
        dialog.show()


def add_manager_controls(manager, layout):
    layout.addSpacing(10)
    layout.addWidget(QLabel(manager.t("Dungeon Alchemist project")))
    field = QLineEdit()
    field.setObjectName("alchemistFilename")
    field.setMaxLength(256)
    field.setPlaceholderText(manager.t("No Dungeon Alchemist project"))
    field.setToolTip(manager.help("Rename this file label without changing its contents."))
    field.editingFinished.connect(lambda: manager.rename_file("alchemist"))
    manager.file_fields["alchemist"] = field
    layout.addWidget(field)
    row = QHBoxLayout()

    def load():
        path, _ = QFileDialog.getOpenFileName(
            manager,
            manager.t("Load Dungeon Alchemist project"),
            str(manager.owner.input_directory or ""),
            manager.t("Dungeon Alchemist projects (*.dam)"),
        )
        if path:
            result = manager.change(
                lambda catalog: manager.owner.import_alchemist(catalog, manager.selected, path)
            )
            if result:
                manager.owner.remember_directory("input", Path(path).resolve().parent)

    def remove():
        if manager.confirm(
            "Dungeon Alchemist",
            "Remove the attached DAM file and its contours? The original file is kept.",
        ):

            def operation(catalog):
                session = catalog.views[manager.selected].session
                geometry = scoped_geometry(session, scope="regular")
                session.add(geometry)
                session.trim_history(0)
                session.alchemist = None

            manager.change(operation)

    manager.alchemist_load_button = manager.button("Load DAM", load)
    manager.alchemist_remove_button = manager.button("Delete DAM", remove)
    row.addWidget(manager.alchemist_load_button)
    row.addWidget(manager.alchemist_remove_button)
    layout.addLayout(row)
