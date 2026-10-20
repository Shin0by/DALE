"""Best-effort Windows product discovery for ordinary packaged launches."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from dale import __version__

PRODUCT_KEY = r"Software\Shin0by\DALE"
APP_PATHS_KEY = r"Software\Microsoft\Windows\CurrentVersion\App Paths\DALE.exe"
PRODUCT_ID = "Shin0by.DALE"
REGISTRY_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RegistrationResult:
    """Report independent key writes without making registration a startup dependency."""

    written_keys: tuple[str, ...] = ()
    failed_keys: tuple[str, ...] = ()
    skipped: bool = False


def _product_values(executable: Path, now: datetime) -> dict[str, str | int]:
    major, minor, revision = (int(part) for part in __version__.split("."))
    return {
        "DisplayName": "Dungeon Alchemist Levels Export",
        "DisplayVersion": f"{major}.{minor:02d}.{revision:03d}",
        "Publisher": "Shin0by",
        "RepositoryUrl": "https://github.com/Shin0by/DALE",
        "ExecutablePath": str(executable),
        "ProductId": PRODUCT_ID,
        "LastRunTimeUtc": now.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "RegistrySchemaVersion": REGISTRY_SCHEMA_VERSION,
    }


def _write_registration(registry, executable: Path, now: datetime) -> RegistrationResult:
    """Attempt each key separately with the existing token and the 64-bit view."""
    values = _product_values(executable, now)
    written, failed = [], []
    access = registry.KEY_SET_VALUE | registry.KEY_WOW64_64KEY
    for hive_name in ("HKEY_CURRENT_USER", "HKEY_LOCAL_MACHINE"):
        for subkey, entries in (
            (PRODUCT_KEY, values),
            (APP_PATHS_KEY, {"": str(executable)}),
        ):
            label = f"{hive_name}\\{subkey}"
            try:
                with registry.CreateKeyEx(getattr(registry, hive_name), subkey, 0, access) as key:
                    for name, value in entries.items():
                        value_type = (
                            registry.REG_DWORD if isinstance(value, int) else registry.REG_SZ
                        )
                        registry.SetValueEx(key, name, 0, value_type, value)
            except OSError:
                failed.append(label)
            else:
                written.append(label)
    return RegistrationResult(tuple(written), tuple(failed))


def register_current_product(*, verification: bool = False) -> RegistrationResult:
    """Register only a real packaged Windows EXE, never development or smoke runs.

    The most recently launched copy replaces these discovery values even when its
    version is older. No application settings, file associations, environment or
    uninstall entries belong here. Access failures never request elevation.
    """
    if verification or sys.platform != "win32" or not getattr(sys, "frozen", False):
        return RegistrationResult(skipped=True)
    try:
        import winreg

        executable = Path(sys.executable).resolve(strict=True)
        if executable.suffix.lower() != ".exe" or not executable.is_file():
            return RegistrationResult(skipped=True)
        return _write_registration(winreg, executable, datetime.now(UTC))
    except (ImportError, OSError):
        return RegistrationResult(failed_keys=("Windows product registration",))
