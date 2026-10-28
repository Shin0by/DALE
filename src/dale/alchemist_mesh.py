"""Bounded, local-only model readers and cached top-view obstacle silhouettes."""

from __future__ import annotations

import io
import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from shapely import LineString, Polygon, build_area, concave_hull, from_wkb, to_wkb, union_all
from shapely.errors import GEOSException

MAX_VERTICES = 250000
MAX_TRIANGLES = 250000
MAX_MODEL_BYTES = 128 * 1024 * 1024
FORMAT = 5
PREVIEW_FORMAT = 6


def transform(position=(0, 0, 0), rotation=(0, 0, 0, 1), scale=(1, 1, 1)):
    x, y, z, w = rotation
    length = math.sqrt(x * x + y * y + z * z + w * w)
    if not math.isfinite(length) or length < 1e-12:
        raise ValueError("Invalid model rotation.")
    x, y, z, w = (v / length for v in (x, y, z, w))
    result = np.eye(4)
    result[:3, :3] = np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    ) @ np.diag(scale)
    result[:3, 3] = position
    if not np.isfinite(result).all() or np.abs(result).max() > 1e6:
        raise ValueError("Invalid model transform.")
    return result


def transformed(vertices, matrix):
    vertices = np.asarray(vertices, dtype=np.float64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) > MAX_VERTICES:
        raise ValueError("Unsupported model vertex count.")
    result = vertices @ matrix[:3, :3].T + matrix[:3, 3]
    if not np.isfinite(result).all() or np.abs(result).max(initial=0) > 1e6:
        raise ValueError("Invalid model coordinates.")
    return result


def project(meshes, ceiling=None, floor=None, *, allow_empty=False, check_cancel=None):
    """Project clipped triangle faces and closed cut caps of a horizontal model band."""
    polygons, caps = [], {level: [] for level in (floor, ceiling) if level is not None}
    alpha_meshes = []
    total = 0
    for mesh in meshes:
        if check_cancel:
            check_cancel()
        vertices, triangles = mesh[:2]
        vertices = np.asarray(vertices, dtype=float)
        indices = np.asarray(triangles)
        total += len(indices)
        if (
            total > MAX_TRIANGLES
            or indices.ndim != 2
            or indices.shape[1] != 3
            or indices.dtype.kind not in "iu"
            or np.any(indices < 0)
            or np.any(indices >= len(vertices))
        ):
            raise ValueError("Invalid or oversized model triangles.")
        if len(mesh) > 3 and mesh[3] is not None:
            alpha_meshes.append((vertices, indices, mesh[2], mesh[3]))
            continue
        heights = vertices[indices, 1]
        keep = np.ones(len(indices), dtype=bool)
        if floor is not None:
            keep &= heights.max(axis=1) >= floor
        if ceiling is not None:
            keep &= heights.min(axis=1) <= ceiling
        for face_index, face in enumerate(indices[keep]):
            if check_cancel and face_index % 256 == 0:
                check_cancel()
            original = [vertices[i] for i in face]
            for level, lines in caps.items():
                hits = []
                for a, b in zip(original, original[1:] + original[:1], strict=True):
                    if (a[1] <= level <= b[1] or b[1] <= level <= a[1]) and a[1] != b[1]:
                        p = a + (b - a) * ((level - a[1]) / (b[1] - a[1]))
                        hit = (round(float(p[0]), 6), round(float(p[2]), 6))
                        if hit not in hits:
                            hits.append(hit)
                if len(hits) == 2 and hits[0] != hits[1]:
                    lines.append(LineString(hits))
            points = original
            for level, below in ((ceiling, True), (floor, False)):
                if level is None or not points:
                    continue
                clipped = []
                for a, b in zip(points, points[1:] + points[:1], strict=True):
                    inside_a = a[1] <= level if below else a[1] >= level
                    inside_b = b[1] <= level if below else b[1] >= level
                    if inside_a:
                        clipped.append(a)
                    if inside_a != inside_b:
                        clipped.append(a + (b - a) * ((level - a[1]) / (b[1] - a[1])))
                points = clipped
            if len(points) >= 3:
                polygon = Polygon([(p[0], p[2]) for p in points])
                if polygon.area > 1e-12 and polygon.is_valid:
                    polygons.append(polygon)
    for lines in caps.values():
        if check_cancel:
            check_cancel()
        if lines:
            cap = build_area(union_all(lines, grid_size=1e-6))
            if not cap.is_empty:
                polygons.append(cap)
    if alpha_meshes:
        from dale.alchemist_alpha import project_alpha

        shape = project_alpha(alpha_meshes, floor, ceiling, check_cancel)
        if not shape.is_empty:
            polygons.append(shape)
    if not polygons:
        if allow_empty:
            return Polygon()
        raise ValueError("No usable model projection.")
    if check_cancel:
        check_cancel()
    result = union_all(polygons, grid_size=1e-7).simplify(1e-6, preserve_topology=True)
    if check_cancel:
        check_cancel()
    if result.is_empty or result.geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError("No usable model projection.")
    return result


