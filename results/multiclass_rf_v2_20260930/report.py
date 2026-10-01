from pathlib import Path
import json,csv,sys
from collections import defaultdict
import numpy as np
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R))
import train_multiclass as rf
O=Path(__file__).resolve().parent
r=json.loads((O/'metrics.json').read_text());rows=r['scenes']
keys=['original_only_rf','expanded_rf']
def combine(items,key):return rf.scores(sum((np.array(s[key]['confusion_matrix']) for s in items),np.zeros((3,3),dtype=np.int64)))
scene_groups=defaultdict(list)
for s in rows:scene_groups[(s['cohort'],s['site'],s['date'])].append(s)
source_results=[]
for (cohort,site,date),items in scene_groups.items():
 source_results.append(dict(cohort=cohort,site=site,date=date,frames=len(items),**{k:combine(items,k) for k in keys}))
r['per_site_date']=source_results
for cohort in ['all','original','new']:
 selected=[s for s in source_results if cohort=='all' or s['cohort']==cohort]
 for key in keys:
  vals=[s[key]['classes']['plume']['f1'] for s in selected if s[key]['classes']['plume']['support']]
  r['summary'][cohort][key]['positive_site_date_macro_f1']=float(np.mean(vals))
  vals2=[]
  for g in sorted({s['group'] for s in rows}):
   part=[s for s in rows if s['group']==g and (cohort=='all' or s['cohort']==cohort)]
   if part:
    v=combine(part,key)['classes']['plume']
    if v['support']:vals2.append(v['f1'])
  r['summary'][cohort][key]['positive_group_macro_f1']=float(np.mean(vals2))
r['negative_reference_frames']=[]
for s in rows:
 if s['expanded_rf']['classes']['plume']['support']==0:
  entry={'png':s['png']}
  for key in keys:
   m=np.array(s[key]['confusion_matrix']);entry[key]={'false_plume_pixels':int(m[:,1].sum()),'reference_pixels':int(m.sum()),'false_positive_rate':float(m[:,1].sum()/m.sum())}
  r['negative_reference_frames'].append(entry)
r['limitations']+=['Some source acquisitions have multiple tiles; site/date and group macro metrics are reported to reduce their influence.','The original P2-05 products share a date and footprint. They stay in one fold and one site/date summary; retained to match the previous 21-frame baseline.','Contact-sheet inspection checks alignment only; broad/faint plume polygons (including Arno January 2021) remain human reference labels, not verified physical boundaries.']
(O/'metrics.json').write_text(json.dumps(r,indent=2))
with (O/'per_frame.csv').open('w') as f:
 w=csv.writer(f);w.writerow(['image','cohort','group','site','date','plume_reference_pixels','old_precision','old_recall','old_f1','old_iou','new_precision','new_recall','new_f1','new_iou','f1_change'])
 for s in rows:
  a=s[keys[0]]['classes']['plume'];b=s[keys[1]]['classes']['plume']
  w.writerow([s['png'],s['cohort'],s['group'],s['site'],s['date'],b['support'],*[a[k] for k in ['precision','recall','f1','iou']],*[b[k] for k in ['precision','recall','f1','iou']],b['f1']-a['f1']])
lines=['# RF update — 30 September 2026','', '## Result','', 'The additional labels do not establish a uniformly better RF. Keep the existing baseline in place; the new model is a separate research checkpoint. No U-Net was trained and no dashboard model was replaced.','', '## Matched held-out evaluation','', '| Reference cohort | Original-label RF F1 | Expanded RF F1 | Original IoU | Expanded IoU |','|---|---:|---:|---:|---:|']
for cohort,label in [('original','Original 21 frames'),('new','New 28 frames'),('all','All 49 frames')]:
 a=r['summary'][cohort]['original_only_rf']['classes']['plume'];b=r['summary'][cohort]['expanded_rf']['classes']['plume']
 lines.append(f"| {label} | {a['f1']:.4f} | {b['f1']:.4f} | {a['iou']:.4f} | {b['iou']:.4f} |")
lines+=['','Both columns use exactly the same sampled reference pixels and hold out the entire linked site/event group. The original-label comparator is refit using only the original data outside that group; the expanded RF adds new labels outside that group. These are cross-validation scores, not scores of the final all-data model.','', '| Cohort | Old precision | New precision | Old recall | New recall | Old site/date macro F1 | New site/date macro F1 |','|---|---:|---:|---:|---:|---:|---:|']
for cohort in ['original','new','all']:
 a=r['summary'][cohort][keys[0]];b=r['summary'][cohort][keys[1]]
 lines.append(f"| {cohort} | {a['classes']['plume']['precision']:.4f} | {b['classes']['plume']['precision']:.4f} | {a['classes']['plume']['recall']:.4f} | {b['classes']['plume']['recall']:.4f} | {a['positive_site_date_macro_f1']:.4f} | {b['positive_site_date_macro_f1']:.4f} |")
