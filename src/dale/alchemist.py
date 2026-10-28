"""Dungeon Alchemist import metadata, immutable source sizes and scoped contours."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import zlib
from dataclasses import dataclass, replace
from functools import lru_cache
from uuid import uuid4

from dale.alchemist_terrain import FEET_PER_DA_CELL, ground_height, read_terrain
from dale.provenance import LineRecord, geometry_edges
from dale.session import GeometryEdit
from dale.source_editing import layer_geometry
from dale.wall_styles import geometry_styles, ordinary_wall, property_style

CATEGORIES = ("wall", "tree", "bush", "rock")
DISPLAY_CATEGORIES = {
    "ffaf276aa837446ae9c89522bf00b151#6637960012852186378": "tree",
    "e6bf0691dcea246a082e1c346c877689#6637960012852186378": "bush",
    "50d7b19b372994769a7cd147d9bd1be4#6637960012852186378": "rock",
}
MAX_SOURCE = 64 * 1024 * 1024


class AlchemistCancelled(Exception):
    """Cooperative import cancellation, without publishing partial contours."""


def finite(value, label, limit=1e9):
    if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > limit:
        raise ValueError(f"Invalid Dungeon Alchemist {label}.")
    return float(value)


def object_placement(instance, block):
    """Compose DA mesh-to-model and model-to-instance transforms in the X/Z plane."""
    instance_scale = finite(instance.get("scale", 1), "instance scale")
    scale = instance_scale * finite(block.get("scale", 1), "model scale")
    angle = math.radians(finite(instance.get("rotation", 0), "rotation"))
    # Object is the game's default BuildingBlockType. Its model rotator adds180
    # degrees before the block's own rotation/scale, then its unscaled offset.
    model_angle = math.radians(
        finite(block.get("rotation", 0), "model rotation")
        + (180 if block.get("type", 2) == 2 else 0)
    )
    ox = finite(block.get("xOffset", 0), "model offset")
    oz = finite(block.get("zOffset", 0), "model offset")
    tx = finite(instance["center"].get("x", 0), "object center") + instance_scale * (
        ox * math.cos(angle) + oz * math.sin(angle)
    )
    tz = finite(instance["center"].get("y", 0), "object center") + instance_scale * (
        -ox * math.sin(angle) + oz * math.cos(angle)
    )
    a, b = scale * math.cos(angle + model_angle), scale * math.sin(angle + model_angle)
    base = finite(instance.get("height", 0), "object elevation") + instance_scale * finite(
        block.get("yOffset", 0), "model elevation"
    )
    return (a, b, -b, a, tx, tz), base, scale


@dataclass(frozen=True)
class DAObject:
    id: str
    category: str
    original_size: float
    roots: tuple[str, ...]
    layer: int = 0
    original_height_ft: float | None = None
    block_id: str | None = None
    projection: tuple | None = None


@dataclass(frozen=True)
class DAData:
    name: str
    source: bytes
    objects: tuple[DAObject, ...]
    # Each category stores enabled, minimum original diameter in cells.
    settings: tuple = ((True, 0.0),) * 4
    show_regular: bool = True
    minimum_heights_ft: tuple = (0, 0, 0, 0)
    individual_transforms: bool = False
    json_walls: tuple = (None,) * 4
    profiles: tuple = ()
    alpha_projection: bool = False
    separate_projection_parts: bool = False

    def encode(self):
        return {
            "version": 1,
            "name": self.name,
            "sha256": hashlib.sha256(self.source).hexdigest(),
            "source_zlib": base64.b64encode(zlib.compress(self.source)).decode("ascii"),
            "objects": [
                {
                    "id": o.id,
                    "category": o.category,
                    "original_size": o.original_size,
                    "roots": o.roots,
                    "layer": o.layer,
                    "original_height_ft": o.original_height_ft,
                    "block_id": o.block_id,
                    **({"projection": o.projection} if o.projection is not None else {}),
                }
                for o in self.objects
            ],
            "settings": self.settings,
            "show_regular": self.show_regular,
            "minimum_heights_ft": self.minimum_heights_ft,
            "individual_transforms": self.individual_transforms,
            "json_walls": [
                json.loads(value) if value is not None else None for value in self.json_walls
            ],
            "profiles": [
                [key, [base64.b64encode(b).decode("ascii") for b in layers]]
                for key, layers in self.profiles
            ],
            "alpha_projection": self.alpha_projection,
            "separate_projection_parts": self.separate_projection_parts,
        }

    @classmethod
    def decode(cls, value):
        if not isinstance(value, dict) or value.get("version") != 1:
            raise ValueError("Invalid Dungeon Alchemist project data.")
        name = value.get("name")
        if not isinstance(name, str) or not 1 <= len(name) <= 256:
            raise ValueError("Invalid Dungeon Alchemist source name.")
        try:
            decompressor = zlib.decompressobj()
            source = decompressor.decompress(
                base64.b64decode(value["source_zlib"], validate=True), MAX_SOURCE + 1
            )
            if len(source) > MAX_SOURCE or not decompressor.eof or decompressor.unused_data:
                raise ValueError("Invalid or oversized Dungeon Alchemist source.")
        except (ValueError, KeyError, TypeError, zlib.error) as exc:
            raise ValueError("Invalid compressed Dungeon Alchemist source.") from exc
        if hashlib.sha256(source).hexdigest() != value.get("sha256"):
            raise ValueError("Dungeon Alchemist source checksum mismatch.")
        original = read_map(source)
        instance_types = {i["id"]: i["blockId"] for i in original["buildingBlockInstances"]}
        original_types = {
            o["id"]: instance_types[o["buildingBlockInstanceId"]]
            for o in (*original["objects"], *original["walls"])
        }
        objects, identifiers, roots = [], set(), set()
        items = value.get("objects")
        if not isinstance(items, list) or len(items) > 100000:
            raise ValueError("Invalid Dungeon Alchemist object catalog.")
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Invalid Dungeon Alchemist object.")
            identifier, category, own = item.get("id"), item.get("category"), item.get("roots")
            if (
                not isinstance(identifier, str)
                or not 1 <= len(identifier) <= 128
                or identifier in identifiers
                or category not in CATEGORIES
                or not isinstance(own, list)
                or not 1 <= len(own) <= 100000
                or any(not isinstance(r, str) or not 1 <= len(r) <= 256 or r in roots for r in own)
                or len(set(own)) != len(own)
            ):
                raise ValueError("Invalid Dungeon Alchemist object identity.")
            size = finite(item.get("original_size"), "original size")
            if size < 0:
                raise ValueError("Invalid Dungeon Alchemist original size.")
            identifiers.add(identifier)
            roots.update(own)
            layer = item.get("layer", 0)
            if type(layer) is not int or not -1000 <= layer <= 1000:
                raise ValueError("Invalid Dungeon Alchemist floor.")
            height = item.get("original_height_ft")
            if height is not None:
                height = finite(height, "original height above surface")
                if height < 0:
                    raise ValueError("Invalid Dungeon Alchemist height above surface.")
            block_id = item.get("block_id", original_types.get(identifier))
            if block_id is not None and (
                not isinstance(block_id, str) or not 1 <= len(block_id) <= 256
            ):
                raise ValueError("Invalid Dungeon Alchemist object type.")
            from dale.alchemist_slices import decode_placement

            objects.append(
                DAObject(
                    identifier,
                    category,
                    size,
                    tuple(own),
                    layer,
                    height,
                    block_id,
                    decode_placement(item.get("projection")),
                )
            )
        settings = value.get("settings")
        if not isinstance(settings, list) or len(settings) != 4:
            raise ValueError("Invalid Dungeon Alchemist category settings.")
        parsed = []
        for pair in settings:
            if not isinstance(pair, list) or len(pair) != 2 or type(pair[0]) is not bool:
                raise ValueError("Invalid Dungeon Alchemist category setting.")
            minimum = finite(pair[1], "minimum size", 10000)
            if minimum < 0:
                raise ValueError("Invalid Dungeon Alchemist minimum size.")
            parsed.append((pair[0], minimum))
        if type(value.get("show_regular")) is not bool:
            raise ValueError("Invalid Dungeon Alchemist reference display.")
        heights = value.get("minimum_heights_ft", [0, 0, 0, 0])
        if (
            not isinstance(heights, list)
            or len(heights) != 4
            or any(type(h) is not int or not 0 <= h <= 10 for h in heights)
        ):
            raise ValueError("Invalid Dungeon Alchemist minimum heights.")
        individual = value.get("individual_transforms", False)
        if type(individual) is not bool:
            raise ValueError("Invalid Dungeon Alchemist individual transform setting.")
        from dale.alchemist_export import decode_settings
        from dale.alchemist_slices import decode_profiles

        profiles = decode_profiles(value.get("profiles", []))
        alpha_projection = value.get("alpha_projection", False)
        if type(alpha_projection) is not bool:
            raise ValueError("Invalid Dungeon Alchemist alpha projection setting.")
        separate_parts = value.get("separate_projection_parts", False)
        if type(separate_parts) is not bool:
            raise ValueError("Invalid Dungeon Alchemist projection boundary setting.")
        keys = {key for key, _ in profiles}
        if any(o.projection is not None and o.block_id not in keys for o in objects):
            raise ValueError("Missing Dungeon Alchemist projection profile.")

        return cls(
            name,
            source,
            tuple(objects),
            tuple(parsed),
            value["show_regular"],
            tuple(heights),
            individual,
            decode_settings(value.get("json_walls")),
            profiles,
            alpha_projection,
            separate_parts,
        )


def read_map(raw):
    if len(raw) > MAX_SOURCE:
        raise ValueError("Dungeon Alchemist source exceeds 64 MiB.")
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("Version") not in (6, 11):
        raise ValueError("Supported Dungeon Alchemist file versions are 6 and 11.")
    for key in ("width", "height"):
        if type(data.get(key)) is not int or not 1 <= data[key] <= 10000:
            raise ValueError("Invalid Dungeon Alchemist map dimensions.")
    for key in ("buildingBlockInstances", "objects", "walls", "foundations"):
        if not isinstance(data.get(key), list) or len(data[key]) > 100000:
            raise ValueError("Invalid Dungeon Alchemist object arrays.")
        identifiers = set()
        for item in data[key]:
            if not isinstance(item, dict):
                raise ValueError("Invalid Dungeon Alchemist object record.")
            identifier = item.get("id")
            if (
                not isinstance(identifier, str)
                or not 1 <= len(identifier) <= 80
                or identifier in identifiers
            ):
                raise ValueError("Invalid or duplicate Dungeon Alchemist object identifier.")
            identifiers.add(identifier)
    instances = {item["id"] for item in data["buildingBlockInstances"]}
    foundations = {item["id"] for item in data["foundations"]}
    identifiers = set()
    for item in (*data["objects"], *data["walls"]):
        if (
            item.get("buildingBlockInstanceId") not in instances
            or item.get("foundationId") not in foundations
            or item["id"] in identifiers
        ):
            raise ValueError("Invalid Dungeon Alchemist object reference.")
        identifiers.add(item["id"])
    return data


def category_of(block):
    categories = set(block.get("displayCategoryIds", ()))
    for identifier, category in DISPLAY_CATEGORIES.items():
        if identifier in categories:
            return category
    return None


def _bounds(block, model, category):
    manual = block.get("manualColliderSet", {}).get("colliders", [])
    boxes = []
    for collider in manual:
        center = collider.get("center", {})
        if "size" in collider:
            extents = {
                k: finite(collider["size"].get(k, 0), "collider size") / 2 for k in ("x", "y", "z")
            }
        elif "outerRadius" in collider:
            radius = finite(collider["outerRadius"], "collider radius")
            extents = {
                "x": radius,
                "z": radius,
                "y": finite(collider.get("height", 0), "collider height") / 2,
            }
        else:
            continue
        boxes.append({"center": center, "extents": extents})
    if not boxes:
        boxes = model.get("colliderBounds", [])
    render = model.get("mapColliderCache", {}).get("stateIndependentBounds") or model.get("bounds")
    # Foliage uses its actual envelope; a trunk uses the lowest useful collider.
    if category == "bush" and render:
        boxes = [render]
    if not boxes:
        boxes = [render] if render else []
    if not boxes:
        raise ValueError("The Dungeon Alchemist model has no usable dimensions.")
    if category == "tree":
        boxes = [min(boxes, key=lambda b: b.get("center", {}).get("y", 0))]
    lows, highs = {}, {}
    for axis in ("x", "y", "z"):
        lows[axis] = min(
            finite(b.get("center", {}).get(axis, 0), "model center")
            - finite(b.get("extents", {}).get(axis, 0), "model extent")
            for b in boxes
        )
        highs[axis] = max(
            finite(b.get("center", {}).get(axis, 0), "model center")
            + finite(b.get("extents", {}).get(axis, 0), "model extent")
            for b in boxes
        )
    return lows, highs, render


def _import_bounds(session):
    """Declared Scene JSON bounds in the same image-space frame as native export."""
    source = session.source
    if source.json_bytes is None:
        return 0.0, 0.0, float(source.size[0]), float(source.size[1])
    low = tuple(
        -(session.origin[i] + source.background_offset[i]) * source.size[i] / source.scene_size[i]
        for i in (0, 1)
    )
    return *low, low[0] + source.size[0], low[1] + source.size[1]


def _outside_import_bounds(outlines, bounds):
    points = [point for ring in outlines for point in ring]
    if not points:
        return True
    left, top, right, bottom = bounds
    xs, ys = zip(*points, strict=True)
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    if x1 < left or x0 > right or y1 < top or y0 > bottom:
        return True
    if left <= x0 <= x1 <= right and top <= y0 <= y1 <= bottom:
        return False
    from shapely import MultiLineString, box, build_area

    frame = box(*bounds)
    lines = MultiLineString([ring for ring in outlines if len(ring) >= 2])
    # Crossing/touching open walls and polygon edges stay intact. A closed contour
    # surrounding the frame also intersects it, even if every vertex is outside.
    return not lines.intersects(frame) and not build_area(lines).intersects(frame)


def remove_outside_objects(session, progress=None):
    """Remove whole current DA objects outside the registered map, with normal undo."""
    from dale.region_transform import delete_figures

    geometry = session.geometry()
    owners = memberships(session.alchemist, geometry)
    by_object = {}
    for edge, owned in zip(geometry_edges(geometry.walls, geometry.closures), owners, strict=True):
        for identifier in owned:
            by_object.setdefault(identifier, []).append(edge)
    bounds, outside = _import_bounds(session), set()
    for index, (identifier, edges) in enumerate(by_object.items()):
        if progress:
            progress(int(90 * index / max(1, len(by_object))), "Checking map bounds")
        if _outside_import_bounds(edges, bounds):
            outside.add(identifier)
    removed = {
        record.id
        for record, owned in zip(geometry.lineage, owners, strict=True)
        if owned and owned.issubset(outside)
    }
    return delete_figures(geometry, removed) if removed else None, len(outside)


def import_map(raw, name, session, library, progress=None, load_geometry=False):
    report = progress or (lambda *_: None)
    report(5, "Reading the Dungeon Alchemist map")
    if not isinstance(name, str) or not 1 <= len(name) <= 256:
        raise ValueError("Invalid Dungeon Alchemist source name.")
    data = read_map(raw)
    surface = read_terrain(data)
    import_bounds = _import_bounds(session)
    report(15, "Reading local object descriptions")
    instances = {b["id"]: b for b in data["buildingBlockInstances"]}
    foundations = {f["id"]: f for f in data["foundations"]}
    needed = {instances[o["buildingBlockInstanceId"]]["blockId"] for o in data["objects"]}
    needed.update(instances[w["buildingBlockInstanceId"]]["blockId"] for w in data["walls"])
    metadata = library.resolve(needed, data.get("usedWorkshopItems", {}))
    footprints = (
        library.profiles(metadata, data.get("usedWorkshopItems", {}), report)
        if (load_geometry)
        else {}
    )
    # The map extent provides a deterministic initial image-space registration.
    sx, sy = session.source.size[0] / data["width"], session.source.size[1] / data["height"]
    unit = session.source.raw.get("gridDistance", 5)
    if isinstance(session.source.raw.get("grid"), dict):
        unit = session.source.raw["grid"].get("distance", unit)
    unit = finite(unit, "scene distance")
    if unit <= 0:
        raise ValueError("Scene grid distance must be positive.")
    previous = session.geometry()
    if session.alchemist:
        previous = scoped_geometry(session, previous, "regular")
    edges, records = list(geometry_edges(previous.walls, previous.closures)), list(previous.lineage)
    retained = {r.id for r in (*previous.lineage, *previous.ancestry)}
    styles = {key: value for key, value in geometry_styles(previous).items() if key in retained}
    digest = hashlib.sha256(raw).hexdigest()
    objects = []
    outline_cache = {}
    imported_ancestry = list(previous.ancestry)
    object_tokens = {}

    def append(
        identifier,
        category,
        original_size,
        points,
        bottom,
        top,
        layer=0,
        ground=0,
        block_id=None,
        rings=None,
        projection=None,
    ):
        if not isinstance(identifier, str) or not 1 <= len(identifier) <= 80:
            raise ValueError("Invalid Dungeon Alchemist object identifier.")
        if type(layer) is not int or not -1000 <= layer <= 1000:
            raise ValueError("Invalid Dungeon Alchemist floor.")
        for point in points:
            for value in point:
                finite(value, "contour coordinate")
        own = []
        outlines = rings if rings is not None else (points,)
        if _outside_import_bounds(outlines, import_bounds):
            return
        token = hashlib.sha256(f"{digest}:{identifier}".encode()).hexdigest()[:24]
        if token in object_tokens and object_tokens[token] != identifier:
            raise ValueError("Dungeon Alchemist object identity collision.")
        object_tokens[token] = identifier
        style_id = f"da-style:{token}"
        group = f"da:{token}"
        style = (property_style(ordinary_wall(bottom * unit, max(top, bottom + 0.01) * unit)),)
        if projection is not None:
            # One explicit owner avoids serializing identical wall properties for
            # every edge of a detailed texture-derived obstacle.
            imported_ancestry.append(LineRecord(style_id, origin="editor", connection_group=group))
            styles[style_id] = style
        for i, edge in enumerate(
            edge for ring in outlines for edge in zip(ring, ring[1:], strict=False)
        ):
            rid = f"da:{token}:{i}"
            own.append(rid)
            edges.append(edge)
            records.append(
                LineRecord(
                    rid,
                    parents=(style_id,) if projection is not None else (),
                    origin="derived" if projection is not None else "editor",
                    connection_group=group,
                )
            )
            if projection is None:
                styles[rid] = style
        height = finite(max(0, (top - ground) * FEET_PER_DA_CELL), "height above surface")
        objects.append(
            DAObject(
                identifier, category, original_size, tuple(own), layer, height, block_id, projection
            )
        )

    total = max(1, len(data["objects"]) + len(data["walls"]))
    contour_start = 65 if load_geometry else 25
    contour_span = 90 - contour_start
    contour_label = (
        "Models ready. Building placed object contours"
        if load_geometry
        else "Building object contours"
    )
    report(contour_start, contour_label)
    for index, obj in enumerate(data["objects"]):
        if index % 32 == 0:
            report(contour_start + int(contour_span * index / total), contour_label)
        instance = instances[obj["buildingBlockInstanceId"]]
        entry = metadata[instance["blockId"]]
        block, model = entry["block"], entry["model"]
        category = category_of(block)
        if category is None:
            continue
        low, high, render = _bounds(block, model, category)
        plane, base, scale = object_placement(instance, block)
        radius = max(high["x"] - low["x"], high["z"] - low["z"]) * abs(scale) / 2
        if radius <= 0:
            continue
        a, b, c, d, tx, tz = plane
        dx, dz = (low["x"] + high["x"]) / 2, (low["z"] + high["z"]) / 2
        cx, cy = a * dx + b * dz + tx, c * dx + d * dz + tz
        height_bounds = render or {
            "center": {"y": (low["y"] + high["y"]) / 2},
            "extents": {"y": (high["y"] - low["y"]) / 2},
        }
        center_height = finite(height_bounds.get("center", {}).get("y", 0), "model height")
        extent_height = finite(height_bounds.get("extents", {}).get("y", 0), "model height")
        bottom, top = sorted(
            (
                base + (center_height - extent_height) * scale,
                base + (center_height + extent_height) * scale,
            )
        )
        points = tuple(
            (
                (cx + radius * math.cos(2 * math.pi * i / 24)) * sx,
                (data["height"] - cy - radius * math.sin(2 * math.pi * i / 24)) * sy,
            )
            for i in range(24)
        )
        rings = None
        projection = None
        ground = ground_height(surface, instance, foundations[obj["foundationId"]])
        if instance["blockId"] in footprints:
            from dale.alchemist_mesh import outlines

            profile = footprints[instance["blockId"]]
            shape, ground = surface_projection(
                profile, surface, instance, foundations[obj["foundationId"]], block, base, scale
            )
            if shape is None or shape.is_empty:
                continue
            band = next(i for i, candidate in enumerate(profile.layers) if candidate is shape)
            projection = (
                band,
                (a * sx, b * sx, -c * sy, -d * sy, tx * sx, (data["height"] - tz) * sy),
                scale < 0,
            )
            foliage = category in ("tree", "bush")
            outline_key = (instance["blockId"], band, foliage, None if foliage else radius * 2)
            if outline_key not in outline_cache:
                if len(outline_cache) >= 512:
                    outline_cache.clear()
                outline_cache[outline_key] = outlines(
                    shape, radius * 2, foliage, alpha=True, separate_parts=True
                )
            model_rings = outline_cache[outline_key]
            rings = []
            for ring in model_rings:
                transformed = []
                for x, z in ring:
                    gx, gy = a * x + b * z + tx, c * x + d * z + tz
                    transformed.append(
                        (
                            finite(gx * sx, "contour coordinate"),
                            finite((data["height"] - gy) * sy, "contour coordinate"),
                        )
                    )
                rings.append(tuple(transformed))
        append(
            obj["id"],
            category,
            radius * 2,
            (*points, points[0]),
            bottom,
            top,
            foundations[obj["foundationId"]].get("layer", 0),
            ground,
            instance["blockId"],
            rings=rings,
            projection=projection,
        )
    for index, wall in enumerate(data["walls"]):
        if index % 32 == 0:
            report(
                contour_start + int(contour_span * (len(data["objects"]) + index) / total),
                contour_label,
            )
        foundation = foundations[wall["foundationId"]]
        instance = instances[wall["buildingBlockInstanceId"]]
        position = foundation.get("mapPosition", {})
        rotation = math.radians(finite(foundation.get("rotation", 0), "foundation rotation"))
        ends = [tuple(map(float, wall["wall"].get(k, "0 0").split())) for k in ("p1", "p2")]
        points = ends
        curvature = finite(wall["wall"].get("curvature", 0), "wall curvature")
        if curvature:
            # Circular DA corners use quarter-circle signed curvature. Keep their arc.
            (x1, y1), (x2, y2) = ends
            chord = math.hypot(x2 - x1, y2 - y1)
            if chord:
                theta = curvature * math.pi / 2
                distance = chord / (2 * math.tan(theta / 2))
                cx, cy = (
                    (x1 + x2) / 2 - (y2 - y1) / chord * distance,
                    (y1 + y2) / 2 + (x2 - x1) / chord * distance,
                )
                radius = math.hypot(x1 - cx, y1 - cy)
                start = math.atan2(y1 - cy, x1 - cx)
                points = [
                    (
                        cx + radius * math.cos(start + theta * i / 16),
                        cy + radius * math.sin(start + theta * i / 16),
                    )
                    for i in range(17)
                ]
                points[0], points[-1] = ends
        transformed = []
        for x, y in points:
            gx = position.get("x", 0) + x * math.cos(rotation) + y * math.sin(rotation)
            gy = position.get("y", 0) - x * math.sin(rotation) + y * math.cos(rotation)
            transformed.append((gx * sx, (data["height"] - gy) * sy))
        base = finite(instance.get("height", foundation.get("height", 0)), "wall elevation")
        entry = metadata[instance["blockId"]]
        low, high, render = _bounds(entry["block"], entry["model"], "wall")
        wall_height = (
            finite(render.get("center", {}).get("y", 0), "wall height")
            + finite(render.get("extents", {}).get("y", 0), "wall height")
            if render
            else high["y"]
        )
        wall_height *= abs(
            finite(instance.get("scale", 1), "wall scale")
            * finite(entry["block"].get("scale", 1), "wall model scale")
        )
        append(
            wall["id"],
            "wall",
            math.dist(*ends),
            transformed,
            base,
            base + wall_height,
            foundation.get("layer", 0),
            ground_height(surface, instance, foundation),
            instance["blockId"],
        )
    imported = DAData(
        name,
        raw,
        tuple(objects),
        json_walls=(session.alchemist.json_walls if session.alchemist else (None,) * 4),
        profiles=tuple(
            (key, tuple(layer.wkb for layer in profile.layers))
            for key, profile in footprints.items()
            if any(o.block_id == key and o.projection is not None for o in objects)
        ),
        alpha_projection=bool(load_geometry),
        separate_projection_parts=bool(load_geometry),
    )
    geometry = GeometryEdit(
        tuple(edges),
        lineage=tuple(records),
        ancestry=tuple(imported_ancestry),
        wall_styles=tuple(styles.items()),
        alchemist_slices=(-1, -1, -1, -1),
        alchemist_object_slices=(),
        alchemist_complexity=(),
        alchemist_transforms=(),
        alchemist_detail_frames=(),
        alchemist_empty_frames=(),
    )
    return imported, geometry


def surface_projection(profile, surface, instance, foundation, block, base, scale):
    """Sample local relief at the contour's real basal position, not model bounds center."""
    from dale.alchemist_mesh import layer_anchor

    ground = ground_height(surface, instance, foundation)
    index = 0 if scale > 0 else 9
    shape = profile.layers[index]
    a, b, c, d, tx, tz = object_placement(instance, block)[0]
    for _ in range(3):
        anchor = layer_anchor(shape) if shape is not None else None
        if anchor is not None:
            x, z = anchor
            located = dict(
                instance,
                center={
                    "x": a * x + b * z + tx,
                    "y": c * x + d * z + tz,
                },
            )
            ground = ground_height(surface, located, foundation)
        shape, selected = profile.at_surface(ground, base, scale)
        if selected is None or selected == index:
            break
        index = selected
    return shape, ground


