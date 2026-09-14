"""Classify quality-valid pixels; outputs are unmasked by water, not area estimates."""
import csv,json,pickle,sys
from pathlib import Path
import numpy as np
import rasterio
from pyproj import Transformer
from PIL import Image,ImageDraw

root=Path(sys.argv[1]); out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True)
with (root/'results/baseline_v1/model.pkl').open('rb') as f: bundle=pickle.load(f)
with rasterio.open(root/'hutt-test/hutt_20210723_full_scene_v1.tif') as src:
    assert list(src.descriptions[:10])==bundle['bands']
    assert src.descriptions[10:]==('SCL','valid') and src.res==(10,10)
    data=src.read(); profile=src.profile.copy(); grid=src.transform
    xy=Transformer.from_crs(4326,src.crs,always_xy=True)
    with (root/'hutt-test/hutt_20210723_test-v2_all_samples.csv').open() as f: rows=list(csv.DictReader(f))
    x,y=xy.transform([float(r['longitude']) for r in rows],[float(r['latitude']) for r in rows])
    rr,cc=rasterio.transform.rowcol(grid,x,y)
    expected=np.array([[float(r[b]) for b in bundle['bands']] for r in rows])
    actual=data[:10,rr,cc].T
    delta=float(np.max(np.abs(expected-actual)))
    assert np.allclose(actual,expected,atol=1e-7,rtol=0), delta
    good=(data[11]==1)&np.isfinite(data[:10]).all(axis=0)&(data[:10]!=-9999).all(axis=0)
    flat=np.flatnonzero(good); features=data[:10].reshape(10,-1).T
    pred=np.full(good.size,255,dtype='uint8');prob=np.full(good.size,-9999,dtype='float32')
    model=bundle['model']; plume_index=list(model.classes_).index(1)
    for start in range(0,len(flat),50000):
        ix=flat[start:start+50000]; xx=features[ix]
        pred[ix]=model.predict(xx);prob[ix]=model.predict_proba(xx)[:,plume_index]
    pred=pred.reshape(good.shape);prob=prob.reshape(good.shape)
    for name,array,dtype,nodata in [('classification_unmasked',pred,'uint8',255),('plume_probability_unmasked',prob,'float32',-9999)]:
        profile.update(count=1,dtype=dtype,nodata=nodata,compress='deflate')
        with rasterio.open(out/(name+'.tif'),'w',**profile) as dst:
            dst.write(array,1);dst.set_band_description(1,name)
            dst.update_tags(water_mask='NONE',warning='Do not interpret as validated plume extent or area')
rgb=np.moveaxis(data[[2,1,0]],0,-1)
rgb=(np.clip(np.nan_to_num(rgb)/0.25,0,1)**(1/1.2)*255).astype('uint8')
rgb[(data[:3]==-9999).any(axis=0)]=[32,32,32]
overlay=rgb.copy();hit=pred==1
overlay[hit]=(overlay[hit]*0.5+np.array([255,55,30])*0.5).astype('uint8')
panels=[Image.fromarray(rgb),Image.fromarray(overlay)]
labels=json.loads((root/'hutt-test/hutt_20210723_test-v2_all_labels.geojson').read_text())['features']
for panel in panels:
    draw=ImageDraw.Draw(panel)
    for f in labels:
        points=[]
        for lon,lat in f['geometry']['coordinates'][0]:
            east,north=xy.transform(lon,lat);c,r=(~grid)*(east,north);points.append((c,r))
        color='yellow' if f['properties']['class_id']==1 else 'cyan'
        draw.line(points,fill=color,width=3)
        draw.text(points[0],f['properties']['polygon_id'].split('_')[-1],fill=color,stroke_width=1,stroke_fill='black')
canvas=Image.new('RGB',(panels[0].width*2,panels[0].height+70),'white');draw=ImageDraw.Draw(canvas)
for i,panel in enumerate(panels):canvas.paste(panel,(i*panel.width,70))
draw.text((12,10),'RGB | yellow: plume test polygons; cyan: background test polygons',fill='black')
draw.text((panels[0].width+12,10),'RED: model predicts plume | NO WATER MASK | NOT AN AREA ESTIMATE',fill='black')
canvas.save(out/'scene_comparison.png')
stats={'valid_pixels':int(good.sum()),'predicted_plume_pixels_before_water_mask':int(hit.sum()),
       'test_sample_max_band_difference':delta,'test_samples_checked':len(rows),
       'plume_predictions_by_SCL':{str(int(s)):int(((data[10]==s)&hit).sum()) for s in np.unique(data[10][good])},
       'warning':'No water mask applied. No plume area estimated. SCL classes are not reference truth.'}
(out/'scene_checks.json').write_text(json.dumps(stats,indent=2)+'\n');print(json.dumps(stats,indent=2))
