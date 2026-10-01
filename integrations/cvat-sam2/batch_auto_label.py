"""Segment a TIFF folder and import every image into ONE standalone CVAT task."""
import argparse,json,hashlib,subprocess,sys,tempfile,time
from pathlib import Path
import numpy as np,rasterio
from auto_label import ROOT,DOCKER,IMPORT,docker,verify_polygons
from processing import usable


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path)
    args=parser.parse_args();folder=args.folder.resolve(strict=True)
    if not folder.is_relative_to(ROOT): raise ValueError('Use a folder inside this project')
    sources=sorted(folder.glob('*.tif'))
    if not sources: raise ValueError('No TIFF files')
    prepared=[];frame_specs=[];next_group=1
    for source in sources:
        out=ROOT/'data/processed/sam_candidates'/source.stem
        complete=all((out/n).exists() for n in ['report.json','source.json','polygons.json','masks.npz'])
        if out.exists() and not complete:
            archived=out.with_name(out.name+'_interrupted_'+str(time.time_ns()))
            out.rename(archived); print('Preserved interrupted output:',archived,flush=True)
        if not complete:
            print('SEGMENT',source.name,flush=True)
            subprocess.run([sys.executable,'-u',str(Path(__file__).with_name('auto_label.py')),str(source)],check=True)
        meta=json.loads((out/'source.json').read_text())
        with source.open('rb') as stream: digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if digest!=meta['source_sha256']: raise ValueError('Cached source changed: '+str(source))
        rows=json.loads((out/'polygons.json').read_text());ids=sorted({r['group'] for r in rows})
        with rasterio.open(source) as src: valid=usable(src.read())
        with np.load(out/'masks.npz') as archive: masks=archive['masks']
        verify_polygons(rows,masks,valid,ids)
        mapping={old:next_group+i for i,old in enumerate(ids)};next_group+=len(ids)
        remapped=[dict(group=mapping[r['group']],points=r['points']) for r in rows]
        frame_specs.append(dict(png_name=meta['png'],width=meta['width'],height=meta['height'],polygons=remapped))
        prepared.append(dict(output=str(out),source=str(source),png=meta['png'],sha256=digest,group_map=mapping))
        print('READY',source.name,'regions',len(ids),'polygons',len(rows),flush=True)
    identity=hashlib.sha256(json.dumps([(r['source'],r['sha256']) for r in prepared]).encode()).hexdigest()[:12]
    batch=ROOT/'data/processed/sam_candidates'/('_batch_'+folder.name+'_'+identity)
    if batch.exists(): raise ValueError('Batch output already exists; preserved: '+str(batch))
    batch.mkdir()
    spec=dict(name=f'SAM candidates — {folder.name} — {len(sources)} images [{identity}]',frames=frame_specs)
    (batch/'import.json').write_text(json.dumps(spec));(batch/'sources.json').write_text(json.dumps(prepared,indent=2))
    with tempfile.TemporaryDirectory(prefix='plumewatch-sam-batch-') as tmp:
        remote='/tmp/'+Path(tmp).name
        try:
            docker('exec','cvat_server','mkdir','-p',remote)
            docker('cp',str(batch/'import.json'),f'cvat_server:{remote}/import.json')
            for row in prepared: docker('cp',str(Path(row['output'])/row['png']),f"cvat_server:{remote}/{row['png']}")
            try: docker('exec','-i','cvat_server','python','manage.py','shell',code='WORK='+repr(remote)+'\n'+IMPORT)
            finally: subprocess.run([DOCKER,'cp',f'cvat_server:{remote}/task.json',str(batch/'cvat_task.json')],capture_output=True)
            docker('cp',f'cvat_server:{remote}/imported.json',str(batch/'imported_annotations.json'))
        finally: subprocess.run([DOCKER,'exec','cvat_server','rm','-rf','--',remote],capture_output=True)
    saved=json.loads((batch/'imported_annotations.json').read_text())['shapes']
    task=json.loads((batch/'cvat_task.json').read_text())
    indices={row['png']:row['frame'] for row in task['frames']}
    for row in prepared:
        out=Path(row['output']);inverse={v:int(k) for k,v in row['group_map'].items()}
        polygons=[dict(group=inverse[s['group']],points=s['points']) for s in saved if s['frame']==indices[row['png']]]
        with rasterio.open(row['source']) as src: valid=usable(src.read())
        with np.load(out/'masks.npz') as archive: masks=archive['masks']
        verify_polygons(polygons,masks,valid,list(inverse.values()))
    (batch/'verification.json').write_text(json.dumps(dict(frames=len(prepared),polygons=len(saved),native_grid_round_trip='passed for every frame',candidate_regions=next_group-1),indent=2))
    print('COMPLETE',json.dumps(task),flush=True);print('BATCH_OUTPUT',batch,flush=True)

if __name__=='__main__': main()
