"""Single-image classifiers compared on one fixed grid and all-date valid coverage."""
import csv
import json
import re
import zipfile
from pathlib import Path
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin, array_bounds
from rasterio.warp import calculate_default_transform, reproject, transform
from processing import (MAX_BYTES, MAX_PIXELS, validate, prepare_scene, image_url,
                        classify_rf, classify_unet, classify_svm)
from rainfall import acquisition_date, fetch_rainfall

MAX_SCENES = 6
MAX_SERIES_PIXELS = 20_000_000


def suggested_date(name):
    """Suggest one distinct year-first date; never guess between conflicting dates."""
    pattern = r'(?<!\d)(20\d{2})(?:(\d{2})(\d{2})|([-_.])(\d{2})\4(\d{2}))(?!\d)'
    dates = set()
    for match in re.finditer(pattern, name):
        y, compact_m, compact_d, _, m, d = match.groups()
        try:
            dates.add(acquisition_date(f'{y}-{compact_m or m}-{compact_d or d}').isoformat())
        except ValueError:
            pass
    return dates.pop() if len(dates) == 1 else ''


def inspect_files(files, folder):
    if not 2 <= len(files) <= MAX_SCENES:
        raise ValueError(f'Choose 2–{MAX_SCENES} images of the same location.')
    entries, total = [], 0
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    for i, item in enumerate(files):
        source = Path(item['datapath'])
        if source.stat().st_size > MAX_BYTES:
            raise ValueError(f"{item['name']}: maximum file size is 250 MiB.")
        with rasterio.open(source) as src:
            validate(src)
            total += src.width * src.height
            entries.append({'name': item['name'], 'path': str(source),
                            'date': suggested_date(item['name'])})
    if total > MAX_SERIES_PIXELS:
        raise ValueError('This prototype supports 20 million source pixels across the series. Use smaller crops or fewer images.')
    # Validate shared geography before copying or classifying anything.
    common_grid(entries)
    import shutil
    for i, entry in enumerate(entries):
        target = folder / f'{i}.tif'
        shutil.copyfile(entry['path'], target)
        entry['path'] = str(target)
    return entries


def common_grid(entries):
    with rasterio.open(entries[0]['path']) as first:
        validate(first)
        crs, anchor, bounds = first.crs, first.transform, first.bounds
    left, bottom, right, top = bounds
    for entry in entries[1:]:
        with rasterio.open(entry['path']) as src:
            validate(src)
            if src.crs != crs:
                raise ValueError('Use images exported in the same projected CRS for this prototype. Different CRS inputs are not silently compared.')
            b = src.bounds
            left, bottom = max(left, b.left), max(bottom, b.bottom)
            right, top = min(right, b.right), min(top, b.top)
    # Crop inward to whole pixels on the first source's 10 m grid.
    x0 = int(np.ceil((left-anchor.c)/10 - 1e-7))
    x1 = int(np.floor((right-anchor.c)/10 + 1e-7))
    y0 = int(np.ceil((anchor.f-top)/10 - 1e-7))
    y1 = int(np.floor((anchor.f-bottom)/10 + 1e-7))
    if x1 <= x0 or y1 <= y0:
        raise ValueError('These images have no shared geographic coverage. Choose one location.')
    if (x1-x0)*(y1-y0) > MAX_PIXELS:
        raise ValueError('Shared region exceeds the ten-million-pixel limit.')
    grid = from_origin(anchor.c+x0*10, anchor.f-y0*10, 10, 10)
    return crs, grid, y1-y0, x1-x0


def warp_band(src, band, crs, grid, shape, dtype, nodata):
    dest = np.full(shape, nodata, dtype=dtype)
    reproject(rasterio.band(src, band), dest, src_transform=src.transform, src_crs=src.crs,
              src_nodata=src.nodata, dst_transform=grid, dst_crs=crs, dst_nodata=nodata,
              resampling=Resampling.nearest)
    return dest