def with_estimated_heights(session):
    """Fill optional measurements from embedded DAM and retained wall styles, without a library."""
    from dale.wall_styles import resolve_style

    data = session.alchemist
    if all(o.original_height_ft is not None for o in data.objects):
        return data
    raw = read_map(data.source)
    surface = read_terrain(raw)
    placements = {o["id"]: o for o in (*raw["objects"], *raw["walls"])}
    instances = {o["id"]: o for o in raw["buildingBlockInstances"]}
    foundations = {o["id"]: o for o in raw["foundations"]}
    geometry = session.geometry()
    styles = geometry_styles(geometry)
    for operation in (*session.operations, *session.future):
        for key, value in getattr(operation, "wall_styles", ()):
            styles.setdefault(key, value)
    grid = session.source.raw.get("grid")
    unit = (
        grid.get("distance", session.source.raw.get("gridDistance", 5))
        if isinstance(grid, dict)
        else session.source.raw.get("gridDistance", 5)
    )
    unit = finite(unit, "scene distance")
    if unit <= 0:
        raise ValueError("Scene grid distance must be positive.")
    objects = []
    for obj in data.objects:
        placement = placements.get(obj.id)
        height = obj.original_height_ft
        if height is None and placement:
            instance = instances[placement["buildingBlockInstanceId"]]
            ground = ground_height(surface, instance, foundations[placement["foundationId"]])
            tops = []
            for root in obj.roots:
                for style in styles.get(root, ()):
                    wall = resolve_style(style, {})
                    top = wall.get("flags", {}).get("wall-height", {}).get("top")
                    if top is not None:
                        tops.append(finite(top, "object height") / unit)
            if tops:
                height = finite(
                    max(0, (max(tops) - ground) * FEET_PER_DA_CELL), "height above surface"
                )
        objects.append(replace(obj, original_height_ft=height))
    return replace(data, objects=tuple(objects))


