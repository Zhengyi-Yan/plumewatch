"""Prepare native-grid SAM polygon candidates; optionally create a separate local CVAT task."""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import shapes, rasterize
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from annotation_pipeline import render_rgb
from processing import validate, usable

SAM_CONTAINER = 'nuclio-nuclio-plumewatch-sam2-small'
DOCKER = shutil.which('docker') or '/Applications/Docker.app/Contents/Resources/bin/docker'

SAM_RUN = '''
import sys,time,json,numpy as np,torch
from pathlib import Path
from ultralytics.models.sam.predict import SAM2Predictor
class Automatic(SAM2Predictor):
    def generate(self,im,*args,**kwargs):
        return super().generate(im,points_stride=32,points_batch_size=8,crop_n_layers=0)
p=Path(sys.argv[1]);torch.set_num_threads(4);start=time.monotonic()
model=Automatic(overrides=dict(model='/opt/nuclio/sam2.1_s.pt',device='cpu',imgsz=1024,conf=0.25,task='segment',mode='predict',save=False,verbose=False))
r=model(source=str(p/'source.png'))[0]
m=r.masks.data.cpu().numpy().astype(bool) if r.masks is not None else np.zeros((0,*r.orig_shape),bool)
assert m.shape[1:]==r.orig_shape
np.savez_compressed(p/'masks.npz',masks=m)
(p/'sam.json').write_text(json.dumps(dict(model='SAM 2.1 Small',seconds=time.monotonic()-start,mask_count=len(m),grid=32,input_size=1024,crop_layers=0)))
print('SAM masks:',len(m),'seconds:',round(time.monotonic()-start,1),flush=True)
'''

CONVERT = '''
import json,sys,numpy as np
from pathlib import Path
from datumaro.util.mask_tools import _merge_contour_with_parent
p=Path(sys.argv[1]);rows=[]
for f in json.loads((p/'geometry.json').read_text()):
    rings=f['geometry']['coordinates'];contour=np.asarray(rings[0][:-1],dtype=float)
    for ring in rings[1:]: contour=_merge_contour_with_parent(contour,np.asarray(ring[:-1],dtype=float))
    rows.append(dict(group=f['candidate'],points=contour.ravel().tolist()))
(p/'polygons.json').write_text(json.dumps(rows))
'''

IMPORT = '''
import json,time
from pathlib import Path
from contextlib import ExitStack
from collections import Counter
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from cvat.apps.engine.models import Task,Job
p=Path(WORK);spec=json.loads((p/'import.json').read_text())
existing=Task.objects.filter(name=spec['name']).first()
if existing: raise RuntimeError(f'Task {existing.id} already exists; refusing to overwrite annotations')
frames=spec.get('frames')
if frames is None:
    frames=[dict(png_name=spec['png_name'],width=spec['width'],height=spec['height'],polygons=json.loads((p/'polygons.json').read_text()))]
u=get_user_model().objects.filter(is_superuser=True,is_active=True).first()
if u is None: raise RuntimeError('No active local CVAT administrator')
c=APIClient();c.force_authenticate(user=u)
labels=[dict(name=n,type='any',color=color,attributes=[]) for n,color in [('candidate','#d48b28'),('plume','#e76f32'),('normal_water','#2879ba'),('land','#828282'),('shallow_water','#46b5ad')]]
r=c.post('/api/tasks',dict(name=spec['name'],labels=labels,owner_id=u.id,segment_size=1000),format='json')
if r.status_code!=201: raise RuntimeError(str(r.data))
task=r.data['id']; print('Created CVAT task',task,flush=True)
(p/'task.json').write_text(json.dumps(dict(task=task,name=spec['name'])))
with ExitStack() as stack:
    upload={'image_quality':100,'sorting_method':'lexicographical'}
    for i,f in enumerate(frames): upload[f'client_files[{i}]']=stack.enter_context((p/f['png_name']).open('rb'))
    r=c.post(f'/api/tasks/{task}/data',upload,format='multipart')
if r.status_code!=202: raise RuntimeError(str(r.data))
for _ in range(90):
    t=Task.objects.get(id=task)
    if t.data and t.data.size==len(frames): break
    time.sleep(1)
else: raise RuntimeError(f'Task {task} upload still processing; task preserved for inspection')
actual_frames=c.get(f'/api/tasks/{task}/data/meta').data['frames']
lookup={Path(f['name']).name:(i,f) for i,f in enumerate(actual_frames)}
label=t.label_set.get(name='candidate').id;items=[];mapping=[]
for f in frames:
    index,actual=lookup[f['png_name']]
    if (actual['width'],actual['height'])!=(f['width'],f['height']): raise RuntimeError('CVAT image dimensions changed')
    mapping.append(dict(frame=index,png=f['png_name'],width=f['width'],height=f['height']))
    items.extend(dict(type='polygon',frame=index,label_id=label,group=row['group'],source='auto',occluded=False,z_order=0,rotation=0,attributes=[],points=row['points']) for row in f['polygons'])
r=c.put(f'/api/tasks/{task}/annotations',dict(version=0,tags=[],tracks=[],shapes=items),format='json')
if r.status_code!=200: raise RuntimeError(str(r.data))
r=c.get(f'/api/tasks/{task}/annotations')
if r.status_code!=200 or len(r.data['shapes'])!=len(items): raise RuntimeError('Annotation readback failed')
key=lambda x:(x['frame'],x['group'],tuple(x['points']))
if Counter(map(key,items))!=Counter(map(key,r.data['shapes'])): raise RuntimeError('CVAT changed polygon coordinates')
(p/'imported.json').write_text(json.dumps(r.data))
jobs=list(Job.objects.filter(segment__task=t).values_list('id',flat=True))
(p/'task.json').write_text(json.dumps(dict(task=task,jobs=jobs,job=jobs[0],name=spec['name'],polygons=len(items),frames=mapping)))
print('Verified CVAT task',task,'jobs',jobs,'frames',len(frames),flush=True)
'''