def assemble(entries, outputs, model, threshold, folder):
    """Metrics are 10 m; previews are separate nearest-neighbour Web Mercator images."""
    crs, grid, height, width = common_grid(entries)
    shape = (height, width)
    shared = np.ones(shape, dtype=bool)
    masks = []
    for out in outputs:
        with rasterio.open(Path(out)/'classification.tif') as src:
            classes = warp_band(src, 1, crs, grid, shape, 'uint8', 255)
        with rasterio.open(Path(out)/'model_score.tif') as src:
            scores = warp_band(src, 1, crs, grid, shape, 'float32', -9999)
        shared &= (classes != 255) & np.isfinite(scores) & (scores >= 0)
        masks.append((classes == 1) & (scores >= threshold))
    count = int(shared.sum())
    if not count:
        raise ValueError('No pixels are valid on every date. Choose clearer acquisitions with shared coverage.')
    area = abs(grid.a * grid.e) / 1e6
    bounds = array_bounds(height, width, grid)
    x, y = grid * (width/2, height/2)
    lon, lat = transform(crs, 'EPSG:4326', [x], [y])
    location = (lat[0], lon[0])
    preview, pw, ph = calculate_default_transform(crs, 'EPSG:3857', width, height, *bounds)
    original_pw, original_ph = pw, ph
    ratio = max(pw, ph)/900
    if ratio > 1:
        pw, ph = max(1, int(pw/ratio)), max(1, int(ph/ratio))
        from affine import Affine
        preview = preview * Affine.scale(original_pw/pw, original_ph/ph)
    pshape = (ph, pw)
    def display(array):
        dest = np.zeros(pshape, dtype='uint8')
        reproject(array.astype('uint8'), dest, src_transform=grid, src_crs=crs,
                  dst_transform=preview, dst_crs='EPSG:3857', resampling=Resampling.nearest)
        return dest
    import base64
    valid_preview = display(shared)
    rows, maps = [], []
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    profile = dict(driver='GTiff', height=height, width=width, count=1, crs=crs,
                   transform=grid, dtype='uint8', nodata=255, compress='deflate')
    for i, (entry, plume) in enumerate(zip(entries, masks)):
        plume &= shared
        rows.append({'date': entry['date'], 'name': entry['name'],
                     'plume_km2': float(plume.sum()*area)})
        with rasterio.open(entry['path']) as src:
            rgb = np.stack([warp_band(src,b,'EPSG:3857',preview,pshape,'float32',-9999) for b in (3,2,1)],axis=-1)
        rgb = (np.clip(np.nan_to_num(rgb)/.25,0,1)**(1/1.2)*255).astype('uint8')
        rgba = np.concatenate([rgb, (valid_preview*255)[...,None]],axis=-1)
        maps.append({'rgb':image_url(rgba), 'plume':base64.b64encode(display(plume).tobytes()).decode()})
        with rasterio.open(folder/f'plume_{entry["date"]}.tif','w',**profile) as dst:
            dst.write(np.where(shared, plume,255).astype('uint8'),1)
            dst.update_tags(definition='1=predicted plume passing fixed score filter;0=other;255=not valid on all dates',
                            model=model, date=entry['date'], score_threshold=threshold)
    pairs = {}
    for a in range(len(masks)):
        for b in range(a+1,len(masks)):
            earlier, later = masks[a], masks[b]
            pairs[f'{a}-{b}'] = {'earlier_only_km2':float((earlier & ~later).sum()*area),
                                'later_only_km2':float((later & ~earlier).sum()*area),
                                'both_km2':float((earlier & later).sum()*area)}
            change = np.where(shared, earlier.astype('uint8')+2*later,255).astype('uint8')
            with rasterio.open(folder/f'change_{entries[a]["date"]}_{entries[b]["date"]}.tif','w',**profile) as dst:
                dst.write(change,1)
                dst.update_tags(definition='0=neither;1=earlier only;2=later only;3=both;255=not valid on all dates')
    frequency=np.zeros(shape,dtype='uint8')
    for mask in masks: frequency += mask
    frequency_areas={str(n):float(((frequency==n)&shared).sum()*area) for n in range(len(entries)+1)}
    with rasterio.open(folder/'plume_frequency.tif','w',**profile) as dst:
        dst.write(np.where(shared,frequency,255).astype('uint8'),1)
        dst.update_tags(definition='number of acquisitions classified as plume on all-date-valid pixels', observations=len(entries))
    west, south, east, north = array_bounds(ph,pw,preview)
    llon,llat = transform('EPSG:3857','EPSG:4326',[west,east],[south,north])
    return {'rows':rows,'maps':maps,'pairs':pairs,'width':pw,'height':ph,
            'frequency':base64.b64encode(display(frequency).tobytes()).decode(),'frequency_km2':frequency_areas,
            'valid':base64.b64encode(valid_preview.tobytes()).decode(),
            'bounds':[[llat[0],llon[0]],[llat[1],llon[1]]],
            'model':model,'threshold':threshold,'shared_km2':count*area,
            'overlap_km2':height*width*area,'coverage_percent':100*count/(height*width),
            'location':location,'crs':str(crs),'transform':list(grid)[:6],
            'native_width':width,'native_height':height,'folder':str(folder)}


