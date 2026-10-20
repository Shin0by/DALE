"""Grid-aligned PNG bounds preserve exact native pixels and scene placement."""

import json

import pytest
from PIL import Image
from shapely.geometry import box

from dale.bounds_preview import BoundsPreview
from dale.export_grid import export_grid
from dale.overlay_export import export_overlays, prepare_overlay
from dale.session import Session, Stroke


def rectangle(polygon):
    points = list(polygon.exterior.coords)
    return [{"c": [*a, *b]} for a, b in zip(points[:-1], points[1:], strict=True)]


@pytest.mark.parametrize("grid", [100, {"size": 100, "type": 1}])
@pytest.mark.parametrize("offset", [-4, 0, 7])
@pytest.mark.parametrize("rgba", [False, True])
def test_grid_export_preserves_every_pixel_after_offset_masks_and_brushes(
    pair_factory, tmp_path, grid, offset, rgba
):
    source = pair_factory(size=(230, 170), grid=grid, walls=rectangle(box(4, 5, 222, 161)))
    if rgba:
        with Image.open(source.image_path) as image:
            pixels = image.convert("RGBA")
        pixels.putpixel((120, 80), (25, 50, 75, 1))
        pixels.save(source.image_path, format="PNG")
    before = source.image_path.read_bytes(), source.json_path.read_bytes()
    session = Session(source, contour_offset=offset)
    session.add(session.make_mask("outside"))
    session.add(Stroke(((50, 80),), 11))
    geometry, history = session.geometry(), tuple(session.operations)
    tight_folder = export_overlays(session, tmp_path)
    padded_folder = export_overlays(session, tmp_path, size_to_grid=True)
    manifest = json.loads(next(padded_folder.glob("*-placement.json")).read_text())
    tight = json.loads(next(tight_folder.glob("*-placement.json")).read_text())["items"][0]
    item = manifest["items"][0]
    assert manifest["grid"]["cell_pixels"] == [100, 100]
    assert (item["x"], item["y"], item["width"], item["height"]) == (0, 0, 300, 200)
    assert item["content_bounds"] == tight["content_bounds"]
    with (
        Image.open(tight_folder / tight["file"]) as original,
        Image.open(padded_folder / item["file"]) as padded,
    ):
        assert padded.mode == "RGBA" and padded.size == (300, 200)
        assert item["file"].endswith("-300x200px.png")
        assert padded.crop(tuple(tight["content_bounds"])).tobytes() == original.tobytes()
        assert padded.getpixel((120, 80))[3] == (1 if rgba else 255)
        assert padded.getpixel((50, 80))[3] == 0
        assert padded.getpixel((230, 80)) == (0, 0, 0, 0)
        assert padded.getpixel((120, 170)) == (0, 0, 0, 0)
        assert padded.getchannel("A").getbbox() == tuple(item["content_bounds"])
    assert before == (source.image_path.read_bytes(), source.json_path.read_bytes())
    assert session.geometry() == geometry and tuple(session.operations) == history


def test_scaled_offset_frame_uses_grid_phase_and_negative_transparent_padding(
    pair_factory, tmp_path
):
    source = pair_factory(
        size=(200, 120),
        width=400,
        height=360,
        grid={"size": 60, "type": 1},
        background={"offsetX": 14, "offsetY": -12},
        padding=0.25,
        walls=rectangle(box(20, 20, 190, 160)),
    )
    session = Session(source, origin=(6, 3), contour_offset=5)
    frame = export_grid(session)
    assert frame.cell == (30, 20) and frame.origin == (20, 3)
    polygon = box(0, 0, 80, 45)
    bounds, _, content = prepare_overlay(session, polygon, size_to_grid=True)
    assert bounds == (-10, -17, 110, 63) and content == (0, 0, 81, 46)
    folder = export_overlays(session, tmp_path, selected_polygons=(polygon,), size_to_grid=True)
    item = json.loads(next(folder.glob("*-placement.json")).read_text())["items"][0]
    assert item["scene_x"] % 60 == item["scene_y"] % 60 == 0
    assert item["scene_width"] % 60 == item["scene_height"] % 60 == 0
    assert (item["scene_x"] + item["scene_width"]) % 60 == 0
    assert (item["scene_y"] + item["scene_height"]) % 60 == 0
    with Image.open(folder / item["file"]) as image:
        assert image.getpixel((0, 20)) == (0, 0, 0, 0)
        assert image.getpixel((20, 0)) == (0, 0, 0, 0)


@pytest.mark.parametrize(
    "grid",
    [
        None,
        False,
        0,
        -1,
        "100",
        {"size": 100, "type": 0},
        {"size": 100, "type": 2},
        {"size": 2.5},
        {"size": 100, "type": True},
    ],
)
def test_no_fallback_or_misleading_output_for_unusable_grid(pair_factory, tmp_path, grid):
    session = Session(pair_factory(grid=grid))
    with pytest.raises(ValueError):
        export_overlays(session, tmp_path, size_to_grid=True)
    assert not list(tmp_path.glob("*-overlays*"))
    # The explicit drawing fallback and ordinary native crop remain available.
    export_overlays(session, tmp_path)


