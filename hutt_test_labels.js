// PLUMEWATCH: independent test labels for the existing Hutt training acquisition.
// Paste into a NEW GEE Code Editor script. Save as Hutt_20200713_test.
// Draw two layers, Import as FeatureCollection: plumeTest and backgroundTest.
// Save and Run after editing polygons, then click Prepare test batch.
// All samples are labelled split='test'; do not use them to fit the model.

var BATCH_NUMBER = 1;
var POLYGONS_PER_BATCH = 2;
var RUN_TAG = 'test_v1';
var DRIVE_FOLDER = 'NZ_Plume_Test';
var SAMPLE_LIMIT = 2000;
var ASSET = 'COPERNICUS/S2_SR_HARMONIZED/20200712T222549_20200712T222545_T60GUV';
var BANDS = ['B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B11', 'B12'];
// Exact training boundaries from your exported GeoJSON; do not edit these.
var TRAINING_RINGS = [
  [[174.87782721304268,-41.26762778708208],[174.8682141759333,-41.27162750243136],[174.87164740347237,-41.278207146133425],[174.8795438268122,-41.27691707218894],[174.88709692739815,-41.28001320681792],[174.89173178457588,-41.27704608073083],[174.89156012319893,-41.2726596472611],[174.89035849356026,-41.26943414048524],[174.88280539297435,-41.2677568139825],[174.87782721304268,-41.26762778708208]],
  [[174.8721446961471,-41.25568740008632],[174.87399005594935,-41.257881223799124],[174.87544917765345,-41.25917167391612],[174.87759494486536,-41.260462098536706],[174.88038444224085,-41.26165571861081],[174.8839035004684,-41.26165571861081],[174.88360309305875,-41.26049435882554],[174.88171481791224,-41.25920393484238],[174.878968235881,-41.25749408379224],[174.8770799607345,-41.256171338121874],[174.8745050400802,-41.25517119556321],[174.87278842631068,-41.25500988081313],[174.8721446961471,-41.25568740008632]]
];

function batch(items, number, size) {
  if (number < 1 || number % 1 || size < 1 || size > 4 || size % 1) {
    throw new Error('Use a positive integer batch number and 1-4 polygons per batch.');
  }
  return items.slice((number - 1) * size, number * size);
}
function problem(row) {
  if (['Polygon', 'MultiPolygon'].indexOf(row.kind) < 0) return 'Use a polygon.';
  if (!(row.area > 0) || row.area > 1e6) return 'Keep each test feature below 1 square kilometre.';
  if (row.outside > 0.1) return 'Polygon extends outside the yellow study boundary.';
  if (row.training_overlap > 0.1) return 'Polygon enters the orange training exclusion zone.';
  if (row.test_overlap > 0.1) return 'Polygon overlaps another test feature.';
  if (!(row.usable > 0)) return 'No usable pixels after quality masking.';
  return '';
}

// GEE runtime begins.
batch([], BATCH_NUMBER, POLYGONS_PER_BATCH);
if (!/^[A-Za-z0-9_-]+$/.test(RUN_TAG)) throw new Error('Use letters/numbers/underscore/hyphen for RUN_TAG.');
var roi = ee.Geometry.Rectangle([174.80, -41.32, 174.96, -41.20], null, false);
var training = ee.FeatureCollection(TRAINING_RINGS.map(function(ring, i) {
  return ee.Feature(ee.Geometry.Polygon([ring]), {class_id: i});
}));
// 30 m buffer reduces shared/resampled edge pixels; it does not remove spatial autocorrelation.
var exclusion = training.geometry().buffer(30, 1);
var image = ee.Image(ASSET);
var projection = image.select('B2').projection();
var scl = image.select('SCL');
var valid = scl.neq(0).and(scl.neq(1)).and(scl.neq(3)).and(scl.lt(8))
  .and(image.select(BANDS).mask().reduce(ee.Reducer.min()));
var usable = image.select(BANDS).multiply(0.0001).toFloat().updateMask(valid);

function group(input, prefix, code) {
  return ee.FeatureCollection(input).map(function(f) {
    return f.set({polygon_id: ee.String('hutt_20200713_' + prefix + '_').cat(ee.String(f.id())),
      class_id: code, split: 'test', scene_key: 'hutt_20200713', asset_id: ASSET,
      acquisition_utc: image.date().format('YYYY-MM-dd HH:mm:ss'),
      source_url: 'https://doi.org/10.1080/00288330.2022.2088569',
      figure: 'Gall et al. 2022, Figure 10A', run_tag: RUN_TAG,
      processing: 'S2_SR_HARMONIZED_SCL_v1'});
  });
}
var labels = group(typeof plumeTest === 'undefined' ? [] : plumeTest, 'plumeTest', 1)
  .merge(group(typeof backgroundTest === 'undefined' ? [] : backgroundTest, 'backgroundTest', 0))
  .sort('polygon_id');

