# PlumeWatch experiment and model report

Consolidated 1 October 2026. This is the single narrative report for the original U-Net pilot, expanded RF comparison, expanded U-Net evaluation and final research checkpoints. Setup and annotation instructions remain in the separate operational guides.

## Findings and current status

PlumeWatch classifies visible plume-like water, normal water and land from one Sentinel-2 acquisition. It does not estimate sediment concentration, prove physical sediment presence or establish complete plume boundaries. Reviewed annotations are human reference labels; unreviewed regions cannot be scored as right or wrong.

The expanded LayerNorm U-Net did not outperform the RF comparators overall. Its higher precision accompanies lower plume recall and substantial failures on some faint scenes. It improves particular scenes, but those gains do not establish a general advantage or justify replacing the RF baseline. Expanded RF labels also produced mixed results: performance improved on the new cohort while regressing on the original cohort. The final dashboard checkpoints use all reviewed frames and have no untouched independent test score. SVM remains an exploratory comparison with no independent accuracy claim. No ensemble has been validated.

The dashboard now offers RF, U-Net and SVM for visual review. This later integration supersedes the earlier training reports' statements that no dashboard model had changed. Scores are uncalibrated, and visual disagreement does not identify which prediction is correct.

## Data and reference policy

- The original cohort comprises 21 frames in four connected site/event groups. The expanded cohort comprises 49 reviewed frames in 13 linked groups, including 28 new usable frames.
- Seven new CVAT ZIPs contained 33 image entries, 30 unique frames and 28 frames with supported reviewed classes. Three duplicated exports were merged once with agreeing reviewed overlaps. Two Rhône frames containing only candidate objects were excluded.
- Unreviewed SAM objects still labelled `candidate` are skipped. Supported class annotations are retained even when their source is `auto`. No disputed scene was relabelled for these comparisons.
- Raster IDs are normal water=0, plume=1, land=3, ignored=255. Network channels 0/1/2 map to raster IDs 0/1/3. No shallow-water class is fitted in the reported three-class models.
- Inputs are B2, B3, B4, B5, B6, B7, B8, B8A, B11, B12 in that order. RGB images are previews, not model inputs. Source validity, finite reflectance and the existing SCL policy override annotations; source-valid pixels outside SCL 2/4/5/6/7 remain excluded.
- Same sites, related events, acquisitions and overlapping footprints stay in one fold. Burdekin/Tully, Nelson and Hawkesbury/Hunter are conservatively linked. Tiles are not independent scenes.
- Evaluation uses deterministic uniform samples of up to 15,000 valid labelled pixels per frame. Ignored pixels and unverified regions do not enter quantitative metrics. Results are sampled-reference scores, not full-raster plume-area accuracy.

## Original 21-frame GroupNorm U-Net pilot

The isolated pilot used a small four-level ten-channel U-Net: encoder widths 16/32/64/128, 256-channel bottleneck, GroupNorm and bilinear decoding, with three logits. Training used 256×256 patches, 40 epochs, 128 patches per epoch, batch size 4, AdamW at 3e-4 with weight decay 1e-4, flips and 90-degree rotations, and masked class-weighted cross-entropy. The base seed was 42, with fold seeds 43–46. Training-only fold data determined normalization and class weights; the held-out group did not select stopping/checkpoints. No Dice/Focal loss, temporal inputs or foundation model was used.

| Model | Plume precision | Recall | F1 | IoU |
|---|---:|---:|---:|---:|
| Original RF comparator | 0.9722 | 0.8692 | 0.9178 | 0.8481 |
| Original GroupNorm U-Net | 0.9602 | 0.9120 | 0.9355 | 0.8788 |

The pooled pilot F1 gain was about 0.0177, but the recorded pilot success flag was false: the clear August 2019 Hutt example regressed by about 0.313 F1. Some weak examples improved, including July 2020 Hutt and April 2021 Canterbury cases. Only four independent groups, disputed annotations and sparse reference coverage limit interpretation. These results belong to the original GroupNorm recipe and must not be pooled with the expanded LayerNorm results below.

Earlier tile-context probes implicated GroupNorm's spatial normalization pathway. Replacing it with per-pixel channel LayerNorm removes that particular pathway, but does not remove the U-Net's spatial receptive field or establish a universal cause for missed faint plumes. The expanded evaluation cannot distinguish architecture, training budget, seed variability, label inconsistency or domain differences as the overall cause.

## Expanded RF comparison

