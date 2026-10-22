# SVM group cross-validation — 22 October 2026

The fixed RBF SVM recipe was evaluated on the same 13 linked site/event groups and 735,000 reference pixels across 49 reviewed frames as expanded RF and LayerNorm U-Net. Each group was held out once.

| Model | Plume precision | Plume recall | Plume F1 | Overall accuracy |
|---|---:|---:|---:|---:|
| RBF SVM | 97.62% | 78.79% | 87.20% | 89.71% |

Precision, recall and F1 refer to plume. Overall accuracy includes normal water, plume and land. Metrics pool held-out pixels, rather than averaging fold scores.

StandardScaler was fitted independently within each training fold. SVM settings match the deployed recipe: RBF, C=1, gamma=scale, balanced class weights, probability=True, seed42. Native SVC.predict classes were scored. Up to 300 training pixels per group/class were spread across eligible frames, matching train_svm.py.

Verification passed: original sample-cache and reviewed-mask hashes; matching saved U-Net truth arrays and RF/U-Net class supports; disjoint train/test groups; training-only scaler fits; reported confusion matrix rebuilt from saved predictions. Independent sklearn metric calculations matched all four reported scores. The deployed model checksum remained unchanged.

## Held-out groups

| Group | Sites | Plume F1 | Overall accuracy |
|---|---|---:|---:|
| group_01 | Hutt / Wellington Harbour | 99.02% | 99.37% |
| group_02 | Manawatū mouth, Rangitīkei mouth, Whanganui mouth | 81.96% | 89.19% |
| group_03 | Hurunui mouth, Waiau Uwha mouth, Waimakariri / Pegasus Bay | 76.39% | 83.82% |
| group_04 | Mohaka mouth, Nūhaka mouth, Uawa / Tolaga Bay, Waiapu mouth, Waipaoa / Tūranganui-a-Kiwa, Wairoa mouth | 91.59% | 92.61% |
| group_05 | Isonzo | 86.27% | 81.69% |
| group_06 | Arno | 98.91% | 98.43% |
| group_07 | Var | 81.34% | 92.57% |
| group_08 | Pineios | 99.28% | 99.76% |
| group_09 | Burdekin, Tully | 94.47% | 93.77% |
| group_10 | Murray | 99.99% | 99.99% |
| group_11 | Tweed | 88.17% | 84.00% |
| group_12 | Maitai, Wakapuaka | 63.06% | 69.76% |
| group_13 | Hawkesbury, Hunter | 60.42% | 80.62% |

## Interpretation

- Exploratory group cross-validation of the training recipe, not an independent test of the final all-data checkpoint.
- Previously inspected development labels; no untouched external validation.
- Only sampled valid reviewed pixels are scored; ignored pixels and unreviewed candidates are excluded.
- One seed and fixed hyperparameters; label uncertainty and geographic domain shift remain.
- Overall accuracy covers water, plume and land; precision/recall/F1 below refer to plume.

## Reproduce

Requires the original trusted local sample cache, masks, SVM protocol/model and expanded U-Net evaluation artifacts:

```bash
.venv/bin/python evaluate_svm.py --reference /path/to/unet-expanded-evaluation-20260930 --out /path/to/new-svm-evaluation
```

Cloning alone does not provide the evaluation inputs. Raw pixel predictions remain in the local output directory; metrics and per-scene CSV are retained in reports/evidence.
