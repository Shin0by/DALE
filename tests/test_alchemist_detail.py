"""Selected ring reduction, persistent targets and raw-slice affine regeneration."""

import math
from dataclasses import replace

import pytest
from shapely import Polygon
from test_alchemist import sample as sample
from test_alchemist_interaction import editor as editor
from test_alchemist_slices import object_edges
from test_alchemist_slices import projected as projected
from test_alchemist_window import panel as panel

from dale.alchemist import memberships, remove_outside_objects
from dale.alchemist_detail import closed_paths, decode_values, simplify_contours, values_for
from dale.alchemist_slices import change_slice
from dale.project_io import load_project, save_project
from dale.provenance import LineRecord
from dale.session import GeometryEdit


def ring(x=0, group="asset"):
    points = tuple(
        (x + 10 * math.cos(i * math.tau / 24), 10 * math.sin(i * math.tau / 24)) for i in range(24)
    )
    edges = tuple(zip(points, (*points[1:], points[0]), strict=True))
    return GeometryEdit(
        edges, lineage=tuple(LineRecord(f"{x}:{i}", connection_group=group) for i in range(24))
    )


def test_four_vertices_partial_selection_and_disconnected_islands():
    a, b = ring(), ring(40)
    original = GeometryEdit(a.walls + b.walls, lineage=a.lineage + b.lineage)
    selected = tuple(r.id for r in original.lineage)
    reduced, selection, count = simplify_contours(original, selected, dict.fromkeys(selected, 4))
    assert count == 2
    assert len(reduced.lineage) == len(selection) == 8
    paths = closed_paths(reduced)[1]
    assert len(paths) == 2 and paths[0][3].disjoint(paths[1][3])
    assert all(len(points) == 4 for _, _, points, _ in paths)
    assert all(r.parents for r in reduced.lineage)
    assert {r.id for r in original.lineage}.issubset({r.id for r in reduced.ancestry})
    partial, _, count = simplify_contours(original, selected[:-1], dict.fromkeys(selected, 4))
    assert count == 1
    assert partial.walls[:24] == b.walls


def round_profiles(session):
    key = session.alchemist.profiles[0][0]
    profiles = tuple(
        Polygon(
            [
                (
                    math.cos(i * math.tau / 32) * (1 + band / 10),
                    math.sin(i * math.tau / 32) * (1 + band / 10),
                )
                for i in range(32)
            ]
        ).wkb
        for band in range(10)
    )
    session.alchemist = replace(session.alchemist, profiles=((key, profiles),))
    session.add(change_slice(session, "tree", 2))


def test_panel_reapplies_complexity_to_new_slices_and_reopen(panel, tmp_path):
    session = panel.session
    round_profiles(session)
    panel.owner.refresh()
    panel.choose_all()
    before, start = session.geometry(), len(session.operations)
    assert panel.complexity.maximum() > 4
    panel.complexity.setValue(4)
    panel.flush()
    assert not panel.status.text()
    for level in (5, 8, 1):
        panel.lower.setValue(level)
        panel.flush()
        assert not panel.status.text()
        assert all(len(points) == 4 for _, _, points, _ in closed_paths(session.geometry())[1])
        assert len(session.operations) == start + 1
    panel.between.setChecked(True)
    panel.upper.setValue(8)
    panel.flush()
    assert all(len(points) == 4 for _, _, points, _ in closed_paths(session.geometry())[1])
    panel.hide()
    assert set(values_for(session).values()) == {4}
    path = tmp_path / "detail.dale"
    save_project(session, path)
    with load_project(path) as loaded:
        restored = loaded.session
        assert values_for(restored) == values_for(session)
        restored.trim_history(0)
        assert values_for(restored) == values_for(session)
        restored.add(change_slice(restored, "tree", 7))
        assert all(len(points) == 4 for _, _, points, _ in closed_paths(restored.geometry())[1])
    session.undo()
    assert session.geometry() == before


