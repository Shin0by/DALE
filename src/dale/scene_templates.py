"""Reusable scene definitions, independent of placed geometry and source assets."""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from uuid import uuid4

TEMPLATE_FORMAT = "dale-scene-templates"
TEMPLATE_SCHEMA = 1
MAX_TEMPLATE_BYTES = 2 * 1024 * 1024
PRESET_ICONS = (
    "wall",
    "window",
    "window_locked",
    "window_barred",
    "door",
    "door_locked",
    "door_secret",
    "door_secret_locked",
)
SENSE_CHOICES = (
    ("None", 0),
    ("Limited", 10),
    ("Normal", 20),
    ("Proximity", 30),
    ("Reverse proximity", 40),
)
ANIMATION_TYPES = ("", "ascend", "descend", "slide", "swing", "swivel")
PALETTE = (
    "#e53935",
    "#fb8c00",
    "#fdd835",
    "#7cb342",
    "#43a047",
    "#00897b",
    "#00acc1",
    "#039be5",
    "#3949ab",
    "#5e35b1",
    "#8e24aa",
    "#d81b60",
    "#8d6e63",
    "#757575",
    "#bdbdbd",
    "#ffffff",
)


def identity():
    return uuid4().hex


def default_wall_properties():
    return {
        "dir": 0,
        "move": 20,
        "light": 20,
        "sight": 20,
        "sound": 20,
        "door": 0,
        "ds": 0,
        "doorSound": "",
        "threshold": {"light": None, "sight": None, "sound": None, "attenuation": False},
        "animation": {
            "type": "",
            "texture": None,
            "flip": False,
            "double": False,
            "direction": 1,
            "duration": 750,
            "strength": 1.0,
        },
    }


@dataclass(frozen=True)
class LevelTemplate:
    id: str = field(default_factory=identity)
    name: str = "Level"
    bottom_ft: int | None = None
    top_ft: int | None = None
    color: str = PALETTE[6]
    visible: bool = True


@dataclass(frozen=True)
class WallPreset:
    id: str = field(default_factory=identity)
    name: str = "Wall preset"
    icon: str = "wall"
    properties: dict = field(default_factory=default_wall_properties)


