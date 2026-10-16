"""Portable .dale ZIP projects with exact sources and complete undo/redo history."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from shapely.geometry import mapping, shape

from dale import __version__
from dale.placement import Placement
from dale.scene import load_pair, number
from dale.session import Closure, ContourMask, GeometryEdit, Session, Stroke

FORMAT = "dale-project"
SCHEMA_VERSION = 1
LIMITS = {
    "manifest.json": 64 * 1024,
    "history.json": 64 * 1024 * 1024,
    "sources/map.jpg": 1024 * 1024 * 1024,
    "sources/scene.json": 32 * 1024 * 1024,
}


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
        return {"type": "closure", "points": operation.points}
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
        return {"type": "geometry", "walls": operation.walls, "closures": operation.closures}
    raise ValueError("Unsupported editing operation.")


def _decode(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid project operation.")
    kind = value.get("type")
    if kind == "closure":
        points = _points(value["points"])
        if len(points) < 2:
            raise ValueError("A project closure needs at least two points.")
        return Closure(points)
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
        return GeometryEdit(walls, closures)
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
            stream.flush()
            os.fsync(stream.fileno())
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
    if mode == "Closure":
        mode = "New line"
    tool_set = value.get("tool_set", "geometry")
    language = value.get("language", "ru")
    brush = number(value.get("brush_diameter", 40), "Brush diameter")
    geometry_diameter = number(value.get("geometry_diameter", 24), "Geometry eraser diameter")
    line_diameter = number(
        value.get("line_eraser_diameter", geometry_diameter), "Line eraser diameter"
    )
    vertex_diameter = number(
        value.get("vertex_eraser_diameter", geometry_diameter), "Vertex eraser diameter"
    )
    snap_distance = number(value.get("snap_distance_px", 14), "Snap distance")
    auto_distance = number(value.get("auto_close_distance_px", 14), "Auto-close distance")
    export_region = value.get("export_region", -1)
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
    ):
        raise ValueError("Invalid project editing mode.")
    if not 1 <= brush <= 4096 or not 0 < zoom <= 10000:
        raise ValueError("Invalid project editing preferences.")
    if language not in ("en", "ru"):
        raise ValueError("Invalid project interface language.")
    if tool_set not in ("geometry", "pixels"):
        raise ValueError("Invalid project tool set.")
    if (
        any(
            not 1 <= diameter <= 512
            for diameter in (geometry_diameter, line_diameter, vertex_diameter)
        )
        or not 0 <= snap_distance <= 256
        or auto_distance != int(auto_distance)
        or not 1 <= auto_distance <= 256
    ):
        raise ValueError("Invalid project tool sizes or snap distance.")
    if type(export_region) is not int or not -1 <= export_region < 100_000:
        raise ValueError("Invalid project export region.")
    snap_enabled = value.get("snap_enabled", True)
    if type(snap_enabled) is not bool:
        raise ValueError("Invalid project snapping preference.")
    return {
        "foundry_major": placement.foundry_major,
        "elevation_ft": placement.elevation_ft,
        "mode": mode,
        "tool_set": tool_set,
        "language": language,
        "brush_diameter": int(brush),
        "geometry_diameter": int(geometry_diameter),
        "line_eraser_diameter": int(line_diameter),
        "vertex_eraser_diameter": int(vertex_diameter),
        "snap_distance_px": int(snap_distance),
        "auto_close_distance_px": int(auto_distance),
        "snap_enabled": snap_enabled,
        "export_region": export_region,
        "show_walls": bool(value.get("show_walls", True)),
        "zoom": zoom,
        "center": _point(value.get("center", [0, 0])),
        "pending_closure": _points(value.get("pending_closure", [])),
    }


def load_project(path: Path) -> LoadedProject:
    workspace = tempfile.TemporaryDirectory(prefix="dale-project-")
    try:
        root = Path(workspace.name)
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)) or set(names) != set(LIMITS):
                raise ValueError("Project archive must contain exactly the four expected members.")
            for entry in entries:
                if entry.flag_bits & 1 or not 0 <= entry.file_size <= LIMITS[entry.filename]:
                    raise ValueError("Encrypted or oversized project member.")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest.get("format") != FORMAT or manifest.get("schema_version") != SCHEMA_VERSION:
                raise ValueError("Unsupported DALE project format or version.")
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
        )
        return LoadedProject(session, _load_ui(history.get("ui", {})), workspace)
    except Exception:
        workspace.cleanup()
        raise
