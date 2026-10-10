"""Accept complete, fixed-buffer workset sweeps with full shared-ring traversal."""
import argparse,csv,hashlib,importlib.util,json,math,random,re,statistics,tarfile
from pathlib import Path
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ceil(n,u):return (n+u-1)//u*u
def quantile(xs,p):
    xs=sorted(xs);v=(len(xs)-1)*p;i=int(v);j=min(i+1,len(xs)-1);return xs[i]+(xs[j]-xs[i])*(v-i)
def receive(runs,akl,tasks,partial=False):
    web=Path(__file__).resolve().parent;spec=importlib.util.spec_from_file_location('plan',web/'workset-plan.py');plan=importlib.util.module_from_spec(spec);spec.loader.exec_module(plan)
    jobs=json.loads(tasks.read_text());rows=[];seen=set();env=profile=build=None;dates=set();hashes=[];failed=[];receipts=[]
    for mp in sorted(runs.rglob('manifest.json')):
        m=json.loads(mp.read_text())
        if m.get('schema')!='akl.workset.mbench.v1':continue
        if m['status']!='validated':failed.append(dict(manifestSha256=sha(mp),status=m['status']));continue
        root_id=mp.relative_to(runs).parts[0];job=next(v for v in jobs.values() if v['id']==root_id);t=job['status_snapshot']
        if t['status']!='succeeded' or t['exitCode']!=0 or not t['archiveReady']:raise ValueError('Remote task not accepted')
        ar=tasks.parent/'archives'/(root_id+'.tar.gz')
        if sha(ar)!=job['archive_sha256']:raise ValueError('Archive hash mismatch')
        files=[mp,mp.parent/'plan.csv',mp.parent/'samples.jsonl']+[mp.parent/f'occupancy-{x}.txt' for x in ['before','after']]+[runs/root_id/'results'/f'host-{x}.txt' for x in ['before','after']]
        with tarfile.open(ar) as tar:
            for p in files:
                stored=tar.extractfile(str(p.relative_to(runs/root_id)))
                if stored is None or stored.read()!=p.read_bytes():raise ValueError('Extracted data differs from archive')
        if sha(mp.parent/'plan.csv')!=m['plan_sha256'] or sha(mp.parent/'samples.jsonl')!=m['samples_sha256']:raise ValueError('Plan / samples changed')
        for label in ['before','after']:
            p=mp.parent/f'occupancy-{label}.txt';e=m['occupancy_'+label]
            if e['observed_idle'] is not True or sha(p)!=e['sha256']:raise ValueError('Occupancy receipt mismatch')
            for p in [p,runs/root_id/'results'/f'host-{label}.txt']:
                s=p.read_text()
                if 'No running processes found' not in s or re.search(r'^\|\s*\d+\s*\|\s*\d+\s*\|',s,re.M):raise ValueError('Busy Host / container')
        b=m['build']
        if set(b['source_sha256'])!={f'examples/a5_bandwidth/{x}' for x in ['kernel.cpp','main.cpp','CMakeLists.txt']}:raise ValueError('Incomplete core receipt')
        for p,h in b['source_sha256'].items():
            if sha(akl/p)!=h:raise ValueError('Core source changed')
        if m['runner_sha256']!=sha(web/'workset-runner.py') or m['planner_sha256']!=sha(web/'workset-plan.py'):raise ValueError('Runner / planner changed')
        if env is not None and (env!=m['environment'] or profile!=m['clock_profile'] or build!=b):raise ValueError('Mixed build / environment')
        env=m['environment'];profile=m['clock_profile'];build=b
        if profile['soc']!=env['soc'] or profile['clock_hz']<=0 or not profile['clock_source'].strip():raise ValueError('Clock profile invalid')
        if not m['fixed_buffers'] or m['seed']!=2026101000+m['round'] or m['round'] not in [1,2]:raise ValueError('Fixed-buffer order invalid')
        count,warm=(3,1) if m['smoke'] else (12,2)
        if (m['samples'],m['warmup'])!=(count,warm):raise ValueError('Wrong sample counts')
        canonical=plan.cases(env,m['scope'],m['smoke']);expected={r[0]:r for r in canonical}
        submitted=[tuple(map(int,r)) for r in csv.reader((mp.parent/'plan.csv').open())]
        if set(submitted)!=set(canonical) or len(submitted)!=len(canonical):raise ValueError('Incomplete submitted curve')
        ordered=list(canonical);random.Random(m['seed']).shuffle(ordered)
        if submitted!=ordered:raise ValueError('Randomized execution order differs')
        raw=[json.loads(x) for x in (mp.parent/'samples.jsonl').read_text().splitlines()]
        if len(raw)!=len(expected) or {r['id'] for r in raw}!=set(expected):raise ValueError('Incomplete executed curve')
        max_ring=0
        for r in raw:
            key=(m['smoke'],m['round'],r['id'])
            if key in seen:raise ValueError('Duplicate point');
            seen.add(key);case=expected[r['id']]
            if tuple(r[k] for k in ['id','direction','shared_read','cores','tile_bytes','batch','requested_ring_bytes','target_bytes','control'])!=case:raise ValueError('Parameters differ')
            _,direction,shared,n,tile,batch,ring,target,control=case;bank=tile*batch
            per=ceil(ring if shared else (ring+n-1)//n,2*bank);actual=per*(1 if shared else n);groups=max(2,ceil((target+n*bank-1)//(n*bank),2));moved=groups*n*bank;max_ring=max(max_ring,actual)
            if [r[k] for k in ['per_core_ring_bytes','actual_ring_bytes','groups','moved_bytes']]!=[per,actual,groups,moved]:raise ValueError('Byte denominator invalid')
            if groups*bank<2*per:raise ValueError('Allocated ring not fully traversed twice')
            if r['soc']!=env['soc'] or r['available_aiv']!=env['aiv_count'] or r['ub_bytes']!=env['ub_bytes'] or r['correctness'] is not True or r['validated_every_launch'] is not True:raise ValueError('Device / oracle invalid')
            times=r['event_ms'];ticks=r['core_raw_ticks']
            if len(times)!=count or len(ticks)!=count or len(r['warmup_event_ms'])!=warm or len(r['host_launch_sync_us'])!=count or any(not math.isfinite(x) or x<=0 for x in times+r['warmup_event_ms']):raise ValueError('Missing or invalid samples')
            spans=[]
            for ms,sample in zip(times,ticks):
                if len(sample)!=n*4:raise ValueError('Missing core records')
                ds=[]
                for core in range(n):
                    start,end,logical,magic=map(int,sample[4*core:4*core+4])
                    if not 0<=start<end<2**64 or logical!=core or magic!=0x414b4c42414e4431:raise ValueError('Core interval invalid')
                    if (end-start)*1e6/profile['clock_hz']>ms*1000+.5:raise ValueError('Core / ACL clock mismatch')
                    ds.append(str(end-start))
                spans.append(ds)
            rows.append(dict(id=f'ws-{"smoke" if m["smoke"] else "r"+str(m["round"])}-c{r["id"]}',caseId=r['id'],round=m['round'],phase='smoke' if m['smoke'] else 'formal',scope=m['scope'],direction='UB_GM' if direction else 'GM_UB',sharedRead=bool(shared),cores=n,tileBytes=tile,batch=batch,requestedRing=ring,actualRing=actual,coveredGmBytes=actual,perCoreRing=per,groups=groups,control=False,targetBytes=target,movedBytes=moved,repeatsPerCore=groups*bank/per,fixedBuffers=True,p50Us=statistics.median(times)*1000,p95Us=quantile(times,.95)*1000,eventMs=times,warmupEventMs=r['warmup_event_ms'],hostLaunchSyncUs=r['host_launch_sync_us'],coreDurationTicks=spans,coreP50Us=[statistics.median(int(d[i])*1e6/profile['clock_hz'] for d in spans) for i in range(n)],correctness=True,validatedEveryLaunch=True,manifestHash=sha(mp),binaryHash=b['executable_sha256']))
        if m['max_allocated_input_bytes']!=max_ring:raise ValueError('Fixed allocation envelope differs')
        dates.add(m['started_utc'][:10]);hashes.append(sha(mp))
        receipts.append(dict(scope=m['scope'],round=m['round'],phase='smoke' if m['smoke'] else 'formal',manifestSha256=sha(mp),archiveSha256=sha(ar),planSha256=m['plan_sha256'],samplesSha256=m['samples_sha256'],maxAllocatedInputBytes=max_ring))
    if env is None:raise ValueError('No accepted device results')
    wanted={(False,rd,r[0]) for rd in [1,2] for scope in plan.SCOPES for r in plan.cases(env,scope)}
    formal=[r for r in rows if r['phase']=='formal']
    if not partial and {x for x in seen if not x[0]}!=wanted:raise ValueError(f'Incomplete matrix: {len(formal)} / {len(wanted)}')
    version=re.search(r'^version=(.+)$',build['cann_install'],re.M).group(1)
    spec=importlib.util.spec_from_file_location('analysis',web/'workset-analysis.py');analysis=importlib.util.module_from_spec(spec);spec.loader.exec_module(analysis)
    return dict(schema='akl.web.workset.v1',measuredDate=' / '.join(sorted(dates)),environment=env|dict(cann='CANN '+version,clockHz=profile['clock_hz']),rows=rows,analysis=analysis.analyse(rows) if not partial else None,evidence=dict(receiverValidation='partial' if partial else 'passed',configsPerRound=len(wanted)//2,rounds=2,timedSamples=sum(len(r['eventMs']) for r in formal),warmupSamples=sum(len(r['warmupEventMs']) for r in formal),sourceHashes=build['source_sha256'],binaryHash=build['executable_sha256'],runnerSha256=sha(web/'workset-runner.py'),plannerSha256=sha(web/'workset-plan.py'),manifestHashes=hashes,curveReceipts=receipts,rejectedRuns=failed,fixedBuffers='one process / GM allocation per scope curve; sizes randomized per round',timing='full-kernel same-stream ACL Event; no subtraction',isolation='Host and container before/after snapshots; instantaneous interference unknown',sharedReads='entire shared ring traversed at least twice per launch; logical payload includes repeated requests by every AIV'))
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--runs',type=Path,required=True);p.add_argument('--akl-root',type=Path,required=True);p.add_argument('--tasks-state',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--partial',action='store_true')
    a=p.parse_args();d=receive(a.runs,a.akl_root,a.tasks_state,a.partial);a.output.write_text(json.dumps(d,ensure_ascii=False,separators=(',',':'))+'\n');print(len(d['rows']),'accepted rows')
