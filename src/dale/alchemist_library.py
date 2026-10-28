"""Read local Dungeon Alchemist metadata and cache resolved IDs without network access."""

from __future__ import annotations

import gc
import json
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path

APP_ID = "1588530"
DATABASE = Path("Dungeon Alchemist_Data/StreamingAssets/Database")
MAX_METADATA_BYTES = 64 * 1024 * 1024


class _NativeBatch:
    """Reuse the reader across models; restart only after sustained retained growth."""

    growth_budget = 128 * 1024 * 1024
    growth_step = 8 * 1024 * 1024
    low_memory = 256 * 1024 * 1024

    def __init__(self, executable):
        self.executable = executable
        self.reader = None
        self.baseline = self.previous = self.growing = self.restarts = 0

    @staticmethod
    def memory():
        import psutil

        return psutil.Process().memory_info().rss, psutil.virtual_memory().available

    def meshes(self, identifier):
        from dale.alchemist_mesh import NativeModels

        if self.reader is None:
            self.reader = NativeModels(self.executable)
            self.baseline = self.previous = self.memory()[0]
            self.growing = 0
        return self.reader.meshes(identifier)

    def release_model(self):
        if self.reader is None:
            return
        used, available = self.memory()
        self.growing = self.growing + 1 if used > self.previous + self.growth_step else 0
        self.previous = used
        growth = used - self.baseline
        if not (
            (growth > self.growth_budget and self.growing >= 2)
            or (available < self.low_memory and growth > self.growth_step * 4)
        ):
            return
        # Do not reload for temporary garbage that can be collected cheaply here.
        gc.collect()
        used, available = self.memory()
        if used - self.baseline > self.growth_budget or (
            available < self.low_memory and used - self.baseline > self.growth_step * 4
        ):
            self.close()
            self.restarts += 1
        self.previous = used

    def close(self):
        if self.reader is not None:
            self.reader.close()
            self.reader = None
            gc.collect()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class MissingAlchemistItems(ValueError):
    def __init__(self, items):
        self.items = tuple(items)
        super().__init__("Missing local Dungeon Alchemist objects: " + ", ".join(self.items))


def installation(executable):
    path = Path(executable)
    if not path.is_file() or path.name.lower() != "dungeon alchemist.exe":
        raise ValueError("Choose Dungeon Alchemist.exe from the installed application.")
    database = path.parent / DATABASE
    if not all(
        (database / name).is_file() for name in ("BuildingBlocks.json", "ModelStaticData.json")
    ):
        raise ValueError(
            "The selected Dungeon Alchemist installation has no readable object database."
        )
    return path.resolve()


def _registry_locations():
    try:
        import winreg
    except ImportError:
        return (), ()
    steam, installs = [], []
    entries = (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath", steam),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath", steam),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 1588530",
            "InstallLocation",
            installs,
        ),
    )
    for hive, key, value, result in entries:
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as handle:
                    found, _ = winreg.QueryValueEx(handle, value)
                    if isinstance(found, str) and found:
                        result.append(Path(found))
            except OSError:
                continue
    return tuple(dict.fromkeys(steam)), tuple(dict.fromkeys(installs))


def steam_libraries(roots):
    result = list(roots)
    for root in roots:
        try:
            path = root / "steamapps/libraryfolders.vdf"
            if path.stat().st_size > 1024 * 1024:
                continue
            text = path.read_text(encoding="utf-8-sig")
            for value in re.findall(r'"path"\s*"([^"\r\n]+)"', text):
                result.append(Path(value.replace("\\\\", "\\")))
        except (OSError, UnicodeError):
            continue
    return tuple(dict.fromkeys(result))


def discover_installations(saved=None):
    steam, installs = _registry_locations()
    candidates = ([Path(saved)] if saved else []) + [p / "Dungeon Alchemist.exe" for p in installs]
    candidates += [
        p / "steamapps/common/Dungeon Alchemist/Dungeon Alchemist.exe"
        for p in steam_libraries(steam)
    ]
    result = []
    for candidate in candidates:
        try:
            found = installation(candidate)
            if found not in result:
                result.append(found)
        except (OSError, ValueError):
            continue
    return tuple(result)


def local_workshop_roots(executable):
    """Inspect downloaded Steam libraries only. Never invoke Steam or request downloads."""
    steam, _ = _registry_locations()
    roots = list(steam_libraries(steam))
    for parent in Path(executable).parents:
        if parent.name.lower() == "steamapps":
            roots.insert(0, parent.parent)
            break
    return tuple(dict.fromkeys(p / "steamapps/workshop/content" / APP_ID for p in roots))


def _read_json(path):
    with path.open("rb") as stream:
        raw = stream.read(MAX_METADATA_BYTES + 1)
    if len(raw) > MAX_METADATA_BYTES:
        raise ValueError("Dungeon Alchemist metadata exceeds the supported size.")
    return json.loads(raw)


def cache_path(preferences):
    return Path(preferences).parent / "alchemist-cache.sqlite3"


