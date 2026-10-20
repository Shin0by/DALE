"""Separate PNGs with signed artwork offset and exact bicubic alpha bounds."""

from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
from collections import Counter
from functools import lru_cache
from pathlib import Path

from shapely import STRtree
from shapely.ops import unary_union

from dale.export_files import resolve_export_file
from dale.export_grid import export_grid
from dale.export_names import export_family, group_export_stem, png_filename, selection_number
from dale.geometry import offset_region
from dale.json_repair import repaired_json_bytes
from dale.project_io import current_contours_document
from dale.raster import (
    ALPHA_FILTER_HALO,
    ExportCancelled,
    alpha_bounds,
    export_png,
    raster_operations,
)
from dale.selection_groups import matching_export_groups
from dale.session import ContourMask, RasterTransform, Session


def next_export_directory(directory: Path, stem: str) -> Path:
    if not stem or Path(stem).name != stem or any(c in stem for c in '<>:"/\\|?*'):
        raise ValueError("Invalid export filename.")
    return _available_file(Path(directory), f"{stem}-overlays", "")


def _available_file(directory, stem, suffix):
    path = directory / f"{stem}{suffix}"
    number = 2
    while path.exists() or path.is_symlink():
        path = directory / f"{stem}-{number}{suffix}"
        number += 1
    return path


def _file_stamp(path):
    value = path.stat()
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def _publish_overlay_set(staging, destination, cancelled, overwrites):
    if not destination.exists():
        os.rename(staging, destination)
        return
    published = []
    try:
        files = tuple(staging.iterdir())
        for source in files:
            if cancelled and cancelled():
                raise ExportCancelled("Separate PNG export cancelled.")
            target = destination / source.name
            if target.name in overwrites:
                if _file_stamp(target) != overwrites[target.name]:
                    raise ValueError("Export destination changed. Try exporting again.")
                backup = staging / ".previous" / target.name
                backup.parent.mkdir(exist_ok=True)
                shutil.copy2(target, backup)
                published.append((target, backup))
                os.replace(source, target)
                continue
            try:
                os.link(source, target)
            except FileExistsError:
                raise
            except OSError:
                # Filesystems without hardlinks still get exclusive, non-overwriting writes.
                with target.open("xb") as output:
                    published.append((target, None))
                    with source.open("rb") as content:
                        shutil.copyfileobj(content, output)
            else:
                published.append((target, None))
        if cancelled and cancelled():
            raise ExportCancelled("Separate PNG export cancelled.")
    except BaseException:
        for path, backup in reversed(published):
            if backup is not None:
                os.replace(backup, path)
            else:
                path.unlink(missing_ok=True)
        raise


def export_regions(session: Session, *, individual=False, analysis=None):
    analysis = analysis or session.analysis()
    if individual:
        return analysis.cells
    area = offset_region(analysis.area, session.contour_offset)
    polygons = [area] if area.geom_type == "Polygon" else list(area.geoms)
    return tuple(
        sorted((p for p in polygons if not p.is_empty), key=lambda p: (p.bounds[1], p.bounds[0]))
    )


def selected_export_regions(polygons, offset=0, *, merge_adjacent=False, cancelled=None):
    """Group selected cells before offsetting, without bridging unselected space.

    Exact edge, point and area contacts connect a group. A point contact can
    retain multiple polygon parts in one image; holes remain transparent.
    """
    polygons = tuple(polygons)
    tree = STRtree(polygons) if merge_adjacent else None
    remaining = set(range(len(polygons)))
    result = []
    for index in range(len(polygons)):
        if cancelled and cancelled():
            raise ExportCancelled("Separate PNG export cancelled.")
        if index not in remaining:
            continue
        remaining.remove(index)
        group, pending = [index], [index]
        while merge_adjacent and pending:
            if cancelled and cancelled():
                raise ExportCancelled("Separate PNG export cancelled.")
            current = pending.pop()
            for neighbour in tree.query(polygons[current], predicate="intersects"):
                neighbour = int(neighbour)
                if neighbour in remaining:
                    remaining.remove(neighbour)
                    group.append(neighbour)
                    pending.append(neighbour)
        group = tuple(sorted(group))
        area = unary_union([polygons[i] for i in group]) if len(group) > 1 else polygons[index]
        result.append((group, offset_region(area, offset)))
    return tuple(result)


def _candidate_bounds(polygon, source_size):
    margin = ALPHA_FILTER_HALO
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


@lru_cache(maxsize=32)
def _cached_alpha_bounds(size, operations, candidate, source_path):
    return alpha_bounds(size, operations, candidate, source_path=source_path)


def overlay_operations(operations, polygon):
    """Shared immutable image/mask order for Raster preview and PNG export."""
    outside = ContourMask(polygon, "outside")
    if not any(
        isinstance(op, RasterTransform) or isinstance(op, ContourMask) and op.mode == "outside"
        for op in operations
    ):
        operations = (outside, *operations)
    return (*operations, outside)


