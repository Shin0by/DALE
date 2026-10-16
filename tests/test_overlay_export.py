import json

import pytest
from PIL import Image
from shapely.geometry import Polygon

from dale.overlay_export import export_overlays
from dale.placement import Placement
from dale.raster import ExportCancelled, render_export_alpha
from dale.session import ContourMask, Session, Stroke


def _rectangle(x, y, width, height):
    return [
        {"c": [*a, *b]}
        for a, b in [
            ((x, y), (x + width, y)),
            ((x + width, y), (x + width, y + height)),
            ((x + width, y + height), (x, y + height)),
            ((x, y + height), (x, y)),
        ]
    ]


def test_separate_contours_have_no_implicit_margin(pair_factory, tmp_path):
    source = pair_factory(
        size=(200, 200), walls=_rectangle(10, 20, 20, 30) + _rectangle(100, 120, 40, 50)
    )
    session = Session(source)
    session.add(session.make_mask("outside"))
    before = source.image_path.read_bytes(), source.json_path.read_bytes()
    folder = export_overlays(session, tmp_path, Placement(14, 17))
    manifest = json.loads((folder / "placement.json").read_text())
    assert len(manifest["items"]) == 2
    first, second = manifest["items"]
    assert (first["x"], first["y"], first["width"], first["height"]) == (9, 19, 22, 32)
    assert (second["x"], second["y"], second["width"], second["height"]) == (99, 119, 42, 52)
    assert "edge_guard_px" not in manifest
    assert "extra_padding_px" not in manifest
    with Image.open(folder / first["file"]) as image:
        assert image.size == (22, 32)
        assert 0 < image.getpixel((0, 10))[3] < 255  # Minimal bicubic edge coverage.
        assert image.getchannel("A").getbbox() == (0, 0, 22, 32)  # No transparent border.
        assert image.info["DALE.SourceX"] == "9"
        assert "DALE.EdgeGuardPixels" not in image.info
    assert before == (source.image_path.read_bytes(), source.json_path.read_bytes())


def test_artwork_margin_is_clipped_to_source_image_bounds(pair_factory, tmp_path):
    source = pair_factory(size=(80, 80), walls=_rectangle(0, 0, 30, 30))
    folder = export_overlays(Session(source, contour_offset=10), tmp_path, Placement())
    item = json.loads((folder / "placement.json").read_text())["items"][0]
    assert (item["x"], item["y"]) == (0, 0)
    with Image.open(folder / item["file"]) as image:
        assert image.getpixel((0, 0))[3] == 255
        assert image.size == (41, 41)


def test_brush_edits_remain_in_cropped_result(pair_factory, tmp_path):
    source = pair_factory(size=(80, 80), walls=_rectangle(10, 10, 40, 40))
    session = Session(source, contour_offset=2)
    session.add(session.make_mask("outside"))
    session.add(Stroke(((30, 30),), 3))
    folder = export_overlays(session, tmp_path, Placement(13, 5))
    item = json.loads((folder / "placement.json").read_text())["items"][0]
    assert item["x"] == 7  # Offset 2, plus actual bicubic coverage; no fixed guard.
    with Image.open(folder / item["file"]) as image:
        assert image.getpixel((30 - item["x"], 30 - item["y"]))[3] == 0
        assert image.info["DALE.FoundryMajor"] == "13"


def test_cancelled_set_leaves_no_partial_directory(pair_factory, tmp_path):
    session = Session(pair_factory())
    with pytest.raises(ExportCancelled):
        export_overlays(session, tmp_path, Placement(), cancelled=lambda: True)
    assert not list(tmp_path.glob(".dale-export-*"))
    assert not list(tmp_path.glob("*-overlays*"))


def test_selected_region_uses_the_same_bounds_as_the_information_panel(pair_factory, tmp_path):
    source = pair_factory(
        size=(200, 200), walls=_rectangle(10, 20, 20, 30) + _rectangle(100, 120, 40, 50)
    )
    folder = export_overlays(Session(source), tmp_path, Placement(), region_index=1)
    manifest = json.loads((folder / "placement.json").read_text())
    assert manifest["selected_region"] == 1
    assert len(manifest["items"]) == 1
    item = manifest["items"][0]
    assert (item["x"], item["y"], item["width"], item["height"]) == (99, 119, 42, 52)