lines+=['','Macro plume F1 includes only reference scenes with plume labels. Negative reference scenes are reported separately below; zero-support F1 is not treated as a segmentation failure.','', '## Frozen baseline comparison on new, unseen groups','', 'Waimakariri 2022 is excluded here because its site was already in the baseline training set. The remaining 27 new frames are unseen by the frozen baselines. The expanded model is still evaluated using its held-out folds.','', '| Model | Plume precision | Recall | F1 | IoU |','|---|---:|---:|---:|---:|']
for key,label in [('frozen_binary_pilot','Original two-class pilot'),('frozen_v1','Frozen three-class RF v1'),('expanded_rf','Expanded RF (held-out)')]:
 v=r['summary']['new_unseen_groups'][key];v=v if key=='frozen_binary_pilot' else v['classes']['plume']
 lines.append('| '+label+' | '+' | '.join(f'{v[k]:.4f}' for k in ['precision','recall','f1','iou'])+' |')
lines+=['','The two-class pilot has no land class: its comparison is binary plume versus all other annotated pixels, not three-class accuracy. Historical baseline scores on different test sets are not directly compared.','', '## Changes by site/date','', '| Cohort | Site | Date | Frames | Old plume F1 | New plume F1 | Change |','|---|---|---|---:|---:|---:|---:|']
for s in sorted(source_results,key=lambda s:s[keys[1]]['classes']['plume']['f1']-s[keys[0]]['classes']['plume']['f1']):
 a=s[keys[0]]['classes']['plume'];b=s[keys[1]]['classes']['plume']
 if b['support']:lines.append(f"| {s['cohort']} | {s['site']} | {s['date']} | {s['frames']} | {a['f1']:.4f} | {b['f1']:.4f} | {b['f1']-a['f1']:+.4f} |")
lines+=['', '## Negative reference scenes','', '| Frame | Old false-plume rate | New false-plume rate |','|---|---:|---:|']
for s in r['negative_reference_frames']:lines.append(f"| {s['png']} | {s[keys[0]]['false_positive_rate']:.4%} | {s[keys[1]]['false_positive_rate']:.4%} |")
lines+=['', '## Input audit and training','', '- Seven ZIPs contain 33 image entries, 30 unique frames, and 28 frames with supported class labels. Three duplicate exports were merged once; all overlapping reviewed classes agreed.','- Two Rhône frames contain only `candidate` objects and were excluded. Unreviewed SAM candidates were ignored. Supported class labels were retained even when their source was `auto`. No reference annotations were relabelled.','- All new masks use the source CRS, affine transform and dimensions, with class IDs 0/1/3 and ignore=255. Source validity and the existing SCL screening policy override annotations.','- 21 original + 28 new frames; 13 connected held-out groups. Burdekin/Tully, Nelson, and Hawkesbury/Hunter are grouped conservatively; all same-site dates stay together.','- Unchanged RF: 120 trees, minimum leaf 20, balanced_subsample, seed 42, ten original reflectance bands. Up to 3,000 training pixels per frame/class, capped at 10,000 per group/class. No tuning.','- Evaluation: deterministic uniform sample of 15,000 valid labelled pixels per frame. Ignored pixels never enter training or scores. Metrics are not full-raster scores.','- Final RF uses all 49 frames and '+str(r['final_train_samples'])+' sampled training pixels. Its performance must be assessed through the held-out models above or genuinely independent future data.','', '## Interpretation and limitations','']
lines+=['- '+s for s in r['limitations']]
lines+=['','Review the largest regressions and the annotation contact sheet before promoting this checkpoint. In particular, some new polygons cover broad faint/turbid-water areas; their intended class definition may differ from earlier labels. This is a possible contributor, not a proven cause.','', 'Files: `metrics.json` (full results), `per_frame.csv`, `manifest.json`, `groups.json`, `audit.json`, `annotation_contact_sheet.jpg`. The original baselines and source ZIPs are preserved.']
(O/'REPORT.md').write_text('\n'.join(lines)+'\n')
print('\n'.join(lines[:25]))
