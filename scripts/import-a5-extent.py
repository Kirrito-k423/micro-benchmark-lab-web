"""Accept the original source, build, archives, raw ticks, and exact 18-point coverage."""
import argparse,csv,hashlib,json,math,re,statistics,tarfile
from pathlib import Path
WEB=Path(__file__).resolve().parents[1]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def quantile(xs,q):
    a=sorted(xs);v=(len(a)-1)*q;i=int(v);j=min(i+1,len(a)-1);return a[i]+(a[j]-a[i])*(v-i)

def receive(base,partial=False):
    q=json.loads((base/'queue.json').read_text());plan=json.loads((base/'execution-plan.json').read_text())
    jobs=json.loads((base/'tasks-state.json').read_text());build=q['build']
    assert sha(base/'execution-plan.json')==q['planSha256'],'Frozen plan mismatch'
    assert sha(base/'source.tar.gz')==q['sourceArchiveSha256'],'Source archive mismatch'
    with tarfile.open(base/'source.tar.gz') as t:
        assert json.loads(t.extractfile('execution-plan.json').read())==plan,'Packaged plan differs'
        for name,h in build['sources'].items():
            assert hashlib.sha256(t.extractfile(name).read()).hexdigest()==h,'Built source differs'
            assert sha(WEB/'experiments/a5_extent'/name)==h,'Published source differs'
    def bind(key):
        j=jobs[key];s=j['status_snapshot']
        assert s['status']=='succeeded' and s['exitCode']==0 and s['finishedAt'] and s['archiveReady'] and s['selectedMachineId']==q['machine'],'Task not accepted'
        archive=base/'archives'/(j['id']+'.tar.gz');assert sha(archive)==j['archive_sha256'],'Archive digest mismatch'
        root=Path(j['raw'])
        with tarfile.open(archive) as t:
            for p in root.rglob('*'):
                if p.is_file():assert t.extractfile(str(p.relative_to(root))).read()==p.read_bytes(),'Raw archive bytes differ'
        return root/'results'
    br=bind(q.get('buildKey','build'))
    assert json.loads((br/'setup/build.json').read_text())==build,'Build receipt differs'
    cann=re.search(r'^version=(.+)$',build['cann'],re.M).group(1)
    assert cann=='9.1.0' and plan['expectedSoc']=='Ascend950DT_9582' and plan['clockHz']==10**9,'Clock/target not validated'
    assert q['clockDocumentUrl'] and plan['clockSource']
    seen=set();rows=[];smoke=[];receipts=[];environment=None
    for stage in plan['stages']:
        key=stage['key']
        if key not in q['accepted']:
            assert partial,'Missing stage '+key
            continue
        jobKey=q.get('acceptedAttempts',{}).get(key,key)
        root=bind(jobKey);folder=root/'stage';m=json.loads((folder/'receipt.json').read_text())
        assert m['status']=='validated' and m['build']==build and m['stage']==stage and m['planSha256']==q['planSha256'],'Stage receipt mismatch'
        for name,h in m['outputFiles'].items():assert sha(folder/name)==h,'Output digest mismatch'
        for name in ['host-before.txt','host-after.txt','stage/container-before.txt','stage/container-after.txt']:
            s=(root/name).read_text();assert 'No running processes found' in s and not re.search(r'^\|\s*\d+\s*\|\s*\d+\s*\|',s,re.M),'NPU interference'
        with (folder/'plan.csv').open() as f:assert [[int(v) for v in r] for r in csv.reader(f)]==stage['cases']
        raw=[json.loads(s) for s in (folder/'samples.jsonl').read_text().splitlines()]
        assert len(raw)==len(stage['cases']) and len({r['id'] for r in raw})==len(raw),'Duplicate/missing configurations'
        byid={r['id']:r for r in raw}
        for c in stage['cases']:
            ident,api,direction,total,tile,windows,repeats=c;r=byid[ident]
            expected=dict(id=ident,api=api,direction=direction,total_bytes=total,tile_bytes=tile,windows=windows,repeats=repeats,
                tiles_per_request=total//tile,moved_bytes=total*repeats,working_set_bytes=total,policy=stage['policy'],soc=plan['expectedSoc'],
                ub_bytes=plan['ubBytes'],input_allocation_bytes=max(2<<20,total),output_allocation_bytes=max(2<<20,max(total,tile*windows)+128))
            assert all(r[k]==v for k,v in expected.items()),'Measured geometry differs'
            assert r['available_aiv']>=1 and tile*windows+64+32768<=r['ub_bytes'] and total%tile==0
            assert r['correctness'] and r['validated_every_launch'] and r['full_read_oracle'] and r['guard_bytes']==128,'Oracle failed'
            n=stage['samples'];warm=stage['warmup']
            for name in ['trace_event_ms','plain_event_ms','host_launch_sync_us','raw_ticks']:assert len(r[name])==n
            for name in ['warmup_trace_event_ms','warmup_plain_event_ms']:assert len(r[name])==warm
            assert len(r['trace_order'])==len(r['launch_stamps'])==n+warm and all(v in [0,1] for v in r['trace_order'])
            assert all(len(v)==2 for v in r['launch_stamps'])
            for i,(order,stamps) in enumerate(zip(r['trace_order'],r['launch_stamps'])):
                assert stamps==[0x60000000 ^ (97*ident+17*i+(order+j)%2+1) for j in range(2)]
            for name in ['trace_event_ms','plain_event_ms','host_launch_sync_us','warmup_trace_event_ms','warmup_plain_event_ms']:
                assert all(math.isfinite(x) and x>0 for x in r[name]),'Invalid time'
            sample=[]
            for i,words in enumerate(r['raw_ticks']):
                assert len(words)==8 and all(isinstance(v,str) and v.isdigit() for v in words)
                tick=list(map(int,words));assert tick[1]>tick[0] and tick[2:]==[total,tile,repeats,total//tile,windows,0x414b4c4558544e31],'Raw tick receipt mismatch'
                us=(tick[1]-tick[0])/plan['clockHz']*1e6
                assert us<=r['trace_event_ms'][i]*1000+0.5 and r['trace_event_ms'][i]*1000<=r['host_launch_sync_us'][i]+0.5,'Clock intervals inconsistent'
                sample.append(us/repeats)
            if environment is None:environment=dict(soc=r['soc'],cann='CANN '+cann,aiv_count=r['available_aiv'],ub_bytes=r['ub_bytes'],
                clockHz=plan['clockHz'],clockSource=plan['clockSource'],topology='single_device_local_GM')
            assert environment['aiv_count']==r['available_aiv']
            if stage['round']==0:continue
            signature=(ident,stage['round'],stage['policy']);assert signature not in seen;seen.add(signature)
            p50=statistics.median(sample);bindingKey='extent/'+build['binaries']['build/measure']
            rows.append(dict(id=f"extent/{ident}/{stage['round']}/{stage['policy']}",kind='extent',caseId=ident,round=stage['round'],
                allocation=stage['policy'],api=['DataCopy_count','DataCopy_params','DataCopyPad_params'][api],direction=['GM_UB','UB_GM'][direction],
                dtype='uint32',cores=1,payload=total,tileBytes=tile,tilesPerRequest=total//tile,windows=windows,loops=repeats,batch=1,
                mode='small',control=0,gmOffset=0,workingSet=total,movedBytes=total*repeats,p50=p50,p95=quantile(sample,.95),gbps=total/p50/1000,
                sampleUs=sample,rawTicks=r['raw_ticks'],kernelSampleUs=[v*1000 for v in r['trace_event_ms']],
                plainKernelSampleUs=[v*1000 for v in r['plain_event_ms']],warmupKernelSampleUs=[v*1000 for v in r['warmup_trace_event_ms']],
                warmupPlainKernelSampleUs=[v*1000 for v in r['warmup_plain_event_ms']],traceOrder=r['trace_order'],launchStamps=r['launch_stamps'],
                allocationBytes=dict(input=r['input_allocation_bytes'],output=r['output_allocation_bytes'],records=64),
                binaryHash=build['binaries']['build/measure'],bindingKey=bindingKey,manifestHash=sha(folder/'receipt.json'),
                archiveHash=jobs[jobKey]['archive_sha256'],correctness='full independent read; every timed full write or retained UB tail + 128 B guard'))
        receipt=dict(key=key,receiptHash=sha(folder/'receipt.json'),archiveHash=jobs[jobKey]['archive_sha256'])
        (smoke if stage['round']==0 else receipts).append(receipt)
    if not partial:
        expected={(c[0],s['round'],s['policy']) for s in plan['stages'] if s['round'] for c in s['cases']}
        assert seen==expected and len(rows)==plan['counts']['configurationRounds'] and len(smoke)==2,'Incomplete coverage'
        for api in ['DataCopy_count','DataCopy_params','DataCopyPad_params']:
            for direction in ['GM_UB','UB_GM']:
                for windows in [1,2]:
                    for policy in ['normal','huge-first']:
                        for round in [1,2]:
                            assert {r['payload'] for r in rows if (r['api'],r['direction'],r['windows'],r['allocation'],r['round'])==(api,direction,windows,policy,round)}=={1<<p for p in range(5,23)}
    sources={name:build['sources'][name] for name in ['kernel.cpp','main.cpp']}
    return dict(schema='akl.web.extent.v1',measuredDate='2026-10-11',environment=environment,rows=rows,evidence=dict(
        receiverValidation='partial' if partial else 'passed',configurationRounds=len(rows),pointsPerCurve=18,minBytes=32,maxBytes=4<<20,
        timedSamples=sum(len(r['sampleUs']) for r in rows),traceOffSamples=sum(len(r['plainKernelSampleUs']) for r in rows),
        sourceBindings={'extent/'+build['binaries']['build/measure']:dict(binaryHash=build['binaries']['build/measure'],sources=sources,compileOptions=build['compileOptions'])},
        sourceArchiveSha256=q['sourceArchiveSha256'],planSha256=q['planSha256'],receipts=receipts,smoke=smoke,clockDocumentUrl=q['clockDocumentUrl'],
        timing='SYS_CNT/repeats; each request waits for completion; separate full ACL Event and trace-off samples',
        memory='new input/output allocations per configuration, >=2 MiB; NORMAL_ONLY / HUGE_FIRST paired; actual working set=total bytes',
        isolation='whole Host and container idle snapshots before/after each short task; transient interference unknown',
        cache='repeated same request under default L2; no physical HBM, TLB, cache, or page-table counters',
        oracle='independent full read verification; every launch full write or full retained UB tail plus 128 B guard'))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('base',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--partial',action='store_true');a=p.parse_args();d=receive(a.base,a.partial)
    a.output.write_text(json.dumps(d,ensure_ascii=False,separators=(',',':'))+'\n')
    print(d['evidence']['receiverValidation'],len(d['rows']),d['evidence']['timedSamples'])