The RF recipe remained fixed: 120 trees, minimum leaf 20, balanced_subsample and seed42, using the ten reflectance bands. Training sampled up to 3,000 pixels per frame/class and capped each group/class at 10,000. No tuning was performed. The final all-data RF used 274,000 sampled pixels across all 49 frames.

Original-label comparators were refitted using original frames outside each held-out group. Expanded RF comparators added new reviewed frames outside that same group. Both were scored on the identical reference pixels. These are fold-model scores, not independent scores of the final all-data RF.

| Reference cohort | Original-label RF F1 | Expanded RF F1 | Original IoU | Expanded IoU |
|---|---:|---:|---:|---:|
| Original 21 frames | 0.9178 | 0.8777 | 0.8481 | 0.7821 |
| New 28 frames | 0.8845 | 0.8990 | 0.7928 | 0.8166 |
| All 49 frames | 0.8954 | 0.8921 | 0.8107 | 0.8052 |

Both columns use exactly the same sampled reference pixels and hold out the entire linked site/event group. The original-label comparator is refit using only the original data outside that group; the expanded RF adds new labels outside that group. These are cross-validation scores, not scores of the final all-data model.

| Cohort | Old precision | New precision | Old recall | New recall | Old site/date macro F1 | New site/date macro F1 |
|---|---:|---:|---:|---:|---:|---:|
| original | 0.9722 | 0.9320 | 0.8692 | 0.8294 | 0.8799 | 0.8287 |
| new | 0.9689 | 0.9676 | 0.8135 | 0.8395 | 0.8313 | 0.8412 |
| all | 0.9700 | 0.9559 | 0.8315 | 0.8362 | 0.8562 | 0.8348 |

Macro plume F1 includes only reference scenes with plume labels. Negative reference scenes are reported separately below; zero-support F1 is not treated as a segmentation failure.

### Frozen baselines on new unseen groups

Waimakariri 2022 is excluded here because its site was already in the baseline training set. The remaining 27 new frames are unseen by the frozen baselines. The expanded model is still evaluated using its held-out folds.

| Model | Plume precision | Recall | F1 | IoU |
|---|---:|---:|---:|---:|
| Original two-class pilot | 0.3737 | 0.4424 | 0.4051 | 0.2540 |
| Frozen three-class RF v1 | 0.9682 | 0.8120 | 0.8833 | 0.7909 |
| Expanded RF (held-out) | 0.9670 | 0.8384 | 0.8981 | 0.8151 |

The two-class pilot has no land class: its comparison is binary plume versus all other annotated pixels, not three-class accuracy. Historical baseline scores on different test sets are not directly compared.

## Expanded LayerNorm U-Net comparison

The expanded U-Net retained the four-level architecture and bilinear decoder but used per-pixel channel LayerNorm. Every fold used seed42, 40 epochs, 128 patches per epoch, batch4, 256×256 patches, AdamW 3e-4, weight decay1e-4, masked weighted cross-entropy and flips/90-degree rotations. Groups/classes were sampled to avoid domination by large scenes. Each fold learned mean/std and class weights from its training groups only. Checkpoints were always the final epoch; no held-out tuning, stopping or checkpoint selection occurred.

The held-out inference reproduced 256px overlapping tiles at stride192 with Hann-weight probability blending at the exact RF reference pixels. Only tiles unable to contribute to any evaluated pixel were skipped. This evaluation did not generate new complete scene rasters or claim full-raster scores.

| Cohort | Original-label RF F1 | Expanded RF F1 | Expanded U-Net F1 | U-Net precision | U-Net recall | U-Net IoU |
|---|---:|---:|---:|---:|---:|---:|
| Original 21 frames | 0.9178 | 0.8777 | 0.8335 | 0.9918 | 0.7187 | 0.7145 |
| New 28 frames | 0.8845 | 0.8990 | 0.8870 | 0.9684 | 0.8182 | 0.7969 |
| All 49 frames | 0.8954 | 0.8921 | 0.8705 | 0.9752 | 0.7861 | 0.7707 |

### Macro results

| Cohort | Expanded RF site/date macro F1 | U-Net site/date macro F1 | Expanded RF group macro F1 | U-Net group macro F1 |
|---|---:|---:|---:|---:|
| original | 0.8287 | 0.7763 | 0.8651 | 0.8598 |
| new | 0.8412 | 0.8238 | 0.8926 | 0.8681 |
| all | 0.8348 | 0.7994 | 0.8820 | 0.8595 |

