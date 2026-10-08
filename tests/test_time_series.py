"""Known-area checks for alignment, shared validity, changes and weather failure."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import rasterio
from rasterio.transform import from_origin
from processing import BANDS
from time_series import common_grid, assemble, build_series, export_series, suggested_date


class SeriesTest(unittest.TestCase):
    def make_source(self,folder,name,left=300000,crs='EPSG:32632'):
        path=folder/name
        profile=dict(driver='GTiff',count=12,height=4,width=4,dtype='float32',crs=crs,
                     transform=from_origin(left,4800000,10,10),nodata=-9999)
        data=np.full((12,4,4),.03,dtype='float32');data[10]=6;data[11]=1
        with rasterio.open(path,'w',**profile) as dst:
            dst.write(data)
            for i,b in enumerate(BANDS,1): dst.set_band_description(i,b)
        return path

    def write_result(self,source,folder,classes):
        folder.mkdir()
        with rasterio.open(source) as src: profile={**src.profile,'count':1}
        with rasterio.open(folder/'classification.tif','w',**{**profile,'dtype':'uint8','nodata':255}) as dst: dst.write(classes.astype('uint8'),1)
        with rasterio.open(folder/'model_score.tif','w',**profile) as dst: dst.write(np.where(classes==255,-9999,.8).astype('float32'),1)
        return folder

    def test_shifted_grid_validity_change_export_and_weather_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            a=self.make_source(folder,'river_20200226.tif')
            b=self.make_source(folder,'river_20200228.tif',left=300010)
            entries=[{'path':str(a),'name':a.name,'date':'2020-02-26'}, {'path':str(b),'name':b.name,'date':'2020-02-28'}]
            # Native overlap is four rows x three columns, with one invalid pixel.
            earlier=np.zeros((4,4),dtype='uint8');earlier[0,1]=255;earlier[1,1:3]=1
            later=np.zeros((4,4),dtype='uint8');later[1,1:3]=1
            outputs=[self.write_result(a,folder/'a',earlier),self.write_result(b,folder/'b',later)]
            result=assemble(entries,outputs,'rf',0,folder/'comparison')
            self.assertAlmostEqual(result['overlap_km2'],.0012)
            self.assertAlmostEqual(result['shared_km2'],.0011)
            self.assertEqual(result['native_width'],3)
            self.assertAlmostEqual(result['rows'][0]['plume_km2'],.0002)
            self.assertAlmostEqual(result['pairs']['0-1']['both_km2'],.0001)
            self.assertAlmostEqual(result['pairs']['0-1']['earlier_only_km2'],.0001)
            self.assertAlmostEqual(result['pairs']['0-1']['later_only_km2'],.0001)
            with rasterio.open(folder/'comparison/change_2020-02-26_2020-02-28.tif') as src:
                self.assertEqual(src.transform,from_origin(300010,4800000,10,10))
                self.assertEqual(src.read(1)[0,0],255)
                self.assertEqual(set(np.unique(src.read(1))),{0,1,2,3,255})
            for n, expected in {'0':.0008,'1':.0002,'2':.0001}.items():
                self.assertAlmostEqual(result['frequency_km2'][n],expected)
            with rasterio.open(folder/'comparison/plume_frequency.tif') as src:
                self.assertEqual(src.read(1)[0,0],255)
                self.assertEqual(int((src.read(1)==2).sum()),1)
            calls=[]
            def weather(location,date):
                calls.append((location,date))
                if date=='2020-02-28': raise ValueError('archive unavailable')
                return {'totals_mm':{7:12.5},'location':location}
            with patch('time_series.classify_rf',side_effect=[{'output_dir':outputs[0],'map':{'modelId':'test-rf'}},{'output_dir':outputs[1],'map':{'modelId':'test-rf'}}]):
                result=build_series(list(reversed(entries)),'rf',0,folder/'batch',weather=weather)
            self.assertEqual([r['date'] for r in result['rows']],['2020-02-26','2020-02-28'])
            self.assertEqual(calls[0][0],calls[1][0])
            self.assertIsNone(result['rows'][1]['rainfall_7d_mm'])
            self.assertIn('archive unavailable',result['rows'][1]['weather_error'])
            self.assertTrue(export_series(result).is_file())
            filtered=assemble(entries,outputs,'rf',.9,folder/'filtered')
            self.assertEqual(filtered['shared_km2'],result['shared_km2'])
            self.assertTrue(all(r['plume_km2']==0 for r in filtered['rows']))
            for output in outputs:
                with rasterio.open(output/'classification.tif','r+') as dst:
                    dst.write(np.full((4,4),255,dtype='uint8'),1)
            with self.assertRaisesRegex(ValueError,'No pixels are valid'):
                assemble(entries,outputs,'rf',0,folder/'invalid')

    def test_reject_disjoint_crs_and_duplicate_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);a=self.make_source(folder,'a.tif');b=self.make_source(folder,'b.tif',left=400000)
            entries=[{'path':str(p),'name':p.name,'date':'2020-02-26'} for p in (a,b)]
            with self.assertRaisesRegex(ValueError,'no shared'):common_grid(entries)
            with self.assertRaisesRegex(ValueError,'distinct'):build_series(entries,'rf',0,folder/'output')
            b=self.make_source(folder,'c.tif',crs='EPSG:32760')
            with self.assertRaisesRegex(ValueError,'same projected CRS'):common_grid([{'path':str(a)},{'path':str(b)}])
        self.assertEqual(suggested_date('France_Var_20201003_S2.tif'),'2020-10-03')
        self.assertEqual(suggested_date('scene_without_date.tif'),'')
        self.assertEqual(suggested_date('scene_20201340.tif'),'')

if __name__=='__main__':unittest.main()
