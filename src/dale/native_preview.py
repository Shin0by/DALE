"""Latest-only native Raster tiles with one cancellable worker and bounded cache."""

import math
from collections import OrderedDict

from PIL import Image, ImageChops
from PySide6.QtCore import QEvent, QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap, QTransform

from dale.native_cache import clean_stale_cache
from dale.native_image import NativeImageSource
from dale.raster import render_export_alpha
from dale.session import RasterTransform

TILE = 512
MAX_BATCH_TILES = 32


class NativeTileWorker(QThread):
    def __init__(self, source, operations, base, tiles, decoded, parent):
        super().__init__(parent)
        self.source, self.operations, self.base = source, operations, base
        self.tiles, self.decoded = tiles, decoded
        self.frames = {}
        self.error = ""

    def run(self):
        try:
            if self.decoded is None:
                self.decoded = NativeImageSource(self.source, self.isInterruptionRequested)
            factor = self.base[2]
            for x, y in self.tiles:
                if self.isInterruptionRequested():
                    return
                width, height = (
                    min(TILE * factor, self.source.size[0] - x),
                    min(TILE * factor, self.source.size[1] - y),
                )
                size = math.ceil(width / factor), math.ceil(height / factor)
                if any(isinstance(op, RasterTransform) for op in self.operations):
                    from dale.raster_transform import crop_reader, render_layered

                    image = render_layered(
                        crop_reader(self.decoded, self.source.size),
                        self.source.size,
                        self.operations,
                        (x, y, x + width, y + height),
                        size,
                        self.isInterruptionRequested,
                    )
                    self.frames[(x, y)] = *size, image.tobytes()
                    continue
                image = self.decoded.crop((x, y, x + width, y + height))
                if image.size != size:
                    image = image.resize(size, Image.Resampling.LANCZOS)
                alpha = render_export_alpha(
                    size,
                    self.source.size,
                    self.operations,
                    top=y / factor,
                    left=x / factor,
                    scale=(1 / factor, 1 / factor),
                )
                image.putalpha(ImageChops.multiply(image.getchannel("A"), alpha))
                self.frames[(x, y)] = *size, image.tobytes()
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.error = str(exc)


