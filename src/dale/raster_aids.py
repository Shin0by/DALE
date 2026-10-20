"""Viewport rulers, cursor crosshair and source-anchored Raster guides."""

import math

from PySide6.QtCore import QEvent, QLineF, QObject, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QLabel, QWidget

from dale.measurement import (
    MAX_GUIDES,
    grid_positions,
    measurement_scale,
    measurement_settings,
    ruler_interval,
)

RULER_TOP = 24
RULER_LEFT = 48


class RulerBar(QWidget):
    def __init__(self, aids, axis):
        super().__init__(aids.view)
        self.aids, self.axis = aids, axis
        self.setObjectName("horizontalRuler" if axis == 0 else "verticalRuler")
        self.setCursor(Qt.CursorShape.SplitVCursor if axis == 0 else Qt.CursorShape.SplitHCursor)
        self.setMouseTracking(True)
        self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#303030"))
        painter.setPen(QColor("#d8d8d8"))
        scale = self.aids.scale()
        if scale is None:
            return
        view, axis = self.aids.view, self.axis
        low = view.mapToScene(QPoint()).x() if axis == 0 else view.mapToScene(QPoint()).y()
        end = view.viewport().rect().bottomRight()
        high = view.mapToScene(end).x() if axis == 0 else view.mapToScene(end).y()
        zoom = abs(view.transform().m11() if axis == 0 else view.transform().m22())
        interval = ruler_interval(scale.pixels_per_unit[axis], zoom)
        step = interval / 5
        start = math.floor(scale.value(low, axis) / step)
        finish = math.ceil(scale.value(high, axis) / step)
        font = painter.font()
        font.setPixelSize(10)
        painter.setFont(font)
        for index in range(start, min(finish + 1, start + 4096)):
            value = index * step
            coordinate = scale.position(value, axis)
            screen = view.viewportTransform().map(
                QPointF(coordinate, 0) if axis == 0 else QPointF(0, coordinate)
            )
            major = index % 5 == 0
            text = f"{0.0 if abs(value) < step * 1e-7 else value:.8g}"
            if axis == 0:
                x = round(screen.x())
                painter.drawLine(x, self.height() - 1, x, self.height() - (10 if major else 5))
                if major:
                    painter.drawText(x + 3, 11, text)
            else:
                y = round(screen.y())
                painter.drawLine(self.width() - 1, y, self.width() - (10 if major else 5), y)
                if major:
                    painter.save()
                    painter.translate(11, y - 3)
                    painter.rotate(-90)
                    painter.drawText(0, 0, text)
                    painter.restore()
        painter.setPen(QColor("#666666"))
        if axis == 0:
            painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        else:
            painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.aids.begin_guide(1 - self.axis, event.globalPosition().toPoint())
            event.accept()

    def mouseMoveEvent(self, event):
        if self.aids.pending is not None:
            self.aids.move_guide(event.globalPosition().toPoint())
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.aids.pending is not None:
            self.aids.end_guide(event.globalPosition().toPoint())
            event.accept()