class AlchemistLibrary:
    """An ID cache of descriptions and 2D silhouettes, without textures or map content."""

    def __init__(self, path, executable=None, workshop_roots=None):
        self.path = Path(path)
        self.executable = Path(executable) if executable else None
        self.workshop_roots = workshop_roots

    @contextmanager
    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            with connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS metadata "
                    "(id TEXT PRIMARY KEY, format INTEGER NOT NULL, payload TEXT NOT NULL)"
                )
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS model_profiles "
                    "(id TEXT PRIMARY KEY, format INTEGER NOT NULL, payload TEXT NOT NULL)"
                )
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS model_previews "
                    "(id TEXT PRIMARY KEY, payload BLOB NOT NULL)"
                )
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS item_settings "
                    "(id TEXT PRIMARY KEY, format INTEGER NOT NULL, payload TEXT NOT NULL)"
                )
                yield connection
        finally:
            connection.close()

    def clear(self):
        # Delete rows in our own database, never a directory or any Steam content.
        with self._connect() as connection:
            connection.execute("DELETE FROM metadata")
            connection.execute("DELETE FROM model_profiles")
            connection.execute("DELETE FROM model_previews")
            connection.execute("DELETE FROM item_settings")

    def item_settings(self, identifiers):
        from dale.alchemist_presets import validate_settings

        result = {}
        if not self.path.exists():
            return result
        with self._connect() as connection:
            for identifier in sorted(set(identifiers)):
                row = connection.execute(
                    "SELECT format, payload FROM item_settings WHERE id=?", (identifier,)
                ).fetchone()
                if row and row[0] == 1:
                    result[identifier] = validate_settings(json.loads(row[1]))
        return result

    def remember_item_settings(self, values):
        from dale.alchemist_presets import validate_settings

        checked = {key: validate_settings(value) for key, value in values.items()}
        if any(not isinstance(key, str) or not 1 <= len(key) <= 256 for key in checked):
            raise ValueError("Invalid saved object type.")
        with self._connect() as connection:
            for identifier, value in checked.items():
                row = connection.execute(
                    "SELECT format, payload FROM item_settings WHERE id=?", (identifier,)
                ).fetchone()
                previous = validate_settings(json.loads(row[1])) if row and row[0] == 1 else {}
                payload = json.dumps({**previous, **value}, separators=(",", ":"))
                connection.execute(
                    "INSERT OR REPLACE INTO item_settings VALUES (?,1,?)", (identifier, payload)
                )

    def profiles(self, entries, workshop_items, progress):
        from dale.alchemist import AlchemistCancelled, category_of
        from dale.alchemist_mesh import (
            PREVIEW_FORMAT,
            build_profile,
            cached_profile,
            layer_anchor,
            preview_image,
            save_profile,
        )

        result, unavailable = {}, []
        native_failed = False
        check_cancel = getattr(progress, "check_cancel", lambda: None)
        with _NativeBatch(self.executable) as native, self._connect() as connection:
            selected = [
                (key, entry)
                for key, entry in entries.items()
                if category_of(entry["block"]) is not None
            ]
            for index, (identifier, entry) in enumerate(selected):
                block, model = entry["block"], entry["model"]
                category = category_of(block)
                if category is None:
                    continue
                progress(
                    16 + int(49 * index / max(1, len(selected))), "Reading local object geometry"
                )
                key = model["Id"]
                profile = cached_profile(connection, key)
                preview = getattr(progress, "preview", None)
                context = {"appearance": {}, "meshes": ()}
                meshes = ()
                model_name = block.get("name", identifier)

                def show(
                    layer,
                    shape,
                    cached=False,
                    *,
                    preview=preview,
                    key=key,
                    category=category,
                    context=context,
                    name=model_name,
                    index=index,
                ):
                    check_cancel()
                    progress(
                        16 + int(49 * (index + (layer + 1) / 10) / max(1, len(selected))),
                        "Reading cached model projections"
                        if cached
                        else "Calculating model projections",
                    )
                    if preview is None or shape.is_empty:
                        return
                    preview_key = json.dumps([PREVIEW_FORMAT, key, layer])
                    row = (
                        connection.execute(
                            "SELECT payload FROM model_previews WHERE id=?", (preview_key,)
                        ).fetchone()
                        if cached
                        else None
                    )
                    pixels = (
                        row[0]
                        if row
                        else preview_image(
                            shape,
                            layer_anchor(shape) if category == "tree" else None,
                            context["meshes"],
                            context["appearance"],
                            category in ("tree", "bush"),
                        )
                    )
                    if row is None:
                        connection.execute(
                            "INSERT OR REPLACE INTO model_previews VALUES (?, ?)",
                            (preview_key, pixels),
                        )
                    caption = f"{name} - {layer * 10}-{(layer + 1) * 10}%"
                    preview((pixels, caption, cached))

                if profile is None:
                    try:
                        if not self.executable:
                            raise ValueError("Local model installation is unavailable.")
                        if key.startswith("NATIVE#"):
                            if native_failed:
                                raise ValueError("Local native models are unavailable.")
                            try:
                                meshes = native.meshes(key)
                            except Exception:
                                native_failed = native.reader is None
                                raise
                        else:
                            meshes = self._workshop_meshes(identifier, key, workshop_items)
                        context["meshes"] = meshes
                        profile = build_profile(meshes, show, check_cancel=check_cancel)
                        check_cancel()
                        save_profile(connection, key, profile)
                    except AlchemistCancelled:
                        raise
                    except Exception as exc:
                        unavailable.append((identifier, str(exc)))
                        continue
                    finally:
                        context.clear()
                        meshes = ()
                        native.release_model()
                else:
                    for layer, shape in enumerate(profile.layers):
                        show(layer, shape, True)
                result[identifier] = profile
        self.geometry_unavailable = tuple(unavailable)
        self.geometry_reader_restarts = native.restarts
        return result

    def _workshop_meshes(self, identifier, model_id, workshop_items):
        from dale.alchemist_mesh import glb_meshes

        workshop_id = str(
            workshop_items.get(identifier, {}).get("description", {}).get("publishedWorkshopId", "")
        )
        if not re.fullmatch(r"[0-9]{1,20}", workshop_id):
            raise ValueError("Local Workshop model is unavailable.")
        roots = (
            self.workshop_roots
            if self.workshop_roots is not None
            else (local_workshop_roots(self.executable))
        )
        for root in roots:
            for path in (Path(root) / workshop_id).glob("*/*.json"):
                value = _read_json(path)
                if value.get("staticData", {}).get("Id") != model_id:
                    continue
                name = value.get("fileName", "")
                if not name or Path(name).name != name or Path(name).suffix.lower() != ".glb":
                    raise ValueError("Unsupported local model file.")
                source = (path.parent / name).resolve()
                if not source.is_relative_to(path.parent.resolve()):
                    raise ValueError("Invalid local model path.")
                return glb_meshes(source, value.get("nativeOffset"), value.get("nativeScale", 1))
        raise ValueError("Local Workshop model is unavailable.")

    def resolve(self, identifiers, workshop_items=None):
        wanted = set(identifiers)
        if len(wanted) > 100000 or any(
            not isinstance(i, str) or not 1 <= len(i) <= 256 for i in wanted
        ):
            raise ValueError("Invalid Dungeon Alchemist model identifiers.")
        result = {}
        with self._connect() as connection:
            for identifier in sorted(wanted):
                row = connection.execute(
                    "SELECT format, payload FROM metadata WHERE id=?", (identifier,)
                ).fetchone()
                if row and row[0] == 1:
                    try:
                        value = json.loads(row[1])
                        if value["block"]["Id"] == identifier and isinstance(value["model"], dict):
                            result[identifier] = value
                    except (ValueError, KeyError, TypeError):
                        pass
        missing = wanted - result.keys()
        if not missing:
            return result
        if self.executable:
            executable = installation(self.executable)
            database = executable.parent / DATABASE
            blocks = {
                b["Id"]: b
                for b in _read_json(database / "BuildingBlocks.json")
                if isinstance(b, dict) and "Id" in b
            }
            models = {
                m["Id"]: m
                for m in _read_json(database / "ModelStaticData.json")
                if isinstance(m, dict) and "Id" in m
            }
            for identifier in missing:
                block = blocks.get(identifier)
                if block and block.get("modelId") in models:
                    result[identifier] = {"block": block, "model": models[block["modelId"]]}
            roots = (
                self.workshop_roots
                if self.workshop_roots is not None
                else local_workshop_roots(executable)
            )
            workshop_items = workshop_items or {}
            workshop_ids = {
                str(workshop_items.get(i, {}).get("description", {}).get("publishedWorkshopId", ""))
                for i in wanted - result.keys()
            }
            for root in roots:
                for workshop_id in sorted(workshop_ids):
                    if not re.fullmatch(r"[0-9]{1,20}", workshop_id):
                        continue
                    directory = Path(root) / workshop_id
                    if not directory.is_dir():
                        continue
                    # DA stores each model's JSON exactly one directory below the item.
                    for path in directory.glob("*/*.json"):
                        try:
                            value = _read_json(path)
                        except (OSError, ValueError):
                            continue
                        if not isinstance(value, dict) or not isinstance(
                            value.get("staticData"), dict
                        ):
                            continue
                        for block in value.get("configs", []):
                            if isinstance(block, dict) and block.get("Id") in wanted:
                                result[block["Id"]] = {"block": block, "model": value["staticData"]}
        with self._connect() as connection:
            for identifier, value in result.items():
                connection.execute(
                    "INSERT OR REPLACE INTO metadata VALUES (?, 1, ?)",
                    (identifier, json.dumps(value, ensure_ascii=True, allow_nan=False)),
                )
        missing = wanted - result.keys()
        if missing:
            items = workshop_items or {}
            raise MissingAlchemistItems(
                [
                    f"{items.get(i, {}).get('description', {}).get('name', i)} ({i})"
                    if items.get(i, {}).get("description", {}).get("name")
                    else i
                    for i in sorted(missing)
                ]
            )
        return result
