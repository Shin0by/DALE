"""Map canvas input, navigation, and editing overlays in native image coordinates."""

from __future__ import annotations

import math
from itertools import pairwise

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from dale.editing import (
    add_line,
    delete_vertex,
    erase_geometry,
    hit_edge,
    hit_vertex,
    insert_vertex,
    move_vertex,
    snap_point,
    vertices,
)
from dale.geometry import analyze_regions, offset_region
from dale.raster import render_preview
from dale.session import Closure, GeometryEdit, Stroke

HANDLE_DIAMETER = 10
GEOMETRY_TOOLS = ("Edit points", "New line", "Closure", "Erase lines", "Erase vertices")
GEOMETRY_ERASERS = ("Erase lines", "Erase vertices")


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
    size_changed = Signal()

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setMouseTracking(True)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        checker = QPixmap(32, 32)
        checker.fill(QColor("#303030"))
        painter = QPainter(checker)
        painter.fillRect(0, 0, 16, 16, QColor("#3b3b3b"))
        painter.fillRect(16, 16, 16, 16, QColor("#3b3b3b"))
        painter.end()
        self.setBackgroundBrush(QBrush(checker))
        self.session = None
        self.preview = None
        self.item = None
        self.image_rect = QRectF()
        self.mode = "Pan"
        self.show_walls = True
        self.diameter = 40
        self.geometry_diameter = 24
        self.snap_distance = 14
        self.snap_enabled = True
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
        self.join_path = QPainterPath()
        self.offset_path = QPainterPath()
        self.selected_path = QPainterPath()
        self.working_geometry = None
        self.edit_preview = None
        self.drag_base = None
        self.drag_original = None
        self.drag_vertex = None
        self.drag_offset = None
        self.line_start = None
        self.line_end = None
        self.geometry_stroke = None
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

    def clear_map(self):
        self.cancel_pending()
        self.scene().clear()
        self.session = self.preview = self.item = self.working_geometry = self.analysis = None
        self.geometry_key = None
        self.walls = ()
        self.image_rect = QRectF()
        self.selected_path = QPainterPath()
        self.viewport().update()

    def _line_anchor(self, point):
        geometry = self.session.geometry()
        candidate = snap_point(geometry, point, self._snap_tolerance()) or point
        # Reuse nearby handles rather than creating crowded duplicate vertices.
        return hit_vertex(geometry, candidate, self._handle_tolerance()) or candidate

    def refresh(self, render_image=True):
        if not self.session:
            return
        geometry = self.edit_preview or self.session.geometry()
        key = geometry, self.session.gap_tolerance, self.session.contour_offset
        if key != self.geometry_key:
            self.working_geometry = geometry
            self.walls = geometry.walls
            self.analysis = analyze_regions(
                geometry.walls, geometry.closures, self.session.gap_tolerance
            )
            self.original_path = line_path(
                (
                    *self.walls,
                    *self.analysis.joins,
                    *(edge for path in geometry.closures for edge in pairwise(path)),
                )
            )
            self.warning_path = line_path(self.analysis.unresolved)
            self.join_path = line_path(self.analysis.joins)
            self.offset_path = QPainterPath()
            if self.session.contour_offset and self.analysis.faces:
                try:
                    area = offset_region(self.analysis.area, self.session.contour_offset)
                    polygons = [area] if area.geom_type == "Polygon" else area.geoms
                    for polygon in polygons:
                        for ring in (polygon.exterior, *polygon.interiors):
                            self.offset_path.addPath(line_path(pairwise(ring.coords)))
                except ValueError:
                    pass  # The mask action reports an offset that erases all enclosed areas.
            self.geometry_key = key
        if render_image:
            self.update_image()
        else:
            self.viewport().update()

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
        was_editing = self.edit_preview is not None
        self.edit_preview = self.drag_base = self.drag_original = self.drag_vertex = None
        self.drag_offset = None
        self.line_start = self.line_end = self.geometry_stroke = None
        if was_editing:
            self.refresh(render_image=False)
        self.viewport().update()

    def _point(self, event):
        p = self.mapToScene(event.position().toPoint())
        return p.x(), p.y()

    def _inside(self, point):
        return self.image_rect.contains(QPointF(*point))

    def _snapped(self, point):
        return snap_point(GeometryEdit(self.walls), point, self._snap_tolerance())

    def _snap_tolerance(self):
        return self.snap_distance / max(self.transform().m11(), 1e-9) if self.snap_enabled else 0

    @property
    def active_gesture(self):
        return bool(self.stroke) or self.drag_base is not None or self.line_start is not None

    def resize_tool(self, steps):
        attribute = "geometry_diameter" if self.mode in GEOMETRY_ERASERS else "diameter"
        if self.mode not in (*GEOMETRY_ERASERS, "Erase", "Restore"):
            return
        old = getattr(self, attribute)
        limit = 512 if attribute == "geometry_diameter" else 4096
        value = round(old * 1.15**steps)
        if value == old:
            value += 1 if steps > 0 else -1
        setattr(self, attribute, max(1, min(limit, value)))
        self.size_changed.emit()
        self.viewport().update()

    def _drag_destination(self, point):
        destination = (point[0] + self.drag_offset[0], point[1] + self.drag_offset[1])
        if math.dist(destination, self.drag_vertex) > 0.5 / self.transform().m11():
            self.snap = snap_point(
                self.drag_base, destination, self._snap_tolerance(), exclude=self.drag_vertex
            )
            return self.snap or destination
        self.snap = None
        return destination

    def _erase_geometry(self, point):
        start = self.geometry_stroke or point
        self.edit_preview = erase_geometry(
            self.edit_preview,
            start,
            point,
            self.geometry_diameter / 2 / self.transform().m11(),
            "lines" if self.mode == "Erase lines" else "vertices",
        )
        self.geometry_stroke = point
        self.refresh(render_image=False)

    def _handle_tolerance(self):
        return HANDLE_DIAMETER / max(self.transform().m11(), 1e-9)

    def _begin_point_edit(self, point):
        original = self.session.geometry()
        geometry = original
        vertex = hit_vertex(geometry, point, self._handle_tolerance())
        if vertex is None:
            hit = hit_edge(geometry, point, self._handle_tolerance() * 0.7)
            if hit is None:
                return
            vertex = hit_vertex(geometry, hit.point, self._handle_tolerance())
            if vertex is None:
                geometry = insert_vertex(geometry, hit)
                vertex = hit.point
        self.drag_base, self.drag_original = geometry, original
        self.drag_vertex = vertex
        self.drag_offset = (vertex[0] - point[0], vertex[1] - point[1])
        self.edit_preview = geometry
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.refresh(render_image=False)

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
        self.cursor_point = point
        if self.mode == "Edit points":
            self._begin_point_edit(point)
            event.accept()
            return
        if self.mode == "New line":
            self.snap = snap_point(self.session.geometry(), point, self._snap_tolerance())
            self.line_start = self.line_end = self._line_anchor(point)
            self.viewport().update()
            event.accept()
            return
        if self.mode in GEOMETRY_ERASERS:
            self.drag_original = self.drag_base = self.session.geometry()
            self.edit_preview = self.drag_base
            self._erase_geometry(point)
            event.accept()
            return
        if not self._inside(point):
            return
        if self.mode == "Closure":
            free = event.modifiers() & Qt.KeyboardModifier.AltModifier
            if self.pending and free:
                self.pending.append(point)
            else:
                snap = self._snapped(point)
                if snap is None:
                    self.message.emit("Click near a wall within the configured snap distance.")
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
        if self.mode in GEOMETRY_ERASERS and self.session:
            if self.drag_base is not None and event.buttons() & Qt.MouseButton.LeftButton:
                self._erase_geometry(point)
            self.viewport().update()
            event.accept()
            return
        if self.mode == "New line" and self.session:
            self.snap = snap_point(self.session.geometry(), point, self._snap_tolerance())
            if self.line_start is not None:
                self.line_end = self._line_anchor(point)
            self.viewport().update()
            event.accept()
            return
        if self.mode == "Edit points" and self.session:
            if self.drag_base is not None and event.buttons() & Qt.MouseButton.LeftButton:
                destination = self._drag_destination(point)
                self.edit_preview = move_vertex(self.drag_base, self.drag_vertex, destination)
                self.refresh(render_image=False)
            else:
                vertex = hit_vertex(self.session.geometry(), point, self._handle_tolerance())
                self.setCursor(
                    Qt.CursorShape.PointingHandCursor
                    if vertex is not None
                    else Qt.CursorShape.CrossCursor
                )
                self.viewport().update()
            event.accept()
            return
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
        if self.drag_base is not None and event.button() == Qt.MouseButton.LeftButton:
            point = self._point(event)
            if self.mode in GEOMETRY_ERASERS:
                self._erase_geometry(point)
                geometry = self.edit_preview
            else:
                destination = self._drag_destination(point)
                geometry = move_vertex(self.drag_base, self.drag_vertex, destination)
            original = self.drag_original
            self.edit_preview = self.drag_base = self.drag_original = self.drag_vertex = None
            self.drag_offset = None
            self.geometry_stroke = None
            if geometry != original:
                self.session.add(geometry)
                self.changed.emit()
            self.refresh(render_image=False)
            self.setCursor(
                Qt.CursorShape.PointingHandCursor
                if self.mode == "Edit points"
                else Qt.CursorShape.CrossCursor
            )
            event.accept()
            return
        if self.line_start is not None and event.button() == Qt.MouseButton.LeftButton:
            point = self._point(event)
            original = self.session.geometry()
            end = self._line_anchor(point)
            start = self.line_start
            self.line_start = self.line_end = None
            if math.dist(start, end) >= self._handle_tolerance():
                geometry = add_line(original, start, end)
                if geometry != original:
                    self.session.add(geometry)
                    self.changed.emit()
            self.refresh(render_image=False)
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

    def mouseDoubleClickEvent(self, event):
        if (
            self.mode == "Edit points"
            and self.session
            and event.button() == Qt.MouseButton.LeftButton
        ):
            point = self._point(event)
            self.cancel_pending()
            geometry = self.session.geometry()
            vertex = hit_vertex(geometry, point, self._handle_tolerance() * 0.65)
            if vertex is not None:
                edited = delete_vertex(geometry, vertex)
                if edited != geometry:
                    self.session.add(edited)
                    self.changed.emit()
                    self.refresh(render_image=False)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            steps = event.angleDelta().y() / 120
            if steps:
                self.resize_tool(steps)
            event.accept()
            return
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

        def pen(color, width, dashed=False):
            result = QPen(QColor(color), width)
            result.setCosmetic(True)
            if dashed:
                # Match dash lengths in device pixels across both stroke widths.
                result.setDashPattern([6 / width, 4 / width])
            return result

        def outlined(draw, color, dashed=False):
            painter.save()
            # Keep crisp device-pixel edges and an exact-color central pixel.
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            painter.setPen(pen("#000000", 3, dashed))
            draw()
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(pen(color, 1, dashed))
            draw()
            painter.restore()

        def path(shape, color, dashed=False):
            outlined(lambda: painter.drawPath(shape), color, dashed)

        def circle(point, radius, color):
            outlined(lambda: painter.drawEllipse(QPointF(*point), radius, radius), color)

        if self.show_walls or self.mode in GEOMETRY_TOOLS:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(88, 217, 236, 38))
            painter.drawPath(self.selected_path)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            path(self.original_path, "#58d9ec")
            path(self.warning_path, "#ff0000")
            path(self.offset_path, "#58d9ec", True)
        if self.pending:
            points = self.pending + ([self.snap or self.cursor_point] if self.cursor_point else [])
            path(line_path(pairwise(points)), "#ff0000", True)
        if self.line_start is not None:
            path(line_path(((self.line_start, self.line_end),)), "#ff0000")
            painter.setBrush(QColor("#effbff"))
            radius = HANDLE_DIAMETER / 2 / self.transform().m11()
            for point in (self.line_start, self.line_end):
                circle(point, radius, "#ff0000")
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self.snap:
            radius = 5 / self.transform().m11()
            circle(self.snap, radius, "#ffffff")
        if self.cursor_point and self.mode in ("Erase", "Restore"):
            circle(self.cursor_point, self.diameter / 2, "#ffffff")
        if self.cursor_point and self.mode in GEOMETRY_ERASERS:
            radius = self.geometry_diameter / 2 / self.transform().m11()
            painter.setBrush(QColor(255, 0, 0, 35))
            circle(self.cursor_point, radius, "#ff0000")
        if self.mode in ("Edit points", "New line", "Erase vertices") and self.working_geometry:
            radius = HANDLE_DIAMETER / 2 / self.transform().m11()
            painter.setBrush(QColor("#effbff"))
            for vertex in vertices(self.working_geometry):
                circle(vertex, radius, "#183244")