def memberships(data, geometry):
    from dale.object_index import find

    cached = find(data, geometry)
    if cached is not None:
        return cached.owned
    return _memberships(_OwnershipKey(data.objects, geometry.lineage, geometry.ancestry))


class _OwnershipKey:
    """Retain immutable inputs while avoiding a full provenance hash on cache hits."""

    __slots__ = ("objects", "lineage", "ancestry")

    def __init__(self, objects, lineage, ancestry):
        self.objects, self.lineage, self.ancestry = objects, lineage, ancestry

    def __hash__(self):
        return hash((id(self.objects), id(self.lineage), id(self.ancestry)))

    def __eq__(self, other):
        if not isinstance(other, _OwnershipKey):
            return NotImplemented
        return (
            self.objects is other.objects
            and self.lineage is other.lineage
            and self.ancestry is other.ancestry
        )


@lru_cache(maxsize=8)
def _memberships(key):
    objects, lineage, ancestry = key.objects, key.lineage, key.ancestry
    roots = {root: obj.id for obj in objects for root in obj.roots}
    catalog = {r.id: r for r in (*ancestry, *lineage)}
    memo, visiting = {}, set()

    def owners(identifier):
        if identifier in memo:
            return memo[identifier]
        if identifier in roots:
            return frozenset((roots[identifier],))
        record = catalog.get(identifier)
        if record is None or record.origin == "editor" or identifier in visiting:
            return frozenset()
        visiting.add(identifier)
        result = frozenset(o for p in record.parents for o in owners(p))
        visiting.remove(identifier)
        memo[identifier] = result
        return result

    try:
        return tuple(owners(r.id) for r in lineage)
    finally:
        # Break the recursive closure, which otherwise retains the temporary catalog.
        owners = None


