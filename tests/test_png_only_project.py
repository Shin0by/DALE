"""Single-image projects preserve alpha, geometry, and exact PNG crop identity."""

import json
import zipfile

import pytest
from PIL import Image
from shapely.geometry import box

from dale.editing import add_line
from dale.overlay_export import export_overlays
from dale.project_io import load_project, read_json_documents, save_project
from dale.raster import render_preview
from dale.scene import load_pair
from dale.session import ContourMask, Session, Stroke


@pytest.mark.parametrize("suffix", [".png", ".webp", ".bmp", ".tif"])
def test_static_image_only_project_keeps_exact_source_bytes_and_manual_geometry(tmp_path, suffix):
    image_path = tmp_path / ("source" + suffix)
    Image.new("RGB", (64, 48), (40, 80, 160)).save(image_path)
    source_bytes = image_path.read_bytes()
    session = Session(load_pair(image_path))
    points = ((5, 5), (50, 5), (50, 40), (5, 40))
    for a, b in zip(points, (*points[1:], points[0]), strict=True):
        session.add(add_line(session.geometry(), a, b))
    session.add(session.make_mask("outside"))
    session.add(Stroke(((20, 20),), 3))
    session.undo()
    path = tmp_path / "manual.dale"
    save_project(session, path)
    documents = read_json_documents(path)
    assert len(documents) == 1 and documents[0].kind == "updated"
    assert len(json.loads(documents[0].data)["walls"]) == 4
    image_path.unlink()
    with load_project(path) as project:
        restored = project.session
        assert restored.source.image_path.read_bytes() == source_bytes
        assert restored.source.json_path is None
        assert restored.geometry() == session.geometry()
        assert restored.operations == session.operations and restored.future == session.future
        assert restored.operations[-1].boundary.equals(session.operations[-1].boundary)
        folder = export_overlays(restored, tmp_path)
        item = json.loads((folder / "placement.json").read_text())["items"][0]
        with Image.open(folder / item["file"]) as png:
            assert item["file"].endswith(f"-{png.width}x{png.height}px.png")
    with zipfile.ZipFile(path) as archive:
        assert set(archive.namelist()) == {
            "manifest.json",
            "history.json",
            "sources/map.image",
            "sources/json/current-contours.json",
        }


def test_png_original_alpha_caps_restore_and_defines_exact_export_name(tmp_path):
    image_path = tmp_path / "alpha.png"
    original = Image.new("RGBA", (80, 70), (80, 120, 160, 0))
    original.paste((80, 120, 160, 128), (20, 15, 60, 55))
    original.save(image_path)
    session = Session(load_pair(image_path))
    session.add(ContourMask(box(0, 0, 80, 70), "outside"))
    session.add(Stroke(((0, 0), (79, 69)), 100, restore=True))
    preview = render_preview(original, original.size, session.operations)
    assert preview.getchannel("A").tobytes() == original.getchannel("A").tobytes()
    # Supply a closed editable boundary as the export region.
    points = ((0, 0), (79, 0), (79, 69), (0, 69))
    for a, b in zip(points, (*points[1:], points[0]), strict=True):
        session.add(add_line(session.geometry(), a, b))
    folder = export_overlays(session, tmp_path)
    item = json.loads((folder / "placement.json").read_text())["items"][0]
    assert (item["x"], item["y"], item["width"], item["height"]) == (20, 15, 40, 40)
    assert item["file"] == "alpha-part-001-40x40px.png"
    with Image.open(folder / item["file"]) as png:
        assert png.getchannel("A").getextrema() == (128, 128)


@pytest.mark.parametrize("version", [2, 3, 4, 5, 6, 8])
def test_only_current_png_editor_schema_is_accepted(tmp_path, version):
    image_path = tmp_path / "source.png"
    Image.new("RGB", (8, 8)).save(image_path)
    path = tmp_path / "project.dale"
    save_project(Session(load_pair(image_path)), path)
    with zipfile.ZipFile(path) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(members["manifest.json"])
    manifest["schema_version"] = version
    members["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
    with pytest.raises(ValueError, match="Unsupported"):
        load_project(path)
