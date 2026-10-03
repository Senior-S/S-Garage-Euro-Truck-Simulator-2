from pathlib import Path
from copy import deepcopy
import sys
import unittest
from concurrent.futures import CancelledError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from scene import build_scene, compose, IDENTITY


class FakeAssets:
    def __init__(self):
        self.entries = [
            {"path": "/chassis", "unitId": "chassis", "category": "chassis", "model": "frame"},
            {"path": "/cab", "unitId": "cab", "category": "cabin", "model": "cab"},
            {"path": "/bar", "unitId": "bar", "category": "r_grill", "model": "bar"},
            {"path": "/horn#horn", "unitId": "horn.addon_hookup", "category": "hookup", "model": "horn"},
            {"path": "/tire", "unitId": "tire", "category": "r_tire", "model": "tire"},
            {"path": "/steering", "unitId": "steering", "category": "steering_w", "model": "steering"},
        ]
        self.calls = []
        self.options = []

    def catalog(self):
        return self.entries

    def model(self, path, look=None, variant=None, cancelled=None):
        self.calls.append(path)
        self.options.append((path, look, variant))
        locators = []
        if path == "/chassis":
            locators = [{"name": "r_grill_sh", "position": [0, 3, -2], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1]},
                        {"name": "wheel_r_2_1", "position": [-1, .5, 2], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1]},
                        {"name": "wheel_r_3_1", "position": [1, .5, 2], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1]},
                        {"name": "swheel", **IDENTITY, "position": [-.5, 2, -1]}]
        elif path == "/cab":
            locators = [{"name": "f_wnd_frame", "position": [0, 0, 0], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1]}]
        elif path == "/bar":
            locators = [{"name": "slot_0", "position": [1, .2, 0], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1]}]
        return {"pieces": [{"positions": [0, 0, 0, 1, 0, 0, 0, 1, 0], "indices": [0, 1, 2], "material": {"name": "test"}}], "locators": locators}


