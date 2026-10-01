import unittest

import numpy as np
import torch

from data import normalized_input
from model import UNet
from run import PATCH, positions


class ExperimentChecks(unittest.TestCase):
    def test_unet_and_inference_tiles(self):
        with torch.inference_mode():
            result = UNet()(torch.zeros(1, 10, PATCH, PATCH))
        self.assertEqual(tuple(result.shape), (1, 3, PATCH, PATCH))
        for length in (2035, 2042, 2056):
            covered = np.zeros(length, dtype=bool)
            for start in positions(length):
                covered[start:start + PATCH] = True
            self.assertTrue(covered.all())

    def test_invalid_pixels_are_filled_after_normalization(self):
        data = np.ones((12, 4, 4), dtype='float32')
        data[10] = 6
        data[11] = 1
        data[:10, 2, 2] = -9999
        data[11, 0, 0] = 0
        image, valid = normalized_input(data, np.ones(10, dtype='float32'),
                                        np.ones(10, dtype='float32'))
        self.assertFalse(valid[2, 2])
        self.assertFalse(valid[0, 0])
        self.assertTrue((image[:, 2, 2] == 0).all())
        self.assertTrue((image[:, 0, 0] == 0).all())


if __name__ == '__main__':
    unittest.main()
