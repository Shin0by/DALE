"""Export-only perimeter merging, native ownership and PNG grouping."""

import json

import pytest
from shapely import LineString
from shapely.geometry import box
from test_overlay_export import _rectangle

from dale.export_contours import merge_selected_perimeters
from dale.json_repair import repaired_json_bytes
from dale.overlay_export import export_overlays
from dale.raster import ExportCancelled
from dale.session import Session


@pytest.mark.parametrize("enabled, count", [(False, 3), (True, 2)])
@pytest.mark.parametrize("include_json", [False, True])
def test_export_merges_png_and_json_only_when_enabled(
    pair_factory, tmp_path, enabled, count, include_json
):
    walls = _rectangle(10, 10, 30, 40) + _rectangle(40, 10, 30, 40) + _rectangle(100, 10, 20, 40)
    session = Session(pair_factory(size=(150, 100), walls=walls))
    original = session.geometry()
    source_bytes = session.source.json_bytes
    folder = export_overlays(
        session,
        tmp_path,
        region_indices=(0, 1, 2),
        individual_regions=True,
        merge_contours=enabled,
        include_json=include_json,
    )
    assert len(list(folder.glob("*.png"))) == count
    scenes = [p for p in folder.glob("*.json") if not p.name.endswith("-placement.json")]
    assert len(scenes) == int(include_json)
    if include_json:
        result = json.loads(scenes[0].read_bytes())
        divider = [w for w in result["walls"] if w["c"][0] == w["c"][2] == 40]
        assert bool(divider) is not enabled
        assert {k: v for k, v in result.items() if k != "walls"} == {
            k: v for k, v in session.source.raw.items() if k != "walls"
        }
    assert session.geometry() == original and not session.operations
    assert session.source.json_bytes == source_bytes


def test_perimeter_clips_crossing_wall_preserves_outside_properties_and_gaps(pair_factory):
    crossing = {
        "_id": "CrossingWall0001",
        "c": [0, 30, 90, 30],
        "door": 1,
        "flags": {"wall-height": {"bottom": -2, "top": 9}},
    }
    session = Session(pair_factory(walls=[crossing, {"c": [80, 80, 90, 90]}]))
    group = (box(10, 10, 40, 50), box(40, 10, 70, 50))
    result = merge_selected_perimeters(session, (group,))
    walls = json.loads(repaired_json_bytes(result)[0])["walls"]
    parts = [w for w in walls if w.get("door") == 1]
    assert {tuple(w["c"]) for w in parts} == {(0, 30, 10, 30), (70, 30, 90, 30)}
    assert all(w["flags"] == crossing["flags"] for w in parts)
    assert any(w["c"] == [80, 80, 90, 90] for w in walls)
    assert session.operations == []
    assert merge_selected_perimeters(session, ((group[0],), (group[1],))) is session
    with pytest.raises(ExportCancelled):
        merge_selected_perimeters(session, (group,), cancelled=lambda: True)


def test_union_preserves_unselected_hole_and_its_perimeter(pair_factory):
    groups = ((box(0, 0, 30, 10), box(0, 20, 30, 30), box(0, 10, 10, 20), box(20, 10, 30, 20)),)
    session = Session(pair_factory(walls=_rectangle(10, 10, 10, 10) + [{"c": [0, 10, 30, 10]}]))
    result = merge_selected_perimeters(session, groups)
    edges = [LineString(edge) for edge in result.geometry().walls]
    assert all(
        any(edge.covers(LineString(wall)) for edge in edges)
        for wall in session.geometry().walls[:4]
    )
