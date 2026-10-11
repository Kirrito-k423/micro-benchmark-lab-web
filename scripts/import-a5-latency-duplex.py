"""Receive single-request and common-time duplex evidence, without inferred samples."""
import argparse,csv,hashlib,json,math,re,statistics,tarfile
from pathlib import Path
WEB=Path(__file__).resolve().parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def quantile(xs,q):
    a=sorted(xs);v=(len(a)-1)*q;i=int(v);j=min(i+1,len(a)-1);return a[i]+(a[j]-a[i])*(v-i)
def ceil(n,u):return (n+u-1)//u*u
def bind(base,q,jobs,key):
    j=jobs[key];s=j['status_snapshot']
    assert s['status']=='succeeded' and s['exitCode']==0 and s['finishedAt'] and s['archiveReady'] and s['selectedMachineId']==q['machine'],'Task not terminal/accepted'
    archive=base/'archives'/(j['id']+'.tar.gz');assert sha(archive)==j['archive_sha256'],'Archive digest mismatch'
    root=Path(j['raw'])
    with tarfile.open(archive) as t:
        for p in root.rglob('*'):
            if p.is_file():assert t.extractfile(str(p.relative_to(root))).read()==p.read_bytes(),'Raw bytes differ'
    return root/'results'
def context(base):
    q=json.loads((base/'queue.json').read_text());plan=json.loads((base/'execution-plan.json').read_text());jobs=json.loads((base/'tasks-state.json').read_text());build=q['build']
    assert sha(base/'execution-plan.json')==q['planSha256'] and sha(base/'source.tar.gz')==q['sourceArchiveSha256']
    with tarfile.open(base/'source.tar.gz') as t:
        assert t.extractfile('execution-plan.json').read()==(base/'execution-plan.json').read_bytes()
        for name,h in build['sources'].items():
            assert hashlib.sha256(t.extractfile(name).read()).hexdigest()==h
            assert sha(WEB/'experiments/a5_latency_duplex'/name)==h,'Published source changed'
    br=bind(base,q,jobs,q['buildKey']);assert json.loads((br/'setup/build.json').read_text())==build
    assert re.search(r'^version=9\.1\.0$',build['cann'],re.M),'CANN mismatch'
    assert plan['expectedSoc']=='Ascend950DT_9582' and plan['clockHz']==10**9 and q['clockDocumentUrl']
    return q,plan,jobs,build
