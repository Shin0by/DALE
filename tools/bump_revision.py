"""Advance only the build revision before packaging; major/minor are owner-controlled."""

import json
import re
import tomllib
from pathlib import Path


def bump_revision(root: Path) -> str:
    package_path = root / "src/dale/__init__.py"
    metadata_path = root / "pyproject.toml"
    state_path = root / "project/state.json"
    package = package_path.read_text(encoding="utf-8")
    metadata = metadata_path.read_text(encoding="utf-8")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    match = re.search(r'^__version__ = "(\d+)\.(\d+)\.(\d+)"$', package, re.MULTILINE)
    if not match:
        raise ValueError("Expected a major.minor.revision package version.")
    current = ".".join(match.groups())
    if (
        tomllib.loads(metadata)["project"]["version"] != current
        or state["current_version"] != current
    ):
        raise ValueError(
            "Package, project metadata, and state versions must agree before building."
        )
    major, minor, revision = map(int, match.groups())
    updated = f"{major}.{minor}.{revision + 1}"
    package = package[: match.start()] + f'__version__ = "{updated}"' + package[match.end() :]
    metadata, changes = re.subn(
        rf'^version = "{re.escape(current)}"$',
        f'version = "{updated}"',
        metadata,
        count=1,
        flags=re.MULTILINE,
    )
    if changes != 1:
        raise ValueError("Cannot locate the project version field.")
    state["current_version"] = updated
    contents = {
        package_path: package,
        metadata_path: metadata,
        state_path: json.dumps(state, ensure_ascii=False, indent=2) + "\n",
    }
    for path, text in contents.items():
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(text, encoding="utf-8", newline="\n")
        temporary.replace(path)
    return updated


if __name__ == "__main__":
    print(bump_revision(Path(__file__).resolve().parents[1]))
