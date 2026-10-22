#!/usr/bin/env bash
set -euo pipefail
trap 'echo "Setup stopped at line $LINENO. Keep the error above; rerun the installer after fixing it." >&2' ERR

if [[ $(id -u) == 0 ]]; then
    echo 'Run setup as your normal Ubuntu user, not root.' >&2
    exit 1
fi
if [[ $(uname -m) != x86_64 ]]; then
    echo 'This installer supports Intel/AMD 64-bit Windows (x86-64 Ubuntu). Windows ARM is not verified.' >&2
    exit 1
fi

repo="$HOME/projects/plumewatch"
url='https://github.com/Zhengyi-Yan/plumewatch.git'
echo 'Installing Ubuntu prerequisites. Enter your Ubuntu password if sudo asks.'
sudo apt-get update
sudo apt-get install -y git curl ca-certificates

if [[ -e "$repo" ]]; then
    if [[ ! -d "$repo/.git" ]] || [[ $(git -C "$repo" remote get-url origin) != "$url" ]]; then
        echo "$repo already exists and is not the expected GitHub checkout. Nothing was replaced." >&2
        exit 1
    fi
    echo "Reusing $repo without pulling updates or replacing your files."
else
    mkdir -p "$(dirname "$repo")"
    git clone "$url" "$repo"
fi
cd "$repo"

if [[ ! -x "$HOME/.local/bin/uv" ]]; then
    installer=$(mktemp)
    trap 'rm -f "$installer"' EXIT
    curl -fLsS https://astral.sh/uv/install.sh -o "$installer"
    UV_INSTALL_DIR="$HOME/.local/bin" UV_NO_MODIFY_PATH=1 sh "$installer"
fi
uv="$HOME/.local/bin/uv"
export UV_CONCURRENT_INSTALLS=1 UV_CONCURRENT_DOWNLOADS=1 UV_CONCURRENT_BUILDS=1
"$uv" python install 3.14.3 3.12.2

# Keep partially installed environments so retries can finish without deleting files.
if [[ ! -e .venv ]]; then "$uv" venv --python 3.14.3 .venv; fi
if [[ ! -e experiments/unet/.venv ]]; then "$uv" venv --python 3.12.2 experiments/unet/.venv; fi
.venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3, 14), "Dashboard needs Python 3.14"'
experiments/unet/.venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3, 12), "U-Net needs Python 3.12"'
"$uv" pip install --python .venv/bin/python --only-binary :all: -r requirements.txt
"$uv" pip install --python experiments/unet/.venv/bin/python --torch-backend cpu --only-binary :all: -r experiments/unet/requirements.txt
"$uv" pip check --python .venv/bin/python
"$uv" pip check --python experiments/unet/.venv/bin/python

for file in app.py data/processed/multiclass_rf_v2_20260930/model.pkl \
    experiments/unet/outputs/expanded_all_data_20260930/model.pt \
    data/processed/svm_rbf_20261001/model.pkl hutt-test/hutt_20210723_full_scene_v1.tif; do
    if [[ ! -s "$file" ]]; then echo "Missing or empty included file: $file" >&2; exit 1; fi
done
.venv/bin/python -c 'import shiny, rasterio, sklearn, numpy, PIL; print("Dashboard imports OK")'
experiments/unet/.venv/bin/python -c 'import torch, rasterio, numpy; print("U-Net imports OK:", torch.__version__)'
# This integration test needs only included checkpoints, including on older checkouts.
PYTHONPATH=. .venv/bin/python tests/test_processing.py TwoModelWorkflowTest.test_real_checkpoints_preserve_grid_and_export_three_classes -v
echo 'Ubuntu dependencies, all three models and raster/export checks passed.'
