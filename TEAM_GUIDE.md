# PlumeWatch teammate guide

This guide covers running the current dashboard, reviewing predictions and understanding the data pipeline. You do **not** need to train a model, run SAM, install CVAT or connect Google Earth Engine just to classify an existing supported image.

## 1. What you need

- Git and Python, with permission to create virtual environments and install packages.
- The repository, which includes the **three active trained model files** and Wellington example.
- A browser and enough memory for the source scene, model outputs and previews. Large images use considerably more memory than their compressed file size.

**Verified setup:** macOS, dashboard Python 3.14.3 and a separate U-Net Python 3.12.2 environment. The commands below use that setup. Linux x86-64 dependency resolution with prebuilt wheels has been checked for both environments; a full Linux installation and runtime have not been tested here. Native Windows is **not supported unchanged**: the dashboard looks for `experiments/unet/.venv/bin/python`, whereas Windows virtual environments use `Scripts/python.exe`. Windows teammates can try the Linux instructions inside WSL2, but that route has not been verified. Do not copy another machine's virtual environments; recreate them locally.

The U-Net worker uses Apple Metal/MPS when available and otherwise CPU. It does not currently select CUDA. CPU inference may be substantially slower.

## 2. Download the code and install dependencies

Follow the [full installation guide in README](README.md#full-installation-guide), which includes macOS commands, Windows/WSL setup, Linux environments, included model locations, checks and startup. Return here for the dashboard controls and pipeline explanation.

The dashboard and U-Net environments are separate. Run commands from the repository root and recreate environments locally rather than copying them between machines.

## 3. Included trained models

The active model files are included in GitHub and already sit in the locations used by the dashboard:

```text
plumewatch/
├── data/processed/
│   ├── multiclass_rf_v2_20260930/model.pkl
│   └── svm_rbf_20261001/model.pkl
└── experiments/unet/outputs/
    └── expanded_all_data_20260930/model.pt
```

No separate model transfer or training is needed. For an older checkout, run `git pull --ff-only` from the repository root. The Wellington example is included at `hutt-test/hutt_20210723_full_scene_v1.tif`. Other generated checkpoints, training caches and most imagery remain ignored.

RF and U-Net are computed together when either is requested, so install both Python environments from README. SVM runs separately when selected. Do not substitute the historical `results/baseline_v1/model.pkl`; it is not the active dashboard RF.

## 4. Start the dashboard

```sh
.venv/bin/python -m shiny run --host 127.0.0.1 --port 8000 app.py
```

Open **http://127.0.0.1:8000** in your browser. Leave the terminal running; press **Ctrl+C** there to stop the dashboard. If port 8000 is already in use, choose another port, for example `--port 8001`, and use the matching browser address.

The Wellington example should appear automatically. This verifies scene loading, not model inference or accuracy. To check the installed models on a small synthetic input without retraining:

```sh
.venv/bin/python -m unittest discover -s tests -p test_processing.py -v
```

This integration check exercises actual checkpoints and raster handling. Passing it does not establish performance on new plume scenes.

## 5. Classify and review a scene

1. Use **Load example scene**, or **Open a scene** to upload a supported GeoTIFF.
2. Select **Random forest**, **U-Net** or **SVM**.
3. Click **Classify scene**. RF/U-Net runs both models; SVM runs independently. Wait for the completion message before reviewing results.
4. Switch between completed models to compare their results without rerunning inference. Loading another scene clears the previous scene's results.
5. Review the imagery and predictions, then use **Export selected model** to save that model's output ZIP.

SVM can take several minutes on a large image because it uses an exact RBF classifier. RF/U-Net inference also depends on scene size and hardware. Changing display controls does not retrain any model.

| Map view | What it shows |
|---|---|
| Original | Sentinel-2 RGB preview. |
| Overlay | Class colours over the RGB image. |
| Classes | Classification with the imagery subdued. |
| Swipe | A movable divider between original imagery and classification. |
| Plume score | The selected model's score for plume, including pixels where another class wins. |
| Disagreement | RF versus U-Net when either is selected; RF versus SVM when SVM is selected. Both corresponding results must exist. |

The **minimum predicted-class score** controls which predicted classes appear and contribute to the displayed class areas. It is not a plume-detection threshold: at 0%, a pixel where water wins still remains water. Score and disagreement views ignore this display threshold.

**Score appearance** switches between the soft colour ramp and the original colours. **Smooth display** and its strength affect the plume-score preview only. They can reduce visual speckling but hide small details; they do not improve measured accuracy, alter the model's classifications, change area counts or smooth exported rasters. Turn smoothing off to inspect the original scores.

The map is a downsampled preview, so clicked pixels are preview pixels. Native-grid outputs are the authoritative saved model results. OpenStreetMap tiles and external fonts/icons need internet access; the satellite image itself remains available without basemap tiles.

## 6. Which input images work?

An ordinary RGB image, a `.visualize()` export, or an arbitrary ten-band TIFF will not satisfy the dashboard's input contract. Use a single-acquisition export compatible with the repository's [scene exporter](export_all_plume_scenes.js), and check the settings before exporting a new area.

| Requirement | Expected value |
|---|---|
| Product | Sentinel-2 L2A, normally `COPERNICUS/S2_SR_HARMONIZED`. |
| Bands and descriptions, in exact order | `B2, B3, B4, B5, B6, B7, B8, B8A, B11, B12, SCL, valid`. |
| Reflectance | Floating point; Sentinel-2 integer values multiplied by `0.0001`. |
| Grid | North-up 10 m pixels, projected CRS in metres, no rotation/skew. |
| Missing data | Export convention `-9999`; `valid` equals 1 for available input pixels. |
| Size limits | Maximum 250 MiB file size and 10 million source pixels. |
| Acquisition | One image; no before-image input or averaging across dates. |

The models use the first **ten** bands. `SCL` and `valid` are screening inputs, not model features. Available, finite spectra are analysed only where `valid == 1` and SCL is one of `2, 4, 5, 6, 7`. Other pixels are excluded, so downloading without an extra cloud mask does **not** mean the dashboard classifies every source pixel.

For export background, see [GEE quick start](GEE_QUICK_START.md). Older annotation export instructions may target a different file contract; verify the twelve bands, descriptions, scaling and grid above before using any export in the dashboard. A compatible format alone does not guarantee a cloud-free scene, correct date or visible plume.

## 7. What the downloads contain

Each export contains results for the **selected model**:

| File | Meaning |
|---|---|
| `classification.tif` | Raw predicted classes: `0` normal water, `1` visible plume, `3` land; `255` NoData/excluded. Class ID 2 is intentionally unused. |
| `model_score.tif` | Score for the predicted class; invalid pixels use NoData `-9999`. |
| `plume_score.tif` | Score for class 1 regardless of the winning class; invalid pixels use NoData `-9999`. |
| `summary.csv` | Areas and metadata, using the display threshold selected at export time. |
| `metadata.json` | Model identity, source/grid information, screening and interpretation notes. |

TIFFs retain the original CRS, affine transform, dimensions and pixel grid. Class-area totals use native pixels, not the map preview. The class TIFF is **not** filtered by the score slider, so a thresholded CSV can legitimately differ from a count of all raw class pixels. “Uncertain” area means valid pixels below the display threshold; it is not a fourth trained class.

Save exports before closing the session. Uploaded scenes and generated outputs are held in temporary session directories, not committed to Git or added automatically to the training dataset.

## 8. How the project works

```text
Single Sentinel-2 export → input validation and screening
                        → RF / U-Net / SVM inference
                        → native-grid classes and scores
                        → map previews, area summaries and downloadable results
```

| Component | Responsibility |
|---|---|
| `app.py` | Shiny interface, session state and inference requests. |
| `processing.py` | Input validation, RGB previews, RF/SVM inference, screening, summaries and exports. |
| `unet_worker.py` | U-Net inference in the separate PyTorch environment, using saved normalization and overlapping blended tiles. |
| `www/app.js`, `www/app.css` | Map interactions, score display and dashboard styling. |
| `annotation_pipeline.py` | Converts reviewed annotations into aligned training masks. |
| `REPORT.md` | Consolidated experiment results, protocols and limitations. |

RF uses saved per-pixel spectral features. U-Net also uses spatial context. SVM applies its saved StandardScaler once before the RBF classifier. Inference uses the supplied trained artifacts; it does not learn statistics from the uploaded scene, run SAM or train new models.

The separate training workflow is: acquire imagery → create CVAT previews → review annotations → export CVAT ZIPs → convert reviewed classes into masks → evaluate by held-out site/event → fit and distribute model artifacts. See [annotation workflow](ANNOTATION_WORKFLOW.md). Unreviewed `candidate` objects are skipped; reviewed supported labels are retained even if originally produced by SAM. Unannotated pixels remain ignored (`255`).

A fresh Git clone does **not** reproduce expanded training by itself: raw scenes, reviewed exports, masks, sample caches and relevant experiment protocols are also needed. `train_multiclass.py` covers the original experiment and must not be assumed to rebuild the expanded model. Do not retrain just to start the dashboard.

## 9. Interpreting results

The project maps **candidate visible sediment plumes**, not sediment concentration or verified physical plume boundaries. Predictions in unlabelled regions are not quantitatively right or wrong merely because they disagree with an incomplete annotation.

Model scores are uncalibrated and not directly comparable between models. SVM's predicted class can differ from the class with the highest reported probability; its predicted-class score follows the actual SVM prediction. Smooth boundaries, high scores and model agreement do not prove correctness.

The final all-data models do not have independent test scores for those final fitted artifacts. The Wellington example overlaps training data and cannot demonstrate generalization. Consult [the report](REPORT.md) for held-out experiment evidence and its limits; use genuinely unseen, independently reviewed scenes to assess new performance.

## 10. Troubleshooting

| Symptom | Check |
|---|---|
| Missing checkpoint / U-Net environment error | Exact model locations and `experiments/unet/.venv/bin/python`; RF/U-Net needs both models. |
| A Python import fails | Install the appropriate requirements using that environment's Python, not a different global interpreter. |
| Model cannot deserialize | Confirm the artifact and dependency versions with the owner; do not replace it with a different model or refit silently. |
| TIFF rejected | Check twelve band descriptions/order, floating-point scaling, projected 10 m grid and size limits. |
| Scene has holes or excluded areas | Inspect `SCL`, `valid`, missing spectra and source coverage; screening can exclude pixels even when RGB looks usable. |
| Faint area stays water at threshold 0 | Water still wins; inspect plume scores and original imagery. The slider does not change the classifier's decision. |
| No disagreement output | Classify the relevant pair on the same scene first. |
| Slow classification | Check selected model and source dimensions; exact RBF SVM and CPU U-Net are slower. Do not repeatedly resubmit while inference runs. |
| Browser cannot connect | Keep the server terminal open, use its actual port, and inspect any terminal error. |
| Old styling after updating | Refresh the browser; use a hard refresh if assets remain cached. |

When reporting a problem, include the scene filename, selected model, operating system/Python versions and the terminal error. For unexpected predictions, also include the original imagery and view/threshold settings so display effects can be separated from model behavior.
