"""Portable .dale ZIP projects with exact sources and applied editing state."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import zipfile
from copy import copy
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from uuid import uuid4

from shapely.geometry import mapping, shape

from dale import __version__
from dale.preferences import ROTATION_VALUE_RANGES
from dale.provenance import SourceWall, decode_record, encode_record, geometry_edges
from dale.scene import SceneInput, load_pair, number, open_source, scene_from_json
from dale.session import (
    AddedSourceWall,
    Closure,
    ContourMask,
    GeometryEdit,
    Session,
    SourceRepairEdit,
    Stroke,
)

FORMAT = "dale-project"
SCHEMA_VERSION = 7
DEFAULT_CUSTOM_COLORS = ("#ffffffff",) * 16
LIMITS = {
    "manifest.json": 64 * 1024,
    "history.json": None,
    "sources/map.image": 1024 * 1024 * 1024,
    "sources/scene.json": None,
}


@dataclass(frozen=True)
class JsonDocument:
    id: str
    name: str
    kind: str
    data: bytes
    image_name: str | None = None
    image_member: str | None = None
    image_path: Path | None = field(default=None, compare=False)
    is_current: bool = False


def _custom_colors(value):
    if (
        not isinstance(value, list)
        or len(value) != 16
        or any(
            not isinstance(color, str) or not re.fullmatch(r"#[a-fA-F0-9]{8}", color)
            for color in value
        )
    ):
        raise ValueError("Invalid project custom colors.")
    return tuple(color.lower() for color in value)


def _archive_manifest(archive):
    entries = archive.infolist()
    names = [entry.filename for entry in entries]
    if len(names) != len(set(names)) or "manifest.json" not in names:
        raise ValueError(
            "Project archive must contain exactly the expected members and declared JSON files."
        )
    if archive.getinfo("manifest.json").file_size > LIMITS["manifest.json"]:
        raise ValueError("Oversized project manifest.")
    manifest = json.loads(archive.read("manifest.json"))
    if manifest.get("format") != FORMAT or manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            "Unsupported DALE project format or version. Older projects are not supported."
        )
    if "custom_colors" in manifest:
        _custom_colors(manifest["custom_colors"])
    documents = manifest.get("json_documents")
    if not isinstance(documents, list) or not 0 <= len(documents) <= 100:
        raise ValueError("A current project requires a JSON document catalog.")
    expected = {key: value for key, value in LIMITS.items() if key != "sources/scene.json"}
    source_kind = manifest.get("source_kind")
    if source_kind not in ("image", "json", "empty"):
        raise ValueError("Invalid project source kind.")
    if source_kind != "image":
        expected.pop("sources/map.image")
    if manifest.get("datasets", False) is not False:
        if manifest["datasets"] is not True or manifest.get("catalog_views"):
            raise ValueError("Invalid project datasets declaration.")
        expected["datasets.json"] = LIMITS["history.json"]
    if manifest.get("catalog_views", False) is not False:
        if manifest["catalog_views"] is not True:
            raise ValueError("Invalid project catalog views declaration.")
        expected["catalog-views.json"] = LIMITS["history.json"]
    images = manifest.get("catalog_images", [])
    if not isinstance(images, list) or len(images) > 100:
        raise ValueError("Invalid project image catalog.")
    image_entries = set()
    for item in images:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("name"), str)
            or not 1 <= len(item["name"]) <= 256
            or not isinstance(item.get("member"), str)
            or not re.fullmatch(r"sources/images/[a-f0-9]{64}\.image", item["member"])
        ):
            raise ValueError("Invalid project image catalog entry.")
        pair = item["name"], item["member"]
        if (
            pair in image_entries
            or manifest.get("sha256", {}).get(item["member"]) != Path(item["member"]).stem
        ):
            raise ValueError("Invalid or duplicate project image catalog entry.")
        image_entries.add(pair)
        expected[item["member"]] = LIMITS["sources/map.image"]
    identifiers, members = set(), set()
    for document in documents:
        if not isinstance(document, dict):
            raise ValueError("Invalid project JSON document.")
        identifier, member = document.get("id"), document.get("member")
        if (
            not isinstance(identifier, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identifier)
            or identifier in identifiers
            or not isinstance(member, str)
            or member in members
            or member
            != (
                "sources/scene.json"
                if identifier == "source"
                else f"sources/json/{identifier}.json"
            )
            or not isinstance(document.get("name"), str)
            or not 1 <= len(document["name"]) <= 256
            or document.get("kind") not in ("original", "updated")
        ):
            raise ValueError("Invalid project JSON catalog entry.")
        identifiers.add(identifier)
        members.add(member)
        expected[member] = LIMITS["sources/scene.json"]
        image_member = document.get("image_member")
        image_name = document.get("image_name")
        if image_member is not None:
            if (
                not isinstance(image_member, str)
                or not isinstance(image_name, str)
                or not 1 <= len(image_name) <= 256
                or image_member != "sources/map.image"
                and not re.fullmatch(r"sources/images/[a-f0-9]{64}\.image", image_member)
                or image_member == "sources/map.image"
                and source_kind != "image"
            ):
                raise ValueError("Invalid catalog image reference.")
            expected[image_member] = LIMITS["sources/map.image"]
            if (
                image_member.startswith("sources/images/")
                and manifest.get("sha256", {}).get(image_member) != Path(image_member).stem
            ):
                raise ValueError("Invalid catalog image checksum reference.")
        elif image_name is not None:
            raise ValueError("A catalog image name requires its image member.")
    if set(names) != set(expected):
        raise ValueError(
            "Project archive must contain exactly the expected members and declared JSON files."
        )
    if source_kind == "json" and "sources/scene.json" not in members:
        raise ValueError("A JSON-only project requires its original scene JSON.")
    current_id = manifest.get("current_contours_id")
    if current_id is not None and not any(
        d["id"] == current_id and d["id"] != "source" and d["kind"] == "updated" for d in documents
    ):
        raise ValueError("Invalid current contours JSON catalog reference.")
    for entry in entries:
        limit = expected[entry.filename]
        if entry.flag_bits & 1:
            raise ValueError(f"Encrypted project member: {entry.filename}.")
        if entry.file_size < 0:
            raise ValueError(f"Invalid project member size: {entry.filename}.")
        if limit is not None and entry.file_size > limit:
            raise ValueError(f"Project member exceeds its size limit: {entry.filename}.")
    return manifest


def _read_json_documents(archive, manifest):
    documents = []
    for entry in manifest["json_documents"]:
        data = archive.read(entry["member"])
        if hashlib.sha256(data).hexdigest() != manifest.get("sha256", {}).get(entry["member"]):
            raise ValueError(f"Project checksum mismatch: {entry['member']}.")
        documents.append(
            JsonDocument(
                entry["id"],
                entry["name"],
                entry["kind"],
                data,
                entry.get("image_name"),
                entry.get("image_member"),
                is_current=entry["id"] == manifest.get("current_contours_id"),
            )
        )
    return tuple(documents)


def read_json_documents(path: Path):
    """Offer original/stored JSON and the applied contours, reading only image headers."""
    with zipfile.ZipFile(path) as archive:
        manifest = _archive_manifest(archive)
        catalog = _catalog_from_archive(archive, manifest)
        original = next((d for d in catalog.documents if d.id == "source"), None)
        documents = list(_session_json_documents(catalog.base_session, original))
        for key, view in catalog.views.items():
            if key != catalog.base_key and view.session.operations:
                identifier = "view-" + hashlib.sha256(repr(key).encode()).hexdigest()[:24]
                documents.append(replace(catalog.snapshot(key), id=identifier))
        if manifest["source_kind"] == "image":
            documents = [
                replace(d, image_member="sources/map.image", image_name=manifest["image_name"])
                if d.id == "source" or d.is_current and d.id.startswith("current-contours")
                else d
                for d in documents
            ]
        return tuple(documents)


def _checked_bytes(archive, manifest, member):
    data = archive.read(member)
    if hashlib.sha256(data).hexdigest() != manifest.get("sha256", {}).get(member):
        raise ValueError(f"Project checksum mismatch: {member}.")
    return data


def _catalog_from_archive(archive, manifest):
    from dale.catalog import CatalogImage, SceneCatalog

    documents = _read_json_documents(archive, manifest)
    members = {d.image_member for d in documents if d.image_member}
    members.update(item["member"] for item in manifest.get("catalog_images", []))
    if manifest["source_kind"] == "image":
        members.add("sources/map.image")
    sizes = {}
    for member in members:
        with archive.open(member) as stream, open_source(stream) as image:
            sizes[member] = image.size
    size = sizes.get("sources/map.image")
    if manifest["source_kind"] == "empty":
        size = _empty_size(manifest)
    original = next((d for d in documents if d.id == "source"), None)
    source = (
        scene_from_json(original.data, size)
        if original
        else SceneInput(None, None, size, {}, (), size, (0, 0), ())
    )
    session, ui = _restore_session(source, documents, manifest, _read_history(archive, manifest))
    catalog = SceneCatalog(
        session,
        ui,
        sizes,
        tuple(
            CatalogImage(item["name"], item["member"], None, sizes[item["member"]])
            for item in manifest.get("catalog_images", [])
        ),
    )
    if manifest.get("catalog_views"):
        from dale.project_state_reader import read_state_bytes

        catalog.restore(read_state_bytes(_checked_bytes(archive, manifest, "catalog-views.json")))
    if manifest.get("datasets"):
        from dale.datasets import DatasetCatalog
        from dale.project_state_reader import read_state_bytes

        image_inputs = (
            [CatalogImage(manifest["image_name"], "sources/map.image", None, size)]
            if manifest["source_kind"] == "image"
            else []
        )
        image_inputs.extend(
            CatalogImage(item["name"], item["member"], None, sizes[item["member"]])
            for item in manifest.get("catalog_images", [])
        )
        catalog = DatasetCatalog.restore(
            session,
            ui,
            documents,
            image_inputs,
            read_state_bytes(_checked_bytes(archive, manifest, "datasets.json")),
        )
    return catalog


def _hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def extract_catalog_image(project: Path, document: JsonDocument, destination: Path):
    if document.image_member is None:
        return None
    with zipfile.ZipFile(project) as archive:
        manifest = _archive_manifest(archive)
        if document.image_member not in manifest.get("sha256", {}):
            raise ValueError("Unknown catalog image.")
        with archive.open(document.image_member) as source, destination.open("wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
        if _hash(destination) != manifest["sha256"][document.image_member]:
            destination.unlink(missing_ok=True)
            raise ValueError("Project catalog image checksum mismatch.")
    return destination


def append_project_document(project: Path, document: JsonDocument):
    """Atomically append one JSON/image snapshot without changing existing payloads."""
    project = project.resolve()
    if project.suffix.lower() != ".dale":
        raise ValueError("Choose an existing DALE project.")
    if not isinstance(document.name, str) or not 1 <= len(document.name) <= 256:
        raise ValueError("Invalid catalog set name.")
    image_digest, image_size = None, None
    if document.image_path:
        if document.image_path.stat().st_size > LIMITS["sources/map.image"]:
            raise ValueError("Catalog image exceeds the project limit.")
        with open_source(document.image_path) as image:
            image_size = image.size
        image_digest = _hash(document.image_path)
    elif document.image_member:
        raise ValueError("A catalog image is unavailable for export.")
    scene_from_json(document.data, image_size)
    before = _hash(project)
    temporary = None
    try:
        with zipfile.ZipFile(project) as archive:
            manifest = _archive_manifest(archive)
            _catalog_from_archive(archive, manifest)
            stored = _read_json_documents(archive, manifest)
            image_member = None
            if image_digest:
                image_member = (
                    "sources/map.image"
                    if image_digest == manifest["sha256"].get("sources/map.image")
                    else f"sources/images/{image_digest}.image"
                )
            result = replace(
                document,
                id="set-" + uuid4().hex,
                kind="updated",
                image_member=image_member,
                is_current=False,
            )
            for existing in stored:
                if (
                    not existing.is_current
                    and existing.name == result.name
                    and existing.data == result.data
                    and existing.image_name == result.image_name
                    and manifest["sha256"].get(existing.image_member) == image_digest
                ):
                    return replace(existing, image_path=document.image_path), False
            if len(stored) >= 100:
                raise ValueError("The project already contains 100 JSON documents.")
            member = f"sources/json/{result.id}.json"
            entry = {"id": result.id, "name": result.name, "kind": result.kind, "member": member}
            if image_member:
                entry.update(
                    image_member=image_member,
                    image_name=result.image_name or result.image_path.name,
                )
                manifest["sha256"][image_member] = image_digest
            manifest["json_documents"].append(entry)
            manifest["sha256"][member] = hashlib.sha256(result.data).hexdigest()
            manifest["app_version"] = __version__
            descriptor, name = tempfile.mkstemp(
                prefix=".dale-append-", suffix=".tmp", dir=project.parent
            )
            temporary = Path(name)
            with os.fdopen(descriptor, "wb") as stream:
                with zipfile.ZipFile(stream, "w", allowZip64=True) as target:
                    for info in archive.infolist():
                        if info.filename == "manifest.json":
                            target.writestr(info, _json_bytes(manifest))
                            continue
                        digest = hashlib.sha256()
                        with (
                            archive.open(info) as source,
                            target.open(info, "w", force_zip64=True) as output,
                        ):
                            while chunk := source.read(1024 * 1024):
                                digest.update(chunk)
                                output.write(chunk)
                        if digest.hexdigest() != manifest["sha256"].get(info.filename):
                            raise ValueError(f"Project checksum mismatch: {info.filename}.")
                    target.writestr(member, result.data, zipfile.ZIP_DEFLATED)
                    if image_member and image_member not in archive.namelist():
                        digest = hashlib.sha256()
                        with (
                            document.image_path.open("rb") as source,
                            target.open(image_member, "w", force_zip64=True) as output,
                        ):
                            while chunk := source.read(1024 * 1024):
                                digest.update(chunk)
                                output.write(chunk)
                        if digest.hexdigest() != image_digest:
                            raise ValueError("The image changed during export. Try again.")
                stream.flush()
                os.fsync(stream.fileno())
        with zipfile.ZipFile(temporary) as verification:
            _archive_manifest(verification)
            _read_json_documents(verification, manifest)
        if _hash(project) != before:
            raise ValueError("The destination project changed during export. Try again.")
        os.replace(temporary, project)
        temporary = None
        return result, True
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _point(value):
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValueError("Project points must contain exactly two coordinates.")
    return tuple(number(v, "Project coordinate") for v in value)


def _points(values):
    if not isinstance(values, list) or len(values) > 2_000_000:
        raise ValueError("Invalid or excessive project point list.")
    return tuple(_point(value) for value in values)


def _encode(operation):
    from shapely import from_wkb

    from dale.session import RasterSelectionEdit

    if isinstance(operation, RasterSelectionEdit):

        def selection(state):
            return {
                "polygons": [mapping(from_wkb(p)) for p in state.polygons],
                "detached": state.detached,
                "lines": state.line_ids,
                "all_regions": state.all_regions,
            }

        return {
            "type": "raster_selection",
            "before": selection(operation.before),
            "after": selection(operation.after),
        }
    if isinstance(operation, Closure):
        return {
            "type": "closure",
            "points": operation.points,
            "lineage": [encode_record(record) for record in operation.lineage],
        }
    if isinstance(operation, Stroke):
        return {
            "type": "stroke",
            "points": operation.points,
            "radius": operation.radius,
            "restore": operation.restore,
            **(
                {
                    "shape": operation.shape,
                    "feather": operation.feather,
                    "opacity": operation.opacity,
                }
                if (operation.shape, operation.feather, operation.opacity) != ("circle", 0, 1)
                else {}
            ),
        }
    if isinstance(operation, ContourMask):
        return {
            "type": "mask",
            "area": mapping(operation.area),
            "mode": operation.mode,
            "boundary": mapping(operation.boundary) if operation.boundary is not None else None,
        }
    if isinstance(operation, GeometryEdit):
        result = {
            "type": "source_repair" if isinstance(operation, SourceRepairEdit) else "geometry",
            "walls": operation.walls,
            "closures": operation.closures,
            "lineage": [
                encode_record(record, compact=len(operation.lineage) > 10000)
                for record in operation.lineage
            ],
            "ancestry": [
                encode_record(record, compact=len(operation.lineage) > 10000)
                for record in operation.ancestry
            ],
        }
        # Vertex diagnostics are derived from the exact walls and lineage on read.
        # Large DA maps must not exhaust the archive budget by repeating those IDs.
        if len(operation.lineage) <= 10_000:
            result["vertices"] = operation.vertex_lineage
        if operation.wall_styles:
            from dale.wall_styles import encode_styles

            result["wall_styles"] = encode_styles(operation.wall_styles)
        if operation.alchemist_slices is not None:
            result["alchemist_slices"] = operation.alchemist_slices
        if operation.alchemist_object_slices is not None:
            result["alchemist_object_slices"] = operation.alchemist_object_slices
        if operation.alchemist_complexity is not None:
            result["alchemist_complexity"] = operation.alchemist_complexity
        if operation.alchemist_transforms is not None:
            result["alchemist_transforms"] = operation.alchemist_transforms
        if operation.alchemist_detail_frames is not None:
            result["alchemist_detail_frames"] = operation.alchemist_detail_frames
        if operation.alchemist_empty_frames is not None:
            result["alchemist_empty_frames"] = operation.alchemist_empty_frames
        if operation.alchemist_thinning is not None:
            result["alchemist_thinning"] = operation.alchemist_thinning
        if operation.raster is not None:
            from dale.raster_transform import area_of

            result["raster_transform"] = {
                "area": mapping(area_of(operation.raster.area_wkb)),
                "matrix": operation.raster.matrix,
            }
            if operation.raster.regions:
                result["raster_transform"]["regions"] = [
                    mapping(area_of(data)) for data in operation.raster.regions
                ]
                result["raster_transform"]["cells"] = [
                    cell.encode() for cell in operation.raster.cells
                ]
            if operation.raster.parts:
                result["raster_transform"]["parts"] = [
                    {"area": mapping(area_of(area)), "matrix": matrix}
                    for area, matrix in operation.raster.parts
                ]
        if isinstance(operation, SourceRepairEdit):
            result["additions"] = [
                {
                    "native_id": a.native_id,
                    "bottom": a.bottom,
                    "top": a.top,
                    **(
                        {
                            "source_ref": asdict(a.source_ref),
                            "properties": json.loads(a.properties_json),
                        }
                        if a.source_ref is not None
                        else {}
                    ),
                }
                for a in operation.additions
            ]
        return result
    raise ValueError("Unsupported editing operation.")


def _decode(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid project operation.")
    kind = value.get("type")
    if kind == "raster_selection":
        from dale.session import RasterSelectionEdit, RegionSelection

        def selection(state):
            if not isinstance(state, dict) or set(state) != {
                "polygons",
                "detached",
                "lines",
                "all_regions",
            }:
                raise ValueError("Invalid raster selection fields.")
            polygons, lines = state["polygons"], state["lines"]
            if (
                not isinstance(polygons, list)
                or len(polygons) > 100_000
                or not isinstance(lines, list)
                or len(lines) > 100_000
                or any(not isinstance(i, str) or not 1 <= len(i) <= 256 for i in lines)
                or len(set(lines)) != len(lines)
                or type(state["detached"]) is not bool
                or type(state["all_regions"]) is not bool
                or (not state["detached"] and lines)
                or (state["all_regions"] and (polygons or lines or state["detached"]))
            ):
                raise ValueError("Invalid raster selection values.")
            result = []
            for data in polygons:
                polygon = shape(data)
                if (
                    polygon.geom_type != "Polygon"
                    or polygon.is_empty
                    or not polygon.is_valid
                    or not all(abs(v) <= 1e9 for v in polygon.bounds)
                    or len(polygon.exterior.coords) + sum(len(r.coords) for r in polygon.interiors)
                    > 2_000_000
                ):
                    raise ValueError("Invalid raster selection polygon.")
                result.append(polygon.wkb)
            return RegionSelection(
                tuple(result), state["detached"], tuple(lines), state["all_regions"]
            )

        if set(value) != {"type", "before", "after"}:
            raise ValueError("Invalid raster selection operation.")
        return RasterSelectionEdit(selection(value["before"]), selection(value["after"]))
    if kind == "closure":
        points = _points(value["points"])
        if len(points) < 2:
            raise ValueError("A project closure needs at least two points.")
        lineage = value.get("lineage")
        if not isinstance(lineage, list) or len(lineage) != len(points) - 1:
            raise ValueError("Path provenance is required in the current project format.")
        return Closure(points, tuple(decode_record(record) for record in lineage))
    if kind == "stroke":
        points = _points(value["points"])
        radius = number(value["radius"], "Brush radius")
        restore = value.get("restore", False)
        if not points or not 0 < radius <= 4096 or type(restore) is not bool:
            raise ValueError("Invalid project brush stroke.")
        brush_shape = value.get("shape", "circle")
        feather = number(value.get("feather", 0), "Brush feather")
        opacity = number(value.get("opacity", 1), "Brush pressure")
        if (
            brush_shape not in ("circle", "square")
            or not 0 <= feather <= 1
            or not 0 <= opacity <= 1
        ):
            raise ValueError("Invalid project brush profile.")
        return Stroke(points, radius, restore, brush_shape, feather, opacity)
    if kind == "mask":
        if value.get("mode") not in ("inside", "outside"):
            raise ValueError("Invalid project mask mode.")
        area = shape(value["area"])
        if area.geom_type not in ("Polygon", "MultiPolygon") or area.is_empty or not area.is_valid:
            raise ValueError("Invalid project mask polygon.")
        if not all(abs(v) <= 1e9 for v in area.bounds):
            raise ValueError("Project mask coordinates exceed the supported range.")
        if "boundary" not in value:
            raise ValueError("A current project mask requires its boundary snapshot.")
        boundary = shape(value["boundary"]) if value["boundary"] is not None else None
        if boundary is not None and (
            boundary.geom_type not in ("Polygon", "MultiPolygon")
            or boundary.is_empty
            or not boundary.is_valid
            or not all(abs(v) <= 1e9 for v in boundary.bounds)
        ):
            raise ValueError("Invalid project mask boundary.")
        return ContourMask(area, value["mode"], boundary)
    if kind in ("geometry", "source_repair"):
        walls = tuple(_points(edge) for edge in value["walls"])
        closures = tuple(_points(path) for path in value["closures"])
        if any(len(edge) != 2 for edge in walls) or any(len(path) < 2 for path in closures):
            raise ValueError("Invalid project contour or closure geometry.")
        lineage, ancestry = value.get("lineage"), value.get("ancestry")
        if any(
            not isinstance(records, list) or len(records) > 2_000_000
            for records in (lineage, ancestry)
        ):
            raise ValueError("Invalid or excessive line provenance.")
        if len(lineage) != len(walls) + sum(len(path) - 1 for path in closures):
            raise ValueError("Line provenance is required in the current project format.")
        operation_type = SourceRepairEdit if kind == "source_repair" else GeometryEdit
        extra = {}
        if "alchemist_slices" in value:
            from dale.alchemist_slices import validate_values

            extra["alchemist_slices"] = validate_values(value["alchemist_slices"])
        if "alchemist_object_slices" in value:
            from dale.alchemist_slices import decode_object_values

            extra["alchemist_object_slices"] = decode_object_values(
                value["alchemist_object_slices"]
            )
        if "alchemist_complexity" in value:
            from dale.alchemist_detail import decode_values

            extra["alchemist_complexity"] = decode_values(value["alchemist_complexity"])
        if "alchemist_thinning" in value:
            from dale.alchemist_thinning import decode_state

            extra["alchemist_thinning"] = decode_state(value["alchemist_thinning"])
        if "alchemist_transforms" in value:
            from dale.alchemist_presets import decode_transforms

            extra["alchemist_transforms"] = decode_transforms(value["alchemist_transforms"])
        if "alchemist_detail_frames" in value:
            from dale.alchemist_detail_frames import decode_frames

            extra["alchemist_detail_frames"] = decode_frames(value["alchemist_detail_frames"])
        if "alchemist_empty_frames" in value:
            from dale.alchemist_slices import decode_empty_frames

            extra["alchemist_empty_frames"] = decode_empty_frames(value["alchemist_empty_frames"])
        if "raster_transform" in value:
            from dale.session import RasterTransform

            raster = value["raster_transform"]
            if not isinstance(raster, dict) or set(raster) not in (
                {"area", "matrix"},
                {"area", "matrix", "regions", "cells"},
                {"area", "matrix", "regions", "cells", "parts"},
            ):
                raise ValueError("Invalid raster transform fields.")
            area = shape(raster["area"])
            matrix = raster["matrix"]
            if (
                area.geom_type not in ("Polygon", "MultiPolygon")
                or (area.is_empty and "parts" not in raster)
                or not area.is_valid
                or (not area.is_empty and not all(abs(v) <= 1e9 for v in area.bounds))
                or not isinstance(matrix, list)
                or len(matrix) != 6
            ):
                raise ValueError("Invalid raster transform geometry.")
            matrix = tuple(number(v, "Raster affine coefficient") for v in matrix)
            if abs(matrix[0] * matrix[3] - matrix[1] * matrix[2]) < 1e-12:
                raise ValueError("Raster transform must be invertible.")
            regions, cells = (), ()
            if "regions" in raster:
                from dale.region_groups import decode_cells

                cells = decode_cells(raster["cells"])
                regions = raster["regions"]
                if not isinstance(regions, list) or not 1 <= len(regions) <= 100_000:
                    raise ValueError("Invalid raster region objects.")
                regions = tuple(shape(p) for p in regions)
                if len(cells) != len(regions) or any(
                    p.geom_type != "Polygon"
                    or p.is_empty
                    or not p.is_valid
                    or not all(math.isfinite(v) and abs(v) <= 1e9 for v in p.bounds)
                    or sum(len(r.coords) for r in (p.exterior, *p.interiors)) > 2_000_000
                    or any(
                        abs(matrix[0] * x + matrix[1] * y + matrix[4]) > 1e9
                        or abs(matrix[2] * x + matrix[3] * y + matrix[5]) > 1e9
                        for x in (p.bounds[0], p.bounds[2])
                        for y in (p.bounds[1], p.bounds[3])
                    )
                    for p in regions
                ):
                    raise ValueError("Invalid raster region objects.")
                regions = tuple(p.wkb for p in regions)
            from dale.individual_transform import raster_parts

            parts = raster_parts(raster.get("parts"), len(regions))
            extra["raster"] = RasterTransform(area.wkb, matrix, regions, cells, parts)
        if "wall_styles" in value:
            from dale.wall_styles import decode_styles

            extra["wall_styles"] = decode_styles(value["wall_styles"])
        if kind == "source_repair":
            additions = value.get("additions")
            if not isinstance(additions, list) or len(additions) > 100_000:
                raise ValueError("Invalid authored contour list.")
            if any(
                not isinstance(a, dict)
                or set(a)
                not in (
                    {"native_id", "bottom", "top"},
                    {"native_id", "bottom", "top", "source_ref", "properties"},
                )
                for a in additions
            ):
                raise ValueError("Invalid authored contour definition.")
            extra["additions"] = tuple(
                AddedSourceWall(
                    a["native_id"],
                    a["bottom"],
                    a["top"],
                    SourceWall(**a["source_ref"]) if "source_ref" in a else None,
                    _json_bytes(a["properties"]) if "properties" in a else None,
                )
                for a in additions
            )
        return operation_type(
            walls,
            closures,
            tuple(decode_record(r) for r in lineage),
            tuple(decode_record(r) for r in ancestry),
            **extra,
        )
    raise ValueError(f"Unsupported project operation type: {kind!r}.")


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode(
        "utf-8"
    )


def _read_history(archive, manifest):
    from dale.project_state_reader import read_state_bytes

    data = archive.read("history.json")
    if hashlib.sha256(data).hexdigest() != manifest.get("sha256", {}).get("history.json"):
        raise ValueError("Project checksum mismatch: history.json.")
    return read_state_bytes(data)


def _session_json_documents(session, original=None):
    documents = ((original,) if original else ()) + tuple(session.json_documents)
    geometry = session.geometry()
    if geometry.walls == session.source.image_walls(session.origin) and not geometry.closures:
        return documents
    identifiers = {d.id for d in documents}
    identifier, suffix = "current-contours", 1
    while identifier in identifiers:
        identifier = f"current-contours-{suffix}"
        suffix += 1
    return (*documents, replace(current_contours_document(session), id=identifier))


def current_contours_document(session):
    """Freeze current extraction geometry and retain its original asset names."""
    geometry = session.geometry()
    # This is an extraction contour snapshot, not a regenerated Foundry Scene.
    # Image-space coordinates deliberately bake the working origin/scale, not artwork offset.
    payload = _json_bytes(
        {
            "name": "Current contours (DALE)",
            "width": session.source.size[0],
            "height": session.source.size[1],
            "padding": 0,
            "grid": {"size": session.source.cell_pixels},
            "walls": [
                {"_id": record.id, "c": [float(value) for point in edge for value in point]}
                for edge, record in zip(
                    geometry_edges(geometry.walls, geometry.closures),
                    geometry.lineage,
                    strict=True,
                )
            ],
        }
    )
    source = session.source
    name = source.json_name or (source.json_path.name if source.json_path else None)
    if not name:
        name = (
            Path(source.image_name or (source.image_path.name if source.image_path else "Contours"))
            .with_suffix(".json")
            .name
        )
    return JsonDocument(
        "current-contours",
        name,
        "updated",
        payload,
        source.image_name or (source.image_path.name if source.image_path else None),
        image_path=source.image_path,
        is_current=True,
    )


def snapshot_project(session, catalog=None):
    """Detach mutable histories/UI before handing project serialization to a worker."""
    frozen = replace(session, operations=list(session.operations), future=list(session.future))
    if catalog is None:
        return frozen, None
    copied = copy(catalog)
    copied.views = {
        key: replace(
            view,
            session=replace(
                view.session,
                operations=list(view.session.operations),
                future=list(view.session.future),
            ),
            ui=dict(view.ui),
        )
        for key, view in catalog.views.items()
    }
    if not getattr(copied, "managed", False):
        copied.base_session = copied.views[copied.base_key].session
    return frozen, copied


def publish_saved_state(original_session, original_catalog, session, catalog):
    targets = (
        ((original_catalog.views[k].session, view.session) for k, view in catalog.views.items())
        if original_catalog
        else ((original_session, session),)
    )
    for target, _ in targets:
        # Saving a checkpoint must not erase this working session's undo/redo.
        target.trim_history()
    if original_catalog:
        for key, view in catalog.views.items():
            original_catalog.views[key].ui = dict(view.ui)


def save_project(
    session: Session,
    destination: Path,
    ui_state: dict | None = None,
    *,
    catalog=None,
    custom_colors=None,
    progress=None,
):
    from dale.project_state import checkpoint_session
    from dale.selection_storage import pack_selection

    report = progress or (lambda *_: None)
    report(5, "Preparing project state")
    if custom_colors is not None:
        custom_colors = _custom_colors(custom_colors)
    original_session, original_catalog = session, catalog
    view_bytes = None
    if catalog is not None:
        catalog = copy(catalog)
        catalog.views = {
            key: replace(
                view,
                session=replace(
                    view.session,
                    operations=list(view.session.operations),
                    future=list(view.session.future),
                ),
                ui=dict(view.ui),
            )
            for key, view in original_catalog.views.items()
        }
        if not getattr(catalog, "managed", False):
            catalog.base_session = catalog.views[catalog.base_key].session
        if ui_state is not None:
            catalog.capture(ui_state)
        if getattr(catalog, "managed", False):
            catalog.prepare()
        for view in catalog.views.values():
            view.session = checkpoint_session(view.session)
        if not getattr(catalog, "managed", False):
            catalog.base_session = catalog.views[catalog.base_key].session
        report(15, "Serializing project datasets")
        view_bytes = _json_bytes(catalog.encode())
        session = catalog.base_session
        ui_state = catalog.views[catalog.base_key].ui
        session = replace(
            session, contour_offset=ui_state.get("artwork_offset_px", session.contour_offset)
        )
    else:
        session = checkpoint_session(session)
    destination = destination.resolve()
    sources = tuple(path for path in (session.source.image_path, session.source.json_path) if path)
    if destination in (path.resolve() for path in sources) or (
        destination.exists() and any(os.path.samefile(destination, path) for path in sources)
    ):
        raise ValueError("Saving a project cannot replace an imported source file.")
    report(30, "Serializing project state")
    history = {
        **({"alchemist": session.alchemist.encode()} if session.alchemist else {}),
        "origin": session.origin,
        "gap_tolerance": session.gap_tolerance,
        "contour_offset": session.contour_offset,
        "operations": [_encode(op) for op in session.operations],
        "redo": [_encode(op) for op in session.future],
        **({"undo_floor": session.history_floor} if session.history_floor else {}),
        "ui": pack_selection(ui_state or {}, session),
    }
    history_bytes = _json_bytes(history)
    report(45, "Preparing project assets")
    manifest = {
        "format": FORMAT,
        "schema_version": SCHEMA_VERSION,
        "app_version": __version__,
        "source_kind": "image"
        if session.source.image_path
        else "json"
        if session.source.json_bytes is not None
        else "empty",
        "image_name": session.source.image_name
        or (session.source.image_path.name if session.source.image_path else None),
        "scene_name": session.source.json_name
        or (session.source.json_path.name if session.source.json_path else None),
        "sha256": {
            "history.json": hashlib.sha256(history_bytes).hexdigest(),
        },
    }
    if custom_colors is not None:
        manifest["custom_colors"] = custom_colors
    if manifest["source_kind"] == "empty":
        manifest["empty_size"] = session.source.size
    if session.source.image_path:
        manifest["sha256"]["sources/map.image"] = _hash(session.source.image_path)
    if view_bytes is not None:
        managed = getattr(catalog, "managed", False)
        manifest["datasets" if managed else "catalog_views"] = True
        manifest["sha256"]["datasets.json" if managed else "catalog-views.json"] = hashlib.sha256(
            view_bytes
        ).hexdigest()
    original = (
        JsonDocument(
            "source",
            manifest["scene_name"],
            "original",
            session.source.json_bytes
            if session.source.json_bytes is not None
            else session.source.json_path.read_bytes(),
            image_name=session.source.image_name,
            image_path=session.source.image_path,
        )
        if session.source.json_bytes is not None or session.source.json_path
        else None
    )
    documents = _session_json_documents(session, original)
    if len(documents) > bool(original) + len(session.json_documents):
        manifest["current_contours_id"] = documents[-1].id
    manifest["json_documents"] = []
    payloads = {}
    image_payloads = {}
    if catalog is not None and catalog.extra_images:
        manifest["catalog_images"] = []
        for item in catalog.extra_images:
            if item.path is None:
                raise ValueError("Catalog image is unavailable for saving.")
            digest = _hash(item.path)
            if digest != Path(item.member).stem:
                raise ValueError("A catalog image changed after import.")
            manifest["catalog_images"].append({"name": item.name, "member": item.member})
            manifest["sha256"][item.member] = digest
            image_payloads[item.member] = item.path
    for document in documents:
        member = (
            "sources/scene.json" if document.id == "source" else f"sources/json/{document.id}.json"
        )
        manifest["json_documents"].append(
            {"id": document.id, "name": document.name, "kind": document.kind, "member": member}
        )
        if document.image_path is not None:
            digest = _hash(document.image_path)
            image_member = (
                "sources/map.image"
                if digest == manifest["sha256"].get("sources/map.image")
                else f"sources/images/{digest}.image"
            )
            manifest["json_documents"][-1].update(
                image_member=image_member,
                image_name=document.image_name or document.image_path.name,
            )
            manifest["sha256"][image_member] = digest
            if image_member != "sources/map.image":
                image_payloads[image_member] = document.image_path
        elif document.image_member is not None:
            raise ValueError("A catalog image is unavailable for saving.")
        manifest["sha256"][member] = hashlib.sha256(document.data).hexdigest()
        payloads[member] = document.data
    temporary = None
    try:
        fd, name = tempfile.mkstemp(prefix=".dale-project-", suffix=".tmp", dir=destination.parent)
        temporary = Path(name)
        with os.fdopen(fd, "wb") as stream:
            with zipfile.ZipFile(stream, "w", allowZip64=True) as archive:
                archive.writestr("manifest.json", _json_bytes(manifest), zipfile.ZIP_DEFLATED)
                archive.writestr("history.json", history_bytes, zipfile.ZIP_DEFLATED)
                if view_bytes is not None:
                    archive.writestr(
                        "datasets.json"
                        if getattr(catalog, "managed", False)
                        else "catalog-views.json",
                        view_bytes,
                        zipfile.ZIP_DEFLATED,
                    )
                image_members = (
                    (("sources/map.image", session.source.image_path),)
                    if (session.source.image_path)
                    else ()
                )
                for member, path in image_members:
                    if path.stat().st_size > LIMITS[member]:
                        raise ValueError(f"Source exceeds the project limit for {member}.")
                    archive.write(path, member, compress_type=zipfile.ZIP_STORED)
                report(60, "Writing project archive")
                for index, (member, data) in enumerate(payloads.items()):
                    archive.writestr(member, data, zipfile.ZIP_DEFLATED)
                    report(
                        60 + int(20 * (index + 1) / max(1, len(payloads))),
                        "Writing project archive",
                    )
                for member, image_path in image_payloads.items():
                    if image_path.stat().st_size > LIMITS["sources/map.image"]:
                        raise ValueError("Catalog image exceeds the project limit.")
                    archive.write(image_path, member, compress_type=zipfile.ZIP_STORED)
            stream.flush()
            os.fsync(stream.fileno())
        report(85, "Verifying project archive")
        with zipfile.ZipFile(temporary) as verification:
            _archive_manifest(verification)
            for entry in verification.infolist():
                if entry.filename == "manifest.json":
                    continue
                with verification.open(entry) as payload:
                    digest = hashlib.file_digest(payload, "sha256").hexdigest()
                if digest != manifest["sha256"].get(entry.filename):
                    raise ValueError("A source asset changed while saving the project.")
        report(95, "Publishing project archive")
        os.replace(temporary, destination)
        temporary = None
        publish_saved_state(original_session, original_catalog, session, catalog)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@dataclass
class LoadedProject:
    session: Session
    ui_state: dict
    workspace: tempfile.TemporaryDirectory
    catalog: object = None
    custom_colors: tuple[str, ...] = DEFAULT_CUSTOM_COLORS

    def close(self):
        self.workspace.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _load_ui(value):
    from dale.individual_transform import settings as individual_settings
    from dale.measurement import measurement_settings
    from dale.raster_brush import brush_settings
    from dale.selection_groups import group_ui_state

    if not isinstance(value, dict):
        raise ValueError("Invalid project UI settings.")
    mode = value.get("mode", "Pan")
    tool_set = value.get("tool_set", "geometry")
    language = value.get("language", "ru")
    safe_repair = value.get("safe_json_repair", False)
    source_layer = value.get("source_layer", "all")
    if not isinstance(source_layer, str) or not 1 <= len(source_layer) <= 256:
        raise ValueError("Invalid source height layer.")
    if type(safe_repair) is not bool:
        raise ValueError("Invalid source JSON repair preference.")
    raster_erase = number(value.get("raster_erase_diameter", 40), "Raster eraser diameter")
    raster_restore = number(value.get("raster_restore_diameter", 40), "Restore brush diameter")
    square_sizes = {}
    for key in ("raster_erase_square_diameter", "raster_restore_square_diameter"):
        diameter = number(value.get(key, 40), "Square brush diameter")
        if diameter != int(diameter) or not 1 <= diameter <= 4096:
            raise ValueError("Invalid square raster brush diameter.")
        square_sizes[key] = int(diameter)
    line_diameter = number(value.get("line_eraser_diameter", 24), "Line eraser diameter")
    vertex_diameter = number(value.get("vertex_eraser_diameter", 24), "Vertex eraser diameter")
    snap_distance = number(value.get("snap_distance_px", 14), "Snap distance")
    contour_distance = number(value.get("contour_alignment_distance_px", 14), "Alignment distance")
    extension_distance = value.get("extension_distance_px", 14)
    if type(extension_distance) is not int or not 1 <= extension_distance <= 9999:
        raise ValueError("Invalid project extension guide distance.")
    angle_tolerance = number(value.get("right_angle_tolerance_deg", 5), "Angular tolerance")
    circle_detail = value.get("circle_detail_steps", 0)
    figure_scale_step = value.get("figure_scale_step_percent", 5)
    if type(figure_scale_step) is not int or not 1 <= figure_scale_step <= 100:
        raise ValueError("Invalid project contour scaling step.")
    if type(circle_detail) is not int or not 0 <= circle_detail <= 95:
        raise ValueError("Invalid project circle detail.")
    if contour_distance != int(contour_distance) or not 1 <= contour_distance <= 9999:
        raise ValueError("Invalid project alignment distance.")
    if angle_tolerance != int(angle_tolerance) or not 1 <= angle_tolerance <= 90:
        raise ValueError("Invalid project angular tolerance.")
    auto_distance = number(value.get("auto_close_distance_px", 14), "Auto-close distance")
    global_distance = number(
        value.get("global_close_distance_px", 14), "Whole-scene close distance"
    )
    artwork_offset = number(value.get("artwork_offset_px", 0), "Artwork offset")
    if artwork_offset != int(artwork_offset) or not -4096 <= artwork_offset <= 4096:
        raise ValueError("Invalid artwork offset.")
    zoom = number(value.get("zoom", 1), "Viewport zoom")
    rotation_values = {}
    for key, (low, high, default) in ROTATION_VALUE_RANGES.items():
        step = number(value.get(key, default), "Rotation step")
        if step != int(step) or not low <= step <= high:
            raise ValueError("Invalid project rotation step.")
        rotation_values[key] = int(step)
    if mode not in (
        "Pan",
        "Move guides",
        "Auto-close",
        "Edit points",
        "Erase",
        "Restore",
        "Erase square",
        "Restore square",
        "New line",
        "New circle",
        "New rectangle",
        "Erase lines",
        "Erase vertices",
        "Select regions",
        "Select raster regions",
        "Move regions",
        "Rotate regions",
        "Move raster regions",
        "Rotate raster regions",
        "Scale raster regions",
        "Select figures",
        "Move figures",
        "Rotate figures",
        "Scale figures",
    ):
        raise ValueError("Invalid project editing mode.")
    if (
        any(size != int(size) or not 1 <= size <= 4096 for size in (raster_erase, raster_restore))
        or not 0 < zoom <= 10000
    ):
        raise ValueError("Invalid project editing preferences.")
    if language not in ("en", "ru"):
        raise ValueError("Invalid project interface language.")
    if tool_set not in ("geometry", "pixels", "regions", "figures", "alchemist"):
        raise ValueError("Invalid project tool set.")
    if (
        any(
            diameter != int(diameter) or not 1 <= diameter <= 512
            for diameter in (line_diameter, vertex_diameter)
        )
        or not 0 <= snap_distance <= 256
        or auto_distance != int(auto_distance)
        or not 1 <= auto_distance <= 256
        or global_distance != int(global_distance)
        or not 1 <= global_distance <= 256
    ):
        raise ValueError("Invalid project tool sizes or snap distance.")

    def region_selection(selection):
        if selection is None:
            return None
        if (
            not isinstance(selection, list)
            or len(selection) > 100_000
            or any(type(i) is not int or not 0 <= i < 100_000 for i in selection)
        ):
            raise ValueError("Invalid project region selection.")
        return tuple(sorted(set(selection)))

    selected_regions = region_selection(value.get("export_regions"))
    section_regions = value.get("section_region_selections")
    if section_regions is not None:
        if not isinstance(section_regions, dict) or set(section_regions) != {"regions", "pixels"}:
            raise ValueError("Invalid section region selections.")
        section_regions = {
            key: region_selection(selection) for key, selection in section_regions.items()
        }
    snap_enabled = value.get("snap_enabled", True)
    move_related = value.get("move_related_lines", False)
    figure_move_double_click = value.get("figure_move_double_click", True)
    if type(figure_move_double_click) is not bool:
        raise ValueError("Invalid contour move double-click preference.")
    if type(move_related) is not bool:
        raise ValueError("Invalid project related-line preference.")
    if type(snap_enabled) is not bool:
        raise ValueError("Invalid project snapping preference.")
    alignment = {
        key: value.get(key, False) for key in ("right_angle_alignment", "contour_alignment")
    }
    alignment["right_angle_neighbours"] = value.get("right_angle_neighbours", True)
    alignment["figure_extension_alignment"] = value.get("figure_extension_alignment", False)
    alignment["extension_connected"] = value.get("extension_connected", False)
    alignment["right_angle_own_priority"] = value.get("right_angle_own_priority", True)
    alignment.update(
        {
            f"{section}_{kind}_alignment": value.get(f"{section}_{kind}_alignment", kind == "point")
            for section in ("figure", "region")
            for kind in ("point", "guide")
        }
    )
    if any(type(enabled) is not bool for enabled in alignment.values()):
        raise ValueError("Invalid project alignment preference.")
    detached = value.get("detached_region_selection")
    figure_lines = value.get("figure_lines", [])
    figure_pivot = value.get("figure_pivot")
    if (
        not isinstance(figure_lines, list)
        or any(not isinstance(i, str) or not 1 <= len(i) <= 256 for i in figure_lines)
        or len(set(figure_lines)) != len(figure_lines)
    ):
        raise ValueError("Invalid figure line selection.")
    if figure_pivot is not None:
        _point(figure_pivot)
    if detached is not None:
        from shapely import from_wkb

        if not isinstance(detached, dict) or set(detached) != {"lines", "polygons", "pivot"}:
            raise ValueError("Invalid detached region selection.")
        lines, polygons = detached["lines"], detached["polygons"]
        if (
            not isinstance(lines, list)
            or not 1 <= len(lines) <= 100_000
            or any(not isinstance(i, str) or not 1 <= len(i) <= 256 for i in lines)
            or not isinstance(polygons, list)
            or not 1 <= len(polygons) <= 100_000
        ):
            raise ValueError("Invalid detached region selection.")
        for encoded in polygons:
            if not isinstance(encoded, str) or len(encoded) > 32 * 1024 * 1024:
                raise ValueError("Invalid detached region polygon.")
            try:
                polygon = from_wkb(bytes.fromhex(encoded))
            except Exception as exc:
                raise ValueError("Invalid detached region polygon.") from exc
            if (
                polygon.geom_type != "Polygon"
                or polygon.is_empty
                or not polygon.is_valid
                or any(not -1e9 <= v <= 1e9 for v in polygon.bounds)
            ):
                raise ValueError("Invalid detached region polygon.")
        _point(detached["pivot"])
    return {
        **group_ui_state(value),
        "raster_aids": measurement_settings(value.get("raster_aids")),
        "raster_brushes": brush_settings(value.get("raster_brushes")),
        **square_sizes,
        "mode": mode,
        "figure_lines": figure_lines,
        "figure_move_double_click": figure_move_double_click,
        "individual_transform_settings": individual_settings(
            value.get("individual_transform_settings")
        ),
        "figure_pivot": figure_pivot,
        "safe_json_repair": safe_repair,
        "source_layer": source_layer,
        "tool_set": tool_set,
        "language": language,
        "raster_erase_diameter": int(raster_erase),
        "raster_restore_diameter": int(raster_restore),
        "export_regions": selected_regions,
        **({"section_region_selections": section_regions} if section_regions is not None else {}),
        "line_eraser_diameter": int(line_diameter),
        "vertex_eraser_diameter": int(vertex_diameter),
        "snap_distance_px": int(snap_distance),
        "contour_alignment_distance_px": int(contour_distance),
        "extension_distance_px": extension_distance,
        "right_angle_tolerance_deg": int(angle_tolerance),
        "circle_detail_steps": circle_detail,
        "figure_scale_step_percent": figure_scale_step,
        "artwork_offset_px": int(artwork_offset),
        "auto_close_distance_px": int(auto_distance),
        "global_close_distance_px": int(global_distance),
        "snap_enabled": snap_enabled,
        **alignment,
        "move_related_lines": move_related,
        "show_walls": bool(value.get("show_walls", True)),
        "zoom": zoom,
        **rotation_values,
        "center": _point(value.get("center", [0, 0])),
        "detached_region_selection": detached,
    }


def _restore_session(source, documents, manifest, history, *, provenance_documents=()):
    from dale.alchemist import DAData
    from dale.project_state import applied_operations

    source = replace(
        source,
        image_name=manifest.get("image_name", source.image_name),
        json_name=manifest.get("scene_name", source.json_name),
    )
    operations, redo = history["operations"], history["redo"]
    undo_floor = history.get("undo_floor", 0)
    if (
        not isinstance(operations, list)
        or not isinstance(redo, list)
        or len(operations) + len(redo) > 100_000
    ):
        raise ValueError("Invalid or excessive project history.")
    if type(undo_floor) is not int or not 0 <= undo_floor <= len(operations):
        raise ValueError("Invalid project undo checkpoint.")
    operations = applied_operations(operations)
    gap = number(history.get("gap_tolerance", 0), "Gap tolerance")
    offset = number(history.get("contour_offset", 0), "Contour offset")
    if not 0 <= gap <= 4096 or not -4096 <= offset <= 4096:
        raise ValueError("Project contour settings exceed supported limits.")
    session = Session(
        source,
        alchemist=DAData.decode(history["alchemist"]) if "alchemist" in history else None,
        origin=_point(history.get("origin", [0, 0])),
        operations=[_decode(op) for op in operations],
        future=[],
        gap_tolerance=gap,
        contour_offset=offset,
        history_floor=len(operations),
        json_documents=tuple(
            d for d in documents if d.id not in ("source", manifest.get("current_contours_id"))
        ),
    )
    references = {reference.id: reference for reference in session.source.wall_sources}
    needed = {
        ref.json_sha256
        for operation in (*session.operations, *session.future)
        if isinstance(operation, (Closure, GeometryEdit))
        for record in (
            *operation.lineage,
            *(operation.ancestry if isinstance(operation, GeometryEdit) else ()),
        )
        for ref in record.sources
        if ref.id not in references
    }
    for document in (*documents, *provenance_documents):
        if hashlib.sha256(document.data).hexdigest() in needed:
            external = scene_from_json(document.data, source.size)
            references.update((ref.id, ref) for ref in external.wall_sources)
    catalog = {}
    for operation in (*session.operations, *session.future):
        if isinstance(operation, (Closure, GeometryEdit)):
            records = (
                *operation.lineage,
                *(operation.ancestry if isinstance(operation, GeometryEdit) else ()),
            )
            for record in records:
                if record.id in catalog and catalog[record.id] != record:
                    raise ValueError("Conflicting line provenance identities.")
                catalog[record.id] = record
                if any(references.get(ref.id) != ref for ref in record.sources):
                    raise ValueError("Line provenance does not match the embedded source JSON.")
            if isinstance(operation, GeometryEdit):
                owner_ids = {r.id for r in records}
                for owner, styles in operation.wall_styles:
                    if owner not in owner_ids or any(
                        isinstance(style, SourceWall) and references.get(style.id) != style
                        for style in styles
                    ):
                        raise ValueError("Wall properties do not match their declared provenance.")
    known_ids = set(catalog) | set(references)
    if session.alchemist:
        # Old schema7 files may declare pasted objects that exist only in redo.
        # Read their identity labels without decoding any discarded operation.
        discarded_ids = {
            record["id"]
            for operation in redo
            if isinstance(operation, dict)
            for key in ("lineage", "ancestry")
            for record in operation.get(key, ())
            if isinstance(record, dict) and isinstance(record.get("id"), str)
        }
        session.alchemist = replace(
            session.alchemist,
            objects=tuple(
                obj
                for obj in session.alchemist.objects
                if not (set(obj.roots) - known_ids and set(obj.roots) - known_ids <= discarded_ids)
            ),
        )
    if session.alchemist and any(
        root not in known_ids for obj in session.alchemist.objects for root in obj.roots
    ):
        raise ValueError("Dungeon Alchemist objects reference unknown contour identities.")
    for operation in (*session.operations, *session.future):
        raster = getattr(operation, "raster", None)
        if raster is not None and any(
            identifier not in known_ids
            for cell in raster.cells
            for ring in (cell.shell, *cell.holes)
            for identifier in ring
        ):
            raise ValueError("Raster region references unknown lines.")
    from dale.session import RasterSelectionEdit

    for operation in (*session.operations, *session.future):
        if isinstance(operation, RasterSelectionEdit) and any(
            not set(state.line_ids).issubset(known_ids)
            for state in (operation.before, operation.after)
        ):
            raise ValueError("Raster selection references unknown lines.")
    if any(parent not in known_ids for record in catalog.values() for parent in record.parents):
        raise ValueError("Line provenance contains an unknown parent.")
    from dale.layer_repair import canonical_geometry

    addition_sources = {
        addition.source_ref.json_sha256
        for operation in (*session.operations, *session.future)
        if isinstance(operation, SourceRepairEdit)
        for addition in operation.additions
        if addition.source_ref is not None
    }
    imported = {
        hashlib.sha256(d.data).hexdigest(): json.loads(d.data)
        for d in (*documents, *provenance_documents)
        if addition_sources and hashlib.sha256(d.data).hexdigest() in addition_sources
    }
    if source.json_bytes is not None:
        imported[hashlib.sha256(source.json_bytes).hexdigest()] = source.raw
    for operation in (*session.operations, *session.future):
        if isinstance(operation, SourceRepairEdit):
            canonical_geometry(session.source, operation)
            for addition in operation.additions:
                if addition.source_ref is not None:
                    ref = addition.source_ref
                    raw = imported[ref.json_sha256]["walls"][ref.wall_index]
                    expected = {k: v for k, v in raw.items() if k not in ("_id", "id", "c")}
                    if _json_bytes(expected) != addition.properties_json:
                        raise ValueError(
                            "Imported contour properties do not match their exact source."
                        )
    from dale.selection_storage import unpack_selection
    from dale.source_editing import source_layers

    ui = _load_ui(unpack_selection(history.get("ui", {}), session))
    detached = ui["detached_region_selection"]
    if detached and not set(detached["lines"]).issubset({r.id for r in session.geometry().lineage}):
        raise ValueError("Detached selection references missing lines.")
    if session.source.json_bytes is not None and ui["source_layer"] not in {
        layer.key
        for layer in source_layers(
            session.source,
            session.geometry(),
            (*documents, *provenance_documents),
            alchemist=session.alchemist,
        )
    }:
        raise ValueError("Invalid source height layer.")
    stored = next((d for d in documents if d.id == manifest.get("current_contours_id")), None)
    if stored is not None:
        current = _session_json_documents(session)
        if not current or current[-1].id != stored.id or current[-1].data != stored.data:
            raise ValueError("Current contours JSON does not match project history.")
    session.trim_history()
    return session, ui


def _empty_size(manifest):
    size = manifest.get("empty_size")
    if (
        not isinstance(size, (list, tuple))
        or len(size) != 2
        or any(type(n) is not int or not 1 <= n <= 100_000 for n in size)
    ):
        raise ValueError("Invalid empty workspace dimensions.")
    return tuple(size)


def load_project(path: Path, *, progress=None) -> LoadedProject:
    report = progress or (lambda value, label: None)
    report(5, "Reading project archive")
    workspace = tempfile.TemporaryDirectory(prefix="dale-project-")
    try:
        root = Path(workspace.name)
        with zipfile.ZipFile(path) as archive:
            manifest = _archive_manifest(archive)
            report(10, "Checking project documents")
            documents = _read_json_documents(archive, manifest)
            members_to_extract = ["history.json"]
            if manifest["source_kind"] == "image":
                members_to_extract.append("sources/map.image")
            members_to_extract.extend(
                sorted(
                    {
                        d.image_member
                        for d in documents
                        if d.image_member and d.image_member != "sources/map.image"
                    }
                )
            )
            members_to_extract.extend(
                item["member"]
                for item in manifest.get("catalog_images", [])
                if item["member"] not in members_to_extract
            )
            if manifest.get("catalog_views"):
                members_to_extract.append("catalog-views.json")
            if manifest.get("datasets"):
                members_to_extract.append("datasets.json")
            total = max(1, sum(archive.getinfo(m).file_size for m in members_to_extract))
            completed = 0
            report(15, "Extracting and checking project files")
            for member in members_to_extract:
                destination = root / Path(member).name
                with archive.open(member) as source, destination.open("wb") as target:
                    while block := source.read(1024 * 1024):
                        target.write(block)
                        completed += len(block)
                        report(
                            15 + int(40 * completed / total),
                            "Extracting and checking project files",
                        )
                if _hash(destination) != manifest.get("sha256", {}).get(member):
                    raise ValueError(f"Project checksum mismatch: {member}.")
        documents = tuple(
            replace(d, image_path=root / Path(d.image_member).name) if d.image_member else d
            for d in documents
        )
        report(58, "Loading project state")
        from dale.project_state_reader import read_state_file

        history = read_state_file(root / "history.json")
        source_document = next(
            (document for document in documents if document.id == "source"), None
        )
        json_path = root / "scene.json" if source_document else None
        if json_path:
            json_path.write_bytes(source_document.data)
        session, ui = _restore_session(
            (
                SceneInput(
                    None, None, _empty_size(manifest), {}, (), _empty_size(manifest), (0, 0), ()
                )
                if manifest["source_kind"] == "empty"
                else load_pair(
                    root / "map.image" if manifest["source_kind"] == "image" else None, json_path
                )
            ),
            documents,
            manifest,
            history,
        )
        from dale.catalog import CatalogImage, SceneCatalog

        report(65, "Loading project datasets")
        extra_images = []
        for item in manifest.get("catalog_images", []):
            image_path = root / Path(item["member"]).name
            with open_source(image_path) as image:
                size = image.size
            extra_images.append(CatalogImage(item["name"], item["member"], image_path, size))
        catalog = SceneCatalog(session, ui, extra_images=extra_images)
        if manifest.get("catalog_views"):
            catalog.restore(read_state_file(root / "catalog-views.json"))
        if manifest.get("datasets"):
            from dale.datasets import DatasetCatalog

            image_inputs = list(extra_images)
            if manifest["source_kind"] == "image":
                image_inputs.append(
                    CatalogImage(
                        manifest["image_name"],
                        "sources/map.image",
                        root / "map.image",
                        session.source.size,
                    )
                )
            catalog = DatasetCatalog.restore(
                session,
                ui,
                documents,
                image_inputs,
                read_state_file(root / "datasets.json"),
            )
        return LoadedProject(
            catalog.current.session,
            catalog.current.ui,
            workspace,
            catalog,
            _custom_colors(manifest["custom_colors"])
            if "custom_colors" in manifest
            else DEFAULT_CUSTOM_COLORS,
        )
    except Exception:
        workspace.cleanup()
        raise
