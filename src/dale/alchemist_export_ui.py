"""Foundry-order wall controls adapted from the former WallPresetDialog."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from dale.alchemist_export import ANIMATIONS, validate


class WallExportSettings(QWidget):
    changed = Signal()

    def __init__(self, owner, value, parent=None):
        super().__init__(parent)
        t = owner.t
        self.owner = owner
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        note = QLabel(
            t("JSON export only. These settings do not change display filters or contours.")
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        def group(title):
            box = QGroupBox(t(title), self)
            layout.addWidget(box)
            form = QFormLayout(box)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            return form

        def combo(title, choices, initial, editable=False):
            control = QComboBox(self)
            for caption, key in choices:
                control.addItem(t(caption), key)
            control.setEditable(editable)
            index = control.findData(initial)
            if index >= 0:
                control.setCurrentIndex(index)
            elif editable:
                control.setEditText(initial)
            control.setToolTip(
                owner.control_help(
                    "Choose the value written to exported walls in this category.", title=title
                )
            )
            control.currentIndexChanged.connect(self.changed)
            if editable:
                control.editTextChanged.connect(self.changed)
            return control

        def number(title, initial, low=0, high=1000000, suffix=""):
            control = QDoubleSpinBox(self)
            control.setDecimals(2)
            control.setRange(low, high)
            control.setSingleStep(1)
            control.setValue(initial)
            control.setSuffix(t(suffix))
            control.setToolTip(
                owner.control_help(
                    "Numeric export value; does not affect contour selection or filtering.",
                    title=title,
                )
            )
            control.valueChanged.connect(self.changed)
            return control

        form = QFormLayout()
        layout.addLayout(form)
        self.direction = combo(
            "Restriction direction", [("Both", 0), ("Left", 1), ("Right", 2)], value["dir"]
        )
        form.addRow(t("Restriction direction"), self.direction)
        form = group("Wall restrictions")
        self.movement = combo("Movement", [("None", 0), ("Normal", 20)], value["move"])
        form.addRow(t("Movement"), self.movement)
        self.senses, self.thresholds = {}, {}
        for key, title in (("light", "Light"), ("sight", "Sight"), ("sound", "Sound")):
            row = QWidget(self)
            horizontal = QHBoxLayout(row)
            horizontal.setContentsMargins(0, 0, 0, 0)
            sense = combo(
                title,
                [
                    ("None", 0),
                    ("Limited", 10),
                    ("Normal", 20),
                    ("Proximity", 30),
                    ("Reverse proximity", 40),
                ],
                value[key],
            )
            threshold = number(
                "Threshold distance (feet)",
                value["threshold"][key] if value["threshold"][key] is not None else 5,
                suffix=" ft",
            )
            threshold.setMaximumWidth(112)
            horizontal.addWidget(sense, 1)
            horizontal.addWidget(threshold)
            self.senses[key], self.thresholds[key] = sense, threshold
            sense.currentIndexChanged.connect(self.update_dynamic)
            form.addRow(t(title), row)
        self.attenuation = QCheckBox(t("Proximity threshold attenuation"), self)
        self.attenuation.setChecked(value["threshold"]["attenuation"])
        self.attenuation.setToolTip(
            owner.control_help(
                "Attenuate the light and vision source radius through a proximity wall.",
                title="Proximity threshold attenuation",
            )
        )
        self.attenuation.toggled.connect(self.changed)
        form.addRow(self.attenuation)
        form = group("Door settings")
        self.door = combo(
            "Door type", [("None", 0), ("Door", 1), ("Secret door", 2)], value["door"]
        )
        self.state = combo("Door state", [("Closed", 0), ("Opened", 1), ("Locked", 2)], value["ds"])
        self.sound = combo("Door sound", [("None", "")], value["doorSound"], True)
        animation = value["animation"] or dict(
            type="", texture=None, flip=False, double=False, direction=1, duration=1000, strength=1
        )
        self.animation = combo(
            "Animation type",
            [(k.capitalize() if k else "None", k) for k in ANIMATIONS],
            animation["type"],
            True,
        )
        for title, control in (
            ("Door type", self.door),
            ("Door state", self.state),
            ("Door sound", self.sound),
            ("Animation type", self.animation),
        ):
            form.addRow(t(title), control)
        self.door_form = form
        self.door.currentIndexChanged.connect(self.update_dynamic)
        self.animation.currentTextChanged.connect(self.update_dynamic)
        form = group("Door animation")
        self.animation_group = form.parentWidget()
        self.texture = QLineEdit(animation["texture"] or "", self)
        self.texture.setMaxLength(2048)
        self.texture.setToolTip(
            owner.control_help(
                "Foundry asset path written to JSON. DALE does not open or download it.",
                title="Texture",
            )
        )
        self.texture.textChanged.connect(self.changed)
        form.addRow(t("Texture"), self.texture)
        self.flip, self.double = QCheckBox(t("Flip texture")), QCheckBox(t("Double door"))
        for key, control in (("flip", self.flip), ("double", self.double)):
            control.setChecked(animation[key])
            control.setToolTip(
                owner.control_help(
                    "Configure the exported door animation.",
                    title="Flip texture" if key == "flip" else "Double door",
                )
            )
            control.toggled.connect(self.changed)
            form.addRow(control)
        self.animation_direction = combo(
            "Open direction", [("Normal", 1), ("Reversed", -1)], animation["direction"]
        )
        self.duration = number("Duration (ms)", animation["duration"])
        self.strength = number("Strength", animation["strength"])
        for title, control in (
            ("Open direction", self.animation_direction),
            ("Duration (ms)", self.duration),
            ("Strength", self.strength),
        ):
            form.addRow(t(title), control)
        form = group("Wall height")
        self.height_fields = {}
        for key, title in (("top", "Top height"), ("bottom", "Base height")):
            initial = value["flags"]["wall-height"][key]
            row = QWidget(self)
            horizontal = QHBoxLayout(row)
            horizontal.setContentsMargins(0, 0, 0, 0)
            editor = number(
                title,
                initial if initial is not None else (10 if key == "top" else 0),
                -10000,
                10000,
                " ft",
            )
            unlimited = QCheckBox(t("Unbounded"), self)
            unlimited.setToolTip(
                owner.control_help(
                    "Export this height without a limit. "
                    "Global height normalization takes priority.",
                    title="Unbounded",
                )
            )
            unlimited.setChecked(initial is None)
            unlimited.toggled.connect(editor.setDisabled)
            unlimited.toggled.connect(self.changed)
            editor.setDisabled(initial is None)
            horizontal.addWidget(editor, 1)
            horizontal.addWidget(unlimited)
            form.addRow(t(title), row)
            self.height_fields[key] = (editor, unlimited)
        self.update_dynamic()

    @staticmethod
    def text_value(combo):
        return (
            combo.currentData()
            if combo.currentIndex() >= 0
            and (combo.currentText() == combo.itemText(combo.currentIndex()))
            else combo.currentText().strip()
        )

    def update_dynamic(self):
        if not hasattr(self, "animation_group"):
            return
        for key, control in self.senses.items():
            self.thresholds[key].setVisible(control.currentData() in (30, 40))
        door = self.door.currentData() != 0
        for control in (self.state, self.sound, self.animation):
            self.door_form.setRowVisible(control, door)
        self.animation_group.setVisible(door and bool(self.text_value(self.animation)))

    def values(self):
        animation = None
        kind = self.text_value(self.animation)
        if self.door.currentData() and kind:
            animation = dict(
                type=kind,
                texture=self.texture.text().strip() or None,
                flip=self.flip.isChecked(),
                double=self.double.isChecked(),
                direction=self.animation_direction.currentData(),
                duration=self.duration.value(),
                strength=self.strength.value(),
            )
        return validate(
            dict(
                move=self.movement.currentData(),
                dir=self.direction.currentData(),
                **{key: control.currentData() for key, control in self.senses.items()},
                door=self.door.currentData(),
                ds=self.state.currentData(),
                doorSound=self.text_value(self.sound),
                animation=animation,
                threshold={
                    **{
                        key: control.value() if self.senses[key].currentData() in (30, 40) else None
                        for key, control in self.thresholds.items()
                    },
                    "attenuation": self.attenuation.isChecked(),
                },
                flags={
                    "wall-height": {
                        key: None if unlimited.isChecked() else editor.value()
                        for key, (editor, unlimited) in self.height_fields.items()
                    }
                },
            )
        )
