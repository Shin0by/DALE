"""Stable region identities, matching package names and optional JSON publication."""

import json
from itertools import pairwise

import pytest
from PIL import Image
from shapely.geometry import Polygon, box

from dale.export_names import export_family, group_export_stem, png_filename, selection_number
from dale.json_repair import repaired_json_bytes
from dale.overlay_export import export_group_matches, export_overlays, overlay_region_plan
from dale.project_io import load_project, save_project
from dale.selection_groups import SelectionGroup, boundary_members
from dale.session import Session, Stroke


@pytest.mark.parametrize(
    "name, expected",
    [("Room / A:*", "Room _ A__"), ("CON", "_CON"), ("...", "Group"), ("Комната", "Комната")],
)
def test_group_physical_names_are_safe_without_changing_the_display_name(name, expected):
    assert group_export_stem(name) == expected


@pytest.mark.parametrize("grid", [False, True])
def test_exact_group_name_changes_package_prefix_only_before_offset_and_grid(
    pair_factory, tmp_path, grid
):
    session, areas = scene(pair_factory)
    group = SelectionGroup.create("Room A").assign(boundary_members(session.geometry(), areas[:1]))
    original = repaired_json_bytes(session)[0]
    session.contour_offset = 3
    output = export_overlays(
        session,
        tmp_path,
        selected_polygons=areas[:1],
        export_name="Dataset",
        export_groups=(group,),
        size_to_grid=grid,
    )
    family = export_family(group.name, selection_number(areas[:1]))
    assert (output / f"{family}.json").read_bytes() == original
    manifest = json.loads((output / f"{family}-placement.json").read_text())
    assert len(manifest["items"]) == 1
    assert next(output.glob("*.png")).name.startswith(family + "-")


def test_mixed_export_names_only_exact_group_parts_and_retains_dataset_json(pair_factory, tmp_path):
    session, areas = scene(pair_factory)
    group = SelectionGroup.create("Room A").assign(boundary_members(session.geometry(), areas[:1]))
    output = export_overlays(
        session,
        tmp_path,
        selected_polygons=(areas[0], areas[2]),
        export_name="Dataset",
        export_groups=(group,),
    )
    names = sorted(path.name for path in output.glob("*.png"))
    assert names[0].startswith("Dataset-") and names[1].startswith("Room A-")
    family = export_family("Dataset", selection_number((areas[0], areas[2])))
    assert (output / f"{family}.json").is_file()


def test_whole_export_group_match_ignores_other_components_touching_at_one_corner(pair_factory):
    areas = (box(10, 10, 40, 40), box(40, 40, 70, 70))
    source = pair_factory(
        size=(100, 100),
        walls=[{"c": [*a, *b]} for p in areas for a, b in pairwise(p.exterior.coords)],
    )
    session = Session(source)
    groups = tuple(
        SelectionGroup.create(str(i)).assign(boundary_members(session.geometry(), (p,)))
        for i, p in enumerate(areas)
    )
    matches = export_group_matches(session, groups, overlay_region_plan(session))
    assert {g.id for g in matches} == {g.id for g in groups}


@pytest.mark.parametrize(
    "variant", ["winding", "rotation", "collinear", "collinear-start", "negative-zero"]
)
def test_identical_region_numbers_ignore_representation_and_selection_order(variant):
    points = [(0, 0), (20, 0), (20, 30), (0, 30)]
    if variant == "winding":
        points.reverse()
    elif variant == "rotation":
        points = points[2:] + points[:2]
    elif variant == "collinear":
        points.insert(1, (10, 0))
    elif variant == "collinear-start":
        points = [(10, 0), *points[1:], points[0]]
    else:
        points[0] = (-0.0, -0.0)
    other = box(50, 60, 70, 80)
    wanted = selection_number((box(0, 0, 20, 30), other))
    assert wanted == selection_number((other, Polygon(points), other))
    assert wanted.isdigit() and len(wanted) == 29
    assert wanted != selection_number((other,))
    assert wanted != selection_number((other, box(1e-9, 0, 20, 30)))


