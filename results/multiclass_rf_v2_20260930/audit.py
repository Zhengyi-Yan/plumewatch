from pathlib import Path
import sys,json,copy
from collections import defaultdict,Counter
import numpy as np,rasterio
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R))
from annotation_pipeline import read_xml,polygon_mask
from processing import usable
O=Path(__file__).resolve().parent
entries=defaultdict(list)
for p in sorted((R/'data/processed').glob('dataset_task_*.zip')):
 for e in read_xml(p).findall('image'):entries[Path(e.get('name')).name].append((p.name,e))
rows=[]
for name,versions in entries.items():
 side=R/'data/processed/sam_candidates'/name.removesuffix('_cvat.png')/'source.json'
 meta=json.loads(side.read_text());source=Path(meta['source_tif'])
 counts=defaultdict(int);merged=None;conflict=None;shape=(meta['height'],meta['width'])
 for archive,e in versions:
  for el in e:
   counts[el.get('label')]+=1
   if el.get('label')=='candidate':continue
   single=copy.deepcopy(e);single[:]=[copy.deepcopy(el)]
   m=polygon_mask(single,shape)
   if merged is None:merged=np.full(shape,255,np.uint8);conflict=np.zeros(shape,bool)
   clash=(m!=255)&(merged!=255)&(m!=merged);conflict|=clash
   merged[m!=255]=m[m!=255]
 row=dict(name=name,archives=[v[0] for v in versions],source=str(source),counts=dict(counts))
 if merged is None:row.update(status='candidate_only');rows.append(row);print(name,'CANDIDATE ONLY',flush=True);continue
 with rasterio.open(source) as d:valid=usable(d.read())
 row.update(conflicts=int((conflict&valid).sum()),conflicts_total=int(conflict.sum()),valid_labelled=int(((merged!=255)&valid).sum()))
 rows.append(row);print(name,'conflicts',row['conflicts'],'labelled',row['valid_labelled'],flush=True)
(O/'audit.json').write_text(json.dumps(rows,indent=2))
