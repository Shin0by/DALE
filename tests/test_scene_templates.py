"""Reusable definitions must never include placed objects or mutate source assets."""

import hashlib
import json
import zipfile
from copy import deepcopy
from dataclasses import replace

import pytest

from dale.project_io import SCHEMA_VERSION, load_project, read_project_templates, save_project
from dale.scene_templates import (
    LevelTemplate,
    SceneTemplates,
    WallPreset,
    decode_templates,
    default_wall_properties,
    load_template_file,
    save_template_file,
)
from dale.session import Session


def library():
    properties = default_wall_properties()
    properties.update(dir=2, move=0, sight=30, light=40, sound=10, door=2, ds=2)
    properties["threshold"].update(sight=2.5, light=None, attenuation=True)
    properties["animation"].update(
        type="swing", texture="doors/wood.png", double=True, direction=-1
    )
    properties["doorSound"] = "customSound"
    return SceneTemplates(
        (
            LevelTemplate(name="Ground"),
            LevelTemplate(name="Upper", bottom_ft=10, top_ft=20, color="#1234ef", visible=False),
        ),
        (WallPreset(name="Locked window", icon="window_locked", properties=properties),),
    )


def test_null_height_ranges_rgb_and_independent_semantics_round_trip(tmp_path):
    source = library()
    path = tmp_path / "floors.json"
    save_template_file(source, path)
    assert load_template_file(path) == source
    data = json.loads(path.read_bytes())
    assert data["levels"][0]["bottom_ft"] is None and data["levels"][0]["top_ft"] is None
    assert set(data) == {"format", "schema_version", "levels", "wall_presets"}
    assert not any(
        word in path.read_text() for word in ('walls"', "coordinates", "sources/", "operations")
    )
    swapped = replace(source.levels[1], bottom_ft=40, top_ft=-5)
    normalized = SceneTemplates((swapped,)).validated().levels[0]
    assert (normalized.bottom_ft, normalized.top_ft) == (-5, 40)


def test_project_stores_hashed_definitions_and_preserves_original_sources(pair_factory, tmp_path):
    source = pair_factory()
    before = source.image_path.read_bytes(), source.json_path.read_bytes()
    path = tmp_path / "scene.dale"
    expected = library()
    save_project(Session(source), path, templates=expected)
    with load_project(path) as loaded:
        assert loaded.templates == expected
        assert loaded.templates.levels[0].bottom_ft is None
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["schema_version"] == SCHEMA_VERSION == 3
        assert (
            manifest["sha256"]["templates.json"]
            == hashlib.sha256(archive.read("templates.json")).hexdigest()
        )
    assert before == (source.image_path.read_bytes(), source.json_path.read_bytes())


def test_import_from_project_reads_only_manifest_and_shared_definitions(
    pair_factory, tmp_path, monkeypatch
):
    path = tmp_path / "scene.dale"
    expected = library()
    save_project(Session(pair_factory()), path, templates=expected)
    real_open = zipfile.ZipFile.open
    read_members = []

    def guarded_open(archive, name, *args, **kwargs):
        name = name.filename if isinstance(name, zipfile.ZipInfo) else name
        read_members.append(name)
        assert name in ("manifest.json", "templates.json")
        return real_open(archive, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", guarded_open)
    assert read_project_templates(path) == expected
    assert set(read_members) == {"manifest.json", "templates.json"}


def test_import_remaps_ids_without_overwriting_or_aliasing_existing_presets():
    source = library()
    imported = source.merge(source)
    assert len(imported.levels) == 4 and len(imported.wall_presets) == 2
    assert len({item.id for item in (*imported.levels, *imported.wall_presets)}) == 6
    assert imported.levels[:2] == source.levels
    assert imported.wall_presets[0] == source.wall_presets[0]
    imported.wall_presets[1].properties["threshold"]["sight"] = 99
    assert source.wall_presets[0].properties["threshold"]["sight"] == 2.5


@pytest.mark.parametrize(
    "field,value",
    [("bottom_ft", True), ("top_ft", 1.5), ("color", "#12345678"), ("visible", 0), ("name", "")],
)
def test_invalid_level_definitions_are_rejected(field, value):
    data = library().to_data()
    data["levels"][0][field] = value
    with pytest.raises(ValueError):
        decode_templates(data)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(height=30),
        lambda p: p.update(c=[0, 0, 10, 20]),
        lambda p: p.update(sight=99),
        lambda p: p["threshold"].update(sight=float("nan")),
        lambda p: p["threshold"].update(light=-1),
        lambda p: p["animation"].update(direction=0),
    ],
)
def test_presets_reject_instance_heights_coordinates_and_invalid_values(mutate):
    data = library().to_data()
    mutate(data["wall_presets"][0]["properties"])
    with pytest.raises(ValueError):
        decode_templates(data)


def test_older_projects_and_template_checksum_corruption_are_rejected(pair_factory, tmp_path):
    path = tmp_path / "scene.dale"
    save_project(Session(pair_factory()), path, templates=library())
    with zipfile.ZipFile(path) as archive:
        payloads = {item.filename: archive.read(item) for item in archive.infolist()}
    for name, patch in (("old", {"schema_version": 2}), ("corrupt", {})):
        manifest = json.loads(payloads["manifest.json"])
        manifest.update(patch)
        output = tmp_path / f"{name}.dale"
        with zipfile.ZipFile(output, "w") as archive:
            for member, data in payloads.items():
                if member == "manifest.json":
                    data = json.dumps(manifest).encode()
                if member == "templates.json" and name == "corrupt":
                    data = b"{}"
                archive.writestr(member, data)
        with pytest.raises(ValueError, match="Unsupported|checksum"):
            read_project_templates(output)


def test_failed_template_export_keeps_existing_destination_and_cleans_temp(tmp_path, monkeypatch):
    path = tmp_path / "templates.json"
    path.write_bytes(b"existing")
    monkeypatch.setattr(
        "dale.scene_templates.os.replace", lambda *args: (_ for _ in ()).throw(OSError("blocked"))
    )
    with pytest.raises(OSError):
        save_template_file(library(), path)
    assert path.read_bytes() == b"existing"
    assert not list(tmp_path.glob(".dale-templates-*"))


def test_duplicate_ids_unknown_versions_and_excessive_levels_are_rejected():
    data = library().to_data()
    duplicate = deepcopy(data)
    duplicate["levels"].append(duplicate["levels"][0])
    with pytest.raises(ValueError, match="duplicate"):
        decode_templates(duplicate)
    data["schema_version"] = 999
    with pytest.raises(ValueError, match="Unsupported"):
        decode_templates(data)
    with pytest.raises(ValueError, match="Too many"):
        SceneTemplates(tuple(LevelTemplate() for _ in range(257))).validated()
