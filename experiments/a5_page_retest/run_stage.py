"""Execute one predeclared short stage; never overwrite output or replay unknown work."""
import argparse,json,csv,subprocess,sys,hashlib,re,shutil
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--key',required=True);p.add_argument('--device',type=int,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--plan',type=Path,default=Path('execution-plan.json'));a=p.parse_args()
plan=json.loads(a.plan.read_text());stage=next(s for s in plan['stages'] if s['key']==a.key);a.output.mkdir(parents=True,exist_ok=False)
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
build=json.loads((ROOT/'setup/build.json').read_text())
for name,h in (build['sources']|build['binaries']).items():assert sha(ROOT/name)==h,'Stale source/binary '+name
meta=dict(schema='akl.page-retest.stage.v1',status='incomplete',stage=stage,build=build,planSha256=sha(a.plan),startedUtc=datetime.now(timezone.utc).isoformat(),outputFiles={})
def save(): (a.output/'receipt.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2))
def idle(label):
 r=subprocess.run(['npu-smi','info'],capture_output=True,text=True,timeout=20);s=r.stdout+r.stderr;f=a.output/(label+'.txt');f.write_text(s)
 assert r.returncode==0 and 'No running processes found' in s and not re.search(r'^\|\s*\d+\s*\|\s*\d+\s*\|',s,re.M),'NPU occupied'
 return sha(f)
save()
try:
 meta['before']=idle('container-before')
 if 'cases' in stage:
  f=a.output/'cases.json';f.write_text(json.dumps(stage['cases'],indent=2));cmd=[sys.executable,str(ROOT/'scripts/run_datacopy.py'),'--profile',str(ROOT/'setup/profile.json'),'--library',str(ROOT/'build-a5/libakl_datacopy.so'),'--cases',str(f),'--device',str(a.device),'--data-allocation',stage['policy'],'--min-data-allocation',str(stage['minDataAllocation']),'--warmup',str(stage['warmup']),'--samples',str(stage['samples']),'--seed',str(20261050+stage['round']),'--output',str(a.output/'run')]
  if stage['reuse']:cmd+=['--reuse-buffers']
 else:
  f=a.output/'plan.csv'
  with f.open('w') as stream:csv.writer(stream).writerows(stage['plan'])
  cmd=[str(ROOT/('build-tail' if stage['kind']=='tail' else 'build-bandwidth')/'measure'),str(a.device),str(f),str(stage['warmup']),str(stage['samples']),str(a.output/'samples.jsonl'),str(build['environment']['ub_bytes'])]
  if stage['kind']=='tail':cmd+=[str(20261060+stage['round'])]
 meta['command']=cmd;save();subprocess.run(cmd,check=True,timeout=420)
 meta['after']=idle('container-after');meta['outputFiles']={str(p.relative_to(a.output)):sha(p) for p in a.output.rglob('*') if p.is_file() and p.name!='receipt.json'};meta['status']='validated'
except BaseException as e:meta.update(status='failed',error=str(e));raise
finally:meta['endedUtc']=datetime.now(timezone.utc).isoformat();save()
