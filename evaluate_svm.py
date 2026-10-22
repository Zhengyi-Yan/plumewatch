"""Evaluate the fixed dashboard SVM recipe on the saved RF/U-Net group folds."""
import argparse
import csv
import json
import pickle
import time
from pathlib import Path
import numpy as np
import sklearn
from sklearn.metrics import confusion_matrix
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from train_multiclass import scores
from train_svm import ROOT, file_hash


def training_samples(samples, groups, included):
    # Match train_svm.py's bounded per-group/class sampling, excluding the test group.
    rng = np.random.default_rng(42)
    xs, ys = [], []
    for group in sorted({groups[i] for i in included}):
        members = [i for i in included if groups[i] == group]
        for cls in [0, 1, 3]:
            eligible = [i for i in members if (samples[i][1] == cls).any()]
            for i in eligible:
                features = samples[i][0][samples[i][1] == cls]
                count = min(len(features), max(1, 300 // len(eligible)))
                xs.append(features[rng.choice(len(features), count, replace=False)])
                ys.append(np.full(count, cls, dtype='uint8'))
    return np.concatenate(xs), np.concatenate(ys)


def evaluate(root, reference, out):
    records = json.loads((root/'results/multiclass_rf_v2_20260930/manifest.json').read_text())
    group_records = json.loads((root/'results/multiclass_rf_v2_20260930/groups.json').read_text())
    groups = [g['group'] for g in group_records]
    protocol = json.loads((root/'data/processed/svm_rbf_20261001/protocol.json').read_text())
    unet_protocol = json.loads((reference/'protocol.json').read_text())
    cache = root/'data/processed/multiclass_rf_v2_20260930/samples.pkl'
    assert file_hash(cache) == protocol['samples_sha256'] == unet_protocol['samples_sha256']
    assert group_records == unet_protocol['groups']
    samples = pickle.loads(cache.read_bytes())
    model_path = root/'data/processed/svm_rbf_20261001/model.pkl'
    model_digest = file_hash(model_path)
    assert model_digest == protocol['model_sha256']
    assert len(records) == len(samples) == len(groups) == 49 and len(set(groups)) == 13
    for i, record in enumerate(records):
        assert Path(record['png']).name == Path(group_records[i]['png']).name
        assert file_hash(record['mask_path']) == unet_protocol['mask_sha256'][record['mask_path']]
        assert np.isfinite(samples[i][0]).all() and np.isfinite(samples[i][2]).all()
        assert set(samples[i][1]) <= {0, 1, 3} and set(samples[i][3]) <= {0, 1, 3}
        with np.load(reference/'sample_predictions'/(Path(record['png']).stem+'.npz')) as saved:
            assert np.array_equal(saved['truth'], samples[i][3])
    # Check that the sampler reproduces the final model's training-only scaler.
    x, y = training_samples(samples, groups, list(range(len(samples))))
    final = pickle.loads(model_path.read_bytes())['model']
    assert len(y) == protocol['train_samples']
    assert np.allclose(x.mean(0, dtype='float64'), final['scale'].mean_, atol=1e-10)
    assert np.allclose(x.std(0, dtype='float64'), final['scale'].scale_, atol=1e-10)
    del final, x, y
    out.mkdir(parents=True, exist_ok=False)
    (out/'predictions').mkdir()
    folds, scenes = [], []
    started = time.perf_counter()
    for held in sorted(set(groups)):
        train = [i for i,g in enumerate(groups) if g != held]
        test = [i for i,g in enumerate(groups) if g == held]
        assert set(train).isdisjoint(test) and all(groups[i] != held for i in train)
        x, y = training_samples(samples, groups, train)
        model = Pipeline([('scale', StandardScaler()), ('svc', SVC(kernel='rbf', C=1,
            gamma='scale', class_weight='balanced', probability=True, random_state=42, cache_size=512))])
        tick = time.perf_counter(); model.fit(x,y)
        assert np.allclose(model['scale'].mean_, x.mean(0,dtype='float64'), atol=1e-10)
        rows = []
        for i in test:
            truth = samples[i][3]; predicted = model.predict(samples[i][2])
            name = Path(records[i]['png']).name
            row = dict(png=name, group=held, site=records[i]['site'], date=records[i]['date'],
                       svm=scores(confusion_matrix(truth,predicted,labels=[0,1,3])))
            np.savez_compressed(out/'predictions'/(Path(name).stem+'.npz'),truth=truth,predicted=predicted)
            rows.append(row)
        fold = dict(group=held,train_frames=[Path(records[i]['png']).name for i in train],
                    test_frames=[Path(records[i]['png']).name for i in test],train_samples=len(y),
                    seconds=time.perf_counter()-tick,scenes=rows)
        (out/(held+'.json')).write_text(json.dumps(fold,indent=2)+'\n')
        folds.append(fold); scenes.extend(rows)
        print(f'{held}: {len(test)} held-out frames completed ({fold["seconds"]:.1f}s)',flush=True)
    matrix = sum((np.array(r['svm']['confusion_matrix']) for r in scenes),np.zeros((3,3),dtype='int64'))
    assert len(scenes)==49 and len({r['png'] for r in scenes})==49 and matrix.sum()==735000
    comparators = json.loads((reference/'metrics.json').read_text())['summary']['all']
    for key in ['unet','expanded_rf']:
        assert np.array_equal(matrix.sum(1),np.array(comparators[key]['confusion_matrix']).sum(1))
    # Rebuild the confusion matrix from the persisted predictions as an independent output check.
    rebuilt = np.zeros((3,3),dtype='int64')
    for row in scenes:
        with np.load(out/'predictions'/(Path(row['png']).stem+'.npz')) as a:
            rebuilt += confusion_matrix(a['truth'],a['predicted'],labels=[0,1,3])
    assert np.array_equal(matrix,rebuilt) and file_hash(model_path)==model_digest
    summary = scores(matrix)
    report = dict(method='Leave one linked site/event group out; matching RF/U-Net reference pixels',
        seed=42,frames=49,groups=13,evaluation_pixels=int(matrix.sum()),sklearn_version=sklearn.__version__,
        sampling=protocol['sampling'],parameters=dict(kernel='rbf',C=1,gamma='scale',class_weight='balanced',probability=True),
        samples_sha256=file_hash(cache),reference_metrics_sha256=file_hash(reference/'metrics.json'),
        deployed_model_sha256=model_digest,deployed_model_unchanged=True,summary=summary,folds=folds,
        verification=dict(matched_truth=True,matched_class_support=True,mask_hashes_verified=True,
                          fold_exclusions_verified=True,training_only_scaler_verified=True,persisted_predictions_verified=True),
        elapsed_seconds=time.perf_counter()-started,
        limitations=['Exploratory group cross-validation of the training recipe, not an independent test of the final all-data checkpoint.',
                     'Previously inspected development labels; no untouched external validation.',
                     'Only sampled valid reviewed pixels are scored; ignored pixels and unreviewed candidates are excluded.',
                     'One seed and fixed hyperparameters; label uncertainty and geographic domain shift remain.',
                     'Overall accuracy covers water, plume and land; precision/recall/F1 below refer to plume.'])
    (out/'metrics.json').write_text(json.dumps(report,indent=2)+'\n')
    with (out/'per_scene.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['scene','group','site','date','plume_precision','plume_recall','plume_f1','overall_accuracy'])
        for row in scenes:
            m=row['svm'];p=m['classes']['plume'];w.writerow([row['png'],row['group'],row['site'],row['date'],p['precision'],p['recall'],p['f1'],m['accuracy']])
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--reference',type=Path,required=True,help='Existing expanded U-Net evaluation directory')
    parser.add_argument('--out',type=Path,required=True,help='New output directory; never overwrites results')
    args=parser.parse_args();evaluate(args.root,args.reference,args.out)
