"""Receive page-policy retests: original archive bytes, full oracles and exact coverage."""
import argparse,hashlib,json,tarfile,re,statistics,math,sys,copy
from pathlib import Path
import numpy as np
WEB=Path(__file__).resolve().parents[1];FIXTURE=WEB/'experiments/a5_page_retest';sys.path.insert(0,str(FIXTURE/'python'))
from akl.datacopy import CopyCase
from akl.trace import decode,duration_ticks
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def quantile(xs,q):
 a=sorted(xs);i=(len(a)-1)*q;lo=int(i);hi=min(lo+1,len(a)-1);return a[lo]+(a[hi]-a[lo])*(i-lo)

def receive(base,partial=False):
 q=json.loads((base/'queue.json').read_text());plan_file=q.get('planFile','execution-plan.json');plan=json.loads((base/plan_file).read_text());jobs=json.loads((base/'tasks-state.json').read_text());stages={s['key']:s for s in plan['stages']};assert sha(base/plan_file)==q['planSha256'];rows=[];receipts=[];build=q['build'];env=build['environment'];hz=plan['clockHz'];assert hz>0 and plan['clockSource'] and env['soc']==plan['expectedSoc'] and env['aiv_count']==plan['availableAiv'] and env['ub_bytes']==plan['ubBytes']
 revisions=q.get('planRevisions',{plan_file:q['planSha256']});known_plans={}
 for name,h in revisions.items():
  assert sha(base/name)==h,'Frozen plan changed';p=json.loads((base/name).read_text());known_plans[h]={s['key']:s for s in p['stages']}
 if q.get('planRevisions'):
  original=json.loads((base/'execution-plan.json').read_text());assert {k:v for k,v in original.items() if k!='stages'}=={k:v for k,v in plan.items() if k!='stages'},'Plan environment/coverage changed'
  old_stages={s['key']:s for s in original['stages']};assert len(plan['stages'])==len(old_stages)
  legacy_file=WEB/'public/data/a5-bandwidth.json';assert sha(legacy_file)==q['controlBaselineSha256'],'Control baseline changed'
  legacy={r['caseId']:r for r in json.loads(legacy_file.read_text())['rows'] if r['round']==1};changed=0
  for s in plan['stages']:
   old_key=s['key'].removesuffix('-control');expected=copy.deepcopy(old_stages[old_key])
   controls=[r for r in expected.get('plan',[]) if r[8]]
   if controls:
    assert expected['kind']=='bandwidth' and len(controls)==len(expected['plan']);expected['key']+='-control'
    for row in controls:
     assert row[7]==0;r=legacy[row[0]];row[7]=r['groups']*r['cores']*r['tileBytes']*r['batch'];changed+=1
   assert s==expected,'A payload stage or loop workload changed'
  assert changed==56
 assert sha(base/'source.tar.gz')==q['sourceArchiveSha256'],'Original source archive digest differs'
 with tarfile.open(base/'source.tar.gz') as source_tar:
  for name,h in build['sources'].items():
   member=source_tar.extractfile(name);assert member and hashlib.sha256(member.read()).hexdigest()==h,'Built source differs from original source archive: '+name
   if name!='plan.py':assert sha(FIXTURE/name)==h,'Published fixture differs: '+name
 def archive(key):
  j=jobs[key];t=j['status_snapshot'];assert t['status']=='succeeded' and t['exitCode']==0 and t['finishedAt'] and t['archiveReady'] and t['selectedMachineId']==q['machine'],'Task receipt invalid'
  f=base/'archives'/(j['id']+'.tar.gz');assert sha(f)==j['archive_sha256'],'Archive digest mismatch';return f
 def bind(key,files):
  j=jobs[key];root=Path(j['raw'])
  with tarfile.open(archive(key)) as t:
   for p in files:
    member=t.extractfile(str(p.relative_to(root)));assert member and member.read()==p.read_bytes(),'Archive bytes differ'
 # Bind the environment and every binary/source hash to the original build receipt.
 br=Path(jobs['build']['raw'])/'results';bind('build',list((br/'setup').iterdir())+[br/'copy-build.json']);assert json.loads((br/'setup/build.json').read_text())==build
 cann=re.search(r'^version=(.+)$',build['cann'],re.M).group(1);environment=env|dict(cann='CANN '+cann,clockHz=hz,clockSource=plan['clockSource'],topology='single_device_local_GM')
 smoke={};smoke_plan=json.loads((base/'smoke-plan.json').read_text())
 for stage in smoke_plan['stages']:
  key=stage['key'];policy=stage['policy'];assert key in q['accepted'] and policy in ['normal','huge-first','huge-only']
  root=Path(jobs[key]['raw'])/'results';folder=root/'stage';bind(key,[p for p in root.rglob('*') if p.is_file()]);meta=json.loads((folder/'receipt.json').read_text())
  assert meta['status']=='validated' and meta['stage']==stage and meta['build']==build and meta['planSha256']==sha(base/'smoke-plan.json')
  for name,h in meta['outputFiles'].items():assert sha(folder/name)==h,'Smoke output digest differs'
  for name in ['host-before.txt','host-after.txt','stage/container-before.txt','stage/container-after.txt']:
   s=(root/name).read_text();assert 'No running processes found' in s and not re.search(r'^\|\s*\d+\s*\|\s*\d+\s*\|',s,re.M),'Smoke NPU contention'
  manifest=json.loads((folder/'run/manifest.json').read_text());assert manifest['status']=='validated' and manifest['hardware']==env and manifest['build']['library_sha256']==build['binaries']['build-a5/libakl_datacopy.so'] and manifest['arguments']['data_allocation']==policy
  assert len(manifest['cases'])==len(stage['cases'])==6 and {r['case']['name'] for r in manifest['cases']}=={c['name'] for c in stage['cases']}
  for r in manifest['cases']:
   assert r['status']=='validated' and r['memory_policy']['input']==r['memory_policy']['output']==policy
   samples=json.loads((folder/'run'/r['case']['name']/'samples.json').read_text());assert len(samples)==5 and all(s['correctness'] for s in samples) and sum(s['warmup'] for s in samples)==1 and sum(not s['trace'] for s in samples)==2
  smoke[policy]=dict(cases=6,correctness=True,taskArchiveSha256=jobs[key]['archive_sha256'],manifestSha256=sha(folder/'run/manifest.json'))
 assert set(smoke)=={'normal','huge-first','huge-only'}
 for key in q['accepted']:
  if key not in stages:continue
  j=jobs[key];root=Path(j['raw'])/'results';folder=root/'stage';files=[p for p in root.rglob('*') if p.is_file()];bind(key,files)
  for name in ['host-before.txt','host-after.txt','stage/container-before.txt','stage/container-after.txt']:
   text=(root/name).read_text();assert 'No running processes found' in text and not re.search(r'^\|\s*\d+\s*\|\s*\d+\s*\|',text,re.M),'NPU contention'
  meta=json.loads((folder/'receipt.json').read_text());stage=stages[key];assert meta['status']=='validated' and meta['stage']==stage and meta['build']==build and known_plans.get(meta['planSha256'],{}).get(key)==stage,'Stage manifest differs'
  for name,h in meta['outputFiles'].items():assert sha(folder/name)==h,'Raw file digest differs'
  receipt=dict(taskArchiveSha256=j['archive_sha256'],stageManifestSha256=sha(folder/'receipt.json'),occupancySha256=[sha(root/n) for n in ['host-before.txt','host-after.txt','stage/container-before.txt','stage/container-after.txt']]);receipts.append(receipt)
  if 'cases' in stage:
   m=json.loads((folder/'run/manifest.json').read_text());assert m['status']=='validated' and m['hardware']==env and m['profile']['clock_hz']==hz and m['profile']['soc']==env['soc'];assert m['build']['library_sha256']==build['binaries']['build-a5/libakl_datacopy.so']
   assert m['arguments']['data_allocation']==stage['policy'] and m['arguments']['min_data_allocation']==stage['minDataAllocation'] and m['arguments']['reuse_buffers']==stage['reuse']
   expected={c['name']:c for c in stage['cases']};got={c['case']['name']:c for c in m['cases']};assert got.keys()==expected.keys(),'Case coverage differs'
   for name,c in expected.items():
    r=got[name];case=CopyCase(**c);assert r['case']==c and r['params']==case.params() and r['layout']==case.layout() and r['status']=='validated','Case fields differ'
    samples=json.loads((folder/'run'/name/'samples.json').read_text());assert len(samples)==stage['warmup']+2*stage['samples'] and all(s['correctness'] for s in samples),'Native oracle/launch coverage failed'
    assert sum(s['warmup'] for s in samples)==stage['warmup'];timed=[s for s in samples if s['trace'] and not s['warmup']];assert len(timed)==stage['samples'] and sum(not s['trace'] for s in samples)==stage['samples'];ticks=[]
    for sample in samples:
     if not sample['trace']:continue
     raw=np.load(folder/'run'/name/f"trace-{sample['launch']}.npy",allow_pickle=False);events=decode(raw,m['run_id'],sample['launch'],m['device'],[r['expected_retained']]);value=int(duration_ticks(events,0));assert str(value)==sample['ticks'] and 0<value<2**64 and value*1e6/hz<=sample['host_launch_sync_us']+.5,'Native clock inconsistency'
     if not sample['warmup']:ticks.append(str(value))
    durations=[int(t)*1e6/hz/(c['loops']*c['batch']) for t in ticks];policy=r['memory_policy'];assert policy['input']==policy['output']==stage['policy'] and policy['other']=='normal' and all(policy['capacities_bytes'][i]>=stage['minDataAllocation'] for i in [0,2])
    p50=statistics.median(durations);layout=case.layout();payload=layout['payload_bytes_per_call'];binding='copy'
    row=dict(id=key+'/'+name,caseId=name,stageKey=key,kind=stage['kind'],round=stage['round'],allocation=stage['policy'],direction=c['direction'],api=c['api'],dtype=c['dtype'],payload=payload,bytes=payload,elements=payload/(case.params()['element_bytes']),windows=c['windows'],batch=c['batch'],loops=c['loops'],slots=c['slots'],cores=1,gmOffset=c['gm_offset_bytes'],blocks=c['blocks'],gmGap=c['gm_gap_bytes'],workingSet=layout['gm_working_set_bytes'],ubWorkingSet=layout['ub_working_set_bytes'],p50=p50,p50Us=p50,p95=quantile(durations,.95),gbps=(payload/p50/1000 if c['control']=='payload' else 0),control=c['control']!='payload',rawTicks=ticks,sampleUs=durations,clockHz=hz,case=c,mode='ring' if c['name'].endswith('_ring') or layout['gm_working_set_bytes']>layout['ub_working_set_bytes'] else 'small',fixedBuffers=stage['reuse'],memoryPolicy=policy,correctness=True,validatedEveryLaunch=True,manifestHash=sha(folder/'receipt.json'),binaryHash=build['binaries']['build-a5/libakl_datacopy.so'],bindingKey=binding)
    rows.append(row)
  else:
   raw=[json.loads(x) for x in (folder/'samples.jsonl').read_text().splitlines()];assert len(raw)==len(stage['plan'])*(2 if stage['kind']=='tail' else 1),'C++ coverage differs';wanted={r[0]:r for r in stage['plan']};seen=set()
   allocation=dict(input=max(r['actual_ring_bytes'] for r in raw),output=max(r['actual_ring_bytes'] if r['direction'] else 2*r['tile_bytes']*r['batch']*r['cores'] for r in raw)+128,records=env['aiv_count']*32,evidence='requested capacities derived from stage plan and receipt-matched Host allocation code')
   for r in raw:
    case=wanted[r['id']];assert [r[k] for k in ['id','direction','shared_read','cores','tile_bytes','batch','requested_ring_bytes','target_bytes','control']]==case and r['correctness'] is True
    ns=stage['samples'];times=r['event_ms'];assert len(times)==len(r['core_raw_ticks'])==ns and len(r['warmup_event_ms'])==stage['warmup'];assert all(math.isfinite(t) and t>0 for t in times);durations=[]
    for ms,s in zip(times,r['core_raw_ticks']):
     assert len(s)==r['cores']*4;ds=[]
     for i in range(r['cores']):
      start,end,core,magic=map(int,s[i*4:i*4+4]);assert 0<=start<end<2**64 and core==i and magic==0x414b4c42414e4431;ds.append(end-start)
     assert max(ds)*1e6/hz<=ms*1000+.5,'Clock exceeds complete duration';durations.append([str(x) for x in ds])
    per=r['per_core_ring_bytes'];bank=r['tile_bytes']*r['batch'];assert r['actual_ring_bytes']==per*(1 if r['shared_read'] else r['cores']) and per%(2*bank)==0 and r['groups']%2==0 and r['moved_bytes']==(0 if r['control'] else r['groups']*bank*r['cores'])
    assert r['shared_read'] or r['groups']*bank>=per,'GM ring incomplete';mode=r.get('mode','windowed');seen.add((r['id'],mode));p50=statistics.median(times)*1000;binding='tail' if stage['kind']=='tail' else 'bandwidth'
    row=dict(id=key+f"/c{r['id']}-"+mode,caseId=r['id'],stageKey=key,kind=stage['kind'],round=stage['round'],allocation=stage['policy'],direction='UB_GM' if r['direction'] else 'GM_UB',api='DataCopy_count',dtype='uint32',cores=r['cores'],tileBytes=r['tile_bytes'],batch=r['batch'],windows=2,requestedRing=r['requested_ring_bytes'],actualRing=r['actual_ring_bytes'],perCoreRing=per,groups=r['groups'],control=bool(r['control']),sharedRead=bool(r['shared_read']),mode=mode,movedBytes=r['moved_bytes'],workingSet=r['actual_ring_bytes'],p50=p50,p50Us=p50,p95=quantile(times,.95)*1000,gbps=r['moved_bytes']/p50/1000,eventMs=times,sampleUs=[t*1000 for t in times],warmupEventMs=r['warmup_event_ms'],coreDurationTicks=durations,correctness=True,validatedEveryLaunch=True,memoryPolicy=dict(input='huge-first',output='huge-first',other='normal'),manifestHash=sha(folder/'receipt.json'),binaryHash=build['binaries']['build-'+binding+'/measure'],bindingKey=binding)
    row['allocationBytes']=allocation
    if 'pair_first_modes' in r:row['pairFirstModes']=r['pair_first_modes'];assert len(r['pair_first_modes'])==ns+stage['warmup']
    if stage['kind']=='workset':row['scope']='shared_read' if r['shared_read'] else 'partition_write' if r['direction'] else 'partition_read';assert row['movedBytes']/(r['cores']*per)>=2
    rows.append(row)
   expected={(i,mode) for i in wanted for mode in (['windowed','tail'] if stage['kind']=='tail' else ['windowed'])};assert seen==expected,'C++ duplicate/missing modes'
 counts={k:sum(r['kind']==k for r in rows) for k in plan['counts']};assert partial or counts==plan['counts'],f'Incomplete matrix: {counts}'
 sourceBindings={}
 for key,folder,binary in [('copy','',build['binaries']['build-a5/libakl_datacopy.so']),('bandwidth','bandwidth/',build['binaries']['build-bandwidth/measure']),('tail','tail/',build['binaries']['build-tail/measure'])]:
  paths=['kernels/datacopy.cpp','python/akl/native.py','scripts/run_datacopy.py'] if key=='copy' else [folder+'kernel.cpp',folder+'main.cpp']
  sourceBindings[key]=dict(binaryHash=binary,sources={p:build['sources'][p] for p in paths})
 return dict(schema='akl.web.page-retest.v1',measuredDate='2026-10-10',environment=environment,rows=rows,evidence=dict(receiverValidation='partial' if partial else 'passed',expectedCounts=plan['counts'],actualCounts=counts,timedSamples=sum(len(r['sampleUs']) for r in rows),sourceBindings=sourceBindings,sourceArchiveSha256=q['sourceArchiveSha256'],planSha256=q['planSha256'],planRevisions=revisions,controlBaselineSha256=q.get('controlBaselineSha256'),planRepair='Control target bytes restored from original groups; all payload stage parameters and binaries unchanged' if q.get('planRevisions') else None,receipts=receipts,smoke=smoke,clockSource=plan['clockSource'],allocation='input and output data allocations use recorded policy; other buffers ordinary; minimum native data allocation 2 MiB; HUGE_FIRST can fall back; HUGE_ONLY smoke passed',cache='API default normal; no cache counters or HBM physical transactions measured',isolation='whole Host and container idle snapshots before/after each short task; transient interference unknown'),skipped=plan['skipped'])
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--runs',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--partial',action='store_true');a=p.parse_args();d=receive(a.runs,a.partial);a.output.write_text(json.dumps(d,ensure_ascii=False,separators=(',',':'))+'\n');print(d['evidence']['actualCounts'],d['evidence']['timedSamples'],'accepted timed samples')
