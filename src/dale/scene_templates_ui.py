"""Scene template cards and localized modal editors; no placed object assignment."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QDoubleValidator, QIcon, QIntValidator, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from dale.localization import prepare_control_tooltips, translate, translate_static
from dale.scene_templates import (
    ANIMATION_TYPES,
    PALETTE,
    PRESET_ICONS,
    SENSE_CHOICES,
    LevelTemplate,
    SceneTemplates,
    WallPreset,
)
from dale.toolbar import tool_icon

ICON_NAMES = {
    "wall": "Wall",
    "window": "Opening window",
    "window_locked": "Locked opening window",
    "window_barred": "Barred window",
    "door": "Door",
    "door_locked": "Locked door",
    "door_secret": "Secret door",
    "door_secret_locked": "Locked secret door",
}


def preset_icon(kind):
    canvas = QPixmap(28, 28)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#edf5ff"), 1.6))
    painter.setBrush(QColor("#3b5665"))
    painter.drawRect(3, 3, 20, 22)
    if kind.startswith("window"):
        painter.setBrush(QColor("#70d2e5"))
        painter.drawRect(6, 6, 14, 16)
        painter.drawLine(13, 6, 13, 22)
        if kind == "window_barred":
            for x in (8, 13, 18):
                painter.drawLine(x, 4, x, 24)
            for y in (10, 17):
                painter.drawLine(4, y, 22, y)
        else:
            painter.drawLine(6, 6, 10, 9)
            painter.drawLine(10, 9, 10, 19)
            painter.drawLine(10, 19, 6, 22)
            painter.drawLine(20, 6, 16, 9)
            painter.drawLine(16, 9, 16, 19)
            painter.drawLine(16, 19, 20, 22)
    elif kind.startswith("door"):
        painter.drawRect(6, 6, 13, 19)
        painter.drawPoint(16, 16)
        if "secret" in kind:
            painter.drawText(8, 20, "?")
    else:
        for y in (10, 17):
            painter.drawLine(3, y, 23, y)
        for x, y in ((13, 3), (8, 10), (18, 10), (13, 17)):
            painter.drawLine(x, y, x, y + 7)
    if "locked" in kind:
        painter.setBrush(QColor("#e5bd61"))
        painter.setPen(QPen(QColor("#1d2529"), 1.2))
        painter.drawRoundedRect(18, 13, 7, 8, 2, 2)
        painter.drawRect(16, 18, 11, 9)
    painter.end()
    return QIcon(canvas)


def visibility_icon(visible):
    if visible:
        return tool_icon("Show contours")
    canvas = QPixmap(24, 24)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    tool_icon("Show contours").paint(painter, 0, 0, 24, 24)
    painter.setPen(QPen(QColor("#f1f6ff"), 2))
    painter.drawLine(3, 21, 21, 3)
    painter.end()
    return QIcon(canvas)


def finish_dialog(dialog, language, layout):
    dialog.error = QLabel()
    dialog.error.setWordWrap(True)
    dialog.error.setStyleSheet("color: #ff9393;")
    layout.addWidget(dialog.error)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.button(QDialogButtonBox.StandardButton.Save).setToolTip(
        "Save this definition. Enter: save."
    )
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setToolTip(
        "Cancel without changes. Escape: cancel."
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    prepare_control_tooltips(dialog)
    translate_static(dialog, language, (dialog.error,))


class ColorPaletteDialog(QDialog):
    def __init__(self, color, language, parent=None):
        super().__init__(parent)
        self.setWindowTitle(translate("Level RGB color", language))
        self.language = language
        self.color = color
        layout = QVBoxLayout(self)
        grid = QGridLayout()
        self.swatches = []
        for index, value in enumerate(PALETTE):
            button = QPushButton()
            button.setFixedSize(44, 32)
            button.setStyleSheet(f"background: {value}; border: 1px solid #aaaaaa;")
            button.setToolTip(value)
            button.clicked.connect(lambda checked=False, value=value: self.choose(value))
            grid.addWidget(button, index // 4, index % 4)
            self.swatches.append(button)
        layout.addLayout(grid)
        full = QPushButton(translate("Full RGB palette…", language))
        full.setToolTip(translate("Choose any red, green, and blue color.", language))
        full.clicked.connect(self.choose_full)
        layout.addWidget(full)
        cancel = QPushButton(translate("Cancel", language))
        cancel.setToolTip(translate("Cancel without changes. Escape: cancel.", language))
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel)

    def choose(self, color):
        self.color = color
        self.accept()

    def choose_full(self):
        picker = self.make_rgb_dialog()
        if picker.exec() == QDialog.DialogCode.Accepted:
            self.choose(picker.selectedColor().name())

    def make_rgb_dialog(self):
        picker = QColorDialog(QColor(self.color), self)
        picker.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog)
        picker.setWindowTitle(self.windowTitle())
        picker.setToolTip(
            translate("Choose an RGB color. Enter: accept. Escape: cancel.", self.language)
        )
        for index, color in enumerate(PALETTE):
            picker.setCustomColor(index, QColor(color))
        prepare_control_tooltips(picker)
        translate_static(picker, self.language)
        return picker


class LevelDialog(QDialog):
    def __init__(self, level, language, parent=None):
        super().__init__(parent)
        self.setWindowTitle(translate("Level definition", language))
        self.language, self.level, self.result_level = language, level, None
        self.color = level.color
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(level.name)
        self.name.setMaxLength(128)
        self.name.setToolTip("Name of this reusable level definition.")
        form.addRow("Name", self.name)
        self.bottom, self.top = QLineEdit(), QLineEdit()
        for field, value in ((self.bottom, level.bottom_ft), (self.top, level.top_ft)):
            field.setValidator(QIntValidator(-1_000_000, 1_000_000, field))
            field.setText("" if value is None else str(value))
            field.setToolTip(
                "Whole feet only. Empty bottom means minus infinity; empty top means plus infinity."
            )
        self.bottom.setPlaceholderText("−∞")
        self.top.setPlaceholderText("+∞")
        form.addRow("Bottom (ft)", self.bottom)
        form.addRow("Top (ft)", self.top)
        self.color_button = QPushButton("Choose RGB color…")
        self.color_button.setToolTip("Choose from 16 colors or the full RGB palette.")
        self.color_button.clicked.connect(self.choose_color)
        form.addRow("Color", self.color_button)
        layout.addLayout(form)
        finish_dialog(self, language, layout)
        self.update_color()

    def update_color(self):
        swatch = QPixmap(18, 18)
        swatch.fill(QColor(self.color))
        self.color_button.setIcon(QIcon(swatch))

    def choose_color(self):
        dialog = ColorPaletteDialog(self.color, self.language, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.color = dialog.color
            self.update_color()

    def accept(self):
        try:
            values = []
            for field in (self.bottom, self.top):
                if field.text().strip() and not field.hasAcceptableInput():
                    raise ValueError("Enter whole feet or leave the height empty.")
                values.append(int(field.text()) if field.text().strip() else None)
            level = replace(
                self.level,
                name=self.name.text().strip(),
                bottom_ft=values[0],
                top_ft=values[1],
                color=self.color,
            )
            self.result_level = SceneTemplates((level,)).validated().levels[0]
        except ValueError as exc:
            self.error.setText(translate(str(exc), self.language))
            return
        super().accept()


def combo(choices, value, tip, editable=False):
    widget = QComboBox()
    for title, key in choices:
        widget.addItem(title, key)
    widget.setEditable(editable)
    index = widget.findData(value)
    if index >= 0:
        widget.setCurrentIndex(index)
    elif editable:
        widget.setCurrentText(str(value))
    widget.setToolTip(tip)
    return widget


def combo_value(widget):
    index = widget.currentIndex()
    return (
        widget.currentData()
        if index >= 0 and widget.currentText() == widget.itemText(index)
        else widget.currentText().strip()
    )


class WallPresetDialog(QDialog):
    def __init__(self, preset, language, parent=None):
        super().__init__(parent)
        self.setWindowTitle(translate("Wall preset definition", language))
        self.language, self.preset, self.result_preset = language, preset, None
        self.setMinimumWidth(470)
        self.resize(510, 660)
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setToolTip("Scroll wall preset settings.")
        content = QWidget()
        column = QVBoxLayout(content)
        form = QFormLayout()
        self.name = QLineEdit(preset.name)
        self.name.setMaxLength(128)
        self.name.setToolTip("Name of this reusable wall preset.")
        form.addRow("Name", self.name)
        self.icon = combo(
            [(ICON_NAMES[key], key) for key in PRESET_ICONS],
            preset.icon,
            "Choose the preset icon. Door icons always depict closed doors.",
        )
        for index, key in enumerate(PRESET_ICONS):
            self.icon.setItemIcon(index, preset_icon(key))
        form.addRow("Icon", self.icon)
        value = deepcopy(preset.properties)
        self.direction = combo(
            [("Both", 0), ("Left", 1), ("Right", 2)],
            value["dir"],
            "Side on which movement and perception restrictions apply.",
        )
        form.addRow("Restriction direction", self.direction)
        column.addLayout(form)
        restrictions = QGroupBox("Wall restrictions")
        restriction_form = QFormLayout(restrictions)
        self.movement = combo(
            [("None", 0), ("Normal", 20)],
            value["move"],
            "Choose whether the wall blocks token movement.",
        )
        restriction_form.addRow("Movement", self.movement)
        self.senses, self.thresholds = {}, {}
        for key, title in (("light", "Light"), ("sight", "Sight"), ("sound", "Sound")):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            sense = combo(
                SENSE_CHOICES,
                value[key],
                "Independent restriction. Proximity modes reveal the distance field.",
            )
            distance = QLineEdit()
            distance.setMaximumWidth(80)
            distance.setValidator(QDoubleValidator(0, 1_000_000, 3, distance))
            threshold = value["threshold"][key]
            distance.setText("" if threshold is None else str(threshold))
            distance.setPlaceholderText("ft")
            distance.setToolTip("Threshold distance in feet. Empty preserves the default.")
            row_layout.addWidget(sense, 1)
            row_layout.addWidget(distance)
            self.senses[key], self.thresholds[key] = sense, distance
            sense.currentIndexChanged.connect(self.update_dynamic)
            restriction_form.addRow(title, row)
        self.attenuation = QCheckBox("Proximity threshold attenuation")
        self.attenuation.setChecked(value["threshold"]["attenuation"])
        self.attenuation.setToolTip(
            "Distance attenuation for proximity light and vision; not sound."
        )
        restriction_form.addRow(self.attenuation)
        column.addWidget(restrictions)
        door_group = QGroupBox("Door settings")
        self.door_form = QFormLayout(door_group)
        self.door = combo(
            [("None", 0), ("Door", 1), ("Secret door", 2)],
            value["door"],
            "Choose whether this boundary is an ordinary or secret door.",
        )
        self.state = combo(
            [("Closed", 0), ("Open", 1), ("Locked", 2)],
            value["ds"],
            "Initial door state. The preset icon stays visually closed.",
        )
        self.sound = combo(
            [(translate("None", language), "")],
            value["doorSound"],
            "Foundry door sound configuration key. Empty means no sound.",
            True,
        )
        self.animation = combo(
            [
                (translate("None" if not key else key.capitalize(), language), key)
                for key in ANIMATION_TYPES
            ],
            value["animation"]["type"],
            "Choose a door animation or enter a Foundry configuration key.",
            True,
        )
        for title, widget in (
            ("Door type", self.door),
            ("Door state", self.state),
            ("Door sound", self.sound),
            ("Animation type", self.animation),
        ):
            self.door_form.addRow(title, widget)
        self.door.currentIndexChanged.connect(self.update_dynamic)
        self.animation.currentTextChanged.connect(self.update_dynamic)
        column.addWidget(door_group)
        self.animation_group = QGroupBox("Door animation")
        animation_form = QFormLayout(self.animation_group)
        animation = value["animation"]
        self.texture = QLineEdit(animation["texture"] or "")
        self.texture.setToolTip("Foundry asset path for the animated door texture.")
        animation_form.addRow("Texture", self.texture)
        self.flip, self.double = QCheckBox("Flip texture"), QCheckBox("Double door")
        for control, key in ((self.flip, "flip"), (self.double, "double")):
            control.setChecked(animation[key])
            control.setToolTip("Configure the animated door texture.")
            animation_form.addRow(control)
        self.animation_direction = combo(
            [("Normal", 1), ("Reversed", -1)],
            animation["direction"],
            "Door animation direction relative to endpoint order.",
        )
        animation_form.addRow("Open direction", self.animation_direction)
        self.duration, self.strength = QSpinBox(), QDoubleSpinBox()
        for control in (self.duration, self.strength):
            control.setRange(0, 1_000_000)
        self.duration.setValue(int(animation["duration"]))
        self.duration.setToolTip("Door animation duration in milliseconds.")
        self.strength.setDecimals(3)
        self.strength.setValue(animation["strength"])
        self.strength.setToolTip("Door animation strength.")
        animation_form.addRow("Duration (ms)", self.duration)
        animation_form.addRow("Strength", self.strength)
        column.addWidget(self.animation_group)
        note = QLabel("Wall heights come from the assigned level, not this preset.")
        note.setWordWrap(True)
        column.addWidget(note)
        scroll.setWidget(content)
        layout.addWidget(scroll)
        finish_dialog(self, language, layout)
        self.update_dynamic()

    def update_dynamic(self):
        if not hasattr(self, "animation_group"):
            return
        for key in self.senses:
            self.thresholds[key].setVisible(self.senses[key].currentData() in (30, 40))
        door = self.door.currentData() != 0
        for widget in (self.state, self.sound, self.animation):
            self.door_form.setRowVisible(widget, door)
        self.animation_group.setVisible(door and bool(combo_value(self.animation)))

    def accept(self):
        try:
            distances = {}
            for key, editor in self.thresholds.items():
                text = editor.text().strip()
                distances[key] = float(text.replace(",", ".")) if text else None
            properties = {
                "dir": self.direction.currentData(),
                "move": self.movement.currentData(),
                **{key: widget.currentData() for key, widget in self.senses.items()},
                "door": self.door.currentData(),
                "ds": self.state.currentData(),
                "doorSound": combo_value(self.sound),
                "threshold": {**distances, "attenuation": self.attenuation.isChecked()},
                "animation": {
                    "type": combo_value(self.animation),
                    "texture": self.texture.text().strip() or None,
                    "flip": self.flip.isChecked(),
                    "double": self.double.isChecked(),
                    "direction": self.animation_direction.currentData(),
                    "duration": self.duration.value(),
                    "strength": self.strength.value(),
                },
            }
            preset = replace(
                self.preset,
                name=self.name.text().strip(),
                icon=self.icon.currentData(),
                properties=properties,
            )
            self.result_preset = SceneTemplates(wall_presets=(preset,)).validated().wall_presets[0]
        except ValueError as exc:
            self.error.setText(translate(str(exc), self.language))
            return
        super().accept()


class TemplateDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(250, 52)

    def paint(self, painter, option, index):
        item = index.data(Qt.ItemDataRole.UserRole)
        if item is None:
            return
        painter.save()
        rect = option.rect.adjusted(2, 2, -2, -2)
        selected = self.parent().currentIndex() == index
        painter.setBrush(QColor("#485966" if selected else "#363636"))
        painter.setPen(QColor("#9aafbd" if selected else "#606060"))
        painter.drawRect(rect)
        if isinstance(item, LevelTemplate):
            painter.fillRect(rect.x() + 8, rect.y() + 12, 20, 20, QColor(item.color))
            visibility_icon(item.visible).paint(painter, rect.right() - 28, rect.y() + 12, 24, 24)
            bottom = str(item.bottom_ft) if item.bottom_ft is not None else "−∞"
            top = str(item.top_ft) if item.top_ft is not None else "+∞"
            detail = f"{bottom} → {top} ft"
        else:
            preset_icon(item.icon).paint(painter, rect.x() + 5, rect.y() + 9, 28, 28)
            detail = translate(ICON_NAMES[item.icon], self.parent().language)
        painter.setPen(QColor("#eeeeee"))
        available = rect.width() - (76 if isinstance(item, LevelTemplate) else 48)
        name = painter.fontMetrics().elidedText(item.name, Qt.TextElideMode.ElideRight, available)
        painter.drawText(rect.x() + 40, rect.y() + 19, name)
        painter.setPen(QColor("#bbbbbb"))
        painter.drawText(rect.x() + 40, rect.y() + 37, detail)
        painter.restore()


class TemplateList(QListWidget):
    visibility_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.language = "ru"
        self.setItemDelegate(TemplateDelegate(self))
        self.setFixedHeight(110)
        self.setMinimumWidth(240)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item is not None and isinstance(item.data(Qt.ItemDataRole.UserRole), LevelTemplate):
            rect = self.visualItemRect(item)
            if (
                event.button() == Qt.MouseButton.LeftButton
                and event.position().x() >= rect.right() - 32
            ):
                self.setCurrentItem(item)
                self.visibility_changed.emit(item.data(Qt.ItemDataRole.UserRole).id)
                return
        super().mousePressEvent(event)


class SceneTemplatesPanel(QWidget):
    changed = Signal(object)
    import_requested = Signal()
    export_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.library = SceneTemplates()
        self.language = "ru"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.levels_group, self.presets_group = QGroupBox("Levels"), QGroupBox("Wall presets")
        self.levels_list, self.presets_list = TemplateList(), TemplateList()
        self.levels_list.setToolTip(
            "Double-click a level to edit it. Click its eye to show or hide all its contents."
        )
        self.presets_list.setToolTip("Double-click a wall preset to edit its shared properties.")
        self.delete_buttons = []
        for group, listing, add_title, delete_title, add, delete in (
            (
                self.levels_group,
                self.levels_list,
                "Add level",
                "Delete level",
                self.add_level,
                self.delete_level,
            ),
            (
                self.presets_group,
                self.presets_list,
                "Add preset",
                "Delete preset",
                self.add_preset,
                self.delete_preset,
            ),
        ):
            column = QVBoxLayout(group)
            column.setContentsMargins(6, 6, 6, 6)
            column.addWidget(listing)
            row = QHBoxLayout()
            for title, handler in ((add_title, add), (delete_title, delete)):
                button = QPushButton(title)
                button.setToolTip(
                    {
                        "Add level": (
                            "Configure a level name, optional heights in feet, and RGB color."
                        ),
                        "Delete level": "Delete the selected level definition.",
                        "Add preset": "Configure a reusable wall preset without heights.",
                        "Delete preset": "Delete the selected wall preset definition.",
                    }[title]
                )
                button.clicked.connect(handler)
                row.addWidget(button)
                if title == delete_title:
                    button.setEnabled(False)
                    self.delete_buttons.append(button)
                    listing.currentRowChanged.connect(
                        lambda index, button=button: button.setEnabled(index >= 0)
                    )
            column.addLayout(row)
            layout.addWidget(group)
        self.levels_list.itemDoubleClicked.connect(self.edit_level)
        self.presets_list.itemDoubleClicked.connect(self.edit_preset)
        self.levels_list.visibility_changed.connect(self.toggle_visibility)
        row = QHBoxLayout()
        for title, signal in (
            ("Import templates…", self.import_requested),
            ("Export templates…", self.export_requested),
        ):
            button = QPushButton(title)
            button.setToolTip(
                "Import only shared definitions from a DALE project or template file."
                if title.startswith("Import")
                else "Export level and wall preset definitions without placed objects or images."
            )
            button.clicked.connect(lambda checked=False, signal=signal: signal.emit())
            row.addWidget(button)
        layout.addLayout(row)

    def set_library(self, library):
        self.library = library
        for listing, entries in (
            (self.levels_list, library.levels),
            (self.presets_list, library.wall_presets),
        ):
            current = listing.currentItem()
            selected_id = current.data(Qt.ItemDataRole.UserRole).id if current else None
            listing.clear()
            listing.language = self.language
            for entry in entries:
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, entry)
                item.setToolTip(
                    translate("Double-click to edit. Eye: toggle level contents.", self.language)
                    if isinstance(entry, LevelTemplate)
                    else translate("Double-click to edit wall preset properties.", self.language)
                )
                listing.addItem(item)
                if entry.id == selected_id:
                    listing.setCurrentItem(item)

    def commit(self, library):
        self.set_library(library.validated())
        self.changed.emit(self.library)

    def add_level(self):
        dialog = LevelDialog(
            LevelTemplate(name=translate("Level", self.language)), self.language, self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.commit(replace(self.library, levels=(*self.library.levels, dialog.result_level)))

    def edit_level(self, item):
        level = item.data(Qt.ItemDataRole.UserRole)
        dialog = LevelDialog(level, self.language, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.commit(
                replace(
                    self.library,
                    levels=tuple(
                        dialog.result_level if old.id == level.id else old
                        for old in self.library.levels
                    ),
                )
            )

    def delete_level(self):
        if item := self.levels_list.currentItem():
            identifier = item.data(Qt.ItemDataRole.UserRole).id
            self.commit(
                replace(
                    self.library,
                    levels=tuple(item for item in self.library.levels if item.id != identifier),
                )
            )

    def toggle_visibility(self, identifier):
        self.commit(
            replace(
                self.library,
                levels=tuple(
                    replace(item, visible=not item.visible) if item.id == identifier else item
                    for item in self.library.levels
                ),
            )
        )

    def add_preset(self):
        dialog = WallPresetDialog(
            WallPreset(name=translate("Wall preset", self.language)), self.language, self
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.commit(
                replace(
                    self.library, wall_presets=(*self.library.wall_presets, dialog.result_preset)
                )
            )

    def edit_preset(self, item):
        preset = item.data(Qt.ItemDataRole.UserRole)
        dialog = WallPresetDialog(preset, self.language, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.commit(
                replace(
                    self.library,
                    wall_presets=tuple(
                        dialog.result_preset if old.id == preset.id else old
                        for old in self.library.wall_presets
                    ),
                )
            )

    def delete_preset(self):
        if item := self.presets_list.currentItem():
            identifier = item.data(Qt.ItemDataRole.UserRole).id
            self.commit(
                replace(
                    self.library,
                    wall_presets=tuple(
                        item for item in self.library.wall_presets if item.id != identifier
                    ),
                )
            )
