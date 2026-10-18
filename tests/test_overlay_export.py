import json

import pytest
from PIL import Image
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from dale.editing import add_circle
from dale.overlay_export import export_overlays, selected_export_regions
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


def test_circular_contour_exports_selected_polygon_with_smooth_clipped_alpha(
    pair_factory, tmp_path
):
    source = pair_factory(size=(200, 200), walls=[], grid={"size": 40})
    session = Session(source)
    session.add(add_circle(session.geometry(), (100, 100), 90, source.cell_pixels))
    folder = export_overlays(session, tmp_path, region_indices=(0,), individual_regions=True)
    item = json.loads((folder / "placement.json").read_text())["items"][0]
    with Image.open(folder / item["file"]) as image:
        alpha = image.getchannel("A")
        assert image.mode == "RGBA"
        assert image.width <= 200 and image.height <= 200
        assert image.getpixel((100 - item["x"], 100 - item["y"]))[3] == 255
        assert image.getpixel((0, 0))[3] == 0
        assert alpha.getbbox() == (0, 0, *image.size)
        assert any(0 < value < 255 for value in alpha.tobytes())


def test_separate_contours_have_no_implicit_margin(pair_factory, tmp_path):
    source = pair_factory(
        size=(200, 200), walls=_rectangle(10, 20, 20, 30) + _rectangle(100, 120, 40, 50)
    )
    session = Session(source)
    session.add(session.make_mask("outside"))
    before = source.image_path.read_bytes(), source.json_path.read_bytes()
    folder = export_overlays(session, tmp_path)
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


@pytest.mark.parametrize("individual", [False, True])
def test_names_match_actual_final_png_sizes_after_alpha_edits(pair_factory, tmp_path, individual):
    source = pair_factory(
        size=(200, 200), walls=_rectangle(0, 0, 40, 50) + _rectangle(100, 120, 40, 50)
    )
    session = Session(source, contour_offset=7)
    session.add(Stroke(((80, 100), (130, 180)), 20))
    folder = export_overlays(session, tmp_path, individual_regions=individual)
    manifest = json.loads((folder / "placement.json").read_text())
    assert len(manifest["items"]) == 2
    assert "elevation_ft" not in manifest and "foundry_major" not in manifest
    for item in manifest["items"]:
        with Image.open(folder / item["file"]) as image:
            assert item["file"].endswith(f"-{image.width}x{image.height}px.png")
            assert (item["width"], item["height"]) == image.size
            assert image.getchannel("A").getbbox() == (0, 0, *image.size)
            assert "DALE.ElevationFeet" not in image.info
            assert image.mode == "RGBA"


def test_artwork_margin_is_clipped_to_source_image_bounds(pair_factory, tmp_path):
    source = pair_factory(size=(80, 80), walls=_rectangle(0, 0, 30, 30))
    folder = export_overlays(Session(source, contour_offset=10), tmp_path)
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
    folder = export_overlays(session, tmp_path)
    item = json.loads((folder / "placement.json").read_text())["items"][0]
    assert item["x"] == 7  # Offset 2, plus actual bicubic coverage; no fixed guard.
    with Image.open(folder / item["file"]) as image:
        assert image.getpixel((30 - item["x"], 30 - item["y"]))[3] == 0


def test_cancelled_set_leaves_no_partial_directory(pair_factory, tmp_path):
    session = Session(pair_factory())
    with pytest.raises(ExportCancelled):
        export_overlays(session, tmp_path, cancelled=lambda: True)
    assert not list(tmp_path.glob(".dale-export-*"))
    assert not list(tmp_path.glob("*-overlays*"))


def test_selected_region_uses_the_same_bounds_as_the_information_panel(pair_factory, tmp_path):
    source = pair_factory(
        size=(200, 200), walls=_rectangle(10, 20, 20, 30) + _rectangle(100, 120, 40, 50)
    )
    folder = export_overlays(Session(source), tmp_path, region_index=1)
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
    folder = export_overlays(session, tmp_path)
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
        export_overlays(session, tmp_path)
    assert not list(tmp_path.glob("*-overlays*"))


def test_cancel_during_alpha_bounds_leaves_no_output(pair_factory, tmp_path):
    session = Session(pair_factory(size=(1000, 1000), walls=_rectangle(50, 50, 500, 500)))
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        return calls >= 3

    with pytest.raises(ExportCancelled):
        export_overlays(session, tmp_path, cancelled=cancel)
    assert not list(tmp_path.glob("*-overlays*"))


def test_tight_crop_preserves_every_faint_pixel_from_full_canvas_bicubic_render(
    pair_factory, tmp_path
):
    points = [(20.2, 20.3), (170.8, 80.6), (60.4, 180.1)]
    source = pair_factory(
        size=(200, 200),
        walls=[{"c": [*points[i], *points[(i + 1) % 3]]} for i in range(3)],
    )
    folder = export_overlays(Session(source), tmp_path)
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


