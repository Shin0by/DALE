"""Vector editing history: mask snapshots, local closures, and brush strokes."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

from dale.geometry import analyze_regions, offset_region
from dale.provenance import LineRecord, SourceWall, geometry_edges, vertex_records
from dale.scene import Point, SceneInput


@dataclass(frozen=True)
class Closure:
    points: tuple[Point, ...]
    lineage: tuple[LineRecord, ...] = field(default=(), compare=False)

    def __post_init__(self):
        edges = geometry_edges((), (self.points,))
        if not self.lineage:
            object.__setattr__(
                self, "lineage", tuple(LineRecord.standalone(edge) for edge in edges)
            )
        elif len(self.lineage) != len(edges):
            raise ValueError("Path provenance must match its edge count.")


@dataclass(frozen=True)
class Stroke:
    points: tuple[Point, ...]
    radius: float
    restore: bool = False
    shape: str = "circle"
    feather: float = 0.0
    opacity: float = 1.0


@dataclass(frozen=True)
class ContourMask:
    area: object
    mode: Literal["outside", "inside"]
    boundary: object = None


@dataclass(frozen=True)
class RasterTransform:
    """Immutable cut-and-transform of the preceding raster state in source pixels."""

    area_wkb: bytes
    matrix: tuple[float, float, float, float, float, float]
    regions: tuple[bytes, ...] = ()
    cells: tuple = ()


@dataclass(frozen=True)
class RegionSelection:
    """Immutable selected cells, independent of Qt and transient cell indices."""

    polygons: tuple[bytes, ...] = ()
    detached: bool = False
    line_ids: tuple[str, ...] = ()
    all_regions: bool = False


@dataclass(frozen=True)
class RasterSelectionEdit:
    before: RegionSelection
    after: RegionSelection


@dataclass(frozen=True)
class GeometryEdit:
    walls: tuple
    closures: tuple[tuple[Point, ...], ...] = ()
    lineage: tuple[LineRecord, ...] = field(default=(), compare=False)
    ancestry: tuple[LineRecord, ...] = field(default=(), compare=False)
    wall_styles: tuple = field(default=(), compare=False, kw_only=True)
    raster: RasterTransform | None = field(default=None, compare=False, kw_only=True)
    connection_state: tuple = field(default=(), init=False)

    def __post_init__(self):
        edges = geometry_edges(self.walls, self.closures)
        if not self.lineage:
            object.__setattr__(
                self, "lineage", tuple(LineRecord.standalone(edge) for edge in edges)
            )
        elif len(self.lineage) != len(edges):
            raise ValueError("Line provenance must match the working edge count.")
        groups = tuple(record.connection_group for record in self.lineage)
        object.__setattr__(self, "connection_state", groups if any(groups) else ())

    @property
    def vertex_lineage(self):
        return vertex_records(self)


@dataclass(frozen=True)
class AddedSourceWall:
    """Stable native identity with manual bounds or exact imported source properties."""

    native_id: str
    bottom: float | None
    top: float | None
    source_ref: SourceWall | None = None
    properties_json: bytes | None = None


@dataclass(frozen=True)
class SourceRepairEdit(GeometryEdit):
    """Canonical source coordinates followed by explicit manual/imported additions."""

    additions: tuple[AddedSourceWall, ...] = ()


Operation = Closure | Stroke | ContourMask | GeometryEdit | RasterSelectionEdit
HISTORY_LIMIT = 100


@dataclass
class Session:
    source: SceneInput
    origin: Point = (0.0, 0.0)
    operations: list[Operation] = field(default_factory=list)
    future: list[Operation] = field(default_factory=list)
    gap_tolerance: float = 0.0
    contour_offset: float = 0.0
    json_documents: tuple = ()
    history_floor: int = field(default=0, kw_only=True)

    @property
    def walls(self):
        return self.geometry().walls

    @property
    def closures(self):
        return self.geometry().closures

    def geometry(self) -> GeometryEdit:
        walls = self.source.image_walls(self.origin)
        records = tuple(LineRecord.source(ref) for ref in self.source.wall_sources)
        geometry = GeometryEdit(walls, lineage=records)
        closures = []
        for operation in self.operations:
            if isinstance(operation, Closure):
                closures.append(operation.points)
                records = (
                    *geometry.lineage,
                    *operation.lineage,
                )
                geometry = GeometryEdit(
                    walls,
                    tuple(closures),
                    tuple(records),
                    geometry.ancestry,
                    wall_styles=geometry.wall_styles,
                )
            elif isinstance(operation, GeometryEdit):
                walls, closures = operation.walls, list(operation.closures)
                geometry = operation
        return geometry

    def analysis(self):
        geometry = self.geometry()
        key = geometry.walls, geometry.closures, self.gap_tolerance
        cached = getattr(self, "_analysis_cache", None)
        if cached is None or cached[0] != key:
            cached = key, analyze_regions(*key)
            self._analysis_cache = cached
        return cached[1]

    def make_mask(self, mode: Literal["outside", "inside"], area=None):
        area = self.analysis().area if area is None else area
        return ContourMask(offset_region(area, self.contour_offset), mode, area)

    def add(self, operation: Operation):
        self.operations.append(operation)
        self.future.clear()
        self.trim_history()

    def trim_history(self, keep=HISTORY_LIMIT):
        """Checkpoint old geometry while retaining exact ordered raster state and lineage."""
        self.future[:] = self.future[-keep:] if keep else []
        cut = max(self.history_floor, len(self.operations) - max(0, keep - len(self.future)))
        if cut <= self.history_floor:
            return
        prefix = self.operations[:cut]
        baseline = [
            op
            for op in prefix
            if isinstance(op, (Stroke, ContourMask)) or getattr(op, "raster", None) is not None
        ]
        if any(isinstance(op, (GeometryEdit, Closure)) for op in prefix):
            geometry = replace(self, operations=prefix, future=[]).geometry()
            records = {}
            for op in prefix:
                if isinstance(op, (GeometryEdit, Closure)):
                    for record in (*getattr(op, "ancestry", ()), *op.lineage):
                        records[record.id] = record
            records.update({r.id: r for r in (*geometry.ancestry, *geometry.lineage)})
            live = {r.id for r in geometry.lineage}
            baseline.append(
                replace(
                    geometry,
                    ancestry=tuple(r for i, r in records.items() if i not in live),
                    raster=None,
                )
            )
        self.operations[:] = [*baseline, *self.operations[cut:]]
        self.history_floor = len(baseline)

    def undo(self):
        if len(self.operations) > self.history_floor:
            self.future.append(self.operations.pop())

    def redo(self):
        if self.future:
            self.operations.append(self.future.pop())
