"""Reproduce the September 30 RF update; never changes the v1 baseline."""
from pathlib import Path
import sys, json, pickle, re, copy, xml.etree.ElementTree as ET
from collections import defaultdict
import numpy as np
import rasterio
import sklearn
from sklearn.metrics import confusion_matrix
R=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(R))
import annotation_pipeline as ap
import train_multiclass as rf
O=Path(__file__).resolve().parent
M=R/'data/processed/cvat_masks_v2_20260930'; M.mkdir(exist_ok=True)
audit=json.loads((O/'audit.json').read_text())
assert len(audit)==30 and all(r.get('conflicts_total',0)==0 for r in audit)
archives=sorted((R/'data/processed').glob('dataset_task_*.zip'))
assert {p.name for p in archives}=={f'dataset_task_{i}.zip' for i in range(8,15)}
snapshot=json.loads((O/'metrics.json').read_text())
assert {p.name:rf.file_hash(p) for p in archives} == snapshot['input_zip_sha256'], 'Changed exports: use a fresh version'
versions=defaultdict(list)
for p in archives:
 for el in ap.read_xml(p).findall('image'): versions[Path(el.get('name')).name].append(el)
old=[r for r in json.loads(ap.MANIFEST.read_text()) if rf.mask_path(r).exists()]
for r in old:
 r['cohort']='original'; r['mask_path']=str(rf.mask_path(r))
new=[]
for row in audit:
 if row.get('status')=='candidate_only':continue
 name=row['name']; meta=json.loads((R/'data/processed/sam_candidates'/name.removesuffix('_cvat.png')/'source.json').read_text())
 date=re.search(r'(20\d{6})',name).group(1)
 site=next(s for token,s in [('Isonzo','Isonzo'),('Arno','Arno'),('Var','Var'),('Pineios','Pineios'),('Burdekin','Burdekin'),('Murray','Murray'),('Tully','Tully'),('Tweed','Tweed'),('Maitai','Maitai'),('Wakapuaka','Wakapuaka'),('Waimakariri','Waimakariri / Pegasus Bay'),('Hawkesbury','Hawkesbury'),('Hunter','Hunter')] if token in name)
 event=site+' '+date
 if site in ('Burdekin','Tully') and date.startswith('202502'):event='Queensland February 2025'
 if site in ('Maitai','Wakapuaka'):event='Nelson August 2022'
 if site in ('Hawkesbury','Hunter'):event='NSW April 2022'
 acquisition=re.search(r'(20\d{6}T\d{6})',name)
 # Missing exact acquisition metadata is never represented by an empty shared key.
 acquisition=acquisition.group(1) if acquisition else site+' '+date
 rec={k:meta[k] for k in ('source_tif','width','height','crs','transform')}
 rec.update(png=name,bands=ap.BANDS[:10],site=site,event_group=event,acquisition=acquisition,date=date,cohort='new',archives=row['archives'],source_sha256=meta['source_sha256'])
 target=M/(Path(name).stem+'_mask.tif');rec['mask_path']=str(target)
 merged=copy.deepcopy(versions[name][0]);merged[:]=[]
 seen=set()
 for version in versions[name]:
  for shape in version:
   if shape.get('label')=='candidate':continue
   # Same reviewed geometry can occur in multiple exports with different IDs/source.
   key=(shape.tag,tuple(sorted((k,v) for k,v in shape.attrib.items() if k not in ('id','source','z_order'))))
   if key not in seen:merged.append(copy.deepcopy(shape));seen.add(key)
 if not target.exists():
  xml=O/'one_image.xml';root=ET.Element('annotations');root.append(merged);ET.ElementTree(root).write(xml)
  ap.convert([xml],[rec],M)
 new.append(rec)
records=old+new
assert len(old)==21 and len(new)==28
(O/'manifest.json').write_text(json.dumps(records,indent=2))
groups=rf.groups_for(records)
# Geographic overlap across CRS is also forbidden (existing helper checks same CRS only).
from rasterio.warp import transform_bounds
bounds=[transform_bounds(r['crs'],'EPSG:4326',r['transform'][2],r['transform'][5]+r['transform'][4]*r['height'],r['transform'][2]+r['transform'][0]*r['width'],r['transform'][5],densify_pts=21) for r in records]
for i,a in enumerate(bounds):
 for j,b in enumerate(bounds[:i]):
  if min(a[2],b[2])>max(a[0],b[0]) and min(a[3],b[3])>max(a[1],b[1]) and groups[i]!=groups[j]:
   before=groups[i];after=groups[j];groups=[after if g==before else g for g in groups]
(O/'groups.json').write_text(json.dumps([dict(png=r['png'],cohort=r['cohort'],site=r['site'],event=r['event_group'],group=g) for r,g in zip(records,groups)],indent=2))
rf.mask_path=lambda r:Path(r['mask_path'])
cache=R/'data/processed/multiclass_rf_v2_20260930/samples.pkl'
if cache.exists():samples=pickle.loads(cache.read_bytes())
else:
 samples=[]
 for i,r in enumerate(records):
  samples.append(rf.sample_scene(r));print('Sample',i+1,len(records),Path(r['png']).name,flush=True)
 cache.write_bytes(pickle.dumps(samples))
assert len(samples)==len(records)
for modelpath in ['data/processed/multiclass_rf_v1/model.pkl','results/baseline_v1/model.pkl']:
 print('Baseline',modelpath,flush=True)
