"""Render the synthetic editor workflow offscreen for visual inspection."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dale.raster import load_preview
from dale.scene import load_pair
from dale.session import Closure, ContourMask, Session, Stroke
from dale.ui import MainWindow, configure_application

ROOT = Path(__file__).resolve().parents[1]
app = QApplication([])
configure_application(app)
source = load_pair(ROOT / "artifacts/demo/demo.jpg", ROOT / "artifacts/demo/demo.json")
session = Session(source)
session.add(Closure(((200, 350), (180, 400), (180, 450), (200, 500))))
session.add(ContourMask(session.analysis().area, "outside"))
session.add(Stroke(((740, 510), (780, 550)), 30))
window = MainWindow()
window.show()
app.processEvents()
window.view.assign(session, load_preview(source))
window.info.setText("Synthetic demonstration\n1,200 × 900 px\nNot a Dungeon Alchemist export")
window.elevation.setCurrentText("17")
window.refresh()
app.processEvents()
destination = ROOT / "artifacts/demo/editor-preview.png"
window.grab().save(str(destination))
print(destination)
# No event loop is entered and no desktop window is shown by the offscreen platform.
