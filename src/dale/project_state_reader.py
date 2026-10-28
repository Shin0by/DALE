"""Read applied schema7 state without allocating historical coordinate snapshots."""

import json
import mmap
import re

_TOKEN = re.compile(rb'"[^"\\]*(?:\\.[^"\\]*)*"|\[[^][{}"\\]*\]|[{}\[\]]')
_SPACE = re.compile(rb"\s*")
_ATOM = re.compile(rb"[^,\]}\s]+")


class StateReader:
    def __init__(self, data):
        self.data = data

    def space(self, position):
        return _SPACE.match(self.data, position).end()

    def end(self, start):
        first = self.data[start : start + 1]
        if first == b'"':
            token = _TOKEN.match(self.data, start)
            if token is None:
                raise ValueError("Invalid project state JSON string.")
            return token.end()
        if first not in (b"{", b"["):
            token = _ATOM.match(self.data, start)
            if token is None:
                raise ValueError("Invalid project state JSON value.")
            return token.end()
        stack = []
        for token in _TOKEN.finditer(self.data, start):
            if token.end() - token.start() != 1:
                if token.start() == start:
                    return token.end()
                continue
            value = token.group()
            if value in (b"{", b"["):
                stack.append(value)
            elif value in (b"}", b"]"):
                if not stack or stack.pop() != (b"{" if value == b"}" else b"["):
                    raise ValueError("Invalid project state JSON container.")
                if not stack:
                    return token.end()
        raise ValueError("Incomplete project state JSON.")

    def decode(self, span):
        return json.loads(self.data[span[0] : span[1]])

    def members(self, start):
        opening = self.data[start : start + 1]
        if opening not in (b"{", b"["):
            raise ValueError("Invalid project state JSON container.")
        closing = b"}" if opening == b"{" else b"]"
        position, seen = self.space(start + 1), set()
        while self.data[position : position + 1] != closing:
            key = None
            if opening == b"{":
                end = self.end(position)
                key = self.decode((position, end))
                if not isinstance(key, str) or key in seen:
                    raise ValueError("Duplicate or invalid project state JSON key.")
                seen.add(key)
                position = self.space(end)
                if self.data[position : position + 1] != b":":
                    raise ValueError("Invalid project state JSON member.")
                position = self.space(position + 1)
            end = self.end(position)
            yield key, (position, end)
            position = self.space(end)
            if self.data[position : position + 1] == closing:
                break
            if self.data[position : position + 1] != b",":
                raise ValueError("Invalid project state JSON separator.")
            position = self.space(position + 1)
            if self.data[position : position + 1] == closing:
                raise ValueError("Invalid project state JSON trailing comma.")
        self.container_end = position + 1

    def operations(self, span, *, redo=False):
        if self.data[span[0] : span[0] + 1] != b"[":
            raise ValueError("Invalid project state operations.")

        def entry(_key, start):
            fields = dict(self.members(start))
            end = self.container_end
            kind = self.decode(fields["type"]) if "type" in fields else None
            if kind not in (
                "geometry",
                "source_repair",
                "closure",
                "stroke",
                "mask",
                "raster_selection",
            ):
                raise ValueError("Invalid project state operation.")
            return (kind, (start, end), fields), end

        entries = self.walk(span[0], entry, limit=100_000)
        records, metadata, raster, closures = {}, {}, [], []
        last = max(
            (i for i, (kind, _, _) in enumerate(entries) if kind in ("geometry", "source_repair")),
            default=-1,
        )
        current = None
        for index, (kind, item, fields) in enumerate(entries):
            for key in ("lineage", "ancestry"):
                if key in fields:
                    for record in self.decode(fields[key]):
                        if isinstance(record, dict) and isinstance(record.get("id"), str):
                            records[record["id"]] = {"id": record["id"]} if redo else record
            if redo:
                continue
            for key, value in fields.items():
                if key.startswith("alchemist_"):
                    metadata[key] = self.decode(value)
            if "raster_transform" in fields:
                raster.append(
                    {
                        "type": "geometry",
                        "walls": [],
                        "closures": [],
                        "lineage": [],
                        "ancestry": [],
                        "raster_transform": self.decode(fields["raster_transform"]),
                    }
                )
            if kind in ("stroke", "mask"):
                raster.append(self.decode(item))
            elif index == last:
                current = self.decode(item)
            elif index > last and kind == "closure":
                closures.append(self.decode(item))
        if redo:
            return ([{"lineage": list(records.values())}] if records else []), len(entries)
        if current is not None:
            current.update(metadata)
            current.pop("raster_transform", None)
            live = {record["id"] for record in current.get("lineage", ())}
            current["ancestry"] = [r for key, r in records.items() if key not in live]
        return [*raster, *([current] if current is not None else []), *closures], len(entries)

    def walk(self, start, read, *, limit=100_000):
        opening = self.data[start : start + 1]
        if opening not in (b"{", b"["):
            raise ValueError("Invalid project state JSON container.")
        closing = b"}" if opening == b"{" else b"]"
        result = {} if opening == b"{" else []
        position = self.space(start + 1)
        while self.data[position : position + 1] != closing:
            key = None
            if opening == b"{":
                end = self.end(position)
                key = self.decode((position, end))
                if not isinstance(key, str) or key in result:
                    raise ValueError("Duplicate or invalid project state JSON key.")
                position = self.space(end)
                if self.data[position : position + 1] != b":":
                    raise ValueError("Invalid project state JSON member.")
                position = self.space(position + 1)
            value, end = read(key, position)
            if opening == b"{":
                result[key] = value
            else:
                result.append(value)
            if len(result) > limit:
                raise ValueError("Excessive project state entries.")
            position = self.space(end)
            if self.data[position : position + 1] == closing:
                break
            if self.data[position : position + 1] != b",":
                raise ValueError("Invalid project state JSON separator.")
            position = self.space(position + 1)
            if self.data[position : position + 1] == closing:
                raise ValueError("Invalid project state JSON trailing comma.")
        self.container_end = position + 1
        return result

    def document(self, start=0):
        counts = {}

        def nested(_key, position):
            value = self.document(position)
            return value, self.container_end

        def field(key, position):
            if key in ("operations", "redo"):
                value, counts[key] = self.operations((position, None), redo=key == "redo")
            elif key == "history":
                value = self.document(position)
            elif key in ("sets", "views"):
                value = self.walk(position, nested, limit=256)
            else:
                end = self.end(position)
                return self.decode((position, end)), end
            return value, self.container_end

        result = self.walk(self.space(start), field)
        if not isinstance(result, dict):
            raise ValueError("Invalid project state JSON object.")
        if "operations" in counts:
            floor = result.get("undo_floor", 0)
            if type(floor) is not int or not 0 <= floor <= counts["operations"]:
                raise ValueError("Invalid project undo checkpoint.")
            if sum(counts.values()) > 100_000:
                raise ValueError("Excessive project state operations.")
            result["undo_floor"] = len(result["operations"])
        return result


def read_state_file(path):
    with path.open("rb") as stream:
        if not path.stat().st_size:
            raise ValueError("Empty project state JSON.")
        with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
            return read_state_bytes(data)


def read_state_bytes(data):
    reader = StateReader(data)
    result = reader.document()
    if reader.space(reader.container_end) != len(data):
        raise ValueError("Unexpected trailing project state JSON.")
    return result
