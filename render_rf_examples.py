"""Render six native-grid, site/event-held-out RF classification examples."""

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import rasterio
from rasterio.windows import Window

from annotation_pipeline import MANIFEST, ROOT, check_source
from processing import usable
from train_multiclass import SEED, groups_for, make_model, mask_path, sample_scene, training_set

EXAMPLES = [
    ('clear', 'P1-01_20190812T222541_20190812T222624_T60GUV_cvat_v1.png'),
    ('clear', 'P2-01_20210602T222551_20210602T222545_T59GPN_cvat_v1.png'),
    ('clear', 'P3-05_20230219T221601_20230219T221601_T60HWC_cvat_v1.png'),
    ('ambiguous', 'P1-03_20200712T222549_20200712T222545_T60GUV_cvat_v1.png'),
    ('ambiguous', 'P2-04_20210428T222539_20210428T222539_T59GPN_cvat_v1.png'),
    ('ambiguous', 'P3-04_20230219T221601_20230219T221601_T60HWB_cvat_v1.png'),
]
RASTER_DIR = ROOT / 'data/processed/multiclass_rf_v1/examples'
PREVIEW_DIR = ROOT / 'results/multiclass_rf_v1/examples'
COLORS = {0: (36, 101, 219, 145), 1: (245, 113, 38, 145), 3: (150, 150, 150, 125)}


def classify_held_out(record, model, destination):
    with rasterio.open(ROOT / record['source_tif']) as src:
        check_source(src, record)
        profile = src.profile.copy()
        profile.update(count=1, dtype='uint8', nodata=255, compress='deflate')
        with rasterio.open(destination, 'w', **profile) as dst:
            for top in range(0, src.height, 256):
                window = Window(0, top, src.width, min(256, src.height - top))
                data = src.read(window=window)
                valid = usable(data)
                output = np.full(valid.shape, 255, dtype='uint8')
                if valid.any():
                    output[valid] = model.predict(data[:10, valid].T.astype('float32'))
                dst.write(output, 1, window=window)
            dst.set_band_description(1, 'held_out_class_id')
            dst.update_tags(classes='0=normal_water;1=plume;3=land;255=invalid',
                            source_tif=record['source_tif'])


def overlay(rgb, labels):
    layer = np.zeros((*labels.shape, 4), dtype='uint8')
    for cls, rgba in COLORS.items():
        layer[labels == cls] = rgba
    return Image.alpha_composite(rgb.convert('RGBA'), Image.fromarray(layer, 'RGBA')).convert('RGB')


def preview(record, prediction, destination, caption):
    width = 470
    rgb = Image.open(ROOT / record['png']).convert('RGB')
    with rasterio.open(mask_path(record)) as src:
        labels = Image.fromarray(src.read(1))
    with rasterio.open(prediction) as src:
        predicted = Image.fromarray(src.read(1))
    height = round(width * rgb.height / rgb.width)
    rgb = rgb.resize((width, height), Image.Resampling.BILINEAR)
    labels = np.asarray(labels.resize((width, height), Image.Resampling.NEAREST))
    predicted = np.asarray(predicted.resize((width, height), Image.Resampling.NEAREST))
    panels = [rgb, overlay(rgb, labels), overlay(rgb, predicted)]
    canvas = Image.new('RGB', (width * 3 + 40, height + 100), 'white')
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', 18)
    except OSError:
        font = ImageFont.load_default()
    draw.text((12, 8), caption, font=font, fill='#172332')
    for n, (title, panel) in enumerate(zip(('Sentinel-2 RGB', 'CVAT labels', 'Held-out RF classification'), panels)):
        x = 10 + n * (width + 10)
        draw.text((x, 38), title, font=font, fill='#172332')
        canvas.paste(panel, (x, 65))
    draw.text((12, height + 72), 'Orange: plume    Blue: normal water    Grey: land    Uncoloured: unlabelled/invalid',
              font=font, fill='#172332')
    canvas.save(destination)
    return canvas


def main():
    records = [r for r in json.loads(MANIFEST.read_text()) if mask_path(r).exists()]
    groups = groups_for(records)
    index = {Path(r['png']).name: i for i, r in enumerate(records)}
    samples = [sample_scene(r) for r in records]
    RASTER_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    pages = {'clear': [], 'ambiguous': []}
    for group in sorted({groups[index[name]] for _, name in EXAMPLES}):
        included = [i for i, value in enumerate(groups) if value != group]
        x, y = training_set(samples, groups, included, np.random.default_rng(SEED))
        model = make_model().fit(x, y)
        for kind, name in EXAMPLES:
            i = index[name]
            if groups[i] != group:
                continue
            record = records[i]
            stem = Path(name).stem
            raster = RASTER_DIR / f'{stem}_heldout_rf.tif'
            classify_held_out(record, model, raster)
            caption = f'{record["site"]}  ·  {record["date"]}  ·  group held out: {group}'
            panel = preview(record, raster, PREVIEW_DIR / f'{stem}_heldout_rf.png', caption)
            pages[kind].append(panel)
            print('Rendered', kind, name, flush=True)
    for kind, panels in pages.items():
        sheet = Image.new('RGB', (max(p.width for p in panels), sum(p.height for p in panels) + 12 * (len(panels) - 1)),
                          '#dfe4e8')
        top = 0
        for panel in panels:
            sheet.paste(panel, (0, top))
            top += panel.height + 12
        path = PREVIEW_DIR / f'{kind}_examples.png'
        sheet.save(path)
        print('Gallery:', path)


if __name__ == '__main__':
    main()
