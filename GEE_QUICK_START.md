# PlumeWatch: spreadsheet → GEE → download

## 1. Pick a row
Open the spreadsheet and filter **Person** to your name. Work on one assignment at a time.

## 2. Open the template
Copy all of `reusable_plume_export.js` into a **new script** in the [GEE Code Editor](https://code.earthengine.google.com/).
Save it using your Task ID, such as `P1-01`.

## 3. Fill Section A
Copy the row's Task ID, person, location, latitude, longitude, event group and source into the matching settings.
Use **GEE start UTC** and **GEE last day UTC** for the dates, written as `YYYY-MM-DD`.
Keep quotation marks around text. Leave Section D alone unless you need a wider search area.

## 4. Choose an image
1. Leave `MODE = 'SEARCH'` and click **Run**.
2. Open **Layers** and view one candidate at a time. Turn the previous candidate off.
3. Choose a clear, usable image. If none works, widen the dates and try again.
4. Expand the candidate list in **Console**. Copy the chosen full `asset_id`.
5. Paste it into `ASSET_ID` in Section B and the spreadsheet.
6. Change `MODE` to `'LABEL'`. Set the agreed `SPLIT`, or leave `'unassigned'`.
7. Click **Run**.

## 5. Draw the classes
Create drawing layers with these exact names:

| Layer name | Draw here |
|---|---|
| `plume` | Clearly visible sediment plume water |
| `normal_water` | Clearly non-plume water with no visible bottom |
| `shallow_water` | Water where you can confidently identify the seabed |
| `land` | Dry land, including buildings, vegetation and beaches |
| `unknown` | Unclear patches you want a teammate to review |

Draw several small, separate patches. Stay inside the yellow square and do not overlap polygons.
Do not force every class into every image. Leave absent classes at zero.
Skip ships, wakes, clouds and glare, or put them in `unknown`. Do not create separate ship/building classes.
If you cannot tell shallow water from plume, use `unknown`.

**Confidence:** plain layer names mean **high confidence**.
For a tentative label, create a layer such as `plume_medium` or `shallow_water_low`.
Medium/low labels and unknown patches are saved for review but excluded from sample CSVs.
You can leave uncertain areas undrawn; drawing unknown patches is optional.
Extra layers may use a number at the end, such as `land_high_2`.

## 6. Count and save
In Section C, enter your counts across all confidence levels. Example:

```javascript
var EXPECTED = {
  plume: 5,
  normal_water: 3,
  shallow_water: 2,
  land: 3,
  unknown: 1
};
var BATCH_NUMBER = 1;
```

Use your actual counts. Keep each drawing separate rather than combining shapes.
Click **Save**, keeping the drawing Imports, then **Run**.

## 7. Prepare exports
1. Click **Prepare scene export (once)**.
2. Click **Check labels + prepare batch 1**.
3. If a check fails, read the panel/Console message, fix it, Save and Run again.
4. Open **Tasks** and click **Run** for each prepared task.
5. Check how many batches the panel reports.
6. For the next batch, change only `BATCH_NUMBER`, Save and Run, then click the label export button.

Repeat until every batch is done. Do not change polygons between batches, and do not export the scene again.
A batch normally creates a CSV and a GeoJSON. A batch containing only review labels creates **only a GeoJSON**.

## 8. Download and hand over
Open Google Drive → `PlumeWatch_Exports`.
Download the scene TIFF file(s), scene metadata, and every batch's CSV/GeoJSON.
Keep filenames unchanged and put everything in a folder named after your Task ID.
Update the spreadsheet's progress and reviewer, then hand over that folder.

**New image:** start a fresh script from the template. Do not carry old polygons onto a new image.
**Changed labels:** increase `RUN_TAG` (for example, `mc_v2`) and export all label batches again.
Keep only one complete version in the eventual training input; retain older work separately.

## Team notes
- Agree the dataset split before training. Keep crops from the same held-out scene/event out of training.
- Review medium/low/unknown polygons together. Move accepted polygons to the correct high-confidence layer, update counts and export a new version.
- Existing `background` drawing layers are accepted as `normal_water`; check that those patches really are non-plume water.
- Class IDs are normal water 0, plume 1, shallow water 2, land 3, unknown -1.
- This update prepares multiclass labels. The existing Python model is still the old two-class Hutt pilot; its training loader must be updated before using the new data.
- Local checks passed. A first small export still needs verification inside an authenticated GEE session.
