"""Inspect local map pairs without publishing sources or changing editor behavior."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, JpegImagePlugin

from dale.geometry import analyze_regions
from dale.placement import Placement
from dale.raster import export_png, load_preview
from dale.scene import MAX_SIDE, load_pair, open_source
from dale.session import ContourMask


def fingerprint(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def inspect_pair(
    json_path: Path, output: Path, previews: bool, gap_tolerances: list[float]
) -> dict:
    image_path = next(
        (
            json_path.with_suffix(extension)
            for extension in (".jpg", ".jpeg")
            if json_path.with_suffix(extension).is_file()
        ),
        None,
    )
    if image_path is None:
        raise ValueError(f"No JPG/JPEG sibling found for {json_path.name}.")
    source = load_pair(image_path, json_path)
    raw, walls = source.raw, source.image_walls()
    analysis = analyze_regions(walls)
    endpoints = Counter(point for segment in walls for point in segment)
    tips = [point for point, degree in endpoints.items() if degree == 1]
    nearest = (
        sorted(min(math.dist(p, q) for q in tips if p != q) for p in tips) if len(tips) > 1 else []
    )
    grid = raw.get("grid")
    grid_size = grid.get("size") if isinstance(grid, dict) else grid
    distance = grid.get("distance") if isinstance(grid, dict) else raw.get("gridDistance")
    units = grid.get("units") if isinstance(grid, dict) else raw.get("gridUnits")
    with open_source(image_path) as image:
        image_info = {
            "format": image.format,
            "mode": image.mode,
            "size": image.size,
            "dpi": image.info.get("dpi"),
            "jpeg_sampling_code": JpegImagePlugin.get_sampling(image),
            "progressive": bool(image.info.get("progressive")),
            "exif_orientation": image.getexif().get(274),
            "icc_profile_present": bool(image.info.get("icc_profile")),
        }
    result = {
        "pair": json_path.stem,
        "sources": {
            "image_bytes": image_path.stat().st_size,
            "json_bytes": json_path.stat().st_size,
            "image_sha256": fingerprint(image_path),
            "json_sha256": fingerprint(json_path),
        },
        "image": image_info,
        "scene": {
            "dimensions": source.scene_size,
            "padding": raw.get("padding"),
            "shift": [raw.get("shiftX"), raw.get("shiftY")],
            "background_offset": source.background_offset,
            "grid_pixels": grid_size,
            "grid_distance": distance,
            "grid_units": units,
            "grid_cells": [s / grid_size for s in source.size] if grid_size else None,
            "darkness": raw.get("darkness"),
            "globalLight": raw.get("globalLight"),
            "schema_profile": "legacy-grid-number"
            if isinstance(grid, (int, float))
            else "grid-object"
            if isinstance(grid, dict)
            else "unspecified",
            "root_field_types": {k: type(v).__name__ for k, v in raw.items()},
        },
        "geometry": {
            "wall_count": len(walls),
            "light_count": len(raw.get("lights", [])),
            "door_counts": dict(Counter(str(w.get("door")) for w in raw["walls"])),
            "sense_counts": dict(Counter(str(w.get("sense")) for w in raw["walls"])),
            "closed_faces": analysis.faces,
            "unresolved_segments": len(analysis.unresolved),
            "closed_area_pixels": analysis.area.area,
            "closed_area_percent": round(100 * analysis.area.area / math.prod(source.size), 6),
            "endpoint_degree_counts": dict(Counter(endpoints.values())),
            "nearest_free_endpoint_distances": nearest,
            "gap_tolerance_scan": [
                {
                    "tolerance_px": tolerance,
                    "joins": len(result.joins),
                    "closed_faces": result.faces,
                    "unresolved_segments": len(result.unresolved),
                    "closed_area_pixels": result.area.area,
                }
                for tolerance in gap_tolerances
                for result in [analyze_regions(walls, gap_tolerance=tolerance)]
            ],
        },
        "warnings": source.warnings,
    }
    if previews:
        preview = load_preview(source)
        preview.save(output / f"{json_path.stem}-preview.png")
        draw = ImageDraw.Draw(preview)
        sx, sy = preview.width / source.size[0], preview.height / source.size[1]
        for color, segments in (("cyan", walls), ("orange", analysis.unresolved)):
            for a, b in segments:
                draw.line((a[0] * sx, a[1] * sy, b[0] * sx, b[1] * sy), fill=color, width=2)
        preview.save(output / f"{json_path.stem}-walls.png")
        preview.close()
    return result


def verify_export(json_path: Path, output: Path, inspection: dict) -> dict:
    image_path = json_path.with_suffix(".jpg")
    if not image_path.is_file():
        image_path = json_path.with_suffix(".jpeg")
    source = load_pair(image_path, json_path)
    analysis = analyze_regions(source.image_walls())
    if not analysis.faces:
        raise ValueError("Cannot verify a contour mask without a closed face.")
    # This checks the pipeline only; unresolved source contours are deliberately not repaired.
    destination = output / f"{json_path.stem}-contour-check.png"
    milestone = [-1]

    def progress(percent):
        if percent // 25 > milestone[0]:
            milestone[0] = percent // 25
            print(f"Export verification: {percent}%", flush=True)

    started = time.perf_counter()
    export_png(
        source,
        [ContourMask(analysis.area, "outside")],
        destination,
        progress=progress,
        placement=Placement(14, 17),
    )
    seconds = round(time.perf_counter() - started, 2)
    interior = analysis.area.representative_point()
    point = (round(interior.x), round(interior.y))
    previous = Image.MAX_IMAGE_PIXELS
    try:
        Image.MAX_IMAGE_PIXELS = MAX_SIDE * MAX_SIDE
        with Image.open(destination) as image:
            assert image.size == source.size and image.mode == "RGBA"
            assert image.getpixel((0, 0))[3] == 0
            assert image.getpixel(point)[3] == 255
            assert image.info["DALE.ElevationFeet"] == "17"
    finally:
        Image.MAX_IMAGE_PIXELS = previous
    assert fingerprint(image_path) == inspection["sources"]["image_sha256"]
    assert fingerprint(json_path) == inspection["sources"]["json_sha256"]
    return {
        "pair": json_path.stem,
        "dimensions": source.size,
        "format": "RGBA PNG",
        "seconds": seconds,
        "png_bytes": destination.stat().st_size,
        "sources_unchanged": True,
        "checks": [
            "dimensions",
            "alpha_outside",
            "alpha_inside",
            "placement_metadata",
            "source_hashes",
        ],
        "scope": "Image pipeline check; not a finished floor mask or a Foundry import test.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, nargs="?", default=Path("examples"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/sample-analysis"))
    parser.add_argument("--previews", action="store_true")
    parser.add_argument("--verify-export", metavar="PAIR_STEM")
    parser.add_argument("--gap-tolerances", type=float, nargs="+", default=[0, 3, 6, 12, 24])
    args = parser.parse_args()
    output = args.output.resolve()
    directory = args.directory.resolve()
    if output == directory or directory in output.parents:
        parser.error("Analysis output must be outside the source directory.")
    output.mkdir(parents=True, exist_ok=True)
    reports = []
    exports = []
    for path in sorted(directory.glob("*.json")):
        report = inspect_pair(path, output, args.previews, args.gap_tolerances)
        reports.append(report)
        geo = report["geometry"]
        print(
            f"{path.stem}: {report['image']['size']}, {geo['wall_count']} walls, "
            f"{geo['closed_faces']} faces, {geo['unresolved_segments']} unresolved",
            flush=True,
        )
        if args.verify_export == path.stem:
            exports.append(verify_export(path, output, report))
    if not reports:
        parser.error("No local JSON/JPG pairs found.")
    if args.verify_export and not exports:
        parser.error("The requested verification pair was not found.")
    result = {"schema_version": 1, "pairs": reports, "export_checks": exports}
    report_path = output / "report.json"
    report_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(report_path, flush=True)


if __name__ == "__main__":
    main()
