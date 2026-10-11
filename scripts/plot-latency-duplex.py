"""Export figures from accepted data. Run with the project's cached matplotlib."""
import json, statistics
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
WEB=Path(__file__).resolve().parents[1]
db=json.loads((WEB/'public/data/a5-latency-duplex.json').read_text());assert db['evidence']['receiverValidation']=='passed'
rows=db['rows'];out=WEB/'public/figures';out.mkdir(exist_ok=True)
def time(**filters):
    rs=[r for r in rows if not r['control'] and all(r[k]==v for k,v in filters.items())]
    assert len(rs)==2 and {r['round'] for r in rs}=={1,2}
    return statistics.median(r['p50'] for r in rs)
colors={'normal':'#e77d42','huge-first':'#16756b'}
fig,axes=plt.subplots(2,3,figsize=(12,8),constrained_layout=True)
sizes=[1<<i for i in range(5,23)]
for col,api in enumerate(['DataCopy_count','DataCopy_params','DataCopyPad_params']):
    for line,direction in enumerate(['GM_UB','UB_GM']):
        ax=axes[line,col]
        for policy in ['normal','huge-first']:
            ax.plot(sizes,[time(kind='latency',api=api,direction=direction,bytes=n,windows=2,allocation=policy) for n in sizes],
                marker='.',label=policy,color=colors[policy])
        ax.set_xscale('log',base=2);ax.set_yscale('log');ax.grid(alpha=.2)
        ax.set_xticks([32,1024,32768,2**20,4*2**20],['32 B','1 KiB','32 KiB','1 MiB','4 MiB'])
        ax.set_title(f'{api}\n{direction.replace("_"," → ")} · 2 UB windows');ax.set_xlabel('Complete request bytes');ax.set_ylabel('One-request completion p50 (µs)');ax.legend(fontsize=8)
fig.suptitle('A5 single-request DataCopy latency · two rounds · CANN 9.1.0')
fig.savefig(out/'a5-latency-20261011.svg');plt.close(fig)
fig,axes=plt.subplots(1,3,figsize=(12,4.2),constrained_layout=True)
for ax,ring in zip(axes,[64*2*32768,128*2**20,2**31]):
    for policy in ['normal','huge-first']:
        for mode,style in [('read','--'),('write',':'),('duplex','-')]:
            values=[]
            for cores in [1,16,64]:
                requested=cores*2*32768 if ring==64*2*32768 else ring
                t=time(kind='duplex',mode=mode,cores=cores,tileBytes=32768,requestedWorkingSet=requested,allocation=policy)
                values.append((8 if mode=='duplex' else 4)*2**30/t/1e6)
            ax.plot([1,16,64],values,style,marker='.',color=colors[policy],label=f'{policy} / {mode}')
    ax.set_title('2 tiles/core' if ring==64*2*32768 else f'{ring/2**20:g} MiB per direction')
    ax.set_xticks([1,16,64]);ax.set_xlabel('AIV cores');ax.set_ylabel('Effective total TB/s');ax.grid(alpha=.2);ax.legend(fontsize=7)
fig.suptitle('Independent read/write · 32 KiB tile · complete trace-off common ACL time')
fig.savefig(out/'a5-duplex-20261011.svg');plt.close(fig)
print('FIGURES_SAVED')
