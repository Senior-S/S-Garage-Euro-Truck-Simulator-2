from concurrent.futures import CancelledError
import json
from pathlib import Path
import subprocess
import struct
import tempfile
import unittest
from unittest.mock import patch

from backend.assets import AssetStore, Image, _parse_model, _patch_definition
from backend.converter_formats import DEFINITION_BUNDLE_MAGIC
from tests.test_scene import FakeAssets, build_scene


class ConverterIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        capability_patch = patch.object(AssetStore, "_converter_capabilities", return_value={"batch": True, "definitionBundle": True, "viewerGeometry": True})
        capability_patch.start()
        self.addCleanup(capability_patch.stop)
        self.store = AssetStore(game_path=str(self.root), cache_path=self.root / "cache")

    def write_bundle(self, root, records):
        root.mkdir(parents=True, exist_ok=True)
        path = root / "definitions.sgbundle"
        with path.open("wb") as handle:
            handle.write(DEFINITION_BUNDLE_MAGIC)
            for name, text in records.items():
                encoded_name, encoded_text = name.encode(), text.encode()
                handle.write(struct.pack("<IQ", len(encoded_name), len(encoded_text)))
                handle.write(encoded_name)
                handle.write(encoded_text)
        return path

    def write_geometry(self, path):
        """One fixture keeps legacy/native comparisons and batch exports equivalent."""
        path.parent.mkdir(parents=True, exist_ok=True)
        positions, normals = [0, 0, 0, 1, 0, 0, 0, 1, 0], [0, 0, 1] * 3
        uv0, uv1, indices = [0, 0, 1, 0, 0, 1], [.25, .5, .75, .5, .25, 1], [0, 2, 1]
        binary = bytearray()
        streams = {}
        for tag, values, width in (("_POSITION", positions, 3), ("_NORMAL", normals, 3), ("_UV0", uv0, 2), ("_UV1", uv1, 2)):
            streams[tag] = {"offset": len(binary), "count": len(values), "components": width, "type": "f32"}
            binary.extend(struct.pack(f"<{len(values)}f", *values))
        descriptor = {"offset": len(binary), "count": 3, "components": 1, "type": "u32"}
        binary.extend(struct.pack("<3I", *indices))
        piece = {"material": 0, "vertexCount": 3, "boneCount": 0, "streams": streams, "indices": descriptor,
                 "uvAliases": {"_UV0": ["_TEXCOORD0"], "_UV1": ["_TEXCOORD1"]}}
        native = {"format": "SGarageModel", "version": 1, "binary": path.with_suffix(".sgb").name,
                  "binaryBytes": len(binary), "materials": [{"alias": "paint", "effect": "eut2.truckpaint"}],
                  "pieces": [{**piece, "index": 0}, {**piece, "index": 1}],
                  "parts": [{"name": "body", "pieces": [0], "locators": [0]}, {"name": "trim", "pieces": [1], "locators": [1]}],
                  "locators": [{"index": index, "name": name, "position": [1, 2, 3], "rotation": [0, 0, .5, .5],
                                "scale": [-1, 2, 1], "hookup": "flare.test"} for index, name in enumerate(("r_grill", "trim_slot"))],
                  "bones": []}
        path.with_suffix(".sgb").write_bytes(binary)
        path.with_suffix(".sgm").write_text(json.dumps(native), encoding="utf-8")
        pim = 'Material {\nAlias: "paint"\nEffect: "eut2.truckpaint"\n}\n'
        for index in range(2):
            pim += f'Piece {{\nIndex: {index}\nMaterial: 0\n'
            for tag, values, width in (("_POSITION", positions, 3), ("_NORMAL", normals, 3), ("_UV0", uv0, 2), ("_UV1", uv1, 2)):
                vectors = "\n".join(f'{i // width} ( {" ".join(str(v) for v in values[i:i + width])} )' for i in range(0, len(values), width))
                pim += f'Stream {{\nTag: "{tag}"\n{vectors}\n}}\n'
            pim += 'Triangles {\n0 ( 0 2 1 )\n}\n}\n'
        for index, name in enumerate(("body", "trim")):
            pim += f'Part {{\nName: "{name}"\nPieces: {index}\nLocators: {index}\n}}\n'
        for name in ("r_grill", "trim_slot"):
            pim += f'Locator {{\nName: "{name}"\nPosition: (1 2 3)\nRotation: (.5 0 0 .5)\nScale: (-1 2 1)\nHookup: "flare.test"\n}}\n'
        path.with_suffix(".pim").write_text(pim, encoding="utf-8")
        pit = ""
        for name, color in (("default", "1 1 1"), ("blue", "0.25 0.5 1")):
            pit += f'Look {{\nName: "{name}"\nMaterial {{\nEffect: "eut2.truckpaint"\nAttribute {{\nTag: "diffuse"\nValue: ({color})\n}}\n}}\n}}\n'
        for variant, trim_visible in (("standard", 0), ("full", 1)):
            pit += f'Variant {{\nName: "{variant}"\n'
            for name, visible in (("body", 1), ("trim", trim_visible)):
                pit += f'Part {{\nName: "{name}"\nAttribute {{\nTag: "visible"\nValue: ({visible})\n}}\n}}\n'
            pit += '}\n'
        path.with_suffix(".pit").write_text(pit, encoding="utf-8")
        return path.with_suffix(".sgm")

    def model_entries(self, *names):
        entries = [{"path": f"/def/{name}.sii", "sourcePath": f"/def/{name}.sii", "unitId": name,
                    "model": f"/vehicle/{name}.pmd", "baseModel": f"/vehicle/{name}.pmd", "fields": {}} for name in names]
        self.store._catalog = entries
        return entries

    def test_material_warning_allows_exported_model_and_still_requires_geometry(self):
        warning = ('<warning> [tobj] /automat/96/.tobj: Unable to mstat file!\n'
                   '<warning> [tobj] /automat/96/.tobj: Unable to load!\n'
                   '<warning> [material] /automat/96/960d89b4c0a3b477.mat: Error in material!\n'
                   '[model] qashqai_cabin: pim:no pit:yes pis:no pic:no pip:no viewer:yes vertices:24 indices:12 materials:1')
        (self.root / 'base.scs').touch()
        self.store.tool_path = self.root / 'converter.exe'
        self.store.tool_path.touch()
        for exported in (True, False):
            with self.subTest(exported=exported):
                entry = self.model_entries('police' if exported else 'missing')[0]
                model_path, _, _, _, export, parsed = self.store._model_paths(entry)
                geometry = export / model_path.lstrip('/')
                # A prior rejected export must also be recoverable.
                incomplete = geometry.with_suffix('.export-incomplete')
                incomplete.parent.mkdir(parents=True, exist_ok=True)
                incomplete.touch()
                with patch('backend.assets.subprocess.Popen') as popen:
                    popen.return_value.returncode = 0
                    popen.return_value.communicate.return_value = (warning, '')
                    if exported:
                        self.write_geometry(geometry)
                        geometry.with_suffix('.pim').unlink()
                        result = self.store.model(entry['path'])
                        self.assertTrue(result['pieces'])
                        self.assertTrue(parsed.is_file())
                        self.assertFalse(incomplete.exists())
                    else:
                        with self.assertRaisesRegex(FileNotFoundError, 'did not export geometry'):
                            self.store.model(entry['path'])
                        self.assertFalse(parsed.exists())
                        self.assertTrue(incomplete.exists())
                    popen.assert_called_once()

    def test_converter_errors_and_nonzero_exit_still_fail(self):
        (self.root / 'base.scs').touch()
        self.store.tool_path = self.root / 'converter.exe'
        self.store.tool_path.touch()
        for code, message in ((1, ''), (0, '<error> [model] broken'),
                              (0, 'ERROR: broken'), (0, '  FATAL broken')):
            for stderr in (False, True):
                with self.subTest(code=code, message=message, stderr=stderr):
                    with patch('backend.assets.subprocess.Popen') as popen:
                        popen.return_value.returncode = code
                        popen.return_value.communicate.return_value = ('', message) if stderr else (message, '')
                        with self.assertRaisesRegex(RuntimeError, 'ConverterPIX failed'):
                            self.store._run(['-m', '/vehicle/broken'])

    def test_bundled_catalog_matches_loose_truck_trailer_wheels_and_hookups(self):
        records = {
            "/def/vehicle/truck/test/chassis/base.sii": 'accessory_chassis_data : chassis.test {\nname: "Truck frame"\nmodel: "/truck.pmd"\nprice: 150\n}',
            "/def/vehicle/truck/test/cabin/UPPER.SII": 'accessory_cabin_data : cabin.test {\nmodel: "/cab.pmd"\n}',
            "/def/vehicle/trailer_owned/test/body/base.sii": 'accessory_body_data : body.test {\nname: "Trailer body"\nmodel: "/trailer.pmd"\n}',
            "/def/vehicle/f_tire/base.sii": 'accessory_wheel_data : tire.test {\nmodel: "/tire.pmd"\n}',
            "/def/vehicle/trailer_wheel/r_disc/base.sii": 'accessory_wheel_data : disc.test {\nmodel: "/disc.pmd"\n}',
            "/def/vehicle/addon_hookups/lamps.sii": 'addon_hookup_data : lamp.test {\nmodel: "/lamp.pmd"\n}',
            "/def/vehicle/addon_hookups/horns.sui": 'addon_hookup_data : horn.test {\nmodel: "/horn.pmd"\n}\naddon_hookup_data : horn.second {\nmodel: "/horn2.pmd"\n}',
            "/def/vehicle/truck/test/chassis/settings.sui": 'accessory_chassis_data : ignored {\nmodel: "/ignored.pmd"\n}',
        }
        loose, bundled = self.root / "loose", self.root / "bundled"
        for name, text in records.items():
            file = loose / name.lstrip("/")
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(text, encoding="utf-8")
        self.write_bundle(bundled, dict(reversed(list(records.items()))))
        catalog = self.store._read_catalog(bundled)
        self.assertEqual(catalog, self.store._read_catalog(loose))
        self.assertEqual(len(catalog), 8)
        self.assertEqual({entry["category"] for entry in catalog}, {"chassis", "cabin", "body", "f_tire", "r_disc", "hookup"})
        self.assertEqual([file.name for file in bundled.iterdir()], ["definitions.sgbundle"])

    def test_bundle_only_paint_job_includes_settings_and_accessory_overrides(self):
        if Image is None:
            self.skipTest("Pillow is not installed")
        root = self.store.cache_path / "catalog" / self.store._fingerprint()
        path = "/def/vehicle/truck/test/paint_job/test.sii"
        self.write_bundle(root, {
            path: 'accessory_paint_job_data : paint.test {\n@include "settings.sui"\npaint_job_mask: "/main.tobj"\n}',
            str(Path(path).with_name("settings.sui")).replace("\\", "/"): 'airbrush: false\nbase_color: (1,0.5,0)\nsuitable_for[]: "cab.test"\n',
            "/def/vehicle/truck/test/paint_job/accessory/test.sii": '@include "overrides.sui"',
            "/def/vehicle/truck/test/paint_job/accessory/overrides.sui": 'simple_paint_job_data : .paint {\npaint_job_mask: "/override.tobj"\nacc_list[]: "sunshld.painted"\nacc_list[]: "mirror.painted"\n}',
        })
        self.store._catalog = self.store._read_catalog(root)
        def export(arguments, **kwargs):
            self.assertEqual(arguments[2], "-t")
            target = Path(arguments[1]) / arguments[3].lstrip("/").replace(".tobj", ".png")
            target.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGBA", (1, 1), (1, 2, 3, 255)).save(target)
            return ""
        with patch.object(self.store, "_run", side_effect=export) as run:
            settings = self.store.paint_job(path, textures=False)
            self.assertEqual(settings["suitableFor"], ["cab.test"])
            self.assertEqual(settings["fields"]["base_color"], "(1,0.5,0)")
            run.assert_not_called()
            painted = self.store.paint_job(path)
            self.assertEqual(set(painted["overrides"]), {"sunshld.painted", "mirror.painted"})
            self.assertEqual(painted["overrides"]["sunshld.painted"], painted["overrides"]["mirror.painted"])
            self.assertEqual(run.call_count, 2)
            self.assertIs(self.store.paint_job(path), painted)
        self.assertFalse((root / "def").exists())

    def test_physics_patch_resolves_shared_bundled_include_without_extraction(self):
        root = self.root / "physics"
        self.write_bundle(root, {
            "/def/toys/main.sii": '@include "first.sui"\n@include "second.sui"',
            "/def/toys/first.sui": '@include "shared.sui"',
            "/def/toys/second.sui": '@include "shared.sui"\n@include "cloth.sui"',
            "/def/toys/shared.sui": 'physics_patch_data : .other {\nx_size: 1\n}',
            "/def/toys/cloth.sui": 'physics_patch_data : .cloth {\nmaterial: "/cloth.mat"\nx_size: 0.4\ny_size: 0.25\n}',
        })
        with patch.object(self.store, "_run", side_effect=AssertionError("Bundled includes need no extraction")):
            patch_data = _patch_definition(root / "def/toys/main.sii", ".cloth", read_file=lambda file: self.store._definition_text(file, root))
        self.assertEqual(patch_data, {"material": "/cloth.mat", "x_size": "0.4", "y_size": "0.25"})
        self.assertFalse((root / "def").exists())

    def test_native_and_legacy_models_match_for_pit_looks_variants_uv1_and_locators(self):
        native = self.write_geometry(self.root / "geometry" / "truck")
        for look, variant, count in ((None, None, 1), ("BLUE", "FULL", 2), ("blue", "standard", 1)):
            with self.subTest(look=look, variant=variant):
                parsed = _parse_model(native, native.with_suffix(".pit"), native.parent, look, variant)
                legacy = _parse_model(native.with_suffix(".pim"), native.with_suffix(".pit"), native.parent, look, variant)
                self.assertEqual(parsed, legacy)
                self.assertEqual(len(parsed["pieces"]), count)
                self.assertEqual(parsed["pieces"][0]["uvs1"], [.25, .5, .75, .5, .25, 1])
                self.assertEqual(parsed["pieces"][0]["indices"], [0, 2, 1])
                self.assertEqual(parsed["locators"][0]["rotation"], [0, 0, .5, .5])
                self.assertEqual(parsed["pieces"][0]["material"]["color"], [.25, .5, 1] if look else [1, 1, 1])

    def test_batch_deduplicates_model_across_definitions_looks_and_tracks_failed_jobs(self):
        entries = self.model_entries("good", "bad")
        alias = {**entries[0], "path": "/def/alias.sii"}
        self.store._catalog = [*entries, alias]
        submitted = []
        def convert(arguments, **kwargs):
            self.assertEqual(arguments[0], "--batch")
            rows = Path(arguments[1]).read_text(encoding="utf-8").splitlines()
            submitted.extend(rows)
            statuses = []
            for index, row in enumerate(rows):
                kind, model, export = row.split("\t")
                self.assertEqual(kind, "model")
                success = model.endswith("/good")
                if success:
                    self.write_geometry(Path(export) / model.lstrip("/"))
                statuses.append(json.dumps({"garageJob": index, "kind": "model", "path": model,
                                            "success": success, "error": None if success else "broken model"}))
            return "Converter log\n{invalid json\n" + "\n".join(statuses)
        with patch.object(self.store, "_run", side_effect=convert) as run:
            self.store.prepare_models([(entries[0]["path"], "blue", "full"), (entries[0]["path"], "default", "standard"),
                                       (alias["path"], None, None), (entries[1]["path"], None, None)])
            self.assertEqual(run.call_count, 1)
        self.assertEqual(len(submitted), 2)
        good_paths, bad_paths = (self.store._model_paths(entry) for entry in entries)
        good_geometry = good_paths[4] / "vehicle/good.sgm"
        bad_marker = bad_paths[4] / "vehicle/bad.export-incomplete"
        self.assertFalse(good_geometry.with_suffix(".export-incomplete").exists())
        self.assertTrue(bad_marker.is_file())
        self.assertEqual(self.store._model_cache, {})
        self.assertEqual(list(self.store.cache_path.glob("*.tsv")), [])
        with patch.object(self.store, "_run", side_effect=AssertionError("Do not convert failed or completed batch jobs again")):
            self.assertEqual(self.store.model(entries[0]["path"], "blue", "full")["look"], "blue")
            with self.assertRaisesRegex(RuntimeError, "broken model"):
                self.store.model(entries[1]["path"])
        self.assertTrue(self.store._model_paths(entries[0], "blue", "full")[5].is_file())
        self.assertFalse(bad_paths[5].exists())

    def test_batch_skips_memory_parsed_legacy_and_native_exports(self):
        # This test exercises backwards-compatible readers after migration acceptance.
        self.store._cache_migration_required = False
        entries = self.model_entries("memory", "parsed", "legacy", "native")
        for entry in entries:
            paths = self.store._model_paths(entry)
            if entry["unitId"] == "memory":
                self.store._model_cache[paths[3]] = '{"pieces":[],"locators":[]}'
            elif entry["unitId"] == "parsed":
                paths[5].parent.mkdir(parents=True, exist_ok=True)
                paths[5].write_text('{"pieces":[],"locators":[]}', encoding="utf-8")
            else:
                geometry = self.write_geometry(paths[4] / paths[0].lstrip("/"))
                geometry.with_suffix(".sgm" if entry["unitId"] == "legacy" else ".pim").unlink()
        with patch.object(self.store, "_run", side_effect=AssertionError("Completed exports need no batch")):
            self.store.prepare_models([(entry["path"], None, None) for entry in entries])

    def test_cancelled_batch_retains_incomplete_markers_and_publishes_no_cache(self):
        entries = self.model_entries("one", "two")
        def cancelled(arguments, **kwargs):
            rows = Path(arguments[1]).read_text(encoding="utf-8").splitlines()
            _, model, export = rows[0].split("\t")
            self.write_geometry(Path(export) / model.lstrip("/"))
            raise CancelledError()
        with patch.object(self.store, "_run", side_effect=cancelled):
            with self.assertRaises(CancelledError):
                self.store.prepare_models([(entry["path"], None, None) for entry in entries], cancelled=lambda: False)
        for entry in entries:
            paths = self.store._model_paths(entry)
            self.assertTrue((paths[4] / (paths[0].lstrip("/") + ".export-incomplete")).is_file())
            self.assertFalse(paths[5].exists())
        self.assertEqual(self.store._model_cache, {})
        self.assertEqual(list(self.store.cache_path.glob("*.tsv")), [])

    def test_scene_batches_only_missing_selected_models_and_declared_hookups(self):
        assets = FakeAssets()
        prepared = []
        assets.prepare_models = lambda requests, cancelled=None: prepared.append(requests)
        accessories = [
            {"id": "frame", "dataPath": "/chassis", "category": "chassis", "type": "vehicle_accessory", "fields": {}, "slots": []},
            {"id": "cab", "dataPath": "/cab", "category": "cabin", "type": "vehicle_accessory", "fields": {"look": '"blue"', "variant": '"full"'}, "slots": []},
            {"id": "bar", "dataPath": "/bar", "category": "r_grill", "type": "vehicle_addon_accessory", "fields": {},
             "slots": [{"name": "slot_0", "hookup": "horn.addon_hookup"}, {"name": "slot_1", "hookup": "unknown.addon_hookup"}]},
        ]
        cached_frame = assets.model("/chassis")
        cached_bar = assets.model("/bar")
        cache = {("/chassis", None, None): cached_frame, ("/bar", None, None): cached_bar}
        assets.calls.clear()
        scene = build_scene({"id": "truck", "accessories": accessories}, assets, model_cache=cache)
        self.assertEqual(prepared, [[("/cab", '"blue"', '"full"'), ("/horn#horn", None, None)]])
        self.assertEqual(assets.calls, ["/cab", "/horn#horn"])
        self.assertIs(scene["parts"][0]["model"], cached_frame)
        prepared.clear()
        build_scene({"id": "truck", "accessories": accessories}, assets, model_cache=cache)
        self.assertEqual(prepared, [])


