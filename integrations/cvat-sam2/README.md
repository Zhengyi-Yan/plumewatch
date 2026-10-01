# SAM 2.1 Small CVAT experiment

Status (2026-09-23): **deployed locally and verified through CVAT**. CVAT lists
`SAM 2.1 Small (PlumeWatch)` and returned one mask from a box prompt on the demo
task (HTTP 200). That smoke test did not save or change an annotation. Nuclio's
management port is bound to localhost:8070; CVAT remains on its existing URL.

Verified backup: `.cvat-local/backups/pre-sam2-20260923.swAVM2/` contains a PostgreSQL
dump, task data/keys archive and the previous local Compose override (about 127 MB).

`main.py` implements CVAT's generic interactor protocol (as used by bundled IOG).
It accepts an image, two-corner box, positive points and negative points, then
returns a cropped CVAT RLE mask in the input image's pixel coordinates. It uses
SAM 2.1 Small through Ultralytics. `function.yaml` builds the Nuclio CPU function.

The box and clicks select a crop with 64 pixels of context. Crop offsets are
added back to the returned mask. One worker limits memory and serializes calls;
image state is reset between calls to prevent cross-image contamination. All
teammates will share this worker, so requests can queue. Native pilot timings
are not a Docker performance guarantee.

The model weights are downloaded inside the function image, not committed to Git.
The pilot checkpoint can be supplied locally using `SAM2_CHECKPOINT`. Dependencies
are confined to the experiment environment/container, not the dashboard environment.
Ultralytics carries its own AGPL-3.0 licensing terms.

## Use

Open a CVAT job, choose the AI interactor **SAM 2.1 Small (PlumeWatch)**, select a
label, draw a box and add positive/negative clicks. Review the returned mask before
accepting and saving it. Keep masks or convert them to polygons using CVAT's
controls if preferred. The first accepted mask should be checked visually in CVAT.

Export **CVAT for images 1.1** as usual. `annotation_pipeline.py` now reads both
polygon and mask annotations, preserves mask holes and offsets, rejects class
overlaps, and excludes TIFF-invalid pixels after conversion. Black PNG colour is
not a validity test. Automatic masks still require human review.

## Validation

From the repository root:

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_annotation_pipeline.py'
```

The mask round-trip check covers foreground-first RLE, holes, crop offsets,
malformed lengths and polygon/mask class conflicts.

## Start after Docker Desktop restarts

The deployment uses an ARM64 Nuclio dashboard, a single CPU function and
the private `cvat_sam2` Docker network. Nuclio needs Docker-socket access to build
and manage function containers; this grants control over Docker Desktop containers
and volumes. Its management port should bind to localhost only. This is the
[standard Nuclio Docker deployment mechanism](https://docs.nuclio.io/en/stable/tasks/quick-start.html).

From the repository root, use the SAM Compose file whenever starting CVAT so
`cvat_server` keeps its serverless settings:

```sh
docker compose -p cvat -f .cvat-local/docker-compose.yml -f .cvat-local/docker-compose.override.yml -f integrations/cvat-sam2/compose.yaml --env-file .cvat-local/.env up -d
```

The function and its image persist across Docker restarts. Redeploy only if
`main.py` or `function.yaml` changes. The CLI lives at `.cvat-local/bin/nuctl`:

```sh
.cvat-local/bin/nuctl deploy plumewatch-sam2-small --project-name cvat --namespace nuclio --path integrations/cvat-sam2 --file integrations/cvat-sam2/function.yaml --platform local --platform-config '{"attributes":{"network":"cvat_sam2"}}' --readiness-timeout 180
```

To stop only the added manager: `docker stop nuclio`. Remove only the SAM function
and its image when retiring the experiment; never run `docker compose down -v`,
which could delete CVAT data.

## Automatic polygons before labelling

From the project root, with Docker Desktop, `cvat_server`, and
`nuclio-nuclio-plumewatch-sam2-small` running:

```sh
.venv/bin/python integrations/cvat-sam2/auto_label.py \
  data/raw/spencer-sentinel-2/Italy_Arno_20210126_S2_L2A_12band.tif \
  --import-cvat
```

Replace only the TIFF path to process another image. Omit `--import-cvat` for
local previews only. Run one image at a time. The command uses the installed
model and dependencies, with no new downloads. It administers the local CVAT
instance through Docker; it is not a remote CVAT login client.

The command creates `data/processed/sam_candidates/<TIFF stem>/` (Git ignored).
It refuses an existing output folder or identically named CVAT task rather than
replacing work. If a run fails, inspect the retained folder and printed task ID;
do not delete a task containing annotations to force a rerun.

Outputs include the full-size `_cvat.png`, original SAM masks, candidate polygon
coordinates, `preview.png`, `source.json`, `report.json`, and (when imported)
`cvat_task.json` and read-back annotations. Source metadata records CRS, affine
transform, dimensions, original filename and SHA-256. The TIFF stays untouched.

PNG preparation uses the existing fixed RGB stretch and **both** `valid` and SCL
screening, plus finite/non-nodata reflectance. Output coordinates stay on the
source grid. SAM internally runs at 1024 pixels; mapping its predictions back
does not recover details lost at that resolution. Automatic settings are a
32x32 point grid, eight prompts per batch, no extra crop layers, and the installed
SAM quality/stability filters. Masks with fewer than 100 valid pixels are dropped.
Masks are clipped to usable pixels. CVAT's existing contour bridge helper
preserves holes; each candidate's polygons must reconstruct its mask exactly
both before and after import. Bridges can appear as thin lines in polygon outlines.

The standalone task starts with `candidate` objects and labels `plume`,
`normal_water`, `land`, and `shallow_water`. Select an object, change its label,
correct/delete it, and save. Some regions have multiple polygon pieces sharing
a group ID; review all pieces. Overlapping proposals remain candidates, and
`report.json` counts their overlap. Resolve overlaps between classes yourself.

These are unclassified proposals, not complete ground truth. Review every object;
SAM can miss the plume or leave large areas uncovered. Do not label all uncovered
water as plume. No labels are inferred by this command. Export CVAT for images
1.1 after review. Remaining `candidate` objects are skipped by the training converter; reviewed objects relabelled to a supported class are retained, including `source=auto`. The source sidecar is not automatically added to
`data/annotation_manifest.json`; register it there before converting a reviewed
export into training masks, and choose site/event splits then.

Check the PNG preparation with:

```sh
.venv/bin/python tests/test_sam_auto_label.py
```

### One task for a folder of images

```sh
.venv/bin/python integrations/cvat-sam2/batch_auto_label.py data/raw/spencer-sentinel-2
```

This is the preferred command for a batch: it imports all TIFFs in the folder
into **one task and one job**, with one image per frame. Completed local SAM
results are reused after checking the source SHA-256 and polygon reconstruction.
Incomplete local output is renamed with an `_interrupted_` suffix, never deleted.
Previously created individual CVAT tasks are left untouched.

The batch assigns distinct group IDs across images and matches polygons to CVAT
frames by filename, verifying image dimensions and exact polygon/mask agreement
again after import. CVAT may return polygons in a different order; verification
compares their geometry without relying on response order. Task IDs and frame
mapping are stored under `data/processed/sam_candidates/_batch_*/`.
An already-existing combined output/task is preserved rather than overwritten.
