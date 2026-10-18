"""Map canvas input, navigation, and editing overlays in native image coordinates."""

from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import replace
from itertools import pairwise
from time import monotonic

from PIL import Image
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QApplication, QGraphicsScene, QGraphicsView
from shapely import STRtree
from shapely.affinity import translate as translate_shape
from shapely.geometry import GeometryCollection, LineString, Point, box
from shapely.ops import unary_union

from dale.autoclose import AutoCloseIndex, AutoClosePlan
from dale.connections import components, cut_contacts, groups, isolate, join, point_contacts
from dale.editing import (
    LineEraser,
    add_circle,
    add_line,
    add_rectangle,
    align_orthogonal_point,
    alignment_points,
    circle_points,
    delete_vertex,
    erase_geometry,
    geometry_targets,
    hit_edge,
    hit_vertex,
    insert_vertex,
    move_vertex,
    project,
    rectangle_points,
    right_angle_point,
    snap_point,
    vertices,
)
from dale.geometry import RegionAnalysis, analyze_regions, contour_components, offset_region
from dale.layer_repair import LayerRepairIndex, flat_geometry, infer_layers, wall_intervals
from dale.provenance import geometry_edges
from dale.raster import raster_operations, render_preview
from dale.region_transform import (
    copy_figures,
    copy_regions,
    plan_figure_transform,
    plan_region_transform,
)
from dale.session import Stroke
from dale.source_editing import (
    add_source_wall,
    layer_geometry,
    move_source_vertex,
    replace_layer_geometry,
    source_layers,
)

