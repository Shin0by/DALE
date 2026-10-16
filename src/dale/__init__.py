"""DALE: local wall-guided transparency editing."""

__version__ = "0.3.16"


def application_title():
    major, minor, revision = (int(part) for part in __version__.split("."))
    return f"Dungeon Alchemist Levels Export (v.{major}.{minor:02d}.{revision:03d})"