class RasterAids(QObject):
    changed = Signal()

    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.viewport = view.viewport()
        self.closed = False
        view.destroyed.connect(lambda: setattr(self, "closed", True))
        self.settings = measurement_settings()
        self.pending = None
        self.hover_guide = None
        self.guide_cursor = False
        self.cursor = None
        self.transform_key = None
        self.rulers = (RulerBar(self, 0), RulerBar(self, 1))
        self.corner = QLabel(view)
        self.corner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.corner.setObjectName("rulerCorner")
        self.corner.setStyleSheet("background: #303030;")
        self.corner.hide()
        view.installEventFilter(self)
        view.viewport().installEventFilter(self)
        view.horizontalScrollBar().valueChanged.connect(self.repaint)
        view.verticalScrollBar().valueChanged.connect(self.repaint)

    @property
    def visible(self):
        return bool(self.view.session and self.view.session.source.image_path)

    def snapshot(self):
        return measurement_settings(self.settings)

    def restore(self, value=None):
        self.cancel()
        self.settings = measurement_settings(value)
        self.update_layout()

    def configure(self, **values):
        if values.get("rulers") is False or values.get("move_guides") is False:
            self.cancel()
        self.settings = measurement_settings({**self.settings, **values})
        self.update_layout()
        self.changed.emit()

    def scale(self):
        if not self.view.session:
            return None
        try:
            return measurement_scale(self.view.session.source, self.settings["unit"])
        except ValueError:
            return None

    def update_layout(self):
        self.view.setBackgroundBrush(
            QBrush(QColor(self.settings["background_color"]))
            if self.settings["background_kind"] == "solid"
            else self.view.checker_brush
        )
        self.view.native_preview.set_enabled(self.visible and self.settings["full_resolution"])
        show = self.visible and self.settings["rulers"]
        margins = self.view.viewportMargins()
        left, top = (RULER_LEFT, RULER_TOP) if show else (0, 0)
        if margins.left() != left or margins.top() != top:
            center = self.view.camera_center()
            self.view.setViewportMargins(left, top, 0, 0)
            if self.view.session:
                self.view.centerOn(center)
        for bar in self.rulers:
            bar.setVisible(show)
        self.corner.setVisible(show)
        self.position_rulers()
        self.repaint()

    def position_rulers(self):
        viewport = self.view.viewport()
        p = viewport.pos()
        self.rulers[0].setGeometry(p.x(), p.y() - RULER_TOP, viewport.width(), RULER_TOP)
        self.rulers[1].setGeometry(p.x() - RULER_LEFT, p.y(), RULER_LEFT, viewport.height())
        self.corner.setGeometry(p.x() - RULER_LEFT, p.y() - RULER_TOP, RULER_LEFT, RULER_TOP)

    def repaint(self, *args):
        for ruler in self.rulers:
            ruler.update()
        self.view.viewport().update()

    def begin_guide(self, axis, global_point, index=None):
        if not self.visible or not self.settings["rulers"] or self.view.active_gesture:
            return
        if index is None and len(self.settings["guides"]) >= MAX_GUIDES:
            self.view.message.emit("The raster guide limit has been reached.")
            return
        self.view.setFocus()
        self.pending = {"axis": axis, "position": 0.0, "index": index}
        self.move_guide(global_point)

    def move_guide(self, global_point):
        if self.pending is None:
            return
        p = self.view.mapToScene(self.view.viewport().mapFromGlobal(global_point))
        axis = self.pending["axis"]
        position = p.x() if axis == 0 else p.y()
        scale = self.scale()
        if self.settings["snap"] and scale is not None:
            position = scale.snap(position, axis)
        self.pending["position"] = position
        self.repaint()

    def end_guide(self, global_point):
        self.move_guide(global_point)
        pending, self.pending = self.pending, None
        if pending is None:
            return
        guides = list(self.settings["guides"])
        index, axis, position = pending["index"], pending["axis"], pending["position"]
        local = self.view.viewport().mapFromGlobal(global_point)
        inside = self.view.viewport().rect().contains(local)
        valid = inside and 0 <= position <= self.view.session.source.size[axis]
        guide = {"axis": "x" if axis == 0 else "y", "position": position}
        if index is not None:
            if valid:
                guides[index] = guide
            else:
                guides.pop(index)
        elif valid and guide not in guides:
            guides.append(guide)
        self.configure(guides=guides)

    def cancel(self):
        self.pending = None
        self.hover_guide = None
        if self.guide_cursor:
            self.viewport.unsetCursor()
            self.guide_cursor = False
        self.repaint()

    @property
    def editing_guides(self):
        return self.visible and self.settings["rulers"] and self.settings["move_guides"]

    def guide_at(self, point):
        hits = []
        for i, guide in enumerate(self.settings["guides"]):
            axis = 0 if guide["axis"] == "x" else 1
            p = self.view.viewportTransform().map(
                QPointF(guide["position"], 0) if axis == 0 else QPointF(0, guide["position"])
            )
            distance = abs(point.x() - p.x()) if axis == 0 else abs(point.y() - p.y())
            if distance <= 6:
                hits.append((distance, i, axis))
        return min(hits)[1:] if hits else None

    def hover(self, point):
        hit = self.guide_at(point)
        self.hover_guide = hit[0] if hit else None
        self.viewport.setCursor(
            (Qt.CursorShape.SplitHCursor if hit[1] == 0 else Qt.CursorShape.SplitVCursor)
            if hit
            else Qt.CursorShape.ArrowCursor
        )
        self.guide_cursor = True
        self.repaint()

    def eventFilter(self, watched, event):
        if self.closed:
            return False
        kind = event.type()
        if watched is self.view and kind == QEvent.Type.Resize:
            self.position_rulers()
        if watched is self.viewport:
            if kind == QEvent.Type.Resize:
                self.position_rulers()
            elif kind == QEvent.Type.Paint:
                key = self.view.viewportTransform(), self.view.viewport().size()
                if key != self.transform_key:
                    self.transform_key = key
                    for ruler in self.rulers:
                        ruler.update()
            elif kind == QEvent.Type.MouseMove:
                self.cursor = event.position().toPoint()
                if self.pending is not None:
                    self.move_guide(event.globalPosition().toPoint())
                    return True
                if self.editing_guides and not event.buttons() & Qt.MouseButton.RightButton:
                    self.hover(event.position())
                    return True
                if self.visible and self.settings["crosshair"]:
                    self.view.viewport().update()
            elif kind == QEvent.Type.Leave:
                self.cursor = None
                self.hover_guide = None
                if self.guide_cursor:
                    self.viewport.unsetCursor()
                    self.guide_cursor = False
                self.view.viewport().update()
            elif kind == QEvent.Type.MouseButtonDblClick:
                if self.editing_guides and event.button() == Qt.MouseButton.LeftButton:
                    hit = self.guide_at(event.position())
                    self.cancel()
                    if hit:
                        guides = list(self.settings["guides"])
                        guides.pop(hit[0])
                        self.configure(guides=guides)
                    return True
            elif kind == QEvent.Type.MouseButtonPress:
                if (
                    self.visible
                    and self.settings["rulers"]
                    and event.button() == Qt.MouseButton.LeftButton
                    and (
                        self.editing_guides
                        or event.modifiers() & Qt.KeyboardModifier.ControlModifier
                    )
                ):
                    hit = self.guide_at(event.position())
                    if hit:
                        index, axis = hit
                        self.begin_guide(axis, event.globalPosition().toPoint(), index)
                        return True
                    if self.editing_guides:
                        return True
            elif kind == QEvent.Type.MouseButtonRelease:
                if self.pending is not None and event.button() == Qt.MouseButton.LeftButton:
                    self.end_guide(event.globalPosition().toPoint())
                    return True
                if self.editing_guides and event.button() == Qt.MouseButton.LeftButton:
                    return True
            elif kind == QEvent.Type.Wheel and self.pending is not None:
                return True
        if kind == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape and self.pending:
            self.cancel()
            return True
        return False

    def draw(self, painter):
        if not self.visible:
            return
        view = self.view
        painter.save()
        painter.resetTransform()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        viewport = view.viewport().rect()

        def pen(color, dashed=False, width=1):
            p = QPen(QColor(color), width)
            p.setCosmetic(True)
            if dashed:
                p.setDashPattern([4, 4])
            return p

        def line(axis, position):
            p = view.viewportTransform().map(
                QPointF(position, 0) if axis == 0 else QPointF(0, position)
            )
            painter.drawLine(
                QLineF(p.x(), 0, p.x(), viewport.height())
                if axis == 0
                else QLineF(0, p.y(), viewport.width(), p.y())
            )

        frame = view.export_grid_frame
        if frame is not None:
            painter.save()
            image = view.viewportTransform().mapRect(view.image_rect).toAlignedRect()
            painter.setClipRect(image.intersected(viewport))
            color = QColor(self.settings["export_grid_color"])
            color.setAlpha(round(255 * (100 - self.settings["export_grid_transparency"]) / 100))
            painter.setPen(pen(color, width=self.settings["export_grid_width"]))
            low, high = view.mapToScene(viewport.topLeft()), view.mapToScene(viewport.bottomRight())
            for axis in (0, 1):
                start = max(0, low.x() if axis == 0 else low.y())
                end = min(view.session.source.size[axis], high.x() if axis == 0 else high.y())
                origin, step = frame.origin[axis], frame.cell[axis]
                zoom = abs(view.transform().m11() if axis == 0 else view.transform().m22())
                for position in grid_positions(start - origin, end - origin, step, zoom):
                    line(axis, origin + position)
            painter.restore()

        if self.settings["rulers"]:
            scale = self.scale()
            if self.settings["grid"] and scale is not None:
                painter.save()
                image = view.viewportTransform().mapRect(view.image_rect).toAlignedRect()
                painter.setClipRect(image.intersected(viewport))
                painter.setPen(pen("#38ffffff"))
                low, high = (
                    view.mapToScene(viewport.topLeft()),
                    view.mapToScene(viewport.bottomRight()),
                )
                for axis in (0, 1):
                    start = max(0, low.x() if axis == 0 else low.y())
                    end = min(view.session.source.size[axis], high.x() if axis == 0 else high.y())
                    step = scale.position(self.settings["step"], axis)
                    zoom = abs(view.transform().m11() if axis == 0 else view.transform().m22())
                    for position in grid_positions(start, end, step, zoom):
                        line(axis, position)
                painter.restore()
            painter.setPen(pen("#a073baff", True))
            for i, guide in enumerate(self.settings["guides"]):
                if self.pending is None or self.pending["index"] != i:
                    painter.setPen(pen("#eea0d8ff" if i == self.hover_guide else "#a073baff", True))
                    line(0 if guide["axis"] == "x" else 1, guide["position"])
            if self.pending is not None:
                painter.setPen(pen("#d0a0d8ff", True))
                line(self.pending["axis"], self.pending["position"])
            guide = self.pending
            if guide is None and self.hover_guide is not None:
                stored = self.settings["guides"][self.hover_guide]
                guide = {"axis": 0 if stored["axis"] == "x" else 1, "position": stored["position"]}
            if guide is not None and scale is not None:
                axis, position = guide["axis"], guide["position"]
                value = scale.value(position, axis)
                if self.pending is not None and self.settings["snap"]:
                    value = round(value)
                text = f"{'X' if axis == 0 else 'Y'}: {value:.8g} {self.corner.text()}"
                metrics = painter.fontMetrics()
                width, height = metrics.horizontalAdvance(text) + 12, metrics.height() + 6
                p = view.viewportTransform().map(
                    QPointF(position, 0) if axis == 0 else QPointF(0, position)
                )
                x = min(max(4, p.x() + 8 if axis == 0 else 8), viewport.width() - width - 4)
                y = min(max(4, p.y() + 8 if axis == 1 else 8), viewport.height() - height - 4)
                label = QRectF(x, y, width, height)
                painter.fillRect(label, QColor("#dd202020"))
                painter.setPen(QColor("#ffffff"))
                painter.drawText(label, Qt.AlignmentFlag.AlignCenter, text)
        if self.settings["crosshair"] and self.cursor is not None:
            painter.setPen(pen("#70ffffff", True))
            painter.drawLine(self.cursor.x(), 0, self.cursor.x(), viewport.height())
            painter.drawLine(0, self.cursor.y(), viewport.width(), self.cursor.y())
        painter.restore()
