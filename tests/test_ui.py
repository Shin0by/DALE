"""Exercise actual Qt pointer events offscreen, without controlling the owner's desktop."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QTransform
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from dale.canvas import MapView
from dale.raster import load_preview
from dale.session import Closure, Session, Stroke
from dale.ui import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("mode", ["Pan", "Erase", "Restore", "Closure"])
@pytest.mark.parametrize("zoomed", [False, True])
def test_right_drag_pans_in_every_mode_without_editing(app, pair_factory, mode, zoomed):
    source = pair_factory()
    view = MapView()
    view.resize(500, 400)
    view.show()
    view.assign(Session(source), load_preview(source))
    if zoomed:
        view.setTransform(QTransform.fromScale(12, 12))
        view.centerOn(40, 150)
    view.set_mode(mode)
    app.processEvents()
    before = view.horizontalScrollBar().value(), view.verticalScrollBar().value()
    point = QPoint(200, 160)
    QTest.mousePress(view.viewport(), Qt.MouseButton.RightButton, pos=point)
    QTest.mouseMove(view.viewport(), point + QPoint(40, 30))
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.RightButton, pos=point + QPoint(40, 30))
    after = view.horizontalScrollBar().value(), view.verticalScrollBar().value()
    assert after == (before[0] - 40, before[1] - 30)
    assert not view.session.operations
    assert not view.panning
    view.close()


def test_closure_click_modifiers_and_escape(app, pair_factory):
    source = pair_factory(walls=[{"c": [10, 20, 60, 20]}, {"c": [60, 20, 60, 270]}])
    view = MapView()
    view.resize(500, 700)
    view.show()
    view.assign(Session(source), load_preview(source))
    view.set_mode("Closure")
    app.processEvents()

    def click(point, modifiers=Qt.KeyboardModifier.NoModifier):
        QTest.mouseClick(
            view.viewport(), Qt.MouseButton.LeftButton, modifiers, view.mapFromScene(*point)
        )

    click((30, 21))
    assert len(view.pending) == 1
    assert view.pending[0][1] == 20
    click((15, 130), Qt.KeyboardModifier.ControlModifier)
    click((25, 220), Qt.KeyboardModifier.AltModifier)
    click((59, 250))
    assert isinstance(view.session.operations[0], Closure)
    assert len(view.session.operations[0].points) == 4
    assert view.session.operations[0].points[-1][0] == 60
    click((30, 20))
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert not view.pending
    assert len(view.session.operations) == 1
    view.close()


def test_brush_drag_is_one_undo_step(app, pair_factory):
    source = pair_factory()
    view = MapView()
    view.resize(500, 700)
    view.show()
    view.assign(Session(source), load_preview(source))
    view.set_mode("Erase")
    app.processEvents()
    start, end = view.mapFromScene(20, 40), view.mapFromScene(50, 70)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(view.viewport(), end)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
    assert len(view.session.operations) == 1
    assert isinstance(view.session.operations[0], Stroke)
    view.session.undo()
    assert not view.session.operations
    view.close()


def test_version_and_integer_elevation_controls(app):
    window = MainWindow()
    assert [window.elevation.itemText(i) for i in range(4)] == ["-20", "-15", "-10", "-5"]
    window.elevation.setCurrentText("17")
    window.version.setCurrentIndex(1)
    assert window.placement().foundry_major == 13
    assert window.placement().elevation_ft == 17
    window.version.setCurrentIndex(0)
    assert window.placement().foundry_major == 14
    window.elevation.setCurrentText("1.5")
    with pytest.raises(ValueError, match="whole"):
        window.placement()
    window.close()