class NativeRasterPreview(QObject):
    failed = Signal(str)

    def __init__(self, view):
        super().__init__(view)
        self.view, self.viewport = view, view.viewport()
        self.enabled = self.closed = False
        self.worker = self.decoded = self.base = None
        self.items = {}
        self.cache = OrderedDict()
        self.pending = None
        self.wanted = ()
        self.wanted_view = self.covered_view = None
        try:
            clean_stale_cache()
        except OSError:
            pass
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(35)
        self.timer.timeout.connect(self.request)
        self.viewport.installEventFilter(self)
        view.destroyed.connect(lambda: setattr(self, "closed", True))
        view.horizontalScrollBar().valueChanged.connect(self.schedule)
        view.verticalScrollBar().valueChanged.connect(self.schedule)

    def set_enabled(self, enabled):
        changed = self.enabled != enabled
        self.enabled = enabled
        if changed:
            self.fallback()
        if enabled:
            self.schedule()
        elif changed:
            self.timer.stop()
            self.pending = None
            if self.worker:
                self.worker.requestInterruption()
            else:
                self.release_decoded()

    def release_decoded(self):
        if self.decoded is not None and not (self.worker and self.worker.decoded is self.decoded):
            self.decoded.close()
        self.decoded = None

    def fallback(self):
        self.covered_view = None
        for item in self.items.values():
            item.hide()
        if self.view.item is not None:
            self.view.item.show()

    def invalidate(self):
        self.fallback()
        self.schedule()

    def current_base(self):
        if self.view.session is None:
            return None
        source = self.view.session.source
        return (
            source.image_path,
            source.size,
            max(
                1,
                2 ** max(0, math.floor(math.log2(1 / max(1e-9, abs(self.view.transform().m11()))))),
            ),
            self.view.preview_raster_operations(),
        )

    def activate(self):
        complete = (
            self.enabled
            and self.wanted
            and self.base == self.current_base()
            and self.wanted_view == self.viewport_state()
            and all(tile in self.items for tile in self.wanted)
        )
        for item in self.items.values():
            item.setVisible(bool(complete))
        if self.view.item is not None:
            self.view.item.setVisible(not complete)
        self.covered_view = self.wanted_view if complete else None

    def viewport_state(self):
        return self.view.viewportTransform(), self.viewport.size()

    def schedule(self, *args):
        if self.enabled and not self.closed and not self.timer.isActive():
            self.timer.start()
        if self.covered_view is not None and self.covered_view != self.viewport_state():
            self.fallback()

    def eventFilter(self, watched, event):
        if (
            not self.closed
            and self.enabled
            and event.type() in (QEvent.Type.Paint, QEvent.Type.Resize)
        ):
            self.schedule()
        return False

    def remove_items(self):
        for item in self.items.values():
            self.view.scene().removeItem(item)
        self.items.clear()

    def request(self):
        view = self.view
        if self.closed or not self.enabled or view.session is None or view.preview is None:
            return
        source = view.session.source
        # Below the preview's sampling scale it already has at least one image
        # sample per screen pixel. Keep that lightweight overview for navigation.
        zoom = abs(view.transform().m11())
        threshold = min(view.preview.width / source.size[0], view.preview.height / source.size[1])
        if zoom <= threshold:
            self.fallback()
            self.wanted = ()
            self.pending = None
            if self.worker:
                self.worker.requestInterruption()
            return
        base = self.current_base()
        operations = base[-1]
        if base != self.base:
            old_source = self.base[:2] if self.base else None
            self.fallback()
            self.remove_items()
            self.cache.clear()
            if old_source != base[:2]:
                self.release_decoded()
            self.base = base
        rect = view.mapToScene(self.viewport.rect()).boundingRect().intersected(view.image_rect)
        self.wanted_view = self.viewport_state()
        tiles = []
        span = TILE * base[2]
        if not rect.isEmpty():
            for y in range(
                max(0, math.floor(rect.top() / span)) * span,
                min(source.size[1], math.ceil(rect.bottom() / span) * span),
                span,
            ):
                for x in range(
                    max(0, math.floor(rect.left() / span)) * span,
                    min(source.size[0], math.ceil(rect.right() / span) * span),
                    span,
                ):
                    tiles.append((x, y))
        self.wanted = tuple(tiles)
        for tile in tuple(self.items):
            if tile not in self.wanted:
                self.view.scene().removeItem(self.items.pop(tile))
        missing = []
        for tile in self.wanted:
            if tile in self.items:
                continue
            elif tile in self.cache:
                self.publish(tile, self.cache[tile])
            else:
                missing.append(tile)
        self.pending = (
            (source, operations, base, tuple(missing[:MAX_BATCH_TILES])) if missing else None
        )
        if self.worker:
            if self.worker.base != base or not set(self.worker.tiles).intersection(missing):
                self.worker.requestInterruption()
        else:
            self.start_pending()
        self.activate()

    def start_pending(self):
        if self.closed or not self.enabled or self.worker or self.pending is None:
            return
        source, operations, base, tiles = self.pending
        self.pending = None
        worker = NativeTileWorker(source, operations, base, tiles, self.decoded, self)
        self.worker = worker
        worker.finished.connect(lambda: self.finished(worker))
        worker.start()

    def publish(self, tile, frame):
        width, height, data = frame
        image = QImage(data, width, height, width * 4, QImage.Format.Format_RGBA8888).copy()
        item = self.view.scene().addPixmap(QPixmap.fromImage(image))
        item.setPos(*tile)
        factor = self.base[2]
        item.setTransform(
            QTransform.fromScale(
                min(TILE * factor, self.base[1][0] - tile[0]) / width,
                min(TILE * factor, self.base[1][1] - tile[1]) / height,
            )
        )
        item.setZValue(1)
        item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        item.hide()
        self.items[tile] = item

    def finished(self, worker):
        if self.worker is not worker:
            return
        self.worker = None
        current = self.current_base()
        if (
            self.enabled
            and not self.closed
            and worker.decoded is not None
            and current is not None
            and worker.base[:2] == current[:2]
            and self.decoded is None
        ):
            self.decoded = worker.decoded
        if self.enabled and not self.closed and worker.base == self.base == self.current_base():
            self.decoded = worker.decoded
            for tile, frame in worker.frames.items():
                self.cache[tile] = frame
                self.cache.move_to_end(tile)
                if tile in self.wanted and tile not in self.items:
                    self.publish(tile, frame)
            while len(self.cache) > 64:
                self.cache.popitem(last=False)
            if worker.error:
                self.enabled = False
                self.remove_items()
                self.release_decoded()
                self.failed.emit(worker.error)
            else:
                self.activate()
                self.schedule()
        if worker.decoded is not self.decoded and worker.decoded is not None:
            worker.decoded.close()
        if not self.enabled:
            self.release_decoded()
        worker.decoded = None
        worker.frames = {}
        worker.deleteLater()
        self.schedule()

    def clear(self):
        self.fallback()
        self.enabled = False
        self.timer.stop()
        self.pending = None
        if self.worker:
            worker = self.worker
            worker.requestInterruption()
            worker.wait()
            if worker.decoded is not self.decoded and worker.decoded is not None:
                worker.decoded.close()
            worker.decoded = None
            worker.frames = {}
            self.worker = None
            worker.deleteLater()
        self.remove_items()
        self.cache.clear()
        self.release_decoded()
        self.base = None
        self.wanted = ()
        self.wanted_view = self.covered_view = None
        try:
            clean_stale_cache()
        except OSError:
            pass

    def shutdown(self):
        self.clear()
        self.closed = True
        self.viewport.removeEventFilter(self)
