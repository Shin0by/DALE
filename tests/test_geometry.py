import math
import random

import pytest
from shapely.geometry import box

from dale.geometry import analyze_regions, nearest_source, offset_region
from dale.session import Closure, ContourMask, Session, Stroke


@pytest.mark.parametrize("scale,shift", [(1, 0), (1, 8000), (0.01, 50), (100, 100000)])
def test_projected_wall_endpoint_stays_closed_while_sliding_on_angled_wall(scale, shift):
    from dale.editing import project

    def point(x, y):
        return x * scale + shift, y * scale + shift

    target = (point(39.9832, 182.7731), point(1101.3927, 519.2221))
    corner = point(334.2481, 702.3419)
    for index in range(20, 181):
        cursor = tuple(
            target[0][axis] + (target[1][axis] - target[0][axis]) * index / 200 for axis in (0, 1)
        )
        snapped, _ = project((cursor[0] - 2 * scale, cursor[1] + 3 * scale), target)
        walls = (target, (target[0], corner), (corner, snapped))
        before = tuple(walls)
        result = analyze_regions(walls)
        assert result.faces == 1, (index, snapped)
        assert result.area.area > 0
        assert len(result.unresolved) == 1
        assert walls == before  # Contact reconciliation is analysis-only.


def test_nearby_wall_gaps_and_parallel_lines_are_not_closed_by_contact_roundoff():
    target = ((0, 0), (100, 50))
    for gap in (1e-5, 1e-3, 1, 10):
        walls = (target, ((0, 0), (0, -20)), ((0, -20), (50, 25 - gap)))
        assert analyze_regions(walls).faces == 0


def test_snap_projects_to_segment_interior_and_obeys_tolerance():
    walls = (((0, 0), (100, 0)),)
    assert nearest_source((43, 3), walls, 5) == (43, 0)
    assert nearest_source((43, 6), walls, 5) is None


def test_polyline_closes_open_boundary_without_writing_json(pair_factory):
    source = pair_factory(walls=[{"c": [0, 0, 100, 0]}, {"c": [100, 0, 100, 100]}])
    before = source.json_path.read_bytes()
    session = Session(source)
    assert session.analysis().faces == 0
    session.add(Closure(((100, 100), (60, 120), (0, 100), (0, 0))))
    assert session.analysis().faces == 1
    assert session.analysis().area.area == pytest.approx(11000)
    assert source.json_path.read_bytes() == before
    session.undo()
    assert session.analysis().faces == 0
    session.redo()
    assert session.analysis().faces == 1


def test_closure_snapped_to_middle_of_walls_nodes_intersections():
    walls = (((0, 0), (100, 0)), ((100, 0), (100, 100)), ((100, 100), (0, 100)))
    result = analyze_regions(walls, (((50, 0), (50, 100)),))
    assert result.faces == 1
    assert result.area.area == 5000
    assert len(result.unresolved) == 2


def test_multiple_rooms_and_crossings_are_noded():
    walls = (
        ((0, 0), (100, 0)),
        ((100, 0), (100, 100)),
        ((100, 100), (0, 100)),
        ((0, 100), (0, 0)),
        ((50, 0), (50, 100)),
        ((0, 50), (100, 50)),
    )
    result = analyze_regions(walls)
    assert result.faces == 4
    assert result.area.area == 10000
    assert not result.unresolved


def test_projected_closures_on_angled_walls_survive_floating_point_epsilon():
    rng = random.Random(42)
    for _ in range(100):
        angle = rng.random() * 6
        ax, ay = rng.random() * 100, rng.random() * 100
        ux, uy = math.cos(angle) * 100, math.sin(angle) * 100
        vx, vy = -uy, ux
        a, b = (ax, ay), (ax + ux, ay + uy)
        c, d = (ax + ux + vx, ay + uy + vy), (ax + vx, ay + vy)
        t = rng.random()
        start = nearest_source((ax + ux * t + 0.1, ay + uy * t + 0.2), ((a, b),), 10)
        end = nearest_source((d[0] + ux * t + 0.1, d[1] + uy * t + 0.2), ((d, c),), 10)
        result = analyze_regions(((a, b), (b, c), (c, d)), ((start, end),))
        assert result.faces == 1
        assert result.area.area > 0