@dataclass(frozen=True)
class ModelProfile:
    low: float
    high: float
    layers: tuple

    def at_surface(self, ground, elevation, scale):
        if not scale or not all(math.isfinite(v) for v in (ground, elevation, scale)):
            raise ValueError("Invalid model placement.")
        bottom, top = sorted((elevation + self.low * scale, elevation + self.high * scale))
        if ground > top + 1e-7:
            return None, None
        local = (ground - elevation) / scale
        fraction = (local - self.low) / (self.high - self.low)
        index = max(0, min(9, math.floor(fraction * 10 + 1e-9)))
        return self.layers[index], index


def build_profile(meshes, report=None, *, check_cancel=None):
    if not meshes:
        raise ValueError("No usable model geometry.")
    low = min(float(m[0][:, 1].min()) for m in meshes if len(m[0]))
    high = max(float(m[0][:, 1].max()) for m in meshes if len(m[0]))
    if high - low <= 1e-7:
        # Flat ground-cover models have the same footprint at every band.
        shape = exterior_shape(project(meshes, check_cancel=check_cancel))
        return ModelProfile(low, low + 1e-6, (shape,) * 10)
    layers = []
    for index in range(10):
        shape = project(
            meshes,
            low + (high - low) * (index + 1) / 10,
            low + (high - low) * index / 10,
            allow_empty=True,
            check_cancel=check_cancel,
        )
        shape = exterior_shape(shape)
        layers.append(shape)
        if report:
            report(index, shape)
    return ModelProfile(low, high, tuple(layers))


def exterior_shape(shape):
    """DA obstacles follow external boundaries; enclosed transparent holes are irrelevant."""
    if shape.is_empty:
        return shape
    parts = [shape] if shape.geom_type == "Polygon" else shape.geoms
    return union_all([Polygon(part.exterior) for part in parts])


def layer_anchor(shape):
    if shape.is_empty:
        return None
    parts = [shape] if shape.geom_type == "Polygon" else shape.geoms
    center = max(parts, key=lambda p: p.area).centroid
    return center.x, center.y


