"""Exercise discovery writes with an isolated registry double, never production keys."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from dale import __version__
from dale import registration as subject

NOW = datetime(2026, 10, 20, 12, 34, 56, tzinfo=UTC)


class Registry:
    HKEY_CURRENT_USER = "HKCU"
    HKEY_LOCAL_MACHINE = "HKLM"
    KEY_SET_VALUE = 2
    KEY_WOW64_64KEY = 256
    REG_SZ = 1
    REG_DWORD = 4

    def __init__(self, denied=(), failing_value=None):
        self.denied = set(denied)
        self.failing_value = failing_value
        self.values = {}
        self.opened = []
        self.closed = []

    def CreateKeyEx(self, hive, subkey, reserved, access):
        registry = self
        identity = (hive, subkey)
        self.opened.append((identity, reserved, access))
        if hive in self.denied or identity in self.denied:
            raise PermissionError("Access denied")
        self.values.setdefault(identity, {})

        class Key:
            def __enter__(self):
                return identity

            def __exit__(self, *args):
                registry.closed.append(identity)

        return Key()

    def SetValueEx(self, key, name, reserved, kind, value):
        assert reserved == 0
        if (key, name) == self.failing_value:
            raise OSError("Registry is unavailable")
        self.values[key][name] = (value, kind)


def test_metadata_and_app_paths_are_identical_in_both_hives():
    registry = Registry()
    executable = Path("C:/Portable apps/DALE/DALE.exe")
    result = subject._write_registration(registry, executable, NOW)
    assert len(result.written_keys) == 4 and not result.failed_keys and not result.skipped
    major, minor, revision = map(int, __version__.split("."))
    expected = {
        "DisplayName": ("Dungeon Alchemist Levels Export", 1),
        "DisplayVersion": (f"{major}.{minor:02d}.{revision:03d}", 1),
        "Publisher": ("Shin0by", 1),
        "RepositoryUrl": ("https://github.com/Shin0by/DALE", 1),
        "ExecutablePath": (str(executable), 1),
        "ProductId": ("Shin0by.DALE", 1),
        "LastRunTimeUtc": ("2026-10-20T12:34:56Z", 1),
        "RegistrySchemaVersion": (1, 4),
    }
    for hive in ("HKCU", "HKLM"):
        assert registry.values[hive, subject.PRODUCT_KEY] == expected
        assert registry.values[hive, subject.APP_PATHS_KEY] == {"": (str(executable), 1)}
    assert [key for key, _, _ in registry.opened] == [
        (hive, key)
        for hive in ("HKCU", "HKLM")
        for key in (subject.PRODUCT_KEY, subject.APP_PATHS_KEY)
    ]
    assert all(reserved == 0 and access == 258 for _, reserved, access in registry.opened)
    assert registry.closed == [key for key, _, _ in registry.opened]


def test_last_copy_wins_without_removing_unrelated_values(monkeypatch):
    registry = Registry()
    subject._write_registration(registry, Path("C:/New/DALE.exe"), NOW)
    for hive in ("HKCU", "HKLM"):
        registry.values[hive, subject.PRODUCT_KEY]["OtherProductSetting"] = ("keep", 1)
    monkeypatch.setattr(subject, "__version__", "1.2.3")
    path = Path("D:/Older portable copy/DALE.exe")
    later = NOW + timedelta(hours=1)
    subject._write_registration(registry, path, later)
    for hive in ("HKCU", "HKLM"):
        values = registry.values[hive, subject.PRODUCT_KEY]
        assert values["DisplayVersion"] == ("1.02.003", 1)
        assert values["ExecutablePath"] == (str(path), 1)
        assert values["OtherProductSetting"] == ("keep", 1)
        assert values["LastRunTimeUtc"] == ("2026-10-20T13:34:56Z", 1)


@pytest.mark.parametrize("denied", [("HKLM",), ("HKCU",), ("HKCU", "HKLM")])
def test_access_denied_never_prevents_other_independent_writes(denied):
    registry = Registry(denied=denied)
    result = subject._write_registration(registry, Path("C:/DALE.exe"), NOW)
    assert len(result.failed_keys) == 2 * len(denied)
    assert len(result.written_keys) == 4 - len(result.failed_keys)
    assert len(registry.opened) == 4


def test_partial_key_failure_closes_handle_and_continues():
    registry = Registry(failing_value=(("HKCU", subject.PRODUCT_KEY), "Publisher"))
    result = subject._write_registration(registry, Path("C:/DALE.exe"), NOW)
    assert result.failed_keys == (f"HKEY_CURRENT_USER\\{subject.PRODUCT_KEY}",)
    assert len(result.written_keys) == 3
    assert len(registry.closed) == 4


@pytest.mark.parametrize(
    ("platform", "frozen", "verification"),
    [("linux", True, False), ("win32", False, False), ("win32", True, True)],
)
def test_development_other_platforms_and_verification_never_write(
    monkeypatch, platform, frozen, verification
):
    registry = Registry()
    monkeypatch.setitem(subject.sys.modules, "winreg", registry)
    monkeypatch.setattr(subject.sys, "platform", platform)
    monkeypatch.setattr(subject.sys, "frozen", frozen, raising=False)
    assert subject.register_current_product(verification=verification).skipped
    assert not registry.opened


def test_packaged_launch_resolves_executable_not_working_directory(monkeypatch, tmp_path):
    executable = tmp_path / "Portable folder" / "DALE.exe"
    executable.parent.mkdir()
    executable.write_bytes(b"test executable")
    registry = Registry()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(subject.sys.modules, "winreg", registry)
    monkeypatch.setattr(subject.sys, "platform", "win32")
    monkeypatch.setattr(subject.sys, "frozen", True, raising=False)
    monkeypatch.setattr(subject.sys, "executable", str(Path("Portable folder") / "DALE.exe"))
    result = subject.register_current_product()
    assert len(result.written_keys) == 4
    values = registry.values["HKCU", subject.PRODUCT_KEY]
    assert values["ExecutablePath"] == (str(executable.resolve()), 1)
    recorded = datetime.fromisoformat(values["LastRunTimeUtc"][0].replace("Z", "+00:00"))
    assert abs((datetime.now(UTC) - recorded).total_seconds()) < 5


@pytest.mark.parametrize("filename", ["python", "missing.exe"])
def test_invalid_executable_never_writes(monkeypatch, tmp_path, filename):
    executable = tmp_path / filename
    if filename == "python":
        executable.touch()
    registry = Registry()
    monkeypatch.setitem(subject.sys.modules, "winreg", registry)
    monkeypatch.setattr(subject.sys, "platform", "win32")
    monkeypatch.setattr(subject.sys, "frozen", True, raising=False)
    monkeypatch.setattr(subject.sys, "executable", str(executable))
    subject.register_current_product()
    assert not registry.opened


@pytest.mark.parametrize("verification", [False, True])
def test_ui_startup_registers_after_show_and_skips_smoke(monkeypatch, tmp_path, verification):
    from dale import ui

    events = []
    application = SimpleNamespace(exec=lambda: events.append("exec") or 0)
    window = SimpleNamespace(show=lambda: events.append("show"))
    monkeypatch.setattr(ui, "QApplication", lambda args: application)
    monkeypatch.setattr(ui, "configure_application", lambda app: None)
    monkeypatch.setattr(ui, "MainWindow", lambda: window)
    monkeypatch.setattr(
        ui,
        "register_current_product",
        lambda **kwargs: events.append(("register", kwargs["verification"])),
    )
    monkeypatch.setattr(ui, "QTimer", SimpleNamespace(singleShot=lambda *args: None))
    arguments = ["DALE.exe"]
    if verification:
        arguments += ["--smoke-report", str(tmp_path / "smoke.json")]
    monkeypatch.setattr(ui.sys, "argv", arguments)
    with pytest.raises(SystemExit) as stopped:
        ui.main()
    assert stopped.value.code == 0
    assert events == ["show", ("register", verification), "exec"]
