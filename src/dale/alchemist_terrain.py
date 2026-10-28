"""Bounded readers for DAM6 BSON and DAM11 binary terrain height grids."""

import base64
import math
import struct
import sys
from array import array
from dataclasses import dataclass

MAX_BYTES = 64 * 1024 * 1024
MAX_SAMPLES = 8_000_000
FEET_PER_DA_CELL = 5


def _integer(data, offset):
    if not 0 <= offset <= len(data) - 4:
        raise ValueError("Incomplete Dungeon Alchemist terrain.")
    return struct.unpack_from("<i", data, offset)[0]


def _fields(data, start=0):
    end = start + _integer(data, start)
    if not start + 5 <= end <= len(data) or data[end - 1] != 0:
        raise ValueError("Invalid Dungeon Alchemist terrain document.")
    position = start + 4
    while position < end - 1:
        kind = data[position]
        key_end = data.find(b"\0", position + 1, end)
        if key_end < 0:
            raise ValueError("Invalid Dungeon Alchemist terrain field.")
        key = data[position + 1 : key_end].decode("ascii")
        value = key_end + 1
        if kind in (3, 4):
            size = _integer(data, value)
            if size < 5:
                raise ValueError("Invalid Dungeon Alchemist terrain document.")
        elif kind in (2, 5):
            length = _integer(data, value)
            if length < 0:
                raise ValueError("Invalid Dungeon Alchemist terrain field length.")
            size = length + (4 if kind == 2 else 5)
        elif kind in (1, 18):
            size = 8
        elif kind == 16:
            size = 4
        elif kind == 8:
            size = 1
        elif kind == 10:
            size = 0
        else:
            raise ValueError("Unsupported Dungeon Alchemist terrain field.")
        position = value + size
        if position > end - 1:
            raise ValueError("Incomplete Dungeon Alchemist terrain field.")
        yield key, kind, value, position


def _dimensions(width, height, count, sample_budget):
    if (
        not 2 <= width <= 80001
        or not 2 <= height <= 80001
        or width * height != count
        or count > sample_budget
    ):
        raise ValueError("Invalid Dungeon Alchemist terrain dimensions.")


@dataclass(frozen=True)
class TerrainSurface:
    width: int
    height: int
    map_width: int
    map_height: int
    values: array

    def at(self, x, y):
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("Invalid Dungeon Alchemist terrain coordinate.")
        x = max(0, min(self.width - 1, x * (self.width - 1) / self.map_width))
        y = max(0, min(self.height - 1, y * (self.height - 1) / self.map_height))
        ix, iy = min(int(x), self.width - 2), min(int(y), self.height - 2)
        dx, dy = x - ix, y - iy
        low = (
            self.values[iy * self.width + ix] * (1 - dx)
            + self.values[iy * self.width + ix + 1] * dx
        )
        high = (
            self.values[(iy + 1) * self.width + ix] * (1 - dx)
            + self.values[(iy + 1) * self.width + ix + 1] * dx
        )
        return low * (1 - dy) + high * dy


@dataclass(frozen=True)
class TerrainSurfaces:
    layers: tuple[TerrainSurface, ...]

    def for_layer(self, layer):
        # DAM11 TerrainMapLayer.FromFoundationLayer clamps to -1..0;
        # TerrainMapLayer.Index takes the absolute value, not foundation order.
        index = 1 if layer < 0 else 0
        return self.layers[index] if index < len(self.layers) else None

    def at(self, x, y):
        return self.layers[0].at(x, y)


