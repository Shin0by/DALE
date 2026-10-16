"""Separate contour PNGs with a three-pixel edge guard and placement coordinates."""

from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path

from shapely.geometry import box

from dale.geometry import offset_region
from dale.placement import Placement
from dale.raster import ExportCancelled, export_png
from dale.session import ContourMask, Session

EDGE_GUARD = 3


def export_regions(session: Session, *, individual=False):
    if individual:
        return session.analysis().cells
    masks = [
        op for op in session.operations if isinstance(op, ContourMask) and op.mode == "outside"
    ]
    mask = masks[-1] if masks else session.make_mask("outside")
    polygons = [mask.area] if mask.area.geom_type == "Polygon" else list(mask.area.geoms)
    return tuple(
        sorted((p for p in polygons if not p.is_empty), key=lambda p: (p.bounds[1], p.bounds[0]))
    )


def crop_bounds(polygon, extra_padding=0, source_size=None):
    if type(extra_padding) is not int or not 0 <= extra_padding <= 4096:
        raise ValueError("Export padding must be an integer from 0 to 4096 pixels.")
    margin = EDGE_GUARD + extra_padding
    x0, y0, x1, y1 = polygon.bounds
    bounds = (
        math.floor(x0) - margin,
        math.floor(y0) - margin,
        math.floor(x1) + margin + 1,
        math.floor(y1) + margin + 1,
    )
    if source_size is not None:
        left, top, right, bottom = bounds
        bounds = (
            max(0, left),
            max(0, top),
            min(source_size[0], right),
            min(source_size[1], bottom),
        )
        if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
            raise ValueError("The selected region lies outside the source image.")
    return bounds


def export_overlays(
    session: Session,
    directory: Path,
    placement: Placement,
    progress=None,
    cancelled=None,
    region_index=None,
    region_indices=None,
    extra_padding=0,
    individual_regions=False,
) -> Path:
    directory = directory.resolve()
    masks = [
        op for op in session.operations if isinstance(op, ContourMask) and op.mode == "outside"
    ]
    mask = masks[-1] if masks else session.make_mask("outside")
    polygons = export_regions(session, individual=individual_regions)
    if not polygons:
        raise ValueError("No closed contour is available for separate PNG export.")
    selected = tuple(enumerate(polygons))
    if region_index is not None and region_indices is not None:
        raise ValueError("Choose either one region or a region selection.")
    if region_index is not None:
        if type(region_index) is not int or not 0 <= region_index < len(polygons):
            raise ValueError("The selected export region is no longer available.")
        selected = ((region_index, polygons[region_index]),)
    if region_indices is not None:
        if not region_indices or any(
            type(i) is not int or not 0 <= i < len(polygons) for i in region_indices
        ):
            raise ValueError("Select at least one available export region.")
        selected = tuple((i, polygons[i]) for i in sorted(set(region_indices)))
    if individual_regions:
        selected = tuple(
            (i, offset_region(polygon, session.contour_offset)) for i, polygon in selected
        )
    crop_bounds(selected[0][1], extra_padding)  # Validate before creating output.
    operations = [
        ContourMask(op.area.buffer(EDGE_GUARD), "outside")
        if isinstance(op, ContourMask) and op.mode == "outside"
        else op
        for op in session.operations
    ]
    if not masks:
        operations.insert(0, ContourMask(mask.area.buffer(EDGE_GUARD), "outside"))
    source = session.source
    stem = source.image_path.stem
    if stem == "map" and session.source.raw.get("name"):
        # Use an archive's generic source basename rather than untrusted scene paths.
        stem = "map"
    destination = directory / f"{stem}-overlays"
    suffix = 2
    while destination.exists():
        destination = directory / f"{stem}-overlays-{suffix}"
        suffix += 1
    manifest = {
        "format": "dale-overlay-set",
        "schema_version": 1,
        "foundry_major": placement.foundry_major,
        "elevation_ft": placement.elevation_ft,
        "source_image_size": source.size,
        "edge_guard_px": EDGE_GUARD,
        "selected_region": region_index,
        "selected_regions": [i for i, _ in selected],
        "extra_padding_px": extra_padding,
        "region_mode": "faces" if individual_regions else "components",
        "coordinate_units": "source-image pixels",
        "items": [],
        "note": "DALE placement manifest; not a Foundry scene import document.",
    }
    with tempfile.TemporaryDirectory(prefix=".dale-export-", dir=directory) as temporary:
        staging = Path(temporary).resolve()
        if staging.parent != directory or destination.parent != directory:
            raise ValueError("Export staging and destination must stay inside the selected folder.")
        for part, (index, polygon) in enumerate(selected):
            if cancelled and cancelled():
                raise ExportCancelled("Separate PNG export cancelled.")
            bounds = crop_bounds(polygon, extra_padding, source.size)
            x, y, right, bottom = bounds
            name = f"{stem}-part-{index + 1:03d}-{placement.elevation_ft}ft.png"
            guarded = polygon.buffer(EDGE_GUARD)
            object_operations = operations + [
                ContourMask(guarded, "outside"),
                ContourMask(box(0, 0, source.size[0] - 1, source.size[1] - 1), "outside"),
            ]

            def part_progress(percent, part=part):
                if progress:
                    progress(min(99, (part * 100 + percent) // len(selected)))

            visible = export_png(
                source,
                object_operations,
                staging / name,
                progress=part_progress,
                cancelled=cancelled,
                placement=placement,
                crop=bounds,
                metadata={
                    "DALE.SourceX": str(x),
                    "DALE.SourceY": str(y),
                    "DALE.EdgeGuardPixels": str(EDGE_GUARD),
                    "DALE.ExtraPaddingPixels": str(extra_padding),
                },
            )
            if not visible:
                (staging / name).unlink()
                continue
            sx, sy = source.scene_size[0] / source.size[0], source.scene_size[1] / source.size[1]
            manifest["items"].append(
                {
                    "file": name,
                    "x": x,
                    "y": y,
                    "width": right - x,
                    "height": bottom - y,
                    "scene_x": session.origin[0] + source.background_offset[0] + x * sx,
                    "scene_y": session.origin[1] + source.background_offset[1] + y * sy,
                    "scene_width": (right - x) * sx,
                    "scene_height": (bottom - y) * sy,
                }
            )
        if not manifest["items"]:
            raise ValueError("All contour regions are transparent; no PNGs were exported.")
        (staging / "placement.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        if cancelled and cancelled():
            raise ExportCancelled("Separate PNG export cancelled.")
        os.replace(staging, destination)
    if progress:
        progress(100)
    return destination
