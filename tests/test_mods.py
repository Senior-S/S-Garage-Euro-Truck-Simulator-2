from pathlib import Path
import sys
import tempfile
import json
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from mods import resolve_mods, _truckersmp_sources


class ModResolutionTests(unittest.TestCase):
    def setUp(self):
        discovered = patch("mods._truckersmp_sources", return_value=([], []))
        discovered.start()
        self.addCleanup(discovered.stop)

    def test_truckersmp_assets_load_before_saved_mod_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save = root / "profiles/profile/save/autosave/game.sii"
            save.parent.mkdir(parents=True)
            (save.parent / "info.sii").write_text('SiiNunit\n{\ndependencies[0]: "mod|custom|1"\n}')
            custom = root / "mod/custom.scs"
            custom.parent.mkdir()
            custom.touch()
            shared, ets2 = root / "shared.mp", root / "ets2.mp"
            with patch("mods._find_steam_roots", return_value=[]), patch("mods._truckersmp_sources", return_value=([shared, ets2], [])):
                sources, issues = resolve_mods(save, root / "profiles", None, None)
            self.assertEqual(sources, [shared, ets2, custom])
            self.assertEqual(issues, [])

    def test_unused_paint_archives_and_extracted_packages_are_available(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mods = root / "mod"
            mods.mkdir()
            definition = "def/vehicle/truck/test/paint_job/custom.sii"
            for package in ("paint.scs", "paint.zip"):
                with zipfile.ZipFile(mods / package, "w") as archive:
                    archive.writestr(definition, "paint")
            for package in (mods, mods / "extracted"):
                path = package / definition
                path.parent.mkdir(parents=True)
                path.write_text("paint")
            with patch("mods._find_steam_roots", return_value=[]):
                sources, issues = resolve_mods(root / "missing/game.sii", root / "profiles", None, None)
            self.assertEqual(set(sources), {mods, mods / "extracted", mods / "paint.scs", mods / "paint.zip"})
            self.assertEqual(issues, [])

    def test_other_mods_are_only_mounted_when_saved_and_priority_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mods = root / "mod"
            mods.mkdir()
            for name, definitions in (
                ("paint.scs", ["def/vehicle/truck/test/paint_job/a.sii"]),
                ("map.scs", ["def/country/test.sii"]),
                ("mixed.scs", ["def/vehicle/truck/test/paint_job/a.sii", "def/vehicle/truck/test/chassis/a.sii"]),
            ):
                with zipfile.ZipFile(mods / name, "w") as archive:
                    for definition in definitions:
                        archive.writestr(definition, "fixture")
            save = root / "profiles/profile/save/autosave/game.sii"
            save.parent.mkdir(parents=True)
            info = save.parent / "info.sii"
            info.write_text('SiiNunit\n{\ndependencies[0]: "mod|paint|1"\ndependencies[1]: "mod|map|1"\n}')
            with patch("mods._find_steam_roots", return_value=[]):
                sources, issues = resolve_mods(save, root / "profiles", None, None)
            self.assertEqual(sources, [mods / "map.scs", mods / "paint.scs"])
            self.assertEqual(issues, [])

    def test_missing_saved_mod_is_reported_alongside_available_paints(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paint = root / "mod/paint/def/vehicle/trailer_owned/test/paint_job/a.sii"
            paint.parent.mkdir(parents=True)
            paint.write_text("paint")
            save = root / "profiles/profile/save/autosave/game.sii"
            save.parent.mkdir(parents=True)
            (save.parent / "info.sii").write_text('SiiNunit\n{\ndependencies[0]: "mod|missing|1"\n}')
            with patch("mods._find_steam_roots", return_value=[]):
                sources, issues = resolve_mods(save, root / "profiles", None, None)
            self.assertEqual(sources, [root / "mod/paint"])
            self.assertEqual(len(issues), 1)
            self.assertIn("missing", issues[0])


class TruckersMPDiscoveryTests(unittest.TestCase):
    def test_custom_launcher_path_wins_and_shared_assets_precede_ets2(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            roaming = root / "roaming"
            options = roaming / "TruckersMP/launcher-options.json"
            options.parent.mkdir(parents=True)
            install = root / "custom"
            options.write_text(json.dumps({"installPath": str(install)}))
            for name in ("shared/mods/shared.mp", "ets2/mods/scout.mp", "ats/mods/ats.mp", "ets2/mods/client.dll"):
                file = install / "data" / name
                file.parent.mkdir(parents=True, exist_ok=True)
                file.touch()
            legacy = root / "program/TruckersMP/data/ets2/mods/old.mp"
            legacy.parent.mkdir(parents=True)
            legacy.touch()
            with patch.dict("os.environ", {"APPDATA": str(roaming), "LOCALAPPDATA": str(root / "local"), "PROGRAMDATA": str(root / "program")}):
                sources, issues = _truckersmp_sources()
            self.assertEqual(sources, [install / "data/shared/mods/shared.mp", install / "data/ets2/mods/scout.mp"])
            self.assertEqual(issues, [])

    def test_invalid_launcher_settings_still_find_standard_installation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            options = root / "roaming/TruckersMP/launcher-options.json"
            options.parent.mkdir(parents=True)
            options.write_text("invalid json")
            archive = options.parent / "installation/data/ets2/mods/scout.mp"
            archive.parent.mkdir(parents=True)
            archive.touch()
            with patch.dict("os.environ", {"APPDATA": str(root / "roaming"), "LOCALAPPDATA": str(root / "local"), "PROGRAMDATA": str(root / "program")}):
                sources, issues = _truckersmp_sources()
            self.assertEqual(sources, [archive])
            self.assertEqual(len(issues), 1)