@dataclass(frozen=True)
class SceneTemplates:
    levels: tuple[LevelTemplate, ...] = ()
    wall_presets: tuple[WallPreset, ...] = ()

    def to_data(self):
        return {
            "format": TEMPLATE_FORMAT,
            "schema_version": TEMPLATE_SCHEMA,
            "levels": [asdict(item) for item in self.levels],
            "wall_presets": [asdict(item) for item in self.wall_presets],
        }

    def to_bytes(self):
        return json.dumps(
            self.to_data(), ensure_ascii=True, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")

    def merge(self, incoming, *, levels=True, presets=True):
        """Import definitions as independent records; never overwrite existing IDs."""
        return SceneTemplates(
            self.levels + tuple(replace(item, id=identity()) for item in incoming.levels)
            if levels
            else self.levels,
            self.wall_presets
            + tuple(replace(item, id=identity()) for item in incoming.wall_presets)
            if presets
            else self.wall_presets,
        ).validated()

    def validated(self):
        return decode_templates(self.to_data())


def _exact(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"Invalid {label} fields.")


def _text(value, label, maximum=128, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()):
        raise ValueError(f"Invalid {label}.")
    return value


def _enum(value, choices, label):
    if type(value) is not int or value not in choices:
        raise ValueError(f"Invalid {label}.")


def _finite(value, label, *, nullable=False, maximum=1_000_000):
    if nullable and value is None:
        return
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= maximum:
        raise ValueError(f"Invalid {label}.")


def validate_wall_properties(value):
    _exact(value, default_wall_properties(), "wall preset")
    for key, choices in (
        ("dir", (0, 1, 2)),
        ("move", (0, 20)),
        ("door", (0, 1, 2)),
        ("ds", (0, 1, 2)),
    ):
        _enum(value[key], choices, key)
    for key in ("light", "sight", "sound"):
        _enum(value[key], (0, 10, 20, 30, 40), key)
    _text(value["doorSound"], "door sound key", 512, empty=True)
    threshold = value["threshold"]
    _exact(threshold, ("light", "sight", "sound", "attenuation"), "threshold")
    for key in ("light", "sight", "sound"):
        _finite(threshold[key], "threshold distance", nullable=True)
    if type(threshold["attenuation"]) is not bool:
        raise ValueError("Invalid threshold attenuation.")
    animation = value["animation"]
    _exact(
        animation,
        ("type", "texture", "flip", "double", "direction", "duration", "strength"),
        "door animation",
    )
    _text(animation["type"], "animation type", 128, empty=True)
    if animation["texture"] is not None:
        _text(animation["texture"], "animation texture", 2048, empty=True)
    if any(type(animation[key]) is not bool for key in ("flip", "double")):
        raise ValueError("Invalid door animation switch.")
    _enum(animation["direction"], (-1, 1), "animation direction")
    _finite(animation["duration"], "animation duration")
    _finite(animation["strength"], "animation strength")


def decode_templates(data):
    _exact(data, ("format", "schema_version", "levels", "wall_presets"), "scene templates")
    if (
        data["format"] != TEMPLATE_FORMAT
        or type(data["schema_version"]) is not int
        or data["schema_version"] != TEMPLATE_SCHEMA
    ):
        raise ValueError("Unsupported scene template format or version.")
    for key, maximum in (("levels", 256), ("wall_presets", 1024)):
        if not isinstance(data[key], list) or len(data[key]) > maximum:
            raise ValueError("Too many or invalid scene template definitions.")
    identifiers, levels, presets = set(), [], []
    for key in ("levels", "wall_presets"):
        for item in data[key]:
            _exact(
                item,
                ("id", "name", "bottom_ft", "top_ft", "color", "visible")
                if key == "levels"
                else ("id", "name", "icon", "properties"),
                key,
            )
            identifier = item["id"]
            if (
                not isinstance(identifier, str)
                or not re.fullmatch(r"[0-9a-f]{32}", identifier)
                or identifier in identifiers
            ):
                raise ValueError("Invalid or duplicate scene template identity.")
            identifiers.add(identifier)
            _text(item["name"], "template name")
            if key == "levels":
                bottom, top = item["bottom_ft"], item["top_ft"]
                for height in (bottom, top):
                    if height is not None and (type(height) is not int or abs(height) > 1_000_000):
                        raise ValueError("Level heights must be whole feet or empty.")
                if not isinstance(item["color"], str) or not re.fullmatch(
                    r"#[0-9a-fA-F]{6}", item["color"]
                ):
                    raise ValueError("Level color must be an RGB hex value.")
                if type(item["visible"]) is not bool:
                    raise ValueError("Invalid level visibility.")
                if bottom is not None and top is not None and bottom > top:
                    item = {**item, "bottom_ft": top, "top_ft": bottom}
                levels.append(LevelTemplate(**item))
            else:
                if item["icon"] not in PRESET_ICONS:
                    raise ValueError("Invalid wall preset icon.")
                validate_wall_properties(item["properties"])
                presets.append(WallPreset(**item))
    return SceneTemplates(tuple(levels), tuple(presets))


def read_template_bytes(data):
    if len(data) > MAX_TEMPLATE_BYTES:
        raise ValueError("Scene templates exceed the 2 MiB limit.")
    return decode_templates(json.loads(data))


def save_template_file(library: SceneTemplates, destination: Path):
    payload = library.validated().to_bytes()
    if len(payload) > MAX_TEMPLATE_BYTES:
        raise ValueError("Scene templates exceed the 2 MiB limit.")
    temporary = None
    try:
        fd, name = tempfile.mkstemp(prefix=".dale-templates-", dir=destination.parent)
        temporary = Path(name)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_template_file(path: Path):
    if path.stat().st_size > MAX_TEMPLATE_BYTES:
        raise ValueError("Scene templates exceed the 2 MiB limit.")
    return read_template_bytes(path.read_bytes())
