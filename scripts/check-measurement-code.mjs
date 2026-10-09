import {readFileSync} from 'node:fs';
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
console.log(`${points} measurement rows bound; hashes, exact excerpts, two historical A3 kernels, SDK/CQ variants and stale/missing receipts checked.`);