def build_series(entries, model, threshold, folder, *, weather=fetch_rainfall, progress=lambda text:None):
    if model not in ('rf','unet','svm') or not 0 <= threshold <= .95:
        raise ValueError('Choose a supported model and a score filter from 0 to 95%.')
    entries = sorted([{**e,'date':acquisition_date(e['date']).isoformat()} for e in entries],key=lambda e:e['date'])
    if not 2 <= len(entries) <= MAX_SCENES or len({e['date'] for e in entries}) != len(entries):
        raise ValueError('Use 2–6 distinct acquisition dates, with one image per date.')
    common_grid(entries)
    outputs = []; checkpoint_ids = set()
    classifier = {'rf':classify_rf,'unet':classify_unet,'svm':classify_svm}[model]
    for i, entry in enumerate(entries):
        progress(f'Classifying {i+1}/{len(entries)} · {entry["date"]}')
        result = classifier(prepare_scene(entry['path']), Path(folder)/f'inference_{i}')
        outputs.append(result['output_dir'])
        checkpoint_ids.add(result['map']['modelId'])
        del result
    progress('Aligning grids and calculating shared valid coverage…')
    result = assemble(entries,outputs,model,threshold,Path(folder)/'comparison')
    result['checkpoint_ids'] = sorted(checkpoint_ids)
    for i, row in enumerate(result['rows']):
        progress(f'Retrieving rainfall {i+1}/{len(entries)} · {row["date"]}')
        try:
            row['weather'] = weather(result['location'],row['date'])
            row['rainfall_7d_mm'] = row['weather']['totals_mm'][7]
            row['weather_error'] = ''
        except Exception as error:
            row['weather'] = None; row['rainfall_7d_mm'] = None
            row['weather_error'] = str(error) or 'Weather unavailable. Retry rainfall.'
    return result


def export_series(result):
    folder=Path(result['folder'])
    with (folder/'observations.csv').open('w',newline='') as f:
        fields=['date','name','plume_km2','rainfall_7d_mm','weather_error']
        writer=csv.DictWriter(f,fieldnames=fields); writer.writeheader()
        writer.writerows({k:r[k] for k in fields} for r in result['rows'])
    metadata={k:v for k,v in result.items() if k not in ('maps','valid','frequency','folder')}
    metadata['notes']='Fixed intersection; all-date valid pixels; nearest-neighbour grid alignment. Areas are classification estimates, not concentration. Rainfall is context, not causation. No interpolation between observations.'
    (folder/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    target=folder/'plumewatch_time_series.zip'
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for p in sorted(folder.iterdir()):
            if p.suffix in ('.tif','.csv','.json'): archive.write(p,p.name)
    return target
