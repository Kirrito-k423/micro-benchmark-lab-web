"""Fixed AIV/tile/batch sweep; requested, allocated and touched GM are distinct."""
import math
TILE=32768
BATCH=2
SCOPES={'read':(0,0),'write':(1,0),'shared':(0,1)}
def sizes(env):
    mib=1<<20
    # Predeclared dense grid around the device's recorded L2 capacity.
    center=env['l2_bytes']//mib
    dense=range(max(8,center-64),center+65,8)
    common=sorted(set([8,16,24,32,48,*dense,208,224,240,256,320,384,512,768,1024,1536,2048]))
    common=[x*mib for x in common if x<=2048]
    return sorted(set([1<<17,1<<18,1<<19,1<<20,2<<20,4<<20,*common]))
def cases(env,scope,smoke=False):
    n=env['aiv_count'];unit=2*TILE*BATCH
    if unit+32768+32>env['ub_bytes']:raise ValueError('Insufficient UB for the fixed preset')
    direction,shared=SCOPES[scope];rows=[];used=set()
    for index,requested in enumerate(sizes(env)):
        per=math.ceil((requested if shared else math.ceil(requested/n))/unit)*unit
        ring=per*(1 if shared else n)
        if not shared and requested<unit*n:continue
        if ring in used:continue
        used.add(ring)
        # Shared reads must actually visit the entire shared ring at least twice.
        target=max(4<<30,2*n*per) if shared else 4<<30
        rows.append((list(SCOPES).index(scope)*1000+index,direction,shared,n,TILE,BATCH,requested,target,0))
    if smoke:
        rows=[rows[0],rows[-1]] if scope=='read' else [rows[0]]
    return rows
