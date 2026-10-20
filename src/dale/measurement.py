"""Source-pixel ruler coordinates and declared scene-world distance conversion."""

import math
import re
from dataclasses import dataclass

UNITS = ("px", "ft", "cm", "mm")
MAX_GUIDES = 4096


def measurement_settings(value=None):
    value = {} if value is None else value
    defaults = {
        "crosshair": False,
        "rulers": False,
        "move_guides": False,
        "isolate_regions": False,
        "background_kind": "checker",
        "background_color": "#303030",
        "raster_offset": 0,
        "preview_merge": None,
        "preview_grid": False,
        "export_grid_size": 0,
        "export_grid_visible": False,
        "export_grid_color": "#e5bd78",
        "export_grid_transparency": 56,
        "export_grid_width": 1,
        "preview_json": True,
        "preview_naming": None,
        "selection": None,
        "full_resolution": False,
        "unit": "px",
        "snap": False,
        "grid": False,
        "step": 100.0,
        "guides": [],
    }
    if not isinstance(value, dict) or set(value) - set(defaults):
        raise ValueError("Invalid raster ruler settings.")
    result = {**defaults, **value}
    if any(
        type(result[key]) is not bool
        for key in (
            "crosshair",
            "rulers",
            "move_guides",
            "isolate_regions",
            "preview_grid",
            "export_grid_visible",
            "preview_json",
            "full_resolution",
            "snap",
            "grid",
        )
    ):
        raise ValueError("Invalid raster ruler switches.")
    if result["unit"] not in UNITS:
        raise ValueError("Invalid ruler unit.")
    if any(
        type(result[key]) is not int or not 0 <= result[key] <= 1_000_000_000
        for key in ("export_grid_size",)
    ):
        raise ValueError("Invalid export grid cell size.")
    if not isinstance(result["export_grid_color"], str) or not re.fullmatch(
        r"#[0-9a-fA-F]{6}", result["export_grid_color"]
    ):
        raise ValueError("Invalid export grid color.")
    if (
        type(result["export_grid_transparency"]) is not int
        or not 0 <= result["export_grid_transparency"] <= 100
        or type(result["export_grid_width"]) is not int
        or not 1 <= result["export_grid_width"] <= 16
    ):
        raise ValueError("Invalid export grid appearance.")
    selection = result["selection"]
    if selection is not None:
        from shapely import from_wkb

        if (
            not isinstance(selection, dict)
            or set(selection) != {"lines", "polygons", "pivot"}
            or not isinstance(selection["lines"], list)
            or not 1 <= len(selection["lines"]) <= 100000
            or any(not isinstance(i, str) or not 1 <= len(i) <= 256 for i in selection["lines"])
            or not isinstance(selection["polygons"], list)
            or not 1 <= len(selection["polygons"]) <= 100000
            or not isinstance(selection["pivot"], (tuple, list))
            or len(selection["pivot"]) != 2
            or any(
                type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e9
                for v in selection["pivot"]
            )
        ):
            raise ValueError("Invalid raster region selection.")
        for encoded in selection["polygons"]:
            if not isinstance(encoded, str) or len(encoded) > 32 * 1024 * 1024:
                raise ValueError("Invalid raster region selection polygon.")
            try:
                area = from_wkb(bytes.fromhex(encoded))
            except Exception as exc:
                raise ValueError("Invalid raster region selection polygon.") from exc
            if (
                area.geom_type != "Polygon"
                or area.is_empty
                or not area.is_valid
                or any(not -1e9 <= v <= 1e9 for v in area.bounds)
            ):
                raise ValueError("Invalid raster region selection polygon.")
    if (
        type(result["raster_offset"]) is not int
        or not -4096 <= result["raster_offset"] <= 4096
        or result["preview_merge"] is not None
        and type(result["preview_merge"]) is not bool
        or result["preview_naming"] not in (None, "dataset", "group")
    ):
        raise ValueError("Invalid region preview settings.")
    if (
        result["background_kind"] not in ("checker", "solid")
        or not isinstance(result["background_color"], str)
        or not re.fullmatch(r"#[0-9a-fA-F]{6}", result["background_color"])
    ):
        raise ValueError("Invalid canvas background settings.")
    step = result["step"]
    if type(step) not in (int, float) or not math.isfinite(step) or not 0.000001 <= step <= 1e9:
        raise ValueError("Invalid ruler grid spacing.")
    guides = result["guides"]
    if not isinstance(guides, list) or len(guides) > MAX_GUIDES:
        raise ValueError("Invalid raster guides.")
    normalized = []
    for guide in guides:
        if not isinstance(guide, dict) or set(guide) != {"axis", "position"}:
            raise ValueError("Invalid raster guide fields.")
        position = guide["position"]
        if (
            guide["axis"] not in ("x", "y")
            or type(position) not in (int, float)
            or not math.isfinite(position)
            or not -1e9 <= position <= 1e9
        ):
            raise ValueError("Invalid raster guide position.")
        normalized.append({"axis": guide["axis"], "position": float(position)})
    result.update(step=float(step), guides=normalized)
    return result


