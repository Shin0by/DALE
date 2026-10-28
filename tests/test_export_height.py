"""Export-only height normalization, source preservation and staged settings."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from dale.export_height import normalize_wall_heights, validate_height_normalization
from dale.json_repair import JsonCoordinateDocument
from dale.preferences import load_height_normalization, save_height_normalization
from dale.ui import MainWindow


def test_normalization_preserves_coordinates_properties_and_exact_nonwall_bytes():
    payload = (
        b'{ "name" : "Unchanged", "walls" : [{"_id":"door","c":[1,2,3,4],"door":1,'
        b'"flags":{"other":{"keep":true},"wall-height":{"bottom":-15,"top":44,"custom":7}}},'
        b'{"c":[4,5,6,7]}], "tokens" : [ ] }\n'
    )
    result = normalize_wall_heights(payload, (True, -3, 17))
    old, new = JsonCoordinateDocument(payload), JsonCoordinateDocument(result)
    assert old.text[: old.walls_start] == new.text[: new.walls_start]
    assert old.text[old.walls_end + 1 :] == new.text[new.walls_end + 1 :]
    assert new.raw["walls"][0]["c"] == [1, 2, 3, 4]
    assert new.raw["walls"][0]["door"] == 1
    assert new.raw["walls"][0]["flags"]["other"] == {"keep": True}
    assert new.raw["walls"][0]["flags"]["wall-height"]["custom"] == 7
    for wall in new.raw["walls"]:
        assert wall["flags"]["wall-height"]["bottom"] == -3
        assert wall["flags"]["wall-height"]["top"] == 17
    assert normalize_wall_heights(payload, (False, -3, 17)) is payload


@pytest.mark.parametrize(
    "settings",
    [
        (True, 5, 5),
        (True, 8, 2),
        (True, 0.5, 10),
        (True, False, 10),
        (1, 0, 10),
        (True, -10001, 10),
    ],
)
def test_invalid_normalization_is_rejected(settings):
    with pytest.raises(ValueError):
        validate_height_normalization(settings)


def test_preferences_roundtrip_and_invalid_fallback(tmp_path):
    path = tmp_path / "settings.json"
    assert load_height_normalization(path) == (False, 0, 10)
    save_height_normalization(path, (True, -7, 23))
    assert load_height_normalization(path) == (True, -7, 23)
    path.write_text(json.dumps({"height_normalization": [True, 20, 1]}))
    assert load_height_normalization(path) == (False, 0, 10)


def test_export_height_popup_is_staged_and_has_integer_foot_steps(tmp_path):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "preferences.json"
    window = MainWindow(preferences_path=path)
    try:
        window.show_tool_settings("Export selected regions")
        dialog = window.tool_settings_popup
        dialog.normalize_height.setChecked(True)
        dialog.base_height.setValue(-7)
        dialog.top_height.setValue(23)
        assert all(s.singleStep() == 1 for s in dialog.height_sliders)
        assert [s.value() for s in dialog.height_sliders] == [-7, 23]
        dialog.reject()
        assert window.height_normalization == (False, 0, 10)
        assert load_height_normalization(path) == (False, 0, 10)
        window.show_tool_settings("Export selected regions")
        dialog = window.tool_settings_popup
        dialog.normalize_height.setChecked(True)
        dialog.base_height.setValue(30)
        assert not dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
        dialog.height_sliders[0].setValue(-7)
        dialog.height_sliders[1].setValue(23)
        assert dialog.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
        dialog.accept()
        assert window.height_normalization == (True, -7, 23)
        assert load_height_normalization(path) == (True, -7, 23)
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_selected_export_perimeter_merge_setting_is_staged_and_persistent(tmp_path):
    from dale.preferences import load_merge_export_contours

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "preferences.json"
    window = MainWindow(preferences_path=path)
    try:
        popup = window.show_tool_settings("Export selected regions")
        assert not popup.merge_contours.isChecked()
        popup.merge_contours.setChecked(True)
        assert not popup.default_action.isEnabled()
        popup.reject()
        assert not window.merge_export_contours and not load_merge_export_contours(path)
        popup = window.show_tool_settings("Export selected regions")
        popup.merge_contours.setChecked(True)
        popup.json_export.setChecked(False)
        popup.accept()
        assert window.merge_export_contours and window.merge_selected_regions
        assert load_merge_export_contours(path) and not window.include_json
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()
