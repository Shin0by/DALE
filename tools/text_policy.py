"""Enforce ASCII hyphens in authored text without reading private or generated inputs."""

import ast
import html
import json
import unicodedata
from pathlib import Path

TEXT_ROOTS = ("src", "docs", "tools", "tests", "project", "skills", ".github", ".githooks")
TEXT_SUFFIXES = {
    ".md",
    ".txt",
    ".rst",
    ".adoc",
    ".html",
    ".htm",
    ".py",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".ps1",
    ".cmd",
    ".css",
    ".js",
    ".ts",
    ".tsx",
    ".svg",
    ".lock",
}
MINUS_LIKE = frozenset((0x00AD, 0x02D7, 0x2043, 0x2053, 0x207B, 0x208B, 0x2212, 0x2796))


def dash_analogues(text):
    return {
        char
        for char in html.unescape(text)
        if char != "-" and (unicodedata.category(char) == "Pd" or ord(char) in MINUS_LIKE)
    }


def json_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from json_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from json_strings(item)


def text_violations(path, text):
    """Include runtime Python/JSON strings so Unicode escapes cannot bypass the rule."""
    found = {
        (line_number, ord(char))
        for line_number, line in enumerate(text.splitlines(), 1)
        for char in dash_analogues(line)
    }
    if path.suffix == ".py":
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found.update((node.lineno, ord(char)) for char in dash_analogues(node.value))
    elif path.suffix == ".json":
        found.update(
            (1, ord(char))
            for value in json_strings(json.loads(text))
            for char in dash_analogues(value)
        )
    return sorted(found)


def authored_text_paths(root: Path):
    paths = {p for p in root.iterdir() if p.is_file() and p.suffix in TEXT_SUFFIXES}
    for directory in TEXT_ROOTS:
        paths.update(
            p for p in (root / directory).rglob("*") if p.is_file() and p.suffix in TEXT_SUFFIXES
        )
    if (root / "examples/README.md").is_file():
        paths.add(root / "examples/README.md")
    return sorted(paths)


def check_authored_texts(root: Path):
    paths = authored_text_paths(root)
    failures = []
    for path in paths:
        text = path.read_text(encoding="utf-8-sig")
        for line, codepoint in text_violations(path, text):
            failures.append(
                f"{path.relative_to(root)}:{line}: use ASCII '-' instead of U+{codepoint:04X}"
            )
    return len(paths), failures