def test_selected_export_groups_transitive_contacts_and_retains_corner_parts_and_holes():
    ring = box(100, 10, 160, 70).difference(box(120, 30, 140, 50))
    polygons = (
        box(10, 10, 30, 30),
        box(50, 10, 70, 30),
        box(30, 10, 50, 30),
        ring,
        box(70, 30, 80, 40),  # Corner-only contact belongs to the same PNG.
    )
    grouped = selected_export_regions(polygons, merge_adjacent=True)
    assert [group for group, _ in grouped] == [(0, 1, 2, 4), (3,)]
    assert grouped[0][1].equals(unary_union([polygons[i] for i in (0, 1, 2, 4)]))
    assert grouped[0][1].geom_type == "MultiPolygon"
    assert len(grouped[1][1].interiors) == 1
    assert selected_export_regions(polygons) == tuple(((i,), p) for i, p in enumerate(polygons))


@pytest.mark.parametrize("offset", [-3, 0, 7])
def test_merged_export_unions_before_offset_and_matches_exact_alpha_and_bounds(
    pair_factory, tmp_path, offset
):
    from dale.bounds_preview import calculate_bounds
    from dale.geometry import offset_region

    source = pair_factory(
        size=(120, 100), walls=_rectangle(20, 20, 80, 60) + [{"c": [60, 20, 60, 80]}]
    )
    session = Session(source, contour_offset=offset)
    session.add(Stroke(((40, 40),), 4))
    original = source.image_path.read_bytes(), source.json_path.read_bytes()
    history = tuple(session.operations)
    folder = export_overlays(
        session, tmp_path, region_indices=(0, 1), individual_regions=True, merge_adjacent=True
    )
    manifest = json.loads((folder / "placement.json").read_text())
    assert manifest["selected_regions"] == [0, 1]
    assert manifest["region_groups"] == [[0, 1]]
    assert manifest["region_mode"] == "selected_components"
    assert len(manifest["items"]) == 1
    item = manifest["items"][0]
    polygon = offset_region(box(20, 20, 100, 80), offset)
    assert item["content_bounds"] == list(calculate_bounds(session, (polygon,)).bounds[0])
    reconstructed = Image.new("L", source.size)
    with Image.open(folder / item["file"]) as image, Image.open(source.image_path) as rgb:
        assert image.getpixel((60 - item["x"], 50 - item["y"]))[3] == 255  # No inner seam.
        assert image.getpixel((40 - item["x"], 40 - item["y"]))[3] == 0  # Raster retained.
        assert image.getpixel((50 - item["x"], 50 - item["y"]))[:3] == rgb.getpixel((50, 50))
        assert item["file"].endswith(f"-{image.width}x{image.height}px.png")
        assert image.getchannel("A").getbbox() == (0, 0, *image.size)
        reconstructed.paste(image.getchannel("A"), (item["x"], item["y"]))
    expected = render_export_alpha(
        source.size,
        source.size,
        [ContourMask(polygon, "outside"), *session.operations, ContourMask(polygon, "outside")],
    )
    assert reconstructed.tobytes() == expected.tobytes()
    assert original == (source.image_path.read_bytes(), source.json_path.read_bytes())
    assert history == tuple(session.operations)


def test_merged_selection_never_includes_unselected_bridge_or_merges_by_artwork_margin(
    pair_factory, tmp_path
):
    source = pair_factory(
        size=(160, 100),
        walls=_rectangle(20, 20, 120, 60) + [{"c": [60, 20, 60, 80]}, {"c": [100, 20, 100, 80]}],
    )
    session = Session(source, contour_offset=30)
    cells = session.analysis().cells
    chosen = tuple(i for i, p in enumerate(cells) if p.centroid.x < 60 or p.centroid.x > 100)
    assert len(chosen) == 2
    folder = export_overlays(
        session, tmp_path, region_indices=chosen, individual_regions=True, merge_adjacent=True
    )
    manifest = json.loads((folder / "placement.json").read_text())
    assert manifest["selected_regions"] == list(chosen)
    assert manifest["region_groups"] == [[i] for i in chosen]
    assert len(manifest["items"]) == 2  # Expanded artwork overlaps, original cells do not.


def test_merged_selected_polygons_preserve_unselected_hole_and_disconnected_group(
    pair_factory, tmp_path
):
    session = Session(pair_factory(size=(200, 120), walls=[]))
    polygons = (
        box(20, 20, 100, 40),
        box(20, 80, 100, 100),
        box(20, 40, 40, 80),
        box(80, 40, 100, 80),
        box(140, 20, 180, 60),
    )
    folder = export_overlays(session, tmp_path, selected_polygons=polygons, merge_adjacent=True)
    manifest = json.loads((folder / "placement.json").read_text())
    assert manifest["region_groups"] == [[0, 1, 2, 3], [4]]
    assert len(manifest["items"]) == 2
    item = manifest["items"][0]
    with Image.open(folder / item["file"]) as image:
        assert image.getpixel((60 - item["x"], 60 - item["y"]))[3] == 0
        assert image.getpixel((30 - item["x"], 40 - item["y"]))[3] == 255


def test_merge_grouping_cancels_before_any_output_is_published(pair_factory, tmp_path):
    session = Session(pair_factory())
    with pytest.raises(ExportCancelled):
        export_overlays(session, tmp_path, merge_adjacent=True, cancelled=lambda: True)
    assert not list(tmp_path.glob("*-overlays*"))
