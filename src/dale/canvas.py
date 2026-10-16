"""Map canvas input, navigation, and editing overlays in native image coordinates."""

from __future__ import annotations

import math
from itertools import pairwise

from PIL import Image
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView
from shapely.geometry import GeometryCollection, LineString
from shapely.ops import unary_union

from dale.autoclose import AutoCloseIndex, AutoClosePlan
from dale.editing import (
    add_line,
    delete_vertex,
    erase_geometry,
    geometry_targets,
    hit_edge,
    hit_vertex,
    insert_vertex,
    move_vertex,
    project,
    snap_point,
    vertices,
)
from dale.geometry import analyze_regions, offset_region
from dale.raster import render_preview
from dale.region_transform import plan_region_transform
from dale.session import Stroke

HANDLE_DIAMETER = 10
GEOMETRY_TOOLS = ("Edit points", "New line", "Auto-close", "Erase lines", "Erase vertices")
GEOMETRY_ERASERS = ("Erase lines", "Erase vertices")
REGION_TOOLS = ("Select regions", "Move regions", "Rotate regions")


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
    auto_close_requested = Signal(object)
    region_clicked = Signal(object)
    regions_transformed = Signal(object)

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
        self.raster_diameters = {"Erase": 40, "Restore": 40}
        self.geometry_diameters = {mode: 24 for mode in GEOMETRY_ERASERS}
        self.snap_distance = 14
        self.snap_enabled = True
        self.auto_close_distance = 14
        self.auto_close_index = None
        self.auto_close_key = None
        self.auto_close_plan = AutoClosePlan()
        self.auto_close_review = False
        self.hover_path = QPainterPath()
        self.hover_warning_path = QPainterPath()
        self.highlighted_edges = ()
        self.warning_geometry = GeometryCollection()
        self.hover_edge = None
        self.eraser_vertices = ()
        self.auto_join_path = QPainterPath()
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
        self.drag_axis = None
        self.axis_constrained = False
        self.line_start = None
        self.line_end = None
        self.region_polygons = ()
        self.region_pivot = None
        self.move_related = False
        self.region_drag_start = None
        self.region_plan = None
        self.region_original_path = None
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
            self.update_hover()

    def clear_map(self):
        self.cancel_pending()
        self.scene().clear()
        self.session = self.preview = self.item = self.working_geometry = self.analysis = None
        self.geometry_key = None
        self.auto_close_index = self.auto_close_key = None
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
            self.warning_geometry = unary_union(
                [LineString(edge) for edge in self.analysis.unresolved]
            )
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
            self.update_hover()
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
            Qt.CursorShape.OpenHandCursor
            if mode in ("Pan", "Move regions")
            else Qt.CursorShape.PointingHandCursor
            if mode == "Select regions"
            else Qt.CursorShape.CrossCursor
        )
        self.update_hover()
        self.viewport().update()

    def cancel_pending(self):
        self.render_timer.stop()
        self.stroke, self.snap = [], None
        self.auto_close_plan = AutoClosePlan()
        self.hover_path = QPainterPath()
        self.hover_warning_path = QPainterPath()
        self.highlighted_edges = ()
        self.auto_join_path = QPainterPath()
        was_editing = self.edit_preview is not None
        self.edit_preview = self.drag_base = self.drag_original = self.drag_vertex = None
        self.drag_offset = None
        self.drag_axis = None
        self.axis_constrained = False
        if self.region_original_path is not None:
            self.selected_path = self.region_original_path
        self.region_drag_start = self.region_plan = self.region_original_path = None
        self.line_start = self.line_end = self.geometry_stroke = None
        if was_editing:
            self.refresh(render_image=False)
        self.viewport().update()

    def _point(self, event):
        p = self.mapToScene(event.position().toPoint())
        return p.x(), p.y()

    def _inside(self, point):
        return self.image_rect.contains(QPointF(*point))

    def update_hover(self):
        self.auto_close_plan = AutoClosePlan()
        self.eraser_vertices = ()
        edges = ()
        if self.session and self.cursor_point:
            geometry = self.edit_preview or self.session.geometry()
            if self.mode == "Auto-close":
                tolerance = self.auto_close_distance / max(self.transform().m11(), 1e-9)
                key = geometry, tolerance
                if self.auto_close_key != key:
                    self.auto_close_index = AutoCloseIndex(geometry, tolerance)
                    self.auto_close_key = key
                self.auto_close_plan = self.auto_close_index.at(self.cursor_point)
                edges = self.auto_close_plan.segments
            elif self.mode in GEOMETRY_ERASERS:
                targets = geometry_targets(
                    geometry,
                    self.cursor_point,
                    self.cursor_point,
                    self.geometry_diameter / 2 / max(self.transform().m11(), 1e-9),
                    "lines" if self.mode == "Erase lines" else "vertices",
                )
                if self.mode == "Erase lines":
                    edges = targets
                else:
                    self.eraser_vertices = targets
                    erased = erase_geometry(
                        geometry,
                        self.cursor_point,
                        self.cursor_point,
                        self.geometry_diameter / 2 / max(self.transform().m11(), 1e-9),
                        "vertices",
                    )
                    remaining = {
                        tuple(sorted(edge))
                        for edge in (
                            *erased.walls,
                            *(edge for path in erased.closures for edge in pairwise(path)),
                        )
                    }
                    edges = tuple(
                        edge
                        for edge in (
                            *geometry.walls,
                            *(edge for path in geometry.closures for edge in pairwise(path)),
                        )
                        if tuple(sorted(edge)) not in remaining
                    )
            elif self.mode in ("Edit points", "New line"):
                point = self.snap or self.cursor_point
                vertex = hit_vertex(geometry, point, self._handle_tolerance())
                all_edges = (
                    *geometry.walls,
                    *(edge for path in geometry.closures for edge in pairwise(path)),
                )
                hit = hit_edge(geometry, point, self._handle_tolerance())
                if hit and (
                    vertex is None
                    or self.hover_edge is None
                    or math.dist(project(vertex, self.hover_edge)[0], vertex) > 1e-7
                ):
                    self.hover_edge = (
                        geometry.walls[hit.path_index]
                        if hit.kind == "wall"
                        else tuple(
                            geometry.closures[hit.path_index][hit.edge_index : hit.edge_index + 2]
                        )
                    )
                if vertex is not None:
                    edges = tuple(
                        edge
                        for edge in all_edges
                        if math.dist(project(vertex, edge)[0], vertex) <= 1e-7
                    )
                else:
                    hit = hit_edge(geometry, point, self._handle_tolerance() * 0.7)
                    if hit:
                        edges = (
                            geometry.walls[hit.path_index]
                            if hit.kind == "wall"
                            else geometry.closures[hit.path_index][
                                hit.edge_index : hit.edge_index + 2
                            ],
                        )
        self.highlight_edges(edges, self.auto_close_plan.extensions)
        self.viewport().update()

    def highlight_edges(self, edges, extensions=()):
        edges = self.highlighted_edges = tuple(edges)
        self.hover_path = line_path(edges)
        active = unary_union([LineString(edge) for edge in edges])
        unresolved = active.intersection(self.warning_geometry)
        self.hover_warning_path = QPainterPath()

        def append(shape):
            if shape.geom_type == "LineString":
                self.hover_warning_path.addPath(line_path(pairwise(shape.coords)))
            elif hasattr(shape, "geoms"):
                for part in shape.geoms:
                    append(part)

        append(unresolved)
        self.auto_join_path = line_path(extensions)

    def _snap_tolerance(self):
        return self.snap_distance / max(self.transform().m11(), 1e-9) if self.snap_enabled else 0

    @property
    def active_gesture(self):
        return (
            bool(self.stroke)
            or self.drag_base is not None
            or self.line_start is not None
            or self.region_drag_start is not None
        )

    @property
    def diameter(self):
        return self.raster_diameters[self.mode if self.mode in ("Erase", "Restore") else "Erase"]

    @diameter.setter
    def diameter(self, value):
        self.raster_diameters[self.mode if self.mode in ("Erase", "Restore") else "Erase"] = value

    @property
    def geometry_diameter(self):
        mode = self.mode if self.mode in GEOMETRY_ERASERS else "Erase lines"
        return self.geometry_diameters[mode]

    @geometry_diameter.setter
    def geometry_diameter(self, value):
        mode = self.mode if self.mode in GEOMETRY_ERASERS else "Erase lines"
        self.geometry_diameters[mode] = value

    def resize_tool(self, steps):
        if self.mode == "Move regions":
            self.transform_regions(scale=1.05**steps)
            return
        if self.mode == "Auto-close":
            self.auto_close_distance = max(1, min(256, self.auto_close_distance + round(steps)))
            self.size_changed.emit()
            self.update_hover()
            return
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
        self.update_hover()
        self.viewport().update()

    def _region_plan(self):
        analysis = self.session.analysis()
        return plan_region_transform(
            self.session.geometry(),
            self.region_polygons,
            analysis.cells,
            self.move_related,
            self.snap_distance / max(self.transform().m11(), 1e-9),
            analysis.joins,
            self.region_pivot,
        )

    def transform_regions(self, scale=1.0, angle=0.0):
        if not self.session or not self.region_polygons or self.active_gesture:
            return
        plan = self._region_plan()
        geometry, polygons = plan.apply(scale=scale, angle=angle)
        if geometry != plan.original:
            self.session.add(geometry)
            self.changed.emit()
            self.regions_transformed.emit({"polygons": polygons, "pivot": plan.pivot})

    def _preview_region_move(self, point):
        dx, dy = point[0] - self.region_drag_start[0], point[1] - self.region_drag_start[1]
        self.edit_preview, _ = self.region_plan.apply(dx=dx, dy=dy)
        self.selected_path = QTransform.fromTranslate(dx, dy).map(self.region_original_path)
        self.refresh(render_image=False)

    def _drag_destination(self, point, modifiers=Qt.KeyboardModifier.NoModifier):
        destination = (point[0] + self.drag_offset[0], point[1] + self.drag_offset[1])
        self.axis_constrained = (
            bool(modifiers & Qt.KeyboardModifier.AltModifier) and self.drag_axis is not None
        )
        if self.axis_constrained:
            distance = sum(
                (value - origin) * axis
                for value, origin, axis in zip(
                    destination, self.drag_vertex, self.drag_axis, strict=True
                )
            )
            destination = tuple(
                origin + distance * axis
                for origin, axis in zip(self.drag_vertex, self.drag_axis, strict=True)
            )
        if math.dist(destination, self.drag_vertex) > 0.5 / self.transform().m11():
            self.snap = snap_point(
                self.drag_base, destination, self._snap_tolerance(), exclude=self.drag_vertex
            )
            if self.snap and self.axis_constrained:
                delta = self.snap[0] - self.drag_vertex[0], self.snap[1] - self.drag_vertex[1]
                if abs(delta[0] * self.drag_axis[1] - delta[1] * self.drag_axis[0]) > 1e-7:
                    self.snap = None
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
        edge = hit_edge(geometry, point, self._handle_tolerance())
        if edge:
            segment = (
                geometry.walls[edge.path_index]
                if edge.kind == "wall"
                else geometry.closures[edge.path_index][edge.edge_index : edge.edge_index + 2]
            )
            if self.hover_edge and math.dist(project(vertex, self.hover_edge)[0], vertex) <= 1e-7:
                segment = self.hover_edge
            a, b = segment
            length = math.dist(a, b)
            self.drag_axis = ((b[0] - a[0]) / length, (b[1] - a[1]) / length) if length else None
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
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.cursor_point = point
        if self.mode == "Move regions":
            if self.selected_path.contains(QPointF(*point)) and self.region_polygons:
                self.region_drag_start = point
                self.region_plan = self._region_plan()
                self.region_original_path = QPainterPath(self.selected_path)
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if self.mode == "Select regions":
            self.region_clicked.emit(point)
            event.accept()
            return
        if self.mode == "Auto-close":
            self.update_hover()
            self.auto_close_review = True
            try:
                self.auto_close_requested.emit(self.auto_close_plan)
            finally:
                self.auto_close_review = False
            event.accept()
            return
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
        if self.mode in ("Erase", "Restore"):
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
            self.cursor_point = self._point(event)
            self.update_hover()
            event.accept()
            return
        point = self._point(event)
        self.cursor_point = point
        if self.mode == "Move regions" and self.region_drag_start is not None:
            self._preview_region_move(point)
            event.accept()
            return
        if self.mode == "Auto-close" and self.session:
            self.update_hover()
            event.accept()
            return
        if self.mode in GEOMETRY_ERASERS and self.session:
            if self.drag_base is not None and event.buttons() & Qt.MouseButton.LeftButton:
                self._erase_geometry(point)
            self.update_hover()
            event.accept()
            return
        if self.mode == "New line" and self.session:
            self.snap = snap_point(self.session.geometry(), point, self._snap_tolerance())
            if self.line_start is not None:
                self.line_end = self._line_anchor(point)
            self.update_hover()
            self.viewport().update()
            event.accept()
            return
        if self.mode == "Edit points" and self.session:
            if self.drag_base is not None and event.buttons() & Qt.MouseButton.LeftButton:
                destination = self._drag_destination(point, event.modifiers())
                self.edit_preview = move_vertex(self.drag_base, self.drag_vertex, destination)
                self.refresh(render_image=False)
            else:
                vertex = hit_vertex(self.session.geometry(), point, self._handle_tolerance())
                self.setCursor(
                    Qt.CursorShape.PointingHandCursor
                    if vertex is not None
                    else Qt.CursorShape.CrossCursor
                )
                self.update_hover()
                self.viewport().update()
            event.accept()
            return
        self.snap = None
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
                Qt.CursorShape.OpenHandCursor
                if self.mode in ("Pan", "Move regions")
                else Qt.CursorShape.CrossCursor
            )
            self.cursor_point = self._point(event)
            self.update_hover()
            event.accept()
            return
        if self.region_drag_start is not None and event.button() == Qt.MouseButton.LeftButton:
            point = self._point(event)
            dx, dy = point[0] - self.region_drag_start[0], point[1] - self.region_drag_start[1]
            plan = self.region_plan
            geometry, polygons = plan.apply(dx=dx, dy=dy)
            self.region_drag_start = self.region_plan = self.region_original_path = None
            self.edit_preview = None
            if geometry != plan.original:
                self.session.add(geometry)
                self.changed.emit()
                self.regions_transformed.emit(
                    {"polygons": polygons, "pivot": (plan.pivot[0] + dx, plan.pivot[1] + dy)}
                )
            self.refresh(render_image=False)
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        if self.drag_base is not None and event.button() == Qt.MouseButton.LeftButton:
            point = self._point(event)
            if self.mode in GEOMETRY_ERASERS:
                self._erase_geometry(point)
                geometry = self.edit_preview
            else:
                destination = self._drag_destination(point, event.modifiers())
                geometry = move_vertex(self.drag_base, self.drag_vertex, destination)
            original = self.drag_original
            self.edit_preview = self.drag_base = self.drag_original = self.drag_vertex = None
            self.drag_offset = None
            self.drag_axis = None
            self.axis_constrained = False
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
        if (
            self.mode == "Rotate regions"
            and not event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            steps = event.angleDelta().y() / 120
            if steps:
                self.transform_regions(angle=(round(steps) or (1 if steps > 0 else -1)) / 10)
            event.accept()
            return
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
            self.cursor_point = self._point(event)
            self.update_hover()
        event.accept()

    def leaveEvent(self, event):
        if not self.active_gesture and not self.panning and not self.auto_close_review:
            self.cursor_point = None
            self.update_hover()
        super().leaveEvent(event)

    def keyPressEvent(self, event):
        if (
            event.key() == Qt.Key.Key_Alt
            and self.mode == "Edit points"
            and self.drag_base is not None
        ):
            self._update_axis_drag(Qt.KeyboardModifier.AltModifier)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_pending()
            self.update_image()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if (
            event.key() == Qt.Key.Key_Alt
            and self.mode == "Edit points"
            and self.drag_base is not None
        ):
            self._update_axis_drag(Qt.KeyboardModifier.NoModifier)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def _update_axis_drag(self, modifiers):
        if self.cursor_point is not None:
            destination = self._drag_destination(self.cursor_point, modifiers)
            self.edit_preview = move_vertex(self.drag_base, self.drag_vertex, destination)
            self.refresh(render_image=False)

    def contextMenuEvent(self, event):
        event.accept()

    def viewportEvent(self, event):
        if event.type() == QEvent.Type.ToolTip:
            event.accept()
            return True
        return super().viewportEvent(event)

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

        def outlined(draw, color, dashed=False, backing="#000000"):
            painter.save()
            # Keep crisp device-pixel edges and an exact-color central pixel.
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            painter.setPen(pen(backing, 3, dashed))
            draw()
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(pen(color, 1, dashed))
            draw()
            painter.restore()

        def path(shape, color, dashed=False):
            outlined(lambda: painter.drawPath(shape), color, dashed)

        def circle(point, radius, color, backing="#000000"):
            outlined(
                lambda: painter.drawEllipse(QPointF(*point), radius, radius), color, backing=backing
            )

        if self.show_walls or self.mode in REGION_TOOLS:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(88, 217, 236, 64))
            painter.drawPath(self.selected_path)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            path(self.selected_path, "#58d9ec")
        if self.show_walls:
            path(self.original_path, "#58d9ec")
            path(self.warning_path, "#ff0000")
            path(self.offset_path, "#58d9ec", True)
        if not self.hover_path.isEmpty():
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            painter.setPen(pen("#ffffff", 3))
            painter.drawPath(self.hover_path)
            painter.setPen(pen("#58d9ec", 1))
            painter.drawPath(self.hover_path)
            painter.setPen(pen("#ff0000", 1))
            painter.drawPath(self.hover_warning_path)
            painter.restore()
        outlined(lambda: painter.drawPath(self.auto_join_path), "#ff0000", True, "#ffffff")
        if self.cursor_point and self.mode == "Auto-close":
            circle(self.cursor_point, self.auto_close_distance / self.transform().m11(), "#ffffff")
        if self.line_start is not None:
            path(line_path(((self.line_start, self.line_end),)), "#ff0000")
            painter.setBrush(QColor("#effbff"))
            radius = HANDLE_DIAMETER / 2 / self.transform().m11()
            for point in (self.line_start, self.line_end):
                circle(point, radius, "#ff0000")
        if self.axis_constrained and self.drag_vertex is not None:
            reach = max(self.session.source.size)
            a = tuple(p - reach * v for p, v in zip(self.drag_vertex, self.drag_axis, strict=True))
            b = tuple(p + reach * v for p, v in zip(self.drag_vertex, self.drag_axis, strict=True))
            path(line_path(((a, b),)), "#58d9ec", True)
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
            active_points = {
                *self.eraser_vertices,
                *(p for edge in self.highlighted_edges for p in edge),
            }
            for vertex in vertices(self.working_geometry):
                if not self.show_walls and vertex not in active_points:
                    continue
                targeted = vertex in self.eraser_vertices
                painter.setBrush(QColor("#ffffff" if targeted else "#effbff"))
                circle(vertex, radius, "#183244", "#ffffff" if targeted else "#000000")
