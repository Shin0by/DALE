"""Bounded immutable DA object indexes and retained numeric coordinate buffers."""

from collections import OrderedDict
from functools import cached_property
from math import cos, radians, sin
from threading import RLock

import numpy as np

from dale.provenance import geometry_edges

_POINT = np.dtype([("x", np.float64), ("y", np.float64)])
_EDGE = np.dtype([("start", _POINT), ("end", _POINT)])


def readonly(values, dtype=None):
    array = np.asarray(values, dtype=dtype)
    # Bytes-backed buffers cannot be made writable by a consumer.
    return np.frombuffer(array.tobytes(), dtype=array.dtype).reshape(array.shape)


class ObjectIndex:
    def __init__(self, objects, geometry, owned, *, parent=None, indices=None, coordinates=None):
        self.objects, self.geometry, self.owned = objects, geometry, owned
        self.edges = geometry_edges(geometry.walls, geometry.closures)
        if parent is None:
            lookup, owners, codes = {}, [], []
            for own in owned:
                if own not in lookup:
                    lookup[own] = len(owners)
                    owners.append(own)
                codes.append(lookup[own])
            self.owners = tuple(owners)
            self.codes = readonly(codes, np.int32)
        else:
            self.owners = parent.owners
            self.codes = parent.codes if indices is None else readonly(parent.codes[indices])
        if coordinates is not None:
            self.coordinates = readonly(coordinates, np.float64)
        self.views = OrderedDict()
        self.lock = RLock()

    @cached_property
    def coordinates(self):
        return readonly(self.edges, np.float64).reshape((-1, 2, 2))

    @cached_property
    def flat_view(self):
        from dale.session import GeometryEdit

        return GeometryEdit(
            self.geometry.walls,
            lineage=self.geometry.lineage,
            ancestry=self.geometry.ancestry,
            wall_styles=self.geometry.wall_styles,
        )

    @cached_property
    def by_owner(self):
        order = np.argsort(self.codes, kind="stable")
        splits = np.flatnonzero(np.diff(self.codes[order])) + 1
        return tuple(
            (self.owners[int(self.codes[part[0]])], readonly(part))
            for part in np.split(order, splits)
            if len(part)
        )

    @cached_property
    def units(self):
        parents = {obj.id: obj.id for obj in self.objects}

        def root(identifier):
            while parents[identifier] != identifier:
                parents[identifier] = parents[parents[identifier]]
                identifier = parents[identifier]
            return identifier

        for owners, _ in self.by_owner:
            if len(owners) > 1:
                first, *others = sorted(owners)
                for other in others:
                    parents[root(other)] = root(first)
        grouped = {}
        for owners, indices in self.by_owner:
            if owners:
                grouped.setdefault(root(min(owners)), []).append(indices)
        result = [(key, readonly(np.sort(np.concatenate(parts)))) for key, parts in grouped.items()]
        return tuple(sorted(result, key=lambda item: item[1][0]))

    @cached_property
    def line_positions(self):
        return {record.id: i for i, record in enumerate(self.geometry.lineage)}

    @cached_property
    def bounds(self):
        if not self.units:
            return readonly(np.empty((0, 4)))
        order = np.concatenate([indices for _, indices in self.units])
        starts = np.cumsum([0, *[len(indices) for _, indices in self.units[:-1]]])
        low = np.minimum.reduceat(self.coordinates.min(axis=1)[order], starts, axis=0)
        high = np.maximum.reduceat(self.coordinates.max(axis=1)[order], starts, axis=0)
        return readonly(np.column_stack((low, high)))

    @cached_property
    def drawing_groups(self):
        categories = {obj.id: obj.category for obj in self.objects}
        result, walls = [], []
        for owners, indices in self.by_owner:
            if owners and all(categories[owner] != "wall" for owner in owners):
                result.append((int(indices[0]), tuple(self.edges[i] for i in indices)))
            else:
                walls.append(indices)
        if walls:
            indices = np.sort(np.concatenate(walls))
            result.append((int(indices[0]), tuple(self.edges[i] for i in indices)))
        return tuple(lines for _, lines in sorted(result))

    def selection(self, identifiers):
        mask = np.zeros(len(self.edges), dtype=bool)
        positions = [
            self.line_positions[value] for value in identifiers if value in self.line_positions
        ]
        mask[positions] = True
        return mask

    def visible(self, enabled, scope, category):
        flags = np.asarray(
            [
                (not own and not category and scope not in ("alchemist", "alchemist_all"))
                or bool(own and scope != "regular" and (scope == "alchemist_all" or own & enabled))
                for own in self.owners
            ],
            dtype=bool,
        )
        return np.flatnonzero(flags[self.codes])

    def subset(self, indices):
        from dale.source_editing import layer_geometry

        indices = tuple(indices.tolist()) if isinstance(indices, np.ndarray) else tuple(indices)
        if not self.geometry.closures and indices == tuple(range(len(self.edges))):
            return self.flat_view
        with self.lock:
            if indices in self.views:
                self.views.move_to_end(indices)
                return self.views[indices]
        result = layer_geometry(self.geometry, indices)
        child = ObjectIndex(
            self.objects,
            result,
            tuple(self.owned[i] for i in indices),
            parent=self,
            indices=np.asarray(indices, dtype=np.intp),
        )
        retain(child)
        with self.lock:
            self.views[indices] = result
            while len(self.views) > 2:
                self.views.popitem(last=False)
        return result


