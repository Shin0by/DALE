import math

import pytest

from dale.editing import (
    GuideTargets,
    LineEraser,
    add_circle,
    add_line,
    align_orthogonal_point,
    alignment_points,
    circle_points,
    delete_vertex,
    erase_geometry,
    geometry_targets,
    hit_edge,
    insert_vertex,
    move_vertex,
    right_angle_constraints,
    right_angle_point,
    snap_constrained_point,
    snap_point,
    vertices,
)
from dale.geometry import open_contour_count
from dale.session import Closure, GeometryEdit, Session


@pytest.mark.parametrize(
    "point,guide,edge,expected",
    [
        ((295, 100), (1, (400, 100)), ((300, 0), (300, 200)), (300, 100)),
        ((100, 295), (0, (100, 400)), ((0, 300), (200, 300)), (100, 300)),
        ((295, 100), (1, (400, 100)), ((250, 100), (350, 100)), (295, 100)),
        ((295, 100), (1, (400, 100)), ((300, 110), (300, 200)), None),
        ((295, 100), (1, (400, 100)), ((250, 101), (350, 101)), None),
    ],
)
def test_constrained_snap_intersects_guides_without_extending_target_segments(
    point, guide, edge, expected
):
    geometry = GeometryEdit((edge,))
    assert snap_constrained_point(geometry, point, 14, guides=(guide,)) == expected


def test_constrained_snap_skips_incompatible_vertices_and_keeps_compatible_vertex_priority():
    geometry = GeometryEdit((((300, 0), (300, 200)), ((294, 102), (294, 160))))
    guide = ((1, (400, 100)),)
    assert snap_constrained_point(geometry, (295, 100), 14, guides=guide) == (300, 100)
    geometry = add_line(geometry, (303, 100), (350, 150))
    assert snap_constrained_point(geometry, (295, 100), 14, guides=guide) == (303, 100)


@pytest.mark.parametrize(
    "edge,expected",
    [
        (((25, -10), (25, 10)), (25, 0)),
        (((25, 10), (25, 20)), None),
    ],
)
def test_constrained_snap_keeps_right_angle_at_stationary_neighbour(edge, expected):
    angle = ((0, -100), (0, 0), (20, 0))
    assert snap_constrained_point(GeometryEdit((edge,)), (20, 0), 6, angle=angle) == expected


def test_constrained_snap_keeps_right_angle_at_dragged_vertex_with_circle_intersection():
    geometry = GeometryEdit((((6, 0), (6, 20)),))
    angle = ((-10, 0), (0, 10), (10, 0))
    assert snap_constrained_point(geometry, (0, 10), 7, angle=angle) == pytest.approx((6, 8))
    assert snap_constrained_point(geometry, (0, 10), 6, angle=angle) is None
    assert snap_constrained_point(geometry, (0, 10), 7, angle=angle, guides=((0, (0, 20)),)) is None


def test_constrained_snap_respects_zero_tolerance_own_edge_exclusion_and_both_axes():
    geometry = GeometryEdit((((0, 10), (40, 10)), ((30, 0), (30, 20))))
    guides = ((0, (30, 50)), (1, (50, 10)))
    assert snap_constrained_point(geometry, (30, 10), 14, guides=guides, exclude=(20, 10)) == (
        30,
        10,
    )
    assert snap_constrained_point(geometry, (30, 10), 0, guides=guides) is None
    assert snap_constrained_point(geometry, (30, 10), 14, guides=guides, exclude=(30, 10)) is None


@pytest.mark.parametrize("preferred", [(0, 0), (10, 0)])
def test_right_angle_uses_cursor_when_axis_guides_collapse_a_leg_or_land_on_circle_center(
    preferred,
):
    geometry = GeometryEdit((((-10, 0), (0, 10)), ((0, 10), (10, 0))))
    target, angle = right_angle_point((1, 10), preferred, (0, 10), ((-10, 0), (10, 0)), geometry, 5)
    assert target == pytest.approx((10 / math.sqrt(101), 100 / math.sqrt(101)))
    assert angle[1] == target


def test_alignment_uses_both_neighbours_and_farther_points_in_same_contour():
    geometry = GeometryEdit(
        (
            ((40, 40), (140, 120)),
            ((140, 120), (160, 160)),
            ((160, 160), (210, 40)),
            ((158, 43), (158, 90)),
        )
    )
    anchors = alignment_points(geometry, (140, 120))
    assert set(anchors) == {(40, 40), (160, 160), (210, 40)}
    destination, guides = align_orthogonal_point((157, 43), anchors, 4)
    assert destination == (160, 40)
    assert set(guides) == {(0, (160, 160)), (1, (40, 40))}
    assert align_orthogonal_point((208, 80), anchors, 4)[0] == (210, 80)


