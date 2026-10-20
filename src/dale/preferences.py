"""Small local preferences kept beside the portable application."""

import json
import os
import re
import sys
from pathlib import Path

ROTATION_VALUE_RANGES = {
    "figure_rotation_step_cdeg": (1, 36000, 10),
    "figure_alt_rotation_step_cdeg": (1, 36000, 4500),
    "region_rotation_step_cdeg": (1, 36000, 10),
    "region_alt_rotation_step_cdeg": (1, 36000, 4500),
}

TOOL_VALUE_RANGES = {
    "circle_detail_steps": (0, 95, 0),
    "line_eraser_diameter": (1, 512, 24),
    "vertex_eraser_diameter": (1, 512, 24),
    "raster_erase_diameter": (1, 4096, 40),
    "raster_restore_diameter": (1, 4096, 40),
    "raster_erase_square_diameter": (1, 4096, 40),
    "raster_restore_square_diameter": (1, 4096, 40),
    "auto_close_distance_px": (1, 256, 14),
    "global_close_distance_px": (1, 256, 14),
    "snap_distance_px": (0, 256, 14),
    "right_angle_tolerance_deg": (1, 90, 5),
    "contour_alignment_distance_px": (1, 9999, 14),
    "extension_distance_px": (1, 9999, 14),
    "artwork_offset_px": (-4096, 4096, 0),
    **ROTATION_VALUE_RANGES,
}


def settings_path() -> Path:
    if os.environ.get("DALE_SETTINGS_PATH"):
        return Path(os.environ["DALE_SETTINGS_PATH"])
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "UserData" / "settings.json"
    return Path(__file__).resolve().parents[2] / "artifacts" / "user-settings.json"


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def load_language(path: Path) -> str:
    return "en" if _load(path).get("language") == "en" else "ru"


def _save(path: Path, **changes):
    data = _load(path)
    data.update(changes)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data), encoding="utf-8")
    os.replace(temporary, path)


def save_language(path: Path, language: str):
    _save(path, language=language)


def load_right_panel_visible(path: Path) -> bool:
    value = _load(path).get("right_panel_visible", True)
    return value if type(value) is bool else True


def save_right_panel_visible(path: Path, visible: bool):
    _save(path, right_panel_visible=visible)


def load_tool_values(path: Path) -> dict[str, int]:
    stored = _load(path).get("tool_values", {})
    if not isinstance(stored, dict):
        stored = {}
    return {
        key: value if type(value := stored.get(key)) is int and low <= value <= high else default
        for key, (low, high, default) in TOOL_VALUE_RANGES.items()
    }


def save_tool_value(path: Path, key: str, value: int):
    low, high, _ = TOOL_VALUE_RANGES[key]
    if type(value) is not int or not low <= value <= high:
        raise ValueError("Tool value is outside its supported integer range.")
    values = load_tool_values(path)
    values[key] = value
    _save(path, tool_values=values)


def load_global_tool_settings(path: Path) -> bool:
    return _load(path).get("global_tool_settings") is True


def save_global_tool_settings(path: Path, enabled: bool):
    _save(path, global_tool_settings=enabled)


def load_move_related(path: Path) -> bool | None:
    value = _load(path).get("move_related_lines")
    return value if type(value) is bool else None


def save_move_related(path: Path, choice: bool | None):
    _save(path, move_related_lines=choice)


def load_merge_selected_regions(path: Path) -> bool | None:
    value = _load(path).get("merge_selected_regions")
    return value if type(value) is bool else None


def save_merge_selected_regions(path: Path, choice: bool | None):
    if choice is not None and type(choice) is not bool:
        raise ValueError("Invalid selected-region export preference.")
    _save(path, merge_selected_regions=choice)


def load_size_to_grid(path: Path) -> bool:
    return _load(path).get("size_to_grid") is True


def load_export_group_naming(path: Path) -> str | None:
    value = _load(path).get("export_group_naming")
    return value if isinstance(value, str) and value in ("dataset", "group") else None


