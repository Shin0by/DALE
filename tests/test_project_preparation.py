"""Parallel image/contour preparation and topology-equivalent local DA fast paths."""

import threading

import pytest
from PIL import Image
from shapely import Polygon

from dale.alchemist_progress import prepare_project_view
from dale.alchemist_render import _part
from dale.geometry import RegionAnalysis, analyze_regions
from dale.session import Session


def ring(points):
    return tuple(zip(points, (*points[1:], points[0]), strict=True))


def test_many_small_objects_keep_their_unchanged_topology(monkeypatch):
    import dale.alchemist_render as render

    render._part.cache_clear()
    shapes = [ring(((x, 0), (x + 1, 0), (x + 1, 1), (x, 1))) for x in range(0, 9000, 3)]
    expected = [render._part(shape, 1) for shape in shapes]
    monkeypatch.setattr(
        render._part,
        "calculate",
        lambda *_: pytest.fail("Visibility must not recalculate unchanged object topology"),
    )
    assert all(
        render._part(shape, 1) is value for shape, value in zip(shapes, expected, strict=True)
    )
    assert render._part.cache_info().edges == 12000
    render._part.cache_clear()


def test_object_topology_cache_bounds_volume_and_rejects_post_clear_publication():
    from concurrent.futures import ThreadPoolExecutor

    from dale.alchemist_render import _PartCache

    calls = []
    cache = _PartCache(
        lambda edges, gap: calls.append((edges, gap)) or object(), max_edges=5, max_entries=3
    )
    first = cache((1, 2), 1)
    cache((3, 4, 5), 1)
    assert cache((1, 2), 1) is first
    cache((6, 7), 1)  # Evict the least recently used three-edge object.
    assert cache.cache_info().edges == 4
    assert cache((1, 2), 1) is first
    cache((0,) * 6, 1)  # Oversized shapes are computed but not retained.
    assert cache.cache_info().edges == 4
    cache((1, 2), 2)  # Tolerance is part of the key.
    assert cache.cache_info().edges <= 5
    started, release = threading.Event(), threading.Event()

    def calculate(*_):
        started.set()
        assert release.wait(5)
        return object()

    cache = _PartCache(calculate)
    with ThreadPoolExecutor(max_workers=1) as pool:
        task = pool.submit(cache, (1,), 1)
        assert started.wait(5)
        cache.cache_clear()
        release.set()
        assert task.result() is not None
    assert cache.cache_info().currsize == cache.cache_info().edges == 0


def test_disjoint_ordered_rings_skip_noding_without_changing_cells(monkeypatch):
    import dale.alchemist_render as render

    a = ring(((0, 0), (10, 0), (10, 10), (0, 10)))
    b = ring(((20, 1), (25, 1), (22, 5)))
    expected = analyze_regions(a + b)
    _part.cache_clear()
    monkeypatch.setattr(render, "analyze_regions", lambda *_a, **_k: pytest.fail("Unneeded noding"))
    actual = _part(a + b, 1)
    assert actual.area.equals(expected.area)
    assert actual.faces == expected.faces == 2
    assert actual.unresolved == expected.unresolved and actual.joins == expected.joins
    assert all(a.equals(b) for a, b in zip(actual.cells, expected.cells, strict=True))


@pytest.mark.parametrize(
    "other",
    [
        ((2, 2), (5, 2), (5, 5), (2, 5)),  # Nested boundaries need hole/cell handling.
        ((5, 5), (15, 5), (15, 15), (5, 15)),  # Crossing.
        ((10, 0), (20, 0), (20, 10), (10, 10)),  # Shared edge.
        ((10 + 1e-8, 0), (20, 0), (20, 10), (10 + 1e-8, 10)),  # Contact tolerance.
    ],
)
def test_general_contacts_keep_full_topology_analysis(other, monkeypatch):
    import dale.alchemist_render as render

    edges = ring(((0, 0), (10, 0), (10, 10), (0, 10))) + ring(other)
    expected = analyze_regions(edges)
    calls = []

    def analyze(*args, **kwargs):
        calls.append(True)
        return analyze_regions(*args, **kwargs)

    _part.cache_clear()
    monkeypatch.setattr(render, "analyze_regions", analyze)
    actual = _part(edges, 0)
    assert calls and actual.area.equals(expected.area)
    assert actual.faces == expected.faces and actual.unresolved == expected.unresolved


def test_project_preview_and_contours_overlap_and_match_serial(pair_factory, monkeypatch):
    session = Session(pair_factory())
    image_started, contours_started = threading.Event(), threading.Event()
    threads = []
    polygon = Polygon(((0, 0), (2, 0), (2, 2)))

    def image(source):
        threads.append(threading.get_ident())
        image_started.set()
        assert contours_started.wait(5)
        return Image.new("RGBA", (2, 2), "red")

    def contours():
        threads.append(threading.get_ident())
        contours_started.set()
        assert image_started.wait(5)
        return RegionAnalysis(polygon, 1, ())

    monkeypatch.setattr(session, "analysis", contours)
    parallel = prepare_project_view(session, "geometry", (), lambda *_: None, image, parallel=True)
    assert len(set(threads)) == 2
    serial = prepare_project_view(session, "geometry", (), lambda *_: None, image, parallel=False)
    assert serial[0].tobytes() == parallel[0].tobytes()
    assert serial[1:] == parallel[1:]
