import json

import pytest
from PIL import Image

from dale.scene import MAX_SIDE, load_pair, open_source


def test_scene_scale_origin_and_background_offset(pair_factory):
    source = pair_factory(
        width=160, height=600, padding=0.25, background={"offsetX": 2, "offsetY": 4}
    )
    assert source.image_walls((8, 16))[0] == ((0, 0), (25, 0))
    assert any("padding" in warning for warning in source.warnings)


@pytest.mark.parametrize(
    "wall", [{"c": [0, 0, 1]}, {"c": [True, 1, 2, 3]}, {"c": [0, 0, float("nan"), 3]}]
)
def test_malformed_walls_fail_visibly(pair_factory, wall):
    with pytest.raises(ValueError, match="Wall"):
        pair_factory(walls=[wall])


def test_unknown_transform_rejected(pair_factory):
    with pytest.raises(ValueError, match="transform"):
        pair_factory(background={"rotation": 10})


def test_raw_json_is_not_changed_by_transformation(pair_factory):
    source = pair_factory()
    before = source.json_path.read_bytes()
    source.image_walls((12, 34))
    assert source.json_path.read_bytes() == before
    assert source.raw == json.loads(before)


def test_unrecognized_json_does_not_silently_become_an_empty_scene(pair_factory):
    source = pair_factory()
    source.json_path.write_text('{"unrecognized": "data"}', encoding="utf-8")
    with pytest.raises(ValueError, match="walls array"):
        load_pair(source.image_path, source.json_path)


def test_reject_oversized_before_decoding(tmp_path):
    path = tmp_path / "wide.jpg"
    Image.new("RGB", (MAX_SIDE + 1, 1)).save(path)
    with pytest.raises(ValueError, match="per-side"):
        with open_source(path):
            pass


def test_non_jpeg_and_exif_rotation_rejected(tmp_path):
    path = tmp_path / "image.png"
    Image.new("RGB", (4, 4)).save(path)
    with pytest.raises(ValueError, match="JPG"):
        with open_source(path):
            pass
    rotated = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (4, 8)).save(rotated, exif=exif)
    with pytest.raises(ValueError, match="EXIF"):
        load_pair(rotated, tmp_path / "unused.json")