def outlines(shape, diameter, foliage=False, *, alpha=False, separate_parts=False):
    """Use the circle's size budget, preserving topology and visible concavities."""
    if separate_parts:
        return separate_outlines(shape, foliage)
    budget = (
        4
        if diameter <= 0.5
        else 6
        if diameter <= 1
        else 8
        if diameter <= 2
        else (min(4096, 8 + 2 * math.ceil((diameter - 2) / 2.5)))
    )
    width = max(shape.bounds[2] - shape.bounds[0], shape.bounds[3] - shape.bounds[1])
    foliage_width = width
    feature = width * min(0.04, 0.025 / max(diameter, 0.25))
    original_parts = [shape] if shape.geom_type == "Polygon" else list(shape.geoms)
    complexity = sum(
        len(p.exterior.coords) + sum(len(h.coords) for h in p.interiors) for p in original_parts
    )
    preserve_alpha = foliage and alpha
    if complexity > (32 if preserve_alpha else budget * 4):
        if foliage:
            # Trace the outer envelope of visible foliage fragments, without internal
            # leaf gaps. Alpha still determines the actual tips and outer notches.
            shape = concave_hull(shape, ratio=0.10 if alpha else 0.25, allow_holes=False)
        # Resolve sub-grid leaf gaps before reducing vertices, keeping meaningful openings.
        radius = width * 0.01 if preserve_alpha else feature
        reduced = shape.buffer(radius, quad_segs=2).buffer(-radius, quad_segs=2)
        if not reduced.is_empty and reduced.is_valid:
            shape = reduced
    parts = [shape] if shape.geom_type == "Polygon" else list(shape.geoms)
    result = []
    for part in parts:
        minimum_area = (
            max(shape.area * 0.005, (foliage_width * 0.01) ** 2)
            if preserve_alpha
            else shape.area * 1e-6
        )
        if part.area < minimum_area:
            continue
        # Projected triangle seams can leave hundreds of subpixel numerical pinholes.
        part = Polygon(
            part.exterior,
            []
            if alpha
            else [
                ring
                for ring in part.interiors
                if Polygon(ring).area
                >= max(
                    1e-10,
                    part.area * 1e-5,
                    minimum_area if preserve_alpha else feature * feature * 4,
                )
            ],
        )
        # Never erase a substantial notch merely to meet the nominal vertex budget.
        width = max(part.bounds[2] - part.bounds[0], part.bounds[3] - part.bounds[1])
        tolerance = width * 0.001
        simplified = part
        if preserve_alpha:
            # One model-relative tolerance, including small islands; do not recreate
            # every raster stair-step or bridge broad transparent margins with a hull.
            simplified = part.simplify(foliage_width * 0.01, preserve_topology=True)
        while (
            not preserve_alpha
            and len(simplified.exterior.coords) - 1 > budget
            and tolerance <= width * 0.03
        ):
            simplified = part.simplify(tolerance, preserve_topology=True)
            tolerance *= 1.5
        result.append(tuple(simplified.exterior.coords))
        if not alpha:
            result.extend(tuple(r.coords) for r in simplified.interiors)
    if sum(len(r) for r in result) > 100000:
        raise ValueError("Model silhouette exceeds the supported size.")
    return tuple(result)


def separate_outlines(shape, foliage=False):
    """Simplify real outer boundaries together, without bridging gaps or closing necks."""
    if shape.is_empty:
        return ()
    shape = exterior_shape(shape)
    width = max(shape.bounds[2] - shape.bounds[0], shape.bounds[3] - shape.bounds[1])
    parts = [shape] if shape.geom_type == "Polygon" else shape.geoms
    minimum_area = max(shape.area * 0.005, (width * 0.01) ** 2) if foliage else shape.area * 1e-6
    retained = [part for part in parts if part.area >= minimum_area]
    if not retained:
        return ()
    # GEOS topology-preserving simplification sees all components at once, so
    # simplifying one island cannot cause it to cross or merge with its neighbour.
    simplified = union_all(retained).simplify(width * 0.01, preserve_topology=True)
    parts = [simplified] if simplified.geom_type == "Polygon" else simplified.geoms
    result = tuple(tuple(part.exterior.coords) for part in parts)
    if sum(len(ring) for ring in result) > 100000:
        raise ValueError("Model silhouette exceeds the supported size.")
    return result


def _release_environment(environment):
    """Dispose only our read-only UnityPy files and break their ownership cycles."""
    if environment is None:
        return
    seen = set()
    for item in (*environment.files.values(), *environment.cabs.values()):
        reader = getattr(item, "reader", item)
        if id(reader) not in seen:
            seen.add(id(reader))
            dispose = getattr(reader, "dispose", None)
            if dispose is not None:
                dispose()
        for name in ("objects", "_cache"):
            value = getattr(item, name, None)
            if value is not None:
                value.clear()
    environment.files.clear()
    environment.cabs.clear()


