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


def load_language(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return "en" if data.get("language") == "en" else "ru"
    except (OSError, ValueError, AttributeError):
        return "ru"


def save_language(path: Path, language: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps({"language": language}), encoding="utf-8")
    os.replace(temporary, path)
