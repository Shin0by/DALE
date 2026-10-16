import json

import pytest
from PIL import Image

from dale.scene import load_pair


@pytest.fixture
def pair_factory(tmp_path):
    def create(size=(80, 300), **overrides):
        image_path = tmp_path / "source.jpg"
        json_path = tmp_path / "source.json"
        Image.new("RGB", size, (120, 80, 40)).save(image_path)
        raw = {
            "width": size[0],
            "height": size[1],
            "padding": 0,
            "walls": [
                {"c": [10, 20, 60, 20]},
                {"c": [60, 20, 60, 270]},
                {"c": [60, 270, 10, 270]},
                {"c": [10, 270, 10, 20]},
            ],
        }
        raw.update(overrides)
        json_path.write_text(json.dumps(raw), encoding="utf-8")
        return load_pair(image_path, json_path)

    return create
