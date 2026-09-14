// PLUMEWATCH — paste this whole file into a NEW Google Earth Engine script.
// Save one separate Code Editor script per selected image; keep its Imports.
// 1. SEARCH: copy a spreadsheet row into A, Run, inspect candidates in Layers.
// 2. Copy the chosen full asset ID from Console into B; set MODE = 'LABEL'.
// 3. Run, draw class layers listed in C, then Save.
// 4. Set expected counts in C, Run, prepare exports, then start them in Tasks.
// No median/mosaic: labels always belong to one exact Sentinel-2 granule.

// ================= A. CHANGE FOR EACH SPREADSHEET ROW =================
var TASK_ID = 'P1-01';                 // Task ID
var PERSON = 'Person 1';              // Person (or your name)
var LOCATION = 'Hutt / Wellington Harbour'; // Location
var LATITUDE = -41.24;                // Approx. latitude (negative in NZ)
var LONGITUDE = 174.90;               // Approx. longitude
var START_UTC = '2019-08-12';         // GEE start UTC, YYYY-MM-DD
var LAST_DAY_UTC = '2019-08-13';       // GEE last day UTC, INCLUSIVE
var EVENT_GROUP = 'Hutt 2019-08-13';   // Event group; keep consistent across team
var SOURCE_URL = 'https://doi.org/10.1080/00288330.2022.2088569';
var SOURCE_NOTE = 'Gall et al. Figure 10B'; // Evidence/date caveats from spreadsheet

// ================= B. CHANGE AFTER CHOOSING AN IMAGE ==================
var MODE = 'SEARCH';                  // 'SEARCH' or 'LABEL'
var ASSET_ID = '';                    // Paste FULL COPERNICUS/S2_SR_HARMONIZED/... ID
var SPLIT = 'unassigned';             // 'train', 'development', 'test', 'unassigned'
// unassigned may export for review; do not silently include it in training.
// Reserve whole scenes/events. Different polygons alone are NOT independent tests.
var RUN_TAG = 'mc_v1';                // Change when labels change, e.g. 'mc_v2'
var DRIVE_FOLDER = 'PlumeWatch_Exports'; // Folder name, not a path

// ================= C. CHANGE AFTER DRAWING / BETWEEN BATCHES ==========
// Counts include ALL confidence levels for that class. Leave absent classes at 0.
var EXPECTED = {plume: 0, normal_water: 0, shallow_water: 0, land: 0, unknown: 0};
// DRAWING LAYER NAMES:
// plume         = clear sediment plume water                (class 1)
// normal_water  = clear non-plume water, no visible bottom   (class 0)
// shallow_water = confidently identified visible seabed     (class 2)
// land          = dry land, buildings, vegetation, beaches   (class 3)
// unknown       = unclear patches / objects to exclude      (class -1)
// A plain class name means HIGH confidence (unknown always excluded).
// Optional: plume_medium, shallow_water_low, land_high, etc.
// Optional extra layers: plume_high_2, normal_water_2, etc.
// Only HIGH-confidence known classes produce sample CSV rows.
// Medium/low/unknown drawings remain in GeoJSON for review, never sample CSVs.
var BATCH_NUMBER = 1;                 // 1, then 2, ...; total printed after checks
var POLYGONS_PER_BATCH = 4;           // GeoJSON + CSV if batch has eligible labels

// ================= D. OPTIONAL SEARCH / SIZE SETTINGS ================
var RADIUS_KM = 10;                   // Search/export square extends ~10 km each way
var MAX_SCENE_CLOUD_PERCENT = 100;    // Whole-tile cloud, NOT local plume cloud
var MAX_CANDIDATES = 12;              // Narrow dates if results are truncated
var SAMPLE_LIMIT_PER_POLYGON = 2000;  // Upper bound; tiny polygons yield fewer
// Keep each individual label <= 1 km². Label clear patches, not an entire plume.
// Buildings belong to land. Ships/wakes, cloud and glare: skip or mark unknown.
// Do not guess shallow water from colour alone. No SCL-water-only mask:
// turbid water can be assigned other SCL codes.

// ================= ENGINE — NO NORMAL EDITS BELOW HERE ================
var COLLECTION = 'COPERNICUS/S2_SR_HARMONIZED';
var BANDS = ['B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B11', 'B12'];

