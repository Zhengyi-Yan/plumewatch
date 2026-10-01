from pathlib import Path
import json
import numpy as np
import rasterio
from rasterio.enums import Resampling
from PIL import Image,ImageDraw
O=Path(__file__).resolve().parent
rows=[r for r in json.loads((O/'audit.json').read_text()) if r.get('status')!='candidate_only']
canvas=Image.new('RGB',(1920,7*205),'white');draw=ImageDraw.Draw(canvas)
for i,r in enumerate(rows):
 path=Path(__file__).resolve().parents[2]/'data/processed/cvat_masks_v2_20260930'/(Path(r['name']).stem+'_mask.tif')
 with rasterio.open(r['source']) as src:
  data=src.read([3,2,1],out_shape=(3,170,240),resampling=Resampling.bilinear)
 rgb=(np.clip(np.nan_to_num(data)/.25,0,1)**(1/1.2)*255).astype('uint8').transpose(1,2,0)
 with rasterio.open(path) as src: m=src.read(1,out_shape=(170,240),resampling=Resampling.nearest)
 over=rgb.copy()
 for cls,c in [(0,[20,100,255]),(1,[255,40,40]),(3,[240,210,30])]:over[m==cls]=(.5*rgb[m==cls]+.5*np.array(c)).astype('uint8')
 x=(i%4)*480;y=(i//4)*205
 canvas.paste(Image.fromarray(rgb),(x,y+30));canvas.paste(Image.fromarray(over),(x+240,y+30))
 label=r['name'].replace('_UNMASKED','').replace('_S2_SR_L2A_12band_Float32','').replace('_S2_L2A_12band','').replace('_cvat.png','')
 draw.text((x+3,y+2),label[:67],fill='black')
 draw.text((x+3,y+15),'RGB | reviewed: red=plume blue=water yellow=land',fill='black')
canvas.save(O/'annotation_contact_sheet.jpg')