legacy=pickle.loads((R/'results/baseline_v1/model.pkl').read_bytes())['model'];legacy.n_jobs=4
frozen=pickle.loads((R/'data/processed/multiclass_rf_v1/model.pkl').read_bytes())['model'];frozen.n_jobs=4
rows=[];folds=[]
for held in sorted(set(groups)):
 idx=[i for i,g in enumerate(groups) if g==held]
 train=[i for i,g in enumerate(groups) if g!=held]
 original_train=[i for i in train if i<len(old)]
 assert not set(groups[i] for i in train)&{held}
 resultfile=O/(held+'.json')
 if resultfile.exists():
  result=json.loads(resultfile.read_text());rows+=result['scenes'];folds.append(result);continue
 x,y=rf.training_set(samples,groups,train,np.random.default_rng(42))
 print('Fit expanded',held,'train',len(y),'test frames',len(idx),flush=True)
 model=rf.make_model().fit(x,y)
 bx,by=rf.training_set(samples,groups,original_train,np.random.default_rng(42))
 print('Fit original-only',held,'train',len(by),flush=True)
 baseline=rf.make_model().fit(bx,by)
 scene_rows=[]
 for i in idx:
  yy=samples[i][3];xx=samples[i][2]
  rr=dict(png=Path(records[i]['png']).name,cohort=records[i]['cohort'],group=held,site=records[i]['site'],date=records[i]['date'],labelled_pixel_counts=samples[i][4])
  for key,est in [('expanded_rf',model),('original_only_rf',baseline)]:
   pred=est.predict(xx);rr[key]=rf.scores(confusion_matrix(yy,pred,labels=rf.CLASS_IDS))
  if i>=len(old):
   rr['frozen_v1_seen_site']=any(groups[j]==held for j in range(len(old)))
   rr['frozen_v1']=rf.scores(confusion_matrix(yy,frozen.predict(xx),labels=rf.CLASS_IDS))
   rr['pilot_binary_confusion']=confusion_matrix(yy==1,legacy.predict(xx)==1,labels=[False,True]).tolist()
  scene_rows.append(rr)
 result=dict(group=held,train_samples=len(y),original_only_train_samples=len(by),train_frames=len(train),test_frames=len(idx),sites=sorted({records[i]['site'] for i in idx}),scenes=scene_rows)
 resultfile.write_text(json.dumps(result,indent=2));rows+=scene_rows;folds.append(result)
 print('Done',held,flush=True)
x,y=rf.training_set(samples,groups,list(range(len(records))),np.random.default_rng(42))
print('Fit final',len(y),flush=True)
final=rf.make_model().fit(x,y)
(R/'data/processed/multiclass_rf_v2_20260930/model.pkl').write_bytes(pickle.dumps(dict(model=final,bands=ap.BANDS[:10],classes=rf.CLASS_IDS,sklearn_version=sklearn.__version__,processing='S2_SR_HARMONIZED_SCL_v1')))
def aggregate(selected,key):
 matrix=sum((np.array(s[key]['confusion_matrix']) for s in selected),np.zeros((3,3),dtype=np.int64))
 result=rf.scores(matrix)
 positives=[s[key]['classes']['plume']['f1'] for s in selected if s[key]['classes']['plume']['support']]
 result['positive_frame_macro_f1']=float(np.mean(positives));result['positive_frame_median_f1']=float(np.median(positives));result['positive_frames_below_0_7']=sum(f<.7 for f in positives)
 return result
summary={}
for cohort in ['all','original','new']:
 selected=[s for s in rows if cohort=='all' or s['cohort']==cohort]
 summary[cohort]={key:aggregate(selected,key) for key in ['expanded_rf','original_only_rf']}
unseen=[s for s in rows if s['cohort']=='new' and not s['frozen_v1_seen_site']]
summary['new_unseen_groups']={key:aggregate(unseen,key) for key in ['expanded_rf','original_only_rf','frozen_v1']}
cm=sum((np.array(s['pilot_binary_confusion']) for s in unseen),np.zeros((2,2),dtype=np.int64));tn,fp,fn,tp=map(int,cm.ravel())
summary['new_unseen_groups']['frozen_binary_pilot']={'confusion_matrix':cm.tolist(),'precision':tp/(tp+fp),'recall':tp/(tp+fn),'f1':2*tp/(2*tp+fp+fn),'iou':tp/(tp+fp+fn)}
report=dict(method='leave-one-linked-site-event-group-out; matched deterministic 15000 labelled pixels per frame',seed=42,original_frames=len(old),new_frames=len(new),groups=len(set(groups)),final_train_samples=len(y),model_parameters=final.get_params(),bands=ap.BANDS[:10],summary=summary,folds=folds,scenes=rows,audit=audit,input_zip_sha256={p.name:rf.file_hash(p) for p in archives},limitations=['Visual reference labels, not measured sediment ground truth.','Only reviewed annotations are scored; unlabelled pixels and SAM candidates ignored.','Uniform sample of up to 15000 pixels per frame; not full-raster metrics. Tiles are not independent scenes.','Fold groups join sites, events, acquisitions and overlapping map footprints.','Old-only RF is refitted per fold excluding the same held-out group; frozen baselines are independent only on new unseen groups.','SCL/valid filtering follows the existing RF baseline; valid source pixels outside SCL 2,4,5,6,7 are ignored.','No hyperparameter tuning; final all-data model has no independent test score.','Sparse or ambiguous labels can bias metrics. No sediment concentration or detection of invisible sediment is claimed.'])
(O/'metrics.json').write_text(json.dumps(report,indent=2))
print(json.dumps(summary,indent=2),flush=True)
