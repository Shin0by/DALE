"""Persistent line ancestry and exact references to unmodified source JSON contours."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from itertools import pairwise
from uuid import NAMESPACE_URL, uuid4, uuid5

from shapely import STRtree
from shapely.geometry import LineString, Point

EPSILON = 1e-7


def edge_key(edge):
    return tuple(sorted(tuple(p) for p in edge))


def geometry_edges(walls, closures=()):
    return (*walls, *(edge for path in closures for edge in pairwise(path)))


@dataclass(frozen=True, order=True)
class SourceWall:
    json_sha256: str
    wall_index: int
    foundry_id: str | None = None

    @property
    def pointer(self):
        return f"/walls/{self.wall_index}"

    @property
    def id(self):
        return f"sha256:{self.json_sha256}#{self.pointer}"


@dataclass(frozen=True)
class LineRecord:
    id: str
    parents: tuple[str, ...] = ()
    sources: tuple[SourceWall, ...] = ()
    origin: str = "editor"
    connection_group: str | None = field(default=None, compare=False)

    @classmethod
    def source(cls, reference):
        return cls(reference.id, sources=(reference,), origin="source")

    @classmethod
    def standalone(cls, edge):
        digest = hashlib.sha256(json.dumps(edge_key(edge)).encode()).hexdigest()
        return cls(f"editor:{digest}", origin="editor")

    @classmethod
    def child(cls, parents, edge, *, manual=False):
        parents = tuple(sorted({p.id: p for p in parents}.values(), key=lambda p: p.id))
        ids = tuple(p.id for p in parents)
        identifier = (
            str(uuid4()) if manual else str(uuid5(NAMESPACE_URL, repr((ids, edge_key(edge)))))
        )
        sources = {s.id: s for p in parents for s in p.sources}
        groups = {p.connection_group for p in parents}
        return cls(
            f"line:{identifier}",
            ids,
            tuple(sources[k] for k in sorted(sources)),
            "editor" if manual else "derived",
            next(iter(groups)) if len(groups) == 1 else None,
        )


def vertex_records(geometry):
    """A contact explicitly names its incident lines, parents, and source contour segments."""
    nodes = {}
    for edge, record in zip(
        geometry_edges(geometry.walls, geometry.closures), geometry.lineage, strict=True
    ):
        for point in edge:
            nodes.setdefault((point, record.connection_group), []).append(record)
    return tuple(
        {
            "point": point,
            "lines": sorted({r.id for r in records}),
            "parents": sorted({parent for r in records for parent in (r.id, *r.parents)}),
            "sources": [
                asdict(s)
                for s in sorted(
                    {s.id: s for r in records for s in r.sources}.values(), key=lambda s: s.id
                )
            ],
            **({"connection_group": group} if group is not None else {}),
        }
        for (point, group), records in sorted(
            nodes.items(), key=lambda item: (item[0][0], item[0][1] or "")
        )
    )


class LineageBuilder:
    """Carry identities through exact copies/splits; other changes require explicit parents."""

    def __init__(self, geometry):
        from dale.wall_styles import geometry_styles

        self.original = geometry
        self.styles = geometry_styles(geometry)
        self.edges = geometry_edges(geometry.walls, geometry.closures)
        self.shapes = [LineString(edge) for edge in self.edges]
        self.tree = STRtree(self.shapes)
        self.exact = {}
        for edge, record in zip(self.edges, geometry.lineage, strict=True):
            self.exact.setdefault(edge_key(edge), []).append(record)

    def covering(self, edge):
        shape = LineString(edge)
        return tuple(
            self.original.lineage[int(i)]
            for i in self.tree.query(shape.buffer(EPSILON))
            if self.shapes[int(i)].buffer(EPSILON).covers(shape)
        )

    def contacts(self, edge):
        indices = set()
        for point in edge:
            shape = Point(point)
            indices.update(
                int(i)
                for i in self.tree.query(shape.buffer(EPSILON))
                if self.shapes[int(i)].distance(shape) <= EPSILON
            )
        return tuple(self.original.lineage[i] for i in sorted(indices))

    def record(self, edge, parents=None, manual=False):
        exact = self.exact.get(edge_key(edge), ()) if parents is None else ()
        if len(exact) == 1 and not manual:
            return exact[0]
        parents = parents if parents is not None else exact or self.covering(edge)
        if not parents and not manual:
            return LineRecord.child((), edge, manual=True)
        return LineRecord.child(parents, edge, manual=manual)

    def build(self, walls, closures=(), overrides=None, style_overrides=None):
        from dale.session import GeometryEdit

        walls, closures = tuple(walls), tuple(closures)
        overrides = overrides or {}
        used = {}
        records = []
        for edge in geometry_edges(walls, closures):
            key = edge_key(edge)
            candidates = self.exact.get(key, ())
            at = used.get(key, 0)
            record = overrides.get(key)
            if record is None:
                record = candidates[at] if at < len(candidates) else self.record(edge)
            used[key] = at + 1
            records.append(record)
        records = tuple(records)
        catalog = {r.id: r for r in (*self.original.ancestry, *self.original.lineage, *records)}
        from dale.wall_styles import geometry_styles

        styles = dict(self.styles)
        for edge, record in zip(geometry_edges(walls, closures), records, strict=True):
            if style_overrides and edge_key(edge) in style_overrides:
                styles[record.id] = style_overrides[edge_key(edge)]
        result = GeometryEdit(
            walls, closures, records, tuple(catalog.values()), wall_styles=tuple(styles.items())
        )
        return GeometryEdit(
            walls,
            closures,
            records,
            tuple(catalog.values()),
            wall_styles=tuple(geometry_styles(result).items()),
        )


def encode_record(record):
    return asdict(record)


def decode_record(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid line provenance record.")
    identifier, parents, sources = (
        value.get("id"),
        value.get("parents", []),
        value.get("sources", []),
    )
    origin = value.get("origin")
    if (
        not isinstance(identifier, str)
        or not 1 <= len(identifier) <= 256
        or not isinstance(parents, list)
        or len(parents) > 100_000
        or any(not isinstance(p, str) or not 1 <= len(p) <= 256 for p in parents)
        or not isinstance(sources, list)
        or len(sources) > 100_000
        or origin not in ("source", "editor", "derived")
    ):
        raise ValueError("Invalid line provenance fields.")
    references = []
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("Invalid source contour reference.")
        digest, index, wall_id = (
            source.get("json_sha256"),
            source.get("wall_index"),
            source.get("foundry_id"),
        )
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
            or type(index) is not int
            or not 0 <= index < 100_000
            or (wall_id is not None and (not isinstance(wall_id, str) or len(wall_id) > 256))
        ):
            raise ValueError("Invalid source contour identity.")
        references.append(SourceWall(digest, index, wall_id))
    group = value.get("connection_group")
    if group is not None and (not isinstance(group, str) or not 1 <= len(group) <= 128):
        raise ValueError("Invalid contour connection group.")
    return LineRecord(identifier, tuple(parents), tuple(references), origin, group)
