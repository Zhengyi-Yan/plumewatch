"""Train the three-class Sentinel-2 baseline with site/event-held-out evaluation.

Run after converting CVAT exports with annotation_pipeline.py. The PNGs are
annotation aids only; features come from the ten original reflectance bands.
"""

import hashlib
import json
import pickle
from pathlib import Path

import numpy as np
import rasterio
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import confusion_matrix

from annotation_pipeline import CLASSES, MANIFEST, ROOT, check_source
from processing import BANDS, validate

MASK_DIR = ROOT / 'data/processed/cvat_masks_v1'
MODEL_DIR = ROOT / 'data/processed/multiclass_rf_v1'
REPORT_DIR = ROOT / 'results/multiclass_rf_v1'
CLASS_IDS = [CLASSES[name] for name in ('normal_water', 'plume', 'land')]
SEED = 42
TRAIN_PER_SCENE_CLASS = 3000
TRAIN_PER_GROUP_CLASS = 10000
EVAL_PER_SCENE = 15000


def mask_path(record):
    return MASK_DIR / (Path(record['png']).stem + '_mask.tif')


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def groups_for(records):
    """Join scenes sharing a site, event, acquisition, or actual map footprint."""
    parent = list(range(len(records)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def bounds(r):
        a, _, x, _, e, y = r['transform']
        return x, y + e * r['height'], x + a * r['width'], y

    for i, left in enumerate(records):
        for j in range(i):
            right = records[j]
            linked = any(left[k] == right[k] for k in ('site', 'event_group', 'acquisition'))
            if left['crs'] == right['crs']:
                lx0, ly0, lx1, ly1 = bounds(left)
                rx0, ry0, rx1, ry1 = bounds(right)
                linked |= min(lx1, rx1) > max(lx0, rx0) and min(ly1, ry1) > max(ly0, ry0)
            if linked:
                parent[root(i)] = root(j)
    roots = {root(i) for i in range(len(records))}
    order = {value: n for n, value in enumerate(sorted(roots), 1)}
    return [f'group_{order[root(i)]:02d}' for i in range(len(records))]


def sample_scene(record):
    path = mask_path(record)
    seed = int.from_bytes(hashlib.sha256(record['png'].encode()).digest()[:8], 'big') ^ SEED
    rng = np.random.default_rng(seed)
    with rasterio.open(ROOT / record['source_tif']) as src, rasterio.open(path) as mask_src:
        check_source(src, record)
        validate(src)
        if (src.crs, src.transform, src.shape) != (mask_src.crs, mask_src.transform, mask_src.shape):
            raise ValueError('Mask/source grid mismatch: ' + path.name)
        mask = mask_src.read(1).ravel()
        if not set(np.unique(mask)).issubset({*CLASS_IDS, 255}):
            raise ValueError('Unexpected class in ' + path.name)
        train_ids = []
        for cls in CLASS_IDS:
            ids = np.flatnonzero(mask == cls)
            if len(ids):
                train_ids.append(rng.choice(ids, min(len(ids), TRAIN_PER_SCENE_CLASS), replace=False))
        if not train_ids:
            raise ValueError('No labelled pixels in ' + path.name)
        train_ids = np.concatenate(train_ids)
        labelled = np.flatnonzero(mask != 255)
        eval_ids = rng.choice(labelled, min(len(labelled), EVAL_PER_SCENE), replace=False)
        pixels = np.unique(np.concatenate((train_ids, eval_ids)))
        data = src.read().reshape(src.count, -1)[:, pixels].T
        chosen = data[:, :10]
        valid = (data[:, 11] == 1) & np.isfinite(chosen).all(axis=1)
        valid &= (chosen != -9999).all(axis=1) & np.isin(data[:, 10], [2, 4, 5, 6, 7])
        if not valid.all() or np.percentile(chosen, 99) > 2:
            raise ValueError('Invalid reflectance under labelled mask: ' + path.name)
        x_train = chosen[np.searchsorted(pixels, train_ids)].astype('float32')
        x_eval = chosen[np.searchsorted(pixels, eval_ids)].astype('float32')
        return (x_train, mask[train_ids].copy(), x_eval, mask[eval_ids].copy(),
                {str(cls): int((mask == cls).sum()) for cls in CLASS_IDS})


def training_set(samples, group_ids, included, rng):
    x_parts, y_parts = [], []
    for group in sorted(set(group_ids[i] for i in included)):
        indices = [i for i in included if group_ids[i] == group]
        for cls in CLASS_IDS:
            features = [samples[i][0][samples[i][1] == cls] for i in indices]
            features = [part for part in features if len(part)]
            if features:
                values = np.concatenate(features)
                keep = rng.choice(len(values), min(len(values), TRAIN_PER_GROUP_CLASS), replace=False)
                x_parts.append(values[keep])
                y_parts.append(np.full(len(keep), cls, dtype='uint8'))
    x, y = np.concatenate(x_parts), np.concatenate(y_parts)
    if set(y) != set(CLASS_IDS):
        raise ValueError('Training fold lacks one of the three classes')
    return x, y


def make_model():
    return RandomForestClassifier(n_estimators=120, min_samples_leaf=20,
                                  class_weight='balanced_subsample', random_state=SEED,
                                  n_jobs=4)


def scores(matrix):
    support = matrix.sum(axis=1)
    per_class = {}
    for i, name in enumerate(('normal_water', 'plume', 'land')):
        tp = int(matrix[i, i])
        predicted = int(matrix[:, i].sum())
        actual = int(support[i])
        precision = tp / predicted if predicted else 0.0
        recall = tp / actual if actual else 0.0
        per_class[name] = {'support': actual, 'precision': precision, 'recall': recall,
                           'f1': 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
                           'iou': tp / (actual + predicted - tp) if actual + predicted > tp else 0.0}
    present = [v['f1'] for v in per_class.values() if v['support']]
    return {'accuracy': float(np.trace(matrix) / matrix.sum()),
            'macro_f1_present_classes': float(np.mean(present)), 'classes': per_class,
            'confusion_matrix': matrix.tolist()}


def main():
    manifest = json.loads(MANIFEST.read_text())
    records = [r for r in manifest if mask_path(r).exists()]
    if not records:
        raise ValueError('No converted CVAT masks found; run annotation_pipeline.py masks first')
    groups = groups_for(records)
    if len(set(groups)) < 3:
        raise ValueError('Need at least three independent site/event groups')
    samples = [sample_scene(r) for r in records]
    folds, total = [], np.zeros((3, 3), dtype='int64')
    for held_out in sorted(set(groups)):
        train_indices = [i for i, group in enumerate(groups) if group != held_out]
        test_indices = [i for i, group in enumerate(groups) if group == held_out]
        x, y = training_set(samples, groups, train_indices, np.random.default_rng(SEED))
        model = make_model().fit(x, y)
        scene_results = []
        fold_matrix = np.zeros((3, 3), dtype='int64')
        for i in test_indices:
            predicted = model.predict(samples[i][2])
            matrix = confusion_matrix(samples[i][3], predicted, labels=CLASS_IDS)
            fold_matrix += matrix
            scene_results.append({'png': Path(records[i]['png']).name,
                                  'labelled_pixel_counts': samples[i][4], **scores(matrix)})
        total += fold_matrix
        folds.append({'held_out_group': held_out, 'sites': sorted({records[i]['site'] for i in test_indices}),
                      'events': sorted({records[i]['event_group'] for i in test_indices}),
                      'scenes': scene_results, 'train_sample_count': len(y), **scores(fold_matrix)})
        print(held_out, 'scenes', len(test_indices), 'plume F1', round(folds[-1]['classes']['plume']['f1'], 3))

    x, y = training_set(samples, groups, list(range(len(records))), np.random.default_rng(SEED))
    final_model = make_model().fit(x, y)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    with (MODEL_DIR / 'model.pkl').open('wb') as stream:
        pickle.dump({'model': final_model, 'bands': BANDS[:10], 'classes': CLASS_IDS,
                     'sklearn_version': sklearn.__version__, 'processing': 'S2_SR_HARMONIZED_SCL_v1'}, stream)
    scene_plume_f1 = [s['classes']['plume']['f1'] for fold in folds for s in fold['scenes']]
    inputs = [MANIFEST, *sorted((ROOT / 'data/raw').glob('dataset_task_*.zip'))]
    inputs += [mask_path(r) for r in records]
    inputs += [ROOT / r['source_tif'] for r in records]
    report = {'method': 'leave-one-linked-site-event-group-out', 'class_ids': dict(CLASSES),
              'evaluated_class_ids': CLASS_IDS, 'bands': BANDS[:10], 'product': 'COPERNICUS/S2_SR_HARMONIZED',
              'seed': SEED, 'train_per_scene_class': TRAIN_PER_SCENE_CLASS,
              'train_per_group_class': TRAIN_PER_GROUP_CLASS, 'eval_per_scene': EVAL_PER_SCENE,
              'model_parameters': final_model.get_params(), 'sklearn_version': sklearn.__version__,
              'annotated_scenes': len(records), 'groups': len(set(groups)),
              'final_train_sample_count': len(y), 'overall_scene_balanced_sample': scores(total),
              'per_scene_plume_f1': {'median': float(np.median(scene_plume_f1)),
                                     'minimum': float(min(scene_plume_f1)),
                                     'scenes_below_0_7': sum(value < 0.7 for value in scene_plume_f1)},
              'folds': folds, 'excluded_unannotated': [r['png'] for r in manifest if r not in records],
              'input_sha256': {str(p.relative_to(ROOT)): file_hash(p) for p in inputs},
              'limitations': ['Labels are visual interpretations, not measured sediment or water quality.',
                              'Only four linked geographic/event groups; these scores are exploratory.',
                              'Evaluation samples pixels uniformly within each labelled scene, not whole-scene area.',
                              'Neighbouring pixels are correlated; sample counts are not independent observations.',
                              'No shallow-water class was annotated; it may be confused with plume.',
                              'RF probabilities are not calibrated and provide no area margin of error.']}
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / 'metrics.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Overall plume F1', round(report['overall_scene_balanced_sample']['classes']['plume']['f1'], 3))
    print('Report:', REPORT_DIR / 'metrics.json')
    print('Final model:', MODEL_DIR / 'model.pkl')


if __name__ == '__main__':
    main()
