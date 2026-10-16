import json

import pytest
from PIL import Image

from dale.overlay_export import export_overlays
from dale.placement import Placement
from dale.raster import ExportCancelled
from dale.session import Session, Stroke


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


def test_each_separate_contour_gets_its_own_png_with_three_real_pixel_guard(pair_factory, tmp_path):
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
    assert (first["x"], first["y"], first["width"], first["height"]) == (7, 17, 27, 37)
    assert (second["x"], second["y"], second["width"], second["height"]) == (97, 117, 47, 57)
    with Image.open(folder / first["file"]) as image:
        assert image.size == (27, 37)
        assert (
            image.getpixel((0, 10))[3] == 255
        )  # Actual source pixels three pixels outside the wall.
        assert image.info["DALE.SourceX"] == "7"
        assert image.info["DALE.EdgeGuardPixels"] == "3"
    assert before == (source.image_path.read_bytes(), source.json_path.read_bytes())


def test_crop_guard_is_clipped_to_source_image_bounds(pair_factory, tmp_path):
    source = pair_factory(size=(80, 80), walls=_rectangle(0, 0, 30, 30))
    folder = export_overlays(Session(source), tmp_path, Placement())
    item = json.loads((folder / "placement.json").read_text())["items"][0]
    assert (item["x"], item["y"]) == (0, 0)
    with Image.open(folder / item["file"]) as image:
        assert image.getpixel((0, 0))[3] == 255
        assert image.size == (34, 34)


def test_brush_edits_remain_in_cropped_result(pair_factory, tmp_path):
    source = pair_factory(size=(80, 80), walls=_rectangle(10, 10, 40, 40))
    session = Session(source, contour_offset=2)
    session.add(session.make_mask("outside"))
    session.add(Stroke(((30, 30),), 3))
    folder = export_overlays(session, tmp_path, Placement(13, 5))
    item = json.loads((folder / "placement.json").read_text())["items"][0]
    assert item["x"] == 5  # 10 - user offset 2 - mandatory guard 3.
    with Image.open(folder / item["file"]) as image:
        assert image.getpixel((30 - item["x"], 30 - item["y"]))[3] == 0
        assert image.info["DALE.FoundryMajor"] == "13"


def test_cancelled_set_leaves_no_partial_directory(pair_factory, tmp_path):
    session = Session(pair_factory())
    with pytest.raises(ExportCancelled):
        export_overlays(session, tmp_path, Placement(), cancelled=lambda: True)
    assert not list(tmp_path.glob(".dale-export-*"))
    assert not list(tmp_path.glob("*-overlays*"))


def test_exporting_selected_region_uses_the_same_guarded_bounds_as_the_footer(
    pair_factory, tmp_path
):
    source = pair_factory(
        size=(200, 200), walls=_rectangle(10, 20, 20, 30) + _rectangle(100, 120, 40, 50)
    )
    folder = export_overlays(Session(source), tmp_path, Placement(), region_index=1)
    manifest = json.loads((folder / "placement.json").read_text())
    assert manifest["selected_region"] == 1
    assert len(manifest["items"]) == 1
    item = manifest["items"][0]
    assert (item["x"], item["y"], item["width"], item["height"]) == (97, 117, 47, 57)


def test_selected_adjacent_cells_export_separately_with_padding_clipped_to_jpg(
    pair_factory, tmp_path
):
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
        extra_padding=500,
    )
    manifest = json.loads((folder / "placement.json").read_text())
    assert manifest["selected_regions"] == [0, 1]
    assert manifest["extra_padding_px"] == 500
    assert manifest["region_mode"] == "faces"
    for item in manifest["items"]:
        assert (item["x"], item["y"], item["width"], item["height"]) == (0, 0, 200, 100)
        with Image.open(folder / item["file"]) as image:
            assert image.size == source.size
            assert image.info["DALE.ExtraPaddingPixels"] == "500"
    with Image.open(folder / manifest["items"][0]["file"]) as image:
        assert image.getpixel((30, 50))[3] == 255
        assert image.getpixel((150, 50))[3] == 0
    with Image.open(folder / manifest["items"][1]["file"]) as image:
        assert image.getpixel((30, 50))[3] == 0
        assert image.getpixel((150, 50))[3] == 255
