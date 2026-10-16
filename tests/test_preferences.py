import json

import pytest

from dale.preferences import (
    load_directory,
    load_foundry_major,
    load_language,
    load_move_related,
    load_tool_values,
    save_directory,
    save_foundry_major,
    save_language,
    save_move_related,
    save_tool_value,
)


def test_language_preferences_survive_restart_and_invalid_files(tmp_path):
    path = tmp_path / "UserData" / "settings.json"
    assert load_language(path) == "ru"
    save_language(path, "en")
    assert load_language(path) == "en"
    path.write_text("invalid", encoding="utf-8")
    assert load_language(path) == "ru"


def test_foundry_and_language_preferences_merge_and_survive_restart(tmp_path):
    path = tmp_path / "settings.json"
    assert load_foundry_major(path) == 14
    save_foundry_major(path, 13)
    save_language(path, "en")
    assert load_foundry_major(path) == 13
    assert load_language(path) == "en"
    save_foundry_major(path, 14)
    assert load_language(path) == "en"
    assert load_foundry_major(path) == 14
    path.write_text(json.dumps({"foundry_major": "13", "language": "en"}), encoding="utf-8")
    assert load_foundry_major(path) == 14
    path.write_text("[]", encoding="utf-8")
    assert load_foundry_major(path) == 14


def test_related_line_choice_is_optional_and_preserves_other_preferences(tmp_path):
    path = tmp_path / "settings.json"
    assert load_move_related(path) is None
    save_foundry_major(path, 13)
    save_language(path, "en")
    for choice in (True, False, None):
        save_move_related(path, choice)
        assert load_move_related(path) is choice
        assert load_foundry_major(path) == 13
        assert load_language(path) == "en"


def test_input_and_output_directories_are_independent_and_merge(tmp_path):
    path = tmp_path / "settings.json"
    source, output = tmp_path / "sources", tmp_path / "output"
    source.mkdir()
    output.mkdir()
    assert load_directory(path, "input") is None
    save_directory(path, "input", source)
    save_directory(path, "output", output)
    save_language(path, "en")
    save_move_related(path, True)
    assert load_directory(path, "input") == source
    assert load_directory(path, "output") == output
    source.rmdir()
    assert load_directory(path, "input") is None
    assert load_directory(path, "output") == output


def test_numeric_tool_preferences_merge_independently_and_validate_fields(tmp_path):
    path = tmp_path / "settings.json"
    save_language(path, "en")
    save_foundry_major(path, 13)
    save_tool_value(path, "artwork_offset_px", -123)
    save_tool_value(path, "snap_distance_px", 0)
    save_tool_value(path, "raster_restore_diameter", 4096)
    assert load_tool_values(path)["artwork_offset_px"] == -123
    assert load_tool_values(path)["snap_distance_px"] == 0
    assert load_tool_values(path)["raster_restore_diameter"] == 4096
    assert load_language(path) == "en" and load_foundry_major(path) == 13
    data = json.loads(path.read_text())
    data["tool_values"].update(line_eraser_diameter=True, auto_close_distance_px=257)
    path.write_text(json.dumps(data))
    assert load_tool_values(path)["line_eraser_diameter"] == 24
    assert load_tool_values(path)["auto_close_distance_px"] == 14
    assert load_tool_values(path)["artwork_offset_px"] == -123
    with pytest.raises(ValueError, match="integer range"):
        save_tool_value(path, "snap_distance_px", 257)
