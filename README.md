# PlumeWatch

Shiny for Python dashboard based on the [PlumeWatch Figma concept](https://www.figma.com/design/ZF9HZSM09M44cL9WTZpNJq?node-id=11-72). It opens a supported Sentinel-2 GeoTIFF, runs the expanded three-class Random Forest, final per-pixel LayerNorm U-Net and RBF SVM, and lets you switch the map between their results without rerunning inference. The map preview is downsampled; exports and area counts use the native source grid.

Start with [the teammate setup and dashboard guide](TEAM_GUIDE.md) for installation, model files, controls and troubleshooting. See [the consolidated experiment report](REPORT.md) for results, protocols and limitations.

## Full installation guide

### Before starting

The dashboard needs two Python environments. The three active trained models are included in the repository. You do **not** need CVAT, SAM, a GEE account, Node.js or training data to run inference on an existing supported image.

- **Verified locally:** macOS with dashboard Python 3.14.3 and U-Net Python 3.12.2.
- **Linux:** compatible environment paths, but a fresh installation has not been tested.
- **Windows:** use Ubuntu through WSL2. Native Windows needs a change to the hardcoded U-Net executable path; the full WSL installation has not been tested.
- **Hardware:** Apple Silicon uses MPS when available. Other machines currently use CPU for U-Net; CUDA is not selected automatically. Large images need substantially more RAM than their compressed file size.

Do not copy virtual environments between computers. Recreate them using the commands below. Homebrew installs the latest patch release in each Python series; the exact local patch versions above describe the tested machine, not a guarantee for every fresh installation.

### A. macOS installation

Open Terminal. If Homebrew is not installed, use its [official installer](https://brew.sh/):

```sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Complete the installer's printed **Next steps** to put Homebrew on your PATH, then run:

```sh
brew install git python@3.14 python@3.12

mkdir -p ~/projects
cd ~/projects
git clone https://github.com/Zhengyi-Yan/plumewatch.git
cd plumewatch

"$(brew --prefix python@3.14)/bin/python3.14" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

"$(brew --prefix python@3.12)/bin/python3.12" -m venv experiments/unet/.venv
experiments/unet/.venv/bin/python -m pip install --upgrade pip
experiments/unet/.venv/bin/python -m pip install -r experiments/unet/requirements.txt
```

If you already cloned the repository, enter that existing checkout rather than cloning again. Continue with **D. Included trained models**.

### B. Windows installation through WSL2

Requires Windows 11 or Windows 10 version 2004/build 19041 or newer. See [Microsoft's WSL installation instructions](https://learn.microsoft.com/en-us/windows/wsl/install). This is a proposed compatible route, not an end-to-end verified Windows installation.

Open **PowerShell as Administrator**:

```powershell
wsl --install -d Ubuntu
```

Restart Windows when prompted. Then open PowerShell:

```powershell
wsl --set-version Ubuntu 2
wsl -d Ubuntu
```

On the first Ubuntu launch, create a Linux username and password. Run the following **inside Ubuntu**, not PowerShell:

```sh
sudo apt update
sudo apt install -y git curl ca-certificates
```

Continue with **C. Linux/WSL Python environments**.

### C. Linux/WSL Python environments

These commands target Ubuntu/WSL. On an existing Ubuntu machine, first install `git`, `curl` and `ca-certificates` with the commands in section B. Other distributions use their own package manager.

Use [uv's official installer](https://docs.astral.sh/uv/getting-started/installation/) to obtain the two Python versions:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

mkdir -p ~/projects
cd ~/projects
git clone https://github.com/Zhengyi-Yan/plumewatch.git
cd plumewatch

uv python install 3.14.3 3.12.2

uv venv --python 3.14.3 .venv
uv pip install --python .venv/bin/python -r requirements.txt

uv venv --python 3.12.2 experiments/unet/.venv
uv pip install --python experiments/unet/.venv/bin/python \
  -r experiments/unet/requirements.txt
```

Keep the checkout in the Linux home directory under WSL. If a dependency fails to install, retain the error rather than silently changing pinned versions or retraining. PyTorch downloads can be large. Continue with section D.

### D. Included trained models

**All three active dashboard models are included when you clone or pull this repository.** No separate model download, copying or training is needed.

| Model | Included file |
|---|---|
| Random Forest | `data/processed/multiclass_rf_v2_20260930/model.pkl` |
| U-Net | `experiments/unet/outputs/expanded_all_data_20260930/model.pt` |
| SVM | `data/processed/svm_rbf_20261001/model.pkl` |

If you cloned an older version, update it from the repository root:

```sh
git pull --ff-only
```

RF/U-Net requests compute **both** models and require the separate U-Net Python environment installed above. SVM runs separately when selected. Training caches, other experiment checkpoints and downloaded imagery remain excluded; the Wellington example is included. Do not substitute the historical `results/baseline_v1/model.pkl` for the active RF.

### E. Verify the installation

From the repository root:

```sh
.venv/bin/python -c "import shiny, rasterio, sklearn, numpy, PIL; print('Dashboard imports OK')"
experiments/unet/.venv/bin/python -c "import torch, rasterio, numpy; print('U-Net imports OK:', torch.__version__); print('Apple GPU available:', torch.backends.mps.is_available())"

.venv/bin/python -m unittest discover -s tests -p test_processing.py -v
```

The tests require all three checkpoints and exercise actual inference and native-grid raster handling on a small synthetic input. They do not establish accuracy on new scenes. Apple GPU availability being false is expected on Intel Macs and Linux/WSL; inference uses CPU.

### F. Launch and stop

```sh
.venv/bin/python -m shiny run --host 127.0.0.1 --port 8000 app.py
```

Open **http://localhost:8000** in your browser. Keep the terminal running. Press **Ctrl+C** there to stop. If port 8000 is occupied, use `--port 8001` and open the corresponding address. No environment activation is needed because the command explicitly uses its Python executable.

The included Wellington image at `hutt-test/hutt_20210723_full_scene_v1.tif` loads automatically. It overlaps training data, so it is a setup example rather than an independent accuracy test.

For later launches on macOS/Linux:

```sh
cd ~/projects/plumewatch
.venv/bin/python -m shiny run --host 127.0.0.1 --port 8000 app.py
```

For later Windows launches, first enter Ubuntu from PowerShell:

```powershell
wsl -d Ubuntu
```

Then run the same two Linux launch commands above. If your checkout is elsewhere, use its actual path. Do not reinstall dependencies for each launch.

### G. Use the dashboard

Open a supported scene, choose a model and click **Classify scene**. RF/U-Net runs their comparison; SVM runs separately. Completed results remain available until you load a different image. Large-scene SVM inference can take several minutes.

Supported inputs are twelve-band GeoTIFFs from the [PlumeWatch scene exporter](export_all_plume_scenes.js), with exact band descriptions/order `B2, B3, B4, B5, B6, B7, B8, B8A, B11, B12, SCL, valid`, scaled floating-point reflectance and a north-up projected 10 m grid. Maximum file size is 250 MiB and maximum scene size is ten million pixels. RGB-only files are not suitable. The models use ten reflectance bands; `SCL` and `valid` screen input pixels.

The threshold slider filters class previews and displayed areas, not raw exported classifications. Score smoothing changes display only. Exports contain `classification.tif`, `model_score.tif`, `plume_score.tif`, `summary.csv` and `metadata.json`; TIFFs preserve the native source grid. Save exports before closing the session.

The [teammate guide](TEAM_GUIDE.md) explains each view, score interpretation, annotation/training flow and troubleshooting. It is a Markdown document in the repository root, next to this README. Model disagreement is not accuracy, scores are uncalibrated, and predictions are estimates of visible plume extent rather than sediment concentration or verified physical boundaries.

## Code

- `app.py`: Shiny UI and session workflow
- `processing.py`: scene validation, RF/SVM inference, native-grid results and exports
- `unet_worker.py`: U-Net inference in the existing PyTorch environment
- `www/app.css`, `www/app.js`: Figma-based layout and Leaflet review controls
- `tests/test_processing.py`: real-checkpoint native-grid integration check

Run the check with `.venv/bin/python -m unittest tests.test_processing -v`. Uploaded scenes remain in per-session temporary directories. Leaflet 1.9.4 is vendored in `www/`; OpenStreetMap provides surrounding basemap tiles when online. The satellite scene remains visible without basemap access.

## SVM checkpoint

`data/processed/svm_rbf_20261001/model.pkl` contains a single saved `StandardScaler` → exact RBF `SVC` pipeline, with C=1, gamma=scale, balanced class weights and seed42. All 49 reviewed frames across 13 linked groups contribute to 11,368 valid labelled pixel samples, capped by group/class and distributed across frames. This uses every reviewed frame, not every labelled pixel. Ignored pixels and unreviewed SAM candidates are absent from the reviewed masks used for training.

The dashboard applies the saved scaler once to the same ten scaled reflectance bands. It exports native `SVC.predict` class IDs and the Platt score for that predicted class; probability argmax may differ, so the score control is labelled “predicted-class score”. These scores are not externally calibrated. The all-data fit has no independent accuracy claim. Exact RBF inference can take several minutes for a large scene; SVM runs only when selected and requested.

Training settings, frame participation, sample hash and fitted scaling are recorded in `data/processed/svm_rbf_20261001/protocol.json`. Reproduce the fixed fit with `.venv/bin/python train_svm.py --out NEW_DIRECTORY` only when the required reviewed sample cache, manifests, masks and protocol artifacts are available; a Git clone alone is insufficient. Existing model files are never overwritten. No architecture or parameter search is performed.

Dashboard review tools include RGB/classification swipe, an uncalibrated plume-class score view, and disagreement highlighting (RF vs U-Net when RF/U-Net is selected; RF vs SVM when SVM is selected). Score and disagreement views ignore the predicted-class display threshold; class views still apply it. Excluded pixels stay transparent. Downloads now include `plume_score.tif` alongside the existing class and predicted-class score rasters.

Scene/model details show available source metadata, the selected checkpoint ID, inputs, screening and excluded area; acquisition dates cannot be independently verified when absent from the source metadata.

Check valid-pixel disagreement with `node tests/test_review.js`; raster checks use `.venv/bin/python -m unittest discover -s tests -p test_processing.py`.

The plume-score view defaults to a blue → teal → gold → orange ramp with opacity increasing from 0 to 80% as the plume score increases. Low scores reveal the original imagery. Choose **Original colours** under **Score appearance** to restore the previous dark-to-lime score view immediately. This affects display only, applies to all valid pixels regardless of winning class, and does not recalibrate or change predictions, area totals or exported rasters. Optional display-only smoothing offers 20 m, 50 m and 100 m strengths; it preserves land and NoData but can hide fine detail. Scores are uncalibrated; colour and transparency do not establish plume presence or a physical boundary.
