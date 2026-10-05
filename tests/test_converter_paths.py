"""Exercise the shipped executable, including its Windows process manifest."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from backend.converter_formats import DefinitionBundle


CONVERTER = Path(__file__).resolve().parents[1] / "tools" / "converter_pix.exe"


@unittest.skipUnless(os.name == "nt" and CONVERTER.is_file(), "Requires the bundled Windows converter")
class ConverterPathTests(unittest.TestCase):
    def test_definition_import_handles_unicode_executable_source_and_cache_paths(self):
        with tempfile.TemporaryDirectory(prefix="garage-converter-paths-") as temporary:
            for name in ("ascii", "K\u00e4se", "\u65e5\u672c\u8a9e"):
                with self.subTest(path=name):
                    root = Path(temporary) / name
                    root.mkdir()
                    executable = root / "converter_pix.exe"
                    shutil.copy2(CONVERTER, executable)
                    source = root / "base"
                    path = "/def/vehicle/truck/test/data.sii"
                    definition = source / path.lstrip("/")
                    definition.parent.mkdir(parents=True)
                    text = 'SiiNunit\n{\naccessory_truck_data : test.truck {\n name: "Test"\n}\n}\n'
                    definition.write_bytes(text.encode("utf-8"))
                    bundle = root / "cache" / "definitions.sgbundle"
                    result = subprocess.run([str(executable), "-b", str(source), "--extract-bundle",
                                             "/def/vehicle", "-e", str(bundle)], capture_output=True, timeout=30,
                                            creationflags=subprocess.CREATE_NO_WINDOW)
                    self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).decode("utf-8", errors="replace"))
                    self.assertEqual(DefinitionBundle(bundle).read_text(path), text)


if __name__ == "__main__":
    unittest.main()