def same_type_lines(data, geometry, selected):
    """Expand selected visible object parts to visible instances of their exact block IDs."""
    selected = set(selected)
    owned = memberships(data, geometry)
    types = {o.id: o.block_id for o in data.objects}
    wanted = {
        types[o]
        for record, owners in zip(geometry.lineage, owned, strict=True)
        if record.id in selected
        for o in owners
        if types[o] is not None
    }
    if not wanted:
        return ()
    return tuple(
        record.id
        for record, owners in zip(geometry.lineage, owned, strict=True)
        if any(types[o] in wanted for o in owners)
    )


def register_pasted_objects(session, before, after, clipboard, source_data=None):
    """A pasted object owns its new roots, independently of originals or contact ancestry."""
    if session.alchemist is None:
        return after
    source_data = source_data or session.alchemist
    by_id = {o.id: o for o in source_data.objects}
    source_owners = dict(
        zip(
            (r.id for r in clipboard.geometry.lineage),
            memberships(source_data, clipboard.geometry),
            strict=True,
        )
    )
    copied = after.lineage[len(before.lineage) :]
    groups = {}
    for old, new in zip(clipboard.records, copied, strict=True):
        groups.setdefault(source_owners.get(old.id, frozenset()), []).append(new.id)
    additions, new_groups = [], {}
    for owners, roots in groups.items():
        identifier = uuid4().hex
        references = [by_id[o] for o in sorted(owners)]
        if references:
            category = (
                references[0].category if len({o.category for o in references}) == 1 else "wall"
            )
            size = max(o.original_size for o in references)
            floor = references[0].layer
            height = (
                max(o.original_height_ft for o in references)
                if all(o.original_height_ft is not None for o in references)
                else None
            )
        else:
            category, floor = "wall", 0
            height = None
            points = [
                p
                for r, edge in zip(after.lineage, after.walls, strict=True)
                if r.id in roots
                for p in edge
            ]
            size = max(max(p[i] for p in points) - min(p[i] for p in points) for i in (0, 1)) / max(
                session.source.cell_pixels, 1
            )
        types = {o.block_id for o in references}
        block_id = next(iter(types)) if len(types) == 1 else None
        additions.append(
            DAObject(identifier, category, size, tuple(roots), floor, height, block_id)
        )
        new_groups.update((root, f"da:{identifier}") for root in roots)
    session.alchemist = replace(session.alchemist, objects=(*session.alchemist.objects, *additions))
    return replace(
        after,
        lineage=tuple(
            replace(r, connection_group=new_groups[r.id]) if r.id in new_groups else r
            for r in after.lineage
        ),
    )