class NativeModels:
    """Resolve ModelSource IDs explicitly, then traverse the referenced model hierarchy."""

    def __init__(self, executable):
        import UnityPy

        root = Path(executable).parent / "Dungeon Alchemist_Data"
        self.root = root
        self.environment = UnityPy.load(str(root / "resources.assets"))
        scripts = UnityPy.load(str(root / "globalgamemanagers.assets"))
        script_ids = set()
        try:
            for obj in scripts.objects:
                if obj.type.name == "MonoScript":
                    value = obj.read()
                    if (value.m_ClassName, value.m_Namespace) == (
                        "ModelSource",
                        "DungeonAlchemist.Backend",
                    ):
                        script_ids.add(obj.path_id)
        finally:
            _release_environment(scripts)
        self.models = {}
        for obj in self.environment.objects:
            if obj.type.name != "MonoBehaviour" or obj.byte_size > 4096:
                continue
            raw = obj.get_raw_data()
            # Explicit observed little-endian ModelSource layout, fail closed on changes.
            if (
                len(raw) < 52
                or struct.unpack_from("<iq", raw, 16)
                not in ((1, identifier) for identifier in script_ids)
                or struct.unpack_from("<I", raw, 28)[0] != 0
            ):
                continue
            file_id, transform_id = struct.unpack_from("<iq", raw, 32)
            offset = 44
            values = []
            try:
                for _ in range(2):
                    size = struct.unpack_from("<I", raw, offset)[0]
                    offset += 4
                    if not 1 <= size <= 512 or offset + size > len(raw):
                        raise ValueError("Invalid model source.")
                    values.append(raw[offset : offset + size].decode("utf-8"))
                    offset = (offset + size + 3) & ~3
                if offset == len(raw) and file_id == 0 and values[1].startswith("NATIVE#"):
                    self.models[values[1]] = obj.assets_file.objects[transform_id]
            except (ValueError, KeyError, struct.error):
                continue

    def meshes(self, identifier):
        from UnityPy.helpers.MeshHelper import MeshHandler

        if identifier not in self.models:
            raise ValueError("Local native model is unavailable.")
        result, seen, alpha_cache = [], set(), {}

        def walk(reader, parent, depth=0):
            if depth > 64 or reader.path_id in seen or len(seen) > 4096:
                raise ValueError("Unsupported model hierarchy.")
            seen.add(reader.path_id)
            node = reader.read()
            game = node.m_GameObject.deref().read()
            if not game.m_IsActive:
                return

            def xyz(value):
                return value.x, value.y, value.z

            q = node.m_LocalRotation
            matrix = parent @ transform(
                xyz(node.m_LocalPosition), (q.x, q.y, q.z, q.w), xyz(node.m_LocalScale)
            )
            components = [c.component.deref() for c in game.m_Component]
            renderers = [c.read() for c in components if c.type.name == "MeshRenderer"]
            if any(c.type.name == "SkinnedMeshRenderer" for c in components):
                raise ValueError("Animated model projection is unavailable.")
            if any(r.m_Enabled for r in renderers):
                for component in components:
                    if component.type.name == "MeshFilter":
                        mesh = component.read().m_Mesh.deref().read()
                        handler = MeshHandler(mesh)
                        handler.process()
                        vertices = transformed(handler.m_Vertices, matrix)
                        for index, faces in enumerate(handler.get_triangles()):
                            color = (0.65, 0.65, 0.65)
                            material = None
                            try:
                                material = renderers[0].m_Materials[index].deref().read()
                                colors = dict(material.m_SavedProperties.m_Colors)
                                tint = colors.get("_BaseColor", colors.get("_Color"))
                                if tint:
                                    color = (tint.r, tint.g, tint.b)
                            except (IndexError, KeyError, ValueError, AttributeError):
                                pass
                            from dale.alchemist_materials import native_surface

                            surface = native_surface(
                                material, handler.m_UV0, self.root, alpha_cache
                            )
                            result.append((vertices, faces, color, surface))
            for child in node.m_Children:
                walk(child.deref(), matrix, depth + 1)

        try:
            walk(self.models[identifier], np.eye(4))
            return result
        finally:
            # Recursive closures must not keep decoded meshes/the reader alive.
            walk = None

    def close(self):
        if hasattr(self, "models"):
            self.models.clear()
        _release_environment(getattr(self, "environment", None))
        self.environment = None


