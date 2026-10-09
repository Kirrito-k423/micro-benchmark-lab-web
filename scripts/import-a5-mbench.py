#!/usr/bin/env python3
"""重算已验证的 A5 原始样本，并仅导出网站所需的脱敏字段。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from datetime import datetime,timedelta,timezone
import numpy as np


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runs',type=Path,required=True)
    p.add_argument('--setup',type=Path,required=True)
    p.add_argument('--akl-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--allow-partial',action='store_true',help='仅用于本地检查；正式发布必须完整两轮')
    a=p.parse_args()
    sys.path.insert(0,str(a.akl_root/'python'))
    from akl.datacopy_report import analyse
    from akl.trace import decode,duration_ticks
    def load_plan(name):
        spec=importlib.util.spec_from_file_location(name,a.akl_root/'scripts'/(name+'.py'))
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module.plan()
    alignment_plan={c['name']:c for c in load_plan('plan_alignment')}
    edge={127,128,129,159,160,161,191,192,193,223,224,225,255,256,257}
    paired_names={c['name'] for c in alignment_plan.values() if c['api']=='DataCopyPad_params' and c['windows']==1 and c['gm_offset_bytes']==0
                  and c['block_bytes']//(1 if c['dtype']=='uint8' else 4) in edge}
    simt_plan={i:list(c) for i,c in enumerate(load_plan('plan_simt_arithmetic'))}
    profile=json.loads((a.setup/'profile.json').read_text())
    install=(a.setup/'cann-install.txt').read_text()
    version=re.search(r'^version=(.+)$',install,re.M).group(1)
    result=dict(schema='akl.web.mbench.v1',measuredDate=None,
        environment=dict(soc=profile['soc'],cann=f'CANN {version}',clockHz=profile['clock_hz'],aivCount=1,deviceIds={},
            topology='A5 借用节点；两类实验各自在固定节点重复两轮',memoryScope='local_GM'),
        alignment=[],alignmentPaired=[],simt=[],evidence=dict(manifests=[],sources={},
            boundaries={'alignment':'DataCopy 循环完成区间 / 调用数；原始值，不扣空循环',
                'simt':'同工作量 FP32 依赖链，含计算调用与完成等待；不含 GM 准备和导出',
                'overhead':'VF 调用 + 每线程一次 UB 写出 + 完成等待；不是线程创建的独立时间'},
            isolation='每短批次前后 npu-smi 空闲检查；瞬时干扰不能完全排除',clockSource=profile['clock_source']))
    seen=set();dates=set()
    for manifest_path in sorted(a.runs.rglob('manifest.json')):
        m=json.loads(manifest_path.read_text());folder=manifest_path.parent
        if m.get('status')!='validated': continue
        batch_path=folder.parent/'batch.json'
        if batch_path.exists():
            batch=json.loads(batch_path.read_text())
            if not any(c['run']==folder.name and c['status']=='validated' for c in batch['chunks']):continue
        elif not a.allow_partial:raise ValueError('正式实验缺少短批次结束检查凭据')
        stamp=m.get('started_utc') or (batch.get('started_utc') if batch_path.exists() else None)
        if stamp:dates.add(datetime.fromisoformat(stamp).astimezone(timezone(timedelta(hours=8))).date().isoformat())
        schema=m.get('schema')
        match=re.search(r'(alignment(?:-paired)?|simt)-r([12])-c\d+',folder.name)
        if not match: continue
        round_=int(match[2])
        dataset='alignmentPaired' if match[1]=='alignment-paired' else match[1]
        if schema=='akl.datacopy.v1':
            result['environment']['deviceIds'].setdefault('alignment',[])
            if m['device'] not in result['environment']['deviceIds']['alignment']:result['environment']['deviceIds']['alignment'].append(m['device'])
            rows=analyse(folder,render_figures=False)
            if m['profile']['soc']!=profile['soc'] or m['profile']['clock_hz']!=profile['clock_hz']:
                raise ValueError('测量芯片/时钟不一致')
            if m['build']['cann_install']!=install:raise ValueError('CANN 环境不一致')
            for name,value in m['build']['source_sha256'].items():
                if sha(a.akl_root/name)!=value:raise ValueError('接收端 DataCopy 源码版本不匹配')
                result['evidence']['sources'][name]=value
            records={r['case']['name']:r for r in m['cases']}
            for r in rows:
                record=records[r['name']];c=record['case']
                if c!=alignment_plan.get(c['name']):raise ValueError('DataCopy 配置与此次矩阵不符')
                samples=json.loads((folder/r['name']/'samples.json').read_text())
                raw=[s['ticks'] for s in samples if s['trace'] and not s['warmup']]
                if len(raw)!=12 or len(samples)!=26:raise ValueError('DataCopy 计时/对照/预热样本数不符')
                if dataset=='alignmentPaired':
                    if m.get('fixed_buffers',{}).get('reused_across_cases') is not True or not m['arguments'].get('reuse_buffers'):
                        raise ValueError('边界复验缺少固定分配证据')
                    if c['windows']!=1 or c['gm_offset_bytes']!=0 or c['api']!='DataCopyPad_params':raise ValueError('边界复验参数不符')
                    if c['name'] not in paired_names:raise ValueError('边界复验未使用预定长度')
                key=(dataset,round_,r['name'])
                if key in seen:raise ValueError('配置/轮次重复，不能静默选最快项')
                seen.add(key)
                element=1 if r['dtype']=='uint8' else 4
                result[dataset].append(dict(id=f'{dataset}-r{round_}-{r["name"]}',round=round_,dtype=r['dtype'],fixedBuffers=dataset=='alignmentPaired',
                    direction=r['direction'],api=r['api'],elements=r['block_bytes']//element,payload=r['payload_bytes_per_call'],
                    gmOffset=c['gm_offset_bytes'],windows=r['windows'],loops=r['loops'],batch=r['batch'],
                    slots=r['slots'],workingSet=r['working_set_bytes'],p50=r['p50_us_per_call'],p95=r['p95_us_per_call'],
                    rawTicks=raw,manifestHash=sha(manifest_path),libraryHash=m['build']['library_sha256'],correctness=True))
        elif schema=='akl.simt.mbench.v1':
            result['environment']['deviceIds'].setdefault('simt',[])
            if m['device'] not in result['environment']['deviceIds']['simt']:result['environment']['deviceIds']['simt'].append(m['device'])
            if m['clock_profile']!=profile or m['cann_install']!=install:raise ValueError('SIMT 环境不一致')
            if m['samples_sha256']!=sha(folder/'samples.jsonl') or m['plan_sha256']!=sha(folder/'plan.csv'):
                raise ValueError('SIMT 样本/plan 哈希不一致')
            for label in ('before','after'):
                evidence=m[f'occupancy_{label}']
                if evidence['observed_idle'] is not True or evidence['sha256']!=sha(folder/f'occupancy-{label}.txt'):
                    raise ValueError('SIMT 占用证据不一致')
            build=m['build']
            if build['executable_sha256']!=m['executable_sha256'] or build['source_sha256']!=m['source_sha256']:
                raise ValueError('SIMT 构建绑定不一致')
            for name,value in build['source_sha256'].items():
                if sha(a.akl_root/name)!=value:raise ValueError('接收端 SIMT 源码版本不匹配')
                result['evidence']['sources'][name]=value
            plan={int(line.split(',')[0]):list(map(int,line.split(',')[1:])) for line in (folder/'plan.csv').read_text().splitlines()}
            rows=[json.loads(line) for line in (folder/'samples.jsonl').read_text().splitlines()]
            if len(rows)!=len(plan) or len({r['id'] for r in rows})!=len(plan):raise ValueError('SIMT 配置覆盖不完整')
            for r in rows:
                if [r[k] for k in ('impl','op','elements','threads','steps','vf_calls')]!=plan[r['id']]:
                    raise ValueError('SIMT 输出参数与 plan 不符')
                if plan[r['id']]!=simt_plan.get(r['id']):raise ValueError('SIMT 配置与此次矩阵不符')
                raw=r['raw_ticks']
                if r['correctness'] is not True or r['soc']!=profile['soc'] or len(raw)!=15 or any(int(t)<=0 for t in raw):
                    raise ValueError('SIMT 正确性/样本无效')
                key=('simt',round_,r['id'])
                if key in seen:raise ValueError('SIMT 配置/轮次重复')
                seen.add(key)
                values=np.array([int(t)*1e6/profile['clock_hz'] for t in raw])
                result['simt'].append(dict(id=f's-r{round_}-{r["id"]}',round=round_,impl=r['impl'],op=r['op'],
                    dtype='float32',elements=r['elements'],threads=r['threads'],threadsApplicable=r['impl'] in (1,3),steps=r['steps'],vf_calls=r['vf_calls'],
                    actualSimtVfCalls=1 if r['impl']==1 else r['vf_calls'] if r['impl']==3 else 0,
                    p50=float(np.percentile(values,50)),p95=float(np.percentile(values,95)),rawTicks=raw,
                    maxAbsError=r['max_abs_error'],correctness=True,manifestHash=sha(manifest_path),executableHash=m['executable_sha256']))
        else: continue
        result['evidence']['manifests'].append(dict(run=folder.name,sha256=sha(manifest_path)))
    counts={kind:{round_:sum(r['round']==round_ for r in result[kind]) for round_ in (1,2)} for kind in ('alignment','alignmentPaired','simt')}
    if not a.allow_partial and counts!={'alignment':{1:1496,2:1496},'alignmentPaired':{1:60,2:60},'simt':{1:764,2:764}}:
        raise ValueError(f'正式数据要求完整两轮，当前 {counts}')
    result['evidence']['coverage']=counts
    repeatability={}
    for kind in counts:
        groups={}
        for r in result[kind]:
            key=tuple(r.get(k) for k in (('dtype','direction','api','windows','gmOffset','elements') if kind.startswith('alignment') else ('impl','op','elements','threads','steps','vf_calls')))
            groups.setdefault(key,{})[r['round']]=r['p50']
        differences=[abs(v[2]/v[1]-1)*100 for v in groups.values() if len(v)==2]
        if differences:repeatability[kind]=dict(pairedConfigs=len(differences),medianRelativePct=float(np.median(differences)),maxRelativePct=float(max(differences)))
    result['evidence']['repeatability']=repeatability
    result['measuredDate']=' / '.join(sorted(dates)) or 'unknown'
    result['evidence']['receiverValidation']='passed' if not a.allow_partial else 'partial; local preview only'
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':'),allow_nan=False))
    print(json.dumps(counts),a.output.stat().st_size,'bytes')


if __name__=='__main__':main()
