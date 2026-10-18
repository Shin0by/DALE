"""Local desktop workflow, controls, and export worker lifecycle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QFont,
    QFontDatabase,
    QIcon,
    QKeySequence,
    QPainterPath,
    QTransform,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shapely.geometry import LineString, box
from shapely.geometry import Point as ShapePoint
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from dale import __version__, application_title
from dale.bounds_preview import BoundsPreview
from dale.canvas import (
    AREA_TOOLS,
    FIGURE_TOOLS,
    GEOMETRY_ERASERS,
    MOVE_TOOLS,
    REGION_TOOLS,
    ROTATE_TOOLS,
    SELECTION_TOOLS,
    TRANSFORM_TOOLS,
    MapView,
)
from dale.datasets import DatasetCatalog
from dale.geometry import invert_regions_in_box, open_contour_count
from dale.json_repair import repaired_json_bytes, write_json_copy
from dale.layer_repair import infer_layers
from dale.localization import (
    DesktopTranslator,
    format_tooltip,
    prepare_control_tooltips,
    translate,
    translate_static,
)
from dale.overlay_export import export_overlays, export_regions, selected_export_regions
from dale.preferences import (
    TOOL_VALUE_RANGES,
    load_connection_choice,
    load_directory,
    load_global_tool_settings,
    load_language,
    load_merge_selected_regions,
    load_move_related,
    load_recent_projects,
    load_right_panel_visible,
    load_tool_values,
    save_connection_choice,
    save_directory,
    save_global_tool_settings,
    save_language,
    save_merge_selected_regions,
    save_recent_projects,
    save_right_panel_visible,
    save_tool_value,
    settings_path,
)
from dale.project_io import (
    SCHEMA_VERSION,
    JsonDocument,
    current_contours_document,
    load_project,
    save_project,
)
from dale.raster import ExportCancelled, load_preview
from dale.region_transform import delete_figures, delete_regions
from dale.scene import load_pair
from dale.session import Session
from dale.source_editing import source_layers
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

    def __init__(
        self,
        session,
        path,
        parent,
        region_indices=None,
        selected_polygons=None,
        merge_adjacent=False,
    ):
        super().__init__(parent)
        self.source = session.source
        self.operations = tuple(session.operations)
        self.path = path
        self.region_indices = tuple(region_indices) if region_indices is not None else None
        self.selected_polygons = tuple(selected_polygons) if selected_polygons is not None else None
        self.merge_adjacent = merge_adjacent
        self.export_name = parent.catalog.name if parent.catalog else None
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
                self.progress.emit,
                self.isInterruptionRequested,
                region_indices=self.region_indices,
                individual_regions=self.region_indices is not None,
                export_name=self.export_name,
                selected_polygons=self.selected_polygons,
                merge_adjacent=self.merge_adjacent,
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
        self.remembered_merge_selected_regions = load_merge_selected_regions(self.preferences_path)
        self.merge_selected_regions = self.remembered_merge_selected_regions is True
        self.connection_choices = {
            tool: load_connection_choice(self.preferences_path, tool)
            for tool in ("Erase lines", "Edit points")
        }
        self.input_directory = load_directory(self.preferences_path, "input")
        self.output_directory = load_directory(self.preferences_path, "output")
        self.recent_projects = load_recent_projects(self.preferences_path)
        self.setWindowTitle(application_title())
        self.resize(1280, 860)
        self.setMinimumSize(1224, 768)
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
        self.catalog = None
        self.json_workspaces = []
        self.saved_state = None
        self.regions = ()
        self.region_key = None
        self.selected_region = None
        self.marquee_selection = None
        self.figure_marquee = None
        self.current_tool_set = "geometry"
        self.last_tool_modes = {
            "geometry": "Edit points",
            "figures": "Select figures",
            "regions": "Select regions",
            "pixels": "Select raster regions",
        }
        self.view = MapView()
        self.view.connection_prompt = self.confirm_contour_connection
        self.view.move_related = self.remembered_move_related is True
        self.view.changed.connect(self.refresh)
        self.view.auto_close_requested.connect(self.confirm_auto_close)
        self.view.region_clicked.connect(self.toggle_region_at)
        self.view.figure_clicked.connect(self.select_figure_at)
        self.view.region_box_selected.connect(self.select_regions_in_box)
        self.view.regions_transformed.connect(self.select_transformed_regions)
        self.view.clipboard_changed.connect(self.update_clipboard_actions)
        self.view.paste_committed.connect(self.retain_clipboard_sources)
        self._clipboard_documents = ()
        self.view.message.connect(
            lambda message: self.statusBar().showMessage(self.t(message), 7000)
        )
        self.info = QLabel("Open a scene image to begin; scene JSON is optional.")
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
        form.addRow("Language", self.language_control)
        self.global_tools_control = QCheckBox("Store settings globally")
        self.global_tools_control.setChecked(self.use_global_tool_settings)
        self.global_tools_control.setToolTip(
            "Use these tool values for every project. Enabling copies current values; "
            "disabling restores this project's values."
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
        self.layer_control = QComboBox()
        self.layer_control.setMinimumWidth(120)
        self.layer_control.setToolTip(
            "Show and edit one height band including shared contours, or an exact source range. "
            "Shared contours keep one identity in every covered band. New contours use this range."
        )
        self.layer_control.currentIndexChanged.connect(self.select_source_layer)
        self.layer_control.hide()
        regions_layout.addWidget(self.layer_control)
        regions_layout.addWidget(self.region_control)
        self.project_info_group = QGroupBox("File information")
        file_layout = QVBoxLayout(self.project_info_group)
        for label in (self.info, self.map_info, self.diagnostics, self.feedback_label):
            file_layout.addWidget(label)
        self.json_repair_control = QCheckBox("Edit contours by height layers")
        self.json_repair_control.setToolTip(
            "Filter contour editing by height range. JSON export preserves all other scene data."
        )
        self.json_repair_control.toggled.connect(self.set_json_repair)
        self.json_repair_control.hide()
        file_layout.addWidget(self.json_repair_control)
        project_layout.addWidget(self.regions_group)
        project_layout.addWidget(self.project_info_group)
        self.sidebar_stack = QStackedWidget()
        self.sidebar_pages = {}
        self.mode_help_labels = {}
        self.information_groups = {}
        for key, content in (
            ("project", self.project_group),
            ("settings", self.settings_group),
        ):
            page = QWidget()
            sidebar = QVBoxLayout(page)
            sidebar.setContentsMargins(0, 0, 0, 0)
            sidebar.addWidget(content)
            information = QGroupBox("Information")
            information_layout = QVBoxLayout(information)
            help_label = QLabel()
            help_label.setWordWrap(True)
            help_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            help_scroll = QScrollArea()
            help_scroll.setWidgetResizable(True)
            help_scroll.setWidget(help_label)
            help_scroll.setMinimumHeight(160)
            help_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            help_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            help_scroll.setToolTip(
                "Scroll the available shortcuts for the current tool and window."
            )
            information_layout.addWidget(help_scroll)
            sidebar.addWidget(information, 1)
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
        self.sidebar_scroll = sidebar_scroll
        self.sidebar_toggle = QToolButton()
        self.sidebar_toggle.setObjectName("sidebarToggle")
        self.sidebar_toggle.setFixedSize(16, 64)
        self.sidebar_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sidebar_toggle.clicked.connect(
            lambda: self.set_sidebar_visible(not self.right_panel_visible)
        )
        layout = QHBoxLayout()
        left_panel = QWidget()
        self.left_panel = left_panel
        left_panel.setFixedWidth(76)
        self.tool_column = QVBoxLayout(left_panel)
        self.tool_column.setContentsMargins(0, 0, 0, 0)
        self.tool_column.setSpacing(4)
        self.tool_stack = QStackedWidget()
        self.tool_stack.setFixedWidth(64)
        self.tool_stack.setStyleSheet("QStackedWidget { background: transparent; border: 0; }")
        self.tool_scroll = QScrollArea()
        self.tool_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.tool_scroll.setWidgetResizable(True)
        self.tool_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tool_scroll.setStyleSheet("QScrollBar:vertical { width: 10px; }")
        self.tool_scroll.setWidget(self.tool_stack)
        self.tool_column.addWidget(self.tool_scroll, 1)
        layout.addWidget(left_panel)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.sidebar_toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(sidebar_scroll)
        self.set_sidebar_visible(load_right_panel_visible(self.preferences_path), persist=False)
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
        self.basic_toolbar = make_toolbar(self, "Main")
        self.dataset_toolbar = make_toolbar(self, "Dataset")
        self.dataset_heading = self.dataset_toolbar.findChild(QLabel)
        self.dataset_control = QComboBox()
        self.dataset_control.setFixedSize(230, 36)
        self.dataset_control.setToolTip("Choose a dataset with its current image and contours.")
        self.dataset_control.currentIndexChanged.connect(self.select_dataset)
        self.manager_button = QToolButton(self.dataset_toolbar)
        self.manager_button.setText("Dataset manager")
        self.manager_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.manager_button.setIcon(tool_icon("Dataset manager"))
        self.manager_button.setIconSize(QSize(22, 22))
        self.manager_button.setFixedSize(36, 36)
        self.manager_button.setToolTip(
            "Dataset manager: create, rename, combine or transfer datasets."
        )
        self.manager_button.clicked.connect(self.manage_datasets)
        self.dataset_toolbar.addWidget(self.manager_button)
        dataset_gap = QWidget()
        # Match the 4px panel inset plus 3px heading padding, including two 1px gaps.
        dataset_gap.setFixedWidth(5)
        self.dataset_toolbar.addWidget(dataset_gap)
        self.dataset_toolbar.addWidget(self.dataset_control)
        geometry = make_toolbar(self, "Vertices", vertical=True)
        self.geometry_toolbar = geometry
        figures = make_toolbar(self, "Contours", vertical=True)
        self.figure_toolbar = figures
        region_tools = make_toolbar(self, "Regions", vertical=True)
        pixels = make_toolbar(self, "Raster", vertical=True)
        self.toolbars = (
            categories,
            self.basic_toolbar,
            self.dataset_toolbar,
            geometry,
            region_tools,
            pixels,
            figures,
        )
        self.geometry_eraser_tiles = {}
        self.sized_tools = {}
        for bar in (geometry, figures, region_tools, pixels):
            self.tool_stack.addWidget(bar)

        def action(bar, title, handler, shortcut=None):
            item = QAction(title, self)
            item.setProperty("dale_tool_key", title)
            display = {
                "Auto-close": "Auto-close contours",
                "Edit points": "Edit contour vertices",
                "Select figures": "Select contours",
                "Move figures": "Move contours",
                "Rotate figures": "Rotate contours",
                "Figure point alignment": "Contour point alignment",
                "Figure guide alignment": "Contour guide alignment",
                "New line": "New contour line",
                "New circle": "New circular contour",
                "New rectangle": "New rectangular contour",
                "Export PNGs": "Export regions as PNGs",
                "Erase lines": "Erase contour lines",
                "Erase vertices": "Erase contour vertices",
                "Snapping (px)": "Contour snapping (px)",
                "Artwork offset (px)": "Region artwork offset (px)",
                "Erase": "Erase raster pixels",
                "Restore": "Restore raster pixels",
                "Remove outside": "Erase raster outside selected regions",
                "Remove inside": "Erase raster inside selected regions",
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
            item.triggered.connect(lambda *_: self.view.finish_rotation())
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
                "Region point alignment": (
                    0,
                    256,
                    14,
                    "region_point_distance",
                    lambda v: self.snap_distance.setValue(v),
                ),
                "Region guide alignment": (
                    1,
                    9999,
                    14,
                    "region_guide_distance",
                    lambda v: self.contour_alignment_distance.setValue(v),
                ),
                "Figure point alignment": (
                    0,
                    256,
                    14,
                    "figure_point_distance",
                    lambda v: self.snap_distance.setValue(v),
                ),
                "Figure guide alignment": (
                    1,
                    9999,
                    14,
                    "figure_guide_distance",
                    lambda v: self.contour_alignment_distance.setValue(v),
                ),
                "Right-angle alignment": (
                    1,
                    9999,
                    14,
                    "right_angle_distance",
                    lambda value: self.set_alignment_distance("right_angle_distance_px", value),
                ),
                "Contour alignment": (
                    1,
                    9999,
                    14,
                    "contour_alignment_distance",
                    lambda value: self.set_alignment_distance(
                        "contour_alignment_distance_px", value
                    ),
                ),
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
        for key, title in (
            ("geometry", "Vertices"),
            ("figures", "Contours"),
            ("regions", "Regions"),
            ("pixels", "Raster"),
        ):
            item = action(
                categories, title, lambda checked=False, key=key: self.select_tool_set(key)
            )
            item.setCheckable(True)
            tool_sets.addAction(item)
            self.tool_set_actions[key] = item
        self.tool_set_actions["geometry"].setChecked(True)

        self.manager_action = action(
            self.file_menu, "Dataset manager…", self.manage_datasets, "Ctrl+I"
        )
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
        self.export_json_action = action(
            self.file_menu, "Export JSON…", self.export_json, "Ctrl+Shift+J"
        )
        self.export_json_action.setEnabled(False)
        self.export_json_action.setToolTip(
            "Export the current set's applied contours as JSON, including unsaved edits."
        )
        action(self.file_menu, "Close project", self.close_document)
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
                    "New rectangle",
                    "Auto-close",
                    "Erase lines",
                    "Erase vertices",
                ),
            ),
            (region_tools, REGION_TOOLS),
            (figures, FIGURE_TOOLS),
            (pixels, ("Select raster regions", "Erase", "Restore")),
        ):
            for mode in names:
                item = action(bar, mode, lambda checked=False, m=mode: self.activate_mode(m))
                item.setCheckable(True)
                item.setChecked(mode == "Pan")
                modes.addAction(item)
                self.mode_actions[mode] = item
        self.mode_actions["Select raster regions"].setEnabled(False)
        self.select_all_action = action(
            self.basic_toolbar, "Select all contour lines", self.select_all_elements, "Ctrl+A"
        )
        self.clear_selection_action = action(
            self.basic_toolbar, "Clear selection", self.clear_selection, "Ctrl+Shift+A"
        )
        self.edit_menu.addAction(self.select_all_action)
        self.edit_menu.addAction(self.clear_selection_action)
        self.copy_regions_action = action(
            self.edit_menu, "Copy region contours", self.copy_region_contours, "Ctrl+C"
        )
        self.paste_regions_action = action(
            self.edit_menu, "Paste region contours", self.paste_region_contours, "Ctrl+V"
        )
        self.copy_regions_action.setToolTip(
            "Copy selected region boundaries. Raster pixels stay in place."
        )
        self.paste_regions_action.setToolTip(
            "Preview copied contours at the cursor; click to place. Alt with "
            "Contour alignment: snap to a vertex first, then horizontal/vertical guides. "
            "Escape: cancel."
        )
        self.update_clipboard_actions()
        self.move_button = region_tools.widgetForAction(self.mode_actions["Move regions"])
        self.rotate_button = region_tools.widgetForAction(self.mode_actions["Rotate regions"])
        action(self.basic_toolbar, "Fit", self.view.fit_map, "F")
        self.walls_action = action(self.basic_toolbar, "Show contours", self.toggle_walls)
        self.walls_action.setCheckable(True)
        self.walls_action.setChecked(True)
        self.alignment_actions = {}
        for key, title in (
            ("right_angle_alignment", "Right-angle alignment"),
            ("contour_alignment", "Contour alignment"),
        ):
            item = action(
                geometry, title, lambda checked, key=key: self.set_alignment(key, checked)
            )
            item.setCheckable(True)
            self.alignment_actions[key] = item
        self.settings_action = action(
            self.basic_toolbar,
            "Settings",
            lambda checked: self.show_sidebar("settings" if checked else "project"),
        )
        self.settings_action.setCheckable(True)
        self.settings_action.setToolTip("Show or hide the application settings panel.")
        self.geometry_brush_control = self.geometry_eraser_tiles["Erase lines"].editor()
        for tool, button in (
            ("Erase lines", self.geometry_eraser_tiles["Erase lines"]),
            ("Edit points", geometry.widgetForAction(self.mode_actions["Edit points"])),
        ):
            button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            button.customContextMenuRequested.connect(
                lambda position, tool=tool: self.confirm_contour_connection(tool, settings=True)
            )
        self.vertex_brush_control = self.geometry_eraser_tiles["Erase vertices"].editor()
        pixels.addSeparator()
        self.mask_actions = {
            "outside": action(pixels, "Remove outside", lambda: self.mask("outside")),
            "inside": action(pixels, "Remove inside", lambda: self.mask("inside")),
        }
        self.auto_close_tile = self.sized_tools["Auto-close"]
        self.snap_action = action(geometry, "Snapping (px)", self.set_snapping)
        self.snap_action.setCheckable(True)
        self.snap_action.setChecked(True)
        self.snap_tile = self.sized_tools["Snapping (px)"]
        action(geometry, "Close all contours", self.close_all_contours)
        self.delete_regions_action = action(
            region_tools, "Delete region", self.delete_selected_regions, "Del"
        )
        self.delete_regions_action.setEnabled(False)
        self.edit_menu.addAction(self.delete_regions_action)
        self.delete_contours_action = action(
            self.edit_menu, "Delete contours", self.delete_selected_contours, "Del"
        )
        self.delete_contours_action.setEnabled(False)
        self.export_regions_action = action(
            region_tools, "Export selected regions", lambda: self.export(selected_only=True)
        )
        self.export_regions_button = region_tools.widgetForAction(self.export_regions_action)
        self.export_regions_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.export_regions_button.customContextMenuRequested.connect(
            lambda position: self.confirm_merge_selected_regions(settings=True)
        )
        self.region_alignment_actions = {}
        self.figure_alignment_actions = {}
        for bar, prefix, target in (
            (region_tools, "Region", self.region_alignment_actions),
            (figures, "Figure", self.figure_alignment_actions),
        ):
            for suffix, source_control, initial in (
                ("point alignment", self.snap_distance, True),
                (
                    "guide alignment",
                    self.contour_alignment_distance,
                    False,
                ),
            ):
                title = f"{prefix} {suffix}"
                item = action(bar, title, self.apply_section_alignment)
                item.setCheckable(True)
                item.setChecked(initial)
                source_control.valueChanged.connect(self.sized_tools[title].editor().setValue)
                target[title] = item
        for command in (
            self.snap_action,
            *self.alignment_actions.values(),
            *self.figure_alignment_actions.values(),
            *self.region_alignment_actions.values(),
        ):
            command.toggled.connect(self.apply_section_alignment)
        action(region_tools, "Artwork offset (px)", lambda: self.contour_offset.setFocus())
        for bar in (geometry, figures, region_tools, pixels):
            bar.ensurePolished()
            bar.setFixedHeight(bar.sizeHint().height())
        self.tool_stack.setFixedHeight(self.tool_stack.currentWidget().sizeHint().height())
        self.view.size_changed.connect(self.sync_tool_sizes)
        QApplication.instance().installEventFilter(self)
        tips = {
            "Select all contour lines": (
                "Select all elements of the current section in the visible height scope."
            ),
            "Delete region": (
                "Delete selected region boundaries, including hole outlines. "
                "Keep lines inside and image pixels."
            ),
            "Region point alignment": (
                "Snap the highlighted region vertex to an existing point; move the whole figure."
            ),
            "Region guide alignment": (
                "Align the highlighted region vertex with horizontal/vertical vertex guides."
            ),
            "Dataset manager…": "Dataset manager: create, rename, combine or transfer datasets.",
            "Open project": "Open a .dale project with its files, edits and undo history.",
            "Save project": (
                "Save every dataset and its editing history in the current .dale project."
            ),
            "Save project as…": (
                "Save all datasets and editing history to a new .dale project file."
            ),
            "Export PNGs": (
                "Save closed regions as separate transparent PNGs with a coordinate manifest."
            ),
            "Export JSON…": (
                "Save the current dataset's contours, including unsaved edits, as JSON."
            ),
            "Close project": "Close all datasets. Unsaved changes can be saved first.",
            "Exit": "Exit DALE. Unsaved changes can be saved first.",
            "About DALE…": "Show the installed version and application information.",
            "Pan": "Drag with either mouse button to pan the scene. Wheel: zoom.",
            "Auto-close": "Hover over a contour to preview connections. Click to confirm them.",
            "Close all contours": (
                "Preview joins across all contours by extending or shortening free ends."
            ),
            "New line": (
                "Press at the first point, drag to the second and release to create a line."
            ),
            "New rectangle": "Press at one corner, drag to the opposite corner and release.",
            "New circle": "Press at the center, drag the radius and release to create a contour.",
            "Erase lines": "Delete touched line pieces up to their intersections or endpoints.",
            "Erase vertices": (
                "Drag to delete points. Two neighbours reconnect; branches are removed."
            ),
            "Snapping (px)": "Toggle snapping to existing points and lines. Points take priority.",
            "Right-angle alignment": (
                "Make a right angle with adjacent contour lines, including rotated contours."
            ),
            "Contour alignment": (
                "Align a point or shape with other vertices horizontally or vertically."
            ),
            "Vertices": "Edit contour vertices and lines, draw shapes and close gaps.",
            "Regions": "Select closed regions, adjust their contours and export PNGs.",
            "Raster": "Erase image pixels or restore them from the original image.",
            "Select figures": ("Select contour lines for moving, scaling, rotating or copying."),
            "Delete contours": (
                "Delete only selected contour lines; keep unselected lines and image pixels."
            ),
            "Select regions": (
                "Click to toggle a region; drag over 10 screen pixels to invert regions in a box. "
                "Empty click clears selection."
            ),
            "Contours": (
                "Select open or closed contour lines to move, scale, rotate or copy together."
            ),
            "Move figures": "Move selected contour lines together. Image pixels stay in place.",
            "Rotate figures": "Rotate selected contour lines around their common center.",
            "Figure point alignment": "Snap the highlighted contour vertex to an existing point.",
            "Figure guide alignment": (
                "Align the highlighted contour vertex with vertex X/Y guides."
            ),
            "Select raster regions": (
                "Click to toggle a region; drag over 10 screen pixels to invert regions in a box. "
                "Empty click clears selection."
            ),
            "Move regions": "Drag selected contours to move them. Image pixels stay in place.",
            "Rotate regions": (
                "Wheel: rotate selected contours by 0.1 degrees per notch; up is "
                "clockwise. Image pixels stay in place."
            ),
            "Export selected regions": (
                "Save selected regions as transparent PNGs, optionally joining adjacent selections."
            ),
            "Artwork offset (px)": "Include scene image pixels beyond the contour or cut inward.",
            "Edit points": (
                "Click a line: add a point. Drag a point: move it. Double-click: delete it."
            ),
            "Erase": "Drag to make image pixels transparent.",
            "Restore": "Drag to restore image pixels from the original scene image.",
            "Remove outside": (
                "Erase pixels outside selected regions using the same edge filtering as PNG export."
            ),
            "Remove inside": (
                "Erase pixels inside selected regions using the same edge filtering as PNG export."
            ),
            "Undo": "Undo the last edit in the current dataset.",
            "Redo": "Reapply the last undone edit in the current dataset.",
            "Fit": "Fit the whole scene image in the editing area.",
            "Show contours": (
                "Toggle contour visibility. Selected regions and highlighted lines stay visible."
            ),
            "Clear selection": (
                "Deselect regions and highlighted contours; cancel the current gesture."
            ),
            "Settings": "Open or close language and tool settings in the right panel.",
            "Copy region contours": (
                "Copy selected outlines to the clipboard for use in any dataset."
            ),
            "Paste region contours": "Click to place copied outlines. Image pixels stay in place.",
        }
        contour_tools = {
            "Edit points",
            "New line",
            "New circle",
            "New rectangle",
            "Auto-close",
            "Erase lines",
            "Erase vertices",
            "Snapping (px)",
            "Close all contours",
        }
        conditions = {
            "Delete contours": (
                "Contours is active, a line is selected and no gesture or export is in progress."
            ),
            "Select all contour lines": "The current section contains selectable elements.",
            "Delete region": (
                "Regions is active, a region is selected and no gesture is in progress."
            ),
            "Region point alignment": (
                "This button is enabled and a region is being moved or pasted."
            ),
            "Region guide alignment": (
                "This button is enabled and a region is being moved or pasted."
            ),
            "Figure point alignment": (
                "This button is enabled and contours are being moved or pasted."
            ),
            "Figure guide alignment": (
                "This button is enabled and contours are being moved or pasted."
            ),
            "Select figures": "Contours are available.",
            "Move figures": "At least one contour line is selected.",
            "Rotate figures": "At least one contour line is selected.",
            **{key: "An image or contour JSON is open." for key in contour_tools},
            "Right-angle alignment": "This button is enabled and a contour point is being moved.",
            "Contour alignment": (
                "This button is enabled and a point or shape is being moved or drawn."
            ),
            "Select regions": "Contours enclose a closed region.",
            "Select raster regions": "A scene image and closed contours are available.",
            "Move regions": "At least one region is selected.",
            "Rotate regions": "At least one region is selected.",
            "Copy region contours": "At least one region is selected.",
            "Paste region contours": (
                "Region contours have been copied to the application clipboard."
            ),
            "Export selected regions": "A scene image is open and at least one region is selected.",
            "Export PNGs": ("A scene image and closed contours are available."),
            "Export JSON…": "The current dataset has contours or a scene JSON.",
            "Erase": "A scene image is open.",
            "Restore": "A scene image is open.",
            "Remove outside": "A scene image and selected regions are available.",
            "Remove inside": "A scene image and selected regions are available.",
            "Artwork offset (px)": "A scene image and closed contours are available.",
            "Undo": "The current dataset has an edit to undo.",
            "Redo": "The current dataset has an undone edit to reapply.",
            "Fit": "An image or contour JSON is open.",
        }
        for item in self.findChildren(QAction):
            key = item.property("dale_tool_key")
            if key in tips:
                parts = [tips[key]]
                keys = []
                if key in ("Edit points", "Paste region contours"):
                    keys.append("Alt: use the enabled alignment buttons.")
                if key == "New rectangle":
                    keys.append("Alt: align corners when Contour alignment is enabled.")
                if key == "New circle":
                    keys.append("Ctrl+wheel while drawing: adjust the radius.")
                if key in ("Edit points", "Erase lines"):
                    keys.append("Right-click the tool button: configure the connection question.")
                if key == "Export selected regions":
                    keys.append("Right-click this button: configure adjacent-region export.")
                if key in (
                    "Right-angle alignment",
                    "Contour alignment",
                    "Region point alignment",
                    "Region guide alignment",
                    "Figure point alignment",
                    "Figure guide alignment",
                ):
                    keys.append("Alt: apply this alignment while dragging.")
                if key in MOVE_TOOLS:
                    keys.append("Ctrl+wheel: scale selected contours.")
                if key in ROTATE_TOOLS:
                    keys.append("Wheel: rotate selected contours by 0.1 degrees.")
                if key == "Select figures":
                    keys.extend(
                        [
                            "Click: toggle the line under the cursor.",
                            "Double-click: select all lines connected by shared vertices.",
                            "Drag over 10 screen pixels: invert lines intersecting the box.",
                        ]
                    )
                if key in (
                    "New line",
                    "New circle",
                    "New rectangle",
                    "Edit points",
                    "Erase lines",
                    "Erase vertices",
                    "Erase",
                    "Restore",
                    "Move regions",
                    "Select regions",
                    "Select raster regions",
                    "Select figures",
                    "Move figures",
                    "Paste region contours",
                ):
                    keys.append("Escape: cancel the current gesture.")
                item.setProperty("dale_tooltip_parts", parts)
                item.setProperty("dale_default_tooltip_parts", parts)
                item.setProperty("dale_tooltip_condition", conditions.get(key))
                item.setProperty("dale_default_tooltip_condition", conditions.get(key))
                item.setProperty("dale_tooltip_keys", keys)
                item.setToolTip(
                    format_tooltip(
                        parts,
                        "en",
                        item.shortcut(),
                        condition=conditions.get(key),
                        keys=keys,
                        title=item.property("dale_display_key") or key,
                    )
                )
            display_key = item.property("dale_display_key")
            if display_key:
                item.setText(display_key)
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
        for control in (self.language_control,):
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

    def control_help(self, text, *, condition=None, keys=(), title=None):
        return format_tooltip([text], self.language, condition=condition, keys=keys, title=title)

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
        close.setToolTip(
            self.control_help(
                "Close this window.", keys=["Escape: close this window."], title="Close"
            )
        )
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
            "right_angle_distance_px": self.right_angle_distance,
            "contour_alignment_distance_px": self.contour_alignment_distance,
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
            control.valueChanged.connect(lambda *_: self.view.finish_rotation())
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
        self.view.detached_selection = None
        self.selected_regions = ()
        self.view.region_pivot = None
        self.view.figure_line_ids = ()
        self.view.figure_pivot = None
        self.view.contour_line_ids = ()
        self.view.cursor_point = self.view.hover_edge = None
        self.view.update_hover()
        self.update_map_info()
        self.view.update_image()

    def select_all_elements(self):
        if not self.view.session:
            return
        self.view.cancel_pending()
        if self.current_tool_set in ("geometry", "figures"):
            geometry = self.view.editing_geometry()
            ids = tuple(record.id for record in geometry.lineage)
            if self.current_tool_set == "figures":
                self.view.figure_line_ids = ids
                self.view.figure_pivot = None
            else:
                self.view.contour_line_ids = ids
                self.view.update_hover()
        else:
            self.view.detached_selection = None
            self.view.region_pivot = None
            self.selected_regions = ()
            self.update_map_info()
            self.selected_regions = tuple(range(len(self.regions)))
        self.update_map_info()

    def set_language(self, language, persist=True):
        self.view.finish_rotation()
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
                self.map_info,
                self.region_control,
                self.layer_control,
                self.dataset_control,
                self.dataset_heading,
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
        self.rebuild_dataset_controls()
        self.set_sidebar_visible(self.right_panel_visible, persist=False)
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
            self.info.setText(self.t("Open a scene image to begin; scene JSON is optional."))
            return
        source = self.view.session.source
        name = self.project_path.name if self.project_path else source.name
        self.info.setText("\n".join((name, *(self.t(warning) for warning in source.warnings))))

    def information(self, title, text, *options):
        return QMessageBox.information(self, self.t(title), self.t(text), *options)

    def warning(self, title, text, *options):
        return QMessageBox.warning(self, self.t(title), self.t(text), *options)

    def question(self, title, text, *options):
        return QMessageBox.question(self, self.t(title), self.t(text), *options)

    def confirm_contour_connection(self, tool, *, settings=False):
        self.view.finish_rotation()
        choice = self.connection_choices[tool]
        if choice is not None and not settings:
            return choice
        title = self.mode_actions[tool].text()
        purpose = (
            "Connect new cut endpoints to intersecting contours with shared vertices?"
            if tool == "Erase lines"
            else "Connect this point to the other contour with a shared vertex?"
        )
        dialog = QMessageBox(QMessageBox.Icon.Question, title, self.t(purpose), parent=self)
        dialog.setObjectName("contourConnectionQuestion")
        if settings:
            dialog.setInformativeText(
                self.t(
                    "Choose the answer for this tool. Clear the checkbox to ask on each contact."
                )
            )
        checkbox = QCheckBox(self.t("Do not ask again"), dialog)
        checkbox.setObjectName("rememberContourConnection")
        checkbox.setChecked(settings and choice is not None)
        checkbox.setToolTip(
            self.control_help(
                "Remember this answer for this tool. Right-click its button to change it.",
                title="Do not ask again",
            )
        )
        dialog.setCheckBox(checkbox)
        for kind, caption, help_text in (
            (QMessageBox.StandardButton.Yes, "Yes", "Connect the contours with shared vertices."),
            (QMessageBox.StandardButton.No, "No", "Keep the contours separate."),
            (
                QMessageBox.StandardButton.Cancel,
                "Cancel",
                "Leave contours and question settings unchanged.",
            ),
        ):
            button = dialog.addButton(kind)
            button.setText(self.t(caption))
            button.setToolTip(self.control_help(help_text, title=caption))
        dialog.setDefaultButton(
            QMessageBox.StandardButton.Yes if choice is True else QMessageBox.StandardButton.No
        )
        dialog.setEscapeButton(QMessageBox.StandardButton.Cancel)
        result = dialog.exec()
        if result == QMessageBox.StandardButton.Cancel:
            return None
        answer = result == QMessageBox.StandardButton.Yes
        remembered = answer if checkbox.isChecked() else None
        self.connection_choices[tool] = remembered
        try:
            save_connection_choice(self.preferences_path, tool, remembered)
        except OSError:
            self.statusBar().showMessage(self.t("Preferences could not be written."), 7000)
        return answer

    def confirm_merge_selected_regions(self, *, settings=False):
        self.view.finish_rotation()
        choice = self.remembered_merge_selected_regions
        if choice is not None and not settings:
            self.merge_selected_regions = choice
            return choice
        dialog = QMessageBox(
            QMessageBox.Icon.Question,
            self.t("Export selected regions"),
            self.t("Export adjacent regions as one?"),
            parent=self,
        )
        dialog.setObjectName("mergeSelectedRegionsQuestion")
        dialog.setInformativeText(
            self.t(
                "Yes: one PNG per connected group of selected regions. No: one PNG per region. "
                "Unselected regions are not included."
            )
        )
        if settings:
            dialog.setInformativeText(
                dialog.informativeText()
                + "\n\n"
                + self.t("Choose the answer for export. Clear the checkbox to ask on every export.")
            )
        checkbox = QCheckBox(self.t("Do not ask again"), dialog)
        checkbox.setChecked(settings and choice is not None)
        checkbox.setToolTip(
            self.control_help(
                "Remember the answer between launches. "
                "Right-click Export selected regions to change it.",
                title="Do not ask again",
            )
        )
        dialog.setCheckBox(checkbox)
        for kind, caption, help_text in (
            (
                QMessageBox.StandardButton.Yes,
                "Yes",
                "Save each adjacent selected group in one PNG.",
            ),
            (QMessageBox.StandardButton.No, "No", "Save each selected region in its own PNG."),
            (
                QMessageBox.StandardButton.Cancel,
                "Cancel",
                "Cancel without exporting or changing the question settings.",
            ),
        ):
            button = dialog.addButton(kind)
            button.setText(self.t(caption))
            button.setToolTip(self.control_help(help_text, title=caption))
        dialog.setDefaultButton(
            QMessageBox.StandardButton.Yes
            if self.merge_selected_regions
            else QMessageBox.StandardButton.No
        )
        dialog.setEscapeButton(QMessageBox.StandardButton.Cancel)
        result = dialog.exec()
        if result == QMessageBox.StandardButton.Cancel:
            return None
        answer = result == QMessageBox.StandardButton.Yes
        self.merge_selected_regions = answer
        self.remembered_merge_selected_regions = answer if checkbox.isChecked() else None
        try:
            save_merge_selected_regions(
                self.preferences_path, self.remembered_merge_selected_regions
            )
        except OSError:
            self.statusBar().showMessage(self.t("Preferences could not be written."), 7000)
        self.update_map_info()
        return answer

    def close_all_contours(self):
        if self.view.session:
            tolerance = self.global_close_control.value() / max(self.view.transform().m11(), 1e-9)
            index = self.view.repair_index(self.view.session.geometry(), tolerance)
            plan = index.all()
            self.view.auto_close_review = True
            self.view.highlight_edges(plan.segments, plan.endpoint_moves)
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
                    "Affected segments: {segments}\nEndpoint extensions: {extensions}\n"
                    "Endpoint shortenings: {retractions}\nShared"
                    " intersections: {connections}\n\nConnect the highlighted lines?"
                ),
                segments=len(plan.segments),
                extensions=len(plan.extensions),
                retractions=len(plan.retractions),
                connections=len(plan.connections),
            )
        elif plan.segments:
            text = self.t(
                "No changes are needed or possible at this distance. Touching lines are"
                " already connected; remaining gaps need a larger distance or New line."
            )
        else:
            text = self.t("No lines under the cursor. Point at a line and click again.")
        if hasattr(plan, "conflicts"):
            if not changed:
                text = self.t("No compatible endpoint moves at this distance.")
            text += "\n\n" + self.t(
                "Height bands: {layers}. Conflict groups left unchanged: {conflicts}.",
                layers=plan.layer_count,
                conflicts=len(plan.conflicts),
            )
            if plan.conflicts:
                indices = sorted(
                    {
                        (
                            session.source.wall_sources[i].wall_index + 1
                            if i < len(session.source.wall_sources)
                            else len(session.source.raw["walls"])
                            + i
                            - len(session.source.wall_sources)
                            + 1
                        )
                        for _, keys in plan.conflicts
                        for i, _ in keys
                    }
                )
                text += "\n" + self.t(
                    "Review original contours: {numbers}.",
                    numbers=", ".join(map(str, indices[:30])),
                )
        if not changed:
            dialog = QMessageBox(
                QMessageBox.Icon.Information, self.t("Auto-close contours"), text, parent=self
            )
            dialog.setObjectName("autoCloseInformation")
            close = dialog.addButton(QMessageBox.StandardButton.Close)
            close.setText(self.t("Close"))
            close.setToolTip(
                self.control_help(
                    "Close this window.", keys=["Escape: close this window."], title="Close"
                )
            )
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
        cancel.setToolTip(
            self.control_help("Leave contours unchanged.", keys=["Escape: cancel."], title="Cancel")
        )
        yes.setToolTip(
            self.control_help("Apply the shown connections as one undo step.", title="Yes")
        )
        dialog.setDefaultButton(cancel)
        dialog.setEscapeButton(cancel)
        if dialog.exec() == QMessageBox.StandardButton.Yes and changed:
            if self.view.session is session and session.geometry() == original:
                session.add(geometry)
                self.refresh()

    def configure_json_repair(self, enabled=None):
        source = self.view.session.source if self.view.session else None
        available = bool(source and source.json_bytes is not None)
        self.json_repair_control.setVisible(available)
        if enabled is None:
            enabled = bool(
                available
                and (
                    source.image_path is None
                    or any(
                        isinstance(w.get("flags"), dict) and "wall-height" in w["flags"]
                        for w in source.raw["walls"]
                    )
                )
            )
        self.json_repair_control.blockSignals(True)
        self.json_repair_control.setChecked(bool(enabled and available))
        self.json_repair_control.blockSignals(False)
        self.set_json_repair(bool(enabled and available))

    def set_json_repair(self, enabled):
        session = self.view.session
        self.view.cancel_pending()
        self.view.safe_json_repair = enabled
        self.view.auto_close_key = None
        blocked = (
            "New circle",
            *GEOMETRY_ERASERS,
            *TRANSFORM_TOOLS,
            "Erase",
            "Restore",
        )
        for mode in blocked:
            self.mode_actions[mode].setEnabled(True)
        self.restore_geometry_tool_help(blocked)
        for mode in ("Edit points", "New line", "New rectangle"):
            self.mode_actions[mode].setEnabled(True)
        has_image = bool(session and session.source.image_path)
        for key in ("figures", "regions", "pixels"):
            self.tool_set_actions[key].setEnabled(bool(session))
        for mode in ("Erase", "Restore", "Select raster regions"):
            self.mode_actions[mode].setEnabled(has_image)
        self.tool_set_actions["pixels"].setEnabled(has_image)
        self.export_action.setEnabled(has_image and not self.worker)
        self.export_regions_action.setEnabled(has_image and not self.worker)
        has_data = bool(
            session
            and (
                session.source.image_path
                or session.source.json_bytes is not None
                or session.geometry().lineage
            )
        )
        self.export_json_action.setEnabled(has_data and not self.worker)
        self.mode_actions["Auto-close"].setEnabled(has_data)
        if session and not has_data:
            for key, item in self.mode_actions.items():
                item.setEnabled(key == "Pan")
        self.refresh()

    def restore_geometry_tool_help(self, tools):
        actions = [
            *(self.mode_actions[key] for key in tools),
            self.tool_set_actions["regions"],
            self.tool_set_actions["figures"],
            self.tool_set_actions["pixels"],
            self.export_action,
            self.export_regions_action,
        ]
        for action in actions:
            condition = action.property("dale_default_tooltip_condition")
            action.setProperty("dale_tooltip_condition", condition)
            action.setToolTip(
                format_tooltip(
                    action.property("dale_tooltip_parts"),
                    self.language,
                    action.shortcut(),
                    condition=condition,
                    keys=action.property("dale_tooltip_keys") or [],
                    shortcut_label=action.text(),
                )
            )
        self.update_size_help()

    def rebuild_source_layers(self):
        enabled = bool(self.view.session and self.view.safe_json_repair)
        self.layer_control.setVisible(enabled)
        self.region_control.setVisible(not enabled)
        self.regions_group.setTitle(self.t("Height layers" if enabled else "Regions"))
        self.layer_control.blockSignals(True)
        self.layer_control.clear()
        if enabled:
            choices = source_layers(
                self.view.session.source, self.view.session.geometry(), self.view.property_documents
            )
            for layer in choices:
                label = (
                    self.t("All height layers")
                    if layer.kind == "all"
                    else self.t("Ambiguous heights")
                    if layer.kind == "ambiguous"
                    else self.t("{range} (exact range)", range=layer.range_text)
                    if layer.kind == "range"
                    else layer.range_text
                )
                self.layer_control.addItem(label, layer.key)
            index = self.layer_control.findData(self.view.source_layer)
            self.layer_control.setCurrentIndex(max(0, index))
            if index < 0 and not self.view.active_gesture:
                self.view.source_layer = "all"
                self.view.geometry_key = None
                self.view.refresh(render_image=False)
        self.layer_control.blockSignals(False)

    def select_source_layer(self, index):
        self.view.finish_rotation()
        if index < 0 or not self.view.session:
            return
        key = self.layer_control.itemData(index)
        if key == self.view.source_layer:
            return
        self.view.cancel_pending()
        self.view.detached_selection = None
        self.view.source_layer = key
        self.view.hover_edge = self.view.cursor_point = self.view.snap = None
        self.view.auto_close_key = None
        self.refresh()
        self.update_mode_help()

    def export_json(self):
        session = self.view.session
        if not session or self.worker:
            return
        if self.view.active_gesture:
            self.information("Finish editing", "Finish or cancel the active gesture first.")
            return
        document = self.catalog.snapshot() if self.catalog else current_contours_document(session)
        directory = (
            self.output_directory
            or (self.project_path.parent if self.project_path else self.input_directory)
            or Path.cwd()
        )
        selected, _ = QFileDialog.getSaveFileName(
            self,
            self.t("Export JSON…"),
            str(directory / Path(document.name).name),
            self.t("Scene JSON (*.json)"),
        )
        if not selected:
            return
        destination = Path(selected)
        if destination.suffix.lower() != ".json":
            destination = destination.with_name(destination.name + ".json")
        sources = [self.project_path] if self.project_path else []
        sessions = (
            (draft.session for draft in self.catalog.views.values()) if self.catalog else (session,)
        )
        sources.extend(
            path
            for draft in sessions
            for path in (draft.source.image_path, draft.source.json_path)
            if path
        )
        if self.catalog:
            sources.extend(image.path for image in self.catalog.images.values() if image.path)
            sources.extend(self.catalog.protected_inputs)
        try:
            native_session = (
                replace(session, json_documents=self.catalog.documents) if self.catalog else session
            )
            payload = (
                repaired_json_bytes(native_session)[0]
                if session.source.json_bytes is not None
                else document.data
            )
            write_json_copy(payload, destination, sources)
            self.remember_directory("output", destination.resolve().parent)
            self.information(
                "JSON exported",
                self.t(
                    "Current set contours exported.\n{path}",
                    path=destination,
                ),
            )
        except Exception as exc:
            self.warning("Cannot export scene JSON", str(exc))

    def set_brush(self, mode, value):
        self.view.raster_diameters[mode] = value
        self.view.viewport().update()

    def select_tool_set(self, key, activate=True):
        if key != self.current_tool_set:
            self.view.cancel_pending()
        self.left_panel.show()
        self.show_sidebar("project")
        self.current_tool_set = key
        self.view.figure_selection = key == "figures"
        self.view.contour_selection_context = key == "geometry"
        self.apply_section_alignment()
        self.view.update_hover()
        self.update_clipboard_actions()
        self.tool_stack.setCurrentIndex(
            {"geometry": 0, "figures": 1, "regions": 2, "pixels": 3}[key]
        )
        self.tool_stack.setFixedHeight(self.tool_stack.currentWidget().sizeHint().height())
        self.update_size_help()
        self.tool_set_actions[key].setChecked(True)
        if activate:
            self.activate_mode(self.last_tool_modes[key])

    def show_sidebar(self, key):
        if key == "settings" and not self.right_panel_visible:
            self.set_sidebar_visible(True)
        self.sidebar_stack.setCurrentWidget(self.sidebar_pages[key])
        self.settings_action.setChecked(key == "settings")

    def set_sidebar_visible(self, visible, *, persist=True):
        self.right_panel_visible = visible
        self.sidebar_scroll.setVisible(visible)
        self.sidebar_toggle.setArrowType(
            Qt.ArrowType.RightArrow if visible else Qt.ArrowType.LeftArrow
        )
        tip = "Hide right panel" if visible else "Show right panel"
        purpose = (
            "Collapse the project/settings panel to give the scene more space."
            if visible
            else "Show the project and settings panel."
        )
        self.sidebar_toggle.setProperty("dale_tooltip_parts", [purpose])
        self.sidebar_toggle.setProperty("dale_tooltip_title", tip)
        self.sidebar_toggle.setToolTip(format_tooltip([purpose], self.language, title=tip))
        self.sidebar_toggle.setAccessibleName(self.t(tip))
        if persist:
            try:
                save_right_panel_visible(self.preferences_path, visible)
            except OSError:
                self.statusBar().showMessage(self.t("Preferences could not be written."), 7000)

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
        self.update_clipboard_actions()
        if not self.mode_actions["Edit points"].property("dale_default_tooltip_parts"):
            return
        mode = self.view.mode
        instructions = {
            "Pan": ["Left-drag: pan the scene image."],
            "Edit points": [
                "Click a line: insert a contour point. Drag a circle: move it.",
                "Double-click a circle: delete the point. Alt-drag: use enabled "
                "angle/contour alignment buttons; "
                "guides show anchors.",
                "Escape: cancel the current gesture.",
            ],
            "New line": [
                "Press, drag, release: draw a contour line.",
                "Escape: cancel the current gesture.",
            ],
            "New rectangle": [
                (
                    "Press for the first corner, drag, release for the opposite "
                    "corner. One closed contour, one undo step."
                ),
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
                "Drag the circle: erase highlighted pieces up to intersections or endpoints.",
                "Ctrl+wheel: change this tool's diameter.",
                "Escape: cancel the current gesture.",
            ],
            "Erase vertices": [
                "Drag the circle: erase highlighted contour points.",
                "Ctrl+wheel: change this tool's diameter.",
                "Escape: cancel the current gesture.",
            ],
            "Select regions": [
                "Click a region: select/deselect. Empty click: clear selection.",
                "Drag over 10 screen pixels: invert regions intersecting the box.",
                "Escape: restore the selection from before dragging.",
            ],
            "Select figures": [
                "Click: toggle the line under the cursor.",
                "Double-click: select all lines connected by shared vertices.",
                "Drag over 10 screen pixels: invert lines intersecting the box.",
                "Empty click clears selection.",
                "Escape: restore the selection from before dragging.",
            ],
            "Move figures": [
                "Drag selected contour lines: move. Ctrl+wheel: scale.",
                "Escape: cancel the current gesture.",
            ],
            "Rotate figures": [
                "Wheel: rotate selected contour lines by 0.1 degrees around their common center.",
            ],
            "Select raster regions": [
                "Click a region: select/deselect. Empty click: clear selection.",
                "Drag over 10 screen pixels: invert regions intersecting the box.",
                "Escape: restore the selection from before dragging.",
                "Raster inside/outside commands use selected regions only.",
            ],
            "Move regions": [
                "Drag selected regions: move. Ctrl+wheel: scale.",
                "Escape: cancel the current gesture.",
            ],
            "Rotate regions": [
                "Wheel: rotate selected regions by 0.1 degrees around their common center.",
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
        for key in ("Edit points", "New line"):
            action = self.mode_actions[key]
            parts = action.property("dale_default_tooltip_parts")
            action.setProperty("dale_tooltip_parts", parts)
            tooltip = format_tooltip(
                parts,
                self.language,
                action.shortcut(),
                condition="An image or contour JSON is open.",
                keys=action.property("dale_tooltip_keys") or [],
                shortcut_label=action.text(),
            )
            action.setToolTip(tooltip)
            self.geometry_toolbar.widgetForAction(action).setToolTip(tooltip)
        if mode == "New rectangle":
            instructions = [
                *instructions,
                (
                    "Alt with Contour alignment enabled: align horizontally/vertically"
                    " with distant vertices."
                ),
            ]
        if mode in REGION_TOOLS:
            instructions = [
                *instructions,
                (
                    "The nearest region vertex is highlighted; "
                    "dragging keeps this vertex as the anchor."
                ),
                "Alt: use the enabled region point/guide alignment buttons.",
                (
                    "Ctrl+C: copy selected region contours. Ctrl+V: preview a copy; "
                    "click to place. Escape: cancel. Raster stays in place."
                ),
            ]
        if mode in FIGURE_TOOLS:
            instructions = [
                *instructions,
                (
                    "The nearest contour vertex is highlighted and stays the grab point "
                    "while dragging."
                ),
                "Alt: use the enabled contour point/guide alignment buttons.",
                (
                    "Ctrl+C: copy selected contours. Ctrl+V: preview a copy; "
                    "click to place. Escape cancels."
                ),
            ]
        if mode in ("Edit points", "Erase lines"):
            instructions = [
                *instructions,
                "Right-click the tool button: configure the connection question.",
            ]
        lines = [self.mode_actions[mode].text(), *(self.t(line) for line in instructions)]
        lines.append(self.t("Right-drag: pan the scene image."))
        if mode not in ROTATE_TOOLS:
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

    def activate_mode(self, mode, prompt=True):
        if mode in (*MOVE_TOOLS, *ROTATE_TOOLS) and prompt:
            if not (self.view.figure_line_ids if mode in FIGURE_TOOLS else self.selected_regions):
                mode = "Select figures" if mode in FIGURE_TOOLS else "Select regions"
        if mode != "Pan":
            key = (
                "pixels"
                if mode in ("Erase", "Restore", "Select raster regions")
                else "figures"
                if mode in FIGURE_TOOLS
                else "regions"
                if mode in REGION_TOOLS
                else "geometry"
            )
            self.last_tool_modes[key] = mode
            self.select_tool_set(key, activate=False)
        self.mode_actions[mode].setChecked(True)
        self.view.set_mode(mode)
        if mode in SELECTION_TOOLS and self.selected_regions is None:
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
        self.snap_action.setChecked(enabled)
        self.apply_section_alignment()
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
            and self.view.mode in ROTATE_TOOLS
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
                    self.right_angle_distance,
                    self.contour_alignment_distance,
                    self.region_point_distance,
                    self.region_guide_distance,
                    self.figure_point_distance,
                    self.figure_guide_distance,
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

    def set_alignment(self, key, enabled):
        self.alignment_actions[key].setChecked(enabled)
        self.apply_section_alignment()
        if self.view.drag_base is not None:
            self.view._update_axis_drag(QApplication.keyboardModifiers())

    def set_alignment_distance(self, key, value):
        setattr(self.view, key, value)
        if self.view.drag_base is not None:
            self.view._update_axis_drag(QApplication.keyboardModifiers())

    def apply_section_alignment(self, _enabled=None):
        actions, prefix = (
            (self.figure_alignment_actions, "Figure")
            if self.current_tool_set == "figures"
            else (self.region_alignment_actions, "Region")
            if self.current_tool_set == "regions"
            else (None, None)
        )
        self.view.snap_enabled = (
            actions[f"{prefix} point alignment"].isChecked()
            if actions
            else self.snap_action.isChecked()
        )
        self.view.contour_alignment = (
            actions[f"{prefix} guide alignment"].isChecked()
            if actions
            else self.alignment_actions["contour_alignment"].isChecked()
        )
        self.view.right_angle_alignment = (
            self.current_tool_set == "geometry"
            and self.alignment_actions["right_angle_alignment"].isChecked()
        )
        self.view.snap = None
        self.view.viewport().update()

    def alignment_ui_state(self):
        return {
            "snap_enabled": self.snap_action.isChecked(),
            **{key: command.isChecked() for key, command in self.alignment_actions.items()},
            **{
                f"{prefix}_{kind}_alignment": actions[
                    f"{prefix.title()} {kind} alignment"
                ].isChecked()
                for prefix, actions in (
                    ("figure", self.figure_alignment_actions),
                    ("region", self.region_alignment_actions),
                )
                for kind in ("point", "guide")
            },
        }

    def restore_alignment_state(self, settings):
        self.snap_action.setChecked(settings.get("snap_enabled", True))
        for key, command in self.alignment_actions.items():
            command.setChecked(settings.get(key, False))
        for prefix, actions in (
            ("figure", self.figure_alignment_actions),
            ("region", self.region_alignment_actions),
        ):
            for kind in ("point", "guide"):
                actions[f"{prefix.title()} {kind} alignment"].setChecked(
                    settings.get(f"{prefix}_{kind}_alignment", kind == "point")
                )
        self.apply_section_alignment()

    def close_document(self):
        if self.worker or not self.can_discard():
            return
        self.view.clear_map()
        self.bounds_preview.clear()
        if self.bounds_preview.worker:
            self.bounds_preview.worker.wait()
        self.configure_json_repair(False)
        self.release_json_workspaces()
        if self.loaded_project:
            self.loaded_project.close()
            self.loaded_project = None
        self.catalog = None
        self.rebuild_dataset_controls()
        self.project_path = self.saved_state = None
        self._project_tool_values = None
        self.info.setText(self.t("Open a scene image to begin; scene JSON is optional."))
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
        if self.saved_state is None and not self.view.session.operations and not self.catalog:
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
        if self.catalog:
            return self.catalog.state(
                self._project_tool_values["artwork_offset_px"]
                if self.use_global_tool_settings and self._project_tool_values is not None
                else session.contour_offset
            )
        return (
            tuple(session.operations),
            tuple(session.future),
            session.origin,
            session.gap_tolerance,
            self._project_tool_values["artwork_offset_px"]
            if self.use_global_tool_settings and self._project_tool_values is not None
            else session.contour_offset,
        )

    def ui_state(self):
        center = self.view.mapToScene(self.view.viewport().rect().center())
        detached = self.view.detached_selection
        selection = None
        if detached and self.view.session and detached["geometry"] == self.view.session.geometry():
            selection = {
                "lines": list(detached["line_ids"]),
                "polygons": [p.wkb_hex for p in detached["polygons"]],
                "pivot": list(self.view.region_pivot or detached["polygons"][0].centroid.coords[0]),
            }
        return {
            "detached_region_selection": selection,
            "figure_lines": list(self.view.figure_line_ids),
            "figure_pivot": list(self.view.figure_pivot) if self.view.figure_pivot else None,
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
            **self.alignment_ui_state(),
            "snap_distance_px": self.view.snap_distance,
            "right_angle_distance_px": self.view.right_angle_distance_px,
            "contour_alignment_distance_px": self.view.contour_alignment_distance_px,
            "line_eraser_diameter": self.view.geometry_diameters["Erase lines"],
            "vertex_eraser_diameter": self.view.geometry_diameters["Erase vertices"],
            "tool_set": self.current_tool_set,
            "artwork_offset_px": self.contour_offset.value(),
            "safe_json_repair": self.view.safe_json_repair,
            "source_layer": self.view.source_layer,
        }

    def update_clipboard_actions(self):
        if not hasattr(self, "paste_regions_action"):
            return
        figures = self.current_tool_set == "figures"
        if hasattr(self, "select_all_action"):
            contours = self.current_tool_set in ("geometry", "figures")
            caption = "Select all contour lines" if contours else "Select all regions"
            command = self.select_all_action
            if command.property("dale_display_key") != caption:
                command.setProperty("dale_display_key", caption)
            if command.text() != self.t(caption):
                command.setText(self.t(caption))
            enabled = bool(
                self.view.session
                and (self.view.editing_geometry().lineage if contours else self.available_regions())
            )
            if command.isEnabled() != enabled:
                command.setEnabled(enabled)
            parts = command.property("dale_tooltip_parts")
            if parts:
                help_text = format_tooltip(
                    parts,
                    self.language,
                    command.shortcut(),
                    condition=command.property("dale_tooltip_condition"),
                    title=command.text(),
                )
                if command.toolTip() != help_text:
                    command.setToolTip(help_text)
        for command, caption in (
            (
                self.copy_regions_action,
                "Copy contours" if figures else "Copy region contours",
            ),
            (
                self.paste_regions_action,
                "Paste contours" if figures else "Paste region contours",
            ),
        ):
            if command.property("dale_display_key") != caption:
                command.setProperty("dale_display_key", caption)
            if command.text() != self.t(caption):
                command.setText(self.t(caption))
            parts = command.property("dale_default_tooltip_parts")
            if parts:
                if figures and command == self.copy_regions_action:
                    parts = ["Copy selected contour lines. Image pixels stay in place."]
                elif figures:
                    parts = ["Place copied contour lines. Image pixels stay in place."]
                condition = (
                    "At least one contour line is selected."
                    if figures and command == self.copy_regions_action
                    else "Contour lines have been copied to the application clipboard."
                    if figures
                    else command.property("dale_default_tooltip_condition")
                )
                command.setProperty("dale_tooltip_parts", parts)
                command.setProperty("dale_tooltip_condition", condition)
                help_text = format_tooltip(
                    parts,
                    self.language,
                    command.shortcut(),
                    condition=condition,
                    keys=command.property("dale_tooltip_keys") or [],
                    title=command.text(),
                )
                if command.toolTip() != help_text:
                    command.setToolTip(help_text)
        available = bool(self.view.session and self.current_tool_set in ("figures", "regions"))
        copy_enabled = available and bool(
            self.view.figure_line_ids if figures else self.selected_regions
        )
        paste_enabled = available and self.view.region_clipboard is not None
        # QAction.changed refreshes help; avoid recursive unchanged writes.
        if self.copy_regions_action.isEnabled() != copy_enabled:
            self.copy_regions_action.setEnabled(copy_enabled)
        if self.paste_regions_action.isEnabled() != paste_enabled:
            self.paste_regions_action.setEnabled(paste_enabled)
        delete_enabled = bool(
            copy_enabled
            and self.current_tool_set == "regions"
            and not self.worker
            and not self.view.active_gesture
        )
        if (
            hasattr(self, "delete_regions_action")
            and self.delete_regions_action.isEnabled() != delete_enabled
        ):
            self.delete_regions_action.setEnabled(delete_enabled)
        if hasattr(self, "delete_contours_action"):
            contour_delete_enabled = bool(
                copy_enabled and figures and not self.worker and not self.view.active_gesture
            )
            if self.delete_contours_action.isEnabled() != contour_delete_enabled:
                self.delete_contours_action.setEnabled(contour_delete_enabled)
        if hasattr(self, "mask_actions"):
            mask_enabled = bool(
                self.view.session
                and self.view.session.source.image_path
                and self.view.region_polygons
                and self.current_tool_set != "figures"
                and not self.view.active_gesture
                and not self.worker
            )
            for command in self.mask_actions.values():
                if command.isEnabled() != mask_enabled:
                    command.setEnabled(mask_enabled)

    def delete_selected_contours(self):
        if (
            not self.view.session
            or self.current_tool_set != "figures"
            or self.worker
            or self.view.active_gesture
        ):
            return
        visible = {record.id for record in self.view.editing_geometry().lineage}
        selected = tuple(i for i in self.view.figure_line_ids if i in visible)
        if not selected:
            return
        original = self.view.session.geometry()
        try:
            geometry = delete_figures(original, selected)
        except ValueError as exc:
            self.warning("Cannot delete contours", str(exc))
            return
        self.view.session.add(geometry)
        self.view.cancel_pending()
        self.view.figure_line_ids = ()
        self.view.figure_pivot = None
        self.refresh()

    def delete_selected_regions(self):
        if (
            not self.view.session
            or self.current_tool_set != "regions"
            or not self.view.region_polygons
            or self.worker
            or self.view.active_gesture
        ):
            return
        original = self.view.session.geometry()
        try:
            geometry = delete_regions(
                original,
                self.view.region_polygons,
                selection_ids=self.view.detached_selection["line_ids"]
                if self.view.detached_selection
                else (),
                active_ids={
                    original.lineage[i].id for i in self.view.selected_source_layer().indices
                }
                if self.view.safe_json_repair
                else None,
            )
        except ValueError as exc:
            self.warning("Cannot delete region", str(exc))
            return
        if geometry != original:
            self.view.session.add(geometry)
            self.view.cancel_pending()
            self.view.detached_selection = None
            self.view.region_pivot = None
            self.selected_regions = ()
            self.refresh()

    def copy_region_contours(self):
        if self.view.copy_selected_regions():
            documents = self.catalog.documents if self.catalog else ()
            source = self.view.session.source
            if source.json_bytes is not None:
                documents = (
                    *documents,
                    JsonDocument(
                        "clipboard", source.json_name or source.name, "original", source.json_bytes
                    ),
                )
            needed = {
                ref.json_sha256
                for record in (
                    *self.view.region_clipboard.geometry.lineage,
                    *self.view.region_clipboard.geometry.ancestry,
                )
                for ref in record.sources
            }
            self._clipboard_documents = tuple(
                {
                    hashlib.sha256(d.data).hexdigest(): d
                    for d in documents
                    if hashlib.sha256(d.data).hexdigest() in needed
                }.values()
            )

    def clipboard_source_additions(self):
        if not self.catalog:
            return ()
        known = {hashlib.sha256(d.data).hexdigest() for d in self.catalog.documents}
        additions = tuple(
            replace(
                d,
                id="copy-source-" + hashlib.sha256(d.data).hexdigest()[:32],
                kind="original",
                image_name=None,
                image_member=None,
                image_path=None,
                is_current=False,
            )
            for d in self._clipboard_documents
            if hashlib.sha256(d.data).hexdigest() not in known
        )
        if (
            len(self.catalog.documents) + len(additions) >= 100
            or sum(len(d.data) for d in (*self.catalog.documents, *additions)) > 128 * 1024 * 1024
        ):
            raise ValueError("The project JSON catalog is full. Export to a different project.")
        return additions

    def paste_region_contours(self):
        try:
            self.clipboard_source_additions()
            if self.view.mode not in TRANSFORM_TOOLS:
                self.activate_mode(
                    "Select figures" if self.current_tool_set == "figures" else "Select regions"
                )
            self.view.begin_paste_regions()
        except ValueError as exc:
            self.warning("Cannot paste regions", str(exc))

    def retain_clipboard_sources(self, source):
        additions = self.clipboard_source_additions()
        if additions:
            self.catalog.base_session.json_documents += additions
            self.rebuild_dataset_controls()

    def project_ui_state(self):
        settings = self.ui_state()
        if self.use_global_tool_settings and self._project_tool_values is not None:
            settings.update(self._project_tool_values)
        return settings

    def rebuild_dataset_controls(self):
        control = self.dataset_control
        control.blockSignals(True)
        control.clear()
        if self.catalog:
            for key, view in self.catalog.views.items():
                control.addItem(view.name, key)
                control.setItemData(control.count() - 1, view.name, Qt.ItemDataRole.ToolTipRole)
            control.setCurrentIndex(control.findData(self.catalog.active_key))
        else:
            control.addItem(self.t("No dataset"))
        control.setEnabled(self.catalog is not None)
        control.blockSignals(False)
        self.dataset_heading.setText(self.t("Dataset"))
        self.manager_button.setAccessibleName(self.t("Dataset manager"))
        self.manager_button.setToolTip(self.manager_action.toolTip())
        self.manager_button.setEnabled(not self.worker)

    def manage_datasets(self):
        self.view.finish_rotation()
        if self.worker or self.view.active_gesture:
            self.information("Finish editing", "Finish or cancel the active gesture first.")
            return
        if self.catalog:
            self.catalog.capture(self.project_ui_state())
        from dale.dataset_manager import DatasetManager

        dialog = DatasetManager(self)
        dialog.exec()
        dialog.deleteLater()
        self.release_json_workspaces(keep_current=True)

    def apply_dataset_manager(self, catalog, open_id=None):
        previous_catalog = self.catalog
        previous_preview = self.view.preview
        previous_ui = self.project_ui_state()
        previous_id = self.catalog.active_key if self.catalog else None
        identifier = open_id or (previous_id if previous_id in catalog.views else catalog.base_key)
        try:
            catalog.activate(identifier)
            catalog.prepare()
            source = catalog.current.session.source
            preview = (
                self.view.preview
                if self.view.session
                and self.view.session.source.image_path == source.image_path
                and self.view.session.source.size == source.size
                else load_preview(source)
            )
            self.catalog = catalog
            self.show_catalog_view(
                catalog.current,
                preview,
                True,
                center=open_id is not None or previous_id != identifier,
            )
            return True
        except Exception as exc:
            self.catalog = previous_catalog
            if previous_catalog:
                old = replace(previous_catalog.current, ui=previous_ui)
                self.show_catalog_view(old, previous_preview, True, center=False)
            else:
                self.view.clear_map()
                self.configure_json_repair(False)
                self.refresh()
            self.warning("Cannot update datasets", str(exc))
            return False

    def select_dataset(self):
        if not self.catalog:
            return
        if self.worker or self.view.active_gesture:
            self.information("Finish editing", "Finish or cancel the active gesture first.")
            self.rebuild_dataset_controls()
            return
        key = self.dataset_control.currentData()
        previous = self.catalog.active_key
        if key == previous:
            return
        self.catalog.capture(self.project_ui_state())
        try:
            draft = self.catalog.activate(key)
            preview = load_preview(draft.session.source)
        except Exception as exc:
            self.catalog.active_key = previous
            self.rebuild_dataset_controls()
            self.warning("Cannot open scene", str(exc))
            return
        self.show_catalog_view(draft, preview, True)

    def show_catalog_view(self, draft, preview, existing, *, center=True):
        self.view.safe_json_repair = False
        self.view.assign(draft.session, preview)
        self.selected_regions = None
        settings = {**self.project_ui_state(), **draft.ui}
        self._project_tool_values = {
            k: settings.get(k, draft.session.contour_offset)
            if k == "artwork_offset_px"
            else settings[k]
            for k in TOOL_VALUE_RANGES
        }
        for control, value in (
            (self.gap_tolerance, draft.session.gap_tolerance),
            (self.origin_x, draft.session.origin[0]),
            (self.origin_y, draft.session.origin[1]),
        ):
            control.blockSignals(True)
            control.setValue(value)
            control.blockSignals(False)
        if not self.use_global_tool_settings:
            self.apply_tool_values(self._project_tool_values)
        else:
            self.apply_tool_values(self.current_tool_values())
        # New independent drafts start with the appropriate source repair policy.
        self.configure_json_repair(settings.get("safe_json_repair") if existing else None)
        self.view.source_layer = settings.get("source_layer", "all")
        self.view.move_related = settings.get("move_related_lines", False)
        self.view.show_walls = settings.get("show_walls", True)
        self.walls_action.setChecked(self.view.show_walls)
        self.restore_alignment_state(settings)
        self.activate_mode(settings.get("mode", "Edit points"), prompt=False)
        self.restore_region_selection(settings)
        if "zoom" in settings:
            self.view.setTransform(QTransform.fromScale(settings["zoom"], settings["zoom"]))
            if not center:
                self.view.centerOn(*settings["center"])
        self.refresh()
        self.selected_regions = settings.get("export_regions")
        self.update_map_info()
        self.update_project_info()
        self.rebuild_dataset_controls()
        self.update_clipboard_actions()
        if center:
            self.view.center_map()

    def export_dataset_to_project(self, catalog, identifier):
        if self.worker:
            return
        selected, _ = QFileDialog.getOpenFileName(
            self,
            self.t("Export dataset to project…"),
            str(self.output_directory or Path.cwd()),
            self.t("DALE projects (*.dale)"),
        )
        if not selected:
            return
        from dale.datasets import append_dataset, copy_session

        destination = Path(selected)
        try:
            was_clean = self.saved_state == self.document_state() if self.view.session else False
            same_project = bool(
                self.project_path and destination.resolve() == self.project_path.resolve()
            )
            new_id, name = append_dataset(
                destination,
                catalog,
                identifier,
                reserved_names=tuple(v.name for v in catalog.views.values())
                if same_project
                else (),
            )
            if same_project:
                view = catalog.views[identifier]
                self.catalog._source_documents = (*self.catalog.documents, *catalog.documents)
                self.catalog.views[new_id] = replace(
                    view,
                    id=new_id,
                    name=name,
                    session=copy_session(view.session),
                    ui=dict(view.ui),
                    json_name=name + ".json" if view.has_json else None,
                    image_name=name + Path(view.filename("image")).suffix
                    if view.has_image
                    else None,
                )
                self.catalog.prepare()
                if catalog is not self.catalog:
                    catalog.views[new_id] = replace(
                        self.catalog.views[new_id],
                        session=copy_session(view.session),
                        ui=dict(view.ui),
                    )
                    catalog.prepare()
                self.rebuild_dataset_controls()
                if was_clean:
                    self.saved_state = self.document_state()
            self.remember_directory("output", destination.resolve().parent)
            self.information("Dataset exported", str(destination))
        except Exception as exc:
            self.warning("Cannot export dataset", str(exc))

    def save_project_file(self, checked=False, save_as=False):
        self.view.finish_rotation()
        if not self.view.session:
            return False
        if self.view.active_gesture:
            self.information("Finish editing", "Finish the active drag before saving.")
            return False
        path = self.project_path
        if path is None or save_as:
            filename = (
                path.name
                if path
                else Path(
                    self.catalog.base_session.source.name
                    if self.catalog
                    else self.view.session.source.name
                )
                .with_suffix(".dale")
                .name
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
                project_ui.update(self._project_tool_values)
            save_project(project_session, path, project_ui, catalog=self.catalog)
            self.remember_directory("output", path.parent)
            self.project_path = path
            self.saved_state = self.document_state()
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
            loaded.catalog = DatasetCatalog.from_catalog(loaded.catalog)
            loaded.session = loaded.catalog.current.session
            loaded.ui_state = loaded.catalog.current.ui
            preview = load_preview(loaded.session.source)
            self.view.safe_json_repair = False
            self.catalog = loaded.catalog
            self.view.assign(loaded.session, preview)
            if self.loaded_project:
                self.loaded_project.close()
            self.loaded_project, loaded = loaded, None
            session, settings = self.loaded_project.session, self.loaded_project.ui_state
            self.configure_json_repair(settings["safe_json_repair"])
            self.view.source_layer = settings["source_layer"]
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
            self.apply_tool_values(active_tool_values)
            self.restore_alignment_state(settings)
            self.walls_action.setChecked(settings["show_walls"])
            self.view.show_walls = settings["show_walls"]
            self.select_tool_set(settings["tool_set"], activate=False)
            self.view.move_related = settings["move_related_lines"]
            self.activate_mode(settings["mode"], prompt=False)
            # Build the saved mode's figure/cell choices before restoring its indices.
            self.selected_regions = settings["export_regions"]
            self.update_map_info()
            self.restore_region_selection(settings)
            self.view.setTransform(QTransform.fromScale(settings["zoom"], settings["zoom"]))
            self.project_path = path
            self.remember_directory("input", path.resolve().parent)
            self.remember_recent_project(path)
            self.saved_state = self.document_state()
            self.rebuild_dataset_controls()
            self.update_project_info()
            self.refresh()
            self.view.center_map()
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

    def save_catalog_json(self, document, project_path):
        selected, _ = QFileDialog.getSaveFileName(
            self,
            self.t("Save JSON…"),
            str((self.output_directory or project_path.parent) / Path(document.name).name),
            self.t("Scene JSON (*.json)"),
        )
        if not selected:
            return
        destination = Path(selected)
        if destination.suffix.lower() != ".json":
            destination = destination.with_name(destination.name + ".json")
        sources = [project_path]
        if self.catalog:
            sources.extend(self.catalog.protected_inputs)
            sources.extend(
                path
                for view in self.catalog.views.values()
                for path in (view.session.source.image_path, view.session.source.json_path)
                if path
            )
        if self.view.session:
            sources.extend(
                p
                for p in (self.view.session.source.image_path, self.view.session.source.json_path)
                if p
            )
        try:
            write_json_copy(document.data, destination, sources)
            self.remember_directory("output", destination.resolve().parent)
        except Exception as exc:
            self.warning("Cannot export scene JSON", str(exc))

    def release_json_workspaces(self, keep_current=False):
        current = self.view.session.source if keep_current and self.view.session else None
        retained = []
        paths = [p for p in (current.image_path, current.json_path) if p] if current else []
        if keep_current and self.catalog:
            paths.extend(item.path for item in self.catalog.images.values() if item.path)
            paths.extend(
                p
                for draft in self.catalog.views.values()
                for p in (draft.session.source.image_path, draft.session.source.json_path)
                if p
            )
        if keep_current:
            worker = self.bounds_preview.worker
            snapshots = [worker.session] if worker and not worker.isFinished() else []
            if self.bounds_preview.pending:
                snapshots.append(self.bounds_preview.pending[1])
            paths.extend(
                snapshot.source.image_path for snapshot in snapshots if snapshot.source.image_path
            )
        for workspace in self.json_workspaces:
            root = Path(workspace.name).resolve()
            if any(path.resolve().is_relative_to(root) for path in paths):
                retained.append(workspace)
            else:
                workspace.cleanup()
        self.json_workspaces = retained

    def load_sources(
        self,
        image_path: Path | None,
        json_path: Path | None,
        remember_input=True,
        *,
        image_name=None,
        json_name=None,
    ):
        try:
            source = load_pair(image_path, json_path)
            source = replace(
                source,
                image_name=image_name or source.image_name,
                json_name=json_name or source.json_name,
            )
            preview = load_preview(source)
            if remember_input:
                self.remember_directory("input", (json_path or image_path).resolve().parent)
            self.view.safe_json_repair = False
            self.view.assign(
                Session(
                    source,
                    gap_tolerance=self.gap_tolerance.value(),
                    contour_offset=self.contour_offset.value(),
                ),
                preview,
            )
            self.catalog = DatasetCatalog(self.view.session)
            self.configure_json_repair()
            self._project_tool_values = self.current_tool_values()
            self.origin_x.setValue(0)
            self.origin_y.setValue(0)
            self.refresh()
            if self.loaded_project and not any(
                p.is_relative_to(Path(self.loaded_project.workspace.name).resolve())
                for p in (source.image_path, source.json_path)
                if p
            ):
                self.loaded_project.close()
                self.loaded_project = None
            self.project_path = None
            self.update_project_info()
            self.catalog.capture(self.project_ui_state())
            self.rebuild_dataset_controls()
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
        self.view.property_documents = self.catalog.documents if self.catalog else ()
        self.update_clipboard_actions()
        self.view.refresh()
        self.rebuild_source_layers()
        self.update_map_info()
        if self.view.session and self.view.safe_json_repair and self.current_tool_set != "figures":
            self.diagnostics.setText(
                self.t(
                    "Editing operations: {operations}", operations=len(self.view.session.operations)
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
        self.view.finish_rotation()
        if self.current_tool_set == "figures":
            data = self.region_control.itemData(index)
            self.view.figure_line_ids = tuple(data or ())
            self.view.figure_pivot = None
            self.update_map_info()
            return
        self.view.detached_selection = None
        data = self.region_control.itemData(index)
        self.selected_regions = None if data is None else tuple(data)
        self.view.region_pivot = None
        self.update_map_info()

    def toggle_region_at(self, point):
        if self.view.detached_selection:
            self.view.detached_selection = None
            self.selected_regions = ()
            self.update_map_info()
        self.view.region_pivot = None
        hit = min(
            (i for i, polygon in enumerate(self.regions) if polygon.covers(ShapePoint(point))),
            key=lambda i: self.regions[i].area,
            default=None,
        )
        selected = set(self.selected_regions or ())
        if hit is None:
            self.clear_selection()
            return
        elif hit in selected:
            selected.remove(hit)
        else:
            selected.add(hit)
        self.selected_regions = tuple(sorted(selected))
        self.update_map_info()

    def available_regions(self):
        return self.view.selectable_regions()

    def select_figure_at(self, event):
        point = ShapePoint(event["point"])
        components = self.view.contour_figures()
        candidates = [
            (LineString(edge).distance(point), line_id, component)
            for component in components
            for edge, line_id in zip(component.edges, component.line_ids, strict=True)
        ]
        first = event.get("first_click") if event.get("double") else None
        hit = (
            next(
                (
                    (0, line_id, component)
                    for _, line_id, component in candidates
                    if line_id == first["target"]
                ),
                None,
            )
            if first is not None
            else min(candidates, key=lambda item: item[0], default=None)
        )
        before = self.view.figure_line_ids
        tolerance = 6 / max(self.view.transform().m11(), 1e-9)
        if not hit or hit[0] > tolerance:
            self.clear_selection()
            if event.get("mouse"):
                self.view.remember_figure_click(event["point"], None, before)
            return
        selected = set(first["before"] if first is not None else before)
        if event.get("double"):
            selected.update(hit[2].line_ids)
        elif hit[1] in selected:
            selected.remove(hit[1])
        else:
            selected.add(hit[1])
        self.view.figure_line_ids = tuple(sorted(selected))
        self.view.figure_pivot = None
        self.update_map_info()
        if event.get("mouse"):
            self.view.remember_figure_click(event["point"], hit[1], before)

    def select_figures_in_box(self, event):
        phase = event["phase"]
        if phase == "begin":
            self.figure_marquee = self.view.figure_line_ids, self.view.figure_pivot
        elif self.figure_marquee is not None:
            if phase == "cancel":
                self.view.figure_line_ids, self.view.figure_pivot = self.figure_marquee
                self.figure_marquee = None
            elif phase == "preview":
                x0, y0, x1, y1 = event["bounds"]
                rectangle = box(x0, y0, x1, y1)
                hits = {
                    line_id
                    for component in self.view.contour_figures()
                    for line_id, edge in zip(component.line_ids, component.edges, strict=True)
                    if x1 > x0 and y1 > y0 and LineString(edge).intersects(rectangle)
                }
                self.view.figure_line_ids = tuple(sorted(set(self.figure_marquee[0]) ^ hits))
                self.view.figure_pivot = None
            else:
                self.figure_marquee = None
        self.update_map_info()

    def select_regions_in_box(self, event):
        if self.current_tool_set == "figures":
            self.select_figures_in_box(event)
            return
        phase = event["phase"]
        if phase == "begin":
            self.marquee_selection = {
                "selected": self.selected_regions,
                "detached": self.view.detached_selection,
                "pivot": self.view.region_pivot,
                "key": self.region_key,
                "polygons": None,
            }
            self.update_clipboard_actions()
            return
        original = self.marquee_selection
        if not original:
            return
        if phase == "cancel":
            self.view.detached_selection = original["detached"]
            self.view.region_pivot = original["pivot"]
            self.region_key = original["key"]
            self.selected_regions = original["selected"]
            self.marquee_selection = None
            self.update_map_info()
        elif phase == "preview":
            if original["polygons"] is None:
                if self.view.detached_selection:
                    area = unary_union(self.view.region_polygons)
                    self.view.detached_selection = None
                    polygons = self.available_regions()
                    original["base"] = tuple(
                        i for i, p in enumerate(polygons) if area.covers(p.representative_point())
                    )
                    self.region_key = tuple(p.wkb for p in polygons)
                else:
                    polygons = self.regions
                    original["base"] = tuple(original["selected"] or ())
                original["polygons"] = tuple(polygons)
            self.selected_regions = invert_regions_in_box(
                original["polygons"], original["base"], event["bounds"]
            )
            self.view.region_pivot = self.view.region_anchor = None
            self.update_map_info()
        else:
            self.marquee_selection = None
            self.update_clipboard_actions()

    def select_transformed_regions(self, result):
        if self.current_tool_set == "figures":
            self.view.figure_line_ids = tuple(result.get("line_ids", ()))
            self.view.figure_pivot = result["pivot"]
            self.update_map_info()
            return
        polygons = result["polygons"]
        self.view.detached_selection = {
            "geometry": self.view.session.geometry(),
            "polygons": polygons,
            "line_ids": result.get("line_ids", ()),
        }
        self.selected_regions = tuple(range(len(polygons)))
        self.update_map_info()
        self.view.region_pivot = result["pivot"]

    def restore_region_selection(self, settings):
        from shapely import from_wkb

        live = {r.id for r in self.view.session.geometry().lineage}
        self.view.figure_line_ids = tuple(i for i in settings.get("figure_lines", ()) if i in live)
        pivot = settings.get("figure_pivot")
        self.view.figure_pivot = tuple(pivot) if pivot is not None else None

        selection = settings.get("detached_region_selection")
        if selection and set(selection["lines"]).issubset(
            {r.id for r in self.view.session.geometry().lineage}
        ):
            polygons = tuple(from_wkb(bytes.fromhex(p)) for p in selection["polygons"])
            self.view.detached_selection = {
                "geometry": self.view.session.geometry(),
                "polygons": polygons,
                "line_ids": tuple(selection["lines"]),
            }
            self.selected_regions = tuple(range(len(polygons)))
            self.view.region_pivot = tuple(selection["pivot"])
            self.update_map_info()
        if self.current_tool_set == "figures":
            self.update_map_info()

    def update_figure_info(self):
        session = self.view.session
        components = self.view.contour_figures()
        live = {i for component in components for i in component.line_ids}
        self.view.figure_line_ids = tuple(i for i in self.view.figure_line_ids if i in live)
        self.view.selected_path = self.view.figure_path()
        self.regions_group.setTitle(self.t("Contours"))
        self.region_control.setToolTip(
            self.t("Choose a connected contour or all contour lines to select.")
        )
        self.region_control.blockSignals(True)
        self.region_control.clear()
        self.region_control.addItem(self.t("No selected contours"), ())
        self.region_control.addItem(self.t("All contours"), tuple(sorted(live)))
        for i, component in enumerate(components):
            self.region_control.addItem(
                self.t("Contour {number}", number=i + 1), component.line_ids
            )
        if self.view.figure_line_ids:
            self.region_control.addItem(
                self.t("Selected lines: {count}", count=len(self.view.figure_line_ids)),
                self.view.figure_line_ids,
            )
            self.region_control.setCurrentIndex(self.region_control.count() - 1)
        self.region_control.setEnabled(bool(components))
        self.region_control.blockSignals(False)
        self.diagnostics.setText(
            self.t(
                "Contour groups: {groups}\nSelected lines: {lines}",
                groups=len(components),
                lines=len(self.view.figure_line_ids),
            )
        )
        self.update_clipboard_actions()
        if not session or not session.source.image_path:
            self.bounds_preview.clear()
            self.map_info.setText(self.t("No image"))
            self.view.viewport().update()
            return
        try:
            selected = export_regions(session)
        except ValueError:
            selected = ()
        self.update_png_info(session, selected)

    def update_map_info(self):
        if self.current_tool_set == "figures":
            self.update_figure_info()
            return
        self.region_control.setToolTip(
            self.t("Choose all closed regions or one region to highlight and export.")
        )
        self.update_clipboard_actions()
        session = self.view.session
        if (
            session
            and session.source.image_path is None
            and self.view.mode not in AREA_TOOLS
            and self.current_tool_set not in ("regions", "figures")
        ):
            self.bounds_preview.clear()
            self.regions, self.selected_regions = (), None
            self.view.selected_path = QPainterPath()
            self.region_control.clear()
            self.region_control.setEnabled(False)
            layers, ambiguous = infer_layers(
                session.source, session.geometry(), self.view.property_documents
            )
            self.map_info.setText(
                self.t(
                    "Original contours: {count}\nNew contours: {added}\n"
                    "Visible contours: {visible}\nHeight bands: {layers}\n"
                    "Ambiguous heights: {ambiguous}",
                    count=len(session.source.raw.get("walls", ())),
                    added=len(getattr(session.geometry(), "additions", ())),
                    visible=len(self.view.walls),
                    layers=len(layers),
                    ambiguous=len(ambiguous),
                )
            )
            return
        if session:
            try:
                regions = self.available_regions()
            except ValueError:
                regions = ()
        else:
            regions = ()
        key = tuple(polygon.wkb for polygon in regions)
        detached = self.view.detached_selection
        if detached and session and detached["geometry"] == session.geometry():
            regions = detached["polygons"]
            self.selected_regions = tuple(range(len(regions)))
        else:
            self.view.detached_selection = None
        if not self.view.detached_selection and key != self.region_key:
            self.selected_regions = () if self.view.mode in AREA_TOOLS else None
            self.view.region_pivot = None
            self.region_key = key
        self.regions = regions
        if self.selected_regions is not None:
            self.selected_regions = tuple(i for i in self.selected_regions if 0 <= i < len(regions))
        self.view.region_polygons = tuple(regions[i] for i in self.selected_regions or ())
        self.update_clipboard_actions()
        self.region_control.blockSignals(True)
        self.regions_group.setTitle(self.t("Regions"))
        self.region_control.clear()
        self.region_control.addItem(self.t("All regions"), None)
        for index in range(len(regions)):
            self.region_control.addItem(
                self.t("Region {number}", number=index + 1),
                (index,),
            )
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
            # Consistent ring winding preserves holes in detached selections.
            polygon = orient(regions[index], sign=1.0)
            for ring in (polygon.exterior, *polygon.interiors):
                coordinates = list(ring.coords)
                self.view.selected_path.moveTo(*coordinates[0])
                for point in coordinates[1:]:
                    self.view.selected_path.lineTo(*point)
                self.view.selected_path.closeSubpath()
        self.view.selected_path.setFillRule(Qt.FillRule.WindingFill)
        if session and not self.view.safe_json_repair:
            self.diagnostics.setText(
                self.t(
                    "Selectable cells: {cells}\nEditing operations: {operations}",
                    cells=len(regions),
                    operations=len(session.operations),
                )
            )
        if not session:
            self.bounds_preview.clear()
            self.map_info.setText(self.t("Scene image: not loaded\nClosed: 0 | Open: 0"))
            return
        if session.source.image_path is None:
            self.bounds_preview.clear()
            self.map_info.setText(self.t("No image"))
            return
        try:
            selected = (
                export_regions(session)
                if self.selected_regions is None and regions
                else tuple(
                    polygon
                    for _, polygon in selected_export_regions(
                        (regions[i] for i in self.selected_regions or ()),
                        session.contour_offset,
                        merge_adjacent=self.merge_selected_regions,
                    )
                )
            )
        except ValueError:
            selected = ()
        self.update_png_info(session, selected)

    def update_png_info(self, session, selected):
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
        if (
            not self.view.session
            or not self.view.session.source.image_path
            or not self.view.region_polygons
            or self.view.active_gesture
            or self.worker
            or self.current_tool_set == "figures"
        ):
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
            operation = self.view.session.make_mask(mode, unary_union(self.view.region_polygons))
        except ValueError as exc:
            self.information("Review contour offset", str(exc))
            return
        self.view.session.add(operation)
        self.refresh()

    def export(self, selected_only=False):
        self.view.finish_rotation()
        if not self.view.session or self.worker:
            return
        if self.view.session.source.image_path is None:
            self.information(
                "PNG export", "Disable JSON repair and open a scene image for PNG export."
            )
            return
        if self.view.active_gesture:
            self.information("Finish editing", "Finish or cancel the active gesture first.")
            return
        selection = None if self.current_tool_set == "figures" else self.selected_regions
        if selection == () or (selected_only and selection is None):
            self.activate_mode("Select regions")
            self.information(
                "Select regions", "Select at least one closed region on the scene image."
            )
            return
        merge_adjacent = False
        if selection is not None:
            merge_adjacent = self.confirm_merge_selected_regions()
            if merge_adjacent is None:
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
            self,
            selection,
            selected_polygons=(
                tuple(self.regions[i] for i in selection) if selection is not None else None
            ),
            merge_adjacent=merge_adjacent,
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
    if options.project and options.image:
        parser.error("Open a project or an image pair, not both.")
    app = QApplication([sys.argv[0]])
    configure_application(app)
    window = MainWindow()
    window.show()
    if options.image or options.scene:
        window.load_sources(options.image, options.scene)
    elif options.project:
        if options.project.suffix.lower() == ".json":
            window.load_sources(None, options.project)
        else:
            window.load_project_file(options.project)
    if options.smoke_report:

        def smoke_report():
            raster_preview = (
                window.view.item.pixmap().toImage() if window.view.item is not None else None
            )
            report = {
                "version": __version__,
                "window_title": window.windowTitle(),
                "window_icon_loaded": not window.windowIcon().isNull(),
                "geometry_eraser_diameters": window.view.geometry_diameters,
                "auto_close_distance_px": window.view.auto_close_distance,
                "global_close_distance_px": window.global_close_control.value(),
                "tool_set": window.current_tool_set,
                "section_names": {
                    key: action.text() for key, action in window.tool_set_actions.items()
                },
                "show_walls": window.view.show_walls,
                "selected_regions": window.selected_regions,
                "region_choices": {
                    "kind": "cells",
                    "count": len(window.available_regions()),
                    "max_area": max((p.area for p in window.available_regions()), default=0),
                    "selected_holes": sum(len(p.interiors) for p in window.view.region_polygons),
                },
                "figures": {
                    "groups": len(window.view.contour_figures()),
                    "selected_lines": list(window.view.figure_line_ids),
                    "selected_edges": window.view.selected_figure_edges(),
                    "pivot": window.view.figure_pivot,
                    "buttons": [
                        command.property("dale_tool_key")
                        for command in window.figure_toolbar.actions()
                    ],
                    "alignment": {
                        title: {
                            "checked": command.isChecked(),
                            "size": [
                                window.sized_tools[title].width(),
                                window.sized_tools[title].height(),
                            ],
                            "tooltip": command.toolTip(),
                        }
                        for title, command in window.figure_alignment_actions.items()
                    },
                },
                "select_all": {
                    "text": window.select_all_action.text(),
                    "enabled": window.select_all_action.isEnabled(),
                    "shortcut": window.select_all_action.shortcut().toString(),
                    "main_order": [
                        command.property("dale_tool_key")
                        for command in window.basic_toolbar.actions()
                    ],
                    "size": [
                        window.basic_toolbar.widgetForAction(window.select_all_action).width(),
                        window.basic_toolbar.widgetForAction(window.select_all_action).height(),
                    ],
                    "visible": window.basic_toolbar.widgetForAction(
                        window.select_all_action
                    ).isVisible(),
                },
                "artwork_offset_px": window.contour_offset.value(),
                "selected_region_export": {
                    "remembered_merge": window.remembered_merge_selected_regions,
                    "merge": window.merge_selected_regions,
                    "right_click": window.export_regions_button.contextMenuPolicy()
                    == Qt.ContextMenuPolicy.CustomContextMenu,
                    "tooltip": window.export_regions_action.toolTip(),
                },
                "global_tool_settings": window.global_tools_control.isChecked(),
                "tool_values": window.current_tool_values(),
                "alignment_enabled": {
                    key: getattr(window.view, key) for key in window.alignment_actions
                },
                "section_alignment": window.alignment_ui_state(),
                "effective_snapping": window.view.snap_enabled,
                "mode_help": window.mode_help.text(),
                "raster_diameters": window.view.raster_diameters,
                "move_related_lines": window.view.move_related,
                "contour_connections": {
                    "choices": window.connection_choices,
                    "groups": {
                        record.id: record.connection_group
                        for record in window.view.session.geometry().lineage
                        if record.connection_group is not None
                    }
                    if window.view.session
                    else {},
                    "right_click": {
                        tool: button.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
                        for tool, button in (
                            (
                                "Edit points",
                                window.geometry_toolbar.widgetForAction(
                                    window.mode_actions["Edit points"]
                                ),
                            ),
                            ("Erase lines", window.geometry_eraser_tiles["Erase lines"]),
                        )
                    },
                },
                "project_schema_version": SCHEMA_VERSION,
                "safe_json_repair": window.view.safe_json_repair,
                "source_layer": window.view.source_layer,
                "height_layer_choices": [
                    window.layer_control.itemData(i) for i in range(window.layer_control.count())
                ],
                "visible_contours": len(window.view.walls),
                "manual_contour_tools_enabled": all(
                    window.mode_actions[key].isEnabled() for key in ("Edit points", "New line")
                ),
                "lineage_edges": len(window.view.session.geometry().lineage)
                if window.view.session
                else 0,
                "dataset": {
                    "name": window.catalog.name if window.catalog else None,
                    "active": window.catalog.active_key if window.catalog else None,
                    "base": window.catalog.base_key if window.catalog else None,
                    "choices": window.dataset_control.count(),
                    "drafts": len(window.catalog.views) if window.catalog else 0,
                    "manager_button_size": [
                        window.manager_button.width(),
                        window.manager_button.height(),
                    ],
                    "manager_left": window.manager_button.x() < window.dataset_control.x(),
                    "selector_size": [
                        window.dataset_control.width(),
                        window.dataset_control.height(),
                    ],
                    "selector_button_gap": window.dataset_control.x()
                    - window.manager_button.x()
                    - window.manager_button.width(),
                    "heading_text_inset": window.dataset_heading.x()
                    + window.dataset_heading.contentsRect().x(),
                    "names": [v.name for v in window.catalog.views.values()]
                    if window.catalog
                    else [],
                    "rectangle_available": window.mode_actions["New rectangle"].isEnabled(),
                },
                "json_document_count": int(window.view.session.source.json_path is not None)
                + len(window.view.session.json_documents)
                if window.view.session
                else 0,
                "json_export": {
                    "text": window.export_json_action.text(),
                    "enabled": window.export_json_action.isEnabled(),
                    "shortcut": window.export_json_action.shortcut().toString(),
                },
                "delete_region": {
                    "text": window.delete_regions_action.text(),
                    "enabled": window.delete_regions_action.isEnabled(),
                    "shortcut": window.delete_regions_action.shortcut().toString(),
                    "help": window.delete_regions_action.toolTip(),
                    "size": [
                        window.toolbars[4].widgetForAction(window.delete_regions_action).width(),
                        window.toolbars[4].widgetForAction(window.delete_regions_action).height(),
                    ],
                },
                "delete_contours": {
                    "text": window.delete_contours_action.text(),
                    "enabled": window.delete_contours_action.isEnabled(),
                    "shortcut": window.delete_contours_action.shortcut().toString(),
                    "help": window.delete_contours_action.toolTip(),
                },
                "raster_selection": {
                    "text": window.mode_actions["Select raster regions"].text(),
                    "help": window.mode_actions["Select raster regions"].toolTip(),
                    "enabled": window.mode_actions["Select raster regions"].isEnabled(),
                    "first": window.toolbars[5].actions()[0]
                    == window.mode_actions["Select raster regions"],
                    "size": [
                        window.toolbars[5]
                        .widgetForAction(window.mode_actions["Select raster regions"])
                        .width(),
                        window.toolbars[5]
                        .widgetForAction(window.mode_actions["Select raster regions"])
                        .height(),
                    ],
                    "mask_commands": {
                        key: {
                            "text": item.text(),
                            "enabled": item.isEnabled(),
                            "help": item.toolTip(),
                        }
                        for key, item in window.mask_actions.items()
                    },
                    "selected_area": sum(p.area for p in window.view.region_polygons),
                    "preview_sha256": hashlib.sha256(raster_preview.constBits()).hexdigest()
                    if raster_preview is not None and not raster_preview.isNull()
                    else None,
                },
                "button_help": {
                    "right_angle": window.sized_tools["Right-angle alignment"].toolTip(),
                    "right_angle_value": window.right_angle_distance.toolTip(),
                    "contour_alignment": window.sized_tools["Contour alignment"].toolTip(),
                    "export_png": window.export_action.toolTip(),
                    "edit_points": window.mode_actions["Edit points"].toolTip(),
                    "erase_lines": window.geometry_eraser_tiles["Erase lines"].toolTip(),
                },
                "camera": {
                    "center_error_pixels": (
                        window.view.mapFromScene(window.view.image_rect.center())
                        - window.view.viewport().rect().center()
                    ).manhattanLength(),
                    "zoom": window.view.transform().m11(),
                }
                if window.view.session
                else None,
                "geometry_erasers_enabled": all(
                    window.mode_actions[key].isEnabled() for key in GEOMETRY_ERASERS
                ),
                "editing_mode": window.view.mode,
                "language": window.language,
                "right_panel_visible": window.right_panel_visible,
                "sidebar_toggle_size": [
                    window.sidebar_toggle.width(),
                    window.sidebar_toggle.height(),
                ],
                "information_height": window.information_group.height(),
                "information_scroll_maximum": window.information_group.findChild(QScrollArea)
                .verticalScrollBar()
                .maximum(),
                "window_visible": window.isVisible(),
                "minimum_window": [window.minimumWidth(), window.minimumHeight()],
                "map_info": window.map_info.text(),
                "footer_visible": window.statusBar().isVisible(),
                "project_loaded": bool(window.project_path),
                "dimensions": window.view.session.source.size if window.view.session else None,
                "operations": len(window.view.session.operations) if window.view.session else 0,
                "region_alignment": {
                    title: {
                        "checked": item.isChecked(),
                        "size": [
                            window.sized_tools[title].width(),
                            window.sized_tools[title].height(),
                        ],
                        "value": window.sized_tools[title].editor().value(),
                        "help": window.sized_tools[title].toolTip(),
                    }
                    for title, item in window.region_alignment_actions.items()
                },
                "detached_region_selection": [
                    {"area": p.area, "bounds": p.bounds} for p in window.view.region_polygons
                ]
                if window.view.detached_selection
                else [],
            }
            if window.view.session and window.view.session.source.json_bytes is not None:
                from dale.json_repair import JsonCoordinateDocument

                session = replace(window.view.session, json_documents=window.catalog.documents)
                payload, _ = repaired_json_bytes(session)
                original = JsonCoordinateDocument(session.source.json_bytes)
                updated = JsonCoordinateDocument(payload)
                report["native_export"] = {
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "walls": len(updated.raw["walls"]),
                    "other_bytes_preserved": (
                        original.text[: original.walls_start] == updated.text[: updated.walls_start]
                        and original.text[original.walls_end + 1 :]
                        == updated.text[updated.walls_end + 1 :]
                    ),
                }
            from dale.dataset_manager import DatasetManager

            manager = DatasetManager(window)
            manager.show()
            QApplication.processEvents()
            load, send, remove = manager.component_buttons["json"]
            report["dataset_manager"] = {
                "tree_width": manager.tree.width(),
                "header_buttons": [manager.new_button.text(), manager.delete_button.text()],
                "header_button_heights": [
                    manager.new_button.height(),
                    manager.delete_button.height(),
                ],
                "standard_button_height": manager.apply_button.height(),
                "json_actions": [
                    button.text() for button in (load, manager.add_json_button, send, remove)
                ],
                "merge_enabled": manager.add_json_button.isEnabled(),
                "merge_help": manager.add_json_button.toolTip(),
                "status_footer_center": manager.status.geometry().center().y(),
                "open_footer_center": manager.open_button.geometry().center().y(),
            }
            manager.grab().save(
                str(options.smoke_report.with_name(options.smoke_report.stem + "-manager.png"))
            )
            manager.close()
            manager.deleteLater()
            options.smoke_report.write_text(json.dumps(report), encoding="utf-8")
            window.grab().save(str(options.smoke_report.with_suffix(".png")))
            window.windowIcon().pixmap(256, 256).save(
                str(options.smoke_report.with_name(options.smoke_report.stem + "-icon.png"))
            )
            app.quit()

        QTimer.singleShot(500, smoke_report)
    sys.exit(app.exec())
