import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from saves import SaveSession, category, fields, refs


SOURCE = '''SiiNunit
{
player : _nameless.1 {
 trucks: 2
 trucks[0]: _nameless.2
 trucks[1]: _nameless.3
 assigned_vehicles: _nameless.4
}
vehicle_assignment : _nameless.4 {
 vehicle: _nameless.2
}
vehicle : _nameless.2 {
 accessories: 2
 accessories[0]: _nameless.5
 accessories[1]: _nameless.6
 license_plate: "TEST|argentina"
 fuel_relative: 0.6
}
vehicle : _nameless.3 {
 accessories: 1
 accessories[0]: _nameless.6
 license_plate: "SHARED|argentina"
}
vehicle_accessory : _nameless.5 {
 data_path: "/def/vehicle/truck/scania.s_2016/cabin/highline.sii"
 refund: 38000
}
vehicle_addon_accessory : _nameless.6 {
 slot_name: 1
 slot_name[0]: "slot_0"
 slot_hookup: 1
 slot_hookup[0]: lamp.white.addon_hookup
 paint_color: (1, 1, 1)
 data_path: "/def/vehicle/truck/scania.s_2016/accessory/r_grill/bar.sii"
 refund: 500
}
economy : _nameless.7 {
 player: _nameless.1
 money_account: 40000
 strange_string: "Leave {this} alone"
}
}
'''
CATALOG = {path: {"path": path} for path in (
    "/def/vehicle/truck/volvo.fh_2024/cabin/high.sii",
    "/def/vehicle/truck/daf.2021/accessory/r_grill/bar.sii",
)}