Macro plume F1 excludes zero-plume reference cases. Their false-positive rates are given separately. Site/date aggregation joins tiles of the same source acquisition; group aggregation respects the related-event/site grouping. Neither pixels nor tiles are independent statistical observations.

### Held-out group results

| Group | Sites | Expanded RF F1 | U-Net F1 | Change |
|---|---|---:|---:|---:|
| group_01 | Hutt / Wellington Harbour | 0.7799 | 0.9546 | +0.1747 |
| group_02 | Manawatū mouth, Rangitīkei mouth, Whanganui mouth | 0.9187 | 0.8289 | -0.0898 |
| group_03 | Hurunui mouth, Waiau Uwha mouth, Waimakariri / Pegasus Bay | 0.8153 | 0.7860 | -0.0293 |
| group_04 | Mohaka mouth, Nūhaka mouth, Uawa / Tolaga Bay, Waiapu mouth, Waipaoa / Tūranganui-a-Kiwa, Wairoa mouth | 0.9616 | 0.8950 | -0.0666 |
| group_05 | Isonzo | 0.8985 | 0.9024 | +0.0039 |
| group_06 | Arno | 0.9896 | 0.9895 | -0.0000 |
| group_07 | Var | 0.9071 | 0.7643 | -0.1429 |
| group_08 | Pineios | 0.9937 | 0.9962 | +0.0024 |
| group_09 | Burdekin, Tully | 0.9240 | 0.9279 | +0.0040 |
| group_10 | Murray | 0.9999 | 1.0000 | +0.0001 |
| group_11 | Tweed | 0.8743 | 0.8978 | +0.0234 |
| group_12 | Maitai, Wakapuaka | 0.7136 | 0.6328 | -0.0808 |
| group_13 | Hawkesbury, Hunter | 0.6902 | 0.5982 | -0.0920 |

## Site/date results

All 39 plume-positive site/date summaries are retained below, ordered by the U-Net change relative to expanded RF. Multiple tiles of the same site/date are aggregated. Original-label RF denotes the refitted comparator, not the frozen original checkpoint.

