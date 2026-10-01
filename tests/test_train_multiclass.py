import unittest

import numpy as np

from train_multiclass import groups_for, scores


class MulticlassTrainingTests(unittest.TestCase):
    def test_related_scenes_stay_in_one_group(self):
        def scene(site, event, acquisition, x):
            return {'site': site, 'event_group': event, 'acquisition': acquisition,
                    'crs': 'EPSG:32760', 'transform': [10, 0, x, 0, -10, 100],
                    'width': 10, 'height': 10}

        records = [scene('A', 'one', 't1', 0), scene('A', 'two', 't2', 1000),
                   scene('B', 'two', 't3', 2000), scene('C', 'three', 't4', 3000),
                   scene('D', 'four', 't5', 3050)]
        groups = groups_for(records)
        self.assertEqual(len(set(groups)), 2)
        self.assertEqual(groups[0], groups[1])
        self.assertEqual(groups[1], groups[2])
        self.assertEqual(groups[3], groups[4])
        self.assertNotEqual(groups[0], groups[3])

    def test_plume_scores_use_three_class_confusion(self):
        result = scores(np.array([[8, 2, 0], [1, 7, 2], [0, 1, 9]]))
        self.assertAlmostEqual(result['classes']['plume']['precision'], 0.7)
        self.assertAlmostEqual(result['classes']['plume']['recall'], 0.7)
        self.assertAlmostEqual(result['classes']['plume']['iou'], 7 / 13)


if __name__ == '__main__':
    unittest.main()
