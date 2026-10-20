"""Named independent datasets, transactional component editing and current JSON merging."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import uuid4

from dale.catalog import CatalogImage, CatalogView
from dale.json_repair import JsonCoordinateDocument, repaired_json_bytes
from dale.layer_repair import repair_history_is_safe, wall_bounds
from dale.project_io import JsonDocument, _encode, _restore_session, current_contours_document
from dale.provenance import LineRecord, SourceWall, geometry_edges
from dale.scene import SceneInput, load_pair, scene_from_json
from dale.session import (
    AddedSourceWall,
    Closure,
    ContourMask,
    GeometryEdit,
    Session,
    SourceRepairEdit,
    Stroke,
)


def property_key(value):
    if isinstance(value, dict):
        return tuple((key, property_key(item)) for key, item in sorted(value.items()))
    if isinstance(value, list):
        return tuple(property_key(item) for item in value)
    if type(value) in (int, float):
        return "number", value
    return type(value).__name__, value


def wall_key(wall):
    return tuple(wall["c"]), property_key(
        {k: v for k, v in wall.items() if k not in ("_id", "id", "c")}
    )


def valid_name(value, limit=240):
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > limit
        or value != value.strip()
        or re.search(r'[<>:"/\\|?*\x00-\x1f]', value)
        or value.endswith((".", " "))
        or value.split(".")[0].upper()
        in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }
    ):
        raise ValueError("Use a nonempty file-safe name of at most 240 characters.")
    return value


def empty_source(size=(1, 1)):
    return SceneInput(None, None, size, {}, (), size, (0, 0), ())


def copy_session(session):
    return replace(
        session, operations=list(session.operations), future=list(session.future), json_documents=()
    )


def snapshot_in_frame(geometry, native):
    """Retain the typed repair contract when preserving coordinates in a new image frame."""
    if not native:
        return geometry
    return SourceRepairEdit(
        geometry.walls,
        lineage=geometry.lineage,
        ancestry=geometry.ancestry,
        additions=getattr(geometry, "additions", ()),
    )


@dataclass
class Dataset(CatalogView):
    id: str = ""
    json_name: str | None = None
    image_name: str | None = None

    @property
    def has_json(self):
        return self.session.source.json_bytes is not None or bool(self.session.geometry().lineage)

    @property
    def has_image(self):
        return bool(self.session.source.image_path or self.session.source.image_name)

    def filename(self, kind):
        if kind == "json":
            return self.json_name or self.session.source.json_name or f"{self.name}.json"
        return self.image_name or self.session.source.image_name


class DatasetCatalog:
    managed = True

    def __init__(self, session=None, ui=None):
        session = session or Session(empty_source())
        identifier = "set-" + uuid4().hex
        name = self.unique_name(
            Path(session.source.name).stem
            if session.source.json_bytes or session.source.image_path
            else "Dataset 1",
            (),
        )
        self.views = {identifier: Dataset(session, dict(ui or {}), name, identifier)}
        self.active_key = identifier
        self._hash_cache = {}
        self._source_documents = tuple(session.json_documents)
        self._image_assets = ()
        self.protected_inputs = {
            p for p in (session.source.json_path, session.source.image_path) if p
        }

    @staticmethod
    def unique_name(name, names):
        name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")[:220] or "Dataset"
        try:
            valid_name(name)
        except ValueError:
            name = "Dataset"
        existing = {n.casefold() for n in names}
        candidate, index = name, 2
        while candidate.casefold() in existing:
            candidate = f"{name} ({index})"
            index += 1
        return candidate

    @classmethod
    def from_catalog(cls, catalog):
        if isinstance(catalog, cls):
            return catalog
        result = cls(catalog.base_session, catalog.views[catalog.base_key].ui)
        result.views.clear()
        result._source_documents = catalog.documents
        pairs = [catalog.default_key, *(k for k in catalog.views if k != catalog.default_key)]
        used = {pair[0] for pair in pairs}
        needed = catalog._required_json_hashes()
        for document in catalog.documents:
            if document.id not in used and not (
                not document.image_member
                and document.kind == "original"
                and hashlib.sha256(document.data).hexdigest() in needed
            ):
                image_id = next(
                    (
                        key
                        for key, image in catalog.images.items()
                        if image.member == document.image_member
                        and image.name == document.image_name
                    ),
                    None,
                )
                pairs.append((document.id, image_id))
        active = None
        for pair in pairs:
            old = catalog.views.get(pair)
            session = copy_session(old.session) if old else Session(catalog.source_for(pair))
            # Current pair catalogs have stable selection keys, even before their first save.
            identifier = (
                "set-"
                + hashlib.sha256(
                    json.dumps(pair, separators=(",", ":")).encode("utf-8")
                ).hexdigest()[:32]
            )
            name = result.unique_name(
                old.name if old and old.name else Path(session.source.name).stem,
                (v.name for v in result.views.values()),
            )
            result.views[identifier] = Dataset(
                session, dict(old.ui if old else catalog.current.ui), name, identifier
            )
            if pair == catalog.active_key:
                active = identifier
        result.active_key = active or next(iter(result.views))
        result.protected_inputs.update(
            p
            for view in result.views.values()
            for p in (view.session.source.json_path, view.session.source.image_path)
            if p
        )
        result.prepare()
        return result

    @property
    def base_key(self):
        return next(iter(self.views))

    @property
    def default_key(self):
        return self.active_key

    @property
    def base_session(self):
        return self.views[self.base_key].session

    @property
    def current(self):
        return self.views[self.active_key]

    @property
    def name(self):
        return self.current.name

    @property
    def documents(self):
        source = self.base_session.source
        original = (
            (
                JsonDocument(
                    "source", source.json_name or "Contours.json", "original", source.json_bytes
                ),
            )
            if source.json_bytes is not None
            else ()
        )
        return (*original, *self.base_session.json_documents)

    @property
    def extra_images(self):
        return self._image_assets

    @property
    def images(self):
        source = self.base_session.source
        root = (
            {
                "source-image": CatalogImage(
                    source.image_name or "Image",
                    "sources/map.image",
                    source.image_path,
                    source.size,
                )
            }
            if source.image_path or source.image_name
            else {}
        )
        return {**root, **{item.member: item for item in self._image_assets}}

    def digest(self, path):
        stat = path.stat()
        key = path, stat.st_size, stat.st_mtime_ns
        if key not in self._hash_cache:
            with path.open("rb") as stream:
                self._hash_cache[key] = hashlib.file_digest(stream, "sha256").hexdigest()
            if len(self._hash_cache) > 256:
                self._hash_cache = {key: self._hash_cache[key]}
        return self._hash_cache[key]

    def prepare(self):
        """Declare exact current/provenance assets without changing any input bytes."""
        root = self.base_session.source
        known = {
            hashlib.sha256(d.data).hexdigest(): d
            for d in (*self._source_documents, *self.base_session.json_documents)
        }
        for view in self.views.values():
            source = view.session.source
            if source.json_bytes is not None:
                digest = hashlib.sha256(source.json_bytes).hexdigest()
                known[digest] = JsonDocument(
                    "input-" + digest[:32],
                    source.json_name or "Contours.json",
                    "original",
                    source.json_bytes,
                )
        needed = {
            hashlib.sha256(v.session.source.json_bytes).hexdigest()
            for v in self.views.values()
            if v.session.source.json_bytes is not None
        }
        needed.update(
            ref.json_sha256
            for v in self.views.values()
            for op in (*v.session.operations, *v.session.future)
            if isinstance(op, (GeometryEdit, Closure))
            for record in (*op.lineage, *getattr(op, "ancestry", ()))
            for ref in record.sources
        )
        root_hash = (
            hashlib.sha256(root.json_bytes).hexdigest() if root.json_bytes is not None else None
        )
        documents = tuple(
            replace(
                d,
                id="input-" + digest[:32],
                image_member=None,
                image_name=None,
                image_path=None,
                is_current=False,
            )
            for digest, d in known.items()
            if digest in needed and digest != root_hash
        )
        if (
            len(documents) + bool(root_hash) > 99
            or sum(len(d.data) for d in documents) + len(root.json_bytes or b"") > 128 * 1024 * 1024
        ):
            raise ValueError("The project JSON catalog is full. Export to a different project.")
        self._source_documents = documents
        self.base_session.json_documents = documents
        root_image = self.digest(root.image_path) if root.image_path else None
        images = {}
        for view in self.views.values():
            source = view.session.source
            if source.image_path:
                digest = self.digest(source.image_path)
                if digest != root_image:
                    member = f"sources/images/{digest}.image"
                    images.setdefault(
                        member,
                        CatalogImage(
                            source.image_name or source.image_path.name,
                            member,
                            source.image_path,
                            source.size,
                        ),
                    )
        if len(images) > 99:
            raise ValueError("The project image catalog is full.")
        self._image_assets = tuple(images.values())

    def fork(self):
        result = object.__new__(type(self))
        result.views = {
            key: replace(view, session=copy_session(view.session), ui=dict(view.ui))
            for key, view in self.views.items()
        }
        result.base_session.json_documents = tuple(self.base_session.json_documents)
        result.active_key = self.active_key
        result._hash_cache = dict(self._hash_cache)
        result._source_documents = self.documents
        result._image_assets = self._image_assets
        result.protected_inputs = set(self.protected_inputs)
        return result

    def capture(self, ui):
        self.current.ui = dict(ui)

    def activate(self, identifier):
        if identifier not in self.views:
            raise ValueError("Unknown dataset.")
        self.active_key = identifier
        return self.current

    def create(self, name=None, ui=None):
        if len(self.views) >= 256:
            raise ValueError("The project already contains 256 editing views.")
        name = self.unique_name(name or "Dataset", (v.name for v in self.views.values()))
        identifier = "set-" + uuid4().hex
        view = Dataset(Session(empty_source()), dict(ui or self.current.ui), name, identifier)
        view.ui.update(
            safe_json_repair=False,
            source_layer="all",
            export_regions=None,
            mode="Pan",
            groups=[],
            active_group=None,
            group_sections={},
            section_active_groups={},
            raster_aids={},
            raster_brushes={},
        )
        self.views[identifier] = view
        return view

    def remove(self, identifier):
        self._source_documents = self.documents
        self.views.pop(identifier)
        if not self.views:
            identifier = "set-" + uuid4().hex
            self.views[identifier] = Dataset(Session(empty_source()), {}, "Dataset 1", identifier)
        if self.active_key not in self.views:
            self.active_key = self.base_key
        self.prepare()

    def rename(self, name, identifier=None):
        name = valid_name(name)
        identifier = identifier or self.active_key
        if any(
            v.id != identifier and v.name.casefold() == name.casefold() for v in self.views.values()
        ):
            raise ValueError("A dataset with this name already exists.")
        self.views[identifier].name = name

    def rename_file(self, identifier, kind, stem):
        view = self.views[identifier]
        name = valid_name(stem)
        suffix = (
            Path(view.filename(kind)).suffix
            if view.filename(kind)
            else ".json"
            if kind == "json"
            else ".png"
        )
        setattr(view, kind + "_name", name + suffix)

    def snapshot(self, key=None):
        view = self.views[key or self.active_key]
        doc = current_contours_document(view.session)
        image = view.session.source
        return replace(
            doc,
            name=view.name + ".json",
            image_name=view.name + Path(view.filename("image") or ".png").suffix
            if view.has_image
            else None,
            image_path=image.image_path,
        )

    def state(self, active_offset=None):
        return tuple(
            (
                key,
                v.name,
                v.json_name,
                v.image_name,
                v.session.source,
                tuple(v.session.operations),
                tuple(v.session.future),
                v.session.origin,
                v.session.gap_tolerance,
                active_offset
                if key == self.active_key and active_offset is not None
                else v.ui.get("artwork_offset_px", v.session.contour_offset),
                json.dumps(v.ui.get("groups", []), sort_keys=True),
                json.dumps(v.ui.get("group_sections", {}), sort_keys=True),
            )
            for key, v in self.views.items()
        )

    def encode(self):
        self.prepare()
        documents = {hashlib.sha256(d.data).hexdigest(): d.id for d in self.documents}
        root = self.base_session.source
        root_hash = self.digest(root.image_path) if root.image_path else None
        sets = []
        for key, view in self.views.items():
            source = view.session.source
            digest = self.digest(source.image_path) if source.image_path else None
            sets.append(
                {
                    "id": key,
                    "name": view.name,
                    "json": documents[hashlib.sha256(source.json_bytes).hexdigest()]
                    if source.json_bytes is not None
                    else None,
                    "image": (
                        "sources/map.image"
                        if digest == root_hash
                        else f"sources/images/{digest}.image"
                    )
                    if digest
                    else None,
                    "size": source.size,
                    "json_name": source.json_name,
                    "image_name": source.image_name,
                    "json_label": view.json_name,
                    "image_label": view.image_name,
                    "history": {
                        "origin": view.session.origin,
                        "gap_tolerance": view.session.gap_tolerance,
                        "contour_offset": view.ui.get(
                            "artwork_offset_px", view.session.contour_offset
                        ),
                        "operations": [_encode(op) for op in view.session.operations],
                        "redo": [_encode(op) for op in view.session.future],
                        **(
                            {"undo_floor": view.session.history_floor}
                            if view.session.history_floor
                            else {}
                        ),
                        "ui": view.ui,
                    },
                }
            )
        return {"version": 1, "default": self.default_key, "sets": sets}

    @classmethod
    def restore(cls, session, ui, documents, images, value):
        if (
            not isinstance(value, dict)
            or value.get("version") != 1
            or not isinstance(value.get("sets"), list)
            or not 1 <= len(value["sets"]) <= 256
        ):
            raise ValueError("Invalid project datasets.")
        result = cls(session, ui)
        result.views.clear()
        result._source_documents = documents
        by_id = {d.id: d for d in documents}
        by_member = {i.member: i for i in images}
        names = set()
        for item in value["sets"]:
            if (
                not isinstance(item, dict)
                or not re.fullmatch(r"set-[a-f0-9]{32}", str(item.get("id")))
                or item["id"] in result.views
            ):
                raise ValueError("Invalid or duplicate dataset identity.")
            name = valid_name(item.get("name"))
            if name.casefold() in names:
                raise ValueError("A dataset with this name already exists.")
            names.add(name.casefold())
            size = item.get("size")
            if (
                not isinstance(size, list)
                or len(size) != 2
                or any(type(n) is not int or not 1 <= n <= 100_000 for n in size)
            ):
                raise ValueError("Invalid dataset dimensions.")
            document = by_id.get(item.get("json"))
            image = by_member.get(item.get("image"))
            if (
                item.get("json") is not None
                and document is None
                or item.get("image") is not None
                and image is None
            ):
                raise ValueError("Unknown dataset input reference.")
            source = (
                scene_from_json(
                    document.data, tuple(size), image_path=image.path if image else None
                )
                if document
                else load_pair(image.path)
                if image and image.path
                else empty_source(tuple(size))
            )
            if image and image.size != tuple(size):
                raise ValueError("Dataset image dimensions do not match its input.")
            for field in ("json_name", "image_name", "json_label", "image_label"):
                if item.get(field) is not None:
                    valid_name(item[field], 256)
            source = replace(
                source, json_name=item.get("json_name"), image_name=item.get("image_name")
            )
            restored, settings = _restore_session(
                source, (), {}, item["history"], provenance_documents=documents
            )
            result.views[item["id"]] = Dataset(
                restored,
                settings,
                name,
                item["id"],
                item.get("json_label"),
                item.get("image_label"),
            )
        default = value.get("default")
        if not isinstance(default, str) or default not in result.views:
            raise ValueError("Invalid project default dataset.")
        result.active_key = default
        result.base_session.json_documents = tuple(
            d for d in documents if d.id != "source" and not d.is_current
        )
        result._image_assets = tuple(i for i in images if i.member != "sources/map.image")
        return result

    def replace_component(self, identifier, kind, incoming=None):
        view = self.views[identifier]
        target = view.session
        before = target.geometry()
        raster = [op for op in target.operations if isinstance(op, (Stroke, ContourMask))]
        self._source_documents = self.documents
        if kind == "json":
            view.ui.update(
                groups=[], active_group=None, group_sections={}, section_active_groups={}
            )
            base = (
                incoming.source
                if incoming
                else load_pair(target.source.image_path)
                if target.source.image_path
                else empty_source(target.source.size)
            )
            source = replace(
                base,
                image_path=target.source.image_path,
                image_name=target.source.image_name,
                size=target.source.size if target.source.image_path else base.size,
            )
            if incoming:
                operations = [
                    op for op in incoming.operations if isinstance(op, (GeometryEdit, Closure))
                ]
                geometry = incoming.geometry()
                safe = incoming.source.json_bytes is not None and repair_history_is_safe(incoming)
                temp = Session(source, origin=incoming.origin, operations=operations)
                if temp.geometry() != geometry:
                    operations.append(snapshot_in_frame(geometry, safe))
                origin = incoming.origin
                view.json_name = incoming.source.json_name
            else:
                operations, origin, safe = [], (0, 0), False
                view.json_name = None
            view.session = Session(
                source,
                origin=origin,
                operations=[*operations, *raster],
                gap_tolerance=target.gap_tolerance,
                contour_offset=target.contour_offset,
                history_floor=sum(
                    isinstance(op, (GeometryEdit, Closure))
                    for op in incoming.operations[: incoming.history_floor]
                )
                if incoming
                else 0,
            )
            view.ui.update(safe_json_repair=safe, source_layer="all", export_regions=None)
        elif kind == "image":
            source = replace(
                target.source,
                image_path=incoming.source.image_path if incoming else None,
                image_name=incoming.source.image_name if incoming else None,
                size=incoming.source.size if incoming else target.source.size,
            )
            operations = [op for op in target.operations if isinstance(op, (GeometryEdit, Closure))]
            temp = Session(source, origin=target.origin, operations=operations)
            if temp.geometry() != before:
                safe = target.source.json_bytes is not None and repair_history_is_safe(target)
                operations.append(snapshot_in_frame(before, safe))
            operations.extend(
                op for op in incoming.operations if isinstance(op, (Stroke, ContourMask))
            ) if incoming else None
            view.session = replace(
                target,
                source=source,
                operations=operations,
                future=[],
                json_documents=(),
                history_floor=sum(
                    isinstance(op, (GeometryEdit, Closure))
                    for op in target.operations[: target.history_floor]
                ),
            )
            view.image_name = incoming.source.image_name if incoming else None
            view.ui.update(export_regions=None)
        else:
            raise ValueError("Unknown dataset component.")
        view.ui.update(mode="Pan")
        self.prepare()

    def transfer(self, source_id, destination_id, kind, *, move=False):
        if source_id == destination_id:
            return
        source = self.views[source_id]
        incoming = copy_session(source.session)
        incoming.source = replace(
            incoming.source, json_name=source.filename("json"), image_name=source.filename("image")
        )
        self.replace_component(destination_id, kind, incoming)
        if move:
            self.replace_component(source_id, kind)

    def add_json(self, identifier, incoming):
        """Append exact new contour records; safe native mode retains all other Scene bytes."""
        from dale.wall_styles import geometry_styles, property_style, resolve_style

        view = self.views[identifier]
        if not view.has_json:
            self.replace_component(identifier, "json", incoming)
            return len(incoming.walls)
        session = view.session
        before, addition = session.geometry(), incoming.geometry()
        self._source_documents = (
            *self.documents,
            *incoming.json_documents,
            *(
                (
                    JsonDocument(
                        "incoming",
                        incoming.source.json_name or "Contours.json",
                        "original",
                        incoming.source.json_bytes,
                    ),
                )
                if incoming.source.json_bytes is not None
                else ()
            ),
        )
        incoming_styles = geometry_styles(addition)
        documents = {
            hashlib.sha256(d.data).hexdigest(): json.loads(d.data) for d in self._source_documents
        }
        native_properties = all(
            isinstance(style, SourceWall) for values in incoming_styles.values() for style in values
        )
        if (
            session.source.json_bytes is not None
            and repair_history_is_safe(session)
            and native_properties
        ):
            payload, _ = repaired_json_bytes(session)
            document = JsonCoordinateDocument(payload)
            existing = document.raw["walls"]
            signatures = {wall_key(wall) for wall in existing}
            identifiers = {str(w.get("_id", w.get("id"))) for w in existing}
            walls = []
            kept_records = []
            for edge, record, style in (
                (incoming_edge, incoming_record, owned_style)
                for incoming_edge, incoming_record in zip(
                    geometry_edges(addition.walls, addition.closures), addition.lineage, strict=True
                )
                for owned_style in incoming_styles[incoming_record.id]
            ):
                wall = resolve_style(style, documents)
                wall["c"] = [
                    p[axis] * session.source.scene_size[axis] / session.source.size[axis]
                    + session.origin[axis]
                    + session.source.background_offset[axis]
                    for p in edge
                    for axis in (0, 1)
                ]
                signature = wall_key(wall)
                if signature in signatures:
                    continue
                signatures.add(signature)
                native_id = str(wall.get("_id", wall.get("id", "")))
                if not re.fullmatch(r"[A-Za-z0-9]{16}", native_id) or native_id in identifiers:
                    wall.pop("id", None)
                    wall["_id"] = uuid4().hex[:16]
                    native_id = wall["_id"]
                identifiers.add(native_id)
                walls.append(wall)
                kept_records.append((record, style))
            if not walls:
                return 0
            records = list(before.lineage)
            additions = list(getattr(before, "additions", ()))
            ancestry = {r.id: r for r in (*before.ancestry, *addition.ancestry)}
            ids = {r.id for r in (*records, *before.ancestry)}
            incoming_edges = {
                record.id: edge
                for edge, record in zip(addition.walls, addition.lineage, strict=True)
            }
            for wall, (record, style) in zip(walls, kept_records, strict=True):
                if record.id in ids or record.origin == "derived":
                    ancestry[record.id] = record
                    record = LineRecord.child((record,), incoming_edges[record.id], manual=True)
                records.append(record)
                ids.add(record.id)
                properties = {k: v for k, v in wall.items() if k not in ("_id", "id", "c")}
                try:
                    bottom, top = wall_bounds(wall)
                except ValueError:
                    bottom, top = -math.inf, math.inf
                additions.append(
                    AddedSourceWall(
                        wall["_id"],
                        bottom if math.isfinite(bottom) else None,
                        top if math.isfinite(top) else None,
                        style if isinstance(style, SourceWall) else None,
                        json.dumps(
                            properties, ensure_ascii=True, allow_nan=False, separators=(",", ":")
                        ).encode(),
                    )
                )
            # Appended edges stay in the original image pixel frame.
            edges = (
                *before.walls,
                *(incoming_edges[record.id] for record, _ in kept_records),
            )
            session.add(
                SourceRepairEdit(
                    tuple(edges),
                    lineage=tuple(records),
                    ancestry=tuple(ancestry.values()),
                    additions=tuple(additions),
                )
            )
            view.ui.update(source_layer="all", export_regions=None)
            count = len(walls)
        else:
            # Preserve every existing edge/identity and all immutable raster snapshots.
            edges = list(geometry_edges(before.walls, before.closures))
            records = list(before.lineage)
            styles = geometry_styles(before)

            def signature(edge, record, owned_styles):
                return edge, frozenset(
                    wall_key(dict(resolve_style(style, documents), c=[]))[1]
                    for style in owned_styles[record.id]
                )

            known = {
                signature(edge, record, styles) for edge, record in zip(edges, records, strict=True)
            }
            ids = {record.id for record in (*records, *before.ancestry)}
            ancestors = {r.id: r for r in (*before.ancestry, *addition.ancestry)}
            for edge, record in zip(
                geometry_edges(addition.walls, addition.closures), addition.lineage, strict=True
            ):
                item = signature(edge, record, incoming_styles)
                if item not in known:
                    properties = tuple(
                        property_style(resolve_style(style, documents))
                        for style in incoming_styles[record.id]
                    )
                    if record.id in ids or record.origin == "derived":
                        ancestors[record.id] = record
                        record = LineRecord.child((record,), edge, manual=True)
                    edges.append(edge)
                    records.append(record)
                    styles[record.id] = properties
                    ids.add(record.id)
                    known.add(item)
            count = len(edges) - len(before.lineage)
            if count:
                ancestry = tuple(ancestors.values())
                session.add(
                    GeometryEdit(
                        tuple(edges),
                        lineage=tuple(records),
                        ancestry=ancestry,
                        wall_styles=tuple(styles.items()),
                    )
                )
            view.ui.update(source_layer="all", export_regions=None)
        self.prepare()
        return count


def append_dataset(project, source, identifier, *, reserved_names=()):
    """Add an independent full dataset, verifying the target before atomic publication."""
    from dale.project_io import load_project, save_project

    project = Path(project).resolve()
    with project.open("rb") as stream:
        before = hashlib.file_digest(stream, "sha256").digest()
    with load_project(project) as loaded:
        target = DatasetCatalog.from_catalog(loaded.catalog)
        incoming = source.views[identifier]
        name = target.unique_name(
            incoming.name, (*reserved_names, *(v.name for v in target.views.values()))
        )
        added = target.create(name)
        target._source_documents = (*target.documents, *source.documents)
        copied = replace(
            incoming,
            id=added.id,
            name=added.name,
            session=copy_session(incoming.session),
            ui=dict(incoming.ui),
            json_name=added.name + ".json" if incoming.has_json else None,
            image_name=added.name + Path(incoming.filename("image")).suffix
            if incoming.has_image
            else None,
        )
        target.views[added.id] = copied
        target.prepare()
        with tempfile.TemporaryDirectory(
            prefix=".dale-dataset-export-", dir=project.parent
        ) as directory:
            staging = Path(directory) / "project.dale"
            save_project(
                target.current.session,
                staging,
                target.current.ui,
                catalog=target,
                custom_colors=list(loaded.custom_colors),
            )
            with project.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").digest() != before:
                    raise ValueError("The target project changed during export. Try again.")
            os.replace(staging, project)
    return copied.id, copied.name
