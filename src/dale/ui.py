"""Local desktop workflow, controls, and export worker lifecycle."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QFont,
    QFontDatabase,
    QIcon,
    QIntValidator,
    QKeySequence,
    QPainterPath,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from shapely.geometry import Point as ShapePoint

from dale import __version__, application_title
from dale.autoclose import AutoCloseIndex
from dale.canvas import GEOMETRY_ERASERS, MapView, line_path
from dale.geometry import offset_region, open_contour_count
from dale.localization import (
    DesktopTranslator,
    prepare_control_tooltips,
    translate,
    translate_static,
)
from dale.overlay_export import crop_bounds, export_overlays, export_regions
from dale.placement import Placement
from dale.preferences import (
    load_directory,
    load_foundry_major,
    load_language,
    load_move_related,
    save_directory,
    save_foundry_major,
    save_language,
    save_move_related,
    settings_path,
)
from dale.project_io import SCHEMA_VERSION, load_project, read_json_documents, save_project
from dale.raster import ExportCancelled, load_preview
from dale.scene import load_pair
from dale.session import Session
from dale.toolbar import (
    SizedToolButton,
    ToolSpinBox,
    apply_theme,
    make_toolbar,
    tool_icon,
)


class ExportWorker(QThread):
    progress = Signal(int)
    outcome = Signal(str, str)

    def __init__(self, session, path, placement, parent, region_indices=None, extra_padding=0):
        super().__init__(parent)
        self.source = session.source
        self.operations = tuple(session.operations)
        self.path = path
        self.placement = placement
        self.region_indices = region_indices
        self.extra_padding = extra_padding
        self.session = Session(
            session.source,
            session.origin,
            list(session.operations),
            gap_tolerance=session.gap_tolerance,
            contour_offset=session.contour_offset,
        )

    def run(self):
        try:
            destination = export_overlays(
                self.session,
                self.path,
                self.placement,
                self.progress.emit,
                self.isInterruptionRequested,
                region_indices=self.region_indices,
                extra_padding=self.extra_padding,
                individual_regions=self.region_indices is not None,
            )
            self.outcome.emit("success", str(destination))
        except ExportCancelled:
            self.outcome.emit("cancelled", "PNG export cancelled; destination unchanged.")
        except Exception as exc:
            self.outcome.emit("error", str(exc))


class MainWindow(QMainWindow):
    def __init__(self, preferences_path=None):
        super().__init__()
        self.preferences_path = preferences_path or settings_path()
        self.language = load_language(self.preferences_path)
        self.remembered_move_related = load_move_related(self.preferences_path)
        self.input_directory = load_directory(self.preferences_path, "input")
        self.output_directory = load_directory(self.preferences_path, "output")
        self.setWindowTitle(application_title())
        self.resize(1280, 860)
        self.setMinimumSize(1024, 768)
        self.worker = None
        self.progress = None
        self.export_outcome = None
        self.project_path = None
        self.loaded_project = None
        self.json_workspaces = []
        self.saved_state = None
        self.regions = ()
        self.region_key = None
        self.selected_region = None
        self.current_tool_set = "geometry"
        self.last_tool_modes = {
            "geometry": "Edit points",
            "regions": "Select regions",
            "pixels": "Erase",
        }
        self.view = MapView()
        self.view.move_related = self.remembered_move_related is True
        self.view.changed.connect(self.refresh)
        self.view.auto_close_requested.connect(self.confirm_auto_close)
        self.view.region_clicked.connect(self.toggle_region_at)
        self.view.regions_transformed.connect(self.select_transformed_regions)
        self.view.message.connect(
            lambda message: self.statusBar().showMessage(self.t(message), 7000)
        )
        self.info = QLabel("Open an upper-floor JPG and its Foundry JSON to begin.")
        self.info.setWordWrap(True)
        self.map_info = QLabel()
        self.map_info.setWordWrap(True)
        self.feedback_label = QLabel()
        self.feedback_label.setWordWrap(True)
        self.region_control = QComboBox()
        self.region_control.setMinimumWidth(120)
        self.region_control.setToolTip(
            "Choose all closed regions or one region to highlight and export."
        )
        self.region_control.currentIndexChanged.connect(self.select_region)
        self.diagnostics = QLabel()
        self.diagnostics.setWordWrap(True)
        self.version = QComboBox()
        self.version.addItems(["Foundry 14", "Foundry 13"])
        self.version.setCurrentIndex(0 if load_foundry_major(self.preferences_path) == 14 else 1)
        self.elevation = QComboBox()
        self.elevation.setEditable(True)
        self.elevation.addItems([str(i) for i in range(-20, 105, 5)])
        self.elevation.setCurrentText("5")
        self.elevation.lineEdit().setValidator(QIntValidator(-1_000_000, 1_000_000, self))
        self.elevation.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.elevation.setToolTip(
            "Presets every 5 ft; type any whole number of feet, including negatives."
        )
        self.placement_hint = QLabel()
        self.placement_hint.setWordWrap(True)
        self.version.currentTextChanged.connect(self.update_placement_hint)
        self.version.currentIndexChanged.connect(self.remember_foundry_version)
        self.elevation.currentTextChanged.connect(self.update_placement_hint)
        self.origin_x, self.origin_y = QDoubleSpinBox(), QDoubleSpinBox()
        for control in (self.origin_x, self.origin_y):
            control.setRange(-1_000_000, 1_000_000)
            control.setDecimals(2)
        alignment = QPushButton("Apply alignment")
        alignment.setToolTip(
            "Apply source-scene origin offsets. Existing edits require save/discard."
        )
        alignment.clicked.connect(self.apply_alignment)
        self.gap_tolerance = QDoubleSpinBox()
        self.gap_tolerance.setRange(0, 4096)
        self.gap_tolerance.setDecimals(2)
        self.gap_tolerance.setSingleStep(1)
        self.gap_tolerance.setToolTip(
            "Connect free wall ends within this distance in original image pixels. "
            "0 disables joining."
        )
        self.contour_offset = QSpinBox()
        self.contour_offset.setRange(-4096, 4096)
        self.contour_offset.setToolTip(
            "Original image pixels: positive expands the contour, negative shrinks it."
        )
        self.gap_tolerance.valueChanged.connect(self.update_contour_settings)
        self.contour_offset.valueChanged.connect(self.update_contour_settings)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.language_control = QComboBox()
        self.language_control.addItems(["English", "Русский"])
        self.language_control.setCurrentIndex(1 if self.language == "ru" else 0)
        self.language_control.setToolTip(
            "Switch the interface language. The choice is saved locally."
        )
        self.language_control.currentIndexChanged.connect(
            lambda index: self.set_language("en" if index == 0 else "ru")
        )
        form.addRow("Target", self.version)
        form.addRow("Contour offset (px)", self.contour_offset)
        form.addRow("Regions", self.region_control)
        form.addRow("Language", self.language_control)
        self.settings_group = QGroupBox("Settings")
        self.settings_group.setLayout(form)
        self.information_group = QGroupBox("Information")
        information_layout = QVBoxLayout(self.information_group)
        for label in (self.info, self.map_info, self.diagnostics, self.feedback_label):
            information_layout.addWidget(label)
        sidebar = QVBoxLayout()
        sidebar.addWidget(self.information_group)
        sidebar.addWidget(self.settings_group)
        sidebar.addStretch()
        panel = QWidget()
        panel.setLayout(sidebar)
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setWidget(panel)
        sidebar_scroll.setFixedWidth(360)
        layout = QHBoxLayout()
        left_panel = QWidget()
        left_panel.setFixedWidth(64)
        self.tool_column = QVBoxLayout(left_panel)
        self.tool_column.setContentsMargins(0, 0, 0, 0)
        self.tool_column.setSpacing(4)
        self.tool_stack = QStackedWidget()
        self.tool_stack.setFixedWidth(64)
        self.tool_stack.setStyleSheet(
            "QStackedWidget { background: #303030; border: 1px solid #494949; }"
        )
        self.tool_column.addWidget(self.tool_stack)
        layout.addWidget(left_panel)
        layout.addWidget(self.view, 1)
        layout.addWidget(sidebar_scroll)
        root = QWidget()
        root.setLayout(layout)
        self.setCentralWidget(root)
        self.statusBar().hide()
        self.statusBar().messageChanged.connect(self.feedback_label.setText)
        general = make_toolbar(self, "General")
        categories = make_toolbar(self, "Tool sets", new_row=True)
        geometry = make_toolbar(self, "Contours", vertical=True)
        region_tools = make_toolbar(self, "Regions", vertical=True)
        pixels = make_toolbar(self, "Raster", vertical=True)
        self.toolbars = (general, categories, geometry, region_tools, pixels)
        self.geometry_eraser_tiles = {}
        self.sized_tools = {}
        for bar in (geometry, region_tools, pixels):
            container = QWidget()
            column = QVBoxLayout(container)
            column.setContentsMargins(0, 0, 0, 0)
            column.addWidget(bar)
            self.tool_stack.addWidget(container)

        def action(bar, title, handler, shortcut=None):
            item = QAction(title, self)
            if bar.orientation() == Qt.Orientation.Vertical:
                item.setIcon(tool_icon(title))
                item.setProperty("dale_icon_only", True)
            if bar in (general, categories):
                item.setProperty(
                    "dale_display_key",
                    {
                        "Open pair": "Image + JSON",
                        "Open project": "Open",
                        "Save project": "Save",
                        "Save project as…": "Save as…",
                        "Close map": "Close",
                        "Export PNGs": "Export",
                        "Pan": "Hand",
                        "Show walls": "Walls",
                    }.get(title, title),
                )
            item.triggered.connect(handler)
            if shortcut:
                item.setShortcut(shortcut)
            sizes = {
                "Erase lines": (
                    1,
                    512,
                    24,
                    "geometry_brush_control",
                    lambda v: self.set_geometry_brush("Erase lines", v),
                ),
                "Erase vertices": (
                    1,
                    512,
                    24,
                    "vertex_brush_control",
                    lambda v: self.set_geometry_brush("Erase vertices", v),
                ),
                "Auto-close": (1, 256, 14, "auto_close_control", self.set_auto_close_distance),
                "Erase": (1, 4096, 40, "brush_control", lambda v: self.set_brush("Erase", v)),
                "Restore": (
                    1,
                    4096,
                    40,
                    "restore_brush_control",
                    lambda v: self.set_brush("Restore", v),
                ),
                "Snapping (px)": (0, 256, 14, "snap_distance", self.set_snap_distance),
                "Close all contours": (1, 256, 14, "global_close_control", lambda value: None),
                "Export padding (px)": (
                    0,
                    4096,
                    0,
                    "export_padding_control",
                    lambda v: self.update_map_info(),
                ),
            }
            if title in sizes:
                low, high, initial, attribute, handler = sizes[title]
                editor = ToolSpinBox()
                editor.setRange(low, high)
                editor.setValue(initial)
                editor.valueChanged.connect(handler)
                setattr(self, attribute, editor)
                tile = SizedToolButton(editor, item)
                self.sized_tools[title] = tile
                if title in GEOMETRY_ERASERS:
                    self.geometry_eraser_tiles[title] = tile
                bar.addWidget(tile)
            else:
                bar.addAction(item)
                if bar.orientation() == Qt.Orientation.Vertical:
                    bar.widgetForAction(item).setFixedSize(48, 48)
            return item

        tool_sets = QActionGroup(self)
        tool_sets.setExclusive(True)
        self.tool_set_actions = {}
        for key, title in (("geometry", "Contours"), ("regions", "Regions"), ("pixels", "Raster")):
            item = action(
                categories, title, lambda checked=False, key=key: self.select_tool_set(key)
            )
            item.setCheckable(True)
            tool_sets.addAction(item)
            self.tool_set_actions[key] = item
        self.tool_set_actions["geometry"].setChecked(True)
        categories.addSeparator()

        action(general, "Open pair", self.open_pair, "Ctrl+I")
        action(general, "JSON", self.open_json)
        action(general, "Open project", self.open_project, QKeySequence.StandardKey.Open)
        action(general, "Save project", self.save_project_file, QKeySequence.StandardKey.Save)
        save_as = action(
            general,
            "Save project as…",
            lambda: self.save_project_file(save_as=True),
            QKeySequence.StandardKey.SaveAs,
        )
        self.menuBar().setToolTip("Project file menu.")
        file_menu = self.menuBar().addMenu("File")
        file_menu.setToolTipsVisible(True)
        file_menu.addAction(save_as)
        action(general, "Close map", self.close_document)
        self.export_action = action(general, "Export PNGs", self.export, "Ctrl+E")
        general.addSeparator()
        action(general, "Undo", lambda: self.history(False), QKeySequence.StandardKey.Undo)
        action(general, "Redo", lambda: self.history(True), QKeySequence.StandardKey.Redo)
        modes = QActionGroup(self)
        modes.setExclusive(True)
        self.mode_actions = {}
        for bar, names in (
            (categories, ("Pan",)),
            (geometry, ("Edit points", "New line", "Auto-close", "Erase lines", "Erase vertices")),
            (region_tools, ("Select regions", "Move regions")),
            (pixels, ("Erase", "Restore")),
        ):
            for mode in names:
                item = action(bar, mode, lambda checked=False, m=mode: self.activate_mode(m))
                item.setCheckable(True)
                item.setChecked(mode == "Pan")
                modes.addAction(item)
                self.mode_actions[mode] = item
        self.move_button = region_tools.widgetForAction(self.mode_actions["Move regions"])
        self.move_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.move_button.customContextMenuRequested.connect(lambda: self.configure_region_move())
        action(categories, "Fit", self.view.fit_map, "F")
        self.walls_action = action(categories, "Show walls", self.toggle_walls)
        self.walls_action.setCheckable(True)
        self.walls_action.setChecked(True)
        self.geometry_brush_control = self.geometry_eraser_tiles["Erase lines"].editor()
        self.vertex_brush_control = self.geometry_eraser_tiles["Erase vertices"].editor()
        pixels.addSeparator()
        action(pixels, "Remove outside", lambda: self.mask("outside"))
        action(pixels, "Remove inside", lambda: self.mask("inside"))
        self.auto_close_tile = self.sized_tools["Auto-close"]
        self.snap_action = action(geometry, "Snapping (px)", self.set_snapping)
        self.snap_action.setCheckable(True)
        self.snap_action.setChecked(True)
        self.snap_tile = self.sized_tools["Snapping (px)"]
        action(geometry, "Close all contours", self.close_all_contours)
        self.export_regions_action = action(
            region_tools, "Export selected regions", lambda: self.export(selected_only=True)
        )
        action(region_tools, "Export padding (px)", lambda: self.export_padding_control.setFocus())
        self.tool_column.addStretch()
        for bar in (geometry, region_tools, pixels):
            bar.ensurePolished()
            bar.setFixedHeight(bar.sizeHint().height())
        self.tool_stack.setFixedHeight(self.tool_stack.currentWidget().sizeHint().height())
        self.view.size_changed.connect(self.sync_tool_sizes)
        QApplication.instance().installEventFilter(self)
        tips = {
            "Open pair": "Load a source JPG and matching wall JSON.",
            "JSON": (
                "Load another wall JSON for the current JPG. "
                "Save existing edits before replacing the source pair."
            ),
            "Open project": "Open a portable .dale archive including sources and undo history.",
            "Save project": (
                "Save sources, masks, geometry, preferences, and undo/redo in one .dale file."
            ),
            "Save project as…": (
                "Save sources, masks, geometry, preferences, and undo/redo in one .dale file."
            ),
            "Export PNGs": (
                "Export separate cropped PNGs with a 3 px guard and a placement manifest."
            ),
            "Pan": "Drag to move the map. Right-drag works in every tool.",
            "Auto-close": (
                "Hover to trace connected lines and valid continuations. "
                "White edges show affected lines; "
                "dashed lines preview extensions. Click to extend existing lines "
                "along their directions after confirmation in one undo step."
            ),
            "Close all contours": (
                "Extend eligible lines across the whole map after confirmation. "
                "Distance uses screen pixels."
            ),
            "New line": (
                "Press for the first point, drag, release for the second. "
                "Snap now or when moving points."
            ),
            "Erase lines": (
                "Erase entire line segments touched by the circle. Drag is one undo step."
            ),
            "Erase vertices": (
                "Erase vertices inside the circle; reconnect ordinary line neighbors. "
                "Branching vertices remove their connected edges."
            ),
            "Close map": "Close the current map after offering to save its project.",
            "Snapping (px)": (
                "Enable snapping for new lines and moved vertices; vertices take priority."
            ),
            "Contours": "Edit lines, vertices, auto-close, and snapping.",
            "Regions": "Select closed regions and export their PNGs.",
            "Raster": "Erase or restore image pixels.",
            "Select regions": (
                "Click closed regions to toggle selection. Click empty space to clear selection."
            ),
            "Move regions": (
                "Drag selected region contours. Ctrl+wheel: scale. "
                "Alt+wheel: rotate by 0.1 degrees "
                "around their common center. Raster pixels stay unchanged. "
                "Right-click: configure connected lines. Escape: cancel the current gesture."
            ),
            "Export selected regions": "Export only the highlighted regions as separate PNGs.",
            "Export padding (px)": (
                "Additional transparent pixels around each region box, beyond the manda"
                "tory 3 px guard."
            ),
            "Edit points": (
                "Click a line to insert; drag a fixed-size circle to move; "
                "double-click it to delete. "
                "Hold Alt to move along the selected line vector."
            ),
            "Erase": "Paint transparency over unwanted objects.",
            "Restore": "Restore opacity from the original JPG.",
            "Remove outside": "Keep enclosed regions and make their exterior transparent.",
            "Remove inside": "Erase enclosed regions and keep their exterior.",
            "Undo": "Undo the last complete stroke, mask, or geometry edit.",
            "Redo": "Redo the last undone edit.",
            "Fit": "Show the complete source map.",
            "Show walls": "Show or hide wall and contour overlays.",
        }
        for item in self.findChildren(QAction):
            if item.text() in tips:
                description = tips[item.text()]
                parts = (
                    [item.text(), description] if item.property("dale_icon_only") else [description]
                )
                if item.text() in (
                    "New line",
                    "Edit points",
                    "Erase lines",
                    "Erase vertices",
                    "Erase",
                    "Restore",
                ):
                    parts.append("Escape: cancel the current gesture.")
                if item.text() in ("Erase", "Restore", *GEOMETRY_ERASERS):
                    parts.append("Ctrl+wheel: change this tool's diameter.")
                if item.text() == "Auto-close":
                    parts.append("Ctrl+wheel: change the auto-close distance.")
                item.setProperty("dale_tooltip_parts", parts)
                item.setToolTip("\n".join(parts))
            display_key = item.property("dale_display_key")
            if display_key:
                item.setText(display_key)
        self.version.setToolTip(
            "Select the target Foundry generation. The choice is saved between launches."
        )
        for control in (self.origin_x, self.origin_y):
            control.setToolTip(
                "Source scene origin in scene pixels. Apply alignment to start a fresh session."
            )
        self.view.setToolTip("")
        self.view.viewport().setToolTip("")
        self.view.horizontalScrollBar().setToolTip("Pan the map horizontally.")
        self.view.verticalScrollBar().setToolTip("Pan the map vertically.")
        sidebar_scroll.verticalScrollBar().setToolTip("Scroll map settings and editing help.")
        sidebar_scroll.horizontalScrollBar().setToolTip("Scroll map settings and editing help.")
        for control in (
            self.version,
            self.contour_offset,
            self.language_control,
            self.region_control,
        ):
            form.labelForField(control).setToolTip(control.toolTip())
        self.set_language(self.language, persist=False)
        self.statusBar().showMessage(self.t("Ready. All editing is local."))

    def t(self, text, **values):
        return translate(text, self.language, **values)

    def set_language(self, language, persist=True):
        self.language = language
        app = QApplication.instance()
        if not hasattr(app, "dale_translator"):
            app.dale_translator = DesktopTranslator(app)
            app.installTranslator(app.dale_translator)
        app.dale_translator.language = language
        self.language_control.blockSignals(True)
        self.language_control.setCurrentIndex(1 if language == "ru" else 0)
        self.language_control.blockSignals(False)
        prepare_control_tooltips(self)
        translate_static(
            self,
            language,
            (
                self.info,
                self.diagnostics,
                self.placement_hint,
                self.map_info,
                self.region_control,
            ),
        )
        self.update_size_help()
        self.region_control.setToolTip(
            self.t("Choose all closed regions or one region to highlight and export.")
        )
        if not self.view.session:
            self.info.setText(self.t("Open an upper-floor JPG and its Foundry JSON to begin."))
        self.update_placement_hint()
        self.refresh()
        self.statusBar().clearMessage()
        if persist:
            try:
                save_language(self.preferences_path, language)
            except OSError:
                self.statusBar().showMessage(
                    self.t("Language changed; preferences could not be written."), 7000
                )

    def information(self, title, text, *options):
        return QMessageBox.information(self, self.t(title), self.t(text), *options)

    def warning(self, title, text, *options):
        return QMessageBox.warning(self, self.t(title), self.t(text), *options)

    def question(self, title, text, *options):
        return QMessageBox.question(self, self.t(title), self.t(text), *options)

    def close_all_contours(self):
        if self.view.session:
            tolerance = self.global_close_control.value() / max(self.view.transform().m11(), 1e-9)
            index = AutoCloseIndex(self.view.session.geometry(), tolerance)
            plan = index.all()
            self.view.auto_close_review = True
            self.view.hover_path = line_path(plan.segments)
            self.view.auto_join_path = line_path(plan.extensions)
            self.view.viewport().update()
            try:
                self.confirm_auto_close(plan)
            finally:
                self.view.auto_close_review = False
                self.view.update_hover()

    def confirm_auto_close(self, plan):
        session = self.view.session
        if session is None:
            return
        original = session.geometry()
        geometry = plan.apply(original)
        changed = geometry != original
        if changed:
            text = self.t(
                (
                    "Affected segments: {segments}\nEndpoint extensions: {extensions}\nShared"
                    " intersections: {connections}\n\nConnect the highlighted lines?"
                ),
                segments=len(plan.segments),
                extensions=len(plan.extensions),
                connections=len(plan.connections),
            )
        elif plan.segments:
            text = self.t(
                "No changes are needed or possible at this distance. Touching lines are"
                " already connected; remaining gaps need a larger distance or New line."
            )
        else:
            text = self.t("No lines under the cursor. Point at a line and click again.")
        dialog = QMessageBox(
            QMessageBox.Icon.Question, self.t("Confirm auto-close"), text, parent=self
        )
        dialog.setObjectName("autoCloseConfirmation")
        cancel = dialog.addButton(QMessageBox.StandardButton.Cancel)
        yes = dialog.addButton(QMessageBox.StandardButton.Yes)
        cancel.setText(self.t("Cancel"))
        yes.setText(self.t("Yes"))
        cancel.setToolTip(self.t("Cancel without changing geometry. Escape: cancel."))
        yes.setToolTip(self.t("Apply the shown connections as one undo step."))
        yes.setEnabled(changed)
        dialog.setDefaultButton(cancel)
        dialog.setEscapeButton(cancel)
        if dialog.exec() == QMessageBox.StandardButton.Yes and changed:
            if self.view.session is session and session.geometry() == original:
                session.add(geometry)
                self.refresh()

    def placement(self):
        text = self.elevation.currentText()
        if not self.elevation.lineEdit().hasAcceptableInput():
            raise ValueError("Enter a whole-number elevation in feet.")
        return Placement(14 if self.version.currentIndex() == 0 else 13, int(text))

    def update_placement_hint(self):
        try:
            placement = self.placement()
            text = self.t(
                (
                    "Foundry 13: place the PNG as a tile at {height} ft. Floor visibil"
                    "ity depends on the scene's module configuration."
                )
                if placement.foundry_major == 13
                else (
                    "Foundry 14: assign the PNG to the intended Scene Level at {height"
                    "} ft and configure its elevation range/visibility."
                ),
                height=placement.elevation_ft,
            )
        except ValueError:
            text = self.t("Elevation must be a whole number of feet.")
        self.placement_hint.setText(
            text
            + "\n\n"
            + self.t("Placement in Foundry is configured separately. PNG edge guard: 3 px.")
        )

    def remember_foundry_version(self):
        try:
            save_foundry_major(
                self.preferences_path, 14 if self.version.currentIndex() == 0 else 13
            )
        except OSError:
            self.statusBar().showMessage(
                self.t("Foundry version changed; preferences could not be written."), 7000
            )

    def set_brush(self, mode, value):
        self.view.raster_diameters[mode] = value
        self.view.viewport().update()

    def select_tool_set(self, key, activate=True):
        self.current_tool_set = key
        self.tool_stack.setCurrentIndex({"geometry": 0, "regions": 1, "pixels": 2}[key])
        self.tool_stack.setFixedHeight(self.tool_stack.currentWidget().sizeHint().height())
        self.update_size_help()
        self.tool_set_actions[key].setChecked(True)
        if activate:
            self.activate_mode(self.last_tool_modes[key])

    def update_size_help(self):
        for tile in self.sized_tools.values():
            tile.set_help(self.language)

    def configure_region_move(self):
        dialog = QMessageBox(
            QMessageBox.Icon.Question,
            self.t("Move regions"),
            self.t("Move all connected lines?"),
            parent=self,
        )
        dialog.setObjectName("regionMoveConfiguration")
        dialog.setInformativeText(
            self.t(
                "Yes includes lines connected within the snapping distance. "
                "No moves only selected boundaries. Right-click this tool to reopen this dialog."
            )
        )
        remember = QCheckBox(self.t("Remember choice"), dialog)
        remember.setToolTip(
            self.t("Remember this choice between launches. Right-click the tool to change it.")
        )
        remember.setChecked(self.remembered_move_related is not None)
        dialog.setCheckBox(remember)
        for key, tip in (
            ("Yes", "Move selected boundaries and related lines."),
            ("No", "Move only selected region boundaries."),
            ("Cancel", "Cancel without changing geometry. Escape: cancel."),
        ):
            button = dialog.addButton(getattr(QMessageBox.StandardButton, key))
            button.setText(self.t(key))
            button.setToolTip(self.t(tip))
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        result = dialog.exec()
        if result not in (QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No):
            return False
        self.view.move_related = result == QMessageBox.StandardButton.Yes
        self.remembered_move_related = self.view.move_related if remember.isChecked() else None
        try:
            save_move_related(self.preferences_path, self.remembered_move_related)
        except OSError:
            self.statusBar().showMessage(self.t("Preferences could not be written."), 7000)
        return True

    def activate_mode(self, mode, prompt=True):
        if mode == "Move regions" and prompt:
            if not self.selected_regions:
                self.activate_mode("Select regions")
                self.information("Select regions", "Select at least one closed region on the map.")
                return
            if self.remembered_move_related is None and not self.configure_region_move():
                self.mode_actions[self.view.mode].setChecked(True)
                return
        if mode != "Pan":
            key = (
                "pixels"
                if mode in ("Erase", "Restore")
                else "regions"
                if mode in ("Select regions", "Move regions")
                else "geometry"
            )
            self.last_tool_modes[key] = mode
            self.select_tool_set(key, activate=False)
        self.mode_actions[mode].setChecked(True)
        self.view.set_mode(mode)
        if mode == "Select regions" and self.selected_regions is None:
            self.selected_regions = ()
            self.update_map_info()

    def set_geometry_brush(self, mode, value):
        self.view.geometry_diameters[mode] = value
        self.sync_tool_sizes()
        self.view.update_hover()

    def sync_tool_sizes(self):
        for control, value in (
            (self.brush_control, self.view.raster_diameters["Erase"]),
            (self.restore_brush_control, self.view.raster_diameters["Restore"]),
            (self.geometry_brush_control, self.view.geometry_diameters["Erase lines"]),
            (self.vertex_brush_control, self.view.geometry_diameters["Erase vertices"]),
            (self.auto_close_control, self.view.auto_close_distance),
        ):
            control.blockSignals(True)
            control.setValue(value)
            control.blockSignals(False)

    def set_auto_close_distance(self, value):
        self.view.auto_close_distance = value
        self.view.update_hover()

    def set_snapping(self, enabled):
        self.view.snap_enabled = enabled
        self.view.snap = None
        self.view.viewport().update()

    def set_snap_distance(self, value):
        self.view.snap_distance = value
        self.view.snap = None
        self.view.viewport().update()

    def eventFilter(self, watched, event):
        if (
            event.type() == QEvent.Type.Wheel
            and isinstance(watched, QWidget)
            and watched.window() == self
            and self.view.mode == "Move regions"
            and event.modifiers() & Qt.KeyboardModifier.AltModifier
        ):
            steps = event.angleDelta().y() / 120
            if steps:
                self.view.transform_regions(angle=(round(steps) or (1 if steps > 0 else -1)) / 10)
            event.accept()
            return True
        if (
            event.type() == QEvent.Type.Wheel
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
            and isinstance(watched, QWidget)
            and watched.window() == self
        ):
            steps = event.angleDelta().y() / 120
            if steps:
                control = watched
                sizeable = (
                    self.brush_control,
                    self.restore_brush_control,
                    self.export_padding_control,
                    self.global_close_control,
                    self.geometry_brush_control,
                    self.vertex_brush_control,
                    self.auto_close_control,
                    self.snap_distance,
                    self.gap_tolerance,
                    self.contour_offset,
                )
                while control is not None and control not in sizeable:
                    if isinstance(control, SizedToolButton):
                        control = control.editor()
                        break
                    control = control.parentWidget()
                if control in sizeable:
                    control.stepBy(round(steps) or (1 if steps > 0 else -1))
                else:
                    self.view.resize_tool(steps)
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def close_document(self):
        if self.worker or not self.can_discard():
            return
        self.view.clear_map()
        self.release_json_workspaces()
        if self.loaded_project:
            self.loaded_project.close()
            self.loaded_project = None
        self.project_path = self.saved_state = None
        self.info.setText(self.t("Open an upper-floor JPG and its Foundry JSON to begin."))
        self.diagnostics.clear()
        self.update_map_info()

    def toggle_walls(self, value):
        self.view.show_walls = value
        self.view.viewport().update()

    def update_contour_settings(self):
        if self.view.session:
            self.view.session.gap_tolerance = self.gap_tolerance.value()
            self.view.session.contour_offset = self.contour_offset.value()
            self.refresh()
            self.statusBar().showMessage(
                self.t(
                    "Contour preview updated. Apply Remove outside/inside to use these settings."
                ),
                7000,
            )

    def can_discard(self):
        if self.view.active_gesture:
            self.information("Finish editing", "Finish or cancel the active gesture first.")
            return False
        if not self.view.session:
            return True
        if self.saved_state is not None and self.document_state() == self.saved_state:
            return True
        if self.saved_state is None and not self.view.session.operations:
            return True
        answer = self.question(
            "Save changes?",
            "Save the project and editing history before continuing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project_file()
        return answer == QMessageBox.StandardButton.Discard

    def document_state(self):
        session = self.view.session
        return (
            tuple(session.operations),
            tuple(session.future),
            session.origin,
            session.gap_tolerance,
            session.contour_offset,
            self.version.currentIndex(),
            self.elevation.currentText(),
        )

    def ui_state(self):
        placement = self.placement()
        center = self.view.mapToScene(self.view.viewport().rect().center())
        return {
            "foundry_major": placement.foundry_major,
            "elevation_ft": placement.elevation_ft,
            "raster_erase_diameter": self.view.raster_diameters["Erase"],
            "raster_restore_diameter": self.view.raster_diameters["Restore"],
            "export_padding_px": self.export_padding_control.value(),
            "export_regions": self.selected_regions,
            "move_related_lines": self.view.move_related,
            "mode": self.view.mode,
            "show_walls": self.view.show_walls,
            "zoom": self.view.transform().m11(),
            "center": [center.x(), center.y()],
            "auto_close_distance_px": self.view.auto_close_distance,
            "global_close_distance_px": self.global_close_control.value(),
            "language": self.language,
            "snap_enabled": self.view.snap_enabled,
            "snap_distance_px": self.view.snap_distance,
            "line_eraser_diameter": self.view.geometry_diameters["Erase lines"],
            "vertex_eraser_diameter": self.view.geometry_diameters["Erase vertices"],
            "tool_set": self.current_tool_set,
        }

    def save_project_file(self, checked=False, save_as=False):
        if not self.view.session:
            return False
        if self.view.active_gesture:
            self.information("Finish editing", "Finish the active drag before saving.")
            return False
        path = self.project_path
        if path is None or save_as:
            filename = (
                path.name if path else self.view.session.source.image_path.with_suffix(".dale").name
            )
            default = (self.output_directory or (path.parent if path else Path.cwd())) / filename
            selected, _ = QFileDialog.getSaveFileName(
                self, self.t("Save DALE project"), str(default), self.t("DALE projects (*.dale)")
            )
            if not selected:
                return False
            path = Path(selected)
            if path.suffix.lower() != ".dale":
                path = path.with_name(path.name + ".dale")
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            save_project(self.view.session, path, self.ui_state())
            self.remember_directory("output", path.parent)
            self.project_path = path
            self.saved_state = self.document_state()
            self.statusBar().showMessage(self.t("Saved complete project: {path}", path=path), 10000)
            return True
        except Exception as exc:
            self.warning("Cannot save project", str(exc))
            return False
        finally:
            QApplication.restoreOverrideCursor()

    def open_project(self):
        if not self.can_discard():
            return
        selected, _ = QFileDialog.getOpenFileName(
            self,
            self.t("Open DALE project"),
            str(self.input_directory or Path.cwd()),
            self.t("DALE projects (*.dale)"),
        )
        if selected:
            self.load_project_file(Path(selected))

    def load_project_file(self, path):
        loaded = None
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            loaded = load_project(path)
            preview = load_preview(loaded.session.source)
            self.view.assign(loaded.session, preview)
            if self.loaded_project:
                self.loaded_project.close()
            self.loaded_project, loaded = loaded, None
            session, settings = self.loaded_project.session, self.loaded_project.ui_state
            self.set_language(settings["language"])
            controls = (self.gap_tolerance, self.contour_offset, self.origin_x, self.origin_y)
            for control in controls:
                control.blockSignals(True)
            self.gap_tolerance.setValue(session.gap_tolerance)
            self.contour_offset.setValue(session.contour_offset)
            self.origin_x.setValue(session.origin[0])
            self.origin_y.setValue(session.origin[1])
            for control in controls:
                control.blockSignals(False)
            self.version.setCurrentIndex(0 if settings["foundry_major"] == 14 else 1)
            self.elevation.setCurrentText(str(settings["elevation_ft"]))
            self.brush_control.setValue(settings["raster_erase_diameter"])
            self.restore_brush_control.setValue(settings["raster_restore_diameter"])
            self.export_padding_control.setValue(settings["export_padding_px"])
            self.geometry_brush_control.setValue(settings["line_eraser_diameter"])
            self.vertex_brush_control.setValue(settings["vertex_eraser_diameter"])
            self.auto_close_control.setValue(settings["auto_close_distance_px"])
            self.global_close_control.setValue(settings["global_close_distance_px"])
            self.snap_distance.setValue(settings["snap_distance_px"])
            self.snap_action.setChecked(settings["snap_enabled"])
            self.view.snap_enabled = settings["snap_enabled"]
            selected = settings["export_regions"]
            self.selected_regions = (
                selected
                if selected is None or all(i < len(self.regions) for i in selected)
                else None
            )
            self.walls_action.setChecked(settings["show_walls"])
            self.view.show_walls = settings["show_walls"]
            self.select_tool_set(settings["tool_set"], activate=False)
            self.view.move_related = settings["move_related_lines"]
            self.activate_mode(settings["mode"], prompt=False)
            self.view.setTransform(QTransform.fromScale(settings["zoom"], settings["zoom"]))
            self.view.centerOn(*settings["center"])
            self.project_path = path
            self.remember_directory("input", path.resolve().parent)
            self.saved_state = self.document_state()
            self.info.setText(path.name)
            self.refresh()
            return True
        except Exception as exc:
            if loaded:
                loaded.close()
            self.warning("Cannot open project", str(exc))
            return False
        finally:
            QApplication.restoreOverrideCursor()

    def open_pair(self):
        if not self.can_discard():
            return
        image_path, _ = QFileDialog.getOpenFileName(
            self,
            self.t("Open source JPG"),
            str(self.input_directory or Path("examples")),
            self.t("JPEG images (*.jpg *.jpeg)"),
        )
        if not image_path:
            return
        json_path = Path(image_path).with_suffix(".json")
        if not json_path.is_file():
            selected, _ = QFileDialog.getOpenFileName(
                self,
                self.t("Open matching Foundry JSON"),
                str(json_path),
                self.t("JSON files (*.json)"),
            )
            if not selected:
                return
            json_path = Path(selected)
        self.load_sources(Path(image_path), json_path)

    def open_json(self):
        if not self.view.session:
            self.information("JSON", "Open a source JPG before loading another JSON.")
            return
        if not self.can_discard():
            return
        selected, _ = QFileDialog.getOpenFileName(
            self,
            self.t("Import wall JSON"),
            str(self.input_directory or self.view.session.source.json_path.parent),
            self.t("JSON or DALE projects (*.json *.dale)"),
        )
        if selected:
            path = Path(selected)
            if path.suffix.lower() == ".dale":
                self.import_project_json(path)
            else:
                self.load_sources(self.view.session.source.image_path, path)

    def import_project_json(self, path):
        try:
            documents = read_json_documents(path)
            self.remember_directory("input", path.resolve().parent)
            dialog = QDialog(self)
            dialog.setObjectName("jsonDocumentSelection")
            dialog.setWindowTitle(self.t("JSON files in DALE project"))
            dialog.resize(520, 300)
            layout = QVBoxLayout(dialog)
            layout.addWidget(QLabel(self.t("Choose wall JSON to use with the current JPG.")))
            choices = QListWidget(dialog)
            choices.setToolTip(
                self.t("Select the original or an updated JSON stored in this project.")
            )
            for document in documents:
                kind = self.t("Original JSON" if document.kind == "original" else "Updated JSON")
                item = QListWidgetItem(f"{document.name} — {kind}", choices)
                item.setToolTip(f"{document.name}\n{kind}")
            choices.setCurrentRow(0)
            layout.addWidget(choices)
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            )
            buttons.button(QDialogButtonBox.StandardButton.Ok).setText(self.t("Import"))
            buttons.button(QDialogButtonBox.StandardButton.Ok).setToolTip(
                self.t("Import the selected JSON for the current JPG.")
            )
            buttons.button(QDialogButtonBox.StandardButton.Cancel).setToolTip(
                self.t("Cancel without changing geometry. Escape: cancel.")
            )
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            choices.itemDoubleClicked.connect(lambda item: dialog.accept())
            layout.addWidget(buttons)
            prepare_control_tooltips(dialog)
            translate_static(dialog, self.language)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            document = documents[choices.currentRow()]
            workspace = tempfile.TemporaryDirectory(prefix="dale-json-")
            self.json_workspaces.append(workspace)
            selected = Path(workspace.name) / f"{document.id}.json"
            selected.write_bytes(document.data)
            if self.load_sources(
                self.view.session.source.image_path, selected, remember_input=False
            ):
                self.remember_directory("input", path.resolve().parent)
            self.release_json_workspaces(keep_current=True)
        except Exception as exc:
            self.warning("Cannot import JSON", str(exc))

    def release_json_workspaces(self, keep_current=False):
        current = self.view.session.source if keep_current and self.view.session else None
        retained = []
        for workspace in self.json_workspaces:
            root = Path(workspace.name)
            if current and any(
                path.is_relative_to(root) for path in (current.image_path, current.json_path)
            ):
                retained.append(workspace)
            else:
                workspace.cleanup()
        self.json_workspaces = retained

    def load_sources(self, image_path: Path, json_path: Path, remember_input=True):
        try:
            source = load_pair(image_path, json_path)
            preview = load_preview(source)
            if remember_input:
                self.remember_directory("input", json_path.resolve().parent)
            self.view.assign(
                Session(
                    source,
                    gap_tolerance=self.gap_tolerance.value(),
                    contour_offset=self.contour_offset.value(),
                ),
                preview,
            )
            self.origin_x.setValue(0)
            self.origin_y.setValue(0)
            self.info.setText(f"{source.image_path.name}\n" + "\n".join(source.warnings))
            self.refresh()
            if self.loaded_project and not source.image_path.is_relative_to(
                Path(self.loaded_project.workspace.name)
            ):
                self.loaded_project.close()
                self.loaded_project = None
            self.project_path = None
            self.saved_state = self.document_state()
            self.release_json_workspaces(keep_current=True)
            return True
        except Exception as exc:
            self.warning("Cannot open source pair", str(exc))
            return False

    def remember_directory(self, purpose, directory):
        directory = directory.resolve()
        setattr(self, f"{purpose}_directory", directory)
        try:
            save_directory(self.preferences_path, purpose, directory)
        except OSError:
            self.statusBar().showMessage(self.t("Preferences could not be written."), 7000)

    def refresh(self):
        self.view.refresh()
        self.update_map_info()
        if self.view.session:
            analysis = self.view.analysis
            self.diagnostics.setText(
                self.t(
                    "Selectable cells: {cells}\nEditing operations: {operations}",
                    cells=analysis.faces,
                    operations=len(self.view.session.operations),
                )
            )

    @property
    def selected_region(self):
        return (
            self.selected_regions[0]
            if self.selected_regions is not None and len(self.selected_regions) == 1
            else None
        )

    @selected_region.setter
    def selected_region(self, value):
        self.selected_regions = None if value is None else (value,)

    def select_region(self, index):
        data = self.region_control.itemData(index)
        self.selected_regions = None if data is None else tuple(data)
        self.view.region_pivot = None
        self.update_map_info()

    def toggle_region_at(self, point):
        self.view.region_pivot = None
        hit = min(
            (i for i, polygon in enumerate(self.regions) if polygon.covers(ShapePoint(point))),
            key=lambda i: self.regions[i].area,
            default=None,
        )
        selected = set(self.selected_regions or ())
        if hit is None:
            selected.clear()
        elif hit in selected:
            selected.remove(hit)
        else:
            selected.add(hit)
        self.selected_regions = tuple(sorted(selected))
        self.update_map_info()

    def select_transformed_regions(self, result):
        polygons = result["polygons"]
        self.selected_regions = tuple(
            i
            for i, cell in enumerate(self.regions)
            if any(p.buffer(1e-7).covers(cell.representative_point()) for p in polygons)
        )
        self.update_map_info()
        self.view.region_pivot = result["pivot"]

    def update_map_info(self):
        session = self.view.session
        if session:
            try:
                regions = export_regions(session, individual=True)
            except ValueError:
                regions = ()
        else:
            regions = ()
        key = tuple(polygon.wkb for polygon in regions)
        if key != self.region_key:
            self.selected_regions = (
                () if self.view.mode in ("Select regions", "Move regions") else None
            )
            self.view.region_pivot = None
            self.region_key = key
        self.regions = regions
        self.view.region_polygons = tuple(regions[i] for i in self.selected_regions or ())
        self.region_control.blockSignals(True)
        self.region_control.clear()
        self.region_control.addItem(self.t("All regions"), None)
        for index in range(len(regions)):
            self.region_control.addItem(self.t("Region {number}", number=index + 1), (index,))
        if self.selected_regions is None:
            selected_index = 0
        elif len(self.selected_regions) == 1:
            selected_index = self.selected_regions[0] + 1
        else:
            self.region_control.addItem(
                self.t("Selected: {count}", count=len(self.selected_regions)), self.selected_regions
            )
            selected_index = self.region_control.count() - 1
        self.region_control.setCurrentIndex(selected_index)
        self.region_control.setEnabled(bool(regions))
        self.region_control.blockSignals(False)
        self.view.selected_path = QPainterPath()
        for index in self.selected_regions or ():
            polygon = regions[index]
            for ring in (polygon.exterior, *polygon.interiors):
                coordinates = list(ring.coords)
                self.view.selected_path.moveTo(*coordinates[0])
                for point in coordinates[1:]:
                    self.view.selected_path.lineTo(*point)
                self.view.selected_path.closeSubpath()
        self.view.selected_path.setFillRule(Qt.FillRule.OddEvenFill)
        if not session:
            self.map_info.setText(self.t("Map: not loaded\nClosed: 0 | Open: 0"))
            return
        try:
            selected = (
                export_regions(session)
                if self.selected_regions is None and regions
                else tuple(
                    offset_region(regions[i], session.contour_offset)
                    for i in self.selected_regions or ()
                )
            )
        except ValueError:
            selected = ()
        if not selected:
            detail = self.t("PNG: none")
        else:
            padding = self.export_padding_control.value()
            bounds = []
            for polygon in selected:
                try:
                    bounds.append(crop_bounds(polygon, padding, session.source.size))
                except ValueError:
                    pass
            if not bounds:
                detail = self.t("PNG: none (selection outside the source map)")
            elif len(bounds) == 1:
                x, y, right, bottom = bounds[0]
                detail = self.t(
                    "PNG: {width} × {height} (+{margin} px)",
                    width=right - x,
                    height=bottom - y,
                    margin=3 + padding,
                )
            else:
                largest = max(bounds, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
                detail = self.t(
                    "PNG: {count} · max {width} × {height} (+{margin} px)",
                    count=len(bounds),
                    width=largest[2] - largest[0],
                    height=largest[3] - largest[1],
                    margin=3 + padding,
                )
        self.map_info.setText(
            self.t(
                "Map: {width} × {height} px\n{detail}\nClosed: {closed} | Open: {open}",
                width=session.source.size[0],
                height=session.source.size[1],
                closed=(
                    0
                    if self.view.analysis.area.is_empty
                    else 1
                    if self.view.analysis.area.geom_type == "Polygon"
                    else len(self.view.analysis.area.geoms)
                ),
                open=open_contour_count(self.view.analysis.unresolved),
                detail=detail,
            )
        )
        self.map_info.setToolTip(
            self.t(
                "Closed: connected closed regions in current geometry. "
                "Open: connected groups of unresolved lines. "
                "Export bounds include 3 px on every side."
            )
        )
        self.view.viewport().update()

    def apply_alignment(self):
        if self.view.session and self.can_discard():
            session = Session(
                self.view.session.source,
                (self.origin_x.value(), self.origin_y.value()),
                gap_tolerance=self.gap_tolerance.value(),
                contour_offset=self.contour_offset.value(),
            )
            self.view.assign(session, self.view.preview)
            self.refresh()

    def history(self, redo):
        self.view.cancel_pending()
        if self.view.session:
            (self.view.session.redo if redo else self.view.session.undo)()
            self.refresh()

    def mask(self, mode):
        if not self.view.session:
            return
        analysis = self.view.analysis
        if not analysis.faces:
            self.information(
                "Close a boundary first",
                "No enclosed region exists. Use Auto-close for nearby gaps "
                "or New line to draw a boundary.",
            )
            return
        if (
            analysis.unresolved
            and self.question(
                "Review open contours",
                self.t(
                    "{count} unresolved segments remain. "
                    "They may be gaps or unused/internal lines.\n"
                    "Apply the mask to the closed regions anyway? "
                    "Choose No to repair with Auto-close or New line.",
                    count=len(analysis.unresolved),
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            operation = self.view.session.make_mask(mode)
        except ValueError as exc:
            self.information("Review contour offset", str(exc))
            return
        self.view.session.add(operation)
        self.refresh()

    def export(self, selected_only=False):
        if not self.view.session or self.worker:
            return
        if self.view.active_gesture:
            self.information("Finish editing", "Finish or cancel the active gesture first.")
            return
        if self.selected_regions == () or (selected_only and self.selected_regions is None):
            self.activate_mode("Select regions")
            self.information("Select regions", "Select at least one closed region on the map.")
            return
        try:
            placement = self.placement()
        except ValueError as exc:
            self.warning("Invalid elevation", str(exc))
            return
        default = self.output_directory or (
            self.project_path.parent if self.project_path else Path.cwd()
        )
        path = QFileDialog.getExistingDirectory(
            self, self.t("Export separate PNGs with 3 px edge guard"), str(default)
        )
        if not path:
            return
        self.remember_directory("output", Path(path))
        self.export_action.setEnabled(False)
        self.export_regions_action.setEnabled(False)
        self.progress = QProgressDialog(
            self.t("Exporting separate PNGs with 3 px edge guard…"), self.t("Cancel"), 0, 100, self
        )
        self.progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.progress.setAutoClose(False)
        self.progress.setAutoReset(False)
        self.progress.setMinimumDuration(0)
        self.worker = ExportWorker(
            self.view.session,
            Path(path),
            placement,
            self,
            self.selected_regions,
            self.export_padding_control.value(),
        )
        self.worker.progress.connect(self.progress.setValue)
        self.worker.outcome.connect(self.record_outcome)
        self.worker.finished.connect(self.export_finished)
        self.progress.canceled.connect(self.cancel_export)
        self.worker.start()

    def cancel_export(self):
        if self.worker:
            self.worker.requestInterruption()
            self.progress.setLabelText(self.t("Cancelling after the current decode/stripe…"))

    def record_outcome(self, outcome, text):
        self.export_outcome = (outcome, text)

    def export_finished(self):
        self.progress.close()
        self.worker.deleteLater()
        self.worker = None
        self.export_action.setEnabled(True)
        self.export_regions_action.setEnabled(True)
        outcome, text = self.export_outcome or ("error", "Export ended without a result.")
        self.export_outcome = None
        if outcome == "error":
            self.warning("Export failed", text)
        elif outcome == "success":
            self.statusBar().showMessage(self.t("Exported {path}", path=text), 15000)
        else:
            self.statusBar().showMessage(self.t(text), 10000)

    def closeEvent(self, event):
        if self.worker:
            self.cancel_export()
            self.statusBar().showMessage(
                self.t("Cancelling export. Close the window after export stops.")
            )
            event.ignore()
        elif self.can_discard():
            self.release_json_workspaces()
            if self.loaded_project:
                self.loaded_project.close()
                self.loaded_project = None
            event.accept()
        else:
            event.ignore()


def configure_application(app):
    app.setApplicationName("DALE")
    app.setWindowIcon(QIcon(str(Path(__file__).with_name("assets") / "favicon.ico")))
    app.setStyle("Fusion")
    apply_theme(app)
    if sys.platform == "win32" and not QFontDatabase.families():
        font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"
        if font_path.exists():
            font_id = QFontDatabase.addApplicationFont(str(font_path))
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                app.setFont(QFont(families[0], 9))


def main():
    parser = argparse.ArgumentParser(description="DALE desktop floor overlay editor")
    parser.add_argument("--image", type=Path)
    parser.add_argument("--scene", type=Path)
    parser.add_argument("project", type=Path, nargs="?")
    parser.add_argument("--smoke-report", type=Path, help=argparse.SUPPRESS)
    options = parser.parse_args()
    if bool(options.image) != bool(options.scene):
        parser.error("Pass both --image and --scene to open a map pair.")
    if options.project and options.image:
        parser.error("Open a project or an image pair, not both.")
    app = QApplication([sys.argv[0]])
    configure_application(app)
    window = MainWindow()
    window.show()
    if options.image:
        window.load_sources(options.image, options.scene)
    elif options.project:
        window.load_project_file(options.project)
    if options.smoke_report:

        def smoke_report():
            report = {
                "version": __version__,
                "window_title": window.windowTitle(),
                "window_icon_loaded": not window.windowIcon().isNull(),
                "geometry_eraser_diameters": window.view.geometry_diameters,
                "auto_close_distance_px": window.view.auto_close_distance,
                "global_close_distance_px": window.global_close_control.value(),
                "tool_set": window.current_tool_set,
                "selected_regions": window.selected_regions,
                "export_padding_px": window.export_padding_control.value(),
                "raster_diameters": window.view.raster_diameters,
                "move_related_lines": window.view.move_related,
                "project_schema_version": SCHEMA_VERSION,
                "lineage_edges": len(window.view.session.geometry().lineage)
                if window.view.session
                else 0,
                "json_document_count": 1 + len(window.view.session.json_documents)
                if window.view.session
                else 0,
                "editing_mode": window.view.mode,
                "language": window.language,
                "foundry_major": window.placement().foundry_major,
                "window_visible": window.isVisible(),
                "minimum_window": [window.minimumWidth(), window.minimumHeight()],
                "map_info": window.map_info.text(),
                "footer_visible": window.statusBar().isVisible(),
                "project_loaded": bool(window.project_path),
                "dimensions": window.view.session.source.size if window.view.session else None,
                "operations": len(window.view.session.operations) if window.view.session else 0,
            }
            options.smoke_report.write_text(json.dumps(report), encoding="utf-8")
            window.grab().save(str(options.smoke_report.with_suffix(".png")))
            window.windowIcon().pixmap(256, 256).save(
                str(options.smoke_report.with_name(options.smoke_report.stem + "-icon.png"))
            )
            app.quit()

        QTimer.singleShot(500, smoke_report)
    sys.exit(app.exec())
