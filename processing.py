"""Validated Sentinel-2 scenes, two-model inference, previews, and exports."""
import base64
import csv
import io
import json
import pickle
import subprocess
import zipfile
from functools import lru_cache
from pathlib import Path
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT
from rasterio.warp import calculate_default_transform, transform_bounds, reproject
from rasterio.windows import Window
from PIL import Image
import numpy as np
import rasterio
from scipy.ndimage import gaussian_filter

ROOT = Path(__file__).resolve().parent
SVM_MODEL = ROOT / 'data/processed/svm_rbf_20261001/model.pkl'
RF_MODEL = ROOT / 'data/processed/multiclass_rf_v2_20260930/model.pkl'
UNET_MODEL = ROOT / 'experiments/unet/outputs/expanded_all_data_20260930/model.pt'
UNET_PYTHON = ROOT / 'experiments/unet/.venv/bin/python'
EXAMPLE = ROOT / 'hutt-test/hutt_20210723_full_scene_v1.tif'
BANDS = ['B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B11', 'B12', 'SCL', 'valid']
CLASSES = {0: 'normal water', 1: 'visible plume', 3: 'land'}
MAX_BYTES = 250 * 1024 * 1024
MAX_PIXELS = 10_000_000
WARNING = ('Candidate visible-plume classes require human review. Model scores are not calibrated '
           'probabilities. Class footprints are estimates, not measured sediment or verified plume boundaries.')


def validate(src):
    if src.driver != 'GTiff' or src.count != 12 or list(src.descriptions) != BANDS:
        raise ValueError('Use a PlumeWatch 12-band GEE scene GeoTIFF: ten reflectance bands, SCL, valid.')
    if not src.crs or not src.crs.is_projected or src.crs.linear_units != 'metre':
        raise ValueError('The scene must use a projected CRS in metres.')
    if src.width * src.height > MAX_PIXELS:
        raise ValueError('Scene exceeds 10 million pixels. Export a smaller region or one tile.')
    if not np.allclose((src.transform.a, src.transform.e), (10, -10), atol=.01) or src.transform.b or src.transform.d:
        raise ValueError('Use a north-up 10 m grid from the GEE export.')
    if not all(dtype.startswith('float') for dtype in src.dtypes[:10]):
        raise ValueError('Use scaled floating-point reflectance, not raw Sentinel integers.')


def usable(data):
    spectra = data[:10]
    good = (data[11] == 1) & np.isfinite(spectra).all(axis=0) & (spectra != -9999).all(axis=0)
    good &= np.isin(data[10], [2, 4, 5, 6, 7])
    if good.any() and np.percentile(spectra[:, good], 99) > 2:
        raise ValueError('Reflectance appears unscaled. Re-export with the supplied GEE script.')
    return good


