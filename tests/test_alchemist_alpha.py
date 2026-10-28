"""Alpha cards, opaque trunk caps, embedded textures and bounded resource reads."""

import io
import json
import struct
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image
from shapely import LineString, MultiPolygon, Point, Polygon, box, union_all
from test_alchemist_mesh import leaning_tree

from dale.alchemist_alpha import AlphaSurface, alpha_channel
from dale.alchemist_materials import native_alpha
from dale.alchemist_mesh import build_profile, glb_meshes, outlines, project, transform, transformed


def card(alpha, *, height=False):
    vertices = np.array(
        [(0, 0, 0), (1, int(height), 0), (1, int(height), 1), (0, 0, 1)], dtype=float
    )
    uv = np.array([(0, 0), (1, 0), (1, 1), (0, 1)], dtype=float)
    surface = AlphaSurface(uv, alpha, wrap=("clamp", "clamp"))
    return vertices, [(0, 1, 2), (0, 2, 3)], (0.2, 0.7, 0.2), surface


def test_alpha_outer_edge_survives_while_enclosed_holes_are_omitted():
    alpha = np.full((32, 32), 255, dtype=np.uint8)
    alpha[8:24, 8:24] = 0
    alpha[:, :4] = 100
    mesh = card(alpha)
    shape = project([mesh])
    assert shape.area == pytest.approx(0.625, abs=0.004)
    assert not shape.covers(Point(0.5, 0.5))
    assert not shape.covers(Point(0.05, 0.5))
    rings = outlines(shape, 5, foliage=True, alpha=True)
    restored = Polygon(rings[0], rings[1:])
    assert restored.covers(Point(0.5, 0.5))
    assert not restored.covers(Point(0.05, 0.5))
    assert restored.area == pytest.approx(0.875, abs=0.01)
    assert all(not part.interiors for part in [build_profile([mesh]).layers[0]])
    # Material alpha multiplies texture alpha, including otherwise opaque pixels.
    invisible = (*mesh[:3], replace(mesh[3], opacity=0.4))
    assert project([invisible], allow_empty=True).is_empty


def test_alpha_band_clipping_negative_scale_and_opaque_caps():
    alpha = np.zeros((32, 32), dtype=np.uint8)
    alpha[:, :16] = 255
    mesh = card(alpha, height=True)
    profile = build_profile([mesh])
    assert profile.layers[2].area == pytest.approx(0.1, abs=0.004)
    assert all(shape.is_empty for shape in profile.layers[5:])
    reflected = (transformed(mesh[0], transform((4, 2, 5), scale=(-2, -2, 2))), *mesh[1:])
    assert project([reflected]).area == pytest.approx(2, abs=0.01)
    # Transparent cards cannot make cut caps that resurrect their empty portions.
    trunk = leaning_tree()
    invisible = (*mesh[:3], replace(mesh[3], alpha=np.zeros((32, 32), dtype=np.uint8)))
    actual = project([*trunk, invisible], floor=0.1, ceiling=0.3)
    expected = project(trunk, floor=0.1, ceiling=0.3)
    assert actual.equals(expected)


def test_alpha_uv_wrap_and_cancel():
    alpha = np.array([[255, 0]], dtype=np.uint8)
    surface = AlphaSurface(np.zeros((3, 2)), alpha)
    uv = np.array([[-0.25, 0], [1.25, 0], [1.75, 0]])
    assert surface.visible(uv).tolist() == [False, True, False]
    assert replace(surface, wrap=("mirror", "repeat")).visible(uv).tolist() == [True, False, True]
    assert replace(surface, wrap=("clamp", "repeat")).visible(uv).tolist() == [True, False, False]
    calls = []

    def cancel():
        calls.append(1)
        if len(calls) == 4:
            raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        project([card(np.ones((2, 2), dtype=np.uint8) * 255)], check_cancel=cancel)


def test_native_resource_reads_only_range_and_retains_one_channel(tmp_path, monkeypatch):
    resource = tmp_path / "resources.assets.resS"
    resource.write_bytes(b"prefix" + b"data" + b"suffix")
    texture = SimpleNamespace(
        m_Width=4,
        m_Height=4,
        image_data=b"",
        m_TextureFormat=4,
        m_StreamData=SimpleNamespace(size=4, offset=6, path="resources.assets.resS"),
        object_reader=SimpleNamespace(version=(2022, 3, 0, 0), platform=19),
        m_PlatformBlob=None,
    )
    seen = []

    def decode(raw, *args, **kwargs):
        seen.append((raw, kwargs))
        return Image.new("RGBA", (4, 4), (1, 2, 3, 80))

    monkeypatch.setattr("UnityPy.export.Texture2DConverter.parse_image_data", decode)
    with native_alpha(texture, tmp_path) as image:
        channel = alpha_channel(image)
    assert seen == [(b"data", {"flip": False})]
    assert channel.shape == (4, 4) and channel.nbytes == 16 and np.all(channel == 80)
    assert resource.read_bytes() == b"prefixdatasuffix"
    texture.m_Width = 10000000
    with pytest.raises(ValueError, match="size"):
        native_alpha(texture, tmp_path)


