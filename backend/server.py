"""Loopback-only garage server and desktop entry point."""
from __future__ import annotations

import argparse
from concurrent.futures import CancelledError
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import gzip
import hashlib
import json
import mimetypes
import os
import sys
from pathlib import Path
import threading
import traceback
from urllib.parse import parse_qs, unquote, urlsplit
import webbrowser

from assets import AssetStore, _numbers
from saves import SaveSession, read_sii, game_running
from scene import build_scene, paint_material
from mods import resolve_mods


APP = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
DATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "ETS2Garage"


def default_profiles() -> Path:
    documents = Path.home() / "Documents"
    if os.name == "nt":
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
            documents = Path(os.path.expandvars(winreg.QueryValueEx(key, "Personal")[0]))
    return documents / "Euro Truck Simulator 2" / "profiles"


class Garage:
    def __init__(self):
        DATA.mkdir(parents=True, exist_ok=True)
        self.config_file = DATA / "settings.json"
        self.config = json.loads(self.config_file.read_text("utf-8")) if self.config_file.exists() else {}
        if self.config.get("toolPath"):
            os.environ["ETS_GARAGE_CONVERTER"] = self.config["toolPath"]
        self.profiles = Path(self.config.get("profilesPath") or default_profiles()).resolve()
        self.assets = AssetStore(self.config.get("gamePath"), Path(self.config.get("cachePath") or DATA / "cache").expanduser().resolve())
        self.session: SaveSession | None = None
        self.lock = threading.RLock()
        self.scene_cache = None
        self.scene_key = None
        self.scene_models = {}
        self.scene_model_scope = None
        self.scene_cancel = threading.Event()
        self.scene_request = None
        self.scene_lock = threading.Lock()
        self.model_requests = {}
        self.model_request_lock = threading.Lock()
        self.source_issues = []

    def decryptor(self) -> Path | None:
        configured = self.config.get("decryptorPath") or os.environ.get("ETS_GARAGE_DECRYPTOR")
        if configured:
            return Path(configured).resolve()
        bundled = APP / "tools" / "SII_Decrypt.exe"
        if bundled.is_file():
            return bundled
        # Local copies are common in save-editing profiles. Search only these roots.
        for root in self.profile_roots():
            for profile in root.iterdir() if root.is_dir() else []:
                for candidate in (profile / "SII_Decrypt.exe", profile / "save" / "quicksave" / "SII_Decrypt.exe"):
                    if candidate.is_file():
                        return candidate.resolve()
        return None

    def profile_roots(self) -> list[Path]:
        roots = [self.profiles]
        if self.profiles.name == "profiles":
            roots.append(self.profiles.with_name("steam_profiles"))
        return [root for root in roots if root.is_dir()]

    def status(self) -> dict:
        return {**self.assets.status(), "appId": "ets2-local-garage", "profilesPath": str(self.profiles),
                "decryptorPath": str(self.decryptor() or ""), "session": self.session.state() if self.session else None,
                "gameRunning": game_running()}

    def saves(self) -> list[dict]:
        output = []
        for root in self.profile_roots():
            for profile in root.iterdir():
                save_root = profile / "save"
                if not save_root.is_dir():
                    continue
                try:
                    name = bytes.fromhex(profile.name).decode("utf-8")
                except (ValueError, UnicodeDecodeError):
                    name = profile.name
                for folder in save_root.iterdir():
                    path = folder / "game.sii"
                    if path.is_file():
                        with path.open("rb") as stream:
                            magic = stream.read(12)
                        stat = path.stat()
                        output.append({"id": f"{root.name}/{profile.name}/{folder.name}", "profile": name,
                                       "profileId": f"{root.name}/{profile.name}",
                                       "name": folder.name.replace("_", " ").title(),
                                       "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
                                       "created": datetime.fromtimestamp(getattr(stat, "st_birthtime", stat.st_ctime), timezone.utc).isoformat(),
                                       "format": "text" if b"SiiNunit" in magic else "encrypted"})
        return sorted(output, key=lambda save: save["modified"], reverse=True)

    def load(self, save_id: str) -> dict:
        listing = {save["id"]: save for save in self.saves()}
        save = listing.get(save_id)
        if not save:
            raise ValueError("Save not found in the configured profiles folder.")
        root_name, profile, folder = save_id.split("/")
        root = next(root for root in self.profile_roots() if root.name == root_name)
        path = (root / profile / "save" / folder / "game.sii").resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Save path leaves the profiles folder.")
        text = read_sii(path, self.decryptor())
        session = SaveSession(path, text, save_id, f'{save["profile"]} / {save["name"]}')
        mod_sources, issues = resolve_mods(path, root, self.assets.game_path, self.decryptor())
        self.assets.set_mod_sources(mod_sources)
        self.source_issues = issues
        self.session = session
        return self.session.state()

    def require_session(self) -> SaveSession:
        if not self.session:
            raise ValueError("Load a save first.")
        return self.session