function requireCondition(ok, message) { if (!ok) throw new Error(message); }
function validDate(value) {
  var d = new Date(value + 'T00:00:00Z');
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && !isNaN(d.getTime()) &&
    d.toISOString().slice(0, 10) === value;
}
function integerBetween(value, low, high) {
  return typeof value === 'number' && value % 1 === 0 && value >= low && value <= high;
}
function batchSlice(items, number, size) { return items.slice((number - 1) * size, number * size); }
function parseLayer(name) {
  var m = /^(plume|normal_water|shallow_water|land|unknown|background)(?:_(high|medium|low))?(?:_\d+)?$/.exec(name);
  if (!m) return null;
  var type = m[1] === 'background' ? 'normal_water' : m[1]; // legacy clear-water alias
  var confidence = type === 'unknown' ? 'unknown' : (m[2] || 'high');
  return {type: type, confidence: confidence,
    classId: {normal_water: 0, plume: 1, shallow_water: 2, land: 3, unknown: -1}[type],
    eligible: type !== 'unknown' && confidence === 'high'};
}
function geometryProblem(row) {
  if (row.kind !== 'Polygon') return 'Draw individual polygons/rectangles, not points, lines or combined MultiPolygons.';
  if (!(row.area > 0) || row.area > 1e6) return 'Each polygon must have area > 0 and <= 1 km².';
  if (row.outside > 1) return 'Polygon extends outside yellow export boundary.';
  if (row.overlap > 1) return 'Polygon overlaps another label. Remove overlap.';
  if (row.eligible !== false && !(row.usable > 0)) return 'No usable pixels in this polygon.';
  return '';
}
requireCondition(MODE === 'SEARCH' || MODE === 'LABEL', 'MODE must be SEARCH or LABEL.');
requireCondition(validDate(START_UTC) && validDate(LAST_DAY_UTC) && START_UTC <= LAST_DAY_UTC, 'Fix the UTC dates (YYYY-MM-DD).');
requireCondition(typeof LATITUDE === 'number' && LATITUDE > -80 && LATITUDE < 80 &&
  typeof LONGITUDE === 'number' && LONGITUDE >= -180 && LONGITUDE <= 180, 'Fix decimal latitude/longitude.');
requireCondition(RADIUS_KM > 0 && RADIUS_KM <= 25, 'Use RADIUS_KM between 0 and 25.');
requireCondition(integerBetween(MAX_CANDIDATES, 1, 30), 'Use 1–30 candidates.');
requireCondition(MAX_SCENE_CLOUD_PERCENT >= 0 && MAX_SCENE_CLOUD_PERCENT <= 100, 'Cloud percentage must be 0–100.');
requireCondition(integerBetween(BATCH_NUMBER, 1, 100) && integerBetween(POLYGONS_PER_BATCH, 1, 10), 'Use a positive batch number and 1–10 polygons per batch.');
requireCondition(integerBetween(SAMPLE_LIMIT_PER_POLYGON, 1, 10000), 'Use 1–10000 samples per polygon.');
requireCondition(/^[A-Za-z0-9_-]{1,24}$/.test(TASK_ID) && /^[A-Za-z0-9_-]{1,16}$/.test(RUN_TAG), 'TASK_ID/RUN_TAG: short letters, numbers, underscores, hyphens only.');
requireCondition(['train', 'development', 'test', 'unassigned'].indexOf(SPLIT) >= 0, 'Invalid SPLIT.');
requireCondition(PERSON.length > 0 && LOCATION.length > 0 && EVENT_GROUP.length > 0 && DRIVE_FOLDER.length > 0, 'Fill person, location, event group and Drive folder.');

var roi = ee.Geometry.Point([LONGITUDE, LATITUDE]).buffer(RADIUS_KM * 1000).bounds();
var rgb = {bands: ['B4', 'B3', 'B2'], min: 0, max: 2500, gamma: 1.2};
Map.centerObject(roi, 12);
Map.addLayer(ee.Image().byte().paint(roi, 1, 2), {palette: ['ffff00']}, 'Export boundary', true);
var panel = ui.Panel({style: {width: '360px', padding: '10px'}});
panel.add(ui.Label(TASK_ID + ' — ' + LOCATION, {fontWeight: 'bold'}));
var status = ui.Label('Loading...'); panel.add(status); ui.root.insert(0, panel);