def glb_meshes(path, offset=None, scale=1):
    """Read embedded glTF2 meshes and alpha only; no URI or network resolution."""
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_MODEL_BYTES + 1)
    if len(raw) > MAX_MODEL_BYTES or len(raw) < 20:
        raise ValueError("Unsupported GLB size.")
    if struct.unpack_from("<4sII", raw) != (b"glTF", 2, len(raw)):
        raise ValueError("Invalid GLB header.")
    chunks, cursor = {}, 12
    while cursor < len(raw):
        size, kind = struct.unpack_from("<II", raw, cursor)
        cursor += 8
        if cursor + size > len(raw) or kind in chunks:
            raise ValueError("Invalid GLB chunk.")
        chunks[kind] = raw[cursor : cursor + size]
        cursor += size
    document, binary = json.loads(chunks[0x4E4F534A]), chunks[0x004E4942]
    if document.get("extensionsRequired"):
        raise ValueError("Unsupported GLB extension.")
    if len(document.get("buffers", [])) != 1 or document["buffers"][0].get("uri"):
        raise ValueError("External model buffers are unsupported.")

    def accessor(index, positions=False, width=1):
        item = document["accessors"][index]
        if item.get("sparse") or (item.get("normalized") and width != 2):
            raise ValueError("Unsupported model accessor.")
        count = item["count"]
        width = 3 if positions else width
        dtype = {5126: "<f4", 5125: "<u4", 5123: "<u2", 5121: "u1"}[item["componentType"]]
        if (
            item["type"] != {1: "SCALAR", 2: "VEC2", 3: "VEC3"}[width]
            or (positions and item["componentType"] != 5126)
            or not 0 < count <= (MAX_VERTICES if positions else MAX_TRIANGLES * 3)
        ):
            raise ValueError("Unsupported model accessor size.")
        view = document["bufferViews"][item["bufferView"]]
        unit = np.dtype(dtype).itemsize
        stride = view.get("byteStride", width * unit)
        start = view.get("byteOffset", 0) + item.get("byteOffset", 0)
        end = start + (count - 1) * stride + width * unit
        if (
            view.get("buffer", 0) != 0
            or stride < width * unit
            or start < 0
            or end > len(binary)
            or end > view.get("byteOffset", 0) + view["byteLength"]
        ):
            raise ValueError("Invalid model buffer range.")
        values = np.ndarray(
            (count, width), dtype, buffer=binary, offset=start, strides=(stride, unit)
        ).copy()
        if item.get("normalized"):
            if item["componentType"] not in (5121, 5123):
                raise ValueError("Unsupported normalized texture coordinates.")
            values = values.astype(float) / np.iinfo(dtype).max
        return values

    result, seen, alpha_cache = [], set(), {}

    def walk(index, parent, depth=0):
        if depth > 64 or index in seen or len(seen) > 4096:
            raise ValueError("Unsupported model hierarchy.")
        seen.add(index)
        node = document["nodes"][index]
        if "skin" in node:
            raise ValueError("Animated model projection is unavailable.")
        matrix = parent @ (
            np.array(node["matrix"]).reshape(4, 4).T
            if "matrix" in node
            else transform(
                node.get("translation", (0, 0, 0)),
                node.get("rotation", (0, 0, 0, 1)),
                node.get("scale", (1, 1, 1)),
            )
        )
        if "mesh" in node:
            for primitive in document["meshes"][node["mesh"]]["primitives"]:
                if primitive.get("mode", 4) != 4 or primitive.get("targets"):
                    raise ValueError("Unsupported model primitive.")
                vertices = transformed(accessor(primitive["attributes"]["POSITION"], True), matrix)
                indices = (
                    accessor(primitive["indices"]).ravel()
                    if "indices" in primitive
                    else np.arange(len(vertices))
                )
                material = (
                    document["materials"][primitive["material"]] if "material" in primitive else {}
                )
                color = material.get("pbrMetallicRoughness", {}).get(
                    "baseColorFactor", (0.65, 0.65, 0.65, 1)
                )[:3]
                from dale.alchemist_materials import glb_surface

                surface = glb_surface(
                    document, binary, material, primitive["attributes"], accessor, alpha_cache
                )
                result.append((vertices, indices.reshape(-1, 3), color, surface))
        for child in node.get("children", []):
            walk(child, matrix, depth + 1)

    # glTF right-handed X is reflected by the DA Unity importer.
    offset = offset or {}
    root = transform(tuple(offset.get(k, 0) for k in ("x", "y", "z")), scale=(-scale, scale, scale))
    try:
        for index in document["scenes"][document.get("scene", 0)]["nodes"]:
            walk(index, root)
        return result
    finally:
        walk = None


