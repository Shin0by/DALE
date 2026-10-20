import json

import pytest

from dale.preferences import (
    load_connection_choice,
    load_directory,
    load_export_group_naming,
    load_language,
    load_merge_selected_regions,
    load_move_related,
    load_recent_projects,
    load_right_panel_visible,
    load_size_to_grid,
    load_tool_values,
    save_connection_choice,
    save_directory,
    save_export_group_naming,
    save_language,
    save_merge_selected_regions,
    save_move_related,
    save_recent_projects,
    save_right_panel_visible,
    save_size_to_grid,
    save_tool_value,
)


@pytest.mark.parametrize("value", [True, False, 1, [], {}, "other"])
def test_group_export_naming_rejects_invalid_preferences(tmp_path, value):
    path = tmp_path / "preferences.json"
    path.write_text(json.dumps({"export_group_naming": value}), encoding="utf-8")
    assert load_export_group_naming(path) is None
    with pytest.raises(ValueError):
        save_export_group_naming(path, value)


def test_group_export_naming_merges_and_resets_without_changing_other_preferences(tmp_path):
    path = tmp_path / "preferences.json"
    save_language(path, "ru")
    save_merge_selected_regions(path, True)
    for value in ("group", "dataset", None):
        save_export_group_naming(path, value)
        assert load_export_group_naming(path) == value
        assert load_language(path) == "ru" and load_merge_selected_regions(path) is True


def test_grid_export_choice_is_strict_and_independent_of_default_answers(tmp_path):
    path = tmp_path / "settings.json"
    assert not load_size_to_grid(path)
    save_merge_selected_regions(path, None)
    save_connection_choice(path, "Edit points", False)
    save_language(path, "en")
    for value in (True, False):
        save_size_to_grid(path, value)
        assert load_size_to_grid(path) is value
        assert load_merge_selected_regions(path) is None
        assert load_connection_choice(path, "Edit points") is False
        assert load_language(path) == "en"
    with pytest.raises(ValueError):
        save_size_to_grid(path, 1)
    path.write_text('{"size_to_grid": "true"}')
    assert not load_size_to_grid(path)


def test_connection_questions_are_independent_and_merge_portable_preferences(tmp_path):
    path = tmp_path / "settings.json"
    save_language(path, "en")
    assert load_connection_choice(path, "Edit points") is None
    save_connection_choice(path, "Erase lines", False)
    save_connection_choice(path, "Edit points", True)
    assert load_connection_choice(path, "Erase lines") is False
    assert load_connection_choice(path, "Edit points") is True
    save_connection_choice(path, "Erase lines", None)
    assert load_connection_choice(path, "Erase lines") is None
    assert load_connection_choice(path, "Edit points") is True
    assert load_language(path) == "en"
    with pytest.raises(ValueError):
        save_connection_choice(path, "Erase lines", 1)


def test_selected_export_question_is_optional_validated_and_merges_preferences(tmp_path):
    path = tmp_path / "settings.json"
    assert load_merge_selected_regions(path) is None
    save_language(path, "en")
    save_connection_choice(path, "Edit points", True)
    for value in (True, False, None):
        save_merge_selected_regions(path, value)
        assert load_merge_selected_regions(path) is value
        assert load_language(path) == "en"
        assert load_connection_choice(path, "Edit points") is True
    path.write_text('{"merge_selected_regions": 1}')
    assert load_merge_selected_regions(path) is None
    with pytest.raises(ValueError):
        save_merge_selected_regions(path, 1)


def test_language_preferences_survive_restart_and_invalid_files(tmp_path):
    path = tmp_path / "UserData" / "settings.json"
    assert load_language(path) == "ru"
    save_language(path, "en")
    assert load_language(path) == "en"
    path.write_text("invalid", encoding="utf-8")
    assert load_language(path) == "ru"


def test_right_panel_visibility_defaults_and_merges_with_other_preferences(tmp_path):
    path = tmp_path / "settings.json"
    assert load_right_panel_visible(path)
    save_language(path, "en")
    save_right_panel_visible(path, False)
    assert not load_right_panel_visible(path)
    save_tool_value(path, "snap_distance_px", 23)
    assert not load_right_panel_visible(path) and load_language(path) == "en"
    save_right_panel_visible(path, True)
    assert load_right_panel_visible(path) and load_tool_values(path)["snap_distance_px"] == 23
    data = json.loads(path.read_text())
    data["right_panel_visible"] = "false"
    path.write_text(json.dumps(data))
    assert load_right_panel_visible(path)