function search() {
  var collection = ee.ImageCollection(COLLECTION).filterBounds(roi)
    .filterDate(START_UTC, ee.Date(LAST_DAY_UTC).advance(1, 'day'))
    .filter(ee.Filter.lte('CLOUDY_PIXEL_PERCENTAGE', MAX_SCENE_CLOUD_PERCENT))
    .sort('system:time_start');
  var limited = collection.limit(MAX_CANDIDATES);
  var records = limited.toList(MAX_CANDIDATES).map(function(item) {
    var im = ee.Image(item);
    return ee.Dictionary({asset_id: ee.String(COLLECTION + '/').cat(im.get('system:index')),
      utc: im.date().format('YYYY-MM-dd HH:mm:ss', 'UTC'),
      nz: im.date().format('YYYY-MM-dd HH:mm:ss', 'Pacific/Auckland'),
      tile: im.get('MGRS_TILE'), tile_cloud_percent: im.get('CLOUDY_PIXEL_PERCENTAGE')});
  });
  ee.Dictionary({count: collection.size(), candidates: records}).evaluate(function(result, error) {
    if (error) { status.setValue('Search failed: ' + error); return; }
    print('Candidate images — expand each record and copy asset_id', result.candidates);
    if (!result.count) { status.setValue('No S2 SR images found. Widen dates/check location. MODIS evidence does not guarantee a matching S2 image.'); return; }
    result.candidates.forEach(function(row, i) {
      Map.addLayer(ee.Image(row.asset_id).clip(roi), rgb, (i + 1) + ': ' + row.utc + ' UTC / ' + row.tile, i === 0);
    });
    status.setValue('Found ' + result.count + '; showing ' + result.candidates.length + '. Toggle one candidate at a time in Layers. Inspect cloud/plume, copy its asset_id into B, set LABEL, then Run.');
    panel.add(ui.Label('Do not draw in SEARCH mode. Separate tiles can cover only part of the boundary. Dates alone do not confirm a plume.'));
  });
}

