"""Numeric object snapshots preserve exact geometry and scope ownership."""

import math
from dataclasses import replace

import numpy as np
import pytest
from test_alchemist import sample as sample

from dale.alchemist import memberships, scoped_geometry, transform_individual_objects
from dale.object_index import clear_indexes, object_index
from dale.provenance import geometry_edges


@pytest.fixture(autouse=True)
def isolated_index():
    clear_indexes()
    yield
    clear_indexes()


def test_visibility_inherits_ownership_without_rewalking_ancestry(sample, monkeypatch):
    import dale.alchemist as module

    session, *_ = sample
    geometry = session.geometry()
    full = object_index(session.alchemist, geometry)
    monkeypatch.setattr(module, "_memberships", lambda *_: pytest.fail("Repeated ancestry walk"))
    for scope in ("alchemist", "regular", "combined", "alchemist_all"):
        actual = scoped_geometry(session, geometry, scope)
        expected = tuple(
            own
            for own in full.owned
            if (not own and scope not in ("alchemist", "alchemist_all"))
            or (own and scope != "regular")
        )
        assert memberships(session.alchemist, actual) == expected
    assert session.geometry() is geometry


@pytest.mark.parametrize("angle,scale", [(0, 1.2), (15, 1), (-45, 0.7), (0.1, 1.02)])
def test_numeric_transform_matches_scalar_order_and_partial_selection(sample, angle, scale):
    session, *_ = sample
    geometry = session.geometry()
    index = object_index(session.alchemist, geometry)
    identifiers = session.alchemist.objects[0].roots[::2]
    expected = list(geometry_edges(geometry.walls, geometry.closures))
    selected = set(identifiers)
    a, b = scale * math.cos(math.radians(angle)), scale * math.sin(math.radians(angle))
    for _, indices in index.units:
        points = [point for i in indices for point in expected[i]]
        cx, cy = tuple((min(p[k] for p in points) + max(p[k] for p in points)) / 2 for k in (0, 1))
        for i in indices:
            if geometry.lineage[i].id in selected:
                expected[i] = tuple(
                    (cx + a * (x - cx) - b * (y - cy), cy + b * (x - cx) + a * (y - cy))
                    for x, y in expected[i]
                )
    result, _ = transform_individual_objects(session, identifiers, scale=scale, angle=angle)
    assert result.walls == tuple(expected)
    assert result.lineage is geometry.lineage and result.ancestry is geometry.ancestry
    assert result.wall_styles is geometry.wall_styles
    updated = object_index(session.alchemist, result)
    assert updated.owned is index.owned
    assert np.array_equal(updated.coordinates, np.asarray(result.walls))
    assert not updated.coordinates.flags.writeable
    with pytest.raises(ValueError):
        updated.coordinates.setflags(write=True)
    assert session.geometry() is geometry


def test_metadata_and_geometry_changes_invalidate_exact_indexes(sample):
    session, *_ = sample
    geometry = session.geometry()
    original = object_index(session.alchemist, geometry)
    assert (
        object_index(replace(session.alchemist, settings=((False, 0),) * 4), geometry) is original
    )
    data = replace(session.alchemist, objects=(session.alchemist.objects[0],))
    assert object_index(data, geometry) is not original
    # Metadata-only edits with unchanged coordinates must not reuse stale styles.
    changed = replace(geometry, wall_styles=(("new", ()),))
    assert object_index(session.alchemist, changed) is not original


def test_cache_evicts_by_edge_volume(sample, monkeypatch):
    import dale.object_index as module

    session, *_ = sample
    geometry = session.geometry()
    monkeypatch.setattr(module, "MAX_EDGES", len(geometry.lineage) + 1)
    original = object_index(session.alchemist, geometry)
    changed = replace(geometry, walls=tuple(((a[0] + 1, a[1]), b) for a, b in geometry.walls))
    object_index(session.alchemist, changed)
    assert module.find(session.alchemist, geometry) is None
    assert original.coordinates.shape == (len(geometry.lineage), 2, 2)


def test_full_scope_does_not_copy_checkpoint_metadata_into_a_display_layer(sample):
    session, *_ = sample
    geometry = replace(session.geometry(), alchemist_transforms=(("example", 2, 15),))
    scoped = scoped_geometry(session, geometry, "combined")
    assert scoped.walls == geometry.walls
    assert scoped.alchemist_transforms is None
    assert scoped.lineage is geometry.lineage


def test_coowned_edge_transforms_once_but_category_scale_excludes_other_type(sample):
    from dale.alchemist import DAData, DAObject, scale_category
    from dale.provenance import LineRecord
    from dale.session import GeometryEdit

    session, *_ = sample
    edges = (((0.0, 0.0), (2.0, 0.0)), ((10.0, 0.0), (12.0, 0.0)), ((2.0, 0.0), (10.0, 0.0)))
    first, second = (LineRecord.standalone(edge) for edge in edges[:2])
    shared = LineRecord.child((first, second), edges[2])
    geometry = GeometryEdit(edges, lineage=(first, second, shared))
    session.alchemist = DAData(
        "synthetic",
        b"",
        (DAObject("a", "tree", 2, (first.id,)), DAObject("b", "rock", 2, (second.id,))),
    )
    session.operations = [geometry]
    moved, _ = transform_individual_objects(session, (r.id for r in geometry.lineage), scale=2)
    assert moved.walls == tuple(tuple((6 + 2 * (x - 6), y) for x, y in edge) for edge in edges)
    scaled = scale_category(session, "tree", 2)
    assert scaled.walls[0] == ((-1.0, 0.0), (3.0, 0.0))
    assert scaled.walls[1:] == edges[1:]
    index = object_index(session.alchemist, geometry)
    assert index.bounds.tolist() == [[0.0, 0.0, 12.0, 0.0]]
