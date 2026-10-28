"""Source-coordinate RGBA cut transforms shared by previews, exact bounds and PNGs."""

import math
from collections import OrderedDict
from dataclasses import replace
from functools import lru_cache

from PIL import Image, ImageChops
from shapely import from_wkb
from shapely.affinity import affine_transform

from dale.session import ContourMask, RasterTransform, Stroke


@lru_cache(maxsize=8)
def region_entries(geometry, polygons, transforms):
    """Independent Raster objects replace cells by identity, never polygonize overlaps."""
    from dale.region_groups import cell_references

    entries = dict(zip(cell_references(geometry, polygons), polygons, strict=True))
    for transform in transforms:
        for i, (cell, data) in enumerate(zip(transform.cells, transform.regions, strict=True)):
            matrix = transform.parts[i][1] if transform.parts else transform.matrix
            entries[cell] = affine_transform(area_of(data), matrix)
    return tuple(entries.items())


def group_cells(group, entries):
    if group.cells is not None:
        return set(group.cells) & {cell for cell, _ in entries}
    return {
        cell
        for cell, _ in entries
        if set(cell.shell).issubset(set(group.lines) - set(group.excluded))
    }


def assign_cells(group, entries, selected, add):
    selected = set(selected)
    cells = group_cells(group, entries)
    cells = cells | selected if add else cells - selected
    members = {i for cell in cells for ring in (cell.shell, *cell.holes) for i in ring}
    return replace(
        group,
        cells=tuple(sorted(cells)),
        lines=tuple(sorted(members)),
        excluded=tuple(sorted((set(group.excluded) | set(group.lines)) - members)),
    )


@lru_cache(maxsize=128)
def area_of(data):
    return from_wkb(data)


def affine_matrix(pivot, dx=0, dy=0, scale=1, angle=0):
    radians = math.radians(angle)
    a, b = scale * math.cos(radians), -scale * math.sin(radians)
    d, e = -b, a
    x, y = pivot
    return a, b, d, e, x - a * x - b * y + dx, y - d * x - e * y + dy


def image_reader(image, native_size):
    def read(box, size):
        sx, sy = image.width / native_size[0], image.height / native_size[1]
        return image.convert("RGBA").transform(
            size,
            Image.Transform.EXTENT,
            (box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy),
            Image.Resampling.BICUBIC,
        )

    return read


def crop_reader(source, native_size):
    """Adapt a native disk source without retaining an entire decoded RGBA image."""

    def read(box, size):
        bounds = (
            max(0, math.floor(box[0])),
            max(0, math.floor(box[1])),
            min(native_size[0], math.ceil(box[2])),
            min(native_size[1], math.ceil(box[3])),
        )
        if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
            return Image.new("RGBA", size)
        fx = fy = 1
        if (
            hasattr(source, "sample_crop")
            and (bounds[2] - bounds[0]) * (bounds[3] - bounds[1]) > 4 * size[0] * size[1]
        ):
            sampled_size = (
                max(1, math.ceil((bounds[2] - bounds[0]) * size[0] / (box[2] - box[0]))),
                max(1, math.ceil((bounds[3] - bounds[1]) * size[1] / (box[3] - box[1]))),
            )
            image = source.sample_crop(bounds, sampled_size)
            fx, fy = image.width / (bounds[2] - bounds[0]), image.height / (bounds[3] - bounds[1])
        else:
            image = source.crop(bounds).convert("RGBA")
        return image.transform(
            size,
            Image.Transform.EXTENT,
            (
                (box[0] - bounds[0]) * fx,
                (box[1] - bounds[1]) * fy,
                (box[2] - bounds[0]) * fx,
                (box[3] - bounds[1]) * fy,
            ),
            Image.Resampling.BICUBIC,
        )

    return read


def render_layered(reader, native_size, operations, box, size, cancelled=None):
    """Evaluate immutable tile dependencies without Python recursion or full-image state."""
    from dale.raster import ExportCancelled

    cache, used = OrderedDict(), 0
    key = len(operations), tuple(box), tuple(size)
    stack = [(key, _render_layered(reader, native_size, operations, box, size, cancelled))]
    result = None
    while stack:
        if cancelled and cancelled():
            raise ExportCancelled("Raster transform cancelled.")
        key, step = stack[-1]
        try:
            before, bounds, output_size = step.send(result)
            child_key = len(before), tuple(bounds), tuple(output_size)
            if child_key in cache:
                cache.move_to_end(child_key)
                result = cache[child_key].copy()
            else:
                stack.append(
                    (
                        child_key,
                        _render_layered(
                            reader, native_size, before, bounds, output_size, cancelled
                        ),
                    )
                )
                result = None
        except StopIteration as finished:
            result = finished.value
            stack.pop()
            cost = result.width * result.height * 4
            if cost <= 1024 * 1024:
                while cache and used + cost > 8 * 1024 * 1024:
                    _, old = cache.popitem(last=False)
                    used -= old.width * old.height * 4
                cache[key] = result.copy()
                used += cost
    return result


