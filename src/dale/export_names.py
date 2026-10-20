"""Deterministic physical export names, independent of selection order and history IDs."""

import hashlib
import re
import struct
from pathlib import Path


def group_export_stem(name):
    """Use a readable group name as a safe physical basename, leaving metadata intact."""
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip().rstrip(" .") or "Group"
    if stem.split(".")[0].upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        stem = "_" + stem
    return stem


def _coordinates(points):
    return b"".join(struct.pack(">dd", x + 0.0, y + 0.0) for x, y in points)


def _region_key(region):
    region = region.normalize().simplify(0, preserve_topology=True).normalize()
    if region.geom_type == "Polygon":
        rings = (region.exterior, *region.interiors)
        return b"P" + b"".join(
            struct.pack(">Q", len(ring.coords)) + _coordinates(ring.coords) for ring in rings
        )
    if region.geom_type == "MultiPolygon":
        return b"M" + b"".join(
            struct.pack(">Q", len(key)) + key
            for key in sorted(_region_key(p) for p in region.geoms)
        )
    raise ValueError("Export identifiers require closed regions.")


def selection_number(regions, *, fallback_edges=()):
    """Return a fixed29-digit SHA256/96 identifier of an exact unordered region set."""
    keys = sorted({_region_key(p) for p in regions if not p.is_empty})
    digest = hashlib.sha256(b"dale-export-regions-v1\0")
    if not keys:
        digest.update(b"edges\0")
        keys = sorted({_coordinates(sorted(edge)) for edge in fallback_edges})
    for key in keys:
        digest.update(struct.pack(">Q", len(key)))
        digest.update(key)
    return f"{int.from_bytes(digest.digest()[:12], 'big'):029d}"


def export_family(stem, number):
    """Keep a common readable prefix and enough Windows filename space for both IDs."""
    if not stem or Path(stem).name != stem or any(c in stem for c in '<>:"/\\|?*'):
        raise ValueError("Invalid export filename.")
    while len(stem.encode("utf-16-le")) > 320:
        stem = stem[:-1]
    return f"{stem.rstrip(' .')}-{number}"


def png_filename(family, selection_id, region_id, width, height):
    part = f"-part-{region_id}" if region_id != selection_id else ""
    return f"{family}{part}-{width}x{height}px.png"