def test_undo_stroke_and_branch_discards_redo(pair_factory):
    session = Session(pair_factory())
    mask = ContourMask(session.analysis().area, "outside")
    stroke = Stroke(((20, 20), (30, 30)), 5)
    session.add(mask)
    session.add(stroke)
    session.undo()
    assert session.operations == [mask]
    session.add(Stroke(((40, 40),), 2))
    session.redo()
    assert len(session.operations) == 2
    assert not session.future


@pytest.mark.parametrize("tolerance, faces", [(0, 0), (2.99, 0), (3, 1), (4, 1)])
def test_small_endpoint_gap_closes_only_within_explicit_tolerance(tolerance, faces):
    walls = (((0, 0), (100, 0)), ((100, 0), (100, 100)), ((100, 100), (0, 100)), ((0, 100), (0, 3)))
    result = analyze_regions(walls, gap_tolerance=tolerance)
    assert result.faces == faces
    assert len(result.joins) == faces
    assert walls[-1][-1] == (0, 3)


@pytest.mark.parametrize("gap", [0, 3])
def test_t_junction_uses_the_middle_of_a_long_wall(gap):
    walls = (
        ((0, 0), (100, 0)),
        ((100, 0), (100, 100)),
        ((100, 100), (0, 100)),
        ((50, 100), (50, gap)),
    )
    result = analyze_regions(walls, gap_tolerance=gap)
    assert result.faces == 1
    assert result.area.area == pytest.approx(5000)
    assert len(result.joins) == (1 if gap else 0)
    if gap:
        assert result.joins[0] == ((50, 3), (50, 0))
        assert analyze_regions(walls, gap_tolerance=2.99).faces == 0


def test_long_gap_is_not_repaired_and_zero_disables_joining():
    walls = (
        ((0, 0), (100, 0)),
        ((100, 0), (100, 100)),
        ((100, 100), (0, 100)),
        ((0, 100), (0, 20)),
    )
    assert analyze_regions(walls, gap_tolerance=3).faces == 0
    assert not analyze_regions(walls).joins


@pytest.mark.parametrize("tolerance", [-1, float("nan"), float("inf")])
def test_invalid_gap_tolerance_is_rejected(tolerance):
    with pytest.raises(ValueError, match="tolerance"):
        analyze_regions((), gap_tolerance=tolerance)


def test_signed_offset_expands_or_contracts_without_changing_original_area():
    original = box(10, 20, 60, 270)
    assert offset_region(original, 5).bounds == (5, 15, 65, 275)
    assert offset_region(original, -5).bounds == (15, 25, 55, 265)
    assert original.bounds == (10, 20, 60, 270)
    with pytest.raises(ValueError, match="No enclosed"):
        offset_region(original, -30)


def test_mask_snapshots_keep_gap_and_offset_edits_out_of_source_json(pair_factory):
    source = pair_factory(
        walls=[
            {"c": [10, 20, 60, 20]},
            {"c": [60, 20, 60, 270]},
            {"c": [60, 270, 10, 270]},
            {"c": [10, 270, 10, 23]},
        ]
    )
    before = source.json_path.read_bytes()
    session = Session(source, gap_tolerance=3, contour_offset=5)
    mask = session.make_mask("outside")
    assert mask.area.bounds == (5, 15, 65, 275)
    session.add(mask)
    session.gap_tolerance = 0
    session.contour_offset = -10
    assert session.analysis().faces == 0
    assert mask.area.bounds == (5, 15, 65, 275)
    assert source.json_path.read_bytes() == before
    session.undo()
    assert not session.operations
