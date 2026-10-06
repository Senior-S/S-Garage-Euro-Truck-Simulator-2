"""Read-only import of local Euro Truck Simulator 2 vehicle assets."""

from __future__ import annotations

import hashlib
from io import BytesIO
import json
import math
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zlib
from concurrent.futures import CancelledError
from pathlib import Path
from typing import Any

if __package__:
    from .converter_formats import DefinitionBundle, read_viewer_model
else:
    from converter_formats import DefinitionBundle, read_viewer_model

try:
    import winreg
except ImportError:  # This module can be inspected and parser-tested off Windows.
    winreg = None

try:
    from PIL import Image
except ImportError:  # Pillow is optional; geometry remains usable without textures.
    Image = None


_IMPORT_LOCK = threading.RLock()
_FLOAT = re.compile(r"&([0-9a-fA-F]{8})|[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
_FIELD = re.compile(r'^\s*([\w\[\].]+)\s*:\s*(.*?)\s*$')
_BLOCK = re.compile(r'([\w]+)\s*\{')
_STRUCTURE = re.compile(r'\\.|["{}]')
_BRACES = re.compile(r'[{}]')
_WHEEL_DEF_DIRS = ("f_tire", "r_tire", "f_disc", "r_disc", "f_hub", "r_hub", "f_nuts", "r_nuts", "f_cover", "r_cover", "f_rim", "r_rim")


def _unquote(value: str) -> str:
    return value.strip().strip('"')


def _display_name(name: str, unit: str) -> str:
    if name.startswith("@@") and name.endswith("@@"):
        name = name[2:-2]
    if not name or name.startswith("@@"):
        name = unit.rsplit(".", 1)[-1]
    return re.sub(r"\s+", " ", name.replace("_", " ").replace(".", " ")).strip().title()


def _blocks(text: str, kind: str) -> list[str]:
    """Return balanced bodies for SCS text blocks of the requested kind."""
    bodies = []
    for match in re.finditer(rf'\b{re.escape(kind)}\s*\{{', text):
        start = match.end()
        depth = 1
        quoted = False
        # Numeric mesh streams contain millions of characters but few delimiters.
        for token in _STRUCTURE.finditer(text, start):
            char = token[0][-1]
            if char == '"' and len(token[0]) == 1:
                quoted = not quoted
            if not quoted:
                if char == '{':
                    depth += 1
                elif char == '}':
                    depth -= 1
                    if depth == 0:
                        bodies.append(text[start:token.end() - 1])
                        break
    return bodies


def _properties(text: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    depth = 0
    for line in text.splitlines():
        visible = line.split("{", 1)[0] if depth == 0 else ""
        if visible:
            match = _FIELD.match(visible)
            if match:
                result.setdefault(match.group(1), []).append(_unquote(match.group(2)))
        depth += line.count("{") - line.count("}")
    return result


def _numbers(value: str) -> list[float]:
    numbers = []
    for match in _FLOAT.finditer(value):
        token = match.group(0)
        number = struct.unpack('>f', bytes.fromhex(token[1:]))[0] if token.startswith('&') else float(token)
        if math.isfinite(number):
            numbers.append(number)
    return numbers


def _vectors(block: str) -> list[float]:
    return [component for match in re.finditer(r'\(\s*([^()]*)\)', block) for component in _numbers(match.group(1))]


def _float_text(text: str) -> list[float]:
    return _numbers(text)


def _find_steam_roots() -> list[Path]:
    roots: list[Path] = []
    if winreg is None:
        return roots
    for key_path in (r"SOFTWARE\WOW6432Node\Valve\Steam", r"SOFTWARE\Valve\Steam"):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "InstallPath")
                roots.append(Path(value))
        except OSError:
            pass
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            value, _ = winreg.QueryValueEx(key, "SteamPath")
            roots.append(Path(value))
    except OSError:
        pass
    return list(dict.fromkeys(roots))


def _library_paths(steam_root: Path) -> list[Path]:
    libraries = [steam_root]
    manifest = steam_root / "steamapps" / "libraryfolders.vdf"
    if manifest.is_file():
        for value in re.findall(r'"path"\s*"([^"]+)"', manifest.read_text(encoding="utf-8", errors="replace")):
            libraries.append(Path(value.replace("\\\\", "\\")))
    return list(dict.fromkeys(libraries))


def _detect_game_path() -> Path | None:
    override = os.environ.get("ETS2_GAME_PATH")
    if override:
        return Path(override).expanduser()
    for steam_root in _find_steam_roots():
        for library in _library_paths(steam_root):
            candidate = library / "steamapps" / "common" / "Euro Truck Simulator 2"
            if (candidate / "base.scs").is_file():
                return candidate
    return None


class AssetStore:
    def __init__(self, game_path: str | None = None, cache_path: Path | None = None, *, tool_path: str | None = None):
        self.game_path = Path(game_path).expanduser() if game_path else _detect_game_path()
        configured_tool = tool_path if tool_path is not None else os.environ.get("ETS_GARAGE_CONVERTER") or os.environ.get("ETS2_CONVERTER_PIX")
        if configured_tool:
            self.tool_path = Path(configured_tool).expanduser()
        else:
            local_tool = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "tools" / "converter_pix.exe"
            found = shutil.which("converter_pix") or shutil.which("converter_pix.exe")
            temp_tool = Path(os.environ.get("TEMP", "")) / "ets2-custom-builds" / "converter_pix.exe"
            self.tool_path = local_tool if local_tool.is_file() else Path(found) if found else temp_tool
        local_app_data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        self.cache_path = Path(cache_path).expanduser() if cache_path else Path(os.environ.get("ETS2_CACHE_PATH", local_app_data / "ETS2Garage" / "cache"))
        self.lock = _IMPORT_LOCK
        self._parser_fingerprint = hashlib.sha256(Path(__file__).read_bytes() + b"\0" +
                                                 Path(__file__).with_name("converter_formats.py").read_bytes()).hexdigest()
        self.mod_sources: list[Path] = []
        self._mod_fingerprint = ""
        self._catalog: list[dict[str, Any]] | None = None
        self._model_cache: dict[str, str] = {}
        self.texture_files: dict[str, Path] = {}
        self.progress = None
        self._definitions = {}
        self._definition_catalog = None
        self._bundles = {}
        self._converter_features = None
        self._batch_failures = {}
        self._cache_migration_required = None

    def set_mod_sources(self, sources: list[str | Path]) -> None:
        """Mount discovered local assets and saved mods in load order."""
        requested = [Path(source).expanduser() for source in sources]
        missing = [str(source) for source in requested if not source.exists()]
        if missing:
            raise FileNotFoundError(f"Mod sources not found: {', '.join(missing)}")
        with _IMPORT_LOCK:
            if requested == self.mod_sources:
                return
            self.mod_sources = requested
            self._mod_fingerprint = ""
            if self.mod_sources:
                digest = hashlib.sha256()
                for source in self.mod_sources:
                    directory = source.is_dir()
                    files = sorted(source.rglob("*") if directory else [source])
                    digest.update(f"{source.resolve()}\n".encode())
                    for index, file in enumerate(files):
                        if self.progress and index % 64 == 0:
                            self.progress("Checking mod files", source.name, index, len(files))
                        try:
                            metadata = file.stat()
                        except FileNotFoundError:
                            # Match is_file() for removed files or broken links.
                            continue
                        if stat.S_ISREG(metadata.st_mode):
                            digest.update(f"{file.relative_to(source) if directory else file.name}:{metadata.st_size}:{metadata.st_mtime_ns}\n".encode())
                self._mod_fingerprint = digest.hexdigest()
            self._catalog = None
            self._definitions.clear()
            self._definition_catalog = None
            self._model_cache.clear()
            self.texture_files.clear()
            self._bundles.clear()
            self._batch_failures.clear()

    def status(self) -> dict[str, Any]:
        archives = self._archives() if self.game_path and self.game_path.is_dir() else []
        ready = bool(self.game_path and self.game_path.is_dir() and archives and self.tool_path.is_file())
        message = "Asset import is ready." if ready else ""
        if not self.game_path or not self.game_path.is_dir():
            message = "ETS2 install not found. Set ETS2_GAME_PATH or pass game_path to AssetStore."
        elif not archives:
            message = f"No ETS2 .scs archives found under {self.game_path}."
        elif not self.tool_path.is_file():
            message = "ConverterPIX not found. Set ETS2_CONVERTER_PIX to converter_pix.exe."
        return {
            "gamePath": str(self.game_path) if self.game_path else None,
            "cachePath": str(self.cache_path),
            "previewVersion": self._fingerprint() + ":" + self._parser_fingerprint,
            "ready": ready,
            "toolPath": str(self.tool_path),
            "message": message,
            "cacheMigrationRequired": self.cache_migration_required() if ready else False,
        }

    def cache_migration_required(self) -> bool:
        """Detect legacy exports once before status or catalog loading can reuse them."""
        if self._cache_migration_required is not None:
            return self._cache_migration_required
        features = self._converter_capabilities()
        if not features.get("definitionBundle") or not features.get("viewerGeometry"):
            return False
        catalogs = self.cache_path / "catalog"
        legacy_catalog = catalogs.is_dir() and any(
            folder.is_dir() and not (folder / "definitions.sgbundle").is_file() and any(folder.iterdir())
            for folder in catalogs.iterdir())
        models = self.cache_path / "models"
        self._cache_migration_required = bool(legacy_catalog or models.is_dir() and next(models.rglob("*.pim"), None))
        return self._cache_migration_required

    def rebuild_cache(self) -> None:
        """Remove only owned asset cache trees after the application obtains acceptance."""
        with _IMPORT_LOCK:
            if not self.cache_migration_required():
                return
            root = self.cache_path.resolve()
            targets = [root / name for name in ("catalog", "models")]
            # Validate every target before removing any files, including redirected folders.
            for target in targets:
                if target.resolve().parent != root or target.is_symlink() or getattr(target, "is_junction", lambda: False)():
                    raise ValueError(f"Asset cache folder is redirected outside its expected location: {target}")
                if target.exists() and not target.is_dir():
                    raise ValueError(f"Asset cache folder is not a directory: {target}")
            if self.progress:
                self.progress("Clearing old asset cache", "Removing imported definitions, models, and textures.")
            for target in targets:
                if target.exists():
                    shutil.rmtree(target)
            self._catalog = None
            self._definition_catalog = None
            self._definitions.clear()
            self._model_cache.clear()
            self.texture_files.clear()
            self._bundles.clear()
            self._batch_failures.clear()
            self.__dict__.pop("_paint_jobs", None)
            self._cache_migration_required = False

    def _archives(self) -> list[Path]:
        base_archives = sorted(self.game_path.glob("*.scs"), key=lambda path: path.name.casefold()) if self.game_path else []
        return base_archives + self.mod_sources

    def _fingerprint(self) -> str:
        digest = hashlib.sha256(b"ets-garage-assets-v2\n")
        for archive in self._archives():
            stat = archive.stat()
            digest.update(f"{archive.resolve()}:{stat.st_size}:{stat.st_mtime_ns}\n".encode())
        digest.update(self._mod_fingerprint.encode())
        return digest.hexdigest()

    def _converter_capabilities(self) -> dict:
        """Probe once per executable revision, keeping upstream tools usable."""
        try:
            metadata = self.tool_path.stat()
        except OSError:
            return {}
        revision = (str(self.tool_path.resolve()), metadata.st_size, metadata.st_mtime_ns)
        if self._converter_features is not None and self._converter_features[0] == revision:
            return self._converter_features[1]
        features = {}
        try:
            options = {"capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace", "timeout": 10,
                       "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
            help_result = subprocess.run([str(self.tool_path), "--help"], **options)
            if help_result.returncode == 0 and "--garage-capabilities" in help_result.stdout:
                result = subprocess.run([str(self.tool_path), "--garage-capabilities"], **options)
            else:
                result = help_result
            if result.returncode == 0 and "--garage-capabilities" in help_result.stdout:
                for line in result.stdout.splitlines():
                    if not line.startswith("{"):
                        continue
                    candidate = json.loads(line)
                    if isinstance(candidate, dict) and candidate.get("garageFormatVersion") == 1:
                        features = candidate
                        break
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
        self._converter_features = revision, features
        return features

    def _truckersmp_archive(self, source: Path, cancelled=None) -> Path:
        """Normalize readable TruckersMP HashFS v1 flags in a cached copy."""
        if source.suffix.casefold() != ".mp":
            return source
        metadata = source.stat()
        signature = hashlib.sha256(f"tmp-flags-v1:{source.resolve()}:{metadata.st_size}:{metadata.st_mtime_ns}".encode()).hexdigest()
        target = self.cache_path / "truckersmp" / f"{signature}.mp"
        if target.is_file():
            return target
        with source.open("rb") as archive:
            header = archive.read(32)
            if len(header) != 32 or header[:6] != b"SCS#\x01\x00":
                return source
            count, offset = struct.unpack_from("<II", header, 12)
            if offset < 32 or offset + count * 32 > metadata.st_size:
                raise RuntimeError(f"Invalid TruckersMP archive table: {source.name}")
            archive.seek(offset)
            table = bytearray(archive.read(count * 32))
            changed = False
            for index in range(count):
                if cancelled and cancelled():
                    raise CancelledError()
                _, location, flags, _, size, packed_size = struct.unpack_from("<QQIIII", table, index * 32)
                if not flags & 8:
                    continue
                if location + packed_size > metadata.st_size or size > 256 * 1024 * 1024:
                    raise RuntimeError(f"Invalid TruckersMP archive entry: {source.name}")
                if flags & 2:
                    archive.seek(location)
                    try:
                        decoder = zlib.decompressobj()
                        payload = decoder.decompress(archive.read(packed_size), size + 1)
                    except zlib.error as error:
                        raise RuntimeError(f"TruckersMP archive contains an unreadable encrypted entry: {source.name}") from error
                    if len(payload) != size or not decoder.eof or decoder.unused_data:
                        raise RuntimeError(f"Invalid TruckersMP entry size: {source.name}")
                struct.pack_into("<I", table, index * 32 + 16, flags & ~8)
                changed = True
        if not changed:
            return source
        if self.progress:
            self.progress("Preparing TruckersMP assets", source.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        os.close(descriptor)
        try:
            shutil.copyfile(source, temporary)
            with open(temporary, "r+b") as copy:
                copy.seek(offset)
                copy.write(table)
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return target

    def _run(self, arguments: list[str], timeout: int = 300, cancelled=None, *, partial_batch=False) -> str:
        archives = self._archives()
        if not self.game_path or not self.game_path.is_dir() or not archives or not self.tool_path.is_file():
            raise RuntimeError(self.status()["message"])
        features = self._converter_capabilities()
        arguments = list(arguments)
        if features.get("definitionBundle") and "--extract-directory" in arguments:
            index = arguments.index("--extract-directory")
            if arguments[index + 1] == "/def/vehicle":
                arguments[index] = "--extract-bundle"
                target = arguments.index("-e") + 1
                arguments[target] = str(Path(arguments[target]) / "definitions.sgbundle")
        if "-m" in arguments or "--batch" in arguments:
            if features.get("viewerGeometry"):
                arguments.append("--viewer-geometry")
            if features.get("garagePreview"):
                arguments.append("--garage-preview")
        mounted = [self._truckersmp_archive(archive, cancelled) for archive in archives]
        command = [str(self.tool_path), *(part for archive in mounted for part in ("-b", str(archive))), *arguments]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        deadline = time.monotonic() + timeout
        while True:
            if cancelled and cancelled():
                process.kill()
                process.communicate()
                raise CancelledError()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                process.communicate()
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                stdout, stderr = process.communicate(timeout=min(0.1, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        output = (stdout + "\n" + stderr).strip()
        if not partial_batch and (process.returncode or re.search(r"(?:^|\s)(?:ERROR|FATAL)(?:\s|:)|<error>\s*\d*", output, re.I)):
            raise RuntimeError(f"ConverterPIX failed ({process.returncode}): {output[-3000:]}")
        return output

    def ensure_catalog(self) -> list[dict[str, Any]]:
        if self.cache_migration_required():
            raise ValueError("The asset cache format changed. Accept the cache rebuild notice to continue.")
        if self._catalog is not None:
            return self._catalog
        if self.progress:
            self.progress("Waiting for game assets", "Another import may be using the disk.")
        with _IMPORT_LOCK:
            # Another request can finish the import while this one waits.
            if self._catalog is not None:
                return self._catalog
            fingerprint = self._fingerprint()
            root = self.cache_path / "catalog" / fingerprint
            index_path = root / "catalog.json"
            if index_path.is_file():
                if self.progress:
                    self.progress("Reading cached catalog", "Reusing imported game definitions.")
                try:
                    cached = json.loads(index_path.read_text(encoding="utf-8"))
                    if not isinstance(cached, list) or any(not isinstance(entry, dict) for entry in cached):
                        raise ValueError("Invalid catalog cache.")
                    self._catalog = [self._enrich_catalog_entry(entry) for entry in cached]
                    return self._catalog
                except (ValueError, TypeError, KeyError):
                    # A partial cache from an interrupted older import is rebuilt.
                    pass
            root.mkdir(parents=True, exist_ok=True)
            if self.progress:
                self.progress("Importing game definitions", "First import can take several minutes on a hard disk. Keep the garage open.")
            self._run(["-e", str(root), "--extract-directory", "/def/vehicle"], timeout=900)
            catalog = [self._enrich_catalog_entry(entry) for entry in self._read_catalog(root)]
            if self.progress:
                self.progress("Saving catalog cache", f"{len(catalog):,} parts indexed. Later launches reuse this cache.")
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=root, suffix=".tmp", delete=False) as temporary:
                json.dump(catalog, temporary, ensure_ascii=False, separators=(",", ":"))
            try:
                os.replace(temporary.name, index_path)
            except OSError as error:
                if getattr(error, "winerror", None) != 17:
                    raise
                index_path.write_text(Path(temporary.name).read_text("utf-8"), encoding="utf-8")
            finally:
                Path(temporary.name).unlink(missing_ok=True)
            self._catalog = catalog
            return self._catalog

    def catalog(self) -> list[dict[str, Any]]:
        return self.ensure_catalog()

    def _definition_bundle(self, root: Path):
        path = root / "definitions.sgbundle"
        if not path.is_file():
            return None
        metadata = path.stat()
        revision = metadata.st_size, metadata.st_mtime_ns
        cached = self._bundles.get(root)
        if cached is None or cached[0] != revision:
            cached = revision, DefinitionBundle(path)
            self._bundles[root] = cached
        return cached[1]

    def _definition_text(self, file: Path, root: Path, cancelled=None) -> str:
        if cancelled and cancelled():
            raise CancelledError()
        file, root = Path(os.path.abspath(file)), Path(os.path.abspath(root))
        if not file.is_relative_to(root):
            raise ValueError(f"Definition include is outside the catalog: {file}")
        virtual_path = "/" + file.relative_to(root).as_posix()
        bundle = self._definition_bundle(root)
        if bundle is not None and virtual_path in bundle:
            return bundle.read_text(virtual_path)
        if not file.is_file():
            file.parent.mkdir(parents=True, exist_ok=True)
            self._run(["-e", str(root), "--extract-file", virtual_path], cancelled=cancelled)
        return file.read_text(encoding="utf-8", errors="replace")

    def _read_catalog(self, root: Path) -> list[dict[str, Any]]:
        entries = []
        groups = []
        bundle = self._definition_bundle(root)
        for family in ("truck", "trailer_owned"):
            defs_root = root / "def" / "vehicle" / family
            paths = (root / path.lstrip("/") for path in bundle.paths
                     if path.casefold().startswith(f"/def/vehicle/{family}/") and path.casefold().endswith(".sii")) if bundle else defs_root.rglob("*.sii")
            groups.append((None, sorted(paths)))
        for family in ("", "trailer_wheel"):
            for directory in _WHEEL_DEF_DIRS:
                defs_root = root / "def" / "vehicle" / family / directory
                prefix = "/" + defs_root.relative_to(root).as_posix() + "/"
                paths = (root / path.lstrip("/") for path in bundle.paths
                         if path.casefold().startswith(prefix.casefold()) and path.casefold().endswith(".sii")) if bundle else defs_root.rglob("*.sii")
                groups.append((directory, sorted(paths)))
        hookup_root = root / "def" / "vehicle" / "addon_hookups"
        paths = (root / path.lstrip("/") for path in bundle.paths
                 if path.casefold().startswith("/def/vehicle/addon_hookups/") and Path(path).suffix.casefold() in (".sii", ".sui")) if bundle else (
                     file for file in hookup_root.rglob("*") if file.suffix.casefold() in (".sii", ".sui"))
        groups.append(("hookup", sorted(paths)))
        total = sum(len(files) for _, files in groups)
        completed = 0
        for directory, files in groups:
            definitions = bundle.iter_texts("/" + file.relative_to(root).as_posix() for file in files) if bundle else (
                ("/" + file.relative_to(root).as_posix(), file.read_text(encoding="utf-8", errors="replace")) for file in files)
            for relative, definition in definitions:
                file = root / relative.lstrip("/")
                if self.progress and completed % 64 == 0:
                    self.progress("Indexing parts", file.name, completed, total)
                for record_type, unit, body in _records(definition):
                    if directory != "hookup" and (not record_type.startswith("accessory_") or not record_type.endswith("_data")):
                        continue
                    category = directory or record_type.removeprefix("accessory_").removesuffix("_data")
                    entries.append(self._catalog_entry(relative + ("#" + unit if directory == "hookup" else ""), unit, category, file, _properties(body), record_type))
                completed += 1
        if self.progress:
            self.progress("Indexing parts", f"{len(entries):,} parts found.", total, total)
        return entries

    @staticmethod
    def _catalog_entry(path: str, unit: str, category: str, file: Path, fields: dict[str, list[str]], unit_type: str | None = None) -> dict[str, Any]:
        values = {key: items[-1] for key, items in fields.items() if items}
        parts = file.parts
        truck_index = next((i for i, part in enumerate(parts) if part.casefold() in ("truck", "trailer_owned")), -1)
        brand = parts[truck_index + 1] if truck_index >= 0 and truck_index + 1 < len(parts) else ""
        path_parts = Path(path.split("#", 1)[0]).parts
        vehicle_parts = path.lstrip("/").split("/")
        if len(vehicle_parts) > 4 and vehicle_parts[2] in ("truck", "trailer_owned") and vehicle_parts[4] != "data.sii":
            category = vehicle_parts[4]
        accessory_index = next((i for i, part in enumerate(path_parts) if part.casefold() == "accessory"), -1)
        if accessory_index >= 0 and accessory_index + 1 < len(path_parts):
            category = path_parts[accessory_index + 1]
        info = fields.get("info[]", [])
        name = _display_name(values.get("name") or (info[-1] if info else ""), unit)
        model_values = values.get("model") or values.get("model[]") or values.get("detail_model")
        exterior_model = values.get("ext_model") or values.get("ext_model[]")
        return {
            "path": path,
            "name": name,
            "category": category,
            "brand": brand,
            "unitType": unit_type or ("addon_hookup_data" if category == "hookup" else f"accessory_{category}_data"),
            "unitName": unit,
            "unitId": unit,
            "id": unit,
            "baseModel": model_values,
            "model": values.get("exterior_model") or values.get("exterior_model[]") or exterior_model or model_values or values.get("interior_model") or values.get("interior_model[]"),
            "extModel": exterior_model,
            "extLook": values.get("ext_look"),
            "extVariant": values.get("ext_variant"),
            "exteriorModel": values.get("exterior_model") or values.get("exterior_model[]"),
            "exteriorLook": values.get("exterior_look"),
            "exteriorVariant": values.get("exterior_variant"),
            "interiorModel": values.get("interior_model") or values.get("interior_model[]"),
            "interiorLook": values.get("interior_look"),
            "interiorVariant": values.get("interior_variant"),
            "variant": values.get("variant"),
            "look": values.get("look"),
            "icon": values.get("icon"),
            "price": _number_or_none(values.get("price")),
            "unit": unit,
            "sourcePath": path.split("#", 1)[0],
            "fields": values,
        }

    @staticmethod
    def _enrich_catalog_entry(entry: dict[str, Any]) -> dict[str, Any]:
        fields = entry.get("fields", {})
        source_path = entry.get("sourcePath") or entry["path"].split("#", 1)[0]
        path_parts = Path(source_path.lstrip("/")).parts
        vehicle_parts = source_path.lstrip("/").split("/")
        if len(vehicle_parts) > 4 and vehicle_parts[2] in ("truck", "trailer_owned") and vehicle_parts[4] != "data.sii":
            entry["category"] = vehicle_parts[4]
        if "accessory" in path_parts:
            index = path_parts.index("accessory") + 1
            if index < len(path_parts):
                entry["category"] = path_parts[index]
        entry["sourcePath"] = source_path
        entry["name"] = _display_name(entry.get("name") or fields.get("name", ""), entry.get("unitId", entry["path"]))
        entry["exteriorModel"] = entry.get("exteriorModel") or fields.get("exterior_model") or fields.get("exterior_model[]")
        entry["exteriorLook"] = entry.get("exteriorLook") or fields.get("exterior_look")
        entry["exteriorVariant"] = entry.get("exteriorVariant") or fields.get("exterior_variant")
        entry["interiorModel"] = entry.get("interiorModel") or fields.get("interior_model") or fields.get("interior_model[]")
        entry["interiorLook"] = entry.get("interiorLook") or fields.get("interior_look")
        entry["interiorVariant"] = entry.get("interiorVariant") or fields.get("interior_variant")
        entry["extModel"] = entry.get("extModel") or fields.get("ext_model") or fields.get("ext_model[]")
        entry["extLook"] = entry.get("extLook") or fields.get("ext_look")
        entry["extVariant"] = entry.get("extVariant") or fields.get("ext_variant")
        entry["baseModel"] = entry.get("baseModel") or fields.get("model") or fields.get("model[]") or fields.get("detail_model") or (entry.get("model") if not (entry.get("exteriorModel") or entry.get("extModel") or entry.get("interiorModel")) else None)
        entry["model"] = entry.get("exteriorModel") or entry.get("extModel") or entry.get("baseModel") or entry.get("interiorModel")
        if entry.get("unitId"):
            entry["unitName"] = entry["unitId"]
            entry["id"] = entry["unitId"]
        return entry

    def definition(self, path_or_unit: str) -> dict[str, Any]:
        """Resolve either a definition path or SII unit ID from the imported catalog."""
        with _IMPORT_LOCK:
            catalog = self.ensure_catalog()
            if self._definition_catalog is not catalog:
                self._definitions = {value.casefold(): entry for entry in catalog
                                     for value in (entry["path"], entry.get("unitId", ""), entry.get("unitName", "")) if value}
                self._definition_catalog = catalog
            return self._definitions.get(path_or_unit.casefold())

    def head_lights(self, path: str, cancelled=None, *, auxiliary=False) -> dict:
        """Export the installed headlight definition and its projection masks."""
        fields = (self.definition(path) or {}).get("fields", {})
        export = self.cache_path / "lights" / self._fingerprint()
        masks, diagnostics = {}, []
        for mode in ("low_beam", "hi_beam", *(("front_beam", "roof_beam") if auxiliary else ())):
            resource = _unquote(fields.get(mode + "_mask", ""))
            if not resource:
                continue
            base = resource.removesuffix(".tobj")
            target = export / (base.lstrip("/") + ".dds")
            try:
                if not target.is_file() and not target.with_suffix(".png").is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    self._run(["-e", str(export), "-t", resource], cancelled=cancelled)
                url = _texture_url({"texture_base": base}, export, ignore_alpha=True)
                if not url:
                    raise FileNotFoundError(resource)
                relative = url.removeprefix("/cache/")
                self.texture_files[relative] = (self.cache_path / relative).resolve()
                masks[mode] = url
            except (RuntimeError, FileNotFoundError) as error:
                diagnostics.append(f"{mode}: projection mask unavailable; using an approximate beam. {error}")
        return {"fields": fields, "masks": masks, "diagnostics": diagnostics}

    def paint_job(self, path: str, cancelled=None, textures=True, *, include_overrides=True, accessory_key=None, accessory_keys=None, _entry=None, _fingerprint=None) -> dict:
        """Import paint masks once, including the game's accessory overrides."""
        with _IMPORT_LOCK:
            if cancelled and cancelled():
                raise CancelledError()
            cache = self.__dict__.setdefault("_paint_jobs", {})
            fingerprint = _fingerprint or self._fingerprint()
            selected_keys = frozenset(accessory_keys) if accessory_keys is not None else None
            key = (fingerprint, path, textures, include_overrides, accessory_key, selected_keys)
            if key in cache:
                return cache[key]
            entry = _entry or self.definition(path)
            if not entry:
                return {}
            root = self.cache_path / "catalog" / fingerprint
            def expand(file, visited=()):
                file = Path(os.path.abspath(file))
                if file in visited:
                    raise ValueError(f"Circular paint job include: {file}")
                return re.sub(r'@include\s+"([^"\n]+)"', lambda match: expand(file.parent / match[1], (*visited, file)),
                              self._definition_text(file, root, cancelled))
            text = expand(root / entry["sourcePath"].lstrip("/"))
            settings = next(_properties(body) for kind, unit, body in _records(text) if unit == entry["unitId"])
            if not textures:
                result = {"fields": {name: values[-1] for name, values in settings.items()}, "suitableFor": settings.get("suitable_for[]", [])}
                cache[key] = result
                return result
            overrides = {}
            definition_file = root / entry["sourcePath"].lstrip("/")
            override_file = definition_file.parent / "accessory" / definition_file.name
            bundle = self._definition_bundle(root)
            if include_overrides and (override_file.is_file() or bundle is not None and "/" + override_file.relative_to(root).as_posix() in bundle):
                for kind, unit, body in _records(expand(override_file)):
                    if kind == "simple_paint_job_data":
                        values = _properties(body)
                        for accessory in values.get("acc_list[]", []):
                            accessory = _unquote(accessory)
                            if (accessory_key is None or accessory == accessory_key) and (selected_keys is None or accessory in selected_keys):
                                overrides[accessory] = values
            export = self.cache_path / "models" / hashlib.sha256(str(key[:3]).encode()).hexdigest()[:20]
            def mask(values):
                resource = _unquote(values.get("paint_job_mask", [""])[-1])
                if not resource:
                    return None
                base = resource.removesuffix(".tobj")
                target = export / (base.lstrip("/") + ".dds")
                if not target.is_file() and not target.with_suffix(".png").is_file():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    self._run(["-e", str(export), "-t", resource], cancelled=cancelled)
                url = _texture_url({"texture_base": base}, export, ignore_alpha=_unquote(settings.get("airbrush", ["false"])[-1]) != "true")
                if not url:
                    raise FileNotFoundError(f"Paint mask export is missing: {resource}")
                relative = url.removeprefix("/cache/")
                self.texture_files[relative] = (self.cache_path / relative).resolve()
                return url
            result = {"fields": {name: values[-1] for name, values in settings.items()}, "texture": mask(settings),
                      "overrides": {}, "diagnostics": []}
            failed_masks = {}
            for name, values in overrides.items():
                resource = _unquote(values.get("paint_job_mask", [""])[-1])
                try:
                    if resource in failed_masks:
                        raise FileNotFoundError(failed_masks[resource])
                    result["overrides"][name] = mask(values)
                except (FileNotFoundError, RuntimeError) as error:
                    failed_masks[resource] = str(error)
                    result["diagnostics"].append(f"Paint override for {name} unavailable: {resource}. Using the main paint texture.")
            cache[key] = result
            return result

    def _model_paths(self, entry: dict, look=None, variant=None, *, fingerprint=None):
        """Keep model selection and cache destinations identical for single and batch imports."""
        fields = entry.get("fields", {})
        model_options = (
            (entry.get("exteriorModel"), entry.get("exteriorLook"), entry.get("exteriorVariant")),
            (entry.get("extModel"), entry.get("extLook"), entry.get("extVariant")),
            (entry.get("baseModel") or fields.get("model") or fields.get("model[]") or fields.get("detail_model"), entry.get("look"), entry.get("variant")),
            (entry.get("interiorModel"), entry.get("interiorLook") or entry.get("look"), entry.get("interiorVariant") or entry.get("variant")),
        )
        selected = next(((path, model_look, model_variant) for path, model_look, model_variant in model_options if path), None)
        if selected is None:
            raise ValueError(f"{entry['path']} has no model path; this is a model-less definition.")
        model_value, model_look, model_variant = selected
        model_path = _unquote(model_value[-1] if isinstance(model_value, list) else model_value).replace("\\", "/").removesuffix(".pmd")
        look = _unquote(look) if look else model_look
        variant = _unquote(variant) if variant else model_variant
        fingerprint = fingerprint or self._fingerprint()
        cache_key = hashlib.sha256(f"{fingerprint}:{self._parser_fingerprint}:{entry['path']}:{look}:{variant}".encode()).hexdigest()
        key = hashlib.sha256((fingerprint + model_path).encode()).hexdigest()[:20]
        export = self.cache_path / "models" / key
        return model_path, look, variant, cache_key, export, export / "parsed" / f"{cache_key}.json"

    def prepare_models(self, requests, cancelled=None) -> None:
        """Convert uncached fitted models together without loading their geometry into memory."""
        with _IMPORT_LOCK:
            if cancelled and cancelled():
                raise CancelledError()
            if not self._converter_capabilities().get("batch"):
                return
            self._batch_failures.clear()
            fingerprint = self._fingerprint()
            jobs = {}
            for path, look, variant in requests:
                if cancelled and cancelled():
                    raise CancelledError()
                entry = self.definition(path)
                if not entry:
                    continue
                try:
                    model_path, _, _, cache_key, export, parsed = self._model_paths(entry, look, variant, fingerprint=fingerprint)
                except ValueError:
                    continue
                if cache_key in self._model_cache or parsed.is_file():
                    continue
                geometry = export / (model_path.lstrip("/") + ".pim")
                incomplete = geometry.with_suffix(".export-incomplete")
                if not incomplete.exists() and (geometry.is_file() or geometry.with_suffix(".sgm").is_file()):
                    continue
                if any(character in value for value in (model_path, str(export)) for character in "\t\r\n"):
                    raise ValueError("Model paths cannot contain tabs or line breaks in a converter batch.")
                jobs[model_path] = export, incomplete
            if not jobs:
                return
            self.cache_path.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.cache_path, suffix=".tsv", delete=False) as manifest:
                for model_path, (export, incomplete) in jobs.items():
                    incomplete.parent.mkdir(parents=True, exist_ok=True)
                    incomplete.write_text("ConverterPIX batch export did not finish.\n", encoding="utf-8")
                    manifest.write(f"model\t{model_path}\t{export}\n")
            try:
                if self.progress:
                    self.progress("Converting fitted models", f"{len(jobs)} uncached models share one archive mount.", 0, len(jobs))
                output = self._run(["--batch", manifest.name], timeout=max(300, 300 * len(jobs)), cancelled=cancelled, partial_batch=True)
                statuses = {}
                for line in output.splitlines():
                    if not line.startswith("{"):
                        continue
                    try:
                        status = json.loads(line)
                    except ValueError:
                        continue
                    index = status.get("garageJob") if isinstance(status, dict) else None
                    if type(index) is int and 0 <= index < len(jobs):
                        statuses[index] = status
                for index, (model_path, (_, incomplete)) in enumerate(jobs.items()):
                    status = statuses.get(index, {})
                    if status.get("success") is True and status.get("kind") == "model" and status.get("path") == model_path:
                        incomplete.unlink(missing_ok=True)
                    else:
                        self._batch_failures[incomplete] = f"ConverterPIX batch failed for {model_path}: {status.get('error') or output[-1500:]}"
                if self.progress:
                    self.progress("Converting fitted models", "Model conversion batch finished.", len(jobs), len(jobs))
            finally:
                Path(manifest.name).unlink(missing_ok=True)

    def model(self, definition_path: str, look: str | None = None, variant: str | None = None, cancelled=None, *, _entry=None) -> dict[str, Any]:
        with _IMPORT_LOCK:
            if cancelled and cancelled():
                raise CancelledError()
            catalog = self.ensure_catalog()
            if cancelled and cancelled():
                raise CancelledError()
            entry = _entry if _entry is not None else self.definition(definition_path)
            if entry is None:
                raise FileNotFoundError(f"No catalog definition found for {definition_path!r}.")
            fields = entry.get("fields", {})
            fingerprint = self._fingerprint()
            model_path, look, variant, cache_key, export, parsed_path = self._model_paths(entry, look, variant, fingerprint=fingerprint)
            if cache_key in self._model_cache:
                if cancelled and cancelled():
                    raise CancelledError()
                return self._model_result(self._model_cache[cache_key])
            if parsed_path.is_file():
                self._model_cache[cache_key] = parsed_path.read_text(encoding="utf-8")
                if cancelled and cancelled():
                    raise CancelledError()
                return self._model_result(self._model_cache[cache_key])
            pim_path = export / (model_path.lstrip("/") + ".pim")
            native_path = pim_path.with_suffix(".sgm")
            pit_path = export / (model_path.lstrip("/") + ".pit")
            incomplete_path = pim_path.with_suffix(".export-incomplete")
            if incomplete_path in self._batch_failures:
                raise RuntimeError(self._batch_failures[incomplete_path])
            if not (pim_path.is_file() or native_path.is_file()) or incomplete_path.exists():
                pim_path.parent.mkdir(parents=True, exist_ok=True)
                incomplete_path.write_text("ConverterPIX export did not finish.\n", encoding="utf-8")
                self._run(["-e", str(export), "-m", model_path], timeout=300, cancelled=cancelled)
            if cancelled and cancelled():
                raise CancelledError()
            geometry_path = native_path if native_path.is_file() else pim_path
            if not geometry_path.is_file():
                raise FileNotFoundError(f"ConverterPIX did not export geometry for {model_path}: {pim_path}")
            if Image is not None and pit_path.is_file():
                for material in _blocks(pit_path.read_text(encoding="utf-8", errors="replace"), "Material"):
                    properties = _properties(material)
                    effect = _unquote(properties.get("Effect", [""])[-1]).casefold().split(".")
                    if "glass" not in effect:
                        continue
                    for texture in _blocks(material, "Texture"):
                        texture_properties = _properties(texture)
                        if not texture_properties.get("Tag") or not texture_properties.get("Value") or "texture_base" not in texture_properties["Tag"][-1]:
                            continue
                        base = _unquote(texture_properties["Value"][-1])
                        if any((export / (base.lstrip("/") + suffix)).is_file() for suffix in (".dds", ".png")):
                            continue
                        incomplete_path.write_text("Glass texture export did not finish.\n", encoding="utf-8")
                        self._run(["-e", str(export), "-t", base + ".tobj"], timeout=120, cancelled=cancelled)
            model = _parse_model(geometry_path, pit_path if pit_path.is_file() else None, export, look, variant)
            if entry.get("category") == "interior" and fields.get("animated_model"):
                animated_path = entry["path"] + "#animated"
                try:
                    animated = self.model(animated_path, cancelled=cancelled, _entry={
                        "path": animated_path, "fields": {"model": fields["animated_model"]}})
                    model["steeringBones"] = animated.get("bones", [])
                    if not model["steeringBones"]:
                        model["diagnostics"].append("Steering skeleton unavailable; using the cab steering mount.")
                except (ValueError, FileNotFoundError, RuntimeError) as error:
                    model["diagnostics"].append(f"Steering skeleton unavailable; using the cab steering mount: {error}")
            if fields.get("data[]"):
                catalog_root = self.cache_path / "catalog" / fingerprint
                definition = catalog_root / entry["sourcePath"].lstrip("/")
                read_file = lambda file: self._definition_text(file, catalog_root, cancelled)
                properties = _patch_definition(definition, entry["unitId"], read_file=read_file, kind=None, all_values=True)
                for reference in properties["data[]"]:
                    toy = _patch_definition(definition, _unquote(reference), read_file=read_file, kind="physics_toy_data")
                    if toy is None:
                        raise ValueError(f"Physics toy definition unavailable: {reference} in {entry['sourcePath']}")
                    toy_path = entry["sourcePath"] + "#" + _unquote(reference)
                    child = self.model(toy_path, cancelled=cancelled, _entry={"path": toy_path, "fields": {"model": toy["phys_model"]}})
                    offset = _float_text(toy.get("locator_hook_offset", "(0, 0, 0)").split("#", 1)[0])
                    if len(offset) != 3 or not all(math.isfinite(value) for value in offset):
                        raise ValueError(f"Invalid physics toy attachment offset: {toy_path}")
                    # Physics meshes use the joint as their origin. Show their
                    # rest pose at the connection point on the accessory.
                    for piece in child["pieces"]:
                        piece["positions"] = [value + offset[index % 3] for index, value in enumerate(piece["positions"])]
                    model["pieces"].extend(child["pieces"])
            if fields.get("data"):
                catalog_root = self.cache_path / "catalog" / fingerprint
                definition = catalog_root / entry["sourcePath"].lstrip("/")
                patch = _patch_definition(definition, _unquote(fields["data"]), read_file=lambda file:
                    self._definition_text(file, catalog_root, cancelled))
                if patch:
                    material_path = _unquote(patch["material"])
                    material_file = export / material_path.lstrip("/")
                    if not material_file.is_file():
                        material_file.parent.mkdir(parents=True, exist_ok=True)
                        incomplete_path.write_text("Physics patch material export did not finish.\n", encoding="utf-8")
                        self._run(["-e", str(export), "--extract-file", material_path], cancelled=cancelled)
                    material = material_file.read_text(encoding="utf-8")
                    texture = re.search(r'\b(?:source|texture)\s*:\s*"([^"\n]+\.tobj)"', material)
                    if not texture:
                        raise ValueError(f"Physics patch material has no base texture: {material_path}")
                    texture_path = (Path(material_path).parent / texture[1]).as_posix()
                    base = texture_path.removesuffix(".tobj")
                    if not any((export / (base.lstrip("/") + suffix)).is_file() for suffix in (".dds", ".png")):
                        incomplete_path.write_text("Physics patch texture export did not finish.\n", encoding="utf-8")
                        self._run(["-e", str(export), "-t", texture_path], cancelled=cancelled)
                    texture_url = _texture_url({"texture_base": base}, export)
                    if not texture_url:
                        raise FileNotFoundError(f"Physics patch texture unavailable: {texture_path}")
                    anchors = [locator for locator in model["locators"] if locator["name"].startswith("anchor")]
                    if not anchors:
                        raise ValueError(f"Physics patch has no anchor locator: {definition_path}")
                    model["pieces"].extend(_patch_piece(patch, anchor, texture_url) for anchor in anchors)
            self._model_cache[cache_key] = json.dumps(model, separators=(",", ":"))
            parsed_path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=parsed_path.parent, prefix=f".{cache_key}.", suffix=".tmp", delete=False) as temporary:
                temporary.write(self._model_cache[cache_key])
            try:
                os.replace(temporary.name, parsed_path)
            except OSError as error:
                # EFS-protected LocalAppData can report same-directory replace as cross-device.
                if getattr(error, "winerror", None) != 17:
                    raise
                parsed_path.write_text(self._model_cache[cache_key], encoding="utf-8")
            finally:
                Path(temporary.name).unlink(missing_ok=True)
            incomplete_path.unlink(missing_ok=True)
            if cancelled and cancelled():
                raise CancelledError()
            return self._model_result(self._model_cache[cache_key])

    def _model_result(self, serialized: str) -> dict[str, Any]:
        model = json.loads(serialized)
        root = Path(os.path.abspath(self.cache_path))
        for piece in model.get("pieces", []):
            for name in ("texture", "lightMask", "lightAlpha"):
                texture = piece.get("material", {}).get(name)
                if texture and texture.startswith("/cache/"):
                    relative = texture.removeprefix("/cache/")
                    file = Path(os.path.abspath(root / relative))
                    if not file.is_relative_to(root):
                        raise ValueError(f"Model texture is outside the asset cache: {texture}")
                    self.texture_files[relative] = file.resolve()
        return model


def _patch_definition(file: Path, unit: str, visited=None, load_file=None, *, kind="physics_patch_data", all_values=False, read_file=None) -> dict | None:
    file = Path(os.path.abspath(file))
    visited = set() if visited is None else visited
    if file in visited:
        raise ValueError(f"Circular physics patch include: {file}")
    visited = visited | {file}
    if read_file is None and not file.is_file() and load_file:
        file.parent.mkdir(parents=True, exist_ok=True)
        load_file(file)
    text = read_file(file) if read_file else file.read_text(encoding="utf-8")
    for record_kind, name, body in _records(text):
        if (kind is None or record_kind == kind) and name == unit:
            properties = _properties(body)
            return properties if all_values else {key: values[-1] for key, values in properties.items() if values}
    for include in re.findall(r'@include\s+"([^"\n]+)"', text):
        patch = _patch_definition(file.parent / include, unit, visited, load_file, kind=kind, all_values=all_values, read_file=read_file)
        if patch:
            return patch
    return None


def _patch_piece(patch: dict, anchor: dict, texture: str) -> dict:
    width, height = float(patch["x_size"]), float(patch["y_size"])
    if not (math.isfinite(width) and math.isfinite(height) and width > 0 and height > 0):
        raise ValueError("Physics patch dimensions must be positive finite numbers.")
    qx, qy, qz, qw = anchor["rotation"]
    x_axis = [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy + qw * qz), 2 * (qx * qz - qw * qy)]
    y_axis = [2 * (qx * qy - qw * qz), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz + qw * qx)]
    scale = anchor.get("scale", [1, 1, 1])
    left = -width if anchor.get("name", "").endswith("_r") else 0
    positions = [anchor["position"][axis] + x * scale[0] * x_axis[axis] + y * scale[1] * y_axis[axis]
                 for x, y in ((left, 0), (left + width, 0), (left, -height), (left + width, -height)) for axis in range(3)]
    return {"name": "physics_patch", "part": ["physics_patch"], "positions": positions,
            "uvs": [0, 0, 1, 0, 0, 1, 1, 1], "indices": [0, 2, 1, 1, 2, 3],
            "material": {"name": "physics_patch", "color": [1, 1, 1], "texture": texture,
                         "metalness": 0, "roughness": .85, "alphaTest": .01}}


