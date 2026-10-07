from pathlib import Path
from copy import deepcopy
import sys
import math
import unittest
from concurrent.futures import CancelledError
from unittest.mock import patch

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
    def test_plate_text_is_per_instance_and_does_not_change_shared_model_keys(self):
        assets = FakeAssets()
        original = assets.model
        def model(path, **kwargs):
            result = original(path, **kwargs)
            result['pieces'][0]['material']['driverPlate'] = True
            return result
        assets.model = model
        assets.driver_plate_texture = lambda text, cancelled: '/text/' + text
        truck = {'id': 'truck', 'accessories': [
            {'id': 'first', 'dataPath': '/chassis', 'category': 'chassis', 'fields': {'text': '"Senior S"'}, 'slots': []},
            {'id': 'second', 'dataPath': '/chassis', 'category': 'chassis', 'fields': {'text': '"Other"'}, 'slots': []},
        ]}
        cache = {}
        result = build_scene(truck, assets, model_cache=cache)
        self.assertEqual([part['textTexture'] for part in result['parts']], ['/text/Senior S', '/text/Other'])
        keys = [part['model']['key'] for part in result['parts']]
        truck['accessories'][0]['fields']['text'] = '""'
        again = build_scene(truck, assets, model_cache=cache)
        self.assertEqual([part['model']['key'] for part in again['parts']], keys)
        self.assertEqual([part['textTexture'] for part in again['parts']], ['/text/', '/text/Other'])
        with patch.object(assets, 'driver_plate_texture', side_effect=OSError('font missing')):
            failed = build_scene(truck, assets, model_cache=cache)
        self.assertEqual(len(failed['parts']), 2)
        self.assertTrue(any('font missing' in issue for issue in failed['issues']))
        with patch.object(assets, 'driver_plate_texture', side_effect=CancelledError):
            with self.assertRaises(CancelledError):
                build_scene(truck, assets, model_cache=cache)

    def test_model_less_headlights_get_a_stable_rig_without_importing_geometry(self):
        assets = FakeAssets()
        assets.entries.append({"path": "/lights", "unitId": "lights", "category": "head_light", "model": None})
        assets.head_lights = lambda path, **kwargs: {"fields": {"reflectors_offset": "(0,.8,-3)"}, "masks": {"low_beam": "/mask"}}
        truck = {"id": "truck", "accessories": [
            {"id": category, "dataPath": path, "category": category, "type": "vehicle_accessory", "fields": {}, "slots": []}
            for path, category in (("/chassis", "chassis"), ("/lights", "head_light"))]}
        cache = {}
        result = build_scene(truck, assets, model_cache=cache)
        rig = next(part for part in result["parts"] if part["category"] == "head_light")
        self.assertEqual(rig["model"]["headLights"]["masks"]["low_beam"], "/mask")
        self.assertEqual(rig["model"]["headLights"]["auxiliary"], [])
        self.assertEqual(rig["model"]["pieces"], [])
        self.assertEqual(rig["vehicleId"], "truck")
        self.assertNotIn("/lights", assets.calls)
        # A second assembly uses the existing chassis model and preserves rig identity.
        again = build_scene(truck, assets, model_cache=cache)
        self.assertEqual(rig["modelKey"], next(part for part in again["parts"] if part["category"] == "head_light")["modelKey"])

    def test_steering_uses_interior_bone_chain_before_cab_mount(self):
        assets = FakeAssets()
        assets.entries.append({"path": "/interior", "unitId": "interior", "category": "interior", "model": "interior"})
        original = assets.model
        def model(path):
            result = original(path)
            if path == "/chassis":
                result["locators"].append({"name": "ext_interior", **IDENTITY, "position": [0, 3, 0]})
            if path == "/interior":
                result["steeringBones"] = [
                    {"name": "root", "parent": 255, "translation": [0, 0, 0], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1]},
                    {"name": "column", "parent": 0, "translation": [0, -.2, -.5], "rotation": [math.sin(.3), 0, 0, math.cos(.3)], "scale": [1, 1, 1]},
                    {"name": "steering_w", "parent": 1, "translation": [0, .1, 0], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1]},
                ]
            return result
        assets.model = model
        truck = {"id": "truck", "accessories": [
            {"id": category, "dataPath": path, "category": category, "type": "vehicle_accessory", "fields": {}, "slots": []}
            for path, category in (("/chassis", "chassis"), ("/steering", "steering_w"), ("/interior", "interior"))]}
        scene = build_scene(truck, assets)
        wheel = next(p for p in scene["parts"] if p["category"] == "steering_w")
        expected = compose({**IDENTITY, "position": [0, 2.8, -.5], "rotation": [math.sin(.3), 0, 0, math.cos(.3)]}, {**IDENTITY, "position": [0, .1, 0]})
        expected = compose(expected, {**IDENTITY, "rotation": [0, -math.sqrt(.5), 0, math.sqrt(.5)]})
        for actual, target in zip(wheel["position"], expected["position"]):
            self.assertAlmostEqual(actual, target)
        self.assertEqual(wheel["rotation"], expected["rotation"])
        markers = [p for p in scene["points"] if p.get("category") == "steering_w"]
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0]["position"], wheel["position"])
        self.assertFalse(scene["issues"])

    def test_linked_trailer_sections_keep_mounts_paint_and_models_independent(self):
        assets = FakeAssets()
        assets.entries = [{"path": path, "unitId": path, "category": category, "model": path}
                          for path, category in (("/lead", "chassis"), ("/rear", "chassis"), ("/body", "body"), ("/tire", "r_tire"))]
        assets.entries.append({"path": "/paint", "unitId": "paint", "category": "paint_job"})
        piece = {"positions": [-1, 0, -5, 1, 0, 5, 1, 2, 5], "indices": [0, 1, 2], "material": {"paintable": True}}
        mounts = [{"name": name, **IDENTITY, "position": position} for name, position in (
            ("body", [0, 1.3, 0]), ("wheel_r_0", [-.8, .5, 4]), ("wheel_r_1", [.8, .5, 4]))]
        models = {
            "/lead": {"pieces": [piece], "locators": mounts + [{"name": "s_hook", **IDENTITY, "position": [0, .45, 5.451593399]}]},
            "/rear": {"pieces": [piece], "locators": mounts + [{"name": "hook", **IDENTITY, "position": [0, .45, -5.516731739]}]},
            "/body": {"pieces": [piece], "locators": [{"name": "slot_0", **IDENTITY, "position": [0, 1, 2]}]},
            "/tire": {"pieces": [piece], "locators": []},
        }
        sections = []
        for number, chassis, color in ((1, "/lead", "(1,0,0)"), (2, "/rear", "(0,0,1)")):
            section_id = f"section{number}"
            accessories = [{"id": category, "type": "vehicle_wheel_accessory" if category == "r_tire" else "vehicle_accessory",
                            "dataPath": path, "category": category, "fields": {}, "slots": []}
                           for path, category in ((chassis, "chassis"), ("/body", "body"), ("/tire", "r_tire"))]
            accessories.append({"id": "paint", "type": "vehicle_paint_job_accessory", "dataPath": "/paint", "category": "paint_job", "fields": {"base_color": color}, "slots": []})
            sections.append({"id": section_id, "section": number, "accessories": accessories})
        trailer = {"id": "section1", "sections": sections, "accessories": [part for section in sections for part in section["accessories"]]}
        cache = {}
        with patch.object(assets, "model", side_effect=lambda path: deepcopy(models[path])) as load:
            scene = build_scene(trailer, assets, model_cache=cache)
            self.assertEqual(scene["issues"], [])
            bodies = [part for part in scene["parts"] if part["category"] == "body"]
            self.assertEqual([part["vehicleId"] for part in bodies], ["section1", "section2"])
            self.assertEqual([part["paint"]["color"] for part in bodies], [[1, 0, 0], [0, 0, 1]])
            self.assertEqual(bodies[0]["position"], [0, 1.3, 0])
            self.assertAlmostEqual(bodies[1]["position"][2], 10.968325138)
            self.assertEqual(len([part for part in scene["parts"] if part["category"] == "r_tire"]), 4)
            points = [point for point in scene["points"] if point.get("category") == "body"]
            self.assertEqual([point["vehicleId"] for point in points], ["section1", "section2"])
            self.assertEqual([point["section"] for point in points], [1, 2])
            hookup_points = [point for point in scene["points"] if point["kind"] == "hookup"]
            self.assertEqual([point["vehicleId"] for point in hookup_points], ["section1", "section2"])
            self.assertAlmostEqual(hookup_points[1]["position"][2] - hookup_points[0]["position"][2], 10.968325138)
            self.assertEqual(load.call_count, 4)
            build_scene(trailer, assets, model_cache=cache)
            self.assertEqual(load.call_count, 4)
            trailer["sections"] = [sections[0], {**sections[1], "accessories": []}]
            build_scene(trailer, assets, model_cache=cache)
            self.assertNotIn(("/rear", None, None), cache)

    def test_trailer_chain_without_couplers_uses_transformed_bounds_and_marks_empty_mounts(self):
        assets = FakeAssets()
        assets.entries = [{"path": "/chassis", "unitId": "chassis", "category": "chassis", "model": "frame"},
                          {"path": "/body", "unitId": "body", "category": "body"}]
        model = {"pieces": [{"positions": [-1, 0, -3, 1, 0, 7], "material": {}}],
                 "locators": [{"name": "body", **IDENTITY, "position": [0, 1, 0]}]}
        sections = [{"id": f"section{number}", "section": number,
                     "accessories": [{"id": "shared", "type": "vehicle_accessory", "dataPath": "/chassis", "category": "chassis", "fields": {}, "slots": []}]}
                    for number in range(1, 4)]
        with patch.object(assets, "model", return_value=model):
            scene = build_scene({"id": "section1", "sections": sections}, assets)
        self.assertEqual([part["position"][2] for part in scene["parts"]], [0, 10.5, 21])
        self.assertEqual([point["vehicleId"] for point in scene["points"]], ["section1", "section2", "section3"])
        self.assertTrue(all(point["accessoryId"] is None for point in scene["points"]))
        self.assertEqual(len(scene["issues"]), 2)
        self.assertTrue(all("preview spacing is approximate" in issue for issue in scene["issues"]))

    def test_plural_doorstep_mount_renders_and_selects_the_singular_category(self):
        assets = FakeAssets()
        assets.entries.append({"path": "/step", "unitId": "step", "category": "doorstep", "model": "step"})
        assets.model = lambda path: {"pieces": [], "locators": [{"name": "doorsteps", **IDENTITY, "position": [1, 2, 3]}] if path == "/chassis" else []}
        truck = {"id": "truck", "accessories": [{"id": path, "dataPath": path, "category": category, "type": "vehicle_accessory", "fields": {}, "slots": []} for path, category in (("/chassis", "chassis"), ("/step", "doorstep"))]}
        scene = build_scene(truck, assets)
        self.assertEqual(scene["issues"], [])
        self.assertEqual(next(part for part in scene["parts"] if part["category"] == "doorstep")["position"], [1, 2, 3])
        point = next(point for point in scene["points"] if point["name"] == "doorsteps")
        self.assertEqual(point["category"], "doorstep")
        self.assertEqual(point["accessoryId"], "/step")

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
        cache = {}
        scene = build_scene(truck, assets, model_cache=cache)
        materials = {part["category"]: part["paint"] for part in scene["parts"]}
        self.assertEqual(materials["cabin"]["paintTexture"], "/atlas")
        self.assertEqual(materials["sunshld"]["paintTexture"], "/white")
        self.assertEqual(materials["sunshld"]["color"], [1, 1, 1])
        self.assertEqual(materials["sunshld"]["accessoryColor"], [0, 0, 0])
        self.assertEqual(materials["cabin"]["paintColors"][2], [0, .5, 1])
        truck["accessories"][-1]["fields"]["base_color"] = "(0,1,0)"
        repainted = build_scene(truck, assets, model_cache=cache)
        self.assertIs(repainted["parts"][0]["model"], scene["parts"][0]["model"])
        self.assertEqual(repainted["parts"][0]["paint"]["color"], [0, 1, 0])
        # Explicitly paintable addons use their own color, without the truck atlas.
        assets.entries[-1]["unitType"] = "accessory_addon_painted_data"
        independent = build_scene(truck, assets, model_cache=cache)
        shield = next(part for part in independent["parts"] if part["category"] == "sunshld")
        self.assertEqual(shield["paint"]["color"], [0, 0, 0])
        self.assertNotIn("paintTexture", shield["paint"])

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