class SaveTests(unittest.TestCase):
    def test_source_snapshot_is_reused_and_still_detects_external_changes(self):
        original = self.path.read_bytes()
        self.path.write_bytes(original + b"\n")
        with patch.object(Path, "read_bytes", side_effect=AssertionError("Reuse the bytes read for decryption")):
            session = SaveSession(self.path, SOURCE, "test", "Test", source_data=original)
        session.edit({"op": "duplicate", "accessoryId": "_nameless.6"}, CATALOG)
        with self.assertRaisesRegex(ValueError, "changed outside"):
            session.save()

    def test_multi_step_history_restores_snapshots_and_discards_redo_branch(self):
        for refund in ("100", "200", "300"):
            self.session.edit({"op": "fields", "accessoryId": "_nameless.5", "fields": {"refund": refund}}, CATALOG)
        self.assertEqual(self.session.state()["historyPosition"], 3)
        self.session.history(steps=2)
        self.assertEqual(fields(self.session.block("_nameless.5"))["refund"], "100")
        self.assertEqual(self.session.state()["historyPosition"], 1)
        self.session.history(True, steps=2)
        self.assertEqual(fields(self.session.block("_nameless.5"))["refund"], "300")
        with self.assertRaises(ValueError):
            self.session.history(steps=4)
        self.assertEqual(self.session.state()["historyPosition"], 3)
        self.session.history(steps=2)
        self.session.edit({"op": "fields", "accessoryId": "_nameless.5", "fields": {"refund": "500"}}, CATALOG)
        self.assertEqual(len(self.session.state()["history"]), 2)
        self.assertFalse(self.session.state()["canRedo"])

    def test_paint_defaults_colors_locks_and_shared_accessory_are_undoable(self):
        original = "/def/vehicle/truck/scania.s_2016/paint_job/color0.sii"
        target = "/def/vehicle/truck/scania.s_2016/paint_job/custom.sii"
        text = SOURCE.replace("vehicle_addon_accessory", "vehicle_paint_job_accessory").replace("/def/vehicle/truck/scania.s_2016/accessory/r_grill/bar.sii", original)
        self.path.write_text(text)
        session = SaveSession(self.path, text, "test", "Test")
        catalog = {target: {"path": target, "category": "paint_job", "name": "Custom", "fields": {"base_color": "(0.2, 0.3, 0.4)", "base_color_locked": "false", "mask_r_color": "(1, 0, 0)", "mask_r_locked": "true"}}}
        result = session.edit({"op": "paint", "accessoryId": "_nameless.6", "dataPath": target, "colors": {"base_color": [0.1, 0.2, 0.3]}}, catalog)
        private_id = result["editedAccessoryId"]
        self.assertNotEqual(private_id, "_nameless.6")
        self.assertEqual(fields(session.block(private_id))["base_color"], "(0.1, 0.2, 0.3)")
        self.assertEqual(fields(session.block(private_id))["mask_r_color"], "(1, 0, 0)")
        self.assertIn(original, session.block("_nameless.6"))
        before = session.render()
        for colors in ({"mask_r_color": [0, 0, 0]}, {"base_color": [2, 0, 0]}, {"base_color": [float('nan'), 0, 0]}):
            with self.assertRaises(ValueError):
                session.edit({"op": "paint", "accessoryId": private_id, "colors": colors}, catalog)
            self.assertEqual(session.render(), before)
        session.history()
        self.assertEqual(session.render(), text)
        session.history(True)
        self.assertEqual(session.render(), before)
        self.assertEqual(SaveSession(self.path, before, "test", "Test").state()["truck"]["accessories"][1]["fields"]["base_color"], "(0.1, 0.2, 0.3)")

    def test_switch_paint_carries_entire_custom_palette_and_reset_is_undoable(self):
        original = "/def/vehicle/truck/scania.s_2016/paint_job/color0.sii"
        target = "/def/vehicle/truck/scania.s_2016/paint_job/custom.sii"
        text = SOURCE.replace("vehicle_addon_accessory", "vehicle_paint_job_accessory").replace("/def/vehicle/truck/scania.s_2016/accessory/r_grill/bar.sii", original)
        text = text.replace(' paint_color: (1, 1, 1)', ' base_color: (&3e4ccccd, &3e99999a, &3ecccccd)\n mask_r_color: (1, 0, 0)\n mask_g_color: (0, 1, 0)')
        old = {"base_color": "(0.2, 0.3, 0.4)", "mask_r_color": "(1,0,0)", "mask_g_color": "(0,1,0)"}
        new = {"base_color": "(.8,.7,.6)", "mask_r_color": "(0,0,1)", "mask_g_color": "(.5,.5,.5)", "mask_g_locked": "true"}
        catalog = {path: {"path": path, "category": "paint_job", "fields": settings} for path, settings in ((original, old), (target, new))}
        session = SaveSession(self.path, text, "test", "Test")
        result = session.edit({"op": "paint", "accessoryId": "_nameless.6", "dataPath": target}, catalog)
        self.assertEqual(fields(session.block(result["editedAccessoryId"]))["base_color"], new["base_color"])
        session.history()
        result = session.edit({"op": "paint", "accessoryId": "_nameless.6", "colors": {"mask_r_color": [.1,.2,.3]}}, catalog)
        unit = result["editedAccessoryId"]
        result = session.edit({"op": "paint", "accessoryId": unit, "dataPath": target}, catalog)
        palette = fields(session.block(unit))
        self.assertEqual(palette["base_color"], "(&3e4ccccd, &3e99999a, &3ecccccd)")
        self.assertEqual(palette["mask_r_color"], "(0.1, 0.2, 0.3)")
        self.assertEqual(palette["mask_g_color"], new["mask_g_color"])
        session.edit({"op": "paint", "accessoryId": unit, "resetColors": True}, catalog)
        self.assertEqual(fields(session.block(unit))["base_color"], new["base_color"])
        self.assertEqual(fields(session.block(unit))["mask_r_color"], new["mask_r_color"])
        self.assertIn("Reset colors", session.state()["history"][-1]["label"])
        session.history()
        self.assertEqual(fields(session.block(unit)), palette)

    @patch("saves.game_running", return_value=False)
    def test_save_rejects_disconnected_accessory_before_backup_or_write(self, _):
        self.session.overrides["_nameless.orphan"] = 'vehicle_addon_accessory : _nameless.orphan {\n data_path: "/def/vehicle/truck/test/accessory/r_grill/bar.sii"\n}\n'
        with self.assertRaisesRegex(ValueError, "disconnected unit trees"):
            self.session.save()
        self.assertEqual(self.path.read_bytes(), SOURCE.encode())
        self.assertFalse((self.path.parent / "garage-backups").exists())

    def test_real_definition_categories(self):
        self.assertEqual(category("/def/vehicle/f_tire/f385_55.sii"), "f_tire")
        self.assertEqual(category("/def/vehicle/r_disc/stock.sii"), "r_disc")
        self.assertEqual(category("/def/vehicle/truck/scania.s_2016/data.sii"), "truck")
        self.assertEqual(category("/def/vehicle/truck/scania.s_2016/accessory/r_grill/bar.sii"), "r_grill")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "game.sii"
        self.path.write_bytes(SOURCE.encode())
        self.session = SaveSession(self.path, SOURCE, "profiles/test/quicksave", "Test")

    def test_no_edit_is_byte_identical_and_selects_assigned_truck(self):
        self.assertEqual(self.session.render().encode(), self.path.read_bytes())
        self.assertEqual(self.session.state()["truck"]["id"], "_nameless.2")

    def test_duplicate_has_independent_id_and_undo_redo_preserve_originals(self):
        result = self.session.edit({"op": "duplicate", "accessoryId": "_nameless.6"}, CATALOG)
        ids = refs(self.session.block("_nameless.2"), "accessories")
        new_id = ids[2]
        self.assertNotEqual(new_id, "_nameless.6")
        self.assertEqual(fields(self.session.block(new_id)), fields(self.session.block("_nameless.6")))
        self.assertEqual(self.session.block("_nameless.3"), self.session.units["_nameless.3"][1])
        self.session.history()
        self.assertEqual(self.session.render(), SOURCE)
        self.assertFalse(self.session.state()["dirty"])
        self.session.history(True)
        self.assertEqual(len(refs(self.session.block("_nameless.2"), "accessories")), 3)
        reparsed = SaveSession(self.path, self.session.render(), "test", "Test")
        self.assertEqual(len(reparsed.state()["truck"]["accessories"]), 3)

    def test_cross_brand_replace_preserves_instance_fields_and_unrelated_bytes(self):
        path = "/def/vehicle/truck/volvo.fh_2024/cabin/high.sii"
        self.session.edit({"op": "replace", "accessoryId": "_nameless.5", "dataPath": path}, CATALOG)
        self.assertEqual(fields(self.session.block("_nameless.5"))["refund"], "38000")
        self.assertIn(self.session.units["_nameless.7"][1], self.session.render())
        with self.assertRaisesRegex(ValueError, "same part category"):
            self.session.edit({"op": "replace", "accessoryId": "_nameless.5", "dataPath": next(p for p in CATALOG if "r_grill" in p)}, CATALOG)

    def test_hookup_duplicate_and_remove_keep_arrays_paired(self):
        request = {"op": "hookup", "accessoryId": "_nameless.6", "slotName": "slot_0", "hookup": "horn.addon_hookup", "duplicate": True}
        self.session.edit(request, CATALOG)
        private_id = refs(self.session.block("_nameless.2"), "accessories")[1]
        self.assertEqual(refs(self.session.block(private_id), "slot_name"), ['"slot_0"', '"slot_0"'])
        self.session.edit({**request, "accessoryId": private_id, "hookup": "", "index": 1}, CATALOG)
        self.assertEqual(refs(self.session.block(private_id), "slot_hookup"), ["lamp.white.addon_hookup"])
        self.session.history()
        self.assertEqual(refs(self.session.block(private_id), "slot_hookup"), ["lamp.white.addon_hookup", "horn.addon_hookup"])
        self.assertEqual(refs(self.session.block(private_id), "slot_name"), ['"slot_0"', '"slot_0"'])

    def test_failed_edit_is_atomic_and_does_not_hide_errors(self):
        for value in ("1\n refund: 200", "(1)\n}", "(garbage)"):
            with self.assertRaises(ValueError):
                self.session.edit({"op": "fields", "accessoryId": "_nameless.6", "fields": {"paint_color": value}}, CATALOG)
            self.assertEqual(self.session.render(), SOURCE)
        with self.assertRaisesRegex(ValueError, "at least one cabin"):
            self.session.edit({"op": "remove", "accessoryId": "_nameless.5"}, CATALOG)

    def test_remove_shared_instance_keeps_other_truck_and_definition_unit(self):
        self.session.edit({"op": "remove", "accessoryId": "_nameless.6"}, CATALOG)
        self.assertEqual(refs(self.session.block("_nameless.3"), "accessories"), ["_nameless.6"])
        self.assertIn(self.session.units["_nameless.6"][1], self.session.render())

    def test_removing_last_owner_deletes_original_unit_and_undo_restores_it(self):
        self.session.edit({"op": "remove", "accessoryId": "_nameless.6"}, CATALOG)
        self.session.edit({"op": "remove", "truckId": "_nameless.3", "accessoryId": "_nameless.6"}, CATALOG)
        self.assertNotIn("vehicle_addon_accessory : _nameless.6", self.session.render())
        self.session.history()
        self.assertIn(self.session.units["_nameless.6"][1], self.session.render())
        self.session.history(True)
        self.assertNotIn("vehicle_addon_accessory : _nameless.6", self.session.render())

    def test_edit_shared_instance_copies_it_without_changing_other_truck(self):
        self.session.edit({"op": "fields", "accessoryId": "_nameless.6", "fields": {"paint_color": "(0.5, 0.1, 0.2)"}}, CATALOG)
        new_id = refs(self.session.block("_nameless.2"), "accessories")[1]
        self.assertNotEqual(new_id, "_nameless.6")
        self.assertEqual(fields(self.session.block(new_id))["paint_color"], "(0.5, 0.1, 0.2)")
        self.assertEqual(fields(self.session.block("_nameless.6"))["paint_color"], "(1, 1, 1)")
        self.assertEqual(refs(self.session.block("_nameless.3"), "accessories"), ["_nameless.6"])
        self.session.history()
        self.assertEqual(self.session.render(), SOURCE)

    @patch("saves.game_running", return_value=False)
    def test_save_backup_and_external_write_conflict(self, _):
        self.session.edit({"op": "duplicate", "accessoryId": "_nameless.6"}, CATALOG)
        self.path.with_name("info.sii").write_bytes(b"metadata")
        result = self.session.save()
        backup = Path(result["backupPath"])
        self.assertEqual((backup / "game.sii").read_bytes(), SOURCE.encode())
        self.assertEqual((backup / "info.sii").read_bytes(), b"metadata")
        self.assertFalse(result["state"]["dirty"])
        self.session.history()
        self.assertTrue(self.session.state()["dirty"])
        self.path.write_bytes(b"external edit")
        with self.assertRaisesRegex(ValueError, "changed outside"):
            self.session.save()
        self.assertEqual(self.path.read_bytes(), b"external edit")

    @patch("saves.game_running", return_value=True)
    def test_running_game_allows_write_with_backup(self, _):
        self.session.edit({"op": "duplicate", "accessoryId": "_nameless.6"}, CATALOG)
        result = self.session.save()
        self.assertFalse(result["state"]["dirty"])
        self.assertNotEqual(self.path.read_bytes(), SOURCE.encode())
        self.assertEqual((Path(result["backupPath"]) / "game.sii").read_bytes(), SOURCE.encode())

    def test_duplicate_then_remove_does_not_serialize_orphans(self):
        self.session.edit({"op": "duplicate", "accessoryId": "_nameless.6"}, CATALOG)
        new_id = refs(self.session.block("_nameless.2"), "accessories")[2]
        self.session.edit({"op": "remove", "accessoryId": new_id}, CATALOG)
        self.assertNotIn(new_id, self.session.render())


if __name__ == "__main__":
    unittest.main()
