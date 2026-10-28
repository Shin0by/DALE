"""Hard complexity bounds, complete slider sweeps and atomic failed requests."""

import math
from dataclasses import replace

import numpy as np
import pytest
from shapely import Polygon
from test_alchemist_detail import editor as editor
from test_alchemist_detail import panel as panel
from test_alchemist_detail import projected as projected
from test_alchemist_detail import sample as sample

from dale.alchemist_detail import closed_paths, values_for
from dale.alchemist_fit import ContourComplexityError
from dale.alchemist_outline import clear_outline_cache, outer_outline
from dale.alchemist_slices import change_slice

# A hand-traced reproduction of the reported crown, not a private project file.
CROWN = (
    (137, 20),
    (160, 23),
    (172, 35),
    (207, 89),
    (222, 94),
    (241, 125),
    (263, 66),
    (282, 50),
    (302, 54),
    (309, 80),
    (335, 54),
    (357, 54),
    (370, 66),
    (370, 99),
    (339, 143),
    (306, 166),
    (368, 150),
    (393, 160),
    (400, 181),
    (391, 203),
    (335, 221),
    (393, 243),
    (420, 261),
    (428, 282),
    (424, 298),
    (404, 310),
    (352, 296),
    (361, 316),
    (359, 332),
    (337, 348),
    (314, 343),
    (281, 307),
    (271, 338),
    (257, 344),
    (230, 315),
    (208, 412),
    (193, 423),
    (176, 425),
    (160, 404),
    (162, 366),
    (151, 370),
    (139, 362),
    (132, 334),
    (142, 305),
    (165, 261),
    (102, 292),
    (61, 305),
    (41, 299),
    (32, 282),
    (41, 263),
    (69, 246),
    (66, 231),
    (77, 213),
    (132, 199),
    (149, 181),
    (86, 133),
    (78, 109),
    (88, 93),
    (113, 92),
    (167, 129),
    (128, 57),
    (127, 33),
)


def test_equivalent_placed_masks_share_fit_across_rounding_boundaries(monkeypatch):
    import dale.alchemist_outline as module

    clear_outline_cache()
    count = 57
    angles = np.arange(count) * math.tau / count
    radii = 1 + 0.18 * np.cos(angles * 5)
    raw = np.column_stack((radii * np.cos(angles), radii * np.sin(angles)))
    original = module._checked_build
    calls = []

    def build(*args):
        calls.append(args[2])
        return original(*args)

    monkeypatch.setattr(module, "_checked_build", build)
    for i in range(64):
        angle = i * 0.137
        c, s = math.cos(angle), math.sin(angle)
        placed = raw @ np.array(((c, -s), (s, c))) * (1 + i / 20) + (12000, 34000)
        points = tuple(map(tuple, placed))
        polygon = Polygon(points)
        result, _ = outer_outline(points, polygon, 12)
        assert len(result) <= 12
        assert module._covers(Polygon(result), polygon)
    assert calls == [12]
    assert len(module._cache) == 1
    # An actually different silhouette must still receive its own fit.
    raw[3] *= 1.05
    points = tuple(map(tuple, raw))
    outer_outline(points, Polygon(points), 12)
    assert calls == [12, 12]


def test_every_crown_slider_value_obeys_its_budget():
    clear_outline_cache()
    original = Polygon(CROWN)
    assert original.is_valid
    for target in range(4, len(CROWN) + 1):
        result, anchors = outer_outline(CROWN, original, target)
        assert 4 <= len(result) <= target, (target, len(result))
        assert len(result) == len(set(anchors))
        shape = Polygon(result)
        assert shape.is_valid and shape.buffer(1e-7).covers(original)
        if target in (18, 19, 20):
            assert len(result) == target


@pytest.mark.parametrize("fault", ["no_candidate", "over_budget"])
def test_failed_builder_never_returns_or_caches_the_detailed_source(monkeypatch, fault):
    import dale.alchemist_fit as fit
    import dale.alchemist_outline as outlines

    clear_outline_cache()
    if fault == "no_candidate":
        for name in ("_partitions", "_resampled", "_envelopes"):
            monkeypatch.setattr(fit, name, lambda *args: iter(()))
    else:
        monkeypatch.setattr(
            outlines, "build_outline", lambda points, *args: (points, tuple(range(len(points))))
        )
    with pytest.raises(ContourComplexityError):
        outer_outline(CROWN, Polygon(CROWN), 19)
    assert not outlines._cache


