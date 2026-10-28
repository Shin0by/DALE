"""One retained exact selection for painting and pointer queries, independent of zoom."""

from functools import cached_property
from itertools import pairwise
from math import dist

import numpy as np
from PySide6.QtGui import QPainterPath
from shapely import LineString, Point, STRtree, points, union_all

from dale.provenance import geometry_edges


class SelectionDisplay:
    def __init__(self, geometry, identifiers):
        self.geometry, self.identifiers = geometry, tuple(identifiers)

    @cached_property
    def selected(self):
        return frozenset(self.identifiers)

    @cached_property
    def edges(self):
        if not self.selected:
            return ()
        return tuple(
            edge
            for edge, record in zip(
                geometry_edges(self.geometry.walls, self.geometry.closures),
                self.geometry.lineage,
                strict=True,
            )
            if record.id in self.selected
        )

    @cached_property
    def path(self):
        from dale.canvas import line_path

        return line_path(self.edges)

    @cached_property
    def coordinates(self):
        return np.asarray(self.edges).reshape((-1, 2))

    @cached_property
    def center(self):
        if not self.edges:
            return None
        return tuple((self.coordinates.min(axis=0) + self.coordinates.max(axis=0)) / 2)

    @cached_property
    def vertex_index(self):
        coordinates = np.unique(self.coordinates, axis=0)
        return coordinates, STRtree(points(coordinates))

    def nearest_vertex(self, point, center):
        if not self.edges:
            return None
        coordinates, tree = self.vertex_index
        candidates = [tuple(coordinates[int(i)]) for i in tree.query_nearest(Point(point))]
        if center is not None:
            candidates.append(center)
        return min(candidates, key=lambda p: (dist(p, point), p))

    def warning_path(self, warning):
        cached = getattr(self, "_warning", None)
        if cached is not None and cached[0] is warning:
            return cached[1]
        path = QPainterPath()
        # Most DA objects are closed. Do not node hundreds of thousands of
        # selected segments just to intersect them with an empty warning set.
        if self.edges and not warning.is_empty:
            pending = [union_all([LineString(edge) for edge in self.edges]).intersection(warning)]
            while pending:
                shape = pending.pop()
                if shape.geom_type == "LineString":
                    for a, b in pairwise(shape.coords):
                        path.moveTo(*a)
                        path.lineTo(*b)
                elif hasattr(shape, "geoms"):
                    pending.extend(shape.geoms)
        self._warning = warning, path
        return path
