// Run: node tests/test_review.js
const assert=require('node:assert/strict');
global.document={addEventListener:()=>{}};
const {disagrees,plumeColor}=require('../www/app.js');
assert.equal(disagrees(255,1),false);
assert.equal(disagrees(0,255),false);
assert.equal(disagrees(1,1),false);
assert.equal(disagrees(0,1),true);
console.log('Valid-pixel disagreement checks passed.');

assert.deepEqual(plumeColor(0,true),[59,130,246,0]);
assert.deepEqual(plumeColor(35,true),[45,190,170,71]);
assert.deepEqual(plumeColor(100,true),[239,103,63,204]);
assert.deepEqual(plumeColor(50,false),[136,176,133,225]);
assert.ok(plumeColor(20,true)[3]<plumeColor(80,true)[3]);
console.log('Plume ramp and original-colour rollback checks passed.');
