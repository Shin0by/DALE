import math

import pytest
from shapely.geometry import LineString
from shapely.ops import unary_union

from dale.autoclose import AutoCloseIndex
from dale.geometry import analyze_regions
from dale.session import GeometryEdit


def test_cursor_traces_gap_reachable_chain_without_changing_distant_group():
    geometry = GeometryEdit(
        (
            ((0, 0), (100, 0)),
            ((104, 0), (200, 0)),
            ((205, 0), (300, 0)),
            ((1000, 0), (1100, 0)),
            ((1104, 0), (1200, 0)),
        )
    )
    plan = AutoCloseIndex(geometry, 5).at((50, 1))
    assert len(plan.segments) == 3
    assert plan.extensions == (
        ((100, 0), (102, 0)),
        ((104, 0), (102, 0)),
        ((200, 0), (202.5, 0)),
        ((205, 0), (202.5, 0)),
    )
    result = plan.apply(geometry)
    assert len(result.walls) == len(geometry.walls)
    assert result.walls[-2:] == geometry.walls[-2:]
    assert result.walls[:3] == (((0, 0), (102, 0)), ((102, 0), (202.5, 0)), ((202.5, 0), (300, 0)))
    assert not AutoCloseIndex(geometry, 3).at((50, 1)).extensions
    assert not AutoCloseIndex(geometry, 5).at((500, 100)).segments


def test_closed_contour_extends_existing_line_without_extra_connector():
    geometry = GeometryEdit(
        (((0, 0), (100, 0)), ((100, 0), (100, 100)), ((100, 100), (0, 100)), ((0, 100), (0, 4)))
    )
    plan = AutoCloseIndex(geometry, 4).at((50, 0))
    assert plan.extensions == (((0, 4), (0, 0)),)
    result = plan.apply(geometry)
    assert len(result.walls) == len(geometry.walls)
    assert result.walls[-1] == ((0, 100), (0, 0))
    assert analyze_regions(result.walls).area.area == 10000
    assert not AutoCloseIndex(result, 4).at((50, 0)).extensions


def test_multiple_tips_extend_in_their_own_directions_to_a_target_segment():
    geometry = GeometryEdit(
        (((0, 0), (100, 0)), ((50, 6), (50, 50)), ((40, 6), (40, 50)), ((46, 3), (46, 80)))
    )
    plan = AutoCloseIndex(geometry, 6).at((10, 0))
    assert ((50, 6), (50, 0)) in plan.extensions
    assert ((46, 3), (46, 0)) in plan.extensions
    assert ((40, 6), (40, 0)) in plan.extensions
    assert ((46, 3), (50, 6)) not in plan.extensions  # No diagonal shortcuts.


def test_corner_repair_extends_both_vectors_to_future_intersection():
    geometry = GeometryEdit((((0, 0), (100, 0)), ((104, 4), (104, 100))))
    plan = AutoCloseIndex(geometry, 4).at((50, 0))
    assert len(plan.segments) == 2
    assert plan.extensions == (((100, 0), (104, 0)), ((104, 4), (104, 0)))
    result = plan.apply(geometry)
    assert result.walls == (((0, 0), (104, 0)), ((104, 0), (104, 100)))
    assert not AutoCloseIndex(geometry, 3).at((50, 0)).extensions


def test_skew_corner_and_rays_pointing_away_are_not_replaced_by_diagonal_bridge():
    geometry = GeometryEdit((((0, 0), (10, 5)), ((12, 9), (12, 20))))
    plan = AutoCloseIndex(geometry, 4).at((5, 2.5))
    assert plan.extensions == (((10, 5), (12, 6)), ((12, 9), (12, 6)))
    assert plan.apply(geometry).walls == (((0, 0), (12, 6)), ((12, 6), (12, 20)))
    away = GeometryEdit((((0, 0), (10, 0)), ((6, 4), (6, 100))))
    plan = AutoCloseIndex(away, 5).at((10, 0))
    assert plan.extensions == (((6, 4), (6, 0)),)
    assert plan.retractions == (((10, 0), (6, 0)),)
    assert plan.apply(away).walls == (((0, 0), (6, 0)), ((6, 0), (6, 100)))


def test_offset_parallel_lines_are_not_connected_by_a_sideways_shortcut():
    geometry = GeometryEdit((((0, 0), (100, 0)), ((104, 2), (200, 2))))
    assert not AutoCloseIndex(geometry, 5).at((50, 0)).extensions


def test_endpoint_to_segment_extends_existing_line_and_splits_target_without_moving_it():
    geometry = GeometryEdit((((0, 0), (100, 0)), ((50, 4), (50, 50))))
    plan = AutoCloseIndex(geometry, 5).at((10, 0))
    assert plan.extensions == (((50, 4), (50, 0)),)
    result = plan.apply(geometry)
    assert ((0, 0), (50, 0)) in result.walls
    assert ((50, 0), (100, 0)) in result.walls
    assert ((50, 0), (50, 50)) in result.walls
    assert len(result.walls) == 3  # Target split; no separate short connector.
    original = unary_union([LineString(edge) for edge in geometry.walls])
    updated = unary_union([LineString(edge) for edge in result.walls])
    assert original.difference(updated).is_empty