def height_layers(source, geometry, documents, data):
    """Keep ordinary height bands and DA floors without a band for every plant tip."""
    from dale.layer_repair import wall_intervals
    from dale.source_editing import SourceLayer, source_layers

    owned = memberships(data, geometry)
    regular_indices = tuple(i for i, own in enumerate(owned) if not own)
    regular = layer_geometry(geometry, regular_indices)
    choices = [SourceLayer("all", "all", None, None, tuple(range(len(owned))))]
    intervals, _ = wall_intervals(source, geometry, documents)
    for layer in source_layers(source, regular, documents):
        if layer.kind == "all":
            continue
        lower = -math.inf if layer.bottom is None else layer.bottom
        upper = math.inf if layer.top is None else layer.top
        da_indices = tuple(
            i
            for i, own in enumerate(owned)
            if own and intervals[i] and intervals[i][0] < upper and intervals[i][1] > lower
        )
        choices.append(
            replace(layer, indices=tuple(regular_indices[i] for i in layer.indices) + da_indices)
        )
    by_floor = {}
    for obj in data.objects:
        by_floor.setdefault(obj.layer, set()).add(obj.id)
    for floor, identifiers in sorted(by_floor.items()):
        indices = tuple(i for i, own in enumerate(owned) if own & identifiers)
        choices.append(
            SourceLayer(f"da-layer:{floor}", "alchemist", None, None, (*regular_indices, *indices))
        )
    return tuple(choices)


