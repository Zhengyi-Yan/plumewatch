"""Four-panel comparisons drawn directly from native-grid prediction TIFFs."""

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import rasterio

from data import ROOT
from render_rf_examples import COLORS, EXAMPLES
from train_multiclass import mask_path


def layer(rgb, classes):
    rgba = np.zeros((*classes.shape, 4), dtype='uint8')
    for cls, color in COLORS.items():
        rgba[classes == cls] = color
    return Image.alpha_composite(rgb.convert('RGBA'), Image.fromarray(rgba, 'RGBA')).convert('RGB')


def map_pixels(path, source):
    with rasterio.open(path) as image:
        if (image.crs, image.transform, image.shape) != (source.crs, source.transform, source.shape):
            raise ValueError('Gallery source grid mismatch: ' + str(path))
        values = image.read(1)
    if not set(np.unique(values)).issubset({0, 1, 3, 255}):
        raise ValueError('Unexpected class in ' + str(path))
    return values


def font(size):
    try:
        return ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', size)
    except OSError:
        return ImageFont.load_default()


def scene_panel(scene, prediction_dir, destination):
    record = scene.record
    stem = Path(scene.name).stem
    with rasterio.open(ROOT / record['source_tif']) as source:
        labels = map_pixels(mask_path(record), source)
        rf_path = ROOT / 'data/processed/multiclass_rf_v1/examples' / f'{stem}_heldout_rf.tif'
        rf = map_pixels(rf_path, source)
        unet_path = prediction_dir / f'{stem}_unet_class.tif'
        unet = map_pixels(unet_path, source)
        width, height = source.width, source.height
    rgb = Image.open(ROOT / record['png']).convert('RGB')
    if rgb.size != (width, height):
        raise ValueError('RGB dimensions differ from source TIFF: ' + scene.name)
    display_width = 390
    display_height = round(display_width * height / width)
    size = (display_width, display_height)
    rgb = rgb.resize(size, Image.Resampling.BILINEAR)
    views = [rgb]
    for array in (labels, rf, unet):
        # This is the only geometric display operation. Source class rasters stay unchanged.
        reduced = np.asarray(Image.fromarray(array).resize(size, Image.Resampling.NEAREST))
        views.append(layer(rgb, reduced))
    canvas = Image.new('RGB', (display_width * 4 + 50, display_height + 102), '#ffffff')
    draw = ImageDraw.Draw(canvas)
    heading = f'{record["site"]} · {record["date"]} · {scene.group} held out'
    draw.text((10, 8), heading, font=font(18), fill='#182636')
    for i, (title, view) in enumerate(zip(
            ('Sentinel-2 RGB', 'CVAT labels', 'Held-out RF', 'Held-out U-Net'), views)):
        x = 10 + i * (display_width + 10)
        draw.text((x, 38), title, font=font(17), fill='#182636')
        canvas.paste(view, (x, 64))
    draw.text((10, display_height + 72),
              'Orange plume   ·   Blue normal water   ·   Grey land   ·   Uncoloured = unlabelled or invalid',
              font=font(17), fill='#182636')
    canvas.save(destination)
    return canvas, {'scene': scene.name, 'rgb': record['png'], 'labels': str(mask_path(record).relative_to(ROOT)),
                    'rf': str(rf_path.relative_to(ROOT)),
                    'unet': str(unet_path.relative_to(ROOT)),
                    'source_size': [width, height], 'display_size': list(size)}


def build_galleries(scenes, prediction_dir, destination):
    destination.mkdir(parents=True, exist_ok=True)
    lookup = {scene.name: scene for scene in scenes}
    pages = {'clear': [], 'ambiguous': []}
    provenance = []
    for kind, name in EXAMPLES:
        scene = lookup[name]
        canvas, details = scene_panel(scene, prediction_dir,
                                      destination / f'{Path(name).stem}_comparison.png')
        pages[kind].append(canvas)
        provenance.append(details)
    for kind, panels in pages.items():
        sheet = Image.new('RGB', (max(panel.width for panel in panels),
                                  sum(panel.height for panel in panels) + 12 * (len(panels) - 1)), '#dce3e8')
        top = 0
        for panel in panels:
            sheet.paste(panel, (0, top))
            top += panel.height + 12
        sheet.save(destination / f'{kind}_examples.png')
    (destination / 'sources.json').write_text(json.dumps(provenance, indent=2) + '\n')
