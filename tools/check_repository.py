"""Validate navigation paths and requirement references without indexing private input."""

import json
import re
from pathlib import Path

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
print(f"Repository index valid: {len(paths)} paths, {len(ids)} requirement IDs.")
