"""Private disk-backed source pixels for bounded-memory native viewport crops."""

import os
import shutil
from pathlib import Path

from PIL import Image

from dale.native_cache import CacheLease
from dale.scene import open_source

# Sequential codecs feed a private file; direct-access reads map only useful
# windows. No full-image Python/Pillow buffer or libvips operation cache remains.
os.environ.setdefault("VIPS_DISC_THRESHOLD", "8m")
os.environ.setdefault("VIPS_CONCURRENCY", "1")
import pyvips

pyvips.cache_set_max(0)
pyvips.cache_set_max_mem(16 * 1024 * 1024)


class NativeImageSource:
    def __init__(self, source, cancelled=lambda: False):
        self.image = None
        self.workspace = CacheLease()
        try:
            if (
                shutil.disk_usage(self.workspace.name).free
                < source.size[0] * source.size[1] * 4 + 64 * 1024 * 1024
            ):
                raise OSError("Not enough temporary disk space for native image preview.")
            with open_source(source.image_path) as header:
                if header.size != source.size:
                    raise ValueError("Source image dimensions changed; reopen the pair.")
                mode, format_name = header.mode, header.format
                if format_name == "BMP":
                    self._bitmap(header, cancelled)
                    return
            cache = Path(self.workspace.name) / "pixels.v"
            image = pyvips.Image.new_from_file(
                str(source.image_path) + "[]",
                access="sequential",
                memory=False,
                fail_on="error",
                revalidate=True,
            )
            image = image.cast("uchar", shift=image.format == "ushort" and mode in ("RGB", "RGBA"))
            self.mode = (
                "CMYK" if mode == "CMYK" else {1: "L", 2: "LA", 3: "RGB", 4: "RGBA"}[image.bands]
            )
            image.set_progress(True)
            image.signal_connect("eval", lambda image, progress: image.set_kill(cancelled()))
            image.write_to_file(str(cache))
            if cancelled():
                raise InterruptedError
            self.image = pyvips.Image.new_from_file(str(cache), access="random", revalidate=True)
        except BaseException as exc:
            self.close()
            if isinstance(exc, Exception) and cancelled():
                raise InterruptedError from exc
            raise

    def _bitmap(self, header, cancelled):
        """Pillow's raw BMP layout permits bounded row reads without a BMP codec DLL."""
        if len(header.tile) != 1 or header.tile[0].codec_name != "raw":
            raise ValueError("Native preview requires an uncompressed BMP image.")
        _, _, offset, args = header.tile[0]
        rawmode, stride, orientation = args
        width, height = header.size
        cache = Path(self.workspace.name) / "pixels.rgba"
        with open(header.filename, "rb") as original, cache.open("wb") as output:
            for top in range(0, height, 64):
                if cancelled():
                    raise InterruptedError
                rows = min(64, height - top)
                start = height - top - rows if orientation == -1 else top
                original.seek(offset + start * stride)
                part = Image.frombytes(
                    header.mode,
                    (width, rows),
                    original.read(stride * rows),
                    "raw",
                    rawmode,
                    stride,
                    orientation,
                )
                if header.mode == "P":
                    part.putpalette(header.getpalette())
                output.write(part.convert("RGBA").tobytes())
        self.mode = "RGBA"
        self.image = pyvips.Image.rawload(str(cache), width, height, 4)

    def crop(self, box):
        x, y, right, bottom = box
        part = self.image.crop(x, y, right - x, bottom - y)
        return Image.frombytes(
            self.mode, (part.width, part.height), part.write_to_memory()
        ).convert("RGBA")

    def sample_crop(self, box, size):
        """Downsample on disk before copying pixels into Python memory."""
        x, y, right, bottom = box
        part = self.image.crop(x, y, right - x, bottom - y)
        part = part.resize(size[0] / part.width, vscale=size[1] / part.height, kernel="cubic")
        return Image.frombytes(
            self.mode, (part.width, part.height), part.write_to_memory()
        ).convert("RGBA")

    def close(self):
        self.image = None
        self.workspace.cleanup()
