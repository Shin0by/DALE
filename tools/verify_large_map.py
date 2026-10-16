"""Opt-in synthetic maximum-size smoke check. Not a real export compatibility test."""

import argparse
import json
import threading
import time
from pathlib import Path

import psutil
from PIL import Image
from shapely.geometry import box

from dale.placement import Placement
from dale.raster import export_png, load_preview
from dale.scene import MAX_SIDE, load_pair
from dale.session import ContourMask, Stroke


def run(side: int):
    if not 512 <= side <= MAX_SIDE:
        raise ValueError(f"Size must be between 512 and {MAX_SIDE}.")
    directory = Path(__file__).resolve().parents[1] / "artifacts/large-map-check"
    directory.mkdir(parents=True, exist_ok=True)
    image_path, json_path = directory / "synthetic.jpg", directory / "synthetic.json"
    image = Image.new("RGB", (side, side), (130, 90, 60))
    image.save(image_path, quality=85)
    image.close()
    json_path.write_text(json.dumps({"width": side, "height": side, "walls": []}), encoding="utf-8")
    source = load_pair(image_path, json_path)
    preview = load_preview(source)
    assert max(preview.size) <= 2048
    preview.close()
    operations = [
        ContourMask(box(100, 100, side - 100, side - 100), "outside"),
        Stroke(((side / 2, side / 2),), 30),
    ]
    process = psutil.Process()
    peak = [process.memory_info().rss]
    stop = threading.Event()

    def sample():
        while not stop.wait(0.02):
            peak[0] = max(peak[0], process.memory_info().rss)

    monitor = threading.Thread(target=sample, daemon=True)
    monitor.start()
    started = time.perf_counter()
    destination = directory / "synthetic-overlay.png"
    try:
        export_png(source, operations, destination, placement=Placement(14, 17))
        elapsed = time.perf_counter() - started
    finally:
        stop.set()
        monitor.join()
    previous = Image.MAX_IMAGE_PIXELS
    try:
        Image.MAX_IMAGE_PIXELS = MAX_SIDE * MAX_SIDE
        with Image.open(destination) as output:
            assert output.size == (side, side)
            assert output.mode == "RGBA"
            assert output.getpixel((0, 0))[3] == 0
            assert output.getpixel((200, 200))[3] == 255
            assert output.getpixel((side // 2, side // 2))[3] == 0
            assert output.info["DALE.ElevationFeet"] == "17"
    finally:
        Image.MAX_IMAGE_PIXELS = previous
    result = {
        "kind": "synthetic_smoke_check",
        "dimensions": [side, side],
        "export_seconds": round(elapsed, 2),
        "peak_export_rss_mib": round(peak[0] / 1024**2),
        "output_bytes": destination.stat().st_size,
        "checks": ["dimensions", "RGBA", "mask", "brush", "placement_metadata"],
    }
    (directory / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=MAX_SIDE)
    run(parser.parse_args().size)
