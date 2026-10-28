"""Per-category native JSON settings are staged, persistent and independent of filters."""

import json
from dataclasses import replace

import pytest
from PySide6.QtWidgets import QDialogButtonBox, QScrollArea
from test_alchemist import sample as sample
from test_alchemist_interaction import editor as editor

from dale.alchemist import DAData, export_session
from dale.alchemist_export import category_settings, defaults, encode_settings, validate
from dale.export_height import normalize_wall_heights
from dale.json_repair import repaired_json_bytes
from dale.project_io import load_project, save_project


@pytest.mark.parametrize(
    "category,move,sense,threshold",
    [
        ("tree", 20, 10, None),
        ("rock", 20, 10, None),
        ("bush", 0, 30, 5),
    ],
)
def test_category_defaults_match_requested_foundry_settings(
    sample, category, move, sense, threshold
):
    session, _, _, source = sample
    session.alchemist = replace(
        session.alchemist,
        objects=tuple(replace(o, category=category) for o in session.alchemist.objects),
    )
    before = session.geometry()
    data = json.loads(repaired_json_bytes(export_session(session))[0])
    assert data["walls"][0] == source.raw["walls"][0]
    for wall in data["walls"][1:]:
        assert (wall["move"], wall["light"], wall["sight"], wall["sound"]) == (
            move,
            sense,
            sense,
            0,
        )
        assert wall["dir"] == wall["door"] == wall["ds"] == 0
        assert wall["threshold"] == dict(
            light=threshold, sight=threshold, sound=None, attenuation=False
        )
        assert wall["flags"]["wall-height"] == dict(bottom=None, top=None)
    assert session.geometry() == before
    assert len(json.loads(repaired_json_bytes(export_session(session, False))[0])["walls"]) == 1


def test_custom_settings_roundtrip_and_global_normalization_priority(sample, tmp_path):
    session, _, _, _ = sample
    value = defaults("tree")
    value.update(dir=2, door=2, ds=2, doorSound="custom-door", light=40)
    value["threshold"].update(light=7, attenuation=True)
    value["flags"]["wall-height"] = dict(bottom=2, top=12)
    value["animation"] = dict(
        type="swing",
        texture="assets/door.png",
        flip=True,
        double=False,
        direction=-1,
        duration=900,
        strength=1.25,
    )
    session.alchemist = replace(
        session.alchemist, json_walls=(None, encode_settings(value), None, None)
    )
    path = tmp_path / "walls.dale"
    save_project(session, path)
    with load_project(path) as opened:
        assert category_settings(opened.session.alchemist, "tree") == value
        payload = repaired_json_bytes(export_session(opened.session))[0]
        raw = json.loads(payload)
        assert raw["walls"][1]["flags"]["wall-height"] == dict(bottom=2, top=12)
        assert raw["walls"][1]["animation"] == value["animation"]
        normalized = json.loads(normalize_wall_heights(payload, (True, -3, 8)))
        assert all(w["flags"]["wall-height"] == dict(bottom=-3, top=8) for w in normalized["walls"])
        assert normalized["walls"][1]["light"] == 40


@pytest.mark.parametrize(
    "field,bad", [("move", True), ("dir", 4), ("sight", 11), ("sound", float("nan"))]
)
def test_export_restrictions_are_strict(field, bad):
    value = defaults("tree")
    value[field] = bad
    with pytest.raises(ValueError):
        validate(value)


def test_invalid_settings_in_project_metadata_are_rejected(sample):
    session, _, _, _ = sample
    value = json.loads(json.dumps(session.alchemist.encode()))
    value["json_walls"] = [None, defaults("tree"), None, None]
    value["json_walls"][1]["threshold"]["light"] = -1
    with pytest.raises(ValueError):
        DAData.decode(value)


def test_category_popup_stages_export_settings_without_recalculation(editor, monkeypatch, tmp_path):
    window = editor
    session = window.view.session
    before = session.geometry()
    selection = window.view.figure_line_ids
    filters = session.alchemist.settings, session.alchemist.minimum_heights_ft
    window.show_alchemist_category_settings("tree")
    dialog = window.tool_settings_popup
    assert dialog.findChild(QScrollArea) is not None
    assert dialog.height() <= dialog.screen().availableGeometry().height()
    controls = dialog.wall_export
    controls.senses["light"].setCurrentIndex(controls.senses["light"].findData(30))
    controls.thresholds["light"].setValue(0)
    controls.height_fields["bottom"][1].setChecked(False)
    controls.height_fields["top"][1].setChecked(False)
    controls.height_fields["bottom"][0].setValue(20)
    controls.height_fields["top"][0].setValue(10)
    button = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert not button.isEnabled()
    controls.height_fields["top"][0].setValue(30)
    assert button.isEnabled()
    dialog.reject()
    assert session.alchemist.json_walls == (None,) * 4
    window.show_alchemist_category_settings("tree")
    dialog = window.tool_settings_popup
    dialog.wall_export.movement.setCurrentIndex(0)
    monkeypatch.setattr(
        window, "refresh", lambda: pytest.fail("JSON settings must not recalculate")
    )
    dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).click()
    assert category_settings(session.alchemist, "tree")["move"] == 0
    assert (session.alchemist.settings, session.alchemist.minimum_heights_ft) == filters
    assert window.view.figure_line_ids == selection
    assert session.geometry() == before
    path = tmp_path / "staged.dale"
    save_project(session, path)
    with load_project(path) as opened:
        assert category_settings(opened.session.alchemist, "tree")["move"] == 0
        assert category_settings(opened.session.alchemist, "bush")["move"] == 0
        assert category_settings(opened.session.alchemist, "rock")["move"] == 20