def test_related_line_choice_is_optional_and_preserves_other_preferences(tmp_path):
    path = tmp_path / "settings.json"
    assert load_move_related(path) is None
    save_language(path, "en")
    for choice in (True, False, None):
        save_move_related(path, choice)
        assert load_move_related(path) is choice
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
    save_tool_value(path, "artwork_offset_px", -123)
    save_tool_value(path, "snap_distance_px", 0)
    save_tool_value(path, "raster_restore_diameter", 4096)
    assert load_tool_values(path)["artwork_offset_px"] == -123
    assert load_tool_values(path)["snap_distance_px"] == 0
    assert load_tool_values(path)["raster_restore_diameter"] == 4096
    assert load_language(path) == "en"
    data = json.loads(path.read_text())
    data["tool_values"].update(line_eraser_diameter=True, auto_close_distance_px=257)
    path.write_text(json.dumps(data))
    assert load_tool_values(path)["line_eraser_diameter"] == 24
    assert load_tool_values(path)["auto_close_distance_px"] == 14
    assert load_tool_values(path)["artwork_offset_px"] == -123
    with pytest.raises(ValueError, match="integer range"):
        save_tool_value(path, "snap_distance_px", 257)


def test_recent_projects_validate_paths_limit_entries_and_preserve_other_settings(tmp_path):
    path = tmp_path / "settings.json"
    assert load_recent_projects(path) == []
    save_language(path, "en")
    projects = [tmp_path / f"project-{index}.dale" for index in range(12)]
    save_recent_projects(path, projects)
    assert load_recent_projects(path) == projects[:10]
    assert load_language(path) == "en"
    path.write_text(
        json.dumps(
            {
                "recent_projects": [
                    None,
                    42,
                    "relative.dale",
                    str(tmp_path / "x.json"),
                    str(projects[0]),
                    str(projects[0]),
                    str(projects[1]),
                ]
            }
        )
    )
    assert load_recent_projects(path) == projects[:2]


def test_include_json_is_strict_persistent_and_independent_of_other_export_choices(tmp_path):
    from dale.preferences import load_include_json, save_include_json

    path = tmp_path / "settings.json"
    assert load_include_json(path)
    save_size_to_grid(path, True)
    save_merge_selected_regions(path, False)
    for include in (False, True, False):
        save_include_json(path, include)
        assert load_include_json(path) is include
        assert load_size_to_grid(path) and load_merge_selected_regions(path) is False
    with pytest.raises(ValueError):
        save_include_json(path, 1)
    path.write_text('{"include_json":0}')
    assert load_include_json(path)


def test_last_dataset_is_scoped_by_project_and_merges_other_preferences(tmp_path):
    from dale.preferences import load_project_dataset, save_project_dataset

    settings = tmp_path / "settings.json"
    first, second = tmp_path / "First.dale", tmp_path / "Second.dale"
    a, b = "set-" + "a" * 32, "set-" + "b" * 32
    assert load_project_dataset(settings, first) is None
    save_language(settings, "en")
    save_tool_value(settings, "circle_detail_steps", 95)
    save_project_dataset(settings, first, a)
    save_project_dataset(settings, second, b)
    assert load_project_dataset(settings, first) == a
    assert load_project_dataset(settings, second) == b
    save_project_dataset(settings, first.parent / "." / first.name, b)
    assert load_project_dataset(settings, first) == b
    assert (
        load_language(settings) == "en" and load_tool_values(settings)["circle_detail_steps"] == 95
    )


def test_last_dataset_preferences_have_a_bounded_recent_project_list(tmp_path):
    from dale.preferences import load_project_dataset, save_project_dataset

    settings = tmp_path / "settings.json"
    for i in range(105):
        save_project_dataset(settings, tmp_path / f"{i}.dale", "set-" + f"{i:032x}")
    stored = json.loads(settings.read_text())["project_datasets"]
    assert len(stored) == 100
    assert load_project_dataset(settings, tmp_path / "0.dale") is None
    assert load_project_dataset(settings, tmp_path / "104.dale") == "set-" + f"{104:032x}"


@pytest.mark.parametrize("invalid", [None, [], "bad", {"relative.dale": "set-" + "a" * 32}])
def test_last_dataset_ignores_malformed_local_preferences(tmp_path, invalid):
    from dale.preferences import load_project_dataset

    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"project_datasets": invalid}))
    assert load_project_dataset(settings, tmp_path / "map.dale") is None


@pytest.mark.parametrize("invalid", [None, True, "", "set-nope", "set-" + "A" * 32])
def test_last_dataset_preferences_reject_invalid_identities(tmp_path, invalid):
    from dale.preferences import save_project_dataset

    with pytest.raises(ValueError):
        save_project_dataset(tmp_path / "settings.json", tmp_path / "map.dale", invalid)