| Site | Date | Cohort | Frames | Original-label RF F1 | Expanded RF F1 | Expanded U-Net F1 | U-Net − expanded RF |
|---|---|---|---:|---:|---:|---:|---:|
| Waiapu mouth | 20230221 | original | 1 | 0.9348 | 0.8910 | 0.4555 | -0.4355 |
| Hurunui mouth | 20210428 | original | 1 | 0.6235 | 0.3747 | 0.0214 | -0.3534 |
| Waiau Uwha mouth | 20210428 | original | 1 | 0.6782 | 0.3809 | 0.0498 | -0.3311 |
| Manawatū mouth | 20191003 | original | 1 | 0.8885 | 0.9241 | 0.6247 | -0.2994 |
| Wakapuaka | 20220831 | new | 1 | 0.3929 | 0.3245 | 0.0451 | -0.2794 |
| Nūhaka mouth | 20230219 | original | 1 | 0.4635 | 0.9655 | 0.7672 | -0.1984 |
| Waipaoa / Tūranganui-a-Kiwa | 20230221 | original | 1 | 0.9427 | 0.9260 | 0.7322 | -0.1938 |
| Var | 20201003 | new | 1 | 0.9402 | 0.9074 | 0.7643 | -0.1431 |
| Hunter | 20220410 | new | 2 | 0.3255 | 0.3465 | 0.2405 | -0.1061 |
| Hawkesbury | 20220410 | new | 3 | 0.8026 | 0.8113 | 0.7251 | -0.0862 |
| Waimakariri / Pegasus Bay | 20210602 | original | 2 | 0.9989 | 0.9947 | 0.9259 | -0.0688 |
| Burdekin | 20250228 | new | 2 | 0.9939 | 0.9850 | 0.9167 | -0.0684 |
| Rangitīkei mouth | 20191003 | original | 1 | 0.8556 | 0.8144 | 0.7475 | -0.0669 |
| Waimakariri / Pegasus Bay | 20210428 | original | 1 | 0.8520 | 0.5571 | 0.5219 | -0.0352 |
| Isonzo | 20231104 | new | 1 | 0.8061 | 0.8046 | 0.8010 | -0.0036 |
| Mohaka mouth | 20230219 | original | 1 | 0.9833 | 0.9998 | 0.9968 | -0.0029 |
| Waipaoa / Tūranganui-a-Kiwa | 20230219 | original | 1 | 0.9960 | 0.9952 | 0.9939 | -0.0013 |
| Burdekin | 20190210 | new | 3 | 0.9929 | 0.9896 | 0.9887 | -0.0009 |
| Arno | 20210126 | new | 1 | 0.9988 | 0.9988 | 0.9985 | -0.0002 |
| Arno | 20200226 | new | 1 | 0.9767 | 0.9768 | 0.9768 | -0.0001 |
| Arno | 20200228 | new | 1 | 1.0000 | 1.0000 | 0.9999 | -0.0000 |
| Murray | 20230101 | new | 1 | 0.9976 | 0.9999 | 1.0000 | +0.0001 |
| Arno | 20200304 | new | 1 | 0.9828 | 0.9827 | 0.9829 | +0.0002 |
| Whanganui mouth | 20191003 | original | 1 | 0.9995 | 0.9986 | 0.9990 | +0.0003 |
| Maitai | 20220822 | new | 1 | 0.9961 | 0.9979 | 1.0000 | +0.0021 |
| Pineios | 20230910 | new | 1 | 0.9928 | 0.9944 | 0.9966 | +0.0021 |
| Isonzo | 20231022 | new | 1 | 0.9750 | 0.9715 | 0.9827 | +0.0111 |
| Waipaoa / Tūranganui-a-Kiwa | 20230224 | original | 1 | 0.9748 | 0.9852 | 0.9999 | +0.0147 |
| Tweed | 20220301 | new | 1 | 0.8912 | 0.8743 | 0.8978 | +0.0234 |
| Wairoa mouth | 20230219 | original | 1 | 0.9587 | 0.9609 | 0.9890 | +0.0281 |
| Waiau Uwha mouth | 20210602 | original | 1 | 0.9944 | 0.9503 | 0.9851 | +0.0348 |
| Waimakariri / Pegasus Bay | 20220826 | new | 1 | 0.9335 | 0.9348 | 0.9719 | +0.0371 |
| Hutt / Wellington Harbour | 20210722 | original | 1 | 0.9944 | 0.9535 | 0.9968 | +0.0434 |
| Burdekin | 20250218 | new | 2 | 0.6751 | 0.8870 | 0.9463 | +0.0593 |
| Uawa / Tolaga Bay | 20230221 | original | 1 | 0.9476 | 0.8615 | 0.9381 | +0.0766 |
| Hurunui mouth | 20210602 | original | 1 | 0.9950 | 0.8788 | 0.9999 | +0.1211 |
| Hutt / Wellington Harbour | 20190812 | original | 1 | 0.9977 | 0.6729 | 0.8462 | +0.1733 |
| Tully | 20250216 | new | 1 | 0.1205 | 0.1963 | 0.4168 | +0.2205 |
| Hutt / Wellington Harbour | 20200712 | original | 1 | 0.5191 | 0.4883 | 0.9357 | +0.4474 |

## Negative reference scenes

Zero-plume reference scenes are excluded from macro plume F1 and reported using false-plume rates instead. Both scenes remain included wherever appropriate in pooled pixel calculations.

| Reference frame | Original-label RF false-plume rate | Expanded RF | Expanded U-Net |
|---|---:|---:|---:|
| France Var, 2020-09-28 | 0.0333% | 0.0267% | 0.000% |
| Greece Pineios, 2023-08-31 | 0.0533% | 0.0467% | 0.027% |

## Final all-data checkpoints

The dashboard selects these local artifacts:

| Model | Local checkpoint | Independent final-checkpoint score |
|---|---|---|
| Expanded RF | `data/processed/multiclass_rf_v2_20260930/model.pkl` | None; held-out comparisons assess the recipe |
| LayerNorm U-Net | `experiments/unet/outputs/expanded_all_data_20260930/model.pt` | None; all reviewed frames contributed to training |
| RBF SVM | `data/processed/svm_rbf_20261001/model.pkl` | None |

The final U-Net fit used all 49 usable frames across 13 groups and the fixed training settings above. Its statistics therefore come from all reviewed training data. Invalid inputs are zero after normalization; normalized inputs are clipped to [-5,5]. `model.pt` records the final epoch, saved normalization, class weights, losses, settings and patch participation. `resume.pt` is an optimizer-recovery snapshot, not another selected model. The original driver, rerun driver, standalone model definition, protocol and verification remain locally under the checkpoint directory. Training did not use held-out selection, relabelling, an ensemble or temporal inputs. Dashboard integration was added afterward.