def _number_or_none(value: str | None) -> float | int | None:
    if value is None:
        return None
    numbers = _float_text(value)
    if not numbers:
        return None
    number = numbers[0]
    return int(number) if number.is_integer() else number


def _records(text: str) -> list[tuple[str, str, str]]:
    records = []
    for match in re.finditer(r'(?m)^\s*([\w]+)\s*:\s*([^\s{]+)\s*\{', text):
        start = match.end()
        depth = 1
        end = start
        for token in _BRACES.finditer(text, start):
            end = token.start()
            if token[0] == "{":
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    break
        else:
            end = max(start, len(text) - 1)
        records.append((match.group(1), match.group(2), text[start:end]))
    return records


def _blocks_after_record(text: str, record_type: str, unit: str) -> str:
    return next((body for kind, found_unit, body in _records(text) if kind == record_type and found_unit == unit), "")


def _parse_model(pim_path: Path, pit_path: Path | None, export: Path, selected_look: str | None = None, selected_variant: str | None = None) -> dict[str, Any]:
    native = read_viewer_model(pim_path) if pim_path.suffix == ".sgm" else None
    pim = "" if native else pim_path.read_text(encoding="utf-8", errors="replace")
    pit = pit_path.read_text(encoding="utf-8", errors="replace") if pit_path else ""
    pim_materials = [{"Alias": [material["alias"]], "Effect": [material["effect"]]} for material in native["materials"]] if native else [
        _properties(body) for body in _blocks(pim, "Material")]
    material_names = [_unquote(material.get("Alias", [""])[-1]) for material in pim_materials]
    material_effects = [_unquote(material.get("Effect", [""])[-1]) for material in pim_materials]
    looks = _blocks(pit, "Look")
    chosen_look = next((body for body in looks if _properties(body).get("Name", [""])[-1].strip('"').casefold() == selected_look.casefold()), None) if selected_look else None
    chosen_look = chosen_look or (looks[0] if looks else pit)
    look_name = _properties(chosen_look).get("Name", ["default"])[-1].strip('"')
    pit_materials = []
    for body in _blocks(chosen_look, "Material"):
        properties = _properties(body)
        attrs = {}
        for attribute in _blocks(body, "Attribute"):
            item = _properties(attribute)
            if item.get("Tag") and item.get("Value"):
                attrs[item["Tag"][-1].strip('"')] = _float_text(item["Value"][-1])
        textures = {}
        for texture in _blocks(body, "Texture"):
            item = _properties(texture)
            if item.get("Tag") and item.get("Value"):
                textures[item["Tag"][-1].strip('"')] = item["Value"][-1].strip('"')
        pit_materials.append({"attributes": attrs, "textures": textures, "effect": _unquote(properties.get("Effect", [""])[-1])})
    visible_part_names = None
    variants = _blocks(pit, "Variant")
    chosen_variant_body = next((body for body in variants if _properties(body).get("Name", [""])[-1].strip('"').casefold() == selected_variant.casefold()), None) if selected_variant else None
    chosen_variant_body = chosen_variant_body or (variants[0] if variants else None)
    variant_name = _properties(chosen_variant_body).get("Name", ["default"])[-1].strip('"') if chosen_variant_body else "default"
    if chosen_variant_body:
        visible_part_names = set()
        for part in _blocks(chosen_variant_body, "Part"):
            fields = _properties(part)
            visible = [1.0]
            for attribute in _blocks(part, "Attribute"):
                attribute_fields = _properties(attribute)
                if attribute_fields.get("Tag", [""])[-1].strip('"') == "visible":
                    visible = _float_text(attribute_fields.get("Value", ["1"])[-1])
            if visible and visible[0]:
                visible_part_names.add(fields.get("Name", [""])[-1].strip('"'))
    pieces = []
    included_piece_indexes = set()
    piece_parts = {}
    part_fields = [{"Name": [part["name"]], "Pieces": [" ".join(map(str, part["pieces"]))],
                    "Locators": [" ".join(map(str, part["locators"]))]} for part in native["parts"]] if native else [
                        _properties(part) for part in _blocks(pim, "Part")]
    for fields in part_fields:
        part_name = fields.get("Name", [""])[-1].strip('"')
        part_pieces = [int(value) for value in re.findall(r"\d+", " ".join(fields.get("Pieces", [])))]
        for part_piece in part_pieces:
            piece_parts.setdefault(part_piece, []).append(part_name)
    if visible_part_names is not None:
        for fields in part_fields:
            if fields.get("Name", [""])[-1].strip('"') in visible_part_names:
                included_piece_indexes.update(int(value) for value in re.findall(r"\d+", " ".join(fields.get("Pieces", []))))
    for piece_index, piece in enumerate(native["pieces"] if native else _blocks(pim, "Piece")):
        if visible_part_names is not None and piece_index not in included_piece_indexes:
            continue
        material_index = piece["material"] if native else int(_properties(piece).get("Material", ["0"])[-1])
        material_data = pit_materials[material_index] if 0 <= material_index < len(pit_materials) else {"attributes": {}, "textures": {}}
        alias = material_names[material_index] if 0 <= material_index < len(material_names) else f"material_{material_index}"
        effect = material_data.get("effect") or (material_effects[material_index] if 0 <= material_index < len(material_effects) else "")
        effect_tokens = effect.casefold().split(".")
        if "shadowonly" in effect_tokens or "fakeshadow" in effect_tokens:
            continue
        streams = piece["streams"] if native else {}
        triangle_values = piece["indices"] if native else []
        if not native:
            for stream in _blocks(piece, "Stream"):
                stream_props = _properties(stream)
                tag = stream_props.get("Tag", [""])[-1].strip('"')
                streams[tag] = _vectors(stream)
            for triangles in _blocks(piece, "Triangles"):
                for triangle in re.finditer(r'^\s*\d+\s*\(\s*(\d+)\s+(\d+)\s+(\d+)\s*\)', triangles, re.M):
                    triangle_values.extend(int(value) for value in triangle.groups())
        diffuse = material_data["attributes"].get("diffuse", [0.75, 0.75, 0.75])
        transparent = any(token in effect_tokens for token in ("over", "blend", "a", "glass"))
        texture_url = _texture_url(material_data["textures"], export, ignore_alpha=not transparent or "glass" in effect_tokens)
        mask_textures = {"texture_base": value for tag, value in material_data["textures"].items() if "texture_mask" in tag}
        pieces.append({
            "positions": streams.get("_POSITION", []),
            "normals": streams.get("_NORMAL", []),
            "uvs": streams.get("_UV0", streams.get("_TEXCOORD0", [])),
            "uvs1": streams.get("_UV1", streams.get("_UV0", [])),
            "indices": triangle_values,
            "index": piece_index,
            "part": piece_parts.get(piece_index, []),
            "name": piece_parts.get(piece_index, [f"piece_{piece_index}"])[0],
            "material": {
                "name": alias,
                "color": diffuse[:3],
                "texture": texture_url,
                "effect": effect,
                "lightMask": _texture_url(mask_textures, export, ignore_alpha=True) if "lamp" in effect_tokens else None,
                "lightAlpha": _texture_url(mask_textures, export, alpha_only=True) if "lamp" in effect_tokens else None,
                "paintable": "truckpaint" in effect_tokens or "paint" in effect_tokens,
                "transparent": transparent,
                "alphaTest": 0.01 if transparent else 0,
                "depthWrite": not transparent,
                "opacity": 0.55 if "glass" in effect_tokens else 1,
                "metalness": .85 if "chrome" in alias.casefold() else 0,
                "roughness": max(.18 if "chrome" in alias.casefold() or "glass" in effect_tokens else .42, min(.9, (2 / (material_data["attributes"].get("shininess", [16])[0] + 2)) ** .25)),
            },
        })
    locators = []
    included_locator_indexes = set()
    for fields in part_fields:
        if visible_part_names is None or fields.get("Name", [""])[-1].strip('"') in visible_part_names:
            included_locator_indexes.update(int(value) for value in re.findall(r"\d+", " ".join(fields.get("Locators", []))))
    for locator_index, locator in enumerate(native["locators"] if native else _blocks(pim, "Locator")):
        if visible_part_names is not None and locator_index not in included_locator_indexes:
            continue
        if native:
            values = {name: locator.get(name) for name in ("name", "position", "rotation", "scale", "hookup")}
            if values["hookup"]:
                values["hookup"] = _unquote(values["hookup"])
            locators.append(values)
            continue
        fields = _properties(locator)
        rotation = _float_text(fields.get("Rotation", [""])[-1])[:4]
        if len(rotation) == 4:
            rotation = rotation[1:] + rotation[:1]
        locators.append({
            "name": fields.get("Name", [""])[-1].strip('"'),
            "position": _float_text(fields.get("Position", [""])[-1])[:3],
            "rotation": rotation,
            "scale": _float_text(fields.get("Scale", [""])[-1])[:3],
            "hookup": fields.get("Hookup", [None])[-1],
        })
    if not any(piece["positions"] for piece in pieces) and not locators:
        raise ValueError(f"{pim_path} contains neither visible geometry nor locators.")
    return {"pieces": pieces, "locators": locators, "bones": native["bones"] if native else [], "look": look_name, "variant": variant_name, "diagnostics": [] if pit_path else ["PIT material traits are missing; geometry uses neutral material values."]}


