"""Accept archived peer reproduction and controlled DataCopy contrasts."""
import argparse,csv,hashlib,json,math,re,statistics,tarfile
from pathlib import Path
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def quantile(xs,p):
    xs=sorted(xs);i=(len(xs)-1)*p;a=int(i);b=min(a+1,len(xs)-1);return xs[a]+(xs[b]-xs[a])*(i-a)
def receive(base,web,partial=False):
    q=json.loads((base/'queue.json').read_text());jobs=json.loads((base/'tasks-state.json').read_text());plan={p['key']:p for p in json.loads((base/'execution-plan.json').read_text())}
    builds={};binary_sources={};source_prefix='experiments/a5_peer_copy/'
    def archive(job):
        t=job['status_snapshot'];assert t['status']=='succeeded' and t['exitCode']==0 and t['archiveReady'] and t['finishedAt'],'Remote receipt failed'
        assert t['selectedMachineId']==q['machine'],'Different machine'
        p=base/'archives'/(job['id']+'.tar.gz');assert sha(p)==job['archive_sha256'],'Archive digest mismatch';return p
    def bind(job,files):
        with tarfile.open(archive(job)) as t:
            root=Path(job['raw'])
            for p in files:
                f=t.extractfile(str(p.relative_to(root)));assert f and f.read()==p.read_bytes(),'Archive file bytes differ'
    original=jobs['build'];folder=Path(original['raw'])/'results/build';bind(original,[folder/'hashes.txt',folder/'compiler.txt',folder/'cann.txt'])
    original_hashes={n:h for h,n in (s.split() for s in (folder/'hashes.txt').read_text().splitlines())}
    assert original_hashes['datacopy_3t.asc']==q['peerSourceSha256'],'Original source mismatch'
    control=jobs['control-build'];p=Path(control['raw'])/'results/control-hashes.txt';bind(control,[p]);control_hashes={n:h for h,n in (s.split() for s in p.read_text().splitlines())}
    install=(folder/'cann.txt').read_text();cann=re.search(r'^version=(.+)$',install,re.M).group(1)
    compiler=(folder/'compiler.txt').read_text().splitlines()[0]
    for engine in ['peer-original','peer-control','peer-32k4','akl-normal-normal','akl-normal-bypass','akl-huge-first-normal','akl-huge-first-bypass']:
        hs=original_hashes if engine=='peer-original' else control_hashes;binary=hs['build/'+engine]
        names=['datacopy_3t.asc'] if engine=='peer-original' else ['peer_control.asc'] if engine.startswith('peer') else ['akl-control-kernel.cpp','akl-control-main.cpp']
        sources={source_prefix+n:hs[n] for n in names}
        for path,h in sources.items():assert sha(web/path)==h,'Published source differs from measured build'
        flags=['-O2','-g','--npu-arch=dav-3510']
        if engine=='peer-32k4':flags+=['-DTILE_BYTES=32768','-DBUFFER_COUNT=4']
        if engine.startswith('akl-'):flags+=['-DMAX_RING_GIB=4','-DINPUT_POLICY='+('ACL_MEM_MALLOC_NORMAL_ONLY' if engine.startswith('akl-normal') else 'ACL_MEM_MALLOC_HUGE_FIRST'),'-DINPUT_BYPASS='+('1' if engine.endswith('bypass') else '0')]
        builds[engine]=dict(binaryHash=binary,sources=sources,compileOptions=flags);binary_sources[binary]=sources
    rows=[];receipts=[];env=None;hz=q['clockHz'];assert hz>0,'Clock frequency missing'
    for key,job in sorted(jobs.items(),key=lambda kv:(not kv[0].startswith('original-'),kv[0])):
        if not (key.startswith('original-') or key in plan):continue
        if key not in q['accepted']:continue
        root=Path(job['raw'])/'results';run=root/'run';files=[root/f'{side}-{stage}.txt' for side in ['host','container'] for stage in ['before','after']]+list(run.iterdir())
        bind(job,files)
        for p in files[:4]:
            s=p.read_text();assert 'No running processes found' in s and not re.search(r'^\|\s*\d+\s*\|\s*\d+\s*\|',s,re.M),'NPU interference'
        smoke=key=='original-smoke';n,warm=(3,1) if smoke else (20,5)
        if key.startswith('original-'):
            case=dict(id='peer-original',engine='peer-original',bytes=4<<30,tile=65536,buffers=2,cores=64,allocation='huge-first',cache='bypass',pattern='tile-uniform',completion='pipeline');rd=1 if smoke else int(key[-1]);config=None
        else:config=plan[key];case=config['case'];rd=config['round'];assert sha(base/'tasks'/(key+'.sh'))==config['scriptSha256'],'Saved command changed';assert config['command'] in job['shell'],'Task command differs'
        b=builds[case['engine']];kind='akl' if case['engine'].startswith('akl') else 'peer'
        row=dict(id=key,caseId=case['id'],round=rd,phase='smoke' if smoke else 'formal',engine=case['engine'],implementation=kind,cores=case['cores'],tileBytes=case['tile'],batch=case.get('batch'),buffers=case.get('buffers',2),allocation=case['allocation'],cache=case['cache'],pattern=case['pattern'],completion=case['completion'],actualRing=case['bytes'],movedBytes=case.get('payloadBytes',case['bytes']),direction='GM_UB',dtype='uint32',binaryHash=b['binaryHash'],warmupCount=warm,correctness=True)
        if kind=='peer':
            meta=dict(l.split('=',1) for l in (run/'measurement.meta.txt').read_text().splitlines());sample=list(csv.DictReader((run/'measurement.samples.csv').open()));summary=list(csv.DictReader((run/'measurement.csv').open()))
            actual_env=dict(soc=meta['soc'],aiv_count=int(meta['available_aiv']),ub_bytes=int(meta['ub_bytes']),l2_bytes=int(meta['l2_bytes']))
            assert int(meta['device'])==1 and int(meta['working_set_bytes'])==case['bytes'] and int(meta['tile_bytes'])==case['tile'] and int(meta['buffer_count'])==case['buffers'] and meta['cache']==case['cache'],'Peer dimensions differ'
            assert (int(meta['warmup']),int(meta['repeats']))==(warm,n),'Peer samples differ'
            if case['engine']!='peer-original':assert all(meta[k]==case[k] for k in ['allocation','pattern','completion']),'Peer controls differ'
            assert len(summary)==1 and summary[0]['validation']=='PASS' and len(sample)==n and [int(s['iteration']) for s in sample]==list(range(n)),'Peer coverage / oracle failed'
            times=[float(s['event_ms']) for s in sample];lo=[int(s['min_core_cycles']) for s in sample];hi=[int(s['max_core_cycles']) for s in sample]
            assert all(int(s['aivs'])==64 for s in sample) and int(summary[0]['aivs'])==64,'Peer AIV count differs'
            for ms,l,h,s in zip(times,lo,hi,sample):
                assert 0<l<=h<2**64 and h*1e6/hz<=ms*1000+.5,'Peer clock inconsistency'
                assert abs(float(s['GBps'])-case['bytes']/(ms*1e6))<1e-4,'Peer byte denominator differs'
            assert abs(float(summary[0]['median_ms'])-statistics.median(times))<1e-8,'Peer summary differs'
            row.update(coreMinDurationTicks=[str(x) for x in lo],coreMaxDurationTicks=[str(x) for x in hi],oracle='untimed first 32 B of every tile; first 32 B of final buffers after timed run',validatedEveryLaunch=False,readOutputBytes=64*case['buffers']*32)
        else:
            raw=[json.loads(x) for x in (run/'samples.jsonl').read_text().splitlines()];assert len(raw)==1,'AKL case count differs';r=raw[0]
            submitted=[tuple(map(int,x)) for x in csv.reader((run/'plan.csv').open())];assert submitted==[tuple(config['plan'])],'AKL plan differs'
            assert tuple(r[k] for k in ['id','direction','shared_read','cores','tile_bytes','batch','requested_ring_bytes','target_bytes','control'])==tuple(config['plan']),'AKL parameter mismatch'
            bank=case['tile']*case['batch'];per=case['bytes']//64;groups=case['payloadBytes']//(64*bank)
            assert r['actual_ring_bytes']==case['bytes'] and r['per_core_ring_bytes']==per and r['groups']==groups and r['moved_bytes']==case['payloadBytes'] and groups*bank>=per,'AKL traversal differs'
            assert r['correctness'] is True and r['validated_every_launch'] is True and len(r['warmup_event_ms'])==warm,'AKL oracle failed'
            actual_env=dict(soc=r['soc'],aiv_count=r['available_aiv'],ub_bytes=r['ub_bytes'],l2_bytes=env['l2_bytes'])
            # L2 size is independently queried by peer runs on the same device;
            # it is checked for cohort equality below, not used in the denominator.
            times=r['event_ms'];assert len(times)==n and len(r['core_raw_ticks'])==n,'AKL sample count differs';lo=[];hi=[];duration=[]
            for ms,s in zip(times,r['core_raw_ticks']):
                assert len(s)==64*4,'Missing core records';ds=[]
                for core in range(64):
                    start,end,logical,magic=map(int,s[core*4:core*4+4]);assert 0<=start<end<2**64 and logical==core and magic==0x414b4c42414e4431,'Core record differs';ds.append(end-start)
                assert max(ds)*1e6/hz<=ms*1000+.5,'AKL clock inconsistency';lo.append(min(ds));hi.append(max(ds));duration.append([str(d) for d in ds])
            row.update(coreMinDurationTicks=[str(x) for x in lo],coreMaxDurationTicks=[str(x) for x in hi],coreDurationTicks=duration,warmupEventMs=r['warmup_event_ms'],oracle='full last two UB groups and 128 B guard on every launch',validatedEveryLaunch=True,readOutputBytes=64*2*bank)
        assert actual_env['aiv_count']==64 and actual_env['ub_bytes']>=row['tileBytes']*row['buffers']+32,'Device envelope differs'
        if env is None:env=actual_env
        assert env==actual_env,'Mixed device environments'
        assert all(math.isfinite(t) and t>0 for t in times),'Invalid ACL duration'
        row.update(eventMs=times,p50Us=statistics.median(times)*1000,p95Us=quantile(times,.95)*1000,coreMaxP50Us=statistics.median(hi)*1e6/hz)
        row['gbps']=row['movedBytes']/row['p50Us']/1000
        row['dataUbBytes']=row['tileBytes']*(row['buffers'] if kind=='peer' else 2*row['batch'])
        public_receipt=dict(taskArchiveSha256=job['archive_sha256'],files={str(p.relative_to(root)):sha(p) for p in files if p not in files[:4]},occupancySha256=[sha(p) for p in files[:4]],sourceHashes=b['sources'],binaryHash=b['binaryHash'])
        receipt_digest=hashlib.sha256(json.dumps(public_receipt,sort_keys=True,separators=(',',':')).encode()).hexdigest();row['manifestHash']=receipt_digest;receipts.append(public_receipt|dict(manifestHash=receipt_digest));rows.append(row)
    wanted={'original-r1','original-r2',*plan.keys()};got={r['id'] for r in rows if r['phase']=='formal'}
    assert partial or got==wanted,f'Incomplete matrix {len(got)} / {len(wanted)}'
    assert env is not None,'No accepted NPU measurements'
    return dict(schema='akl.web.peer-copy.v1',measuredDate='2026-10-10',environment=env|dict(cann='CANN '+cann,compiler=compiler,clockHz=hz),rows=rows,evidence=dict(receiverValidation='partial' if partial else 'passed',configsPerRound=len(wanted)//2,rounds=2,timedSamples=sum(len(r['eventMs']) for r in rows if r['phase']=='formal'),sourceHashesByBinary=binary_sources,builds=builds,receipts=receipts,peerCommit=q['peerCommit'],peerSourceSha256=q['peerSourceSha256'],timing='same-stream ACL Event enclosing the full kernel; no empty subtraction; per-core SYS_CNT durations separately retained',clockSource=q['clockSource'],isolation='whole Host and container snapshots before/after; instantaneous interference unknown',allocation='policy requested at input allocation only; HUGE_FIRST can fall back; actual page tables / TLB misses not measured',order='20 contrast configurations shuffled independently per round; each configuration uses fresh allocation; 5 warmups, 20 timed samples'))
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--runs',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--partial',action='store_true');a=p.parse_args();d=receive(a.runs,Path(__file__).resolve().parents[1],a.partial);a.output.write_text(json.dumps(d,ensure_ascii=False,separators=(',',':'))+'\n');print(len(d['rows']),'accepted NPU rows')
