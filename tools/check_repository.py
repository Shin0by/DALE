"""Validate navigation paths and requirement references without indexing private input."""

import json
import re
import tomllib
from pathlib import Path

from text_policy import check_authored_texts

ROOT = Path(__file__).resolve().parents[1]
index = json.loads((ROOT / "project/index.json").read_text(encoding="utf-8"))
state = json.loads((ROOT / index["state"]).read_text(encoding="utf-8"))
paths = [
    index["entrypoint"],
    index["state"],
    index["environment_lock"],
    index["ci"],
    *index["documents"].values(),
    *index["code"].values(),
]
missing = [path for path in paths if not (ROOT / path).exists()]
if missing:
    raise SystemExit(f"Index paths missing: {missing}")
requirements = (ROOT / index["documents"]["requirements"]).read_text(encoding="utf-8")
ids = re.findall(r"\| ((?:FR|NFR)-\d+) \|", requirements)
if len(ids) != len(set(ids)) or not ids:
    raise SystemExit("Requirement IDs must exist and be unique.")
if state["communication_language"] != "ru" or state["technical_language"] != "en":
    raise SystemExit("Language agreement changed unexpectedly.")
version = re.search(
    r'^__version__ = "([0-9]+\.[0-9]+\.[0-9]+)"$',
    (ROOT / "src/dale/__init__.py").read_text(encoding="utf-8"),
    re.MULTILINE,
)
metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
if (
    not version
    or version[1] != metadata["project"]["version"]
    or version[1] != state["current_version"]
):
    raise SystemExit("Package, project metadata, and state versions must agree.")
text_count, text_failures = check_authored_texts(ROOT)
if text_failures:
    raise SystemExit("Authored text must use only ASCII hyphens:\n" + "\n".join(text_failures))
print(f"Repository index valid: {len(paths)} paths, {len(ids)} requirement IDs.")
print(f"ASCII hyphen policy valid: {text_count} authored text files.")
