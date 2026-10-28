"""Windows Alt wheel X deltas retain both zoom directions and cursor anchoring."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QTransform, QWheelEvent
from PySide6.QtWidgets import QApplication

from dale.ui import MainWindow


@pytest.fixture
def zoom_window(pair_factory, tmp_path):
    app = QApplication.instance() or QApplication([])
    source = pair_factory()
    window = MainWindow(preferences_path=tmp_path / "settings.json")
    window.warning = lambda *args: pytest.fail(str(args))
    window.can_discard = lambda: True
    window.load_sources(source.image_path, source.json_path)
    window.activate_mode("Pan")
    window.show()
    app.processEvents()
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("route", ["view", "viewport"])
@pytest.mark.parametrize(
    "delta,alt,factor",
    [
        ((0, 120), False, 1.2),
        ((0, -120), False, 1 / 1.2),
        ((120, 0), True, 1.2),
        ((-120, 0), True, 1 / 1.2),
        ((0, 120), True, 1.2),
        ((0, -120), True, 1 / 1.2),
        ((-120, 120), True, 1.2),
        ((120, 0), False, 1),
        ((0, 0), False, 1),
        ((0, 0), True, 1),
    ],
)
def test_zoom_sign_matches_plain_wheel(zoom_window, route, delta, alt, factor):
    view = zoom_window.view
    point = view.viewport().rect().center()
    anchor, scale = view.mapToScene(point), view.transform().m11()
    geometry, history = view.session.geometry(), tuple(view.session.operations)
    modifiers = Qt.KeyboardModifier.AltModifier if alt else Qt.KeyboardModifier.NoModifier
    event = QWheelEvent(
        QPointF(point),
        QPointF(view.viewport().mapToGlobal(point)),
        QPoint(),
        QPoint(*delta),
        Qt.MouseButton.NoButton,
        modifiers,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    if route == "view":
        view.wheelEvent(event)
    else:
        QApplication.sendEvent(view.viewport(), event)
    assert view.transform().m11() == pytest.approx(scale * factor)
    after = view.mapToScene(point)
    assert (after.x(), after.y()) == pytest.approx((anchor.x(), anchor.y()), abs=1e-6)
    assert view.session.geometry() == geometry
    assert tuple(view.session.operations) == history


@pytest.mark.parametrize("zoom", [1e-4, 826.0])
def test_saved_extreme_zoom_is_bounded_without_rewriting_project(zoom_window, tmp_path, zoom):
    window, view = zoom_window, zoom_window.view
    geometry = view.session.geometry()
    view.setTransform(QTransform.fromScale(zoom, zoom))
    view.centerOn(view.image_rect.center())
    window.project_path = tmp_path / "Extreme camera.dale"
    assert window.save_project_file()
    archive = window.project_path.read_bytes()
    assert window.load_project_file(window.project_path)
    actual = view.transform().m11()
    assert actual == pytest.approx(view.bounded_zoom(zoom))
    assert actual <= 16
    assert actual * max(view.session.source.size) >= 32
    assert view.session.geometry().walls == geometry.walls
    assert window.project_path.read_bytes() == archive


@pytest.mark.parametrize("zoom,delta", [(826.0, -120), (1e-9, 120), (16.0, 120)])
def test_wheel_recovers_invalid_zoom_and_respects_limit(zoom_window, zoom, delta):
    view = zoom_window.view
    view.setTransform(QTransform.fromScale(zoom, zoom))
    point = view.viewport().rect().center()
    event = QWheelEvent(
        QPointF(point),
        QPointF(view.viewport().mapToGlobal(point)),
        QPoint(),
        QPoint(0, delta),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    view.wheelEvent(event)
    assert view.transform().m11() == pytest.approx(view.bounded_zoom(zoom))


def test_cursor_leave_between_document_clear_and_assign_is_safe(zoom_window):
    view = zoom_window.view
    view.clear_map()
    view.leaveEvent(QEvent(QEvent.Type.Leave))
    assert view.warning_geometry.is_empty
    assert view.hover_path.isEmpty()
