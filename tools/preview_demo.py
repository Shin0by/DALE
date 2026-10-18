"""Render the synthetic editor workflow offscreen for visual inspection."""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from dale.editing import add_line
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
session.add(add_line(session.geometry(), (950, 650), (1050, 750)))
window = MainWindow()
window.show()
app.processEvents()
window.view.assign(session, load_preview(source))
window.info.setText("Synthetic demonstration\n1,200 × 900 px\nNot a Dungeon Alchemist export")
window.activate_mode("Edit points")
window.refresh()
window.project_path = ROOT / "artifacts/demo/demo.dale"
assert window.save_project_file()
app.processEvents()
destination = ROOT / "artifacts/demo/editor-preview.png"
window.grab().save(str(destination))
print(destination)
window.set_language("en", persist=False)
app.processEvents()
english = destination.with_name("editor-preview-en.png")
window.grab().save(str(english))
print(english)
window.set_language("ru", persist=False)
window.activate_mode("Erase lines")
window.view.cursor_point = (990, 690)
window.view.geometry_diameter = 50
window.geometry_brush_control.setValue(50)
window.region_control.setCurrentIndex(1)
app.processEvents()
eraser = destination.with_name("geometry-eraser-preview.png")
window.grab().save(str(eraser))
print(eraser)
window.tool_set_actions["pixels"].trigger()
app.processEvents()
pixel_tools = destination.with_name("pixel-tools-preview.png")
window.grab().save(str(pixel_tools))
print(pixel_tools)
window.resize(1224, 768)
app.processEvents()
minimum = destination.with_name("minimum-window-preview.png")
window.grab().save(str(minimum))
print(minimum)
# No event loop is entered and no desktop window is shown by the offscreen platform.
