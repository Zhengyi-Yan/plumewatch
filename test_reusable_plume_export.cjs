// Run with Node: node test_reusable_plume_export.cjs
// Local checks only; authenticated Earth Engine execution is a separate check.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const code = fs.readFileSync(__dirname + '/reusable_plume_export.js', 'utf8');
new vm.Script(code); // Parse the entire Code Editor script.
const helpers = code.slice(code.indexOf('function requireCondition'), code.indexOf("requireCondition(MODE"));
const ctx = {}; vm.createContext(ctx); vm.runInContext(helpers, ctx);
assert(ctx.validDate('2024-02-29'));
assert(!ctx.validDate('2023-02-29'));
assert(!ctx.validDate('2023-2-01'));
assert(!ctx.validDate('not-a-date'));
assert(ctx.integerBetween(4, 1, 10));
assert(!ctx.integerBetween(1.5, 1, 10));
const polygons = Array.from({length: 7}, (_, i) => i + 1);
assert.deepEqual(ctx.batchSlice(polygons, 1, 4), [1, 2, 3, 4]);
assert.deepEqual(ctx.batchSlice(polygons, 2, 4), [5, 6, 7]);
assert.deepEqual(ctx.batchSlice(polygons, 3, 4), []);
const good = {kind: 'Polygon', area: 1000, outside: 0, overlap: 0, usable: 10};
assert.equal(ctx.geometryProblem(good), '');
for (const patch of [{kind:'Point'}, {kind:'MultiPolygon'}, {area:0}, {area:1000001}, {outside:2}, {overlap:2}, {usable:0}, {usable:null}]) {
  assert(ctx.geometryProblem({...good, ...patch}));
}
assert.deepEqual([...ctx.batchSlice(polygons,1,4), ...ctx.batchSlice(polygons,2,4)], polygons);
for (const [name, id] of [['normal_water',0], ['plume',1], ['shallow_water',2], ['land',3]]) {
  const p = ctx.parseLayer(name);
  assert.equal(p.classId, id); assert.equal(p.confidence, 'high'); assert(p.eligible);
  assert.equal(ctx.parseLayer(name + '_medium_2').eligible, false);
  assert.equal(ctx.parseLayer(name + '_low').eligible, false);
  assert.equal(ctx.parseLayer(name + '_high_2').classId, id);
}
assert.equal(ctx.parseLayer('background_2').type, 'normal_water');
assert.equal(ctx.parseLayer('unknown_high').eligible, false);
assert.equal(ctx.parseLayer('unknown').classId, -1);
for(const bad of ['plumeTest', 'ships', 'land_medium_extra', 'plume_2_low']) assert.equal(ctx.parseLayer(bad), null);
assert.equal(ctx.geometryProblem({...good, eligible:false, usable:null}), '');
assert(ctx.geometryProblem({...good, eligible:true, usable:null}));
// Mixed batch: review polygons are preserved, only four known high classes sampled.
const mixed = ['plume', 'normal_water', 'shallow_water', 'land', 'unknown', 'plume_medium', 'land_low'].map(ctx.parseLayer);
assert.deepEqual(mixed.filter(p=>p.eligible).map(p=>p.classId), [1,0,2,3]);
assert(!ctx.batchSlice(mixed,2,4).some(p=>p.eligible));
console.log('PASS: syntax, dates, batches, geometry, class mapping and confidence exclusion.');
