"""Render the driver's name-plate UI with locally installed SCS font assets."""
from __future__ import annotations

import re

from PIL import Image, ImageChops


def render_driver_plate(text, read_text, load_texture):
    """Compose the game's two plate regions; model UVs select the visible region.

    Callbacks keep archive extraction and caching in AssetStore. No game assets
    or substitute operating-system fonts are bundled with the application.
    """
    layout = read_text('/ui/driver_plate.sii')
    template = re.search(r'ui::text_template\s*:\s*txt\.driver\.plate\s*\{([^}]+)\}',
                         read_text('/ui/template/text.ets.sii')).group(1)
    font_path = re.search(r'face=(/[^\s>]+)', template).group(1)
    font = read_text(font_path)
    xscale = float(re.search(r'xscale=([\d.]+)', template).group(1))
    yscale = float(re.search(r'yscale=([\d.]+)', template).group(1))
    default_scale = float(re.search(r'^default_scale:([\d.]+)', font, re.M).group(1))
    xscale *= default_scale
    yscale *= default_scale
    line_height = float(re.search(r'^vert_span:([\d.]+)', font, re.M).group(1)) * yscale
    window = re.search(r'ui::window\s*:[^{]+\{([^}]+)\}', layout).group(1)
    width = int(re.search(r'coords_r:\s*(\d+)', window).group(1))
    height = int(re.search(r'coords_t:\s*(\d+)', window).group(1))
    if not 0 < width <= 2048 or not 0 < height <= 2048:
        raise ValueError('Invalid driver plate texture dimensions')
    result = Image.new('RGBA', (width, height))
    images = []
    for row in re.findall(r'^image:([^\n#]+)', font, re.M):
        material_path, _, _, sx, sy, padding = [value.strip() for value in row.split(',')]
        material = read_text(material_path)
        source = re.search(r'source\s*:\s*"([^"]+)"', material).group(1)
        atlas = load_texture(source).convert('RGB')
        distance_range = float(re.search(r'aux\[0\]\s*:\s*\{[^,]+,[^,]+,\s*([\d.]+)', material).group(1))
        images.append((atlas, float(sx) * xscale, float(sy) * yscale, distance_range))
    glyphs = {}
    for code, row in re.findall(r'^x([\da-fA-F]+),\s*([^\n#]+)', font, re.M):
        glyphs[chr(int(code, 16))] = [float(value.strip()) for value in row.split(',')]
    # The stock plate font contains capitals only. Keep saved strings untouched.
    letters = [glyphs.get(char, glyphs.get(char.upper(), glyphs.get(' '))) for char in text]
    letters = [glyph for glyph in letters if glyph is not None]
    advance = sum(glyph[6] * images[int(glyph[7])][1] for glyph in letters)
    for body in re.findall(r'ui::text\s*:[^{]+\{([^}]+)\}', layout):
        background = re.search(r'<img src=([^\s>]+)\s+bottom=p([\d.]+)', body)
        if not background:
            continue
        material = read_text(background[1])
        source = re.search(r'source\s*:\s*"([^"]+)"', material).group(1)
        image = load_texture(source).convert('RGBA')
        coords = {key: int(value) for key, value in re.findall(r'coords_([lrtb]):\s*(\d+)', body)}
        image = image.crop((0, 0, image.width, round(float(background[2]))))
        image = image.resize((coords['r'] - coords['l'], coords['t'] - coords['b']), Image.Resampling.LANCZOS)
        result.alpha_composite(image, (coords['l'], height - coords['t']))
    for body in re.findall(r'ui::text_common\s*:[^{]+\{([^}]+)\}', layout):
        if not re.search(r'look_template:\s*txt\.driver\.plate', body):
            continue
        coords = {key: int(value) for key, value in re.findall(r'coords_([lrtb]):\s*(\d+)', body)}
        tile = Image.new('RGBA', (coords['r'] - coords['l'], coords['t'] - coords['b']))
        pen = (tile.width - advance) / 2
        top = (tile.height - line_height) / 2
        for ax, ay, w, h, px, py, step, image_index in letters:
            atlas, sx, sy, distance_range = images[int(image_index)]
            if w > 0 and h > 0:
                size = (max(1, round(w * sx)), max(1, round(h * sy)))
                bitmap = atlas.transform(size, Image.Transform.EXTENT, (ax, ay, ax + w, ay + h), Image.Resampling.BILINEAR)
                r, g, b = bitmap.split()
                median = ImageChops.lighter(ImageChops.darker(r, g), ImageChops.darker(ImageChops.lighter(r, g), b))
                alpha = median.point(lambda value: round(max(0, min(255, (value / 255 - .5) * distance_range * min(sx, sy) * 255 + 127.5))))
                ink = Image.new('RGBA', size, (0, 0, 0, 255))
                ink.putalpha(alpha)
                tile.alpha_composite(ink, (round(pen + px * sx), round(top + py * sy)))
            pen += step * sx
        result.alpha_composite(tile, (coords['l'], height - coords['t']))
    return result
