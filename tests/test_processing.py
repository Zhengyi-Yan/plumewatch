"""One end-to-end check that both trained models share a valid native grid."""
import tempfile
import pickle
import unittest
from pathlib import Path
import numpy as np
import rasterio
from rasterio.transform import from_origin
from processing import smooth_plume_preview, ROOT, BANDS, classify_rf, classify_unet, classify_svm, load_svm_model, disagreement_km2, make_download, prepare_scene, summary


class TwoModelWorkflowTest(unittest.TestCase):
    def test_display_smoothing_preserves_land_nodata_and_inputs(self):
        classes = np.zeros((7, 7), dtype='uint8')
        classes[:, 0] = 255
        classes[:, 1] = 3
        scores = np.zeros((7, 7), dtype='float32')
        scores[:, 0] = -9999
        scores[:, 1] = 1
        scores[3, 4] = 1
        original = scores.copy()
        smoothed = smooth_plume_preview(scores, classes)
        np.testing.assert_array_equal(scores, original)
        np.testing.assert_array_equal(smoothed[:, :2], scores[:, :2])
        land_only = original.copy(); land_only[3, 4] = 0
        self.assertEqual(smooth_plume_preview(land_only, classes)[3, 2], 0)
        self.assertTrue(0 < smoothed[3, 4] < 1)
        self.assertGreater(smoothed[3, 3], 0)
        strong = smooth_plume_preview(scores, classes, sigma=5)
        self.assertLess(strong[3, 4], smoothed[3, 4])
        np.testing.assert_array_equal(strong[:, :2], scores[:, :2])
        constant = np.full((7, 7), .4, dtype='float32')
        constant[:, 0] = -9999
        np.testing.assert_allclose(smooth_plume_preview(constant, classes)[classes == 0], .4)


    def test_real_checkpoints_preserve_grid_and_export_three_classes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'scene.tif'
            data = np.full((12, 32, 32), .025, dtype='float32')
            data[2, :, 16:] = .08
            data[10] = 6
            data[11] = 1
            data[11, 0] = 0
            data[10, 1] = 9
            profile = dict(driver='GTiff', count=12, height=32, width=32, dtype='float32',
                           transform=from_origin(320000, 5430000, 10, 10), crs='EPSG:32760', nodata=-9999)
            with rasterio.open(source, 'w', **profile) as dst:
                dst.write(data)
                for index, band in enumerate(BANDS, 1):
                    dst.set_band_description(index, band)
            scene = prepare_scene(source)
            results = [classify_rf(scene, root / 'rf'), classify_unet(scene, root / 'unet'), classify_svm(scene, root / 'svm')]
            for result in results:
                pred, score = result['prediction'], result['score']
                self.assertTrue(set(np.unique(pred)).issubset({0, 1, 3, 255}))
                self.assertTrue((pred[:2] == 255).all())
                self.assertTrue(np.array_equal(pred == 255, score == -9999))
                self.assertTrue(np.isfinite(score[pred != 255]).all())
                plume = result['plume_score']
                self.assertTrue(np.array_equal(pred == 255, plume == -9999))
                self.assertTrue(((plume[pred != 255] >= 0) & (plume[pred != 255] <= 1)).all())
                with rasterio.open(result['output_dir'] / 'plume_score.tif') as dst:
                    self.assertEqual(dst.transform, profile['transform'])
                    self.assertEqual(dst.nodata, -9999)
                import base64
                self.assertEqual(set(result['map']['smoothedPlumeScores']), {'light', 'medium', 'strong'})
                for preview in result['map']['smoothedPlumeScores'].values():
                    self.assertEqual(len(base64.b64decode(preview)), result['map']['width'] * result['map']['height'])
                self.assertEqual(len(base64.b64decode(result['map']['plumeScores'])),
                                 result['map']['width'] * result['map']['height'])
                report = summary(result, .7)
                self.assertEqual(report['valid_pixels'], 30 * 32)
                self.assertAlmostEqual(sum(report[name] for name in
                    ['visible_plume_km2', 'normal_water_km2', 'land_km2', 'uncertain_km2']),
                    report['analysed_km2'])
                with rasterio.open(result['output_dir'] / 'classification.tif') as dst:
                    self.assertEqual(dst.transform, profile['transform'])
                    self.assertEqual(dst.crs, rasterio.crs.CRS.from_epsg(32760))
                self.assertTrue(make_download(result, .7).exists())
            self.assertGreaterEqual(disagreement_km2(results[0], results[1]), 0)
            svm = load_svm_model()
            good = results[2]['prediction'] != 255
            features = data[:10, good].T
            expected = svm.predict(features)
            np.testing.assert_array_equal(results[2]['prediction'][good], expected)
            probabilities = svm.predict_proba(features)
            np.testing.assert_allclose(results[2]['plume_score'][good], probabilities[:,1], atol=1e-7)
            columns = np.searchsorted(svm.classes_, expected)
            np.testing.assert_allclose(results[2]['score'][good], probabilities[np.arange(len(expected)), columns], atol=1e-7)
            np.testing.assert_array_equal(svm.predict(features), svm['svc'].predict(svm['scale'].transform(features)))



    def test_svm_keeps_native_class_when_probability_argmax_disagrees(self):
        model = load_svm_model()
        with (ROOT / 'data/processed/multiclass_rf_v2_20260930/samples.pkl').open('rb') as stream:
            samples = pickle.load(stream)
        x = np.concatenate([item[2][:200] for item in samples])
        expected = model.predict(x)
        probabilities = model.predict_proba(x)
        different = np.flatnonzero(expected != model.classes_[probabilities.argmax(1)])
        self.assertGreater(len(different), 0)
        ids = different[:32]
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'native_svm.tif'
            data = np.zeros((12, 1, len(ids)), dtype='float32')
            data[:10, 0] = x[ids].T
            data[10] = 6
            data[11] = 1
            with rasterio.open(source, 'w', driver='GTiff', count=12, height=1, width=len(ids),
                               dtype='float32', transform=from_origin(320000, 5430000, 10, 10),
                               crs='EPSG:32760', nodata=-9999) as dst:
                dst.write(data)
                dst.descriptions = tuple(BANDS)
            result = classify_svm(prepare_scene(source), Path(folder) / 'svm')
            np.testing.assert_array_equal(result['prediction'][0], expected[ids])
            columns = np.searchsorted(model.classes_, expected[ids])
            np.testing.assert_allclose(result['score'][0], probabilities[ids, columns], atol=1e-7)


if __name__ == '__main__':
    unittest.main()
