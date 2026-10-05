from pathlib import Path
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from saves import read_sii


DECRYPTOR = Path(__file__).resolve().parents[1] / "tools" / "SII_Decrypt.exe"


@unittest.skipUnless(os.name == "nt" and DECRYPTOR.is_file(), "bundled Windows decryptor required")
class DecryptorIntegrationTests(unittest.TestCase):
    def test_binary_float_values_decode_without_changing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "game.sii"
            for bits, value in ((0x3F800000, "1"), (0x7F800000, "&7f800000"),
                                (0xFF800000, "&ff800000"), (0x7FC00001, "&7fc00001")):
                with self.subTest(bits=hex(bits)):
                    binary = (
                        b"BSII" + struct.pack("<IIBI", 3, 0, 1, 1)
                        + struct.pack("<I", 4) + b"test"
                        + struct.pack("<II", 5, 5) + b"value"
                        + struct.pack("<IIBQI", 0, 1, 255, 1, bits)
                        + struct.pack("<IB", 0, 0)
                    )
                    path.write_bytes(binary)
                    self.assertIn(f" value: {value}", read_sii(path, DECRYPTOR))
                    self.assertEqual(path.read_bytes(), binary)
