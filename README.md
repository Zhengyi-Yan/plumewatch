# PlumeWatch

Shiny for Python dashboard based on the [PlumeWatch Figma concept](https://www.figma.com/design/ZF9HZSM09M44cL9WTZpNJq?node-id=11-72). It opens a supported Sentinel-2 GeoTIFF, runs the expanded three-class Random Forest, final per-pixel LayerNorm U-Net and RBF SVM, and lets you switch the map between their results without rerunning inference. The map preview is downsampled; exports and area counts use the native source grid.

See [the consolidated experiment report](REPORT.md) for results, protocols and limitations.

## Run locally

The checked-in `requirements.txt` installs Shiny, Rasterio, scikit-learn, NumPy and Pillow for the dashboard. The U-Net uses the existing PyTorch 3.12 environment at `experiments/unet/.venv/bin/python` with `experiments/unet/requirements.txt`. The RF/U-Net comparison needs its two checkpoints; the optional SVM uses a third:

- `data/processed/multiclass_rf_v2_20260930/model.pkl`
- `experiments/unet/outputs/expanded_all_data_20260930/model.pt`

These generated model files are ignored by Git. The selected workflow fails clearly if a required checkpoint is absent; it does not download or retrain a model.

```sh
.venv/bin/shiny run --reload --port 8000 app.py
```

Open <http://127.0.0.1:8000>. The Wellington example loads automatically. You can upload another `.tif`/`.tiff` from the PlumeWatch GEE scene exporter (12 bands: B2, B3, B4, B5, B6, B7, B8, B8A, B11, B12, SCL, valid). Click **Classify scene** with RF or U-Net selected to run their existing comparison. Select **SVM** and click the same button to run SVM separately; completed results stay available until another scene is loaded. Original / Overlay / Classes changes the display only. The score slider hides pixels with low predicted-class scores in the preview and summary; the downloaded class raster retains raw predictions.

Inputs must be north-up projected 10 m scenes with scaled floating-point reflectance, at most 250 MB and 10 million pixels. Inference uses the existing SCL/valid screening policy. Class IDs are 0 normal water, 1 visible plume, 3 land, and 255 excluded. Downloads contain a native-grid class GeoTIFF, a predicted-class score GeoTIFF, a threshold-specific CSV and metadata.

The models' disagreement area identifies places to inspect; it is **not** an accuracy score. The final U-Net trained on all reviewed frames has no independent test score. All models' scores are uncalibrated and cannot be compared as probabilities. Predicted footprints are estimates, not measured sediment concentration or verified physical plume boundaries. The Wellington example overlaps training data and cannot validate generalization.

## Code

- `app.py`: Shiny UI and session workflow
- `processing.py`: scene validation, RF inference, native-grid results and exports
- `unet_worker.py`: U-Net inference in the existing PyTorch environment
- `www/app.css`, `www/app.js`: Figma-based layout and Leaflet review controls
- `tests/test_processing.py`: real-checkpoint native-grid integration check

Run the check with `.venv/bin/python -m unittest tests.test_processing -v`. Uploaded scenes remain in per-session temporary directories. Leaflet 1.9.4 is vendored in `www/`; OpenStreetMap provides surrounding basemap tiles when online. The satellite scene remains visible without basemap access.

## SVM checkpoint

`data/processed/svm_rbf_20261001/model.pkl` contains a single saved `StandardScaler` → exact RBF `SVC` pipeline, with C=1, gamma=scale, balanced class weights and seed42. All 49 reviewed frames across 13 linked groups contribute to 11,368 valid labelled pixel samples, capped by group/class and distributed across frames. This uses every reviewed frame, not every labelled pixel. Ignored pixels and unreviewed SAM candidates are absent from the reviewed masks used for training.

The dashboard applies the saved scaler once to the same ten scaled reflectance bands. It exports native `SVC.predict` class IDs and the Platt score for that predicted class; probability argmax may differ, so the score control is labelled “predicted-class score”. These scores are not externally calibrated. The all-data fit has no independent accuracy claim. Exact RBF inference can take several minutes for a large scene; SVM runs only when selected and requested.

Training settings, frame participation, sample hash and fitted scaling are recorded in `data/processed/svm_rbf_20261001/protocol.json`. Reproduce the fixed fit with `.venv/bin/python train_svm.py --out NEW_DIRECTORY`; existing model files are never overwritten. No architecture or parameter search is performed.

Dashboard review tools include RGB/classification swipe, an uncalibrated plume-class score view, and disagreement highlighting (RF vs U-Net when RF/U-Net is selected; RF vs SVM when SVM is selected). Score and disagreement views ignore the predicted-class display threshold; class views still apply it. Excluded pixels stay transparent. Downloads now include `plume_score.tif` alongside the existing class and predicted-class score rasters.

Scene/model details show available source metadata, the selected checkpoint ID, inputs, screening and excluded area; acquisition dates cannot be independently verified when absent from the source metadata.

Check valid-pixel disagreement with `node tests/test_review.js`; raster checks use `.venv/bin/python -m unittest discover -s tests -p test_processing.py`.

The plume-score view defaults to a blue → teal → gold → orange ramp with opacity increasing from 0 to 80% as the plume score increases. Low scores reveal the original imagery. Choose **Original colours** under **Score appearance** to restore the previous dark-to-lime score view immediately. This affects display only, applies to all valid pixels regardless of winning class, and does not recalibrate or change predictions, area totals or exported rasters. Optional display-only smoothing offers 20 m, 50 m and 100 m strengths; it preserves land and NoData but can hide fine detail. Scores are uncalibrated; colour and transparency do not establish plume presence or a physical boundary.
