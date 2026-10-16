"""Build revisions must never advance owner-controlled major/minor components."""

import json
import runpy
from pathlib import Path

import pytest

bump_revision = runpy.run_path(str(Path(__file__).resolve().parents[1] / "tools/bump_revision.py"))[
    "bump_revision"
]


@pytest.mark.parametrize("before,after", [("0.3.2", "0.3.3"), ("2.9.999", "2.9.1000")])
def test_build_increments_only_revision_in_all_version_records(tmp_path, before, after):
    package = tmp_path / "src/dale/__init__.py"
    package.parent.mkdir(parents=True)
    package.write_text(f'__version__ = "{before}"\n', encoding="utf-8")
    metadata = tmp_path / "pyproject.toml"
    metadata.write_text(f'[project]\nversion = "{before}"\n', encoding="utf-8")
    state = tmp_path / "project/state.json"
    state.parent.mkdir()
    state.write_text(
        json.dumps({"current_version": before, "other": "preserved"}), encoding="utf-8"
    )
    assert bump_revision(tmp_path) == after
    assert package.read_text(encoding="utf-8") == f'__version__ = "{after}"\n'
    assert f'version = "{after}"' in metadata.read_text(encoding="utf-8")
    assert json.loads(state.read_text(encoding="utf-8")) == {
        "current_version": after,
        "other": "preserved",
    }


def test_inconsistent_version_records_fail_without_partial_updates(tmp_path):
    files = {
        tmp_path / "src/dale/__init__.py": '__version__ = "0.3.2"\n',
        tmp_path / "pyproject.toml": '[project]\nversion = "0.3.1"\n',
        tmp_path / "project/state.json": '{"current_version":"0.3.2"}',
    }
    for path, contents in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError, match="must agree"):
        bump_revision(tmp_path)
    assert all(path.read_text(encoding="utf-8") == contents for path, contents in files.items())
