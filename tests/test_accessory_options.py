from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from assets import accessory_options
from saves import SaveSession, fields, refs, unquote
from test_saves import SOURCE


class AccessoryOptionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "game.sii"
        self.path.write_text(SOURCE)
        self.session = SaveSession(self.path, SOURCE, "test", "Test")
        self.plate = {"path": "/def/vehicle/truck/test/accessory/drv_plate/plate.sii",
                      "category": "drv_plate", "unitType": "accessory_addon_data",
                      "model": "/vehicle/truck/upgrade/driver_plate/0.pmd"}
        self.catalog = {self.plate["path"]: self.plate}

    def test_add_text_duplicate_history_and_save_round_trip(self):
        result = self.session.edit({"op": "add", "dataPath": self.plate["path"]}, self.catalog)
        unit = result["editedAccessoryId"]
        self.assertTrue(self.session.block(unit).startswith("vehicle_drv_plate_accessory :"))
        self.assertEqual(fields(self.session.block(unit))["text"], '""')
        text = 'Max "Škoda" \\ {Garage}'
        self.session.edit({"op": "options", "accessoryId": unit, "options": {"text": text}}, self.catalog)
        self.assertEqual(unquote(fields(self.session.block(unit))["text"]), text)
        duplicate = self.session.edit({"op": "duplicate", "accessoryId": unit}, self.catalog)["editedAccessoryId"]
        self.assertEqual(unquote(fields(self.session.block(duplicate))["text"]), text)
        self.session.history()
        self.session.history()
        self.assertEqual(unquote(fields(self.session.block(unit))["text"]), "")
        self.session.history(True)
        saved = self.session.save()
        reloaded = SaveSession(self.path, self.path.read_text(encoding="utf-8"), "test", "Test")
        self.assertEqual(unquote(fields(reloaded.block(unit))["text"]), text)
        self.assertEqual((Path(saved["backupPath"]) / "game.sii").read_text(), SOURCE)

    def test_existing_generic_plate_is_upgraded_without_mutating_shared_unit(self):
        old = '/def/vehicle/truck/scania.s_2016/accessory/r_grill/bar.sii'
        source = SOURCE.replace(old, self.plate['path'])
        session = SaveSession(self.path, source, 'test', 'Test')
        result = session.edit({"op": "options", "accessoryId": "_nameless.6", "options": {"text": "DRIVER"}}, self.catalog)
        unit = result['editedAccessoryId']
        self.assertNotEqual(unit, '_nameless.6')
        self.assertTrue(session.block(unit).startswith('vehicle_drv_plate_accessory :'))
        self.assertNotIn('text:', session.block('_nameless.6'))
        self.assertEqual(refs(session.block(unit), 'slot_hookup'), ['lamp.white.addon_hookup'])
        session.history()
        self.assertEqual(session.render(), source)

    def test_replacement_upgrades_same_category_donor(self):
        source = SOURCE.replace('/accessory/r_grill/bar.sii', '/accessory/drv_plate/art.sii')
        session = SaveSession(self.path, source, 'test', 'Test')
        result = session.edit({"op": "replace", "accessoryId": "_nameless.6", "dataPath": self.plate['path']}, self.catalog)
        self.assertTrue(session.block(result['editedAccessoryId']).startswith('vehicle_drv_plate_accessory :'))
        self.assertEqual(fields(session.block(result['editedAccessoryId']))['text'], '""')

    def test_options_validation_is_atomic_and_rejects_unsupported_fields(self):
        unit = self.session.edit({"op": "add", "dataPath": self.plate['path']}, self.catalog)['editedAccessoryId']
        before = self.session.render()
        for options in ({'text': 'line\nbreak'}, {'text': 'x' * 1025}, {'text': 12},
                        {'text': 'valid', 'paint_color': [1, 0, 0]}, {'look': 'other'}, {}, None):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.session.edit({'op': 'options', 'accessoryId': unit, 'options': options}, self.catalog)
            self.assertEqual(self.session.render(), before)
        with self.assertRaises(ValueError):
            self.session.edit({'op': 'options', 'accessoryId': '_nameless.6', 'options': {'text': 'no'}}, self.catalog)

    def test_painted_addon_default_color_edit_and_validation(self):
        entry = {'path': '/def/vehicle/truck/test/accessory/bumper/paint.sii', 'unitType': 'accessory_addon_painted_data',
                 'fields': {'default_color': '(0.1, 0.2, 0.3)'}}
        catalog = {entry['path']: entry}
        unit = self.session.edit({'op': 'add', 'dataPath': entry['path']}, catalog)['editedAccessoryId']
        self.assertEqual(fields(self.session.block(unit))['paint_color'], '(0.1, 0.2, 0.3)')
        self.session.edit({'op': 'options', 'accessoryId': unit, 'options': {'paint_color': [0.5, 0, 1]}}, catalog)
        self.assertEqual(fields(self.session.block(unit))['paint_color'], '(0.5, 0, 1)')
        before = self.session.render()
        for color in ([1, 2, 3], [True, 0, 0], [float('nan'), 0, 0], [0, 0], 'red'):
            with self.subTest(color=color), self.assertRaises(ValueError):
                self.session.edit({'op': 'options', 'accessoryId': unit, 'options': {'paint_color': color}}, catalog)
            self.assertEqual(self.session.render(), before)

    def test_features_do_not_confuse_fixed_art_or_chrome_with_editable_parts(self):
        self.assertTrue(accessory_options(self.plate)['text'])
        for model in ('/vehicle/truck/upgrade/frntglass_mid/lightboard04.pmd', '/vehicle/truck/upgrade/driver_plate/logo.pmd'):
            self.assertFalse(accessory_options({**self.plate, 'model': model})['text'])
        self.assertFalse(accessory_options({'unitType': 'accessory_rim_data', 'fields': {'paintable': 'false'}})['paintColor'])
        self.assertTrue(accessory_options({'unitType': 'accessory_rim_data', 'fields': {'paintable': 'true'}})['paintColor'])
        self.assertIn('Live display', accessory_options({'fields': {'ui_path': '/gps.sii'}})['features'])


if __name__ == '__main__':
    unittest.main()
