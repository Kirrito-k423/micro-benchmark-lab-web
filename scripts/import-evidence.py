"""PROTOTYPE: import validated public A3 CSV / locally verified A5 bundles.

python3 scripts/import-evidence.py --a3 points.csv --a5 /path/to/a5-web-20260925
Run AKL datacopy_report.analyse(..., render_figures=False) on each A5 run first.
Only allowlisted measurement fields are published; machine logs stay outside Git.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('--a3', type=Path, required=True)
p.add_argument('--a5', type=Path, required=True)
a = p.parse_args()
rows = []
source_a3 = 'https://github.com/Kirrito-k423/ascend-kernel-lab/blob/468a2a147f681d933cb1f78c8d594c31ad258898/reports/datacopy-a3-capacity/points.csv'
source_a5 = 'https://github.com/Kirrito-k423/ascend-kernel-lab/pull/33#issuecomment-5826300302'

def add(device, run, case, ticks, hz, p50, p95, ws, manifest_hash):
    mode = 'ring' if 'ring' in run else 'small'
    rows.append(dict(id=f'{device}/{run}/{case["name"]}', device=device, run=run,
        mode=mode, windows=case.get('windows', 1), batch=case['batch'],
        loops=case['loops'], bytes=case['block_bytes']*case['blocks'],
        direction=case['direction'], api=case['api'], dtype=case['dtype'],
        p50=p50, p95=p95, gbps=case['block_bytes']*case['blocks']/p50/1000,
        workingSet=ws, rawTicks=[str(t) for t in ticks], clockHz=hz,
        manifestHash=manifest_hash, case=case, correctness='validated'))

with a.a3.open() as f:
    for r in csv.DictReader(f):
        add('A3',r['run'],json.loads(r['case_json']),json.loads(r['raw_total_ticks']),
            50_000_000,float(r['p50_us']),float(r['p95_us']),int(r['working_set_bytes']),None)

run_evidence=[]
for path in sorted(a.a5.glob('a5-datacopy*/**/manifest.json')):
    m=json.loads(path.read_text())
    assert m['status']=='validated'
    hz=m['profile']['clock_hz']
    summaries={r['name']:r for r in json.loads((path.parent/'summary.json').read_text())}
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    run_evidence.append(dict(run=path.parent.name, manifestSha256=digest,
        librarySha256=m['build']['library_sha256'], sourceSha256=m['source_sha256'],
        cases=len(m['cases']),launches=sum(c['launches'] for c in m['cases']),
        observedIdleBefore=m['occupancy_before']['observed_idle'],
        observedIdleAfter=m['occupancy_after']['observed_idle']))
    for record in m['cases']:
        c=record['case']; s=summaries[c['name']]
        samples=json.loads((path.parent/c['name']/'samples.json').read_text())
        assert all(x['correctness'] for x in samples)
        ticks=[x['ticks'] for x in samples if x['trace'] and not x['warmup']]
        assert len(ticks)==20
        add('A5',path.parent.name,c,ticks,hz,s['p50_us_per_call'],s['p95_us_per_call'],s['working_set_bytes'],digest)

assert len(rows)==1900
data=dict(schema='akl.web.prototype.v1', rows=rows, sources={'A3':source_a3,'A5':source_a5},
    environments={
      'A3':dict(soc='Ascend910_9382',cann='9.1.0-beta.1',arch='dav-2201',clockHz=50_000_000,ubBytes=196608,aiv=1,date='2026-09-24',topology='A3 · 单设备 · local GM'),
      'A5':dict(soc='Ascend950DT_9582',cann='9.2.0',arch='dav-3510',clockHz=1_000_000_000,ubBytes=221184,aiv=1,date='2026-09-25',topology='A5 PoD · 单设备 · local GM')},
    provenance=dict(a3CsvSha256=hashlib.sha256(a.a3.read_bytes()).hexdigest(),a5Runs=run_evidence,
      a5Bundles=[dict(name=p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(a.a5.glob('*.zip')) if '.part' not in p.name]),
    scope='单 AIV / uint32 / DataCopy(params)；有效 payload 吞吐，不等同于整卡 HBM 峰值。每个点是一次配置轮次的 20 个计时样本。')
out=Path(__file__).resolve().parents[1]/'public/data/datacopy.json'
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')))
print(f'{len(rows)} rows, {sum(len(r["rawTicks"]) for r in rows)} samples, {out.stat().st_size} bytes')
