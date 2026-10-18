"""Immutable wall property ownership, separate from contact ancestry."""

from __future__ import annotations

import hashlib
import json

from dale.provenance import SourceWall


def ordinary_wall(bottom=None, top=None):
    return {
        "move": 20,
        "sight": 20,
        "light": 20,
        "sound": 20,
        "door": 0,
        "ds": 0,
        "dir": 0,
        "flags": {"wall-height": {"bottom": bottom, "top": top}},
    }


def property_style(properties):
    properties = {k: v for k, v in properties.items() if k != "c"}
    return json.dumps(properties, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def geometry_styles(geometry):
    styles = dict(geometry.wall_styles)
    additions = getattr(geometry, "additions", ())
    count = len(geometry.walls) - len(additions)
    for record, addition in zip(geometry.lineage[count:], additions, strict=False):
        properties = (
            json.loads(addition.properties_json)
            if addition.properties_json is not None
            else ordinary_wall(addition.bottom, addition.top)
        )
        properties["_id"] = addition.native_id
        styles.setdefault(record.id, (property_style(properties),))
    catalog = {r.id: r for r in (*geometry.ancestry, *geometry.lineage)}
    pending = set()

    def resolve(record):
        if record.id in styles:
            return styles[record.id]
        if record.id in pending:
            raise ValueError("Cyclic wall property ownership.")
        pending.add(record.id)
        if record.origin == "source":
            value = record.sources
        elif record.origin == "editor":
            value = (property_style(ordinary_wall()),)
        else:
            value = (
                tuple(
                    dict.fromkeys(
                        style
                        for parent in record.parents
                        if parent in catalog
                        for style in resolve(catalog[parent])
                    )
                )
                or record.sources
                or (property_style(ordinary_wall()),)
            )
        pending.remove(record.id)
        styles[record.id] = tuple(value)
        return styles[record.id]

    for record in geometry.lineage:
        resolve(record)
    return styles


def source_documents(source, documents=()):
    result = {
        hashlib.sha256(document.data).hexdigest(): json.loads(document.data)
        for document in documents
    }
    if source.json_bytes is not None:
        result[hashlib.sha256(source.json_bytes).hexdigest()] = source.raw
    return result


def resolve_style(style, documents):
    if isinstance(style, SourceWall):
        try:
            wall = documents[style.json_sha256]["walls"][style.wall_index]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("Wall properties require their exact source JSON.") from exc
        return {k: v for k, v in wall.items() if k != "c"}
    return json.loads(style)


def encode_styles(styles):
    from dataclasses import asdict

    return {
        identifier: [
            {"source": asdict(style)}
            if isinstance(style, SourceWall)
            else {"properties": json.loads(style)}
            for style in values
        ]
        for identifier, values in styles
    }


def decode_styles(value):
    from dale.provenance import decode_record

    if not isinstance(value, dict) or len(value) > 2_000_000:
        raise ValueError("Invalid wall property ownership.")
    result = []
    for identifier, entries in value.items():
        if not isinstance(identifier, str) or not 1 <= len(identifier) <= 256:
            raise ValueError("Invalid wall property owner.")
        if not isinstance(entries, list) or not 1 <= len(entries) <= 100_000:
            raise ValueError("Invalid wall property list.")
        styles = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("Invalid wall property definition.")
            if set(entry) == {"source"}:
                record = decode_record(
                    {
                        "id": identifier,
                        "origin": "source",
                        "sources": [entry["source"]],
                    }
                )
                styles.append(record.sources[0])
            elif set(entry) == {"properties"} and isinstance(entry["properties"], dict):
                if "c" in entry["properties"]:
                    raise ValueError("Wall properties cannot override coordinates.")
                styles.append(property_style(entry["properties"]))
            else:
                raise ValueError("Invalid wall property definition.")
        result.append((identifier, tuple(styles)))
    return tuple(result)
