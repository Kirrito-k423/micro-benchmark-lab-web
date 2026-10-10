"""Receive paired A5 store results; complete two-round matrix required for publication."""
import argparse,csv,hashlib,importlib.util,json,math,re,statistics,subprocess,tarfile
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def percentile(xs,q):
    xs=sorted(xs);i=(len(xs)-1)*q;a=math.floor(i);b=math.ceil(i)
    return xs[a]*(b-i)+xs[b]*(i-a) if a!=b else xs[a]

def receive(runs,akl,tasks,smoke_only=False):
    spec=importlib.util.spec_from_file_location('plan',akl/'examples/a5_store_tail/run.py');plan=importlib.util.module_from_spec(spec);spec.loader.exec_module(plan)
    state=json.loads(tasks.read_text());rows=[];seen=set();env=None;profile=None;build=None;manifests=[];rejected=[];dates=[]
    source_commit=json.loads((tasks.parent/'source-receipt.json').read_text())['commit']
    for mp in sorted(runs.rglob('manifest.json')):
        m=json.loads(mp.read_text())
        if m.get('schema')!='akl.store-tail.mbench.v1':continue
        if m['status']!='validated':rejected.append(dict(manifestSha256=sha(mp),status=m['status']));continue
        if m['round'] not in [1,2] or m['order_seed']!=202610100+m['round']:raise ValueError('Unexpected round / seed')
        if (m['samples'],m['warmup'])!=((3,1) if m['smoke'] else (12,2)):raise ValueError('Unexpected sampling plan')
        dates.append(m['started_utc'][:10])
        root_id=mp.relative_to(runs).parts[0];job=next(v for v in state.values() if v['id']==root_id)
        terminal=job['status_snapshot']
        if terminal['status']!='succeeded' or terminal['exitCode']!=0 or not terminal['archiveReady']:raise ValueError('SSH exit / archive not accepted')
        archive=tasks.parent/'archives'/(root_id+'.tar.gz')
        if sha(archive)!=job['archive_sha256']:raise ValueError('Transport archive hash mismatch')
        # Acceptance inputs must remain identical to the received archive, including
        # Host snapshots that are outside the kernel runner's manifest.
        with tarfile.open(archive) as tar:
            files=[mp,mp.parent/'samples.jsonl',mp.parent/'plan.csv']
            files += [mp.parent/f'occupancy-{x}.txt' for x in ['before','after']]
            files += [runs/root_id/'results'/f'host-{x}.txt' for x in ['before','after']]
            for path in files:
                member=str(path.relative_to(runs/root_id))
                stored=tar.extractfile(member)
                if stored is None or stored.read()!=path.read_bytes():raise ValueError('Extracted evidence differs from received archive')
        if sha(mp.parent/'samples.jsonl')!=m['samples_sha256'] or sha(mp.parent/'plan.csv')!=m['plan_sha256']:raise ValueError('Samples / plan hash mismatch')
        for label in ['before','after']:
            p=mp.parent/f'occupancy-{label}.txt';t=p.read_text();e=m['occupancy_'+label]
            if e['observed_idle'] is not True or sha(p)!=e['sha256'] or 'No running processes found' not in t or re.search(r'^\|\s*\d+\s*\|\s*\d+\s*\|',t,re.M):raise ValueError('Occupancy gate failed')
            host=runs/root_id/'results'/f'host-{label}.txt';ht=host.read_text()
            if 'No running processes found' not in ht or re.search(r'^\|\s*\d+\s*\|\s*\d+\s*\|',ht,re.M):raise ValueError('Host occupancy gate failed')
        b=m['build']
        if set(b['source_sha256'])!={f'examples/a5_store_tail/{x}' for x in ['CMakeLists.txt','kernel.cpp','main.cpp','prepare.py','run.py','receipt.py']}:raise ValueError('Incomplete build source receipt')
        for name,h in b['source_sha256'].items():
            if sha(akl/name)!=h:raise ValueError('Current source differs from compiled receipt')
            content=subprocess.check_output(['git','show',f'{source_commit}:{name}'],cwd=akl)
            if hashlib.sha256(content).hexdigest()!=h:raise ValueError('Recorded source commit differs from compiled receipt')
        if env is not None and (env!=m['environment'] or profile!=m['clock_profile'] or build!=b):raise ValueError('Mixed environment / build cohort')
        env=m['environment'];profile=m['clock_profile'];build=b
        if profile['soc']!=env['soc'] or profile['npu_arch']!='dav-3510' or profile['memory_scope']!='local_GM' or profile['clock_hz']<=0:raise ValueError('Clock or device profile mismatch')
        expected={r[0]:r for r in plan.cases(env['aiv_count'],m['smoke'])}
        planned=[tuple(map(int,r)) for r in csv.reader((mp.parent/'plan.csv').open())]
        if len(set(r[0] for r in planned))!=len(planned) or any(expected.get(r[0])!=r for r in planned):raise ValueError('Unexpected plan')
        raw=[json.loads(l) for l in (mp.parent/'samples.jsonl').read_text().splitlines()]
        if len(raw)!=len(planned)*2:raise ValueError('Missing paired mode')
        if {(r['id'],r['mode']) for r in raw}!={(r[0],mode) for r in planned for mode in ['windowed','tail']}:raise ValueError('Executed case set differs from submitted plan')
        for r in raw:
            key=(m['smoke'],m['round'],r['id'],r['mode'])
            if key in seen or r['mode'] not in ['windowed','tail']:raise ValueError('Duplicate or unknown mode')
            seen.add(key);case=expected[r['id']]
            _,direction,shared,n,tile,batch,ring,target,control=case
            if tuple(r[k] for k in ['direction','shared_read','cores','tile_bytes','batch','requested_ring_bytes','target_bytes','control'])!=case[1:]:raise ValueError('Executed parameters differ from plan')
            if r['soc']!=env['soc'] or r['available_aiv']!=env['aiv_count'] or r['ub_bytes']!=env['ub_bytes']:raise ValueError('Executed environment differs')
            bank=tile*batch;per=((ring+n-1)//n+2*bank-1)//(2*bank)*(2*bank)
            groups=max(2,((target+n*bank-1)//(n*bank)+1)//2*2)
            if (r['per_core_ring_bytes'],r['actual_ring_bytes'],r['groups'],r['moved_bytes'])!=(per,per*n,groups,groups*n*bank):raise ValueError('Byte denominator mismatch')
            if not r['correctness'] or not r['validated_every_launch']:raise ValueError('Oracle failure')
            count=m['samples'];warm=m['warmup'];values=r['event_ms'];orders=r['pair_first_modes']
            if len(values)!=count or len(r['warmup_event_ms'])!=warm or len(r['host_launch_sync_us'])!=count or any(not math.isfinite(v) or v<=0 for v in values+r['warmup_event_ms']):raise ValueError('Missing / invalid samples')
            if r['order_seed']!=m['order_seed'] or len(orders)!=count+warm or any(o not in [0,1] for o in orders):raise ValueError('Pair order evidence missing')
            oracle=r['launch_oracle']
            if len(oracle)!=count+warm or any(o!={'index':i,'warmup':i<warm,'checked_bytes':per*n+128,'mismatches':0} for i,o in enumerate(oracle)):raise ValueError('Full per-launch oracle missing')
            ticks=r['core_raw_ticks'];deltas=[]
            if len(ticks)!=count:raise ValueError('Core tick samples missing')
            for sample in ticks:
                if len(sample)!=n*4:raise ValueError('Core records missing')
                a=list(map(int,sample));ds=[]
                for i in range(n):
                    start,end,core,magic=a[i*4:i*4+4]
                    if not 0<=start<end<2**64 or core!=i or magic!=0x414b4c42414e4431:raise ValueError('Invalid core record')
                    ds.append(str(end-start))
                if max(map(int,ds))*1e6/profile['clock_hz']>sample_time_limit(values[len(deltas)]):raise ValueError('Core duration exceeds ACL interval')
                deltas.append(ds)
            other=next(x for x in raw if x['id']==r['id'] and x['mode']!=r['mode'])
            if other['pair_first_modes']!=orders:raise ValueError('Unpaired mode samples')
            rows.append(dict(id=f"st-{'smoke' if m['smoke'] else 'r'+str(m['round'])}-c{r['id']}-{r['mode']}",caseId=r['id'],round=m['round'],phase='smoke' if m['smoke'] else 'formal',mode=r['mode'],direction='UB_GM',sharedRead=False,
                cores=n,tileBytes=tile,batch=batch,requestedRing=ring,actualRing=per*n,perCoreRing=per,groups=groups,movedBytes=groups*n*bank,control=False,
                p50Us=statistics.median(values)*1000,p95Us=percentile(values,.95)*1000,eventMs=values,warmupEventMs=r['warmup_event_ms'],hostLaunchSyncUs=r['host_launch_sync_us'],coreDurationTicks=deltas,
                pairFirstModes=orders,launchOracle=oracle,correctness=True,manifestHash=sha(mp),binaryHash=b['executable_sha256']))
        manifests.append(sha(mp))
    if env is None:raise ValueError('No device results')
    formal=[r for r in rows if r['phase']=='formal'];smoke=[r for r in rows if r['phase']=='smoke']
    if not smoke_only:
        wanted={(False,rd,r[0],mode) for rd in [1,2] for r in plan.cases(env['aiv_count']) for mode in ['windowed','tail']}
        if {x for x in seen if x[0] is False}!=wanted:raise ValueError(f'Incomplete formal matrix: {len(formal)} / {len(wanted)}')
    version=next(l.split('=',1)[1] for l in build['cann_install'].splitlines() if l.startswith('version='))
    return dict(schema='akl.web.store-tail.v1',measuredDate=' / '.join(sorted(set(dates))),environment=dict(soc=env['soc'],cann='CANN '+version,aiv_count=env['aiv_count'],ub_bytes=env['ub_bytes'],l2_bytes=env['l2_bytes'],clockHz=profile['clock_hz']),rows=rows,
        evidence=dict(receiverValidation='smoke-only' if smoke_only else 'passed',configsPerRound=len(plan.cases(env['aiv_count']))*2,rounds=2,timedSamples=sum(len(r['eventMs']) for r in formal),warmupSamples=sum(len(r['warmupEventMs']) for r in formal),
            smokeConfigs=len(smoke),smokeTimedSamples=sum(len(r['eventMs']) for r in smoke),manifestHashes=manifests,rejectedRuns=rejected,sourceHashes=build['source_sha256'],binaryHash=build['executable_sha256'],
            sourceCommit=source_commit,timing='same-stream ACL Event around full kernel; paired modes share GM allocation, parameters and source pattern',isolation='Host and container snapshots checked; fabric / instantaneous interference not proven',clockSource=profile['clock_source']))

def sample_time_limit(event_ms):return event_ms*1000+1

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--runs',type=Path,required=True);p.add_argument('--akl-root',type=Path,required=True);p.add_argument('--tasks-state',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--smoke-only',action='store_true')
    a=p.parse_args();d=receive(a.runs,a.akl_root,a.tasks_state,a.smoke_only);a.output.write_text(json.dumps(d,ensure_ascii=False,separators=(',',':'))+'\n');print(len(d['rows']),'accepted configuration rounds')