def read_terrain(data):
    if data.get("terrain") is not None:
        encoded_layers = [data["terrain"]]
    else:
        layers = data.get("terrainLayers", [])
        if (
            not isinstance(layers, list)
            or len(layers) > 2
            or any(not isinstance(layer, dict) or "terrain" not in layer for layer in layers)
        ):
            raise ValueError("Invalid Dungeon Alchemist terrain layers.")
        encoded_layers = [layer["terrain"] for layer in layers]
    if not encoded_layers:
        return None
    extent = data["width"], data["height"]
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in extent):
        raise ValueError("Invalid Dungeon Alchemist map extent.")
    surfaces, remaining = [], MAX_SAMPLES
    for encoded in encoded_layers:
        surface = _read_surface(encoded, extent, remaining)
        remaining -= len(surface.values)
        surfaces.append(surface)
    return TerrainSurfaces(tuple(surfaces))


def _read_surface(encoded, extent, sample_budget):
    if not isinstance(encoded, str) or len(encoded) > MAX_BYTES * 4 // 3 + 4:
        raise ValueError("Invalid Dungeon Alchemist terrain payload.")
    raw = base64.b64decode(encoded, validate=True)
    if len(raw) > MAX_BYTES:
        raise ValueError("Dungeon Alchemist terrain exceeds the supported size.")
    values = array("f")
    if _integer(raw, 0) == -1:
        count, position = _integer(raw, 4), 8
        if not 0 <= count <= 4096:
            raise ValueError("Invalid Dungeon Alchemist terrain texture count.")
        for _ in range(count):
            length = _integer(raw, position + 16)
            if length < 0 or position + 20 + length > len(raw):
                raise ValueError("Incomplete Dungeon Alchemist terrain texture.")
            position += 20 + length
        width, height, count = (_integer(raw, position + i * 4) for i in range(3))
        _dimensions(width, height, count, sample_budget)
        if position + 12 + count * 4 != len(raw):
            raise ValueError("Invalid Dungeon Alchemist terrain sample count.")
        values.frombytes(raw[position + 12 :])
        if sys.byteorder != "little":
            values.byteswap()
    else:
        if _integer(raw, 0) != len(raw):
            raise ValueError("Invalid Dungeon Alchemist terrain document length.")
        fields = {key: (kind, start, end) for key, kind, start, end in _fields(raw)}
        if (
            "size" not in fields
            or "map" not in fields
            or fields["size"][0] != 2
            or fields["map"][0] not in (3, 4)
        ):
            raise ValueError("Missing Dungeon Alchemist terrain height grid.")
        _, start, end = fields["size"]
        dimensions = raw[start + 4 : end - 1].decode("ascii").split()
        if len(dimensions) != 2:
            raise ValueError("Invalid Dungeon Alchemist terrain dimensions.")
        width, height = map(int, dimensions)
        _dimensions(width, height, width * height, sample_budget)
        for index, (key, kind, start, _) in enumerate(_fields(raw, fields["map"][1])):
            if key != str(index) or kind != 1 or index >= width * height:
                raise ValueError("Invalid Dungeon Alchemist terrain height sample.")
            value = struct.unpack_from("<d", raw, start)[0]
            if not math.isfinite(value) or abs(value) > 1e9:
                raise ValueError("Invalid Dungeon Alchemist terrain height.")
            values.append(value)
        if len(values) != width * height:
            raise ValueError("Invalid Dungeon Alchemist terrain sample count.")
    if any(not math.isfinite(v) or abs(v) > 1e9 for v in values):
        raise ValueError("Invalid Dungeon Alchemist terrain height.")
    return TerrainSurface(width, height, *extent, values)


def ground_height(surface, instance, foundation):
    """Use the local floor for a building, and sampled relief for terrain foundations."""
    layer = foundation.get("layer", 0)
    if type(layer) is not int or not -1000 <= layer <= 1000:
        raise ValueError("Invalid Dungeon Alchemist floor.")
    terrain = surface.for_layer(layer) if surface is not None else None
    if foundation.get("type", 0) or layer > 0 or terrain is None:
        value = foundation.get("height", 0)
    else:
        center = instance.get("center", {})
        value = terrain.at(center.get("x", 0), center.get("y", 0))
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e9:
        raise ValueError("Invalid Dungeon Alchemist surface height.")
    return value
