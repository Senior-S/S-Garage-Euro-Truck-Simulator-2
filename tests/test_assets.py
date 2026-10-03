import hashlib
import json
import struct
import tempfile
import unittest
from concurrent.futures import CancelledError
from pathlib import Path
from unittest.mock import patch

from backend.assets import AssetStore, Image, _parse_model, _records, _texture_url, _patch_definition, _patch_piece


class AssetParserTests(unittest.TestCase):
    def test_detail_model_cab_is_renderable_in_fresh_and_cached_catalogs(self):
        path = "/def/vehicle/truck/volvo.fh_2024/cabin/l2h3_8x4_aero.sii"
        model = "/vehicle/truck/volvo_fh_2024/cabin/globe_xl_aero_2024.pmd"
        fresh = AssetStore._catalog_entry(path, "cab.volvo.fh_2024.cabin", "cabin", Path(path), {"detail_model": [model], "variant": ["default"], "look": ["default"]})
        cached = AssetStore._enrich_catalog_entry({**fresh, "baseModel": None, "model": None})
        self.assertEqual(fresh["baseModel"], model)
        self.assertEqual(fresh["model"], model)
        self.assertEqual(cached["baseModel"], model)
        self.assertEqual(cached["model"], model)
        cached["fields"]["model"] = "/preferred.pmd"
        cached["baseModel"] = None
        self.assertEqual(AssetStore._enrich_catalog_entry(cached)["baseModel"], "/preferred.pmd")

    def test_paint_job_imports_included_settings_and_all_accessory_overrides_once(self):
        with tempfile.TemporaryDirectory() as temp:
            store = AssetStore(cache_path=Path(temp))
            path = "/def/vehicle/truck/test/paint_job/test.sii"
            store._catalog = [{"path": path, "sourcePath": path, "unitId": "test.paint_job", "unitName": "test.paint_job"}]
            root = store.cache_path / "catalog" / store._fingerprint()
            definition = root / path.lstrip("/")
            definition.parent.mkdir(parents=True)
            definition.write_text('accessory_paint_job_data : test.paint_job {\n@include "settings.sui"\npaint_job_mask: "/main.tobj"\n}')
            definition.with_name("settings.sui").write_text('airbrush: false\nbase_color: (1,1,1)\n')
            overrides = definition.parent / "accessory" / definition.name
            overrides.parent.mkdir()
            overrides.write_text('simple_paint_job_data : .a {\npaint_job_mask: "/override.tobj"\nacc_list[]: "sunshld.painted"\nacc_list[]: "mirror.painted"\n}')
            def export(arguments, **kwargs):
                target = Path(arguments[1]) / arguments[3].lstrip("/").replace(".tobj", ".png")
                target.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGBA", (1, 1), (0, 0, 0, 0)).save(target)
            with patch.object(store, "_run", side_effect=export) as run:
                preview = store.paint_job(path, include_overrides=False)
                self.assertEqual(preview["overrides"], {})
                self.assertEqual(run.call_count, 1)
                job = store.paint_job(path)
                self.assertEqual(job["fields"]["base_color"], "(1,1,1)")
                self.assertEqual(set(job["overrides"]), {"sunshld.painted", "mirror.painted"})
                self.assertIs(store.paint_job(path), job)
                self.assertEqual(run.call_count, 2)
                self.assertTrue(job["texture"].endswith(".opaque.png"))
                self.assertEqual(preview["texture"], job["texture"])
                with self.assertRaises(CancelledError):
                    store.paint_job(path, cancelled=lambda: True, include_overrides=False)

    def test_packed_light_mask_preserves_rgb_when_alpha_is_zero(self):
        with tempfile.TemporaryDirectory() as temp:
            export = Path(temp) / "models" / "test"
            export.mkdir(parents=True)
            Image.new("RGBA", (1, 1), (0, 255, 128, 0)).save(export / "mask.png")
            rgb = _texture_url({"texture_base": "/mask"}, export, ignore_alpha=True)
            alpha = _texture_url({"texture_base": "/mask"}, export, alpha_only=True)
            self.assertEqual(Image.open(Path(temp) / rgb.removeprefix("/cache/")).getpixel((0, 0)), (0, 255, 128))
            self.assertEqual(Image.open(Path(temp) / alpha.removeprefix("/cache/")).getpixel((0, 0)), (0, 0, 0))

    def test_model_result_registers_redirected_textures_and_rejects_cache_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = AssetStore(cache_path=root / "cache")
            texture = store.cache_path / "models/toy/santa.png"
            redirected = root / "package-cache/santa.png"
            original_resolve = Path.resolve
            with patch.object(Path, "resolve", autospec=True, side_effect=lambda path: redirected if path == texture else original_resolve(path)):
                model = {"pieces": [{"material": {"texture": "/cache/models/toy/santa.png"}}]}
                self.assertEqual(store._model_result(json.dumps(model)), model)
            self.assertEqual(store.texture_files, {"models/toy/santa.png": redirected})
            with self.assertRaisesRegex(ValueError, "outside the asset cache"):
                store._model_result(json.dumps({"pieces": [{"material": {"texture": "/cache/../settings.json"}}]}))

    def test_toy_models_include_all_scoped_physics_meshes_and_cache_rest_pose(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = AssetStore(cache_path=root)
            entry = {"path": "/def/toy.sui#toy", "sourcePath": "/def/toy.sui", "unitId": "toy", "unitName": "toy",
                     "fields": {"model": "/base.pmd", "data[]": ".second"}}
            store._catalog = [entry]
            fingerprint = store._fingerprint()
            definition = root / "catalog" / fingerprint / "def/toy.sui"
            definition.parent.mkdir(parents=True)
            definition.write_text('''accessory_hookup_int_data : toy {
 data[]: .first
 data[]: .second
}
physics_toy_data : .first {
 phys_model: "/head.pmd"
 locator_hook_offset: (0, 0.045f, -0.03f) # attachment
}
physics_toy_data : .second {
 phys_model: "/head.pmd"
 locator_hook_offset: (0, 0.08f, 0)
}
''', encoding="utf-8")
            for path in ("/base", "/head"):
                export = root / "models" / hashlib.sha256((fingerprint + path).encode()).hexdigest()[:20]
                export.mkdir(parents=True)
                (export / (path.lstrip("/") + ".pim")).write_text("exported", encoding="utf-8")
            def parsed(pim, *args):
                return {"pieces": [{"name": pim.stem, "positions": [0, 0, 0, 1, 1, 1]}], "locators": []}
            with patch("backend.assets._parse_model", side_effect=parsed) as parse, patch.object(store, "_run", side_effect=AssertionError("Reuse exports")):
                model = store.model(entry["path"])
                self.assertEqual([piece["name"] for piece in model["pieces"]], ["base", "head", "head"])
                self.assertEqual(model["pieces"][1]["positions"], [0, .045, -.03, 1, 1.045, .97])
                self.assertEqual(model["pieces"][2]["positions"], [0, .08, 0, 1, 1.08, 1])
                # Composing the parent must not translate the child's cached geometry.
                cached_child = json.loads(next(value for value in store._model_cache.values() if json.loads(value)["pieces"][0]["name"] == "head"))
                self.assertEqual(cached_child["pieces"][0]["positions"], [0, 0, 0, 1, 1, 1])
                store._model_cache.clear()
                self.assertEqual(store.model(entry["path"]), model)
                self.assertEqual(parse.call_count, 3)

    def test_patch_cloth_uses_anchor_rotation_scale_and_top_origin_uvs(self):
        patch = {"x_size": "0.4", "y_size": "0.25"}
        anchor = {"position": [3, 4, 5], "rotation": [0, 1, 0, 0], "scale": [2, 1, 1]}
        piece = _patch_piece(patch, anchor, "/flag.png")
        self.assertEqual(piece["positions"], [3, 4, 5, 2.2, 4, 5, 3, 3.75, 5, 2.2, 3.75, 5])
        self.assertEqual(piece["uvs"], [0, 0, 1, 0, 0, 1, 1, 1])
        self.assertEqual(len(piece["indices"]), 6)
        self.assertEqual(piece["material"]["texture"], "/flag.png")
        anchor["rotation"] = [0, 0, 0, 1]
        self.assertEqual(_patch_piece(patch, anchor, "/flag.png")["positions"][3], 3.8)
        anchor["name"] = "anchor_r"
        self.assertEqual(_patch_piece(patch, anchor, "/flag.png")["positions"][:6], [2.2, 4, 5, 3, 4, 5])
        with self.assertRaises(ValueError):
            _patch_piece({"x_size": "nan", "y_size": "0.25"}, anchor, "/flag.png")

    def test_patch_definition_resolves_referenced_unit_in_shared_include(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            file = root / "flag.sii"
            file.write_text('@include "cloth.sui"\n', encoding="utf-8")
            (root / "cloth.sui").write_text('physics_patch_data : .cloth {\n material: "/ar.mat"\n x_size: 0.4\n y_size: 0.25\n}\n', encoding="utf-8")
            self.assertEqual(_patch_definition(file, ".cloth")["material"], "/ar.mat")
            self.assertIsNone(_patch_definition(file, ".unrelated"))
            (root / "cloth.sui").unlink()
            file.write_text('@include "shared/cloth.sui"\n', encoding="utf-8")
            loaded = []
            def extract_missing(path):
                loaded.append(path)
                path.write_text('physics_patch_data : .cloth {\n x_size: 0.4\n}\n', encoding="utf-8")
            self.assertEqual(_patch_definition(file, ".cloth", load_file=extract_missing)["x_size"], "0.4")
            self.assertEqual(loaded, [root / "shared/cloth.sui"])

    def test_patch_definition_reports_circular_includes(self):
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "flag.sii"
            file.write_text('@include "flag.sii"\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Circular physics patch include"):
                _patch_definition(file, ".cloth")

    @unittest.skipIf(Image is None, "Pillow is not installed")
    def test_flag_model_includes_cloth_and_persists_it_in_parsed_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = AssetStore(game_path=str(root / "game"), cache_path=root)
            entry = {"path": "/def/flag.sii", "sourcePath": "/def/flag.sii", "unitId": "flag", "unitName": "flag",
                     "model": "/flag.pmd", "baseModel": "/flag.pmd", "fields": {"data": ".cloth"}}
            store._catalog = [entry]
            fingerprint = store._fingerprint()
            definition = root / "catalog" / fingerprint / "def/flag.sii"
            definition.parent.mkdir(parents=True)
            definition.write_text('physics_patch_data : .cloth {\n material: "/ar.mat"\n x_size: 0.4\n y_size: 0.25\n}\n', encoding="utf-8")
            export = root / "models" / hashlib.sha256((fingerprint + "/flag").encode()).hexdigest()[:20]
            export.mkdir(parents=True)
            (export / "flag.pim").write_text("Already exported", encoding="utf-8")
            (export / "ar.mat").write_text('effect : "eut2.dif.shadow.rfx" { texture : "texture_base" { source : "ar.tobj" } }', encoding="utf-8")
            Image.new("RGB", (2, 2), (100, 180, 240)).save(export / "ar.png")
            pole = {"pieces": [{"name": "pole"}], "locators": [{"name": "anchor_l", "position": [0, 1, 0], "rotation": [0, 0, 0, 1]}]}
            with patch("backend.assets._parse_model", return_value=pole) as parse, patch.object(store, "_run", side_effect=AssertionError("Existing exports must be reused")):
                model = store.model(entry["path"])
                self.assertEqual([piece["name"] for piece in model["pieces"]], ["pole", "physics_patch"])
                store._model_cache.clear()
                self.assertEqual(store.model(entry["path"]), model)
                self.assertEqual(parse.call_count, 1)

    @unittest.skipIf(Image is None, "Pillow is not installed")
    def test_dxt4_texture_is_unpremultiplied_without_mutating_dds(self):
        # One 4x4 BC3 block: premultiplied red ~= 66 at alpha 128. The
        # second texel has zero alpha, and must decode to transparent black.
        alpha_indices = 1 << 3
        alpha_block = bytes((128, 0)) + alpha_indices.to_bytes(6, "little")
        color_block = struct.pack("<HHI", 8 << 11, 0, 1 << 2)
        pixel_format = struct.pack("<II4s5I", 32, 4, b"DXT4", 0, 0, 0, 0, 0)
        header = struct.pack("<7I44x", 124, 0x81007, 4, 4, 16, 0, 0)
        header += pixel_format + struct.pack("<5I", 0x1000, 0, 0, 0, 0)
        dds_data = b"DDS " + header + alpha_block + color_block

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            export = root / "models" / "sample"
            export.mkdir(parents=True)
            dds = export / "sample.dds"
            dds.write_bytes(dds_data)

            url = _texture_url({"texture[0]:texture_base": "/sample"}, export)
            rgba_path = export / "sample.png"
            with Image.open(rgba_path) as image:
                pixels = image.convert("RGBA")

            self.assertEqual(url, "/cache/models/sample/sample.png")
            self.assertGreaterEqual(pixels.getpixel((0, 0))[0], 130)
            self.assertEqual(pixels.getpixel((0, 0))[3], 128)
            self.assertEqual(pixels.getpixel((1, 0)), (0, 0, 0, 0))
            self.assertEqual(dds.read_bytes(), dds_data)

    @unittest.skipIf(Image is None, "Pillow is not installed")
    def test_dxt4_glass_export_removes_alpha_after_unpremultiplying(self):
        alpha_block = bytes((128, 0)) + (1 << 3).to_bytes(6, "little")
        color_block = struct.pack("<HHI", 8 << 11, 0, 1 << 2)
        pixel_format = struct.pack("<II4s5I", 32, 4, b"DXT4", 0, 0, 0, 0, 0)
        header = struct.pack("<7I44x", 124, 0x81007, 4, 4, 16, 0, 0)
        header += pixel_format + struct.pack("<5I", 0x1000, 0, 0, 0, 0)
        dds_data = b"DDS " + header + alpha_block + color_block

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            export = root / "models" / "sample"
            export.mkdir(parents=True)
            (export / "sample.dds").write_bytes(dds_data)
            url = _texture_url({"texture[0]:texture_base": "/sample"}, export, ignore_alpha=True)
            with Image.open(export / "sample.opaque.png") as image:
                rgb = image.convert("RGB")

        self.assertEqual(url, "/cache/models/sample/sample.opaque.png")
        self.assertGreaterEqual(rgb.getpixel((0, 0))[0], 130)
        self.assertEqual(rgb.getpixel((1, 0)), (0, 0, 0))

    def test_records_keep_multiline_definition_bodies(self):
        records = _records('''
accessory_addon_data : mirror.left {
    name: "Left mirror"
    model: "/vehicle/truck/test/mirror"
}
''')
        self.assertEqual(records[0][0:2], ("accessory_addon_data", "mirror.left"))
        self.assertIn('"/vehicle/truck/test/mirror"', records[0][2])

    def test_catalog_enriches_exterior_and_interior_model_fields(self):
        definition = AssetStore._catalog_entry(
            "/def/vehicle/truck/scania_2016/accessory/r_grill/shape1_h.sii",
            "shape1_h.scania_2016.r_grill",
            "addon",
            Path("/game/def/vehicle/truck/scania_2016/accessory/r_grill/shape1_h.sii"),
            {
                "exterior_model": ["/vehicle/truck/scania_2016/accessory/r_grill/shape01h"],
                "exterior_look": ["chrome"],
                "exterior_variant": ["standard"],
                "interior_model": ["/vehicle/truck/scania_2016/interior/grill_interior"],
                "interior_look": ["dark"],
                "interior_variant": ["cab"],
            },
        )
        definition = AssetStore._enrich_catalog_entry(definition)

        self.assertEqual(definition["category"], "r_grill")
        self.assertEqual(definition["exteriorModel"], "/vehicle/truck/scania_2016/accessory/r_grill/shape01h")
        self.assertEqual(definition["exteriorLook"], "chrome")
        self.assertEqual(definition["exteriorVariant"], "standard")
        self.assertEqual(definition["interiorModel"], "/vehicle/truck/scania_2016/interior/grill_interior")
        self.assertEqual(definition["interiorLook"], "dark")
        self.assertEqual(definition["interiorVariant"], "cab")

    def test_parsed_models_persist_by_variant_and_parser_fingerprint(self):
        with tempfile.TemporaryDirectory() as temp:
            store = AssetStore(cache_path=Path(temp))
            definition = {
                "path": "/def/vehicle/truck/test/accessory/chassis/model.sii",
                "unitId": "model.test.chassis",
                "unitName": "model.test.chassis",
                "category": "chassis",
                "baseModel": "/vehicle/truck/test/model.pmd",
                "fields": {"model": "/vehicle/truck/test/model.pmd"},
                "model": "/vehicle/truck/test/model.pmd",
            }
            store._catalog = [definition]
            store._parser_fingerprint = "parser-one"
            model_path = "/vehicle/truck/test/model"
            selected_look, selected_variant = "blue", "sport"
            asset_fingerprint = store._fingerprint()
            entry_key = hashlib.sha256(
                f"{asset_fingerprint}:parser-one:{definition['path']}:{selected_look}:{selected_variant}".encode()
            ).hexdigest()
            export_key = hashlib.sha256((asset_fingerprint + model_path).encode()).hexdigest()[:20]
            parsed_path = Path(temp) / "models" / export_key / "parsed" / f"{entry_key}.json"
            parsed_path.parent.mkdir(parents=True)
            expected = {"pieces": [], "locators": [], "look": selected_look, "variant": selected_variant, "diagnostics": []}
            parsed_path.write_text(json.dumps(expected), encoding="utf-8")

            with patch.object(store, "_run", side_effect=AssertionError("cached model should not be converted")):
                self.assertEqual(store.model(definition["path"], selected_look, selected_variant), expected)
                store._model_cache.clear()
                store._parser_fingerprint = "parser-two"
                with self.assertRaises(AssertionError):
                    store.model(definition["path"], selected_look, selected_variant)

    def test_model_cancels_before_catalog_or_export(self):
        store = AssetStore()
        with self.assertRaises(CancelledError):
            store.model("/def/vehicle/test.sii", cancelled=lambda: True)

    def test_cancelled_conversion_leaves_incomplete_export_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            store = AssetStore(cache_path=Path(temp))
            definition = {
                "path": "/def/vehicle/test/chassis.sii", "unitId": "test.chassis", "unitName": "test.chassis",
                "category": "chassis", "model": "/vehicle/test/chassis.pmd", "baseModel": "/vehicle/test/chassis.pmd",
                "fields": {"model": "/vehicle/test/chassis.pmd"},
            }
            store._catalog = [definition]
            with patch.object(store, "_run", side_effect=CancelledError()):
                with self.assertRaises(CancelledError):
                    store.model(definition["path"], cancelled=lambda: False)
            export_key = hashlib.sha256((store._fingerprint() + "/vehicle/test/chassis").encode()).hexdigest()[:20]
            marker = Path(temp) / "models" / export_key / "vehicle" / "test" / "chassis.export-incomplete"
            self.assertTrue(marker.is_file())

    def test_glass_shader_keeps_pane_visible(self):
        pim = '''
Material { Alias: "glass" Effect: "eut2.glass" }
Piece {
 Material: 0
 Stream {
  Tag: "_POSITION"
  0 ( &00000000 &00000000 &00000000 )
  1 ( &3f800000 &00000000 &00000000 )
  2 ( &00000000 &3f800000 &00000000 )
 }
 0 ( 0 1 2 )
}
'''
        pit = '''
Look {
 Name: "default"
 Material {
  Alias: "glass"
  Effect: "eut2.glass"
  Attribute { Tag: "diffuse" Value: ( 1 1 1 ) }
 }
}
'''
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "glass.pim").write_text(pim)
            (root / "glass.pit").write_text(pit)
            model = _parse_model(root / "glass.pim", root / "glass.pit", root)
        self.assertTrue(model["pieces"][0]["material"]["transparent"])
        self.assertEqual(model["pieces"][0]["material"]["opacity"], 0.55)

    def test_glass_texture_alpha_is_removed_without_changing_decal_alpha(self):
        if Image is None:
            self.skipTest("Pillow is not installed")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            export = root / "models" / "test"
            glass = export / "vehicle" / "share" / "glass_int.png"
            decal = export / "vehicle" / "share" / "decal.png"
            glass.parent.mkdir(parents=True)
            Image.new("RGBA", (2, 1), (180, 190, 200, 24)).save(glass)
            Image.new("RGBA", (2, 1), (180, 190, 200, 24)).save(decal)

            glass_url = _texture_url({"texture_base": "/vehicle/share/glass_int"}, export, ignore_alpha=True)
            decal_url = _texture_url({"texture_base": "/vehicle/share/decal"}, export)
            glass_output = root / glass_url.removeprefix("/cache/")
            decal_output = root / decal_url.removeprefix("/cache/")
            with Image.open(glass_output) as image:
                self.assertEqual(image.mode, "RGB")
            with Image.open(decal_output) as image:
                self.assertEqual(image.mode, "RGBA")
                self.assertEqual(image.getchannel("A").getpixel((0, 0)), 24)

    def test_triangle_index_10000_without_space_is_parsed(self):
        pim = '''
Piece {
 Material: 0
 Stream {
  Tag: "_POSITION"
  0 ( &00000000 &00000000 &00000000 )
  1 ( &3f800000 &00000000 &00000000 )
  2 ( &00000000 &3f800000 &00000000 )
 }
 Triangles {
  9999 ( 0 1 2 )
  10000( 0 2 1 )
 }
}
'''
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root / "model.pim"
            path.write_text(pim)
            model = _parse_model(path, None, root)
        self.assertEqual(model["pieces"][0]["indices"], [0, 1, 2, 0, 2, 1])

    def test_model_decodes_streams_traits_variant_and_locators(self):
        pim = '''
Material {
 Alias: "mat_body"
 Effect: "eut2.dif"
}
Material {
 Alias: "mat_shadow"
 Effect: "eut2.fakeshadow"
}
Material {
 Alias: "mat_decal"
 Effect: "eut2.dif.spec.tsnmapuv.paint.decal.over"
}
Piece {
 Index: 0
 Material: 0
 Stream {
  Format: FLOAT3
  Tag: "_POSITION"
  0 ( &3f800000 &00000000 &bf800000 )
  1 ( &00000000 &3f800000 &00000000 )
  2 ( &bf800000 &00000000 &3f800000 )
 }
 Stream {
  Format: FLOAT3
  Tag: "_NORMAL"
  0 ( &00000000 &3f800000 &00000000 )
  1 ( &00000000 &3f800000 &00000000 )
  2 ( &00000000 &3f800000 &00000000 )
 }
 Stream {
  Format: FLOAT2
  Tag: "_UV0"
  0 ( &00000000 &00000000 )
 1 ( &3f800000 &00000000 )
 2 ( &00000000 &3f800000 )
 }
 Triangles {
  0 ( 0 1 2 )
 }
}
Piece {
 Index: 1
 Material: 0
 Stream { Format: FLOAT3 Tag: "_POSITION" 0 ( &3f800000 &00000000 &00000000 ) }
 0 ( 0 0 0 )
}
Piece {
 Index: 2
 Material: 1
 Stream {
  Format: FLOAT3
  Tag: "_POSITION"
  0 ( &3f800000 &00000000 &00000000 )
 }
 0 ( 0 0 0 )
}
Piece {
 Index: 3
 Material: 2
 Stream {
  Format: FLOAT3
  Tag: "_POSITION"
  0 ( &3f800000 &00000000 &00000000 )
 }
 0 ( 0 0 0 )
}
Part {
 Name: "body"
 PieceCount: 1
 Pieces: 0
 LocatorCount: 1
 Locators: 0
}
Part {
 Name: "body_hidden"
 PieceCount: 1
 Pieces: 1
}
Part {
 Name: "shadow"
 PieceCount: 1
 Pieces: 2
}
Part {
 Name: "decal"
 PieceCount: 1
 Pieces: 3
}
Locator {
 Name: "mirror_left"
 Hookup: "flare.vehicle.orange"
 Position: ( &3f800000 &40000000 &40400000 )
 Rotation: ( &00000000 &00000000 &00000000 &3f800000 )
 Scale: ( &3f800000 &3f800000 &3f800000 )
}
'''
        pit = '''
Look {
 Name: "paint"
 Material {
  Attribute {
   Format: FLOAT3
   Tag: "diffuse"
   Value: ( 0.2 0.4 0.6 )
  }
 }
 Material {
  Effect: "eut2.shadowonly.nocull"
 }
 Material {
  Effect: "eut2.dif.spec.tsnmapuv.paint.decal.over"
 }
}
Variant {
 Name: "standard"
 Part {
  Name: "body"
  Attribute {
   Format: INT
   Tag: "visible"
   Value: ( 1 )
  }
 }
 Part {
  Name: "body_hidden"
  Attribute {
   Format: INT
   Tag: "visible"
   Value: ( 0 )
  }
 }
 Part {
  Name: "shadow"
  Attribute {
   Format: INT
   Tag: "visible"
   Value: ( 1 )
  }
 }
 Part {
  Name: "decal"
  Attribute {
   Format: INT
   Tag: "visible"
   Value: ( 1 )
  }
 }
}
'''
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pim_path, pit_path = root / "model.pim", root / "model.pit"
            pim_path.write_text(pim)
            pit_path.write_text(pit)
            model = _parse_model(pim_path, pit_path, root)

        self.assertEqual(model["look"], "paint")
        self.assertEqual(model["variant"], "standard")
        self.assertEqual(len(model["pieces"]), 2)
        self.assertEqual(model["pieces"][0]["positions"], [1.0, 0.0, -1.0, 0.0, 1.0, 0.0, -1.0, 0.0, 1.0])
        self.assertEqual(model["pieces"][0]["indices"], [0, 1, 2])
        self.assertEqual(model["pieces"][0]["material"]["color"], [0.2, 0.4, 0.6])
        decal = model["pieces"][1]["material"]
        self.assertTrue(decal["paintable"])
        self.assertTrue(decal["transparent"])
        self.assertEqual(decal["alphaTest"], 0.01)
        self.assertFalse(decal["depthWrite"])
        self.assertEqual(model["locators"][0]["hookup"], "flare.vehicle.orange")
        self.assertEqual(model["locators"][0]["position"], [1.0, 2.0, 3.0])
        self.assertEqual(model["locators"][0]["rotation"], [0.0, 0.0, 1.0, 0.0])

    def test_locator_only_models_are_valid(self):
        pim = '''
Part {
 Name: "defaultpart"
 PieceCount: 0
 Pieces:
 LocatorCount: 1
 Locators: 0
}
Locator {
 Name: "ml1"
 Hookup: "flare.vehicle.red"
 Position: ( &00000000 &00000000 &00000000 )
 Rotation: ( &00000000 &00000000 &00000000 &3f800000 )
 Scale: ( &3f800000 &3f800000 &3f800000 )
}
'''
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "model.pim"
            path.write_text(pim)
            model = _parse_model(path, None, Path(temp))

        self.assertEqual(model["pieces"], [])
        self.assertEqual(model["locators"][0]["hookup"], "flare.vehicle.red")


if __name__ == "__main__":
    unittest.main()
