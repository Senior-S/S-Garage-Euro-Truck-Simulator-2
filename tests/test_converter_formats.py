from copy import deepcopy
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from backend.converter_formats import DefinitionBundle, DEFINITION_BUNDLE_MAGIC, read_viewer_model


class ConverterFormatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write_model(self, change=None, binary_change=None):
        binary = bytearray()
        def stream(values, components, kind="f32"):
            while len(binary) % 4:
                binary.append(0)
            descriptor = {"offset": len(binary), "count": len(values), "components": components, "type": kind}
            binary.extend(struct.pack(f"<{len(values)}" + {"f32": "f", "u32": "I", "u8": "B"}[kind], *values))
            return descriptor
        metadata = {
            "format": "SGarageModel", "version": 1, "binary": "truck.sgb",
            "materials": [{"alias": "paint", "effect": "eut2.dif.spec"}],
            "parts": [{"name": "cab", "pieces": [0], "locators": [0]}],
            "pieces": [{"index": 0, "material": 0, "vertexCount": 3, "boneCount": 0,
                        "streams": {"_POSITION": stream([0, 0, 0, 1, 0, 0, 0, 1, 0], 3),
                                    "_NORMAL": stream([0, 0, 1] * 3, 3),
                                    "_UV0": stream([0, 0, 1, 0, 0, 1], 2),
                                    "_UV1": stream([.25, .5, .75, .5, .25, 1], 2)},
                        "indices": stream([0, 2, 1], 1, "u32"),
                        "uvAliases": {"_UV0": ["_TEXCOORD0"], "_UV1": ["_TEXCOORD1", "_TEXCOORD2"]}}],
            "locators": [{"index": 0, "name": "r_grill", "position": [1, 2, 3],
                          "rotation": [0, 0, .5, .5], "scale": [-1, 2, 1], "hookup": '"test.addon_hookup"'}],
            "bones": [],
        }
        metadata["binaryBytes"] = len(binary)
        if change:
            change(metadata)
        if binary_change:
            binary_change(binary, metadata)
        (self.root / "truck.sgb").write_bytes(binary)
        path = self.root / "truck.sgm"
        path.write_text(json.dumps(metadata), encoding="utf-8")
        return path, metadata

    def write_bundle(self, records):
        path = self.root / "definitions.sgdef"
        with path.open("wb") as handle:
            handle.write(DEFINITION_BUNDLE_MAGIC)
            for name, content in records:
                name = name.encode("utf-8") if isinstance(name, str) else name
                handle.write(struct.pack("<IQ", len(name), len(content)))
                handle.write(name)
                handle.write(content)
        return path

    def test_model_keeps_uv_aliases_winding_and_locator_transforms(self):
        path, metadata = self.write_model()
        decoded = read_viewer_model(path)
        piece = decoded["pieces"][0]
        self.assertEqual(piece["streams"]["_POSITION"], [0, 0, 0, 1, 0, 0, 0, 1, 0])
        self.assertEqual(piece["streams"]["_UV1"], [.25, .5, .75, .5, .25, 1])
        self.assertEqual(piece["uvAliases"], metadata["pieces"][0]["uvAliases"])
        self.assertEqual(piece["indices"], [0, 2, 1])
        self.assertEqual(decoded["locators"], metadata["locators"])

    def test_model_rejects_unsafe_binary_references(self):
        for name in ("../truck.sgb", "/truck.sgb", "sub/truck.sgb", "sub\\truck.sgb", "C:truck.sgb", "truck.sgb:payload", "truck.bin", "truck\0.sgb"):
            with self.subTest(name=name):
                path, _ = self.write_model(lambda data: data.update(binary=name))
                with self.assertRaises(ValueError):
                    read_viewer_model(path)

    def test_model_rejects_corrupt_descriptors_and_geometry(self):
        mutations = [
            lambda data: data.update(version=True),
            lambda data: data.update(binaryBytes=data["binaryBytes"] + 1),
            lambda data: data["pieces"][0]["streams"]["_POSITION"].update(offset=1),
            lambda data: data["pieces"][0]["streams"]["_POSITION"].update(offset=data["binaryBytes"]),
            lambda data: data["pieces"][0]["streams"]["_POSITION"].update(count=6),
            lambda data: data["pieces"][0]["streams"]["_NORMAL"].update(components=2),
            lambda data: data["pieces"][0]["streams"]["_UV1"].update(count=5),
            lambda data: data["pieces"][0]["streams"]["_UV1"].update(type="f64"),
            lambda data: data["pieces"][0]["indices"].update(count=2),
            lambda data: data["pieces"][0]["indices"].update(type="f32"),
            lambda data: data["pieces"][0].update(material=2 ** 31),
            lambda data: data["pieces"][0].update(index=1),
            lambda data: data["pieces"][0].update(vertexCount=True),
            lambda data: data["parts"][0].update(locators=[1]),
            lambda data: data["parts"][0].update(pieces=[True]),
            lambda data: data["pieces"][0]["uvAliases"].update(_UV3=["_TEXCOORD3"]),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                path, _ = self.write_model(mutation)
                with self.assertRaises(ValueError):
                    read_viewer_model(path)
        for value, tag in ((float("nan"), "_POSITION"), (float("inf"), "_NORMAL"), (float("-inf"), "_UV1")):
            with self.subTest(value=value, tag=tag):
                path, _ = self.write_model(binary_change=lambda binary, data: struct.pack_into("<f", binary, data["pieces"][0]["streams"][tag]["offset"], value))
                with self.assertRaises(ValueError):
                    read_viewer_model(path)
        path, _ = self.write_model(binary_change=lambda binary, data: struct.pack_into("<I", binary, data["pieces"][0]["indices"]["offset"], 3))
        with self.assertRaises(ValueError):
            read_viewer_model(path)

    def test_model_rejects_invalid_locator_transforms(self):
        for key, value in (("position", [1, 2]), ("position", [1, 2, float("nan")]),
                           ("rotation", [0, 0, 1]), ("rotation", [0, 0, 0, float("inf")]),
                           ("scale", [1, True, 1]), ("scale", [1, "2", 1]), ("position", [10 ** 1000, 0, 0])):
            with self.subTest(key=key, value=value):
                path, _ = self.write_model(lambda data: data["locators"][0].update({key: value}))
                with self.assertRaises(ValueError):
                    read_viewer_model(path)

    def test_model_preserves_material_ids_when_material_records_are_missing(self):
        for material in (-1, 0, 7):
            with self.subTest(material=material):
                path, _ = self.write_model(lambda data: (data.update(materials=[]), data["pieces"][0].update(material=material)))
                self.assertEqual(read_viewer_model(path)["pieces"][0]["material"], material)

    def test_model_decodes_extra_and_skin_streams_without_normalizing(self):
        path, data = self.write_model()
        binary = bytearray((self.root / "truck.sgb").read_bytes())
        piece = data["pieces"][0]
        piece["boneCount"] = 1
        for tag, values in (("_BONE_INDEX", [0, 0, 0]), ("_BONE_WEIGHT", [255, 127, 0])):
            piece["streams"][tag] = {"offset": len(binary), "count": 3, "components": 1, "type": "u8"}
            binary.extend(values)
        while len(binary) % 4:
            binary.append(0)
        piece["streams"]["_TANGENT"] = {"offset": len(binary), "count": 12, "components": 4, "type": "f32"}
        binary.extend(struct.pack("<12f", *([1, 0, 0, -1] * 3)))
        identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
        data["bones"] = [{"index": 0, "name": "root", "parent": 255, "matrix": identity, "inverseMatrix": identity,
                          "translation": [0, 0, 0], "rotation": [0, 0, 0, 1], "scale": [1, 1, 1],
                          "stretch": [0, 0, 0, 1], "determinantSign": 1}]
        data["binaryBytes"] = len(binary)
        (self.root / "truck.sgb").write_bytes(binary)
        path.write_text(json.dumps(data), encoding="utf-8")
        decoded = read_viewer_model(path)
        self.assertEqual(decoded["pieces"][0]["streams"]["_BONE_WEIGHT"], [255, 127, 0])
        self.assertEqual(decoded["pieces"][0]["streams"]["_TANGENT"], [1, 0, 0, -1] * 3)
        for change in (lambda value: value["bones"][0].update(parent=0),
                       lambda value: value["bones"][0]["matrix"].__setitem__(0, float("nan")),
                       lambda value: value["pieces"][0].update(boneCount=0)):
            invalid = deepcopy(data)
            change(invalid)
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaises(ValueError):
                read_viewer_model(path)

    def test_bundle_indexes_empty_and_large_records_without_extracting_files(self):
        content = b"a" * (2 * 1024 * 1024 + 3)
        path = self.write_bundle([("/def/empty.sii", b""), ("/def/large.sii", content), ("/def/utf8.sii", b"\xffvalue")])
        bundle = DefinitionBundle(path)
        self.assertEqual(bundle.paths, ("/def/empty.sii", "/def/large.sii", "/def/utf8.sii"))
        self.assertIn("/def/large.sii", bundle)
        self.assertNotIn("/def/missing.sii", bundle)
        self.assertEqual(bundle.read_text("/def/empty.sii"), "")
        self.assertEqual(bundle.read_text("/def/large.sii"), content.decode())
        self.assertEqual(bundle.read_text("/def/utf8.sii"), "\ufffdvalue")
        self.assertEqual(list(self.root.iterdir()), [path])
        self.assertTrue(all(isinstance(entry, tuple) and len(entry) == 2 for entry in bundle.entries.values()))
        with self.assertRaises(KeyError):
            bundle.read_text("/def/missing.sii")

    def test_bundle_empty_bundle_and_iteration_order(self):
        self.assertEqual(list(DefinitionBundle(self.write_bundle([])).iter_texts()), [])
        bundle = DefinitionBundle(self.write_bundle([("/b", b"second"), ("/a", b"first"), ("/c", b"third")]))
        with patch.object(Path, "open", wraps=Path.open, autospec=True) as opened:
            # A bound helper avoids relying on mock descriptor behavior on Windows.
            opened.side_effect = lambda path, *args, **kwargs: open(path, *args, **kwargs)
            self.assertEqual(list(bundle.iter_texts(["/a", "/b", "/c"])), [("/a", "first"), ("/b", "second"), ("/c", "third")])
            self.assertEqual(opened.call_count, 1)

    def test_bundle_rejects_duplicate_unsafe_and_invalid_utf8_paths(self):
        for name in ("relative", "/../escape", "/def/../escape", "/./a", "//a", "/a/", "/a\\b", "/a:b", "/a\0b", b"/\xff"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    DefinitionBundle(self.write_bundle([(name, b"value")]))
        with self.assertRaises(ValueError):
            DefinitionBundle(self.write_bundle([("/a", b"first"), ("/a", b"second")]))

    def test_lazy_bundle_reads_skip_unrequested_large_records(self):
        bundle = DefinitionBundle(self.write_bundle([
            ("/large", b"x" * (2 * 1024 * 1024)), ("/selected", b"selected"),
            ("/tiny-gap", b"small"), ("/last", b"last"),
        ]))
        counts = []
        class CountingFile:
            def __init__(self, handle):
                self.handle = handle
            def __getattr__(self, name):
                return getattr(self.handle, name)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.handle.close()
            def read(self, size=-1):
                result = self.handle.read(size)
                counts.append(len(result))
                return result
        with patch.object(Path, "open", autospec=True, side_effect=lambda file, *args, **kwargs: CountingFile(open(file, *args, **kwargs))):
            self.assertEqual(bundle.read_text("/last"), "last")
            self.assertEqual(sum(counts), 4)
            counts.clear()
            self.assertEqual(list(bundle.iter_texts(["/selected", "/last"])), [("/selected", "selected"), ("/last", "last")])
            self.assertLess(sum(counts), 100)

    def test_bundle_rejects_truncated_records_and_changed_sources(self):
        path = self.write_bundle([("/a", b"value")])
        valid = path.read_bytes()
        for truncated in (b"", b"SGDEFB0\0", valid[:9], valid[:20], valid[:-1], DEFINITION_BUNDLE_MAGIC + struct.pack("<IQ", 2 ** 20 + 1, 0)):
            with self.subTest(length=len(truncated)):
                path.write_bytes(truncated)
                with self.assertRaises(ValueError):
                    DefinitionBundle(path)
        path.write_bytes(valid)
        bundle = DefinitionBundle(path)
        path.write_bytes(valid + b"extra")
        with self.assertRaises(ValueError):
            bundle.read_text("/a")


if __name__ == "__main__":
    unittest.main()
