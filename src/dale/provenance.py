"""Persistent line ancestry and exact references to unmodified source JSON walls."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
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
        return cls(
            f"line:{identifier}",
            ids,
            tuple(sources[k] for k in sorted(sources)),
            "editor" if manual else "derived",
        )


def vertex_records(geometry):
    """A contact explicitly names its incident lines, parents, and source walls."""
    nodes = {}
    for edge, record in zip(
        geometry_edges(geometry.walls, geometry.closures), geometry.lineage, strict=True
    ):
        for point in edge:
            nodes.setdefault(point, []).append(record)
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
        }
        for point, records in sorted(nodes.items())
    )


class LineageBuilder:
    """Carry identities through exact copies/splits; other changes require explicit parents."""

    def __init__(self, geometry):
        self.original = geometry
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

    def build(self, walls, closures=(), overrides=None):
        from dale.session import GeometryEdit

        walls, closures = tuple(walls), tuple(closures)
        overrides = overrides or {}
        records = tuple(
            overrides.get(edge_key(edge)) or self.record(edge)
            for edge in geometry_edges(walls, closures)
        )
        catalog = {r.id: r for r in (*self.original.ancestry, *self.original.lineage, *records)}
        return GeometryEdit(walls, closures, records, tuple(catalog.values()))


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
            raise ValueError("Invalid source wall reference.")
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
            raise ValueError("Invalid source wall identity.")
        references.append(SourceWall(digest, index, wall_id))
    return LineRecord(identifier, tuple(parents), tuple(references), origin)
