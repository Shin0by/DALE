"""Absolute slider positioning with a single value commit on mouse release."""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QProxyStyle, QSlider, QStyle, QStyleOptionSlider


class DaleStyle(QProxyStyle):
    def __init__(self):
        super().__init__("Fusion")

    def styleHint(self, hint, option=None, widget=None, returnData=None):
        if hint == QStyle.StyleHint.SH_Slider_AbsoluteSetButtons:
            return Qt.MouseButton.LeftButton.value | Qt.MouseButton.MiddleButton.value
        return super().styleHint(hint, option, widget, returnData)

    def polish(self, target):
        result = super().polish(target)
        if isinstance(target, QSlider):
            target.setTracking(False)
            target.installEventFilter(self)
        return result

    def eventFilter(self, slider, event):
        if not isinstance(slider, QSlider):
            return super().eventFilter(slider, event)
        kind = event.type()
        active = bool(slider.property("dale_absolute_drag"))
        buttons = Qt.MouseButton.LeftButton | Qt.MouseButton.MiddleButton
        if kind == QEvent.Type.MouseButtonPress and event.button() & buttons:
            option = QStyleOptionSlider()
            slider.initStyleOption(option)
            handle = slider.style().subControlRect(
                QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, slider
            )
            if not handle.contains(event.position().toPoint()):
                slider.setProperty("dale_absolute_drag", True)
                slider.setFocus(Qt.FocusReason.MouseFocusReason)
                slider.setSliderDown(True)
                self.position_slider(slider, event.position())
                return True
        if active and kind == QEvent.Type.MouseMove:
            self.position_slider(slider, event.position())
            return True
        if active and kind == QEvent.Type.MouseButtonRelease and event.button() & buttons:
            self.position_slider(slider, event.position())
            slider.setProperty("dale_absolute_drag", False)
            slider.setSliderDown(False)
            return True
        if active and kind in (QEvent.Type.Hide, QEvent.Type.WindowDeactivate):
            slider.setSliderPosition(slider.value())
            slider.setProperty("dale_absolute_drag", False)
            slider.setSliderDown(False)
        return super().eventFilter(slider, event)

    @staticmethod
    def position_slider(slider, point):
        option = QStyleOptionSlider()
        slider.initStyleOption(option)
        style = slider.style()
        groove = style.subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderGroove, slider
        )
        handle = style.subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, slider
        )
        if slider.orientation() == Qt.Orientation.Horizontal:
            position, span = (
                point.x() - groove.x() - handle.width() / 2,
                groove.width() - handle.width(),
            )
        else:
            position = point.y() - groove.y() - handle.height() / 2
            span = groove.height() - handle.height()
        slider.setSliderPosition(
            QStyle.sliderValueFromPosition(
                slider.minimum(), slider.maximum(), round(position), max(1, span), option.upsideDown
            )
        )
