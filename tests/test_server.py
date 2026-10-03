import json
from concurrent.futures import CancelledError, ThreadPoolExecutor
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from http.server import ThreadingHTTPServer
import server
from test_saves import SOURCE


class MinimalAssets:
    def __init__(self, *arguments):
        self.game_path = None
        self.cache_path = Path(arguments[1])
        self.lock = threading.RLock()

    def status(self):
        return {"ready": True, "gamePath": None, "cachePath": str(self.cache_path)}

    def set_mod_sources(self, sources):
        pass

    def catalog(self):
        return []


class ServerTests(unittest.TestCase):
    def test_scene_update_sends_only_new_models_and_recovers_from_unknown_revision(self):
        self.request("/api/load", {"saveId": "profiles/54455354/quicksave"})
        calls = []
        def assemble(truck, assets, cancelled, model_cache=None):
            calls.append(truck)
            changed = "changed" if len(calls) == 2 else "original"
            return {"parts": [{"id": "frame", "model": {"key": "frame", "pieces": []}},
                              {"id": "toy", "model": {"key": changed, "pieces": []}},
                              {"id": "duplicate", "model": {"key": "frame", "pieces": []}}], "points": [], "issues": []}
        with patch.object(server, "build_scene", side_effect=assemble):
            code, initial = self.request("/api/scene?sinceRevision=-1")
            self.assertEqual(code, 200)
            self.assertEqual(set(initial["models"]), {"frame", "original"})
            self.assertNotIn("model", initial["parts"][0])
            self.request("/api/edit", {"op": "duplicate", "accessoryId": "_nameless.6"})
            code, updated = self.request(f'/api/scene?sinceRevision={initial["revision"]}')
            self.assertEqual(code, 200)
            self.assertEqual(set(updated["models"]), {"changed"})
            self.assertEqual(updated["parts"][0]["modelKey"], "frame")
            self.assertEqual(set(self.request("/api/scene?sinceRevision=-1")[1]["models"]), {"frame", "changed"})
            self.request("/api/undo", {})
            undone = self.request(f'/api/scene?sinceRevision={updated["revision"]}')[1]
            self.assertEqual(set(undone["models"]), {"original"})
            self.assertEqual(undone["parts"], initial["parts"])

    def test_cache_serves_only_registered_redirected_texture(self):
        root = Path(self.temporary.name)
        outside = root / "redirected.png"
        outside.write_text('{"texture":"registered"}', encoding="utf-8")
        cache = self.http.garage.assets.cache_path
        known = cache / "models/toy/santa.png"
        unknown = cache / "models/toy/other.png"
        self.http.garage.assets.texture_files = {"models/toy/santa.png": outside}
        original_resolve = Path.resolve
        with patch.object(Path, "resolve", autospec=True, side_effect=lambda path: outside if path in (known, unknown) else original_resolve(path)):
            self.assertEqual(self.request("/cache/models/toy/santa.png"), (200, {"texture": "registered"}))
            self.assertEqual(self.request("/cache/models/toy/other.png")[0], 403)
            self.assertEqual(self.request("/cache/%2e%2e/settings.json")[0], 403)

    def test_cancel_model_stops_active_import_and_handles_cancel_before_request(self):
        started = threading.Event()
        def model(path, cancelled=None):
            if path == "old":
                started.set()
                if not self.http.garage.model_requests["old-request"].wait(2):
                    raise AssertionError("The old model import was not cancelled")
                if cancelled():
                    raise CancelledError()
            return {"pieces": [], "locators": []}
        with patch.object(self.http.garage.assets, "model", side_effect=model, create=True) as importer:
            with ThreadPoolExecutor() as executor:
                old = executor.submit(self.request, "/api/model?path=old&requestId=old-request")
                self.assertTrue(started.wait(2))
                self.assertEqual(self.request("/api/cancel-model", {"requestId": "old-request"})[0], 200)
                self.assertEqual(old.result()[0], 499)
                self.assertEqual(self.request("/api/model?path=new&requestId=new-request")[0], 200)
            self.request("/api/cancel-model", {"requestId": "early-request"})
            self.assertEqual(self.request("/api/model?path=early&requestId=early-request")[0], 499)
            self.assertEqual(importer.call_count, 2)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        profiles = root / "profiles"
        save = profiles / "54455354" / "save" / "quicksave"
        save.mkdir(parents=True)
        (save / "game.sii").write_text(SOURCE, encoding="utf-8")
        self.path = save / "game.sii"
        with patch.object(server, "DATA", root / "data"), patch.object(server, "default_profiles", return_value=profiles), patch.object(server, "AssetStore", MinimalAssets):
            garage = server.Garage()
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.http.garage = garage
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.http.server_port}"
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)

    def request(self, path, data=None, headers=None):
        request = Request(self.url + path, data=json.dumps(data).encode() if data is not None else None,
                          headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    @patch("saves.game_running", return_value=False)
    def test_load_duplicate_undo_redo_and_backup_over_http(self, _):
        code, saves = self.request("/api/saves")
        self.assertEqual(code, 200)
        code, state = self.request("/api/load", {"saveId": saves[0]["id"]})
        self.assertEqual(code, 200)
        code, duplicated = self.request("/api/edit", {"op": "duplicate", "accessoryId": "_nameless.6", "sessionId": state["sessionId"], "revision": state["revision"]})
        self.assertEqual(len(duplicated["truck"]["accessories"]), 3)
        code, error = self.request("/api/save", {"sessionId": state["sessionId"], "revision": state["revision"]})
        self.assertEqual(code, 400)
        self.assertIn("session changed", error["error"])
        self.assertEqual(self.path.read_text(), SOURCE)
        code, undone = self.request("/api/undo", {})
        self.assertFalse(undone["dirty"])
        self.request("/api/redo", {})
        code, result = self.request("/api/save", {})
        self.assertEqual(code, 200)
        self.assertEqual(Path(result["backupPath"]).joinpath("game.sii").read_text(), SOURCE)

    def test_foreign_origin_host_and_non_json_requests_rejected(self):
        for headers, code in (({"Origin": "https://example.com"}, 403), ({"Host": "example.com"}, 403), ({"Content-Type": "text/plain"}, 415)):
            self.assertEqual(self.request("/api/load", {}, headers)[0], code)
        self.assertEqual(self.path.read_text(), SOURCE)

    def test_path_traversal_cannot_read_outside_ui_or_cache(self):
        self.assertEqual(self.request("/cache/%2e%2e/settings.json")[0], 403)

    def test_catalog_groups_brand_copies_but_keeps_visual_and_functional_variants(self):
        base = {"name": "Phone", "category": "set_lglass", "unitType": "accessory_addon_data",
                "fields": {"exterior_model": "/phone.pmd", "look": "black", "price": "100", "unlock": "0"}}
        entries = [
            {**base, "path": "/daf/phone", "brand": "daf"},
            {**base, "path": "/scania/phone", "brand": "scania", "fields": {**base["fields"], "price": "200", "unlock": "5"}},
            {**base, "path": "/white/phone", "fields": {**base["fields"], "look": "white"}},
            {**base, "path": "/different/ui", "fields": {**base["fields"], "ui_path": "/different.sii"}},
            {"path": "/engine/one", "name": "Engine", "category": "engine"},
            {"path": "/engine/two", "name": "Engine", "category": "engine"},
            {"path": "/toy#physics", "unitType": "physics_toy_data", "category": "hookup"},
        ]
        with patch.object(self.http.garage.assets, "catalog", return_value=entries):
            code, catalog = self.request("/api/catalog")
        self.assertEqual(code, 200)
        self.assertEqual(len(catalog), len(entries) - 1)
        self.assertEqual(catalog[0]["duplicateKey"], catalog[1]["duplicateKey"])
        self.assertEqual(len({item["duplicateKey"] for item in catalog}), 5)

    def test_saves_identify_profiles_and_order_newest_first(self):
        newer = self.path.parent.with_name("manual")
        newer.mkdir()
        (newer / "game.sii").write_text(SOURCE, encoding="utf-8")
        os.utime(self.path, (1000, 1000))
        code, listing = self.request("/api/saves")
        self.assertEqual(code, 200)
        self.assertTrue(listing[0]["id"].endswith("/manual"))
        self.assertEqual({save["profileId"] for save in listing}, {"profiles/54455354"})
        self.assertTrue(all(save["created"] and save["modified"] for save in listing))

    def test_switch_cancels_old_assembly_without_waiting_for_its_completion(self):
        self.request("/api/load", {"saveId": "profiles/54455354/quicksave"})
        started = threading.Event()

        def assemble(truck, assets, cancelled, model_cache=None):
            if truck["id"] == "_nameless.2":
                started.set()
                for _ in range(100):
                    if cancelled():
                        raise CancelledError()
                    threading.Event().wait(.02)
                self.fail("Old assembly was never cancelled.")
            return {"parts": [], "issues": [], "truckId": truck["id"]}

        with patch.object(server, "build_scene", side_effect=assemble), ThreadPoolExecutor(max_workers=1) as executor:
            old = executor.submit(self.request, "/api/scene?requestId=old&truckId=_nameless.2")
            self.assertTrue(started.wait(2))
            code, selected = self.request("/api/select", {"truckId": "_nameless.3"})
            self.assertEqual(code, 200)
            self.assertEqual(selected["truck"]["id"], "_nameless.3")
            self.assertEqual(old.result(timeout=2)[0], 499)
            self.assertEqual(self.request("/api/scene")[1]["truckId"], "_nameless.3")

    def test_cancel_only_targets_its_own_scene_request(self):
        self.request("/api/load", {"saveId": "profiles/54455354/quicksave"})
        started = threading.Event()

        def assemble(truck, assets, cancelled, model_cache=None):
            started.set()
            for _ in range(100):
                if cancelled():
                    raise CancelledError()
                threading.Event().wait(.02)
            self.fail("Explicit scene cancellation did not arrive.")

        with patch.object(server, "build_scene", side_effect=assemble), ThreadPoolExecutor(max_workers=1) as executor:
            active = executor.submit(self.request, "/api/scene?requestId=active")
            self.assertTrue(started.wait(2))
            self.request("/api/cancel-scene", {"requestId": "other-window"})
            self.assertFalse(self.http.garage.scene_cancel.is_set())
            self.request("/api/cancel-scene", {"requestId": "active"})
            self.assertEqual(active.result(timeout=2)[0], 499)
            self.assertIsNone(self.http.garage.scene_cache)

    def test_aborted_browser_response_is_logged_without_retrying_dead_socket(self):
        handler = object.__new__(server.Handler)
        handler.server = self.http
        handler.path = '/api/status'
        handler.headers = {'Host': f'127.0.0.1:{self.http.server_port}'}
        with patch.object(handler, 'json_response', side_effect=ConnectionAbortedError('Browser aborted')), patch.object(handler, 'log_message') as log:
            handler.handle_request()
            self.assertEqual(handler.json_response.call_count, 1)
            log.assert_called_once_with('Browser disconnected during request')


if __name__ == "__main__":
    unittest.main()
