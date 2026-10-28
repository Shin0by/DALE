"""All standard slider tracks jump to the clicked position under the application style."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSlider, QStyle, QStyleOptionSlider

from dale.application_style import DaleStyle


@pytest.fixture
def slider_style():
    app = QApplication.instance() or QApplication([])
    previous = app.style().objectName() or "Fusion"
    style = DaleStyle()
    app.setStyle(style)
    yield app
    app.setStyle(previous)


@pytest.mark.parametrize("orientation", [Qt.Orientation.Horizontal, Qt.Orientation.Vertical])
@pytest.mark.parametrize("inverted", [False, True])
@pytest.mark.parametrize("target", [15, 80])
def test_track_click_sets_absolute_value(slider_style, orientation, inverted, target):
    slider = QSlider(orientation)
    slider.setRange(-1, 100)
    slider.setSingleStep(1)
    slider.setPageStep(1)
    slider.setInvertedAppearance(inverted)
    slider.resize(420, 40) if orientation == Qt.Orientation.Horizontal else slider.resize(40, 420)
    slider.setValue(50)
    slider.show()
    slider_style.processEvents()
    option = QStyleOptionSlider()
    slider.initStyleOption(option)
    style = slider.style()
    handle = style.subControlRect(
        QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, slider
    )
    horizontal = orientation == Qt.Orientation.Horizontal
    extent = handle.width() if horizontal else handle.height()
    span = (slider.width() if horizontal else slider.height()) - extent
    offset = QStyle.sliderPositionFromValue(-1, 100, target, span, option.upsideDown) + extent // 2
    point = (
        QPoint(offset, handle.center().y()) if horizontal else QPoint(handle.center().x(), offset)
    )
    QTest.mouseClick(slider, Qt.MouseButton.LeftButton, pos=point)
    assert slider.value() == pytest.approx(target, abs=1)
    clicked = slider.value()
    QTest.keyClick(slider, Qt.Key.Key_Right if horizontal else Qt.Key.Key_Up)
    assert abs(slider.value() - clicked) == 1
    slider.close()
    slider.deleteLater()
    slider_style.processEvents()


def test_drag_only_commits_value_on_release(slider_style):
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.resize(420, 40)
    slider.setRange(0, 100)
    slider.setValue(25)
    slider.show()
    slider_style.processEvents()
    assert not slider.hasTracking()
    values = []
    slider.valueChanged.connect(values.append)
    option = QStyleOptionSlider()
    slider.initStyleOption(option)
    handle = slider.style().subControlRect(
        QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, slider
    )
    QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=handle.center())
    for x in (200, 250, 320):
        QTest.mouseMove(slider, QPoint(x, handle.center().y()))
        slider_style.processEvents()
        assert slider.value() == 25 and not values
    assert slider.sliderPosition() > 70
    QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=QPoint(320, handle.center().y()))
    assert len(values) == 1 and slider.value() > 70
    slider.close()
    slider.deleteLater()
    slider_style.processEvents()


def test_absolute_press_waits_for_release(slider_style):
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.resize(420, 40)
    slider.setRange(0, 100)
    slider.setValue(10)
    slider.show()
    slider_style.processEvents()
    values = []
    slider.valueChanged.connect(values.append)
    QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=QPoint(330, 20))
    assert not values and slider.value() == 10
    QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=QPoint(330, 20))
    assert len(values) == 1 and slider.value() > 70
    slider.close()
    slider.deleteLater()
    slider_style.processEvents()
