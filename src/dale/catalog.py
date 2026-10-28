"""Independent JSON/image views and retained editing drafts in one portable project."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path

from dale.project_io import JsonDocument, _encode, _restore_session, current_contours_document
from dale.scene import SceneInput, load_pair, open_source, scene_from_json
from dale.session import Session, SourceRepairEdit


@dataclass(frozen=True)
class CatalogImage:
    name: str
    member: str
    path: Path | None
    size: tuple[int, int]


@dataclass
class CatalogView:
    session: Session
    ui: dict
    name: str | None = None


def image_key(member, name):
    return "image-" + hashlib.sha256(f"{member}:{name}".encode()).hexdigest()[:24]


class SceneCatalog:
    def __init__(self, session, ui=None, image_sizes=None, extra_images=()):
        self.base_session = session
        self.image_sizes = image_sizes or {}
        self.extra_images = tuple(extra_images)
        self.base_key = (
            "source" if session.source.json_bytes is not None else None,
            "source-image" if session.source.image_path or session.source.image_name else None,
        )
        self.active_key = self.base_key
        self.default_key = self.base_key
        self.views = {self.base_key: CatalogView(session, dict(ui or {}))}

    @property
    def documents(self):
        source = self.base_session.source
        original = (
            (
                JsonDocument(
                    "source", source.json_name or source.name, "original", source.json_bytes
                ),
            )
            if source.json_bytes is not None
            else ()
        )
        return (*original, *self.base_session.json_documents)

    @property
    def images(self):
        source = self.base_session.source
        result = {}
        if self.base_key[1]:
            result["source-image"] = CatalogImage(
                source.image_name or source.image_path.name,
                "sources/map.image",
                source.image_path,
                source.size,
            )
        for document in self.base_session.json_documents:
            if not document.image_member:
                continue
            if (
                document.image_member == "sources/map.image"
                and result.get("source-image")
                and document.image_name == result["source-image"].name
            ):
                continue
            key = image_key(document.image_member, document.image_name)
            if key in result:
                continue
            size = self.image_sizes.get(document.image_member)
            if size is None:
                if document.image_path is None:
                    raise ValueError("Catalog image is unavailable.")
                with open_source(document.image_path) as image:
                    size = image.size
            result[key] = CatalogImage(
                document.image_name, document.image_member, document.image_path, size
            )
        for item in self.extra_images:
            result[image_key(item.member, item.name)] = item
        return result

    @property
    def current(self):
        return self.views[self.active_key]

    @property
    def name(self):
        return self.current.name or self.current.session.source.name

    def source_for(self, key):
        json_id, image_id = key
        documents = {d.id: d for d in self.documents}
        images = self.images
        if (
            json_id is not None
            and json_id not in documents
            or image_id is not None
            and image_id not in images
        ):
            raise ValueError("Unknown catalog selection.")
        document, image = documents.get(json_id), images.get(image_id)
        if document:
            source = scene_from_json(
                document.data,
                image.size if image else None,
                image_path=image.path if image else None,
                json_path=self.base_session.source.json_path if json_id == "source" else None,
            )
            return replace(
                source, json_name=document.name, image_name=image.name if image else None
            )
        size = image.size if image else self.base_session.source.size
        source = (
            load_pair(image.path)
            if image and image.path
            else SceneInput(None, None, size, {}, (), size, (0, 0), ())
        )
        return replace(source, image_name=image.name if image else None)

    def capture(self, ui):
        self.current.ui = dict(ui)

    def import_source(self, source, ui, *, replace_current=False, json_changed=True):
        """Retain old assets/drafts; assign new inputs to a fresh active pair."""
        from uuid import uuid4

        from dale.project_io import _hash

        previous = self.active_key
        documents = self.base_session.json_documents
        json_id, image_id = self.active_key
        if json_changed:
            json_id = None
            if source.json_bytes is not None:
                if len(self.documents) >= 99:
                    raise ValueError(
                        "The project JSON catalog is full. Export to a different project."
                    )
                json_id = "input-" + uuid4().hex
                documents = (
                    *documents,
                    JsonDocument(
                        json_id, source.json_name or source.name, "original", source.json_bytes
                    ),
                )
        images = self.extra_images
        if source.image_path:
            digest = _hash(source.image_path)
            member = f"sources/images/{digest}.image"
            same = next(
                (
                    key
                    for key, item in self.images.items()
                    if item.name == source.image_name and item.path and _hash(item.path) == digest
                ),
                None,
            )
            image_id = same or image_key(member, source.image_name)
            if same is None:
                if len(self.images) >= 100:
                    raise ValueError("The project image catalog is full.")
                images = (
                    *images,
                    CatalogImage(source.image_name, member, source.image_path, source.size),
                )
        else:
            image_id = None
        key = json_id, image_id
        if key in self.views:
            if key == previous:
                return self.current
            # The same assets may already have a different draft. Preserve both.
            if len(self.documents) >= 99:
                raise ValueError("The project JSON catalog is full. Export to a different project.")
            data = source.json_bytes
            if data is None:
                data = json.dumps(
                    {
                        "width": source.scene_size[0],
                        "height": source.scene_size[1],
                        "padding": 0,
                        "walls": [],
                    }
                ).encode()
                source = replace(
                    scene_from_json(data, source.size, image_path=source.image_path),
                    image_name=source.image_name,
                    json_name=Path(source.image_name).with_suffix(".json").name,
                )
            json_id = "input-" + uuid4().hex
            documents = (
                *documents,
                JsonDocument(json_id, source.json_name or source.name, "updated", data),
            )
            key = json_id, image_id
        if len(self.views) >= 256:
            raise ValueError("The project already contains 256 editing views.")
        if not json_changed:
            before = self.current.session.geometry()
            session = replace(
                self.current.session,
                source=source,
                operations=list(self.current.session.operations),
                future=list(self.current.session.future),
                json_documents=(),
            )
            if session.geometry() != before:
                if ui.get("safe_json_repair"):
                    before = SourceRepairEdit(
                        before.walls,
                        lineage=before.lineage,
                        ancestry=before.ancestry,
                        additions=getattr(before, "additions", ()),
                    )
                session.operations.append(before)
        else:
            session = Session(
                source,
                gap_tolerance=self.current.session.gap_tolerance,
                contour_offset=ui.get("artwork_offset_px", 0),
            )
        alias = self.current.name if replace_current else None
        self.base_session.json_documents = documents
        self.extra_images = images
        self.views[key] = CatalogView(session, dict(ui), alias)
        self.active_key = key
        if replace_current:
            self.views.pop(previous, None)
            if previous == self.base_key:
                self._replace_base(key)
            else:
                self._discard_replaced_assets(previous, json_changed)
        return self.current

    def _required_json_hashes(self):
        return {
            ref.json_sha256
            for view in self.views.values()
            for op in (*view.session.operations, *view.session.future)
            if hasattr(op, "lineage")
            for record in (*op.lineage, *getattr(op, "ancestry", ()))
            for ref in record.sources
        }

    def _discard_replaced_assets(self, previous, json_changed):
        old_json, old_image = previous
        if (
            not json_changed
            and old_json != "source"
            and not any(key == previous for key in self.views)
        ):
            image = self.images.get(self.active_key[1])
            self.base_session.json_documents = tuple(
                replace(
                    d,
                    image_name=image.name if image else None,
                    image_member=image.member if image else None,
                    image_path=image.path if image else None,
                )
                if d.id == old_json
                else d
                for d in self.base_session.json_documents
            )
        hashes = self._required_json_hashes()
        if json_changed and old_json != "source" and all(key[0] != old_json for key in self.views):
            self.base_session.json_documents = tuple(
                d
                for d in self.base_session.json_documents
                if d.id != old_json or hashlib.sha256(d.data).hexdigest() in hashes
            )
        in_use = {key[1] for key in self.views}
        associations = {(d.image_member, d.image_name) for d in self.documents}
        self.extra_images = tuple(
            item
            for item in self.extra_images
            if image_key(item.member, item.name) != old_image
            or image_key(item.member, item.name) in in_use
            or (item.member, item.name) in associations
        )

    def _replace_base(self, new_key):
        """Replace creation assets; retain only old inputs still used elsewhere."""
        from uuid import uuid4

        from dale.project_io import _hash

        old_source = self.base_session.source
        new_view = self.views.pop(new_key)
        new_source = new_view.session.source
        documents = self.base_session.json_documents
        needs_old_json = any(key[0] == "source" for key in self.views) or (
            old_source.json_bytes is not None
            and hashlib.sha256(old_source.json_bytes).hexdigest() in self._required_json_hashes()
        )
        same_json = (
            old_source.json_bytes == new_source.json_bytes
            and old_source.json_name == new_source.json_name
        )
        old_json_id = "source"
        if needs_old_json and not same_json and old_source.json_bytes is not None:
            old_json_id = "retained-" + uuid4().hex
            documents = (
                *documents,
                JsonDocument(
                    old_json_id,
                    old_source.json_name or old_source.name,
                    "original",
                    old_source.json_bytes,
                ),
            )
        old_image_id = "source-image"
        same_image = (
            old_source.image_path
            and new_source.image_path
            and old_source.image_name == new_source.image_name
            and _hash(old_source.image_path) == _hash(new_source.image_path)
        )
        if (
            old_source.image_path
            and not same_image
            and any(key[1] == "source-image" for key in self.views)
        ):
            digest = _hash(old_source.image_path)
            member = f"sources/images/{digest}.image"
            old_image_id = image_key(member, old_source.image_name)
            if not any(
                image_key(item.member, item.name) == old_image_id for item in self.extra_images
            ):
                self.extra_images = (
                    *self.extra_images,
                    CatalogImage(
                        old_source.image_name, member, old_source.image_path, old_source.size
                    ),
                )
        # Existing static associations to the old physical root must follow its bytes.
        updated = []
        for document in documents:
            if document.id == new_key[0]:
                continue
            if document.image_member == "sources/map.image":
                if same_image:
                    document = replace(document, image_path=new_source.image_path)
                elif document.image_path:
                    document = replace(
                        document, image_member=f"sources/images/{_hash(document.image_path)}.image"
                    )
            updated.append(document)
        self.base_session = new_view.session
        self.base_session.json_documents = tuple(updated)
        self.base_key = (
            "source" if new_source.json_bytes is not None else None,
            "source-image" if new_source.image_path else None,
        )
        remapped = {}
        for key, view in self.views.items():
            key = (
                old_json_id if key[0] == "source" else key[0],
                old_image_id if key[1] == "source-image" else key[1],
            )
            remapped[key] = view
        remapped[self.base_key] = new_view
        self.views = remapped
        self.default_key = self.active_key = self.base_key
        selected_image = self.images.get(new_key[1])
        if selected_image:
            self.extra_images = tuple(
                item
                for item in self.extra_images
                if image_key(item.member, item.name) != new_key[1]
                or any(key[1] == new_key[1] for key in self.views)
            )

    def activate(self, json_id, image_id, ui=None):
        key = json_id, image_id
        if key not in self.views:
            if len(self.views) >= 256:
                raise ValueError("The project already contains 256 editing views.")
            self.views[key] = CatalogView(Session(self.source_for(key)), dict(ui or {}))
        self.active_key = key
        return self.current

    def rename(self, name):
        if not isinstance(name, str):
            raise ValueError("A set name must contain 1 to 251 characters.")
        name = name.strip()
        if not name or len(name) > 251:
            raise ValueError("A set name must contain 1 to 251 characters.")
        self.current.name = name

    def snapshot(self, key=None):
        key = key or self.active_key
        view = self.views[key]
        document = current_contours_document(view.session)
        image = self.images.get(key[1])
        name = document.name
        if view.name:
            name = view.name if view.name.lower().endswith(".json") else view.name + ".json"
        return replace(
            document,
            name=name,
            image_name=image.name if image else None,
            image_member=image.member if image else None,
            image_path=image.path if image else None,
        )

    def state(self, active_offset=None):
        return (
            (
                self.base_session.source.image_path,
                self.base_session.source.image_name,
                self.base_session.source.json_name,
                self.base_session.source.json_bytes,
                self.base_session.source.size,
            ),
            tuple(self.base_session.json_documents),
            tuple((item.name, item.member) for item in self.extra_images),
            self.default_key,
            tuple(
                (
                    key,
                    tuple(v.session.operations),
                    tuple(v.session.future),
                    v.session.origin,
                    v.session.gap_tolerance,
                    active_offset
                    if key == self.active_key and active_offset is not None
                    else v.ui.get("artwork_offset_px", v.session.contour_offset),
                    v.name,
                )
                for key, v in self.views.items()
                if key == self.base_key
                or v.session.operations
                or v.session.future
                or v.name
                or v.session.origin != (0, 0)
                or v.session.gap_tolerance != 0
                or (
                    active_offset
                    if key == self.active_key and active_offset is not None
                    else v.ui.get("artwork_offset_px", v.session.contour_offset)
                )
                != 0
            ),
        )

    def encode(self):
        from dale.selection_storage import pack_selection

        return {
            "version": 1,
            "base_name": self.views[self.base_key].name,
            "default": self.default_key,
            "views": [
                {
                    "json": key[0],
                    "image": key[1],
                    "name": view.name,
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
                        "ui": pack_selection(view.ui, view.session),
                    },
                }
                for key, view in self.views.items()
                if key != self.base_key
            ],
        }

    def restore(self, value):
        if (
            not isinstance(value, dict)
            or value.get("version") != 1
            or not isinstance(value.get("views"), list)
            or len(value["views"]) > 255
        ):
            raise ValueError("Invalid project catalog editing views.")
        for item in value["views"]:
            if (
                not isinstance(item, dict)
                or any(
                    item.get(k) is not None and not isinstance(item[k], str)
                    for k in ("json", "image")
                )
                or not isinstance(item.get("history"), dict)
            ):
                raise ValueError("Invalid project catalog editing view.")
            key = item["json"], item["image"]
            if key in self.views:
                raise ValueError("Duplicate catalog editing view.")
            source = self.source_for(key)
            session, ui = _restore_session(
                source, (), {}, item["history"], provenance_documents=self.documents
            )
            name = item.get("name")
            if name is not None and (
                not isinstance(name, str) or not name.strip() or len(name) > 251
            ):
                raise ValueError("Invalid catalog set name.")
            self.views[key] = CatalogView(session, ui, name)
        name = value.get("base_name")
        if name is not None:
            self.rename(name)
        default = value.get("default", self.base_key)
        if (
            not isinstance(default, (list, tuple))
            or len(default) != 2
            or any(v is not None and not isinstance(v, str) for v in default)
            or tuple(default) not in self.views
        ):
            raise ValueError("Invalid project default set.")
        self.default_key = tuple(default)
        self.active_key = self.default_key
