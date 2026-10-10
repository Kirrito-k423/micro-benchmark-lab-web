"""Freeze retest coverage, 32 B power-of-two shapes and independent round order."""
import argparse,json,random,sys
from pathlib import Path
from dataclasses import asdict
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'python'))
from akl.datacopy import CopyCase,APIS

def create(web,ub,aiv):
    singles=[];skipped=[]
    for direction in ['GM_UB','UB_GM']:
      for api in APIS:
       for windows in [1,2]:
        for batch in [1,8]:
         for mode in ['small','ring']:
          n=32
          while n<=ub:
            slots=batch*windows if mode=='small' else max(batch*windows,min(65536,64*1024*1024//n)//batch*batch)
            loops=max(windows,slots//batch,min(8192,max(256,16*1024*1024//(n*batch))))
            c=CopyCase(f'p2_{direction}_{api}_n{n}_b{batch}_w{windows}_{mode}',direction=direction,api=api,block_bytes=n,batch=batch,windows=windows,slots=slots,loops=loops)
            try:
                c.params()
                if c.layout()['ub_working_set_bytes']+320>ub:raise ValueError('actual UB limit')
                singles.append(asdict(c))
            except ValueError as e:skipped.append({'case':asdict(c),'reason':str(e)})
            n*=2
    old=json.loads((web/'public/data/datacopy.json').read_text());capacity={}
    for r in old['rows']:
        if r['device']=='A5':capacity[json.dumps({k:v for k,v in r['case'].items() if k!='name'},sort_keys=True)]=r['case']
    align=json.loads((web/'public/data/a5-mbench.json').read_text());alignment=[];seen=set()
    for r in align['alignment']:
        if r['round']!=1:continue
        name=r['id'].removeprefix('alignment-r1-');c=CopyCase(name,direction=r['direction'],api=r['api'],dtype=r['dtype'],block_bytes=r['payload'],gm_offset_bytes=r['gmOffset'],loops=r['loops'],batch=r['batch'],slots=r['slots'],windows=r['windows']);c.params();alignment.append(asdict(c))
    paired=[]
    for r in align['alignmentPaired']:
        if r['round']!=1:continue
        c=CopyCase('paired_'+r['id'],direction=r['direction'],api=r['api'],dtype=r['dtype'],block_bytes=r['payload'],gm_offset_bytes=r['gmOffset'],loops=r['loops'],batch=r['batch'],slots=r['slots'],windows=r['windows']);c.params();paired.append(asdict(c))
    stages=[]
    for kind,cases,policies,chunk in [('power2',singles,['normal','huge-first'],48),('capacity',[c|{'name':'capacity_'+str(i)+'_'+c['name']} for i,c in enumerate(capacity.values())],['huge-first'],32),('alignment',alignment,['huge-first'],96),('alignment-paired',paired,['huge-first'],60)]:
      for rd in [1,2]:
        shuffled=cases.copy();rng=random.Random(20261030+rd);rng.shuffle(shuffled)
        for start in range(0,len(shuffled),chunk):
            ps=policies.copy();rng.shuffle(ps)
            for policy in ps:stages.append({'kind':kind,'round':rd,'policy':policy,'key':f'{kind}-r{rd}-{policy}-c{start//chunk:03}','cases':shuffled[start:start+chunk],'warmup':2,'samples':12,'reuse':kind=='alignment-paired','minDataAllocation':2<<20})
    for kind,name in [('bandwidth','a5-bandwidth'),('workset','a5-workset'),('tail','a5-store-tail')]:
      d=json.loads((web/'public/data'/f'{name}.json').read_text());groups={}
      for r in d['rows']:
        if r['round']!=1 or r.get('phase','formal')!='formal' or kind=='tail' and r['mode']!='windowed':continue
        # 空对照没有有效搬运字节；工作量仍由旧记录的 groups 决定。
        target=r.get('targetBytes',r['groups']*r['cores']*r['tileBytes']*r['batch'])
        row=[int(r['caseId']),int(r['direction']=='UB_GM'),int(r['sharedRead']),r['cores'],r['tileBytes'],r['batch'],r['requestedRing'],target,int(r.get('control',False))]
        assert row[3]<=aiv
        assert target>=r['requestedRing'] and target>0
        key=r['scope'] if kind=='workset' else str((row[1],row[2],row[4],row[5],row[6],row[8]))
        groups.setdefault(key,[]).append(row)
      for rd in [1,2]:
        rng=random.Random(20261040+rd);gs=list(groups.values());rng.shuffle(gs)
        for i,rows in enumerate(gs):
            rows=rows.copy();rng.shuffle(rows)
            key=f'{kind}-r{rd}-huge-first-c{i:03}'+('-control' if any(r[8] for r in rows) else '')
            stages.append({'kind':kind,'round':rd,'policy':'huge-first','key':key,'plan':rows,'warmup':2,'samples':12,'reuse':True})
    return dict(schema='akl.page-retest.plan.v1',ubBytes=ub,availableAiv=aiv,stages=stages,skipped=skipped,counts={k:sum(len(x.get('cases',x.get('plan',[])))*(2 if k=='tail' else 1) for x in stages if x['kind']==k) for k in {x['kind'] for x in stages}})
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--web-root',type=Path,required=True);p.add_argument('--ub-bytes',type=int,required=True);p.add_argument('--aiv-count',type=int,required=True);p.add_argument('--clock-hz',type=int,required=True);p.add_argument('--clock-source',required=True);p.add_argument('--soc',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();d=create(a.web_root,a.ub_bytes,a.aiv_count);d.update(clockHz=a.clock_hz,clockSource=a.clock_source,expectedSoc=a.soc);a.output.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'counts':d['counts'],'tasks':len(d['stages']),'skipped':len(d['skipped'])}))