def configure_crown(panel):
    session = panel.session
    key = session.alchemist.profiles[0][0]
    shape = Polygon([((x - 230) / 100, (y - 220) / 100) for x, y in CROWN])
    session.alchemist = replace(session.alchemist, profiles=((key, (shape.wkb,) * 10),))
    session.add(change_slice(session, "tree", 2))
    panel.owner.refresh()
    panel.choose_all()


def test_panel_publishes_actual_18_and_19_vertex_results(panel):
    configure_crown(panel)
    session = panel.session
    for target in (18, 19, 20, 18, 19):
        panel.complexity.setValue(target)
        panel.flush()
        assert not panel.status.text()
        assert panel.complexity.value() == target
        assert set(values_for(session).values()) == {target}
        paths = closed_paths(session.geometry())[1]
        assert paths and all(len(points) <= target for _, _, points, _ in paths)


def test_failed_complexity_keeps_applied_geometry_controls_history_and_defaults(panel, monkeypatch):
    import dale.alchemist_outline as outlines

    session = panel.session
    configure_crown(panel)
    saved = []
    monkeypatch.setattr(
        panel.owner,
        "remember_alchemist_parameters",
        lambda session, *args: saved.append(values_for(session)),
    )
    panel.complexity.setValue(18)
    panel.flush()
    geometry = session.geometry()
    history = tuple(session.operations)
    selection = tuple(panel.owner.view.figure_line_ids)
    original = outlines.build_outline
    monkeypatch.setattr(
        outlines, "build_outline", lambda points, *args: (points, tuple(range(len(points))))
    )
    clear_outline_cache()
    panel.complexity.setValue(19)
    panel.flush()
    assert panel.status.text()
    assert panel.complexity.value() == 18
    assert session.geometry() is geometry and tuple(session.operations) == history
    assert tuple(panel.owner.view.figure_line_ids) == selection
    assert set(values_for(session).values()) == {18}
    assert len(saved) == 1
    monkeypatch.setattr(outlines, "build_outline", original)
    panel.complexity.setValue(20)
    panel.flush()
    assert not panel.status.text() and panel.complexity.value() == 20
    assert len(saved) == 2 and len(session.operations) == len(history)
    assert set(values_for(session).values()) == {20}


def test_one_failed_object_does_not_cancel_other_selected_objects(panel, monkeypatch):
    import dale.alchemist_detail as detail
    from dale.alchemist import memberships

    configure_crown(panel)
    session = panel.session
    panel.complexity.setValue(18)
    panel.flush()
    applied = session.geometry()
    failed_id = session.alchemist.objects[0].id
    failed_edges = tuple(
        edge
        for edge, own in zip(applied.walls, memberships(session.alchemist, applied), strict=True)
        if failed_id in own
    )
    midpoint = (
        sum(
            polygon.centroid.x
            for group, _, _, polygon in closed_paths(applied)[1]
            if group and group.startswith("da:")
        )
        / 2
    )
    original = detail.outer_outline

    def fail_first(points, polygon, target, check_cancel=None):
        if polygon.centroid.x < midpoint:
            raise detail.ContourComplexityError(detail.FIT_FAILED)
        return original(points, polygon, target, check_cancel)

    monkeypatch.setattr(detail, "outer_outline", fail_first)
    panel.complexity.setValue(19)
    panel.flush()
    assert panel.status.text()
    values = values_for(session)
    assert values[failed_id] == 18
    assert set(values.values()) == {18, 19}
    actual = session.geometry()
    assert (
        tuple(
            edge
            for edge, own in zip(actual.walls, memberships(session.alchemist, actual), strict=True)
            if failed_id in own
        )
        == failed_edges
    )


@pytest.mark.parametrize("target", [10, 14, 18])
def test_sharp_support_intersections_discard_only_zero_length_sides(monkeypatch, target):
    import dale.alchemist_fit as fit

    clear_outline_cache()
    # A long acute tip and a dense convex arc make multiple support planes
    # intersect at the same tip. No private model coordinates are required.
    angles = np.linspace(math.pi / 2, 3 * math.pi / 2, 95)
    points = ((100.0, 0.0), *tuple(zip(np.cos(angles), np.sin(angles), strict=True)))
    monkeypatch.setattr(fit, "_partitions", lambda *args: iter(()))
    monkeypatch.setattr(fit, "_resampled", lambda *args: iter(()))
    shape = Polygon(points)
    result, _ = outer_outline(points, shape, target)
    assert 4 <= len(result) <= target
    assert Polygon(result).is_valid and Polygon(result).buffer(1e-7).covers(shape)
    assert (
        min(math.dist(a, b) for a, b in zip(result, (*result[1:], result[0]), strict=True)) > 1e-10
    )
