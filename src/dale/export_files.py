"""Shared conflict decisions and free copy names for exported assets."""

import re
from pathlib import Path

from dale.raster import ExportCancelled


def export_copy_path(path: Path) -> Path:
    match = re.fullmatch(r"(.*)(-\d+x\d+px\.png)", path.name, re.IGNORECASE)
    stem, suffix = match.groups() if match else (path.stem, path.suffix)
    number = 2
    candidate = path
    while candidate.exists() or candidate.is_symlink():
        candidate = path.with_name(f"{stem}-{number}{suffix}")
        number += 1
    return candidate


def resolve_export_file(path: Path, conflict=None) -> Path:
    if not path.exists() and not path.is_symlink():
        return path
    answer = conflict(path) if conflict else "copy"
    if answer == "overwrite":
        if not path.is_file() or path.is_symlink():
            raise ValueError("Only a regular export file can be overwritten.")
        return path
    if answer == "copy":
        return export_copy_path(path)
    raise ExportCancelled("File export cancelled.")