def test_selected_adjacent_cells_get_tight_alpha_bounds_clipped_to_jpg(pair_factory, tmp_path):
    source = pair_factory(
        size=(200, 100), walls=_rectangle(0, 0, 199, 99) + [{"c": [100, 0, 100, 99]}]
    )
    session = Session(source)
    folder = export_overlays(
        session,
        tmp_path,
        Placement(),
        region_indices=(0, 1),
        individual_regions=True,
    )
    manifest = json.loads((folder / "placement.json").read_text())
    assert manifest["selected_regions"] == [0, 1]
    assert manifest["region_mode"] == "faces"
    first, second = manifest["items"]
    assert (first["x"], first["y"], first["width"], first["height"]) == (0, 0, 101, 100)
    assert (second["x"], second["y"], second["width"], second["height"]) == (99, 0, 101, 100)
    for item in manifest["items"]:
        with Image.open(folder / item["file"]) as image:
            assert image.size == (101, 100)
            assert image.getchannel("A").getbbox() == (0, 0, *image.size)
            assert image.info["DALE.AlphaAntialiasing"] == "bicubic-2x"
    with Image.open(folder / manifest["items"][0]["file"]) as image:
        assert image.getpixel((30, 50))[3] == 255
        assert 0 < image.getpixel((100, 50))[3] < 255
    with Image.open(folder / manifest["items"][1]["file"]) as image:
        assert 0 < image.getpixel((0, 50))[3] < 255
        assert image.getpixel((50, 50))[3] == 255


@pytest.mark.parametrize("individual", [False, True])
@pytest.mark.parametrize("apply_mask", [False, True])
def test_300_pixel_artwork_offset_preserves_brush_history_and_every_alpha_edge(
    pair_factory, tmp_path, individual, apply_mask
):
    source = pair_factory(size=(1000, 1000), walls=_rectangle(400, 400, 100, 100))
    session = Session(source)
    if apply_mask:
        session.add(session.make_mask("outside"))
    session.contour_offset = 300  # Live export offset, even after an earlier mask snapshot.
    session.add(Stroke(((200, 450),), 3))
    folder = export_overlays(
        session,
        tmp_path,
        Placement(),
        individual_regions=individual,
        region_indices=(0,) if individual else None,
    )
    item = json.loads((folder / "placement.json").read_text())["items"][0]
    assert (item["x"], item["y"], item["width"], item["height"]) == (99, 99, 702, 702)
    assert item["content_bounds"] == [99, 99, 801, 801]
    with Image.open(folder / item["file"]) as image, Image.open(source.image_path) as jpg:
        # The previous exporter made this margin transparent despite the larger box.
        assert image.getpixel((51, 351)) == (*jpg.getpixel((150, 450)), 255)
        assert image.getpixel((101, 351))[3] == 0  # Eraser remains in the expanded artwork.
        alpha = image.getchannel("A")
        assert alpha.getbbox() == (0, 0, 702, 702)
        assert 0 < image.getpixel((0, 351))[3] < 255  # Faint edge is retained.


def test_bounds_follow_actual_pixels_after_erasing_edges(pair_factory, tmp_path):
    source = pair_factory(size=(200, 200), walls=_rectangle(50, 50, 100, 100))
    session = Session(source, contour_offset=10)
    session.add(Stroke(((40, 30), (40, 170)), 20))
    folder = export_overlays(session, tmp_path, Placement())
    item = json.loads((folder / "placement.json").read_text())["items"][0]
    # The eraser removes the original left artwork edge at 40 through x=60 inclusive.
    assert item["content_bounds"] == [60, 39, 161, 161]  # Includes bicubic edge alpha.
    assert (item["x"], item["y"], item["width"], item["height"]) == (60, 39, 101, 122)
    with Image.open(folder / item["file"]) as image:
        assert image.getchannel("A").getbbox() == (0, 0, 101, 122)


def test_fully_erased_region_does_not_create_empty_output(pair_factory, tmp_path):
    session = Session(pair_factory(size=(200, 200), walls=_rectangle(50, 50, 20, 20)))
    session.add(Stroke(((60, 60),), 100))
    with pytest.raises(ValueError, match="transparent"):
        export_overlays(session, tmp_path, Placement())
    assert not list(tmp_path.glob("*-overlays*"))


def test_cancel_during_alpha_bounds_leaves_no_output(pair_factory, tmp_path):
    session = Session(pair_factory(size=(1000, 1000), walls=_rectangle(50, 50, 500, 500)))
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        return calls >= 3

    with pytest.raises(ExportCancelled):
        export_overlays(session, tmp_path, Placement(), cancelled=cancel)
    assert not list(tmp_path.glob("*-overlays*"))


def test_tight_crop_preserves_every_faint_pixel_from_full_canvas_bicubic_render(
    pair_factory, tmp_path
):
    points = [(20.2, 20.3), (170.8, 80.6), (60.4, 180.1)]
    source = pair_factory(
        size=(200, 200),
        walls=[{"c": [*points[i], *points[(i + 1) % 3]]} for i in range(3)],
    )
    folder = export_overlays(Session(source), tmp_path, Placement())
    item = json.loads((folder / "placement.json").read_text())["items"][0]
    area = Polygon(points)
    full = render_export_alpha(
        source.size, source.size, [ContourMask(area, "outside"), ContourMask(area, "outside")]
    )
    assert full.histogram()[1] > 0  # Actual alpha 1/255 exists, well below 1%.
    reconstructed = Image.new("L", source.size, 0)
    with Image.open(folder / item["file"]) as image:
        reconstructed.paste(image.getchannel("A"), (item["x"], item["y"]))
    assert reconstructed.tobytes() == full.tobytes()  # No faint edge was cropped away.