def test_holes_and_open_contour_fallback_have_exact_distinct_identities():
    hole = box(5, 5, 10, 10)
    area = Polygon(box(0, 0, 30, 30).exterior.coords, [hole.exterior.coords])
    reverse = Polygon(tuple(area.exterior.coords)[::-1], [tuple(hole.exterior.coords)[::-1]])
    assert selection_number((area,)) == selection_number((reverse,))
    assert selection_number((area,)) != selection_number((box(0, 0, 30, 30),))
    edge = ((10.0, 20.0), (30.0, 40.0))
    assert selection_number((), fallback_edges=(edge,)) == selection_number(
        (), fallback_edges=(edge[::-1],)
    )
    assert selection_number((), fallback_edges=(edge,)) != selection_number(())


def test_long_unicode_prefixes_leave_windows_space_for_ids_and_dimensions():
    number = selection_number((box(0, 0, 30, 30),))
    family = export_family("Map" + "\U0001f5fa" * 110, number)
    name = png_filename(family, number, "9" * 29, 32768, 32768)
    assert len(name.encode("utf-16-le")) // 2 <= 255
    assert name.endswith("-32768x32768px.png")


def scene(pair_factory):
    areas = (box(10, 10, 40, 40), box(40, 10, 70, 40), box(100, 60, 140, 100))
    source = pair_factory(
        size=(200, 160),
        grid={"size": 20, "type": 1},
        walls=[
            {"c": [*a, *b], "door": int(i == 0)}
            for i, (a, b) in enumerate(e for p in areas for e in pairwise(p.exterior.coords))
        ],
        name="Unchanged Scene",
        background={"src": "original/path.webp"},
        lights=[{"unchanged": True}],
        tiles=[{"texture": {"src": "keep.webp"}}],
    )
    return Session(source), areas


@pytest.mark.parametrize("include_json", [False, True])
@pytest.mark.parametrize("merge", [False, True])
@pytest.mark.parametrize("grid", [False, True])
def test_package_has_common_stable_ids_exact_sizes_and_optional_json(
    pair_factory, tmp_path, include_json, merge, grid
):
    session, areas = scene(pair_factory)
    selected = areas[:2]
    number = selection_number(selected)
    family = export_family("Upper floor", number)
    original = session.source.image_path.read_bytes(), session.source.json_path.read_bytes()
    output = export_overlays(
        session,
        tmp_path,
        selected_polygons=selected,
        export_name="Upper floor",
        include_json=include_json,
        merge_adjacent=merge,
        size_to_grid=grid,
    )
    assert output.name == family + "-overlays"
    pngs = tuple(output.glob("*.png"))
    assert len(pngs) == (1 if merge else 2)
    for path in pngs:
        assert path.name.startswith(family + "-")
        with Image.open(path) as image:
            assert path.name.endswith(f"-{image.width}x{image.height}px.png")
            assert image.info["DALE.SelectionId"] == number
    if include_json:
        assert (output / f"{family}.json").read_bytes() == repaired_json_bytes(session)[0]
        manifest = json.loads((output / f"{family}-placement.json").read_text())
        assert manifest["selection_id"] == number
        assert {item["file"] for item in manifest["items"]} == {p.name for p in pngs}
        assert {item["region_id"] for item in manifest["items"]} == (
            {number} if merge else {selection_number((p,)) for p in selected}
        )
        assert len(tuple(output.glob("*.json"))) == 2
    else:
        assert not tuple(output.glob("*.json"))
    assert original == (
        session.source.image_path.read_bytes(),
        session.source.json_path.read_bytes(),
    )
    assert not session.operations


def test_different_selected_sets_append_without_unrelated_overwrite_questions(
    pair_factory, tmp_path
):
    session, areas = scene(pair_factory)
    output = tmp_path / "Assets"

    def conflict(path):
        pytest.fail(f"Unexpected conflict for another selection: {path.name}")

    export_overlays(
        session, tmp_path, selected_polygons=areas[:1], target_directory=output, conflict=conflict
    )
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    export_overlays(
        session, tmp_path, selected_polygons=areas[1:2], target_directory=output, conflict=conflict
    )
    export_overlays(
        session, tmp_path, selected_polygons=areas[:2], target_directory=output, conflict=conflict
    )
    assert all((output / name).read_bytes() == data for name, data in before.items())
    assert len(tuple(output.glob("*-placement.json"))) == 3


