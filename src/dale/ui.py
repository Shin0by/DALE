"""Local desktop workflow, controls, and export worker lifecycle."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction, QActionGroup, QFont, QFontDatabase, QIntValidator, QKeySequence
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
    QSpinBox,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from dale.canvas import MapView
from dale.placement import Placement
from dale.raster import ExportCancelled, export_png, load_preview
from dale.scene import load_pair
from dale.session import Session


class ExportWorker(QThread):
    progress = Signal(int)
    outcome = Signal(str, str)

    def __init__(self, session, path, placement, parent):
        super().__init__(parent)
        self.source = session.source
        self.operations = tuple(session.operations)
        self.path = path
        self.placement = placement

    def run(self):
        try:
            export_png(
                self.source,
                self.operations,
                self.path,
                self.progress.emit,
                self.isInterruptionRequested,
                self.placement,
            )
            self.outcome.emit("success", str(self.path))
        except ExportCancelled:
            self.outcome.emit("cancelled", "PNG export cancelled; destination unchanged.")
        except Exception as exc:
            self.outcome.emit("error", str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DALE — Floor overlay editor")
        self.resize(1280, 860)
        self.worker = None
        self.progress = None
        self.export_outcome = None
        self.view = MapView()
        self.view.changed.connect(self.refresh)
        self.view.message.connect(lambda message: self.statusBar().showMessage(message, 7000))
        self.info = QLabel("Open an upper-floor JPG and its Foundry JSON to begin.")
        self.info.setWordWrap(True)
        self.diagnostics = QLabel()
        self.diagnostics.setWordWrap(True)
        self.version = QComboBox()
        self.version.addItems(["Foundry 14", "Foundry 13"])
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
        self.elevation.currentTextChanged.connect(self.update_placement_hint)
        self.origin_x, self.origin_y = QDoubleSpinBox(), QDoubleSpinBox()
        for control in (self.origin_x, self.origin_y):
            control.setRange(-1_000_000, 1_000_000)
            control.setDecimals(2)
        alignment = QPushButton("Apply alignment")
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
                "Cyan: source walls\nOrange: unresolved lines\nYellow: local closures\n"
                "Purple: gap joins\nGreen: offset boundary"
            )
        )
        sidebar.addWidget(self.diagnostics)
        help_text = QLabel(
            "Right-drag: pan in every tool\nWheel: zoom at cursor\n\nClosure:\n"
            "Click: snap start/end\nCtrl/Alt-click: free corner\nEscape: cancel\n\n"
            "Erase/Restore: drag to paint\nBrush size: original pixels\n\n"
            "Edits are held in memory.\nPNG export preserves original size."
        )
        help_text.setWordWrap(True)
        sidebar.addWidget(help_text)
        sidebar.addStretch()
        panel = QWidget()
        panel.setFixedWidth(280)
        panel.setLayout(sidebar)
        layout = QHBoxLayout()
        layout.addWidget(self.view, 1)
        layout.addWidget(panel)
        root = QWidget()
        root.setLayout(layout)
        self.setCentralWidget(root)
        toolbar = QToolBar("Editing")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        def action(title, handler, shortcut=None):
            item = QAction(title, self)
            item.triggered.connect(handler)
            if shortcut:
                item.setShortcut(shortcut)
            toolbar.addAction(item)
            return item

        action("Open pair", self.open_pair, QKeySequence.StandardKey.Open)
        self.export_action = action("Export PNG", self.export, "Ctrl+E")
        toolbar.addSeparator()
        modes = QActionGroup(self)
        modes.setExclusive(True)
        for mode in ("Pan", "Closure", "Erase", "Restore"):
            item = action(mode, lambda checked=False, m=mode: self.view.set_mode(m))
            item.setCheckable(True)
            item.setChecked(mode == "Pan")
            modes.addAction(item)
        toolbar.addSeparator()
        action("Remove outside", lambda: self.mask("outside"))
        action("Remove inside", lambda: self.mask("inside"))
        history = QToolBar("History and view")
        history.setMovable(False)
        self.addToolBarBreak()
        self.addToolBar(history)
        for name, handler, shortcut in (
            ("Undo", lambda: self.history(False), QKeySequence.StandardKey.Undo),
            ("Redo", lambda: self.history(True), QKeySequence.StandardKey.Redo),
            ("Fit", self.view.fit_map, "F"),
        ):
            item = QAction(name, self)
            item.triggered.connect(handler)
            item.setShortcut(shortcut)
            history.addAction(item)
        self.walls_action = QAction("Show walls", self)
        self.walls_action.setCheckable(True)
        self.walls_action.setChecked(True)
        self.walls_action.toggled.connect(self.toggle_walls)
        history.addAction(self.walls_action)
        history.addWidget(QLabel("  Brush diameter (px): "))
        brush = QSpinBox()
        brush.setRange(1, 4096)
        brush.setValue(40)
        brush.valueChanged.connect(self.set_brush)
        history.addWidget(brush)
        self.update_placement_hint()
        self.statusBar().showMessage("Ready. All editing is local.")

    def placement(self):
        text = self.elevation.currentText()
        if not self.elevation.lineEdit().hasAcceptableInput():
            raise ValueError("Enter a whole-number elevation in feet.")
        return Placement(14 if self.version.currentIndex() == 0 else 13, int(text))

    def update_placement_hint(self):
        try:
            text = self.placement().guidance
        except ValueError:
            text = "Elevation must be a whole number of feet."
        self.placement_hint.setText(
            text + "\n\nPNG metadata records this choice; set placement in Foundry."
        )

    def set_brush(self, value):
        self.view.diameter = value
        self.view.viewport().update()

    def toggle_walls(self, value):
        self.view.show_walls = value
        self.view.viewport().update()

    def update_contour_settings(self):
        if self.view.session:
            self.view.session.gap_tolerance = self.gap_tolerance.value()
            self.view.session.contour_offset = self.contour_offset.value()
            self.refresh()
            self.statusBar().showMessage(
                "Contour preview updated. Apply Remove outside/inside to use these settings.", 7000
            )

    def can_discard(self):
        if not self.view.session or not (
            self.view.session.operations or self.view.pending or self.view.stroke
        ):
            return True
        return (
            QMessageBox.question(
                self,
                "Discard editing session?",
                "Edits are held in memory. Discard this editing session?\n"
                "An exported PNG does not contain reloadable edit history.",
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            == QMessageBox.StandardButton.Discard
        )

    def open_pair(self):
        if not self.can_discard():
            return
        image_path, _ = QFileDialog.getOpenFileName(
            self, "Open source JPG", "examples", "JPEG images (*.jpg *.jpeg)"
        )
        if not image_path:
            return
        json_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open matching Foundry JSON",
            str(Path(image_path).with_suffix(".json")),
            "JSON files (*.json)",
        )
        if not json_path:
            return
        self.load_sources(Path(image_path), Path(json_path))

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
        except Exception as exc:
            QMessageBox.warning(self, "Cannot open source pair", str(exc))

    def refresh(self):
        self.view.refresh()
        if self.view.session:
            analysis = self.view.analysis
            self.diagnostics.setText(
                f"Closed faces: {analysis.faces}\n"
                f"Unresolved segments: {len(analysis.unresolved)}\n"
                f"Gap joins: {len(analysis.joins)}\n"
                f"Editing operations: {len(self.view.session.operations)}"
            )

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
            QMessageBox.information(
                self, "Finish closure", "Finish the closure or cancel it with Escape."
            )
            return
        analysis = self.view.analysis
        if not analysis.faces:
            QMessageBox.information(
                self,
                "Close a boundary first",
                "No enclosed region exists. Use Closure to connect original walls: "
                "click to snap, Ctrl/Alt-click for corners, click to snap the end.",
            )
            return
        if (
            analysis.unresolved
            and QMessageBox.question(
                self,
                "Review open contours",
                f"{len(analysis.unresolved)} unresolved segments remain (orange). "
                "They may be gaps or unused/internal lines.\n"
                "Apply the mask to the closed regions anyway? Choose No to repair with Closure.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            operation = self.view.session.make_mask(mode)
        except ValueError as exc:
            QMessageBox.information(self, "Review contour offset", str(exc))
            return
        self.view.session.add(operation)
        self.refresh()

    def export(self):
        if not self.view.session or self.worker:
            return
        if self.view.pending or self.view.stroke:
            QMessageBox.information(
                self, "Finish editing", "Finish or cancel the active stroke/closure first."
            )
            return
        try:
            placement = self.placement()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid elevation", str(exc))
            return
        default = self.view.session.source.image_path.with_name(
            f"{self.view.session.source.image_path.stem}-{placement.elevation_ft}ft.png"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Export full-size transparent PNG", str(default), "PNG images (*.png)"
        )
        if not path:
            return
        self.export_action.setEnabled(False)
        self.progress = QProgressDialog(
            "Exporting original-resolution PNG…", "Cancel", 0, 100, self
        )
        self.progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.progress.setAutoClose(False)
        self.progress.setAutoReset(False)
        self.progress.setMinimumDuration(0)
        self.worker = ExportWorker(self.view.session, Path(path), placement, self)
        self.worker.progress.connect(self.progress.setValue)
        self.worker.outcome.connect(self.record_outcome)
        self.worker.finished.connect(self.export_finished)
        self.progress.canceled.connect(self.cancel_export)
        self.worker.start()

    def cancel_export(self):
        if self.worker:
            self.worker.requestInterruption()
            self.progress.setLabelText("Cancelling after the current decode/stripe…")

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
            QMessageBox.warning(self, "Export failed", text)
        elif outcome == "success":
            self.statusBar().showMessage(f"Exported {text}", 15000)
        else:
            self.statusBar().showMessage(text, 10000)

    def closeEvent(self, event):
        if self.worker:
            self.cancel_export()
            self.statusBar().showMessage("Cancelling export. Close the window after export stops.")
            event.ignore()
        elif self.can_discard():
            event.accept()
        else:
            event.ignore()


def configure_application(app):
    app.setApplicationName("DALE")
    app.setStyle("Fusion")
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
    options = parser.parse_args()
    if bool(options.image) != bool(options.scene):
        parser.error("Pass both --image and --scene to open a map pair.")
    app = QApplication([sys.argv[0]])
    configure_application(app)
    window = MainWindow()
    window.show()
    if options.image:
        window.load_sources(options.image, options.scene)
    sys.exit(app.exec())