def prepare_overlay(session, polygon, cancelled=None, *, size_to_grid=False, grid_size=None):
    """Share exact alpha-derived placement between the sidebar and PNG export."""
    candidate = _candidate_bounds(polygon, session.source.size)
    operations = overlay_operations(
        raster_operations(session.operations, session.contour_offset), polygon
    )
    content = (
        alpha_bounds(
            session.source.size, operations, candidate, cancelled, session.source.image_path
        )
        if cancelled is not None
        else _cached_alpha_bounds(
            session.source.size, operations, candidate, session.source.image_path
        )
    )
    if content is None:
        return None, operations, None
    bounds = export_grid(session, grid_size).enclose(content) if size_to_grid else content
    return bounds, operations, content


def overlay_region_plan(
    session,
    *,
    region_index=None,
    region_indices=None,
    individual_regions=False,
    selected_polygons=None,
    merge_adjacent=False,
    cancelled=None,
):
    """Freeze the same source regions and rendered parts for naming and PNG export."""
    analysis = session.analysis() if selected_polygons is None else None
    polygons = (
        tuple(selected_polygons)
        if selected_polygons is not None
        else export_regions(
            session, individual=individual_regions or merge_adjacent, analysis=analysis
        )
    )
    if not polygons:
        raise ValueError("No closed contour is available for separate PNG export.")
    selected = tuple(enumerate(polygons))
    if region_index is not None and region_indices is not None:
        raise ValueError("Choose either one region or a region selection.")
    if selected_polygons is not None:
        region_index = region_indices = None
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
    selected_indices = [i for i, _ in selected]
    if selected_polygons is None and not (individual_regions or merge_adjacent):
        tree = STRtree(analysis.cells)
        identity_groups = tuple(
            tuple(analysis.cells[int(i)] for i in tree.query(polygon, predicate="intersects"))
            for _, polygon in selected
        )
    else:
        identity_groups = tuple((polygon,) for _, polygon in selected)
    selection_id = selection_number(
        analysis.cells
        if selected_polygons is None
        and not (individual_regions or merge_adjacent)
        and region_index is None
        and region_indices is None
        else (p for group in identity_groups for p in group)
    )
    region_groups = None
    if merge_adjacent:
        grouped = selected_export_regions(
            (polygon for _, polygon in selected),
            session.contour_offset,
            merge_adjacent=True,
            cancelled=cancelled,
        )
        region_groups = [tuple(selected_indices[i] for i in group) for group, _ in grouped]
        identity_groups = tuple(
            tuple(p for index in group for p in identity_groups[index]) for group, _ in grouped
        )
        selected = tuple(
            (group[0], polygon) for group, (_, polygon) in zip(region_groups, grouped, strict=True)
        )
    elif individual_regions or selected_polygons is not None:
        selected = tuple(
            (i, offset_region(polygon, session.contour_offset)) for i, polygon in selected
        )
    return selected, selected_indices, identity_groups, region_groups, selection_id


def export_group_matches(session, groups, plan, active=None):
    # A neighbour touching only at a point does not contribute to this PNG part.
    selected, _, identities, _, _ = plan
    region_sets = tuple(
        tuple(region for region in regions if region.intersection(polygon).area > 0)
        for regions, (_, polygon) in zip(identities, selected, strict=True)
    )
    return matching_export_groups(session.geometry(), groups, region_sets, active)


def shared_export_group(matches):
    """One complete group supplies the package prefix even across several PNG parts."""
    group = matches[0] if matches else None
    return group if group and all(g and g.id == group.id for g in matches) else None


