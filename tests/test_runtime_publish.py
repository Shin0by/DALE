"""Publishing must not replace the archive beneath a running frozen importer."""

import ctypes
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows publication guard")
ROOT = Path(__file__).resolve().parents[1]


def staged(tmp_path):
    root = tmp_path / "project"
    tool = root / "tools/publish_windows.ps1"
    tool.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "tools/publish_windows.ps1", tool)
    bundle = root / "artifacts/windows/onedir/DALE"
    bundle.mkdir(parents=True)
    runtime = {
        "DALE.exe": b"new executable",
        "_internal/data.txt": b"new data",
        "START-HERE.txt": b"new notes",
    }
    for name, data in runtime.items():
        path = bundle / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (bundle / "build-info.json").write_text(
        json.dumps(
            {
                "runtime_sha256": {
                    name: hashlib.sha256(data).hexdigest() for name, data in runtime.items()
                }
            }
        )
    )
    portable = root / "DALE"
    (portable / "_internal").mkdir(parents=True)
    (portable / "DALE.exe").write_bytes(b"old executable")
    (portable / "_internal/data.txt").write_bytes(b"old data")
    (portable / "UserData").mkdir()
    (portable / "UserData/settings.json").write_text("private")
    return tool, portable


def publish(tool):
    return subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(tool)], capture_output=True, text=True, timeout=30
    )


def test_busy_executable_defers_entire_bundle_then_publishes_after_release(tmp_path):
    tool, portable = staged(tmp_path)
    create = ctypes.windll.kernel32.CreateFileW
    create.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.c_void_p,
    ]
    create.restype = ctypes.c_void_p
    handle = create(str(portable / "DALE.exe"), 0x80000000, 1, None, 3, 0, None)
    assert handle not in (None, ctypes.c_void_p(-1).value)
    close = ctypes.windll.kernel32.CloseHandle
    close.argtypes = [ctypes.c_void_p]
    before = {p.relative_to(portable): p.read_bytes() for p in portable.rglob("*") if p.is_file()}
    try:
        result = publish(tool)
        assert result.returncode != 0
        assert "Portable publication deferred" in result.stderr
        assert before == {
            p.relative_to(portable): p.read_bytes() for p in portable.rglob("*") if p.is_file()
        }
    finally:
        close(handle)
    assert publish(tool).returncode == 0
    assert (portable / "DALE.exe").read_bytes() == b"new executable"
    assert (portable / "_internal/data.txt").read_bytes() == b"new data"
    assert (portable / "UserData/settings.json").read_text() == "private"


def test_bad_staged_hash_never_changes_the_portable(tmp_path):
    tool, portable = staged(tmp_path)
    (tool.parent.parent / "artifacts/windows/onedir/DALE/DALE.exe").write_bytes(b"broken")
    assert publish(tool).returncode != 0
    assert (portable / "DALE.exe").read_bytes() == b"old executable"