@pytest.mark.parametrize("old_failure", [False, True])
def test_complexity_cancels_running_work_and_only_publishes_latest(panel, monkeypatch, old_failure):
    from threading import Event

    from PySide6.QtTest import QTest

    import dale.alchemist_window as window_module

    session = panel.session
    round_profiles(session)
    panel.owner.refresh()
    panel.choose_all()
    before, count = session.geometry(), len(session.operations)
    started, release = Event(), Event()
    simplify = window_module.simplify_contours
    calls = []

    def controlled(geometry, selection, targets, progress, *, check_cancel, failures=None):
        calls.append(set(targets.values()))
        if len(calls) == 1:
            started.set()
            assert release.wait(5)
            if old_failure:
                raise ValueError("Obsolete calculation failed")
        check_cancel()
        return simplify(
            geometry, selection, targets, progress, check_cancel=check_cancel, failures=failures
        )

    monkeypatch.setattr(window_module, "simplify_contours", controlled)
    panel.complexity.setValue(12)
    panel.apply()
    try:
        assert started.wait(5)
        obsolete = panel.cancel_event
        panel.complexity.setValue(8)
        panel.complexity.setValue(4)
        assert obsolete.is_set() and session.geometry() == before
    finally:
        release.set()
    for _ in range(300):
        QTest.qWait(10)
        if not panel.busy and not panel.dirty:
            break
    assert not panel.busy and not panel.dirty and not panel.status.text()
    assert calls == [{12}, {4}]
    assert set(values_for(session).values()) == {4}
    assert len(session.operations) == count + 1
    session.undo()
    assert session.geometry() == before


@pytest.mark.parametrize("next_value", [12, 6])
def test_drag_discards_ready_result_and_restarts_only_on_release(panel, next_value):
    from PySide6.QtTest import QTest

    session = panel.session
    round_profiles(session)
    panel.owner.refresh()
    panel.choose_all()
    before = session.geometry()
    panel.complexity.setValue(12)
    panel.apply()
    panel.future.result(timeout=5)
    panel.complexity.setSliderDown(True)
    panel.finish()
    assert session.geometry() == before and panel.dirty and not panel.busy
    panel.complexity.setSliderPosition(next_value)
    QTest.qWait(220)
    assert panel.future is None and session.geometry() == before
    panel.complexity.setSliderDown(False)
    panel.flush()
    assert set(values_for(session).values()) == {next_value}
    assert not panel.status.text() and not panel.dirty and not panel.busy


def test_outer_reduction_cancels_inside_ring_without_caching_partial_shape():
    import dale.alchemist_outline as outlines
    from dale.alchemist import AlchemistCancelled

    outlines.clear_outline_cache()
    points = tuple(edge[0] for edge in ring().walls)
    checks = 0

    def cancel_during_reduction():
        nonlocal checks
        checks += 1
        if checks == 6:
            raise AlchemistCancelled()

    with pytest.raises(AlchemistCancelled):
        outlines.outer_outline(points, Polygon(points), 4, cancel_during_reduction)
    assert not outlines._cache
    result, _ = outlines.outer_outline(points, Polygon(points), 4)
    assert len(result) == 4 and Polygon(result).buffer(1e-8).covers(Polygon(points))