class ConverterCapabilityTests(unittest.TestCase):
    def test_upstream_probe_uses_help_and_caches_result(self):
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / "converter.exe"
            executable.write_bytes(b"stock")
            store = AssetStore(cache_path=Path(temp))
            store.tool_path = executable
            with patch("backend.assets.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "Normal upstream help", "")) as run:
                self.assertEqual(store._converter_capabilities(), {})
                self.assertEqual(store._converter_capabilities(), {})
                run.assert_called_once()
                self.assertEqual(run.call_args.args[0], [str(executable), "--help"])

    def test_fork_capabilities_refresh_when_executable_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / "converter.exe"
            executable.write_bytes(b"fork")
            store = AssetStore(cache_path=Path(temp))
            store.tool_path = executable
            features = {"garageFormatVersion": 1, "batch": True}
            responses = [subprocess.CompletedProcess([], 0, "--garage-capabilities", ""),
                         subprocess.CompletedProcess([], 0, json.dumps(features), ""),
                         subprocess.CompletedProcess([], 0, "Upstream replacement", "")]
            with patch("backend.assets.subprocess.run", side_effect=responses) as run:
                self.assertEqual(store._converter_capabilities(), features)
                self.assertEqual(store._converter_capabilities(), features)
                self.assertEqual(run.call_count, 2)
                executable.write_bytes(b"different upstream executable")
                self.assertEqual(store._converter_capabilities(), {})
                self.assertEqual(run.call_count, 3)


if __name__ == "__main__":
    unittest.main()
