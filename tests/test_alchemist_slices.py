"""Offline slab switching, stable placement/history and passive Ctrl feedback."""

import json
from dataclasses import replace

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication
from shapely import Polygon
from test_alchemist import sample as sample
from test_alchemist_interaction import editor as editor
from test_alchemist_mesh import leaning_tree

from dale.alchemist import DAData, import_map, memberships, scale_category
from dale.alchemist_indicator import SliceIndicator
from dale.alchemist_mesh import build_profile
from dale.alchemist_slices import change_slice, decode_profiles, profile_edges, values_for
from dale.project_io import load_project, save_project


@pytest.fixture
def projected(sample, monkeypatch):
    session, library, raw, _ = sample
    data = json.loads(raw)
    data.update(width=16, height=16)
    # Keep this deliberately leaning model inside the synthetic map after the
    # game's default Object model half-turn.
    for instance in data["buildingBlockInstances"]:
        instance["rotation"] = 180
    profile = build_profile(leaning_tree())
    monkeypatch.setattr(library, "profiles", lambda *_: {"tree": profile})
    session.alchemist, geometry = import_map(
        json.dumps(data).encode(), "Slices.dam", session, library, load_geometry=True
    )
    session.add(geometry)
    return session, profile


def object_edges(session, obj):
    geometry = session.geometry()
    return [
        edge
        for edge, owners in zip(
            geometry.walls, memberships(session.alchemist, geometry), strict=True
        )
        if obj.id in owners
    ]


def test_levels_are_offline_reversible_and_preserve_other_contours(projected, tmp_path):
    session, _ = projected
    data, original = session.alchemist, session.geometry()
    regular = [
        (r, edge)
        for r, edge, owners in zip(
            original.lineage, original.walls, memberships(data, original), strict=True
        )
        if not owners
    ]
    changed = change_slice(session, "tree", 8)
    session.add(changed)
    assert values_for(session) == (-1, 8, -1, -1)
    assert session.alchemist is data
    assert all(
        (r, edge) in list(zip(changed.lineage, changed.walls, strict=True)) for r, edge in regular
    )
    for obj in data.objects:
        expected = profile_edges(
            obj,
            dict(data.profiles),
            8,
            {},
            alpha=data.alpha_projection,
            separate_parts=data.separate_projection_parts,
        )
        assert [v for e in object_edges(session, obj) for p in e for v in p] == pytest.approx(
            [v for e in expected for p in e for v in p]
        )
    session.undo()
    assert values_for(session) == (-1,) * 4
    assert session.geometry() is original
    session.redo()
    session.add(change_slice(session, "tree", 10))
    assert values_for(session)[1] == 10
    path = tmp_path / "offline.dale"
    save_project(session, path)
    with load_project(path) as loaded:
        assert loaded.session.alchemist == data
        assert values_for(loaded.session)[1] == 10
        loaded.session.add(change_slice(loaded.session, "tree", -1))
        for actual, expected in zip(loaded.session.geometry().walls, original.walls, strict=True):
            assert [v for p in actual for v in p] == pytest.approx([v for p in expected for v in p])


def test_switch_preserves_current_scale_rotation_and_translation(projected):
    session, _ = projected
    data = session.alchemist
    geometry = scale_category(session, "tree", 1.4)
    # Apply a common affine map, with a nontrivial rotation and translation.
    session.add(
        replace(
            geometry,
            walls=tuple(tuple((500 - y, x + 70) for x, y in edge) for edge in geometry.walls),
        )
    )
    before = session.geometry()
    session.add(change_slice(session, "tree", 8))
    session.add(change_slice(session, "tree", -1))
    by_id = {obj.id: object_edges(session, obj) for obj in data.objects}
    old = replace(session, operations=[before])
    for obj in data.objects:
        assert [v for e in by_id[obj.id] for p in e for v in p] == pytest.approx(
            [v for e in object_edges(old, obj) for p in e for v in p], abs=1e-7
        )


