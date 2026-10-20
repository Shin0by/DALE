"""Exact square-grid placement in the existing source-image coordinate frame."""

import math
from dataclasses import dataclass

from dale.scene import MAX_SIDE


@dataclass(frozen=True)
class ExportGrid:
    cell: tuple[int, int]
    origin: tuple[int, int]
    scene_cell: float

    def enclose(self, bounds):
        """Expand exact nonzero-alpha bounds to whole cells without resampling."""
        result = []
        for i, value in enumerate(bounds):
            axis = i % 2
            start, step = self.origin[axis], self.cell[axis]
            count = (value - start) // step if i < 2 else -((start - value) // step)
            result.append(start + count * step)
        return tuple(result)


def export_grid(session, cell_size=None):
    """Use the declared or explicit square scene grid in source-image coordinates."""
    source = session.source
    raw = source.raw
    grid = raw.get("grid")
    size = (
        cell_size if cell_size is not None else grid.get("size") if isinstance(grid, dict) else grid
    )
    kind = grid.get("type", 1) if isinstance(grid, dict) else raw.get("gridType", 1)
    if type(size) not in (int, float) or not 0 < size <= 1_000_000_000:
        raise ValueError("Size to grid requires a scene JSON with a valid grid size.")
    if cell_size is None and (type(kind) is not int or kind != 1):
        raise ValueError("Size to grid requires a square scene grid.")
    if any(raw.get(key, 0) != 0 for key in ("shiftX", "shiftY")):
        raise ValueError("Size to grid does not support nonzero legacy scene shifts.")
    cell, origin = [], []
    for axis in (0, 1):
        ratio = source.size[axis] / source.scene_size[axis]
        step = size * ratio
        phase = -(session.origin[axis] + source.background_offset[axis]) * ratio
        if any(not math.isfinite(v) or abs(v - round(v)) > 1e-7 for v in (step, phase)):
            raise ValueError(
                "Grid boundaries fall between source pixels; exact grid padding is unavailable."
            )
        if not 1 <= round(step) <= MAX_SIDE:
            raise ValueError("Grid cell size is outside the supported source-pixel range.")
        cell.append(round(step))
        origin.append(round(phase) % round(step))
    return ExportGrid(tuple(cell), tuple(origin), float(size))
