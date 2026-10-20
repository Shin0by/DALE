"""Standard folder browser with an editable final PNG export destination."""

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
)

from dale.overlay_export import next_export_directory


class ExportDirectoryDialog(QFileDialog):
    def __init__(self, parent, directory, stem):
        super().__init__(parent, parent.t("Export separate PNGs"), str(directory))
        self.setObjectName("exportDirectoryDialog")
        self.setOption(QFileDialog.Option.DontUseNativeDialog)
        self.setOption(QFileDialog.Option.ShowDirsOnly, False)
        self.setNameFilter(parent.t("Export assets (*.json *.png)"))
        self.setFileMode(QFileDialog.FileMode.Directory)
        self.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        self.setLabelText(QFileDialog.DialogLabel.FileName, parent.t("Export folder:"))
        self.setLabelText(QFileDialog.DialogLabel.Accept, parent.t("Export"))
        self.setLabelText(QFileDialog.DialogLabel.Reject, parent.t("Cancel"))
        self.findChild(QComboBox, "fileTypeCombo").hide()
        self.findChild(QLabel, "fileTypeLabel").hide()
        self.stem = stem
        self.destination = None
        self.entered_directory = False
        self.directoryEntered.connect(self.on_directory_entered)
        self.export_button = self.findChild(QDialogButtonBox).button(
            QDialogButtonBox.StandardButton.Save
        )
        editor = self.findChild(QLineEdit, "fileNameEdit")
        editor.textChanged.connect(self.update_export_button)
        self.selectFile(next_export_directory(Path(directory), stem).name)
        self.update_export_button()
        editor.setToolTip(
            parent.control_help(
                "Choose an existing folder or enter a new folder name. "
                "PNG files are saved directly inside it.",
                title="Export folder",
            )
        )

    def update_export_button(self):
        # Unlike Qt's existing-directory picker, this browser also accepts new folder names.
        self.export_button.setText(self.parentWidget().t("Export"))
        self.export_button.setEnabled(True)

    def on_directory_entered(self):
        self.entered_directory = True
        self.update_export_button()

    def accept(self):
        directory = Path(self.directory().absolutePath())
        text = self.findChild(QLineEdit, "fileNameEdit").text().strip()
        files = self.selectedFiles()
        path = (
            Path(files[0])
            if text and files
            else directory
            if self.entered_directory
            else next_export_directory(directory, self.stem)
        )
        path = path.resolve()
        if (path.exists() and not path.is_dir()) or not path.parent.is_dir():
            QMessageBox.warning(
                self,
                self.parentWidget().t("Export folder"),
                self.parentWidget().t("Choose an existing folder or a new folder inside it."),
            )
            return
        self.destination = path
        QDialog.accept(self)


def choose_export_directory(parent, directory, stem):
    dialog = ExportDirectoryDialog(parent, directory, stem)
    try:
        return dialog.destination if dialog.exec() == QDialog.DialogCode.Accepted else None
    finally:
        dialog.deleteLater()
