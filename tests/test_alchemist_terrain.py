"""Source-height measurement against both supported DAM terrain encodings."""

import base64
import struct

import pytest

from dale.alchemist_terrain import ground_height, read_terrain


def terrain_payload(values=(1, 3, 5, 7), version=11):
    def document(fields):
        body = b"".join(fields) + b"\0"
        return struct.pack("<i", len(body) + 4) + body

    if version == 11:
        raw = struct.pack("<iiiii4f", -1, 0, 2, 2, 4, *values)
    else:
        samples = document(
            [b"\x01" + str(i).encode() + b"\0" + struct.pack("<d", v) for i, v in enumerate(values)]
        )
        raw = document(
            [
                b"\x02size\0" + struct.pack("<i", 4) + b"2 2\0",
                b"\x04map\0" + samples,
            ]
        )
    return base64.b64encode(raw).decode()


@pytest.mark.parametrize("version", [6, 11])
def test_ground_bilinear_orientation_and_floor_override(version):
    surface = read_terrain({"width": 4, "height": 2, "terrain": terrain_payload(version=version)})
    assert surface.at(0, 0) == 1
    assert surface.at(4, 0) == 3
    assert surface.at(0, 2) == 5
    assert surface.at(2, 1) == 4
    assert surface.at(-1, 8) == 5
    instance = {"center": {"x": 2, "y": 1}, "height": 20}
    assert ground_height(surface, instance, {"height": 0.2}) == 4
    assert ground_height(surface, instance, {"type": 1, "height": 10}) == 10
    assert ground_height(surface, instance, {"layer": -1, "height": -4}) == -4


@pytest.mark.parametrize("version", [6, 11])
def test_bad_or_nonfinite_terrain_rejected(version):
    data = {"width": 4, "height": 2, "terrain": terrain_payload(version=version)}
    raw = base64.b64decode(data["terrain"])
    for bad in (b"", raw[:-1], raw + b"extra"):
        with pytest.raises(ValueError):
            read_terrain({**data, "terrain": base64.b64encode(bad).decode()})
    with pytest.raises(ValueError):
        read_terrain({**data, "terrain": terrain_payload((1, 2, float("nan"), 4), version)})


def test_new_layer_and_multiple_surfaces_use_foundation_level():
    data = {"width": 2, "height": 2, "terrainLayers": [{"terrain": terrain_payload()}]}
    assert read_terrain(data).at(1, 1) == 4
    data["terrainLayers"].append({"terrain": terrain_payload((-9, -7, -5, -3))})
    surface = read_terrain(data)
    instance = {"center": {"x": 1, "y": 1}, "height": -100}
    assert ground_height(surface, instance, {"height": 0.2}) == 4
    assert ground_height(surface, instance, {"layer": -1, "height": -2.2}) == -6
    assert ground_height(surface, instance, {"layer": -2, "height": -4.2}) == -6
    assert ground_height(surface, instance, {"layer": 1, "height": 2.2}) == 2.2
    # A building floor overrides relief, including a floor below the terrain.
    for kind in (1, 2):
        assert ground_height(surface, instance, {"type": kind, "layer": -1, "height": -8}) == -8


@pytest.mark.parametrize(
    "layers", [None, {}, [None], [{}], [{"terrain": None}], [{"terrain": "!"}]]
)
def test_invalid_layer_records_are_rejected(layers):
    with pytest.raises(ValueError):
        read_terrain({"width": 2, "height": 2, "terrainLayers": layers})


def test_all_surfaces_validated_and_share_sample_budget(monkeypatch):
    data = {"width": 2, "height": 2, "terrainLayers": [{"terrain": terrain_payload()}] * 2}
    with pytest.raises(ValueError):
        read_terrain({**data, "terrainLayers": [data["terrainLayers"][0], {"terrain": "!"}]})
    with pytest.raises(ValueError, match="layers"):
        read_terrain({**data, "terrainLayers": data["terrainLayers"] * 2})
    monkeypatch.setattr("dale.alchemist_terrain.MAX_SAMPLES", 7)
    with pytest.raises(ValueError, match="dimensions"):
        read_terrain(data)