def test_simplified_affine_placement_survives_slice_regeneration(projected):
    from dale.alchemist_detail_frames import capture_frames, placements_for

    session, _ = projected
    round_profiles(session)
    original = session.geometry()
    next_raw = change_slice(session, "tree", 8, apply_detail=False)
    next_owners = memberships(session.alchemist, next_raw)
    ids = [
        r.id
        for r, own in zip(original.lineage, memberships(session.alchemist, original), strict=True)
        if own
    ]
    reduced, _, _ = simplify_contours(original, ids, dict.fromkeys(ids, 4))
    frames = capture_frames(
        session.alchemist,
        reduced,
        placements_for(session, original, {obj.id for obj in session.alchemist.objects}),
        {},
    )
    limits = tuple((obj.id, 4) for obj in session.alchemist.objects)
    transformed = replace(
        reduced,
        walls=tuple(
            tuple((300 - y * 1.7, 50 + x * 1.7) for x, y in edge) for edge in reduced.walls
        ),
        alchemist_complexity=limits,
        alchemist_detail_frames=frames,
    )
    session.add(transformed)
    session.add(change_slice(session, "tree", 8, apply_detail=False))
    for obj in session.alchemist.objects:
        expected = [
            edge for edge, own in zip(next_raw.walls, next_owners, strict=True) if obj.id in own
        ]
        assert [v for e in object_edges(session, obj) for p in e for v in p] == pytest.approx(
            [v for e in expected for x, y in e for v in (300 - y * 1.7, 50 + x * 1.7)], abs=1e-7
        )


def test_cleanup_existing_project_preserves_inside_and_undo(projected, tmp_path):
    session, _ = projected
    before = session.geometry()
    obj = session.alchemist.objects[0]
    owners = memberships(session.alchemist, before)
    moved = replace(
        before,
        walls=tuple(
            tuple((x - 10000, y) for x, y in edge) if obj.id in own else edge
            for edge, own in zip(before.walls, owners, strict=True)
        ),
    )
    session.add(moved)
    operation, count = remove_outside_objects(session)
    assert count == 1
    assert operation is not None
    session.add(operation)
    assert all(obj.id not in own for own in memberships(session.alchemist, operation))
    assert operation.walls == tuple(
        e for e, own in zip(moved.walls, owners, strict=True) if obj.id not in own
    )
    path = tmp_path / "cleaned.dale"
    save_project(session, path)
    with load_project(path) as loaded:
        loaded.session.undo()
        assert loaded.session.geometry().walls == operation.walls
        assert not loaded.session.future
    session.undo()
    assert session.geometry() == moved


@pytest.mark.parametrize("value", [[["id", 3]], [["id", True]], [["id", 4], ["id", 5]], None])
def test_complexity_rejects_invalid_metadata(value):
    with pytest.raises(ValueError):
        decode_values(value)


def test_new_detailed_slice_expands_slider_range(panel):
    session = panel.session
    key = session.alchemist.profiles[0][0]
    shape = Polygon([edge[0] for edge in ring().walls]).wkb
    session.alchemist = replace(session.alchemist, profiles=((key, (shape,) * 10),))
    panel.choose_all()
    assert panel.complexity.maximum() == 4
    panel.lower.setValue(8)
    panel.flush()
    assert panel.complexity.maximum() > 4
    assert panel.complexity.value() == panel.complexity.maximum()
    panel.complexity.setValue(4)
    panel.flush()
    assert not panel.status.text()
    assert all(len(points) == 4 for _, _, points, _ in closed_paths(session.geometry())[1])


def test_major_palm_leaf_tips_survive_before_dense_small_teeth():
    from dale.alchemist_detail import _candidate

    radii = {angle: 30 for angle in range(0, 360, 5)}
    major = (0, 50, 145, 220, 290)
    for angle in major:
        radii[angle] = 110
        radii[(angle - 15) % 360] = radii[(angle + 15) % 360] = 40
    for index in range(41):
        radii[80 + index / 2] = 86 if index % 2 else 38
    points = tuple(
        (radius * math.cos(math.radians(angle)), radius * math.sin(math.radians(angle)))
        for angle, radius in sorted(radii.items())
    )
    polygon = Polygon(points)
    assert polygon.is_valid
    candidate = _candidate(points, polygon, 16)
    assert len(candidate) == 16 and Polygon(candidate).is_valid
    for angle in major:
        tip = (110 * math.cos(math.radians(angle)), 110 * math.sin(math.radians(angle)))
        assert min(math.dist(tip, point) for point in candidate) < 1e-7
    # The small-tooth patch stays coarse while every major leaf tip survives.
    assert sum(79.9 <= math.degrees(math.atan2(y, x)) <= 100.1 for x, y in candidate) <= 5


