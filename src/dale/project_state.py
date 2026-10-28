"""Current-state checkpoints without decoding or restoring undo/redo stacks."""

from dataclasses import replace

from dale.session import ContourMask, GeometryEdit, Stroke


def checkpoint_session(session):
    frozen = replace(session, operations=list(session.operations), future=[], history_floor=0)
    frozen.trim_history(0)
    if not any(isinstance(op, GeometryEdit) for op in frozen.operations):
        frozen.history_floor = len(frozen.operations)
        return frozen
    geometry = frozen.geometry()
    raster = []
    for operation in frozen.operations:
        if isinstance(operation, (ContourMask, Stroke)):
            raster.append(operation)
        elif getattr(operation, "raster", None) is not None:
            raster.append(GeometryEdit((), raster=operation.raster))
    frozen.operations = [*raster, replace(geometry, raster=None)]
    frozen.history_floor = len(frozen.operations)
    return frozen


def applied_operations(operations):
    """Select only applied geometry and raster state before operation deserialization.

    Source lineage is current provenance, not reversible editing history. Raster
    recipes remain ordered to preserve exact pixels without flattening/resampling.
    """
    last_geometry = -1
    metadata, records, raster = {}, {}, []
    allowed = {"geometry", "source_repair", "closure", "stroke", "mask", "raster_selection"}
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict) or operation.get("type") not in allowed:
            raise ValueError("Invalid project state operation.")
        kind = operation["type"]
        if kind in ("geometry", "source_repair", "closure"):
            for record in (*operation.get("lineage", ()), *operation.get("ancestry", ())):
                if isinstance(record, dict) and isinstance(record.get("id"), str):
                    records[record["id"]] = record
        if kind in ("geometry", "source_repair"):
            last_geometry = index
            metadata.update(
                (key, value) for key, value in operation.items() if key.startswith("alchemist_")
            )
            if "raster_transform" in operation:
                raster.append(
                    {
                        "type": "geometry",
                        "walls": [],
                        "closures": [],
                        "lineage": [],
                        "ancestry": [],
                        "raster_transform": operation["raster_transform"],
                    }
                )
        elif kind in ("stroke", "mask"):
            raster.append(operation)
    if last_geometry >= 0:
        current = {**operations[last_geometry], **metadata}
        current.pop("raster_transform", None)
        live = {record["id"] for record in current.get("lineage", ())}
        current["ancestry"] = [
            record for identifier, record in records.items() if identifier not in live
        ]
        vector = [current]
    else:
        vector = []
    vector.extend(
        operation for operation in operations[last_geometry + 1 :] if operation["type"] == "closure"
    )
    return [*raster, *vector]
