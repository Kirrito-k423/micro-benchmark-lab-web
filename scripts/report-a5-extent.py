"""Render the accepted 32 B–4 MiB request curves, without extrapolated points."""
import argparse,json,statistics
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def size(n):
    return f'{n/(1<<20):g} MiB' if n>=1<<20 else f'{n/1024:g} KiB' if n>=1024 else f'{n} B'
def aggregate(rows):
    groups={}
    for r in rows:groups.setdefault((r['caseId'],r['allocation']),[]).append(r)
    result=[]
    for rs in groups.values():
        assert len(rs)==2 and {r['round'] for r in rs}=={1,2}
        us=statistics.median(r['p50'] for r in rs)
        result.append(rs[0]|dict(p50=us,gbps=rs[0]['payload']/us/1000,roundP50=[r['p50'] for r in sorted(rs,key=lambda r:r['round'])]))
    return result
def main():
    p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--report',type=Path,required=True)
    p.add_argument('--figures',type=Path,required=True);a=p.parse_args();db=json.loads(a.data.read_text());ev=db['evidence']
    assert ev['receiverValidation']=='passed' and len(db['rows'])==864 and ev['maxBytes']==4<<20
    points=aggregate(db['rows']);sizes=[1<<n for n in range(5,23)]
    a.figures.mkdir(parents=True,exist_ok=True)
    for metric in ['bandwidth','latency']:
        fig,axes=plt.subplots(2,2,figsize=(13,8),constrained_layout=True)
        for j,direction in enumerate(['GM_UB','UB_GM']):
            for k,windows in enumerate([1,2]):
                ax=axes[j,k]
                for policy,color,label in [('normal','#e77d42','Normal'),('huge-first','#16756b','Huge first')]:
                    curve=sorted([r for r in points if r['api']=='DataCopy_count' and r['direction']==direction and r['windows']==windows and r['allocation']==policy],key=lambda r:r['payload'])
                    assert [r['payload'] for r in curve]==sizes
                    ax.plot(sizes,[r['gbps'] if metric=='bandwidth' else r['p50'] for r in curve],color=color,marker='o',markersize=4,label=label)
                ax.set_xscale('log',base=2)
                if metric=='latency':ax.set_yscale('log')
                ax.set_xticks(sizes[::2]+[sizes[-1]],[size(v) for v in sizes[::2]+[sizes[-1]]],rotation=25,fontsize=8)
                ax.axvline(65536,color='#777',linewidth=.8,linestyle='--',label='64 KiB tile cap')
                ax.set_title(f'{"Read GM -> UB" if direction=="GM_UB" else "Write UB -> GM"} / {windows} UB window(s)')
                ax.set_ylabel('Effective GB/s' if metric=='bandwidth' else 'Mean completion per request / us')
                ax.set_xlabel('Logical request bytes (18 measured powers of two)');ax.grid(alpha=.2);ax.legend(fontsize=8)
        fig.suptitle('A5 / 1 AIV / DataCopy(count) / 32 B to 4 MiB / two-round median\nRepeated same working set; default L2; not physical HBM bandwidth',fontsize=12)
        for ext in ['png','svg']:fig.savefig(a.figures/f'a5-extent-{metric}.{ext}',dpi=170)
        plt.close(fig)
    env=db['environment'];lines=['# A5 单 AIV：32 B 到 4 MiB 的完整请求扫描','',
        f"已验收 **18 个倍增点、{len(db['rows'])} 配置轮次、{ev['timedSamples']} 个正式计时样本**，另有 {ev['traceOffSamples']} 个关闭 trace 的对照启动。读、写 / 三种 API / 1、2 个 UB 窗口 / 普通页、大页优先 / 两轮均完整覆盖。历史原始数据保留。",'',
        '![18 点吞吐曲线](../figures/a5-extent-bandwidth.png)','',
        '![18 点完成耗时曲线](../figures/a5-extent-latency.png)','',
        f"设备：{env['soc']}，{env['cann']}，1 个 AIV，实际 UB {env['ub_bytes']} B，uint32，连续地址、无 gap。",'',
        '## 总字节与 API 大小','',
        '横轴为一次完整请求的总字节，从 32 B 翻倍至 4 MiB；4 MiB 不是一次 DataCopy 的 UB Tensor。count / params 的 tile=min(总字节,64 KiB)，DataCopyPad(DataCopyParams) 的 uint16 字节长度使用 tile=min(总字节,32 KiB)。因此 4 MiB 分别需要 64 / 128 次连续 API 调用，UB 中仅保留 1/2 个 tile。', '',
        '每请求结束时包含最后的完成等待，再处理下一请求。小请求最多重复 8192 次，大请求至少重复 4 次；SYS_CNT 总区间除以请求重复数，得到每请求平均完成耗时。双窗口只在一个请求内流水，不跨请求继续 DMA。初始化和结果导出不在该区间内；完整 kernel 的 ACL Event 与 trace-off 样本单独保留。','',
        '## 4 MiB：DataCopy(count)','',
        '| 方向 | UB 窗口 | 页策略 | 请求 p50 / μs | 有效 GB/s | 两轮 p50 / μs |','| --- | ---: | --- | ---: | ---: | --- |']
    for r in sorted([r for r in points if r['payload']==4<<20 and r['api']=='DataCopy_count'],key=lambda r:(r['direction'],r['windows'],r['allocation'])):
        lines.append(f"| {r['direction']} | {r['windows']} | {r['allocation']} | {r['p50']:.5f} | {r['gbps']:.3f} | {' / '.join(f'{v:.5f}' for v in r['roundP50'])} |")
    lines+=['','## 全部 18 个点：双窗口大页优先 count','',
        '| 总字节 | tile × 次数 | 读 p50 / μs | 读 GB/s | 写 p50 / μs | 写 GB/s |','| --- | --- | ---: | ---: | ---: | ---: |']
    for n in sizes:
        selected=[next(r for r in points if r['payload']==n and r['api']=='DataCopy_count' and r['windows']==2 and r['allocation']=='huge-first' and r['direction']==d) for d in ['GM_UB','UB_GM']]
        x,y=selected;lines.append(f"| {size(n)} | {size(x['tileBytes'])} × {x['tilesPerRequest']} | {x['p50']:.5f} | {x['gbps']:.3f} | {y['p50']:.5f} | {y['gbps']:.3f} |")
    lines+=['','## 解释边界','',
        '输入和输出每配置新申请，申请容量至少 2 MiB；实际触达工作集等于请求总字节。普通页与大页优先采用同源码、同 CANN、同参数；HUGE_FIRST 可以回退，未查物理页表。默认 L2 且同一份数据反复访问，未采集缓存命中或物理 HBM 事务，不能将有效吞吐当作冷 HBM 总线带宽，也不能用它解释之前 2 GiB 多核扫描的上限。', '',
        '独立的不计性能读回启动验证所有 tile 和 128 B guard；每个正式/预热启动再次校验完整写目标或最后 1/2 个完整 UB 窗口与 guard。计时读的早期 tile 已被覆盖，其校验范围与独立完整读 oracle 分开记录。', '',
        '两轮配置顺序独立随机，页策略交替短批；trace 开/关顺序随机。全部样本保留，每个短批 Host/容器前后均无其他 NPU 进程，未证明两次快照间完全没有瞬时干扰。', '',
        '该曲线的实现、tile、同步和计时协议与旧“单次 API”曲线有差别；页面将它作为“完整请求”实验单列，不直接拼接旧 API 上限。','',
        f"时钟按匹配芯片的 [CANN GetSystemCycle 文档]({ev['clockDocumentUrl']})换算，保留原始 tick、全部 ACL Event、开关对照与来源哈希。接收端核对任务终态、原始 tar 字节、源码/二进制、参数、时钟区间、占用和完整覆盖后发布。",'',
        '## 复现','',
        '固定源码在 [experiments/a5_extent](https://github.com/Kirrito-k423/micro-benchmark-lab-web/tree/codex/a5-mbench-results/experiments/a5_extent)。确认目标芯片、CANN、UB、时钟及整机占用，空闲时分短任务执行：','',
        '```bash','cd experiments/a5_extent','python3 plan.py','bash build.sh','python3 run_stage.py --device 1 --key smoke-normal-v3 --output results/smoke-normal-v3',
        'python3 run_stage.py --device 1 --key smoke-huge-first-v3 --output results/smoke-huge-first-v3',
        '# 执行 execution-plan.json 中 round=1/2 的短批；每批运行前后再查整机占用。',
        'python3 run_stage.py --device 1 --key r1-normal-00-v3 --output results/r1-normal-00-v3','```','',
        '```bash','python3 scripts/import-a5-extent.py /absolute/private/experiment --output public/data/a5-extent.json',
        'uv run --no-project --with matplotlib python scripts/report-a5-extent.py --data public/data/a5-extent.json --report public/reports/a5-extent-20261011.md --figures public/figures','npm run build:pages','```','',
        f"Source archive SHA-256：`{ev['sourceArchiveSha256']}`。计划 SHA-256：`{ev['planSha256']}`。",'']
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text('\n'.join(lines));print('report and figures passed',len(points))
if __name__=='__main__':main()
