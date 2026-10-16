"""Map canvas input, navigation, and editing overlays in native image coordinates."""

from __future__ import annotations

import math
from itertools import pairwise

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from dale.geometry import nearest_source
from dale.raster import render_preview
from dale.session import Closure, Stroke


def pixmap(image: Image.Image) -> QPixmap:
    rgba = image.convert("RGBA")
    return QPixmap.fromImage(
        QImage(
            rgba.tobytes(), rgba.width, rgba.height, rgba.width * 4, QImage.Format.Format_RGBA8888
        ).copy()
    )


def line_path(segments):
    path = QPainterPath()
    for a, b in segments:
        path.moveTo(*a)
        path.lineTo(*b)
    return path


class MapView(QGraphicsView):
    changed = Signal()
    message = Signal(str)

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setMouseTracking(True)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        checker = QPixmap(32, 32)
        checker.fill(QColor("#29313b"))
        painter = QPainter(checker)
        painter.fillRect(0, 0, 16, 16, QColor("#38424e"))
        painter.fillRect(16, 16, 16, 16, QColor("#38424e"))
        painter.end()
        self.setBackgroundBrush(QBrush(checker))
        self.session = None
        self.preview = None
        self.item = None
        self.image_rect = QRectF()
        self.mode = "Pan"
        self.show_walls = True
        self.diameter = 40
        self.pending = []
        self.stroke = []
        self.cursor_point = None
        self.snap = None
        self.panning = False
        self.pan_button = None
        self.last_pan = None
        self.geometry_key = None
        self.analysis = None
        self.walls = ()
        self.original_path = QPainterPath()
        self.warning_path = QPainterPath()
        self.render_timer = QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.setInterval(35)
        self.render_timer.timeout.connect(self.update_image)

    def assign(self, session, preview):
        self.cancel_pending()
        self.session, self.preview = session, preview
        self.scene().clear()
        self.item = self.scene().addPixmap(pixmap(preview))
        self.item.setTransform(
            QTransform.fromScale(
                session.source.size[0] / preview.width, session.source.size[1] / preview.height
            )
        )
        self.image_rect = QRectF(0, 0, *session.source.size)
        # Navigation space must extend beyond the image, including at fit zoom.
        margin_x = max(session.source.size[0] * 4, 4096)
        margin_y = max(session.source.size[1] * 4, 4096)
        self.scene().setSceneRect(
            self.image_rect.adjusted(-margin_x, -margin_y, margin_x, margin_y)
        )
        self.walls = session.walls
        self.original_path = line_path(self.walls)
        self.geometry_key = None
        self.refresh()
        self.fit_map()

    def fit_map(self):
        if self.session:
            self.fitInView(self.image_rect, Qt.AspectRatioMode.KeepAspectRatio)

    def refresh(self):
        if not self.session:
            return
        key = self.session.closures
        if key != self.geometry_key:
            self.analysis = self.session.analysis()
            self.warning_path = line_path(self.analysis.unresolved)
            self.geometry_key = key
        self.update_image()

    def update_image(self):
        if not self.session:
            return
        operations = self.session.operations
        if self.stroke:
            operations = operations + [
                Stroke(tuple(self.stroke), self.diameter / 2, self.mode == "Restore")
            ]
        self.item.setPixmap(
            pixmap(render_preview(self.preview, self.session.source.size, operations))
        )
        self.viewport().update()

    def set_mode(self, mode):
        self.cancel_pending()
        self.mode = mode
        self.setCursor(
            Qt.CursorShape.OpenHandCursor if mode == "Pan" else Qt.CursorShape.CrossCursor
        )
        self.viewport().update()

    def cancel_pending(self):
        self.render_timer.stop()
        self.pending, self.stroke, self.snap = [], [], None
        self.viewport().update()

    def _point(self, event):
        p = self.mapToScene(event.position().toPoint())
        return p.x(), p.y()

    def _inside(self, point):
        return self.image_rect.contains(QPointF(*point))

    def _snapped(self, point):
        return nearest_source(point, self.walls, 14 / max(self.transform().m11(), 1e-9))

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton or (
            event.button() == Qt.MouseButton.LeftButton and self.mode == "Pan"
        ):
            self.panning = True
            self.pan_button = event.button()
            self.last_pan = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if not self.session or event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        point = self._point(event)
        if not self._inside(point):
            return
        if self.mode == "Closure":
            free = event.modifiers() & (
                Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
            )
            if self.pending and free:
                self.pending.append(point)
            else:
                snap = self._snapped(point)
                if snap is None:
                    self.message.emit("Click within 14 screen pixels of an original cyan wall.")
                    return
                if not self.pending:
                    self.pending = [snap]
                elif math.dist(self.pending[-1], snap) > 1e-6:
                    self.session.add(Closure(tuple(self.pending + [snap])))
                    self.pending = []
                    self.changed.emit()
            self.viewport().update()
        elif self.mode in ("Erase", "Restore"):
            self.stroke = [point]
            self.update_image()
        event.accept()

    def mouseMoveEvent(self, event):
        if self.panning:
            delta = event.position() - self.last_pan
            self.last_pan = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - round(delta.x())
            )
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - round(delta.y()))
            event.accept()
            return
        point = self._point(event)
        self.cursor_point = point
        self.snap = self._snapped(point) if self.mode == "Closure" and self.session else None
        if self.stroke and event.buttons() & Qt.MouseButton.LeftButton:
            if math.dist(self.stroke[-1], point) >= max(0.5, self.diameter / 10):
                self.stroke.append(point)
                if not self.render_timer.isActive():
                    self.render_timer.start()
        self.viewport().update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.panning and event.button() == self.pan_button:
            self.panning = False
            self.pan_button = None
            self.setCursor(
                Qt.CursorShape.OpenHandCursor if self.mode == "Pan" else Qt.CursorShape.CrossCursor
            )
            event.accept()
            return
        if self.stroke and event.button() == Qt.MouseButton.LeftButton:
            self.stroke.append(self._point(event))
            self.session.add(Stroke(tuple(self.stroke), self.diameter / 2, self.mode == "Restore"))
            self.stroke = []
            self.render_timer.stop()
            self.changed.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if not self.session:
            return
        before = self.mapToScene(event.position().toPoint())
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        if 0.005 <= self.transform().m11() * factor <= 16:
            self.scale(factor, factor)
            after = self.mapToScene(event.position().toPoint())
            delta = after - before
            self.translate(delta.x(), delta.y())
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_pending()
            self.update_image()
            event.accept()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        event.accept()

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        if not self.session:
            return

        def pen(color, width=1.5, dashed=False):
            result = QPen(QColor(color), width)
            result.setCosmetic(True)
            if dashed:
                result.setStyle(Qt.PenStyle.DashLine)
            return result

        if self.show_walls:
            painter.setPen(pen("#58d9ec"))
            painter.drawPath(self.original_path)
            painter.setPen(pen("#ff9d54", 2, True))
            painter.drawPath(self.warning_path)
            painter.setPen(pen("#ffe071", 2, True))
            for points in self.session.closures:
                painter.drawPath(line_path(pairwise(points)))
        if self.pending:
            painter.setPen(pen("#ffe071", 2, True))
            points = self.pending + ([self.snap or self.cursor_point] if self.cursor_point else [])
            painter.drawPath(line_path(pairwise(points)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self.snap:
            radius = 5 / self.transform().m11()
            painter.setPen(pen("#ffffff", 2))
            painter.drawEllipse(QPointF(*self.snap), radius, radius)
        if self.cursor_point and self.mode in ("Erase", "Restore"):
            painter.setPen(pen("#ffffff"))
            painter.drawEllipse(QPointF(*self.cursor_point), self.diameter / 2, self.diameter / 2)
