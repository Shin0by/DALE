"""Check the real Git delivery, including Windows runtime bytes and private-data exclusion."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def git(*arguments, check=True):
    return subprocess.run(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", "-C", str(ROOT), *arguments],
        capture_output=True,
        check=check,
    )


def portable_entries():
    entries = {}
    for record in git("ls-files", "--stage", "-z", "--", "DALE").stdout.split(b"\0"):
        if record:
            metadata, name = record.split(b"\t", 1)
            mode, oid, stage = metadata.decode("ascii").split()
            assert stage == "0" and mode == "100644"
            entries[name.decode("utf-8")] = oid
    return entries


@pytest.mark.parametrize(
    "name",
    [
        "DALE/UserData/settings.json",
        "DALE/Cache/image-owned/source.v",
        "DALE/Private project.dale",
        "DALE/Imported artwork.png",
        "DALE/notes.txt",
    ],
)
def test_portable_user_files_are_ignored_even_when_new(name):
    assert git("check-ignore", "--no-index", "-q", "--", name, check=False).returncode == 0


@pytest.mark.parametrize(
    "name",
    [
        "DALE/DALE.exe",
        "DALE/_internal/PySide6/QtCore.pyd",
        "DALE/_internal/pyvips/vimage.py",
        "DALE/START-HERE.txt",
        "DALE/build-info.json",
    ],
)
def test_portable_runtime_is_included_without_lfs_or_line_conversion(name):
    assert git("check-ignore", "--no-index", "-q", "--", name, check=False).returncode == 1
    attributes = git("check-attr", "text", "filter", "--", name).stdout.decode("utf-8")
    assert f"{name}: text: unset" in attributes
    assert f"{name}: filter: unspecified" in attributes


def test_git_portable_delivery_is_complete_and_contains_no_user_data():
    entries = portable_entries()
    build = json.loads((ROOT / "DALE/build-info.json").read_text(encoding="utf-8-sig"))
    runtime = build["runtime_sha256"]
    assert set(entries) == {"DALE/" + name for name in runtime} | {"DALE/build-info.json"}
    for name, expected in runtime.items():
        assert hashlib.sha256((ROOT / "DALE" / name).read_bytes()).hexdigest() == expected
    required = {
        "DALE/DALE.exe",
        "DALE/START-HERE.txt",
        "DALE/build-info.json",
        "DALE/_internal/python311.dll",
        "DALE/_internal/PySide6/QtCore.pyd",
        "DALE/_internal/PySide6/Qt6Widgets.dll",
        "DALE/_internal/PySide6/plugins/platforms/qwindows.dll",
    }
    assert required <= entries.keys()
    for name in entries:
        path = Path(name)
        assert path.parts[1] in {"DALE.exe", "_internal", "START-HERE.txt", "build-info.json"}
        assert not {"userdata", "cache", "examples", "__pycache__"} & {
            part.lower() for part in path.parts
        }
        assert path.suffix.lower() != ".dale"
        file = ROOT / path
        assert file.is_file() and not file.is_symlink()
        assert file.stat().st_size < 100 * 1024 * 1024
    assert (ROOT / "DALE/DALE.exe").read_bytes()[:2] == b"MZ"


def test_git_snapshot_preserves_every_portable_file_byte_for_byte():
    entries = portable_entries()
    assert entries, "The ready portable runtime must be staged/tracked in Git."
    algorithm = git("rev-parse", "--show-object-format").stdout.decode("ascii").strip()
    for name, oid in entries.items():
        payload = (ROOT / name).read_bytes()
        digest = hashlib.new(algorithm, usedforsecurity=False)
        digest.update(f"blob {len(payload)}\0".encode("ascii"))
        digest.update(payload)
        assert digest.hexdigest() == oid, f"Git altered or does not contain current bytes: {name}"
