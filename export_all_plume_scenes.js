// PLUMEWATCH — ALL SPREADSHEET SCENES FOR CVAT
// Paste the WHOLE file into a new GEE Code Editor script and click Run.
// Wait for the searches, then click "Prepare all image exports" in the panel.
// Start exports in the Tasks tab. GEE queues work; these are separate tasks.
// No drawing needed. Download the GeoTIFFs AND manifest CSV from Google Drive.
// Candidates are not automatically confirmed plumes. Inspect before labelling.

// ================= OPTIONAL SETTINGS =================
var DRIVE_FOLDER = 'PlumeWatch_CVAT_Scenes';
var RUN_TAG = 'cvat_v1';
var PERSON_FILTER = '';       // '' = everyone; or 'Person 1', 'Person 2', 'Person 3'
var TASK_IDS = [];            // [] = all; or ['P1-01', 'P3-05'] to retry selected rows
var RADIUS_KM = 10;           // About 20 x 20 km per crop; use 5 for smaller files
var MAX_CANDIDATES_PER_ROW = 30; // Too many? Flag row, never silently truncate it
var MAX_TILE_CLOUD_PERCENT = 100; // Tile-wide cloud is NOT local plume cloud
// Exact asset IDs from the spreadsheet override this cloud filter.
// Different rows may intentionally crop the same acquisition at different rivers.
// Keep shared acquisitions/events together when assigning train/test splits.

