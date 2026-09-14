# PlumeWatch

Shiny for Python dashboard for inspecting GEE-exported Sentinel-2 scenes and running the current PlumeWatch model. The interface uses frosted panels, a Leaflet image map, native-resolution inference, and downloadable GeoTIFF results.

## Run locally

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/shiny run --reload --port 8000 app.py
```

Open http://127.0.0.1:8000. Python 3.11+ is recommended; this build was tested with Python 3.14. The bundled model requires scikit-learn 1.8.0.

1. The Wellington example opens automatically. Alternatively choose a `.tif` from the reusable GEE script's **scene export**.
2. Click **Classify image**. Processing runs in a worker thread while the interface remains responsive.
3. Switch Original / Overlay / Classes, toggle layers, adjust opacity, or change the minimum winning-class score. These controls do not retrain or rerun the model.
4. Click the map for approximate preview-pixel information.
5. Download the ZIP containing native-grid class IDs, winning-class scores, and a summary for the selected threshold.

## Inputs and current model

Supported files have exactly these band descriptions: B2, B3, B4, B5, B6, B7, B8, B8A, B11, B12, SCL, valid. Reflectance must already be scaled to floating-point values by the GEE exporter. The grid must be north-up, 10 m and projected in metres. Maximum size is 250 MB and 10 million pixels per file. For a split GEE export, upload one tile at a time; this version does not merge tiles.

The installed model is **baseline_v1**, the original two-class Hutt pilot: 0 = background/normal water, 1 = plume. Multiclass labels are being collected, but the multiclass model has not been trained. No water mask is applied. Land may be predicted as plume, so the area strip reports provisional class footprints, not validated plume extent. Model scores are not calibrated probabilities or area error bounds.

The summary separates confident class pixels, uncertain pixels (winning-class score below the chosen threshold), and quality-excluded pixels. Areas use the original projected pixel grid. Downloads retain raw predictions even below the display threshold, with scores in a separate raster. Map imagery and click inspection use a downsampled EPSG:3857 preview; scores in that preview are rounded down to whole percentages.

Each browser session has a temporary working directory. Uploaded files are copied there, never used as model files, and removed when the session ends. Up to two operations run concurrently per Python process. This is a local/course prototype; public deployment should set request-size limits and resource limits at the hosting layer.

## Files

- `app.py`: Shiny interface and session workflow.
- `processing.py`: input checks, preview reprojection, windowed model inference and exports.
- `www/app.css`, `www/app.js`: glass styling and map interactions.
- `tests/test_processing.py`: raster validation and area-accounting tests.
- `reusable_plume_export.js`, `GEE_QUICK_START.md`: imagery and label preparation.

The older `train_baseline.py` and `classify_scene.py` remain as the original pilot workflows. The dashboard does not alter their data or retrain the model. All paths for the dashboard are relative to this repository.

Leaflet 1.9.4 is vendored under `www/` (BSD-2-Clause license in `www/LEAFLET-LICENSE`). OpenStreetMap provides the surrounding context map and requires an internet connection; uploaded image previews remain viewable without it. Basemap tile requests disclose the viewed map region to OpenStreetMap, but do not transmit the uploaded raster.

## Checks

```sh
.venv/bin/python -m unittest discover -s tests -v
```
