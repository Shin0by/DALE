from pathlib import Path

import pytest
from PIL import Image
from shapely.geometry import Polygon

from dale.placement import Placement
from dale.raster import ExportCancelled, export_png, render_alpha
from dale.scene import open_source
from dale.session import Closure, ContourMask, Session, Stroke


def test_mask_brush_and_restore_apply_in_order(pair_factory):
    source = pair_factory()
    area = Session(source).analysis().area
    operations = [
        ContourMask(area, "outside"),
        Stroke(((20, 30), (50, 30)), 3),
        Stroke(((35, 30),), 1, restore=True),
    ]
    alpha = render_alpha(source.size, source.size, operations)
    assert alpha.getpixel((0, 0)) == 0
    assert alpha.getpixel((30, 50)) == 255
    assert alpha.getpixel((21, 30)) == 0
    assert alpha.getpixel((35, 30)) == 255
    inside = render_alpha(source.size, source.size, [ContourMask(area, "inside")])
    assert inside.getpixel((0, 0)) == 255
    assert inside.getpixel((30, 50)) == 0


@pytest.mark.parametrize("fraction", [0, 0.4])
def test_export_stripes_match_full_render_preserve_rgb_and_source(pair_factory, fraction):
    source = pair_factory()
    before = source.image_path.read_bytes(), source.json_path.read_bytes()
    area = Polygon([(4.2, 8.4), (74.1, 14.9), (68.7, 294.1), (11.8, 280.4)])
    operations = [
        ContourMask(area, "outside"),
        Stroke(((20 + fraction, 108 + fraction), (50.2, 270.9)), 23.4),
        Stroke(((0, 200), (30, 260)), 2, restore=True),
        Closure(((0, 0), (79, 299))),
    ]
    path = source.image_path.parent / "overlay.png"
    progress = []
    export_png(source, operations, path, progress.append, placement=Placement(13, 17))
    expected = render_alpha(source.size, source.size, operations)
    with Image.open(path) as result, open_source(source.image_path) as original:
        assert result.mode == "RGBA"
        assert result.size == original.size == source.size
        assert result.getchannel("A").tobytes() == expected.tobytes()
        assert result.convert("RGB").tobytes() == original.convert("RGB").tobytes()
        assert result.info["DALE.FoundryMajor"] == "13"
        assert result.info["DALE.ElevationFeet"] == "17"
    assert progress[-1] == 100
    assert before == (source.image_path.read_bytes(), source.json_path.read_bytes())


def test_cancel_leaves_existing_destination_and_cleans_temporary(pair_factory):
    source = pair_factory()
    destination = source.image_path.parent / "existing.png"
    destination.write_bytes(b"existing output")
    progress = []
    with pytest.raises(ExportCancelled):
        export_png(source, [], destination, progress.append, lambda: bool(progress))
    assert destination.read_bytes() == b"existing output"
    assert not list(destination.parent.glob(".dale-*.tmp"))


def test_failure_removes_partial_output(pair_factory):
    source = pair_factory()
    destination = source.image_path.parent / "failed.png"

    def fail(_):
        raise OSError("Synthetic disk failure")

    with pytest.raises(OSError, match="disk failure"):
        export_png(source, [], destination, fail)
    assert not destination.exists()
    assert not list(destination.parent.glob(".dale-*.tmp"))


@pytest.mark.parametrize("field", ["image_path", "json_path"])
def test_export_protects_source_files(pair_factory, field):
    source = pair_factory()
    path = getattr(source, field)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="source"):
        export_png(source, [], path)
    assert path.read_bytes() == before


def test_png_suffix_required(pair_factory):
    with pytest.raises(ValueError, match="extension"):
        export_png(pair_factory(), [], Path("overlay.jpg"))


@pytest.mark.parametrize("version", [13, 14])
def test_elevation_accepts_integer_feet_for_both_versions(version):
    assert Placement(version, 1).elevation_ft == 1
    assert Placement(version, -3).elevation_ft == -3
    with pytest.raises(ValueError, match="whole"):
        Placement(version, 1.5)