def cached_profile(connection, key):
    row = connection.execute(
        "SELECT payload FROM model_profiles WHERE id=? AND format=?", (key, FORMAT)
    ).fetchone()
    if row and len(row[0]) <= 16 * 1024 * 1024:
        try:
            value = json.loads(row[0])
            low, high = value["low"], value["high"]
            if (
                not all(
                    type(v) in (int, float) and math.isfinite(v) and abs(v) <= 1e6
                    for v in (low, high)
                )
                or high <= low
                or len(value["layers"]) != 10
            ):
                return None
            layers = tuple(from_wkb(bytes.fromhex(raw)) for raw in value["layers"])
            if all(
                s.geom_type in ("Polygon", "MultiPolygon")
                and s.is_valid
                and (s.is_empty or np.isfinite(s.bounds).all())
                for s in layers
            ):
                return ModelProfile(low, high, layers)
        except (ValueError, TypeError, KeyError, GEOSException):
            pass
    return None


def save_profile(connection, key, profile):
    payload = json.dumps(
        dict(low=profile.low, high=profile.high, layers=[to_wkb(s).hex() for s in profile.layers])
    )
    if len(payload) > 16 * 1024 * 1024:
        raise ValueError("Model profile exceeds the supported size.")
    connection.execute(
        "INSERT OR REPLACE INTO model_profiles VALUES (?, ?, ?)", (key, FORMAT, payload)
    )


def preview_image(shape, anchor=None, meshes=(), appearance=None, foliage=False):
    """Small worker-owned raster; no Qt objects or source textures cross threads."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (384, 256), "black")
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = shape.bounds
    if meshes:
        x0 = min(x0, *(float(m[0][:, 0].min()) for m in meshes if len(m[0])))
        x1 = max(x1, *(float(m[0][:, 0].max()) for m in meshes if len(m[0])))
        y0 = min(y0, *(float(m[0][:, 2].min()) for m in meshes if len(m[0])))
        y1 = max(y1, *(float(m[0][:, 2].max()) for m in meshes if len(m[0])))
    factor = min(352 / max(x1 - x0, 1e-8), 224 / max(y1 - y0, 1e-8))

    def point(p):
        return 192 + (p[0] - (x0 + x1) / 2) * factor, 128 - (p[1] - (y0 + y1) / 2) * factor

    parts = [shape] if shape.geom_type == "Polygon" else shape.geoms
    for part in parts:
        draw.polygon([point(p) for p in part.exterior.coords], fill="white")
        for hole in part.interiors:
            draw.polygon([point(p) for p in hole.coords], fill="black")
    if meshes:
        layer = appearance.get("layer") if appearance is not None else None
        if layer is None:
            # Small painter-sorted preview, not a renderer or a source of export geometry.
            layer = Image.new("RGBA", image.size)
            painter = ImageDraw.Draw(layer)
            faces = []
            light = np.array((-0.35, 0.9, -0.25))
            light /= np.linalg.norm(light)
            for mesh in meshes:
                if len(mesh) > 3 and mesh[3] is not None:
                    # Keep the corrected alpha mask visible instead of covering it with cards.
                    continue
                vertices, triangles = mesh[:2]
                base = np.asarray(mesh[2] if len(mesh) > 2 else (0.65, 0.65, 0.65))
                for face in triangles:
                    a, b, c = (vertices[i] for i in face)
                    normal = np.cross(b - a, c - a)
                    length = np.linalg.norm(normal)
                    if length < 1e-10:
                        continue
                    if normal[1] < 0:
                        normal = -normal
                    shade = 0.3 + 0.7 * max(0, float(normal @ light) / length)
                    color = tuple(int(v) for v in np.clip(base * shade * 255, 0, 255)) + (150,)
                    faces.append(
                        ((a[1] + b[1] + c[1]) / 3, [point((p[0], p[2])) for p in (a, b, c)], color)
                    )
            for _, points, color in sorted(faces, key=lambda f: f[0]):
                painter.polygon(points, fill=color)
            if appearance is not None:
                appearance["layer"] = layer
        image = Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB")
        draw = ImageDraw.Draw(image)
    for ring in outlines(shape, max(x1 - x0, y1 - y0), foliage, alpha=True, separate_parts=True):
        draw.line([point(p) for p in ring], fill=(0, 190, 210), width=1)
        for p in ring[:-1]:
            x, y = point(p)
            draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=(0, 190, 210))
    if anchor:
        x, y = point(anchor)
        draw.line((x - 6, y, x + 6, y), fill=(255, 180, 0), width=2)
        draw.line((x, y - 6, x, y + 6), fill=(255, 180, 0), width=2)
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()