@pytest.mark.parametrize("target", [4, 8, 16])
def test_outer_reduction_merges_contacting_parts_and_refits_total_budget(target):
    a, b = ring(), ring(20.01)
    original = GeometryEdit(a.walls + b.walls, lineage=a.lineage + b.lineage)
    selected = tuple(r.id for r in original.lineage)
    reduced, _, _ = simplify_contours(original, selected, dict.fromkeys(selected, target))
    before = closed_paths(original)[1]
    after = closed_paths(reduced)[1]
    assert len(after) == (1 if target in (4, 8) else 2)
    assert all(len(points) <= target for _, _, points, _ in after)
    for _, _, _, shape in before:
        assert any(candidate[3].buffer(1e-9).covers(shape) for candidate in after)


def test_outer_frame_survives_archive_checkpoint_and_repeated_slice_changes(panel, tmp_path):
    from dale.alchemist_detail_frames import frames_for

    session = panel.session
    round_profiles(session)
    panel.owner.refresh()
    panel.choose_all()
    baseline = session.geometry()
    panel.complexity.setValue(4)
    panel.flush()
    assert frames_for(session)
    panel.hide()
    path = tmp_path / "outer.dale"
    save_project(session, path)
    with load_project(path) as loaded:
        restored = loaded.session
        restored.trim_history(0)
        assert frames_for(restored) == frames_for(session)
        for level in (8, 2, 8):
            restored.add(change_slice(restored, "tree", level))
        raw = change_slice(restored, "tree", 3, apply_detail=False)
        reference = replace(session, operations=[baseline], future=[])
        expected = change_slice(reference, "tree", 3, apply_detail=False)
        assert [v for e in raw.walls for p in e for v in p] == pytest.approx(
            [v for e in expected.walls for p in e for v in p], abs=1e-6
        )


@pytest.mark.parametrize(
    "value",
    [
        None,
        [["id", [1, 0, 0, 1, 0, 0], []]],
        [["id", [1, 0, 0, 1, 0, 0], [["a", 0, 0, 0], ["b", 0, 1, 1], ["c", 0, 2, 2]]]],
    ],
)
def test_invalid_outer_frames_are_rejected(value):
    from dale.alchemist_detail_frames import decode_frames

    with pytest.raises(ValueError):
        decode_frames(value)


