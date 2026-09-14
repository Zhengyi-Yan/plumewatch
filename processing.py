"""Raster validation, native-grid prediction and Web Mercator display previews."""
from pathlib import Path
from functools import lru_cache
import base64
import csv
import io
import json
import pickle
import zipfile

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.warp import calculate_default_transform, transform_bounds, reproject
from rasterio.windows import Window
from PIL import Image

ROOT = Path(__file__).resolve().parent
MODEL_PATH = ROOT / 'results/baseline_v1/model.pkl'
EXAMPLE = ROOT / 'hutt-test/hutt_20210723_full_scene_v1.tif'
BANDS = ['B2','B3','B4','B5','B6','B7','B8','B8A','B11','B12','SCL','valid']
MAX_BYTES = 250 * 1024 * 1024
MAX_PIXELS = 10_000_000
WARNING = ('Two-class Hutt pilot. No water mask: land can be classified as plume. '
           'Predicted class areas are provisional, not validated plume extent. '
           'Model scores are not calibrated probabilities or area error bounds.')

def validate(src):
    if src.driver != 'GTiff' or src.count != 12 or list(src.descriptions) != BANDS:
        raise ValueError('Use the 12-band GeoTIFF from the PlumeWatch GEE scene export (ten reflectance bands, SCL, valid).')
    if not src.crs or not src.crs.is_projected or src.crs.linear_units != 'metre':
        raise ValueError('The scene must use a projected CRS in metres, as in the GEE export.')
    if src.width * src.height > MAX_PIXELS:
        raise ValueError('Scene exceeds 10 million pixels. Export a smaller region or upload one GEE tile at a time.')
    if not np.allclose((src.transform.a, src.transform.e), (10, -10), atol=.01) or src.transform.b != 0 or src.transform.d != 0:
        raise ValueError('Use the north-up 10 m grid from the GEE export.')
    if not all(dtype.startswith('float') for dtype in src.dtypes[:10]):
        raise ValueError('Use the scaled floating-point reflectance export, not raw Sentinel integer bands.')

def usable(data):
    spectra = data[:10]
    good = (data[11] == 1) & np.isfinite(spectra).all(axis=0) & (spectra != -9999).all(axis=0)
    # Same SCL exclusions as the existing GEE pipeline; keep bright/turbid classes.
    good &= np.isin(data[10], [2, 4, 5, 6, 7])
    if good.any() and np.percentile(spectra[:, good], 99) > 2:
        raise ValueError('Reflectance appears unscaled. Re-export with the supplied GEE script.')
    return good

def image_url(array):
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode()

def prepare_scene(path):
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('Maximum upload size is 250 MB. Export a smaller area.')
    with rasterio.open(path) as src:
        validate(src)
        transform, width, height = calculate_default_transform(src.crs, 'EPSG:3857', src.width, src.height, *src.bounds)
        factor = max(width, height) / 1100
        if factor > 1:
            old_w, old_h = width, height
            width, height = max(1, round(width/factor)), max(1, round(height/factor))
            transform = transform * rasterio.Affine.scale(old_w/width, old_h/height)
        with WarpedVRT(src, crs='EPSG:3857', transform=transform, width=width, height=height,
                       resampling=Resampling.nearest, nodata=-9999) as vrt:
            data = vrt.read()
        good = usable(data)
        rgb = np.moveaxis(data[[2,1,0]], 0, -1)
        rgb = (np.clip(np.nan_to_num(rgb)/.25, 0, 1) ** (1/1.2)*255).astype('uint8')
        rgba = np.concatenate([rgb, (good*255).astype('uint8')[...,None]], axis=2)
        bounds_m = rasterio.transform.array_bounds(height, width, transform)
        west, south, east, north = transform_bounds('EPSG:3857','EPSG:4326',*bounds_m)
        return {'path': str(path), 'name': path.name, 'width': src.width, 'height': src.height,
                'crs': str(src.crs), 'pixel_area': abs(src.transform.a * src.transform.e),
                'grid': (transform, width, height),
                'map': {'rgb': image_url(rgba), 'bounds': [[south,west],[north,east]],
                        'width': width, 'height': height, 'projectedBounds': list(bounds_m)},
                'model': 'Hutt pilot · 2 classes', 'warning': WARNING}