def scoped_geometry(session, geometry=None, scope="combined", *, category=None):
    geometry = geometry or session.geometry()
    data = session.alchemist
    if not data:
        return geometry
    from dale.object_index import object_index

    index = object_index(data, geometry)
    enabled = {
        o.id
        for o in data.objects
        if (o.category == category if category else data.settings[CATEGORIES.index(o.category)][0])
        and o.original_size >= data.settings[CATEGORIES.index(o.category)][1]
        and (
            data.minimum_heights_ft[CATEGORIES.index(o.category)] == 0
            or (
                o.original_height_ft is not None
                and (o.original_height_ft + 1e-6)
                >= data.minimum_heights_ft[CATEGORIES.index(o.category)]
            )
        )
    }
    if scope != "alchemist_all":
        from dale.alchemist_thinning import hidden_objects

        enabled.difference_update(hidden_objects(session))
    return index.subset(index.visible(enabled, scope, category))


def export_session(session, include_alchemist=True, *, only_alchemist=False):
    if not session.alchemist:
        if only_alchemist:
            from dale.source_editing import layer_geometry

            geometry = layer_geometry(session.geometry(), ())
            return replace(session, operations=[*session.operations, geometry], future=[])
        return session
    geometry = scoped_geometry(
        session,
        scope=("alchemist" if only_alchemist else "combined" if include_alchemist else "regular"),
    )
    if include_alchemist:
        categories = {obj.id: obj.category for obj in session.alchemist.objects}
        styles = geometry_styles(geometry)
        from dale.alchemist_export import category_settings

        presets = {
            category: property_style(category_settings(session.alchemist, category))
            for category in CATEGORIES
        }
        for record, owners in zip(
            geometry.lineage, memberships(session.alchemist, geometry), strict=True
        ):
            if owners:
                kinds = {categories[owner] for owner in owners}
                styles[record.id] = tuple(presets[kind] for kind in CATEGORIES if kind in kinds)
        geometry = replace(geometry, wall_styles=tuple(styles.items()))
    return replace(session, operations=[*session.operations, geometry], future=[], alchemist=None)


def transform_individual_objects(session, identifiers, *, scale=1, angle=0, centers=None):
    """Transform exact selected IDs around each object's current bounds, preserving all others."""
    scale, angle = finite(scale, "scale", 100), finite(angle, "rotation")
    if scale <= 0:
        raise ValueError("Dungeon Alchemist scale must be positive.")
    geometry = session.geometry()
    from dale.object_index import transform_objects

    return transform_objects(session.alchemist, geometry, identifiers, scale, angle, centers)


def scale_category(session, category, factor, progress=None, *, object_ids=None):
    """Resize each current object about its current bounds, independent of source size."""
    factor = finite(factor, "scale", 100)
    if factor <= 0:
        raise ValueError("Dungeon Alchemist scale must be positive.")
    geometry = session.geometry()
    from dale.object_index import scale_objects

    wanted = {o.id for o in session.alchemist.objects if o.category == category}
    if object_ids is not None:
        wanted.intersection_update(object_ids)
    return scale_objects(session.alchemist, geometry, wanted, factor, progress)