def test_reopened_geometry_and_reordered_selection_keep_names_after_unrelated_edits(
    pair_factory, tmp_path
):
    session, areas = scene(pair_factory)
    first = export_overlays(session, tmp_path, selected_polygons=areas[:2])
    archive = tmp_path / "Stable.dale"
    save_project(session, archive)
    with load_project(archive) as loaded:
        loaded.session.add(Stroke(((120, 80),), 3))
        loaded.session.contour_offset = 2
        second = export_overlays(loaded.session, tmp_path, selected_polygons=areas[1::-1])
        a = json.loads(next(first.glob("*-placement.json")).read_text())
        b = json.loads(next(second.glob("*-placement.json")).read_text())
        assert a["selection_id"] == b["selection_id"]
        assert {p["region_id"] for p in a["items"]} == {p["region_id"] for p in b["items"]}
        assert (
            next(first.glob("*-placement.json")).name == next(second.glob("*-placement.json")).name
        )


@pytest.mark.parametrize("include_json", [False, True])
def test_optional_scene_json_failure_cannot_publish_partial_pngs(
    pair_factory, tmp_path, monkeypatch, include_json
):
    import dale.overlay_export as module

    session, areas = scene(pair_factory)
    output = tmp_path / "Assets"
    output.mkdir()
    untouched = output / "Unrelated.json"
    untouched.write_bytes(b"unchanged")
    monkeypatch.setattr(
        module,
        "repaired_json_bytes",
        lambda s: (_ for _ in ()).throw(ValueError("Synthetic JSON failure")),
    )
    if include_json:
        with pytest.raises(ValueError, match="Synthetic JSON"):
            export_overlays(session, tmp_path, target_directory=output, include_json=True)
        assert tuple(output.iterdir()) == (untouched,)
    else:
        export_overlays(session, tmp_path, target_directory=output, include_json=False)
        assert tuple(output.glob("*.png"))
        assert tuple(output.glob("*.json")) == (untouched,)
    assert untouched.read_bytes() == b"unchanged"


def test_inward_offset_split_keeps_two_same_sized_pngs_with_distinct_stable_names(
    pair_factory, tmp_path
):
    from shapely.ops import unary_union

    area = unary_union((box(10, 10, 50, 50), box(80, 10, 120, 50), box(50, 28, 80, 32)))
    source = pair_factory(
        size=(160, 100), walls=[{"c": [*a, *b]} for a, b in pairwise(area.exterior.coords)]
    )
    session = Session(source, contour_offset=-3)
    family = export_family("source", selection_number(session.analysis().cells))
    output = export_overlays(session, tmp_path)
    assert output.name == family + "-overlays"
    manifest = json.loads((output / f"{family}-placement.json").read_text())
    assert len(manifest["items"]) == len(tuple(output.glob("*.png"))) == 2
    assert len({p["file"] for p in manifest["items"]}) == 2
    assert len({p["region_id"] for p in manifest["items"]}) == 2
    assert len({(p["width"], p["height"]) for p in manifest["items"]}) == 1
    assert len({p["x"] for p in manifest["items"]}) == 2


def test_all_selection_number_keeps_regions_eroded_completely_by_artwork_offset(
    pair_factory, tmp_path
):
    areas = (box(10, 10, 60, 60), box(100, 10, 104, 14))
    source = pair_factory(
        size=(160, 100),
        walls=[{"c": [*a, *b]} for p in areas for a, b in pairwise(p.exterior.coords)],
    )
    session = Session(source, contour_offset=-3)
    expected = selection_number(session.analysis().cells)
    output = export_overlays(session, tmp_path)
    manifest = json.loads(next(output.glob("*-placement.json")).read_text())
    assert manifest["selection_id"] == expected
    assert len(manifest["items"]) == 1


def test_exact_repeated_selection_cannot_overwrite_another_staged_region(pair_factory, tmp_path):
    session, areas = scene(pair_factory)
    output = export_overlays(session, tmp_path, selected_polygons=(areas[0], areas[0]))
    manifest = json.loads(next(output.glob("*-placement.json")).read_text())
    assert manifest["selection_id"] == selection_number((areas[0],))
    assert len(manifest["items"]) == len(tuple(output.glob("*.png"))) == 1


def test_image_only_package_contains_current_dale_contours_when_json_is_enabled(
    pair_factory, tmp_path
):
    from dale.editing import add_rectangle
    from dale.scene import load_pair

    source = pair_factory()
    session = Session(load_pair(source.image_path, None))
    session.add(add_rectangle(session.geometry(), (10, 20), (60, 80)))
    output = export_overlays(session, tmp_path)
    family = export_family("source", selection_number(session.analysis().cells))
    assert load_pair(None, output / f"{family}.json").walls == session.walls
    assert len(tuple(output.glob("*.json"))) == 2
