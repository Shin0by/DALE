"""DA object import matches mesh/model/instance transform composition."""

import json
import math
from copy import deepcopy

import numpy as np
import pytest
from shapely import Polygon
from test_alchemist import sample as sample

from dale.alchemist import import_map, memberships, object_placement
from dale.alchemist_mesh import ModelProfile
from dale.alchemist_slices import profile_edges


def rotation(angle):
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    return np.array(((c, 0, s), (0, 1, 0), (-s, 0, c)))


@pytest.mark.parametrize("kind", [None, 0, 2, 3])
@pytest.mark.parametrize("scales", [(1.4, 0.7), (-1.2, 2.3)])
def test_mesh_to_model_then_instance_composition(kind, scales):
    instance = {"center": {"x": 5, "y": 7}, "height": 3, "rotation": 37, "scale": scales[0]}
    block = {"rotation": 23, "scale": scales[1], "xOffset": 0.2, "yOffset": 0.5, "zOffset": -0.3}
    if kind is not None:
        block["type"] = kind
    a, b, c, d, tx, tz = object_placement(instance, block)[0]
    base, scale = object_placement(instance, block)[1:]
    for point in ((2, 1, 0.4), (-0.2, 2, 1.7), (0, 0, 0)):
        model = rotation(180 if kind in (None, 2) else 0) @ point
        model = rotation(23) @ (model * scales[1]) + (0.2, 0.5, -0.3)
        expected = rotation(37) @ (model * scales[0]) + (5, 3, 7)
        x, y, z = point
        assert (a * x + b * z + tx, base + y * scale, c * x + d * z + tz) == pytest.approx(expected)


def test_import_uses_default_object_half_turn_and_slice_matches(sample, monkeypatch):
    session, library, raw, _ = sample
    data = json.loads(raw)
    data.update(width=16, height=16)
    for instance in data["buildingBlockInstances"]:
        instance.update(center={"x": 8, "y": 8}, rotation=37)
    entries = deepcopy(library.resolve(["tree"]))
    block = entries["tree"]["block"]
    block.update(rotation=23, scale=0.7, xOffset=0.2, zOffset=-0.3)
    shape = Polygon(((0, 0), (1, 0), (1.5, 0.5), (0, 0.7)))
    profile = ModelProfile(0, 2, (shape,) * 10)
    monkeypatch.setattr(library, "resolve", lambda *_: entries)
    monkeypatch.setattr(library, "profiles", lambda *_: {"tree": profile})
    imported, geometry = import_map(
        json.dumps(data).encode(), "Rotated.dam", session, library, load_geometry=True
    )
    ownership = memberships(imported, geometry)
    for obj in imported.objects:
        raw_object = next(o for o in data["objects"] if o["id"] == obj.id)
        instance = next(
            i
            for i in data["buildingBlockInstances"]
            if i["id"] == raw_object["buildingBlockInstanceId"]
        )
        expected = []
        for x, z in shape.exterior.coords:
            model = rotation(23) @ (rotation(180) @ (x, 0, z) * 0.7) + (0.2, 0, -0.3)
            world = rotation(37) @ (model * instance["scale"]) + (8, 0, 8)
            expected.append(
                (
                    world[0] * session.source.size[0] / 16,
                    (16 - world[2]) * session.source.size[1] / 16,
                )
            )
        edges = tuple(e for e, own in zip(geometry.walls, ownership, strict=True) if obj.id in own)
        actual = Polygon([e[0] for e in edges])
        assert actual.hausdorff_distance(Polygon(expected)) < 1e-6
        sliced = profile_edges(obj, dict(imported.profiles), 4, {}, alpha=True, separate_parts=True)
        assert np.asarray(sliced) == pytest.approx(np.asarray(edges), abs=1e-7)