def image_url(array):
    stream = io.BytesIO()
    Image.fromarray(array).save(stream, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode()


def prepare_scene(path):
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('Maximum upload size is 250 MB.')
    with rasterio.open(path) as src:
        validate(src)
        transform, width, height = calculate_default_transform(src.crs, 'EPSG:3857', src.width, src.height, *src.bounds)
        factor = max(width, height) / 1100
        if factor > 1:
            old_w, old_h = width, height
            width, height = max(1, round(width / factor)), max(1, round(height / factor))
            transform = transform * rasterio.Affine.scale(old_w / width, old_h / height)
        with WarpedVRT(src, crs='EPSG:3857', transform=transform, width=width, height=height,
                       resampling=Resampling.nearest, nodata=-9999) as vrt:
            data = vrt.read()
        good = usable(data)
        rgb = np.moveaxis(data[[2, 1, 0]], 0, -1)
        rgb = (np.clip(np.nan_to_num(rgb) / .25, 0, 1) ** (1 / 1.2) * 255).astype('uint8')
        rgba = np.concatenate([rgb, (good * 255).astype('uint8')[..., None]], axis=2)
        bounds_m = rasterio.transform.array_bounds(height, width, transform)
        west, south, east, north = transform_bounds('EPSG:3857', 'EPSG:4326', *bounds_m)
        return {'path': str(path), 'name': path.name, 'width': src.width, 'height': src.height,
                'crs': str(src.crs), 'pixel_area': abs(src.transform.a * src.transform.e),
                'grid': (transform, width, height),
                'source_tags': src.tags(),
                'map': {'rgb': image_url(rgba), 'bounds': [[south, west], [north, east]],
                        'width': width, 'height': height, 'projectedBounds': list(bounds_m)}}


@lru_cache(maxsize=1)
def load_rf_model():
    # Only the repository's trusted checkpoint is unpickled; uploads are always GeoTIFFs.
    with RF_MODEL.open('rb') as stream:
        bundle = pickle.load(stream)
    import sklearn
    if bundle['sklearn_version'] != sklearn.__version__:
        raise ValueError(f"RF needs scikit-learn {bundle['sklearn_version']}; installed {sklearn.__version__}.")
    if bundle['bands'] != BANDS[:10] or list(bundle['model'].classes_) != [0, 1, 3]:
        raise ValueError('RF checkpoint band order or classes do not match the dashboard.')
    bundle['model'].n_jobs = 1
    return bundle['model']


def _write_rasters(src, out, pred, score, model_id, plume_score):
    out.mkdir(parents=True, exist_ok=True)
    profile = src.profile.copy()
    for name, data, dtype, nodata, band in [
        ('classification.tif', pred, 'uint8', 255, 'class_id'),
        ('model_score.tif', score, 'float32', -9999, 'predicted_class_score' if model_id.startswith('svm_') else 'winning_class_score'),
        ('plume_score.tif', plume_score, 'float32', -9999, 'plume_class_score')]:
        profile.update(count=1, dtype=dtype, nodata=nodata, compress='deflate')
        with rasterio.open(out / name, 'w', **profile) as dst:
            dst.write(data, 1)
            dst.set_band_description(1, band)
            dst.update_tags(model=model_id, classes='0=normal_water;1=visible_plume;3=land;255=excluded',
                            warning=WARNING)


def smooth_plume_preview(scores, classes, sigma=2):
    """Display-only Gaussian smoothing on the native 10 m grid; preserve land/NoData."""
    water = (classes == 0) | (classes == 1)
    weights = gaussian_filter(water.astype('float32'), sigma=sigma, mode='constant')
    total = gaussian_filter(np.where(water, scores, 0), sigma=sigma, mode='constant')
    smoothed = scores.copy()
    np.divide(total, weights, out=smoothed, where=water & (weights > 0))
    return smoothed


def _result(scene, out, model_id):
    with rasterio.open(scene['path']) as src, rasterio.open(out / 'classification.tif') as labels, \
            rasterio.open(out / 'model_score.tif') as scores:
        validate(src)
        if (labels.crs, labels.transform, labels.shape) != (src.crs, src.transform, src.shape) or \
                (scores.crs, scores.transform, scores.shape) != (src.crs, src.transform, src.shape):
            raise ValueError(f'{model_id} output grid differs from the source scene.')
        pred, score = labels.read(1), scores.read(1)
        checkpoint_id = labels.tags().get('model')
        with rasterio.open(out / 'plume_score.tif') as plume:
            if (plume.crs, plume.transform, plume.shape) != (src.crs, src.transform, src.shape):
                raise ValueError('Plume score grid differs from the source.')
            plume_score = plume.read(1)
        if not np.array_equal(pred == 255, plume_score == -9999):
            raise ValueError('Plume score NoData differs from classification.')
        if not set(np.unique(pred)).issubset({0, 1, 3, 255}):
            raise ValueError(f'{model_id} produced an unsupported class ID.')
        if not np.array_equal(pred == 255, score == -9999):
            raise ValueError(f'{model_id} class and score NoData disagree.')
        transform, width, height = scene['grid']
        display_pred = np.full((height, width), 255, dtype='uint8')
        display_score = np.zeros((height, width), dtype='float32')
        display_plume = np.zeros((height, width), dtype='float32')
        for source, dest, nodata in [(pred, display_pred, 255), (score, display_score, -9999), (plume_score, display_plume, -9999)]:
            reproject(source, dest, src_transform=src.transform, src_crs=src.crs, src_nodata=nodata,
                      dst_transform=transform, dst_crs='EPSG:3857', dst_nodata=nodata,
                      resampling=Resampling.nearest)
        smoothed_previews = {}
        for strength, sigma in [('light', 2), ('medium', 5), ('strong', 10)]:
            display_smooth = np.zeros((height, width), dtype='float32')
            reproject(smooth_plume_preview(plume_score, pred, sigma), display_smooth,
                      src_transform=src.transform, src_crs=src.crs, src_nodata=-9999,
                      dst_transform=transform, dst_crs='EPSG:3857', dst_nodata=-9999,
                      resampling=Resampling.nearest)
            smoothed_previews[strength] = base64.b64encode(
                np.clip(display_smooth * 100, 0, 100).astype('uint8').tobytes()).decode()
    payload = dict(scene['map'])
    payload['classes'] = base64.b64encode(display_pred.tobytes()).decode()
    payload['scores'] = base64.b64encode(np.clip(display_score * 100, 0, 100).astype('uint8').tobytes()).decode()
    payload['plumeScores'] = base64.b64encode(np.clip(display_plume * 100, 0, 100).astype('uint8').tobytes()).decode()
    payload['smoothedPlumeScores'] = smoothed_previews
    payload['modelId'] = checkpoint_id
    payload['excludedKm2'] = float((pred == 255).sum() * scene['pixel_area'] / 1e6)
    return {'model': model_id, 'plume_score': plume_score, 'scene': scene, 'prediction': pred, 'score': score,
            'map': payload, 'output_dir': out}


def classify_rf(scene, output_dir):
    model = load_rf_model()
    out = Path(output_dir)
    with rasterio.open(scene['path']) as src:
        validate(src)
        pred = np.full(src.shape, 255, dtype='uint8')
        score = np.full(src.shape, -9999, dtype='float32')
        plume_score = np.full(src.shape, -9999, dtype='float32')
        for y in range(0, src.height, 128):
            window = Window(0, y, src.width, min(128, src.height - y))
            data = src.read(window=window)
            good = usable(data)
            if not good.any():
                continue
            probs = model.predict_proba(data[:10, good].T)
            plume_score[y:y + int(window.height)][good] = probs[:, list(model.classes_).index(1)]
            pred[y:y + int(window.height)][good] = model.classes_[probs.argmax(axis=1)]
            score[y:y + int(window.height)][good] = probs.max(axis=1)
        if not (pred != 255).any():
            raise ValueError('No usable pixels remain after quality screening.')
        _write_rasters(src, out, pred, score, 'rf_v2_20260930', plume_score)
    return _result(scene, out, 'rf')


@lru_cache(maxsize=1)
def load_svm_model():
    # Load only the fixed local trained checkpoint; never accept uploaded models.
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import SVC
    import sklearn
    with SVM_MODEL.open('rb') as stream:
        bundle = pickle.load(stream)
    model = bundle['model']
    if bundle['sklearn_version'] != sklearn.__version__:
        raise ValueError('SVM scikit-learn version differs from its training environment.')
    if (bundle['bands'] != BANDS[:10] or bundle['classes'] != [0, 1, 3]
            or not isinstance(model, Pipeline) or list(model.named_steps) != ['scale', 'svc']
            or not isinstance(model['scale'], StandardScaler) or not isinstance(model['svc'], SVC)
            or model['svc'].kernel != 'rbf' or not model['svc'].probability
            or model['svc'].C != 1.0 or model['svc'].gamma != 'scale'
            or model['svc'].class_weight != 'balanced' or model['svc'].random_state != 42
            or bundle['model_id'] != 'svm_rbf_20261001'
            or model.n_features_in_ != 10 or list(model.classes_) != [0, 1, 3]
            or not np.isfinite(model['scale'].mean_).all()
            or not (model['scale'].scale_ > 0).all()):
        raise ValueError('SVM checkpoint/scaler/classes do not match the dashboard.')
    return model


def classify_svm(scene, output_dir):
    model = load_svm_model()
    out = Path(output_dir)
    with rasterio.open(scene['path']) as src:
        validate(src)
        pred = np.full(src.shape, 255, dtype='uint8')
        score = np.full(src.shape, -9999, dtype='float32')
        plume_score = np.full(src.shape, -9999, dtype='float32')
        for y in range(0, src.height, 16):
            window = Window(0, y, src.width, min(16, src.height - y))
            data = src.read(window=window)
            good = usable(data)
            if not good.any():
                continue
            probs = model.predict_proba(data[:10, good].T)
            plume_score[y:y + int(window.height)][good] = probs[:, list(model.classes_).index(1)]
            labels = model.predict(data[:10, good].T)
            pred[y:y + int(window.height)][good] = labels
            columns = np.searchsorted(model.classes_, labels)
            score[y:y + int(window.height)][good] = probs[np.arange(len(labels)), columns]
        if not (pred != 255).any():
            raise ValueError('No usable pixels remain after quality screening.')
        _write_rasters(src, out, pred, score, 'svm_rbf_20261001', plume_score)
    return _result(scene, out, 'svm')


def classify_unet(scene, output_dir):
    if not UNET_PYTHON.is_file() or not UNET_MODEL.is_file():
        raise FileNotFoundError('U-Net Python environment or final model checkpoint is missing.')
    out = Path(output_dir)
    process = subprocess.run([str(UNET_PYTHON), str(ROOT / 'unet_worker.py'), scene['path'], str(out)],
                             cwd=ROOT, capture_output=True, text=True)
    if process.returncode:
        raise RuntimeError('U-Net inference failed: ' + (process.stderr.strip() or process.stdout.strip())[-1200:])
    return _result(scene, out, 'unet')


def summary(result, threshold):
    pred, score = result['prediction'], result['score']
    valid = pred != 255
    confident = valid & (score >= threshold)
    area = result['scene']['pixel_area'] / 1e6
    return {'source_file': result['scene']['name'], 'model': result['model'], 'score_threshold': threshold,
            'visible_plume_km2': float(((pred == 1) & confident).sum() * area),
            'normal_water_km2': float(((pred == 0) & confident).sum() * area),
            'land_km2': float(((pred == 3) & confident).sum() * area),
            'uncertain_km2': float((valid & ~confident).sum() * area),
            'analysed_km2': float(valid.sum() * area), 'excluded_km2': float((~valid).sum() * area),
            'valid_pixels': int(valid.sum()), 'warning': WARNING}


def disagreement_km2(rf, unet):
    a, b = rf['prediction'], unet['prediction']
    if a.shape != b.shape or rf['scene']['pixel_area'] != unet['scene']['pixel_area']:
        raise ValueError('Cannot compare results on different grids.')
    return float(((a != 255) & (b != 255) & (a != b)).sum() * rf['scene']['pixel_area'] / 1e6)


def make_download(result, threshold):
    out = result['output_dir']
    report = summary(result, threshold)
    report.update(model_id=result['map']['modelId'], bands=BANDS[:10],
                  source_crs=result['scene']['crs'], source_tags=result['scene']['source_tags'],
                  plume_score_definition='Uncalibrated score for class 1, independent of predicted class.')
    if result['model'] == 'svm':
        report.update(model_id='svm_rbf_20261001', kernel='rbf', scaling='saved StandardScaler',
                      score_definition='score for native SVC.predict class; not externally calibrated',
                      accuracy='all-data model; not independently evaluated')
    with (out / 'summary.csv').open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['metric', 'value'])
        writer.writerows(report.items())
    (out / 'metadata.json').write_text(json.dumps(report, indent=2) + '\n')
    archive = out / f"plumewatch_{result['model']}_results.zip"
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as zip_file:
        for name in ['classification.tif', 'model_score.tif', 'plume_score.tif', 'summary.csv', 'metadata.json']:
            zip_file.write(out / name, name)
    return archive
