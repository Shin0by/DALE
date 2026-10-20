"""Exact PNG sidebar bounds without blocking scene editing on large images."""

from collections import OrderedDict
from dataclasses import dataclass

from PySide6.QtCore import QObject, QThread, Signal

from dale.export_grid import export_grid
from dale.overlay_export import prepare_overlay
from dale.raster import ExportCancelled, raster_operations
from dale.session import Session

INLINE_PIXEL_LIMIT = 262_144


@dataclass(frozen=True)
class BoundsResult:
    bounds: tuple
    error: str = ""


def calculate_bounds(session, polygons, cancelled=None, *, size_to_grid=False, grid_size=None):
    if size_to_grid:
        export_grid(session, grid_size)
    bounds = []
    for polygon in polygons:
        if cancelled and cancelled():
            raise ExportCancelled("PNG bounds calculation cancelled.")
        try:
            result, _, _ = prepare_overlay(
                session, polygon, cancelled, size_to_grid=size_to_grid, grid_size=grid_size
            )
            if result is not None:
                bounds.append(result)
        except ValueError:
            continue  # A selected region can lie completely outside the scene image.
    if cancelled and cancelled():
        raise ExportCancelled("PNG bounds calculation cancelled.")
    return BoundsResult(tuple(bounds))


class BoundsWorker(QThread):
    def __init__(self, key, session, polygons, parent, size_to_grid=False, grid_size=None):
        super().__init__(parent)
        self.key, self.session, self.polygons = key, session, polygons
        self.size_to_grid = size_to_grid
        self.grid_size = grid_size
        self.result = None

    def run(self):
        try:
            self.result = calculate_bounds(
                self.session,
                self.polygons,
                self.isInterruptionRequested,
                size_to_grid=self.size_to_grid,
                grid_size=self.grid_size,
            )
        except ExportCancelled:
            pass
        except Exception as exc:
            self.result = BoundsResult((), str(exc))


class BoundsPreview(QObject):
    """One worker, latest request wins, bounded cache, stripe-level cancellation."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cache = OrderedDict()
        self.worker = None
        self.pending = None
        self.current_key = None
        self.closed = False

    def request(self, session, polygons, *, size_to_grid=False, grid_size=None):
        polygons = tuple(polygons)
        if not polygons:
            self.clear()
            return BoundsResult(())
        raster = raster_operations(session.operations, session.contour_offset)
        try:
            grid = export_grid(session, grid_size) if size_to_grid else None
        except ValueError as exc:
            self.clear()
            return BoundsResult((), str(exc))
        key = (
            grid,
            session.source.image_path,
            session.source.size,
            session.analysis().area.wkb,
            session.contour_offset,
            raster,
            tuple(p.wkb for p in polygons),
        )
        self.current_key = key
        if key in self.cache:
            self.cache.move_to_end(key)
            self.pending = None
            if self.worker and self.worker.key != key:
                self.worker.requestInterruption()
            return self.cache[key]
        if self.closed:
            return BoundsResult(())
        if self.worker and self.worker.key == key and not self.worker.isInterruptionRequested():
            return None
        # The worker never reads the mutable live history or any source image file.
        snapshot = Session(
            session.source,
            session.origin,
            list(session.operations),
            gap_tolerance=session.gap_tolerance,
            contour_offset=session.contour_offset,
        )
        pixels = sum(
            min(session.source.size[0], max(0, p.bounds[2] - p.bounds[0] + 6))
            * min(session.source.size[1], max(0, p.bounds[3] - p.bounds[1] + 6))
            for p in polygons
        )
        if pixels <= INLINE_PIXEL_LIMIT:
            self.pending = None
            if self.worker:
                self.worker.requestInterruption()
            try:
                result = calculate_bounds(
                    snapshot, polygons, size_to_grid=size_to_grid, grid_size=grid_size
                )
            except Exception as exc:
                result = BoundsResult((), str(exc))
            self._remember(key, result)
            return result
        self.pending = key, snapshot, polygons
        if self.worker:
            self.worker.requestInterruption()
        else:
            self._start_pending()
        return None

    def _remember(self, key, result):
        self.cache[key] = result
        self.cache.move_to_end(key)
        while len(self.cache) > 16:
            self.cache.popitem(last=False)

    def _start_pending(self):
        if self.closed or self.pending is None or self.worker is not None:
            return
        key, session, polygons = self.pending
        self.pending = None
        worker = BoundsWorker(
            key,
            session,
            polygons,
            self,
            size_to_grid=key[0] is not None,
            grid_size=key[0].scene_cell if key[0] is not None else None,
        )
        self.worker = worker
        worker.finished.connect(lambda: self._finished(worker))
        worker.start()

    def _finished(self, worker):
        if self.worker is not worker:
            return
        self.worker = None
        if not self.closed and worker.result is not None:
            self._remember(worker.key, worker.result)
            if worker.key == self.current_key:
                self.changed.emit()
        worker.deleteLater()
        self._start_pending()

    def clear(self):
        self.current_key = self.pending = None
        if self.worker:
            self.worker.requestInterruption()

    def shutdown(self):
        self.closed = True
        self.clear()
        if self.worker:
            worker = self.worker
            worker.wait()
            self.worker = None
            worker.deleteLater()
