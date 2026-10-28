"""Local per-type defaults and explicit per-instance relative transform choices."""

import math
from collections import defaultdict
from dataclasses import replace

from dale.session import GeometryEdit


def validate_settings(value):
    if not isinstance(value, dict) or set(value) - {"scale", "rotation", "slice", "complexity"}:
        raise ValueError("Invalid saved object settings.")
    result = dict(value)
    for key in ("scale", "rotation"):
        if key in value and (type(value[key]) not in (int, float) or not math.isfinite(value[key])):
            raise ValueError("Invalid saved object transform.")
    if "scale" in value and not 1e-9 <= value["scale"] <= 1e9:
        raise ValueError("Invalid saved object scale.")
    if "rotation" in value and not -180 <= value["rotation"] < 180:
        raise ValueError("Invalid saved object rotation.")
    if "complexity" in value and (
        type(value["complexity"]) is not int or not 4 <= value["complexity"] <= 2147483647
    ):
        raise ValueError("Invalid contour complexity settings.")
    if "slice" in value:
        from dale.alchemist_slices import decode_object_values

        if not isinstance(value["slice"], (list, tuple)):
            raise ValueError("Invalid object slice settings.")
        result["slice"] = decode_object_values([["saved", list(value["slice"])]])[0][1]
    return result


def transforms_for(session):
    return {
        identifier: (scale, rotation)
        for identifier, scale, rotation in next(
            (
                op.alchemist_transforms
                for op in reversed(session.operations)
                if isinstance(op, GeometryEdit) and op.alchemist_transforms is not None
            ),
            (),
        )
    }


def decode_transforms(value):
    if not isinstance(value, list) or len(value) > 100000:
        raise ValueError("Invalid object transform settings.")
    result, seen = [], set()
    for item in value:
        if (
            not isinstance(item, list)
            or len(item) != 3
            or not isinstance(item[0], str)
            or not 1 <= len(item[0]) <= 128
            or item[0] in seen
        ):
            raise ValueError("Invalid object transform settings.")
        validate_settings({"scale": item[1], "rotation": item[2]})
        result.append(tuple(item))
        seen.add(item[0])
    return tuple(result)


def transform_settings(session, identifiers, scale=1, angle=0):
    values = transforms_for(session)
    for identifier in identifiers:
        factor, rotation = values.get(identifier, (1, 0))
        values[identifier] = factor * scale, (rotation + angle + 180) % 360 - 180
    return tuple((key, *value) for key, value in sorted(values.items()))


def whole_objects(session, selected):
    from dale.alchemist import memberships

    selected = set(selected)
    included, excluded = set(), set()
    geometry = session.geometry()
    for record, owners in zip(
        geometry.lineage, memberships(session.alchemist, geometry), strict=True
    ):
        (included if record.id in selected else excluded).update(owners)
    return included - excluded


def settings_for(session, identifiers, fields):
    from dale.alchemist_detail import values_for
    from dale.alchemist_slices import object_value

    transforms, limits = transforms_for(session), values_for(session)
    result = {}
    for obj in session.alchemist.objects:
        if obj.id not in identifiers or not obj.block_id:
            continue
        scale, rotation = transforms.get(obj.id, (1, 0))
        value = {"scale": scale, "rotation": rotation, "slice": object_value(session, obj)}
        if obj.id in limits:
            value["complexity"] = limits[obj.id]
        result[obj.block_id] = {key: value[key] for key in fields if key in value}
    return {key: value for key, value in result.items() if value}


def apply_settings(session, presets, report):
    from dale.alchemist import memberships, transform_individual_objects
    from dale.alchemist_detail import simplify_contours, values_for
    from dale.alchemist_detail_frames import capture_frames, frames_for, placements_for
    from dale.alchemist_progress import snapshot
    from dale.alchemist_slices import change_slice
    from dale.project_state import checkpoint_session

    frozen = snapshot(session)
    objects = [obj for obj in frozen.alchemist.objects if obj.block_id in presets]
    profile_ids = {key for key, _ in frozen.alchemist.profiles}
    slices, transforms, limits = defaultdict(set), defaultdict(set), values_for(frozen)
    for obj in objects:
        value = validate_settings(presets[obj.block_id])
        if "slice" in value and obj.projection is not None and obj.block_id in profile_ids:
            slices[(obj.category, *value["slice"])].add(obj.id)
        transforms[(value.get("scale", 1), value.get("rotation", 0))].add(obj.id)
        if "complexity" in value:
            limits[obj.id] = value["complexity"]
    for index, ((category, low, high, enabled), ids) in enumerate(slices.items()):
        report(5 + int(30 * index / max(1, len(slices))), "Updating Dungeon Alchemist contours")
        geometry = change_slice(
            frozen,
            category,
            low,
            object_ids=ids,
            upper=high,
            between=enabled,
            apply_detail=False,
            progress=lambda *_: report(25, "Updating Dungeon Alchemist contours"),
        )
        if geometry is not None:
            frozen.operations.append(geometry)
    for (scale, angle), ids in transforms.items():
        report(40, "Resizing object contours")
        geometry = frozen.geometry()
        selected = tuple(
            r.id
            for r, owners in zip(
                geometry.lineage, memberships(frozen.alchemist, geometry), strict=True
            )
            if owners & ids
        )
        remaining = scale
        while remaining > 100:
            report(40, "Resizing object contours")
            intermediate, _ = transform_individual_objects(frozen, selected, scale=100)
            frozen.operations.append(intermediate)
            remaining /= 100
        changed, _ = transform_individual_objects(frozen, selected, scale=remaining, angle=angle)
        frozen.operations.append(
            replace(changed, alchemist_transforms=transform_settings(frozen, ids, scale, angle))
        )
    report(60, "Updating Dungeon Alchemist contours")
    geometry = frozen.geometry()
    ids = {obj.id for obj in objects}
    targets = {
        r.id: min(limits[o] for o in owners if o in limits)
        for r, owners in zip(geometry.lineage, memberships(frozen.alchemist, geometry), strict=True)
        if owners & ids & limits.keys()
    }
    if targets:
        placements = placements_for(frozen, geometry, ids)
        geometry, _, _ = simplify_contours(
            geometry,
            targets,
            targets,
            lambda done, total: report(
                60 + int(30 * done / max(1, total)), "Updating Dungeon Alchemist contours"
            ),
            check_cancel=getattr(report, "check_cancel", None),
        )
        frozen.operations.append(
            replace(
                geometry,
                alchemist_complexity=tuple(sorted(limits.items())),
                alchemist_detail_frames=capture_frames(
                    frozen.alchemist, geometry, placements, frames_for(frozen)
                ),
            )
        )
    report(95, "Updating the display")
    return checkpoint_session(frozen).geometry()
