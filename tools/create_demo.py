"""Create a small, explicitly synthetic map pair for local editor exploration."""

import json
from pathlib import Path

from PIL import Image, ImageDraw


def create_demo(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1200, 900), "#557350")
    draw = ImageDraw.Draw(image)
    for x in range(0, 1200, 100):
        draw.line((x, 0, x, 900), fill="#627d5a")
    for y in range(0, 900, 100):
        draw.line((0, y, 1200, y), fill="#627d5a")
    draw.rectangle((200, 200, 700, 650), fill="#b5956a")
    draw.rectangle((850, 250, 1050, 450), fill="#c5b494")
    source_segments = [
        ((200, 200), (700, 200)),
        ((700, 200), (700, 650)),
        ((700, 650), (200, 650)),
        ((200, 650), (200, 500)),
        ((200, 350), (200, 200)),  # Deliberate gap for the Closure tool.
        ((850, 250), (1050, 250)),
        ((1050, 250), (1050, 450)),
        ((1050, 450), (850, 450)),
        ((850, 450), (850, 250)),
    ]
    for a, b in source_segments:
        draw.line((a, b), fill="#39363b", width=12)
    draw.rectangle((400, 330, 530, 405), fill="#664d3c")
    draw.ellipse((730, 500, 790, 560), fill="#334f36")
    draw.text((30, 30), "SYNTHETIC DEMO - not a Dungeon Alchemist export", fill="white")
    image.save(directory / "demo.jpg", quality=92)
    raw = {
        "name": "DALE synthetic demo",
        "width": 1200,
        "height": 900,
        "padding": 0,
        "grid": {"size": 100, "distance": 5, "units": "ft"},
        "background": {"src": "demo.jpg", "offsetX": 0, "offsetY": 0},
        "walls": [{"c": [*a, *b], "door": 0} for a, b in source_segments],
    }
    (directory / "demo.json").write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    return directory


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "artifacts" / "demo"
    print(create_demo(target))
