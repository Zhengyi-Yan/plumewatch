"""Fixed RBF SVM fit using all reviewed frames; no independent accuracy claim."""
import argparse
import hashlib
import json
import pickle
import time
from pathlib import Path
import numpy as np
import rasterio
import sklearn
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

ROOT = Path(__file__).resolve().parent
BANDS = ['B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B11', 'B12']

def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def train(root, out):
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'model.pkl').exists():
        raise FileExistsError('Refusing to overwrite an existing SVM.')
    previous = root / 'results/multiclass_rf_v2_20260930'
    records = json.loads((previous / 'manifest.json').read_text())
    groups = json.loads((previous / 'groups.json').read_text())
    protocol = json.loads((root / 'experiments/unet/outputs/expanded_all_data_20260930/protocol.json').read_text())
    cache = root / 'data/processed/multiclass_rf_v2_20260930/samples.pkl'
    if file_hash(cache) != protocol['samples_sha256']:
        raise ValueError('Reviewed sample cache changed: regenerate/verify before training.')
    samples = pickle.loads(cache.read_bytes())
    if len(records) != 49 or len(samples) != len(records) or len(groups) != len(records):
        raise ValueError('Expected all 49 reviewed frames.')
    rng = np.random.default_rng(42)
    xs, ys, frame_counts = [], [], {}
    # Bounded exact-kernel fit: 300 pixels per group/class, spread across every eligible frame.
    for group in sorted({g['group'] for g in groups}):
        members = [i for i, g in enumerate(groups) if g['group'] == group]
        for cls in [0, 1, 3]:
            eligible = [i for i in members if (samples[i][1] == cls).any()]
            for index in eligible:
                features = samples[index][0][samples[index][1] == cls]
                count = min(len(features), max(1, 300 // len(eligible)))
                ids = rng.choice(len(features), count, replace=False)
                xs.append(features[ids]);ys.append(np.full(count, cls, dtype='uint8'))
                frame_counts[index] = frame_counts.get(index, 0) + count
    for i, record in enumerate(records):
        if Path(record['png']).name != Path(groups[i]['png']).name or i not in frame_counts:
            raise ValueError('Frame missing or metadata mismatch.')
        path = Path(record['mask_path'])
        if file_hash(path) != protocol['mask_sha256'][str(path)]:
            raise ValueError('Reviewed mask changed: ' + str(path))
        with rasterio.open(path) as src:
            mask = src.read(1)
        if not set(np.unique(mask)).issubset({0, 1, 3, 255}):
            raise ValueError('Unsupported reviewed class.')
        if {str(c): int((mask == c).sum()) for c in [0, 1, 3]} != samples[i][4]:
            raise ValueError('Mask/cache support mismatch.')
    x = np.concatenate(xs);y = np.concatenate(ys)
    if not np.isfinite(x).all() or (x == -9999).any() or set(y) != {0, 1, 3}:
        raise ValueError('Invalid training samples.')
    model = Pipeline([('scale', StandardScaler()), ('svc', SVC(
        kernel='rbf', C=1.0, gamma='scale', class_weight='balanced',
        probability=True, random_state=42, cache_size=512))])
    started = time.perf_counter();model.fit(x, y);elapsed = time.perf_counter() - started
    probe = np.concatenate([s[2][:200] for s in samples])
    started = time.perf_counter();pred = model.predict(probe);probs = model.predict_proba(probe)
    probe_seconds = time.perf_counter() - started
    if not np.isfinite(probs).all() or not np.allclose(probs.sum(1), 1) or set(pred) - {0, 1, 3}:
        raise ValueError('Invalid fitted inference.')
    assert np.allclose(model['scale'].mean_, x.mean(axis=0, dtype='float64'), atol=1e-8)
    report = dict(model='svm_rbf_20261001', bands=BANDS, classes=[0,1,3], seed=42,
        frames=len(records), groups=len({g['group'] for g in groups}), train_samples=len(y),
        sampling='Up to 300 pixels/group/class, divided across every eligible frame; all reviewed frames contribute. Not every labelled pixel.',
        frame_samples={records[i]['png']:n for i,n in frame_counts.items()},
        class_counts={str(c):int((y==c).sum()) for c in [0,1,3]},
        kernel='rbf', C=1.0, gamma_setting='scale', fitted_gamma=float(model['svc']._gamma),
        class_weight='balanced', probability=True, score='Platt score for native SVC.predict class; not externally calibrated. Internal calibration uses training samples only.',
        scaler_mean=model['scale'].mean_.tolist(), scaler_scale=model['scale'].scale_.tolist(),
        support_vectors=len(model['svc'].support_vectors_), fit_seconds=elapsed,
        benchmark_pixels=len(probe), benchmark_predict_and_score_seconds=probe_seconds,
        estimated_4m_pixel_seconds=probe_seconds/len(probe)*4_000_000,
        native_predict_probability_argmax_disagreements=int((pred != model.classes_[probs.argmax(1)]).sum()),
        sklearn_version=sklearn.__version__, samples_sha256=file_hash(cache),
        annotation_zip_sha256=protocol['input_zip_sha256'],
        accuracy='Not independently evaluated: this is an all-reviewed-data final fit.')
    for name, digest in protocol['input_zip_sha256'].items():
        if file_hash(root/'data/processed'/name) != digest:
            raise ValueError('Reviewed ZIP changed: ' + name)
    bundle=dict(model=model, bands=BANDS, classes=[0,1,3], sklearn_version=sklearn.__version__,
                model_id='svm_rbf_20261001', protocol=report)
    path=out/'model.pkl';path.write_bytes(pickle.dumps(bundle))
    restored=pickle.loads(path.read_bytes())['model']
    assert np.array_equal(pred,restored.predict(probe))
    assert np.allclose(probs,restored.predict_proba(probe),atol=1e-12)
    report['model_sha256']=file_hash(path)
    (out/'protocol.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2),flush=True)

if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--out',type=Path);args=parser.parse_args()
    train(args.root,args.out or args.root/'data/processed/svm_rbf_20261001')