function label() {
  requireCondition(ASSET_ID.indexOf(COLLECTION + '/') === 0 && ASSET_ID.length > COLLECTION.length + 1, 'Paste a full S2 SR HARMONIZED asset ID into B.');
  var classes = ['plume', 'normal_water', 'shallow_water', 'land', 'unknown'];
  requireCondition(Object.keys(EXPECTED).length === classes.length && classes.every(function(c) {
    return integerBetween(EXPECTED[c], 0, 60);
  }), 'EXPECTED must contain exactly the five class names, with nonnegative integer counts.');
  var image = ee.Image(ASSET_ID), projection = image.select('B2').projection();
  var scl = image.select('SCL');
  var valid = scl.neq(0).and(scl.neq(1)).and(scl.neq(3)).and(scl.lt(8))
    .and(image.select(BANDS).mask().reduce(ee.Reducer.min())).rename('valid');
  // Exactly the pilot's scaling/mask and nearest-neighbour 20 m -> 10 m sampling.
  // A 10 m export does not create new detail in the native 20 m bands.
  var usable = image.select(BANDS).multiply(0.0001).toFloat().updateMask(valid);
  var sceneKey = ASSET_ID.split('/').pop();
  var stem = TASK_ID + '_' + sceneKey + '_' + RUN_TAG;
  var metadata = {task_id: TASK_ID, person: PERSON, location: LOCATION, scene_key: sceneKey,
    asset_id: ASSET_ID, acquisition_utc: image.date().format('YYYY-MM-dd HH:mm:ss', 'UTC'),
    event_group: EVENT_GROUP, split: SPLIT, source_url: SOURCE_URL, source_note: SOURCE_NOTE,
    run_tag: RUN_TAG, processing: 'S2_SR_HARMONIZED_SCL_v1', label_schema: 'plumewatch_multiclass_v1'};
  Map.addLayer(image.clip(roi), rgb, 'LOCKED scene RGB');
  Map.addLayer(image.clip(roi), {bands: ['B8', 'B4', 'B3'], min: 0, max: 3500}, 'NIR / red / green', false);
  Map.addLayer(valid.not().selfMask().clip(roi), {palette: ['ff00ff']}, 'Quality rejected (not a water mask)', false);
  var drawing = Map.drawingTools(); drawing.setLinked(true);
  panel.add(ui.Label('Layers: plume, normal_water, shallow_water, land, unknown. Plain names = high confidence. Add _medium or _low for review-only labels. Save your script including Imports.'));
  var sceneButton = ui.Button('Prepare scene export (once)', null, true);
  var labelButton = ui.Button('Check labels + prepare batch ' + BATCH_NUMBER, null, true);
  panel.add(sceneButton); panel.add(labelButton);
  // Resolve projection once; catch bad asset IDs before enabling any export.
  ee.Dictionary({grid: projection, intersects: image.geometry().intersects(roi, 1),
    utc: image.date().format('YYYY-MM-dd', 'UTC')}).evaluate(function(info, error) {
    if (error) { status.setValue('Cannot load selected asset: ' + error); return; }
    if (!info.intersects) { status.setValue('Selected image does not intersect this location. Fix ASSET_ID or coordinates.'); return; }
    if (info.utc < START_UTC || info.utc > LAST_DAY_UTC) { status.setValue('Selected asset is outside the configured UTC window. Fix dates or asset ID.'); return; }
    status.setValue('Image locked. Draw, set expected counts, Save and Run. Scene export is available without labels.');
    print('Locked scene metadata', metadata);
    sceneButton.setDisabled(false); labelButton.setDisabled(false);
    sceneButton.onClick(function() {
      sceneButton.setDisabled(true);
      var raster = usable.addBands(scl.toFloat()).addBands(valid.unmask(0).toFloat())
        .clip(roi).unmask({value: -9999, sameFootprint: false});
      Export.image.toDrive({image: raster, description: stem + '_scene', folder: DRIVE_FOLDER,
        fileNamePrefix: stem + '_scene', region: roi, crs: info.grid.crs,
        crsTransform: info.grid.transform, maxPixels: 1e8, fileDimensions: 4096,
        fileFormat: 'GeoTIFF', formatOptions: {cloudOptimized: true, noData: -9999}});
      Export.table.toDrive({collection: ee.FeatureCollection([ee.Feature(roi, metadata)]),
        description: stem + '_scene_metadata', folder: DRIVE_FOLDER,
        fileNamePrefix: stem + '_scene_metadata', fileFormat: 'GeoJSON'});
      status.setValue('Scene + metadata tasks prepared. Start both in Tasks. Do this only once for this image/version.');
    });
    labelButton.onClick(function() {
      labelButton.setDisabled(true);
      function stop(message) { status.setValue(message); labelButton.setDisabled(false); }
      var rows = [], eligibleRows = [], counts = {plume: 0, normal_water: 0, shallow_water: 0, land: 0, unknown: 0}, ignored = [];
      drawing.layers().forEach(function(layer) {
        var name = layer.getName();
        var parsed = parseLayer(name);
        if (!parsed) { if (layer.geometries().length()) ignored.push(name); return; }
        var type = parsed.type;
        layer.geometries().forEach(function(g) {
          counts[type]++;
          rows.push(ee.Feature(g, metadata).set({polygon_id: stem + '_' + type + '_' + counts[type],
            class_id: parsed.classId, class_name: type, drawing_layer: name,
            confidence: parsed.confidence, label_eligible: parsed.eligible,
            review_status: parsed.eligible ? 'high_confidence' : 'excluded_pending_review'}));
          eligibleRows.push(parsed.eligible);
        });
      });
      print('Detected individual drawings', counts);
      if (ignored.length) { stop('Unrecognised drawing layers: ' + ignored.join(', ') + '. Rename labels or remove unused imports in this script.'); return; }
      if (classes.some(function(c) { return counts[c] !== EXPECTED[c]; })) {
        stop('Counts differ. See detected counts in Console, check drawings, update EXPECTED in C, Save and Run.'); return;
      }
      if (!rows.length || rows.length > 60) { stop('Draw 1–60 separate polygons total.'); return; }
      var selected = batchSlice(rows, BATCH_NUMBER, POLYGONS_PER_BATCH);
      var eligibleSelected = batchSlice(eligibleRows, BATCH_NUMBER, POLYGONS_PER_BATCH);
      var total = Math.ceil(rows.length / POLYGONS_PER_BATCH);
      if (!selected.length) { stop('There are only ' + total + ' batches. Change BATCH_NUMBER.'); return; }
      var labels = ee.FeatureCollection(rows);
      status.setValue('Checking all polygon boundaries, overlap and usable pixels...');
      var checks = labels.map(function(f) {
        var g = f.geometry();
        var others = labels.filter(ee.Filter.neq('polygon_id', f.get('polygon_id'))).map(function(o) {
          return o.set('overlap_area', g.intersection(o.geometry(), 1).area(1));
        });
        return ee.Feature(null, {id: f.get('polygon_id'), eligible: f.get('label_eligible'), kind: g.type(), area: g.area(1),
          outside: g.difference(roi, 1).area(1),
          overlap: ee.Algorithms.If(others.size(), others.aggregate_max('overlap_area'), 0),
          usable: usable.select('B2').reduceRegion({reducer: ee.Reducer.count(), geometry: g,
            crs: projection, maxPixels: 1e7, tileScale: 4}).get('B2')});
      });
      checks.toList(rows.length).map(function(f) { return ee.Feature(f).toDictionary(); }).evaluate(function(result, err) {
        if (err) { stop('Checks failed; no label tasks created. Try smaller polygons. ' + err); return; }
        var failures = result.map(function(r) { var p = geometryProblem(r); return p ? r.id + ': ' + p : ''; }).filter(Boolean);
        if (failures.length) { print('Fix labels', failures); stop('No label exports created. See Console for corrections.'); return; }
        var samples = ee.FeatureCollection([]);
        selected.forEach(function(f, index) {
          if (!eligibleSelected[index]) return; // unknown/medium/low: polygons only
          // numPixels is approximate; sampling all at most 10,000 pixels in a
          // <=1 km² patch then limiting guarantees a nonempty usable patch is retained.
          var pixels = usable.addBands(ee.Image.pixelLonLat()).sample({region: f.geometry(),
            projection: projection, dropNulls: true, tileScale: 4, geometries: false})
            .randomColumn('sample_random', 99).sort('sample_random').limit(SAMPLE_LIMIT_PER_POLYGON)
            .map(function(p) { return p.set(f.toDictionary()); });
          samples = samples.merge(pixels);
        });
        var prefix = stem + '_b' + BATCH_NUMBER;
        var hasSamples = eligibleSelected.some(function(value) { return value; });
        if (hasSamples) Export.table.toDrive({collection: samples, description: prefix + '_samples', folder: DRIVE_FOLDER,
          fileNamePrefix: prefix + '_samples', fileFormat: 'CSV',
          selectors: ['task_id', 'person', 'location', 'scene_key', 'asset_id', 'acquisition_utc',
            'event_group', 'polygon_id', 'class_id', 'class_name', 'split', 'source_url', 'source_note',
            'run_tag', 'processing', 'label_schema', 'confidence', 'label_eligible', 'review_status',
            'longitude', 'latitude'].concat(BANDS)});
        Export.table.toDrive({collection: ee.FeatureCollection(selected), description: prefix + '_labels',
          folder: DRIVE_FOLDER, fileNamePrefix: prefix + '_labels', fileFormat: 'GeoJSON'});
        print('All polygon checks', result);
        print('Batch sample counts (high-confidence known classes only)', samples.aggregate_histogram('polygon_id'));
        status.setValue('Prepared ' + (hasSamples ? '2 tasks (CSV + GeoJSON)' : '1 task (review-only GeoJSON; no eligible samples)') + '. Batch ' + BATCH_NUMBER + ' of ' + total +
          '. Start in Tasks. ' + (BATCH_NUMBER < total ? 'Then increase BATCH_NUMBER and Run; keep drawings unchanged.' : 'All batches prepared once earlier batches are complete.'));
      });
    });
  });
}
if (MODE === 'SEARCH') search(); else label();

// API references:
// https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED
// https://developers.google.com/earth-engine/apidocs/export-image-todrive
// https://developers.google.com/earth-engine/apidocs/ui-map-geometrylayer-geometries
