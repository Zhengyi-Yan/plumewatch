import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET
import numpy as np
import rasterio
from rasterio.transform import from_origin
import annotation_pipeline as pipeline


class AnnotationPipelineTests(unittest.TestCase):
    def test_sam_rle_roundtrip_and_overlap(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('sam_interactor', pipeline.ROOT/'integrations/cvat-sam2/main.py')
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        expected = np.zeros((8, 11), dtype=bool)
        expected[2:6, 3:8] = True
        expected[3, 4] = False  # preserve holes and nonzero crop offsets
        rle = adapter.mask_to_rle(expected)
        left, top, right, bottom = rle[-4:]
        image = ET.fromstring('<image name="test.png" width="11" height="8"/>')
        shape = ET.SubElement(image, 'mask', label='plume', left=str(left), top=str(top), width=str(right-left+1), height=str(bottom-top+1), rle=', '.join(map(str, rle[:-4])))
        result = pipeline.polygon_mask(image, expected.shape)
        np.testing.assert_array_equal(result == 1, expected)
        self.assertTrue((result[~expected] == 255).all())
        ET.SubElement(image, 'polygon', label='land', points='3,2;5,2;5,3;3,3')
        with self.assertRaisesRegex(ValueError, 'Overlapping'):
            pipeline.polygon_mask(image, expected.shape)
        image.remove(image[-1])
        shape.set('rle', '0,999999999')
        with self.assertRaisesRegex(ValueError, 'RLE'):
            pipeline.polygon_mask(image, expected.shape)
        self.assertEqual(adapter.mask_to_rle(np.zeros((3, 4), dtype=bool)), [])
        with self.assertRaisesRegex(ValueError, 'outside'):
            adapter.prompt_points([[float('nan'), 2]], 11, 8)

    def test_export_to_reflectance_and_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transform = from_origin(600000, 5200000, 10, 10)
            data = np.full((12, 4, 4), .1, dtype='float32')
            data[10] = 6
            data[11] = 1
            data[11, 0, 0] = 0
            with rasterio.open(root/'source.tif', 'w', driver='GTiff', width=4, height=4, count=12, dtype='float32', crs='EPSG:32759', transform=transform, nodata=-9999) as dst:
                dst.write(data)
                dst.descriptions = tuple(pipeline.BANDS)
            record = dict(png='scene.png', source_tif='source.tif', width=4, height=4, crs='EPSG:32759', transform=list(transform)[:6])
            xml = '<annotations><image name="scene.png" width="4" height="4"><polygon label="plume" points="0,0;2,0;2,2;0,2"/><polygon label="shallow_water" points="2,2;4,2;4,4;2,4"/></image></annotations>'
            (root/'annotations.xml').write_text(xml)
            with patch.object(pipeline, 'ROOT', root):
                pipeline.convert([root/'annotations.xml'], [record], root/'masks')
            mask_path = root/'masks/scene_mask.tif'
            with rasterio.open(mask_path) as src:
                mask = src.read(1)
                self.assertEqual(src.transform, transform)
                self.assertEqual(src.nodata, 255)
            self.assertEqual(mask[0,0], 255)
            self.assertEqual(mask[0,1], 1)
            self.assertEqual(mask[3,3], 2)
            self.assertEqual(mask[0,3], 255)
            x, y = pipeline.training_pixels(root/'source.tif', mask_path)
            self.assertEqual(x.shape, (7,10))
            np.testing.assert_allclose(x, .1)
            self.assertEqual(set(y), {1,2})
            image = ET.fromstring(xml).find('image')
            ET.SubElement(image, 'polygon', label='land', points='0,0;2,0;2,2;0,2')
            with self.assertRaisesRegex(ValueError, 'Overlapping'):
                pipeline.polygon_mask(image, (4,4))
            image.remove(image[-1])
            image[0].set('label', 'typo')
            with self.assertRaisesRegex(ValueError, 'Unknown label'):
                pipeline.polygon_mask(image, (4,4))
            rgb = pipeline.render_rgb(data)
            self.assertEqual(rgb.shape, (4,4,3))
            self.assertTrue((rgb[0,0] == 0).all())
            self.assertTrue((rgb[0,1] > 0).all())

    def test_candidates_ignored_but_reviewed_auto_retained(self):
        image = ET.fromstring('<image name="test.png" width="4" height="4"/>')
        ET.SubElement(image, 'polygon', label='candidate', points='0,0;4,0;4,4;0,4')
        ET.SubElement(image, 'polygon', label='plume', source='auto', points='0,0;2,0;2,2;0,2')
        ET.SubElement(image, 'polygon', label='candidate', points='0,0;4,0;4,4;0,4')
        mask = pipeline.polygon_mask(image, (4, 4))
        self.assertTrue((mask[:2, :2] == 1).all())
        self.assertEqual(int((mask == 255).sum()), 12)

    def test_split_leakage(self):
        rows = [dict(site='same', event_group='a', acquisition='a', split='train'), dict(site='same', event_group='b', acquisition='b', split='test')]
        with self.assertRaisesRegex(ValueError, 'site'):
            pipeline.check_splits(rows)


if __name__ == '__main__':
    unittest.main()
