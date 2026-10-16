"""Small local preferences kept beside the portable application."""

import json
import os
import sys
from pathlib import Path


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


def load_foundry_major(path: Path) -> int:
    value = _load(path).get("foundry_major")
    return value if type(value) is int and value in (13, 14) else 14


def _save(path: Path, **changes):
    data = _load(path)
    data.update(changes)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data), encoding="utf-8")
    os.replace(temporary, path)


def save_language(path: Path, language: str):
    _save(path, language=language)


def save_foundry_major(path: Path, foundry_major: int):
    _save(path, foundry_major=foundry_major)


def load_move_related(path: Path) -> bool | None:
    value = _load(path).get("move_related_lines")
    return value if type(value) is bool else None


def save_move_related(path: Path, choice: bool | None):
    _save(path, move_related_lines=choice)


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
