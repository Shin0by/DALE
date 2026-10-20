"""Transactional dataset manager dialog and explicit component drag/drop."""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from dale.datasets import DatasetCatalog, copy_session
from dale.localization import format_tooltip, translate
from dale.project_io import load_project, read_json_documents
from dale.scene import load_pair
from dale.session import Session

MIME = "application/x-dale-dataset-component"

BUTTON_HELP = {
    "+ New dataset": "Create an empty dataset for its own image and contours.",
    "Delete dataset": "Delete this dataset and its edits. External source files are kept.",
    "Load JSON": "Load contours from a JSON file or DALE project. Keep the current image.",
    "Replace JSON": "Replace the current JSON and contour edits. Keep the image.",
    "Merge contours": "Add contours from another JSON without replacing existing ones. Export one "
    "combined JSON; exact copies are skipped.",
    "Load image": "Load an image without moving existing contours. An empty dataset also loads a "
    "same-name JSON beside the image.",
    "Replace image": "Replace the image and its raster edits. Keep contour coordinates.",
    "To another dataset": "Move or copy this file and its edits to another dataset. A copy is "
    "independent.",
    "Delete JSON": "Remove the JSON and all contour edits. Keep the image and external files.",
    "Delete image": "Remove the image and raster edits. Keep contours and external files.",
    "Import datasets": "Copy complete datasets from another .dale project into this project.",
    "Export dataset": "Add this dataset and its edits to an existing .dale project without opening "
    "it.",
    "Cancel": "Close without applying pending changes. Previously applied changes remain.",
    "Apply": "Apply changes to the editor and keep this window open. Save project writes them to "
    "disk.",
    "Open dataset": "Apply changes, open the selected dataset and close this window. Save project "
    "writes changes to disk.",
}

BUTTON_CONDITIONS = {
    "Delete dataset": "A dataset is selected; deleting the last one leaves an empty dataset.",
    "Replace JSON": "The selected dataset has JSON or contours.",
    "Merge contours": "The selected dataset already has JSON or drawn contours.",
    "Replace image": "The selected dataset has an image.",
    "To another dataset": "This file exists and there is another dataset to receive it.",
    "Delete JSON": "The selected dataset has JSON or contours.",
    "Delete image": "The selected dataset has an image.",
    "Import datasets": "Choose an existing source .dale project.",
    "Export dataset": "Choose an existing destination .dale project.",
    "Open dataset": "Select the dataset to edit.",
}


class DatasetTree(QTreeWidget):
    transfer_requested = Signal(str, str, str)

    def __init__(self, parent):
        super().__init__(parent)
        self.token = uuid4().hex
        self.setObjectName("datasetTree")
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)

    def startDrag(self, supported_actions):
        item = self.currentItem()
        value = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not value or not value[1]:
            return
        data = QMimeData()
        data.setData(MIME, json.dumps([self.token, *value]).encode())
        drag = QDrag(self)
        drag.setMimeData(data)
        drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()

    def dropEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if not item or not event.mimeData().hasFormat(MIME):
            return
        try:
            token, source, kind = json.loads(bytes(event.mimeData().data(MIME)))
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if not data and item.parent():
                data = item.parent().data(0, Qt.ItemDataRole.UserRole)
            target = data[0]
            if token != self.token or kind not in ("json", "image") or source == target:
                return
            self.transfer_requested.emit(source, target, kind)
            event.acceptProposedAction()
        except (ValueError, TypeError, IndexError):
            event.ignore()


