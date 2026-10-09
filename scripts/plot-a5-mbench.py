#!/usr/bin/env python3
"""从已校验完整数据导出 PNG/SVG，保留实际轮间范围，不拟合曲线。"""
import argparse,json,statistics
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

p=argparse.ArgumentParser();p.add_argument('--data',type=Path,default=Path('public/data/a5-mbench.json'));p.add_argument('--output',type=Path,default=Path('public/figures'));a=p.parse_args()
d=json.loads(a.data.read_text())
if d['evidence']['receiverValidation']!='passed':raise ValueError('静态报告只接受完整校验数据')
def aggregate(rows,key):
    groups={}
    for r in rows:groups.setdefault(key(r),[]).append(r)
    return [dict(rs[0],p50=statistics.median(r['p50'] for r in rs),low=min(r['p50'] for r in rs),high=max(r['p50'] for r in rs)) for rs in groups.values()]
alignment=aggregate(d['alignment'],lambda r:(r['dtype'],r['direction'],r['api'],r['windows'],r['gmOffset'],r['elements']))
paired=aggregate(d['alignmentPaired'],lambda r:(r['dtype'],r['direction'],r['api'],r['windows'],r['gmOffset'],r['elements']))
simt=aggregate(d['simt'],lambda r:(r['impl'],r['op'],r['elements'],r['threads'],r['steps'],r['vf_calls']))
plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'figure.facecolor':'white','axes.grid':True,'grid.alpha':.2})
title=f"{d['environment']['soc']} | {d['environment']['cann']} | 1 AIV | {d['measuredDate']}"
a.output.mkdir(parents=True,exist_ok=True)
def export(fig,name,footnote):
    fig.suptitle(title,fontsize=12)
    fig.text(.02,.01,footnote,fontsize=8,color='#4e6159')
    fig.tight_layout(rect=(0,.06,1,.95))
    fig.savefig(a.output/(name+'.png'),dpi=180);fig.savefig(a.output/(name+'.svg'));plt.close(fig)
for dataset,name in ((paired,'a5-alignment'),(alignment,'a5-alignment-sweep')):
    fig,axes=plt.subplots(2,2,figsize=(12,7))
    for i,direction in enumerate(('GM_UB','UB_GM')):
        for j,dtype in enumerate(('uint8','float32')):
            ax=axes[i,j]
            for api,color,style in (('DataCopyPad_params','#15756c','-'),('DataCopy_params','#e47c44','--')):
                rows=sorted([r for r in dataset if r['dtype']==dtype and r['direction']==direction and r['windows']==1 and r['gmOffset']==0 and r['api']==api],key=lambda r:r['elements'])
                if not rows:continue
                ax.plot([r['elements'] for r in rows],[r['p50'] for r in rows],style,color=color,marker='.',markersize=3,linewidth=1,label=api)
                if api=='DataCopyPad_params':ax.fill_between([r['elements'] for r in rows],[r['low'] for r in rows],[r['high'] for r in rows],alpha=.12,color=color,label='Range of round medians')
            ax.set(title=f'{direction} / {dtype}',xlabel='Elements (127-257)',ylabel='Completion time per call (us)',xlim=(127,257));ax.legend(fontsize=8)
    export(fig,name,'Same API, aligned GM origin, 1 window, 8192 loops. Two-round median; shaded range is not a confidence interval. Small repeated workset, not HBM peak.')
fig,axes=plt.subplots(2,2,figsize=(12,7))
for op,ax in enumerate(axes.flat):
    rows=[r for r in simt if r['op']==op and r['elements']==2048 and r['steps']==128 and r['impl']<=2]
    vf=sorted([r for r in rows if r['impl']==1],key=lambda r:r['threads'])
    ax.plot([r['threads'] for r in vf],[r['p50'] for r in vf],'-o',color='#15756c',markersize=4,label='SIMT')
    ax.fill_between([r['threads'] for r in vf],[r['low'] for r in vf],[r['high'] for r in vf],color='#15756c',alpha=.12)
    for impl,label,color in ((0,'Scalar','#e47c44'),(2,'SIMD Tensor API','#7894b6')):
        r=next(r for r in rows if r['impl']==impl);ax.axhline(r['p50'],color=color,ls='--',label=label)
    ax.set(xscale='log',yscale='log',title=('Add','Subtract','Multiply','Divide')[op],xlabel='Actual threads = launch bound',ylabel='Completion time (us)',xlim=(1,2048));ax.set_xticks([1,8,32,128,512,2048],['1','8','32','128','512','2048']);ax.legend(fontsize=8)
export(fig,'a5-simt','FP32, 2048 elements x 128 dependent operations. SIMT register chain vs SIMD per-step UB access/sync. Includes dispatch/completion; excludes GM staging/export.')
fig,ax=plt.subplots(figsize=(10,5.5))
for calls,color in ((1,'#e47c44'),(128,'#15756c')):
    rows=sorted([r for r in simt if r['impl']==3 and r['vf_calls']==calls],key=lambda r:r['threads'])
    ax.plot([r['threads'] for r in rows],[r['p50']/calls for r in rows],'-o',color=color,label=f'{calls} VF call(s), per-call p50')
    control=next(r for r in simt if r['impl']==4 and r['vf_calls']==calls)
    ax.axhline(control['p50']/calls,color=color,ls='--',alpha=.6,label=f'{calls} no-VF sync iterations, per-iteration p50')
ax.set(xscale='log',xlabel='Threads (one observable UB store per thread)',ylabel='Amortized completion time (us/call)',xlim=(1,2048));ax.set_xticks([1,8,32,128,512,2048],['1','8','32','128','512','2048']);ax.legend(fontsize=8)
export(fig,'a5-overhead','Includes VF dispatch, per-thread UB store and completion wait. This is not isolated hardware thread creation time. Two-round median.')
print(a.output)