Map.centerObject(roi, 12);
Map.addLayer(image.clip(roi), {bands: ['B4', 'B3', 'B2'], min: 0, max: 2500, gamma: 1.2}, '13 July 2020 NZ: RGB');
Map.addLayer(image.clip(roi), {bands: ['B8', 'B4', 'B3'], min: 0, max: 3500, gamma: 1.2}, 'NIR/red/green', false);
Map.addLayer(valid.not().selfMask().clip(roi), {palette: ['ff00ff']}, 'Quality-rejected pixels', false);
Map.addLayer(ee.FeatureCollection([ee.Feature(exclusion)]).style({color: 'ff8800', fillColor: 'ff880033', width: 2}), {}, 'Training exclusion: do not label');
Map.addLayer(training.style({color: 'ff0000', fillColor: '00000000', width: 2}), {}, 'Existing training polygons');
Map.addLayer(ee.Image().byte().paint(roi, 1, 2), {palette: ['ffff00']}, 'Study boundary');
var panel = ui.Panel({style: {width: '370px', padding: '10px'}});
panel.add(ui.Label('Draw independent test polygons', {fontWeight: 'bold'}));
panel.add(ui.Label('New drawing layers: plumeTest and backgroundTest. Import both as FeatureCollection. ' +
  'Stay outside orange areas. Save and Run after drawing. This is a same-image pilot test.'));
var status = ui.Label('Draw labels, then save and rerun.');
var button = ui.Button('Prepare test batch ' + BATCH_NUMBER);
panel.add(status); panel.add(button); ui.root.insert(0, panel);
var prepared = false;

button.onClick(function() {
  if (prepared) return;
  button.setDisabled(true); status.setValue('Checking test labels...');
  function stop(message) { status.setValue(message); button.setDisabled(false); }
  labels.size().evaluate(function(count, error) {
    if (error) { stop('Cannot read labels: ' + error); return; }
    if (!count || count > 30) { stop('Draw 1-30 polygon features, save and rerun.'); return; }
    var checks = labels.map(function(f) {
      var g = f.geometry();
      var others = labels.filter(ee.Filter.neq('polygon_id', f.get('polygon_id'))).map(function(o) {
        return o.set('overlap', g.intersection(o.geometry(), 1).area(1));
      });
      return ee.Feature(null, {id: f.get('polygon_id'), kind: g.type(), area: g.area(1),
        outside: g.difference(roi, 1).area(1), training_overlap: g.intersection(exclusion, 1).area(1),
        test_overlap: ee.Algorithms.If(others.size(), others.aggregate_max('overlap'), 0),
        usable: usable.select('B2').reduceRegion({reducer: ee.Reducer.count(), geometry: g,
          crs: projection, scale: 10, maxPixels: 1e7, tileScale: 4}).get('B2')});
    });
    checks.toList(count).map(function(f) { return ee.Feature(f).toDictionary(); }).evaluate(function(rows, err) {
      if (err) { stop('Check failed; no tasks created. Try smaller polygons. ' + err); return; }
      var ids = rows.map(function(r) { return r.id; });
      if (ids.some(function(id, i) { return ids.indexOf(id) !== i; })) { stop('Duplicate feature IDs. Use separate features with unique IDs.'); return; }
      var failures = rows.map(function(r) { var p = problem(r); return p ? r.id + ': ' + p : ''; }).filter(Boolean);
      if (failures.length) { print('Fix labels', failures); stop('No tasks created. See Console.'); return; }
      var selected = batch(rows, BATCH_NUMBER, POLYGONS_PER_BATCH);
      if (!selected.length) { stop('There are only ' + Math.ceil(count / POLYGONS_PER_BATCH) + ' batches.'); return; }
      var prefix = 'hutt_20200713_' + RUN_TAG + '_b' + BATCH_NUMBER;
      var manifest = [];
      selected.forEach(function(row, i) {
        var name = prefix + '_p' + ((BATCH_NUMBER - 1) * POLYGONS_PER_BATCH + i + 1);
        var f = ee.Feature(labels.filter(ee.Filter.eq('polygon_id', row.id)).first()).set('export_stem', name);
        manifest.push(f);
        var samples = usable.addBands(ee.Image.pixelLonLat()).sample({region: f.geometry(),
          projection: projection, scale: 10, numPixels: SAMPLE_LIMIT, seed: 99,
          dropNulls: true, tileScale: 4, geometries: false}).limit(SAMPLE_LIMIT)
          .map(function(p) { return p.set(f.toDictionary()); });
        Export.table.toDrive({collection: samples, description: name + '_samples',
          folder: DRIVE_FOLDER, fileNamePrefix: name + '_samples', fileFormat: 'CSV',
          selectors: ['scene_key','asset_id','acquisition_utc','polygon_id','class_id','split',
            'source_url','figure','run_tag','processing','export_stem','longitude','latitude'].concat(BANDS)});
      });
      Export.table.toDrive({collection: ee.FeatureCollection(manifest), description: prefix + '_labels',
        folder: DRIVE_FOLDER, fileNamePrefix: prefix + '_labels', fileFormat: 'GeoJSON'});
      print('Usable pixels in selected polygons', selected);
      print('All test class counts (both classes needed for a two-class evaluation)', labels.aggregate_histogram('class_id'));
      prepared = true;
      status.setValue('Prepared ' + (selected.length + 1) + ' tasks. Start them in Tasks. Batch ' +
        BATCH_NUMBER + ' of ' + Math.ceil(count / POLYGONS_PER_BATCH) + '.');
    });
  });
});
