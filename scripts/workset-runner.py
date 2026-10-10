"""Run one fixed-buffer workset curve using the existing AKL bandwidth executable."""
import argparse,csv,hashlib,importlib.util,json,random,re,subprocess
from pathlib import Path
from datetime import datetime,timezone
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
def idle(folder,label):
    r=subprocess.run(['npu-smi','info'],capture_output=True,text=True,timeout=20)
    p=folder/f'occupancy-{label}.txt';p.write_text(r.stdout+r.stderr)
    if r.returncode or 'No running processes found' not in p.read_text() or re.search(r'^\|\s*\d+\s*\|\s*\d+\s*\|',p.read_text(),re.M):raise RuntimeError('NPU busy or occupancy unavailable')
    return dict(observed_idle=True,sha256=sha(p))
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('.'));p.add_argument('--device',type=int,default=1)
    p.add_argument('--scope',choices=['read','write','shared'],required=True);p.add_argument('--round',type=int,choices=[1,2],required=True)
    p.add_argument('--smoke',action='store_true');p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.root=a.root.resolve();a.output.mkdir(parents=True,exist_ok=False)
    env=json.loads((a.root/'results/setup/environment.json').read_text());profile=json.loads((a.root/'results/setup/profile.json').read_text())
    binary=a.root/'build-bandwidth/akl_bandwidth';build=json.loads(binary.with_suffix('.build.json').read_text())
    if sha(binary)!=build['executable_sha256']:raise ValueError('Binary receipt mismatch')
    for name,h in build['source_sha256'].items():
        if sha(a.root/name)!=h:raise ValueError('Core source changed')
    planner=Path(__file__).with_name('workset-plan.py');spec=importlib.util.spec_from_file_location('plan',planner);plan=importlib.util.module_from_spec(spec);spec.loader.exec_module(plan)
    rows=plan.cases(env,a.scope,a.smoke);seed=2026101000+a.round;random.Random(seed).shuffle(rows)
    def allocated(r):
        _,direction,shared,n,tile,batch,ring,_,_=r;unit=2*tile*batch
        per=((ring if shared else (ring+n-1)//n)+unit-1)//unit*unit
        return per*(1 if shared else n)
    with (a.output/'plan.csv').open('w') as f:csv.writer(f).writerows(rows)
    count,warm=(3,1) if a.smoke else (12,2)
    m=dict(schema='akl.workset.mbench.v1',status='incomplete',scope=a.scope,round=a.round,smoke=a.smoke,environment=env,clock_profile=profile,build=build,
        runner_sha256=sha(Path(__file__)),planner_sha256=sha(planner),plan_sha256=sha(a.output/'plan.csv'),seed=seed,samples=count,warmup=warm,
        fixed_buffers=True,max_allocated_input_bytes=max(map(allocated,rows)),started_utc=datetime.now(timezone.utc).isoformat())
    save(a.output/'manifest.json',m)
    try:
        m['occupancy_before']=idle(a.output,'before');save(a.output/'manifest.json',m)
        with (a.output/'stdout.log').open('w') as out,(a.output/'stderr.log').open('w') as err:
            subprocess.run([str(binary),str(a.device),str(a.output/'plan.csv'),str(warm),str(count),str(a.output/'samples.jsonl'),str(env['ub_bytes'])],stdout=out,stderr=err,check=True,timeout=240)
        m['occupancy_after']=idle(a.output,'after');m.update(status='validated',samples_sha256=sha(a.output/'samples.jsonl'))
    except BaseException as e:m.update(status='failed',error=str(e));raise
    finally:m['ended_utc']=datetime.now(timezone.utc).isoformat();save(a.output/'manifest.json',m)
if __name__=='__main__':main()