def test_grid_sidebar_cache_and_export_share_exact_expanded_bounds(pair_factory):
    session = Session(
        pair_factory(size=(200, 200), grid=50, walls=rectangle(box(50, 50, 100, 100)))
    )
    polygon = box(50, 50, 100, 100)
    preview = BoundsPreview()
    tight = preview.request(session, (polygon,))
    aligned = preview.request(session, (polygon,), size_to_grid=True)
    assert tight.bounds == ((49, 49, 101, 101),)
    assert aligned.bounds == ((0, 0, 150, 150),)
    assert preview.request(session, (polygon,)) == tight
    assert preview.request(session, (polygon,), size_to_grid=True) == aligned
    assert len(preview.cache) == 2
    preview.shutdown()


def test_grid_padding_follows_alpha_after_erasing_not_raw_polygon_bounds(pair_factory):
    session = Session(pair_factory(size=(300, 200), grid=50))
    session.add(Stroke(((50, 10), (50, 190)), 100))
    polygon = box(50, 50, 200, 140)
    tight, _, _ = prepare_overlay(session, polygon)
    bounds, _, content = prepare_overlay(session, polygon, size_to_grid=True)
    assert content == tight and tight[0] >= 100
    assert bounds == export_grid(session).enclose(tight)


@pytest.mark.parametrize("cell", [25, 75, 120])
def test_custom_grid_recalculates_exact_bounds_and_png_without_changing_sources(
    pair_factory, tmp_path, cell
):
    source = pair_factory(size=(230, 170), grid=100)
    session = Session(source, contour_offset=7)
    polygon = box(18, 24, 212, 153)
    before = source.json_path.read_bytes(), source.image_path.read_bytes()
    tight, _, _ = prepare_overlay(session, polygon)
    expected = export_grid(session, cell).enclose(tight)
    preview = BoundsPreview()
    result = preview.request(session, (polygon,), size_to_grid=True, grid_size=cell)
    assert result.bounds == (expected,)
    folder = export_overlays(
        session, tmp_path, selected_polygons=(polygon,), size_to_grid=True, grid_size=cell
    )
    manifest = json.loads(next(folder.glob("*-placement.json")).read_text())
    item = manifest["items"][0]
    assert manifest["grid"]["cell_pixels"] == [cell, cell]
    assert (item["x"], item["y"], item["width"], item["height"]) == (
        expected[0],
        expected[1],
        expected[2] - expected[0],
        expected[3] - expected[1],
    )
    with Image.open(folder / item["file"]) as image:
        assert image.width % cell == image.height % cell == 0
        assert image.getpixel((expected[2] - expected[0] - 1, image.height - 1))[3] == 0
    assert before == (source.json_path.read_bytes(), source.image_path.read_bytes())
    preview.shutdown()


def test_custom_scene_grid_keeps_scaled_offset_origin(pair_factory):
    source = pair_factory(
        size=(200, 120),
        width=400,
        height=360,
        grid=60,
        background={"offsetX": 14, "offsetY": -12},
        padding=0.25,
    )
    session = Session(source, origin=(6, 3))
    frame = export_grid(session, 120)
    assert frame.cell == (60, 40) and frame.origin == (50, 3)
    assert frame.enclose((0, 0, 81, 46)) == (-10, -37, 110, 83)


@pytest.fixture(scope="session")
def grid_app():
    from PySide6.QtWidgets import QApplication

    from dale.ui import configure_application

    app = QApplication.instance() or QApplication([])
    if not app.property("catalog_test_style"):
        configure_application(app)
        app.setProperty("catalog_test_style", True)
    return app


def test_background_bounds_worker_uses_latest_custom_cell_size(pair_factory, grid_app):
    import time

    from PySide6.QtCore import QEvent, QThread

    app = grid_app
    session = Session(pair_factory(size=(800, 800), grid=100))
    polygon = box(17, 19, 719, 723)
    preview = BoundsPreview()
    assert preview.request(session, (polygon,), size_to_grid=True, grid_size=75) is None
    assert preview.request(session, (polygon,), size_to_grid=True, grid_size=120) is None
    deadline = time.monotonic() + 15
    result = None
    while result is None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
        result = preview.request(session, (polygon,), size_to_grid=True, grid_size=120)
    assert result is not None and not result.error
    expected, _, _ = prepare_overlay(session, polygon, size_to_grid=True, grid_size=120)
    assert result.bounds == (expected,)
    preview.shutdown()
    for worker in preview.findChildren(QThread):
        worker.wait()
    preview.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()