def _render_layered(reader, native_size, operations, box, size, cancelled=None):
    from dale.raster import render_export_alpha

    sx, sy = size[0] / (box[2] - box[0]), size[1] / (box[3] - box[1])

    def mask(ops):
        return render_export_alpha(
            size,
            native_size,
            ops,
            top=box[1] * sy,
            left=box[0] * sx,
            scale=(sx, sy),
            cancelled=cancelled,
        )

    last = next(
        (
            i
            for i in range(len(operations) - 1, -1, -1)
            if isinstance(operations[i], RasterTransform)
        ),
        None,
    )
    if last is None:
        image = reader(box, size)
        image.putalpha(ImageChops.multiply(image.getchannel("A"), mask(operations)))
        return image
    operation = operations[last]
    before = operations[:last]
    area = area_of(operation.area_wkb)
    cut = mask((ContourMask(area, "outside"),))
    image = (
        Image.new("RGBA", size) if cut.getextrema() == (255, 255) else (yield (before, box, size))
    )
    image.putalpha(ImageChops.multiply(image.getchannel("A"), ImageChops.invert(cut)))
    for data, matrix in operation.parts or ((operation.area_wkb, operation.matrix),):
        area = area_of(data)
        if area.is_empty:
            continue
        a, b, d, e, tx, ty = matrix
        det = a * e - b * d
        inverse = (
            e / det,
            -b / det,
            -d / det,
            a / det,
            (b * ty - e * tx) / det,
            (d * tx - a * ty) / det,
        )
        destination = affine_transform(area, matrix).bounds
        # Subdivide output so rotations do not allocate full-scene diagonal stripes.
        for output_y in range(
            math.floor(box[1] * sy / 256) * 256, math.ceil(box[3] * sy / 256) * 256, 256
        ):
            for output_x in range(
                math.floor(box[0] * sx / 256) * 256, math.ceil(box[2] * sx / 256) * 256, 256
            ):
                left, top = round(output_x - box[0] * sx), round(output_y - box[1] * sy)
                width = height = 256
                target = (
                    output_x / sx,
                    output_y / sy,
                    (output_x + width) / sx,
                    (output_y + height) / sy,
                )
                if (
                    target[2] < destination[0] - 3 / sx
                    or target[0] > destination[2] + 3 / sx
                    or target[3] < destination[1] - 3 / sy
                    or target[1] > destination[3] + 3 / sy
                ):
                    continue
                ia, ib, id_, ie, ix, iy = inverse
                corners = [
                    (ia * x + ib * y + ix, id_ * x + ie * y + iy)
                    for x in (target[0], target[2])
                    for y in (target[1], target[3])
                ]
                sampling = min(1, max(sx, sy) * math.sqrt(abs(det)))
                halo = 3 / sampling
                source_box = (
                    math.floor((min(p[0] for p in corners) - halo) * sampling) / sampling,
                    math.floor((min(p[1] for p in corners) - halo) * sampling) / sampling,
                    math.ceil((max(p[0] for p in corners) + halo) * sampling) / sampling,
                    math.ceil((max(p[1] for p in corners) + halo) * sampling) / sampling,
                )
                x0, y0, x1, y1 = area.bounds
                source_box = (
                    max(source_box[0], math.floor((x0 - halo) * sampling) / sampling),
                    max(source_box[1], math.floor((y0 - halo) * sampling) / sampling),
                    min(source_box[2], math.ceil((x1 + halo) * sampling) / sampling),
                    min(source_box[3], math.ceil((y1 + halo) * sampling) / sampling),
                )
                if source_box[0] >= source_box[2] or source_box[1] >= source_box[3]:
                    continue
                source_size = (
                    max(1, round((source_box[2] - source_box[0]) * sampling)),
                    max(1, round((source_box[3] - source_box[1]) * sampling)),
                )
                fragment = yield before, source_box, source_size
                fx = source_size[0] / (source_box[2] - source_box[0])
                fy = source_size[1] / (source_box[3] - source_box[1])
                capture = render_export_alpha(
                    source_size,
                    native_size,
                    (ContourMask(area, "outside"),),
                    top=source_box[1] * fy,
                    left=source_box[0] * fx,
                    scale=(fx, fy),
                )
                fragment.putalpha(ImageChops.multiply(fragment.getchannel("A"), capture))
                coefficients = (
                    ia * fx / sx,
                    ib * fx / sy,
                    (ia * target[0] + ib * target[1] + ix - source_box[0]) * fx,
                    id_ * fy / sx,
                    ie * fy / sy,
                    (id_ * target[0] + ie * target[1] + iy - source_box[1]) * fy,
                )
                moved = (
                    fragment.convert("RGBa")
                    .transform(
                        (width, height),
                        Image.Transform.AFFINE,
                        coefficients,
                        Image.Resampling.BICUBIC,
                    )
                    .convert("RGBA")
                )
                image.alpha_composite(moved, (left, top))
    for trailing in operations[last + 1 :]:
        if isinstance(trailing, Stroke) and trailing.restore:
            from dale.raster_brush import stroke_coverage

            coverage = stroke_coverage(size, trailing, sx, sy, box[0] * sx, box[1] * sy)
            if trailing.opacity != 1:
                coverage = coverage.point([round(i * trailing.opacity) for i in range(256)])
            image = Image.composite(reader(box, size), image, coverage)
        else:
            image.putalpha(ImageChops.multiply(image.getchannel("A"), mask((trailing,))))
    alpha = image.getchannel("A")
    image.paste((0, 0, 0, 0), mask=alpha.point([255] + [0] * 255))
    return image
