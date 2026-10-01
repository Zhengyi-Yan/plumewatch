"""Run with .venv/bin/python tests/test_sam_auto_label.py."""
import sys,tempfile
from pathlib import Path
import numpy as np,rasterio
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'integrations/cvat-sam2'))
from auto_label import prepare
from processing import BANDS

with tempfile.TemporaryDirectory() as folder:
    out=Path(folder);source=out/'test.tif'
    data=np.full((12,8,9),0.1,dtype='float32');data[10]=6;data[11]=1
    data[10,1,1]=9  # Cloud despite valid=1: must be hidden in the annotation PNG.
    data[11,2,2]=0
    data[0,3,3]=-9999
    with rasterio.open(source,'w',driver='GTiff',width=9,height=8,count=12,dtype='float32',crs='EPSG:32632',transform=rasterio.Affine(10,0,500000,0,-10,4800000),nodata=-9999) as dst:
        dst.write(data)
        for i,name in enumerate(BANDS,1): dst.set_band_description(i,name)
    rgb,valid,meta=prepare(source,out)
    assert not valid[1,1] and not valid[2,2] and not valid[3,3]
    assert (rgb[1,1]==0).all() and (rgb[2,2]==0).all() and (rgb[3,3]==0).all()
    assert valid[4,4] and (rgb[4,4]>0).all()
    assert Image.open(out/meta['png']).size==(9,8)
    assert meta['transform']==[10,0,500000,0,-10,4800000]
print('PASS: SCL, validity and spectral no-data exclusions; PNG dimensions and source grid preserved')
