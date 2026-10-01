"""Local, native-grid CVAT preparation. See ANNOTATION_WORKFLOW.md."""
import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
from PIL import Image
import rasterio
from rasterio.features import rasterize
from affine import Affine
from processing import BANDS, validate, usable

CLASSES = {'normal_water': 0, 'plume': 1, 'shallow_water': 2, 'land': 3}
ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / 'data/annotation_manifest.json'


def render_rgb(data):
    rgb = np.nan_to_num(data[[2, 1, 0]], nan=0, posinf=0, neginf=0)
    rgb = (np.clip(rgb / .25, 0, 1) ** (1 / 1.2) * 255).astype('uint8').transpose(1, 2, 0)
    rgb[~((data[11] > 0) & np.isfinite(data[[2, 1, 0]]).all(axis=0))] = 0
    return rgb


def check_source(src, record):
    validate(src)
    if (src.width, src.height) != (record['width'], record['height']) or str(src.crs) != record['crs'] or list(src.transform)[:6] != record['transform']:
        raise ValueError('Source grid no longer matches manifest: ' + record['source_tif'])


def polygon_mask(element, shape):
    """CVAT x/y coordinates use the image's top-left corner; burn pixel centres."""
    height, width = shape
    if (int(element.attrib['width']), int(element.attrib['height'])) != (width, height):
        raise ValueError('CVAT dimensions differ from source')
    mask = np.full(shape, 255, dtype=np.uint8)
    for polygon in element:
        if polygon.get('label') == 'candidate':
            continue  # Unreviewed SAM proposals never become training labels.
        if polygon.tag not in ('polygon', 'mask'):
            raise ValueError('Only polygon or mask annotations supported; found ' + polygon.tag)
        label = polygon.attrib['label']
        if label not in CLASSES:
            raise ValueError('Unknown label: ' + label)
        if polygon.tag == 'mask':
            left, top, mw, mh = (int(polygon.attrib[k]) for k in ('left', 'top', 'width', 'height'))
            if min(left, top) < 0 or min(mw, mh) < 1 or left + mw > width or top + mh > height:
                raise ValueError('Invalid or out-of-bounds mask')
            runs = [int(n.strip()) for n in polygon.attrib['rle'].split(',')]
            if not runs or any(n < 0 for n in runs) or sum(runs) != mw * mh:
                raise ValueError('Invalid mask RLE length')
            selected = np.zeros(shape, dtype=bool)
            selected[top:top + mh, left:left + mw] = np.repeat(np.arange(len(runs)) % 2, runs).reshape(mh, mw).astype(bool)
        else:
            points = [tuple(map(float, p.split(','))) for p in polygon.attrib['points'].split(';')]
            if len(points) < 3 or any(len(p) != 2 or not np.isfinite(p).all() or not (0 <= p[0] <= width and 0 <= p[1] <= height) for p in points):
                raise ValueError('Invalid or out-of-bounds polygon')
            geometry = {'type': 'Polygon', 'coordinates': [points + [points[0]]]}
            selected = rasterize([(geometry, 1)], out_shape=shape, transform=Affine.identity(), all_touched=False, dtype='uint8').astype(bool)
        if np.any(selected & (mask != 255) & (mask != CLASSES[label])):
            raise ValueError('Overlapping class annotations in ' + element.attrib['name'])
        mask[selected] = CLASSES[label]
    return mask


def read_xml(path):
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if Path(n).name == 'annotations.xml']
            if len(names) != 1:
                raise ValueError('Expected exactly one annotations.xml in ZIP')
            content = archive.read(names[0])
    else:
        content = path.read_bytes()
    if b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper():
        raise ValueError('XML entities are not supported')
    tree = ET.fromstring(content)
    if tree.tag != 'annotations' or tree.find('track') is not None:
        raise ValueError('Export CVAT for images, not video tracks')
    return tree


