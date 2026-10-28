"""Release documentation fingerprints reject stale text, images, code and PDF bytes."""

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def article_module(path):
    spec = importlib.util.spec_from_file_location("article_check", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_article_fixture(root):
    for directory in ("tools", "src/dale", "docs/images/readme"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    for name in ("build_article.py", "article-requirements.txt"):
        shutil.copy2(ROOT / "tools" / name, root / "tools" / name)
    (root / "src/dale/__init__.py").write_text('__version__ = "1.4.137"\n')
    (root / "src/dale/ui.py").write_text('caption = "Current UI"\n')
    (root / "README.md").write_text('<img src="docs/images/readme/example.png">\n')
    (root / "docs/images/readme/example.png").write_bytes(b"fixture image")
    (root / "docs/DALE-guide.pdf").write_bytes(b"%PDF-1.7\nfixture document\n%%EOF")
    module = article_module(root / "tools/build_article.py")
    record = {
        "format": "dale-article-v1",
        "version": module.version(root),
        "pages": 1,
        "inputs": module.inputs(root),
        "reviewed_interface": module.interface_inputs(root),
        "pdf_sha256": module.digest(root / module.PDF),
    }
    (root / module.MANIFEST).write_text(json.dumps(record), encoding="utf-8")
    return module


@pytest.mark.parametrize(
    "name",
    [
        "README.md",
        "docs/images/readme/example.png",
        "docs/DALE-guide.pdf",
        "src/dale/ui.py",
        "src/dale/__init__.py",
    ],
)
def test_article_rejects_changed_release_inputs(tmp_path, name):
    module = write_article_fixture(tmp_path)
    assert module.check(tmp_path)["version"] == "1.4.137"
    path = tmp_path / name
    if name.endswith("__init__.py"):
        path.write_text('__version__ = "1.4.138"\n')
    else:
        path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError):
        module.check(tmp_path)
