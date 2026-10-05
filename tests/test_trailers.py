from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from test_saves import SOURCE, CATALOG
from saves import SaveSession, category, fields, refs
from assets import AssetStore
from scene import build_scene, IDENTITY


TRAILER_SOURCE = SOURCE.replace(' trucks: 2', ' trailers: 1\n trailers[0]: _nameless.10\n trucks: 2').replace(
    '\n}\n}\n', '''
}
trailer : _nameless.10 {
 slave_trailer: _nameless.11
 accessories: 4
 accessories[0]: _nameless.12
 accessories[1]: _nameless.13
 accessories[2]: _nameless.14
 accessories[3]: _nameless.6
 license_plate: "TRAILER|argentina"
}
trailer : _nameless.11 {
 slave_trailer: null
 accessories: 2
 accessories[0]: _nameless.12
 accessories[1]: _nameless.13
}
vehicle_accessory : _nameless.12 {
 data_path: "/def/vehicle/trailer_owned/scs.box/chassis/ch_3.sii"
 refund: 0
}
vehicle_accessory : _nameless.13 {
 data_path: "/def/vehicle/trailer_owned/scs.box/body/curtain.sii"
 refund: 0
}
vehicle_wheel_accessory : _nameless.14 {
 data_path: "/def/vehicle/trailer_wheel/r_tire/tire.sii"
 offset: 0
 refund: 0
}
}
''')


class TrailerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / 'game.sii'
        self.path.write_text(TRAILER_SOURCE, encoding='utf-8')
        self.session = SaveSession(self.path, TRAILER_SOURCE, 'test', 'Test')

    def test_initial_truck_and_owned_chain_sections(self):
        state = self.session.state()
        self.assertEqual(state['truck']['id'], '_nameless.2')
        self.assertEqual(len(state['trucks']), 2)
        self.assertEqual([v['id'] for v in state['trailers']], ['_nameless.10'])
        self.assertEqual(state['trailers'][0]['sectionCount'], 2)
        self.assertEqual(state['trailers'][0]['accessoryCount'], 6)
        self.session.truck_id = '_nameless.10'
        active = self.session.state()['truck']
        self.assertEqual(active['kind'], 'trailer')
        self.assertEqual(active['brand'], 'scs.box')
        self.assertEqual([a['category'] for a in active['accessories']], ['chassis', 'body', 'r_tire', 'r_grill', 'chassis', 'body'])
        self.assertEqual([part['vehicleId'] for part in active['accessories']], ['_nameless.10'] * 4 + ['_nameless.11'] * 2)
        self.assertEqual([part['section'] for part in active['accessories']], [1] * 4 + [2] * 2)
        self.assertEqual([section['id'] for section in active['sections']], ['_nameless.10', '_nameless.11'])
        self.assertEqual(category('/def/vehicle/trailer_owned/scs.box/data.sii'), 'trailer')
        self.assertEqual(category('/def/vehicle/trailer_owned/scs.box/accessory/r_bumper/paint.sii'), 'r_bumper')

    def test_trailer_edits_history_and_backup_preserve_trucks_and_chain(self):
        result = self.session.edit({'op': 'duplicate', 'truckId': '_nameless.10', 'accessoryId': '_nameless.14'}, CATALOG)
        self.assertEqual(len(result['truck']['accessories']), 7)
        self.assertEqual(fields(self.session.block(result['editedAccessoryId']))['offset'], '0')
        self.session.edit({'op': 'fields', 'accessoryId': '_nameless.13', 'fields': {'refund': '123'}}, CATALOG)
        self.assertEqual(fields(self.session.block('_nameless.13'))['refund'], '0')
        self.assertEqual(self.session.block('_nameless.2'), self.session.units['_nameless.2'][1])
        self.assertEqual(self.session.block('_nameless.11'), self.session.units['_nameless.11'][1])
        self.session.history(steps=2)
        self.assertEqual(self.session.render(), TRAILER_SOURCE)
        self.session.history(True, steps=2)
        result = self.session.save()
        self.assertEqual((Path(result['backupPath']) / 'game.sii').read_text(), TRAILER_SOURCE)
        reopened = SaveSession(self.path, self.path.read_text(), 'test', 'Test')
        self.assertEqual(len(refs(reopened.block('_nameless.10'), 'accessories')), 5)
        self.assertEqual(fields(reopened.block('_nameless.10'))['slave_trailer'], '_nameless.11')
        self.assertEqual(reopened.state()['truck']['id'], '_nameless.2')

    def test_trailer_shared_hookups_are_copied_and_core_body_cannot_be_removed(self):
        result = self.session.edit({'op': 'hookup', 'truckId': '_nameless.10', 'accessoryId': '_nameless.6', 'slotName': 'slot_0', 'hookup': 'horn.addon_hookup', 'duplicate': True}, CATALOG)
        self.assertNotEqual(result['editedAccessoryId'], '_nameless.6')
        self.assertEqual(refs(self.session.block('_nameless.6'), 'slot_hookup'), ['lamp.white.addon_hookup'])
        with self.assertRaisesRegex(ValueError, 'at least one body'):
            self.session.edit({'op': 'remove', 'accessoryId': '_nameless.13'}, CATALOG)

    def test_cross_trailer_body_replacement_and_add_remove_are_undoable(self):
        path = "/def/vehicle/trailer_owned/krone.profiliner/body/curtain.sii"
        catalog = {path: {"path": path, "category": "body"}}
        result = self.session.edit({"op": "replace", "truckId": "_nameless.10", "accessoryId": "_nameless.13", "dataPath": path}, catalog)
        self.assertEqual(fields(self.session.block(result["editedAccessoryId"]))["data_path"], '"' + path + '"')
        self.assertIn("scs.box/body/curtain.sii", self.session.block("_nameless.13"))
        added = self.session.edit({"op": "add", "dataPath": path}, catalog)["editedAccessoryId"]
        self.assertEqual(self.session.state()["truck"]["accessoryCount"], 7)
        self.session.edit({"op": "remove", "accessoryId": added}, catalog)
        self.session.history(steps=3)
        self.assertEqual(self.session.render(), TRAILER_SOURCE)

    def test_trailer_paint_color_and_design_change_undo_redo(self):
        original = "/def/vehicle/trailer_owned/scs.box/paint_job/color.sii"
        target = "/def/vehicle/trailer_owned/scs.box/paint_job/design.sii"
        text = TRAILER_SOURCE.replace("vehicle_wheel_accessory : _nameless.14", "vehicle_paint_job_accessory : _nameless.14").replace("/def/vehicle/trailer_wheel/r_tire/tire.sii", original)
        session = SaveSession(self.path, text, "test", "Test")
        catalog = {target: {"path": target, "category": "paint_job", "fields": {"base_color": "(1,1,1)", "base_color_locked": "false", "mask_r_color": "(1,0,0)", "mask_r_locked": "true"}}}
        session.edit({"op": "paint", "truckId": "_nameless.10", "accessoryId": "_nameless.14", "dataPath": target, "colors": {"base_color": [.2, .3, .4]}}, catalog)
        self.assertEqual(fields(session.block("_nameless.14"))["base_color"], "(0.2, 0.3, 0.4)")
        session.history()
        self.assertEqual(session.render(), text)
        session.history(True)
        self.assertEqual(session.state()["truck"]["kind"], "trailer")
        self.assertIn(target, session.render())

    def test_invalid_trailer_chain_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, 'Invalid owned trailer chain'):
            SaveSession(self.path, TRAILER_SOURCE.replace('slave_trailer: null', 'slave_trailer: _nameless.10'), 'test', 'Test')

    def test_listed_slave_before_root_still_groups_owned_trailer(self):
        text = TRAILER_SOURCE.replace(' trailers: 1\n trailers[0]: _nameless.10', ' trailers: 2\n trailers[0]: _nameless.11\n trailers[1]: _nameless.10')
        session = SaveSession(self.path, text, 'test', 'Test')
        session.truck_id = '_nameless.11'
        state = session.state()
        self.assertEqual([trailer['id'] for trailer in state['trailers']], ['_nameless.10'])
        self.assertEqual(state['truck']['id'], '_nameless.10')
        self.assertTrue(state['trailers'][0]['selected'])
        self.assertEqual([section['id'] for section in state['truck']['sections']], ['_nameless.10', '_nameless.11'])

    def test_slave_shared_accessory_edit_preserves_root_and_history_selection(self):
        result = self.session.edit({'op': 'fields', 'truckId': '_nameless.11', 'accessoryId': '_nameless.13', 'fields': {'refund': '123'}}, CATALOG)
        edited = result['editedAccessoryId']
        self.assertEqual(result['editedVehicleId'], '_nameless.11')
        self.assertNotEqual(edited, '_nameless.13')
        self.assertEqual(result['truck']['id'], '_nameless.10')
        self.assertEqual(self.session.truck_id, '_nameless.10')
        self.assertIn('_nameless.13', refs(self.session.block('_nameless.10'), 'accessories'))
        self.assertIn(edited, refs(self.session.block('_nameless.11'), 'accessories'))
        self.assertEqual(fields(self.session.block('_nameless.13'))['refund'], '0')
        self.assertEqual(fields(self.session.block(edited))['refund'], '123')
        self.assertEqual(result['history'][-1]['truckId'], '_nameless.11')
        self.assertEqual(self.session.history()['truck']['id'], '_nameless.10')
        self.assertEqual(self.session.render(), TRAILER_SOURCE)
        self.assertEqual(self.session.history(True)['truck']['id'], '_nameless.10')
        self.assertIn(edited, refs(self.session.block('_nameless.11'), 'accessories'))

    def test_default_edit_after_slave_selection_targets_root(self):
        self.session.truck_id = '_nameless.11'
        result = self.session.edit({'op': 'duplicate', 'accessoryId': '_nameless.14'}, CATALOG)
        self.assertEqual(result['editedVehicleId'], '_nameless.10')
        self.assertEqual(len(refs(self.session.block('_nameless.10'), 'accessories')), 5)
        self.assertEqual(len(refs(self.session.block('_nameless.11'), 'accessories')), 2)

    def test_add_and_remove_target_slave_section(self):
        path = '/def/vehicle/trailer_owned/scs.box/accessory/r_bumper/paint.sii'
        catalog = {path: {'path': path, 'category': 'r_bumper'}}
        result = self.session.edit({'op': 'add', 'truckId': '_nameless.11', 'dataPath': path}, catalog)
        added = result['editedAccessoryId']
        self.assertEqual(result['truck']['accessoryCount'], 7)
        self.assertIn(added, refs(self.session.block('_nameless.11'), 'accessories'))
        self.assertNotIn(added, refs(self.session.block('_nameless.10'), 'accessories'))
        self.assertEqual(next(part for part in result['truck']['accessories'] if part['id'] == added)['vehicleId'], '_nameless.11')
        self.session.edit({'op': 'remove', 'truckId': '_nameless.11', 'accessoryId': added}, catalog)
        self.assertEqual(self.session.render(), TRAILER_SOURCE)

    def test_multiple_owned_roots_preserve_player_order_and_long_chain(self):
        text = TRAILER_SOURCE.replace(' trailers: 1\n trailers[0]: _nameless.10', ' trailers: 2\n trailers[0]: _nameless.15\n trailers[1]: _nameless.10')
        text = text.replace('slave_trailer: null', 'slave_trailer: _nameless.16')
        text = text.replace('\n}\n}', '\n}\ntrailer : _nameless.15 {\n slave_trailer: null\n accessories: 0\n}\ntrailer : _nameless.16 {\n slave_trailer: null\n accessories: 0\n}\n}')
        session = SaveSession(self.path, text, 'test', 'Test')
        session.truck_id = '_nameless.16'
        state = session.state()
        self.assertEqual([trailer['id'] for trailer in state['trailers']], ['_nameless.15', '_nameless.10'])
        self.assertEqual([trailer['sectionCount'] for trailer in state['trailers']], [1, 3])
        self.assertEqual(state['truck']['id'], '_nameless.10')
        self.assertEqual([section['section'] for section in state['truck']['sections']], [1, 2, 3])

    def test_invalid_missing_and_converging_trailer_chains_fail_clearly(self):
        texts = [TRAILER_SOURCE.replace('slave_trailer: _nameless.11', 'slave_trailer: _nameless.missing'),
                 TRAILER_SOURCE.replace('trailers[0]: _nameless.10', 'trailers[0]: _nameless.missing'),
                 TRAILER_SOURCE.replace(' trailers: 1', ' trailers: 2\n trailers[1]: _nameless.15').replace('\n}\n}', '\n}\ntrailer : _nameless.15 {\n slave_trailer: _nameless.11\n accessories: 0\n}\n}')]
        for text in texts:
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, 'Invalid owned trailer chain'):
                SaveSession(self.path, text, 'test', 'Test')

    def test_trailer_scene_places_body_wheels_and_duplicate_hookups(self):
        self.session.truck_id = "_nameless.10"
        vehicle = self.session.state()["truck"]["sections"][0]
        entries = [{"path": a["dataPath"], "unitId": a["id"], "category": a["category"], "model": a["id"]} for a in vehicle["accessories"]]
        entries.append({"path": "/hookup", "unitId": "lamp.white.addon_hookup", "category": "hookup", "model": "lamp"})
        model = {"pieces": [{"material": {"paintable": True}}], "locators": []}
        chassis_model = {**model, "locators": [
            {"name": "body", **IDENTITY, "position": [0, 1.3, 0]},
            {"name": "r_grill", **IDENTITY, "position": [0, 2, 5]},
            {"name": "wheel_r_0", **IDENTITY, "position": [-.8, .5, 4]},
            {"name": "wheel_r_1", **IDENTITY, "position": [.8, .5, 4]},
        ]}
        addon_model = {**model, "locators": [{"name": "slot_0", **IDENTITY, "position": [0, .2, 0]}]}
        store = AssetStore(game_path=self.temporary.name, cache_path=Path(self.temporary.name))
        with patch.object(store, "prepare_models"), patch.object(store, "catalog", return_value=entries), patch.object(store, "model", side_effect=lambda path: chassis_model if "chassis/" in path else addon_model if "r_grill/" in path else model):
            scene = build_scene(vehicle, store)
            self.assertEqual(scene["issues"], [])
            body = next(p for p in scene["parts"] if p["category"] == "body")
            self.assertEqual(body["position"], [0, 1.3, 0])
            wheels = [p for p in scene["parts"] if p["category"] == "r_tire"]
            self.assertEqual(len(wheels), 2)
            self.assertEqual(wheels[0]["scale"], [-1, 1, 1])
            self.assertTrue(any(p["kind"] == "part" and p["category"] == "body" for p in scene["points"]))
            self.session.edit({"op": "hookup", "accessoryId": "_nameless.6", "slotName": "slot_0", "hookup": "lamp.white.addon_hookup", "duplicate": True}, CATALOG)
            scene = build_scene(self.session.state()["truck"]["sections"][0], store)
            self.assertEqual(len([p for p in scene["parts"] if p["category"] == "hookup"]), 2)

    def test_catalog_imports_owned_trailer_parts_and_wheels(self):
        root = Path(self.temporary.name)
        files = {
            'trailer_owned/scs.box/body/curtain.sii': 'accessory_trailer_body_data : curtain.scs.box.body {\n model: "/body.pmd"\n}',
            'trailer_owned/scs.box/chassis/ch_3.sii': 'accessory_chassis_data : ch3.scs.box.chassis {\n model: "/chassis.pmd"\n}',
            'trailer_owned/scs.box/accessory/r_bumper/paint.sii': 'accessory_addon_data : paint.scs.box.r_bumper {\n model: "/bumper.pmd"\n}',
            'trailer_wheel/r_tire/tire.sii': 'accessory_wheel_data : tire.r_tire {\n model: "/tire.pmd"\n}',
        }
        for relative, text in files.items():
            file = root / 'def/vehicle' / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(text)
        entries = AssetStore(cache_path=root)._read_catalog(root)
        categories = {entry['path']: entry['category'] for entry in entries}
        self.assertEqual(categories['/def/vehicle/trailer_owned/scs.box/body/curtain.sii'], 'body')
        self.assertEqual(categories['/def/vehicle/trailer_wheel/r_tire/tire.sii'], 'r_tire')
        self.assertEqual(categories['/def/vehicle/trailer_owned/scs.box/accessory/r_bumper/paint.sii'], 'r_bumper')
        self.assertTrue(all(e['brand'] == 'scs.box' for e in entries if '/trailer_owned/' in e['path']))


if __name__ == '__main__':
    unittest.main()
