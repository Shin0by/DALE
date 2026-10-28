"""Local desktop workflow, controls, and export worker lifecycle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
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
    QColorDialog,
    QComboBox,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)
from shapely.geometry import LineString, box
from shapely.geometry import Point as ShapePoint
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

from dale import __version__, application_title
from dale.alchemist_ui import AlchemistUI
from dale.bounds_preview import BoundsPreview
from dale.canvas import (
    AREA_TOOLS,
    FIGURE_TOOLS,
    GEOMETRY_ERASERS,
    MOVE_TOOLS,
    RASTER_TRANSFORM_TOOLS,
    REGION_TOOLS,
    ROTATE_TOOLS,
    SELECTION_TOOLS,
    TRANSFORM_TOOLS,
    MapView,
    polygon_path,
)
from dale.datasets import DatasetCatalog
from dale.export_directory import choose_export_directory
from dale.export_grid import export_grid
from dale.export_names import export_family, group_export_stem, selection_number
from dale.geometry import invert_regions_in_box, open_contour_count
from dale.group_manager import GroupManager
from dale.json_repair import repaired_json_bytes, write_json_copy
from dale.layer_repair import infer_layers
from dale.localization import (
    DesktopTranslator,
    format_tooltip,
    prepare_control_tooltips,
    translate,
    translate_static,
)
from dale.measurement import measurement_scale
from dale.overlay_export import (
    export_group_matches,
    export_overlays,
    export_regions,
    overlay_region_plan,
    selected_export_regions,
    shared_export_group,
)
from dale.preferences import (
    ROTATION_VALUE_RANGES,
    TOOL_VALUE_RANGES,
    load_alchemist_export,
    load_connection_choice,
    load_directory,
    load_export_group_naming,
    load_global_tool_settings,
    load_height_normalization,
    load_include_json,
    load_include_png,
    load_language,
    load_merge_export_contours,
    load_merge_selected_regions,
    load_move_related,
    load_project_dataset,
    load_recent_projects,
    load_right_panel_visible,
    load_size_to_grid,
    load_tool_values,
    save_alchemist_export,
    save_connection_choice,
    save_directory,
    save_export_group_naming,
    save_global_tool_settings,
    save_height_normalization,
    save_include_json,
    save_include_png,
    save_language,
    save_merge_export_contours,
    save_merge_selected_regions,
    save_project_dataset,
    save_recent_projects,
    save_right_panel_visible,
    save_size_to_grid,
    save_tool_value,
    settings_path,
)
from dale.project_io import (
    DEFAULT_CUSTOM_COLORS,
    SCHEMA_VERSION,
    JsonDocument,
    current_contours_document,
    load_project,
    save_project,
)
from dale.provenance import geometry_edges
from dale.raster import ExportCancelled, load_preview
from dale.raster_brush import RASTER_BRUSHES, brush_settings
from dale.region_groups import assign_region_cells, matched_cells
from dale.region_transform import delete_figures, delete_regions
from dale.registration import register_current_product
from dale.scene import load_pair
from dale.selection_groups import (
    SelectionGroup,
    assign_group,
    boundary_members,
    decode_groups,
    group_members,
    group_ui_state,
)
from dale.session import RasterSelectionEdit, RegionSelection, Session
from dale.tool_settings import ToolSettingsDialog
from dale.toolbar import (
    ModeTabButton,
    SizedToolButton,
    ToolSettingsCorner,
    ToolSpinBox,
    apply_theme,
    make_toolbar,
    tool_icon,
)


class ExportWorker(QThread):
    progress = Signal(int)
    outcome = Signal(str, str)
    file_conflict = Signal(object)

    def __init__(
        self,
        session,
        path,
        parent,
        region_indices=None,
        selected_polygons=None,
        merge_adjacent=False,
        size_to_grid=False,
        grid_size=None,
        include_json=True,
        include_png=True,
        export_groups=(),
        active_group=None,
        merge_contours=False,
    ):
        super().__init__(parent)
        self.source = session.source
        self.operations = tuple(session.operations)
        self.path = path
        self.region_indices = tuple(region_indices) if region_indices is not None else None
        self.selected_polygons = tuple(selected_polygons) if selected_polygons is not None else None
        self.merge_adjacent = merge_adjacent
        self.merge_contours = merge_contours
        self.size_to_grid = size_to_grid
        self.grid_size = grid_size
        self.include_json = include_json
        self.include_png = include_png
        self.json_contours = parent.json_contours
        self.height_normalization = parent.height_normalization
        self.export_groups = tuple(export_groups)
        self.active_group = active_group
        from threading import Event

        self.conflict_event = Event()
        self.conflict_answer = None
        self.protected_sources = [parent.project_path] if parent.project_path else []
        if parent.catalog:
            self.protected_sources.extend(parent.catalog.protected_inputs)
            self.protected_sources.extend(image.path for image in parent.catalog.images.values())
            self.protected_sources.extend(
                path
                for draft in parent.catalog.views.values()
                for path in (draft.session.source.image_path, draft.session.source.json_path)
                if path
            )
        self.export_name = parent.catalog.name if parent.catalog else None
        self.session = Session(
            session.source,
            session.origin,
            list(session.operations),
            alchemist=session.alchemist,
            gap_tolerance=session.gap_tolerance,
            contour_offset=session.contour_offset,
            json_documents=tuple(
                parent.catalog.documents if parent.catalog else session.json_documents
            ),
        )

    def run(self):
        try:
            destination = export_overlays(
                self.session,
                self.path.parent,
                self.progress.emit,
                self.isInterruptionRequested,
                region_indices=self.region_indices,
                individual_regions=self.region_indices is not None,
                export_name=self.export_name,
                selected_polygons=self.selected_polygons,
                merge_adjacent=self.merge_adjacent,
                merge_contours=self.merge_contours,
                size_to_grid=self.size_to_grid,
                grid_size=self.grid_size,
                target_directory=self.path,
                conflict=self.resolve_file_conflict,
                protected_sources=tuple(self.protected_sources),
                include_json=self.include_json,
                include_png=self.include_png,
                json_contours=self.json_contours,
                height_normalization=self.height_normalization,
                export_groups=self.export_groups,
                active_group=self.active_group,
            )
            self.outcome.emit("success", str(destination))
        except ExportCancelled:
            self.outcome.emit("cancelled", "PNG export cancelled; destination unchanged.")
        except Exception as exc:
            self.outcome.emit("error", str(exc))

    def resolve_file_conflict(self, path):
        self.conflict_answer = None
        self.conflict_event.clear()
        self.file_conflict.emit(path)
        while not self.conflict_event.wait(0.05):
            if self.isInterruptionRequested():
                return None
        return self.conflict_answer


class ApplicationContourClipboard(QObject):
    """One immutable outline/source snapshot shared by all windows in this process."""

    changed = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.content = None

    def store(self, contours, source, documents, section):
        self.content = contours, source, documents, section
        self.changed.emit()


class MainWindow(AlchemistUI, QMainWindow):
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
        self.merge_export_contours = load_merge_export_contours(self.preferences_path)
        self.merge_selected_regions = (
            self.remembered_merge_selected_regions is True or self.merge_export_contours
        )
        self.size_to_grid = load_size_to_grid(self.preferences_path)
        self.json_contours = load_alchemist_export(self.preferences_path)
        self.height_normalization = load_height_normalization(self.preferences_path)
        self.include_json = load_include_json(self.preferences_path)
        self.include_png = load_include_png(self.preferences_path)
        if not self.include_json and not self.include_png:
            self.include_png = True
        self.export_group_naming = load_export_group_naming(self.preferences_path)
        self.connection_choices = {
            tool: load_connection_choice(self.preferences_path, tool)
            for tool in ("Erase lines", "Edit points")
        }
        self.input_directory = load_directory(self.preferences_path, "input")
        self.output_directory = load_directory(self.preferences_path, "output")
        self.recent_projects = load_recent_projects(self.preferences_path)
        self.setWindowTitle(application_title())
        self.resize(1280, 860)
        self.setMinimumSize(1024, 768)
        self.worker = None
        self.tool_settings_popup = None
        self.group_manager = None
        self._groups_value = None
        self._groups_cache = ()
        self._group_render_cache = None
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
        self.custom_colors = DEFAULT_CUSTOM_COLORS
        self.regions = ()
        self.region_key = None
        self.selected_region = None
        self.marquee_selection = None
        self.figure_marquee = None
        self.current_tool_set = "geometry"
        self._region_selection_states = {}
        self._region_selection_section = "regions"
        self.last_tool_modes = {
            "geometry": "Edit points",
            "figures": "Select figures",
            "regions": "Select regions",
            "pixels": "Select raster regions",
        }
        self.view = MapView()
        self.view.raster_aids.changed.connect(self.sync_raster_aids)
        self.view.native_preview.failed.connect(self.native_preview_failed)
        QApplication.instance().aboutToQuit.connect(self.view.native_preview.shutdown)
        self.view.group_overlay = self.group_overlay
        self.view.connection_prompt = self.confirm_contour_connection
        self.view.move_related = self.remembered_move_related is True
        self.view.changed.connect(self.refresh_geometry_edit)
        self.view.auto_close_requested.connect(self.confirm_auto_close)
        self.view.region_clicked.connect(self.toggle_region_at)
        self.view.figure_clicked.connect(self.select_figure_at)
        self.view.region_box_selected.connect(self.select_regions_in_box)
        self.view.regions_transformed.connect(self.select_transformed_regions)
        self.view.alchemist_parameters_changed.connect(
            lambda args: self.remember_alchemist_parameters(*args)
        )
        self.view.clipboard_changed.connect(self.capture_contour_clipboard)
        self.view.paste_committed.connect(self.retain_clipboard_sources)
        self._clipboard_documents = ()
        self._clipboard_section = "regions"
        app = QApplication.instance()
        if not hasattr(app, "_dale_contour_clipboard"):
            app._dale_contour_clipboard = ApplicationContourClipboard(app)
        self.contour_clipboard = app._dale_contour_clipboard
        self.contour_clipboard.changed.connect(self.restore_contour_clipboard)
        self._clipboard_connected = True
        self.restore_contour_clipboard()
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
        self.raster_contour_offset = ToolSpinBox(self)
        self.raster_contour_offset.setRange(-4096, 4096)
        self.raster_contour_offset.hide()
        self.raster_contour_offset.valueChanged.connect(self.set_raster_offset)
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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        left_panel = QWidget()
        self.left_panel = left_panel
        left_panel.setFixedWidth(60)
        self.tool_column = QVBoxLayout(left_panel)
        self.tool_column.setContentsMargins(0, 0, 0, 0)
        self.tool_column.setSpacing(4)
        self.tool_stack = QStackedWidget()
        self.tool_stack.setFixedWidth(60)
        self.tool_stack.setStyleSheet("QStackedWidget { background: transparent; border: 0; }")
        self.tool_scroll = QScrollArea()
        self.tool_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.tool_scroll.setWidgetResizable(True)
        self.tool_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tool_scroll.setStyleSheet("QScrollBar:vertical { width: 10px; }")
        self.tool_scroll.verticalScrollBar().rangeChanged.connect(
            lambda low, high: left_panel.setFixedWidth(60 + (10 if high > low else 0))
        )
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
            (self.file_menu, "Create, open, save, export regions, close, and exit."),
            (self.edit_menu, "Undo, redo, and clear selection."),
            (self.about_menu, "Application name, version, and purpose."),
        ):
            menu.setToolTipsVisible(True)
            menu.setToolTip(tip)
        categories = make_toolbar(self, "Modes")
        self.tool_set_toolbar = categories
        self.basic_toolbar = make_toolbar(self, "Main")
        self.view_toolbar = make_toolbar(self, "View")
        self.groups_toolbar = make_toolbar(self, "Groups")
        self.group_heading = self.groups_toolbar.findChild(QLabel)
        self.group_manager_button = QToolButton(self.groups_toolbar)
        self.group_manager_button.setIcon(tool_icon("Group manager"))
        self.group_manager_button.setIconSize(QSize(22, 22))
        self.group_manager_button.setFixedSize(36, 36)
        self.group_manager_button.setCheckable(True)
        self.group_manager_button.clicked.connect(self.toggle_group_manager)
        self.groups_toolbar.addWidget(self.group_manager_button)
        self.group_control = QComboBox(self.groups_toolbar)
        self.group_control.setFixedHeight(36)
        self.group_control.setMinimumWidth(100)
        self.group_control.setMaximumWidth(140)
        self.group_control.setMinimumContentsLength(8)
        self.group_control.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.group_control.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.group_control.activated.connect(self.choose_selection_group)
        self.groups_toolbar.addWidget(self.group_control)
        self.dataset_toolbar = make_toolbar(self, "Dataset")
        self.dataset_heading = self.dataset_toolbar.findChild(QLabel)
        self.dataset_control = QComboBox()
        self.dataset_control.setFixedHeight(36)
        self.dataset_control.setMinimumWidth(120)
        self.dataset_control.setMaximumWidth(230)
        self.dataset_control.setMinimumContentsLength(12)
        self.dataset_control.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.dataset_control.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
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
        self.region_output_toolbar = make_toolbar(self, "Region output", vertical=True)
        self.raster_output_toolbar = make_toolbar(self, "Raster output", vertical=True)
        self.alignment_toolbars = {
            key: make_toolbar(self, f"{title} alignment", vertical=True)
            for key, title in (
                ("geometry", "Vertices"),
                ("figures", "Contours"),
                ("regions", "Regions"),
            )
        }
        self.toolbars = (
            categories,
            self.basic_toolbar,
            self.dataset_toolbar,
            geometry,
            region_tools,
            pixels,
            figures,
            self.groups_toolbar,
            self.region_output_toolbar,
            self.raster_output_toolbar,
            *self.alignment_toolbars.values(),
            self.view_toolbar,
        )
        from dale.toolbar import TopPanelScrollArea

        self.top_panels = (
            categories,
            self.basic_toolbar,
            self.view_toolbar,
            self.groups_toolbar,
            self.dataset_toolbar,
        )
        self.top_panels_host = QToolBar("Top panels", self)
        self.top_panels_host.setObjectName("topPanelsHost")
        self.top_panels_host.setMovable(False)
        self.top_panels_host.setFloatable(False)
        self.top_panels_host.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        self.top_panels_host.setStyleSheet(
            "QToolBar#topPanelsHost { border: 0; background: transparent; spacing: 0; "
            "padding: 0; margin: 0; }"
        )
        self.top_panels_scroll = TopPanelScrollArea(self.top_panels_host)
        self.top_panels_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        top_content = QWidget()
        row = QHBoxLayout(top_content)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        row.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        for bar in self.top_panels:
            self.removeToolBar(bar)
            row.addWidget(bar)
            bar.show()
        row.addStretch(1)
        self.top_panels_scroll.setWidget(top_content)
        self.top_panels_host.addWidget(self.top_panels_scroll)
        self.top_panels_host.layout().setContentsMargins(0, 0, 0, 0)
        self.addToolBar(self.top_panels_host)
        self.top_panels_scroll.horizontalScrollBar().setToolTip(
            "Scroll the top panels horizontally with the mouse wheel."
        )
        self.top_panels_timer = QTimer(self)
        self.top_panels_timer.setSingleShot(True)
        self.top_panels_timer.timeout.connect(self.update_top_toolbar_geometry)
        self.geometry_eraser_tiles = {}
        self.sized_tools = {}
        self.mode_tool_pages = {}
        for key, bar in (
            ("geometry", geometry),
            ("figures", figures),
            ("regions", region_tools),
            ("pixels", pixels),
        ):
            page = QWidget()
            column = QVBoxLayout(page)
            column.setContentsMargins(0, 0, 0, 0)
            column.setSpacing(4)
            column.addWidget(bar)
            if key in self.alignment_toolbars:
                column.addWidget(self.alignment_toolbars[key])
            if bar in (region_tools, pixels):
                column.addWidget(
                    self.region_output_toolbar
                    if bar == region_tools
                    else self.raster_output_toolbar
                )
            self.mode_tool_pages[key] = page
            self.tool_stack.addWidget(page)

        def action(bar, title, handler, shortcut=None):
            if bar == categories:
                item = QWidgetAction(self)
                item.setText(title)
                button = ModeTabButton(bar)
                button.setDefaultAction(item)
                item.setDefaultWidget(button)
            else:
                item = QAction(title, self)
            item.setProperty("dale_tool_key", title)
            display = {
                "Auto-close": "Auto-close contours",
                "Edit points": "Edit contour vertices",
                "Select figures": "Select contours",
                "Move figures": "Move contours",
                "Rotate figures": "Rotate contours",
                "Scale figures": "Scale contours",
                "Figure point alignment": "Contour point alignment",
                "Figure guide alignment": "Contour guide alignment",
                "Figure extension alignment": "Angled contour guides",
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
                "Erase square": "Square raster eraser",
                "Restore square": "Square raster restore",
                "Remove outside": "Erase raster outside selected regions",
                "Remove inside": "Erase raster inside selected regions",
            }.get(title)
            if display:
                item.setProperty("dale_display_key", display)
            vertical = isinstance(bar, QToolBar) and bar.orientation() == Qt.Orientation.Vertical
            icon_only = vertical or bar in (self.basic_toolbar, self.view_toolbar)
            if icon_only:
                item.setIcon(tool_icon(title))
                item.setProperty("dale_icon_only", True)
            if bar == categories or bar in (self.basic_toolbar, self.view_toolbar):
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
                "Scale figures": (1, 100, 5, "figure_scale_control", self.set_figure_scale_step),
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
                "Erase square": (
                    1,
                    4096,
                    40,
                    "square_brush_control",
                    lambda v: self.set_brush("Erase square", v),
                ),
                "Restore square": (
                    1,
                    4096,
                    40,
                    "square_restore_control",
                    lambda v: self.set_brush("Restore square", v),
                ),
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
                "Figure extension alignment": (
                    1,
                    9999,
                    14,
                    "extension_distance",
                    lambda value: self.set_alignment_distance("extension_distance_px", value),
                ),
                "Right-angle alignment": (
                    1,
                    90,
                    5,
                    "right_angle_tolerance",
                    lambda value: self.set_alignment_distance("right_angle_tolerance_deg", value),
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
                    if title == "Right-angle alignment":
                        editor.setSuffix("°")
                    editor.valueChanged.connect(handler)
                setattr(self, attribute, editor)
                alignment = title in (
                    "Snapping (px)",
                    "Right-angle alignment",
                    "Contour alignment",
                    "Figure point alignment",
                    "Figure guide alignment",
                    "Figure extension alignment",
                    "Region point alignment",
                    "Region guide alignment",
                )
                tile = SizedToolButton(
                    editor,
                    item,
                    inline=title in (*RASTER_BRUSHES, "Scale figures"),
                    activation_hint=("" if title == "Snapping (px)" else "Alt")
                    if alignment
                    else None,
                )
                self.sized_tools[title] = tile
                if title in GEOMETRY_ERASERS:
                    self.geometry_eraser_tiles[title] = tile
                bar.addWidget(tile)
            else:
                bar.addAction(item)
                if vertical:
                    bar.widgetForAction(item).setFixedSize(48, 48)
                elif bar in (self.basic_toolbar, self.view_toolbar):
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

        self.new_project_action = action(
            self.file_menu, "New project", self.new_project, QKeySequence.StandardKey.New
        )
        self.manager_action = action(self, "Dataset manager…", self.manage_datasets, "Ctrl+I")
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
            (pixels, ("Select raster regions", *RASTER_TRANSFORM_TOOLS, *RASTER_BRUSHES)),
        ):
            for mode in names:
                item = action(bar, mode, lambda checked=False, m=mode: self.activate_mode(m))
                item.setCheckable(True)
                item.setChecked(mode == "Pan")
                modes.addAction(item)
                self.mode_actions[mode] = item
        self.rotation_value_controls = {}
        self.circle_detail_control = ToolSpinBox(self)
        self.circle_detail_control.setRange(0, 95)
        self.circle_detail_control.setValue(0)
        self.circle_detail_control.hide()
        self.circle_detail_control.valueChanged.connect(self.set_circle_detail)
        self.rotation_step_controls = {}
        for mode, prefix in (("Rotate figures", "figure"), ("Rotate regions", "region")):
            controls = []
            for modifier in ("", "alt_"):
                key = f"{prefix}_{modifier}rotation_step_cdeg"
                editor = ToolSpinBox(self)
                low, high, default = ROTATION_VALUE_RANGES[key]
                editor.setRange(low, high)
                editor.setValue(default)
                editor.hide()
                self.rotation_value_controls[key] = editor
                controls.append(editor)
                editor.valueChanged.connect(lambda value, mode=mode: self.sync_rotation_steps(mode))
            self.rotation_step_controls[mode] = tuple(controls)
        self.rotation_step_controls["Rotate raster regions"] = self.rotation_step_controls[
            "Rotate regions"
        ]
        self.mirror_contour_actions = {
            axis: action(
                figures, title, lambda checked=False, axis=axis: self.mirror_contours(axis)
            )
            for axis, title in (
                ("vertical", "Mirror contours about vertical axis"),
                ("horizontal", "Mirror contours about horizontal axis"),
            )
        }
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
            self.basic_toolbar, "Copy region contours", self.copy_region_contours, "Ctrl+C"
        )
        self.edit_menu.addAction(self.copy_regions_action)
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
        self.delete_regions_action = action(
            self.basic_toolbar, "Delete region", self.delete_selected_regions, "Del"
        )
        self.delete_regions_action.setEnabled(False)
        self.edit_menu.addAction(self.delete_regions_action)
        self.main_delete_action = self.delete_regions_action
        self.update_clipboard_actions()
        self.move_button = region_tools.widgetForAction(self.mode_actions["Move regions"])
        self.rotate_button = region_tools.widgetForAction(self.mode_actions["Rotate regions"])
        action(self.view_toolbar, "Fit", self.view.fit_map, "F")
        self.walls_action = action(self.view_toolbar, "Show contours", self.toggle_walls)
        self.walls_action.setCheckable(True)
        self.walls_action.setChecked(True)
        self.alignment_actions = {}
        for key, title in (
            ("right_angle_alignment", "Right-angle alignment"),
            ("contour_alignment", "Contour alignment"),
        ):
            item = action(
                self.alignment_toolbars["geometry"],
                title,
                lambda checked, key=key: self.set_alignment(key, checked),
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
        self.vertex_brush_control = self.geometry_eraser_tiles["Erase vertices"].editor()
        pixels.addSeparator()
        self.mask_actions = {
            "outside": action(pixels, "Remove outside", lambda: self.mask("outside")),
            "inside": action(pixels, "Remove inside", lambda: self.mask("inside")),
        }
        self.crosshair_action = action(
            self.view_toolbar,
            "Raster crosshair",
            lambda checked: self.view.raster_aids.configure(crosshair=checked),
        )
        self.rulers_action = action(
            self.view_toolbar,
            "Raster rulers",
            lambda checked: self.view.raster_aids.configure(rulers=checked),
        )
        self.move_guides_action = action(self.view_toolbar, "Move guides", self.set_guide_editing)
        self.mode_actions["Move guides"] = self.move_guides_action
        modes.addAction(self.move_guides_action)
        self.grid_action = action(self.view_toolbar, "Scene grid", self.set_scene_grid_visible)
        self.background_action = action(
            self.view_toolbar,
            "Canvas background",
            lambda: self.show_tool_settings("Canvas background"),
        )
        self.native_resolution_action = action(
            self.view_toolbar,
            "Native raster resolution",
            lambda checked: self.view.raster_aids.configure(full_resolution=checked),
        )
        for command in (
            self.crosshair_action,
            self.rulers_action,
            self.move_guides_action,
            self.grid_action,
            self.native_resolution_action,
        ):
            command.setCheckable(True)
        self.auto_close_tile = self.sized_tools["Auto-close"]
        self.snap_action = action(
            self.alignment_toolbars["geometry"], "Snapping (px)", self.set_snapping
        )
        self.snap_action.setCheckable(True)
        self.snap_action.setChecked(True)
        self.snap_tile = self.sized_tools["Snapping (px)"]
        action(geometry, "Close all contours", self.close_all_contours)
        self.delete_contours_action = action(
            self.edit_menu, "Delete contours", self.delete_selected_contours, "Del"
        )
        self.delete_contours_action.setIcon(tool_icon("Delete region"))
        self.delete_contours_action.setProperty("dale_icon_only", True)
        self.delete_contours_action.setEnabled(False)
        self.export_regions_action = action(
            self.region_output_toolbar,
            "Export selected regions",
            lambda: self.export(selected_only=True),
        )
        self.export_regions_button = self.region_output_toolbar.widgetForAction(
            self.export_regions_action
        )
        self.region_alignment_actions = {}
        self.figure_alignment_actions = {}
        for section, prefix, target in (
            ("regions", "Region", self.region_alignment_actions),
            ("figures", "Figure", self.figure_alignment_actions),
        ):
            controls = [
                (
                    "guide alignment",
                    self.contour_alignment_distance,
                    False,
                ),
            ]
            if section == "figures":
                controls.append(("extension alignment", None, False))
            controls.append(("point alignment", self.snap_distance, True))
            for suffix, source_control, initial in controls:
                title = f"{prefix} {suffix}"
                item = action(self.alignment_toolbars[section], title, self.apply_section_alignment)
                item.setCheckable(True)
                item.setChecked(initial)
                if source_control is not None:
                    source_control.valueChanged.connect(self.sized_tools[title].editor().setValue)
                target[title] = item
        for command in (
            self.snap_action,
            *self.alignment_actions.values(),
            *self.figure_alignment_actions.values(),
            *self.region_alignment_actions.values(),
        ):
            command.toggled.connect(self.apply_section_alignment)
        action(
            self.region_output_toolbar,
            "Artwork offset (px)",
            lambda: self.show_tool_settings("Artwork offset (px)"),
        )
        raster_offset_action = action(
            self.raster_output_toolbar,
            "Raster artwork offset",
            lambda: self.show_tool_settings("Raster artwork offset"),
        )
        raster_offset_action.setProperty("dale_display_key", "Region artwork offset (px)")
        self.raster_output_toolbar.removeAction(raster_offset_action)
        self.raster_offset_button = SizedToolButton(
            self.raster_contour_offset, raster_offset_action
        )
        self.sized_tools["Raster artwork offset"] = self.raster_offset_button
        raster_offset_widget = self.raster_output_toolbar.addWidget(self.raster_offset_button)
        self.isolate_raster_action = action(
            self.raster_output_toolbar, "Preview selected regions", self.set_raster_isolation
        )
        self.isolate_raster_action.setCheckable(True)
        self.raster_output_toolbar.insertAction(raster_offset_widget, self.isolate_raster_action)
        self.tool_settings_buttons = {
            "Move figures": figures.widgetForAction(self.mode_actions["Move figures"]),
            **self.sized_tools,
            "Edit points": geometry.widgetForAction(self.mode_actions["Edit points"]),
            "New circle": geometry.widgetForAction(self.mode_actions["New circle"]),
            "Export selected regions": self.export_regions_button,
            "Raster rulers": self.view_toolbar.widgetForAction(self.rulers_action),
            "Scene grid": self.view_toolbar.widgetForAction(self.grid_action),
            "Canvas background": self.view_toolbar.widgetForAction(self.background_action),
            "Raster artwork offset": self.raster_offset_button,
            "Preview selected regions": self.raster_output_toolbar.widgetForAction(
                self.isolate_raster_action
            ),
        }
        for mode, bar in (
            ("Rotate figures", figures),
            ("Move regions", region_tools),
            ("Rotate regions", region_tools),
            ("Rotate raster regions", pixels),
            ("Scale raster regions", pixels),
        ):
            self.tool_settings_buttons[mode] = bar.widgetForAction(self.mode_actions[mode])
        for title, button in self.tool_settings_buttons.items():
            ToolSettingsCorner(button)
            button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            button.customContextMenuRequested.connect(
                lambda position, title=title: self.show_tool_settings(title)
            )
        for bar in (
            geometry,
            figures,
            region_tools,
            pixels,
            self.region_output_toolbar,
            self.raster_output_toolbar,
            *self.alignment_toolbars.values(),
        ):
            bar.ensurePolished()
            bar.setFixedHeight(bar.sizeHint().height())
        self.tool_stack.setFixedHeight(self.tool_stack.currentWidget().sizeHint().height())
        self.view.size_changed.connect(self.sync_tool_sizes)
        QApplication.instance().installEventFilter(self)
        tips = {
            "Erase square": "Erase image pixels with an axis-aligned square brush.",
            "Restore square": "Restore image pixels with an axis-aligned square brush.",
            "Raster crosshair": "Show dashed one-pixel cursor axes across the scene editing area.",
            "Raster rulers": (
                "Measure the scene and drag horizontal or vertical guides from the rulers."
            ),
            "Move guides": "Select and reposition ruler guides without editing the scene.",
            "Scene grid": "Show the square grid used by PNG export and preview.",
            "Canvas background": (
                "Choose a checkerboard or solid canvas background for this dataset."
            ),
            "Move raster regions": (
                "Move selected boundaries together with their current image pixels."
            ),
            "Rotate raster regions": (
                "Rotate selected boundaries and their image pixels around their common center."
            ),
            "Scale raster regions": "Resize selected boundaries together with their image pixels.",
            "Preview selected regions": (
                "Preview only selected region imagery; "
                "show the whole image when selection is empty."
            ),
            "Raster artwork offset": "Include scene image pixels beyond the contour or cut inward.",
            "Native raster resolution": (
                "Show visible image tiles at source resolution with current raster edits."
            ),
            "Select all contour lines": (
                "Select all elements of the current section in the visible height scope."
            ),
            "Delete region": (
                "Delete selected region boundaries, including hole outlines. "
                "Keep lines inside and image pixels."
            ),
            "Region point alignment": (
                "Snap the highlighted vertex or common center to an existing point."
            ),
            "Region guide alignment": (
                "Align the highlighted region vertex with horizontal/vertical vertex guides."
            ),
            "New project": (
                "Create an empty project with one dataset. Unsaved changes can be saved first."
            ),
            "Dataset manager…": "Dataset manager: create, rename, combine or transfer datasets.",
            "Open project": "Open a .dale project with its files and applied edits.",
            "Save project": (
                "Save every dataset and its applied edits in the current .dale project."
            ),
            "Save project as…": (
                "Save all datasets and applied edits to a new .dale project file."
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
                "Make a right angle while moving a vertex or drawing a line from a contour."
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
            "Scale figures": "Resize selected contour lines around their common center.",
            "Mirror contours about vertical axis": (
                "Swap left and right about the vertical axis through the common contour center. "
                "Keep image pixels and unselected lines in place."
            ),
            "Mirror contours about horizontal axis": (
                "Swap top and bottom about the horizontal axis through the common contour center. "
                "Keep image pixels and unselected lines in place."
            ),
            "Figure point alignment": (
                "Snap the highlighted vertex or common center to an existing point."
            ),
            "Figure guide alignment": (
                "Align the highlighted contour vertex with vertex X/Y guides."
            ),
            "Figure extension alignment": (
                "Snap the highlighted vertex or common center to a stationary line's "
                "virtual extension at any angle. No lines are added."
            ),
            "Select raster regions": (
                "Click to toggle a region; drag over 10 screen pixels to invert regions in a box. "
                "Empty click asks before clearing selection. Undo/redo includes selection changes."
            ),
            "Move regions": "Drag selected contours to move them. Image pixels stay in place.",
            "Rotate regions": "Rotate selected region contours around their common center.",
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
                "Deselect elements in the current section; cancel the current gesture."
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
            "New project": "No gesture or export is in progress.",
            "Erase square": "A scene image is open.",
            "Restore square": "A scene image is open.",
            "Raster crosshair": "A scene image is open.",
            "Raster rulers": "A scene image is open.",
            "Move guides": "Rulers are visible and guide editing is enabled.",
            "Move raster regions": "At least one region is selected.",
            "Rotate raster regions": "At least one region is selected.",
            "Scale raster regions": "At least one region is selected.",
            "Native raster resolution": "A scene image is open.",
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
            "Figure extension alignment": (
                "This button is enabled and contours are being moved or pasted."
            ),
            "Select figures": "Contours are available.",
            "Move figures": "Contours are available; select lines to move.",
            "Rotate figures": "At least one contour line is selected.",
            "Scale figures": "At least one contour line is selected.",
            "Mirror contours about vertical axis": (
                "Contours is active, a line is selected and no gesture or export is in progress."
            ),
            "Mirror contours about horizontal axis": (
                "Contours is active, a line is selected and no gesture or export is in progress."
            ),
            **{key: "An image or contour JSON is open." for key in contour_tools},
            "Right-angle alignment": (
                "This button is enabled and a point is being moved or a line is being drawn."
            ),
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
                if key == "Right-angle alignment":
                    parts.append(
                        "An independent dragged end can align perpendicular to a nearby "
                        "stationary line without joining it."
                    )
                if key == "Contour alignment":
                    parts.append(
                        "A free end of an isolated line can follow its original vector "
                        "within the guide tolerance."
                    )
                if key in ("Contour alignment", "Figure guide alignment", "Region guide alignment"):
                    parts.append(
                        "Hover a stationary vertex during placement to keep its X/Y guides "
                        "until the gesture ends."
                    )
                keys = []
                if key in RASTER_BRUSHES:
                    keys.extend(
                        [
                            "Ctrl+wheel: change brush diameter.",
                            "Alt+wheel: change feather width.",
                            "Right-click: open tool settings.",
                            "Escape: cancel the stroke.",
                        ]
                    )
                if key in ("Edit points", "Paste region contours"):
                    keys.append("Alt: use the enabled alignment buttons.")
                if key == "New rectangle":
                    keys.append("Alt: align corners when Contour alignment is enabled.")
                if key == "New line":
                    keys.append("Alt: use the enabled alignment buttons.")
                if key == "New circle":
                    keys.append("Ctrl+wheel while drawing: adjust the radius.")
                    keys.append("Right-click: open tool settings.")
                if key == "Move figures":
                    keys.append(
                        "Double-click: select only this contour; empty space clears selection, "
                        "when enabled."
                    )
                    keys.append("Right-click: open tool settings.")
                if key in ("Edit points", "Erase lines"):
                    keys.append("Right-click: open tool settings.")
                if key in ("Export selected regions", "Preview selected regions", "Scene grid"):
                    keys.append("Right-click: open tool settings.")
                if key == "Raster rulers":
                    keys.extend(
                        [
                            "Drag from a ruler: create a guide.",
                            "Ctrl+drag a guide: move it; return it to a ruler to delete.",
                            "Escape: cancel the guide drag.",
                            "Right-click: open tool settings.",
                        ]
                    )
                if key == "Move guides":
                    keys.extend(
                        [
                            "Drag a guide: move it.",
                            "Double-click a guide: delete it.",
                            "Escape: cancel the guide drag.",
                        ]
                    )
                if key in RASTER_TRANSFORM_TOOLS:
                    keys.extend(
                        [
                            "Drag selected regions: move. Ctrl+wheel: scale."
                            if key == "Move raster regions"
                            else "Wheel: resize selected raster regions."
                            if key == "Scale raster regions"
                            else (
                                "Wheel: rotate selected regions by the configured step "
                                "around their common center."
                            ),
                            "Alt+wheel: rotate by the configured Alt step."
                            if key == "Rotate raster regions"
                            else "Escape: cancel the current gesture.",
                        ]
                    )
                if key == "Raster artwork offset":
                    keys.append("Right-click: open tool settings.")
                if key in (
                    "Right-angle alignment",
                    "Contour alignment",
                    "Region point alignment",
                    "Region guide alignment",
                    "Figure point alignment",
                    "Figure guide alignment",
                    "Figure extension alignment",
                ):
                    keys.append("Alt: apply this alignment while dragging.")
                if key in MOVE_TOOLS:
                    keys.append("Ctrl+wheel: scale selected contours.")
                if key == "Scale figures":
                    keys.append("Wheel: scale selected contours by the configured step.")
                if key in ROTATE_TOOLS:
                    keys.append("Wheel: rotate by the configured step.")
                    keys.append("Alt+wheel: rotate by the configured Alt step.")
                    keys.append("Right-click: open tool settings.")
                if key == "Select figures":
                    keys.extend(
                        [
                            "Click: toggle the line under the cursor.",
                            "Double-click: select or deselect all lines "
                            "connected by shared vertices.",
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
                item.setProperty("dale_default_tooltip_keys", keys)
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
        self.setup_alchemist()
        self.initialize_tool_preferences()
        self.rebuild_recent_menu()
        for command in self.findChildren(QAction):
            if not command.shortcut().isEmpty():
                command.changed.connect(self.update_mode_help)
        self.set_language(self.language, persist=False)
        self.statusBar().showMessage(self.t("Ready. All editing is local."))

    def t(self, text, **values):
        return translate(text, self.language, **values)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "top_panels_timer"):
            self.top_panels_timer.start(0)

    def update_top_toolbar_geometry(self):
        height = max(bar.sizeHint().height() for bar in self.top_panels)
        for bar in self.top_panels:
            bar.setFixedWidth(bar.sizeHint().width())
            bar.setFixedHeight(height)
        self.top_panels_scroll.setFixedHeight(height + 3)
        self.top_panels_host.setFixedHeight(height + 3)

    def update_main_delete_action(self):
        if not hasattr(self, "settings_action") or not hasattr(self, "delete_contours_action"):
            return
        target = (
            self.delete_contours_action
            if self.current_tool_set in ("figures", "alchemist")
            else self.delete_regions_action
        )
        if target is not self.main_delete_action:
            self.basic_toolbar.removeAction(self.main_delete_action)
            self.basic_toolbar.insertAction(self.settings_action, target)
            self.main_delete_action = target
            button = self.basic_toolbar.widgetForAction(target)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.setFixedSize(36, 36)
            self.top_panels_timer.start(0)

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
            "figure_scale_step_percent": self.figure_scale_control,
            "circle_detail_steps": self.circle_detail_control,
            "line_eraser_diameter": self.geometry_brush_control,
            "vertex_eraser_diameter": self.vertex_brush_control,
            "raster_erase_diameter": self.brush_control,
            "raster_restore_diameter": self.restore_brush_control,
            "raster_erase_square_diameter": self.square_brush_control,
            "raster_restore_square_diameter": self.square_restore_control,
            "auto_close_distance_px": self.auto_close_control,
            "global_close_distance_px": self.global_close_control,
            "snap_distance_px": self.snap_distance,
            "right_angle_tolerance_deg": self.right_angle_tolerance,
            "contour_alignment_distance_px": self.contour_alignment_distance,
            "extension_distance_px": self.extension_distance,
            "artwork_offset_px": self.contour_offset,
            **self.rotation_value_controls,
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

    def set_circle_detail(self, value):
        self.view.circle_detail_steps = value
        self.view.viewport().update()

    def sync_rotation_steps(self, mode):
        self.view.rotation_steps[mode] = tuple(
            c.value() / 100 for c in self.rotation_step_controls[mode]
        )
        if mode == "Rotate regions":
            self.view.rotation_steps["Rotate raster regions"] = self.view.rotation_steps[mode]

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
        before = self.raster_selection_snapshot()
        if self.current_tool_set in ("figures", "alchemist"):
            self.view.figure_line_ids = ()
            if self.current_tool_set == "alchemist":
                self.thinning.clear_selection()
            self.view.figure_pivot = None
            self.view.figure_pivot_edges = ()
        elif self.current_tool_set == "geometry":
            self.view.contour_line_ids = ()
        else:
            self.view.detached_selection = None
            self.selected_regions = ()
            self.view.region_pivot = None
        self.view.cursor_point = self.view.hover_edge = None
        self.view.update_hover()
        self.update_map_info()
        self.view.update_image()
        self.record_raster_selection(before)

    def select_all_elements(self):
        if not self.view.session:
            return
        self.view.cancel_pending()
        before = self.raster_selection_snapshot()
        if self.current_tool_set in ("geometry", "figures", "alchemist"):
            geometry = self.view.editing_geometry()
            ids = tuple(record.id for record in geometry.lineage)
            if self.current_tool_set in ("figures", "alchemist"):
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

        self.record_raster_selection(before)

    def raster_selection_snapshot(self):
        if self.current_tool_set != "pixels" or not self.view.session:
            return None
        detached = self.view.detached_selection
        return RegionSelection(
            tuple(p.wkb for p in self.view.region_polygons),
            bool(detached),
            tuple(detached.get("line_ids", ())) if detached else (),
            self.selected_regions is None,
        )

    def record_raster_selection(self, before):
        if before is None:
            return
        after = self.raster_selection_snapshot()
        if after is not None and before != after:
            self.view.session.add(RasterSelectionEdit(before, after))

    def restore_raster_selection(self, state):
        from shapely import from_wkb

        switched = self.current_tool_set != "pixels"
        if switched:
            self.select_tool_set("pixels", activate=False)
        polygons = self.available_regions()
        self.region_key = tuple(p.wkb for p in polygons)
        self.view.region_pivot = self.view.region_anchor = None
        self.view.detached_selection = None
        if state.detached:
            self.view.detached_selection = {
                "geometry": self.view.session.geometry(),
                "polygons": tuple(from_wkb(p) for p in state.polygons),
                "line_ids": state.line_ids,
            }
            self.selected_regions = tuple(range(len(state.polygons)))
        else:
            chosen = set(state.polygons)
            self.selected_regions = (
                None
                if state.all_regions
                else tuple(i for i, p in enumerate(polygons) if p.wkb in chosen)
            )
        self.update_map_info()
        if switched:
            self.activate_mode("Select raster regions")
        self.view.update_image()

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
                self.group_control,
                self.group_heading,
                *self.mode_help_labels.values(),
            ),
        )
        self.update_size_help()
        self.sync_raster_aids()
        for menu in (self.file_menu, self.edit_menu, self.about_menu, self.recent_menu):
            menu.menuAction().setToolTip(menu.toolTip())
        self.region_control.setToolTip(
            self.t("Choose all closed regions or one region to highlight and export.")
        )
        self.update_project_info()
        self.rebuild_recent_menu()
        self.rebuild_dataset_controls()
        self.rebuild_group_controls()
        self.set_sidebar_visible(self.right_panel_visible, persist=False)
        self.top_panels_timer.start(0)
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
        title = application_title()
        if self.project_path:
            title += f" - {self.project_path.name}"
        self.setWindowTitle(title)
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

    def confirm_export_file(self, path):
        dialog = QMessageBox(self.progress if self.worker and self.progress else self)
        dialog.setObjectName("exportFileConflict")
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setWindowTitle(self.t("File already exists"))
        dialog.setText(self.t('Overwrite file "{name}"?', name=path.name))
        dialog.setInformativeText(self.t("Folder: {folder}", folder=path.parent.name))
        overwrite = dialog.addButton(self.t("Overwrite"), QMessageBox.ButtonRole.AcceptRole)
        copy = dialog.addButton(self.t("Create copy"), QMessageBox.ButtonRole.ActionRole)
        cancel = dialog.addButton(self.t("Cancel"), QMessageBox.ButtonRole.RejectRole)
        for button, title, purpose in (
            (overwrite, "Overwrite", "Replace only this exported file."),
            (copy, "Create copy", "Keep the existing file and save a copy with a free name."),
            (cancel, "Cancel", "Cancel this export and keep existing files unchanged."),
        ):
            button.setToolTip(self.control_help(purpose, title=title))
        dialog.setDefaultButton(cancel)
        dialog.setEscapeButton(cancel)
        dialog.exec()
        return (
            "overwrite"
            if dialog.clickedButton() is overwrite
            else "copy"
            if dialog.clickedButton() is copy
            else None
        )

    def resolve_worker_file_conflict(self, path):
        worker = self.worker
        if worker is None:
            return
        worker.conflict_answer = (
            None if worker.isInterruptionRequested() else self.confirm_export_file(path)
        )
        worker.conflict_event.set()

    def show_tool_settings(self, tool):
        from dale.individual_transform import tool_key

        anchor = (
            self.raster_offset_button
            if tool == "Raster artwork offset"
            else self.raster_output_toolbar.widgetForAction(self.isolate_raster_action)
            if tool == "Preview selected regions"
            else None
        )
        self.view.finish_rotation()
        if self.tool_settings_popup is not None:
            self.tool_settings_popup.reject()
        tile = self.sized_tools.get(tool)
        value = None
        if tile:
            label = (
                "Scaling step (%)"
                if tool == "Scale figures"
                else "Artwork offset (source pixels)"
                if tool == "Artwork offset (px)"
                else "Brush diameter (source pixels)"
                if tool in RASTER_BRUSHES
                else "Brush diameter (screen pixels)"
                if tool in GEOMETRY_ERASERS
                else "Angular tolerance (degrees)"
                if tool == "Right-angle alignment"
                else "Snap distance (screen pixels)"
                if "alignment" in tool.lower() or tool == "Snapping (px)"
                else "Maximum endpoint movement (screen pixels)"
            )
            value = tile.editor(), label
        if tool == "Raster artwork offset":
            value = self.raster_contour_offset, "Artwork offset (source pixels)"
            self.raster_contour_offset.setToolTip(
                self.control_help(
                    "Include scene image pixels beyond the contour or cut inward.",
                    title="Region artwork offset (px)",
                )
            )
        question, choices, remembered = None, (), None
        same_type_question = self.current_tool_set == "alchemist" and tool in (
            "Select figures",
            "Move figures",
        )
        if same_type_question:
            from dale.preferences import load_alchemist_same_type

            question = "Select visible objects of this same type?"
            choices = (("Select the same type", True), ("Select only this contour", False))
            remembered = load_alchemist_same_type(self.preferences_path)
        if tool in self.connection_choices:
            question = (
                "Connect new cut endpoints to intersecting contours with shared vertices?"
                if tool == "Erase lines"
                else "Connect this point to the other contour with a shared vertex?"
            )
            choices = (("Connect contours", True), ("Keep contours independent", False))
            remembered = self.connection_choices[tool]
        is_preview = tool == "Preview selected regions"
        preview_settings = self.view.raster_aids.settings
        is_export = tool in ("Export selected regions", "Preview selected regions")
        grid_info = ""
        grid_size = preview_settings["export_grid_size"] or None
        if is_export or tool == "Scene grid":
            try:
                if self.view.session:
                    grid = export_grid(self.view.session, grid_size)
                    if grid_size is None:
                        grid_size = round(grid.scene_cell)
                    grid_info = self.t(
                        "Grid: {width} × {height} source px. Origin: {x}, {y}.",
                        width=grid.cell[0],
                        height=grid.cell[1],
                        x=grid.origin[0],
                        y=grid.origin[1],
                    )
            except ValueError as exc:
                grid_info = self.t(str(exc))
        if is_export:
            question = "Export adjacent regions as one?"
            choices = (("One PNG per adjacent group", True), ("One PNG per region", False))
            remembered = (
                preview_settings["preview_merge"]
                if is_preview
                else self.remembered_merge_selected_regions
            )
        if self.current_tool_set == "alchemist":
            anchor = getattr(self, "alchemist_tool_buttons", {}).get(tool, anchor)
        button = anchor or self.tool_settings_buttons[tool]
        dialog = ToolSettingsDialog(
            self,
            button.defaultAction().text(),
            value=value,
            question=question,
            choices=choices,
            remembered=remembered,
            size_to_grid=(preview_settings["preview_grid"] if is_preview else self.size_to_grid)
            if is_export
            else None,
            scene_grid=(grid_size or 100) if tool == "Scene grid" else None,
            grid_color=preview_settings["export_grid_color"],
            grid_transparency=preview_settings["export_grid_transparency"],
            grid_width=preview_settings["export_grid_width"],
            include_json=(preview_settings["preview_json"] if is_preview else self.include_json)
            if is_export
            else None,
            include_png=self.include_png if tool == "Export selected regions" else None,
            merge_contours=(
                self.merge_export_contours if tool == "Export selected regions" else None
            ),
            group_naming=(
                preview_settings["preview_naming"] if is_preview else self.export_group_naming
            )
            if is_export
            else None,
            rotation_steps=self.rotation_step_controls.get(tool, ()),
            circle_detail=self.circle_detail_control if tool == "New circle" else None,
            grid_info=grid_info,
            background=self.view.raster_aids.snapshot() if tool == "Canvas background" else None,
            raster_aids=self.view.raster_aids.snapshot() if tool == "Raster rulers" else None,
            raster_brush=(
                {
                    **self.view.raster_brushes[tool],
                    "shape": "square" if tool.endswith("square") else "circle",
                }
                if tool in RASTER_BRUSHES
                else None
            ),
            adjacent_vertices=(
                self.view.right_angle_neighbours if tool == "Right-angle alignment" else None
            ),
            connected_contours=(
                self.view.extension_connected if tool == "Figure extension alignment" else None
            ),
            own_angle_priority=(
                self.view.right_angle_own_priority if tool == "Right-angle alignment" else None
            ),
            json_contours=self.json_contours if tool == "Export selected regions" else None,
            height_normalization=self.height_normalization
            if tool == "Export selected regions"
            else None,
            individual_centers=(
                self.view.individual_transform_enabled(tool)
                if tool_key(self.current_tool_set, tool) and self.current_tool_set != "alchemist"
                else None
            ),
            figure_double_click=(
                self.view.figure_move_double_click if tool == "Move figures" else None
            ),
        )
        dialog.transform_section = self.current_tool_set
        dialog.same_type_question = same_type_question
        position = button.mapToGlobal(QPoint(button.width() + 8, 0))
        available = button.screen().availableGeometry()
        viewport = self.view.viewport()
        map_bounds = QRect(viewport.mapToGlobal(QPoint()), viewport.size())
        map_bounds = map_bounds.intersected(available).adjusted(6, 6, -6, -6)
        if map_bounds.width() >= dialog.width() and map_bounds.height() >= dialog.height():
            available = map_bounds
        dialog.move(
            max(available.left(), min(position.x(), available.right() - dialog.width())),
            max(available.top(), min(position.y(), available.bottom() - dialog.height())),
        )
        self.tool_settings_popup = dialog
        dialog.accepted.connect(lambda: self.apply_tool_settings(tool, dialog, value))
        dialog.finished.connect(lambda result: self.clear_tool_settings_popup(dialog))
        dialog.show()
        return dialog

    def clear_tool_settings_popup(self, dialog):
        if self.tool_settings_popup is dialog:
            self.tool_settings_popup = None

    def apply_tool_settings(self, tool, dialog, value):
        from dale.individual_transform import tool_key
        from dale.preferences import save_alchemist_same_type

        if dialog.individual_centers is not None:
            key = tool_key(dialog.transform_section, tool)
            self.view.finish_rotation()
            self.view.individual_transform_settings[key] = dialog.individual_centers.isChecked()
            self.update_mode_help()
        if dialog.same_type_question:
            try:
                save_alchemist_same_type(self.preferences_path, dialog.default_action.currentData())
            except OSError:
                self.statusBar().showMessage(self.t("Preferences could not be written."), 7000)
        if tool == "Move figures":
            self.view.figure_move_double_click = dialog.figure_double_click.isChecked()
            if self.catalog:
                self.catalog.current.ui["figure_move_double_click"] = (
                    self.view.figure_move_double_click
                )
            self.view.figure_click = None
            self.update_mode_help()
        if tool == "Scene grid":
            try:
                export_grid(self.view.session, dialog.grid_size.value())
            except ValueError as exc:
                self.warning("Scene grid", str(exc))
                return
            self.view.raster_aids.configure(
                export_grid_size=dialog.grid_size.value(),
                export_grid_color=dialog.grid_color,
                export_grid_transparency=dialog.grid_transparency.value(),
                export_grid_width=dialog.grid_width.value(),
            )
        if tool == "Canvas background":
            self.view.raster_aids.configure(
                background_kind=dialog.background_kind.currentData(),
                background_color=dialog.background_color,
            )
        if tool in RASTER_BRUSHES:
            target = ("Restore" if tool.startswith("Restore") else "Erase") + (
                " square" if dialog.brush_shape.currentData() == "square" else ""
            )
            self.sized_tools[target].editor().setValue(dialog.value.value())
            self.view.raster_brushes[target] = {
                "feather": dialog.brush_feather.value(),
                "opacity": dialog.brush_opacity.value(),
            }
            if self.view.mode == tool:
                self.activate_mode(target)
            self.view.viewport().update()
        if tool == "Raster rulers":
            unit = dialog.ruler_units.currentData()
            try:
                if self.view.session:
                    measurement_scale(self.view.session.source, unit)
            except ValueError as exc:
                self.warning("Raster rulers", str(exc))
                return
            self.view.raster_aids.configure(
                unit=unit,
                snap=dialog.ruler_snap.isChecked(),
                grid=dialog.ruler_grid.isChecked(),
                step=dialog.ruler_step.value(),
            )
        if tool == "New circle":
            self.circle_detail_control.setValue(dialog.circle_detail.value())
        if tool in self.rotation_step_controls:
            for source, editor in zip(
                self.rotation_step_controls[tool], dialog.rotation_values, strict=True
            ):
                source.setValue(round(editor.value() * 100))
        if value and tool not in RASTER_BRUSHES:
            value[0].setValue(dialog.value.value())
        if tool == "Right-angle alignment":
            self.set_alignment_distance("right_angle_neighbours", dialog.neighbours.isChecked())
            self.set_alignment_distance(
                "right_angle_own_priority", dialog.own_angle_priority.isChecked()
            )
        if tool == "Figure extension alignment":
            self.view.extension_connected = dialog.connected_contours.isChecked()
        try:
            if tool in self.connection_choices:
                self.connection_choices[tool] = dialog.default_action.currentData()
                save_connection_choice(self.preferences_path, tool, self.connection_choices[tool])
            if tool == "Export selected regions":
                self.remembered_merge_selected_regions = dialog.default_action.currentData()
                self.merge_export_contours = dialog.merge_contours.isChecked()
                self.merge_selected_regions = (
                    self.remembered_merge_selected_regions is True or self.merge_export_contours
                )
                save_merge_export_contours(self.preferences_path, self.merge_export_contours)
                self.size_to_grid = dialog.grid.isChecked()
                self.include_json = dialog.json_export.isChecked()
                self.include_png = dialog.png_export.isChecked()
                self.json_contours = dialog.json_contours.currentData()
                save_alchemist_export(self.preferences_path, self.json_contours)
                self.height_normalization = (
                    dialog.normalize_height.isChecked(),
                    dialog.base_height.value(),
                    dialog.top_height.value(),
                )
                save_height_normalization(self.preferences_path, self.height_normalization)
                self.export_group_naming = dialog.naming_action.currentData()
                save_merge_selected_regions(
                    self.preferences_path, self.remembered_merge_selected_regions
                )
                save_size_to_grid(self.preferences_path, self.size_to_grid)
                save_include_json(self.preferences_path, self.include_json)
                save_include_png(self.preferences_path, self.include_png)
                self.update_export_actions()
                save_export_group_naming(self.preferences_path, self.export_group_naming)
            if tool == "Preview selected regions":
                self.view.raster_aids.configure(
                    preview_merge=dialog.default_action.currentData(),
                    preview_grid=dialog.grid.isChecked(),
                    preview_json=dialog.json_export.isChecked(),
                    preview_naming=dialog.naming_action.currentData(),
                )
        except OSError:
            self.statusBar().showMessage(self.t("Preferences could not be written."), 7000)
        self.update_map_info()

    def confirm_contour_connection(self, tool):
        self.view.finish_rotation()
        choice = self.connection_choices[tool]
        if choice is not None:
            return choice
        title = self.mode_actions[tool].text()
        purpose = (
            "Connect new cut endpoints to intersecting contours with shared vertices?"
            if tool == "Erase lines"
            else "Connect this point to the other contour with a shared vertex?"
        )
        dialog = QMessageBox(QMessageBox.Icon.Question, title, self.t(purpose), parent=self)
        dialog.setObjectName("contourConnectionQuestion")
        checkbox = QCheckBox(self.t("Do not ask again"), dialog)
        checkbox.setObjectName("rememberContourConnection")
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

    def confirm_merge_selected_regions(self):
        self.view.finish_rotation()
        choice = self.remembered_merge_selected_regions
        if choice is not None:
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
        checkbox = QCheckBox(self.t("Do not ask again"), dialog)
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

    def confirm_export_group_naming(self, dataset, groups):
        if self.export_group_naming is not None:
            return self.export_group_naming
        dialog = QMessageBox(
            QMessageBox.Icon.Question,
            self.t("PNG naming"),
            self.t("Which name should a region matching a group use?"),
            parent=self,
        )
        dialog.setObjectName("exportGroupNamingQuestion")
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        names = ", ".join(dict.fromkeys(group_export_stem(group.name) for group in groups if group))
        dialog.setInformativeText(
            self.t(
                "Dataset: {dataset}\nGroups: {groups}\nUnique numbers and PNG dimensions are kept.",
                dataset=dataset,
                groups=names,
            )
        )
        checkbox = QCheckBox(self.t("Do not ask again"), dialog)
        checkbox.setToolTip(
            self.control_help(
                "Remember this naming choice. Right-click Export selected regions to change it.",
                title="Do not ask again",
            )
        )
        dialog.setCheckBox(checkbox)
        dataset_button = dialog.addButton(self.t("Dataset name"), QMessageBox.ButtonRole.AcceptRole)
        group_button = dialog.addButton(self.t("Group name"), QMessageBox.ButtonRole.ActionRole)
        cancel = dialog.addButton(QMessageBox.StandardButton.Cancel)
        cancel.setText(self.t("Cancel"))
        for button, purpose, title in (
            (dataset_button, "Use the dataset name for every exported PNG.", "Dataset name"),
            (
                group_button,
                "Use matching group names; other PNGs keep the dataset name.",
                "Group name",
            ),
            (cancel, "Cancel without exporting or changing the question settings.", "Cancel"),
        ):
            button.setToolTip(self.control_help(purpose, title=title))
        dialog.setDefaultButton(dataset_button)
        dialog.setEscapeButton(cancel)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked not in (dataset_button, group_button):
            return None
        answer = "group" if clicked is group_button else "dataset"
        self.export_group_naming = answer if checkbox.isChecked() else None
        try:
            save_export_group_naming(self.preferences_path, self.export_group_naming)
        except OSError:
            self.statusBar().showMessage(self.t("Preferences could not be written."), 7000)
        return answer

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
                self.refresh_geometry_edit()

    def configure_json_repair(self, enabled=None):
        source = self.view.session.source if self.view.session else None
        available = bool(source and (source.json_bytes is not None or self.view.session.alchemist))
        self.json_repair_control.setVisible(available)
        alchemist = bool(self.view.session and self.view.session.alchemist)
        self.json_repair_control.setEnabled(not alchemist)
        if alchemist:
            enabled = True
        if enabled is None:
            enabled = bool(
                available
                and (
                    source.image_path is None
                    or any(
                        isinstance(w.get("flags"), dict) and "wall-height" in w["flags"]
                        for w in source.raw.get("walls", ())
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
        self.view.safe_json_repair = enabled or bool(session and session.alchemist)
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
        for mode in (*RASTER_BRUSHES, "Select raster regions"):
            self.mode_actions[mode].setEnabled(has_image)
        self.tool_set_actions["pixels"].setEnabled(has_image)
        self.sync_raster_aids()
        self.update_export_actions()
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
            self.view.selected_source_layer()
            choices = self.view._source_layers_cache[2]
            for layer in choices:
                label = (
                    self.t("All height layers")
                    if layer.kind == "all"
                    else self.t("Ambiguous heights")
                    if layer.kind == "ambiguous"
                    else self.t("Dungeon Alchemist floor {floor}", floor=layer.key.split(":")[1])
                    if layer.kind == "alchemist"
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

    def export_identity(self):
        selection = (
            None if self.current_tool_set in ("figures", "alchemist") else self.selected_regions
        )
        regions = (
            tuple(self.regions[i] for i in selection)
            if selection
            else self.view.session.analysis().cells
        )
        geometry = self.view.session.geometry()
        return selection_number(
            regions, fallback_edges=geometry_edges(geometry.walls, geometry.closures)
        )

    def export_json(self):
        if self.defer_slice_action(self.export_json):
            return
        session = self.view.session
        if not session or self.worker:
            return
        if self.view.active_gesture:
            self.information("Finish editing", "Finish or cancel the active gesture first.")
            return
        from dale.alchemist_progress import run_task
        from dale.project_io import snapshot_project

        frozen, frozen_catalog = snapshot_project(session, self.catalog)
        chosen = (
            None if self.current_tool_set in ("figures", "alchemist") else self.selected_regions
        )
        polygons = tuple(self.regions[i] for i in chosen) if chosen else None

        def prepare_name(report):
            report(10, "Preparing Scene JSON")
            document = (
                frozen_catalog.snapshot() if frozen_catalog else current_contours_document(frozen)
            )
            report(55, "Preparing export identity")
            geometry = frozen.geometry()
            number = selection_number(
                polygons if polygons is not None else frozen.analysis().cells,
                fallback_edges=geometry_edges(geometry.walls, geometry.closures),
            )
            return document, number

        try:
            document, identity = run_task(self, "Preparing Scene JSON", prepare_name)
        except Exception as exc:
            self.warning("Cannot export scene JSON", str(exc))
            return
        directory = (
            self.output_directory
            or (self.project_path.parent if self.project_path else self.input_directory)
            or Path.cwd()
        )
        selected, _ = QFileDialog.getSaveFileName(
            self,
            self.t("Export JSON…"),
            str(directory / f"{export_family(Path(document.name).stem, identity)}.json"),
            self.t("Export assets (*.json *.png);;Scene JSON (*.json);;All files (*)"),
            "",
            QFileDialog.Option.DontConfirmOverwrite,
        )
        if not selected:
            return
        destination = Path(selected)
        if destination.suffix.lower() == ".png":
            destination = destination.with_suffix(".json")
        elif destination.suffix.lower() != ".json":
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
                replace(frozen, json_documents=frozen_catalog.documents)
                if frozen_catalog
                else frozen
            )
            from dale.alchemist import export_session
            from dale.export_height import normalize_wall_heights

            include_da, normalization = self.json_contours != "regular", self.height_normalization
            only_da = self.json_contours == "alchemist"

            def prepare_payload(report):
                report(10, "Preparing contour categories")
                source = export_session(native_session, include_da, only_alchemist=only_da)
                report(45, "Preparing Scene JSON")
                payload = (
                    repaired_json_bytes(source)[0]
                    if source.source.json_bytes is not None
                    else current_contours_document(source).data
                )
                report(85, "Applying export heights")
                return normalize_wall_heights(payload, normalization)

            payload = run_task(self, "Preparing Scene JSON", prepare_payload)
            destination = write_json_copy(
                payload, destination, sources, conflict=self.confirm_export_file
            )
            self.remember_directory("output", destination.resolve().parent)
            self.information(
                "JSON exported",
                self.t(
                    "Current set contours exported.\n{path}",
                    path=destination,
                ),
            )
        except ExportCancelled:
            return
        except Exception as exc:
            self.warning("Cannot export scene JSON", str(exc))

    def set_brush(self, mode, value):
        self.view.raster_diameters[mode] = value
        self.view.viewport().update()

    def set_raster_offset(self, value):
        self.view.raster_aids.configure(raster_offset=value)
        self.view.geometry_key = None
        self.view.refresh()
        self.update_map_info()

    def set_guide_editing(self, enabled):
        self.activate_mode(
            "Move guides" if enabled else self.last_tool_modes[self.current_tool_set]
        )

    def sync_raster_aids(self):
        if not hasattr(self, "crosshair_action"):
            return
        settings = self.view.raster_aids.settings
        can_edit_guides = bool(
            self.view.session and self.view.session.source.image_path and settings["rulers"]
        )
        if can_edit_guides and settings["move_guides"] and self.view.mode != "Move guides":
            self.activate_mode("Move guides")
            return
        if self.view.mode == "Move guides" and not (can_edit_guides and settings["move_guides"]):
            self.view.set_mode("Pan")
            self.activate_mode(self.last_tool_modes[self.current_tool_set])
            return
        self.raster_contour_offset.blockSignals(True)
        self.raster_contour_offset.setValue(settings["raster_offset"])
        self.raster_contour_offset.blockSignals(False)
        for command, key in (
            (self.crosshair_action, "crosshair"),
            (self.rulers_action, "rulers"),
            (self.isolate_raster_action, "isolate_regions"),
            (self.native_resolution_action, "full_resolution"),
            (self.grid_action, "export_grid_visible"),
        ):
            command.blockSignals(True)
            command.setChecked(settings[key])
            command.setEnabled(bool(self.view.session and self.view.session.source.image_path))
            command.blockSignals(False)
        self.move_guides_action.setChecked(settings["rulers"] and settings["move_guides"])
        self.move_guides_action.setEnabled(
            bool(self.view.session and self.view.session.source.image_path and settings["rulers"])
        )
        aids = self.view.raster_aids
        aids.corner.setText(
            self.t({"px": "px", "ft": "ft", "cm": "cm", "mm": "mm"}[settings["unit"]])
        )
        aids.corner.setToolTip(
            self.t(
                {"px": "Source pixels", "ft": "Feet", "cm": "Centimeters", "mm": "Millimeters"}[
                    settings["unit"]
                ]
            )
        )
        for bar in aids.rulers:
            bar.setToolTip(
                self.control_help(
                    "Drag from this ruler to create a scene-anchored guide.",
                    title="Raster rulers",
                    keys=[
                        "Ctrl+drag a guide: move it; return it to a ruler to delete.",
                        "Escape: cancel the guide drag.",
                    ],
                )
            )
        aids.repaint()

    def set_scene_grid_visible(self, enabled):
        self.view.raster_aids.configure(export_grid_visible=enabled)
        self.update_map_info()
        if enabled and self.view.export_grid_frame is None:
            self.show_tool_settings("Scene grid")

    def set_raster_isolation(self, enabled):
        self.view.raster_aids.configure(isolate_regions=enabled)
        self.view.update_image()

    def native_preview_failed(self, message):
        self.view.raster_aids.configure(full_resolution=False)
        self.warning("Native raster resolution", message)

    def select_tool_set(self, key, activate=True):
        if key == "alchemist" and not (self.view.session and self.view.session.alchemist):
            key = "figures"
        changed = key != self.current_tool_set
        if changed and key == "alchemist" and not getattr(self, "_entering_da_mode", False):
            self.enter_alchemist_mode(activate)
            return
        if changed:
            self._figure_controls_key = None
            self.view.cancel_pending()
        self.switch_region_selection(key)
        self.left_panel.show()
        self.show_sidebar("project")
        self.current_tool_set = key
        self.view.figure_selection = key in ("figures", "alchemist")
        self.view.selection_section = key
        self.sync_raster_aids()
        self.view.contour_selection_context = key == "geometry"
        if self.view.session and self.view.raster_aids.settings["isolate_regions"]:
            self.view.update_image()
        self.apply_section_alignment()
        self.view.update_hover()
        self.update_clipboard_actions()
        self.tool_stack.setCurrentIndex(
            {"geometry": 0, "figures": 1, "regions": 2, "pixels": 3, "alchemist": 4}[key]
        )
        self.tool_stack.setFixedHeight(self.tool_stack.currentWidget().sizeHint().height())
        self.update_size_help()
        self.tool_set_actions[key].setChecked(True)
        self.tool_set_toolbar.refresh_tabs()
        self.sync_mode_shortcuts()
        if activate:
            self.activate_mode(self.last_tool_modes[key])
        if changed:
            self.rebuild_group_controls()
            if self.view.session and self.view.session.alchemist:
                self._alchemist_navigation = True
                try:
                    self.refresh()
                finally:
                    self._alchemist_navigation = False

    def sync_mode_shortcuts(self):
        modes = {
            "alchemist": ("Select figures", None, "Rotate figures"),
            "geometry": ("Edit points", None, None),
            "figures": ("Select figures", "Move figures", "Rotate figures"),
            "regions": ("Select regions", "Move regions", "Rotate regions"),
            "pixels": ("Select raster regions", "Move raster regions", "Rotate raster regions"),
        }
        bindings = dict(zip(modes[self.current_tool_set], ("S", "M", "R"), strict=True))
        for mode, command in self.mode_actions.items():
            command.setShortcut(bindings.get(mode, ""))
            parts = command.property("dale_tooltip_parts")
            if parts:
                command.setToolTip(
                    format_tooltip(
                        parts,
                        self.language,
                        command.shortcut(),
                        condition=command.property("dale_tooltip_condition"),
                        keys=command.property("dale_tooltip_keys") or [],
                        title=command.text(),
                        shortcut_label=command.text(),
                    )
                )

    def region_selection_state(self):
        return {
            "selected": self.selected_regions,
            "key": self.region_key,
            "detached": self.view.detached_selection,
            "pivot": self.view.region_pivot,
        }

    def switch_region_selection(self, key):
        section = "pixels" if key == "pixels" else "regions"
        if section == self._region_selection_section:
            return
        self._region_selection_states[self._region_selection_section] = (
            self.region_selection_state()
        )
        state = self._region_selection_states.get(section, {})
        self._region_selection_section = section
        self.selected_regions = state.get("selected", ())
        self.region_key = state.get("key")
        self.view.detached_selection = state.get("detached")
        self.view.region_pivot = state.get("pivot")
        self.view.region_polygons = ()
        self.view.selected_path = QPainterPath()

    def reset_region_selections(self):
        self._region_selection_states = {}
        self._region_selection_section = (
            "pixels" if self.current_tool_set == "pixels" else "regions"
        )
        self.selected_regions = None
        self.region_key = None
        self.view.detached_selection = None
        self.view.region_pivot = None
        self.view.region_polygons = ()
        self.view.selected_path = QPainterPath()

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

    def remember_active_dataset(self):
        if not self.project_path or not self.catalog:
            return
        try:
            save_project_dataset(self.preferences_path, self.project_path, self.catalog.active_key)
        except OSError:
            self.statusBar().showMessage(self.t("Preferences could not be written."), 7000)

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
        individual = self.view.individual_transform_enabled()
        for tool, ordinary, separate in (
            (
                "Rotate figures",
                "Rotate selected contour lines around their common center.",
                "Rotate selected objects around their own contour centers.",
            ),
            (
                "Scale figures",
                "Resize selected contour lines around their common center.",
                "Resize selected objects around their own contour centers.",
            ),
            (
                "Rotate regions",
                "Rotate selected region contours around their common center.",
                "Rotate selected objects around their own contour centers.",
            ),
            (
                "Rotate raster regions",
                "Rotate selected raster regions around their common center.",
                "Rotate selected objects around their own contour centers.",
            ),
            (
                "Scale raster regions",
                "Resize selected raster regions around their common center.",
                "Resize selected objects around their own contour centers.",
            ),
        ):
            action = self.mode_actions[tool]
            purpose = separate if self.view.individual_transform_enabled(tool) else ordinary
            action.setProperty("dale_tooltip_parts", [purpose])
            action.setToolTip(
                format_tooltip(
                    [purpose],
                    self.language,
                    action.shortcut(),
                    condition=action.property("dale_tooltip_condition"),
                    keys=action.property("dale_tooltip_keys") or [],
                    title=action.text(),
                    shortcut_label=action.text(),
                )
            )
            for button in (
                self.sized_tools.get(tool),
                getattr(self, "alchemist_tool_buttons", {}).get(tool),
            ):
                if isinstance(button, SizedToolButton):
                    button.set_help(self.language)
        for tool in ("Select figures", "Move figures"):
            action = self.mode_actions[tool]
            keys = list(action.property("dale_default_tooltip_keys") or [])
            parts = action.property("dale_default_tooltip_parts")
            if self.current_tool_set == "alchemist":
                parts = ["Click or drag a selection box to select whole DA objects."]
                keys = [
                    "Click or drag a selection box to select whole DA objects.",
                    "Escape: cancel the current gesture.",
                ]
                keys.append(
                    "Double-click: offer to select visible objects of the same exact type. "
                    "Right-click Select contours to change the remembered answer."
                )
                keys = list(dict.fromkeys([*keys, "Right-click: open tool settings."]))
            action.setProperty("dale_tooltip_parts", parts)
            action.setProperty("dale_tooltip_keys", keys)
            action.setToolTip(
                format_tooltip(
                    action.property("dale_tooltip_parts"),
                    self.language,
                    action.shortcut(),
                    condition=action.property("dale_tooltip_condition"),
                    keys=keys,
                    title=action.text(),
                    shortcut_label=action.text(),
                )
            )
        instructions = {
            "Pan": ["Left-drag: pan the scene image."],
            "Move guides": [
                "Drag a guide: move it.",
                "Double-click a guide: delete it.",
                "Escape: cancel the guide drag.",
            ],
            "Edit points": [
                "Click a line: insert a contour point. Drag a circle: move it.",
                "Double-click a circle: delete the point. Alt-drag: use enabled "
                "angle/contour alignment buttons; "
                "guides show anchors.",
                "Escape: cancel the current gesture.",
            ],
            "New line": [
                "Press, drag, release: draw a contour line.",
                "Alt: use the enabled alignment buttons.",
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
                "Right-click the circle button: adjust detail.",
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
                "Double-click: select or deselect all lines connected by shared vertices.",
                "Drag over 10 screen pixels: invert lines intersecting the box.",
                "Empty click clears selection.",
                "Escape: restore the selection from before dragging.",
            ],
            "Move figures": [
                "Drag selected contour lines: move. Ctrl+wheel: scale.",
                "Double-click: select only this contour; empty space clears selection, "
                "when enabled.",
                "Right-click: open tool settings.",
                "Escape: cancel the current gesture.",
            ],
            "Scale figures": [
                "Wheel: scale selected contours by the configured step.",
                "Ctrl+wheel: change this value.",
                "Number: contour scaling step, in percent. Shared with Move contours.",
                "Right-click: open tool settings.",
            ],
            "Rotate figures": [
                "Wheel: rotate selected contour lines by the configured step "
                "around their common center.",
                "Alt+wheel: rotate by the configured Alt step.",
                "The center label shows the total angle since this rotation started; "
                "negative is counterclockwise.",
            ],
            "Select raster regions": [
                "Click a region: select/deselect. Empty click: ask before clearing selection.",
                "Drag over 10 screen pixels: invert regions intersecting the box.",
                "Escape: restore the selection from before dragging.",
                "Raster inside/outside commands use selected regions only.",
            ],
            "Move regions": [
                "Drag selected regions: move. Ctrl+wheel: scale.",
                "Escape: cancel the current gesture.",
            ],
            "Rotate regions": [
                "Wheel: rotate selected regions by the configured step around their common center.",
                "Alt+wheel: rotate by the configured Alt step.",
                "The center label shows the total angle since this rotation started; "
                "negative is counterclockwise.",
            ],
            "Erase": [
                "Drag: erase raster pixels.",
                "Ctrl+wheel: change this tool's diameter.",
                "Alt+wheel: change feather width.",
                "Escape: cancel the current gesture.",
            ],
            "Restore": [
                "Drag: restore raster pixels.",
                "Ctrl+wheel: change this tool's diameter.",
                "Alt+wheel: change feather width.",
                "Escape: cancel the current gesture.",
            ],
            "Move raster regions": [
                "Drag selected regions: move. Ctrl+wheel: scale.",
                "Escape: cancel the current gesture.",
            ],
            "Rotate raster regions": [
                "Wheel: rotate selected regions by the configured step around their common center.",
                "Alt+wheel: rotate by the configured Alt step.",
            ],
            "Scale raster regions": ["Wheel: resize selected raster regions."],
        }[mode.removesuffix(" square") if mode in RASTER_BRUSHES else mode]
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
                    "The nearest vertex or common center is highlighted; "
                    "dragging keeps this point as the anchor."
                ),
                "Alt: use the enabled region point/guide alignment buttons.",
                (
                    "Ctrl+C: copy selected region contours. Ctrl+V: preview a copy; "
                    "click to place. Escape: cancel. Raster stays in place."
                ),
            ]
        if mode in FIGURE_TOOLS and mode != "Scale figures":
            instructions = [
                *instructions,
                (
                    "The nearest vertex or common center is highlighted and stays the grab point "
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
                "Right-click: open tool settings.",
            ]
        if (
            mode in ("Edit points", "New line", "New rectangle", *REGION_TOOLS, *FIGURE_TOOLS)
            and mode != "Scale figures"
        ):
            instructions = [
                *instructions,
                (
                    "With guide alignment enabled, hover stationary vertices while dragging "
                    "or placing. Their X/Y guides stay available until the gesture ends; "
                    "hold Alt to align."
                ),
            ]
        if individual and mode in ROTATE_TOOLS:
            instructions[0] = "Wheel: rotate each selected object around its own contour center."
        if individual and mode in (
            "Scale figures",
            "Scale raster regions",
            "Move regions",
            "Move figures",
        ):
            instructions = [
                *instructions,
                "Each selected object scales around its own contour center.",
            ]
        if self.current_tool_set == "alchemist" and mode in ("Select figures", "Move figures"):
            instructions = [
                *instructions,
                "Double-click: offer to select visible objects of the same exact type. "
                "Right-click Select contours to change the remembered answer.",
            ]
        if self.current_tool_set == "alchemist" and mode in (
            "Select figures",
            "Rotate figures",
            "Scale figures",
        ):
            instructions = [
                "Click or drag a selection box to select whole DA objects."
                if mode == "Select figures"
                else "Wheel: rotate each selected object around its own contour center."
                if mode == "Rotate figures"
                else "Wheel: resize each selected object around its own contour center.",
                "Object slices changes the selected whole objects.",
            ]
        lines = [self.mode_actions[mode].text(), *(self.t(line) for line in instructions)]
        lines.append(self.t("Right-drag: pan the scene image."))
        if mode not in (*ROTATE_TOOLS, "Scale figures", "Scale raster regions"):
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
        if self.current_tool_set == "alchemist" and mode not in (
            "Pan",
            "Move guides",
            "Select figures",
            "Rotate figures",
            "Scale figures",
        ):
            mode = "Select figures"
        if (
            not prompt
            and self.view.session
            and self.view.session.source.image_path
            and self.view.raster_aids.settings["rulers"]
            and self.view.raster_aids.settings["move_guides"]
        ):
            mode = "Move guides"
        if mode == "Move guides" and not (
            self.view.session
            and self.view.session.source.image_path
            and self.view.raster_aids.settings["rulers"]
        ):
            mode = self.last_tool_modes[self.current_tool_set]
        if mode in (*MOVE_TOOLS, *ROTATE_TOOLS, "Scale raster regions", "Scale figures") and prompt:
            if not (
                self.view.figure_line_ids if mode in FIGURE_TOOLS else self.selected_regions
            ) and not (mode == "Move figures" and self.view.figure_move_double_click):
                mode = (
                    "Select figures"
                    if mode in FIGURE_TOOLS
                    else "Select raster regions"
                    if mode in RASTER_TRANSFORM_TOOLS
                    else "Select regions"
                )
        if mode not in ("Pan", "Move guides"):
            key = (
                "pixels"
                if mode in (*RASTER_BRUSHES, "Select raster regions", *RASTER_TRANSFORM_TOOLS)
                else "figures"
                if mode in FIGURE_TOOLS
                else "regions"
                if mode in REGION_TOOLS
                else "geometry"
            )
            if self.current_tool_set == "alchemist" and mode in (*FIGURE_TOOLS, "Edit points"):
                key = "alchemist"
            self.last_tool_modes[key] = mode
            self.select_tool_set(key, activate=False)
        self.mode_actions[mode].setChecked(True)
        self.view.set_mode(mode)
        guide_editing = mode == "Move guides"
        if self.view.raster_aids.settings["move_guides"] != guide_editing:
            self.view.raster_aids.configure(move_guides=guide_editing)
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
            (self.figure_scale_control, self.view.figure_scale_step_percent),
            (
                self.alchemist_tool_buttons["Scale figures"].editor(),
                self.view.figure_scale_step_percent,
            ),
            (self.brush_control, self.view.raster_diameters["Erase"]),
            (self.restore_brush_control, self.view.raster_diameters["Restore"]),
            (self.square_brush_control, self.view.raster_diameters["Erase square"]),
            (self.square_restore_control, self.view.raster_diameters["Restore square"]),
            (self.geometry_brush_control, self.view.geometry_diameters["Erase lines"]),
            (self.vertex_brush_control, self.view.geometry_diameters["Erase vertices"]),
            (self.auto_close_control, self.view.auto_close_distance),
        ):
            control.blockSignals(True)
            control.setValue(value)
            control.blockSignals(False)
        self.remember_tool_values()

    def set_figure_scale_step(self, value):
        self.view.figure_scale_step_percent = value

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
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
            and hasattr(self, "thinning")
            and isinstance(watched, QWidget)
            and self.current_tool_set == "alchemist"
            and (
                watched is self.thinning_button
                or self.thinning_button.isAncestorOf(watched)
                or (
                    self.thinning.action.isChecked()
                    and watched in (self.view, self.view.viewport())
                )
            )
        ):
            delta = event.angleDelta().y() or event.angleDelta().x()
            if delta:
                self.thinning_value.stepBy(round(delta / 120) or (1 if delta > 0 else -1))
            event.accept()
            return True
        panel = getattr(self, "slice_window", None)
        if (
            panel
            and isinstance(watched, QWidget)
            and (watched is panel or panel.isAncestorOf(watched))
        ):
            return super().eventFilter(watched, event)
        if (
            event.type() == QEvent.Type.Wheel
            and isinstance(watched, QWidget)
            and watched.window() == self
            and hasattr(self, "top_panels_scroll")
            and self.top_panels_scroll.isAncestorOf(watched)
            and not event.modifiers()
            & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
        ):
            self.top_panels_scroll.scroll_wheel(event)
            return True
        if (
            event.type() == QEvent.Type.Wheel
            and isinstance(watched, QWidget)
            and watched.window() == self
            and event.modifiers() & Qt.KeyboardModifier.AltModifier
            and not event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            control = watched
            mode = self.view.mode
            while control is not None:
                if isinstance(control, SizedToolButton):
                    mode = control.defaultAction().property("dale_tool_key")
                    break
                control = control.parentWidget()
            if mode in RASTER_BRUSHES:
                delta = event.angleDelta().y() or event.angleDelta().x()
                self.view.adjust_raster_feather(mode, delta / 120)
                event.accept()
                return True
        if (
            self.group_manager
            and isinstance(watched, QWidget)
            and (watched is self.group_manager or self.group_manager.isAncestorOf(watched))
        ):
            return super().eventFilter(watched, event)
        if (
            event.type() == QEvent.Type.Wheel
            and isinstance(watched, QWidget)
            and watched.window() == self
            and self.view.mode in (*ROTATE_TOOLS, "Scale figures")
            and not event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            if self.view.mode == "Scale figures":
                self.view.scale_figures(event.angleDelta().y() / 120)
            else:
                self.view.rotate_wheel_event(event)
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
                    self.figure_scale_control,
                    self.alchemist_tool_buttons["Scale figures"].editor(),
                    self.brush_control,
                    self.restore_brush_control,
                    self.square_brush_control,
                    self.square_restore_control,
                    self.global_close_control,
                    self.geometry_brush_control,
                    self.vertex_brush_control,
                    self.auto_close_control,
                    self.snap_distance,
                    self.right_angle_tolerance,
                    self.contour_alignment_distance,
                    self.region_point_distance,
                    self.region_guide_distance,
                    self.figure_point_distance,
                    self.figure_guide_distance,
                    self.extension_distance,
                    self.gap_tolerance,
                    self.contour_offset,
                    self.raster_contour_offset,
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
            if self.current_tool_set in ("figures", "alchemist")
            else (self.region_alignment_actions, "Region")
            if self.current_tool_set == "regions"
            else (None, None)
        )
        self.view.snap_enabled = (
            actions[f"{prefix} point alignment"].isChecked()
            if actions
            else False
            if self.current_tool_set == "pixels"
            else self.snap_action.isChecked()
        )
        self.view.contour_alignment = (
            actions[f"{prefix} guide alignment"].isChecked()
            if actions
            else False
            if self.current_tool_set == "pixels"
            else self.alignment_actions["contour_alignment"].isChecked()
        )
        self.view.right_angle_alignment = (
            self.current_tool_set == "geometry"
            and self.alignment_actions["right_angle_alignment"].isChecked()
        )
        self.view.extension_alignment = (
            self.current_tool_set in ("figures", "alchemist")
            and self.figure_alignment_actions["Figure extension alignment"].isChecked()
        )
        self.view.snap = None
        self.view.extension_guide = None
        self.view.viewport().update()

    def alignment_ui_state(self):
        return {
            "snap_enabled": self.snap_action.isChecked(),
            "figure_move_double_click": self.view.figure_move_double_click,
            "individual_transform_settings": dict(self.view.individual_transform_settings),
            "right_angle_neighbours": self.view.right_angle_neighbours,
            "right_angle_own_priority": self.view.right_angle_own_priority,
            "figure_extension_alignment": self.figure_alignment_actions[
                "Figure extension alignment"
            ].isChecked(),
            "extension_connected": self.view.extension_connected,
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
        self.view.individual_transform_settings = dict(
            settings.get("individual_transform_settings", {})
        )
        self.view.figure_move_double_click = settings.get("figure_move_double_click", True)
        self.view.extension_connected = settings.get("extension_connected", False)
        self.figure_alignment_actions["Figure extension alignment"].setChecked(
            settings.get("figure_extension_alignment", False)
        )
        self.view.right_angle_neighbours = settings.get("right_angle_neighbours", True)
        self.view.right_angle_own_priority = settings.get("right_angle_own_priority", True)
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

    def new_project(self):
        if self.close_document():
            self.apply_dataset_manager(DatasetCatalog())

    def close_document(self):
        self._figure_live_ids = None
        if self.worker or not self.can_discard():
            return False
        self.view.clear_map()
        if self.slice_window:
            self.slice_window.clear_document()
        self.thinning.clear_document()
        self._group_render_cache = self._figure_controls_key = None
        self.custom_colors = DEFAULT_CUSTOM_COLORS
        self.reset_region_selections()
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
        self.update_project_info()
        self.diagnostics.clear()
        self.update_map_info()
        return True

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
        self.flush_slice_window()
        if not self.view.session:
            return True
        if self.saved_state is not None and self.document_state() == self.saved_state:
            return True
        if self.saved_state is None and not self.view.session.operations and not self.catalog:
            return True
        answer = self.question(
            "Save changes?",
            "Save the project before continuing?",
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
            ), self.custom_colors
        return (
            tuple(session.operations),
            tuple(session.future),
            session.origin,
            session.gap_tolerance,
            self._project_tool_values["artwork_offset_px"]
            if self.use_global_tool_settings and self._project_tool_values is not None
            else session.contour_offset,
            self.custom_colors,
            session.alchemist,
        )

    def ui_state(self):
        center = self.view.camera_center()
        region_states = {
            **self._region_selection_states,
            self._region_selection_section: self.region_selection_state(),
        }
        region_key = tuple(p.wkb for p in self.available_regions())
        section_selections = {}
        for section in ("regions", "pixels"):
            state = region_states.get(section, {})
            frozen = state.get("detached")
            valid_frozen = bool(
                frozen and self.view.session and frozen["geometry"] == self.view.session.geometry()
            )
            section_selections[section] = (
                state.get("selected", ()) if valid_frozen or state.get("key") == region_key else ()
            )
        detached = region_states.get("regions", {}).get("detached")
        selection = None
        if detached and self.view.session and detached["geometry"] == self.view.session.geometry():
            selection = {
                "lines": list(detached["line_ids"]),
                "polygons": [p.wkb_hex for p in detached["polygons"]],
                "pivot": list(
                    region_states["regions"].get("pivot")
                    or detached["polygons"][0].centroid.coords[0]
                ),
            }
        raster_settings = self.view.raster_aids.snapshot()
        raster_detached = region_states.get("pixels", {}).get("detached")
        raster_settings["selection"] = None
        if (
            raster_detached
            and self.view.session
            and raster_detached["geometry"] == self.view.session.geometry()
        ):
            raster_settings["selection"] = {
                "lines": list(raster_detached["line_ids"]),
                "polygons": [p.wkb_hex for p in raster_detached["polygons"]],
                "pivot": list(
                    region_states["pixels"].get("pivot")
                    or raster_detached["polygons"][0].centroid.coords[0]
                ),
            }
        return {
            "raster_aids": raster_settings,
            "raster_brushes": brush_settings(self.view.raster_brushes),
            "raster_erase_square_diameter": self.view.raster_diameters["Erase square"],
            "raster_restore_square_diameter": self.view.raster_diameters["Restore square"],
            **group_ui_state(self.catalog.current.ui if self.catalog else {}),
            "groups": [group.encode() for group in self.all_selection_groups()],
            "active_group": self.active_selection_group(),
            "detached_region_selection": selection,
            "figure_lines": list(self.view.figure_line_ids),
            "figure_pivot": list(self.view.figure_pivot) if self.view.figure_pivot else None,
            "raster_erase_diameter": self.view.raster_diameters["Erase"],
            "raster_restore_diameter": self.view.raster_diameters["Restore"],
            "export_regions": self.selected_regions,
            "section_region_selections": section_selections,
            "move_related_lines": self.view.move_related,
            "mode": self.view.mode,
            "show_walls": self.view.show_walls,
            "zoom": self.view.transform().m11(),
            "center": [center.x(), center.y()],
            **{key: control.value() for key, control in self.rotation_value_controls.items()},
            "auto_close_distance_px": self.view.auto_close_distance,
            "global_close_distance_px": self.global_close_control.value(),
            "language": self.language,
            **self.alignment_ui_state(),
            "snap_distance_px": self.view.snap_distance,
            "circle_detail_steps": self.view.circle_detail_steps,
            "figure_scale_step_percent": self.view.figure_scale_step_percent,
            "right_angle_tolerance_deg": self.view.right_angle_tolerance_deg,
            "contour_alignment_distance_px": self.view.contour_alignment_distance_px,
            "extension_distance_px": self.view.extension_distance_px,
            "line_eraser_diameter": self.view.geometry_diameters["Erase lines"],
            "vertex_eraser_diameter": self.view.geometry_diameters["Erase vertices"],
            "tool_set": self.current_tool_set,
            "artwork_offset_px": self.contour_offset.value(),
            "safe_json_repair": self.view.safe_json_repair,
            "source_layer": self.view.source_layer,
        }

    def update_clipboard_actions(self):
        if hasattr(self, "alchemist_same_type_action"):
            self.alchemist_same_type_action.setEnabled(
                bool(
                    self.current_tool_set == "alchemist"
                    and self.view.session
                    and self.view.session.alchemist
                    and self.view.figure_line_ids
                    and not self.worker
                    and not self.view.active_gesture
                )
            )
        if self.group_manager and self.group_manager.isVisible():
            self.group_manager.update_actions()
        if not hasattr(self, "paste_regions_action"):
            return
        figures = self.current_tool_set in ("figures", "alchemist")
        paste_figures = figures or (
            self.current_tool_set not in ("figures", "alchemist", "regions")
            and self._clipboard_section == "figures"
        )
        if hasattr(self, "select_all_action"):
            contours = self.current_tool_set in ("geometry", "figures", "alchemist")
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
                "Paste contours" if paste_figures else "Paste region contours",
            ),
        ):
            if command.property("dale_display_key") != caption:
                command.setProperty("dale_display_key", caption)
            if command.text() != self.t(caption):
                command.setText(self.t(caption))
            parts = command.property("dale_default_tooltip_parts")
            if parts:
                contour_subject = figures if command == self.copy_regions_action else paste_figures
                if contour_subject and command == self.copy_regions_action:
                    parts = ["Copy selected contour lines. Image pixels stay in place."]
                elif contour_subject:
                    parts = ["Place copied contour lines. Image pixels stay in place."]
                condition = (
                    "Contours is active, a line is selected "
                    "and no gesture or export is in progress."
                    if contour_subject and command == self.copy_regions_action
                    else "Contour lines have been copied to the application clipboard."
                    if contour_subject
                    else "Regions is active, a region is selected "
                    "and no gesture or export is in progress."
                    if command == self.copy_regions_action
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
        copy_enabled = (
            available
            and not self.worker
            and not self.view.active_gesture
            and bool(self.view.figure_line_ids if figures else self.selected_regions)
        )
        paste_enabled = bool(
            self.view.session
            and self.view.region_clipboard is not None
            and not self.worker
            and self.current_tool_set != "alchemist"
        )
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
        self.update_main_delete_action()
        for command in self.mirror_contour_actions.values():
            enabled = bool(
                copy_enabled and figures and not self.worker and not self.view.active_gesture
            )
            if command.isEnabled() != enabled:
                command.setEnabled(enabled)
        if hasattr(self, "mask_actions"):
            mask_enabled = bool(
                self.view.session
                and self.view.session.source.image_path
                and self.view.region_polygons
                and self.current_tool_set not in ("figures", "alchemist")
                and not self.view.active_gesture
                and not self.worker
            )
            for command in self.mask_actions.values():
                if command.isEnabled() != mask_enabled:
                    command.setEnabled(mask_enabled)

    def mirror_contours(self, axis):
        if (
            not self.view.session
            or self.current_tool_set != "figures"
            or not self.view.figure_line_ids
            or self.worker
            or self.view.active_gesture
        ):
            return
        try:
            self.view.transform_regions(mirror=axis)
        except ValueError as exc:
            self.warning("Cannot transform contours", str(exc))

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
        pointer = self.view.pointer_scene_point()
        if pointer is not None:
            self.view.cursor_point = pointer
        self.view.copy_selected_regions()

    def capture_contour_clipboard(self):
        if self.view.region_clipboard is not None:
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
            self.contour_clipboard.alchemist = self.view.session.alchemist
            self.view.clipboard_alchemist = self.view.session.alchemist
            self.contour_clipboard.store(
                self.view.region_clipboard,
                self.view.clipboard_source,
                self._clipboard_documents,
                "figures" if self.view.figure_selection else "regions",
            )

    def restore_contour_clipboard(self):
        self.view.clipboard_alchemist = getattr(self.contour_clipboard, "alchemist", None)
        if self.contour_clipboard.content is not None:
            if self.view.paste_delta is not None:
                self.view.cancel_pending()
            (
                self.view.region_clipboard,
                self.view.clipboard_source,
                self._clipboard_documents,
                self._clipboard_section,
            ) = self.contour_clipboard.content
        self.update_clipboard_actions()

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
        if self.current_tool_set == "alchemist":
            return
        try:
            self.clipboard_source_additions()
            if self.current_tool_set not in ("figures", "alchemist", "regions"):
                self.activate_mode(
                    "Select figures" if self._clipboard_section == "figures" else "Select regions"
                )
            elif self.view.mode not in TRANSFORM_TOOLS:
                self.activate_mode(
                    "Select figures"
                    if self.current_tool_set in ("figures", "alchemist")
                    else "Select regions"
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
        self.flush_slice_window()
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
        self.rebuild_group_controls()

    def all_selection_groups(self):
        value = self.catalog.current.ui.get("groups") if self.catalog else None
        if value is not self._groups_value:
            self._groups_cache = decode_groups(value or [])
            self._groups_value = value
        return self._groups_cache if value is not None else ()

    def selection_groups(self):
        sections = self.catalog.current.ui.get("group_sections", {}) if self.catalog else {}
        return tuple(
            g
            for g in self.all_selection_groups()
            if sections.get(g.id, "regions") == self.current_tool_set
        )

    def active_selection_group(self):
        if not self.catalog:
            return None
        ui = self.catalog.current.ui
        identifier = ui.get("section_active_groups", {}).get(
            self.current_tool_set, ui.get("active_group")
        )
        return identifier if identifier in {g.id for g in self.selection_groups()} else None

    def set_active_selection_group(self, identifier):
        if identifier is not None and identifier not in {g.id for g in self.selection_groups()}:
            return False
        ui = self.catalog.current.ui
        choices = group_ui_state(ui)["section_active_groups"]
        choices[self.current_tool_set] = identifier
        ui.update(active_group=identifier, section_active_groups=choices)
        return True

    def resolved_group_members(self, identifier):
        if not self.view.session:
            return frozenset()
        group = next((g for g in self.selection_groups() if g.id == identifier), None)
        members = group_members(group, self.view.editing_geometry()) if group else frozenset()
        return frozenset(self.view.whole_da_selection(members))

    def group_selection_ids(self):
        if not self.view.session:
            return frozenset()
        geometry = self.view.editing_geometry()
        if self.current_tool_set in ("figures", "alchemist"):
            selected = self.view.figure_line_ids
        elif self.current_tool_set == "geometry":
            selected = self.view.contour_line_ids
        elif self.current_tool_set == "pixels":
            return frozenset(
                identifier
                for cell in self.selected_raster_cells()
                for ring in (cell.shell, *cell.holes)
                for identifier in ring
            )
        else:
            return boundary_members(geometry, self.view.region_polygons)
        return frozenset(selected) & {r.id for r in geometry.lineage}

    def selected_raster_cells(self):
        selected = set(self.view.region_polygons)
        return tuple(
            cell for cell, polygon in self.view.raster_region_entries() if polygon in selected
        )

    def store_selection_groups(self, groups):
        self.view.finish_rotation()
        if not self.catalog:
            catalog = DatasetCatalog(self.view.session, self.project_ui_state())
            self.catalog = catalog
            if not self.view.session:
                self.show_catalog_view(
                    catalog.current, load_preview(catalog.current.session.source), False
                )
        state = group_ui_state(self.catalog.current.ui)
        current_ids = {g.id for g in self.selection_groups()}
        others = tuple(g for g in self.all_selection_groups() if g.id not in current_ids)
        encoded = [g.encode() for g in (*others, *groups)]
        decode_groups(encoded)
        live = {g["id"] for g in encoded}
        sections = {i: section for i, section in state["group_sections"].items() if i in live}
        sections.update({g.id: self.current_tool_set for g in groups})
        choices = {
            section: identifier if identifier in live else None
            for section, identifier in state["section_active_groups"].items()
        }
        self.catalog.current.ui.update(
            groups=encoded,
            group_sections=sections,
            section_active_groups=choices,
            active_group=choices[self.current_tool_set],
        )
        self.rebuild_dataset_controls()
        self.update_group_rendering()

    def create_selection_group(self):
        if self.worker or self.view.active_gesture:
            return
        groups = self.selection_groups()
        if len(self.all_selection_groups()) >= 256:
            return
        index, names = 1, {g.name for g in groups}
        while self.t("Group {number}", number=index) in names:
            index += 1
        group = SelectionGroup.create(self.t("Group {number}", number=index))
        self.store_selection_groups((*groups, group))
        self.set_active_selection_group(group.id)
        self.rebuild_group_controls()

    def update_selection_group(self, identifier, **values):
        self.store_selection_groups(
            tuple(
                replace(g, **values) if g.id == identifier else g for g in self.selection_groups()
            )
        )

    def reorder_selection_group(self, identifier, index):
        if self.worker or self.view.active_gesture:
            return
        groups = list(self.selection_groups())
        group = next((g for g in groups if g.id == identifier), None)
        if group is None or not 0 <= index < len(groups):
            return
        groups.remove(group)
        groups.insert(index, group)
        if tuple(groups) != self.selection_groups():
            self.store_selection_groups(tuple(groups))

    def rename_selection_group(self, identifier):
        group = next(g for g in self.selection_groups() if g.id == identifier)
        name, accepted = QInputDialog.getText(
            self, self.t("Rename group"), self.t("Group name"), text=group.name
        )
        if accepted and name.strip():
            try:
                self.update_selection_group(identifier, name=name.strip())
            except ValueError as exc:
                self.warning("Cannot update group", str(exc))

    def change_group_color(self, identifier):
        group = next(g for g in self.selection_groups() if g.id == identifier)
        color = self.choose_project_color(QColor(group.color), self.t("Group color"))
        if color.isValid():
            self.update_selection_group(identifier, color=color.name())

    def choose_project_color(self, initial, title):
        for index, color in enumerate(self.custom_colors):
            QColorDialog.setCustomColor(index, QColor(color))
        try:
            return QColorDialog.getColor(
                initial, self, title, QColorDialog.ColorDialogOption.DontUseNativeDialog
            )
        finally:
            # Palette editing is independent of accepting the selected object color.
            self.custom_colors = tuple(
                QColorDialog.customColor(index).name(QColor.NameFormat.HexArgb)
                for index in range(QColorDialog.customCount())
            )

    def delete_selection_group(self, identifier):
        group = next(g for g in self.selection_groups() if g.id == identifier)
        answer = self.question(
            "Delete group",
            self.t('Delete group "{name}"? Scene elements will remain.', name=group.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.store_selection_groups(
                tuple(g for g in self.selection_groups() if g.id != identifier)
            )

    def assign_selection_group(self, identifier, add):
        from dale.raster_transform import assign_cells

        if self.worker or self.view.active_gesture:
            return
        selected = self.group_selection_ids()
        if not selected:
            return
        groups = self.selection_groups()
        priority = max((g.priority for g in groups), default=0) + 1
        # Renumber the bounded group list before its counter could overflow.
        if priority > 1_000_000_000:
            ranks = {g.id: i for i, g in enumerate(sorted(groups, key=lambda g: g.priority))}
            groups = tuple(replace(g, priority=ranks[g.id]) for g in groups)
            priority = len(groups)
        self.store_selection_groups(
            tuple(
                replace(
                    (
                        assign_cells(
                            g, self.view.raster_region_entries(), self.selected_raster_cells(), add
                        )
                        if self.current_tool_set == "pixels"
                        else assign_region_cells(
                            g,
                            self.view.editing_geometry(),
                            self.view.region_polygons,
                            self.available_regions(),
                            add,
                        )
                        if self.current_tool_set == "regions"
                        else assign_group(g, self.view.session.geometry(), selected, add)
                    ),
                    priority=priority if add else g.priority,
                )
                if g.id == identifier
                else g
                for g in groups
            )
        )

    def choose_selection_group(self, index):
        self.select_selection_group(self.group_control.itemData(index))

    def select_selection_group(self, identifier):
        if not self.catalog or self.worker or self.view.active_gesture:
            self.rebuild_group_controls()
            return
        self.view.finish_rotation()
        before = self.raster_selection_snapshot()
        if not self.set_active_selection_group(identifier):
            return
        if identifier is not None:
            members = self.resolved_group_members(identifier)
            if self.current_tool_set in ("figures", "alchemist"):
                self.view.figure_line_ids = tuple(sorted(members))
                self.view.figure_pivot = None
            elif self.current_tool_set == "geometry":
                self.view.contour_line_ids = tuple(sorted(members))
                self.view.update_hover()
            else:
                self.view.detached_selection = None
                self.view.region_pivot = None
                polygons = self.available_regions()
                self.update_map_info()
                group = next(g for g in self.selection_groups() if g.id == identifier)
                if self.current_tool_set == "pixels":
                    from dale.raster_transform import group_cells

                    entries = self.view.raster_region_entries()
                    wanted = group_cells(group, entries)
                    self.selected_regions = tuple(
                        i for i, (cell, _) in enumerate(entries) if cell in wanted
                    )
                else:
                    self.selected_regions = matched_cells(
                        group, self.view.editing_geometry(), polygons
                    )
            self.update_map_info()
            self.record_raster_selection(before)
        self.rebuild_group_controls()
        self.update_group_rendering()

    def rebuild_group_controls(self):
        self.group_heading.setText(self.t("Groups"))
        self.group_manager_button.setAccessibleName(self.t("Group manager"))
        self.group_manager_button.setToolTip(
            self.control_help(
                "Show or hide the floating group manager and group colors.", title="Group manager"
            )
        )
        self.group_control.setToolTip(
            self.control_help(
                "Select a group's elements. Each section of this dataset has its own groups.",
                title="Groups",
            )
        )
        self.group_control.blockSignals(True)
        self.group_control.clear()
        self.group_control.addItem(self.t("All group colors"), None)
        for group in self.selection_groups():
            self.group_control.addItem(group.name, group.id)
            self.group_control.setItemData(
                self.group_control.count() - 1, QColor(group.color), Qt.ItemDataRole.DecorationRole
            )
        self.group_control.setCurrentIndex(
            max(0, self.group_control.findData(self.active_selection_group()))
        )
        self.group_control.blockSignals(False)
        self.group_control.setEnabled(bool(self.selection_groups()) and not self.worker)
        if self.group_manager:
            self.group_manager.rebuild()
        self.update_group_rendering()

    def toggle_group_manager(self, checked=False):
        self.view.finish_rotation()
        if self.group_manager and self.group_manager.isVisible():
            self.group_manager.hide()
            return
        if self.group_manager is None:
            self.group_manager = GroupManager(self)
            viewport = self.view.viewport()
            point = viewport.mapFromGlobal(
                self.group_manager_button.mapToGlobal(QPoint(self.group_manager_button.width(), 0))
            )
            self.group_manager.constrain_position(point, dock=False)
        self.group_manager.rebuild()
        self.group_manager.show()
        self.group_manager.raise_()

    def update_group_rendering(self):
        self._group_render_cache = None
        self.view.viewport().update()

    def group_overlay(self):
        if not self.group_manager or not self.group_manager.isVisible() or not self.view.session:
            return (), ()
        from dale.canvas import line_path

        if self.current_tool_set == "pixels":
            from dale.raster_transform import group_cells

            entries = self.view.raster_region_entries(preview=True)
            groups = self.selection_groups()
            active = self.active_selection_group()
            key = entries, groups, active, self.view.region_polygons, self.view.show_walls
            if self._group_render_cache and key == self._group_render_cache[0]:
                return self._group_render_cache[1]
            colors = {}
            for group in sorted(groups, key=lambda g: (g.id == active, g.priority)):
                colors.update({cell: group.color for cell in group_cells(group, entries)})
            result = (
                tuple(
                    (polygon_path(p), colors[cell])
                    for cell, p in entries
                    if cell in colors and self.view.show_walls
                ),
                tuple(
                    (polygon_path(p), colors[cell])
                    for cell, p in entries
                    if cell in colors and p in self.view.region_polygons
                ),
            )
            self._group_render_cache = key, result
            return result

        geometry = self.view.editing_geometry()
        groups = self.selection_groups()
        active = self.active_selection_group()
        selected = (
            self.view.region_polygons if self.current_tool_set in ("regions", "pixels") else ()
        )
        highlight = frozenset(
            self.view.figure_line_ids
            if self.current_tool_set in ("figures", "alchemist")
            else self.view.contour_line_ids
            if self.current_tool_set == "geometry"
            else ()
        )
        key = (
            geometry,
            geometry.lineage,
            geometry.ancestry,
            groups,
            active,
            tuple(p.wkb for p in selected),
            self.view.show_walls,
            highlight,
        )
        if self._group_render_cache and key == self._group_render_cache[0]:
            return self._group_render_cache[1]
        colors, fills = {}, {}
        for group in sorted(groups, key=lambda g: (g.id == active, g.priority)):
            members = group_members(group, geometry)
            colors.update({i: group.color for i in members})
            for i in matched_cells(group, geometry, selected):
                fills[i] = group.color
        paths = {}
        for edge, record in zip(
            geometry_edges(geometry.walls, geometry.closures), geometry.lineage, strict=True
        ):
            if record.id in colors and (self.view.show_walls or record.id in highlight):
                paths.setdefault(colors[record.id], []).append(edge)
        result = (
            tuple((line_path(edges), color) for color, edges in paths.items()),
            tuple((polygon_path(selected[i]), color) for i, color in fills.items()),
        )
        self._group_render_cache = key, result
        return result

    def manage_datasets(self):
        self.view.finish_rotation()
        if self.worker or self.view.active_gesture:
            self.information("Finish editing", "Finish or cancel the active gesture first.")
            return
        dialog = None
        try:
            from dale.dataset_manager import DatasetManager

            if self.catalog:
                self.catalog.capture(self.project_ui_state())
            dialog = DatasetManager(self)
            dialog.exec()
        except Exception as error:
            self.warning("Dataset manager", str(error))
        finally:
            if dialog is not None:
                dialog.deleteLater()
            self.release_json_workspaces(keep_current=True)

    def apply_dataset_manager(self, catalog, open_id=None):
        from dale.alchemist_progress import prepare_project_view, run_task

        previous_catalog = self.catalog
        previous_preview = self.view.preview
        previous_ui = self.project_ui_state()
        previous_id = self.catalog.active_key if self.catalog else None
        identifier = open_id or (previous_id if previous_id in catalog.views else catalog.base_key)
        candidate = catalog.fork()
        previous_source = self.view.session.source if self.view.session else None
        published = False
        try:

            def prepare(report):
                report(5, "Preparing project state")
                candidate.activate(identifier)
                candidate.prepare()
                session = candidate.current.session
                section = candidate.current.ui.get("tool_set", previous_ui["tool_set"])
                reuse = (
                    previous_source is not None
                    and previous_source.image_path == session.source.image_path
                    and previous_source.size == session.source.size
                )
                return prepare_project_view(
                    session,
                    section,
                    tuple(candidate.documents),
                    report,
                    (lambda _source: previous_preview) if reuse else load_preview,
                )

            def publish(result):
                nonlocal published
                preview, prepared, da_cache = result
                self.catalog = candidate
                published = True
                self.show_catalog_view(
                    candidate.current, preview, True, prepared=(prepared, da_cache)
                )

            run_task(
                self,
                "Applying dataset changes",
                prepare,
                publish,
                object_name="datasetApplyProgress",
                publish_refresh=True,
            )
            return True
        except Exception as exc:
            self.catalog = previous_catalog
            if published and previous_catalog:
                old = replace(previous_catalog.current, ui=previous_ui)
                self.show_catalog_view(old, previous_preview, True)
            elif published:
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

    def show_catalog_view(self, draft, preview, existing, *, prepared=None):
        self.view.safe_json_repair = False
        if prepared is not None:
            analysis, da_cache = prepared
            self.view.selection_section = draft.ui.get("tool_set", self.current_tool_set)
            self.view.property_documents = self.catalog.documents
            self.view._alchemist_contour_analysis_cache = da_cache
            if analysis:
                visible, combined, analyses, choices = analysis
                self.view._alchemist_analysis_cache = visible
                self.view._alchemist_prepared_analyses = analyses
                if combined is not None:
                    draft.session._analysis_cache = combined
                geometry = draft.session.geometry()
                self.view._source_layers_cache = (
                    draft.session.source,
                    (
                        None,
                        geometry.lineage,
                        geometry.ancestry,
                        geometry.wall_styles,
                        tuple(self.catalog.documents),
                        draft.session.alchemist.objects,
                    ),
                    choices,
                )
        self.view.assign(draft.session, preview)
        self.reset_region_selections()
        settings = {**self.project_ui_state(), **draft.ui}
        self.view.raster_aids.restore(draft.ui.get("raster_aids"))
        self.view.raster_brushes = brush_settings(draft.ui.get("raster_brushes"))
        self.sync_raster_aids()
        if "section_region_selections" not in draft.ui:
            settings.pop("section_region_selections", None)
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
        self.select_tool_set(settings.get("tool_set", "geometry"), activate=False)
        self.activate_mode(settings.get("mode", "Edit points"), prompt=False)
        self.refresh()
        self.restore_region_selection(settings)
        self.update_map_info()
        self.update_project_info()
        self.rebuild_dataset_controls()
        self.update_clipboard_actions()
        self.restore_camera(settings)
        self.remember_active_dataset()

    def restore_camera(self, settings):
        if "zoom" in settings:
            zoom = self.view.bounded_zoom(settings["zoom"])
            self.view.setTransform(QTransform.fromScale(zoom, zoom))
        if "center" in settings:
            self.view.centerOn(*settings["center"])
        self.view.update_hover()

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
        if self.defer_slice_action(lambda: self.save_project_file(checked, save_as)):
            return False
        self.view.finish_rotation()
        if not self.view.session:
            return False
        if self.view.active_gesture:
            self.information("Finish editing", "Finish the active drag before saving.")
            return False
        path = self.project_path
        if path is None or save_as:
            filename = (
                path.stem
                if path
                else Path(
                    self.catalog.base_session.source.name
                    if self.catalog
                    else self.view.session.source.name
                ).stem
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
            from dale.alchemist_progress import run_task
            from dale.project_io import publish_saved_state, snapshot_project

            frozen, catalog = snapshot_project(project_session, self.catalog)
            colors = list(self.custom_colors)

            def write_project(report):
                save_project(
                    frozen, path, project_ui, catalog=catalog, custom_colors=colors, progress=report
                )

            run_task(self, "Saving DALE project", write_project, object_name="projectSaveProgress")
            publish_saved_state(project_session, self.catalog, frozen, catalog)
            self.remember_directory("output", path.parent)
            self.project_path = path
            self.saved_state = self.document_state()
            self.remember_recent_project(path)
            self.remember_active_dataset()
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
        from dale.alchemist_progress import prepare_project_view, run_task

        loaded = None
        was_applying = self._applying_tool_values
        self._applying_tool_values = True
        try:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            remembered = load_project_dataset(self.preferences_path, path)

            def prepare(report):
                candidate = load_project(path, progress=report)
                try:
                    candidate.catalog = DatasetCatalog.from_catalog(candidate.catalog)
                    if remembered in candidate.catalog.views:
                        candidate.catalog.activate(remembered)
                    candidate.session = candidate.catalog.current.session
                    candidate.ui_state = candidate.catalog.current.ui
                    preview, prepared, da_cache = prepare_project_view(
                        candidate.session,
                        candidate.ui_state["tool_set"],
                        tuple(candidate.catalog.documents),
                        report,
                        load_preview,
                    )
                    return candidate, preview, prepared, da_cache
                except Exception:
                    candidate.close()
                    raise

            def publish(result):
                nonlocal loaded
                loaded, preview, prepared, da_cache = result
                self.view._alchemist_contour_analysis_cache = da_cache
                if prepared:
                    visible, combined, analyses, _ = prepared
                    self.view._alchemist_analysis_cache = visible
                    self.view._alchemist_prepared_analyses = analyses
                    if combined is not None:
                        loaded.session._analysis_cache = combined
                    self.view.selection_section = loaded.ui_state["tool_set"]
                self.publish_loaded_project(path, loaded, preview)
                loaded = None

            run_task(
                self,
                "Opening DALE project",
                prepare,
                publish,
                object_name="projectProgress",
                publish_refresh=True,
            )
            return True
        except Exception as exc:
            if loaded and loaded is not self.loaded_project:
                loaded.close()
            self.warning("Cannot open project", str(exc))
            return False
        finally:
            self._applying_tool_values = was_applying
            QApplication.restoreOverrideCursor()

    def publish_loaded_project(self, path, loaded, preview):
        self.view.safe_json_repair = False
        self.catalog = loaded.catalog
        self.view.assign(loaded.session, preview)
        self.reset_region_selections()
        if self.loaded_project:
            self.loaded_project.close()
        self.loaded_project, loaded = loaded, None
        session, settings = self.loaded_project.session, self.loaded_project.ui_state
        self.custom_colors = self.loaded_project.custom_colors
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
        self.view.raster_aids.restore(settings.get("raster_aids"))
        self.view.raster_brushes = brush_settings(settings.get("raster_brushes"))
        self.sync_raster_aids()
        self.walls_action.setChecked(settings["show_walls"])
        self.view.show_walls = settings["show_walls"]
        self.select_tool_set(settings["tool_set"], activate=False)
        self.view.move_related = settings["move_related_lines"]
        self.activate_mode(settings["mode"], prompt=False)
        # Build the saved mode's figure/cell choices before restoring its indices.
        self.selected_regions = settings["export_regions"]
        self.update_map_info()
        self.restore_region_selection(settings)
        self.project_path = path
        self.remember_directory("input", path.resolve().parent)
        self.remember_recent_project(path)
        self.saved_state = self.document_state()
        self.rebuild_dataset_controls()
        self.update_project_info()
        self.refresh()
        self.restore_camera(settings)
        self.remember_tool_values()
        self.remember_active_dataset()

    def save_catalog_json(self, document, project_path):
        selected, _ = QFileDialog.getSaveFileName(
            self,
            self.t("Save JSON…"),
            str((self.output_directory or project_path.parent) / Path(document.name).name),
            self.t("Scene JSON (*.json)"),
            "",
            QFileDialog.Option.DontConfirmOverwrite,
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
            destination = write_json_copy(
                document.data, destination, sources, conflict=self.confirm_export_file
            )
            self.remember_directory("output", destination.resolve().parent)
        except ExportCancelled:
            return
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
            self.reset_region_selections()
            self.custom_colors = DEFAULT_CUSTOM_COLORS
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

    def refresh_geometry_edit(self):
        self.refresh()
        if self.current_tool_set == "geometry":
            self._region_selection_states.clear()
            self.view.detached_selection = None
            self.view.region_pivot = self.view.figure_pivot = None
            self.view.figure_pivot_edges = ()
            self.view.figure_line_ids = ()
            self.view.region_polygons = ()
            self.view.selected_path = QPainterPath()
            self.selected_regions = ()
            self.marquee_selection = self.figure_marquee = None
            self.update_map_info()

    def refresh(self):
        if getattr(self, "_alchemist_task_active", False):
            return
        self.view.property_documents = self.catalog.documents if self.catalog else ()
        if self.prepare_alchemist_display():
            return
        self.refresh_display()

    def refresh_display(self):
        self.sync_alchemist_controls()
        self.view.property_documents = self.catalog.documents if self.catalog else ()
        self.update_clipboard_actions()
        self.view.refresh()
        self.rebuild_source_layers()
        self.update_map_info()
        if (
            self.view.session
            and self.view.safe_json_repair
            and self.current_tool_set not in ("figures", "alchemist")
        ):
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
        before = self.raster_selection_snapshot()
        if self.current_tool_set in ("figures", "alchemist"):
            data = self.region_control.itemData(index)
            self.view.figure_line_ids = tuple(data or ())
            if self.current_tool_set == "alchemist" and not data:
                self.thinning.clear_selection()
            self.view.figure_pivot = None
            self.update_map_info()
            return
        self.view.detached_selection = None
        data = self.region_control.itemData(index)
        self.selected_regions = None if data is None else tuple(data)
        self.view.region_pivot = None
        self.update_map_info()
        self.record_raster_selection(before)

    def toggle_region_at(self, point):
        before = self.raster_selection_snapshot()
        polygons = self.available_regions() if self.view.detached_selection else self.regions
        hit = min(
            (i for i, polygon in enumerate(polygons) if polygon.covers(ShapePoint(point))),
            key=lambda i: polygons[i].area,
            default=None,
        )
        if hit is None:
            if (
                before is not None
                and before.polygons
                and self.question(
                    "Clear selection",
                    "Do you want to deselect all regions?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                != QMessageBox.StandardButton.Yes
            ):
                return
            self.clear_selection()
            return
        if self.view.detached_selection:
            self.view.detached_selection = None
            self.selected_regions = ()
            self.update_map_info()
        self.view.region_pivot = None
        selected = set(self.selected_regions or ())
        if hit in selected:
            selected.remove(hit)
        else:
            selected.add(hit)
        self.selected_regions = tuple(sorted(selected))
        self.update_map_info()
        self.record_raster_selection(before)

    def available_regions(self):
        return self.view.selectable_regions()

    def select_figure_at(self, event):
        point = ShapePoint(event["point"])
        first = event.get("first_click") if event.get("double") else None
        tolerance = 6 / max(self.view.transform().m11(), 1e-9)
        components = (
            self.view.da_figures_in_bounds(
                (point.x - tolerance, point.y - tolerance, point.x + tolerance, point.y + tolerance)
            )
            if self.current_tool_set == "alchemist" and first is None
            else self.view.contour_figures()
        )
        candidates = [
            (LineString(edge).distance(point), line_id, component)
            for component in components
            for edge, line_id in zip(component.edges, component.line_ids, strict=True)
        ]
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
        if event.get("remember_only"):
            target = hit[1] if hit and hit[0] <= tolerance else None
            self.view.remember_figure_click(event["point"], target, before)
            return
        if not hit or hit[0] > tolerance:
            self.clear_selection()
            if event.get("mouse"):
                self.view.remember_figure_click(event["point"], None, before)
            return
        selected = set(first["before"] if first is not None else before)
        if event.get("double"):
            component = set(hit[2].line_ids)
            if self.current_tool_set == "alchemist":
                peers = self.alchemist_double_click_peers(hit[1])
                if peers is None:
                    self.view.figure_line_ids = tuple(sorted(selected))
                    self.view.figure_pivot = None
                    self.update_map_info()
                    return
                self.sync_alchemist_controls()
                if peers:
                    component = set(peers)
            if self.view.mode == "Move figures" or (self.current_tool_set == "alchemist" and peers):
                if self.view.mode == "Move figures":
                    selected = component
                else:
                    selected.update(component)
            elif component.issubset(selected):
                selected.difference_update(component)
            else:
                selected.update(component)
        elif self.current_tool_set == "alchemist":
            component = set(hit[2].line_ids)
            if component.issubset(selected):
                selected.difference_update(component)
            else:
                selected.update(component)
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
                if self.current_tool_set == "alchemist":
                    hits = {
                        identifier
                        for component in self.view.da_figures_in_bounds((x0, y0, x1, y1))
                        if x1 > x0
                        and y1 > y0
                        and any(LineString(edge).intersects(rectangle) for edge in component.edges)
                        for identifier in component.line_ids
                    }
                else:
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
        if self.current_tool_set in ("figures", "alchemist"):
            self.select_figures_in_box(event)
            return
        phase = event["phase"]
        if phase == "begin":
            self.marquee_selection = {
                "history": self.raster_selection_snapshot(),
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
            self.record_raster_selection(original["history"])

    def select_transformed_regions(self, result):
        if self.current_tool_set == "pixels" and result.get("raster_cells"):
            self.select_raster_cells(result["raster_cells"], result["pivot"])
            return
        if self.current_tool_set in ("figures", "alchemist"):
            self.view.figure_line_ids = tuple(result.get("line_ids", ()))
            self.view.figure_pivot = result["pivot"]
            self.view.figure_pivot_edges = self.view.selected_figure_edges()
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

    def select_raster_cells(self, cells, pivot=None):
        self.view.detached_selection = None
        self.selected_regions = ()
        self.update_map_info()
        wanted = set(cells)
        self.selected_regions = tuple(
            i for i, (cell, _) in enumerate(self.view.raster_region_entries()) if cell in wanted
        )
        self.update_map_info()
        self.view.region_pivot = pivot

    def restore_region_selection(self, settings):
        from shapely import from_wkb

        live = {r.id for r in self.view.session.geometry().lineage}
        self.view.figure_line_ids = tuple(i for i in settings.get("figure_lines", ()) if i in live)
        # Pivot is derived UI data; stored grab anchors must not become rotation centers.
        self.view.figure_pivot = None
        self.view.figure_pivot_edges = ()

        key = tuple(p.wkb for p in self.available_regions())
        selections = settings.get("section_region_selections") or {
            self._region_selection_section: settings.get("export_regions")
        }
        self._region_selection_states = {
            section: {"selected": selections.get(section, ()), "key": key}
            for section in ("regions", "pixels")
        }
        for section, selection in (
            ("regions", settings.get("detached_region_selection")),
            ("pixels", settings.get("raster_aids", {}).get("selection")),
        ):
            if not selection or not set(selection["lines"]).issubset(
                {r.id for r in self.view.session.geometry().lineage}
            ):
                continue
            polygons = tuple(from_wkb(bytes.fromhex(p)) for p in selection["polygons"])
            detached = {
                "geometry": self.view.session.geometry(),
                "polygons": polygons,
                "line_ids": tuple(selection["lines"]),
            }
            self._region_selection_states[section].update(
                selected=tuple(range(len(polygons))),
                detached=detached,
                pivot=tuple(selection["pivot"]),
            )
        state = self._region_selection_states[self._region_selection_section]
        self.selected_regions = state["selected"]
        self.region_key = state["key"]
        self.view.detached_selection = state.get("detached")
        self.view.region_pivot = state.get("pivot")
        self.update_map_info()

    def update_figure_info(self):
        session = self.view.session
        components = self.view.contour_figures()
        cached = getattr(self, "_figure_live_ids", None)
        if cached is None or cached[0] is not components:
            cached = components, frozenset(i for c in components for i in c.line_ids)
            self._figure_live_ids = cached
        live = cached[1]
        selection = self.view.selection_display() if session else None
        if selection is not None and not selection.selected <= live:
            self.view.figure_line_ids = tuple(i for i in self.view.figure_line_ids if i in live)
        self.view.update_move_cursor()
        self.view.selected_path = self.view.figure_path()
        controls_key = (
            tuple(c.line_ids for c in components),
            self.view.figure_line_ids,
            self.language,
        )
        if controls_key != getattr(self, "_figure_controls_key", None):
            self._figure_controls_key = controls_key
            self.regions_group.setTitle(self.t("Contours"))
            self.region_control.setToolTip(
                self.t(
                    "Choose a whole DA object or all visible objects."
                    if self.current_tool_set == "alchemist"
                    else "Choose a connected contour or all contour lines to select."
                )
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
                selected_ids = set(self.view.figure_line_ids)
                selected_count = (
                    sum(bool(selected_ids.intersection(c.line_ids)) for c in components)
                    if self.current_tool_set == "alchemist"
                    else len(self.view.figure_line_ids)
                )
                self.region_control.addItem(
                    self.t(
                        "Selected objects: {count}"
                        if self.current_tool_set == "alchemist"
                        else "Selected lines: {count}",
                        count=selected_count,
                    ),
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
        if self.current_tool_set == "alchemist":
            selected = set(self.view.figure_line_ids)
            self.diagnostics.setText(
                self.t(
                    "Selected objects: {count}",
                    count=sum(bool(selected.intersection(c.line_ids)) for c in components),
                )
            )
        self.update_clipboard_actions()
        if not session or not session.source.image_path:
            self.bounds_preview.clear()
            self.map_info.setText(self.t("No image"))
            self.view.viewport().update()
            return
        if session.alchemist:
            self.show_deferred_export_info(session)
            return
        try:
            selected = export_regions(session)
        except ValueError:
            selected = ()
        self.update_png_info(session, selected)
        if self.view.raster_aids.settings["isolate_regions"]:
            self.view.update_image()

    def update_map_info(self):
        if self.current_tool_set == "alchemist":
            self.view.figure_line_ids = self.view.whole_da_selection(self.view.figure_line_ids)
        self.sync_slice_window()
        if self.current_tool_set in ("figures", "alchemist"):
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
            and self.current_tool_set not in ("regions", "figures", "alchemist")
        ):
            self.bounds_preview.clear()
            self.regions = ()
            self.view.selected_path = QPainterPath()
            self.region_control.blockSignals(True)
            self.region_control.clear()
            self.region_control.setEnabled(False)
            self.region_control.blockSignals(False)
            if session.alchemist:
                self.view.selected_source_layer()
                choices = self.view._source_layers_cache[2]
                layers = tuple(layer for layer in choices if layer.kind != "all")
                ambiguous = next(
                    (layer.indices for layer in choices if layer.kind == "ambiguous"), ()
                )
            else:
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
        if session.alchemist:
            self.show_deferred_export_info(session)
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

    def show_deferred_export_info(self, session):
        """Editing DA geometry must not calculate the combined export topology or PNG bounds."""
        self.bounds_preview.clear()
        self.view.export_preview_bounds = ()
        self.map_info.setText(
            self.t(
                "Scene image: {width} x {height} px\nPNG dimensions are calculated when exporting.",
                width=session.source.size[0],
                height=session.source.size[1],
            )
        )
        self.map_info.setToolTip(
            self.t(
                "Export uses the current geometry and visibility settings. "
                "Editing does not prepare PNG dimensions."
            )
        )
        settings = self.view.raster_aids.settings
        self.view.preview_merge_adjacent = settings["preview_merge"] is True
        self.view.export_grid_frame = None
        if settings["export_grid_visible"]:
            try:
                self.view.export_grid_frame = export_grid(
                    session, settings["export_grid_size"] or None
                )
            except ValueError:
                pass
        self.view.viewport().update()

    def update_png_info(self, session, selected):
        settings = self.view.raster_aids.settings
        self.view.preview_merge_adjacent = settings["preview_merge"] is True
        grid = self.size_to_grid
        grid_size = settings["export_grid_size"] or None
        self.view.export_grid_frame = None
        if settings["export_grid_visible"]:
            try:
                self.view.export_grid_frame = export_grid(session, grid_size)
            except ValueError:
                pass  # The Information block reports invalid placement settings.
        if self.current_tool_set == "pixels" and settings["isolate_regions"]:
            grid = settings["preview_grid"]
            try:
                selected = tuple(
                    p
                    for _, p in selected_export_regions(
                        self.view.region_polygons,
                        settings["raster_offset"],
                        merge_adjacent=self.view.preview_merge_adjacent,
                    )
                )
            except ValueError:
                selected = ()
        if self.view.raster_aids.settings["isolate_regions"]:
            self.view.update_image()
        result = self.bounds_preview.request(
            session, selected, size_to_grid=grid, grid_size=grid_size
        )
        self.view.export_preview_bounds = result.bounds if result and not result.error else ()
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
            self.t(result.error)
            if result and result.error
            else self.t(
                "PNG bounds retain every nonzero alpha pixel after artwork offset, "
                "then expand to grid lines with transparent padding."
            )
            if self.size_to_grid
            else self.t(
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
            self.reset_region_selections()
            self.refresh()

    def history(self, redo):
        if self.slice_window and self.slice_window.isVisible():
            self.slice_window.flush()
            self.slice_window.last_edit = None
            self.slice_window.baseline = None
        self.view.cancel_pending()
        if self.view.session:
            session = self.view.session
            operation = (
                session.future[-1]
                if redo and session.future
                else session.operations[-1]
                if not redo and len(session.operations) > session.history_floor
                else None
            )
            before = self.view.session.geometry()
            (self.view.session.redo if redo else self.view.session.undo)()
            after = self.view.session.geometry()
            if isinstance(operation, RasterSelectionEdit):
                self.restore_raster_selection(operation.after if redo else operation.before)
            elif getattr(operation, "raster", None) is not None and operation.raster.cells:
                self.select_tool_set("pixels", activate=False)
                self.view.detached_selection = None
                self.refresh()
                self.select_raster_cells(operation.raster.cells)
            elif after != before or after.lineage != before.lineage:
                self.refresh_geometry_edit()
            else:
                self.refresh()

    def mask(self, mode):
        if (
            not self.view.session
            or not self.view.session.source.image_path
            or not self.view.region_polygons
            or self.view.active_gesture
            or self.worker
            or self.current_tool_set in ("figures", "alchemist")
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
        if self.defer_slice_action(lambda: self.export(selected_only)):
            return
        try:
            self.start_png_export(selected_only)
        except Exception as exc:
            if self.worker is None and self.progress is not None:
                self.progress.close()
                self.progress = None
            self.update_export_actions()
            self.warning("Export failed", str(exc))

    def update_export_actions(self):
        session = self.view.session
        enabled = bool(
            session
            and not self.worker
            and (session.source.image_path or (self.include_json and not self.include_png))
        )
        self.export_action.setEnabled(enabled)
        self.export_regions_action.setEnabled(enabled)

    def start_png_export(self, selected_only):
        self.view.finish_rotation()
        if not self.view.session or self.worker:
            return
        if not (self.include_png or self.include_json):
            self.information("Export files", "Enable PNG or JSON export.")
            return
        if self.include_png and self.view.session.source.image_path is None:
            self.information(
                "PNG export", "Disable JSON repair and open a scene image for PNG export."
            )
            return
        if self.view.active_gesture:
            self.information("Finish editing", "Finish or cancel the active gesture first.")
            return
        selection = (
            None if self.current_tool_set in ("figures", "alchemist") else self.selected_regions
        )
        if selection == () or (selected_only and selection is None):
            self.activate_mode("Select regions")
            self.information(
                "Select regions", "Select at least one closed region on the scene image."
            )
            return
        if self.size_to_grid and self.include_png:
            try:
                export_grid(
                    self.view.session, self.view.raster_aids.settings["export_grid_size"] or None
                )
            except ValueError as exc:
                self.warning("PNG export", str(exc))
                return
        merge_adjacent = False
        merge_contours = self.merge_export_contours and selection is not None
        if merge_contours:
            merge_adjacent = True
        elif selection is not None:
            merge_adjacent = self.confirm_merge_selected_regions()
            if merge_adjacent is None:
                return
        polygons = tuple(self.regions[i] for i in selection) if selection is not None else None
        groups = self.selection_groups()
        active_group = self.active_selection_group()
        stem = self.catalog.name if self.catalog else Path(self.view.session.source.name).stem
        if groups:
            group_session, group_polygons = self.view.session, polygons
            if self.json_contours == "alchemist":
                from dale.overlay_export import da_export_regions

                group_session, group_polygons = da_export_regions(group_session, polygons)
            plan = overlay_region_plan(
                group_session,
                selected_polygons=group_polygons,
                merge_adjacent=merge_adjacent,
                allow_empty=not self.include_png,
            )
            matches = export_group_matches(group_session, groups, plan, active_group)
            if any(matches):
                naming = self.confirm_export_group_naming(stem, matches)
                if naming is None:
                    return
                if naming == "dataset":
                    groups = ()
                else:
                    package_group = shared_export_group(matches)
                    if package_group is not None:
                        stem = group_export_stem(package_group.name)
            else:
                groups = ()
        default = self.output_directory or (
            self.project_path.parent if self.project_path else Path.cwd()
        )
        path = choose_export_directory(self, default, export_family(stem, self.export_identity()))
        if not path:
            return
        self.remember_directory("output", Path(path).parent)
        self.export_action.setEnabled(False)
        self.export_regions_action.setEnabled(False)
        self.progress = QProgressDialog(
            self.t("Exporting separate PNGs…" if self.include_png else "Exporting contours…"),
            self.t("Cancel"),
            0,
            100,
            self,
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
            selected_polygons=polygons,
            merge_adjacent=merge_adjacent,
            size_to_grid=self.size_to_grid,
            merge_contours=merge_contours,
            grid_size=self.view.raster_aids.settings["export_grid_size"] or None,
            include_json=self.include_json,
            include_png=self.include_png,
            export_groups=groups,
            active_group=active_group,
        )
        self.worker.progress.connect(self.progress.setValue)
        self.worker.file_conflict.connect(self.resolve_worker_file_conflict)
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

    def showEvent(self, event):
        if not self._clipboard_connected:
            self.contour_clipboard.changed.connect(self.restore_contour_clipboard)
            self._clipboard_connected = True
            self.restore_contour_clipboard()
        super().showEvent(event)

    def closeEvent(self, event):
        if self.worker:
            self.cancel_export()
            self.statusBar().showMessage(
                self.t("Cancelling export. Close the window after export stops.")
            )
            event.ignore()
        elif self.can_discard():
            self.close_slice_controls()
            if self._clipboard_connected:
                self.contour_clipboard.changed.disconnect(self.restore_contour_clipboard)
                self._clipboard_connected = False
            self.bounds_preview.shutdown()
            self.view.native_preview.shutdown()
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
    from shiboken6 import isValid

    from dale.application_style import DaleStyle

    if not (getattr(app, "_dale_style", None) and isValid(app._dale_style)):
        style = DaleStyle()
        app.setStyle(style)
        app._dale_style = style
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
    register_current_product(verification=options.smoke_report is not None)
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
                    "size_to_grid": window.size_to_grid,
                    "include_json": window.include_json,
                    "group_naming": window.export_group_naming,
                    "grid_size": window.view.raster_aids.settings["export_grid_size"],
                    "right_click": window.export_regions_button.contextMenuPolicy()
                    == Qt.ContextMenuPolicy.CustomContextMenu,
                    "tooltip": window.export_regions_action.toolTip(),
                },
                "global_tool_settings": window.global_tools_control.isChecked(),
                "top_panels": {
                    "main": [
                        a.property("dale_tool_key")
                        for a in window.basic_toolbar.actions()
                        if a.property("dale_tool_key")
                    ],
                    "view": [
                        a.property("dale_tool_key")
                        for a in window.view_toolbar.actions()
                        if a.property("dale_tool_key")
                    ],
                    "scroll_maximum": window.top_panels_scroll.horizontalScrollBar().maximum(),
                    "grid_visible": window.grid_action.isChecked(),
                    "grid_color": window.view.raster_aids.settings["export_grid_color"],
                    "grid_transparency": window.view.raster_aids.settings[
                        "export_grid_transparency"
                    ],
                    "grid_width": window.view.raster_aids.settings["export_grid_width"],
                },
                "custom_colors": window.custom_colors,
                "tool_values": window.current_tool_values(),
                "tool_settings": {
                    title: {
                        "size": [button.width(), button.height()],
                        "right_click": button.contextMenuPolicy()
                        == Qt.ContextMenuPolicy.CustomContextMenu,
                        "corner": button.findChild(QWidget, "toolSettingsCorner") is not None,
                        "inline_value_hidden": button.editor().isHidden()
                        if isinstance(button, SizedToolButton)
                        else None,
                    }
                    for title, button in window.tool_settings_buttons.items()
                },
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
                        window.basic_toolbar.widgetForAction(window.main_delete_action).width(),
                        window.basic_toolbar.widgetForAction(window.main_delete_action).height(),
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
                    "right_angle_value": window.right_angle_tolerance.toolTip(),
                    "contour_alignment": window.sized_tools["Contour alignment"].toolTip(),
                    "export_png": window.export_action.toolTip(),
                    "edit_points": window.mode_actions["Edit points"].toolTip(),
                    "erase_lines": window.geometry_eraser_tiles["Erase lines"].toolTip(),
                },
                "camera": {
                    "center": [window.view.camera_center().x(), window.view.camera_center().y()],
                    "center_error_pixels": (
                        window.view.mapFromScene(window.view.image_rect.center())
                        - window.view.viewport().rect().center()
                    ).manhattanLength(),
                    "zoom": window.view.transform().m11(),
                }
                if window.view.session
                else None,
                "rotation_steps": window.view.rotation_steps,
                "mirror_controls": {
                    axis: {
                        "text": command.text(),
                        "enabled": command.isEnabled(),
                        "size": [
                            window.figure_toolbar.widgetForAction(command).width(),
                            window.figure_toolbar.widgetForAction(command).height(),
                        ],
                    }
                    for axis, command in window.mirror_contour_actions.items()
                },
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
                "undo_history": {
                    key: {
                        "floor": draft.session.history_floor,
                        "undo": len(draft.session.operations) - draft.session.history_floor,
                        "redo": len(draft.session.future),
                    }
                    for key, draft in window.catalog.views.items()
                }
                if window.catalog
                else {},
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
            circle_popup = window.show_tool_settings("New circle")
            circle_value = window.view.circle_detail_steps
            circle_popup.circle_detail.setValue(0)
            minimum_label = circle_popup.circle_detail_label.text()
            circle_popup.circle_detail.setValue(95)
            report["circle_detail_settings"] = {
                "steps": circle_value,
                "range": [
                    circle_popup.circle_detail.minimum(),
                    circle_popup.circle_detail.maximum(),
                ],
                "single_step": circle_popup.circle_detail.singleStep(),
                "minimum_label": minimum_label,
                "maximum_label": circle_popup.circle_detail_label.text(),
                "staged_only": window.view.circle_detail_steps == circle_value,
                "nonmodal": not circle_popup.isModal(),
            }
            circle_popup.reject()
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
            if manager.catalog.current.has_json:
                from dale.editing import add_line

                source_id = manager.catalog.active_key
                target = manager.catalog.create(
                    manager.catalog.unique_name(
                        "Merge check", (v.name for v in manager.catalog.views.values())
                    )
                ).id
                manager.catalog.transfer(source_id, target, "json")
                incoming = manager.catalog.views[source_id].session
                x = incoming.source.size[0] + 30
                incoming.add(add_line(incoming.geometry(), (x, 0), (x + 10, 10)))
                before = next(item for item in manager.catalog.state() if item[0] == source_id)
                target_count = len(manager.catalog.views[target].session.geometry().lineage)
                merge_report = {}

                def choose_smoke_merge():
                    dialog = QApplication.activeModalWidget()
                    try:
                        button = next(
                            button
                            for button in dialog.findChildren(QPushButton)
                            if button.text() == window.t("Merge contours")
                        )
                        merge_report.update(label=button.text(), enabled=button.isEnabled())
                        button.click()
                    finally:
                        if dialog.isVisible():
                            dialog.reject()

                QTimer.singleShot(0, choose_smoke_merge)
                manager.transfer(source_id, target, "json")
                merge_report.update(
                    added=len(manager.catalog.views[target].session.geometry().lineage)
                    - target_count,
                    source_unchanged=next(
                        item for item in manager.catalog.state() if item[0] == source_id
                    )
                    == before,
                )
                report["json_transfer_merge"] = merge_report
            manager.close()
            manager.deleteLater()
            naming = window.show_tool_settings("Export selected regions")
            report["group_naming_settings"] = {
                "choices": [
                    naming.naming_action.itemData(i) for i in range(naming.naming_action.count())
                ],
                "current": naming.naming_action.currentData(),
            }
            naming.reject()
            if window.view.session and window.view.session.geometry().lineage:
                from dale.region_transform import copy_figures

                geometry = window.view.session.geometry()
                ids = tuple(record.id for record in geometry.lineage)
                clipboard = copy_figures(geometry, ids)
                copied = clipboard.paste(geometry, window.view.session.source.size[0] + 100, 0)
                new_ids = {record.id for record in copied.lineage} - set(ids)
                report["clipboard_group_isolation"] = all(
                    not (group_members(group, copied) & new_ids)
                    for group in window.selection_groups()
                )
            window.toggle_group_manager()
            QApplication.processEvents()
            groups_manager = window.group_manager
            fixed_position = groups_manager.viewport_position()
            scrollbars = window.view.horizontalScrollBar(), window.view.verticalScrollBar()
            scroll_values = tuple(bar.value() for bar in scrollbars)
            for bar in scrollbars:
                bar.setValue(bar.value() + (27 if bar.value() < bar.maximum() - 27 else -27))
            fixed_on_scroll = fixed_position == groups_manager.viewport_position()
            for bar, value in zip(scrollbars, scroll_values, strict=True):
                bar.setValue(value)
            main_size, manager_size = window.size(), groups_manager.size()
            groups_manager.set_user_size(manager_size + QSize(20, 20))
            resize_only_overlay = (
                window.size() == main_size and groups_manager.size() != manager_size
            )
            groups_manager.user_sized = False
            groups_manager.requested_size = manager_size
            groups_manager.fit_size()
            groups_manager.reposition()
            report["selection_groups"] = {
                "groups": [g.encode() for g in window.selection_groups()],
                "active": window.active_selection_group(),
                "members": {
                    g.id: sorted(window.resolved_group_members(g.id))
                    for g in window.selection_groups()
                },
                "manager_visible": groups_manager.isVisible(),
                "button_checked": window.group_manager_button.isChecked(),
                "map_child": groups_manager.parentWidget() is window.view,
                "fixed_on_scroll": fixed_on_scroll,
                "viewport_position": [fixed_position.x(), fixed_position.y()],
                "resize_grip_visible": groups_manager.size_grip.isVisible(),
                "resize_only_overlay": resize_only_overlay,
                "footer_buttons": len(groups_manager.findChildren(QDialogButtonBox)),
                "width": groups_manager.width(),
                "new_button": groups_manager.new_button.text(),
                "color_layers": len(window.group_overlay()[0]),
                "opaque_fills": len(window.group_overlay()[1]),
                "panel_after_main": window.groups_toolbar.x()
                == window.basic_toolbar.x() + window.basic_toolbar.width(),
                "selector_size": [window.group_control.width(), window.group_control.height()],
            }
            window.grab().save(
                str(options.smoke_report.with_name(options.smoke_report.stem + "-groups.png"))
            )
            groups_manager.hide()
            options.smoke_report.write_text(json.dumps(report), encoding="utf-8")
            window.grab().save(str(options.smoke_report.with_suffix(".png")))
            window.windowIcon().pixmap(256, 256).save(
                str(options.smoke_report.with_name(options.smoke_report.stem + "-icon.png"))
            )
            app.quit()

        QTimer.singleShot(500, smoke_report)
    sys.exit(app.exec())
