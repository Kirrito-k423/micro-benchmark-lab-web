import {readFileSync,existsSync} from 'node:fs';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
import {measurementSource,sourceExcerpts,implementationContext} from '../src/measurement-source.js';

const read=name=>JSON.parse(readFileSync(new URL(`../public/data/${name}.json`,import.meta.url)));
const catalog=read('measurement-code');
for(const [hash,file] of Object.entries(catalog.files)) {
  assert.equal(createHash('sha256').update(file.text).digest('hex'),hash);
  assert.equal(file.sha256,hash);
  assert.match(file.url,new RegExp(`/blob/${file.contentCommit}/`));
}
const sets=[['capacity','datacopy','rows'],['alignment','a5-mbench','alignment'],['alignment','a5-mbench','alignmentPaired'],['simt','a5-mbench','simt'],['simd','a5-simd','rows'],['bandwidth','a5-bandwidth','rows'],['network','a5-network','rows']];
if(existsSync(new URL('../public/data/a5-store-tail.json',import.meta.url)))sets.push(['store-tail','a5-store-tail','rows']);
if(existsSync(new URL('../public/data/a5-workset.json',import.meta.url)))sets.push(['workset','a5-workset','rows']);
if(existsSync(new URL('../public/data/a5-peer-copy.json',import.meta.url)))sets.push(['peer-copy','a5-peer-copy','rows']);
if(existsSync(new URL('../public/data/a5-page-retest.json',import.meta.url)))sets.push(['page-retest','a5-page-retest','rows']);
let points=0;
for(const [family,name,key] of sets) {
  const db=read(name);
  for(const row of db[key]) {
    const source=measurementSource(catalog,family,row,db);
    assert.ok(source,`Unbound ${family} ${row.id}`);
    for(const b of sourceExcerpts(source,family,row)) {
      assert.equal(b.text,b.file.text.split('\n').slice(b.start-1,b.end).join('\n'));
      assert.ok(b.text.trim(),`Empty excerpt ${row.id}`);
    }
    const context=implementationContext(family,row,db);
    assert.ok(context.timing&&context.notes.length);
    assert.ok(!JSON.stringify(context).includes('undefined'),row.id);
    points++;
  }
}
const capacity=read('datacopy');
const serial=capacity.rows.find(r=>r.device==='A3'&&r.run==='long-window-1');
const pipeline=capacity.rows.find(r=>r.device==='A3'&&r.run==='w2-small-long-1');
assert.notEqual(measurementSource(catalog,'capacity',serial,capacity).build.binarySha256,measurementSource(catalog,'capacity',pipeline,capacity).build.binarySha256);
assert.ok(!sourceExcerpts(measurementSource(catalog,'capacity',serial,capacity),'capacity',serial)[0].text.includes('Pipeline'));
assert.equal(measurementSource(catalog,'capacity',{...serial,run:'missing-run'},capacity),null);
const net=read('a5-network');
const native=net.rows.find(r=>r.completionImpl==='sdk');
const grouped=net.rows.find(r=>r.completionImpl==='cq-grouped');
assert.notEqual(measurementSource(catalog,'network',native,net).build.binarySha256,measurementSource(catalog,'network',grouped,net).build.binarySha256);
assert.equal(measurementSource(catalog,'network',{...grouped,binarySha256:'unknown'},net),null);
assert.equal(measurementSource(catalog,'network',{...grouped,sourceCommit:'wrong'},net),null);
const bad=structuredClone(net);bad.evidence.measurementSourceSha256ByBinary[grouped.binarySha256]['src/kernel.cpp']='wrong';
assert.equal(measurementSource(catalog,'network',grouped,bad),null);
if(sets.some(([family])=>family==='store-tail')) {
  const db=read('a5-store-tail'),row=db.rows[0];
  assert.equal(measurementSource(catalog,'store-tail',{...row,binaryHash:'unknown'},db),null);
  const wrong=structuredClone(db);wrong.evidence.sourceCommit='wrong';
  assert.equal(measurementSource(catalog,'store-tail',row,wrong),null);
}
if(sets.some(([family])=>family==='page-retest')) {
  const db=read('a5-page-retest'),row=db.rows[0];
  assert.equal(measurementSource(catalog,'page-retest',{...row,binaryHash:'unknown'},db),null);
  assert.equal(measurementSource(catalog,'page-retest',{...row,bindingKey:'missing'},db),null);
  const missing=structuredClone(db);delete missing.evidence.sourceBindings[row.bindingKey];
  assert.equal(measurementSource(catalog,'page-retest',row,missing),null);
  const wrong=structuredClone(db);const files=wrong.evidence.sourceBindings[row.bindingKey].sources;
  files[Object.keys(files)[0]]='wrong';
  assert.equal(measurementSource(catalog,'page-retest',row,wrong),null);
  const wrongBinary=structuredClone(db);wrongBinary.evidence.sourceBindings[row.bindingKey].binaryHash='wrong';
  assert.equal(measurementSource(catalog,'page-retest',row,wrongBinary),null);
}
console.log(`${points} measurement rows bound; hashes, exact excerpts, two historical A3 kernels, SDK/CQ variants and stale/missing receipts checked.`);
