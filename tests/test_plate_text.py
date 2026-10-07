from concurrent.futures import CancelledError
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from assets import AssetStore
from plate_text import render_driver_plate


class PlateTextTests(unittest.TestCase):
    def setUp(self):
        self.files = {
            '/ui/driver_plate.sii': '''ui::window : window { coords_r: 32 coords_t: 32 }
ui::text_common : first { look_template: txt.driver.plate coords_l: 0 coords_r: 32 coords_t: 32 coords_b: 16 }
ui::text_common : second { look_template: txt.driver.plate coords_l: 0 coords_r: 32 coords_t: 16 coords_b: 0 }
ui::text : first_bg { text: "<img src=/plate.mat bottom=p4 xscale=stretch yscale=stretch>" coords_l: 0 coords_r: 32 coords_t: 32 coords_b: 16 }
ui::text : second_bg { text: "<img src=/plate.mat bottom=p4 xscale=stretch yscale=stretch>" coords_l: 0 coords_r: 32 coords_t: 16 coords_b: 0 }''',
            '/ui/template/text.ets.sii': 'ui::text_template : txt.driver.plate { text: "<font face=/font/test.font xscale=1 yscale=1>%0</font>" }',
            '/font/test.font': '''vert_span:4
default_scale:1
image:/font/test.mat,8,8,1,1,0
x0020,0,0,0,0,0,0,6,0
x0041,2,2,4,4,0,0,6,0
''',
            '/font/test.mat': 'effect : "ui.font.msdf.rfx" { aux[0] : {8,8,4,0} texture : "texture" { source : "/font/test.tobj" } }',
            '/plate.mat': 'effect : "ui.rfx" { texture : "texture" { source : "/plate.tobj" } }',
        }
        atlas = Image.new('RGB', (8, 8), (0, 255, 0))
        atlas.paste((255, 0, 255), (2, 2, 6, 6))
        background = Image.new('RGBA', (32, 8), 'red')
        background.paste('white', (0, 0, 32, 4))
        self.images = {'/font/test.tobj': atlas, '/plate.tobj': background}

    def test_msdf_glyphs_are_centered_in_both_game_regions(self):
        image = render_driver_plate('A', self.files.__getitem__, self.images.__getitem__)
        self.assertEqual(image.size, (32, 32))
        self.assertEqual(image.getpixel((14, 7)), (0, 0, 0, 255))
        self.assertEqual(image.getpixel((14, 23)), (0, 0, 0, 255))
        self.assertEqual(image.getpixel((2, 7)), (255, 255, 255, 255))
        self.assertEqual(image.crop((0, 0, 32, 16)).tobytes(), image.crop((0, 16, 32, 32)).tobytes())

    def test_empty_unsupported_and_lowercase_text(self):
        render = lambda text: render_driver_plate(text, self.files.__getitem__, self.images.__getitem__)
        self.assertEqual(render('a').tobytes(), render('A').tobytes())
        self.assertEqual(render('\u2603').tobytes(), render('').tobytes())
        self.assertEqual(render('').getextrema(), ((255, 255),) * 4)
        self.assertEqual(render('A' * 1024).size, (32, 32))

    def test_texture_cache_tracks_text_archive_revision_and_cancellation(self):
        with tempfile.TemporaryDirectory() as directory:
            assets = AssetStore(cache_path=Path(directory))
            bitmap = Image.new('RGBA', (8, 8), 'white')
            bitmap.putpixel((0, 0), (255, 0, 0, 255))
            with patch.object(assets, '_fingerprint', return_value='game-one'), patch('plate_text.render_driver_plate', return_value=bitmap) as render:
                first = assets.driver_plate_texture('A')
                self.assertEqual(assets.driver_plate_texture('A'), first)
                self.assertEqual(render.call_count, 1)
                self.assertNotEqual(assets.driver_plate_texture(''), first)
                self.assertTrue(assets.texture_files[first.removeprefix('/cache/')].is_file())
                with Image.open(assets.texture_files[first.removeprefix('/cache/')]) as image:
                    self.assertEqual(image.getpixel((0, 7)), (255, 0, 0, 255))
                with self.assertRaises(CancelledError):
                    assets.driver_plate_texture('A', lambda: True)
            with patch.object(assets, '_fingerprint', return_value='game-two'), patch('plate_text.render_driver_plate', return_value=Image.new('RGBA', (8, 8))):
                self.assertNotEqual(assets.driver_plate_texture('A'), first)


if __name__ == '__main__':
    unittest.main()
