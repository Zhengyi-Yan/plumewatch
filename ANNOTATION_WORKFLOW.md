# Local annotation workflow

Use polygon or mask labels `normal_water`, `plume`, `shallow_water`, and `land`.
SAM-assisted masks must be reviewed before saving; they are not automatic ground truth.
Leave uncertain pixels, clouds, cloud shadows, black holes and borders unlabelled.
Do not guess shallow water from colour alone. Draw separate confident patches;
you do not need to cover the whole image. Avoid overlapping different classes.

## Files

`data/annotation_manifest.json` links PNGs to the original 12-band TIFFs and
records their grids, dates, sites, events and sources. Keep this small file in Git.
Large imagery and generated masks remain ignored. The P2-06 mosaic and its
original tile parts are listed for compatibility with existing CVAT tasks;
use the mosaic for new annotations, not both originals as additional samples.

## Before annotation

From the project root, verify existing PNGs or generate missing ones:

```sh
.venv/bin/python annotation_pipeline.py png
```

The fixed RGB display uses B4/B3/B2, clips reflectance to 0–0.25 and applies
an exponent of 1/1.2. No resize, crop, reprojection or per-image stretch occurs.
Existing different PNGs are rejected rather than replaced underneath annotations.

## After annotation

Export annotations from CVAT as **CVAT for images 1.1**, without images.
Place the ZIP or extracted annotations.xml under `data/raw/cvat/annotations/`.
Then run (substitute your actual filenames):

```sh
.venv/bin/python annotation_pipeline.py masks data/raw/cvat/annotations/p1.zip data/raw/cvat/annotations/p2.zip data/raw/cvat/annotations/p3.zip --output data/processed/cvat_masks_v1
```

Each image becomes a georeferenced single-band mask: 0 normal_water, 1 plume,
2 shallow_water, 3 land, 255 ignored. These IDs preserve the pilot's plume=1;
earlier conversational examples using plume=0 were illustrative only.
Objects still labelled `candidate` are skipped, regardless of their source.
SAM-origin objects relabelled to a supported class are retained, including `source=auto`.
Unlabelled pixels remain 255. TIFF validity, SCL screening and finite reflectance
checks always override annotations. PNG black colour is not used for training validity.
No manual cloud label is required. Unknown labels, wrong dimensions, duplicate
images, existing output masks and conflicting classes at pixel centres cause errors.
Same-class overlaps are harmless. Polygons and CVAT RLE masks are supported;
other shape types are rejected. SAM masks retain their exact selected pixels.
Fix conflicts in CVAT and re-export. Use a fresh output folder for each version.

The converter uses pixel-centre inclusion (not all touched edge pixels).
It checks rasterized pixel conflicts, not subpixel geometric intersections.
Visually check the first exported masks against their TIFF before processing all tasks.

## Three-class baseline

`training_pixels(source_tif, mask_tif)` returns X (ten reflectance bands in
B2,B3,B4,B5,B6,B7,B8,B8A,B11,B12 order) and y (class IDs), excluding 255.
It checks the exact raster grid. PNG colour is never a feature. The first
three-class model uses `normal_water`, `plume`, and `land`; there are no
`shallow_water` annotations in the current exports. Keep that class out of
training until it has reviewed examples.

The 21 annotated scenes have four connected groups: Hutt, west coast October
2019, Canterbury 2021, and Cyclone Gabrielle. `train_multiclass.py` holds out
each entire group in turn. It links scenes by site, event, acquisition, and
overlapping footprint, so related images cannot cross a fold. Its fixed RF
settings are evaluated without tuning. It samples up to 3,000 pixels per
class per scene for training, caps each group/class at 10,000, and evaluates a
uniform sample of up to 15,000 labelled pixels per held-out scene. The final
model is then fit on all 21 scenes. No pixel-random train/test split is used.

From the repository root, after converting the three CVAT ZIPs:

```sh
.venv/bin/python train_multiclass.py
```

The metrics are in `results/multiclass_rf_v1/metrics.json`; the local model is
in ignored `data/processed/multiclass_rf_v1/model.pkl`. The manifest's legacy
`split` fields remain `unassigned` because all four groups participate in this
cross-validation; there is no untouched independent test set. Do not tune the
model on these fold scores and then describe them as independent test results.
This section describes the original 21-frame experiment. The dashboard now uses the later expanded three-class RF; see [REPORT.md](REPORT.md) for the consolidated comparisons.

To regenerate six visual examples, run `.venv/bin/python render_rf_examples.py`.
Each prediction comes from a fold that excluded that scene's entire site/event
group. Side-by-side RGB, CVAT-label and RF previews are in
`results/multiclass_rf_v1/examples/`; native-grid classified GeoTIFFs are in
ignored `data/processed/multiclass_rf_v1/examples/`. Unlabelled areas shown in
the RF preview are predictions, not verified ground truth.

Before relying on plume areas, review the April 2021 Canterbury comparison
labels and the weak per-scene cases reported in `metrics.json`. Those large
nearshore `plume` polygons may include naturally turbid or shallow water.
The available labels do not establish a whole-scene plume boundary or a
calibrated area error margin.

If a separate train/validation/test dataset is assembled later, assign splits
in the manifest consistently across linked sites, events and acquisitions, then
run `.venv/bin/python annotation_pipeline.py check-splits` to catch leakage.

Run the pipeline's synthetic integration checks:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_annotation_pipeline.py'
```
