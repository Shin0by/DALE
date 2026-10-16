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


def test_crop_guard_outside_source_is_transparent_not_black_opaque(pair_factory, tmp_path):
    source = pair_factory(size=(80, 80), walls=_rectangle(0, 0, 30, 30))
    folder = export_overlays(Session(source), tmp_path, Placement())
    item = json.loads((folder / "placement.json").read_text())["items"][0]
    assert (item["x"], item["y"]) == (-3, -3)
    with Image.open(folder / item["file"]) as image:
        assert image.getpixel((0, 0)) == (0, 0, 0, 0)
        assert image.getpixel((3, 3))[3] == 255


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
