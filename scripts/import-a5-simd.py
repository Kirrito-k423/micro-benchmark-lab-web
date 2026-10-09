#!/usr/bin/env python3
"""验收完整两轮同工作量 SIMD 实验；只公开脱敏参数和原始样本。"""
import argparse,csv,hashlib,importlib.util,json,re,statistics
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def percentile(xs,p):
    xs=sorted(xs);pos=(len(xs)-1)*p;lo=int(pos);hi=min(lo+1,len(xs)-1)
    return xs[lo]+(xs[hi]-xs[lo])*(pos-lo)
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runs',type=Path,required=True)
    p.add_argument('--akl-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    spec=importlib.util.spec_from_file_location('plan',a.akl_root/'scripts/plan_simd_arithmetic.py')
    plan=importlib.util.module_from_spec(spec);spec.loader.exec_module(plan)
    expected={r[0]:list(r[1:]) for r in plan.cases()}
    rows=[];seen=set();manifests=[];builds=[];profile=None;source=None;install=None;dates=set()
    for bp in sorted(a.runs.rglob('batch.json')):
        batch=json.loads(bp.read_text())
        if batch.get('schema')!='akl.simd.batch.v1':continue
        for chunk in batch['chunks']:
            if chunk['status']!='validated':continue
            folder=bp.parent/chunk['run'];mp=folder/'manifest.json';m=json.loads(mp.read_text())
            if m['schema']!='akl.simd.mbench.v1' or m['status']!='validated':raise ValueError('chunk 状态错误')
            if m['samples']!=15 or m['warmup']!=2:raise ValueError('采样口径变化')
            if m['round']!=batch['round']:raise ValueError('轮次不一致')
            for label in ['before','after']:
                op=folder/f'occupancy-{label}.txt';e=m[f'occupancy_{label}'];text=op.read_text()
                if e['observed_idle'] is not True or sha(op)!=e['sha256'] or 'No running processes found' not in text or re.search(r'^\|\s*\d+\s*\|\s*\d+\s*\|',text,re.M):raise ValueError('占用快照未通过')
            if sha(folder/'samples.jsonl')!=m['samples_sha256'] or sha(folder/'plan.csv')!=m['plan_sha256']:raise ValueError('样本/plan 哈希错误')
            b=m['build']
            if b['schema']!='akl.simd.build.v1' or b['npu_arch']!='dav-3510':raise ValueError('构建目标不匹配')
            for name,value in b['source_sha256'].items():
                if sha(a.akl_root/name)!=value:raise ValueError('源码版本不匹配：'+name)
            if profile is not None and (profile!=m['clock_profile'] or source!=b['source_sha256'] or install!=b['cann_install']):raise ValueError('两轮环境/源码不一致')
            profile=m['clock_profile'];source=b['source_sha256'];install=b['cann_install']
            if profile['clock_hz']<=0 or profile['soc']!='Ascend950DT_9582':raise ValueError('时钟/芯片未核实')
            localplan={int(r[0]):list(map(int,r[1:])) for r in csv.reader((folder/'plan.csv').read_text().splitlines())}
            measured=[json.loads(s) for s in (folder/'samples.jsonl').read_text().splitlines()]
            if len(measured)!=len(localplan) or {r['id'] for r in measured}!=set(localplan):raise ValueError('chunk 覆盖不完整')
            for r in measured:
                params=[r[k] for k in ['impl','op','elements','threads','steps','vf_calls']]
                if params!=localplan[r['id']] or params!=expected[r['id']]:raise ValueError('配置错误')
                key=(m['round'],r['id'])
                if key in seen:raise ValueError('重复配置，禁止挑最快')
                seen.add(key)
                if r['correctness'] is not True or r['soc']!=profile['soc'] or r['aiv_count']!=1 or r['dtype']!='float32':raise ValueError('正确性/环境错误')
                ticks=r['raw_ticks']
                if len(ticks)!=15 or len(r['warmup_ticks'])!=2 or len(r['host_launch_sync_us'])!=15 or any(int(t)<=0 for t in ticks):raise ValueError('原始样本不完整')
                if not 0<=r['max_abs_error']<=3e-5:raise ValueError('最大误差异常')
                values=[int(t)*1e6/profile['clock_hz'] for t in ticks]
                rows.append(dict(id=f'r{m["round"]}-c{r["id"]}',caseId=r['id'],round=m['round'],impl=r['impl'],op=r['op'],
                    elements=r['elements'],threads=r['threads'] if r['impl']==1 else None,steps=r['steps'],dtype='float32',
                    p50=statistics.median(values),p95=percentile(values,.95),rawTicks=ticks,warmupTicks=r['warmup_ticks'],
                    hostLaunchSyncUs=r['host_launch_sync_us'],maxAbsError=r['max_abs_error'],correctness=True,
                    manifestHash=sha(mp),binaryHash=b['executable_sha256']))
            manifests.append(sha(mp));builds.append(b['executable_sha256']);dates.add(m['started_utc'][:10])
    if seen!={(r,i) for r in [1,2] for i in expected}:raise ValueError(f'覆盖不足：{len(seen)} / {2*len(expected)}')
    version=re.search(r'^version=(.+)$',install,re.M).group(1)
    grouped={}
    for r in rows:grouped.setdefault(r['caseId'],{})[r['round']]=r['p50']
    delta=[abs(v[2]/v[1]-1)*100 for v in grouped.values()]
    result=dict(schema='akl.web.simd.v1',measuredDate=' / '.join(sorted(dates)),
        environment=dict(soc=profile['soc'],cann=f'CANN {version}',clockHz=profile['clock_hz'],aivCount=1,dtype='float32',
            memoryScope='local_UB',clockSource=profile['clock_source'],npuArch='dav-3510'),
        implementations=['SIMD Tensor API','SIMT','REG SIMD · 1 组','REG SIMD · 4 组'],rows=rows,
        evidence=dict(receiverValidation='passed',configsPerRound=len(expected),rounds=2,timedSamples=len(rows)*15,
            warmupSamples=len(rows)*2,manifestHashes=manifests,binaryHashes=sorted(set(builds)),sourceHashes=source,
            repeatability=dict(medianRelativePct=statistics.median(delta),maxRelativePct=max(delta)),
            maxAbsError=max(r['maxAbsError'] for r in rows),
            boundary='从计算分发前，到 V_S 完成等待后；不含 GM 准备/导出。不扣空对照。',
            isolation='每 16–128 配置短批次前后整机 npu-smi 空闲快照；无法排除快照之间的瞬时干扰。',
            metric='有效 FP32 元素运算数 n*steps / 完成区间；不是硬件指令 FLOPS 上限。'))
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')))
    print(json.dumps(result['evidence']|dict(manifestHashes=len(manifests)),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
