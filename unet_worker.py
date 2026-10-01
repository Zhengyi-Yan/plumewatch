"""Run the final U-Net checkpoint with its existing PyTorch 3.12 environment."""
import sys
from pathlib import Path
import numpy as np
import rasterio
import torch
from torch import nn
from rasterio.windows import Window
from experiments.unet.model import UNet
from processing import BANDS, UNET_MODEL, _write_rasters, usable, validate

PATCH, STRIDE = 256, 192
VALUES = np.array([0, 1, 3], dtype='uint8')


class PixelNorm(nn.LayerNorm):
    def forward(self, x):
        return super().forward(x.permute(0, 2, 3, 1).contiguous()).permute(0, 3, 1, 2).contiguous()


def positions(size):
    if size <= PATCH:
        return [0]
    values = list(range(0, size - PATCH + 1, STRIDE))
    if values[-1] != size - PATCH:
        values.append(size - PATCH)
    return values


def load_model():
    # This fixed local checkpoint was produced by our training run; never load an uploaded model.
    bundle = torch.load(UNET_MODEL, map_location='cpu', weights_only=False)
    if bundle['bands'] != BANDS[:10] or bundle['classes'] != [0, 1, 3] or bundle['variant'] != 'pixelnorm':
        raise ValueError('U-Net checkpoint metadata does not match the dashboard.')
    model = UNet()
    for name, module in list(model.named_modules()):
        if isinstance(module, nn.GroupNorm):
            model.set_submodule(name, PixelNorm(module.num_channels, eps=module.eps))
    model.load_state_dict(bundle['state_dict'])
    return model.eval(), np.asarray(bundle['mean'], dtype='float32'), np.asarray(bundle['std'], dtype='float32')


def classify(path, out):
    torch.set_num_threads(4)
    model, mean, std = load_model()
    device = torch.device('mps' if torch.backends.mps.is_available() else 'cpu')
    model.to(device)
    with rasterio.open(path) as src:
        validate(src)
        height, width = src.shape
        # ponytail: full-scene accumulators fit the 10M-pixel limit; stream stripes if that limit rises.
        sums = np.zeros((3, height, width), dtype='float32')
        weights = np.zeros((height, width), dtype='float32')
        valid_all = np.zeros((height, width), dtype=bool)
        edge = np.maximum(np.hanning(PATCH), .1).astype('float32')
        blend = np.outer(edge, edge)
        with torch.inference_mode():
            for y in positions(height):
                for x in positions(width):
                    hh, ww = min(PATCH, height-y), min(PATCH, width-x)
                    data = src.read(window=Window(x, y, ww, hh))
                    valid = usable(data)
                    image = np.clip((data[:10] - mean[:, None, None]) / std[:, None, None], -5, 5)
                    image[:, ~valid] = 0
                    if hh < PATCH or ww < PATCH:
                        image = np.pad(image, ((0, 0), (0, PATCH-hh), (0, PATCH-ww)))
                    tensor = torch.from_numpy(np.ascontiguousarray(image[None], dtype='float32')).to(device)
                    probs = torch.softmax(model(tensor), dim=1)[0, :, :hh, :ww].cpu().numpy()
                    weight = blend[:hh, :ww]
                    sums[:, y:y+hh, x:x+ww] += probs * weight
                    weights[y:y+hh, x:x+ww] += weight
                    valid_all[y:y+hh, x:x+ww] |= valid
        if not valid_all.any() or not (weights > 0).all():
            raise ValueError('U-Net inference has no usable pixels or incomplete tile coverage.')
        sums /= weights[None]
        pred = VALUES[sums.argmax(axis=0)]
        score = sums.max(axis=0)
        pred[~valid_all] = 255
        score[~valid_all] = -9999
        plume_score = sums[1].copy()
        plume_score[~valid_all] = -9999
        _write_rasters(src, out, pred, score.astype('float32'), 'unet_pixelnorm_20260930', plume_score)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: unet_worker.py SOURCE.tif OUTPUT_DIR')
    classify(Path(sys.argv[1]), Path(sys.argv[2]))
