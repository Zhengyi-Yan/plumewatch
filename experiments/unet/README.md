# Isolated ten-band U-Net experiment

This pilot uses the same 21 CVAT-labelled Sentinel-2 scenes and four linked
site/event folds as `train_multiclass.py`. It does not change the RF baseline,
CVAT annotations or the Shiny dashboard. Original ten-band reflectance TIFFs
are the inputs; RGB PNGs are only for display. Source masks keep unlabelled and
invalid pixels at 255, which are ignored in training and evaluation.

The model is a small four-level 10-channel U-Net with GroupNorm and three
outputs (`normal_water`, `plume`, `land`). `land=3` is remapped to channel 2 for
training and mapped back to 3 in output rasters. Each held-out fold learns its
normalisation and loss weights using only the other three groups. Training is
fixed at 40 epochs, 128 256-pixel patches per epoch, batch size 4, AdamW at
3e-4, and base seed 42 (fold seeds 43–46). No held-out group is used for stopping or tuning.

This describes the original pilot. The later 49-frame LayerNorm checkpoint is now used by the dashboard; do not delete this folder or its environment while that integration is in use. Results and limitations are consolidated in [REPORT.md](../../REPORT.md). Its `.venv/` and `outputs/` are ignored locally; no
source imagery is copied into it. Set up and run on the Mac with:

```sh
python3.12 -m venv experiments/unet/.venv
experiments/unet/.venv/bin/python -m pip install -r experiments/unet/requirements.txt
experiments/unet/.venv/bin/python experiments/unet/run.py smoke
experiments/unet/.venv/bin/python experiments/unet/run.py run
```

The `smoke` command refuses to run if PyTorch MPS is unavailable. The full run
also refuses a CPU fallback. The first command may require installing `pip` in
the venv; the local setup used `uv pip install --python experiments/unet/.venv/bin/python
-r experiments/unet/requirements.txt`.

Outputs:

- `outputs/metrics.json`: U-Net/RF scores on identical held-out labelled pixels,
  including per-scene plume scores and class confusion matrices.
- `outputs/checkpoints/`: one model checkpoint per fold; these are the original pilot fold models. A later all-data research checkpoint exists under `outputs/expanded_all_data_20260930/`, without an independent final-checkpoint test score.
- `outputs/predictions/`: six native-grid GeoTIFF class maps and uncalibrated
  plume-score maps, all made by models that did not train on their scene group.
- `outputs/galleries/`: clear and ambiguous four-panel comparisons plus six
  individual panels. `sources.json` records the source raster for every panel.

Prediction TIFFs preserve source CRS, transform and pixel dimensions. The
gallery resizes only its display copies: original RGB is shown bilinearly,
whereas CVAT, RF and U-Net classes use nearest-neighbour. Black/invalid pixels
are excluded using the source TIFF's validity and SCL bands, not PNG colour.
The class maps are checked on the native grid before rendering.

These metrics describe visually labelled pixels, not measured sediment or
whole-scene plume-area accuracy. U-Net softmax values are not calibrated
probabilities or area-error margins. The ambiguous April labels are unchanged.