_cache = OrderedDict()
_lock = RLock()
_edge_count = 0
MAX_EDGES = 1_000_000
MAX_ENTRIES = 8


def _key(objects, geometry):
    return tuple(
        map(
            id,
            (
                objects,
                geometry.walls,
                geometry.closures,
                geometry.lineage,
                geometry.ancestry,
                geometry.wall_styles,
            ),
        )
    )


def find(data, geometry):
    with _lock:
        key = _key(data.objects, geometry)
        value = _cache.get(key)
        if value is not None:
            _cache.move_to_end(key)
        return value


def retain(value):
    global _edge_count
    cost = max(1, len(value.edges))
    if cost > MAX_EDGES:
        return value
    with _lock:
        key = _key(value.objects, value.geometry)
        if key in _cache:
            return _cache[key]
        while _cache and (len(_cache) >= MAX_ENTRIES or _edge_count + cost > MAX_EDGES):
            _, old = _cache.popitem(last=False)
            _edge_count -= max(1, len(old.edges))
        _cache[key] = value
        _edge_count += cost
    return value


def object_index(data, geometry):
    from dale.alchemist import memberships

    cached = find(data, geometry)
    if cached is not None:
        return cached
    return retain(ObjectIndex(data.objects, geometry, memberships(data, geometry)))


def indexed_layer(data, geometry, indices):
    return object_index(data, geometry).subset(indices)


def transform_objects(data, geometry, identifiers, scale, angle, centers):
    index = object_index(data, geometry)
    return _transform(index, index.units, index.selection(identifiers), scale, angle, centers)


def _transform(index, units, selected, scale, angle, centers, progress=None):
    from dale.session import GeometryEdit

    geometry = index.geometry
    pivots = dict(centers or {})
    moving, origins = [], []
    points = index.coordinates
    bounds = index.bounds if units is index.units else None
    for number, (identifier, indices) in enumerate(units):
        if progress and number % 16 == 0:
            progress(10 + int(80 * number / max(1, len(units))), "Resizing object contours")
        chosen = indices if selected is None else indices[selected[indices]]
        if not len(chosen):
            continue
        if identifier not in pivots:
            if bounds is not None:
                low, high = bounds[number, :2], bounds[number, 2:]
            else:
                values = points[indices]
                low, high = values.min(axis=(0, 1)), values.max(axis=(0, 1))
            pivots[identifier] = tuple(((low + high) / 2).tolist())
        moving.append(chosen)
        origins.append(np.broadcast_to(pivots[identifier], (len(chosen), 2)))
    result = list(index.edges)
    coordinates = points
    if moving:
        positions = np.concatenate(moving)
        pivot = np.concatenate(origins)[:, None, :]
        a, b = scale * cos(radians(angle)), scale * sin(radians(angle))
        values = points[positions] - pivot
        changed = np.empty_like(values)
        changed[..., 0] = pivot[..., 0] + a * values[..., 0] - b * values[..., 1]
        changed[..., 1] = pivot[..., 1] + b * values[..., 0] + a * values[..., 1]
        # Materialize only changed edges at the existing history/serialization boundary.
        edges = changed.reshape((-1, 4)).view(_EDGE).reshape(-1).tolist()
        for position, edge in zip(positions, edges, strict=True):
            result[position] = edge
        coordinates = points.copy()
        coordinates[positions] = changed
    geometry = GeometryEdit(
        tuple(result),
        lineage=geometry.lineage,
        ancestry=geometry.ancestry,
        wall_styles=geometry.wall_styles,
    )
    updated = ObjectIndex(
        index.objects, geometry, index.owned, parent=index, coordinates=coordinates
    )
    updated.units, updated.by_owner = index.units, index.by_owner
    retain(updated)
    return geometry, pivots


def scale_objects(data, geometry, wanted, factor, progress):
    index = object_index(data, geometry)
    parents = {identifier: identifier for identifier in wanted}

    def root(identifier):
        while parents[identifier] != identifier:
            parents[identifier] = parents[parents[identifier]]
            identifier = parents[identifier]
        return identifier

    eligible = [
        (owners, indices)
        for owners, indices in index.by_owner
        if owners and owners.issubset(wanted)
    ]
    for owners, _ in eligible:
        first, *others = sorted(owners)
        for other in others:
            parents[root(other)] = root(first)
    grouped = {}
    for owners, indices in eligible:
        grouped.setdefault(root(min(owners)), []).append(indices)
    units = tuple((key, np.sort(np.concatenate(parts))) for key, parts in grouped.items())
    result, _ = _transform(index, units, None, factor, 0, None, progress)
    return result


def clear_indexes():
    global _edge_count
    with _lock:
        _cache.clear()
        _edge_count = 0