HANDLE_DIAMETER = 10
GEOMETRY_TOOLS = (
    "Edit points",
    "New line",
    "New circle",
    "New rectangle",
    "Auto-close",
    "Erase lines",
    "Erase vertices",
)
GEOMETRY_ERASERS = ("Erase lines", "Erase vertices")
REGION_TOOLS = ("Select regions", "Move regions", "Rotate regions")
FIGURE_TOOLS = ("Select figures", "Move figures", "Rotate figures")
TRANSFORM_TOOLS = (*REGION_TOOLS, *FIGURE_TOOLS)
MOVE_TOOLS = ("Move regions", "Move figures")
ROTATE_TOOLS = ("Rotate regions", "Rotate figures")
SELECTION_TOOLS = ("Select regions", "Select figures", "Select raster regions")
AREA_TOOLS = (*TRANSFORM_TOOLS, "Select raster regions")
SELECTION_DRAG_PX = 10


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
    figure_clicked = Signal(object)
    region_box_selected = Signal(object)
    regions_transformed = Signal(object)
    clipboard_changed = Signal()
    paste_committed = Signal(object)

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
        self.right_angle_alignment = False
        self.contour_alignment = False
        self.right_angle_distance_px = 14
        self.contour_alignment_distance_px = 14
        self.auto_close_distance = 14
        self.auto_close_index = None
        self.auto_close_key = None
        self.auto_close_plan = AutoClosePlan()
        self.auto_close_review = False
        self.safe_json_repair = False
        self.property_documents = ()
        self.source_layer = "all"
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
        self.alignment_neighbours = self.alignment_anchors = self.alignment_guides = ()
        self.axis_constrained = False
        self.angle_joint = None
        self.line_start = None
        self.line_end = None
        self.rectangle_start = self.rectangle_end = None
        self.circle_center = None
        self.circle_radius = self.circle_adjustment = 0.0
        self.region_clipboard = None
        self.clipboard_source = None
        self.paste_delta = None
        self.placement_guides = ()
        self.region_anchor = self.region_grab_vertex = None
        self.region_polygons = ()
        self.figure_selection = False
        self.figure_line_ids = ()
        self.figure_pivot = None
        self.figure_click = None
        self.contour_line_ids = ()
        self.contour_selection_context = True
        self.selection_start = self.selection_screen = self.selection_rect = None
        self.detached_selection = None
        self.region_pivot = None
        self.move_related = False
        self.region_drag_start = None
        self.region_plan = None
        self.region_original_path = None
        self.geometry_stroke = None
        self.line_eraser_index = self.line_eraser_stroke = None
        self.line_eraser_hits = set()
        self.connection_prompt = None
        self.drag_connection_group = None
        self.drag_component_ids = ()
        self.rotation_last = None
        self.rotation_ids = ()
        self.render_timer = QTimer(self)
        self.render_timer.setSingleShot(True)
        self.render_timer.setInterval(35)
        self.render_timer.timeout.connect(self.update_image)

    def assign(self, session, preview):
        self.cancel_pending()
        self.line_eraser_index = None
        self.detached_selection = None
        self.region_polygons = ()
        self.figure_line_ids = ()
        self.figure_pivot = None
        self.contour_line_ids = ()
        self.source_layer = "all"
        self.session, self.preview = session, preview
        self.raster_key = None
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

    def center_map(self):
        if self.session:
            self.centerOn(self.image_rect.center())
            self.update_hover()

    def clear_map(self):
        self.cancel_pending()
        self.scene().clear()
        self.session = self.preview = self.item = self.working_geometry = self.analysis = None
        self.geometry_key = None
        self.raster_key = None
        self.auto_close_index = self.auto_close_key = None
        self.walls = ()
        self.source_layer = "all"
        self.image_rect = QRectF()
        self.selected_path = QPainterPath()
        self.viewport().update()

    def _line_anchor(self, point):
        geometry = self.editing_geometry()
        candidate = snap_point(geometry, point, self._snap_tolerance()) or point
        # Reuse nearby handles rather than creating crowded duplicate vertices.
        return hit_vertex(geometry, candidate, self._handle_tolerance()) or candidate

    def selected_source_layer(self, geometry=None):
        geometry = geometry or self.session.geometry()
        choices = source_layers(self.session.source, geometry, self.property_documents)
        return next(
            (layer for layer in choices if layer.key == self.source_layer),
            choices[0] if self.source_layer == "all" else replace(choices[0], indices=()),
        )

    def editing_geometry(self, geometry=None):
        geometry = geometry or self.edit_preview or self.session.geometry()
        return (
            layer_geometry(geometry, self.selected_source_layer(geometry).indices)
            if self.safe_json_repair
            else geometry
        )

    def selectable_regions(self):
        """Return standard polygonized extraction cells in the visible height scope."""
        return self.analysis.cells if self.session else ()

    def contour_figures(self):
        if not self.session:
            return ()
        geometry = self.editing_geometry()
        return contour_components(
            geometry_edges(geometry.walls, geometry.closures),
            tuple(record.id for record in geometry.lineage),
            groups(geometry),
        )

    def selected_figure_edges(self):
        if not self.session:
            return ()
        selected = set(self.figure_line_ids)
        geometry = self.editing_geometry()
        return tuple(
            edge
            for edge, record in zip(
                geometry_edges(geometry.walls, geometry.closures), geometry.lineage, strict=True
            )
            if record.id in selected
        )

    def figure_path(self):
        return line_path(self.selected_figure_edges())

    def _move_point(self, destination, report=False):
        if not self.safe_json_repair:
            return move_vertex(
                self.drag_base,
                self.drag_vertex,
                destination,
                connect=self.connection_prompt is None and not any(groups(self.drag_base)),
                connection_group=self.drag_connection_group,
            )
        try:
            return move_source_vertex(
                self.session.source,
                self.drag_base,
                self.drag_vertex,
                destination,
                self.selected_source_layer(self.drag_base).indices
                if self.safe_json_repair
                else range(len(self.drag_base.lineage)),
                documents=self.property_documents,
                group_filter=True,
                connection_group=self.drag_connection_group,
            )
        except ValueError as exc:
            if report:
                self.message.emit(str(exc))
            return self.drag_base

    def refresh(self, render_image=True):
        if not self.session:
            return
        geometry = self.edit_preview or self.session.geometry()
        key = (
            geometry,
            groups(geometry),
            self.session.gap_tolerance,
            self.session.contour_offset,
            self.safe_json_repair,
            self.source_layer,
        )
        if key != self.geometry_key:
            self.working_geometry = self.editing_geometry(geometry)
            self.walls = self.working_geometry.walls
            if self.safe_json_repair:
                analysis_geometry = flat_geometry(geometry)
                layers, ambiguous = infer_layers(
                    self.session.source, geometry, self.property_documents
                )
                active = set(self.selected_source_layer(geometry).indices)
                analyses = [
                    analyze_regions(
                        tuple(analysis_geometry.walls[i] for i in layer.indices if i in active)
                    )
                    for layer in layers
                ]
                if self.selected_source_layer(geometry).kind != "all":
                    analyses = [analyze_regions(self.walls)]
                self.analysis = RegionAnalysis(
                    unary_union([a.area for a in analyses]),
                    sum(a.faces for a in analyses),
                    tuple(
                        dict.fromkeys(
                            [edge for a in analyses for edge in a.unresolved]
                            + [analysis_geometry.walls[i] for i in ambiguous if i in active]
                        )
                    ),
                    cells=tuple({p.wkb: p for a in analyses for p in a.cells}.values()),
                )
            else:
                self.analysis = analyze_regions(
                    geometry.walls, geometry.closures, self.session.gap_tolerance
                )
            self.original_path = line_path(
                (
                    *self.walls,
                    *self.analysis.joins,
                    *(edge for path in self.working_geometry.closures for edge in pairwise(path)),
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
        operations = list(raster_operations(self.session.operations, self.session.contour_offset))
        if self.stroke:
            operations = operations + [
                Stroke(tuple(self.stroke), self.diameter / 2, self.mode == "Restore")
            ]
        key = self.session.source.size, tuple(operations)
        if key == self.raster_key:
            self.viewport().update()
            return
        self.item.setPixmap(
            pixmap(render_preview(self.preview, self.session.source.size, operations))
        )
        self.raster_key = key
        self.viewport().update()

    def repair_index(self, geometry, tolerance):
        return (
            LayerRepairIndex(
                self.session.source,
                geometry,
                tolerance,
                self.selected_source_layer(geometry).indices,
                documents=self.property_documents,
            )
            if self.safe_json_repair
            else AutoCloseIndex(geometry, tolerance)
        )

    def set_mode(self, mode):
        self.cancel_pending()
        self.mode = mode
        self.setCursor(
            Qt.CursorShape.OpenHandCursor
            if mode in ("Pan", *MOVE_TOOLS)
            else Qt.CursorShape.PointingHandCursor
            if mode in SELECTION_TOOLS
            else Qt.CursorShape.CrossCursor
        )
        self.update_hover()
        self.viewport().update()

    def cancel_pending(self):
        self.finish_rotation()
        self.figure_click = None
        selecting = self.selection_start is not None
        self.selection_start = self.selection_screen = self.selection_rect = None
        if selecting:
            self.region_box_selected.emit({"phase": "cancel"})
        self.render_timer.stop()
        self.paste_delta = None
        self.placement_guides = ()
        self.region_anchor = self.region_grab_vertex = None
        self.stroke, self.snap = [], None
        self.auto_close_plan = AutoClosePlan()
        self.hover_path = QPainterPath()
        self.hover_warning_path = QPainterPath()
        self.highlighted_edges = ()
        self.auto_join_path = QPainterPath()
        was_editing = self.edit_preview is not None
        self.edit_preview = self.drag_base = self.drag_original = self.drag_vertex = None
        self.drag_offset = None
        self.alignment_neighbours = self.alignment_anchors = self.alignment_guides = ()
        self.axis_constrained = False
        self.angle_joint = None
        if self.region_original_path is not None:
            self.selected_path = self.region_original_path
        self.region_drag_start = self.region_plan = self.region_original_path = None
        self.line_start = self.line_end = self.geometry_stroke = None
        self.line_eraser_stroke = None
        self.line_eraser_hits = set()
        self.rectangle_start = self.rectangle_end = None
        self.circle_center = None
        self.circle_radius = self.circle_adjustment = 0.0
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
            original = self.edit_preview or self.session.geometry()
            geometry = self.editing_geometry(original)
            if self.mode == "Auto-close":
                tolerance = self.auto_close_distance / max(self.transform().m11(), 1e-9)
                key = original, tolerance, self.safe_json_repair, self.source_layer
                if self.auto_close_key != key:
                    self.auto_close_index = self.repair_index(original, tolerance)
                    self.auto_close_key = key
                self.auto_close_plan = self.auto_close_index.at(self.cursor_point)
                edges = self.auto_close_plan.segments
            elif self.mode in GEOMETRY_ERASERS:
                radius = self.geometry_diameter / 2 / max(self.transform().m11(), 1e-9)
                if self.mode == "Erase lines":
                    index = self.line_eraser_stroke or self._line_eraser(geometry)
                    edges = tuple(
                        piece
                        for hit, piece in index.targets(
                            self.cursor_point, self.cursor_point, radius
                        )
                        if (hit, piece) not in self.line_eraser_hits
                    )
                else:
                    targets = geometry_targets(
                        geometry, self.cursor_point, self.cursor_point, radius, "vertices"
                    )
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
                    if self.connection_prompt is not None or any(groups(geometry)):
                        owner = self._point_owner(geometry, vertex, self.cursor_point)
                        edges = tuple(
                            edge
                            for edge, record in zip(all_edges, geometry.lineage, strict=True)
                            if vertex in edge and record.connection_group == owner.connection_group
                        )
                    else:
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
        if self.session and self.contour_selection_context and self.contour_line_ids:
            geometry = self.editing_geometry()
            selected = set(self.contour_line_ids)
            chosen = tuple(
                edge
                for edge, record in zip(
                    geometry_edges(geometry.walls, geometry.closures), geometry.lineage, strict=True
                )
                if record.id in selected
            )
            edges = tuple(dict.fromkeys((*edges, *chosen)))
        self.highlight_edges(edges, self.auto_close_plan.endpoint_moves)
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
            or self.circle_center is not None
            or self.rectangle_start is not None
            or self.paste_delta is not None
            or self.region_drag_start is not None
            or self.selection_start is not None
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
        if self.mode == "New circle":
            if self.circle_center is not None:
                self.circle_adjustment += steps / max(self.transform().m11(), 1e-9)
                self.circle_radius = max(
                    0, math.dist(self.circle_center, self.cursor_point) + self.circle_adjustment
                )
                self.viewport().update()
            return
        if self.mode in MOVE_TOOLS:
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

    def _shape_anchor(self, point, modifiers):
        self.axis_constrained = (
            bool(modifiers & Qt.KeyboardModifier.AltModifier) and self.contour_alignment
        )
        self.alignment_guides = ()
        self.angle_joint = None
        if self.axis_constrained:
            point, self.alignment_guides = align_orthogonal_point(
                point,
                vertices(self.editing_geometry()),
                self.contour_alignment_distance_px / max(self.transform().m11(), 1e-9),
            )
        self.snap = point if self.alignment_guides else None
        return point

    def copy_selected_regions(self):
        if (
            not self.session
            or not (self.figure_line_ids if self.figure_selection else self.region_polygons)
            or self.active_gesture
        ):
            return False
        self.region_clipboard = (
            copy_figures(self.session.geometry(), self.figure_line_ids)
            if self.figure_selection
            else copy_regions(
                self.session.geometry(),
                self.region_polygons,
                self.selectable_regions(),
                self.analysis.joins,
                selection_ids=self.detached_selection["line_ids"]
                if self.detached_selection
                else (),
                active_ids={r.id for r in self.editing_geometry().lineage}
                if self.safe_json_repair
                else None,
            )
        )
        if self.cursor_point is not None:
            self.region_clipboard = replace(
                self.region_clipboard,
                anchor=min(
                    self.region_clipboard.points,
                    key=lambda p: (math.dist(p, self.cursor_point), p),
                ),
            )
        self.clipboard_source = self.session.source
        self.clipboard_changed.emit()
        self.message.emit(
            "Contours copied. Ctrl+V: place a copy."
            if self.figure_selection
            else "Regions copied. Ctrl+V: place a copy of their contours."
        )
        return True

    def begin_paste_regions(self):
        if (
            not self.session
            or not self.region_clipboard
            or self.mode not in TRANSFORM_TOOLS
            or self.active_gesture
        ):
            return False
        self._freeze_placement_targets(self.editing_geometry())
        self.paste_delta = (0, 0)
        self._preview_paste(
            self.cursor_point or self.region_clipboard.anchor, Qt.KeyboardModifier.NoModifier
        )
        return True

    def _freeze_placement_targets(self, geometry):
        self.paste_vertices = tuple(sorted(vertices(geometry)))
        self.paste_vertex_tree = STRtree([Point(p) for p in self.paste_vertices])
        self.paste_anchors = tuple(
            tuple(sorted((p[axis], p) for p in self.paste_vertices)) for axis in (0, 1)
        )

    def _placement_point(self, point, modifiers):
        """Align one grabbed vertex; the owning region is translated rigidly."""
        self.placement_guides = ()
        self.snap = None
        if not modifiers & Qt.KeyboardModifier.AltModifier:
            return point
        zoom = max(self.transform().m11(), 1e-9)
        if self.snap_enabled and self.snap_distance > 0:
            tolerance = self.snap_distance / zoom
            point_candidates = []
            for hit in self.paste_vertex_tree.query(
                box(
                    point[0] - tolerance,
                    point[1] - tolerance,
                    point[0] + tolerance,
                    point[1] + tolerance,
                )
            ):
                anchor = self.paste_vertices[int(hit)]
                distance = math.dist(point, anchor)
                if distance <= tolerance:
                    point_candidates.append((distance, anchor))
            if point_candidates:
                _, anchor = min(point_candidates)
                self.snap = anchor
                self.placement_guides = ((point, anchor),)
                return anchor
        delta = list(point)
        if self.contour_alignment:
            tolerance = self.contour_alignment_distance_px / zoom
            guides = []
            for axis in (0, 1):
                candidates = []
                anchors = self.paste_anchors[axis]
                coordinate = point[axis]
                at = bisect_left(anchors, (coordinate, (-float("inf"), -float("inf"))))
                for index in (at - 1, at):
                    if 0 <= index < len(anchors):
                        distance = abs(anchors[index][0] - coordinate)
                        if distance <= tolerance:
                            candidates.append((distance, anchors[index][1]))
                if candidates:
                    _, anchor = min(candidates)
                    delta[axis] = anchor[axis]
                    guides.append(anchor)
            self.placement_guides = tuple((a, tuple(delta)) for a in guides)
        return tuple(delta)

    def _preview_paste(self, point, modifiers):
        self.region_anchor = self._placement_point(point, modifiers)
        self.paste_delta = tuple(
            self.region_anchor[i] - self.region_clipboard.anchor[i] for i in (0, 1)
        )
        self.viewport().update()

    def _region_plan(self):
        if self.figure_selection:
            return plan_figure_transform(
                self.session.geometry(), self.figure_line_ids, self.figure_pivot
            )
        return plan_region_transform(
            self.session.geometry(),
            self.region_polygons,
            self.selectable_regions(),
            False,
            self.snap_distance / max(self.transform().m11(), 1e-9),
            self.analysis.joins,
            self.region_pivot,
            selection_ids=self.detached_selection["line_ids"] if self.detached_selection else (),
            active_ids={
                self.session.geometry().lineage[i].id for i in self.selected_source_layer().indices
            }
            if self.safe_json_repair
            else None,
        )

    def transform_regions(self, scale=1.0, angle=0.0):
        if (
            not self.session
            or not (self.figure_line_ids if self.figure_selection else self.region_polygons)
            or self.active_gesture
        ):
            return
        plan = self._region_plan()
        identifiers = tuple(record.id for record in plan.noded.lineage[len(plan.fixed) :])
        rotating = angle != 0 and scale == 1 and self.mode in ROTATE_TOOLS
        continue_rotation = bool(
            rotating
            and self.session.operations
            and self.session.operations[-1] is self.rotation_last
            and identifiers == self.rotation_ids
        )
        if not rotating:
            self.finish_rotation()
        geometry, polygons = plan.apply(scale=scale, angle=angle)
        if geometry != plan.original:
            if continue_rotation:
                self.session.operations[-1] = geometry
            else:
                self.session.add(geometry)
            if rotating:
                self.rotation_last, self.rotation_ids = geometry, identifiers
            self.changed.emit()
            self.regions_transformed.emit(
                {
                    "polygons": polygons,
                    "pivot": plan.pivot,
                    "line_ids": identifiers,
                }
            )

    def finish_rotation(self):
        self.rotation_last = None
        self.rotation_ids = ()

    def _preview_region_move(self, point, modifiers=Qt.KeyboardModifier.NoModifier):
        candidate = tuple(
            self.region_grab_vertex[i] + point[i] - self.region_drag_start[i] for i in (0, 1)
        )
        self.region_anchor = self._placement_point(candidate, modifiers)
        dx, dy = self.region_translation = tuple(
            self.region_anchor[i] - self.region_grab_vertex[i] for i in (0, 1)
        )
        self.edit_preview, _ = self.region_plan.apply(dx=dx, dy=dy)
        self.selected_path = QTransform.fromTranslate(dx, dy).map(self.region_original_path)
        self.refresh(render_image=False)

    def _hover_region_anchor(self, point):
        points = (
            tuple(p for edge in self.selected_figure_edges() for p in edge)
            if self.figure_selection
            else tuple(
                tuple(p)
                for polygon in self.region_polygons
                for ring in (polygon.exterior, *polygon.interiors)
                for p in ring.coords[:-1]
            )
        )
        self.region_anchor = min(points, key=lambda p: (math.dist(p, point), p)) if points else None

    def _drag_destination(self, point, modifiers=Qt.KeyboardModifier.NoModifier):
        destination = (point[0] + self.drag_offset[0], point[1] + self.drag_offset[1])
        self.axis_constrained = bool(modifiers & Qt.KeyboardModifier.AltModifier) and (
            self.right_angle_alignment or self.contour_alignment
        )
        self.alignment_guides = ()
        self.angle_joint = None
        if self.axis_constrained:
            zoom = max(self.transform().m11(), 1e-9)
            raw = destination
            if self.contour_alignment:
                destination, self.alignment_guides = align_orthogonal_point(
                    destination, self.alignment_anchors, self.contour_alignment_distance_px / zoom
                )
            if self.right_angle_alignment:
                destination, self.angle_joint = right_angle_point(
                    raw,
                    destination,
                    self.drag_vertex,
                    self.alignment_neighbours,
                    self.editing_geometry(self.drag_base),
                    self.right_angle_distance_px / zoom,
                )
                self.alignment_guides = tuple(
                    (axis, anchor)
                    for axis, anchor in self.alignment_guides
                    if abs(destination[axis] - anchor[axis]) <= 1e-7
                )
            self.snap = destination if self.alignment_guides or self.angle_joint else None
            return destination
        if math.dist(destination, self.drag_vertex) > 0.5 / self.transform().m11():
            self.snap = snap_point(
                self.editing_geometry(self.drag_base),
                destination,
                self._snap_tolerance(),
                exclude=self.drag_vertex,
            )
            return self.snap or destination
        self.snap = None
        return destination

    def _line_eraser(self, geometry):
        current = self.line_eraser_index
        if current is None or (
            current.geometry != geometry
            or current.geometry.lineage != geometry.lineage
            or current.geometry.ancestry != geometry.ancestry
            or current.geometry.wall_styles != geometry.wall_styles
        ):
            self.line_eraser_index = LineEraser(geometry)
        return self.line_eraser_index

    def _erase_geometry(self, point):
        start = self.geometry_stroke or point
        if self.mode == "Erase lines":
            original = self.drag_base
            active = self.selected_source_layer(original).indices if self.safe_json_repair else None
            if self.line_eraser_stroke is None:
                scoped = layer_geometry(original, active) if active is not None else original
                self.line_eraser_stroke = self._line_eraser(scoped)
            index = self.line_eraser_stroke
            hits = set(
                index.targets(start, point, self.geometry_diameter / 2 / self.transform().m11())
            )
            if hits - self.line_eraser_hits:
                self.line_eraser_hits.update(hits)
                edited = index.erase(self.line_eraser_hits)
                self.edit_preview = (
                    replace_layer_geometry(original, active, edited)
                    if active is not None
                    else edited
                )
            self.geometry_stroke = point
            self.refresh(render_image=False)
            return
        original = self.edit_preview
        active = self.selected_source_layer(original).indices if self.safe_json_repair else None
        scoped = layer_geometry(original, active) if active is not None else original
        edited = erase_geometry(
            scoped,
            start,
            point,
            self.geometry_diameter / 2 / self.transform().m11(),
            "lines" if self.mode == "Erase lines" else "vertices",
        )
        self.edit_preview = (
            replace_layer_geometry(original, active, edited) if active is not None else edited
        )
        self.geometry_stroke = point
        self.refresh(render_image=False)

    def _handle_tolerance(self):
        return HANDLE_DIAMETER / max(self.transform().m11(), 1e-9)

    def _point_owner(self, geometry, vertex, cursor):
        candidates = [
            (edge != self.hover_edge, LineString(edge).distance(Point(cursor)), index, record)
            for index, (edge, record) in enumerate(
                zip(
                    geometry_edges(geometry.walls, geometry.closures), geometry.lineage, strict=True
                )
            )
            if vertex in edge
        ]
        return min(candidates, key=lambda item: item[:3])[-1]

    def _resolve_connection(self, geometry, destination=None):
        if self.connection_prompt is None:
            return geometry
        scoped = self.editing_geometry(geometry)
        if self.mode == "Erase lines":
            if self.line_eraser_stroke is None:
                return geometry
            points, independent, participants = cut_contacts(
                self.line_eraser_stroke.geometry, scoped
            )
            if not points:
                return geometry
        else:
            if not any(
                destination in edge
                for edge, record in zip(
                    geometry_edges(scoped.walls, scoped.closures), scoped.lineage, strict=True
                )
                if record.id in self.drag_component_ids
            ):
                return geometry
            targets = point_contacts(
                self.editing_geometry(self.drag_base), self.drag_component_ids, destination
            )
            if not targets:
                return geometry
            points = (destination,)
            independent = (self.drag_component_ids,)
            participants = {*self.drag_component_ids, *targets}
        answer = self.connection_prompt(self.mode)
        if answer is None:
            return self.drag_original
        if answer:
            resolved = join(scoped, participants, points)
        else:
            resolved = scoped
            for identifiers in independent:
                own_groups = {
                    record.connection_group
                    for record in resolved.lineage
                    if record.id in identifiers
                }
                other_groups = {
                    record.connection_group
                    for record in resolved.lineage
                    if record.id in participants and record.id not in identifiers
                }
                if own_groups.intersection(other_groups):
                    resolved = isolate(resolved, identifiers)
        return (
            replace_layer_geometry(geometry, self.selected_source_layer(geometry).indices, resolved)
            if self.safe_json_repair
            else resolved
        )

    def _begin_point_edit(self, point):
        original = self.session.geometry()
        before_insertion = original
        geometry = self.editing_geometry(original)
        vertex = hit_vertex(geometry, point, self._handle_tolerance())
        if vertex is None:
            hit = hit_edge(geometry, point, self._handle_tolerance() * 0.7)
            if hit is None:
                return
            vertex = hit_vertex(geometry, hit.point, self._handle_tolerance())
            if vertex is None:
                geometry = insert_vertex(geometry, hit)
                vertex = hit.point
                if self.safe_json_repair:
                    original = replace_layer_geometry(
                        original, self.selected_source_layer(original).indices, geometry
                    )
        owner = self._point_owner(geometry, vertex, point)
        self.drag_connection_group = owner.connection_group
        self.drag_component_ids = next(
            component.line_ids
            for component in components(geometry)
            if owner.id in component.line_ids
        )
        self.drag_base, self.drag_original = (
            original if self.safe_json_repair else geometry,
            before_insertion,
        )
        self.drag_vertex = vertex
        intervals = None
        if self.safe_json_repair:
            bounds, _ = wall_intervals(self.session.source, original, self.property_documents)
            intervals = tuple(bounds[i] for i in self.selected_source_layer(original).indices)
        if self.connection_prompt is not None or any(groups(geometry)):
            indices = tuple(
                i
                for i, record in enumerate(geometry.lineage)
                if record.id in self.drag_component_ids
            )
            geometry = layer_geometry(geometry, indices)
            if intervals is not None:
                intervals = tuple(intervals[i] for i in indices)
        self.alignment_anchors = alignment_points(geometry, vertex, intervals)
        self.alignment_neighbours = alignment_points(
            geometry, vertex, intervals, neighbours_only=True
        )
        self.drag_offset = (vertex[0] - point[0], vertex[1] - point[1])
        self.edit_preview = self.drag_base
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        self.refresh(render_image=False)

    def remember_figure_click(self, point, target, before):
        """Keep one provisional click until Qt recognizes a double-click pair."""
        self.figure_click = {
            "target": target,
            "before": before,
            "after": self.figure_line_ids,
            "pivot": self.figure_pivot,
            "session": self.session,
            "geometry": self.geometry_key,
            "transform": self.transform(),
            "point": self.mapFromScene(*point),
            "time": monotonic(),
        }

    def _figure_double_click(self, screen):
        first = self.figure_click
        if first is None:
            return None
        hints = QApplication.instance().styleHints()
        delta = screen.toPoint() - first["point"]
        if (
            self.session is first["session"]
            and self.geometry_key == first["geometry"]
            and self.transform() == first["transform"]
            and self.figure_line_ids == first["after"]
            and self.figure_pivot == first["pivot"]
            and monotonic() - first["time"] <= hints.mouseDoubleClickInterval() / 1000
            and max(abs(delta.x()), abs(delta.y())) <= hints.mouseDoubleClickDistance()
        ):
            return first
        return None

    def mousePressEvent(self, event):
        self.finish_rotation()
        self.figure_click = None
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
        if self.paste_delta is not None:
            self._preview_paste(point, event.modifiers())
            dx, dy = self.paste_delta
            original = self.session.geometry()
            try:
                geometry = self.region_clipboard.paste(original, dx, dy)
                if geometry != original:
                    self.paste_committed.emit(self.clipboard_source)
                    self.session.add(geometry)
                    self.changed.emit()
                    self.regions_transformed.emit(
                        {
                            "polygons": tuple(
                                translate_shape(p, xoff=dx, yoff=dy)
                                for p in self.region_clipboard.polygons
                            ),
                            "pivot": (
                                self.region_clipboard.anchor[0] + dx,
                                self.region_clipboard.anchor[1] + dy,
                            ),
                            "line_ids": tuple(
                                r.id
                                for r in geometry.lineage
                                if r.id not in {old.id for old in original.lineage}
                            ),
                        }
                    )
            except ValueError as exc:
                self.message.emit(str(exc))
            self.paste_delta = None
            self.placement_guides = ()
            self.snap = None
            self.region_anchor = None
            self.refresh(render_image=False)
            event.accept()
            return
        if self.mode in MOVE_TOOLS:
            edges = self.selected_figure_edges() if self.figure_selection else ()
            figure_hit = bool(edges) and (
                unary_union([LineString(edge) for edge in edges]).distance(Point(point))
                <= self._handle_tolerance()
                or any(
                    component.area.covers(Point(point))
                    for component in contour_components(
                        edges, tuple(str(i) for i in range(len(edges)))
                    )
                )
            )
            if (
                figure_hit
                if self.figure_selection
                else self.selected_path.contains(QPointF(*point)) and self.region_polygons
            ):
                self.region_drag_start = point
                self.region_plan = self._region_plan()
                self._hover_region_anchor(point)
                self.region_grab_vertex = self.region_anchor
                from dale.session import GeometryEdit

                self._freeze_placement_targets(
                    self.editing_geometry(
                        GeometryEdit(
                            self.region_plan.fixed,
                            lineage=self.region_plan.noded.lineage[: len(self.region_plan.fixed)],
                            ancestry=self.region_plan.noded.ancestry,
                            wall_styles=self.region_plan.noded.wall_styles,
                        )
                    )
                )
                self.region_original_path = QPainterPath(self.selected_path)
                self.region_translation = (0, 0)
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if self.mode in SELECTION_TOOLS:
            self.selection_start = point
            self.selection_screen = event.position()
            self.selection_rect = None
            self.region_box_selected.emit(
                {
                    "phase": "begin",
                }
            )
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
            if self.safe_json_repair and self.selected_source_layer().kind not in (
                "all",
                "band",
                "range",
            ):
                self.message.emit("Choose a height range before drawing a new contour.")
                event.accept()
                return
            self.snap = snap_point(self.editing_geometry(), point, self._snap_tolerance())
            self.line_start = self.line_end = self._line_anchor(point)
            self.viewport().update()
            event.accept()
            return
        if self.mode == "New rectangle":
            if self.safe_json_repair and self.selected_source_layer().kind not in (
                "all",
                "band",
                "range",
            ):
                self.message.emit("Choose a height range before drawing a new contour.")
                event.accept()
                return
            self.rectangle_start = self.rectangle_end = self._shape_anchor(point, event.modifiers())
            self.viewport().update()
            event.accept()
            return
        if self.mode == "New circle":
            if self.safe_json_repair and self.selected_source_layer().kind not in (
                "all",
                "band",
                "range",
            ):
                self.message.emit("Choose a height range before drawing a new contour.")
                event.accept()
                return
            self.circle_center = point
            self.circle_radius = self.circle_adjustment = 0.0
            self.snap = None
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
        if self.selection_start is not None:
            self._preview_selection(point, event.position(), event.modifiers())
            event.accept()
            return
        if self.paste_delta is not None:
            self._preview_paste(point, event.modifiers())
            event.accept()
            return
        if self.rectangle_start is not None:
            self.rectangle_end = self._shape_anchor(point, event.modifiers())
            self.viewport().update()
            event.accept()
            return
        if self.circle_center is not None:
            self.circle_radius = max(
                0, math.dist(self.circle_center, point) + self.circle_adjustment
            )
            self.viewport().update()
            event.accept()
            return
        if self.mode in MOVE_TOOLS and self.region_drag_start is not None:
            self._preview_region_move(point, event.modifiers())
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
            self.snap = snap_point(self.editing_geometry(), point, self._snap_tolerance())
            if self.line_start is not None:
                self.line_end = self._line_anchor(point)
            self.update_hover()
            self.viewport().update()
            event.accept()
            return
        if self.mode == "Edit points" and self.session:
            if self.drag_base is not None and event.buttons() & Qt.MouseButton.LeftButton:
                destination = self._drag_destination(point, event.modifiers())
                self.edit_preview = self._move_point(destination)
                self.refresh(render_image=False)
            else:
                vertex = hit_vertex(self.editing_geometry(), point, self._handle_tolerance())
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
        if self.mode in (*MOVE_TOOLS, "Select regions", "Select figures"):
            self._hover_region_anchor(point)
        if self.stroke and event.buttons() & Qt.MouseButton.LeftButton:
            if math.dist(self.stroke[-1], point) >= max(0.5, self.diameter / 10):
                self.stroke.append(point)
                if not self.render_timer.isActive():
                    self.render_timer.start()
        self.viewport().update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.selection_start is not None and event.button() == Qt.MouseButton.LeftButton:
            point = self._point(event)
            self._preview_selection(point, event.position(), event.modifiers())
            rectangle = self.selection_rect
            self.selection_start = self.selection_screen = self.selection_rect = None
            self.region_box_selected.emit({"phase": "commit" if rectangle else "click"})
            if rectangle is None:
                if self.figure_selection:
                    self.figure_clicked.emit(
                        {
                            "point": point,
                            "mouse": True,
                        }
                    )
                else:
                    self.region_clicked.emit(point)
            self.viewport().update()
            event.accept()
            return
        if self.panning and event.button() == self.pan_button:
            self.panning = False
            self.pan_button = None
            self.setCursor(
                Qt.CursorShape.OpenHandCursor
                if self.mode in ("Pan", *MOVE_TOOLS)
                else Qt.CursorShape.CrossCursor
            )
            self.cursor_point = self._point(event)
            self.update_hover()
            event.accept()
            return
        if self.rectangle_start is not None and event.button() == Qt.MouseButton.LeftButton:
            start, end = (
                self.rectangle_start,
                self._shape_anchor(self._point(event), event.modifiers()),
            )
            self.rectangle_start = self.rectangle_end = None
            self.alignment_guides = ()
            self.snap = None
            minimum = 1 / max(self.transform().m11(), 1e-9)
            if abs(start[0] - end[0]) >= minimum and abs(start[1] - end[1]) >= minimum:
                try:
                    original = self.session.geometry()
                    if self.safe_json_repair:
                        geometry = original
                        for a, b in pairwise(rectangle_points(start, end)):
                            geometry = add_source_wall(
                                self.session.source,
                                geometry,
                                a,
                                b,
                                self.selected_source_layer(geometry),
                                documents=self.property_documents,
                            )
                    else:
                        geometry = add_rectangle(original, start, end)
                    if geometry != original:
                        self.session.add(geometry)
                        self.changed.emit()
                except ValueError as exc:
                    self.message.emit(str(exc))
            self.refresh(render_image=False)
            event.accept()
            return
        if self.circle_center is not None and event.button() == Qt.MouseButton.LeftButton:
            center = self.circle_center
            radius = max(0, math.dist(center, self._point(event)) + self.circle_adjustment)
            self.circle_center = None
            self.circle_radius = self.circle_adjustment = 0.0
            if radius >= 1 / max(self.transform().m11(), 1e-9):
                try:
                    original = self.session.geometry()
                    if self.safe_json_repair:
                        geometry = original
                        for a, b in pairwise(
                            circle_points(center, radius, self.session.source.cell_pixels)
                        ):
                            geometry = add_source_wall(
                                self.session.source,
                                geometry,
                                a,
                                b,
                                self.selected_source_layer(geometry),
                                documents=self.property_documents,
                            )
                    else:
                        geometry = add_circle(
                            original, center, radius, self.session.source.cell_pixels
                        )
                    if geometry != original:
                        self.session.add(geometry)
                        self.changed.emit()
                except ValueError as exc:
                    self.message.emit(str(exc))
            self.refresh(render_image=False)
            event.accept()
            return
        if self.region_drag_start is not None and event.button() == Qt.MouseButton.LeftButton:
            point = self._point(event)
            self._preview_region_move(point, event.modifiers())
            dx, dy = self.region_translation
            plan = self.region_plan
            geometry, polygons = plan.apply(dx=dx, dy=dy)
            self.region_drag_start = self.region_plan = self.region_original_path = None
            self.edit_preview = None
            self.placement_guides = ()
            self.snap = None
            self.region_grab_vertex = None
            if geometry != plan.original:
                self.session.add(geometry)
                self.changed.emit()
                self.regions_transformed.emit(
                    {
                        "polygons": polygons,
                        "pivot": (plan.pivot[0] + dx, plan.pivot[1] + dy),
                        "line_ids": tuple(r.id for r in geometry.lineage[len(plan.fixed) :]),
                    }
                )
            self.refresh(render_image=False)
            self._hover_region_anchor(point)
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        if self.drag_base is not None and event.button() == Qt.MouseButton.LeftButton:
            point = self._point(event)
            if self.mode in GEOMETRY_ERASERS:
                self._erase_geometry(point)
                geometry = self.edit_preview
                if self.mode == "Erase lines" and geometry != self.drag_original:
                    geometry = self._resolve_connection(geometry)
            else:
                destination = self._drag_destination(point, event.modifiers())
                geometry = self._move_point(destination, report=True)
                geometry = self._resolve_connection(geometry, destination)
            original = self.drag_original
            self.edit_preview = self.drag_base = self.drag_original = self.drag_vertex = None
            self.drag_offset = None
            self.alignment_neighbours = self.alignment_anchors = self.alignment_guides = ()
            self.axis_constrained = False
            self.angle_joint = None
            self.geometry_stroke = None
            self.line_eraser_stroke = None
            self.line_eraser_hits = set()
            if geometry != original or groups(geometry) != groups(original):
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
            minimum = (
                1 / self.transform().m11() if self.safe_json_repair else self._handle_tolerance()
            )
            if math.dist(start, end) >= minimum:
                geometry = (
                    add_source_wall(
                        self.session.source,
                        original,
                        start,
                        end,
                        self.selected_source_layer(original),
                        documents=self.property_documents,
                    )
                    if self.safe_json_repair
                    else add_line(original, start, end)
                )
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

    def _preview_selection(self, point, screen, modifiers=Qt.KeyboardModifier.NoModifier):
        delta = screen - self.selection_screen
        if self.selection_rect is None and math.hypot(delta.x(), delta.y()) <= SELECTION_DRAG_PX:
            return
        a = self.selection_start
        self.selection_rect = (
            min(a[0], point[0]),
            min(a[1], point[1]),
            max(a[0], point[0]),
            max(a[1], point[1]),
        )
        self.region_box_selected.emit(
            {
                "phase": "preview",
                "bounds": self.selection_rect,
            }
        )
        self.viewport().update()

    def mouseDoubleClickEvent(self, event):
        if self.mode == "Select figures" and event.button() == Qt.MouseButton.LeftButton:
            first = self._figure_double_click(event.position())
            self.cancel_pending()
            self.figure_clicked.emit(
                {"point": self._point(event), "double": True, "first_click": first}
            )
            event.accept()
            return
        if (
            self.mode == "Edit points"
            and self.session
            and event.button() == Qt.MouseButton.LeftButton
        ):
            point = self._point(event)
            self.cancel_pending()
            original = self.session.geometry()
            active = self.selected_source_layer(original).indices if self.safe_json_repair else None
            geometry = layer_geometry(original, active) if active is not None else original
            vertex = hit_vertex(geometry, point, self._handle_tolerance() * 0.65)
            if vertex is not None:
                if any(groups(geometry)):
                    owner = self._point_owner(geometry, vertex, point)
                    indices = tuple(
                        i
                        for i, record in enumerate(geometry.lineage)
                        if record.connection_group == owner.connection_group
                    )
                    selected = layer_geometry(geometry, indices)
                    edited = replace_layer_geometry(
                        geometry, indices, delete_vertex(selected, vertex)
                    )
                else:
                    edited = delete_vertex(geometry, vertex)
                if active is not None:
                    edited = replace_layer_geometry(original, active, edited)
                if edited != geometry:
                    self.session.add(edited)
                    self.changed.emit()
                    self.refresh(render_image=False)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):
        if (
            self.mode in ROTATE_TOOLS
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
            self.region_anchor = None
            self.update_hover()
        super().leaveEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Alt and self.cursor_point:
            if self.rectangle_start is not None:
                self.rectangle_end = self._shape_anchor(
                    self.cursor_point, Qt.KeyboardModifier.AltModifier
                )
                self.viewport().update()
            if self.paste_delta is not None:
                self._preview_paste(self.cursor_point, Qt.KeyboardModifier.AltModifier)
            if self.region_drag_start is not None:
                self._preview_region_move(self.cursor_point, Qt.KeyboardModifier.AltModifier)

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
        if event.key() == Qt.Key.Key_Alt and self.cursor_point:
            if self.rectangle_start is not None:
                self.rectangle_end = self._shape_anchor(
                    self.cursor_point, Qt.KeyboardModifier.NoModifier
                )
                self.viewport().update()
            if self.paste_delta is not None:
                self._preview_paste(self.cursor_point, Qt.KeyboardModifier.NoModifier)
            if self.region_drag_start is not None:
                self._preview_region_move(self.cursor_point, Qt.KeyboardModifier.NoModifier)

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
            self.edit_preview = self._move_point(destination)
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

        if not self.figure_selection and (self.show_walls or self.mode in AREA_TOOLS):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(88, 217, 236, 64))
            painter.drawPath(self.selected_path)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            path(self.selected_path, "#58d9ec")
        if self.show_walls:
            path(self.original_path, "#58d9ec")
            path(self.warning_path, "#ff0000")
            path(self.offset_path, "#58d9ec", True)
        if self.figure_selection:
            selected_edges = self.selected_figure_edges()
            selected_path = line_path(selected_edges)
            outlined(lambda: painter.drawPath(selected_path), "#58d9ec", backing="#ffffff")
            key = selected_edges, self.geometry_key
            if getattr(self, "figure_warning_key", None) != key:
                intersection = unary_union([LineString(e) for e in selected_edges]).intersection(
                    self.warning_geometry
                )
                pending, edges = [intersection], []
                while pending:
                    geometry = pending.pop()
                    if geometry.geom_type == "LineString":
                        edges.extend(pairwise(geometry.coords))
                    elif hasattr(geometry, "geoms"):
                        pending.extend(geometry.geoms)
                self.figure_warning_key = key
                self.figure_warning_path = line_path(edges)
            outlined(
                lambda: painter.drawPath(self.figure_warning_path), "#ff0000", backing="#ffffff"
            )
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
        if self.paste_delta is not None:
            dx, dy = self.paste_delta
            edges = tuple(
                tuple((x + dx, y + dy) for x, y in edge) for edge in self.region_clipboard.edges
            )
            path(line_path(edges), "#58d9ec")
        if self.paste_delta is not None or self.region_drag_start is not None:
            painter.save()
            painter.setPen(pen("#999fcbd2", 1, True))
            for a, b in self.placement_guides:
                painter.drawLine(QPointF(*a), QPointF(*b))
            painter.restore()
        if self.region_anchor is not None and self.mode in TRANSFORM_TOOLS:
            painter.setBrush(QColor("#effbff"))
            circle(self.region_anchor, HANDLE_DIAMETER / 2 / self.transform().m11(), "#ffffff")
            painter.setBrush(Qt.BrushStyle.NoBrush)
        if self.selection_rect is not None:
            x0, y0, x1, y1 = self.selection_rect
            rect = QRectF(x0, y0, x1 - x0, y1 - y0)
            painter.fillRect(rect, QColor(88, 217, 236, 24))
            outlined(lambda: painter.drawRect(rect), "#ffffff", True)
        if self.rectangle_start is not None:
            path(
                line_path(pairwise(rectangle_points(self.rectangle_start, self.rectangle_end))),
                "#58d9ec",
            )
        if self.circle_center is not None:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if self.circle_radius > 0:
                points = circle_points(
                    self.circle_center, self.circle_radius, self.session.source.cell_pixels
                )
                path(line_path(pairwise(points)), "#58d9ec")
            painter.setBrush(QColor("#effbff"))
            circle(self.circle_center, HANDLE_DIAMETER / 2 / self.transform().m11(), "#58d9ec")
        if self.axis_constrained and (self.drag_vertex is not None or self.mode == "New rectangle"):
            destination = self.snap
            if destination is not None:
                margin = 20 / max(self.transform().m11(), 1e-9)
                painter.save()
                painter.setPen(pen("#999fcbd2", 1, True))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                for axis, anchor in self.alignment_guides:
                    other = 1 - axis
                    a, b = list(destination), list(destination)
                    a[other] = min(anchor[other], destination[other]) - margin
                    b[other] = max(anchor[other], destination[other]) + margin
                    painter.drawPath(line_path(((a, b),)))
                painter.restore()
            if self.angle_joint is not None:
                a, joint, b = self.angle_joint
                for edge in ((a, joint), (joint, b)):
                    color = (
                        "#ff0000"
                        if self.warning_geometry.buffer(1e-7).covers(LineString(edge))
                        else "#58d9ec"
                    )
                    outlined(
                        lambda edge=edge: painter.drawPath(line_path((edge,))),
                        color,
                        backing="#ffffff",
                    )
                size = min(
                    8 / max(self.transform().m11(), 1e-9),
                    math.dist(a, joint) / 3,
                    math.dist(b, joint) / 3,
                )
                u = tuple((a[i] - joint[i]) / math.dist(a, joint) * size for i in (0, 1))
                v = tuple((b[i] - joint[i]) / math.dist(b, joint) * size for i in (0, 1))
                mark = tuple(
                    tuple(joint[i] + x[i] for i in (0, 1))
                    for x in (u, (u[0] + v[0], u[1] + v[1]), v)
                )
                path(line_path(pairwise(mark)), "#f4db8c")
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
