from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.assets import AssetStore


class CacheMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="E:/ETS2-Garage")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = AssetStore(str(self.root), self.root / "cache")
        capabilities = patch.object(self.store, "_converter_capabilities", return_value={
            "definitionBundle": True, "viewerGeometry": True})
        capabilities.start()
        self.addCleanup(capabilities.stop)

    def test_legacy_catalog_blocks_loading_until_rebuild_and_preserves_other_files(self):
        legacy = self.store.cache_path / "catalog" / "old" / "def"
        legacy.mkdir(parents=True)
        (legacy / "part.sii").write_text("old")
        models = self.store.cache_path / "models" / "old"
        models.mkdir(parents=True)
        (models / "model.pim").write_text("old")
        preserved = self.store.cache_path / "unrelated.txt"
        preserved.write_text("keep")
        self.assertTrue(self.store.cache_migration_required())
        with self.assertRaisesRegex(ValueError, "Accept"):
            self.store.ensure_catalog()
        self.store._definitions["old"] = {}
        self.store._model_cache["old"] = {}
        self.store.rebuild_cache()
        self.assertFalse(legacy.exists())
        self.assertFalse(models.exists())
        self.assertEqual(preserved.read_text(), "keep")
        self.assertFalse(self.store._definitions)
        self.assertFalse(self.store._model_cache)
        self.assertFalse(self.store.cache_migration_required())

    def test_new_or_empty_cache_does_not_prompt(self):
        self.assertFalse(self.store.cache_migration_required())
        self.store._cache_migration_required = None
        native = self.store.cache_path / "catalog" / "new"
        native.mkdir(parents=True)
        (native / "definitions.sgbundle").write_bytes(b"bundle")
        self.assertFalse(self.store.cache_migration_required())

    def test_mixed_cache_with_legacy_models_requires_rebuild(self):
        model = self.store.cache_path / "models" / "old"
        model.mkdir(parents=True)
        (model / "model.pim").write_text("old")
        self.assertTrue(self.store.cache_migration_required())
        with patch.object(self.store, "_converter_capabilities", return_value={}):
            self.store._cache_migration_required = None
            self.assertFalse(self.store.cache_migration_required())

    def test_failed_deletion_can_be_retried(self):
        legacy = self.store.cache_path / "models"
        legacy.mkdir(parents=True)
        (legacy / "model.pim").write_text("old")
        with patch("backend.assets.shutil.rmtree", side_effect=PermissionError("in use")):
            with self.assertRaises(PermissionError):
                self.store.rebuild_cache()
        self.assertTrue(self.store.cache_migration_required())
        self.store.rebuild_cache()
        self.assertFalse(legacy.exists())

    def test_all_targets_are_validated_before_deletion(self):
        legacy = self.store.cache_path / "catalog" / "old"
        legacy.mkdir(parents=True)
        (legacy / "catalog.json").write_text("[]")
        (self.store.cache_path / "models").write_text("not a directory")
        with self.assertRaisesRegex(ValueError, "not a directory"):
            self.store.rebuild_cache()
        self.assertTrue(legacy.exists())