// ================= SPREADSHEET ROWS =================
var ASSIGNMENTS = [
  {"task_id": "P1-01", "person": "Person 1", "location": "Hutt / Wellington Harbour", "latitude": -41.24, "longitude": 174.9, "evidence": "Confirmed Sentinel-2 plume", "start": "2019-08-12", "last": "2019-08-13", "event_group": "Hutt 2019-08-13", "asset_id": "", "split": "unassigned", "source_note": "Gall et al., Fig. 10B. Keep existing development data out of training.", "source_url": "https://doi.org/10.1080/00288330.2022.2088569"},
  {"task_id": "P1-02", "person": "Person 1", "location": "Hutt / Wellington Harbour", "latitude": -41.24, "longitude": 174.9, "evidence": "Confirmed Sentinel-2 plume", "start": "2020-07-02", "last": "2020-07-03", "event_group": "Hutt 2020-07-03", "asset_id": "", "split": "unassigned", "source_note": "Gall et al., Fig. 10D. Keep existing development data out of training.", "source_url": "https://doi.org/10.1080/00288330.2022.2088569"},
  {"task_id": "P1-03", "person": "Person 1", "location": "Hutt / Wellington Harbour", "latitude": -41.24, "longitude": 174.9, "evidence": "Confirmed Sentinel-2 plume", "start": "2020-07-12", "last": "2020-07-13", "event_group": "Hutt 2020-07-13", "asset_id": "COPERNICUS/S2_SR_HARMONIZED/20200712T222549_20200712T222545_T60GUV", "split": "training", "source_note": "Gall et al., Fig. 10A. Keep existing development data out of training.", "source_url": "https://doi.org/10.1080/00288330.2022.2088569"},
  {"task_id": "P1-04", "person": "Person 1", "location": "Hutt / Wellington Harbour", "latitude": -41.24, "longitude": 174.9, "evidence": "Confirmed Sentinel-2 plume", "start": "2021-07-22", "last": "2021-07-23", "event_group": "Hutt 2021-07-23", "asset_id": "COPERNICUS/S2_SR_HARMONIZED/20210722T222551_20210722T222547_T60GUV", "split": "development", "source_note": "Gall et al., Fig. 10C. Keep existing development data out of training.", "source_url": "https://doi.org/10.1080/00288330.2022.2088569"},
  {"task_id": "P1-05", "person": "Person 1", "location": "Whanganui mouth", "latitude": -39.95, "longitude": 174.99, "evidence": "Regional MODIS plume; S2 candidate", "start": "2019-10-03", "last": "2019-10-09", "event_group": "West coast Oct 2019", "asset_id": "", "split": "unassigned", "source_note": "NIWA report Fig. 1-1. Confirm local plume in S2. 20 Sep 2019 is an optional regional comparison.", "source_url": "https://www.envirolink.govt.nz/assets/Envirolink/2011-HZLC159-River-Plume-Dynamics-in-the-Coastal-Marine-Area.pdf"},
  {"task_id": "P1-06", "person": "Person 1", "location": "Rangitīkei mouth", "latitude": -40.3, "longitude": 175.22, "evidence": "Regional MODIS plume; S2 candidate", "start": "2019-10-03", "last": "2019-10-09", "event_group": "West coast Oct 2019", "asset_id": "", "split": "unassigned", "source_note": "NIWA report Fig. 1-1. Confirm local plume in S2. 20 Sep 2019 is an optional regional comparison.", "source_url": "https://www.envirolink.govt.nz/assets/Envirolink/2011-HZLC159-River-Plume-Dynamics-in-the-Coastal-Marine-Area.pdf"},
  {"task_id": "P1-07", "person": "Person 1", "location": "Manawatū mouth", "latitude": -40.47, "longitude": 175.22, "evidence": "Regional MODIS plume; S2 candidate", "start": "2019-10-03", "last": "2019-10-09", "event_group": "West coast Oct 2019", "asset_id": "", "split": "unassigned", "source_note": "NIWA report Fig. 1-1. Confirm local plume in S2. 20 Sep 2019 is an optional regional comparison.", "source_url": "https://www.envirolink.govt.nz/assets/Envirolink/2011-HZLC159-River-Plume-Dynamics-in-the-Coastal-Marine-Area.pdf"},
  {"task_id": "P2-01", "person": "Person 2", "location": "Waiau Uwha mouth", "latitude": -42.78, "longitude": 173.38, "evidence": "Confirmed S2 regional plume", "start": "2021-06-02", "last": "2021-06-02", "event_group": "Canterbury flood 2021", "asset_id": "", "split": "unassigned", "source_note": "Sentinel Vision post-flood figures. River identification is geographic interpretation; verify each crop.", "source_url": "https://www.sentinelvision.eu/gallery/pdf/6f363c8b4fcc48e8b1c2038e61d19556"},
  {"task_id": "P2-02", "person": "Person 2", "location": "Waiau Uwha mouth", "latitude": -42.78, "longitude": 173.38, "evidence": "Before-event comparison", "start": "2021-04-28", "last": "2021-04-28", "event_group": "Canterbury comparison Apr 2021", "asset_id": "", "split": "unassigned", "source_note": "Comparison image may already contain sediment. Do not assume plume-free water.", "source_url": "https://www.sentinelvision.eu/gallery/pdf/6f363c8b4fcc48e8b1c2038e61d19556"},
  {"task_id": "P2-03", "person": "Person 2", "location": "Hurunui mouth", "latitude": -42.91, "longitude": 173.28, "evidence": "Confirmed S2 regional plume", "start": "2021-06-02", "last": "2021-06-02", "event_group": "Canterbury flood 2021", "asset_id": "", "split": "unassigned", "source_note": "Sentinel Vision post-flood figures. River identification is geographic interpretation; verify each crop.", "source_url": "https://www.sentinelvision.eu/gallery/pdf/6f363c8b4fcc48e8b1c2038e61d19556"},
  {"task_id": "P2-04", "person": "Person 2", "location": "Hurunui mouth", "latitude": -42.91, "longitude": 173.28, "evidence": "Before-event comparison", "start": "2021-04-28", "last": "2021-04-28", "event_group": "Canterbury comparison Apr 2021", "asset_id": "", "split": "unassigned", "source_note": "Comparison image may already contain sediment. Do not assume plume-free water.", "source_url": "https://www.sentinelvision.eu/gallery/pdf/6f363c8b4fcc48e8b1c2038e61d19556"},
  {"task_id": "P2-05", "person": "Person 2", "location": "Waimakariri / Pegasus Bay", "latitude": -43.39, "longitude": 172.71, "evidence": "Confirmed S2 regional plume", "start": "2021-06-02", "last": "2021-06-02", "event_group": "Canterbury flood 2021", "asset_id": "", "split": "unassigned", "source_note": "Sentinel Vision post-flood figures. River identification is geographic interpretation; verify each crop.", "source_url": "https://www.sentinelvision.eu/gallery/pdf/6f363c8b4fcc48e8b1c2038e61d19556"},
  {"task_id": "P2-06", "person": "Person 2", "location": "Waimakariri / Pegasus Bay", "latitude": -43.39, "longitude": 172.71, "evidence": "Before-event comparison", "start": "2021-04-28", "last": "2021-04-28", "event_group": "Canterbury comparison Apr 2021", "asset_id": "", "split": "unassigned", "source_note": "Comparison image may already contain sediment. Do not assume plume-free water.", "source_url": "https://www.sentinelvision.eu/gallery/pdf/6f363c8b4fcc48e8b1c2038e61d19556"},
  {"task_id": "P3-01", "person": "Person 3", "location": "Raukōkore / Papatea Bay", "latitude": -37.73, "longitude": 177.98, "evidence": "Confirmed Sentinel-2 plume", "start": "2023-02-13", "last": "2023-02-15", "event_group": "Cyclone Gabrielle 2023", "asset_id": "", "split": "unassigned", "source_note": "University of Waikato caption identifies S2 sediment plume. Search neighbouring Waihau Bay as needed.", "source_url": "https://www.waikato.ac.nz/news-events/news/marine-darkwaves-in-waihau-bay/"},
  {"task_id": "P3-02", "person": "Person 3", "location": "Mohaka mouth", "latitude": -39.13, "longitude": 177.19, "evidence": "Regional plume; local scene unverified", "start": "2023-02-17", "last": "2023-02-19", "event_group": "Cyclone Gabrielle 2023", "asset_id": "", "split": "unassigned", "source_note": "AEBR 343 Fig. 4. Confirm sensor and plume within the crop; regional evidence does not identify every river contribution.", "source_url": "https://www.mpi.govt.nz/dmsdocument/65160/direct"},
  {"task_id": "P3-03", "person": "Person 3", "location": "Wairoa mouth", "latitude": -39.06, "longitude": 177.42, "evidence": "Regional plume; local scene unverified", "start": "2023-02-17", "last": "2023-02-19", "event_group": "Cyclone Gabrielle 2023", "asset_id": "", "split": "unassigned", "source_note": "AEBR 343 Fig. 4. Confirm sensor and plume within the crop; regional evidence does not identify every river contribution.", "source_url": "https://www.mpi.govt.nz/dmsdocument/65160/direct"},
  {"task_id": "P3-04", "person": "Person 3", "location": "Nūhaka mouth", "latitude": -39.07, "longitude": 177.76, "evidence": "Regional plume; local scene unverified", "start": "2023-02-17", "last": "2023-02-19", "event_group": "Cyclone Gabrielle 2023", "asset_id": "", "split": "unassigned", "source_note": "AEBR 343 Fig. 4. Confirm sensor and plume within the crop; regional evidence does not identify every river contribution.", "source_url": "https://www.mpi.govt.nz/dmsdocument/65160/direct"},
  {"task_id": "P3-05", "person": "Person 3", "location": "Waipaoa / Tūranganui-a-Kiwa", "latitude": -38.69, "longitude": 177.97, "evidence": "Event-supported candidate", "start": "2023-02-14", "last": "2023-02-28", "event_group": "Cyclone Gabrielle 2023", "asset_id": "", "split": "unassigned", "source_note": "AEBR 343 identifies regional river sediment sources. Find and verify an optical plume scene before labelling.", "source_url": "https://www.mpi.govt.nz/dmsdocument/65160/direct"},
  {"task_id": "P3-06", "person": "Person 3", "location": "Uawa / Tolaga Bay", "latitude": -38.37, "longitude": 178.3, "evidence": "Event-supported candidate", "start": "2023-02-14", "last": "2023-02-28", "event_group": "Cyclone Gabrielle 2023", "asset_id": "", "split": "unassigned", "source_note": "AEBR 343 identifies regional river sediment sources. Find and verify an optical plume scene before labelling.", "source_url": "https://www.mpi.govt.nz/dmsdocument/65160/direct"},
  {"task_id": "P3-07", "person": "Person 3", "location": "Waiapu mouth", "latitude": -37.79, "longitude": 178.57, "evidence": "Event-supported candidate", "start": "2023-02-14", "last": "2023-02-28", "event_group": "Cyclone Gabrielle 2023", "asset_id": "", "split": "unassigned", "source_note": "AEBR 343 identifies regional river sediment sources. Find and verify an optical plume scene before labelling.", "source_url": "https://www.mpi.govt.nz/dmsdocument/65160/direct"}
];