def docker(*args, code=None):
    subprocess.run([DOCKER, *args], input=code, text=True, check=True)


def prepare(source, out):
    with source.open('rb') as stream:
        source_hash=hashlib.file_digest(stream,'sha256').hexdigest()
    with rasterio.open(source) as src:
        validate(src)
        data=src.read(); valid=usable(data)
        if not valid.any(): raise ValueError('No usable pixels')
        rgb=render_rgb(data); rgb[~valid]=0
        Image.fromarray(rgb).save(out/(source.stem+'_cvat.png'))
        meta=dict(source_tif=str(source),png=source.stem+'_cvat.png',width=src.width,height=src.height,
                  crs=str(src.crs),transform=list(src.transform)[:6],bands=list(src.descriptions),
                  rgb_processing='B4/B3/B2; clip(reflectance/0.25,0,1) ** (1/1.2); no geometric change',
                  valid_processing='valid=1 AND SCL in 2,4,5,6,7 AND finite non-nodata reflectance',
                  source_sha256=source_hash)
    (out/'source.json').write_text(json.dumps(meta,indent=2))
    return rgb,valid,meta


def verify_polygons(rows, masks, valid, ids):
    for candidate in ids:
        geoms=[]
        for row in rows:
            if row['group']==candidate:
                xy=np.asarray(row['points']).reshape(-1,2).tolist()
                geoms.append((dict(type='Polygon',coordinates=[xy+[xy[0]]]),1))
        if not geoms: raise ValueError('Missing candidate polygons')
        actual=rasterize(geoms,out_shape=valid.shape).astype(bool)
        if not np.array_equal(actual,masks[candidate-1]&valid):
            raise ValueError(f'Polygon conversion changed candidate {candidate}')


