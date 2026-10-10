"""Describe a measured decline with brackets; do not fit or invent a discontinuity."""
import statistics
HIGH_MIB=[8,16,24,32]
LOW_MIB=[512,768,1024,1536,2048]
def summarize(rows):
    groups={}
    for r in rows:
        if r['phase']=='formal':groups.setdefault(r['caseId'],[]).append(r)
    points=[]
    for rs in groups.values():
        us=statistics.median(r['p50Us'] for r in rs)
        points.append(rs[0]|dict(p50Us=us,gbps=rs[0]['movedBytes']/us/1000,members=sorted(rs,key=lambda r:r['round'])))
    return sorted(points,key=lambda r:r['coveredGmBytes'])
def bracket(points,threshold):
    for i in range(1,len(points)-1):
        if points[i]['gbps']<=threshold and points[i+1]['gbps']<=threshold:
            previous=[p for p in points[:i] if p['gbps']>threshold]
            if previous:return dict(lowerBytes=previous[-1]['coveredGmBytes'],upperBytes=points[i]['coveredGmBytes'])
    return None
def analyse(rows):
    all_points=summarize(rows);curves=[]
    for scope in ['read','write','shared']:
        points=[p for p in all_points if p['scope']==scope]
        if not points:continue
        high=statistics.median(p['gbps'] for p in points if p['coveredGmBytes']/(1<<20) in HIGH_MIB)
        low=statistics.median(p['gbps'] for p in points if p['coveredGmBytes']/(1<<20) in LOW_MIB)
        contrast=(high-low)/high;crossings={};rounds=[]
        for rd in [1,2]:
            ps=[r|dict(gbps=r['movedBytes']/r['p50Us']/1000) for r in rows if r['phase']=='formal' and r['scope']==scope and r['round']==rd];ps.sort(key=lambda p:p['coveredGmBytes'])
            h=statistics.median(p['gbps'] for p in ps if p['coveredGmBytes']/(1<<20) in HIGH_MIB);l=statistics.median(p['gbps'] for p in ps if p['coveredGmBytes']/(1<<20) in LOW_MIB)
            rounds.append(dict(round=rd,highGbps=h,lowGbps=l,contrast=(h-l)/h,crossings={str(int(f*100)):bracket(ps,h-f*(h-l)) for f in [.1,.5,.9]} if (h-l)/h>=.2 else {}))
        significant=contrast>=.2 and all(r['contrast']>=.2 for r in rounds)
        if significant:
            for f in ['10','50','90']:
                bs=[r['crossings'].get(f) for r in rounds]
                crossings[f]=dict(lowerBytes=min(b['lowerBytes'] for b in bs),upperBytes=max(b['upperBytes'] for b in bs)) if all(bs) else None
        pairs=[dict(lowerBytes=a['coveredGmBytes'],upperBytes=b['coveredGmBytes'],beforeGbps=a['gbps'],afterGbps=b['gbps'],relativeDropPct=(a['gbps']-b['gbps'])/a['gbps']*100) for a,b in zip(points,points[1:])]
        largest=max(pairs,key=lambda p:p['relativeDropPct'])
        repeats=[abs(p['members'][0]['p50Us']-p['members'][1]['p50Us'])/statistics.mean(r['p50Us'] for r in p['members'])*100 for p in points]
        # Endpoint view answers the user's stated 128 KiB / 2 GiB comparison.
        # Keep the predeclared plateau analysis above, even when 8–32 MiB is
        # already in the shared-read decline; never replace its reference silently.
        endpoint_rounds=[]
        for rd in [1,2]:
            ps=sorted([r|dict(gbps=r['movedBytes']/r['p50Us']/1000) for r in rows if r['phase']=='formal' and r['scope']==scope and r['round']==rd],key=lambda p:p['coveredGmBytes'])
            h,l=ps[0]['gbps'],ps[-1]['gbps']
            endpoint_rounds.append(dict(round=rd,highGbps=h,lowGbps=l,crossings={str(int(f*100)):bracket(ps,h-f*(h-l)) for f in [.1,.5,.9]}))
        endpoint_crossings={}
        for f in ['10','50','90']:
            bs=[r['crossings'][f] for r in endpoint_rounds]
            endpoint_crossings[f]=dict(lowerBytes=min(b['lowerBytes'] for b in bs),upperBytes=max(b['upperBytes'] for b in bs)) if all(bs) else None
        endpoint=dict(highBytes=points[0]['coveredGmBytes'],lowBytes=points[-1]['coveredGmBytes'],highGbps=points[0]['gbps'],lowGbps=points[-1]['gbps'],crossings=endpoint_crossings,roundEvidence=endpoint_rounds,method='Descriptive endpoint comparison added after the sweep; distinct from the predeclared plateau reference.')
        curves.append(dict(scope=scope,points=len(points),highGbps=high,lowGbps=low,contrast=contrast,significantDecline=significant,crossings=crossings,roundEvidence=rounds,endpointDecline=endpoint,largestAdjacentDrop=largest,repeatability=dict(medianRelativePct=statistics.median(repeats),maxRelativePct=max(repeats))))
    return dict(method='Reference plateaus at predeclared sizes; crossings require two consecutive measured points below threshold, reported as the union of two-round brackets; no interpolation.',highReferenceMiB=HIGH_MIB,lowReferenceMiB=LOW_MIB,minimumContrast=.2,curves=curves)