def save_export_group_naming(path: Path, choice: str | None):
    if choice is not None and choice not in ("dataset", "group"):
        raise ValueError("Invalid group export naming preference.")
    _save(path, export_group_naming=choice)


def load_include_json(path: Path) -> bool:
    value = _load(path).get("include_json", True)
    return value if type(value) is bool else True


def save_include_json(path: Path, enabled: bool):
    if type(enabled) is not bool:
        raise ValueError("Invalid JSON export preference.")
    _save(path, include_json=enabled)


def save_size_to_grid(path: Path, enabled: bool):
    if type(enabled) is not bool:
        raise ValueError("Invalid grid export preference.")
    _save(path, size_to_grid=enabled)


CONNECTION_TOOLS = ("Erase lines", "Edit points")


def load_connection_choice(path: Path, tool: str) -> bool | None:
    if tool not in CONNECTION_TOOLS:
        raise ValueError("Unknown contour connection tool.")
    stored = _load(path).get("contour_connection_choices", {})
    value = stored.get(tool) if isinstance(stored, dict) else None
    return value if type(value) is bool else None


def save_connection_choice(path: Path, tool: str, choice: bool | None):
    if tool not in CONNECTION_TOOLS or (choice is not None and type(choice) is not bool):
        raise ValueError("Invalid contour connection preference.")
    choices = {key: load_connection_choice(path, key) for key in CONNECTION_TOOLS}
    choices[tool] = choice
    _save(path, contour_connection_choices=choices)


def load_directory(path: Path, purpose: str) -> Path | None:
    if purpose not in ("input", "output"):
        raise ValueError("Directory purpose must be input or output.")
    value = _load(path).get(f"{purpose}_directory")
    if not isinstance(value, str) or not value:
        return None
    try:
        directory = Path(value)
        return directory if directory.is_absolute() and directory.is_dir() else None
    except (ValueError, OSError):
        return None


def save_directory(path: Path, purpose: str, directory: Path):
    if purpose not in ("input", "output"):
        raise ValueError("Directory purpose must be input or output.")
    _save(path, **{f"{purpose}_directory": str(directory.resolve())})


def load_recent_projects(path: Path) -> list[Path]:
    stored = _load(path).get("recent_projects", [])
    if not isinstance(stored, list):
        return []
    result, seen = [], set()
    for value in stored:
        if not isinstance(value, str):
            continue
        candidate = Path(value)
        if not candidate.is_absolute() or candidate.suffix.lower() != ".dale":
            continue
        key = os.path.normcase(str(candidate))
        if key not in seen:
            seen.add(key)
            result.append(candidate)
        if len(result) == 10:
            break
    return result


def save_recent_projects(path: Path, projects: list[Path]):
    _save(path, recent_projects=[str(project.resolve()) for project in projects[:10]])


def _project_dataset_choices(path: Path) -> dict[str, str]:
    stored = _load(path).get("project_datasets", {})
    if not isinstance(stored, dict):
        return {}
    choices = {}
    for name, identifier in list(stored.items())[-100:]:
        if not isinstance(name, str) or not isinstance(identifier, str):
            continue
        try:
            project = Path(name)
            if (
                project.is_absolute()
                and project.suffix.lower() == ".dale"
                and re.fullmatch(r"set-[a-f0-9]{32}", identifier)
            ):
                choices[os.path.normcase(str(project.resolve()))] = identifier
        except (OSError, ValueError):
            continue
    return choices


def load_project_dataset(path: Path, project: Path) -> str | None:
    return _project_dataset_choices(path).get(os.path.normcase(str(project.resolve())))


def save_project_dataset(path: Path, project: Path, identifier: str):
    if (
        not isinstance(identifier, str)
        or not re.fullmatch(r"set-[a-f0-9]{32}", identifier)
        or project.suffix.lower() != ".dale"
    ):
        raise ValueError("Invalid project dataset preference.")
    choices = _project_dataset_choices(path)
    key = os.path.normcase(str(project.resolve()))
    choices.pop(key, None)
    choices[key] = identifier
    _save(path, project_datasets=dict(list(choices.items())[-100:]))
