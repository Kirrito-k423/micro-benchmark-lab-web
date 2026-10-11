"""Frozen single-request latency and paired independent read/write experiments."""
import json,random
from pathlib import Path

def make_plan():
    latency=[]
    for api in range(3):
        for direction in range(2):
            for windows in [1,2]:
                for exponent in range(5,23):
                    size=1<<exponent;tile=min(size,32768 if api==2 else 65536)
                    latency.append([len(latency),api,direction,size,tile,windows,1])
    control=sorted({(c[2],c[3],c[4],c[5]) for c in latency if c[3] in [32,65536,4194304]})
    for direction,size,tile,windows in control:
        latency.append([len(latency),3,direction,size,tile,windows,1])
    shapes=[]
    for cores in [1,16,64]:
        for ring in [0,128<<20,2<<30]:
            for tile in [4096,32768]:
                shapes.append([len(shapes),cores,tile,ring or cores*2*tile,4<<30])
    stages=[]
    smoke_latency=[c for c in latency if c[3] in [32,4<<20] and c[5]==2]
    smoke_duplex=[s for s in shapes if (s[1],s[2],s[3]) in [(1,32768,65536),(1,32768,128<<20),(64,4096,64*8192)]]
    for policy in ['normal','huge-first']:
        for kind,cases in [('latency',smoke_latency),('duplex',smoke_duplex)]:
            stages.append(dict(key=f'smoke-{kind}-{policy}-v1',kind=kind,round=0,policy=policy,
                cases=cases,seed=202610111,warmup=1,samples=2))
    for round in [1,2]:
        shuffled=latency[:];random.Random(202610111+round).shuffle(shuffled)
        for offset in range(0,len(shuffled),18):
            policies=['normal','huge-first'] if (offset//18+round)%2 else ['huge-first','normal']
            for policy in policies:
                stages.append(dict(key=f'latency-r{round}-{policy}-{offset//18:02d}-v1',kind='latency',round=round,
                    policy=policy,cases=shuffled[offset:offset+18],seed=202610200+round*100+offset,warmup=2,samples=12))
    for round in [1,2]:
        shuffled=shapes[:];random.Random(202610311+round).shuffle(shuffled)
        for offset,shape in enumerate(shuffled):
            policies=['normal','huge-first'] if (offset+round)%2 else ['huge-first','normal']
            for policy in policies:
                stages.append(dict(key=f'duplex-r{round}-{policy}-{offset:02d}-v1',kind='duplex',round=round,
                    policy=policy,cases=[shape],seed=202610400+round*100+offset,warmup=2,samples=12))
    return dict(schema='akl.latency-duplex.plan.v1',expectedSoc='Ascend950DT_9582',availableAiv=64,
        ubBytes=221184,npuArch='dav-3510',clockHz=1000000000,
        clockSource='CANN 9.1 GetSystemCycle: Ascend950PR/950DT SYS_CNT 1 GHz; matched prior validated profile',
        stages=stages,counts=dict(latencyPrimaryRounds=864,latencyControlRounds=len(control)*4,
            duplexPrimaryRounds=len(shapes)*3*4,duplexControlRounds=len(shapes)*4,
            configurationRounds=(len(latency)+len(shapes)*4)*4,
            timedSamples=(len(latency)+len(shapes)*4)*4*12,traceOffSamples=(len(latency)+len(shapes)*4)*4*12))
if __name__=='__main__':Path('execution-plan.json').write_text(json.dumps(make_plan(),indent=2)+'\n')
