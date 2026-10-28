"""Superseded derived work never publishes pixels, dimensions or late failures."""

from types import SimpleNamespace

import pytest
from PIL import Image
from test_raster_aids import window as window

from dale.bounds_preview import BoundsPreview, BoundsResult
from dale.raster import ExportCancelled, render_export_alpha


def test_alpha_cancellation_stops_inside_a_wide_stripe(monkeypatch):
    import dale.raster as raster

    tiles = []
    original = raster._alpha_tile

    def tile(*args):
        tiles.append(args[3])
        return original(*args)

    monkeypatch.setattr(raster, "_alpha_tile", tile)
    with pytest.raises(ExportCancelled):
        render_export_alpha((4096, 128), (4096, 128), (), cancelled=lambda: bool(tiles))
    assert tiles == [0]
    expected = Image.new("L", (4096, 128), 255)
    assert render_export_alpha(expected.size, expected.size, ()).tobytes() == expected.tobytes()


@pytest.mark.parametrize("error", ["", "Obsolete failure"])
def test_cancelled_bounds_never_publish_even_when_the_key_matches(window, error):
    controller = BoundsPreview(window)
    emitted, deleted = [], []
    controller.changed.connect(lambda: emitted.append(True))
    controller.current_key = ("same-input",)
    worker = SimpleNamespace(
        key=controller.current_key,
        result=BoundsResult(((1, 2, 3, 4),), error),
        session=object(),
        polygons=(object(),),
        isInterruptionRequested=lambda: True,
        deleteLater=lambda: deleted.append(True),
    )
    controller.worker = worker
    controller._finished(worker)
    assert not controller.cache and not emitted and deleted
    assert worker.result is worker.session is worker.polygons is None


def test_cancelled_native_result_cannot_disable_or_replace_current_preview(window, monkeypatch):
    controller = window.view.native_preview
    controller.enabled = True
    controller.base = ("same-image", (20, 20), 1, ())
    monkeypatch.setattr(controller, "current_base", lambda: controller.base)
    failures, published = [], []
    controller.failed.connect(failures.append)
    monkeypatch.setattr(controller, "publish", lambda *args: published.append(args))
    worker = SimpleNamespace(
        base=controller.base,
        decoded=None,
        frames={(0, 0): (20, 20, bytes(1600))},
        error="Obsolete failure",
        isInterruptionRequested=lambda: True,
        deleteLater=lambda: None,
    )
    controller.worker = worker
    controller.finished(worker)
    assert controller.enabled and not failures and not published and not controller.cache
    assert worker.frames == {} and controller.worker is None
