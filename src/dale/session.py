"""Vector editing history: mask snapshots, local closures, and brush strokes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from dale.geometry import analyze_regions, offset_region
from dale.scene import Point, SceneInput


@dataclass(frozen=True)
class Closure:
    points: tuple[Point, ...]


@dataclass(frozen=True)
class Stroke:
    points: tuple[Point, ...]
    radius: float
    restore: bool = False


@dataclass(frozen=True)
class ContourMask:
    area: object
    mode: Literal["outside", "inside"]


@dataclass(frozen=True)
class GeometryEdit:
    walls: tuple
    closures: tuple[tuple[Point, ...], ...] = ()


Operation = Closure | Stroke | ContourMask | GeometryEdit


@dataclass
class Session:
    source: SceneInput
    origin: Point = (0.0, 0.0)
    operations: list[Operation] = field(default_factory=list)
    future: list[Operation] = field(default_factory=list)
    gap_tolerance: float = 0.0
    contour_offset: float = 0.0

    @property
    def walls(self):
        return self.geometry().walls

    @property
    def closures(self):
        return self.geometry().closures

    def geometry(self) -> GeometryEdit:
        walls = self.source.image_walls(self.origin)
        closures = []
        for operation in self.operations:
            if isinstance(operation, Closure):
                closures.append(operation.points)
            elif isinstance(operation, GeometryEdit):
                walls, closures = operation.walls, list(operation.closures)
        return GeometryEdit(walls, tuple(closures))

    def analysis(self):
        return analyze_regions(self.walls, self.closures, self.gap_tolerance)

    def make_mask(self, mode: Literal["outside", "inside"]):
        return ContourMask(offset_region(self.analysis().area, self.contour_offset), mode)

    def add(self, operation: Operation):
        self.operations.append(operation)
        self.future.clear()

    def undo(self):
        if self.operations:
            self.future.append(self.operations.pop())

    def redo(self):
        if self.future:
            self.operations.append(self.future.pop())
