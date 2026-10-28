"""Independent per-category Foundry wall export settings, never display filters."""

import json
import math

from dale.wall_styles import ordinary_wall

CATEGORIES = ("wall", "tree", "bush", "rock")
ANIMATIONS = ("", "ascend", "descend", "slide", "swing", "swivel")


def defaults(category):
    value = ordinary_wall()
    value.update(
        doorSound="",
        animation=None,
        threshold={"light": None, "sight": None, "sound": None, "attenuation": False},
    )
    if category in ("tree", "rock"):
        value.update(move=20, light=10, sight=10, sound=0)
    elif category == "bush":
        value.update(move=0, light=30, sight=30, sound=0)
        value["threshold"].update(light=5, sight=5)
    return value


def validate(value):
    def number(number, low, high, nullable=False):
        if number is None and nullable:
            return
        if (
            type(number) not in (int, float)
            or not math.isfinite(number)
            or not low <= number <= high
        ):
            raise ValueError("Invalid JSON wall numeric setting.")

    if not isinstance(value, dict) or set(value) != set(defaults("wall")):
        raise ValueError("Invalid JSON wall settings.")
    for key, allowed in (
        ("move", (0, 20)),
        ("dir", (0, 1, 2)),
        ("door", (0, 1, 2)),
        ("ds", (0, 1, 2)),
        *((key, (0, 10, 20, 30, 40)) for key in ("light", "sight", "sound")),
    ):
        if type(value[key]) is not int or value[key] not in allowed:
            raise ValueError("Invalid JSON wall restriction.")
    threshold = value["threshold"]
    if (
        not isinstance(threshold, dict)
        or set(threshold) != {"light", "sight", "sound", "attenuation"}
        or type(threshold["attenuation"]) is not bool
    ):
        raise ValueError("Invalid JSON wall thresholds.")
    for key in ("light", "sight", "sound"):
        number(threshold[key], 0, 1000000, True)
    flags = value["flags"]
    if (
        not isinstance(flags, dict)
        or set(flags) != {"wall-height"}
        or not isinstance(flags["wall-height"], dict)
        or set(flags["wall-height"]) != {"bottom", "top"}
    ):
        raise ValueError("Invalid JSON wall heights.")
    bottom, top = (flags["wall-height"][key] for key in ("bottom", "top"))
    number(bottom, -10000, 10000, True)
    number(top, -10000, 10000, True)
    if bottom is not None and top is not None and top <= bottom:
        raise ValueError("JSON wall top must be above its base.")
    if not isinstance(value["doorSound"], str) or len(value["doorSound"]) > 512:
        raise ValueError("Invalid JSON door sound.")
    animation = value["animation"]
    if animation is not None:
        if not isinstance(animation, dict) or set(animation) != {
            "type",
            "texture",
            "flip",
            "double",
            "direction",
            "duration",
            "strength",
        }:
            raise ValueError("Invalid JSON door animation.")
        if (
            not isinstance(animation["type"], str)
            or len(animation["type"]) > 128
            or (
                animation["texture"] is not None
                and (not isinstance(animation["texture"], str) or len(animation["texture"]) > 2048)
            )
            or any(type(animation[k]) is not bool for k in ("flip", "double"))
            or type(animation["direction"]) is not int
            or animation["direction"] not in (-1, 1)
        ):
            raise ValueError("Invalid JSON door animation.")
        number(animation["duration"], 0, 1000000)
        number(animation["strength"], 0, 1000000)
    return value


def encode_settings(value):
    return json.dumps(validate(value), ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def decode_settings(values):
    if values is None:
        return (None,) * 4
    if not isinstance(values, list) or len(values) != 4:
        raise ValueError("Invalid category JSON wall settings.")
    return tuple(encode_settings(v) if v is not None else None for v in values)


def category_settings(data, category):
    encoded = data.json_walls[CATEGORIES.index(category)]
    return json.loads(encoded) if encoded is not None else defaults(category)