def test_alignment_without_nearby_anchors_is_free():
    assert align_orthogonal_point((170, 140), (), 4) == ((170, 140), ())


@pytest.mark.parametrize("rotation", [0, 27, 81])
def test_right_angle_is_relative_to_adjacent_segments_not_map(rotation):
    def rotated(p):
        angle = math.radians(rotation)
        return (
            p[0] * math.cos(angle) - p[1] * math.sin(angle),
            p[0] * math.sin(angle) + p[1] * math.cos(angle),
        )

    a, vertex, b, cursor = map(rotated, ((40, 40), (140, 120), (160, 160), (157, 43)))
    geometry = GeometryEdit(((a, vertex), (vertex, b)))
    target, joint = right_angle_point(cursor, cursor, vertex, (a, b), geometry, 5)
    assert joint is not None and math.dist(cursor, target) <= 5
    assert sum((a[i] - target[i]) * (b[i] - target[i]) for i in (0, 1)) == pytest.approx(
        0, abs=1e-8
    )
    assert right_angle_point(cursor, cursor, vertex, (a, b), geometry, 1) == (cursor, None)


def test_terminal_right_angle_follows_stationary_adjacent_line():
    geometry = GeometryEdit((((0, 0), (20, 20)), ((20, 20), (39, 2))))
    target, joint = right_angle_point((39, 2), (39, 2), (39, 2), ((20, 20),), geometry, 2)
    assert target == pytest.approx((38.5, 1.5)) and joint is not None


@pytest.mark.parametrize("rotation", [0, 27, 81])
@pytest.mark.parametrize("side", [-1, 1])
def test_right_angle_can_square_either_stationary_neighbour(rotation, side):
    def turn(p):
        angle = math.radians(rotation)
        return (
            p[0] * math.cos(angle) - p[1] * math.sin(angle),
            p[0] * math.sin(angle) + p[1] * math.cos(angle),
        )

    left, a, vertex, b, right = map(turn, ((0, 0), (20, 20), (40, 0), (60, 20), (80, 0)))
    geometry = GeometryEdit(((left, a), (a, vertex), (vertex, b), (b, right)))
    cursor = turn((40 + side, 2))
    target, guide = right_angle_point(cursor, cursor, vertex, (a, b), geometry, 2)
    assert target == pytest.approx(turn((40 + side * 1.5, 1.5)))
    assert guide[1] == (a if side < 0 else b)
    assert sum(
        (guide[0][i] - guide[1][i]) * (guide[2][i] - guide[1][i]) for i in (0, 1)
    ) == pytest.approx(0, abs=1e-8)
    assert right_angle_point(cursor, cursor, vertex, (b, a), geometry, 2) == (target, guide)


def test_right_angle_checks_the_third_neighbour_and_its_continuation():
    vertex = (40, 0)
    neighbours = ((20, 20), (60, 20), (40, -40))
    geometry = GeometryEdit(tuple((vertex, p) for p in neighbours) + (((40, -40), (0, -40)),))
    target, guide = right_angle_point((41, -10), (41, -10), vertex, neighbours, geometry, 2)
    assert target == (40, -10) and guide[1] == (40, -40)


def test_right_angle_checks_all_incident_pairs_at_a_branched_vertex():
    vertex = (40, 0)
    neighbours = ((0, 0), (80, 0), (40, 80))
    geometry = GeometryEdit(tuple((vertex, p) for p in neighbours))
    target, guide = right_angle_point((61, 21), (61, 21), vertex, neighbours, geometry, 2)
    assert guide is not None and guide[1] == target
    assert {guide[0], guide[2]} == {(0, 0), (40, 80)}


@pytest.mark.parametrize("rotation", [0, 31])
@pytest.mark.parametrize("corner", ["moved", "upper", "lower"])
def test_closed_quadrilateral_offers_all_three_affected_corners(rotation, corner):
    def turn(p):
        angle = math.radians(rotation)
        return (
            140 + p[0] * math.cos(angle) - p[1] * math.sin(angle),
            120 + p[0] * math.sin(angle) + p[1] * math.cos(angle),
        )

    fixed, upper, vertex, lower = map(turn, ((0, 0), (0, 60), (40, 40), (80, 0)))
    geometry = GeometryEdit(((fixed, upper), (upper, vertex), (vertex, lower), (lower, fixed)))
    raw = {"moved": (40, 81), "upper": (40, 61), "lower": (81, 30)}[corner]
    wanted = {"moved": (40, 80), "upper": (40, 60), "lower": (80, 30)}[corner]
    target, guide = right_angle_point(turn(raw), turn(raw), vertex, (upper, lower), geometry, 2)
    assert target == pytest.approx(turn(wanted))
    assert guide[1] == pytest.approx({"moved": target, "upper": upper, "lower": lower}[corner])