def accept_stage(base,key,logical=None,ctx=None):
    q,plan,jobs,build=ctx or context(base);logical=logical or key
    stage=next(x for x in plan['stages'] if x['key']==logical)
    root=bind(base,q,jobs,key);folder=root/'stage';m=json.loads((folder/'receipt.json').read_text())
    assert m['status']=='validated' and m['stage']==stage and m['build']==build and m['planSha256']==q['planSha256']
    for name,h in m['outputFiles'].items():assert sha(folder/name)==h,'Output digest mismatch'
    for name in ['host-before.txt','host-after.txt','stage/container-before.txt','stage/container-after.txt']:
        s=(root/name).read_text();assert 'No running processes found' in s and not re.search(r'^\|\s*\d+\s*\|\s*\d+\s*\|',s,re.M),'NPU interference'
    with (folder/'plan.csv').open() as f:assert [[int(x) for x in row] for row in csv.reader(f)]==stage['cases']
    raw=[json.loads(s) for s in (folder/'samples.jsonl').read_text().splitlines()]
    expected=len(stage['cases'])*(4 if stage['kind']=='duplex' else 1)
    assert len(raw)==expected and len({r['id'] for r in raw})==expected,'Missing/duplicate configurations'
    byid={r['id']:r for r in raw};n=stage['samples'];warm=stage['warmup'];rows=[]
    def finite(r,names,count):
        for name in names:assert len(r[name])==count and all(math.isfinite(x) and x>0 for x in r[name]),'Invalid times'
    def common(r):
        assert r['policy']==stage['policy'] and r['soc']==plan['expectedSoc'] and r['available_aiv']==plan['availableAiv'] and r['ub_bytes']==plan['ubBytes']
        assert r['correctness'] and r['validated_every_launch'] and r['guard_bytes']==128
        finite(r,['trace_event_ms','plain_event_ms'],n);finite(r,['warmup_trace_event_ms','warmup_plain_event_ms'],warm)
    evidence=dict(manifestHash=sha(folder/'receipt.json'),archiveHash=jobs[key]['archive_sha256'],sourceCommit=q['sourceCommit'])
    for c in stage['cases']:
        if stage['kind']=='latency':
            ident,api,direction,total,tile,windows,repeats=c;r=byid[ident];common(r)
            values=dict(api=api,direction=direction,total_bytes=total,tile_bytes=tile,windows=windows,repeats=1,
                tiles_per_request=total//tile,moved_bytes=0 if api==3 else total,working_set_bytes=0 if api==3 else total,
                input_allocation_bytes=max(2<<20,total),output_allocation_bytes=max(2<<20,max(total,tile*windows)+128))
            assert repeats==1 and all(r[k]==v for k,v in values.items()),'Single-request geometry differs'
            assert r['control']==(api==3) and r['full_read_oracle']==(api!=3)
            assert len(r['raw_ticks'])==n and len(r['trace_order'])==len(r['launch_stamps'])==n+warm
            finite(r,['host_launch_sync_us'],n)
            for i,(order,stamps) in enumerate(zip(r['trace_order'],r['launch_stamps'])):
                assert order in [0,1] and stamps==[0x60000000^(97*ident+17*i+(order+j)%2+1) for j in range(2)]
            sample=[];ticks=[]
            for i,words in enumerate(r['raw_ticks']):
                assert len(words)==8 and all(isinstance(v,str) and v.isdigit() for v in words)
                t=list(map(int,words));assert t[1]>t[0] and t[2:]==[total,tile,1,total//tile,windows,0x414b4c4558544e31]
                us=(t[1]-t[0])/plan['clockHz']*1e6
                assert us<=r['trace_event_ms'][i]*1000+.5 and r['trace_event_ms'][i]*1000<=r['host_launch_sync_us'][i]+.5
                sample.append(us);ticks.append(['0',str(t[1]-t[0]),*words[2:]])
            binding='latency-duplex/latency/'+build['binaries']['build/latency-measure']
            rows.append(dict(id=f'latency/{ident}/{stage["round"]}/{stage["policy"]}',kind='latency',caseId=ident,
                round=stage['round'],allocation=stage['policy'],api=['DataCopy_count','DataCopy_params','DataCopyPad_params','protocol-control'][api],
                direction=['GM_UB','UB_GM'][direction],dtype='uint32',cores=1,bytes=total,payload=total,tileBytes=tile,tilesPerRequest=total//tile,
                windows=windows,loops=1,workingSet=r['working_set_bytes'],movedBytes=r['moved_bytes'],
                allocationBytes=dict(input=r['input_allocation_bytes'],output=r['output_allocation_bytes']),
                control=api==3,sampleUs=sample,p50=statistics.median(sample),p95=quantile(sample,.95),gbps=r['moved_bytes']/statistics.median(sample)/1000,
                relativeRawTicks=ticks,kernelSampleUs=[v*1000 for v in r['trace_event_ms']],plainKernelSampleUs=[v*1000 for v in r['plain_event_ms']],
                warmupKernelSampleUs=[v*1000 for v in r['warmup_trace_event_ms']],warmupPlainKernelSampleUs=[v*1000 for v in r['warmup_plain_event_ms']],
                traceOrder=r['trace_order'],launchStamps=r['launch_stamps'],binaryHash=build['binaries']['build/latency-measure'],bindingKey=binding,**evidence))
        else:
            shape,cores,tile,requested,target=c;bank=2*tile;per=ceil((requested+cores-1)//cores,bank);ring=per*cores;tail=bank*cores
            groups=max(2,ceil((target+cores*tile-1)//(cores*tile),2));moved=groups*cores*tile;order=None
            assert groups*tile>=per and 4*tile+64+32768<=plan['ubBytes']
            for mode in range(4):
                ident=shape*4+mode;r=byid[ident];common(r)
                read=moved if mode in [0,2] else 0;write=moved if mode in [1,2] else 0
                values=dict(shape_id=shape,mode=mode,cores=cores,tile_bytes=tile,windows_per_direction=2,requested_ring_bytes=requested,
                    actual_ring_bytes_per_direction=ring,per_core_ring_bytes=per,target_bytes_per_direction=target,groups=groups,
                    read_bytes=read,write_bytes=write,moved_bytes=read+write,input_allocation_bytes=max(2<<20,ring+128),
                    output_allocation_bytes=max(2<<20,ring+128),retained_allocation_bytes=tail+128)
                assert all(r[k]==v for k,v in values.items()),'Duplex geometry differs'
                assert r['full_read_oracle'] and r['independent_addresses']
                assert len(r['launch_order'])==n+warm and all(sorted(o)==list(range(8)) for o in r['launch_order'])
                if order is None:order=r['launch_order']
                else:assert order==r['launch_order'],'Modes not paired'
                finite(r,['trace_host_us','plain_host_us'],n)
                assert len(r['core_raw_ticks'])==n
                for i in range(n):
                    assert r['trace_stamps'][i]==0x60000000^(97*shape+17*(warm+i)+mode*2+2)
                    assert r['plain_stamps'][i]==0x60000000^(97*shape+17*(warm+i)+mode*2+1)
                    assert r['trace_event_ms'][i]*1000<=r['trace_host_us'][i]+.5 and r['plain_event_ms'][i]*1000<=r['plain_host_us'][i]+.5
                coreRelative=[]
                for i,words in enumerate(r['core_raw_ticks']):
                    assert len(words)==cores*8 and all(isinstance(v,str) and v.isdigit() for v in words)
                    relative=[]
                    for core in range(cores):
                        t=list(map(int,words[core*8:core*8+8]));assert t[1]>t[0] and t[4:]==[core,groups,mode,0x414b4c4455504c31]
                        assert bool(t[2])==(mode in [0,2,3]) and bool(t[3])==(mode in [1,2,3])
                        assert all(not v or t[0]<=v<=t[1] for v in t[2:4])
                        assert (t[1]-t[0])/plan['clockHz']*1e6<=r['trace_event_ms'][i]*1000+.5
                        relative.extend(map(str,[0,t[1]-t[0],t[2]-t[0] if t[2] else 0,t[3]-t[0] if t[3] else 0,*t[4:]]))
                    coreRelative.append(relative)
                us=[v*1000 for v in r['plain_event_ms']]
                binding='latency-duplex/duplex/'+build['binaries']['build/duplex-measure']
                rows.append(dict(id=f'duplex/{ident}/{stage["round"]}/{stage["policy"]}',kind='duplex',caseId=ident,shapeId=shape,
                    round=stage['round'],allocation=stage['policy'],api='DataCopy_count',dtype='uint32',mode=['read','write','duplex','protocol-control'][mode],
                    direction=['GM_UB','UB_GM','GM_UB+UB_GM','CONTROL'][mode],cores=cores,tileBytes=tile,windows=2,groups=groups,
                    workingSet=ring,requestedWorkingSet=requested,perCoreWorkingSet=per,readBytes=read,writeBytes=write,movedBytes=read+write,
                    control=mode==3,sampleUs=us,p50=statistics.median(us),p95=quantile(us,.95),readGbps=read/statistics.median(us)/1000,
                    writeGbps=write/statistics.median(us)/1000,gbps=(read+write)/statistics.median(us)/1000,
                    traceKernelSampleUs=[v*1000 for v in r['trace_event_ms']],relativeCoreRawTicks=coreRelative,
                    warmupKernelSampleUs=[v*1000 for v in r['warmup_trace_event_ms']],warmupPlainKernelSampleUs=[v*1000 for v in r['warmup_plain_event_ms']],
                    allocationBytes=dict(input=values['input_allocation_bytes'],output=values['output_allocation_bytes'],retained=tail+128),
                    launchOrder=r['launch_order'],traceStamps=r['trace_stamps'],plainStamps=r['plain_stamps'],
                    binaryHash=build['binaries']['build/duplex-measure'],bindingKey=binding,**evidence))
    return rows,dict(key=logical,attempt=key,receiptHash=sha(folder/'receipt.json'),archiveHash=jobs[key]['archive_sha256'])
def receive(base,partial=False):
    ctx=context(base);q,plan,jobs,build=ctx;rows=[];receipts=[];smoke=[];seen=set()
    for st in plan['stages']:
        key=st['key']
        if key not in q['accepted']:
            assert partial,'Missing stage '+key
            continue
        attempt=q.get('acceptedAttempts',{}).get(key,key);r,receipt=accept_stage(base,attempt,key,ctx)
        if st['round']==0:smoke.append(receipt);continue
        for row in r:assert row['id'] not in seen;seen.add(row['id'])
        rows.extend(r);receipts.append(receipt)
    if not partial:
        assert len(smoke)==4 and len(rows)==plan['counts']['configurationRounds'],'Incomplete matrix'
        for kind,count in [('latency',plan['counts']['latencyPrimaryRounds']),('duplex',plan['counts']['duplexPrimaryRounds'])]:
            assert len([r for r in rows if r['kind']==kind and not r['control']])==count
        for api in ['DataCopy_count','DataCopy_params','DataCopyPad_params']:
            for direction in ['GM_UB','UB_GM']:
                for windows in [1,2]:
                    for allocation in ['normal','huge-first']:
                        for round in [1,2]:
                            assert {r['bytes'] for r in rows if r['kind']=='latency' and (r['api'],r['direction'],r['windows'],r['allocation'],r['round'])==(api,direction,windows,allocation,round)}=={1<<i for i in range(5,23)}
    return dict(schema='akl.web.latency-duplex.v1',measuredDate='2026-10-11',environment=dict(soc=plan['expectedSoc'],cann='CANN 9.1.0',
        aiv_count=plan['availableAiv'],ub_bytes=plan['ubBytes'],clockHz=plan['clockHz'],clockSource=plan['clockSource'],topology='single_device_local_GM'),
        rows=rows,evidence=dict(receiverValidation='partial' if partial else 'passed',configurationRounds=len(rows),
        timedSamples=sum(len(r['sampleUs']) for r in rows),traceOffSamples=sum(len(r['sampleUs']) for r in rows),counts=plan['counts'],
        sourceArchiveSha256=q['sourceArchiveSha256'],planSha256=q['planSha256'],sourceCommit=q['sourceCommit'],receipts=receipts,smoke=smoke,
        clockDocumentUrl=q['clockDocumentUrl'],sourceBindings={f'latency-duplex/{k}/'+build['binaries'][f'build/{k}-measure']:dict(
            binaryHash=build['binaries'][f'build/{k}-measure'],sources={f'{k}-{part}.cpp':build['sources'][f'{k}-{part}.cpp'] for part in ['main','kernel']},compileOptions=build['compileOptions']) for k in ['latency','duplex']},
        latencyTiming='One complete logical request in SYS_CNT; last DMA completion included; no division by repeat count or empty-control subtraction',
        duplexTiming='Read bytes, write bytes, and their sum share one complete trace-off ACL Event interval; separate peaks are not summed',
        memory='Independent read/write GM and UB; paired modes share the same allocation; NORMAL_ONLY/HUGE_FIRST flags; physical pages/counters unknown',
        oracle='Independent full read launch; every timed full write/untouched target, complete retained read windows and 128B guards',
        clocks='Public core ticks are within-core relative values; observation stamps do not establish exact independent DMA completion or cross-core calibration',
        isolation='Whole Host/container idle before and after each short task; transient interference unknown'))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('base',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--partial',action='store_true');a=p.parse_args()
    d=receive(a.base,a.partial);a.output.write_text(json.dumps(d,ensure_ascii=False,separators=(',',':'))+'\n')
    print(d['evidence']['receiverValidation'],len(d['rows']),d['evidence']['timedSamples'])