To reconstruct within the checkpoint directory using the experiment's PyTorch environment:

```python
import torch
from model_definition import build_model
bundle = torch.load('model.pt', map_location='cpu', weights_only=False)
model = build_model()
model.load_state_dict(bundle['state_dict'])
model.eval()
# Use bundle['bands'], bundle['mean'] and bundle['std'].
# Clip normalized inputs to [-5,5]; fill invalid pixels with zero.
# Map channels 0/1/2 to raster IDs 0/1/3; invalid pixels remain 255.
```

The SVM is a saved StandardScaler → exact RBF SVC pipeline with C=1, gamma=scale, balanced class weights and seed42. All 49 frames across 13 groups contributed to 11,368 group/class-capped samples. The saved scaler is applied once. Predictions use native SVC.predict; the Platt score for that predicted class need not match probability argmax. Exact RBF inference is slower and runs separately on request. The saved protocol records samples, scaling, hashes and settings; no independent performance improvement is established.

## Inference, display and verification

The dashboard requires one supported, north-up projected 10 m Float32 scene with the ten scaled reflectance bands plus SCL and valid. It preserves the source CRS, affine transform, dimensions and native grid in exported rasters. Invalid pixels remain class255 and score NoData=-9999. U-Net full-scene inference blends overlapping tile probabilities before assigning classes.

RF/U-Net can run together; SVM runs separately. Model scores are uncalibrated. The predicted-class threshold filters class previews and area summaries; it does not reassign classes or change exported predictions. Plume-score and disagreement displays retain valid pixels irrespective of that threshold. Optional plume-score smoothing is display-only and preserves land/NoData; it changes neither raw predictions nor exported areas/rasters. Disagreement is shown on shared valid pixels and is not an accuracy score. The Wellington example overlaps training data and is a demonstration, not a generalization test.

Recorded expanded U-Net checks covered source/mask grid agreement, ZIP/mask/sample hashes, identical reference pixels, tile coverage, probability sums and finite losses. Final checkpoint serialization/inference checks also passed. These are implementation checks, not proof of physical plume accuracy. Dashboard integration checks cover input validation, native-grid outputs, three-class IDs, NoData and exported scores. SAM's verified CVAT round-trip confirms proposal handling, not annotation correctness.

## Limitations and interpretation

- Human labels can be sparse, ambiguous or inconsistent. Broad faint-water polygons may encode a different class definition from earlier annotations; this remains a possible contributor, not a proven cause.
- No unlabelled prediction is scored as quantitatively correct or incorrect. No sediment concentration, invisible-sediment detection or complete physical plume boundary is claimed.
- The expanded comparisons use previously inspected development scenes. LayerNorm was selected after earlier experiments on some of those scenes, so this is exploratory cross-validation rather than untouched external validation.
- One fixed seed does not quantify training variability. A fixed patch budget spread across more groups may affect learning coverage; its causal role has not been established.
- Tile counts and pooled pixels are not independent observations. Group and site/date summaries are required to expose weak cases.
- The original P2-05 products share date/footprint and remain in one fold and site/date summary to preserve the original cohort.
- RF speckles and smoother U-Net boundaries are visual behavior, not independent evidence of accuracy. Display smoothing cannot repair a wrong classification.
- No result establishes a reliable ensemble, production replacement or independently calibrated plume area.

## Evidence and provenance

Underlying metrics, audits, group definitions and per-frame CSVs are retained. This report replaces the expanded RF REPORT.md, expanded U-Net evaluation REPORT.md and all-data U-Net README.md. Their original text was retained in a local cleanup archive outside the repository before removal.

- Original three-class RF: `results/multiclass_rf_v1/metrics.json`.
- Expanded RF: `results/multiclass_rf_v2_20260930/metrics.json`, `per_frame.csv`, `manifest.json`, `groups.json`, `audit.json`, `verification.json` and annotation contact sheet.
- Original U-Net: `reports/evidence/unet_original_metrics.json`.
- Expanded U-Net: `reports/evidence/unet_expanded_metrics.json`.
- Final U-Net checks: `reports/evidence/unet_final_verification.json`.
- SVM setup: `reports/evidence/svm_protocol.json`.

The complete checkpoint protocols, fold checkpoints, sampled probabilities and original data remain local and ignored. Historical report-generation scripts are retained with their original experiment outputs; rerunning them may recreate an ignored/local report and does not regenerate this consolidated narrative. Changed inputs require new versions instead of reusing old caches. No model is retrained during this consolidation.