@pytest.mark.parametrize("rotation", [0, 27, 81])
@pytest.mark.parametrize("scale", [1, 10, 1000])
def test_right_angle_arc_combines_both_neighbour_angles(rotation, scale):
    def turn(p):
        angle = math.radians(rotation)
        return (
            1234.56 + scale * (p[0] * math.cos(angle) - p[1] * math.sin(angle)),
            7890.12 + scale * (p[0] * math.sin(angle) + p[1] * math.cos(angle)),
        )

    fixed, a, vertex, b = map(turn, ((0, 0), (0, 100), (80, 70), (100, 0)))
    geometry = GeometryEdit(((fixed, a), (a, vertex), (vertex, b), (b, fixed)))
    raw = turn((100.25, 50 + math.sqrt(5000 - 50.25**2)))
    target, guides = right_angle_constraints(raw, raw, vertex, (a, b), geometry, 2)
    assert target == pytest.approx(turn((100, 100)))
    assert len(guides) == 3
    assert {g[1] for g in guides} == {a, b, target}
    assert guides[0][1] == target  # The original closest circle remains primary.
    for left, joint, right in guides:
        dot = sum((left[i] - joint[i]) * (right[i] - joint[i]) for i in (0, 1))
        assert dot == pytest.approx(0, abs=scale**2 * 1e-7)
    assert geometry == GeometryEdit(geometry.walls)
    # Secondary snapping stays angular and is disabled by the existing checkbox.
    free, own = right_angle_constraints(
        raw, raw, vertex, (a, b), geometry, 2, include_neighbours=False
    )
    assert free == pytest.approx(raw) and len(own) == 1
    outside = turn((105, 50 + math.sqrt(5000 - 55**2)))
    free, own = right_angle_constraints(outside, outside, vertex, (a, b), geometry, 2)
    assert free == pytest.approx(outside) and len(own) == 1


def test_combined_angle_loci_include_stationary_pairs_and_branched_moving_pairs():
    vertex, a, b = (40, 40), (0, 50), (100, 0)
    geometry = GeometryEdit((((0, 0), a), (a, vertex), (vertex, b), (b, (150, 50))))
    target, guides = right_angle_constraints(
        (49.7, 50.2), (49.7, 50.2), vertex, (a, b), geometry, 2
    )
    assert target == pytest.approx((50, 50)) and len(guides) == 2
    neighbours = ((0, 100), (100, 0), (200, 100))
    geometry = GeometryEdit(tuple((vertex, p) for p in neighbours))
    target, guides = right_angle_constraints(
        (100.2, 99.8), (100.2, 99.8), vertex, neighbours, geometry, 2, include_neighbours=False
    )
    assert target == pytest.approx((100, 100)) and len(guides) == 2


def test_neighbour_angles_are_also_acquired_from_the_accepted_primary_arc():
    vertex, a, b = (80, 70), (0, 100), (100, 0)
    geometry = GeometryEdit((((0, 0), a), (a, vertex), (vertex, b), (b, (0, 0))))
    # The raw cursor misses the left neighbouring corner by2.25 degrees, but
    # its accepted own-angle projection approaches that corner within2 degrees.
    target, guides = right_angle_constraints((102, 96), (102, 96), vertex, (a, b), geometry, 2)
    assert target == pytest.approx((100, 100)) and len(guides) == 3
    assert guides[0][1] == target


@pytest.mark.parametrize("rotation", [0, 37])
@pytest.mark.parametrize("scale", [1, 20])
@pytest.mark.parametrize("priority", [False, True])
def test_own_angle_priority_controls_incompatible_adjacent_angle(rotation, scale, priority):
    def turn(p):
        radians = math.radians(rotation)
        return (
            123.45 + scale * (p[0] * math.cos(radians) - p[1] * math.sin(radians)),
            678.9 + scale * (p[0] * math.sin(radians) + p[1] * math.cos(radians)),
        )

    fixed, a, vertex, b = map(turn, ((-100, 0), (0, 0), (30, 30), (100, 0)))
    raw = turn((1, math.sqrt(99)))
    geometry = GeometryEdit(((fixed, a), (a, vertex), (vertex, b)))
    target, angles = right_angle_constraints(
        raw, raw, vertex, (a, b), geometry, 6, own_priority=priority
    )
    assert len(angles) == 1
    if priority:
        assert target == pytest.approx(raw) and angles[0][1] == target
    else:
        assert target == pytest.approx(turn((0, math.sqrt(99)))) and angles[0][1] == a
    without_neighbours, _ = right_angle_constraints(
        raw, raw, vertex, (a, b), geometry, 6, include_neighbours=False, own_priority=priority
    )
    assert without_neighbours == pytest.approx(raw)


