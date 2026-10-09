#!/usr/bin/env python3
"""校验共同 Event 区间、多核记录与完整预定矩阵，只导出脱敏结果。"""
import argparse,configparser,csv,hashlib,importlib.util,json,math,re,statistics
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def quantile(xs,p):
    xs=sorted(xs);v=(len(xs)-1)*p;lo=int(v);hi=min(lo+1,len(xs)-1)
    return xs[lo]+(xs[hi]-xs[lo])*(v-lo)
def ceil(n,u):return (n+u-1)//u*u
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runs',type=Path,required=True)
    p.add_argument('--akl-root',type=Path,required=True)
    p.add_argument('--environment',type=Path,required=True)
    p.add_argument('--platform-config',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();env=json.loads(a.environment.read_text())
    platform=a.platform_config.read_bytes();platform_hash=sha(a.platform_config)
    cfg=configparser.ConfigParser(strict=False);cfg.read_string(platform.decode())
    if cfg['version']['soc_version']!=env['soc'] or {int(cfg[s]['l2_size']) for s in cfg.sections() if 'l2_size' in cfg[s]}!={env['l2_bytes']}:raise ValueError('平台配置与设备/L2 不匹配')
    public_env=env.copy();platform_meta={'configSha256':platform_hash,'recordedHash':env['platform_config_sha256']}
    if env['platform_config_sha256']!=platform_hash:
        # 早期探针 print 了两个相同 ini：保存原始 manifest，只纠正公开哈希的对象。
        if hashlib.sha256((platform+b'\n')*2).hexdigest()!=env['platform_config_sha256']:raise ValueError('平台配置哈希无法追溯')
        public_env.update(platform_config_sha256=platform_hash,platform_capture_sha256=env['platform_config_sha256'])
        platform_meta['note']='早期记录哈希对应两份同版本相同配置的拼接快照；已独立核对单份配置，容量相同，原始 manifest 保留。'
    spec=importlib.util.spec_from_file_location('plan',a.akl_root/'scripts/plan_bandwidth.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    canonical=module.curves(env['aiv_count']);expected={r[0]:list(r[1:]) for curve in canonical for r in curve}
    seen=set();rows=[];manifest_hashes=[];source=None;binary=None;install=None;profile=None;date=set()
    for bp in sorted(a.runs.rglob('batch.json')):
        batch=json.loads(bp.read_text())
        if batch.get('schema')!='akl.bandwidth.batch.v1':continue
        for c in batch['chunks']:
            if c['status']!='validated':continue
            folder=bp.parent/c['run'];mp=folder/'manifest.json';m=json.loads(mp.read_text())
            if m['schema']!='akl.bandwidth.mbench.v1' or m['status']!='validated' or m['round']!=batch['round']:raise ValueError('状态/轮次错误')
            if m['warmup']!=2 or m['samples']!=12 or m['environment']!=env:raise ValueError('采样或设备配置不匹配')
            if sha(folder/'samples.jsonl')!=m['samples_sha256'] or sha(folder/'plan.csv')!=m['plan_sha256']:raise ValueError('原始文件哈希不匹配')
            for label in ['before','after']:
                op=folder/f'occupancy-{label}.txt';e=m[f'occupancy_{label}'];text=op.read_text()
                if e['observed_idle'] is not True or sha(op)!=e['sha256'] or 'No running processes found' not in text or re.search(r'^\|\s*\d+\s*\|\s*\d+\s*\|',text,re.M):raise ValueError('占用快照未通过')
            b=m['build']
            if b['schema']!='akl.bandwidth.build.v1' or b['npu_arch']!='dav-3510':raise ValueError('构建目标不匹配')
            if set(b['source_sha256'])!={'examples/a5_bandwidth/'+n for n in ['kernel.cpp','main.cpp','CMakeLists.txt']}:raise ValueError('构建源码凭据不完整')
            cp=m['clock_profile']
            if cp['schema']!='akl.datacopy.profile.v1' or cp['soc']!=env['soc'] or cp['npu_arch']!='dav-3510' or cp['memory_scope']!='local_GM' or type(cp['clock_hz']) is not int or cp['clock_hz']<=0 or not cp['clock_source'].strip():raise ValueError('时钟/场景依据无效')
            for name,value in b['source_sha256'].items():
                if sha(a.akl_root/name)!=value:raise ValueError('源码已变化：'+name)
            if source is not None and (source!=b['source_sha256'] or binary!=b['executable_sha256'] or install!=b['cann_install'] or profile!=m['clock_profile']):raise ValueError('二进制/环境不一致')
            source=b['source_sha256'];binary=b['executable_sha256'];install=b['cann_install'];profile=m['clock_profile']
            local_plan={int(r[0]):list(map(int,r[1:])) for r in csv.reader((folder/'plan.csv').read_text().splitlines())}
            measured=[json.loads(s) for s in (folder/'samples.jsonl').read_text().splitlines()]
            if len(measured)!=len(local_plan) or {r['id'] for r in measured}!=set(local_plan):raise ValueError('曲线不完整')
            for r in measured:
                params=[r[k] for k in ['direction','shared_read','cores','tile_bytes','batch','requested_ring_bytes','target_bytes','control']]
                if params!=local_plan[r['id']] or params!=expected[r['id']]:raise ValueError('参数不匹配')
                key=(m['round'],r['id'])
                if key in seen:raise ValueError('重复配置，禁止选最快样本')
                seen.add(key)
                n=r['cores'];bank=r['tile_bytes']*r['batch'];requested=r['requested_ring_bytes']
                per=ceil(requested if r['shared_read'] else (requested+n-1)//n,2*bank)
                groups=max(2,ceil((r['target_bytes']+n*bank-1)//(n*bank),2))
                moved=0 if r['control'] else groups*n*bank
                if [r[k] for k in ['groups','per_core_ring_bytes','actual_ring_bytes','moved_bytes']]!=[groups,per,per*(1 if r['shared_read'] else n),moved]:raise ValueError('有效字节或地址覆盖错误')
                if r['soc']!=env['soc'] or r['available_aiv']!=env['aiv_count'] or r['ub_bytes']!=env['ub_bytes'] or r['correctness'] is not True or r['validated_every_launch'] is not True:raise ValueError('设备/正确性错误')
                times=r['event_ms'];core=r['core_raw_ticks']
                if len(times)!=12 or len(core)!=12 or len(r['warmup_event_ms'])!=2 or len(r['host_launch_sync_us'])!=12 or any(not math.isfinite(t) or t<=0 for t in times+r['warmup_event_ms']+r['host_launch_sync_us']):raise ValueError('样本不足/共同区间无效')
                durations=[]
                for t,record in zip(times,core):
                    if len(record)!=n*4:raise ValueError('核记录不完整')
                    spans=[]
                    for i in range(n):
                        begin,end,logical,magic=map(int,record[i*4:i*4+4])
                        if end<=begin or logical!=i or magic!=0x414b4c42414e4431:raise ValueError('核提交/区间无效')
                        # 每核 DMA 区间包含在 ACL 的整 kernel 区间内；不使用跨核绝对起点。
                        if (end-begin)*1e6/profile['clock_hz']>t*1000+0.5:raise ValueError('核时钟与共同区间矛盾')
                        spans.append(str(end-begin))
                    durations.append(spans)
                us=[t*1000 for t in times]
                rows.append(dict(id=f'r{m["round"]}-c{r["id"]}',caseId=r['id'],round=m['round'],
                    direction='UB_GM' if r['direction'] else 'GM_UB',sharedRead=bool(r['shared_read']),cores=n,
                    tileBytes=r['tile_bytes'],batch=r['batch'],requestedRing=requested,actualRing=r['actual_ring_bytes'],
                    perCoreRing=per,groups=groups,control=bool(r['control']),movedBytes=moved,
                    p50Us=statistics.median(us),p95Us=quantile(us,.95),eventMs=times,warmupEventMs=r['warmup_event_ms'],
                    coreDurationTicks=durations,coreP50Us=[statistics.median(int(d[i])*1e6/profile['clock_hz'] for d in durations) for i in range(n)],
                    correctness=True,manifestHash=sha(mp),binaryHash=binary))
            manifest_hashes.append(sha(mp));date.add(m['started_utc'][:10])
    if seen!={(r,i) for r in [1,2] for i in expected}:raise ValueError(f'完整两轮要求 {2*len(expected)}，当前 {len(seen)}')
    grouped={}
    for r in rows:grouped.setdefault(r['caseId'],[]).append(r)
    points=[]
    for rs in grouped.values():
        r=rs[0];t=statistics.median(x['p50Us'] for x in rs)
        points.append(r|dict(p50Us=t,gbps=r['movedBytes']/t/1000))
    curves=[]
    for ids in canonical:
        cp=[next(p for p in points if p['caseId']==r[0]) for r in ids];cp.sort(key=lambda r:r['cores'])
        p0=cp[0]
        if not p0['control']:
            peak=max(cp,key=lambda p:p['gbps']);threshold=.95*peak['gbps'];n95=next(p for p in cp if p['gbps']>=threshold)
            ix=cp.index(n95);pair=ix+1<len(cp) and cp[ix+1]['gbps']>=threshold
        else:peak=n95=None;pair=False
        curves.append(dict(direction=p0['direction'],sharedRead=p0['sharedRead'],tileBytes=p0['tileBytes'],batch=p0['batch'],
            requestedRing=p0['requestedRing'],control=p0['control'],points=len(cp),peakGbps=peak['gbps'] if peak else None,
            peakCores=peak['cores'] if peak else None,n95=n95['cores'] if n95 else None,adjacentPlateau=pair,
            speedupAtPeak=peak['gbps']/p0['gbps'] if peak else None))
    diffs=[abs(rs[1]['p50Us']/rs[0]['p50Us']-1)*100 for rs in grouped.values()]
    result=dict(schema='akl.web.bandwidth.v1',measuredDate=' / '.join(sorted(date)),
        environment=public_env|dict(cann='CANN '+re.search(r'^version=(.+)$',install,re.M).group(1),clockHz=profile['clock_hz']),
        rows=rows,curves=curves,evidence=dict(receiverValidation='passed',configsPerRound=len(expected),timedSamples=len(rows)*12,
            warmupSamples=len(rows)*2,rounds=2,manifestHashes=manifest_hashes,sourceHashes=source,binaryHash=binary,
            repeatability=dict(medianRelativePct=statistics.median(diffs),maxRelativePct=max(diffs)),platformMetadata=platform_meta,
            aggregateTiming='aclrtEventElapsedTime：同一 stream 的完整多核 kernel 共同区间；原始值，不扣空对照',
            coreTiming='GetSystemCycle 差值用于核内 DMA 区间/均衡；不用跨核绝对时间拼接吞吐',
            bytes='单向全核有效 payload，重复同址只读包括重复逻辑请求，不能当 HBM 物理流量',
            isolation='每曲线前后整机 npu-smi 空闲快照；无法排除快照之间的瞬时干扰'))
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')))
    print(json.dumps(result['evidence']|dict(manifestHashes=len(manifest_hashes)),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
