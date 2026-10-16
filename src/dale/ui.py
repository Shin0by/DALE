"""Local desktop workflow, controls, and export worker lifecycle."""

from __future__ import annotations

import argparse
import json
import os
import sys
from itertools import pairwise
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
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
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

from dale import __version__, application_title
from dale.canvas import GEOMETRY_ERASERS, MapView, line_path
from dale.geometry import open_contour_count
from dale.localization import (
    DesktopTranslator,
    prepare_control_tooltips,
    translate,
    translate_static,
)
from dale.overlay_export import crop_bounds, export_overlays, export_regions
from dale.placement import Placement
from dale.preferences import (
    load_foundry_major,
    load_language,
    save_foundry_major,
    save_language,
    settings_path,
)
from dale.project_io import load_project, save_project
from dale.raster import ExportCancelled, load_preview
from dale.scene import load_pair
from dale.session import Session
from dale.toolbar import (
    NumericToolTile,
    SizedToolButton,
    ToolSpinBox,
    apply_theme,
    make_toolbar,
    tool_icon,
)


class ExportWorker(QThread):
    progress = Signal(int)
    outcome = Signal(str, str)

    def __init__(self, session, path, placement, parent, region_index=None):
        super().__init__(parent)
        self.source = session.source
        self.operations = tuple(session.operations)
        self.path = path
        self.placement = placement
        self.region_index = region_index
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
                region_index=self.region_index,
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
        self.setWindowTitle(application_title())
        self.resize(1280, 860)
        self.setMinimumSize(1024, 768)
        self.worker = None
        self.progress = None
        self.export_outcome = None
        self.project_path = None
        self.loaded_project = None
        self.saved_state = None
        self.regions = ()
        self.region_key = None
        self.selected_region = None
        self.current_tool_set = "geometry"
        self.last_tool_modes = {"geometry": "Edit points", "pixels": "Erase"}
        self.view = MapView()
        self.view.changed.connect(self.refresh)
        self.view.message.connect(
            lambda message: self.statusBar().showMessage(self.t(message), 7000)
        )
        self.info = QLabel("Open an upper-floor JPG and its Foundry JSON to begin.")
        self.info.setWordWrap(True)
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
        form.addRow("Elevation (ft)", self.elevation)
        form.addRow("Scene origin X", self.origin_x)
        form.addRow("Scene origin Y", self.origin_y)
        form.addRow("Join gaps up to (px)", self.gap_tolerance)
        form.addRow("Contour offset (px)", self.contour_offset)
        sidebar = QVBoxLayout()
        sidebar.addWidget(self.info)
        sidebar.addLayout(form)
        sidebar.addWidget(alignment)
        sidebar.addWidget(self.placement_hint)
        sidebar.addWidget(
            QLabel(
                "Cyan: closed regions\nRed: open contours (RGB 255, 0, 0)\n"
                "Lines: 3 px with black edges"
            )
        )
        sidebar.addWidget(self.diagnostics)
        help_text = QLabel(
            "Right-drag: pan in every tool\nWheel: zoom at cursor\n"
            "Ctrl+wheel: active tool size\nAlt-click: free closure corner\n\n"
            "New line: press, drag, release\nEdit points: click line, drag circle\n"
            "Double-click circle: delete\nGeometry erasers: drag the circle\n"
            "Escape: cancel current gesture\n\n"
            "Snapping (px): distance to existing geometry.\nVertices take priority over lines.\n\n"
            "Ctrl+S: save complete project\nPNG: cropped regions + 3 px guard."
        )
        help_text.setWordWrap(True)
        sidebar.addWidget(help_text)
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
        self.footer_label = QLabel()
        self.footer_label.setMinimumWidth(100)
        self.footer_label.setMinimumHeight(24)
        self.footer_label.setMargin(2)
        self.statusBar().setMinimumHeight(28)
        self.statusBar().addPermanentWidget(self.footer_label, 1)
        self.region_control = QComboBox()
        self.region_control.setMinimumWidth(120)
        self.region_control.setToolTip(
            "Choose all closed regions or one region to highlight and export."
        )
        self.region_control.currentIndexChanged.connect(self.select_region)
        self.statusBar().addPermanentWidget(self.region_control)
        self.statusBar().addPermanentWidget(self.language_control)
        general = make_toolbar(self, "General")
        categories = make_toolbar(self, "Tool sets", new_row=True)
        geometry = make_toolbar(self, "Lines and vertices", vertical=True)
        pixels = make_toolbar(self, "Pixels", vertical=True)
        self.toolbars = (general, categories, geometry, pixels)
        self.geometry_eraser_tiles = {}
        for bar in (geometry, pixels):
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
            if title in GEOMETRY_ERASERS:
                editor = ToolSpinBox()
                editor.setRange(1, 512)
                editor.setValue(self.view.geometry_diameters[title])
                editor.valueChanged.connect(
                    lambda value, mode=title: self.set_geometry_brush(mode, value)
                )
                tile = SizedToolButton(editor, item)
                self.geometry_eraser_tiles[title] = tile
                bar.addWidget(tile)
            else:
                bar.addAction(item)
            if bar.orientation() == Qt.Orientation.Vertical and title not in GEOMETRY_ERASERS:
                bar.widgetForAction(item).setFixedSize(48, 48)
            return item

        tool_sets = QActionGroup(self)
        tool_sets.setExclusive(True)
        self.tool_set_actions = {}
        for key, title in (("geometry", "Lines and vertices"), ("pixels", "Pixels")):
            item = action(
                categories, title, lambda checked=False, key=key: self.select_tool_set(key)
            )
            item.setCheckable(True)
            tool_sets.addAction(item)
            self.tool_set_actions[key] = item
        self.tool_set_actions["geometry"].setChecked(True)
        categories.addSeparator()

        action(general, "Open pair", self.open_pair, "Ctrl+I")
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
            (geometry, ("Edit points", "New line", "Closure", "Erase lines", "Erase vertices")),
            (pixels, ("Erase", "Restore")),
        ):
            for mode in names:
                item = action(bar, mode, lambda checked=False, m=mode: self.activate_mode(m))
                item.setCheckable(True)
                item.setChecked(mode == "Pan")
                modes.addAction(item)
                self.mode_actions[mode] = item
        action(categories, "Fit", self.view.fit_map, "F")
        self.walls_action = action(categories, "Show walls", self.toggle_walls)
        self.walls_action.setCheckable(True)
        self.walls_action.setChecked(True)
        self.geometry_brush_control = self.geometry_eraser_tiles["Erase lines"].editor()
        self.vertex_brush_control = self.geometry_eraser_tiles["Erase vertices"].editor()
        pixels.addSeparator()
        action(pixels, "Remove outside", lambda: self.mask("outside"))
        action(pixels, "Remove inside", lambda: self.mask("inside"))
        brush = self.brush_control = ToolSpinBox()
        brush.setRange(1, 4096)
        brush.setValue(40)
        brush.valueChanged.connect(self.set_brush)
        self.size_tile = NumericToolTile(brush, "Brush diameter")
        self.tool_column.addWidget(self.size_tile, 0, Qt.AlignmentFlag.AlignHCenter)
        self.snap_action = QAction(tool_icon("Snapping (px)"), "Snapping (px)", self)
        self.snap_action.triggered.connect(self.set_snapping)
        self.snap_action.setCheckable(True)
        self.snap_action.setChecked(True)
        self.snap_distance = ToolSpinBox()
        self.snap_distance.setRange(0, 256)
        self.snap_distance.setValue(14)
        self.snap_distance.valueChanged.connect(self.set_snap_distance)
        self.snap_tile = NumericToolTile(self.snap_distance, "Snapping (px)", self.snap_action)
        self.tool_column.addWidget(self.snap_tile, 0, Qt.AlignmentFlag.AlignHCenter)
        self.tool_column.addStretch()
        for bar in (geometry, pixels):
            bar.ensurePolished()
            bar.setFixedHeight(bar.sizeHint().height())
        self.tool_stack.setFixedHeight(self.tool_stack.currentWidget().sizeHint().height())
        self.view.size_changed.connect(self.sync_tool_sizes)
        QApplication.instance().installEventFilter(self)
        tips = {
            "Open pair": "Load a source JPG and matching wall JSON.",
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
            "Closure": "Snap the first/last click to a wall; Alt-click adds free corners.",
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
            "Lines and vertices": "Show the single-column line and vertex tools beside the map.",
            "Pixels": "Show the single-column pixel editing tools beside the map.",
            "Edit points": (
                "Click a line to insert; drag a fixed-size circle t"
                "o move; double-click it to delete."
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
                    "Closure",
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
        brush.setToolTip("Circular brush diameter in original image pixels, independent of zoom.")
        self.view.setToolTip(
            "Right-drag pans, wheel zooms, Ctrl+wheel changes tool size. Escape cancels a gesture."
        )
        self.view.horizontalScrollBar().setToolTip("Pan the map horizontally.")
        self.view.verticalScrollBar().setToolTip("Pan the map vertically.")
        sidebar_scroll.verticalScrollBar().setToolTip("Scroll map settings and editing help.")
        sidebar_scroll.horizontalScrollBar().setToolTip("Scroll map settings and editing help.")
        for control in (
            self.version,
            self.elevation,
            self.origin_x,
            self.origin_y,
            self.gap_tolerance,
            self.contour_offset,
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
                self.footer_label,
                self.region_control,
            ),
        )
        self.update_size_help()
        self.snap_tile.set_help(
            "Snapping (px)",
            "Distance to existing vertices or lines. Vertices take priority. "
            "Click the magnet to toggle snapping.",
            self.language,
        )
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

    def set_brush(self, value):
        self.view.diameter = value
        self.view.viewport().update()

    def select_tool_set(self, key, activate=True):
        self.current_tool_set = key
        self.tool_stack.setCurrentIndex(0 if key == "geometry" else 1)
        self.tool_stack.setFixedHeight(self.tool_stack.currentWidget().sizeHint().height())
        self.update_size_help()
        self.tool_set_actions[key].setChecked(True)
        if activate:
            self.activate_mode(self.last_tool_modes[key])

    def update_size_help(self):
        self.size_tile.setVisible(self.current_tool_set == "pixels")
        for tile in self.geometry_eraser_tiles.values():
            tile.set_help(self.language)
        title = (
            "Restore brush diameter (px)"
            if self.last_tool_modes["pixels"] == "Restore"
            else "Pixel eraser diameter (px)"
        )
        description = "Diameter in original image pixels. Ctrl+wheel changes it."
        self.size_tile.set_help(title, description, self.language)

    def activate_mode(self, mode):
        if mode != "Pan":
            key = "pixels" if mode in ("Erase", "Restore") else "geometry"
            self.last_tool_modes[key] = mode
            self.select_tool_set(key, activate=False)
        self.mode_actions[mode].setChecked(True)
        self.view.set_mode(mode)

    def set_geometry_brush(self, mode, value):
        self.view.geometry_diameters[mode] = value
        self.sync_tool_sizes()
        self.view.viewport().update()

    def sync_tool_sizes(self):
        for control, value in (
            (self.brush_control, self.view.diameter),
            (self.geometry_brush_control, self.view.geometry_diameters["Erase lines"]),
            (self.vertex_brush_control, self.view.geometry_diameters["Erase vertices"]),
        ):
            control.blockSignals(True)
            control.setValue(value)
            control.blockSignals(False)

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
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
            and isinstance(watched, QWidget)
            and watched.window() == self
        ):
            steps = event.angleDelta().y() / 120
            if steps:
                control = watched
                sizeable = (
                    self.brush_control,
                    self.geometry_brush_control,
                    self.vertex_brush_control,
                    self.snap_distance,
                    self.gap_tolerance,
                    self.contour_offset,
                )
                while control is not None and control not in sizeable:
                    if isinstance(control, (NumericToolTile, SizedToolButton)):
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
        if self.loaded_project:
            self.loaded_project.close()
            self.loaded_project = None
        self.project_path = self.saved_state = None
        self.info.setText(self.t("Open an upper-floor JPG and its Foundry JSON to begin."))
        self.diagnostics.clear()
        self.update_footer()

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
            self.information("Finish editing", "Finish or cancel the active stroke/closure first.")
            return False
        if not self.view.session:
            return True
        if self.saved_state is not None and self.document_state() == self.saved_state:
            return True
        if self.saved_state is None and not self.view.session.operations and not self.view.pending:
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
            tuple(self.view.pending),
        )

    def ui_state(self):
        placement = self.placement()
        center = self.view.mapToScene(self.view.viewport().rect().center())
        return {
            "foundry_major": placement.foundry_major,
            "elevation_ft": placement.elevation_ft,
            "brush_diameter": self.view.diameter,
            "mode": self.view.mode,
            "show_walls": self.view.show_walls,
            "zoom": self.view.transform().m11(),
            "center": [center.x(), center.y()],
            "pending_closure": self.view.pending,
            "language": self.language,
            "snap_enabled": self.view.snap_enabled,
            "snap_distance_px": self.view.snap_distance,
            "geometry_diameter": self.view.geometry_diameter,
            "line_eraser_diameter": self.view.geometry_diameters["Erase lines"],
            "vertex_eraser_diameter": self.view.geometry_diameters["Erase vertices"],
            "export_region": self.selected_region if self.selected_region is not None else -1,
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
            default = path or self.view.session.source.image_path.with_suffix(".dale")
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
            self, self.t("Open DALE project"), "", self.t("DALE projects (*.dale)")
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
            self.brush_control.setValue(settings["brush_diameter"])
            self.geometry_brush_control.setValue(settings["line_eraser_diameter"])
            self.vertex_brush_control.setValue(settings["vertex_eraser_diameter"])
            self.snap_distance.setValue(settings["snap_distance_px"])
            self.snap_action.setChecked(settings["snap_enabled"])
            self.view.snap_enabled = settings["snap_enabled"]
            selected = settings["export_region"]
            self.region_control.setCurrentIndex(selected + 1 if selected < len(self.regions) else 0)
            self.walls_action.setChecked(settings["show_walls"])
            self.view.show_walls = settings["show_walls"]
            self.select_tool_set(settings["tool_set"], activate=False)
            self.activate_mode(settings["mode"])
            self.view.pending = list(settings["pending_closure"])
            self.view.setTransform(QTransform.fromScale(settings["zoom"], settings["zoom"]))
            self.view.centerOn(*settings["center"])
            self.project_path = path
            self.saved_state = self.document_state()
            self.info.setText(
                f"{path.name}\n{session.source.size[0]:,} × {session.source.size[1]:,} px"
            )
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
            self, self.t("Open source JPG"), "examples", self.t("JPEG images (*.jpg *.jpeg)")
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

    def load_sources(self, image_path: Path, json_path: Path):
        try:
            source = load_pair(image_path, json_path)
            preview = load_preview(source)
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
            self.info.setText(
                f"{source.image_path.name}\n{source.size[0]:,} × {source.size[1]:,} px\n"
                + "\n".join(source.warnings)
            )
            self.refresh()
            if self.loaded_project:
                self.loaded_project.close()
                self.loaded_project = None
            self.project_path = None
            self.saved_state = self.document_state()
        except Exception as exc:
            self.warning("Cannot open source pair", str(exc))

    def refresh(self):
        self.view.refresh()
        self.update_footer()
        if self.view.session:
            analysis = self.view.analysis
            self.diagnostics.setText(
                self.t(
                    "Closed faces: {faces}\nUnresolved segments: {unresolved}\n"
                    "Gap joins: {joins}\nEditing operations: {operations}",
                    faces=analysis.faces,
                    unresolved=len(analysis.unresolved),
                    joins=len(analysis.joins),
                    operations=len(self.view.session.operations),
                )
            )

    def select_region(self, index):
        self.selected_region = index - 1 if index > 0 else None
        self.update_footer()

    def update_footer(self):
        session = self.view.session
        if session:
            try:
                regions = export_regions(session)
            except ValueError:
                regions = ()
        else:
            regions = ()
        key = tuple(polygon.wkb for polygon in regions)
        if key != self.region_key:
            self.selected_region = None
            self.region_key = key
        self.regions = regions
        self.region_control.blockSignals(True)
        self.region_control.clear()
        self.region_control.addItem(self.t("All regions"))
        for index in range(len(regions)):
            self.region_control.addItem(self.t("Region {number}", number=index + 1))
        self.region_control.setCurrentIndex(
            self.selected_region + 1 if self.selected_region is not None else 0
        )
        self.region_control.setEnabled(bool(regions))
        self.region_control.blockSignals(False)
        self.view.selected_path = QPainterPath()
        if self.selected_region is not None:
            polygon = regions[self.selected_region]
            for ring in (polygon.exterior, *polygon.interiors):
                self.view.selected_path.addPath(line_path(pairwise(ring.coords)))
            self.view.selected_path.setFillRule(Qt.FillRule.OddEvenFill)
        if not session:
            self.footer_label.setText(self.t("Map: not loaded | Closed: 0 | Open: 0"))
            return
        if not regions:
            detail = self.t("PNG: none")
        else:
            selected = (
                (regions[self.selected_region],) if self.selected_region is not None else regions
            )
            bounds = [crop_bounds(polygon) for polygon in selected]
            if len(bounds) == 1:
                x, y, right, bottom = bounds[0]
                detail = self.t(
                    "PNG: {width} × {height} (+3 px)",
                    width=right - x,
                    height=bottom - y,
                )
            else:
                largest = max(bounds, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
                detail = self.t(
                    "PNG: {count} · max {width} × {height} (+3 px)",
                    count=len(bounds),
                    width=largest[2] - largest[0],
                    height=largest[3] - largest[1],
                )
        self.footer_label.setText(
            self.t(
                "Map: {width} × {height} | {detail} | Closed: {closed} | Open: {open}",
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
        self.footer_label.setToolTip(
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
        if self.view.pending:
            self.information("Finish closure", "Finish the closure or cancel it with Escape.")
            return
        analysis = self.view.analysis
        if not analysis.faces:
            self.information(
                "Close a boundary first",
                "No enclosed region exists. Use Closure to connect original walls: "
                "click to snap, Alt-click for corners, click to snap the end.",
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
                    "Choose No to repair with Closure.",
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

    def export(self):
        if not self.view.session or self.worker:
            return
        if self.view.pending or self.view.active_gesture:
            self.information("Finish editing", "Finish or cancel the active stroke/closure first.")
            return
        try:
            placement = self.placement()
        except ValueError as exc:
            self.warning("Invalid elevation", str(exc))
            return
        default = (
            self.project_path.parent
            if self.project_path
            else self.view.session.source.image_path.parent
        )
        path = QFileDialog.getExistingDirectory(
            self, self.t("Export separate PNGs with 3 px edge guard"), str(default)
        )
        if not path:
            return
        self.export_action.setEnabled(False)
        self.progress = QProgressDialog(
            self.t("Exporting separate PNGs with 3 px edge guard…"), self.t("Cancel"), 0, 100, self
        )
        self.progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.progress.setAutoClose(False)
        self.progress.setAutoReset(False)
        self.progress.setMinimumDuration(0)
        self.worker = ExportWorker(
            self.view.session, Path(path), placement, self, self.selected_region
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
                "language": window.language,
                "foundry_major": window.placement().foundry_major,
                "window_visible": window.isVisible(),
                "minimum_window": [window.minimumWidth(), window.minimumHeight()],
                "footer": window.footer_label.text(),
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