def test_empty_slab_can_return_without_resurrecting_deleted_objects(projected, tmp_path):
    session, _ = projected
    key, layers = session.alchemist.profiles[0]
    session.alchemist = replace(
        session.alchemist, profiles=((key, (*layers[:4], Polygon().wkb, *layers[5:])),)
    )
    before = session.geometry()
    session.add(change_slice(session, "tree", 4))
    assert not any(memberships(session.alchemist, session.geometry()))
    session.trim_history(0)
    target = tmp_path / "empty-band.dale"
    save_project(session, target)
    with load_project(target) as loaded:
        result = change_slice(loaded.session, "tree", -1)
        assert len(result.walls) == len(before.walls)
    session.add(change_slice(session, "tree", -1))
    assert len(session.geometry().walls) == len(before.walls)
    # Explicit deletion at a nonempty level is not treated as a temporarily empty slab.
    obj = session.alchemist.objects[0]
    geometry = session.geometry()
    keep = [
        i for i, own in enumerate(memberships(session.alchemist, geometry)) if obj.id not in own
    ]
    session.add(
        replace(
            geometry,
            walls=tuple(geometry.walls[i] for i in keep),
            lineage=tuple(geometry.lineage[i] for i in keep),
            ancestry=(
                *geometry.ancestry,
                *[geometry.lineage[i] for i in range(len(geometry.lineage)) if i not in keep],
            ),
        )
    )
    session.add(change_slice(session, "tree", 7))
    assert not object_edges(session, obj)


def test_slice_archive_validation_and_trim(projected):
    session, _ = projected
    session.add(change_slice(session, "tree", 7))
    session.add(replace(session.geometry(), alchemist_slices=None))
    session.trim_history(1)
    assert values_for(session)[1] == 7
    payload = json.loads(json.dumps(session.alchemist.encode()))
    payload["objects"][0]["projection"][0] = 42
    with pytest.raises(ValueError, match="placement"):
        DAData.decode(payload)
    with pytest.raises(ValueError):
        decode_profiles([["tree", ["!"] * 10]])


def send_wheel(window, target, delta=120):
    point = target.rect().center()
    event = QWheelEvent(
        QPointF(point),
        QPointF(target.mapToGlobal(point)),
        QPoint(),
        QPoint(0, delta),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(target, event)


@pytest.mark.parametrize("route", ["button", "field", "canvas"])
def test_da_ctrl_scale_changes_step_even_when_another_tool_is_active(editor, route):
    window = editor
    window.view.figure_line_ids = window.view.session.alchemist.objects[0].roots
    window.activate_mode("Move figures" if route != "canvas" else "Scale figures")
    button = window.alchemist_tool_buttons["Scale figures"]
    target = {
        "button": button,
        "field": button.editor().lineEdit(),
        "canvas": window.view.viewport(),
    }[route]
    before = window.view.session.geometry()
    old = window.figure_scale_control.value()
    send_wheel(window, target)
    assert window.figure_scale_control.value() == old + 1
    assert button.editor().value() == old + 1
    assert window.view.session.geometry() is before


def test_passive_indicator_has_exact_endpoints_and_uniform_scale(editor):
    indicator = SliceIndicator(editor)
    assert indicator.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert indicator.windowFlags() & Qt.WindowType.WindowTransparentForInput
    assert indicator.focusPolicy() == Qt.FocusPolicy.NoFocus
    positions = [indicator.level_y(i) for i in range(11)]
    assert positions[0] == indicator.model_rect().bottom()
    assert positions[-1] == indicator.model_rect().top()
    assert [a - b for a, b in zip(positions, positions[1:], strict=False)] == pytest.approx(
        [indicator.model_rect().height() / 10] * 10
    )
    assert not indicator.picture.isNull()


def test_alpha_outline_policy_is_strict_and_roundtrips(projected, tmp_path):
    session, _ = projected
    assert session.alchemist.alpha_projection
    assert session.alchemist.separate_projection_parts
    encoded = json.loads(json.dumps(session.alchemist.encode()))
    encoded["alpha_projection"] = 1
    with pytest.raises(ValueError, match="alpha projection"):
        DAData.decode(encoded)
    del encoded["alpha_projection"]
    encoded["separate_projection_parts"] = 1
    with pytest.raises(ValueError, match="projection boundary"):
        DAData.decode(encoded)
    del encoded["separate_projection_parts"]
    existing = DAData.decode(encoded)
    assert not existing.alpha_projection
    assert not existing.separate_projection_parts
    session.alchemist = existing
    target = tmp_path / "existing-profile-policy.dale"
    save_project(session, target)
    with load_project(target) as loaded:
        assert not loaded.session.alchemist.alpha_projection
        assert loaded.session.geometry().walls == session.geometry().walls
