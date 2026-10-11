import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { measurementGroups, plotValue } from '../src/latency-duplex-data.js';
const db=JSON.parse(readFileSync(process.argv[2] || new URL('../public/data/a5-latency-duplex.json',import.meta.url)));
assert.equal(db.evidence.receiverValidation,'passed');
assert.equal(db.rows.length,1232);assert.equal(db.evidence.timedSamples,14784);assert.equal(db.evidence.traceOffSamples,14784);
assert.equal(new Set(db.rows.map(r=>r.id)).size,1232);
for(const r of db.rows) {
  assert.equal(r.sampleUs.length,12);assert.ok(r.sampleUs.every(n=>Number.isFinite(n)&&n>0));
  assert.ok(r.p95>=r.p50);assert.equal(r.control,r.movedBytes===0);
  if(r.kind==='latency')assert.equal(r.loops,1);
  else {
    assert.equal(r.movedBytes,r.readBytes+r.writeBytes);
    assert.equal(r.gbps,r.movedBytes/r.p50/1000);
    assert.equal(r.readGbps,r.readBytes/r.p50/1000);assert.equal(r.writeGbps,r.writeBytes/r.p50/1000);
  }
}
let views=0;
for(const api of ['DataCopy_count','DataCopy_params','DataCopyPad_params'])
for(const direction of ['GM_UB','UB_GM']) for(const windows of ['1','2'])
for(const round of ['all','1','2']) for(const policy of ['all','normal','huge-first']) {
  const rows=measurementGroups(db,{kind:'latency',api,direction,windows,round,policy});
  assert.equal(rows.length,policy==='all'?36:18);assert.equal(new Set(rows.map(r=>r.bytes)).size,18);
  assert.equal(Math.min(...rows.map(r=>r.bytes)),32);assert.equal(Math.max(...rows.map(r=>r.bytes)),4*2**20);
  for(const r of rows)assert.equal(r.members.length,round==='all'?2:1);
  views++;
}
for(const ring of ['small',String(128*2**20),String(2**31)]) for(const tile of ['4096','32768'])
for(const mode of ['all','read','write','duplex']) for(const policy of ['all','normal','huge-first'])
for(const round of ['all','1','2']) {
  const state={kind:'duplex',ring,tile,mode,policy,round};const rows=measurementGroups(db,state);
  assert.equal(rows.length,(mode==='all'?9:3)*(policy==='all'?2:1));
  assert.deepEqual([...new Set(rows.map(r=>r.cores))].sort((a,b)=>a-b),[1,16,64]);
  for(const r of rows){
    assert.equal(r.members.length,round==='all'?2:1);
    assert.equal(plotValue(r,{...state,metric:'read'})+plotValue(r,{...state,metric:'write'}),plotValue(r,{...state,metric:'total'}));
    assert.ok(Math.abs(plotValue(r,{...state,metric:'total'})-r.movedBytes/r.p50/1e6)<1e-12*Math.max(1,r.movedBytes/r.p50/1e6));
  }
  views++;
}
console.log(`${views} complete filter combinations checked; single-request coverage and common-time duplex arithmetic passed.`);
