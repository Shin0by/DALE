"""Nonmodal tool settings containers with standard controls and a shared footer."""

from PySide6.QtCore import QEvent, QLocale, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class ToolSettingsButtons(QDialogButtonBox):
    """Retain explicit Apply/Cancel captions after Qt language-change events."""

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            t = self.parentWidget().parentWidget().t
            for kind, caption in (
                (QDialogButtonBox.StandardButton.Ok, "Apply"),
                (QDialogButtonBox.StandardButton.Cancel, "Cancel"),
            ):
                self.button(kind).setText(t(caption))


class ToolSettingsDialog(QDialog):
    def __init__(
        self,
        parent,
        title,
        *,
        value=None,
        question=None,
        choices=(),
        remembered=None,
        size_to_grid=None,
        scene_grid=None,
        grid_color="#e5bd78",
        grid_transparency=56,
        grid_width=1,
        grid_info="",
        adjacent_vertices=None,
        connected_contours=None,
        own_angle_priority=None,
        include_json=None,
        group_naming=None,
        rotation_steps=(),
        circle_detail=None,
        raster_aids=None,
        raster_brush=None,
        background=None,
        figure_double_click=None,
    ):
        super().__init__(parent)
        self.setObjectName("toolSettingsDialog")
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setStyleSheet("QDialog#toolSettingsDialog { border: 1px solid #606060; }")
        t = parent.t
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        caption = QLabel(title, self)
        caption.setObjectName("toolSettingsTitle")
        font = caption.font()
        font.setBold(True)
        caption.setFont(font)
        self.close_button = QToolButton(self)
        self.close_button.setObjectName("closeToolSettings")
        self.close_button.setText("X")
        self.close_button.setFixedSize(22, 22)
        self.close_button.setToolTip(
            parent.control_help("Close without applying settings.", title="Close")
        )
        self.close_button.clicked.connect(self.reject)
        header.addWidget(caption, 1)
        header.addWidget(self.close_button)
        layout.addLayout(header)
        self.value = None
        self.default_action = None
        self.grid = None
        self.grid_size = None
        self.neighbours = None
        self.own_angle_priority = None
        self.json_export = None
        self.naming_action = None
        self.rotation_values = []
        self.circle_detail = None
        self.figure_double_click = None

        def section(title):
            group = QGroupBox(t(title), self)
            layout.addWidget(group)
            return QVBoxLayout(group)

        def color_control(block, key, initial, title, purpose, enabled=None):
            setattr(self, key, initial)
            button = QPushButton(self)
            button.setObjectName(key + "Button")
            button.setToolTip(parent.control_help(purpose, title=title))
            setattr(self, key + "_button", button)

            def refresh_color():
                value = getattr(self, key)
                button.setText(value)
                swatch = QPixmap(18, 18)
                swatch.fill(QColor(value))
                button.setIcon(QIcon(swatch))
                button.setIconSize(QSize(18, 18))
                if enabled is not None:
                    button.setEnabled(enabled())

            def choose_color():
                self.hide()
                try:
                    color = parent.choose_project_color(QColor(getattr(self, key)), t(title))
                finally:
                    self.show()
                if color.isValid():
                    setattr(self, key, color.name())
                refresh_color()

            button.clicked.connect(choose_color)
            refresh_color()
            block.addWidget(button)
            return refresh_color

        if scene_grid is not None:
            block = section("Scene grid")
            block.addWidget(QLabel(t("Grid cell size (scene pixels)"), self))
            self.grid_size = QSpinBox(self)
            self.grid_size.setObjectName("exportGridSize")
            self.grid_size.setRange(1, 1_000_000_000)
            self.grid_size.setValue(scene_grid)
            self.grid_size.setToolTip(
                parent.control_help(
                    "Use one cell size for both axes. The grid starts at the scene origin "
                    "and controls PNG padding when Size to grid is enabled.",
                    title="Grid cell size (scene pixels)",
                )
            )
            block.addWidget(self.grid_size)
            block.addWidget(QLabel(t("Grid color"), self))
            color_control(
                block,
                "grid_color",
                grid_color,
                "Grid color",
                "Choose the grid line color for this dataset. PNG pixels stay unchanged.",
            )
            block.addWidget(QLabel(t("Grid transparency"), self))
            row = QHBoxLayout()
            self.grid_transparency = QSpinBox(self)
            self.grid_transparency.setObjectName("gridTransparency")
            self.grid_transparency.setRange(0, 100)
            self.grid_transparency.setSuffix(" %")
            self.grid_transparency.setValue(grid_transparency)
            self.grid_transparency_slider = QSlider(Qt.Orientation.Horizontal, self)
            self.grid_transparency_slider.setObjectName("gridTransparencySlider")
            self.grid_transparency_slider.setRange(0, 100)
            self.grid_transparency_slider.setValue(grid_transparency)
            self.grid_transparency_slider.valueChanged.connect(self.grid_transparency.setValue)
            self.grid_transparency.valueChanged.connect(self.grid_transparency_slider.setValue)
            help_text = parent.control_help(
                "0% shows opaque grid lines; 100% hides them. PNG pixels stay unchanged.",
                title="Grid transparency",
            )
            self.grid_transparency.setToolTip(help_text)
            self.grid_transparency_slider.setToolTip(help_text)
            row.addWidget(self.grid_transparency_slider, 1)
            row.addWidget(self.grid_transparency)
            block.addLayout(row)
            block.addWidget(QLabel(t("Grid line thickness (screen pixels)"), self))
            self.grid_width = QSpinBox(self)
            self.grid_width.setObjectName("gridLineWidth")
            self.grid_width.setRange(1, 16)
            self.grid_width.setValue(grid_width)
            self.grid_width.setToolTip(
                parent.control_help(
                    "Keep grid line thickness constant on screen when zooming the map.",
                    title="Grid line thickness (screen pixels)",
                )
            )
            block.addWidget(self.grid_width)

        if background is not None:
            block = section("Canvas background")
            self.background_kind = QComboBox(self)
            for caption, key in (("Checkerboard", "checker"), ("Solid color", "solid")):
                self.background_kind.addItem(t(caption), key)
            self.background_kind.setCurrentIndex(
                self.background_kind.findData(background["background_kind"])
            )
            self.background_kind.setToolTip(
                parent.control_help(
                    "Choose the canvas background for this dataset. "
                    "Exported pixels stay unchanged.",
                    title="Canvas background",
                )
            )
            block.addWidget(self.background_kind)
            refresh_color = color_control(
                block,
                "background_color",
                background["background_color"],
                "Background color",
                "Choose a solid preview background color.",
                enabled=lambda: self.background_kind.currentData() == "solid",
            )
            self.background_kind.currentIndexChanged.connect(refresh_color)

        if raster_aids is not None:
            block = section("Ruler units")
            self.ruler_units = QComboBox(self)
            self.ruler_units.setObjectName("rulerUnits")
            for caption, unit in (
                ("Source pixels", "px"),
                ("Feet", "ft"),
                ("Centimeters", "cm"),
                ("Millimeters", "mm"),
            ):
                self.ruler_units.addItem(t(caption), unit)
            self.ruler_units.setCurrentIndex(self.ruler_units.findData(raster_aids["unit"]))
            self.ruler_units.setToolTip(
                parent.control_help(
                    "World distances use the scene JSON grid. Ruler zero is the image origin.",
                    title="Ruler units",
                )
            )
            block.addWidget(self.ruler_units)
            from dale.measurement import measurement_scale

            try:
                if parent.view.session is None:
                    raise ValueError(
                        "World rulers require scene JSON grid size, distance and units."
                    )
                scale = measurement_scale(parent.view.session.source, "ft")
                text = t(
                    "One game foot: {x} × {y} source px.",
                    x=f"{scale.pixels_per_unit[0]:.6g}",
                    y=f"{scale.pixels_per_unit[1]:.6g}",
                )
            except ValueError as exc:
                text = t(str(exc))
            info = QLabel(text, self)
            info.setWordWrap(True)
            block.addWidget(info)
            self.ruler_snap = QCheckBox(t("Snap guides to whole ruler values"), self)
            self.ruler_snap.setChecked(raster_aids["snap"])
            self.ruler_snap.setToolTip(
                parent.control_help(
                    "Round a dragged guide to a whole value in the selected ruler unit.",
                    title="Snap guides to whole ruler values",
                )
            )
            block.addWidget(self.ruler_snap)
            block = section("Automatic grid")
            self.ruler_grid = QCheckBox(t("Show automatic grid"), self)
            self.ruler_grid.setChecked(raster_aids["grid"])
            block.addWidget(self.ruler_grid)
            block.addWidget(QLabel(t("Grid spacing in the selected units"), self))
            self.ruler_step = QDoubleSpinBox(self)
            self.ruler_step.setObjectName("rulerGridStep")
            self.ruler_step.setDecimals(6)
            self.ruler_step.setRange(0.000001, 1e9)
            self.ruler_step.setValue(raster_aids["step"])
            self.ruler_step.setToolTip(
                parent.control_help(
                    "Set the spacing of scene-anchored grid lines in the selected units.",
                    title="Grid spacing",
                )
            )
            self.ruler_grid.setToolTip(
                parent.control_help(
                    "Show a solid translucent grid over the scene image.",
                    title="Show automatic grid",
                )
            )
            block.addWidget(self.ruler_step)
            info = QLabel(t("Dense grid lines are thinned only on screen at low zoom."), self)
            info.setWordWrap(True)
            block.addWidget(info)

        if circle_detail is not None:
            block = section("Circle detail")
            explanation = QLabel(
                t("More segments make the contour smoother without changing its radius."), self
            )
            explanation.setWordWrap(True)
            block.addWidget(explanation)
            limit = QLabel(t("Maximum: 4096 segments."), self)
            block.addWidget(limit)
            self.circle_detail_label = QLabel(self)
            self.circle_detail_label.setObjectName("circleDetailMultiplier")
            block.addWidget(self.circle_detail_label)
            self.circle_detail = QSlider(Qt.Orientation.Horizontal, self)
            self.circle_detail.setObjectName("circleDetailSlider")
            self.circle_detail.setRange(circle_detail.minimum(), circle_detail.maximum())
            self.circle_detail.setSingleStep(1)
            self.circle_detail.setPageStep(1)
            self.circle_detail.setValue(circle_detail.value())
            self.circle_detail.setToolTip(
                parent.control_help(
                    "Increase the automatic segment count. Multiplier 1.0 keeps current detail.",
                    keys=[
                        "Left/Right: change the multiplier by 0.2.",
                        "Home/End: minimum/maximum detail.",
                    ],
                    title="Circle detail",
                )
            )
            self.circle_detail.setAccessibleName(t("Circle detail"))

            def update_multiplier(value):
                factor = QLocale(parent.language).toString(1 + value / 5, "f", 1)
                self.circle_detail_label.setText(t("Multiplier: ×{factor}", factor=factor))

            self.circle_detail.valueChanged.connect(update_multiplier)
            update_multiplier(self.circle_detail.value())
            block.addWidget(self.circle_detail)

        if rotation_steps:
            block = section("Rotation step (degrees)")
            for control, caption in zip(rotation_steps, ("Wheel", "Alt+wheel"), strict=True):
                block.addWidget(QLabel(t(caption), self))
                editor = QDoubleSpinBox(self)
                editor.setDecimals(2)
                editor.setRange(control.minimum() / 100, control.maximum() / 100)
                editor.setSingleStep(0.01)
                editor.setValue(control.value() / 100)
                editor.setSuffix("°")
                editor.setToolTip(
                    parent.control_help(
                        "Degrees per wheel notch. Apply to remember this rotation step.",
                        title=caption,
                    )
                )
                self.rotation_values.append(editor)
                block.addWidget(editor)
        if value is not None:
            control, label = value
            block = section(label)
            self.value = QSpinBox(self)
            self.value.setObjectName("toolSettingsValue")
            self.value.setRange(control.minimum(), control.maximum())
            self.value.setValue(control.value())
            self.value.setSuffix(control.suffix())
            self.value.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.value.setMinimumWidth(130)
            self.value.setToolTip(control.toolTip())
            block.addWidget(self.value)
            if own_angle_priority is not None:
                self.own_angle_priority = QCheckBox(t("Own right-angle priority"), self)
                self.own_angle_priority.setObjectName("ownRightAnglePriority")
                self.own_angle_priority.setChecked(own_angle_priority)
                self.own_angle_priority.setToolTip(
                    parent.control_help(
                        "Prefer the dragged vertex's right angle. When off, adjacent angles "
                        "and horizontal/vertical guides take priority.",
                        title="Own right-angle priority",
                    )
                )
                block.addWidget(self.own_angle_priority)
            if adjacent_vertices is not None:
                self.neighbours = QCheckBox(t("At adjacent vertices"), self)
                self.neighbours.setObjectName("rightAngleNeighbours")
                self.neighbours.setChecked(adjacent_vertices)
                self.neighbours.setToolTip(
                    parent.control_help(
                        "Also square angles at neighbouring vertices. When off, only angles "
                        "at the dragged vertex are considered.",
                        title="At adjacent vertices",
                    )
                )
                block.addWidget(self.neighbours)
        if figure_double_click is not None:
            block = section("Contour selection")
            self.figure_double_click = QCheckBox(t("Select contour by double-click"), self)
            self.figure_double_click.setObjectName("figureMoveDoubleClick")
            self.figure_double_click.setChecked(figure_double_click)
            self.figure_double_click.setToolTip(
                parent.control_help(
                    "Double-click a line to select only its connected contour. "
                    "Double-click empty space to clear selection. "
                    "Single clicks keep the current selection for moving.",
                    title="Select contour by double-click",
                )
            )
            block.addWidget(self.figure_double_click)
        if connected_contours is not None:
            block = section("Guide targets")
            self.connected_contours = QCheckBox(t("Connected by contours"), self)
            self.connected_contours.setObjectName("extensionConnectedContours")
            self.connected_contours.setChecked(connected_contours)
            self.connected_contours.setToolTip(
                parent.control_help(
                    "Use only lines touching the moved selection through a chain of contours "
                    "before the gesture. Independent contours are excluded.",
                    title="Connected by contours",
                )
            )
            block.addWidget(self.connected_contours)
        if raster_brush is not None:
            block = section("Brush shape")
            self.brush_shape = QComboBox(self)
            self.brush_shape.setObjectName("rasterBrushShape")
            for caption, key in (("Circle", "circle"), ("Square", "square")):
                self.brush_shape.addItem(t(caption), key)
            self.brush_shape.setCurrentIndex(self.brush_shape.findData(raster_brush["shape"]))
            self.brush_shape.setToolTip(
                parent.control_help(
                    "Choose the round or square tool for this raster operation.",
                    title="Brush shape",
                )
            )
            block.addWidget(self.brush_shape)
            for key, title, purpose in (
                (
                    "feather",
                    "Feather width (%)",
                    "Keep a solid center and soften only the outer band.",
                ),
                (
                    "opacity",
                    "Brush pressure (%)",
                    "Set the strength of each erase or restore stroke.",
                ),
            ):
                block = section(title)
                label = QLabel(self)
                slider = QSlider(Qt.Orientation.Horizontal, self)
                slider.setObjectName("brushFeather" if key == "feather" else "brushOpacity")
                slider.setRange(0, 100)
                slider.setValue(raster_brush[key])
                slider.setToolTip(parent.control_help(purpose, title=title))
                slider.valueChanged.connect(lambda v, label=label: label.setText(f"{v}%"))
                label.setText(f"{slider.value()}%")
                block.addWidget(label)
                block.addWidget(slider)
                setattr(self, "brush_" + key, slider)
        if question:
            block = section("Default action")
            label = QLabel(t(question), self)
            label.setObjectName("defaultActionQuestion")
            label.setWordWrap(True)
            block.addWidget(label)
            self.default_action = QComboBox(self)
            self.default_action.setObjectName("defaultAction")
            self.default_action.addItem(t("Ask every time"), None)
            for text, answer in choices:
                self.default_action.addItem(t(text), answer)
            self.default_action.setCurrentIndex(0 if remembered is None else 1 if remembered else 2)
            self.default_action.setToolTip(
                parent.control_help(
                    "Use this action automatically, or show the question on every operation.",
                    title="Default action",
                )
            )
            block.addWidget(self.default_action)
        if size_to_grid is not None:
            block = section("PNG dimensions")
            self.grid = QCheckBox(t("Size to grid"), self)
            self.grid.setObjectName("sizeToGrid")
            self.grid.setChecked(size_to_grid)
            self.grid.setToolTip(
                parent.control_help(
                    "Add transparent padding after artwork offset "
                    "so both PNG corners lie on scene grid lines.",
                    title="Size to grid",
                )
            )
            block.addWidget(self.grid)
            info = QLabel(grid_info, self)
            info.setObjectName("gridInfo")
            info.setWordWrap(True)
            block.addWidget(info)
        if include_json is not None:
            block = section("Export files")
            self.json_export = QCheckBox(t("Export JSON files"), self)
            self.json_export.setObjectName("includeJson")
            self.json_export.setChecked(include_json)
            self.json_export.setToolTip(
                parent.control_help(
                    "Include the current scene JSON and PNG placement JSON. "
                    "When off, export only PNGs.",
                    title="Export JSON files",
                )
            )
            block.addWidget(self.json_export)
            block = section("PNG naming")
            question = QLabel(t("Which name should a region matching a group use?"), self)
            question.setWordWrap(True)
            block.addWidget(question)
            self.naming_action = QComboBox(self)
            self.naming_action.setObjectName("exportGroupNaming")
            for text, answer in (
                ("Ask every time", None),
                ("Dataset name", "dataset"),
                ("Group name", "group"),
            ):
                self.naming_action.addItem(t(text), answer)
            self.naming_action.setCurrentIndex(self.naming_action.findData(group_naming))
            self.naming_action.setToolTip(
                parent.control_help(
                    "Choose the filename prefix for an exact group boundary match. "
                    "Other regions keep the dataset name.",
                    title="PNG naming",
                )
            )
            block.addWidget(self.naming_action)
        self.buttons = ToolSettingsButtons(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        for kind, caption, purpose in (
            (QDialogButtonBox.StandardButton.Ok, "Apply", "Apply these tool settings."),
            (QDialogButtonBox.StandardButton.Cancel, "Cancel", "Leave tool settings unchanged."),
        ):
            button = self.buttons.button(kind)
            button.setText(t(caption))
            button.setToolTip(parent.control_help(purpose, title=caption))
        button_size = self.buttons.buttons()[0].sizeHint()
        for button in self.buttons.buttons()[1:]:
            button_size = button_size.expandedTo(button.sizeHint())
        for button in self.buttons.buttons():
            button.setFixedSize(button_size)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.setMinimumWidth(360)
        self.resize(416, max(self.sizeHint().height(), layout.totalHeightForWidth(416)))

    def showEvent(self, event):
        super().showEvent(event)
        QApplication.instance().installEventFilter(self)

    def hideEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        super().hideEvent(event)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress and isinstance(watched, QWidget):
            target = watched
            while target is not None and target is not self:
                target = target.parent()
            # QWidget.isAncestorOf stops at child-window boundaries, including combo lists.
            if target is None:
                self.reject()
        return super().eventFilter(watched, event)
