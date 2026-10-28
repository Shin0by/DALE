"""Export-only normalization of native contour heights, preserving non-wall bytes."""

from dale.json_repair import JsonCoordinateDocument

DEFAULT_HEIGHT_NORMALIZATION = (False, 0, 10)
HEIGHT_LIMIT_FT = 10000


def validate_height_normalization(settings):
    if (
        not isinstance(settings, (tuple, list))
        or len(settings) != 3
        or type(settings[0]) is not bool
        or any(type(v) is not int or abs(v) > HEIGHT_LIMIT_FT for v in settings[1:])
        or (settings[0] and settings[1] >= settings[2])
    ):
        raise ValueError("Top height must be greater than base height; use whole feet.")
    return tuple(settings)


def normalize_wall_heights(payload, settings=DEFAULT_HEIGHT_NORMALIZATION):
    enabled, bottom, top = validate_height_normalization(settings)
    if not enabled:
        return payload
    document = JsonCoordinateDocument(payload)
    entries = []
    for index, original in enumerate(document.raw["walls"]):
        wall = dict(original)
        flags = wall.get("flags")
        flags = dict(flags) if isinstance(flags, dict) else {}
        heights = flags.get("wall-height")
        heights = dict(heights) if isinstance(heights, dict) else {}
        heights.update(bottom=bottom, top=top)
        flags["wall-height"] = heights
        wall["flags"] = flags
        entries.append((index, wall))
    return document.replace_walls(entries)