def test_angled_projection_traces_the_target_through_floating_point_roundoff():
    geometry = GeometryEdit((((13, 17), (113, 73)), ((57, 45), (42, 110))))
    plan = AutoCloseIndex(geometry, 5).at((30, 26.52))
    assert len(plan.segments) == 2
    assert len(plan.extensions) == 1
    updated = plan.apply(geometry)
    assert len(updated.walls) == 3
    original = unary_union([LineString(edge) for edge in geometry.walls])
    changed = unary_union([LineString(edge) for edge in updated.walls])
    assert original.difference(changed.buffer(1e-7)).is_empty


def test_editor_paths_and_all_lines_within_cursor_radius_are_included():
    geometry = GeometryEdit(
        (((0, 0), (100, 0)),),
        (((104, 0), (200, 0)), ((0, 3), (100, 3))),
    )
    plan = AutoCloseIndex(geometry, 4).at((50, 1))
    assert len(plan.segments) == 3
    assert ((100, 0), (102, 0)) in plan.extensions
    result = plan.apply(geometry)
    assert result.closures == (((102, 0), (200, 0)), geometry.closures[1])


@pytest.mark.parametrize("distance", [0, 2])
def test_empty_geometry_has_no_targets(distance):
    assert not AutoCloseIndex(GeometryEdit(()), distance).at((0, 0)).extensions


def test_touching_t_junction_is_committed_as_a_shared_vertex_without_extension():
    geometry = GeometryEdit((((0, 0), (100, 0)), ((50, 0), (50, 50))))
    plan = AutoCloseIndex(geometry, 5).at((10, 0))
    assert not plan.extensions
    assert plan.connections == ((50, 0),)
    assert plan.apply(geometry).walls == (
        ((0, 0), (50, 0)),
        ((50, 0), (100, 0)),
        ((50, 0), (50, 50)),
    )


def test_sub_epsilon_gap_keeps_both_tips_in_the_same_plan_and_really_closes():
    geometry = GeometryEdit((((0, 0), (100, 0)), ((100 + 1e-10, 0), (200, 0))))
    plan = AutoCloseIndex(geometry, 1).at((50, 0))
    assert len(plan.segments) == 2
    assert len(plan.extensions) == 2
    result = plan.apply(geometry)
    assert result.walls[0][1] == result.walls[1][0]


@pytest.mark.parametrize("distance", [-1, math.nan, math.inf])
def test_invalid_distance_is_rejected(distance):
    with pytest.raises(ValueError, match="distance"):
        AutoCloseIndex(GeometryEdit(()), distance)


@pytest.mark.parametrize("distance,expected", [(1.99, False), (2, True), (3, True)])
def test_two_overshooting_ends_shorten_to_intersection_within_exact_tolerance(distance, expected):
    geometry = GeometryEdit((((0, 0), (12, 0)), ((10, -10), (10, 2))))
    plan = AutoCloseIndex(geometry, distance).all()
    assert not plan.extensions
    if expected:
        assert plan.retractions == (((10, 2), (10, 0)), ((12, 0), (10, 0)))
        result = plan.apply(geometry)
        assert result.walls == (((0, 0), (10, 0)), ((10, -10), (10, 0)))
        assert result.lineage == geometry.lineage
        assert not AutoCloseIndex(result, distance).all().endpoint_moves
    else:
        assert not plan.retractions


def test_tip_shortens_to_existing_segment_without_trimming_ambiguous_midpoint_target():
    geometry = GeometryEdit((((0, 0), (12, 0)), ((10, -5), (10, 5))))
    plan = AutoCloseIndex(geometry, 5).all()
    assert plan.retractions == (((12, 0), (10, 0)),)
    result = plan.apply(geometry)
    assert ((0, 0), (10, 0)) in result.walls
    assert ((10, -5), (10, 0)) in result.walls
    assert ((10, 0), (10, 5)) in result.walls


def test_shortenings_remain_on_skew_vectors():
    geometry = GeometryEdit((((0, 0), (12, 6)), ((10, -20), (10, 7))))
    plan = AutoCloseIndex(geometry, 2.3).all()
    assert len(plan.retractions) == 2
    result = plan.apply(geometry)
    assert result.walls[0][1] == pytest.approx((10, 5))
    assert result.walls[1][1] == pytest.approx((10, 5))
    assert all(math.dist(a, b) <= 2.3 for a, b in plan.retractions)


def test_trim_stops_at_nearest_existing_contact_without_losing_an_intervening_branch():
    geometry = GeometryEdit((((0, 0), (12, 0)), ((10, 2), (10, 100)), ((11, -50), (11, 50))))
    plan = AutoCloseIndex(geometry, 2).all()
    assert ((12, 0), (11, 0)) in plan.retractions
    assert ((12, 0), (10, 0)) not in plan.retractions
    updated = unary_union([LineString(edge) for edge in plan.apply(geometry).walls])
    assert updated.covers(LineString(((0, 0), (11, 0))))


def test_short_native_segment_is_not_collapsed_into_existing_contact():
    geometry = GeometryEdit((((0, 0), (2, 0)), ((0, -10), (0, 10))))
    plan = AutoCloseIndex(geometry, 3).all()
    assert not plan.retractions
    assert geometry.walls[0] in plan.apply(geometry).walls


def test_cursor_local_trim_does_not_change_distant_overshoot():
    geometry = GeometryEdit(
        (((0, 0), (12, 0)), ((10, -10), (10, 2)), ((100, 0), (112, 0)), ((110, -10), (110, 2)))
    )
    plan = AutoCloseIndex(geometry, 2).at((5, 0))
    assert len(plan.retractions) == 2
    assert plan.apply(geometry).walls[-2:] == geometry.walls[-2:]