def _texture_url(textures: dict[str, str], export: Path, ignore_alpha: bool = False, alpha_only: bool = False) -> str | None:
    if Image is None:
        return None
    base = next((value for tag, value in textures.items() if "texture_base" in tag), None)
    if not base:
        return None
    candidates = [export / (base.lstrip("/") + suffix) for suffix in (".dds", ".png")]
    source = next((path for path in candidates if path.is_file()), None)
    if not source:
        return None
    if source.suffix.lower() == ".png" and not ignore_alpha and not alpha_only:
        return "/cache/" + source.relative_to(export.parent.parent).as_posix()
    target = source.with_name(source.stem + (".alpha.png" if alpha_only else ".opaque.png" if ignore_alpha else ".png"))
    if not target.is_file():
        if source.suffix.lower() == ".dds":
            data = source.read_bytes()
            premultiplied_alpha = data[:4] == b"DDS " and data[84:88] == b"DXT4"
            if premultiplied_alpha:
                # DXT4 and DXT5 share the BC3 block layout; DXT4 marks RGB as
                # premultiplied by alpha. Pillow decodes DXT5 blocks directly.
                data = data[:84] + b"DXT5" + data[88:]
            with Image.open(BytesIO(data)) as image:
                converted = image.convert("RGBA")
                if premultiplied_alpha:
                    converted = Image.frombytes("RGBa", converted.size, converted.tobytes()).convert("RGBA")
                (converted.getchannel("A").convert("RGB") if alpha_only else converted.convert("RGB") if ignore_alpha else converted).save(target, format="PNG")
        else:
            with Image.open(source) as image:
                (image.convert("RGBA").getchannel("A").convert("RGB") if alpha_only else image.convert("RGB") if ignore_alpha else image).save(target, format="PNG")
    return "/cache/" + target.relative_to(export.parent.parent).as_posix()