@pytest.mark.parametrize("priority", [False, True])
@pytest.mark.parametrize("axis", [0, 1])
def test_own_angle_priority_controls_incompatible_axis_guides(priority, axis):
    a, vertex, b = (0, 0), (30, 30), (100, 0)
    geometry = GeometryEdit(((a, vertex), (vertex, b)))
    raw = (1, math.sqrt(99))
    preferred = list(raw)
    preferred[axis] = 0
    target, angles = right_angle_constraints(
        raw,
        tuple(preferred),
        vertex,
        (a, b),
        geometry,
        6,
        include_neighbours=False,
        own_priority=priority,
        guides=((axis, a),),
    )
    if priority:
        assert angles and angles[0][1] == target
        assert target[axis] != 0
    else:
        assert target == pytest.approx(tuple(preferred)) and not angles


@pytest.mark.parametrize("priority", [False, True])
def test_own_angle_priority_preserves_compatible_three_corner_snap(priority):
    vertex, a, b = (80, 70), (0, 100), (100, 0)
    geometry = GeometryEdit((((0, 0), a), (a, vertex), (vertex, b), (b, (0, 0))))
    raw = (100.25, 50 + math.sqrt(5000 - 50.25**2))
    target, angles = right_angle_constraints(
        raw, raw, vertex, (a, b), geometry, 2, own_priority=priority, guides=((0, b), (1, a))
    )
    assert target == pytest.approx((100, 100)) and len(angles) == 3


@pytest.mark.parametrize("priority", [False, True])
def test_new_line_angle_priority_respects_parallel_axis_guide(priority):
    from dale.editing import right_angle_line

    geometry = GeometryEdit((((-100, 0), (0, 0)),))
    target, angle = right_angle_line(
        (10, 100), (10, 100), (0, 0), geometry, 6, own_priority=priority, guides=((0, (10, 0)),)
    )
    assert target == pytest.approx((0, 100) if priority else (10, 100))
    assert (angle is not None) is priority


def test_external_angle_priority_releases_arc_for_a_newly_approached_neighbour():
    a, vertex, b = (0, 0), (30, 30), (100, 0)
    geometry = GeometryEdit((((-100, 0), a), (a, vertex), (vertex, b)))
    # The cursor misses the neighbour's angular tolerance, but the accepted own
    # circle approaches it. External priority must release that circle as well.
    point = (1.2, 10)
    own, angles = right_angle_constraints(point, point, vertex, (a, b), geometry, 6)
    assert own[0] > 1 and angles[0][1] == own
    target, angles = right_angle_constraints(
        point, point, vertex, (a, b), geometry, 6, own_priority=False
    )
    assert target == pytest.approx((0, 10)) and angles[0][1] == a


def test_parallel_angle_constraints_keep_continuous_motion_without_remote_intersections():
    vertex, a, b = (5, 2), (0, 0), (10, 0)
    geometry = GeometryEdit((((0, -10), a), (a, vertex), (vertex, b), (b, (10, -10))))
    for x in (4.9, 5, 5.1):
        target, guides = right_angle_constraints((x, 0.01), (x, 0.01), vertex, (a, b), geometry, 2)
        assert target == pytest.approx((x, 0)) and len(guides) == 2
    # Nearly parallel but incompatible loci must not pull the vertex far away.
    b = (10, 0.01)
    geometry = GeometryEdit((((0, -10), a), (a, vertex), (vertex, b), (b, (10.000001, -10))))
    target, guides = right_angle_constraints((5, 0.001), (5, 0.001), vertex, (a, b), geometry, 2)
    assert target == pytest.approx((5, 0)) and len(guides) == 1


def test_ordinary_snap_cannot_break_a_combined_right_angle():
    point = (100, 100)
    angles = (((0, 100), point, (100, 0)), ((0, 0), (0, 100), point))
    geometry = GeometryEdit((((100.2, 0), (100.2, 200)), ((98, 100.1), (101, 100.1))))
    assert snap_constrained_point(geometry, point, 14, angles=angles) is None
    geometry = add_line(geometry, point, (130, 150))
    assert snap_constrained_point(geometry, point, 14, angles=angles) == point


