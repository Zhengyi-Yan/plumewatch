// PlumeWatch: export every drawn 2021 test polygon in one run.
// Keep the drawing layers in Imports. Name them plumeTest and backgroundTest.
// Multiple layers are also accepted when their names start with those words.

var ASSET = 'COPERNICUS/S2_SR_HARMONIZED/20210722T222551_20210722T222547_T60GUV';
var DRIVE_FOLDER = 'NZ_Plume_Test';
var RUN_TAG = 'test-v2';
var EXPECTED_PLUME_POLYGONS = 5;
var EXPECTED_BACKGROUND_POLYGONS = 2;
var SAMPLE_LIMIT_PER_POLYGON = 2000;
var BANDS = ['B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B11', 'B12'];

var image = ee.Image(ASSET);
var projection = image.select('B2').projection();
var scl = image.select('SCL');
var valid = scl.neq(0).and(scl.neq(1)).and(scl.neq(3)).and(scl.lt(8))
  .and(image.select(BANDS).mask().reduce(ee.Reducer.min()));
var usable = image.select(BANDS).multiply(0.0001).toFloat().updateMask(valid);

// Read individual geometries directly from every matching drawing layer.
// This avoids collapsing five drawings into a single imported feature.
var drawingTools = Map.drawingTools();
drawingTools.setLinked(true);
var rows = [];
var classCounts = {plume: 0, background: 0};

function collectDrawingLayers(prefix, className, classId) {
  drawingTools.layers().forEach(function(layer) {
    if (layer.getName().indexOf(prefix) !== 0) return;
    layer.geometries().forEach(function(geometry) {
      classCounts[className]++;
      rows.push({
        geometry: geometry,
        className: className,
        classId: classId,
        polygonId: 'hutt_20210723_' + prefix + '_' + classCounts[className]
      });
    });
  });
}

collectDrawingLayers('plumeTest', 'plume', 1);
collectDrawingLayers('backgroundTest', 'background', 0);

if (classCounts.plume !== EXPECTED_PLUME_POLYGONS ||
    classCounts.background !== EXPECTED_BACKGROUND_POLYGONS) {
  throw new Error(
    'Stopped before export: found ' + classCounts.plume + ' plume and ' +
    classCounts.background + ' background polygons. Expected ' +
    EXPECTED_PLUME_POLYGONS + ' plume and ' + EXPECTED_BACKGROUND_POLYGONS +
    ' background. Put every polygon in a drawing layer whose name starts with ' +
    'plumeTest or backgroundTest, then Run again.'
  );
}

var labelFeatures = [];
var allSamples = ee.FeatureCollection([]);

rows.forEach(function(row) {
  var properties = {
    scene_key: 'hutt_20210723',
    asset_id: ASSET,
    acquisition_utc: image.date().format('YYYY-MM-dd HH:mm:ss'),
    polygon_id: row.polygonId,
    class_id: row.classId,
    class_name: row.className,
    split: 'test',
    source_url: 'https://doi.org/10.1080/00288330.2022.2088569',
    figure: 'Gall et al. 2022, Figure 10C',
    run_tag: RUN_TAG,
    processing: 'S2_SR_HARMONIZED_SCL_v1'
  };
  var label = ee.Feature(row.geometry, properties);
  labelFeatures.push(label);

  var samples = usable.addBands(ee.Image.pixelLonLat()).sample({
    region: row.geometry,
    projection: projection,
    scale: 10,
    numPixels: SAMPLE_LIMIT_PER_POLYGON,
    seed: 99,
    dropNulls: true,
    tileScale: 4,
    geometries: false
  }).limit(SAMPLE_LIMIT_PER_POLYGON).map(function(pixel) {
    return pixel.set(properties);
  });
  allSamples = allSamples.merge(samples);
});

var labels = ee.FeatureCollection(labelFeatures);
var prefix = 'hutt_20210723_' + RUN_TAG;

Export.table.toDrive({
  collection: allSamples,
  description: prefix + '_all_samples',
  folder: DRIVE_FOLDER,
  fileNamePrefix: prefix + '_all_samples',
  fileFormat: 'CSV',
  selectors: [
    'scene_key', 'asset_id', 'acquisition_utc', 'polygon_id', 'class_id',
    'class_name', 'split', 'source_url', 'figure', 'run_tag', 'processing',
    'longitude', 'latitude'
  ].concat(BANDS)
});

Export.table.toDrive({
  collection: labels,
  description: prefix + '_all_labels',
  folder: DRIVE_FOLDER,
  fileNamePrefix: prefix + '_all_labels',
  fileFormat: 'GeoJSON'
});

Map.centerObject(image.geometry(), 9);
Map.setCenter(174.88, -41.26, 12);
Map.addLayer(image, {bands: ['B4', 'B3', 'B2'], min: 0, max: 2500, gamma: 1.2}, '23 July 2021 NZ RGB');
Map.addLayer(labels.style({color: 'ffff00', fillColor: '00000000', width: 2}), {}, 'Labels being exported');

print('Found polygons', classCounts);
print('Expected output: 2 Tasks (one combined CSV and one GeoJSON).');
print('Per-polygon sample counts', allSamples.aggregate_histogram('polygon_id'));
