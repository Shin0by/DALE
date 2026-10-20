"""Exact source crops, bounded native storage and safe portable cache ownership."""

import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from dale.native_cache import CacheLease, cache_directory, clean_stale_cache
from dale.native_image import NativeImageSource
from dale.scene import load_pair


@pytest.fixture(autouse=True)
def cache_root(tmp_path, monkeypatch):
    monkeypatch.setenv("DALE_SETTINGS_PATH", str(tmp_path / "preferences.json"))


@pytest.mark.parametrize(
    "kind", ["jpg", "png", "rgba", "palette", "gray16", "cmyk", "bmp", "tif", "webp"]
)
def test_native_crops_match_pillow_without_full_python_decode(tmp_path, kind):
    rng = np.random.default_rng(432)
    data = rng.integers(0, 256, (98, 137, 4), dtype=np.uint8)
    image = Image.fromarray(data)
    extension = {"rgba": "png", "palette": "png", "gray16": "png", "cmyk": "jpg"}.get(kind, kind)
    if kind == "palette":
        image = image.convert("P", palette=Image.Palette.ADAPTIVE)
        image.info["transparency"] = 1
    elif kind == "gray16":
        image = Image.fromarray(data[:, :, 0].astype(np.uint16) * 253)
    elif kind == "cmyk":
        image = image.convert("CMYK")
    elif kind not in ("rgba", "webp"):
        image = image.convert("RGB")
    path = tmp_path / f"Native [source].{extension}"
    image.save(path)
    protected = path.read_bytes()
    source = load_pair(path)
    native = NativeImageSource(source)
    workspace = Path(native.workspace.name)
    try:
        assert workspace.parent == cache_directory()
        with Image.open(path) as original:
            for box in ((0, 0, 15, 17), (23, 47, 137, 98), (111, 5, 137, 15)):
                expected = original.crop(box).convert("RGBA")
                actual = native.crop(box)
                assert actual.size == expected.size
                assert actual.tobytes() == expected.tobytes()
    finally:
        native.close()
    assert not workspace.exists() and path.read_bytes() == protected


def test_cancellation_cleans_partial_cache(tmp_path):
    path = tmp_path / "Cancel.png"
    Image.new("RGB", (2200, 2100), (21, 42, 63)).save(path)
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        return calls > 2

    with pytest.raises(InterruptedError):
        NativeImageSource(load_pair(path), cancel)
    assert calls > 2
    assert not list(cache_directory().glob("image-*"))


def test_stale_cache_cleanup_preserves_live_instances_and_unowned_files(tmp_path):
    active = CacheLease()
    Path(active.name, "pixels.v").write_bytes(b"active")
    root = cache_directory()
    unrelated = root / "image-unrelated"
    unrelated.mkdir()
    (unrelated / "project.dale").write_bytes(b"not a cache")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import os; from pathlib import Path; from dale.native_cache import CacheLease; "
                "c=CacheLease(); Path(c.name,'pixels.v').write_bytes(b'orphan'); "
                "print(c.name,flush=True); os._exit(0)"
            ),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    orphan = Path(process.stdout.strip())
    assert orphan.exists()
    clean_stale_cache()
    assert not orphan.exists() and Path(active.name, "pixels.v").read_bytes() == b"active"
    assert (unrelated / "project.dale").read_bytes() == b"not a cache"
    active.cleanup()
    assert not Path(active.name).exists()


def test_cache_path_is_beside_frozen_executable(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "DALE.exe"))
    assert cache_directory() == tmp_path / "Cache"


def test_disk_full_keeps_cache_empty_and_sources_unchanged(tmp_path, monkeypatch):
    from collections import namedtuple

    source_path = tmp_path / "Source.png"
    Image.new("RGB", (200, 200)).save(source_path)
    before = source_path.read_bytes()
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr("dale.native_image.shutil.disk_usage", lambda path: usage(100, 100, 0))
    with pytest.raises(OSError, match="temporary disk space"):
        NativeImageSource(load_pair(source_path))
    assert not list(cache_directory().glob("image-*")) and source_path.read_bytes() == before


def test_failed_lease_initialization_leaves_no_partial_directory(monkeypatch):
    import dale.native_cache

    original = dale.native_cache.lock

    def fail_owner(stream):
        if Path(stream.name).name == ".owner.lock":
            raise OSError("Synthetic lock failure")
        return original(stream)

    monkeypatch.setattr(dale.native_cache, "lock", fail_owner)
    with pytest.raises(OSError, match="Synthetic lock failure"):
        CacheLease()
    assert not list(cache_directory().glob("image-*"))