def test_alignment_can_follow_t_contacts_but_not_disjoint_height_contacts():
    geometry = GeometryEdit((((0, 0), (20, 0)), ((10, 0), (10, 20)), ((10, 20), (40, 25))))
    assert (40, 25) in alignment_points(geometry, (0, 0))
    assert set(alignment_points(geometry, (0, 0), ((0, 10), (10, 20), (10, 20)))) == {(20, 0)}
    assert (40, 25) in alignment_points(geometry, (0, 0), ((0, 20), (10, 20), (10, 20)))


@pytest.mark.parametrize(
    "diameter,count",
    [
        (0.1, 4),
        (0.5, 4),
        (0.51, 6),
        (1, 6),
        (1.01, 8),
        (2, 8),
        (2.01, 10),
        (4.5, 10),
        (5, 12),
        (10, 16),
        (15, 20),
        (20, 24),
        (100, 88),
    ],
)
def test_circular_contour_vertex_density_uses_map_cells(diameter, count):
    radius = diameter * 150
    points = circle_points((100, 200), radius, 300)
    assert len(points) == count + 1 and points[0] == points[-1]
    assert len(set(points[:-1])) == count
    assert all(math.dist(p, (100, 200)) == pytest.approx(radius) for p in points)
    assert circle_points((100, 200), radius, 300) == points


@pytest.mark.parametrize(
    "radius,cell",
    [(0, 100), (-1, 100), (float("nan"), 100), (10, 0), (True, 100), (10, float("inf"))],
)
def test_circular_contour_rejects_invalid_dimensions(radius, cell):
    with pytest.raises(ValueError, match="Circle"):
        circle_points((0, 0), radius, cell)


def test_circle_contact_keeps_source_parents_and_is_one_undoable_geometry(pair_factory):
    source = pair_factory(size=(400, 400), walls=[{"c": [0, 0, 200, 0]}], grid={"size": 200})
    before = source.json_path.read_bytes()
    session = Session(source)
    original = session.geometry()
    circle = add_circle(original, (100, 50), 50, source.cell_pixels)
    assert len(circle.walls) == 6  # Four polygon edges and two pieces of the source wall.
    assert all(record.parents == (original.lineage[0].id,) for record in circle.lineage[:2])
    contacting = [record for record in circle.lineage[2:] if record.sources]
    assert len(contacting) == 2
    assert all(record.sources == original.lineage[0].sources for record in contacting)
    assert add_circle(circle, (100, 50), 50, 200) == circle
    session.add(circle)
    assert session.analysis().faces == 1
    session.undo()
    assert session.geometry() == original
    session.redo()
    assert session.geometry().lineage == circle.lineage
    assert source.json_path.read_bytes() == before


@pytest.mark.parametrize(
    "grid,expected",
    [(300, 300), ({"size": 300}, 300), (None, 100), ({"size": 0}, 100), ({"size": True}, 100)],
)
def test_circle_uses_imported_grid_or_explicit_pixel_fallback(pair_factory, grid, expected):
    assert pair_factory(grid=grid).cell_pixels == expected


def test_circle_density_scales_with_source_grid_and_has_a_safe_vertex_cap(pair_factory):
    source = pair_factory(size=(200, 200), width=400, height=400, grid={"size": 100})
    assert source.cell_pixels == 50
    assert len(circle_points((100, 100), 12.5, source.cell_pixels)) == 5
    assert len(circle_points((0, 0), 16000, 1)) == 4097
    assert len(circle_points((0, 0), 16000, 1e-300)) == 4097