@dataclass(frozen=True)
class MeasurementScale:
    pixels_per_unit: tuple[float, float]
    unit: str

    def value(self, coordinate, axis):
        return coordinate / self.pixels_per_unit[axis]

    def position(self, value, axis):
        return value * self.pixels_per_unit[axis]

    def snap(self, coordinate, axis):
        return self.position(round(self.value(coordinate, axis)), axis)


def measurement_scale(source, unit):
    if unit not in UNITS:
        raise ValueError("Invalid ruler unit.")
    if unit == "px":
        return MeasurementScale((1.0, 1.0), unit)
    raw = source.raw
    grid = raw.get("grid")
    size = grid.get("size") if isinstance(grid, dict) else grid
    distance = grid.get("distance") if isinstance(grid, dict) else raw.get("gridDistance")
    units = grid.get("units") if isinstance(grid, dict) else raw.get("gridUnits")
    if any(
        type(v) not in (int, float) or not math.isfinite(v) or not 0 < v <= 1e9
        for v in (size, distance)
    ) or not isinstance(units, str):
        raise ValueError("World rulers require scene JSON grid size, distance and units.")
    factors = {
        "ft": 30.48,
        "feet": 30.48,
        "foot": 30.48,
        "фут": 30.48,
        "футы": 30.48,
        "футов": 30.48,
        "m": 100.0,
        "meter": 100.0,
        "meters": 100.0,
        "metre": 100.0,
        "metres": 100.0,
        "м": 100.0,
        "метр": 100.0,
        "метры": 100.0,
        "cm": 1.0,
        "см": 1.0,
        "mm": 0.1,
        "мм": 0.1,
        "km": 100000.0,
        "км": 100000.0,
        "in": 2.54,
        "inch": 2.54,
        "inches": 2.54,
        "yd": 91.44,
        "yard": 91.44,
    }
    factor = factors.get(units.strip().lower().rstrip("."))
    if factor is None:
        raise ValueError("Scene grid units cannot be converted to feet or centimeters.")
    wanted = {"ft": 30.48, "cm": 1.0, "mm": 0.1}[unit]
    pixels = tuple(
        size * source.size[i] / source.scene_size[i] * wanted / (distance * factor) for i in (0, 1)
    )
    return MeasurementScale(pixels, unit)


def ruler_interval(pixels_per_unit, zoom, label_spacing=75):
    target = label_spacing / max(1e-15, pixels_per_unit * zoom)
    power = 10 ** math.floor(math.log10(target))
    return next(value * power for value in (1, 2, 5, 10) if value * power >= target)


def grid_positions(low, high, step, zoom, min_spacing=8):
    """Thin only displayed lines at low zoom, retaining exact configured multiples."""
    stride = max(1, math.ceil(min_spacing / max(1e-15, step * zoom)))
    spacing = step * stride
    first, last = math.ceil(low / spacing), math.floor(high / spacing)
    return tuple(i * spacing for i in range(first, min(last + 1, first + 4096)))