class DatasetManager(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.catalog = (
            owner.catalog.fork() if owner.catalog else DatasetCatalog(ui=owner.project_ui_state())
        )
        if owner.catalog is None:
            self.catalog.rename(f"{self.t('Dataset')} 1")
        self.selected = self.catalog.active_key
        self.setObjectName("datasetManager")
        self.setWindowTitle(self.t("Dataset manager"))
        self.resize(980, 660)
        self.setMinimumSize(840, 600)
        self._refreshing = False
        layout = QVBoxLayout(self)
        columns = QHBoxLayout()
        left = QWidget()
        left.setFixedWidth(320)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        tools = QHBoxLayout()
        self.new_button = self.button("+ New dataset", self.new_dataset)
        self.delete_button = self.button("Delete dataset", self.delete_dataset)
        tools.addWidget(self.new_button, 1)
        tools.addWidget(self.delete_button, 1)
        left_layout.addLayout(tools)
        self.tree = DatasetTree(self)
        self.tree.currentItemChanged.connect(self.select_item)
        self.tree.itemDoubleClicked.connect(lambda *_: self.apply(True))
        self.tree.transfer_requested.connect(self.transfer)
        left_layout.addWidget(self.tree, 1)
        project_actions = QHBoxLayout()
        self.import_project_button = self.button("Import datasets", self.import_project)
        self.export_project_button = self.button("Export dataset", self.export_project)
        project_actions.addWidget(self.import_project_button, 1)
        project_actions.addWidget(self.export_project_button, 1)
        left_layout.addLayout(project_actions)
        columns.addWidget(left)
        right = QWidget()
        details = QVBoxLayout(right)
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("datasetName")
        self.name_edit.setMaxLength(240)
        self.name_edit.setToolTip(
            self.help("Rename the dataset. Export filenames follow this name.")
        )
        self.name_edit.editingFinished.connect(self.rename_dataset)
        form = QFormLayout()
        form.addRow(self.t("Set name"), self.name_edit)
        details.addLayout(form)
        self.file_fields = {}
        self.component_buttons = {}
        for kind, title in (("json", "Scene JSON"), ("image", "Scene image")):
            details.addSpacing(10)
            details.addWidget(QLabel(self.t(title)))
            field = QLineEdit()
            field.setObjectName(kind + "Filename")
            field.setMaxLength(256)
            field.setToolTip(self.help("Rename this file label without changing its contents."))
            field.editingFinished.connect(lambda k=kind: self.rename_file(k))
            details.addWidget(field)
            self.file_fields[kind] = field
            actions = QHBoxLayout()
            load = self.button(
                "Load JSON" if kind == "json" else "Load image",
                lambda k=kind: self.import_component(k),
            )
            actions.addWidget(load)
            if kind == "json":
                self.add_json_button = self.button(
                    "Merge contours", lambda: self.import_component("json", append=True)
                )
                self.add_json_button.setObjectName("addDatasetJson")
                actions.addWidget(self.add_json_button)
            send = self.button(
                "To another dataset", lambda k=kind: self.transfer(self.selected, None, k)
            )
            remove = self.button(
                "Delete JSON" if kind == "json" else "Delete image",
                lambda k=kind: self.remove_component(k),
            )
            actions.addWidget(send)
            actions.addWidget(remove)
            details.addLayout(actions)
            self.component_buttons[kind] = load, send, remove
        details.addSpacing(18)
        details.addWidget(QLabel(self.t("Export filename prefix")))
        self.export_names = QLabel()
        self.export_names.setObjectName("datasetExportNames")
        self.export_names.setTextFormat(Qt.TextFormat.PlainText)
        self.export_names.setWordWrap(True)
        details.addWidget(self.export_names)
        note = QLabel(
            self.t(
                "Exports add the selected-region number and PNG dimensions. "
                "Names and paths inside JSON are preserved."
            )
        )
        note.setWordWrap(True)
        details.addWidget(note)
        details.addStretch()
        columns.addWidget(right, 1)
        layout.addLayout(columns, 1)
        self.status = QLabel(
            self.t("Drag JSON or an image onto another dataset. Changes apply together.")
        )
        self.status.setWordWrap(True)
        footer = QHBoxLayout()
        footer.addWidget(self.status, 1)
        footer.addWidget(self.button("Cancel", self.reject))
        self.apply_button = self.button("Apply", lambda: self.apply(False))
        self.open_button = self.button("Open dataset", lambda: self.apply(True))
        self.open_button.setDefault(True)
        footer.addWidget(self.apply_button)
        footer.addWidget(self.open_button)
        layout.addLayout(footer)
        self.rebuild()

    def t(self, text, **values):
        return translate(text, self.owner.language, **values)

    def help(self, text, *, condition=None, keys=(), title=None):
        return format_tooltip(
            [text], self.owner.language, condition=condition, keys=keys, title=title
        )

    def button(self, text, callback):
        button = QPushButton()
        self.describe_button(button, text)
        # clicked(bool) must not override default-captured component kinds.
        button.clicked.connect(lambda _checked=False: callback())
        return button

    def describe_button(self, button, text):
        button.setText(self.t(text))
        button.setAccessibleName(self.t(text))
        keys = {
            "Cancel": ["Escape: close without applying pending changes."],
            "Open dataset": ["Enter: apply changes and open the selected dataset."],
        }.get(text, [])
        button.setToolTip(
            self.help(
                BUTTON_HELP[text], condition=BUTTON_CONDITIONS.get(text), keys=keys, title=text
            )
        )

    def warning(self, exc):
        self.owner.warning("Cannot update datasets", str(exc))

    def change(self, operation):
        candidate = self.catalog.fork()
        try:
            result = operation(candidate)
            candidate.prepare()
        except Exception as exc:
            self.warning(exc)
            return False
        self.catalog = candidate
        if self.selected not in candidate.views:
            self.selected = candidate.active_key
        self.rebuild()
        return result if result is not None else True

    def rebuild(self):
        self._refreshing = True
        self.tree.blockSignals(True)
        self.tree.clear()
        for key, view in self.catalog.views.items():
            root = QTreeWidgetItem([view.name])
            root.setData(0, Qt.ItemDataRole.UserRole, (key, None))
            root.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsDropEnabled
            )
            root.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
            self.tree.addTopLevelItem(root)
            for kind, present in (("json", view.has_json), ("image", view.has_image)):
                if present:
                    child = QTreeWidgetItem([view.filename(kind)])
                    child.setData(0, Qt.ItemDataRole.UserRole, (key, kind))
                    child.setToolTip(
                        0, self.t("Drag to another dataset, then choose Move or Copy.")
                    )
                    child.setFlags(
                        Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsSelectable
                        | Qt.ItemFlag.ItemIsDragEnabled
                    )
                    child.setIcon(0, self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
                    root.addChild(child)
            if not view.has_json and not view.has_image:
                root.addChild(QTreeWidgetItem([self.t("Empty dataset")]))
            root.setExpanded(True)
            if key == self.selected:
                self.tree.setCurrentItem(root)
        self.tree.blockSignals(False)
        self._refreshing = False
        self.refresh_fields()

    def select_item(self, item, previous):
        if self._refreshing or not item:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data and item.parent():
            data = item.parent().data(0, Qt.ItemDataRole.UserRole)
        if data:
            self.selected = data[0]
            self.refresh_fields()

    def refresh_fields(self):
        self._refreshing = True
        view = self.catalog.views[self.selected]
        self.name_edit.setText(view.name)
        self.add_json_button.setEnabled(view.has_json)
        names = []
        for kind, present in (("json", view.has_json), ("image", view.has_image)):
            field = self.file_fields[kind]
            filename = Path(view.filename(kind) or "")
            field.setText(filename.stem if present else "")
            field.setEnabled(present)
            field.setPlaceholderText(self.t("No JSON" if kind == "json" else "No image"))
            load, send, remove = self.component_buttons[kind]
            self.describe_button(
                load,
                ("Replace JSON" if present else "Load JSON")
                if kind == "json"
                else ("Replace image" if present else "Load image"),
            )
            send.setEnabled(present and len(self.catalog.views) > 1)
            remove.setEnabled(present)
            if present:
                names.append(view.name + (".json" if kind == "json" else filename.suffix))
        self.export_names.setText(view.name if names else self.t("Empty dataset"))
        self._refreshing = False

    def rename_dataset(self):
        if not self._refreshing and self.name_edit.text() != self.catalog.views[self.selected].name:
            return self.change(lambda catalog: catalog.rename(self.name_edit.text(), self.selected))
        return True

    def rename_file(self, kind):
        if self._refreshing:
            return
        field = self.file_fields[kind]
        if (
            field.isEnabled()
            and field.text() != Path(self.catalog.views[self.selected].filename(kind)).stem
        ):
            self.change(lambda catalog: catalog.rename_file(self.selected, kind, field.text()))

    def new_dataset(self):
        def operation(catalog):
            index = 1
            while any(
                view.name == f"{self.t('Dataset')} {index}" for view in catalog.views.values()
            ):
                index += 1
            view = catalog.create(f"{self.t('Dataset')} {index}", ui=self.owner.project_ui_state())
            self.selected = view.id

        self.change(operation)
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def confirm(self, title, text):
        return (
            QMessageBox.question(
                self,
                self.t(title),
                self.t(text),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            == QMessageBox.StandardButton.Yes
        )

    def delete_dataset(self):
        if self.confirm(
            "Delete dataset", "Delete this dataset and its edits? External source files are kept."
        ):

            def operation(catalog):
                last = len(catalog.views) == 1
                catalog.remove(self.selected)
                if last:
                    catalog.rename(f"{self.t('Dataset')} 1")

            self.change(operation)

    def remove_component(self, kind):
        text = (
            "Delete JSON and all current contours? The image is kept."
            if kind == "json"
            else "Delete the image and its raster edits? Contours are kept."
        )
        if self.confirm("Delete", text):
            self.change(lambda catalog: catalog.replace_component(self.selected, kind))

    def freeze(self, source):
        self.catalog.protected_inputs.update(p for p in (source.json_path, source.image_path) if p)
        workspace = tempfile.TemporaryDirectory(prefix="dale-dataset-")
        root = Path(workspace.name)
        try:
            image = None
            if source.image_path:
                image = root / ("image" + Path(source.image_name or source.image_path.name).suffix)
                shutil.copyfile(source.image_path, image)
            scene = None
            if source.json_bytes is not None:
                scene = root / "scene.json"
                scene.write_bytes(source.json_bytes)
            frozen = replace(source, image_path=image, json_path=scene)
            self.owner.json_workspaces.append(workspace)
            return frozen
        except Exception:
            workspace.cleanup()
            raise

    def import_component(self, kind, append=False):
        selected, _ = QFileDialog.getOpenFileName(
            self,
            self.t(
                "Merge contours" if append else "Scene JSON" if kind == "json" else "Scene image"
            ),
            str(self.owner.input_directory or Path.cwd()),
            self.t("Scene JSON or DALE project (*.json *.dale)")
            if kind == "json"
            else self.t("Scene images (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff)"),
        )
        if not selected:
            return
        path = Path(selected)
        try:
            if path.suffix.lower() == ".dale":
                documents = read_json_documents(path)
                dialog = QDialog(self)
                dialog.setObjectName("jsonDocumentSelection")
                dialog.setWindowTitle(self.t("Scene JSON"))
                layout = QVBoxLayout(dialog)
                choices = QComboBox()
                for doc in documents:
                    choices.addItem(
                        self.t("Current contours (DALE)") + " - " + doc.name
                        if doc.is_current
                        else doc.name
                    )
                choices.setCurrentIndex(
                    next((i for i, doc in enumerate(documents) if doc.is_current), 0)
                )
                layout.addWidget(choices)
                buttons = QDialogButtonBox(
                    QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
                )
                buttons.accepted.connect(dialog.accept)
                buttons.rejected.connect(dialog.reject)
                buttons.button(QDialogButtonBox.StandardButton.Ok).setText(self.t("Import"))
                buttons.button(QDialogButtonBox.StandardButton.Ok).setToolTip(
                    self.help(
                        BUTTON_HELP["Merge contours" if append else "Replace JSON"], title="Import"
                    )
                )
                buttons.button(QDialogButtonBox.StandardButton.Cancel).setToolTip(
                    self.help(
                        "Cancel this operation without changing the datasets.",
                        keys=["Escape: cancel."],
                        title="Cancel",
                    )
                )
                buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName(
                    "importSelectedJson"
                )
                save = buttons.addButton(
                    self.t("Save JSON"), QDialogButtonBox.ButtonRole.ActionRole
                )
                save.setObjectName("saveSelectedJson")
                save.setToolTip(
                    self.help(
                        "Save the selected JSON to a separate file without importing it.",
                        title="Save JSON",
                    )
                )
                save.clicked.connect(
                    lambda: self.owner.save_catalog_json(documents[choices.currentIndex()], path)
                )
                layout.addWidget(buttons)
                if not documents or dialog.exec() != QDialog.DialogCode.Accepted:
                    return
                document = documents[choices.currentIndex()]
                from dale.scene import scene_from_json

                source = replace(scene_from_json(document.data), json_name=document.name)
            else:
                current = self.catalog.views[self.selected]
                companion = path.with_suffix(".json")
                source = load_pair(
                    path if kind == "image" else None,
                    path
                    if kind == "json"
                    else companion
                    if not current.has_json and not current.has_image and companion.is_file()
                    else None,
                )
            incoming = Session(self.freeze(source))
            current = self.catalog.views[self.selected]
            paired = (
                kind == "image"
                and not current.has_json
                and not current.has_image
                and source.json_bytes is not None
            )

            def replace_components(catalog):
                catalog.replace_component(self.selected, kind, incoming)
                if paired:
                    catalog.replace_component(self.selected, "json", incoming)

            operation = (
                (lambda catalog: catalog.add_json(self.selected, incoming))
                if append
                else replace_components
            )
            result = self.change(operation)
            if result is not False:
                self.owner.remember_directory("input", path.resolve().parent)
                self.status.setText(
                    self.t("JSON added; existing contours are kept.")
                    if append
                    else self.t("Dataset updated. Press Apply to keep changes.")
                )
        except Exception as exc:
            self.warning(exc)

    def transfer(self, source, target, kind):
        dialog = QDialog(self)
        dialog.setObjectName("datasetTransfer")
        dialog.setWindowTitle(self.t("Transfer JSON" if kind == "json" else "Transfer image"))
        layout = QVBoxLayout(dialog)
        name = QLabel(self.catalog.views[source].filename(kind))
        name.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(name)
        choices = QComboBox()
        for key, view in self.catalog.views.items():
            if key != source:
                choices.addItem(view.name, key)
        if target:
            choices.setCurrentIndex(choices.findData(target))
        layout.addWidget(choices)
        collision = QLabel()
        collision.setWordWrap(True)
        layout.addWidget(collision)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setToolTip(
            self.help(
                "Cancel this operation without changing the datasets.",
                keys=["Escape: cancel."],
                title="Cancel",
            )
        )
        move = buttons.addButton(self.t("Move"), QDialogButtonBox.ButtonRole.AcceptRole)
        copy = buttons.addButton(self.t("Copy"), QDialogButtonBox.ButtonRole.ActionRole)
        merge = (
            buttons.addButton(self.t("Merge contours"), QDialogButtonBox.ButtonRole.ActionRole)
            if kind == "json"
            else None
        )
        if merge is not None:
            merge.setToolTip(
                self.help(
                    "Add the current source contours to the destination without replacing its "
                    "contours or image. Keep the source dataset unchanged.",
                    condition="The destination already has JSON or drawn contours.",
                    title="Merge contours",
                )
            )
        move.setToolTip(
            self.help(
                "Move this file and its current edits to the chosen dataset, removing it here.",
                title="Move",
            )
        )
        copy.setToolTip(
            self.help(
                "Copy this file and its current edits to the chosen dataset, "
                "keeping both copies independent.",
                title="Copy",
            )
        )
        outcome = []
        move.clicked.connect(lambda: (outcome.append("move"), dialog.accept()))
        copy.clicked.connect(lambda: (outcome.append("copy"), dialog.accept()))
        if merge is not None:
            merge.clicked.connect(lambda: (outcome.append("merge"), dialog.accept()))
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        def update():
            view = self.catalog.views[choices.currentData()]
            occupied = view.has_json if kind == "json" else view.has_image
            collision.setText(
                self.t(
                    "The destination already contains JSON. Replace it, merge contours or cancel."
                    if occupied and kind == "json"
                    else "The destination already contains this component. Replace it or cancel."
                    if occupied
                    else "Move or copy the current edits to this dataset?"
                )
            )
            move.setText(self.t("Replace and move" if occupied else "Move"))
            copy.setText(self.t("Replace and copy" if occupied else "Copy"))
            if merge is not None:
                merge.setEnabled(occupied)

        choices.currentIndexChanged.connect(update)
        update()
        if dialog.exec() == QDialog.DialogCode.Accepted and outcome:
            destination = choices.currentData()
            if (
                self.change(
                    lambda catalog: (
                        catalog.add_json(destination, catalog.views[source].session)
                        if outcome[0] == "merge"
                        else catalog.transfer(source, destination, kind, move=outcome[0] == "move")
                    )
                )
                is not False
            ):
                self.selected = destination
                self.rebuild()

    def import_project(self):
        selected, _ = QFileDialog.getOpenFileName(
            self,
            self.t("Import datasets from project"),
            str(self.owner.input_directory or Path.cwd()),
            self.t("DALE projects (*.dale)"),
        )
        if not selected:
            return
        try:
            with load_project(Path(selected)) as loaded:
                source = DatasetCatalog.from_catalog(loaded.catalog)
                dialog = QDialog(self)
                dialog.setWindowTitle(self.t("Import datasets from project"))
                layout = QVBoxLayout(dialog)
                choices = QTreeWidget()
                choices.setHeaderHidden(True)
                for key, view in source.views.items():
                    item = QTreeWidgetItem([view.name])
                    item.setData(0, Qt.ItemDataRole.UserRole, key)
                    item.setCheckState(0, Qt.CheckState.Checked)
                    choices.addTopLevelItem(item)
                layout.addWidget(choices)
                buttons = QDialogButtonBox(
                    QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
                )
                buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
                    self.t("Import datasets")
                )
                buttons.button(QDialogButtonBox.StandardButton.Ok).setToolTip(
                    self.help(BUTTON_HELP["Import datasets"], title="Import datasets")
                )
                buttons.button(QDialogButtonBox.StandardButton.Cancel).setToolTip(
                    self.help(
                        "Cancel this operation without changing the datasets.",
                        keys=["Escape: cancel."],
                        title="Cancel",
                    )
                )
                buttons.accepted.connect(dialog.accept)
                buttons.rejected.connect(dialog.reject)
                layout.addWidget(buttons)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return
                incoming = []
                for index in range(choices.topLevelItemCount()):
                    item = choices.topLevelItem(index)
                    if item.checkState(0) == Qt.CheckState.Checked:
                        view = source.views[item.data(0, Qt.ItemDataRole.UserRole)]
                        session = copy_session(view.session)
                        session.source = self.freeze(session.source)
                        incoming.append(replace(view, session=session, ui=dict(view.ui)))

                def operation(catalog):
                    catalog._source_documents = (*catalog.documents, *source.documents)
                    for view in incoming:
                        new = catalog.create(view.name)
                        catalog.views[new.id] = replace(view, id=new.id, name=new.name)
                        self.selected = new.id

                self.change(operation)
                self.owner.remember_directory("input", Path(selected).resolve().parent)
        except Exception as exc:
            self.warning(exc)

    def export_project(self):
        if self.rename_dataset() is False:
            return
        self.owner.export_dataset_to_project(self.catalog, self.selected)
        self.rebuild()

    def apply(self, open_selected):
        if self.rename_dataset() is False:
            return
        if self.owner.apply_dataset_manager(self.catalog, self.selected if open_selected else None):
            self.catalog = self.owner.catalog.fork()
            self.rebuild()
            self.status.setText(
                self.t("Dataset changes applied. Save the project to write them to disk.")
            )
            if open_selected:
                self.accept()