@pytest.mark.parametrize("radius", [20, 40, 75, 200, 16000])
@pytest.mark.parametrize("steps", [0, 1, 2, 95])
def test_circle_detail_increases_automatic_density_without_changing_radius(radius, steps):
    original = circle_points((100, 200), radius, 100)
    points = circle_points((100, 200), radius, 100, detail_steps=steps)
    count = len(points) - 1
    assert len(original) <= len(points) <= 4097 and count % 2 == 0
    assert points[0] == points[-1] == (100 + radius, 200)
    assert points[count // 2] == (100 - radius, 200)
    assert all(math.dist((100, 200), p) == pytest.approx(radius) for p in points)
    if steps == 0:
        assert points == original
    else:
        assert len(points) > len(original)
    assert len(circle_points((0, 0), 16000, 1, detail_steps=steps)) == 4097


@pytest.mark.parametrize("invalid", [-1, 96, True, 1.5, float("inf"), "1", None])
def test_circle_detail_rejects_invalid_steps(invalid):
    with pytest.raises(ValueError, match="Circle detail"):
        circle_points((100, 100), 50, detail_steps=invalid)


@pytest.mark.parametrize("radius,base,enhanced", [(20, 4, 80), (800, 20, 400)])
def test_circle_twentyfold_detail_multiplies_the_current_radius_baseline(radius, base, enhanced):
    assert len(circle_points((100, 100), radius)) - 1 == base
    assert len(circle_points((100, 100), radius, detail_steps=95)) - 1 == enhanced


def test_insert_drag_and_remove_wall_vertex_preserves_its_neighbors():
    geometry = GeometryEdit((((0, 0), (100, 0)),))
    inserted = insert_vertex(geometry, hit_edge(geometry, (40, 2), 5))
    assert inserted.walls == (((0, 0), (40, 0)), ((40, 0), (100, 0)))
    moved = move_vertex(inserted, (40, 0), (40, 30))
    assert moved.walls == (((0, 0), (40, 30)), ((40, 30), (100, 0)))
    assert delete_vertex(moved, (40, 30)).walls == geometry.walls
    assert geometry.walls == (((0, 0), (100, 0)),)


def test_point_editing_also_handles_temporary_polylines():
    geometry = GeometryEdit((), (((0, 0), (100, 0), (100, 100)),))
    hit = hit_edge(geometry, (30, 1), 5)
    inserted = insert_vertex(geometry, hit)
    assert inserted.closures[0] == ((0, 0), (30, 0), (100, 0), (100, 100))
    moved = move_vertex(inserted, (30, 0), (30, 20))
    assert moved.closures[0][1] == (30, 20)
    assert delete_vertex(moved, (30, 20)).closures == geometry.closures


def test_dragging_t_node_splits_and_moves_the_long_wall_too():
    geometry = GeometryEdit((((0, 0), (100, 0)), ((50, 0), (50, 80))))
    moved = move_vertex(geometry, (50, 0), (55, 10))
    assert moved.walls == (((0, 0), (55, 10)), ((55, 10), (100, 0)), ((55, 10), (50, 80)))


@pytest.mark.parametrize("extra_edges", [(), (((50, 0), (50, -80)),)])
def test_removing_branch_vertex_does_not_choose_a_main_wall(extra_edges):
    untouched = ((200, 0), (300, 0))
    geometry = GeometryEdit((((0, 0), (100, 0)), ((50, 0), (50, 80)), untouched) + extra_edges)
    assert delete_vertex(geometry, (50, 0)).walls == (untouched,)
    erased = erase_geometry(geometry, (50, 0), (50, 0), 4, "vertices")
    assert erased.walls == (untouched,)


def test_geometry_edit_history_is_undoable_and_never_writes_source_json(pair_factory):
    source = pair_factory()
    before = source.json_path.read_bytes()
    session = Session(source)
    session.add(Closure(((10, 20), (30, 40), (60, 20))))
    original = session.geometry()
    session.add(move_vertex(original, (30, 40), (35, 45)))
    assert (35, 45) in vertices(session.geometry())
    session.undo()
    assert session.geometry() == original
    session.redo()
    assert (35, 45) in vertices(session.geometry())
    assert source.json_path.read_bytes() == before


def test_snapping_prioritizes_vertices_over_closer_lines_and_ignores_dragged_edges():
    geometry = GeometryEdit((((0, 0), (100, 0)), ((50, 8), (50, 50))))
    assert snap_point(geometry, (50, 1), 10) == (50, 8)
    assert snap_point(geometry, (25, 1), 10) == (25, 0)
    assert snap_point(geometry, (25, 1), 0) is None
    assert snap_point(geometry, (1, 1), 10, exclude=(0, 0)) is None


def test_new_line_can_connect_two_segment_interiors_without_mutating_the_original():
    geometry = GeometryEdit((((0, 0), (100, 0)), ((0, 100), (100, 100))))
    edited = add_line(geometry, (40, 0), (40, 100))
    assert len(edited.walls) == 5
    assert ((40, 0), (40, 100)) in edited.walls
    assert len(geometry.walls) == 2
    assert add_line(edited, (40, 0), (40, 100)) == edited


def test_line_eraser_sweeps_fast_drags_and_splits_closure_paths():
    geometry = GeometryEdit(
        (((10, 0), (10, 100)), ((80, 0), (80, 100)), ((200, 0), (200, 100))),
        (((20, 20), (20, 80), (60, 80), (60, 20)),),
    )
    edited = erase_geometry(geometry, (0, 50), (100, 50), 2, "lines")
    assert edited.walls == (((200, 0), (200, 100)),)
    assert edited.closures == (((20, 80), (60, 80)),)
    assert geometry.closures[0][0] == (20, 20)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("crossing", [((30, -20), (30, 20)), ((30, 0), (60, 30))])
def test_line_eraser_stops_at_crossings_and_t_contacts_without_splitting_other_edges(
    reverse, crossing
):
    edge = ((0, 0), (100, 0))
    if reverse:
        edge = edge[::-1]
    untouched = ((0, 80), (100, 80))
    geometry = GeometryEdit((edge, crossing, untouched))
    expected = ((100, 0), (30, 0)) if reverse else ((30, 0), (100, 0))
    assert geometry_targets(geometry, (80, 0), (80, 0), 3, "lines") == (expected,)
    edited = erase_geometry(geometry, (80, 0), (80, 0), 3, "lines")
    retained = ((30, 0), (0, 0)) if reverse else ((0, 0), (30, 0))
    assert edited.walls == (retained, crossing, untouched)
    assert edited.lineage[1:] == geometry.lineage[1:]
    assert edited.lineage[0].parents == (geometry.lineage[0].id,)
    assert not geometry_targets(geometry, (200, 200), (200, 200), 1, "lines")
    assert erase_geometry(geometry, (200, 200), (200, 200), 1, "lines") is geometry


def test_line_eraser_removes_middle_between_multiple_intersections_and_coalesces_survivors():
    crossing = (((30, -20), (30, 20)), ((70, -20), (70, 20)))
    geometry = GeometryEdit((((0, 0), (100, 0)), *crossing))
    edited = erase_geometry(geometry, (50, 0), (50, 0), 2, "lines")
    assert edited.walls == (((0, 0), (30, 0)), ((70, 0), (100, 0)), *crossing)
    assert edited.lineage[2:] == geometry.lineage[1:]
    assert all(r.parents == (geometry.lineage[0].id,) for r in edited.lineage[:2])
    # Collinear overlap boundaries count, but unused cuts never become extra edges.
    overlap = GeometryEdit((((0, 0), (100, 0)), ((30, 0), (70, 0))))
    tail = erase_geometry(overlap, (85, 0), (85, 0), 2, "lines")
    assert tail.walls == (((0, 0), (70, 0)), overlap.walls[1])
    middle = erase_geometry(overlap, (50, 0), (50, 0), 2, "lines")
    assert middle.walls == (((0, 0), (30, 0)), ((70, 0), (100, 0)))


@pytest.mark.parametrize("reverse", [False, True])
def test_line_eraser_reconciles_projected_t_contacts_without_moving_other_owners(reverse):
    from dale.editing import project

    target = ((39.9832, 182.7731), (1101.3927, 519.2221))
    corner = (334.2481, 702.3419)
    for index in range(20, 181):
        cursor = tuple(target[0][i] + (target[1][i] - target[0][i]) * index / 200 for i in (0, 1))
        endpoint, _ = project((cursor[0] - 2, cursor[1] + 3), target)
        edge = target[::-1] if reverse else target
        geometry = GeometryEdit((edge, (target[0], corner), (corner, endpoint)))
        eraser = LineEraser(geometry)
        assert len(eraser._parts(0)) == 2
        point = tuple((target[1][i] + endpoint[i]) / 2 for i in (0, 1))
        targets = eraser.targets(point, point, 0.001)
        assert len(targets) == 1 and targets[0][0] == 0
        changed = eraser.erase(targets)
        assert len(changed.walls) == 3
        assert changed.walls[1:] == geometry.walls[1:]
        assert changed.lineage[1:] == geometry.lineage[1:]
        assert changed.lineage[0].parents == (geometry.lineage[0].id,)


def test_line_eraser_does_not_split_at_real_gaps_or_separate_parallel_edges():
    for other in (((30, 1e-5), (50, 20)), ((30, 1e-8), (70, 1e-8))):
        geometry = GeometryEdit((((0, 0), (100, 0)), other))
        assert LineEraser(geometry)._parts(0) == (geometry.walls[0],)


@pytest.mark.parametrize("end", [(10, 0), (10, 20)])
def test_virtual_contact_angle_accepts_a_perpendicular_at_a_segment_endpoint(end):
    from dale.editing import right_angle_contact

    anchor = (0, end[1])
    edge = ((10, 0), (10, 20))
    result = right_angle_contact((10, end[1] + 0.1), (anchor,), (edge,), 2)
    assert result is not None and result[0] == end
    assert right_angle_contact((10, 5), ((0, -10),), (edge,), 90) is None


def test_line_eraser_closure_uses_the_same_partition_and_explicit_source_parent():
    path = ((0, 0), (100, 0), (100, 80), (0, 80))
    crossing = ((30, -20), (30, 100))
    geometry = GeometryEdit((crossing,), (path,))
    edited = erase_geometry(geometry, (70, 0), (70, 0), 2, "lines")
    assert edited.walls == (crossing,)
    assert edited.closures == (((0, 0), (30, 0)), ((100, 0), (100, 80), (0, 80)))
    assert edited.lineage[0] == geometry.lineage[0]
    assert edited.lineage[1].parents == (geometry.lineage[1].id,)
    assert edited.lineage[2:] == geometry.lineage[2:]


def test_line_eraser_stroke_keeps_deleted_intersection_as_a_frozen_boundary():
    geometry = GeometryEdit((((20, 100), (180, 100)), ((80, 20), (80, 100))))
    index = LineEraser(geometry)
    hits = set(index.targets((80, 40), (80, 40), 2))
    assert index.erase(hits).walls == (geometry.walls[0],)
    hits.update(index.targets((80, 40), (140, 100), 2))
    assert index.erase(hits).walls == (((20, 100), (80, 100)),)


def test_vertex_eraser_keeps_unselected_neighbors_and_open_count_uses_connected_groups():
    geometry = GeometryEdit((((0, 0), (50, 20)), ((50, 20), (100, 0))))
    edited = erase_geometry(geometry, (50, 20), (50, 20), 4, "vertices")
    assert edited.walls == (((0, 0), (100, 0)),)
    assert open_contour_count((((0, 0), (20, 0)), ((10, 0), (10, 20)), ((100, 0), (110, 0)))) == 2


@pytest.mark.parametrize("scale", [0.01, 1, 100])
def test_right_angle_tolerance_is_angular_not_a_pixel_distance(scale):
    def scaled(p):
        return tuple(c * scale for c in p)

    a, joint, point = map(scaled, ((0, 0), (20, 20), (39, 2)))
    geometry = GeometryEdit(((a, joint), (joint, point)))
    assert right_angle_point(point, point, point, (joint,), geometry, 1) == (point, None)
    target, guide = right_angle_point(point, point, point, (joint,), geometry, 2)
    assert target == pytest.approx(scaled((38.5, 1.5))) and guide[1] == joint
    assert right_angle_point(
        point, point, point, (joint,), geometry, 2, include_neighbours=False
    ) == (point, None)


def test_disabling_neighbour_angles_keeps_all_pairs_at_dragged_vertex():
    vertex = (40, 0)
    neighbours = ((0, 0), (80, 0), (40, 80))
    geometry = GeometryEdit(tuple((vertex, p) for p in neighbours))
    point = (61, 21)
    target, guide = right_angle_point(
        point, point, vertex, neighbours, geometry, 2, include_neighbours=False
    )
    assert guide[1] == target and {guide[0], guide[2]} == {(0, 0), (40, 80)}


def test_acquired_guides_remember_external_points_and_precede_unvisited_references():
    targets = GuideTargets(((250, 180), (247, 350), (320, 280)))
    assert targets.align((247, 275), 5, acquired_only=True) == ((247, 275), ())
    assert targets.acquire((250, 180), 2) == (250, 180)
    assert targets.acquire((500, 500), 2) is None
    point, guides = targets.align((247, 275), 5)
    assert point == (250, 280)
    assert dict(guides) == {0: (250, 180), 1: (320, 280)}
    assert targets.align((247, 275), 5, acquired_only=True) == ((250, 275), ((0, (250, 180)),))
    targets.acquire((320, 280), 1)
    assert targets.align((247, 275), 5, acquired_only=True)[0] == (250, 280)
    assert len(targets.acquired) == 2
    assert not GuideTargets(targets.points).acquired


def test_guide_acquisition_uses_radial_cursor_hit_and_frozen_geometry():
    points = [(20, 20), (20, 80)]
    targets = GuideTargets(points)
    points.append((100, 100))
    assert targets.acquire((24, 24), 5) is None
    assert targets.acquire((23, 24), 5) == (20, 20)
    assert targets.acquire((100, 100), 5) is None
    assert targets.acquire((20, 80), 1) == (20, 80)
    assert targets.align((22, 120), 3, acquired_only=True)[1] == ((0, (20, 80)),)
    assert not targets.align((30, 120), 3, acquired_only=True)[1]
    assert GuideTargets(()).nearest((0, 0), 10) is None
