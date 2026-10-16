import math
import random

import pytest

from dale.geometry import analyze_regions, nearest_source
from dale.session import Closure, ContourMask, Session, Stroke


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