def test_repeated_masks_share_reduction_across_placement_and_uniform_size(monkeypatch):
    import dale.alchemist_outline as outlines

    outlines.clear_outline_cache()
    points = tuple(edge[0] for edge in ring().walls)
    calls = []
    original = outlines.build_outline

    def counted(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(outlines, "build_outline", counted)
    first = outlines.outer_outline(points, Polygon(points), 8)[0]
    for scale in (0.5, 1.7, -2.0):
        placed = tuple((300 - y * abs(scale), 50 + x * scale) for x, y in points)
        result, _ = outlines.outer_outline(placed, Polygon(placed), 8)
        expected = tuple((300 - y * abs(scale), 50 + x * scale) for x, y in first)
        assert np_array(result) == pytest.approx(np_array(expected), abs=1e-7)
        assert Polygon(result).buffer(1e-8).covers(Polygon(placed))
    assert len(calls) == 1
    outlines.outer_outline(points, Polygon(points), 4)
    edited = (*points[:-1], (points[-1][0] * 1.1, points[-1][1]))
    outlines.outer_outline(edited, Polygon(edited), 8)
    assert len(calls) == 3
    outlines.clear_outline_cache()


def np_array(points):
    return [coordinate for point in points for coordinate in point]


def test_each_budget_constructs_a_complete_shape_from_the_raw_input(monkeypatch):
    import numpy as np

    import dale.alchemist_outline as outlines

    outlines.clear_outline_cache()
    points = tuple(
        (100 * math.cos(i * math.tau / 128), 85 * math.sin(i * math.tau / 128)) for i in range(128)
    )
    polygon = Polygon(points)
    build = outlines.build_outline
    inputs = []

    def tracked(source, shape, budget, *args):
        inputs.append((source, budget))
        return build(source, shape, budget, *args)

    monkeypatch.setattr(outlines, "build_outline", tracked)
    results = []
    for budget in (5, 6, 7):
        result, _ = outlines.outer_outline(points, polygon, budget)
        assert len(result) == budget
        assert Polygon(result).buffer(1e-8).covers(polygon)
        results.append(result)
    assert inputs == [(points, budget) for budget in (5, 6, 7)]
    for before, after in zip(results, results[1:], strict=False):
        distances = np.linalg.norm(np.asarray(before)[:, None, :] - after, axis=2)
        assert np.count_nonzero(distances.min(axis=1) > 1) >= len(before) - 1


@pytest.mark.parametrize("clockwise", [False, True])
def test_coarse_rounded_crown_rebuilds_six_and_seven_sides(clockwise):
    import numpy as np

    from dale.alchemist_outline import outer_outline

    # Eight coarse corners, similar to the owner's report. A densely sampled
    # ellipse alone misses the minimum-area fitter's tendency to retain facets.
    points = ((10, 45), (39, 16), (63, 12), (83, 26), (89, 45), (81, 76), (53, 85), (25, 77))
    if clockwise:
        points = points[::-1]
    source = Polygon(points)
    results = []
    for budget in (5, 6, 7):
        result, anchors = outer_outline(points, source, budget)
        assert len(result) == len(set(anchors)) == budget
        shape = Polygon(result)
        assert shape.buffer(1e-8).covers(source)
        assert shape.exterior.is_ccw == source.exterior.is_ccw
        # Reconstruct the whole coarse crown instead of retaining six old
        # corners when reducing eight vertices to seven.
        distances = np.linalg.norm(np.asarray(result)[:, None, :] - points, axis=2)
        # Coincident good corners may remain, but the old polygon is not a set
        # of fixed output vertices. Fidelity now uses one continuous objective.
        assert np.count_nonzero(distances.min(axis=1) > 0.5) >= budget - 2
        results.append(result)
    for before, after in zip(results, results[1:], strict=False):
        distances = np.linalg.norm(np.asarray(before)[:, None, :] - after, axis=2)
        assert np.count_nonzero(distances.min(axis=1) > 0.5) >= len(before) - 1


def test_rounded_reconstruction_ignores_collinear_sampling_density():
    import numpy as np

    from dale.alchemist_outline import outer_outline

    points = ((10, 45), (39, 16), (63, 12), (83, 26), (89, 45), (81, 76), (53, 85), (25, 77))
    dense = tuple(
        tuple(np.asarray(a) + (np.asarray(b) - a) * t)
        for i, (a, b) in enumerate(zip(points, (*points[1:], points[0]), strict=True))
        for t in np.linspace(0, 1, 20 if i < 3 else 2, endpoint=False)
    )
    simple, _ = outer_outline(points, Polygon(points), 6)
    sampled, _ = outer_outline(dense, Polygon(dense), 6)
    assert Polygon(simple).hausdorff_distance(Polygon(sampled)) < 1e-7


def test_global_reconstruction_preserves_a_narrow_deep_notch():
    import numpy as np
    from shapely import Point

    from dale.alchemist_outline import outer_outline

    angles = np.linspace(0, math.tau, 128, endpoint=False)
    points = np.column_stack((np.cos(angles), np.sin(angles)))
    points[32] *= 0.3
    points = tuple(map(tuple, points))
    polygon = Polygon(points)
    result, _ = outer_outline(points, polygon, 16)
    assert Polygon(result).buffer(1e-8).covers(polygon)
    assert not Polygon(result).covers(Point(0, 0.7))
    assert len(result) == 16


def test_global_reconstruction_rebuilds_concave_shapes_at_coarse_and_fine_budgets(monkeypatch):
    import dale.alchemist_outline as outlines

    points = tuple(
        (
            (100 + 25 * math.cos(5 * i * math.tau / 256)) * math.cos(i * math.tau / 256),
            (100 + 25 * math.cos(5 * i * math.tau / 256)) * math.sin(i * math.tau / 256),
        )
        for i in range(256)
    )
    source = Polygon(points)
    outlines.clear_outline_cache()
    original = outlines.build_outline
    calls = []

    def tracked(raw, shape, target, *args):
        calls.append((raw, target))
        return original(raw, shape, target, *args)

    monkeypatch.setattr(outlines, "build_outline", tracked)
    for budget in (16, 64, 24, 128, 32):
        result, _ = outlines.outer_outline(points, source, budget)
        assert len(result) == budget
        shape = Polygon(result)
        assert shape.buffer(1e-7).covers(source)
        assert shape.area < source.convex_hull.area
    assert calls == [(points, budget) for budget in (16, 64, 24, 128, 32)]
    forward, _ = outlines.outer_outline(points, source, 16)
    outlines.clear_outline_cache()
    independent, _ = outlines.outer_outline(points, source, 16)
    assert np_array(forward) == pytest.approx(np_array(independent), abs=1e-10)


def test_refit_cancellation_does_not_publish_cache_entry(monkeypatch):
    import dale.alchemist_outline as outlines
    from dale.alchemist import AlchemistCancelled

    outlines.clear_outline_cache()
    original = outlines.build_outline
    entered = False

    def wrapped(*args):
        nonlocal entered
        entered = True
        return original(*args)

    monkeypatch.setattr(outlines, "build_outline", wrapped)

    def cancel():
        if entered:
            raise AlchemistCancelled()

    points = tuple(edge[0] for edge in ring().walls)
    with pytest.raises(AlchemistCancelled):
        outlines.outer_outline(points, Polygon(points), 5, cancel)
    assert not outlines._cache


@pytest.mark.parametrize("clockwise", [False, True])
def test_detailed_refit_has_bounded_topology_checks_and_cyclic_ownership(monkeypatch, clockwise):
    import dale.alchemist_outline as outlines

    points = tuple(
        (100 * math.cos(i * math.tau / 2048), 85 * math.sin(i * math.tau / 2048))
        for i in range(2048)
    )
    if clockwise:
        points = points[::-1]
    polygon = Polygon(points)
    calls = []
    covers = outlines._covers

    def counted(*args):
        calls.append(1)
        return covers(*args)

    monkeypatch.setattr(outlines, "_covers", counted)
    candidate, anchors = outlines.build_outline(points, polygon, 512)
    assert len(candidate) == len(anchors) == 512
    assert list(anchors) == sorted(set(anchors))
    assert Polygon(candidate).buffer(1e-8).covers(polygon)
    assert Polygon(candidate).exterior.is_ccw == polygon.exterior.is_ccw
    assert len(calls) <= 72  # Bounded complete candidates, not one scan per output side.


def test_complexity_reopens_with_full_detail_and_ignores_previous_steps(panel, tmp_path):
    session = panel.session
    round_profiles(session)
    panel.owner.refresh()
    panel.choose_all()
    maximum = panel.complexity.maximum()
    panel.complexity.setValue(6)
    panel.flush()
    reference = session.geometry().walls
    panel.complexity.setValue(4)
    panel.flush()
    panel.hide()
    path = tmp_path / "refit.dale"
    save_project(session, path, {"figure_lines": list(panel.owner.view.figure_line_ids)})
    with load_project(path) as loaded:
        restored = loaded.session
        panel.owner.view.session = restored
        panel.owner.refresh()
        panel.owner.view.figure_line_ids = loaded.ui_state["figure_lines"]
        panel.owner.toggle_slice_window(True)
        assert panel.complexity.maximum() == maximum > 6
        for budget in (8, 5, 6):
            panel.complexity.setValue(budget)
            panel.flush()
            assert not panel.status.text()
            assert all(
                len(points) == budget for _, _, points, _ in closed_paths(restored.geometry())[1]
            )
        assert [v for edge in restored.geometry().walls for p in edge for v in p] == pytest.approx(
            [v for edge in reference for p in edge for v in p], abs=1e-7
        )
        assert len(restored.operations) == 2  # Applied archive checkpoint and one panel segment.
        panel.hide()


def test_raw_rebuild_retains_different_object_slices_and_affine_placement(projected):
    from dale.alchemist_detail_frames import capture_frames, placements_for
    from dale.alchemist_slices import object_value

    session, _ = projected
    round_profiles(session)
    first, second = session.alchemist.objects[:2]
    session.add(change_slice(session, "tree", 7, object_ids={first.id}))
    original = session.geometry()
    identifiers = {obj.id for obj in session.alchemist.objects}
    ids = tuple(r.id for r in original.lineage)
    reduced, _, _ = simplify_contours(original, ids, dict.fromkeys(ids, 5))
    frames = capture_frames(
        session.alchemist, reduced, placements_for(session, original, identifiers), {}
    )
    transformed = replace(
        reduced,
        alchemist_detail_frames=frames,
        walls=tuple(tuple((300 - y * 1.7, 50 + x * 1.7) for x, y in e) for e in reduced.walls),
    )
    session.add(transformed)
    session.add(
        change_slice(
            session, "tree", -1, object_ids=identifiers, apply_detail=False, rebuild_current=True
        )
    )
    assert object_value(session, first) == (7, 10, False)
    assert object_value(session, second) == (2, 10, False)
    reference = replace(session, operations=[original])
    for obj in (first, second):
        assert [v for e in object_edges(session, obj) for p in e for v in p] == pytest.approx(
            [
                v
                for e in object_edges(reference, obj)
                for x, y in e
                for v in (300 - y * 1.7, 50 + x * 1.7)
            ],
            abs=1e-7,
        )


def test_merge_is_scoped_to_one_object_and_preserves_all_source_ancestry():
    a, b, c = ring(), ring(20.01), ring(40.02, "other-asset")
    original = GeometryEdit(a.walls + b.walls + c.walls, lineage=a.lineage + b.lineage + c.lineage)
    ids = tuple(r.id for r in original.lineage)
    reduced, selected, _ = simplify_contours(original, ids, dict.fromkeys(ids, 4))
    paths = closed_paths(reduced)[1]
    assert len(paths) == 2
    assert {group for group, *_ in paths} == {"asset", "other-asset"}
    assert all(len(points) == 4 for _, _, points, _ in paths)
    assert set(selected) == {r.id for r in reduced.lineage}
    ancestry = {r.id: r for r in (*reduced.ancestry, *reduced.lineage)}
    for record in reduced.lineage:
        pending, roots = [record.id], set()
        while pending:
            item = ancestry[pending.pop()]
            if item.parents:
                pending.extend(item.parents)
            else:
                roots.add(item.id)
        allowed = {r.id for r in original.lineage if r.connection_group == record.connection_group}
        assert roots <= allowed
        if record.connection_group == "asset":
            assert roots == allowed


def test_contact_chain_is_one_budget_and_cancellation_keeps_input():
    rings = [ring(x) for x in (0, 20.01, 40.02)]
    original = GeometryEdit(
        tuple(e for r in rings for e in r.walls), lineage=tuple(v for r in rings for v in r.lineage)
    )
    ids = tuple(r.id for r in original.lineage)
    reduced, _, _ = simplify_contours(original, ids, dict.fromkeys(ids, 4))
    paths = closed_paths(reduced)[1]
    assert len(paths) == 1 and len(paths[0][2]) == 4
    assert all(paths[0][3].buffer(1e-7).covers(Polygon([e[0] for e in r.walls])) for r in rings)
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == 8:
            raise InterruptedError("cancelled")

    with pytest.raises(InterruptedError):
        simplify_contours(original, ids, dict.fromkeys(ids, 4), check_cancel=cancel)
    assert original.walls == tuple(e for r in rings for e in r.walls)


def test_merged_perimeter_omits_internal_holes_without_bridging_gaps():
    from shapely import box

    from dale.alchemist_merge import merge_outlines

    shapes = [box(0, 0, 4, 1), box(0, 3, 4, 4), box(0, 0, 1, 4), box(3, 0, 4, 4), box(10, 0, 11, 1)]
    result = merge_outlines(shapes, 4)
    assert len(result) == 2
    joined = next(shape for members, shape in result if len(members) == 4)
    assert not joined.interiors and joined.equals(box(0, 0, 4, 4))
    assert next(shape for members, shape in result if members == (4,)).equals(shapes[4])


def test_merged_asset_reopens_and_restores_raw_parts_at_higher_detail(panel, tmp_path):
    from shapely import MultiPolygon

    from dale.alchemist_detail_frames import frames_for

    session = panel.session
    key = session.alchemist.profiles[0][0]
    shape = MultiPolygon([Polygon([e[0] for e in ring(x).walls]) for x in (0, 20.01)])
    session.alchemist = replace(session.alchemist, profiles=((key, (shape.wkb,) * 10),))
    panel.choose_all()
    panel.lower.setValue(8)
    panel.flush()
    panel.hide()
    baseline = session.geometry()
    panel.owner.toggle_slice_window(True)
    panel.complexity.setValue(4)
    panel.flush()
    assert not panel.status.text()
    merged = session.geometry()
    paths = closed_paths(merged)[1]
    assert paths and all(len(points) == 4 for _, _, points, _ in paths)
    assert len(paths) == len(panel.objects)
    owners = memberships(session.alchemist, merged)
    assert all(len(owners[i]) == 1 for _, indices, _, _ in paths for i in indices)
    assert frames_for(session)
    panel.hide()
    session.undo()
    assert session.geometry().walls == baseline.walls
    session.redo()
    assert session.geometry().walls == merged.walls
    path = tmp_path / "merged.dale"
    save_project(session, path)
    with load_project(path) as loaded:
        restored = loaded.session
        assert restored.geometry().walls == merged.walls
        raw = change_slice(restored, "tree", 3, apply_detail=False)
        assert len(closed_paths(raw)[1]) == 2 * len(paths)
        rebuilt = change_slice(restored, "tree", 3)
        assert len(closed_paths(rebuilt)[1]) == len(paths)
        assert all(len(points) == 4 for _, _, points, _ in closed_paths(rebuilt)[1])


def test_merged_shape_sharing_checks_each_placement(monkeypatch):
    import numpy as np
    from shapely.affinity import affine_transform

    import dale.alchemist_merge as merge
    from dale.alchemist_outline import clear_outline_cache

    clear_outline_cache()
    original = merge._merge_outlines
    calls = []

    def counted(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(merge, "_merge_outlines", counted)
    shapes = [Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]), Polygon([(1, 1), (3, 1), (3, 3), (1, 3)])]
    for i in range(32):
        angle = i * 0.137
        c, s = np.cos(angle) * (1 + i / 20), np.sin(angle) * (1 + i / 20)
        placed = [affine_transform(p, (c, -s, s, c, 12000, 34000)) for p in shapes]
        result = merge.merge_outlines(placed, 4)
        assert len(result) == 1 and result[0][0] == (0, 1)
        assert len(result[0][1].exterior.coords) - 1 == 4
        assert all(result[0][1].buffer(1e-7).covers(p) for p in placed)
    assert calls == [1]
