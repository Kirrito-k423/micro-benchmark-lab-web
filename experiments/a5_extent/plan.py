"""Freeze the 18-point single-AIV logical-transfer scan, with independent rounds."""
import json, random
from pathlib import Path

def make_plan():
    cases=[]
    for api in range(3):
        for direction in range(2):
            for windows in [1,2]:
                for exponent in range(5,23):
                    total=1<<exponent
                    tile=min(total,32768 if api==2 else 65536)
                    cases.append([len(cases),api,direction,total,tile,windows,max(4,min(8192,(16<<20)//total))])
    assert len(cases)==216 and len({c[3] for c in cases})==18
    stages=[]
    smoke=[c for c in cases if c[3] in [32,4<<20] and c[5]==2]
    for policy in ['normal','huge-first']:
        stages.append(dict(key='smoke-'+policy,round=0,policy=policy,seed=202610110,
            cases=smoke,warmup=1,samples=2))
    for round in [1,2]:
        shuffled=cases[:];random.Random(202610110+round).shuffle(shuffled)
        for offset in range(0,len(shuffled),18):
            policies=['normal','huge-first'] if (offset//18+round)%2 else ['huge-first','normal']
            for policy in policies:
                stages.append(dict(key=f'r{round}-{policy}-{offset//18:02d}',round=round,policy=policy,
                    seed=202610120+round*100+offset,cases=shuffled[offset:offset+18],warmup=2,samples=12))
    return dict(schema='akl.extent.plan.v1',expectedSoc='Ascend950DT_9582',ubBytes=221184,
        npuArch='dav-3510',clockHz=1000000000,
        clockSource='CANN GetSystemCycle: Ascend950PR/950DT SYS_CNT 1 GHz',stages=stages,
        counts=dict(configurations=216,configurationRounds=864,timedSamples=10368,traceOffSamples=10368))

if __name__=='__main__':
    Path('execution-plan.json').write_text(json.dumps(make_plan(),indent=2)+'\n')
