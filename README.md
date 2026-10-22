# PlumeWatch

PlumeWatch is a local web dashboard for mapping candidate sediment plumes in Sentinel-2 satellite imagery. It uses three trained machine-learning models — Random Forest, U-Net and SVM — to classify pixels as normal water, plume or land.

Review predictions on interactive maps, compare images across acquisition dates, view rainfall context and export georeferenced results and area summaries. Predictions estimate visible plume extent; they do not measure sediment concentration or confirm physical plume boundaries.

Start with [the teammate setup and dashboard guide](TEAM_GUIDE.md) for installation, model files, controls and troubleshooting. See [model evaluation and limitations](#model-evaluation-and-limitations) for the main results and retained evidence.

## Full installation guide

Install once, then use the launch instructions whenever you return. Choose your setup route:

| Platform | First-time setup | After setup |
|---|---|---|
| macOS with Apple Silicon (M-series) | [A. macOS installation](#a-macos-installation) | Run the checks in E, then launch with F |
| Intel/AMD 64-bit Windows | [B. Windows installer](#b-windows-installation-through-wsl2) | Use the **PlumeWatch** desktop shortcut |
| Ubuntu Linux / manual WSL setup | [C. Linux/WSL environments](#c-linuxwsl-python-environments) | Run the checks in E, then launch with F |

### Before starting

The repository includes all three trained models and a Wellington example image. You do **not** need training data, a Google Earth Engine account, CVAT, SAM or Node.js to use the dashboard. Additional imagery must meet the [supported input requirements](#g-use-the-dashboard).

The dashboard uses Python 3.14; U-Net runs in a separate Python 3.12 environment. Setup creates both. Do not copy virtual environments from another computer. Internet access is needed for installation; large scenes also need substantially more RAM than their compressed file size.

**Verification status:** the application and model checks have run locally on Apple Silicon macOS with Python 3.14.3 / 3.12.2. Linux x86-64 dependency resolution and automated installer logic checks have passed. On Windows 11 x86-64 with an existing Ubuntu/WSL2 installation, guided installation/model checks and desktop launcher startup, browser opening, graceful server stop/relaunch and failure handling have passed. The new update confirmation flow and fresh WSL/Ubuntu provisioning still need end-to-end Windows tests.

If a command fails, stop and retain its full error before continuing. A completed download or successful import alone does not verify the installation.

### A. macOS installation

These instructions target **Apple Silicon Macs**. The pinned PyTorch 2.9 dependency has no official Intel Mac wheels; PyTorch ended those builds after 2.2.x ([PyTorch announcement](https://pytorch.org/blog/pytorch2-2/)). This guide does not provide a verified Intel Mac installation route.

**1. Install the prerequisites.** Open Terminal. If Homebrew is missing, run its [official installer](https://brew.sh/) and complete its printed **Next steps** to add Homebrew to your PATH:

```sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Then install Git and both Python versions:

```sh
brew install git python@3.14 python@3.12
```

**2. Download the project.** For a new checkout:

```sh
mkdir -p ~/projects
cd ~/projects
git clone https://github.com/Zhengyi-Yan/plumewatch.git
cd plumewatch
```

Already cloned with GitHub Desktop, or downloaded and extracted the ZIP? Open Terminal in that repository folder and skip the clone commands. You should be in the folder containing `app.py` and `requirements.txt`. A separate fresh clone is preferable when testing installation, so existing environments or ignored files cannot hide missing setup steps.

The example location is `~/projects/plumewatch`; a Desktop folder works too. Use your actual repository path for later launches.

**3. Install the dashboard environment.** From the repository root:

```sh
"$(brew --prefix python@3.14)/bin/python3.14" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
```

**4. Install the U-Net environment.** In the same folder:

```sh
"$(brew --prefix python@3.12)/bin/python3.12" -m venv experiments/unet/.venv
experiments/unet/.venv/bin/python -m pip install --upgrade pip
experiments/unet/.venv/bin/python -m pip install -r experiments/unet/requirements.txt
```

The commands select each Python executable explicitly; no environment activation is needed. Homebrew installs its current patch release for each Python series, so your patch versions may differ from the locally tested versions above. Continue with **E. Verify the installation**, then **F. Launch and stop**.

### B. Windows installation through WSL2

Use the guided installer on **Intel/AMD 64-bit Windows 11 or Windows 10 build 19041 or newer**. It runs the dashboard inside Ubuntu/WSL2; no Windows Git or Python installation is needed. Native Windows Python and Windows ARM are not supported by this installer.

**Guided setup and launching have been tested on Windows 11 with existing Ubuntu/WSL2. The new update prompt and fresh WSL/Ubuntu provisioning remain unverified end to end on Windows.** Windows policy, disabled virtualization, insufficient disk/RAM or download restrictions can block setup. The installer reports errors and does not change your WSL memory limits.

1. [Download the project ZIP](https://github.com/Zhengyi-Yan/plumewatch/archive/refs/heads/main.zip) and choose **Extract All** to a local Windows folder. Keep the extracted files together. An existing Windows checkout containing the installer also works.
2. Double-click **`Install PlumeWatch.bat`** in the extracted project folder. Run it normally and accept its administrator prompt if Windows needs to enable WSL.
3. If asked to restart, save your work, restart Windows yourself and double-click the same installer again. It rechecks completed steps.
4. Create an Ubuntu username/password if prompted. If Ubuntu leaves you at a shell prompt, type `exit` to return to setup. Follow the installer prompts if a separate Ubuntu window opens. Enter your Ubuntu password if `sudo` asks; its characters are not displayed.
5. If an existing Ubuntu checkout is older than GitHub `main`, setup shows the installed and available commit IDs and asks whether to update. Close any running dashboard, then type `y` to accept. Pressing Enter or typing `n` declines the update, stops setup and keeps the existing app and Python environments.
6. Wait for **Installation and model checks passed**. Then double-click the **PlumeWatch** desktop shortcut. Keep its terminal window open while using the dashboard; press **Ctrl+C** there to stop it.

The installer creates both Python environments, installs dependencies including CPU PyTorch, checks the included models/example and runs RF/U-Net/SVM inference and raster/export checks. After success, **skip sections C–E** and continue with **G. Use the dashboard**. Also confirm browser classification, export and relaunch on the target Windows machine.

The application is stored at `~/projects/plumewatch` inside the `Ubuntu` distribution. Logs and the persistent launcher are saved under `%LOCALAPPDATA%\PlumeWatch`; you can remove the extracted installer folder after success. If setup fails, keep its error and `install-*.log`, then rerun the installer after resolving the problem.

If an older desktop launcher reports `Wsl/Service/WSL_E_DISTRO_NOT_FOUND` even though `wsl --list --verbose` shows `Ubuntu`, replace the installed launcher with `Start Dashboard.bat` from the latest project ZIP. From PowerShell in the extracted project folder, run:

```powershell
Copy-Item -LiteralPath '.\Start Dashboard.bat' -Destination (Join-Path $env:LOCALAPPDATA 'PlumeWatch\Start Dashboard.bat') -Force
```

The corrected launcher avoids CMD/WSL distribution-name quoting and stops on every nonzero exit code, including negative WSL errors. Replacing this file preserves Ubuntu and its Python environments; reinstalling is unnecessary for this launcher issue.

Rerunning setup reuses the existing environments and checks the actual Ubuntu checkout at `~/projects/plumewatch` against GitHub `main`. Downloading a new Windows ZIP alone does not update that checkout. An accepted update moves a clean `main` branch forward to the displayed GitHub commit without creating a merge commit; dependency installation and model checks then run against the updated code.

Setup stops if the origin is unexpected, the checkout is on another branch or detached, local commits prevent a fast-forward update, or local changes/untracked files need review before an available update. It also rechecks the checkout after confirmation and refuses to overwrite ignored local files that conflict with incoming files. It never resets, automatically stashes or discards local work, deletes Python environments, or retrains models. A failed version check stops setup instead of silently using a stale version. Review any reported local work before rerunning setup. Updates are tested using temporary Git repositories; the interactive Windows update flow still needs verification.

If an existing Ubuntu uses WSL1, setup asks before converting it; save and back up that distribution's work first. The optional Gabrielle imagery is a separate download described below.

<details>
<summary>Manual Windows/WSL setup instead of the installer</summary>

Follow [Microsoft's WSL setup requirements](https://learn.microsoft.com/en-us/windows/wsl/install). Open **PowerShell as Administrator**:

```powershell
wsl --install -d Ubuntu
```

Restart Windows if prompted and complete Ubuntu's username/password setup. For later access, open PowerShell and enter Ubuntu:

```powershell
wsl -d Ubuntu
```

New WSL installations use WSL2. To check an existing installation, run `wsl --list --verbose` in PowerShell. If Ubuntu uses WSL1, save and back up its work before running `wsl --set-version Ubuntu 2`.

Continue with section C **inside Ubuntu**, not PowerShell.

</details>

### C. Linux/WSL Python environments

**Manual setup only — skip this section if the Windows installer succeeded.** These commands target Ubuntu on x86-64, including Ubuntu inside WSL2. Other distributions need their own prerequisite installation commands. Keep a WSL checkout in the Linux home directory rather than on a Windows-mounted drive.

Install the prerequisites and [uv](https://docs.astral.sh/uv/getting-started/installation/):

```sh
sudo apt update
sudo apt install -y git curl ca-certificates
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
```

For a new checkout:

```sh
mkdir -p ~/projects
cd ~/projects
git clone https://github.com/Zhengyi-Yan/plumewatch.git
cd plumewatch
```

If you already have a checkout, enter its repository root instead of cloning again. Install both environments there:

```sh
uv python install 3.14.3 3.12.2

# Reduce simultaneous installation work on memory-constrained machines.
export UV_CONCURRENT_INSTALLS=1
export UV_CONCURRENT_DOWNLOADS=1
export UV_CONCURRENT_BUILDS=1

uv venv --python 3.14.3 .venv
uv pip install --python .venv/bin/python --only-binary :all: -r requirements.txt

uv venv --python 3.12.2 experiments/unet/.venv
uv pip install --python experiments/unet/.venv/bin/python \
  --torch-backend cpu --only-binary :all: -r experiments/unet/requirements.txt
```

The CPU backend avoids CUDA downloads; the current U-Net worker does not select CUDA. Dependency resolution with Linux x86-64 wheels has been checked, but this does not establish successful installation or inference on every Linux/WSL machine. Continue with **E. Verify the installation**, then **F. Launch and stop**.

If installation reports `Cannot allocate memory (os error 12)`, retain the error and inspect available memory/processes:

```sh
free -h
ps -eo pid,comm,rss --sort=-rss | head -15
```

Save work in all WSL sessions before using `wsl --shutdown` in Windows PowerShell: it stops **all** distributions. Reopen Ubuntu, enter the repository, set the concurrency variables again and retry the failed dependency-install command. Do not delete the checkout, silently change pinned packages or raise WSL memory limits without checking the host's available RAM.

### D. Included trained models

All three active models are included in the repository. No separate model download, copying or training is needed.

| Model | Included file |
|---|---|
| Random Forest | `data/processed/multiclass_rf_v2_20260930/model.pkl` |
| U-Net | `experiments/unet/outputs/expanded_all_data_20260930/model.pt` |
| SVM | `data/processed/svm_rbf_20261001/model.pkl` |

RF and U-Net are computed together when either is requested, so both environments are required. SVM runs separately when selected. Use these active checkpoints rather than the historical `results/baseline_v1/model.pkl`. Training caches, other experiment checkpoints and most imagery are excluded; the Wellington example is included.

For a manual installation, update an existing Git checkout with `git pull --ff-only` from its root. The Windows installer checks for updates and asks before updating the Ubuntu checkout.

### E. Verify the installation

**For macOS and manual Linux/WSL setup.** The Windows installer performs its own checks. From the repository root:

```sh
.venv/bin/python -c "import shiny, rasterio, sklearn, numpy, PIL; print('Dashboard imports OK')"
experiments/unet/.venv/bin/python -c "import torch, rasterio, numpy; print('U-Net imports OK:', torch.__version__); print('Apple GPU available:', torch.backends.mps.is_available())"
.venv/bin/python -m unittest discover -s tests -p test_processing.py -v
```

Both import checks and the tests must pass. The tests exercise the included checkpoints, real inference, native raster grids and exports on small inputs; they do not establish accuracy on new scenes. Apple GPU availability being false is expected on Linux/WSL. On Apple Silicon, U-Net uses MPS when available and falls back to CPU otherwise.

### F. Launch and stop

**Windows after guided installation:** double-click the **PlumeWatch** desktop shortcut. It starts the server and opens your browser. Keep the terminal window open; press **Ctrl+C** there to stop. If the browser does not open, use the URL printed in that window.

**macOS or manual Linux/WSL setup:** from the repository root, run:

```sh
.venv/bin/python -m shiny run --host 127.0.0.1 --port 8000 app.py
```

Open [http://localhost:8000](http://localhost:8000) in your browser. Keep Terminal running and press **Ctrl+C** there to stop. If port 8000 is occupied, use `--port 8001` and open [http://localhost:8001](http://localhost:8001).

For later launches, open Terminal, enter your repository folder and run the same launch command. For example, with the default checkout location:

```sh
cd ~/projects/plumewatch
.venv/bin/python -m shiny run --host 127.0.0.1 --port 8000 app.py
```

Use your actual path if the project is on your Desktop or elsewhere. No environment activation or dependency reinstallation is needed for normal launches. The included Wellington image loads automatically; it overlaps training data and is a setup example, not an independent accuracy test.

<details>
<summary>Launcher for a manual Windows/WSL installation</summary>

Inside Ubuntu, enter the checkout and open it in File Explorer:

```sh
cd ~/projects/plumewatch
explorer.exe .
```

Double-click **`Start Dashboard.bat`**. It checks both environments and all three models, starts the server through Ubuntu and opens your Windows browser. It launches an existing installation; it does not install packages. Keep its window open and press **Ctrl+C** there to stop.

The defaults are distribution `Ubuntu`, repository `~/projects/plumewatch` and port `8000`. If your manual setup differs, edit `PW_DISTRO`, `PW_REPO` or `PW_PORT` at the top of the launcher; `PW_REPO` must be a Linux path. A busy port produces an error rather than stopping another process. WSL startup and installation checks must succeed before the launcher announces startup or opens a browser. Windows regression tests run with `powershell.exe -NoProfile -ExecutionPolicy Bypass -File tests\test_windows_launcher.ps1`.

Alternatively, enter Ubuntu with `wsl -d Ubuntu` in PowerShell, then use the Linux launch commands above.

</details>

### G. Use the dashboard

Open a supported scene, choose a model and click **Classify scene**. RF/U-Net runs their comparison; SVM runs separately. Completed results remain available until you load a different image. Large-scene SVM inference can take several minutes.

Enter the **Sentinel-2 acquisition date** next to the upload controls: the date the image was captured,
not a separate weather date. The known Wellington example fills in 2021-07-23; opening another image
clears the date so you can supply that scene's acquisition date. Classification still works without it.

**Antecedent rainfall near the uploaded scene** appears immediately below the class-area results.
The dashboard transforms the native raster centre from its CRS to WGS84 latitude/longitude and
makes one keyless request to the [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api).
It requests `daily=precipitation_sum`, `precipitation_unit=mm`, `timezone=auto`, and the nearest
weather grid cell for the seven days before acquisition. For acquisition date D, the 1-day value
is D−1, the 3-day value sums D−3 through D−1, and the 7-day value sums D−7 through D−1, inclusive.
These are complete calendar days in the location's timezone; acquisition-day precipitation is excluded.
For example, 14 February uses 13 February, 11–13 February, and 7–13 February.

Rainfall is context only: Open-Meteo's precipitation includes rain, showers and snow, represents a
nearby weather grid estimate, and is not a rain-gauge measurement at the plume or a catchment average.
The section links the data source and its CC BY 4.0 attribution. It does not feed any model, area
calculation or model export. No API key, coordinates or rainfall files are needed.

The acquisition date must be 1940-01-08 or later (to allow a full seven-day archive window) and
no later than the current UTC date. Recent archive days can still be unavailable. Invalid dates,
missing coordinates, timeouts, HTTP errors, malformed responses and missing daily values produce
messages rather than zeros. Weather requests run separately from inference, with a 15-second
network timeout, a retry button after service failures and up to 32 successful location/date results
cached per session. Changing the date clears outdated rainfall without rerunning classification.
The existing supported-raster validation still rejects non-georeferenced or incompatible GeoTIFFs.

Rainfall checks (no network required):

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_rainfall.py' -v
```

Optional workflow checks exercise Shiny's actual upload HTTP endpoint, reactive session, map
payloads, RF/U-Net inference and downloads with controlled weather responses. After setting up
the dashboard and U-Net environments above:

```sh
PLUMEWATCH_WORKFLOW_TESTS=1 .venv/bin/python tests/test_rainfall_workflow.py
```

For an isolated test U-Net environment, set `PLUMEWATCH_TEST_UNET_PYTHON` to its executable.
This changes only the test server's interpreter selection; model and inference code remain the same.
Set `PLUMEWATCH_LIVE_WEATHER_TESTS=1` as well to opt in to live archive retrieval for uploaded
New Zealand and Germany test scenes. The regular rainfall unit tests require no live service.

Supported inputs are twelve-band GeoTIFFs from the [PlumeWatch scene exporter](export_all_plume_scenes.js), with exact band descriptions/order `B2, B3, B4, B5, B6, B7, B8, B8A, B11, B12, SCL, valid`, scaled floating-point reflectance and a north-up projected 10 m grid. Maximum file size is 250 MiB and maximum scene size is ten million pixels. RGB-only files are not suitable. The models use ten reflectance bands; `SCL` and `valid` screen input pixels.

The threshold slider filters class previews and displayed areas, not raw exported classifications. Score smoothing changes display only. Exports contain `classification.tif`, `model_score.tif`, `plume_score.tif`, `summary.csv` and `metadata.json`; TIFFs preserve the native source grid. Save exports before closing the session.

The [teammate guide](TEAM_GUIDE.md) explains each view, score interpretation, annotation/training flow and troubleshooting. It is a Markdown document in the repository root, next to this README. Model disagreement is not accuracy, scores are uncalibrated, and predictions are estimates of visible plume extent rather than sediment concentration or verified physical boundaries.

## Model evaluation and limitations

Development evaluation used 49 reviewed frames in 13 linked site/event groups. Each group was held out in turn; related sites, events and overlapping imagery stayed together. RF, LayerNorm U-Net and RBF SVM were scored on identical uniform samples of up to 15,000 valid reviewed pixels per frame. Unannotated and invalid pixels were excluded.

| Model | Plume precision | Recall | F1 | IoU | Overall accuracy |
|---|---:|---:|---:|---:|---:|
| Expanded Random Forest | 0.956 | 0.836 | 0.892 | 0.805 | 0.911 |
| LayerNorm U-Net | 0.975 | 0.786 | 0.870 | 0.771 | 0.898 |
| RBF SVM | 0.976 | 0.788 | 0.872 | 0.773 | 0.897 |

RF achieved the higher pooled plume F1; performance varied by location, and U-Net performed better in some groups. SVM was evaluated on 22 October 2026 using the same held-out groups and cached reference pixels. Precision, recall, F1 and IoU refer to plume; overall accuracy includes normal water, plume and land. These are sampled human-annotation agreement scores, not physical sediment measurements or complete plume-area accuracy. Previously inspected development scenes and earlier architecture experiments limit their independence; this is exploratory group cross-validation rather than untouched external validation.

The final dashboard models were fitted using all reviewed frames and have no separate unseen test scores. Sparse or uncertain labels, limited geographic coverage and clouds limit interpretation. Scores are uncalibrated; model agreement, disagreement and display smoothing do not establish accuracy. Rainfall provides context rather than evidence of causation.

Supporting evidence remains in [expanded RF results](results/multiclass_rf_v2_20260930/metrics.json), [expanded U-Net metrics](reports/evidence/unet_expanded_metrics.json), [original U-Net metrics](reports/evidence/unet_original_metrics.json), [final U-Net verification](reports/evidence/unet_final_verification.json) and [SVM protocol](reports/evidence/svm_protocol.json), [SVM evaluation report](reports/evidence/SVM_EVALUATION_20261022.md) and [SVM held-out metrics](reports/evidence/svm_group_evaluation_20261022.json). Reproducing training requires the original imagery, reviewed annotations and local experiment inputs; cloning the repository alone does not reproduce expanded training.

## Time-series prototype

Open **Time series** in the navbar, or visit `/timeline/` on the running dashboard. This is a separate Shiny page with its own upload/result state. The existing classification page and checkpoints remain unchanged.

1. Choose 2–6 supported twelve-band acquisitions of one location. Use one image per distinct date, the same projected CRS, and overlapping coverage. The batch limit is 20 million source pixels, with the existing 250 MiB / ten-million-pixel limits per image.
2. Check the dates suggested from filenames, fill any missing dates, and tick the confirmation box. All uploads support year-first `YYYYMMDD`, `YYYY-MM-DD`, `YYYY_MM_DD` and `YYYY.MM.DD` patterns, including compact Sentinel timestamps. Conflicting dates, invalid dates and ambiguous day/month-first patterns require manual entry. Filename suggestions are not verified metadata.
3. Choose one model and a fixed score filter using the slider. Start at 0% to include all predicted plume pixels; raising it excludes predictions below the selected score, potentially including faint plume. Scores are uncalibrated and there is no validated best cutoff. This page runs only that model, sequentially, without retraining. A progress bar advances as each image finishes; elapsed time includes classification, comparison preparation and rainfall retrieval. The bar measures completed images, not progress within an image.
4. Browse dated image cards, labelled plume-area and seven-day rainfall bars, and linked maps. Playback changes only the viewing image. The change map stays visible below the image viewer. Choose **First image** and **Second image** inside the comparison card, then click **Compare dates**; these dates are independent of playback. The smaller reference map shares the viewing map’s centre and zoom. Change maps initially highlight added and removed predictions; use the coloured area cards to toggle layers, including unchanged plume. The all-date footprint view is available within that section.
5. Export the observation CSV, provenance/weather JSON, per-date plume masks, pairwise change TIFFs and plume-frequency TIFF.

The all-image map uses three groups: **Once**, **Some images** (two or more, but not all), and **Every image**. The middle group is empty for a two-image series. Expand **See exact image counts** for the area at each individual count. The exported frequency TIFF retains exact counts.

Comparisons use the intersection of source footprints, aligned by nearest neighbour to the first chronological source's 10 m grid. Every area and change calculation uses pixels valid on **all** uploaded dates. Low-score filtering does not redefine valid coverage. The coverage percentage under **Data, comparison coverage & export** describes the retained share of the geographic overlap, including land; it is not a plume accuracy score. Adding a cloudy date can reduce every observation's comparable area. Different projected CRS inputs, disjoint footprints, duplicate dates and zero shared valid pixels are rejected. Exports use this **comparison grid**, not each source image's full dimensions; previews are downsampled Web Mercator displays.

Rainfall is fetched from Open-Meteo for one fixed point at the overlap centre. It covers the seven complete local-calendar days before each confirmed acquisition. Failures remain unavailable, can be retried without rerunning classification, and are recorded in the export. Rainfall bars can have overlapping windows and must not be summed. Neither rainfall nor the uploaded series feeds temporal inputs into the models. Chart bars represent individual acquisitions in date order, with equal spacing between observations; they do not represent continuous movement, concentration or evidence of causation.

The **Load Cyclone Gabrielle sequence** button loads four Raukōkore acquisitions: **10, 15 and 20 February, and 2 March 2023**. Dates in these filenames use **Pacific/Auckland local dates**; the export manifest retains the UTC acquisition timestamps. The 15 February image shows the immediate aftermath, rather than the main storm itself. The button appears when all four TIFFs are available in `data/demo`.

The approximately 239 MiB of imagery is hosted separately as [GitHub Release assets](https://github.com/Zhengyi-Yan/plumewatch/releases/tag/gabrielle-demo-v1), not committed to Git history. From the repository root, download it once with:

```sh
python download_demo.py
```

On Windows, use `py download_demo.py` if `python` is unavailable. The downloader verifies file sizes and SHA-256 hashes, retains matching local files, and only replaces a file after a complete verified download. Restart the dashboard after downloading so the example button appears. Load the sequence, check the four suggested NZ dates, tick the confirmation box, and classify using one model and a fixed score filter (start at 0%). Loading the example does not precompute predictions.

This sequence demonstrates the comparison workflow, not independently verified plume accuracy or cyclone impact. Both RF and U-Net predict increased area on 15 February relative to 10 February, but disagree on later changes. All-date-valid coverage is approximately 70.6% of the 144 km² crop, including land. The crop may truncate plume features. The March observation follows further rainfall and is not a dry control.

Verification on macOS covered three full-resolution Arno scenes using RF and live rainfall, small real-scene batches through U-Net and SVM, the actual mounted upload/session/download endpoints, browser playback/toggles, and known-area alignment/NoData/change tests. The Gabrielle replacement was also verified on macOS through the mounted dashboard session: loading all four NZ dates, full-resolution RF classification, live rainfall and the four-date export. The same scenes were assessed with U-Net separately. Windows/WSL use of this new page has not been verified. No new Python dependencies are required. Run the comparison checks with:

```sh
.venv/bin/python -m unittest discover -s tests -p test_time_series.py -v
```

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
