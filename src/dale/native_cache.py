"""Portable native-image leases; clean stale files without touching live editors."""

import os
import re
import shutil
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from time import monotonic, sleep

MAGIC = b"DALE native image cache\n"


def cache_directory():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "Cache"
    if os.environ.get("DALE_SETTINGS_PATH"):
        return Path(os.environ["DALE_SETTINGS_PATH"]).resolve().parent / "Cache"
    return Path(__file__).resolve().parents[2] / "artifacts/Cache"


def lock(stream):
    stream.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


@contextmanager
def root_lock(root):
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".lock").open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        end = monotonic() + 2
        while True:
            try:
                lock(stream)
                break
            except OSError:
                if monotonic() >= end:
                    raise
                sleep(0.01)
        yield


def safe_child(root, path):
    return not path.is_symlink() and path.resolve().parent == root.resolve()


def _prune(root):
    for path in root.iterdir():
        if not re.fullmatch(r"image-[a-z0-9_]{8}", path.name) or not safe_child(root, path):
            continue
        marker = path / ".owner.lock"
        if not marker.is_file() or marker.is_symlink():
            continue
        try:
            with marker.open("r+b") as stream:
                lock(stream)
                stream.seek(1)
                if stream.read() != MAGIC:
                    continue
            shutil.rmtree(path)
        except OSError:
            pass  # A live process holds its lease, or another cleanup already finished.


def clean_stale_cache():
    root = cache_directory()
    if root.exists():
        with root_lock(root):
            _prune(root)


class CacheLease:
    def __init__(self):
        self.root = cache_directory()
        self.stream = None
        with root_lock(self.root):
            _prune(self.root)
            self.path = Path(tempfile.mkdtemp(prefix="image-", dir=self.root))
            try:
                self.stream = (self.path / ".owner.lock").open("w+b")
                self.stream.write(b"\0" + MAGIC)
                self.stream.flush()
                lock(self.stream)
            except BaseException:
                if self.stream is not None:
                    self.stream.close()
                    self.stream = None
                if safe_child(self.root, self.path):
                    shutil.rmtree(self.path)
                raise
        self.name = str(self.path)

    def cleanup(self):
        if self.stream is not None:
            with root_lock(self.root):
                self.stream.close()
                self.stream = None
                if safe_child(self.root, self.path) and self.path.exists():
                    shutil.rmtree(self.path)