def export_overlays(
    session: Session,
    directory: Path,
    progress=None,
    cancelled=None,
    region_index=None,
    region_indices=None,
    individual_regions=False,
    export_name=None,
    selected_polygons=None,
    merge_adjacent=False,
    size_to_grid=False,
    grid_size=None,
    target_directory=None,
    conflict=None,
    protected_sources=(),
    include_json=True,
    export_groups=(),
    active_group=None,
) -> Path:
    grid = export_grid(session, grid_size) if size_to_grid else None
    directory = directory.resolve()
    plan = overlay_region_plan(
        session,
        region_index=region_index,
        region_indices=region_indices,
        individual_regions=individual_regions,
        selected_polygons=selected_polygons,
        merge_adjacent=merge_adjacent,
        cancelled=cancelled,
    )
    selected, selected_indices, identity_groups, region_groups, selection_id = plan
    source = session.source
    stem = export_name or Path(source.image_name or source.image_path.name).stem
    named_groups = (
        export_group_matches(session, export_groups, plan, active_group)
        if export_groups
        else (None,) * len(selected)
    )
    package_group = shared_export_group(named_groups)
    if package_group is not None:
        stem = group_export_stem(package_group.name)
    if Path(stem).name != stem or any(c in stem for c in '<>:"/\\|?*'):
        raise ValueError("Invalid export filename.")
    if stem == "map" and session.source.raw.get("name"):
        # Use an archive's generic source basename rather than untrusted scene paths.
        stem = "map"
    family = export_family(stem, selection_id)
    destination = (
        Path(target_directory).resolve()
        if target_directory is not None
        else next_export_directory(directory, family)
    )
    if destination.parent != directory:
        raise ValueError("Export staging and destination must stay inside the selected folder.")
    if destination.exists() and not destination.is_dir():
        raise ValueError("The export destination must be a folder.")
    overwrites = {}

    def export_file(name):
        path = resolve_export_file(destination / name, conflict)
        if path.exists():
            sources = (*protected_sources, source.image_path, source.json_path)
            if any(p and p.exists() and os.path.samefile(path, p) for p in sources):
                raise ValueError("Export cannot replace an imported source file.")
            overwrites[path.name] = _file_stamp(path)
        return path.name

    manifest = {
        "format": "dale-overlay-set",
        "schema_version": 2,
        "selection_id": selection_id,
        "identifier_scheme": "sha256-96-normalized-regions-v1",
        "source_image_size": source.size,
        "selected_region": region_index,
        "selected_regions": selected_indices,
        "artwork_offset_px": session.contour_offset,
        "bounds_mode": "all nonzero bicubic alpha, clipped to scene image",
        "alpha_antialiasing": "2x supersampling, bicubic reduction",
        "region_mode": (
            "selected_components"
            if merge_adjacent
            else "faces"
            if individual_regions
            else "components"
        ),
        "coordinate_units": "source-image pixels",
        "items": [],
        "note": "DALE placement manifest; not a Foundry scene import document.",
    }
    if region_groups is not None:
        manifest["region_groups"] = region_groups
    if grid:
        manifest["bounds_mode"] = "exact nonzero alpha expanded to square grid; transparent padding"
        manifest["grid"] = {
            "cell_pixels": grid.cell,
            "origin_pixels": grid.origin,
            "scene_cell_pixels": grid.scene_cell,
        }
    region_ids = tuple(selection_number(group) for group in identity_groups)
    counts = Counter(region_ids)
    region_ids = tuple(
        selection_number((polygon,)) if counts[region_id] > 1 else region_id
        for region_id, (_, polygon) in zip(region_ids, selected, strict=True)
    )
    with tempfile.TemporaryDirectory(prefix=".dale-export-", dir=directory) as temporary:
        staging = Path(temporary).resolve()
        rendered = {}
        if staging.parent != directory or destination.parent != directory:
            raise ValueError("Export staging and destination must stay inside the selected folder.")
        for part, (_index, polygon) in enumerate(selected):
            if cancelled and cancelled():
                raise ExportCancelled("Separate PNG export cancelled.")
            bounds, object_operations, content = prepare_overlay(
                session, polygon, cancelled, size_to_grid=size_to_grid, grid_size=grid_size
            )
            if bounds is None:
                continue
            x, y, right, bottom = bounds
            width, height = right - x, bottom - y
            region_id = region_ids[part]
            group = named_groups[part]
            part_family = (
                export_family(group_export_stem(group.name), selection_id) if group else family
            )
            proposed = png_filename(part_family, selection_id, region_id, width, height)
            if proposed in rendered:
                if polygon.equals(rendered[proposed]):
                    continue
                raise ValueError("Different regions generated the same export filename.")
            rendered[proposed] = polygon
            name = export_file(proposed)

            def part_progress(percent, part=part):
                if progress:
                    progress(min(99, (part * 100 + percent) // len(selected)))

            visible = export_png(
                source,
                object_operations,
                staging / name,
                progress=part_progress,
                cancelled=cancelled,
                crop=bounds,
                metadata={
                    "DALE.SourceX": str(x),
                    "DALE.SourceY": str(y),
                    "DALE.ArtworkOffsetPixels": str(session.contour_offset),
                    "DALE.AlphaAntialiasing": "bicubic-2x",
                    "DALE.SelectionId": selection_id,
                    "DALE.RegionId": region_id,
                },
            )
            if not visible:
                (staging / name).unlink()
                continue
            sx, sy = source.scene_size[0] / source.size[0], source.scene_size[1] / source.size[1]
            manifest["items"].append(
                {
                    "file": name,
                    "region_id": region_id,
                    "x": x,
                    "y": y,
                    "width": right - x,
                    "height": bottom - y,
                    "content_bounds": content,
                    "scene_x": session.origin[0] + source.background_offset[0] + x * sx,
                    "scene_y": session.origin[1] + source.background_offset[1] + y * sy,
                    "scene_width": (right - x) * sx,
                    "scene_height": (bottom - y) * sy,
                }
            )
        if not manifest["items"]:
            raise ValueError("All contour regions are transparent; no PNGs were exported.")
        if include_json:
            scene_name = export_file(f"{family}.json")
            payload = (
                repaired_json_bytes(session)[0]
                if source.json_bytes is not None
                else current_contours_document(session).data
            )
            (staging / scene_name).write_bytes(payload)
            manifest_name = export_file(f"{family}-placement.json")
            (staging / manifest_name).write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
            )
        if cancelled and cancelled():
            raise ExportCancelled("Separate PNG export cancelled.")
        _publish_overlay_set(staging, destination, cancelled, overwrites)
    if progress:
        progress(100)
    return destination
