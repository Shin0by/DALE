"""Local desktop workflow, controls, and export worker lifecycle."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QFont,
    QFontDatabase,
    QIntValidator,
    QKeySequence,
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
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from dale import __version__
from dale.canvas import MapView
from dale.localization import DesktopTranslator, translate, translate_static
from dale.overlay_export import export_overlays
from dale.placement import Placement
from dale.preferences import load_language, save_language, settings_path
from dale.project_io import load_project, save_project
from dale.raster import ExportCancelled, load_preview
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
        self.setWindowTitle(f"DALE {__version__} — " + self.t("Floor overlay editor"))
        self.resize(1280, 860)
        self.worker = None
        self.progress = None
        self.export_outcome = None
        self.project_path = None
        self.loaded_project = None
        self.saved_state = None
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
        self.junction_delete = QComboBox()
        self.junction_delete.addItems(["Keep main wall", "Remove incident edges"])
        self.junction_delete.setToolTip(
            "Deleting a junction can preserve the straightest wall continuation, "
            "or remove all incident wall edges. Undo is available."
        )
        self.junction_delete.currentIndexChanged.connect(
            lambda index: setattr(
                self.view, "junction_policy", "continue" if index == 0 else "remove"
            )
        )
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
        form.addRow("Target", self.version)
        form.addRow("Elevation (ft)", self.elevation)
        form.addRow("Scene origin X", self.origin_x)
        form.addRow("Scene origin Y", self.origin_y)
        form.addRow("Join gaps up to (px)", self.gap_tolerance)
        form.addRow("Contour offset (px)", self.contour_offset)
        form.addRow("Junction deletion", self.junction_delete)
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
            "Edit points:\nClick line: insert point\nDrag circle: move\n"
            "Double-click circle: delete\n"
            "Circles keep their screen size.\n\n"
            "Erase/Restore: drag to paint\nBrush size: original pixels\n\n"
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
        layout.addWidget(self.view, 1)
        layout.addWidget(sidebar_scroll)
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

        action("Open pair", self.open_pair, "Ctrl+I")
        action("Open project", self.open_project, QKeySequence.StandardKey.Open)
        action("Save project", self.save_project_file, QKeySequence.StandardKey.Save)
        save_as = QAction("Save project as…", self)
        save_as.setShortcut(QKeySequence.StandardKey.SaveAs)
        save_as.triggered.connect(lambda: self.save_project_file(save_as=True))
        self.menuBar().addMenu("File").addAction(save_as)
        self.export_action = action("Export PNGs", self.export, "Ctrl+E")
        toolbar.addSeparator()
        modes = QActionGroup(self)
        self.mode_actions = {}
        modes.setExclusive(True)
        for mode in ("Pan", "Closure", "Edit points", "Erase", "Restore"):
            item = action(mode, lambda checked=False, m=mode: self.view.set_mode(m))
            item.setCheckable(True)
            item.setChecked(mode == "Pan")
            modes.addAction(item)
            self.mode_actions[mode] = item
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
        self.brush_control = brush
        brush.setRange(1, 4096)
        brush.setValue(40)
        brush.valueChanged.connect(self.set_brush)
        history.addWidget(brush)
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
            "Closure": "Snap the first/last click to a wall; Ctrl/Alt-click adds free corners.",
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
                item.setToolTip(tips[item.text()])
        self.version.setToolTip(
            "Select the target Foundry generation for placement guidance and metadata."
        )
        for control in (self.origin_x, self.origin_y):
            control.setToolTip(
                "Source scene origin in scene pixels. Apply alignment to start a fresh session."
            )
        brush.setToolTip("Circular brush diameter in original image pixels, independent of zoom.")
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
        translate_static(self, language, (self.info, self.diagnostics, self.placement_hint))
        if not self.view.session:
            self.info.setText(self.t("Open an upper-floor JPG and its Foundry JSON to begin."))
        self.update_placement_hint()
        self.refresh()
        if not self.project_path:
            self.setWindowTitle(f"DALE {__version__} — " + self.t("Floor overlay editor"))
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
                self.t(
                    "Contour preview updated. Apply Remove outside/inside to use these settings."
                ),
                7000,
            )

    def can_discard(self):
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
            "junction_policy": self.view.junction_policy,
            "language": self.language,
        }

    def save_project_file(self, checked=False, save_as=False):
        if not self.view.session:
            return False
        if self.view.stroke or self.view.drag_base is not None:
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
            self.setWindowTitle(f"{path.name} — DALE {__version__}")
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
            self.walls_action.setChecked(settings["show_walls"])
            self.view.show_walls = settings["show_walls"]
            self.junction_delete.setCurrentIndex(
                0 if settings["junction_policy"] == "continue" else 1
            )
            self.view.junction_policy = settings["junction_policy"]
            self.mode_actions[settings["mode"]].setChecked(True)
            self.view.set_mode(settings["mode"])
            self.view.pending = list(settings["pending_closure"])
            self.view.setTransform(QTransform.fromScale(settings["zoom"], settings["zoom"]))
            self.view.centerOn(*settings["center"])
            self.project_path = path
            self.saved_state = self.document_state()
            self.info.setText(
                f"{path.name}\n{session.source.size[0]:,} × {session.source.size[1]:,} px"
            )
            self.setWindowTitle(f"{path.name} — DALE {__version__}")
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
        json_path, _ = QFileDialog.getOpenFileName(
            self,
            self.t("Open matching Foundry JSON"),
            str(Path(image_path).with_suffix(".json")),
            self.t("JSON files (*.json)"),
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
            if self.loaded_project:
                self.loaded_project.close()
                self.loaded_project = None
            self.project_path = None
            self.saved_state = self.document_state()
            self.setWindowTitle(f"DALE {__version__} — " + self.t("Floor overlay editor"))
        except Exception as exc:
            self.warning("Cannot open source pair", str(exc))

    def refresh(self):
        self.view.refresh()
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
                "click to snap, Ctrl/Alt-click for corners, click to snap the end.",
            )
            return
        if (
            analysis.unresolved
            and self.question(
                "Review open contours",
                self.t(
                    "{count} unresolved segments remain (orange). "
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
        if self.view.pending or self.view.stroke or self.view.drag_base is not None:
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
        self.worker = ExportWorker(self.view.session, Path(path), placement, self)
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
                "language": window.language,
                "window_visible": window.isVisible(),
                "project_loaded": bool(window.project_path),
                "dimensions": window.view.session.source.size if window.view.session else None,
                "operations": len(window.view.session.operations) if window.view.session else 0,
            }
            options.smoke_report.write_text(json.dumps(report), encoding="utf-8")
            window.grab().save(str(options.smoke_report.with_suffix(".png")))
            app.quit()

        QTimer.singleShot(500, smoke_report)
    sys.exit(app.exec())