def preview(rgb, geometry, masks, valid, ids, out):
    original=Image.fromarray(rgb); outline=original.copy(); draw=ImageDraw.Draw(outline)
    colors=['#ff9f43','#31c5ff','#e879f9','#70e6a5','#ff687b','#ffe066']
    for f in geometry:
        for ring in f['geometry']['coordinates']:
            draw.line([tuple(x) for x in ring],fill=colors[(f['candidate']-1)%len(colors)],width=4)
    views=[('Original RGB (SCL masked)',original),('All SAM candidate outlines',outline)]
    for c in sorted(ids,key=lambda i:int((masks[i-1]&valid).sum()),reverse=True)[:6]:
        mask=masks[c-1]&valid; rgba=np.zeros((*valid.shape,4),dtype='uint8')
        color=colors[(c-1)%len(colors)];rgba[mask]=(*bytes.fromhex(color[1:]),95)
        image=Image.alpha_composite(original.convert('RGBA'),Image.fromarray(rgba)).convert('RGB')
        views.append((f'Candidate {c}: {mask.sum():,} pixels',image))
    w=480;h=round(rgb.shape[0]*w/rgb.shape[1]);rows=(len(views)+2)//3
    sheet=Image.new('RGB',(3*(w+12),rows*(h+45)+35),'white');d=ImageDraw.Draw(sheet)
    try: font=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',17)
    except OSError: font=ImageFont.load_default()
    for i,(title,image) in enumerate(views):
        x=(i%3)*(w+12)+6;y=(i//3)*(h+45)+6
        d.text((x,y),title,font=font,fill='black');sheet.paste(image.resize((w,h),Image.Resampling.NEAREST),(x,y+27))
    d.text((8,rows*(h+45)), 'Unclassified proposals; overlaps and missed regions need review.',font=font,fill='black')
    sheet.save(out/'preview.png')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tif',type=Path)
    parser.add_argument('--import-cvat',action='store_true',help='Create a new standalone candidate task')
    args=parser.parse_args();source=args.tif.resolve(strict=True)
    if not source.is_relative_to(ROOT): raise ValueError('Use a TIFF inside this project')
    out=ROOT/'data/processed/sam_candidates'/source.stem
    if out.exists(): raise ValueError(f'Output already exists: {out}. Preserved; inspect it before rerunning.')
    for container in [SAM_CONTAINER,'cvat_server']:
        state=subprocess.check_output([DOCKER,'inspect','--format','{{.State.Running}}',container],text=True).strip()
        if state!='true': raise RuntimeError(f'Start {container} in Docker Desktop first')
    out.mkdir(parents=True)
    rgb,valid,meta=prepare(source,out); print('Prepared native-grid image:',meta['width'],meta['height'],flush=True)
    with tempfile.TemporaryDirectory(prefix='plumewatch-sam-') as tmp:
        work=Path(tmp); remote='/tmp/'+work.name
        try:
            for container in [SAM_CONTAINER,'cvat_server']: docker('exec',container,'mkdir','-p',remote)
            docker('cp',str(out/meta['png']),f'{SAM_CONTAINER}:{remote}/source.png')
            docker('exec','-i',SAM_CONTAINER,'python','-',remote,code=SAM_RUN)
            for name in ['masks.npz','sam.json']: docker('cp',f'{SAM_CONTAINER}:{remote}/{name}',str(out/name))
            with np.load(out/'masks.npz') as archive: masks=archive['masks']
            if masks.shape[1:]!=valid.shape: raise ValueError('SAM output grid mismatch')
            ids=[i+1 for i,m in enumerate(masks) if (m&valid).sum()>=100]
            geometry=[]
            for c in ids:
                clean=masks[c-1]&valid
                geometry.extend(dict(candidate=c,geometry=g) for g,_ in shapes(clean.astype('uint8'),mask=clean))
            (out/'geometry.json').write_text(json.dumps(geometry))
            if not ids: print('SAM returned no candidates of at least 100 valid pixels; retaining an empty frame for manual annotation',flush=True)
            docker('cp',str(out/'geometry.json'),f'cvat_server:{remote}/geometry.json')
            docker('exec','-i','cvat_server','python','-',remote,code=CONVERT)
            docker('cp',f'cvat_server:{remote}/polygons.json',str(out/'polygons.json'))
            rows=json.loads((out/'polygons.json').read_text());verify_polygons(rows,masks,valid,ids)
            preview(rgb,geometry,masks,valid,ids,out)
            cover=np.zeros(valid.shape,dtype='uint16')
            for c in ids: cover+=masks[c-1]&valid
            report=dict(source=meta,candidate_ids=ids,polygon_count=len(rows),overlapping_pixels=int((cover>1).sum()),
                        valid_pixels=int(valid.sum()),covered_valid_pixels=int((cover>0).sum()),
                        conversion='Exact mask-to-polygon raster round trip passed; holes retained',
                        review='Relabel or delete EVERY candidate before training; review overlaps. Source metadata is a sidecar, not added to the training manifest.')
            (out/'report.json').write_text(json.dumps(report,indent=2))
            print('Verified',len(ids),'regions as',len(rows),'polygons; overlap pixels',report['overlapping_pixels'],flush=True)
            if args.import_cvat:
                spec=dict(name=f'SAM candidates — {source.stem} [{meta["source_sha256"][:8]}]',png_name=meta['png'],width=meta['width'],height=meta['height'])
                (out/'import.json').write_text(json.dumps(spec))
                for name in ['import.json',meta['png']]: docker('cp',str(out/name),f'cvat_server:{remote}/{name}')
                try: docker('exec','-i','cvat_server','python','manage.py','shell',code='WORK='+repr(remote)+'\n'+IMPORT)
                finally:
                    # Preserve any task ID if upload/import fails; never delete user tasks.
                    subprocess.run([DOCKER,'cp',f'cvat_server:{remote}/task.json',str(out/'cvat_task.json')],capture_output=True)
                docker('cp',f'cvat_server:{remote}/imported.json',str(out/'imported_annotations.json'))
                saved=json.loads((out/'imported_annotations.json').read_text())['shapes']
                verify_polygons(saved,masks,valid,ids)
                print('CVAT:',(out/'cvat_task.json').read_text(),flush=True)
        finally:
            for container in [SAM_CONTAINER,'cvat_server']:
                subprocess.run([DOCKER,'exec',container,'rm','-rf','--',remote],capture_output=True)
    print('Results:',out,flush=True)

if __name__=='__main__':
    main()
