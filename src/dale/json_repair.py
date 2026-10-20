"""Byte-preserving coordinate patches to an immutable original Scene JSON."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from dale.layer_repair import canonical_geometry, repair_history_is_safe


class JsonCoordinateDocument:
    """Locate coordinate-array tokens without rewriting any surrounding source text."""

    def __init__(self, data: bytes):
        self.data = data
        self.text = data.decode("utf-8")
        self.decoder = json.JSONDecoder(parse_constant=self._invalid_constant)
        self.coordinates = {}
        self.wall_spans = {}
        self.walls_start = None
        self.walls_end = None
        self.position = int(self.text.startswith("\ufeff"))
        self._value((), 0)
        self._space()
        if self.position != len(self.text):
            raise ValueError("Unexpected trailing JSON data.")
        self.raw = json.loads(self.text.lstrip("\ufeff"), parse_constant=self._invalid_constant)
        if not isinstance(self.raw, dict) or not isinstance(self.raw.get("walls"), list):
            raise ValueError("Scene JSON must contain a walls array.")

    @staticmethod
    def _invalid_constant(value):
        raise ValueError(f"Nonstandard JSON constant: {value}.")

    def _space(self):
        while self.position < len(self.text) and self.text[self.position] in " \t\r\n":
            self.position += 1

    def _value(self, path, depth):
        if depth > 256:
            raise ValueError("Scene JSON nesting exceeds the safe repair limit.")
        self._space()
        start = self.position
        if start >= len(self.text):
            raise ValueError("Incomplete Scene JSON.")
        char = self.text[start]
        if char == "{":
            self.position += 1
            keys = set()
            self._space()
            if self.text[self.position : self.position + 1] != "}":
                while True:
                    self._space()
                    key, end = self.decoder.raw_decode(self.text, self.position)
                    if not isinstance(key, str) or key in keys:
                        raise ValueError("Duplicate or invalid JSON object key.")
                    keys.add(key)
                    self.position = end
                    self._space()
                    self._take(":")
                    self._value((*path, key), depth + 1)
                    self._space()
                    if self.text[self.position : self.position + 1] != ",":
                        break
                    self.position += 1
            self._take("}")
        elif char == "[":
            self.position += 1
            index = 0
            self._space()
            if self.text[self.position : self.position + 1] != "]":
                while True:
                    self._value((*path, index), depth + 1)
                    index += 1
                    self._space()
                    if self.text[self.position : self.position + 1] != ",":
                        break
                    self.position += 1
            self._take("]")
        else:
            _, self.position = self.decoder.raw_decode(self.text, self.position)
        if len(path) == 3 and path[0] == "walls" and path[2] == "c":
            if char != "[":
                raise ValueError("Invalid source wall coordinate array.")
            self.coordinates[path[1]] = start, self.position
        if path == ("walls",):
            if char != "[":
                raise ValueError("Scene JSON must contain a walls array.")
            self.walls_end = self.position - 1
            self.walls_start = start
        if len(path) == 2 and path[0] == "walls":
            self.wall_spans[path[1]] = start, self.position

    def _take(self, value):
        if self.text[self.position : self.position + 1] != value:
            raise ValueError("Invalid Scene JSON structure.")
        self.position += 1

    def patch(self, changes, appended=()):
        replacements = []
        for index, coordinates in changes.items():
            if index not in self.coordinates or len(coordinates) != 4:
                raise ValueError("Unknown original wall coordinate path.")
            if any(type(v) not in (int, float) or not math.isfinite(v) for v in coordinates):
                raise ValueError("Invalid repaired coordinate.")
            start, end = self.coordinates[index]
            replacements.append((start, end, json.dumps(coordinates, allow_nan=False)))
        insertion = ""
        if appended:
            insertion = ("," if self.raw["walls"] else "") + ",".join(
                json.dumps(wall, allow_nan=False, separators=(",", ":")) for wall in appended
            )
        result = self.text
        if insertion:
            result = result[: self.walls_end] + insertion + result[self.walls_end :]
        for start, end, value in sorted(replacements, reverse=True):
            result = result[:start] + value + result[end:]
        payload = result.encode("utf-8")
        verification = JsonCoordinateDocument(payload)
        if verification.raw["walls"][len(self.raw["walls"]) :] != list(appended):
            raise ValueError("Authored contour verification failed.")
        # Both semantic equality outside c and original byte spans are checked.
        restored = verification.text
        if insertion:
            position = self.walls_end + sum(
                len(v) - (end - start) for start, end, v in replacements
            )
            if restored[position : position + len(insertion)] != insertion:
                raise ValueError("JSON preservation verification failed.")
            restored = restored[:position] + restored[position + len(insertion) :]
        unappended = JsonCoordinateDocument(restored.encode("utf-8"))
        for index in sorted(changes, key=lambda i: unappended.coordinates[i][0], reverse=True):
            start, end = unappended.coordinates[index]
            old_start, old_end = self.coordinates[index]
            restored = restored[:start] + self.text[old_start:old_end] + restored[end:]
        if restored.encode("utf-8") != self.data:
            raise ValueError("JSON preservation verification failed.")
        for index, coordinates in changes.items():
            if verification.raw["walls"][index]["c"] != coordinates:
                raise ValueError("Repaired coordinate verification failed.")
        return payload

    def replace_walls(self, entries):
        """Replace only the native walls array, retaining untouched wall token text."""
        values = []
        for index, wall in entries:
            if index is not None and {k: v for k, v in wall.items() if k != "c"} == {
                k: v for k, v in self.raw["walls"][index].items() if k != "c"
            }:
                start, end = self.wall_spans[index]
                value = self.text[start:end]
                if wall["c"] != self.raw["walls"][index]["c"]:
                    a, b = self.coordinates[index]
                    value = (
                        value[: a - start]
                        + json.dumps(wall["c"], allow_nan=False)
                        + value[b - start :]
                    )
            else:
                value = json.dumps(wall, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            values.append(value)
        prefix, suffix = self.text[: self.walls_start], self.text[self.walls_end + 1 :]
        payload = (prefix + "[" + ",".join(values) + "]" + suffix).encode("utf-8")
        check = JsonCoordinateDocument(payload)
        if check.text[: check.walls_start] != prefix or check.text[check.walls_end + 1 :] != suffix:
            raise ValueError("Non-wall JSON preservation verification failed.")
        if check.raw["walls"] != [wall for _, wall in entries]:
            raise ValueError("Edited wall verification failed.")
        if {k: v for k, v in check.raw.items() if k != "walls"} != {
            k: v for k, v in self.raw.items() if k != "walls"
        }:
            raise ValueError("Non-wall JSON preservation verification failed.")
        return payload


def _coordinate_repair_bytes(session):
    source = session.source
    if source.json_bytes is None:
        raise ValueError("Open a scene JSON before exporting repaired JSON.")
    if not repair_history_is_safe(session):
        raise ValueError(
            "JSON export supports safe contour repair only. Undo other geometry edits or reopen."
        )
    geometry = canonical_geometry(source, session.geometry())
    document = JsonCoordinateDocument(source.json_bytes)
    if document.raw != source.raw:
        raise ValueError("The original scene snapshot is no longer intact.")
    changes = {}
    old_edges = source.image_walls(session.origin)
    count = len(source.wall_sources)
    for edge, old, ref in zip(geometry.walls[:count], old_edges, source.wall_sources, strict=True):
        if edge == old:
            continue
        original = document.raw["walls"][ref.wall_index]["c"]
        coordinates = list(original)
        for side, (point, previous) in enumerate(zip(edge, old, strict=True)):
            if point == previous:
                continue
            for axis in (0, 1):
                value = (
                    point[axis] * source.scene_size[axis] / source.size[axis]
                    + session.origin[axis]
                    + source.background_offset[axis]
                )
                if not math.isfinite(value) or abs(value) > 1e9:
                    raise ValueError("Repaired coordinates exceed the supported range.")
                coordinates[side * 2 + axis] = value
        changes[ref.wall_index] = coordinates
    appended = []
    for edge, addition in zip(
        geometry.walls[count:], getattr(geometry, "additions", ()), strict=True
    ):
        coordinates = [
            point[axis] * source.scene_size[axis] / source.size[axis]
            + session.origin[axis]
            + source.background_offset[axis]
            for point in edge
            for axis in (0, 1)
        ]
        if any(not math.isfinite(v) or abs(v) > 1e9 for v in coordinates):
            raise ValueError("Repaired coordinates exceed the supported range.")
        wall = (
            json.loads(addition.properties_json)
            if addition.properties_json is not None
            else {
                "_id": addition.native_id,
                "c": coordinates,
                "move": 20,
                "sight": 20,
                "light": 20,
                "sound": 20,
                "door": 0,
                "ds": 0,
                "dir": 0,
                "flags": {"wall-height": {"bottom": addition.bottom, "top": addition.top}},
            }
        )
        wall.update(_id=addition.native_id, c=coordinates)
        appended.append(wall)
    changed = (
        *sorted(changes),
        *range(len(document.raw["walls"]), len(document.raw["walls"]) + len(appended)),
    )
    return document.patch(changes, appended), changed


def repaired_json_bytes(session):
    """Export current walls while preserving every byte outside the walls array."""
    if session.source.json_bytes is None:
        raise ValueError("Open a scene JSON before exporting repaired JSON.")
    from dale.session import SourceRepairEdit

    if isinstance(session.geometry(), SourceRepairEdit):
        canonical_geometry(session.source, session.geometry())
    if repair_history_is_safe(session):
        try:
            canonical_geometry(session.source, session.geometry())
        except ValueError:
            pass
        else:
            return _coordinate_repair_bytes(session)
    from dale.provenance import SourceWall, geometry_edges
    from dale.wall_styles import geometry_styles, resolve_style, source_documents

    source, geometry = session.source, session.geometry()
    document = JsonCoordinateDocument(source.json_bytes)
    if document.raw != source.raw:
        raise ValueError("The original scene snapshot is no longer intact.")
    documents = source_documents(source, session.json_documents)
    styles = geometry_styles(geometry)
    root_hash = hashlib.sha256(source.json_bytes).hexdigest()
    identifiers = set()
    entries = []
    represented = {ref.wall_index for ref in source.wall_sources}
    # Zero-length source records are invisible in the editor and remain untouched.
    for index, wall in enumerate(document.raw["walls"]):
        if index not in represented:
            entries.append((index, wall))
            identifiers.add(str(wall.get("_id", wall.get("id", ""))))
    items = list(
        zip(geometry_edges(geometry.walls, geometry.closures), geometry.lineage, strict=True)
    )
    # Original identities get priority over copies at coincident coordinates.
    items.sort(key=lambda item: (item[1].origin != "source", item[1].id))
    for edge, record in items:
        coordinates = [
            p[axis] * source.scene_size[axis] / source.size[axis]
            + session.origin[axis]
            + source.background_offset[axis]
            for p in edge
            for axis in (0, 1)
        ]
        if any(not math.isfinite(v) or abs(v) > 1e9 for v in coordinates):
            raise ValueError("Repaired coordinates exceed the supported range.")
        seen = set()
        for style in styles[record.id]:
            wall = resolve_style(style, documents)
            signature = style
            if signature in seen:
                continue
            seen.add(signature)
            index = (
                style.wall_index
                if isinstance(style, SourceWall) and style.json_sha256 == root_hash
                else None
            )
            native_id = str(wall.get("_id", wall.get("id", "")))
            if not native_id or native_id in identifiers:
                native_id = uuid5(NAMESPACE_URL, repr((record.id, style))).hex[:16]
                while native_id in identifiers:
                    native_id = hashlib.sha256(native_id.encode()).hexdigest()[:16]
                wall.pop("id", None)
                wall["_id"] = native_id
                index = None
            identifiers.add(native_id)
            wall["c"] = coordinates
            entries.append((index, wall))
    entries.sort(key=lambda item: (item[0] is None, item[0] if item[0] is not None else 0))
    originals = {index: wall for index, wall in entries if index is not None}
    changed = tuple(i for i, wall in enumerate(document.raw["walls"]) if originals.get(i) != wall)
    return document.replace_walls(entries), changed


def export_repaired_json(session, destination: Path):
    sources = tuple(p for p in (session.source.json_path, session.source.image_path) if p)
    source = session.source
    if source.json_path and source.json_path.exists() and source.json_bytes is not None:
        if (
            hashlib.sha256(source.json_path.read_bytes()).digest()
            != hashlib.sha256(source.json_bytes).digest()
        ):
            raise ValueError("Source JSON changed outside DALE. Reopen it before exporting.")
    payload, changed = repaired_json_bytes(session)
    write_json_copy(payload, destination, sources)
    return changed


def write_json_copy(payload: bytes, destination: Path, sources=(), *, conflict=None):
    """Atomically save an exact selected JSON document without replacing input assets."""
    destination = destination.resolve()
    if destination.suffix.lower() != ".json":
        raise ValueError("JSON export destination must have a .json extension.")
    if any(
        destination == p.resolve()
        or (destination.exists() and p.exists() and os.path.samefile(destination, p))
        for p in sources
    ):
        raise ValueError("JSON export cannot replace an imported source file.")
    if conflict is not None:
        from dale.export_files import resolve_export_file

        destination = resolve_export_file(destination, conflict)
    temporary = None
    try:
        descriptor, name = tempfile.mkstemp(
            prefix=".dale-json-", suffix=".tmp", dir=destination.parent
        )
        temporary = Path(name)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.read_bytes() != payload:
            raise ValueError("JSON output verification failed.")
        os.replace(temporary, destination)
        temporary = None
        return destination
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