// ================= ENGINE — NO EDITS NEEDED =================
var COLLECTION = 'COPERNICUS/S2_SR_HARMONIZED';
var BANDS = ['B2','B3','B4','B5','B6','B7','B8','B8A','B11','B12'];
function validDate(s) {
  var d = new Date(s + 'T00:00:00Z');
  return /^\d{4}-\d{2}-\d{2}$/.test(s) && !isNaN(d.getTime()) && d.toISOString().slice(0,10) === s;
}
function selectedRows(rows) {
  return rows.filter(function(r) {
    return (!PERSON_FILTER || r.person === PERSON_FILTER) && (!TASK_IDS.length || TASK_IDS.indexOf(r.task_id) >= 0);
  });
}
function resultProblem(result, error) {
  if (error) return 'SEARCH FAILED: ' + error;
  if (!result || !result.count) return 'NO MATCH: check dates/location; no substitute image selected.';
  if (result.count > MAX_CANDIDATES_PER_ROW) return 'TOO MANY (' + result.count + '): narrow this row’s dates or raise the limit; none exported.';
  return '';
}
function exportStem(row, scene) { return row.task_id + '_' + scene.scene_key + '_' + RUN_TAG; }
function region(row) { return ee.Geometry.Point([row.longitude,row.latitude]).buffer(RADIUS_KM*1000).bounds(); }
if (!(RADIUS_KM > 0 && RADIUS_KM <= 10)) throw new Error('Use RADIUS_KM > 0 and <= 10 to keep files manageable.');
if (!(MAX_CANDIDATES_PER_ROW >= 1 && MAX_CANDIDATES_PER_ROW <= 100 && MAX_CANDIDATES_PER_ROW % 1 === 0)) throw new Error('Candidate limit must be an integer from 1 to 100.');
if (!(MAX_TILE_CLOUD_PERCENT >= 0 && MAX_TILE_CLOUD_PERCENT <= 100)) throw new Error('Cloud limit must be 0–100.');
if (!/^[A-Za-z0-9_-]{1,16}$/.test(RUN_TAG) || !DRIVE_FOLDER) throw new Error('Use a short RUN_TAG and a Drive folder name.');
ASSIGNMENTS.forEach(function(r) {
  if (!validDate(r.start) || !validDate(r.last) || r.start > r.last) throw new Error('Invalid dates: ' + r.task_id);
  if (r.asset_id && r.asset_id.indexOf(COLLECTION + '/') !== 0) throw new Error('Invalid asset ID: ' + r.task_id);
});
var rows = selectedRows(ASSIGNMENTS);
if (!rows.length) throw new Error('No assignments match PERSON_FILTER / TASK_IDS.');
var candidates = [], issues = [], prepared = {};
var panel = ui.Panel({style:{width:'390px',padding:'10px'}});
panel.add(ui.Label('PlumeWatch — spreadsheet image exports',{fontWeight:'bold'}));
panel.add(ui.Label('Each task is one date/tile/location crop. No mosaics. No label polygons required.'));
var status = ui.Label('Searching...'); panel.add(status);
var allButton = ui.Button('Prepare all image exports',null,true);
panel.add(allButton);
var manifestButton = ui.Button('Prepare manifest CSV',null,true);
panel.add(manifestButton);
panel.add(ui.Label('Optional: choose a candidate to inspect. Cloud-free does not mean plume-confirmed.'));
var preview = ui.Select({items:[],placeholder:'Candidates appear after search',disabled:true});
panel.add(preview);
var details = ui.Label(''); panel.add(details);
ui.root.insert(0,panel);
Map.setCenter(174,-41,6);

