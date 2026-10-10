"""Run a frozen short batch; save occupancy, hashes, all samples, and failed evidence."""
import argparse,csv,hashlib,json,re,subprocess
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--key',required=True);p.add_argument('--device',type=int,required=True)
p.add_argument('--output',type=Path,required=True);a=p.parse_args()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
plan=json.loads((ROOT/'execution-plan.json').read_text());stage=next(s for s in plan['stages'] if s['key']==a.key)
build=json.loads((ROOT/'setup/build.json').read_text())
for name,h in (build['sources']|build['binaries']).items():assert sha(ROOT/name)==h,'Source/binary mismatch '+name
a.output.mkdir(parents=True,exist_ok=False)
receipt=dict(schema='akl.extent.stage.v1',status='incomplete',stage=stage,build=build,
    planSha256=sha(ROOT/'execution-plan.json'),startedUtc=datetime.now(timezone.utc).isoformat())
def save(): (a.output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
def idle(label):
    r=subprocess.run(['npu-smi','info'],capture_output=True,text=True,timeout=20)
    s=r.stdout+r.stderr;(a.output/(label+'.txt')).write_text(s)
    assert r.returncode==0 and 'No running processes found' in s and not re.search(r'^\|\s*\d+\s*\|\s*\d+\s*\|',s,re.M),'NPU occupied'
save()
try:
    idle('container-before')
    with (a.output/'plan.csv').open('w') as f:csv.writer(f).writerows(stage['cases'])
    cmd=[str(ROOT/'build/measure'),str(a.device),str(a.output/'plan.csv'),stage['policy'],str(stage['warmup']),
        str(stage['samples']),str(stage['seed']),str(a.output/'samples.jsonl'),str(plan['ubBytes'])]
    receipt['command']=cmd;save();subprocess.run(cmd,check=True,timeout=420)
    idle('container-after')
    rows=[json.loads(x) for x in (a.output/'samples.jsonl').read_text().splitlines()]
    assert len(rows)==len(stage['cases']) and all(r['correctness'] and r['full_read_oracle'] for r in rows)
    receipt['outputFiles']={str(p.relative_to(a.output)):sha(p) for p in a.output.iterdir() if p.is_file() and p.name!='receipt.json'}
    receipt['status']='validated'
except BaseException as e:receipt.update(status='failed',error=str(e));raise
finally:receipt['endedUtc']=datetime.now(timezone.utc).isoformat();save()
