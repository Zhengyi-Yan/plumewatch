"""Run a fixed pilot model; never fit or tune on the held-out 2021 labels."""
import csv
import hashlib
import json
from pathlib import Path
import pickle
import sys
from collections import Counter

import numpy as np
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, balanced_accuracy_score, classification_report, confusion_matrix, roc_auc_score
from shapely.geometry import shape, Point
from shapely.ops import transform
from pyproj import Transformer

ROOT = Path(sys.argv[1])
BANDS = ['B2','B3','B4','B5','B6','B7','B8','B8A','B11','B12']
TRAIN = ROOT / 'drive-download-20260913T095318Z-1-001'
TEST = ROOT / 'hutt-test'
OUT = ROOT / 'results' / 'baseline_v1'
project = Transformer.from_crs(4326, 32760, always_xy=True).transform

def read_set(files, labels_path, split):
    rows = []
    for path in files:
        with path.open() as stream:
            rows.extend(csv.DictReader(stream))
    labels = json.loads(labels_path.read_text())['features']
    geometries = {f['properties']['polygon_id']: transform(project, shape(f['geometry'])) for f in labels}
    classes = {f['properties']['polygon_id']: int(f['properties']['class_id']) for f in labels}
    assert len(geometries) == len(labels), 'Duplicate polygon IDs'
    assert all(g.is_valid and g.area > 0 for g in geometries.values()), 'Invalid geometry'
    overlap = []
    ids = list(geometries)
    for i, a in enumerate(ids):
        for b in ids[i+1:]:
            area = geometries[a].intersection(geometries[b]).area
            if area > 1:
                overlap.append([a,b,area])
    assert not overlap, f'Overlapping labels: {overlap}'
    assert set(r['polygon_id'] for r in rows) == set(ids), 'Missing labelled polygons'
    positions = [(r['asset_id'], r['longitude'],r['latitude']) for r in rows]
    assert len(set(positions)) == len(rows), 'Duplicate sample coordinates'
    distances = []
    for r in rows:
        assert r['split'] == split
        assert r['processing'] == 'S2_SR_HARMONIZED_SCL_v1'
        assert int(r['class_id']) == classes[r['polygon_id']]
        distances.append(geometries[r['polygon_id']].distance(Point(*project(float(r['longitude']),float(r['latitude'])))))
    assert max(distances) < 1, 'Samples outside labels by more than 1 metre'
    x = np.array([[float(r[b]) for b in BANDS] for r in rows])
    y = np.array([int(r['class_id']) for r in rows])
    assert np.isfinite(x).all() and set(y) == {0,1}
    return rows,x,y,{'rows':len(rows),'polygons':len(labels),'class_counts':dict(Counter(map(int,y))),
                     'maximum_distance_outside_polygon_m':max(distances),'overlap_pairs':overlap}

train_files = sorted(TRAIN.glob('*_samples.csv'))
test_files = [TEST / 'hutt_20210723_test-v2_all_samples.csv']
tr,x,y,train_check = read_set(train_files, TRAIN/'hutt_20200713_v1_b1_labels.geojson','train')
te,xt,yt,test_check = read_set(test_files, TEST/'hutt_20210723_test-v2_all_labels.geojson','test')
assert not ({r['asset_id'] for r in tr} & {r['asset_id'] for r in te}), 'Train/test acquisition leakage'
model = RandomForestClassifier(n_estimators=300,min_samples_leaf=5,class_weight='balanced',random_state=42,n_jobs=-1)
model.fit(x,y)
pred = model.predict(xt)
prob = model.predict_proba(xt)[:,list(model.classes_).index(1)]
per_polygon = []
for pid in sorted(set(r['polygon_id'] for r in te)):
    keep = np.array([r['polygon_id']==pid for r in te])
    per_polygon.append({'polygon_id':pid,'class_id':int(yt[keep][0]),'samples':int(keep.sum()),
                        'accuracy':accuracy_score(yt[keep],pred[keep]),'predicted_plume_fraction':float(pred[keep].mean())})
report = {'model':'RandomForestClassifier','parameters':model.get_params(),'bands':BANDS,'sklearn_version':sklearn.__version__,
          'validation':{'train':train_check,'test':test_check},'accuracy':accuracy_score(yt,pred),
          'balanced_accuracy':balanced_accuracy_score(yt,pred),'roc_auc':roc_auc_score(yt,prob),
          'confusion_matrix_rows_true_columns_predicted_background_plume':confusion_matrix(yt,pred,labels=[0,1]).tolist(),
          'classification_report':classification_report(yt,pred,labels=[0,1],target_names=['background','plume'],output_dict=True,zero_division=0),
          'per_polygon':per_polygon,
          'inputs_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in train_files+test_files},
          'limitations':['One training polygon per class; one test acquisition in the same harbour.',
                         'Labels are visual interpretations, not measured sediment truth.',
                         'Neighbouring samples are correlated; pixel counts are not independent observations.',
                         'No whole-image classification or plume-area accuracy was evaluated.',
                         'Test results must not be used for tuning while still calling this an untouched test.']}
OUT.mkdir(parents=True,exist_ok=True)
(OUT/'metrics.json').write_text(json.dumps(report,indent=2)+'\n')
with (OUT/'model.pkl').open('wb') as stream:
    pickle.dump({'model':model,'bands':BANDS,'processing':'S2_SR_HARMONIZED_SCL_v1','sklearn_version':sklearn.__version__},stream)
with (OUT/'test_predictions.csv').open('w',newline='') as stream:
    writer=csv.DictWriter(stream,fieldnames=['polygon_id','longitude','latitude','true_class','predicted_class','plume_probability'])
    writer.writeheader()
    for r,p,q in zip(te,pred,prob):
        writer.writerow({'polygon_id':r['polygon_id'],'longitude':r['longitude'],'latitude':r['latitude'],
                         'true_class':r['class_id'],'predicted_class':int(p),'plume_probability':float(q)})
print(json.dumps(report,indent=2))
