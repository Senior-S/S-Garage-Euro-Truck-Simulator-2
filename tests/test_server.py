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
    def __init__(self, *arguments, **kwargs):
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
    def test_clearing_converter_path_detects_bundle_immediately_and_after_restart(self):
        garage = self.http.garage
        root = Path(self.temporary.name)
        bundled = root / "bundle" / "tools" / "converter_pix.exe"
        bundled.parent.mkdir(parents=True)
        bundled.write_bytes(b"bundled converter")
        custom = root / "custom-converter.exe"
        custom.write_bytes(b"custom converter")
        game = root / "game"
        game.mkdir()
        (game / "def.scs").write_bytes(b"fixture archive")
        environment = {"ETS_GARAGE_CONVERTER": str(root / "missing-converter.exe"),
                       "ETS2_CONVERTER_PIX": str(root / "missing-legacy-converter.exe")}
        with patch.dict(os.environ, environment), patch.object(sys, "_MEIPASS", bundled.parent.parent, create=True), \
             patch.object(server.AssetStore, "_converter_capabilities", return_value={}), \
             patch.object(server, "game_running", return_value=False):
            code, result = self.request("/api/config", {"toolPath": str(custom), "gamePath": str(game),
                                                       "profilesPath": str(garage.profiles)})
            self.assertEqual(code, 200, result)
            self.assertEqual(Path(result["toolPath"]), custom)
            custom.unlink()
            code, result = self.request("/api/config", {"toolPath": "  "})
            self.assertEqual(code, 200, result)
            self.assertTrue(result["ready"])
            self.assertEqual(Path(result["toolPath"]), bundled)
            self.assertEqual(json.loads(garage.config_file.read_text())["toolPath"], "")
            self.assertEqual({name: os.environ[name] for name in environment}, environment)
            with patch.object(server, "DATA", garage.config_file.parent):
                self.assertEqual(server.Garage().assets.tool_path, bundled)

    def test_cache_rebuild_requires_acceptance_and_reimports_before_returning(self):
        garage = self.http.garage
        self.request("/api/load", {"saveId": "profiles/54455354/quicksave"})
        session = garage.session
        garage.scene_models["old"] = {}
        garage.catalog_payload = ["old"]
        cancelled = threading.Event()
        garage.model_requests["old"] = cancelled
        calls = []
        with patch.object(garage.assets, "rebuild_cache", create=True, side_effect=lambda: calls.append("clear")), patch.object(garage.assets, "catalog", side_effect=lambda: calls.append("import") or []):
            self.assertEqual(self.request("/api/rebuild-cache", {})[0], 400)
            self.assertEqual(calls, [])
            code, result = self.request("/api/rebuild-cache?requestId=rebuild", {"accepted": True})
        self.assertEqual(code, 200, result)
        self.assertEqual(calls, ["clear", "import"])
        self.assertIs(garage.session, session)
        self.assertEqual(self.path.read_text(), SOURCE)
        self.assertTrue(cancelled.is_set())
        self.assertFalse(garage.scene_models)
        self.assertIsNone(garage.catalog_payload)
        self.assertEqual(self.request("/api/progress?requestId=rebuild")[1]["rebuild"]["state"], "done")

    def test_progress_remains_responsive_while_catalog_and_session_are_locked(self):
        garage = self.http.garage
        started, release = threading.Event(), threading.Event()
        def catalog():
            with garage.lock, garage.assets.lock:
                garage.progress.update("Indexing parts", "Truck parts", 3, 10)
                started.set()
                self.assertTrue(release.wait(3))
            return []
        with patch.object(garage.assets, "catalog", side_effect=catalog), ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(self.request, "/api/catalog?requestId=import")
            try:
                self.assertTrue(started.wait(2))
                code, progress = self.request("/api/progress?requestId=import&requestId=other-window")
                self.assertEqual(code, 200)
                self.assertEqual(list(progress), ["import"])
                self.assertEqual(progress["import"]["stage"], "Indexing parts")
                self.assertEqual(progress["import"]["completed"], 3)
                self.assertEqual(progress["import"]["total"], 10)
                self.assertEqual(progress["import"]["state"], "running")
            finally:
                release.set()
            self.assertEqual(pending.result(timeout=2)[0], 200)
        self.assertEqual(self.request("/api/progress?requestId=import")[1]["import"]["state"], "done")

    def test_load_reads_only_the_selected_save_and_rejects_path_escape(self):
        with patch.object(self.http.garage, "saves", side_effect=AssertionError("Do not scan every save")):
            code, state = self.request("/api/load?requestId=save", {"saveId": "profiles/54455354/quicksave"})
        self.assertEqual(code, 200, state)
        self.assertEqual(self.request("/api/progress?requestId=save")[1]["save"]["state"], "done")
        for save_id in ("profiles/../quicksave", "profiles/54455354/../../outside", "profiles/54455354/..\\outside", "unknown/54455354/quicksave"):
            self.assertEqual(self.request("/api/load?requestId=bad", {"saveId": save_id})[0], 400)
        self.assertEqual(self.request("/api/progress?requestId=bad")[1]["bad"]["state"], "error")

    def test_owned_trailer_selection_edit_and_scene_over_http(self):
        from test_trailers import TRAILER_SOURCE
        self.path.write_text(TRAILER_SOURCE, encoding="utf-8")
        code, state = self.request("/api/load", {"saveId": "profiles/54455354/quicksave"})
        self.assertEqual(code, 200)
        self.assertEqual(state["truck"]["id"], "_nameless.2")
        code, selected = self.request("/api/select", {"truckId": "_nameless.10"})
        self.assertEqual(code, 200)
        self.assertEqual(selected["truck"]["kind"], "trailer")
        self.assertEqual(len(selected["trailers"]), 1)
        self.assertEqual(selected["truck"]["sectionCount"], 2)
        code, edited = self.request("/api/edit", {"op": "duplicate", "accessoryId": "_nameless.14"})
        self.assertEqual(code, 200)
        self.assertEqual(len(edited["truck"]["accessories"]), 7)
        self.assertEqual(self.request("/api/scene")[1]["truckId"], "_nameless.10")
        code, selected = self.request("/api/select", {"truckId": "_nameless.11"})
        self.assertEqual(code, 200)
        self.assertEqual(selected["truck"]["id"], "_nameless.10")
        self.assertEqual(selected["truck"]["sections"][1]["section"], 2)
        code, edited = self.request("/api/edit", {"op": "fields", "truckId": "_nameless.11", "accessoryId": "_nameless.13", "fields": {"refund": "123"}})
        self.assertEqual(code, 200, edited)
        self.assertEqual(edited["truck"]["id"], "_nameless.10")
        self.assertEqual(edited["editedVehicleId"], "_nameless.11")
        self.assertEqual(edited["truck"]["sections"][0]["accessories"][1]["fields"]["refund"], "0")
        self.assertEqual(edited["truck"]["sections"][1]["accessories"][1]["fields"]["refund"], "123")
        self.assertEqual(self.request("/api/select", {"truckId": "unowned"})[0], 400)
        self.assertEqual(self.path.read_text(), TRAILER_SOURCE)

    def test_cache_folder_change_persists_and_preserves_old_cache(self):
        garage = self.http.garage
        old_cache = garage.assets.cache_path
        old_cache.mkdir(parents=True)
        (old_cache / "existing.txt").write_text("keep", encoding="utf-8")
        target = Path(self.temporary.name) / "custom" / "cache"
        with patch.object(server, "AssetStore", MinimalAssets), patch.object(server, "game_running", return_value=False):
            code, result = self.request("/api/config", {"cachePath": str(target), "profilesPath": str(self.http.garage.profiles)})
        self.assertEqual(code, 200, result)
        target = target.resolve()
        self.assertEqual(Path(result["cachePath"]), target)
        self.assertTrue(target.is_dir())
        self.assertEqual((old_cache / "existing.txt").read_text(), "keep")
        self.assertEqual(json.loads(garage.config_file.read_text())["cachePath"], str(target))
        with patch.object(server, "DATA", garage.config_file.parent), patch.object(server, "default_profiles", return_value=garage.profiles), patch.object(server, "AssetStore", MinimalAssets):
            self.assertEqual(server.Garage().assets.cache_path, target)

    def test_cache_folder_rejects_file_without_changing_settings(self):
        target = Path(self.temporary.name) / "file.txt"
        target.write_text("occupied", encoding="utf-8")
        before = self.http.garage.assets
        code, result = self.request("/api/config", {"cachePath": str(target), "profilesPath": str(self.http.garage.profiles)})
        self.assertEqual(code, 400)
        self.assertEqual(result["error"], "Cache folder must be a directory.")
        self.assertIs(self.http.garage.assets, before)
        self.assertFalse(self.http.garage.config_file.exists())

    def test_paint_preview_uses_default_design_colors_without_editing_save(self):
        self.request("/api/load", {"saveId": "profiles/54455354/quicksave"})
        before = self.request("/api/state")[1]
        job = {"fields": {"base_color": "(1,.5,0)", "mask_r_color": "(0,1,0)", "airbrush": "true"}, "texture": "/cache/design.png", "overrides": {}}
        with patch.object(self.http.garage.assets, "definition", return_value={"path": "/paint", "category": "paint_job"}, create=True), patch.object(self.http.garage.assets, "paint_job", return_value=job, create=True) as load:
            code, preview = self.request("/api/paint?path=/paint&preview=1&requestId=paint-preview")
            self.assertEqual(code, 200)
            self.assertEqual(preview["material"]["color"], [1, .5, 0])
            self.assertEqual(preview["material"]["paintColors"][0], [0, 1, 0])
            self.assertTrue(preview["material"]["airbrush"])
            self.assertEqual(preview["material"]["paintTexture"], "/cache/design.png")
            self.assertFalse(load.call_args.kwargs["include_overrides"])
            self.assertIsNotNone(load.call_args.kwargs["cancelled"])
        self.assertEqual(self.request("/api/state")[1], before)

    def test_paint_preview_uses_only_the_selected_trailer_body_override(self):
        job = {"fields": {"base_color": "(1,1,1)", "airbrush": "true"}, "texture": "/cache/swatch.png",
               "overrides": {"body.curtain_136": "/cache/curtain.png"}}
        definitions = {"/paint": {"path": "/paint", "category": "paint_job"},
                       "/curtain": {"category": "body", "unitId": "curtain_136.scs.box.body"},
                       "/dryvan": {"category": "body", "unitId": "dry_van_136.scs.box.body"}}
        with patch.object(self.http.garage.assets, "definition", side_effect=definitions.get, create=True), patch.object(self.http.garage.assets, "paint_job", return_value=job, create=True) as load:
            for body, key, texture in (("curtain", "body.curtain_136", "/cache/curtain.png"),
                                       ("dryvan", "body.dry_van_136", "/cache/swatch.png")):
                code, preview = self.request(f"/api/paint?path=/paint&preview=1&accessoryPath=/{body}")
                self.assertEqual(code, 200, preview)
                self.assertEqual(preview["material"]["paintTexture"], texture)
                self.assertTrue(preview["material"]["airbrush"])
                self.assertTrue(load.call_args.kwargs["include_overrides"])
                self.assertEqual(load.call_args.kwargs["accessory_key"], key)
            count = load.call_count
            self.assertEqual(self.request("/api/paint?path=/paint&preview=1&accessoryPath=/missing")[0], 400)
            self.assertEqual(load.call_count, count)

    def test_catalog_cab_preview_preserves_selected_look_and_variant(self):
        with patch.object(self.http.garage.assets, "model", return_value={"pieces": []}, create=True) as model:
            self.assertEqual(self.request("/api/model?path=/cab&look=paint&variant=high&requestId=cab-preview")[0], 200)
            self.assertEqual(model.call_args.kwargs["look"], "paint")
            self.assertEqual(model.call_args.kwargs["variant"], "high")

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

    @patch("saves.game_running", return_value=True)
    def test_load_duplicate_undo_redo_and_backup_with_game_running_over_http(self, _):
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