class Handler(BaseHTTPRequestHandler):
    server_version = "ETS2Garage/0.1"

    def json_response(self, payload, status: int = 200):
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        compressed = len(data) > 4096 and "gzip" in self.headers.get("Accept-Encoding", "")
        if compressed:
            data = gzip.compress(data, compresslevel=1)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if compressed:
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_request(self, post: bool = False):
        try:
            host = self.headers.get("Host", "")
            allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
            if host not in allowed:
                self.json_response({"error": "Use the garage through its localhost address."}, 403)
                return
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            garage = self.server.garage
            if post:
                origin = self.headers.get("Origin")
                if origin and origin not in {"http://" + host for host in allowed} | {"http://localhost:5173", "http://127.0.0.1:5173"}:
                    self.json_response({"error": "Requests must come from the local garage."}, 403)
                    return
                if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                    self.json_response({"error": "Expected application/json."}, 415)
                    return
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > 1024 * 1024:
                    raise ValueError("Request body is too large.")
                body = json.loads(self.rfile.read(length) or b"{}")
                if parsed.path == "/api/cancel-model":
                    request_id = body["requestId"]
                    with garage.model_request_lock:
                        garage.model_requests.setdefault(request_id, threading.Event()).set()
                        while len(garage.model_requests) > 256:
                            garage.model_requests.pop(next(iter(garage.model_requests)))
                    self.json_response({"cancelled": True})
                    return
                if parsed.path == "/api/cancel-scene":
                    if body.get("requestId") == garage.scene_request:
                        garage.scene_cancel.set()
                    self.json_response({"cancelled": True})
                    return
                changes_scene = parsed.path in ("/api/load", "/api/select", "/api/edit", "/api/undo", "/api/redo", "/api/config")
                if changes_scene:
                    garage.scene_cancel.set()
                with garage.lock:
                    if changes_scene:
                        # A waiting mutation must also cancel a job registered before it acquired the lock.
                        garage.scene_cancel.set()
                    if body.get("sessionId"):
                        session = garage.require_session()
                        if body["sessionId"] != session.session_id or body.get("revision", session.revision) != session.revision:
                            raise ValueError("The editing session changed in another window. Reload the garage before applying this action.")
                    if parsed.path == "/api/load":
                        result = garage.load(body["saveId"])
                    elif parsed.path == "/api/config":
                        if garage.session and garage.session.state()["dirty"]:
                            raise ValueError("Save or discard your truck edits before changing game folders.")
                        config = dict(garage.config)
                        for name in ("gamePath", "profilesPath", "decryptorPath", "toolPath", "cachePath"):
                            if name in body:
                                value = body[name]
                                if not isinstance(value, str):
                                    raise ValueError(f"{name} must be a folder or file path.")
                                config[name] = value.strip()
                        profiles = Path(config.get("profilesPath") or default_profiles()).resolve()
                        if not profiles.is_dir():
                            raise ValueError("Profiles folder does not exist.")
                        if config.get("gamePath") and not (Path(config["gamePath"]) / "def.scs").is_file():
                            raise ValueError("Game folder must contain def.scs.")
                        for key in ("decryptorPath", "toolPath"):
                            if config.get(key) and not Path(config[key]).is_file():
                                raise ValueError(f"{key} does not exist.")
                        if config.get("toolPath"):
                            os.environ["ETS_GARAGE_CONVERTER"] = config["toolPath"]
                        cache = Path(config.get("cachePath") or garage.config_file.parent / "cache").expanduser().resolve()
                        if cache.exists() and not cache.is_dir():
                            raise ValueError("Cache folder must be a directory.")
                        cache.mkdir(parents=True, exist_ok=True)
                        config["cachePath"] = str(cache)
                        assets = AssetStore(config.get("gamePath"), cache)
                        garage.config_file.write_text(json.dumps(config, indent=2), "utf-8")
                        garage.config, garage.profiles, garage.assets = config, profiles, assets
                        garage.session = None
                        result = garage.status()
                    elif parsed.path == "/api/select":
                        session = garage.require_session()
                        if body["truckId"] not in session.truck_ids:
                            raise ValueError("Truck not found in this save.")
                        session.truck_id = body["truckId"]
                        result = session.state()
                    elif parsed.path == "/api/edit":
                        if body.get("op") == "hookup" and body.get("hookup"):
                            installed_hooks = {item["unitId"] for item in garage.assets.catalog() if item["category"] == "hookup"}
                            if body["hookup"] not in installed_hooks:
                                raise ValueError("Choose an installed hookup from the parts catalog.")
                        definitions = {item["path"]: item for item in garage.assets.catalog()}
                        if body.get("op") == "paint":
                            accessory = next((part for part in garage.require_session().state()["truck"]["accessories"] if part["id"] == body.get("accessoryId")), None)
                            path = body.get("dataPath") or (accessory or {}).get("dataPath")
                            old_path = (accessory or {}).get("dataPath")
                            if old_path in definitions and old_path != path:
                                definitions[old_path] = {**definitions[old_path], **garage.assets.paint_job(old_path, textures=False)}
                            if path in definitions:
                                paint = garage.assets.paint_job(path, textures=False)
                                name = paint["fields"].get("name", definitions[path]["name"]).strip("@").removeprefix("pj_").replace("_", " ").title()
                                definitions[path] = {**definitions[path], **paint, "name": name}
                        result = garage.require_session().edit(body, definitions)
                    elif parsed.path in ("/api/undo", "/api/redo"):
                        result = garage.require_session().history(parsed.path == "/api/redo", body.get("steps", 1))
                    elif parsed.path == "/api/save":
                        result = garage.require_session().save()
                    else:
                        self.json_response({"error": "Unknown API route."}, 404)
                        return
                self.json_response(result)
                return
            if parsed.path == "/api/status":
                self.json_response(garage.status())
            elif parsed.path == "/api/saves":
                self.json_response(garage.saves())
            elif parsed.path == "/api/catalog":
                visible = ("path", "name", "category", "brand", "unitType", "unitId", "model", "price", "iconUrl")
                entries = []
                for entry in garage.assets.catalog():
                    if entry.get("unitType", "").startswith("physics_"):
                        continue
                    item = {key: entry.get(key) for key in visible}
                    # Keep visual and functional differences; price/unlock do not
                    # change an accessory in this save editor.
                    fields = {key: value for key, value in entry.get("fields", {}).items() if key not in ("price", "unlock")}
                    signature = [entry.get("category"), entry.get("unitType"), entry.get("name"), fields]
                    item["duplicateKey"] = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest() if fields else entry["path"]
                    entries.append(item)
                self.json_response(entries)
            elif parsed.path == "/api/state":
                with garage.lock:
                    self.json_response(garage.require_session().state())
            elif parsed.path == "/api/paint":
                entry = garage.assets.definition(query["path"][0])
                if not entry or entry["category"] != "paint_job":
                    raise ValueError("Choose an installed paint job.")
                preview = query.get("preview", [""])[0] == "1"
                cancelled = None
                request_id = query.get("requestId", [None])[0]
                if request_id:
                    with garage.model_request_lock:
                        cancelled = garage.model_requests.setdefault(request_id, threading.Event())
                        while len(garage.model_requests) > 256:
                            garage.model_requests.pop(next(iter(garage.model_requests)))
                paint = garage.assets.paint_job(entry["path"], textures=preview, include_overrides=False, cancelled=cancelled.is_set if cancelled else None)
                if preview:
                    fields = paint["fields"]
                    material = paint_material(_numbers(fields.get("base_color", "(1,1,1)"))[:3], fields, paint.get("texture"))
                    paint = {**paint, "material": material}
                self.json_response(paint)
            elif parsed.path == "/api/paints":
                entries = []
                fingerprint = garage.assets._fingerprint()
                for entry in garage.assets.catalog():
                    if entry["category"] != "paint_job" or entry["brand"] != query.get("brand", [""])[0]:
                        continue
                    paint = garage.assets.paint_job(entry["path"], textures=False, _entry=entry, _fingerprint=fingerprint)
                    settings = paint["fields"]
                    name = settings.get("name", entry["name"]).strip("@").removeprefix("pj_").replace("_", " ").title()
                    signature = [name, {key: value for key, value in settings.items() if key not in ("price", "unlock")}]
                    entries.append({**entry, "name": name, "paintFields": settings, "suitableFor": paint["suitableFor"],
                                    "duplicateKey": hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()})
                self.json_response(entries)
            elif parsed.path == "/api/model":
                request_id = query.get("requestId", [None])[0]
                if request_id:
                    with garage.model_request_lock:
                        cancelled = garage.model_requests.setdefault(request_id, threading.Event())
                        while len(garage.model_requests) > 256:
                            garage.model_requests.pop(next(iter(garage.model_requests)))
                    if cancelled.is_set():
                        raise CancelledError()
                    self.json_response(garage.assets.model(query["path"][0], cancelled=cancelled.is_set, **{name: query[name][0] for name in ("look", "variant") if name in query}))
                else:
                    self.json_response(garage.assets.model(query["path"][0], **{name: query[name][0] for name in ("look", "variant") if name in query}))
            elif parsed.path == "/api/scene":
                with garage.lock:
                    session = garage.require_session()
                    key = (session.session_id, session.truck_id, session.revision)
                    expected = (query.get("sessionId", [key[0]])[0], query.get("truckId", [key[1]])[0], int(query.get("revision", [key[2]])[0]))
                    if expected != key:
                        raise CancelledError()
                    since = query.get("sinceRevision", [None])[0]
                    previous = garage.scene_cache if since is not None and garage.scene_key == (*key[:2], int(since)) else None
                    cached = garage.scene_cache if key == garage.scene_key else None
                    if cached is None:
                        garage.scene_cancel.set()
                        cancelled = threading.Event()
                        garage.scene_cancel = cancelled
                        garage.scene_request = query.get("requestId", [None])[0]
                        truck = session.state()["truck"]
                        assets, source_issues = garage.assets, list(garage.source_issues)
                if cached is None:
                    with garage.scene_lock:
                        scope = (*key[:2], id(assets))
                        if garage.scene_model_scope != scope:
                            garage.scene_models = {}
                            garage.scene_model_scope = scope
                        # A switch can cancel an assembly while it waits for asset import.
                        while not assets.lock.acquire(timeout=.1):
                            if cancelled.is_set():
                                raise CancelledError()
                        try:
                            if cancelled.is_set():
                                raise CancelledError()
                            cached = build_scene(truck, assets, cancelled=cancelled.is_set, model_cache=garage.scene_models)
                            cached["issues"].extend(source_issues)
                        finally:
                            assets.lock.release()
                        with garage.lock:
                            current = garage.require_session()
                            if cancelled.is_set() or key != (current.session_id, current.truck_id, current.revision):
                                raise CancelledError()
                            garage.scene_cache, garage.scene_key = cached, key
                if since is not None:
                    known = {part["model"]["key"] for part in previous["parts"]} if previous else set()
                    models = {part["model"]["key"]: part["model"] for part in cached["parts"] if part["model"]["key"] not in known}
                    parts = [{**{name: value for name, value in part.items() if name != "model"}, "modelKey": part["model"]["key"]} for part in cached["parts"]]
                    self.json_response({**cached, "parts": parts, "models": models, "revision": key[2]})
                else:
                    self.json_response(cached)
            elif parsed.path.startswith("/api/"):
                self.json_response({"error": "Unknown API route."}, 404)
            else:
                cache = parsed.path.startswith("/cache/")
                root = Path(garage.assets.cache_path) if cache else APP / "ui" / "dist"
                relative = unquote(parsed.path[7:] if cache else parsed.path.lstrip("/")) or "index.html"
                path = (root / relative).resolve()
                imported_texture = cache and getattr(garage.assets, "texture_files", {}).get(relative) == path
                if not path.is_relative_to(root.resolve()) and not imported_texture:
                    self.json_response({"error": "Invalid file path."}, 403)
                elif path.is_file():
                    content = path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", mimetypes.guess_type(path)[0] or "application/octet-stream")
                    self.send_header("Content-Length", str(len(content)))
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    self.wfile.write(content)
                else:
                    self.json_response({"error": "File not found. Build the UI with npm run build in ui/."}, 404)
        except CancelledError:
            try:
                self.json_response({"cancelled": True}, 499)
            except ConnectionError:
                self.log_message("Cancelled scene client disconnected")
        except (ValueError, KeyError, FileNotFoundError) as error:
            self.json_response({"error": str(error)}, 400)
        except ConnectionError:
            # A browser can cancel a model request when another truck is selected.
            self.log_message("Browser disconnected during request")
        except Exception as error:
            traceback.print_exc()
            self.json_response({"error": str(error)}, 500)

    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request(True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Local Euro Truck Simulator 2 garage")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="Open the garage in your default browser")
    arguments = parser.parse_args()
    garage = Garage()
    server = ThreadingHTTPServer(("127.0.0.1", arguments.port), Handler)
    server.daemon_threads = True
    server.garage = garage
    print(f"ETS2 Garage: http://127.0.0.1:{arguments.port}", flush=True)
    if arguments.open:
        webbrowser.open(f"http://127.0.0.1:{arguments.port}")
    server.serve_forever()
