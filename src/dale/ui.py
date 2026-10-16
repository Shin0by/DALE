"""Local desktop workflow, controls, and export worker lifecycle."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import replace
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
    QStackedWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)
from shapely.geometry import Point as ShapePoint

from dale import __version__, application_title
from dale.autoclose import AutoCloseIndex
from dale.bounds_preview import BoundsPreview
from dale.canvas import GEOMETRY_ERASERS, REGION_TOOLS, MapView
from dale.geometry import offset_region, open_contour_count
from dale.localization import (
    DesktopTranslator,
    prepare_control_tooltips,
    translate,
    translate_static,
)
from dale.overlay_export import export_overlays, export_regions
from dale.placement import Placement
from dale.preferences import (
    TOOL_VALUE_RANGES,
    load_directory,
    load_foundry_major,
    load_global_tool_settings,
    load_language,
    load_move_related,
    load_recent_projects,
    load_tool_values,
    save_directory,
    save_foundry_major,
    save_global_tool_settings,
    save_language,
    save_move_related,
    save_recent_projects,
    save_tool_value,
    settings_path,
)
from dale.project_io import (
    SCHEMA_VERSION,
    load_project,
    read_json_documents,
    read_project_templates,
    save_project,
)
from dale.raster import ExportCancelled, load_preview
from dale.scene import load_pair
from dale.scene_templates import SceneTemplates, load_template_file, save_template_file
from dale.scene_templates_ui import SceneTemplatesPanel
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

    def __init__(self, session, path, placement, parent, region_indices=None):
        super().__init__(parent)
        self.source = session.source
        self.operations = tuple(session.operations)
        self.path = path
        self.placement = placement
        self.region_indices = region_indices
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
        self._tool_preferences_ready = False
        self._remembered_tool_values = {}
        self._applying_tool_values = False
        self._project_tool_values = None
        self.use_global_tool_settings = load_global_tool_settings(self.preferences_path)
        self.language = load_language(self.preferences_path)
        self.remembered_move_related = load_move_related(self.preferences_path)
        self.input_directory = load_directory(self.preferences_path, "input")
        self.output_directory = load_directory(self.preferences_path, "output")
        self.recent_projects = load_recent_projects(self.preferences_path)
        self.scene_section_active = False
        self.scene_templates = SceneTemplates()
        self.saved_templates = self.scene_templates
        self.setWindowTitle(application_title())
        self.resize(1280, 860)
        self.setMinimumSize(1024, 768)
        self.worker = None
        self.bounds_preview = BoundsPreview(self)
        self.bounds_ready_timer = QTimer(self)
        self.bounds_ready_timer.setSingleShot(True)
        self.bounds_ready_timer.timeout.connect(self.apply_bounds_ready)
        self.bounds_preview.changed.connect(self.apply_bounds_ready)
        QApplication.instance().aboutToQuit.connect(self.bounds_preview.shutdown)
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
        self.info = QLabel("Open a scene image and its scene JSON to begin.")
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
            "Connect free contour ends within this distance in original "
            "image pixels. 0 disables joining."
        )
        self.contour_offset = ToolSpinBox()
        self.contour_offset.setRange(-4096, 4096)
        self.contour_offset.setToolTip(
            "Keep scene image pixels beyond the lines. Positive expands the "
            "artwork; negative cuts inward. Ctrl+wheel: change this value."
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
        form.addRow("Language", self.language_control)
        self.global_tools_control = QCheckBox("Store settings globally")
        self.global_tools_control.setChecked(self.use_global_tool_settings)
        self.global_tools_control.setToolTip(
            "Store all numeric tool values globally. Enabling copies current values; "
            "opening a project keeps global values. Disable to restore this project's values. "
            "Otherwise values are stored in the project file."
        )
        self.global_tools_control.toggled.connect(self.set_global_tool_settings)
        form.addRow(self.global_tools_control)
        global_note = QLabel("Otherwise, tool values are stored in the project file.")
        global_note.setWordWrap(True)
        global_note.setToolTip(self.global_tools_control.toolTip())
        form.addRow(global_note)
        self.settings_group = QGroupBox("Settings")
        self.settings_group.setLayout(form)
        self.project_group = QGroupBox("Project")
        project_layout = QVBoxLayout(self.project_group)
        self.regions_group = QGroupBox("Regions")
        regions_layout = QVBoxLayout(self.regions_group)
        regions_layout.addWidget(self.region_control)
        self.project_info_group = QGroupBox("File information")
        file_layout = QVBoxLayout(self.project_info_group)
        for label in (self.info, self.map_info, self.diagnostics, self.feedback_label):
            file_layout.addWidget(label)
        project_layout.addWidget(self.regions_group)
        project_layout.addWidget(self.project_info_group)
        self.scene_group = QGroupBox("Scene")
        scene_layout = QVBoxLayout(self.scene_group)
        scene_layout.setContentsMargins(6, 6, 6, 6)
        self.templates_panel = SceneTemplatesPanel(self)
        self.scene_levels_group = self.templates_panel.levels_group
        self.templates_panel.changed.connect(self.set_scene_templates)
        self.templates_panel.import_requested.connect(self.import_scene_templates)
        self.templates_panel.export_requested.connect(self.export_scene_templates)
        scene_layout.addWidget(self.templates_panel)
        self.sidebar_stack = QStackedWidget()
        self.sidebar_pages = {}
        self.mode_help_labels = {}
        self.information_groups = {}
        for key, content in (
            ("project", self.project_group),
            ("scene", self.scene_group),
            ("settings", self.settings_group),
        ):
            page = QWidget()
            sidebar = QVBoxLayout(page)
            sidebar.setContentsMargins(0, 0, 0, 0)
            sidebar.addWidget(content)
            sidebar.addStretch()
            information = QGroupBox("Information")
            information.setFixedHeight(240)
            information_layout = QVBoxLayout(information)
            help_label = QLabel()
            help_label.setWordWrap(True)
            help_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            help_scroll = QScrollArea()
            help_scroll.setWidgetResizable(True)
            help_scroll.setWidget(help_label)
            help_scroll.setMinimumHeight(160)
            help_scroll.setMaximumHeight(240)
            help_scroll.setToolTip(
                "Scroll the available shortcuts for the current tool and window."
            )
            information_layout.addWidget(help_scroll)
            sidebar.addWidget(information)
            self.sidebar_pages[key] = page
            self.mode_help_labels[key] = help_label
            self.information_groups[key] = information
            self.sidebar_stack.addWidget(page)
        self.sidebar_layout = self.sidebar_pages["project"].layout()
        self.information_group = self.information_groups["project"]
        self.mode_help = self.mode_help_labels["project"]
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setWidget(self.sidebar_stack)
        sidebar_scroll.setFixedWidth(360)
        layout = QHBoxLayout()
        left_panel = QWidget()
        self.left_panel = left_panel
        left_panel.setFixedWidth(64)
        self.tool_column = QVBoxLayout(left_panel)
        self.tool_column.setContentsMargins(0, 0, 0, 0)
        self.tool_column.setSpacing(4)
        self.tool_stack = QStackedWidget()
        self.tool_stack.setFixedWidth(64)
        self.tool_stack.setStyleSheet("QStackedWidget { background: transparent; border: 0; }")
        self.tool_column.addWidget(self.tool_stack)
        layout.addWidget(left_panel)
        layout.addWidget(self.view, 1)
        layout.addWidget(sidebar_scroll)
        root = QWidget()
        root.setLayout(layout)
        self.setCentralWidget(root)
        self.statusBar().hide()
        self.statusBar().messageChanged.connect(self.feedback_label.setText)
        self.menuBar().setToolTip("Application menus.")
        self.file_menu = self.menuBar().addMenu("File")
        self.edit_menu = self.menuBar().addMenu("Edit")
        self.about_menu = self.menuBar().addMenu("About")
        for menu, tip in (
            (self.file_menu, "Open, save, export regions, close, and exit."),
            (self.edit_menu, "Undo, redo, and clear selection."),
            (self.about_menu, "Application name, version, and purpose."),
        ):
            menu.setToolTipsVisible(True)
            menu.setToolTip(tip)
        categories = make_toolbar(self, "Sections")
        self.tool_set_toolbar = categories
        self.scene_toolbar = make_toolbar(self, "Scene")
        self.basic_toolbar = make_toolbar(self, "Main")
        geometry = make_toolbar(self, "Contours", vertical=True)
        region_tools = make_toolbar(self, "Regions", vertical=True)
        pixels = make_toolbar(self, "Raster", vertical=True)
        self.toolbars = (
            categories,
            self.scene_toolbar,
            self.basic_toolbar,
            geometry,
            region_tools,
            pixels,
        )
        self.geometry_eraser_tiles = {}
        self.sized_tools = {}
        for bar in (geometry, region_tools, pixels):
            self.tool_stack.addWidget(bar)

        def action(bar, title, handler, shortcut=None):
            item = QAction(title, self)
            item.setProperty("dale_tool_key", title)
            display = {
                "Auto-close": "Auto-close contours",
                "Edit points": "Edit contour points",
                "New line": "New contour line",
                "New circle": "New circular contour",
                "Export PNGs": "Export regions as PNGs",
                "Erase lines": "Erase contour lines",
                "Erase vertices": "Erase contour points",
                "Snapping (px)": "Contour snapping (px)",
                "Artwork offset (px)": "Region artwork offset (px)",
                "Erase": "Erase raster pixels",
                "Restore": "Restore raster pixels",
                "Remove outside": "Erase raster outside contours",
                "Remove inside": "Erase raster inside contours",
            }.get(title)
            if display:
                item.setProperty("dale_display_key", display)
            vertical = isinstance(bar, QToolBar) and bar.orientation() == Qt.Orientation.Vertical
            icon_only = vertical or bar == self.basic_toolbar
            if icon_only:
                item.setIcon(tool_icon(title))
                item.setProperty("dale_icon_only", True)
            if bar == categories or bar == self.basic_toolbar:
                item.setProperty(
                    "dale_display_key",
                    {
                        "Open scene": "Image + JSON",
                        "Open project": "Open",
                        "Save project": "Save",
                        "Save project as…": "Save as…",
                        "Close scene": "Close",
                        "Export PNGs": "Export regions",
                        "Pan": "Hand",
                        "Show contours": "Show contours",
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
                "Artwork offset (px)": (
                    -4096,
                    4096,
                    0,
                    "contour_offset",
                    lambda v: self.update_contour_settings(),
                ),
            }
            if title in sizes:
                low, high, initial, attribute, handler = sizes[title]
                editor = self.contour_offset if title == "Artwork offset (px)" else ToolSpinBox()
                if title != "Artwork offset (px)":
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
                if vertical:
                    bar.widgetForAction(item).setFixedSize(48, 48)
                elif bar == self.basic_toolbar:
                    button = bar.widgetForAction(item)
                    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
                    button.setFixedSize(36, 36)
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
        self.levels_action = action(self.scene_toolbar, "Levels", self.select_scene_levels)
        self.levels_action.setCheckable(True)
        tool_sets.addAction(self.levels_action)
        self.levels_action.setToolTip("Open the scene levels panel.")

        action(self.file_menu, "Open scene", self.open_pair, "Ctrl+I")
        action(self.file_menu, "JSON", self.open_json)
        action(self.file_menu, "Open project", self.open_project, QKeySequence.StandardKey.Open)
        self.recent_menu = self.file_menu.addMenu("Recent projects")
        self.recent_menu.menuAction().setProperty("dale_tool_key", "Recent projects")
        self.recent_menu.setToolTipsVisible(True)
        self.recent_menu.setToolTip("Open a recently opened or saved DALE project.")
        self.file_menu.addSeparator()
        action(
            self.file_menu, "Save project", self.save_project_file, QKeySequence.StandardKey.Save
        )
        action(
            self.file_menu,
            "Save project as…",
            lambda: self.save_project_file(save_as=True),
            QKeySequence.StandardKey.SaveAs,
        )
        self.file_menu.addSeparator()
        self.export_action = action(self.file_menu, "Export PNGs", self.export, "Ctrl+E")
        action(self.file_menu, "Close scene", self.close_document)
        self.file_menu.addSeparator()
        action(self.file_menu, "Exit", self.close, "Ctrl+Q")
        action(self.edit_menu, "Undo", lambda: self.history(False), QKeySequence.StandardKey.Undo)
        action(self.edit_menu, "Redo", lambda: self.history(True), QKeySequence.StandardKey.Redo)
        self.edit_menu.addSeparator()
        action(self.about_menu, "About DALE…", self.show_about)
        modes = QActionGroup(self)
        modes.setExclusive(True)
        self.mode_actions = {}
        for bar, names in (
            (self.basic_toolbar, ("Pan",)),
            (
                geometry,
                (
                    "Edit points",
                    "New line",
                    "New circle",
                    "Auto-close",
                    "Erase lines",
                    "Erase vertices",
                ),
            ),
            (region_tools, REGION_TOOLS),
            (pixels, ("Erase", "Restore")),
        ):
            for mode in names:
                item = action(bar, mode, lambda checked=False, m=mode: self.activate_mode(m))
                item.setCheckable(True)
                item.setChecked(mode == "Pan")
                modes.addAction(item)
                self.mode_actions[mode] = item
        self.clear_selection_action = action(
            self.basic_toolbar, "Clear selection", self.clear_selection, "Ctrl+Shift+A"
        )
        self.edit_menu.addAction(self.clear_selection_action)
        self.move_button = region_tools.widgetForAction(self.mode_actions["Move regions"])
        self.rotate_button = region_tools.widgetForAction(self.mode_actions["Rotate regions"])
        for mode, button in (
            ("Move regions", self.move_button),
            ("Rotate regions", self.rotate_button),
        ):
            button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            button.customContextMenuRequested.connect(
                lambda point, m=mode: self.configure_region_move(m)
            )
        action(self.basic_toolbar, "Fit", self.view.fit_map, "F")
        self.walls_action = action(self.basic_toolbar, "Show contours", self.toggle_walls)
        self.walls_action.setCheckable(True)
        self.walls_action.setChecked(True)
        self.settings_action = action(
            self.basic_toolbar,
            "Settings",
            lambda checked: self.show_sidebar(
                "settings" if checked else "scene" if self.scene_section_active else "project"
            ),
        )
        self.settings_action.setCheckable(True)
        self.settings_action.setToolTip("Show or hide the application settings panel.")
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
        action(region_tools, "Artwork offset (px)", lambda: self.contour_offset.setFocus())
        self.tool_column.addStretch()
        for bar in (geometry, region_tools, pixels):
            bar.ensurePolished()
            bar.setFixedHeight(bar.sizeHint().height())
        self.tool_stack.setFixedHeight(self.tool_stack.currentWidget().sizeHint().height())
        self.view.size_changed.connect(self.sync_tool_sizes)
        QApplication.instance().installEventFilter(self)
        tips = {
            "Open scene": "Load a scene image and its scene JSON.",
            "Exit": "Close the application after offering to save the current project.",
            "About DALE…": "Show the application name, version, and purpose.",
            "JSON": ("Load a scene JSON. Current edits can be saved before importing."),
            "Open project": "Open a portable .dale archive including sources and undo history.",
            "Save project": (
                "Save sources, masks, geometry, preferences, and undo/redo in one .dale file."
            ),
            "Save project as…": (
                "Save sources, masks, geometry, preferences, and undo/redo in one .dale file."
            ),
            "Export PNGs": (
                "Export separate cropped PNGs with the configured margin and a placement manifest."
            ),
            "Pan": "Drag to move the scene image. Right-drag works in every tool.",
            "Auto-close": (
                "Hover to trace connected lines and valid continuations. "
                "White edges show affected lines; "
                "dashed lines preview extensions. Click to extend existing lines "
                "along their directions after confirmation in one undo step."
            ),
            "Close all contours": (
                "Extend eligible lines across the whole scene after "
                "confirmation. Distance uses screen pixels."
            ),
            "New line": (
                "Press for the first point, drag, release for the second. "
                "Snap now or when moving points."
            ),
            "New circle": (
                "Press to set the center, drag to change the radius, "
                "release to create a circular contour. "
                "Diameters up to 0.5 cells use 4 vertices, up to 1 use 6, "
                "up to 2 use 8; larger circles use more. "
                "Ctrl+wheel while drawing: adjust the radius."
            ),
            "Erase lines": (
                "Erase entire line segments touched by the circle. Drag is one undo step."
            ),
            "Erase vertices": (
                "Erase vertices inside the circle; reconnect ordinary line neighbors. "
                "Branching vertices remove their connected edges."
            ),
            "Close scene": "Close the current scene after offering to save its DALE project.",
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
                "Raster pixels stay unchanged. "
                "Right-click: configure connected lines. Escape: cancel the current gesture."
            ),
            "Rotate regions": (
                "Wheel: rotate selected contours by 0.1 degrees per notch "
                "around their common center. "
                "Wheel up rotates clockwise; wheel down reverses. Raster pixels stay unchanged. "
                "Right-click: configure connected lines. Each notch is one undo step."
            ),
            "Export selected regions": "Export only the highlighted regions as separate PNGs.",
            "Artwork offset (px)": (
                "Keep scene image pixels beyond the lines. Positive expands the "
                "artwork; negative cuts inward."
            ),
            "Edit points": (
                "Click a line to insert; drag a fixed-size circle to move; "
                "double-click it to delete. "
                "Hold Alt to move along the selected line vector."
            ),
            "Erase": "Paint transparency over unwanted objects.",
            "Restore": "Restore opacity from the original scene image.",
            "Remove outside": "Keep enclosed regions and make their exterior transparent.",
            "Remove inside": "Erase enclosed regions and keep their exterior.",
            "Undo": "Undo the last complete stroke, mask, or geometry edit.",
            "Redo": "Redo the last undone edit.",
            "Fit": "Fit the scene image to the viewport.",
            "Show contours": (
                "Show all contours or hide inactive geometry. Selected regions "
                "and highlighted lines remain visible."
            ),
            "Clear selection": (
                "Clear selected regions and contour highlights. "
                "Cancel the current gesture without changing saved geometry or raster."
            ),
        }
        for item in self.findChildren(QAction):
            if item.text() in tips:
                description = tips[item.text()]
                parts = (
                    [item.property("dale_display_key") or item.text(), description]
                    if item.property("dale_icon_only")
                    else [description]
                )
                if item.text() in (
                    "New line",
                    "New circle",
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
        self.view.horizontalScrollBar().setToolTip("Pan the scene image horizontally.")
        self.view.verticalScrollBar().setToolTip("Pan the scene image vertically.")
        sidebar_scroll.verticalScrollBar().setToolTip("Scroll scene settings and editing help.")
        sidebar_scroll.horizontalScrollBar().setToolTip("Scroll scene settings and editing help.")
        for control in (
            self.version,
            self.language_control,
        ):
            form.labelForField(control).setToolTip(control.toolTip())
        self.initialize_tool_preferences()
        self.rebuild_recent_menu()
        for command in self.findChildren(QAction):
            if not command.shortcut().isEmpty():
                command.changed.connect(self.update_mode_help)
        self.set_language(self.language, persist=False)
        self.statusBar().showMessage(self.t("Ready. All editing is local."))

    def t(self, text, **values):
        return translate(text, self.language, **values)

    def show_about(self):
        dialog = QMessageBox(
            QMessageBox.Icon.Information,
            self.t("About DALE"),
            application_title(),
            parent=self,
        )
        dialog.setObjectName("aboutDALE")
        dialog.setInformativeText(
            self.t(
                "Prepare transparent floor maps from Dungeon Alchemist scene "
                "images and Foundry scene JSON."
            )
        )
        close = dialog.addButton(QMessageBox.StandardButton.Close)
        close.setText(self.t("Close"))
        close.setToolTip(self.t("Close this dialog. Escape: close."))
        dialog.setEscapeButton(close)
        dialog.exec()

    def initialize_tool_preferences(self):
        self.tool_value_controls = {
            "line_eraser_diameter": self.geometry_brush_control,
            "vertex_eraser_diameter": self.vertex_brush_control,
            "raster_erase_diameter": self.brush_control,
            "raster_restore_diameter": self.restore_brush_control,
            "auto_close_distance_px": self.auto_close_control,
            "global_close_distance_px": self.global_close_control,
            "snap_distance_px": self.snap_distance,
            "artwork_offset_px": self.contour_offset,
        }
        initial = (
            load_tool_values(self.preferences_path)
            if self.use_global_tool_settings
            else {key: default for key, (_, _, default) in TOOL_VALUE_RANGES.items()}
        )
        for key, value in initial.items():
            self.tool_value_controls[key].setValue(value)
        self._remembered_tool_values = {
            key: control.value() for key, control in self.tool_value_controls.items()
        }
        self._tool_preferences_ready = True
        for control in self.tool_value_controls.values():
            control.valueChanged.connect(self.remember_tool_values)

    def remember_tool_values(self):
        if not self._tool_preferences_ready or self._applying_tool_values:
            return
        if not self.use_global_tool_settings:
            self._project_tool_values = self.current_tool_values()
            return
        for key, control in self.tool_value_controls.items():
            value = control.value()
            if self._remembered_tool_values.get(key) == value:
                continue
            try:
                save_tool_value(self.preferences_path, key, value)
                self._remembered_tool_values[key] = value
            except OSError:
                self.statusBar().showMessage(
                    self.t("Tool values changed; preferences could not be written."), 7000
                )

    def current_tool_values(self):
        return {key: control.value() for key, control in self.tool_value_controls.items()}

    def apply_tool_values(self, values):
        previous = self._applying_tool_values
        self._applying_tool_values = True
        try:
            for key, value in values.items():
                self.tool_value_controls[key].setValue(value)
            if self.view.session:
                self.view.session.contour_offset = values["artwork_offset_px"]
                self.refresh()
        finally:
            self._applying_tool_values = previous

    def set_global_tool_settings(self, enabled):
        if enabled:
            self._project_tool_values = self.current_tool_values()
        self.use_global_tool_settings = enabled
        try:
            save_global_tool_settings(self.preferences_path, enabled)
        except OSError:
            self.statusBar().showMessage(self.t("Preferences could not be written."), 7000)
        if enabled:
            self._remembered_tool_values.clear()
            self.remember_tool_values()
        elif self._project_tool_values is not None:
            self.apply_tool_values(self._project_tool_values)

    def clear_selection(self):
        self.view.cancel_pending()
        self.selected_regions = ()
        self.view.region_pivot = None
        self.view.cursor_point = self.view.hover_edge = None
        self.view.update_hover()
        self.update_map_info()
        self.view.update_image()

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
                *self.mode_help_labels.values(),
            ),
        )
        self.update_size_help()
        for menu in (self.file_menu, self.edit_menu, self.about_menu, self.recent_menu):
            menu.menuAction().setToolTip(menu.toolTip())
        self.region_control.setToolTip(
            self.t("Choose all closed regions or one region to highlight and export.")
        )
        self.update_project_info()
        self.rebuild_recent_menu()
        self.templates_panel.language = language
        self.templates_panel.set_library(self.scene_templates)
        self.update_placement_hint()
        self.update_mode_help()
        self.refresh()
        self.statusBar().clearMessage()
        if persist:
            try:
                save_language(self.preferences_path, language)
            except OSError:
                self.statusBar().showMessage(
                    self.t("Language changed; preferences could not be written."), 7000
                )

    def apply_bounds_ready(self):
        if self.bounds_preview.closed:
            return
        if self.view.active_gesture:
            self.bounds_ready_timer.start(40)
            return
        self.update_map_info()

    def update_project_info(self):
        if not self.view.session:
            self.info.setText(self.t("Open a scene image and its scene JSON to begin."))
            return
        source = self.view.session.source
        name = self.project_path.name if self.project_path else source.image_path.name
        self.info.setText("\n".join((name, *(self.t(warning) for warning in source.warnings))))

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
            self.view.highlight_edges(plan.segments, plan.extensions)
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
        if not changed:
            dialog = QMessageBox(
                QMessageBox.Icon.Information, self.t("Auto-close contours"), text, parent=self
            )
            dialog.setObjectName("autoCloseInformation")
            close = dialog.addButton(QMessageBox.StandardButton.Close)
            close.setText(self.t("Close"))
            close.setToolTip(self.t("Close this dialog. Escape: close."))
            dialog.setDefaultButton(close)
            dialog.setEscapeButton(close)
            dialog.exec()
            return
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
            + self.t("Placement in Foundry is configured separately. PNG margin is configurable.")
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

    def select_tool_set(self, key, activate=True, preserve_sidebar=False):
        if not preserve_sidebar:
            self.scene_section_active = False
            self.show_sidebar("project")
        self.left_panel.show()
        self.current_tool_set = key
        self.tool_stack.setCurrentIndex({"geometry": 0, "regions": 1, "pixels": 2}[key])
        self.tool_stack.setFixedHeight(self.tool_stack.currentWidget().sizeHint().height())
        self.update_size_help()
        if not self.scene_section_active:
            self.tool_set_actions[key].setChecked(True)
        if activate:
            self.activate_mode(self.last_tool_modes[key])

    def show_sidebar(self, key):
        self.sidebar_stack.setCurrentWidget(self.sidebar_pages[key])
        self.settings_action.setChecked(key == "settings")

    def select_scene_levels(self):
        self.view.cancel_pending()
        self.scene_section_active = True
        self.levels_action.setChecked(True)
        self.left_panel.show()
        self.show_sidebar("scene")
        self.update_mode_help()

    def set_scene_templates(self, library):
        self.scene_templates = library.validated()
        self.templates_panel.set_library(self.scene_templates)
        self.view.set_level_templates(self.scene_templates.levels)

    def import_scene_templates(self):
        selected, _ = QFileDialog.getOpenFileName(
            self,
            self.t("Import scene templates"),
            str(self.input_directory or Path.cwd()),
            self.t("Scene templates or DALE project (*.json *.dale)"),
        )
        if not selected:
            return
        try:
            path = Path(selected)
            library = (
                read_project_templates(path)
                if path.suffix.lower() == ".dale"
                else load_template_file(path)
            )
            self.set_scene_templates(self.scene_templates.merge(library))
            self.remember_directory("input", path.resolve().parent)
        except Exception as exc:
            self.warning("Cannot import scene templates", str(exc))

    def export_scene_templates(self):
        selected, _ = QFileDialog.getSaveFileName(
            self,
            self.t("Export scene templates"),
            str((self.output_directory or Path.cwd()) / "scene-templates.json"),
            self.t("Scene template JSON (*.json)"),
        )
        if not selected:
            return False
        try:
            path = Path(selected)
            if path.suffix.lower() != ".json":
                path = path.with_name(path.name + ".json")
            protected = [self.project_path] if self.project_path else []
            if self.view.session:
                protected.extend(
                    (self.view.session.source.image_path, self.view.session.source.json_path)
                )
            if any(
                path.resolve() == source.resolve()
                or (path.exists() and os.path.samefile(path, source))
                for source in protected
            ):
                raise ValueError("Template export cannot overwrite project or source files.")
            save_template_file(self.scene_templates, path)
            self.remember_directory("output", path.resolve().parent)
            if self.view.session is None:
                self.saved_templates = self.scene_templates
            return True
        except Exception as exc:
            self.warning("Cannot export scene templates", str(exc))
            return False

    def rebuild_recent_menu(self):
        self.recent_menu.clear()
        if not self.recent_projects:
            empty = self.recent_menu.addAction(self.t("No recent projects"))
            empty.setProperty("dale_original_text", "No recent projects")
            empty.setEnabled(False)
        for index, path in enumerate(self.recent_projects, 1):
            item = self.recent_menu.addAction(f"{index}. {path.name.replace('&', '&&')}")
            item.setData(str(path))
            item.setEnabled(path.is_file())
            item.setProperty(
                "dale_tooltip_parts",
                [
                    "Open this recent DALE project."
                    if path.is_file()
                    else "Project file is unavailable.",
                    str(path),
                ],
            )
            item.setToolTip("\n".join(self.t(part) for part in item.property("dale_tooltip_parts")))
            item.triggered.connect(lambda checked=False, path=path: self.open_recent_project(path))
        if self.recent_projects:
            self.recent_menu.addSeparator()
            clear = self.recent_menu.addAction(self.t("Clear recent projects"))
            clear.setProperty("dale_original_text", "Clear recent projects")
            clear.setProperty(
                "dale_original_tooltip", "Clear the list without deleting project files."
            )
            clear.setToolTip(self.t("Clear the list without deleting project files."))
            clear.triggered.connect(self.clear_recent_projects)

    def remember_recent_project(self, path):
        resolved = path.resolve()
        projects = [resolved, *(p for p in self.recent_projects if p != resolved)][:10]
        try:
            save_recent_projects(self.preferences_path, projects)
        except OSError:
            self.statusBar().showMessage(self.t("Preferences could not be written."), 7000)
        self.recent_projects = projects
        self.rebuild_recent_menu()

    def clear_recent_projects(self):
        try:
            save_recent_projects(self.preferences_path, [])
        except OSError:
            self.statusBar().showMessage(self.t("Preferences could not be written."), 7000)
            return
        self.recent_projects = []
        self.rebuild_recent_menu()

    def open_recent_project(self, path):
        if self.can_discard():
            self.load_project_file(path)

    def update_size_help(self):
        for tile in self.sized_tools.values():
            tile.set_help(self.language)

    def update_mode_help(self):
        mode = self.view.mode
        instructions = {
            "Pan": ["Left-drag: pan the scene image."],
            "Edit points": [
                "Click a line: insert a contour point. Drag a circle: move it.",
                "Double-click a circle: delete the point. Alt-drag: follow the line vector.",
                "Escape: cancel the current gesture.",
            ],
            "New line": [
                "Press, drag, release: draw a contour line.",
                "Escape: cancel the current gesture.",
            ],
            "New circle": [
                "Press: set center. Drag: change radius. Release: create circular contour.",
                "Ctrl+wheel while drawing: adjust the radius.",
                "Escape: cancel the current gesture.",
            ],
            "Auto-close": [
                "Hover: preview contour connections. Click: review and apply.",
                "Ctrl+wheel: change the auto-close distance.",
            ],
            "Erase lines": [
                "Drag the circle: erase highlighted contour lines.",
                "Ctrl+wheel: change this tool's diameter.",
                "Escape: cancel the current gesture.",
            ],
            "Erase vertices": [
                "Drag the circle: erase highlighted contour points.",
                "Ctrl+wheel: change this tool's diameter.",
                "Escape: cancel the current gesture.",
            ],
            "Select regions": ["Click a region: select/deselect. Empty click: clear selection."],
            "Move regions": [
                "Drag selected regions: move. Ctrl+wheel: scale.",
                "Right-click the tool button: configure connected lines.",
                "Escape: cancel the current gesture.",
            ],
            "Rotate regions": [
                "Wheel: rotate selected regions by 0.1 degrees around their common center.",
                "Right-click the tool button: configure connected lines.",
            ],
            "Erase": [
                "Drag: erase raster pixels.",
                "Ctrl+wheel: change this tool's diameter.",
                "Escape: cancel the current gesture.",
            ],
            "Restore": [
                "Drag: restore raster pixels.",
                "Ctrl+wheel: change this tool's diameter.",
                "Escape: cancel the current gesture.",
            ],
        }[mode]
        lines = (
            [self.t("Levels"), *(self.t(line) for line in instructions)]
            if self.scene_section_active
            else [self.mode_actions[mode].text(), *(self.t(line) for line in instructions)]
        )
        lines.append(self.t("Right-drag: pan the scene image."))
        if mode != "Rotate regions":
            lines.append(self.t("Wheel: zoom at cursor."))
        lines.append("")
        lines.append(self.t("Window shortcuts"))
        for command in self.findChildren(QAction):
            if not command.isEnabled() or command.shortcut().isEmpty():
                continue
            keys = command.shortcut().toString(QKeySequence.SequenceFormat.PortableText)
            lines.append(f"{keys}: {command.text()}")
        for label in self.mode_help_labels.values():
            label.setText("\n".join(lines))

    def configure_region_move(self, mode="Move regions"):
        dialog = QMessageBox(
            QMessageBox.Icon.Question,
            self.t(mode),
            self.t(
                "Rotate all connected lines?"
                if mode == "Rotate regions"
                else "Move all connected lines?"
            ),
            parent=self,
        )
        dialog.setObjectName("regionMoveConfiguration")
        dialog.setInformativeText(
            self.t(
                "Yes includes lines connected within the snapping distance. "
                "No affects only selected boundaries. Right-click this tool to reopen this dialog."
            )
        )
        remember = QCheckBox(self.t("Remember choice"), dialog)
        remember.setToolTip(
            self.t("Remember this choice between launches. Right-click the tool to change it.")
        )
        remember.setChecked(self.remembered_move_related is not None)
        dialog.setCheckBox(remember)
        for key, tip in (
            ("Yes", "Transform selected boundaries and related lines."),
            ("No", "Transform only selected region boundaries."),
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
        if mode in ("Move regions", "Rotate regions") and prompt:
            if not self.selected_regions:
                self.activate_mode("Select regions")
                self.information(
                    "Select regions", "Select at least one closed region on the scene image."
                )
                return
            if self.remembered_move_related is None and not self.configure_region_move(mode):
                self.mode_actions[self.view.mode].setChecked(True)
                return
        if mode != "Pan":
            key = (
                "pixels"
                if mode in ("Erase", "Restore")
                else "regions"
                if mode in REGION_TOOLS
                else "geometry"
            )
            self.last_tool_modes[key] = mode
            self.select_tool_set(
                key,
                activate=False,
                preserve_sidebar=self.scene_section_active or self.settings_action.isChecked(),
            )
        self.mode_actions[mode].setChecked(True)
        self.view.set_mode(mode)
        if mode == "Select regions" and self.selected_regions is None:
            self.selected_regions = ()
            self.update_map_info()
        self.update_mode_help()

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
        self.remember_tool_values()

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
            and self.view.mode == "Rotate regions"
            and not event.modifiers() & Qt.KeyboardModifier.ControlModifier
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
        self.set_scene_templates(SceneTemplates())
        self.saved_templates = self.scene_templates
        self.release_json_workspaces()
        if self.loaded_project:
            self.loaded_project.close()
            self.loaded_project = None
        self.project_path = self.saved_state = None
        self._project_tool_values = None
        self.info.setText(self.t("Open a scene image and its scene JSON to begin."))
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
        templates_saved = self.scene_templates == self.saved_templates
        if not self.view.session and templates_saved:
            return True
        if (
            self.view.session
            and self.saved_state is not None
            and self.document_state() == self.saved_state
            and templates_saved
        ):
            return True
        if (
            self.view.session
            and self.saved_state is None
            and not self.view.session.operations
            and templates_saved
        ):
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
        if session is None:
            return (self.scene_templates.to_bytes(),)
        return (
            self.scene_templates.to_bytes(),
            tuple(session.operations),
            tuple(session.future),
            session.origin,
            session.gap_tolerance,
            self._project_tool_values["artwork_offset_px"]
            if self.use_global_tool_settings and self._project_tool_values is not None
            else session.contour_offset,
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
            return self.export_scene_templates()
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
            project_session = self.view.session
            project_ui = self.ui_state()
            if self.use_global_tool_settings and self._project_tool_values is not None:
                project_session = replace(
                    project_session, contour_offset=self._project_tool_values["artwork_offset_px"]
                )
                project_ui.update(
                    (key, value)
                    for key, value in self._project_tool_values.items()
                    if key != "artwork_offset_px"
                )
            save_project(project_session, path, project_ui, templates=self.scene_templates)
            self.remember_directory("output", path.parent)
            self.project_path = path
            self.saved_state = self.document_state()
            self.saved_templates = self.scene_templates
            self.remember_recent_project(path)
            self.update_project_info()
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
        was_applying = self._applying_tool_values
        self._applying_tool_values = True
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            loaded = load_project(path)
            preview = load_preview(loaded.session.source)
            self.view.assign(loaded.session, preview)
            if self.loaded_project:
                self.loaded_project.close()
            self.loaded_project, loaded = loaded, None
            self.set_scene_templates(self.loaded_project.templates)
            self.saved_templates = self.scene_templates
            session, settings = self.loaded_project.session, self.loaded_project.ui_state
            self._project_tool_values = {
                key: session.contour_offset if key == "artwork_offset_px" else settings[key]
                for key in TOOL_VALUE_RANGES
            }
            active_tool_values = (
                self.current_tool_values()
                if self.use_global_tool_settings
                else self._project_tool_values
            )
            self.set_language(settings["language"])
            controls = (self.gap_tolerance, self.contour_offset, self.origin_x, self.origin_y)
            for control in controls:
                control.blockSignals(True)
            self.gap_tolerance.setValue(session.gap_tolerance)
            self.origin_x.setValue(session.origin[0])
            self.origin_y.setValue(session.origin[1])
            for control in controls:
                control.blockSignals(False)
            self.version.setCurrentIndex(0 if settings["foundry_major"] == 14 else 1)
            self.elevation.setCurrentText(str(settings["elevation_ft"]))
            self.apply_tool_values(active_tool_values)
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
            self.remember_recent_project(path)
            self.saved_state = self.document_state()
            self.update_project_info()
            self.refresh()
            self.remember_tool_values()
            return True
        except Exception as exc:
            if loaded:
                loaded.close()
            self.warning("Cannot open project", str(exc))
            return False
        finally:
            self._applying_tool_values = was_applying
            QApplication.restoreOverrideCursor()

    def open_pair(self):
        if not self.can_discard():
            return
        image_path, _ = QFileDialog.getOpenFileName(
            self,
            self.t("Open scene image"),
            str(self.input_directory or Path("examples")),
            self.t("Scene images (*.jpg *.jpeg)"),
        )
        if not image_path:
            return
        json_path = Path(image_path).with_suffix(".json")
        if not json_path.is_file():
            selected, _ = QFileDialog.getOpenFileName(
                self,
                self.t("Load scene JSON"),
                str(json_path),
                self.t("Scene JSON (*.json)"),
            )
            if not selected:
                return
            json_path = Path(selected)
        self.load_sources(Path(image_path), json_path)

    def open_json(self):
        if not self.view.session:
            self.information("JSON", "Open a scene image before loading a scene JSON.")
            return
        if not self.can_discard():
            return
        selected, _ = QFileDialog.getOpenFileName(
            self,
            self.t("Load scene JSON"),
            str(self.input_directory or self.view.session.source.json_path.parent),
            self.t("Scene JSON or DALE projects (*.json *.dale)"),
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
            dialog.setWindowTitle(self.t("Scene JSON documents in DALE project"))
            dialog.resize(520, 300)
            layout = QVBoxLayout(dialog)
            layout.addWidget(QLabel(self.t("Choose a scene JSON for the current scene image.")))
            choices = QListWidget(dialog)
            choices.setToolTip(
                self.t("Select an original or updated scene JSON stored in this DALE project.")
            )
            for document in documents:
                kind = self.t(
                    "Original scene JSON" if document.kind == "original" else "Updated scene JSON"
                )
                item = QListWidgetItem(f"{document.name} — {kind}", choices)
                item.setToolTip(f"{document.name}\n{kind}")
            choices.setCurrentRow(0)
            layout.addWidget(choices)
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            )
            buttons.button(QDialogButtonBox.StandardButton.Ok).setText(self.t("Import"))
            buttons.button(QDialogButtonBox.StandardButton.Ok).setToolTip(
                self.t("Load the selected scene JSON for the current scene image.")
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
            self.warning("Cannot load scene JSON", str(exc))

    def release_json_workspaces(self, keep_current=False):
        current = self.view.session.source if keep_current and self.view.session else None
        retained = []
        for workspace in self.json_workspaces:
            root = Path(workspace.name).resolve()
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
            self._project_tool_values = self.current_tool_values()
            self.origin_x.setValue(0)
            self.origin_y.setValue(0)
            self.refresh()
            if self.loaded_project and not source.image_path.is_relative_to(
                Path(self.loaded_project.workspace.name).resolve()
            ):
                self.loaded_project.close()
                self.loaded_project = None
            self.project_path = None
            self.update_project_info()
            self.saved_state = self.document_state()
            self.release_json_workspaces(keep_current=True)
            return True
        except Exception as exc:
            self.warning("Cannot open scene", str(exc))
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
            self.selected_regions = () if self.view.mode in REGION_TOOLS else None
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
            self.bounds_preview.clear()
            self.map_info.setText(self.t("Scene image: not loaded\nClosed: 0 | Open: 0"))
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
        result = self.bounds_preview.request(session, selected)
        if not selected:
            detail = self.t("PNG: none")
        elif result is None:
            detail = self.t("PNG: calculating exact bounds…")
        elif result.error:
            detail = self.t("PNG: bounds unavailable")
        else:
            bounds = result.bounds
            if not bounds:
                detail = self.t("PNG: none (selection outside the scene image)")
            elif len(bounds) == 1:
                x, y, right, bottom = bounds[0]
                detail = self.t(
                    "PNG: {width} × {height}",
                    width=right - x,
                    height=bottom - y,
                )
            else:
                largest = max(bounds, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
                detail = self.t(
                    "PNG: {count} · max {width} × {height}",
                    count=len(bounds),
                    width=largest[2] - largest[0],
                    height=largest[3] - largest[1],
                )
        self.map_info.setText(
            self.t(
                "Scene image: {width} × {height} px\n{detail}\nClosed: {closed} | Open: {open}",
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
                "Closed: connected closed regions in current geometry. Open: "
                "connected groups of unresolved lines. PNG bounds include every "
                "nonzero bicubic alpha pixel, clipped to the scene image."
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
            self.information(
                "Select regions", "Select at least one closed region on the scene image."
            )
            return
        try:
            placement = self.placement()
        except ValueError as exc:
            self.warning("Invalid elevation", str(exc))
            return
        default = self.output_directory or (
            self.project_path.parent if self.project_path else Path.cwd()
        )
        path = QFileDialog.getExistingDirectory(self, self.t("Export separate PNGs"), str(default))
        if not path:
            return
        self.remember_directory("output", Path(path))
        self.export_action.setEnabled(False)
        self.export_regions_action.setEnabled(False)
        self.progress = QProgressDialog(
            self.t("Exporting separate PNGs…"), self.t("Cancel"), 0, 100, self
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
            self.bounds_preview.shutdown()
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
        parser.error("Pass both --image and --scene to open a scene image and scene JSON.")
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
                "show_walls": window.view.show_walls,
                "selected_regions": window.selected_regions,
                "artwork_offset_px": window.contour_offset.value(),
                "global_tool_settings": window.global_tools_control.isChecked(),
                "tool_values": window.current_tool_values(),
                "mode_help": window.mode_help.text(),
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
