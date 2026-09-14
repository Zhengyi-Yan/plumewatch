import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import rasterio
from rasterio.transform import from_origin
from sklearn.ensemble import RandomForestClassifier

from processing import BANDS, prepare_scene, classify, summary, make_download


class RasterWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.path=self.root/'scene.tif'
        self.data=np.full((12,32,32),.02,dtype='float32')
        self.data[3:10]=.025
        self.data[2,:,16:]=.08
        self.data[10]=6; self.data[11]=1
        self.data[11,0,:]=0
        self.data[10,1,:]=9  # Even if valid says 1, reject cloud SCL.
        self.profile=dict(driver='GTiff',count=12,height=32,width=32,dtype='float32',
                          transform=from_origin(320000,5430000,10,10),crs='EPSG:32760',nodata=-9999)
        self.write()

    def write(self,descriptions=BANDS):
        with rasterio.open(self.path,'w',**self.profile) as dst:
            dst.write(self.data)
            for i,name in enumerate(descriptions,1): dst.set_band_description(i,name)

    def tearDown(self): self.temp.cleanup()

    def test_whole_flow_preserves_grid_and_accounts_for_every_pixel(self):
        x=np.array([[.02,.02,.02]+[.025]*7,[.02,.02,.08]+[.025]*7]*10)
        model=RandomForestClassifier(n_estimators=5,random_state=42).fit(x,[0,1]*10)
        scene=prepare_scene(self.path)
        with patch('processing.load_model',return_value=model): result=classify(scene,self.root/'out')
        report=summary(result,.7)
        self.assertEqual(report['valid_pixels'],30*32)
        self.assertAlmostEqual(report['predicted_plume_class_km2'],30*16*.0001)
        self.assertAlmostEqual(report['excluded_km2'],2*32*.0001)
        self.assertAlmostEqual(sum(report[k] for k in ['predicted_plume_class_km2','predicted_background_class_km2','uncertain_km2']),report['analysed_km2'])
        with rasterio.open(result['output_dir']/'classification.tif') as src:
            self.assertEqual(src.transform,self.profile['transform'])
            self.assertEqual(src.crs,rasterio.crs.CRS.from_epsg(32760))
            self.assertTrue((src.read(1)[:2]==255).all())
        self.assertTrue(make_download(result,.7).exists())

    def test_low_scores_in_either_class_are_uncertain(self):
        result={'prediction':np.array([[0,1,0,1,255]],dtype='uint8'),
                'score':np.array([[.6,.6,.9,.9,-9999]]),
                'scene':{'pixel_area':100,'name':'test'}}
        report=summary(result,.7)
        self.assertAlmostEqual(report['uncertain_km2'],.0002)
        self.assertAlmostEqual(report['predicted_plume_class_km2'],.0001)
        self.assertAlmostEqual(report['excluded_km2'],.0001)

    def test_bad_band_order_rejected(self):
        names=list(BANDS);names[0],names[1]=names[1],names[0];self.write(names)
        with self.assertRaisesRegex(ValueError,'12-band'): prepare_scene(self.path)

    def test_geographic_grid_rejected(self):
        self.profile.update(crs='EPSG:4326',transform=from_origin(174.8,-41.2,.0001,.0001));self.write()
        with self.assertRaisesRegex(ValueError,'metres'): prepare_scene(self.path)

    def test_unscaled_values_rejected(self):
        self.data[:10]*=10000;self.write()
        with self.assertRaisesRegex(ValueError,'unscaled'): prepare_scene(self.path)

    def test_south_up_grid_rejected(self):
        self.profile['transform']=rasterio.Affine(10,0,320000,0,10,5430000)
        self.write()
        with self.assertRaisesRegex(ValueError,'north-up'): prepare_scene(self.path)


if __name__=='__main__': unittest.main()
