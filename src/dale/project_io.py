"""Portable .dale ZIP projects with exact sources and complete undo/redo history."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from shapely.geometry import mapping, shape

from dale import __version__
from dale.placement import Placement
from dale.provenance import decode_record, encode_record
from dale.scene import load_pair, number
from dale.session import Closure, ContourMask, GeometryEdit, Session, Stroke

FORMAT = "dale-project"
SCHEMA_VERSION = 2
LIMITS = {
    "manifest.json": 64 * 1024,
    "history.json": 64 * 1024 * 1024,
    "sources/map.jpg": 1024 * 1024 * 1024,
    "sources/scene.json": 32 * 1024 * 1024,
}


@dataclass(frozen=True)
class JsonDocument:
    id: str
    name: str
    kind: str
    data: bytes


def _archive_manifest(archive):
    entries = archive.infolist()
    names = [entry.filename for entry in entries]
    if len(names) != len(set(names)) or "manifest.json" not in names:
        raise ValueError(
            "Project archive must contain exactly the four expected members "
            "and declared JSON files."
        )
    if archive.getinfo("manifest.json").file_size > LIMITS["manifest.json"]:
        raise ValueError("Oversized project manifest.")
    manifest = json.loads(archive.read("manifest.json"))
    if manifest.get("format") != FORMAT or manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            "Unsupported DALE project format or version. Older projects are not supported."
        )
    documents = manifest.get("json_documents")
    if not isinstance(documents, list) or not 1 <= len(documents) <= 100:
        raise ValueError("A current project requires a JSON document catalog.")
    expected = dict(LIMITS)
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
    if "sources/scene.json" not in members or set(names) != set(expected):
        raise ValueError(
            "Project archive must contain exactly the four expected members "
            "and declared JSON files."
        )
    for entry in entries:
        if entry.flag_bits & 1 or not 0 <= entry.file_size <= expected[entry.filename]:
            raise ValueError("Encrypted or oversized project member.")
    if sum(archive.getinfo(member).file_size for member in members) > 128 * 1024 * 1024:
        raise ValueError("Project JSON documents exceed the 128 MiB combined limit.")
    return manifest


def _read_json_documents(archive, manifest):
    documents = []
    for entry in manifest["json_documents"]:
        data = archive.read(entry["member"])
        if hashlib.sha256(data).hexdigest() != manifest.get("sha256", {}).get(entry["member"]):
            raise ValueError(f"Project checksum mismatch: {entry['member']}.")
        documents.append(JsonDocument(entry["id"], entry["name"], entry["kind"], data))
    return tuple(documents)


def read_json_documents(path: Path):
    """Read the declared JSON catalog without extracting or decoding the source JPG."""
    with zipfile.ZipFile(path) as archive:
        return _read_json_documents(archive, _archive_manifest(archive))


def _hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _point(value):
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValueError("Project points must contain exactly two coordinates.")
    return tuple(number(v, "Project coordinate") for v in value)


def _points(values):
    if not isinstance(values, list) or len(values) > 2_000_000:
        raise ValueError("Invalid or excessive project point list.")
    return tuple(_point(value) for value in values)


def _encode(operation):
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
        }
    if isinstance(operation, ContourMask):
        return {"type": "mask", "area": mapping(operation.area), "mode": operation.mode}
    if isinstance(operation, GeometryEdit):
        return {
            "type": "geometry",
            "walls": operation.walls,
            "closures": operation.closures,
            "lineage": [encode_record(record) for record in operation.lineage],
            "ancestry": [encode_record(record) for record in operation.ancestry],
            "vertices": operation.vertex_lineage,
        }
    raise ValueError("Unsupported editing operation.")


def _decode(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid project operation.")
    kind = value.get("type")
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
        return Stroke(points, radius, restore)
    if kind == "mask":
        if value.get("mode") not in ("inside", "outside"):
            raise ValueError("Invalid project mask mode.")
        area = shape(value["area"])
        if area.geom_type not in ("Polygon", "MultiPolygon") or area.is_empty or not area.is_valid:
            raise ValueError("Invalid project mask polygon.")
        if not all(abs(v) <= 1e9 for v in area.bounds):
            raise ValueError("Project mask coordinates exceed the supported range.")
        return ContourMask(area, value["mode"])
    if kind == "geometry":
        walls = tuple(_points(edge) for edge in value["walls"])
        closures = tuple(_points(path) for path in value["closures"])
        if any(len(edge) != 2 for edge in walls) or any(len(path) < 2 for path in closures):
            raise ValueError("Invalid project wall or closure geometry.")
        lineage, ancestry = value.get("lineage"), value.get("ancestry")
        if any(
            not isinstance(records, list) or len(records) > 2_000_000
            for records in (lineage, ancestry)
        ):
            raise ValueError("Invalid or excessive line provenance.")
        if len(lineage) != len(walls) + sum(len(path) - 1 for path in closures):
            raise ValueError("Line provenance is required in the current project format.")
        return GeometryEdit(
            walls,
            closures,
            tuple(decode_record(r) for r in lineage),
            tuple(decode_record(r) for r in ancestry),
        )
    raise ValueError(f"Unsupported project operation type: {kind!r}.")


def _json_bytes(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode(
        "utf-8"
    )


def save_project(session: Session, destination: Path, ui_state: dict | None = None):
    destination = destination.resolve()
    sources = (session.source.image_path, session.source.json_path)
    if destination in (path.resolve() for path in sources) or (
        destination.exists() and any(os.path.samefile(destination, path) for path in sources)
    ):
        raise ValueError("Saving a project cannot replace an imported source file.")
    history = {
        "origin": session.origin,
        "gap_tolerance": session.gap_tolerance,
        "contour_offset": session.contour_offset,
        "operations": [_encode(op) for op in session.operations],
        "redo": [_encode(op) for op in session.future],
        "ui": ui_state or {},
    }
    history_bytes = _json_bytes(history)
    if len(history_bytes) > LIMITS["history.json"]:
        raise ValueError("Editing history exceeds the 64 MiB project limit.")
    manifest = {
        "format": FORMAT,
        "schema_version": SCHEMA_VERSION,
        "app_version": __version__,
        "image_name": session.source.image_path.name,
        "scene_name": session.source.json_path.name,
        "sha256": {
            "sources/map.jpg": _hash(sources[0]),
            "sources/scene.json": _hash(sources[1]),
            "history.json": hashlib.sha256(history_bytes).hexdigest(),
        },
    }
    documents = (
        JsonDocument("source", session.source.json_path.name, "original", sources[1].read_bytes()),
        *session.json_documents,
    )
    manifest["json_documents"] = []
    payloads = {}
    for document in documents:
        member = (
            "sources/scene.json" if document.id == "source" else f"sources/json/{document.id}.json"
        )
        manifest["json_documents"].append(
            {"id": document.id, "name": document.name, "kind": document.kind, "member": member}
        )
        manifest["sha256"][member] = hashlib.sha256(document.data).hexdigest()
        if document.id != "source":
            payloads[member] = document.data
    temporary = None
    try:
        fd, name = tempfile.mkstemp(prefix=".dale-project-", suffix=".tmp", dir=destination.parent)
        temporary = Path(name)
        with os.fdopen(fd, "wb") as stream:
            with zipfile.ZipFile(stream, "w", allowZip64=True) as archive:
                archive.writestr("manifest.json", _json_bytes(manifest), zipfile.ZIP_DEFLATED)
                archive.writestr("history.json", history_bytes, zipfile.ZIP_DEFLATED)
                for member, path in zip(
                    ("sources/map.jpg", "sources/scene.json"), sources, strict=True
                ):
                    if path.stat().st_size > LIMITS[member]:
                        raise ValueError(f"Source exceeds the project limit for {member}.")
                    compression = (
                        zipfile.ZIP_STORED if member.endswith(".jpg") else zipfile.ZIP_DEFLATED
                    )
                    archive.write(path, member, compress_type=compression)
                for member, data in payloads.items():
                    archive.writestr(member, data, zipfile.ZIP_DEFLATED)
            stream.flush()
            os.fsync(stream.fileno())
        with zipfile.ZipFile(temporary) as verification:
            _archive_manifest(verification)
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@dataclass
class LoadedProject:
    session: Session
    ui_state: dict
    workspace: tempfile.TemporaryDirectory

    def close(self):
        self.workspace.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _load_ui(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid project UI settings.")
    placement = Placement(value.get("foundry_major", 14), value.get("elevation_ft", 5))
    mode = value.get("mode", "Pan")
    tool_set = value.get("tool_set", "geometry")
    language = value.get("language", "ru")
    raster_erase = number(value.get("raster_erase_diameter", 40), "Raster eraser diameter")
    raster_restore = number(value.get("raster_restore_diameter", 40), "Restore brush diameter")
    export_padding = number(value.get("export_padding_px", 0), "Export padding")
    line_diameter = number(value.get("line_eraser_diameter", 24), "Line eraser diameter")
    vertex_diameter = number(value.get("vertex_eraser_diameter", 24), "Vertex eraser diameter")
    snap_distance = number(value.get("snap_distance_px", 14), "Snap distance")
    auto_distance = number(value.get("auto_close_distance_px", 14), "Auto-close distance")
    global_distance = number(value.get("global_close_distance_px", 14), "Whole-map close distance")
    zoom = number(value.get("zoom", 1), "Viewport zoom")
    if mode not in (
        "Pan",
        "Auto-close",
        "Edit points",
        "Erase",
        "Restore",
        "New line",
        "Erase lines",
        "Erase vertices",
        "Select regions",
        "Move regions",
    ):
        raise ValueError("Invalid project editing mode.")
    if (
        any(size != int(size) or not 1 <= size <= 4096 for size in (raster_erase, raster_restore))
        or not 0 < zoom <= 10000
    ):
        raise ValueError("Invalid project editing preferences.")
    if language not in ("en", "ru"):
        raise ValueError("Invalid project interface language.")
    if tool_set not in ("geometry", "pixels", "regions"):
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
    selected_regions = value.get("export_regions")
    if selected_regions is not None:
        if (
            not isinstance(selected_regions, list)
            or len(selected_regions) > 100_000
            or any(type(i) is not int or not 0 <= i < 100_000 for i in selected_regions)
        ):
            raise ValueError("Invalid project region selection.")
        selected_regions = tuple(sorted(set(selected_regions)))
    if export_padding != int(export_padding) or not 0 <= export_padding <= 4096:
        raise ValueError("Invalid project export padding.")
    snap_enabled = value.get("snap_enabled", True)
    move_related = value.get("move_related_lines", False)
    if type(move_related) is not bool:
        raise ValueError("Invalid project related-line preference.")
    if type(snap_enabled) is not bool:
        raise ValueError("Invalid project snapping preference.")
    return {
        "foundry_major": placement.foundry_major,
        "elevation_ft": placement.elevation_ft,
        "mode": mode,
        "tool_set": tool_set,
        "language": language,
        "raster_erase_diameter": int(raster_erase),
        "raster_restore_diameter": int(raster_restore),
        "export_padding_px": int(export_padding),
        "export_regions": selected_regions,
        "line_eraser_diameter": int(line_diameter),
        "vertex_eraser_diameter": int(vertex_diameter),
        "snap_distance_px": int(snap_distance),
        "auto_close_distance_px": int(auto_distance),
        "global_close_distance_px": int(global_distance),
        "snap_enabled": snap_enabled,
        "move_related_lines": move_related,
        "show_walls": bool(value.get("show_walls", True)),
        "zoom": zoom,
        "center": _point(value.get("center", [0, 0])),
    }


def load_project(path: Path) -> LoadedProject:
    workspace = tempfile.TemporaryDirectory(prefix="dale-project-")
    try:
        root = Path(workspace.name)
        with zipfile.ZipFile(path) as archive:
            manifest = _archive_manifest(archive)
            documents = _read_json_documents(archive, manifest)
            for member in ("sources/map.jpg", "sources/scene.json", "history.json"):
                destination = root / Path(member).name
                with archive.open(member) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
                if _hash(destination) != manifest.get("sha256", {}).get(member):
                    raise ValueError(f"Project checksum mismatch: {member}.")
        history = json.loads((root / "history.json").read_text(encoding="utf-8"))
        operations, redo = history["operations"], history["redo"]
        if (
            not isinstance(operations, list)
            or not isinstance(redo, list)
            or len(operations) + len(redo) > 100_000
        ):
            raise ValueError("Invalid or excessive project history.")
        gap = number(history.get("gap_tolerance", 0), "Gap tolerance")
        offset = number(history.get("contour_offset", 0), "Contour offset")
        if not 0 <= gap <= 4096 or not -4096 <= offset <= 4096:
            raise ValueError("Project contour settings exceed supported limits.")
        session = Session(
            load_pair(root / "map.jpg", root / "scene.json"),
            origin=_point(history.get("origin", [0, 0])),
            operations=[_decode(op) for op in operations],
            future=[_decode(op) for op in redo],
            gap_tolerance=gap,
            contour_offset=offset,
            json_documents=tuple(document for document in documents if document.id != "source"),
        )
        references = {reference.id: reference for reference in session.source.wall_sources}
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
        known_ids = set(catalog) | set(references)
        if any(parent not in known_ids for record in catalog.values() for parent in record.parents):
            raise ValueError("Line provenance contains an unknown parent.")
        return LoadedProject(session, _load_ui(history.get("ui", {})), workspace)
    except Exception:
        workspace.cleanup()
        raise