function searchRow(index) {
  if (index >= rows.length) { finishSearch(); return; }
  var row = rows[index], roi = region(row);
  status.setValue('Searching ' + (index+1) + '/' + rows.length + ': ' + row.task_id + ' ' + row.location);
  var collection = ee.ImageCollection(COLLECTION).filterBounds(roi)
    .filterDate(row.start,ee.Date(row.last).advance(1,'day'));
  if (row.asset_id) collection = collection.filter(ee.Filter.eq('system:index',row.asset_id.split('/').pop()));
  else collection = collection.filter(ee.Filter.lte('CLOUDY_PIXEL_PERCENTAGE',MAX_TILE_CLOUD_PERCENT));
  collection = collection.sort('system:index');
  var list = collection.limit(MAX_CANDIDATES_PER_ROW).toList(MAX_CANDIDATES_PER_ROW).map(function(item) {
    var im = ee.Image(item);
    return ee.Dictionary({scene_key:im.get('system:index'),grid:im.select('B2').projection(),
      utc:im.date().format('YYYY-MM-dd HH:mm:ss','UTC'),nz:im.date().format('YYYY-MM-dd HH:mm:ss','Pacific/Auckland'),
      tile:im.get('MGRS_TILE'),cloud:im.get('CLOUDY_PIXEL_PERCENTAGE')});
  });
  // Only small metadata comes to the browser. Search one row at a time.
  ee.Dictionary({count:collection.size(),images:list}).evaluate(function(result,error) {
    var problem = resultProblem(result,error);
    if (problem) { issues.push(row.task_id + ': ' + problem); print(row.task_id,problem); }
    else {
      result.images.forEach(function(scene) { candidates.push({row:row,scene:scene}); });
      print(row.task_id + ' — ' + row.location + ': ' + result.count + ' candidate(s)', result.images);
    }
    searchRow(index+1);
  });
}
function metadata(item) {
  var r=item.row,s=item.scene;
  return {file_prefix:exportStem(r,s),task_id:r.task_id,person:r.person,location:r.location,
    asset_id:COLLECTION+'/'+s.scene_key,scene_key:s.scene_key,acquisition_utc:s.utc,acquisition_nz:s.nz,
    mgrs_tile:s.tile,tile_cloud_percent:s.cloud,latitude:r.latitude,longitude:r.longitude,radius_km:RADIUS_KM,
    crs:s.grid.crs,crs_transform:JSON.stringify(s.grid.transform),event_group:r.event_group,split:r.split,
    evidence:r.evidence,source_url:r.source_url,source_note:r.source_note,
    search_start_utc:r.start,search_last_day_utc:r.last,review_status:'not_reviewed',
    processing:'S2_SR_HARMONIZED_SCL_v1',bands:BANDS.concat(['SCL','valid']).join(','),run_tag:RUN_TAG};
}
function prepareImage(item) {
  var row=item.row, scene=item.scene, stem=exportStem(row,scene);
  if (prepared[stem]) return;
  var im=ee.Image(COLLECTION+'/'+scene.scene_key), scl=im.select('SCL');
  var valid=scl.neq(0).and(scl.neq(1)).and(scl.neq(3)).and(scl.lt(8))
    .and(im.select(BANDS).mask().reduce(ee.Reducer.min())).rename('valid');
  // Same 12-band format as the existing exports/dashboard; nearest-neighbour sampling.
  // SCL is quality screening, NOT a water mask. Retain land for multiclass labelling.
  var raster=im.select(BANDS).multiply(0.0001).toFloat().updateMask(valid)
    .addBands(scl.toFloat()).addBands(valid.unmask(0).toFloat())
    .clip(region(row)).unmask({value:-9999,sameFootprint:false});
  Export.image.toDrive({image:raster,description:stem,folder:DRIVE_FOLDER,fileNamePrefix:stem,
    region:region(row),crs:scene.grid.crs,crsTransform:scene.grid.transform,
    maxPixels:1e7,shardSize:256,fileDimensions:4096,fileFormat:'GeoTIFF',
    formatOptions:{cloudOptimized:true,noData:-9999}});
  prepared[stem]=true;
}
function finishSearch() {
  status.setValue('Search complete: ' + candidates.length + ' candidates; ' + issues.length + ' rows need attention.');
  if (issues.length) print('ROWS NEEDING ATTENTION — retry with TASK_IDS after adjusting dates',issues);
  if (!candidates.length) return;
  preview.items().reset(candidates.map(function(item,i) {
    return {label:item.row.task_id+' | '+item.scene.utc+' UTC | '+item.scene.tile,value:String(i)};
  }));
  preview.setDisabled(false); allButton.setDisabled(false);
  preview.onChange(function(value) {
    var item=candidates[Number(value)],roi=region(item.row);
    Map.layers().reset(); Map.centerObject(roi,11);
    Map.addLayer(ee.Image(COLLECTION+'/'+item.scene.scene_key).clip(roi),
      {bands:['B4','B3','B2'],min:0,max:2500,gamma:1.2},'Candidate RGB');
    Map.addLayer(ee.Image().byte().paint(roi,1,2),{palette:['ffff00']},'Crop boundary');
    details.setValue(item.row.location+' | '+item.row.evidence+' | tile cloud '+item.scene.cloud.toFixed(1)+'%. Tiles may cover only part of the crop.');
  });
  preview.setValue('0',true);
}
allButton.onClick(function() {
  allButton.setDisabled(true);
  candidates.forEach(function(item) {
    try { prepareImage(item); }
    catch (error) { print('EXPORT SETUP FAILED: '+item.row.task_id,error); }
  });
  manifestButton.setDisabled(Object.keys(prepared).length===0);
  status.setValue(Object.keys(prepared).length+' separate image tasks prepared. Start them in Tasks, and prepare the manifest below.');
});
manifestButton.onClick(function() {
  manifestButton.setDisabled(true);
  var records=candidates.filter(function(item) { return prepared[exportStem(item.row,item.scene)]; })
    .map(function(item) { return ee.Feature(null,metadata(item)); });
  Export.table.toDrive({collection:ee.FeatureCollection(records),description:'PlumeWatch_manifest_'+RUN_TAG,
    folder:DRIVE_FOLDER,fileNamePrefix:'PlumeWatch_manifest_'+RUN_TAG,fileFormat:'CSV'});
  status.setValue('Image + manifest tasks ready. Start in Tasks. CSV lists prepared exports, not proof they succeeded.');
});
searchRow(0);

// References:
// https://developers.google.com/earth-engine/apidocs/export-image-todrive
// https://developers.google.com/earth-engine/datasets/catalog/COPERNICUS_S2_SR_HARMONIZED