def convert(paths, records, output):
    lookup = {Path(r['png']).name: r for r in records}
    if len(lookup) != len(records):
        raise ValueError('Duplicate PNG names in manifest')
    jobs, seen = [], set()
    # Validate the whole export before writing any masks.
    for path in paths:
        for element in read_xml(path).findall('image'):
            name = Path(element.attrib['name']).name
            if name in seen or name not in lookup:
                raise ValueError('Duplicate or unknown image: ' + name)
            seen.add(name)
            record = lookup[name]
            target = output / (Path(name).stem + '_mask.tif')
            if target.exists():
                raise ValueError('Output exists; choose a new output folder: ' + str(target))
            with rasterio.open(ROOT / record['source_tif']) as src:
                check_source(src, record)
                mask = polygon_mask(element, src.shape)
                mask[~usable(src.read())] = 255
            jobs.append((record, target, mask))
    if not jobs:
        raise ValueError('No images found in annotation exports')
    output.mkdir(parents=True, exist_ok=True)
    for record, target, mask in jobs:
        with rasterio.open(ROOT / record['source_tif']) as src:
            profile = src.profile.copy()
        profile.update(count=1, dtype='uint8', nodata=255, compress='deflate', predictor=1)
        with rasterio.open(target, 'w', **profile) as dst:
            dst.write(mask, 1)
            dst.set_band_description(1, 'class_id')
            dst.update_tags(classes=json.dumps(CLASSES), source_tif=record['source_tif'])
        print(target.name, dict(zip(*np.unique(mask, return_counts=True))))


def training_pixels(source, mask_path):
    """Return ten-band reflectance X and labels y for ONE scene, before any split."""
    with rasterio.open(source) as src, rasterio.open(mask_path) as labels:
        validate(src)
        if (src.crs, src.transform, src.shape) != (labels.crs, labels.transform, labels.shape):
            raise ValueError('Training mask/source grids differ')
        data, mask = src.read(), labels.read(1)
        if not set(np.unique(mask)).issubset({*CLASSES.values(), 255}):
            raise ValueError('Unexpected class IDs')
        keep = usable(data) & (mask != 255)
        return data[:10, keep].T, mask[keep]


def check_splits(records):
    """Related sites, events and acquisitions cannot cross assigned splits."""
    for key in ('site', 'event_group', 'acquisition'):
        groups = {}
        for r in records:
            split = r.get('split', 'unassigned')
            if split == 'unassigned':
                continue
            if split not in ('train', 'validation', 'test') or not r.get(key):
                raise ValueError('Invalid split or missing grouping metadata')
            groups.setdefault(r[key], set()).add(split)
        if any(len(splits) > 1 for splits in groups.values()):
            raise ValueError('Split leakage across ' + key)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['png', 'masks', 'check-splits'])
    parser.add_argument('annotations', nargs='*', type=Path)
    parser.add_argument('--manifest', type=Path, default=MANIFEST)
    parser.add_argument('--output', type=Path, default=ROOT / 'data/processed/cvat_masks')
    args = parser.parse_args()
    records = json.loads(args.manifest.read_text())
    if args.command == 'masks':
        convert(args.annotations, records, args.output)
    elif args.command == 'check-splits':
        check_splits(records)
        if any(r.get('split', 'unassigned') == 'unassigned' for r in records):
            raise ValueError('Splits are not ready: unassigned scenes remain')
        print('No site/event/acquisition crosses splits')
    else:
        for r in records:
            with rasterio.open(ROOT / r['source_tif']) as src:
                check_source(src, r)
                rgb = render_rgb(src.read())
            target = ROOT / r['png']
            if target.exists():
                with Image.open(target) as existing:
                    if not np.array_equal(np.asarray(existing), rgb):
                        raise ValueError('Existing PNG differs; refusing to replace: ' + str(target))
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                Image.fromarray(rgb).save(target)
        print('Verified/generated', len(records), 'native-grid PNGs')


if __name__ == '__main__':
    main()