class SceneTests(unittest.TestCase):
    def test_paint_job_uses_atlas_on_front_panels_and_override_on_sunshield(self):
        assets = FakeAssets()
        assets.entries.extend([{"path": "/paint", "unitId": "paint", "category": "paint_job"}, {"path": "/shield", "unitId": "painted.test.sunshld", "category": "sunshld", "model": "shield"}])
        assets.paint_job = lambda *args, **kwargs: {"texture": "/atlas", "fields": {}, "overrides": {"sunshld.painted": "/white"}}
        original = assets.model
        def model(*args, **kwargs):
            result = original(*args, **kwargs)
            result["pieces"][0]["material"]["paintable"] = True
            if args[0] == "/cab":
                result["locators"].append({"name": "sunshld", **IDENTITY})
            return result
        assets.model = model
        truck = {"id": "truck", "accessories": [
            {"id": "cab", "type": "vehicle_accessory", "dataPath": "/cab", "category": "cabin", "fields": {}, "slots": []},
            {"id": "shield", "type": "vehicle_addon_accessory", "dataPath": "/shield", "category": "sunshld", "fields": {"paint_color": "(0,0,0)"}, "slots": []},
            {"id": "paint", "type": "vehicle_paint_job_accessory", "dataPath": "/paint", "category": "paint_job", "fields": {"base_color": "(&3f800000,1,1)", "mask_b_color": "(0,.5,1)"}, "slots": []},
        ]}
        scene = build_scene(truck, assets)
        materials = {part["category"]: part["model"]["pieces"][0]["material"] for part in scene["parts"]}
        self.assertEqual(materials["cabin"]["paintTexture"], "/atlas")
        self.assertEqual(materials["sunshld"]["paintTexture"], "/white")
        self.assertEqual(materials["sunshld"]["color"], [1, 1, 1])
        self.assertEqual(materials["cabin"]["paintColors"][2], [0, .5, 1])

    def test_marker_edit_reuses_base_models_and_imports_only_new_hookup(self):
        assets = FakeAssets()
        truck = {"id": "truck", "accessories": [
            {"id": "frame", "dataPath": "/chassis", "category": "chassis", "type": "vehicle_accessory", "fields": {}, "slots": []},
            {"id": "bar", "dataPath": "/bar", "category": "r_grill", "type": "vehicle_addon_accessory", "fields": {}, "slots": []},
        ]}
        cache = {}
        before = build_scene(truck, assets, model_cache=cache)
        assets.calls.clear()
        truck["accessories"][1]["slots"] = [{"name": "slot_0", "hookup": "horn.addon_hookup"}]
        after = build_scene(truck, assets, model_cache=cache)
        self.assertEqual(assets.calls, ["/horn#horn"])
        self.assertIs(before["parts"][0]["model"], after["parts"][0]["model"])
        self.assertEqual(after["parts"][-1]["position"], [1, 3.2, -2])
        truck["accessories"][1]["slots"] = []
        undone = build_scene(truck, assets, model_cache=cache)
        self.assertEqual(undone["parts"], before["parts"])
        self.assertNotIn(("/horn#horn", None, None), cache)

    def test_quaternion_parent_rotation_and_scale_transform(self):
        parent = {"position": [10, 0, 0], "rotation": [0, 0, 1, 0], "scale": [2, 1, 1]}
        self.assertEqual(compose(parent, {**IDENTITY, "position": [1, 0, 0]})["position"], [8, 0, 0])

    def test_real_locator_assembly_duplicate_hookups_and_wheel_offsets(self):
        assets = FakeAssets()
        truck = {"id": "truck", "accessories": [
            {"id": "frame", "dataPath": "/chassis", "category": "chassis", "type": "vehicle_accessory", "fields": {}, "slots": []},
            {"id": "bar", "dataPath": "/bar", "category": "r_grill", "type": "vehicle_addon_accessory", "fields": {},
             "slots": [{"name": "slot_0", "hookup": "horn.addon_hookup"}, {"name": "slot_0", "hookup": "horn.addon_hookup"}]},
            {"id": "wheels", "dataPath": "/tire", "category": "r_tire", "type": "vehicle_wheel_accessory", "fields": {"offset": "2"}, "slots": []},
            {"id": "steering", "dataPath": "/steering", "category": "steering_w", "type": "vehicle_addon_accessory", "fields": {}, "slots": []},
        ]}
        scene = build_scene(truck, assets)
        bar = next(p for p in scene["parts"] if p["category"] == "r_grill")
        self.assertEqual(bar["position"], [0, 3, -2])
        hooks = [p for p in scene["parts"] if p["category"] == "hookup"]
        self.assertEqual(len(hooks), 2)
        self.assertEqual(hooks[0]["position"], [1, 3.2, -2])
        tires = [p for p in scene["parts"] if p["category"] == "r_tire"]
        self.assertEqual(len(tires), 2)
        self.assertEqual(tires[0]["scale"], [-1, 1, 1])
        self.assertEqual(assets.calls.count("/horn#horn"), 1)
        self.assertEqual(next(p for p in scene["parts"] if p["id"] == "steering")["position"], [-.5, 2, -1])
        self.assertEqual(next(p for p in scene["points"] if p["name"] == "swheel")["category"], "steering_w")
        self.assertFalse(scene["issues"])

    def test_instance_look_and_variant_are_passed_to_model_import(self):
        assets = FakeAssets()
        assets.entries.append({"path": "/cab", "unitId": "cab", "category": "cabin", "model": "cab"})
        truck = {"id": "truck", "accessories": [
            {"id": "cab", "dataPath": "/cab", "category": "cabin", "type": "vehicle_accessory",
             "fields": {"look": '"painted"', "variant": '"uk"'}, "slots": []},
        ]}
        build_scene(truck, assets)
        self.assertIn(("/cab", '"painted"', '"uk"'), assets.options)

    def test_scene_cancels_before_reading_catalog(self):
        assets = FakeAssets()
        with self.assertRaises(CancelledError):
            build_scene({"accessories": []}, assets, cancelled=lambda: True)
        self.assertEqual(assets.calls, [])

    def test_unresolvable_saved_hookups_are_skipped_without_changing_saved_entries(self):
        assets = FakeAssets()
        truck = {"id": "truck", "accessories": [
            {"id": "cab", "dataPath": "/cab", "category": "cabin", "type": "vehicle_accessory", "fields": {}, "slots": []},
            {"id": "window", "dataPath": "/chassis", "category": "f_wnd_frame", "type": "vehicle_addon_accessory",
             "fields": {}, "slots": [{"name": "slot_23", "hookup": "horn.addon_hookup"}]},
            {"id": "gps", "dataPath": "/bar", "category": "r_grill", "type": "vehicle_addon_accessory",
             "fields": {}, "slots": [{"name": "slot_0", "hookup": "gps.scania"},
                                     {"name": "slot_0", "hookup": "horn.addon_hookup"}]},
        ]}
        saved_truck = deepcopy(truck)
        scene = build_scene(truck, assets)
        self.assertFalse(scene["issues"])
        hooks = [part for part in scene["parts"] if part["category"] == "hookup"]
        self.assertEqual(len(hooks), 1)
        self.assertEqual(hooks[0]["position"], [1, 3.2, -2])
        self.assertEqual(truck, saved_truck)


if __name__ == "__main__":
    unittest.main()