@lru_cache(maxsize=1)
def load_model():
    # Load only the repository's trusted model, never an uploaded pickle.
    with MODEL_PATH.open('rb') as stream:
        bundle = pickle.load(stream)
    import sklearn
    if bundle['sklearn_version'] != sklearn.__version__:
        raise ValueError('Model requires scikit-learn '+bundle['sklearn_version']+'. Install requirements.txt.')
    if bundle['bands'] != BANDS[:10] or list(bundle['model'].classes_) != [0,1]:
        raise ValueError('This app version requires the bundled two-class pilot model.')
    bundle['model'].n_jobs = 1  # Avoid each visitor starting an all-core prediction.
    return bundle['model']

def classify(scene, output_dir):
    model = load_model()
    out = Path(output_dir); out.mkdir(parents=True, exist_ok=True)
    with rasterio.open(scene['path']) as src:
        validate(src)
        prediction = np.full((src.height,src.width), 255, dtype='uint8')
        score = np.full(prediction.shape, -9999, dtype='float32')
        for y in range(0,src.height,128):
            window = Window(0,y,src.width,min(128,src.height-y))
            data = src.read(window=window)
            good = usable(data)
            if not good.any(): continue
            features = data[:10,good].T
            probabilities = model.predict_proba(features)
            prediction[y:y+int(window.height)][good] = model.classes_[probabilities.argmax(axis=1)]
            score[y:y+int(window.height)][good] = probabilities.max(axis=1)
        if not (prediction != 255).any(): raise ValueError('No usable pixels remain after quality screening.')
        profile = src.profile.copy()
        for filename, array, dtype, nodata, band in [
            ('classification.tif',prediction,'uint8',255,'class_id'),
            ('model_score.tif',score,'float32',-9999,'winning_class_score')]:
            profile.update(count=1,dtype=dtype,nodata=nodata,compress='deflate')
            with rasterio.open(out/filename,'w',**profile) as dst:
                dst.write(array,1); dst.set_band_description(1,band)
                dst.update_tags(model='baseline_v1',warning=WARNING,classes='0=background_water;1=plume;255=no_data')
        transform,width,height = scene['grid']
        display_pred = np.full((height,width),255,dtype='uint8')
        display_score = np.zeros((height,width),dtype='float32')
        for source,dest,nodata in [(prediction,display_pred,255),(score,display_score,-9999)]:
            reproject(source,dest,src_transform=src.transform,src_crs=src.crs,src_nodata=nodata,
                      dst_transform=transform,dst_crs='EPSG:3857',dst_nodata=nodata,resampling=Resampling.nearest)
    payload = dict(scene['map'])
    payload['classes'] = base64.b64encode(display_pred.tobytes()).decode()
    payload['scores'] = base64.b64encode(np.clip(display_score*100,0,100).astype('uint8').tobytes()).decode()
    return {'scene':scene,'prediction':prediction,'score':score,'map':payload,'output_dir':out}

def summary(result, threshold):
    pred,score=result['prediction'],result['score']
    valid=pred!=255; confident=valid&(score>=threshold)
    pixel_area=result['scene']['pixel_area']/1e6
    return {'source_file':result['scene']['name'],'model':'baseline_v1','score_threshold':threshold,
            'predicted_plume_class_km2':float(((pred==1)&confident).sum()*pixel_area),
            'predicted_background_class_km2':float(((pred==0)&confident).sum()*pixel_area),
            'uncertain_km2':float((valid&~confident).sum()*pixel_area),
            'analysed_km2':float(valid.sum()*pixel_area),
            'excluded_km2':float((~valid).sum()*pixel_area),
            'valid_pixels':int(valid.sum()),'warning':WARNING}

def make_download(result, threshold):
    """Raw labels + scores remain unchanged; CSV states the display threshold."""
    out=result['output_dir']; report=summary(result,threshold)
    with (out/'summary.csv').open('w',newline='') as stream:
        writer=csv.writer(stream); writer.writerow(['metric','value']); writer.writerows(report.items())
    (out/'metadata.json').write_text(json.dumps(report,indent=2)+'\n')
    archive=out/'plumewatch_results.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name in ['classification.tif','model_score.tif','summary.csv','metadata.json']: z.write(out/name,name)
    return archive