def write_alpha_glb(path, *, external=False, opaque=False):
    mesh = card(np.ones((4, 4), dtype=np.uint8))
    arrays = [
        mesh[0].astype("<f4").tobytes(),
        np.array(mesh[1], dtype="<u2").tobytes(),
        mesh[3].uv.astype("<f4").tobytes(),
    ]
    image = Image.new("RGBA", (8, 8), (0, 255, 0, 0))
    for y in range(8):
        for x in range(4):
            image.putpixel((x, y), (0, 255, 0, 255))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    arrays.append(stream.getvalue())
    views, binary = [], b""
    for array in arrays:
        binary += b"\0" * (-len(binary) % 4)
        views.append(dict(buffer=0, byteOffset=len(binary), byteLength=len(array)))
        binary += array
    binary += b"\0" * (-len(binary) % 4)
    doc = dict(
        asset={"version": "2.0"},
        buffers=[{"byteLength": len(binary)}],
        bufferViews=views,
        accessors=[
            dict(bufferView=0, componentType=5126, count=4, type="VEC3"),
            dict(bufferView=1, componentType=5123, count=6, type="SCALAR"),
            dict(bufferView=2, componentType=5126, count=4, type="VEC2"),
        ],
        meshes=[
            {
                "primitives": [
                    {"attributes": {"POSITION": 0, "TEXCOORD_0": 2}, "indices": 1, "material": 0}
                ]
            }
        ],
        nodes=[{"mesh": 0}],
        scenes=[{"nodes": [0]}],
        scene=0,
        textures=[{"source": 0}],
        images=[{"uri": "missing.png"} if external else {"bufferView": 3, "mimeType": "image/png"}],
        materials=[
            {
                "alphaMode": "OPAQUE" if opaque else "MASK",
                "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}},
            }
        ],
    )
    raw = json.dumps(doc).encode()
    raw += b" " * (-len(raw) % 4)
    path.write_bytes(
        struct.pack("<4sII", b"glTF", 2, 28 + len(raw) + len(binary))
        + struct.pack("<II", len(raw), 0x4E4F534A)
        + raw
        + struct.pack("<II", len(binary), 0x004E4942)
        + binary
    )


def test_embedded_workshop_alpha_and_no_external_texture_loading(tmp_path):
    path = tmp_path / "card.glb"
    write_alpha_glb(path)
    shape = project(glb_meshes(path))
    assert shape.area == pytest.approx(0.5, abs=0.003)
    assert shape.bounds == pytest.approx((-0.5, 0, 0, 1), abs=0.003)
    write_alpha_glb(path, external=True)
    with pytest.raises(ValueError, match="External"):
        glb_meshes(path)
    write_alpha_glb(path, opaque=True)
    assert project(glb_meshes(path)).area == pytest.approx(1)


def test_pre_alpha_profile_cache_is_not_reused(tmp_path):
    from dale.alchemist_library import AlchemistLibrary
    from dale.alchemist_mesh import FORMAT, cached_profile, save_profile

    library = AlchemistLibrary(tmp_path / "profiles.sqlite3")
    profile = build_profile([card(np.full((4, 4), 255, dtype=np.uint8))])
    with library._connect() as connection:
        save_profile(connection, "model", profile)
        assert cached_profile(connection, "model") == profile
        connection.execute("UPDATE model_profiles SET format=?", (FORMAT - 1,))
        assert cached_profile(connection, "model") is None


@pytest.mark.parametrize("gap", [0.001, 0.05, 1.0])
def test_disconnected_foliage_islands_never_gain_bridges(gap):
    shape = union_all(
        [
            Point(0, 0).buffer(1, quad_segs=12),
            Point(2 + gap, 0).buffer(1, quad_segs=12),
            Point(1, 4).buffer(1, quad_segs=12),
        ]
    )
    rings = outlines(shape, 5, True, alpha=True, separate_parts=True)
    parts = [Polygon(ring) for ring in rings]
    assert len(parts) == 3
    assert MultiPolygon(parts).is_valid
    assert all(a.disjoint(b) for i, a in enumerate(parts) for b in parts[i + 1 :])
    assert not union_all(parts).intersects(LineString([(1 + gap / 2, -0.5), (1 + gap / 2, 0.5)]))


@pytest.mark.parametrize("contact", ["point", "thin", "wide"])
def test_real_contacts_are_preserved_without_inflating_their_width(contact):
    if contact == "point":
        shape = union_all([box(0, 0, 1, 1), box(1, 1, 2, 2)])
    else:
        width = 0.002 if contact == "thin" else 0.7
        shape = union_all(
            [box(0, 0, 1, 1), box(3, 0, 4, 1), box(0.9, 0.5 - width / 2, 3.1, 0.5 + width / 2)]
        )
    rings = outlines(shape, 5, True, alpha=True, separate_parts=True)
    actual = union_all([Polygon(ring) for ring in rings])
    assert actual.equals(shape)
    if contact == "point":
        assert len(rings) == 2
    else:
        assert len(rings) == 1
        assert actual.intersection(LineString([(2, 0), (2, 1)])).length == pytest.approx(width)


def test_external_boundaries_keep_open_notches_but_omit_enclosed_holes():
    shape = box(0, 0, 10, 10).difference(union_all([box(3, 4, 7, 11), box(1, 1, 2, 2)]))
    rings = outlines(shape, 10, True, alpha=True, separate_parts=True)
    assert len(rings) == 1
    actual = Polygon(rings[0])
    assert actual.covers(Point(1.5, 1.5))
    assert not actual.intersects(box(3.1, 4.1, 6.9, 10))
