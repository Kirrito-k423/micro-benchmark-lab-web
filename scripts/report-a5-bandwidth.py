#!/usr/bin/env python3
"""重建多核带宽报告与图；N95 是观测阈值，不能将末点当硬件上限。"""
import argparse,json,statistics
from pathlib import Path

def points(db):
    groups={}
    for r in db['rows']:groups.setdefault(r['caseId'],[]).append(r)
    return [rs[0]|dict(p50Us=statistics.median(r['p50Us'] for r in rs),
        gbps=rs[0]['movedBytes']/statistics.median(r['p50Us'] for r in rs)/1000) for rs in groups.values()]
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--figures',type=Path,required=True)
    a=p.parse_args();db=json.loads(a.data.read_text());rows=points(db)
    large=[c for c in db['curves'] if not c['control'] and not c['sharedRead'] and c['requestedRing']>=2**30]
    lines=['# A5 DataCopy：单卡多 AIV 的有效聚合带宽','',
        f"{db['environment']['soc']}，{db['environment']['cann']}。ACL 查询可用 AIV={db['environment']['aiv_count']}、UB={db['environment']['ub_bytes']}B；同版本平台配置 L2={db['environment']['l2_bytes']/2**20:g}MiB。{db['evidence']['configsPerRound']} 配置 × 两轮，共 {db['evidence']['timedSamples']} 计时样本，逐 launch 正确性与保护区验证通过。",'',
        '## 结果','']
    for ring in [1<<30,2<<30]:
        for direction in ['GM_UB','UB_GM']:
            cs=[c for c in large if c['requestedRing']==ring and c['direction']==direction]
            best=max(cs,key=lambda c:c['peakGbps'])
            ps=sorted([r for r in rows if not r['control'] and not r['sharedRead'] and r['requestedRing']==ring and r['direction']==direction and r['tileBytes']==best['tileBytes'] and r['batch']==best['batch']],key=lambda r:r['cores'])
            last_gain=(ps[-1]['gbps']/ps[-2]['gbps']-1)*100
            lines.append(f"- {ring/2**30:g}GiB 工作集 {'读' if direction=='GM_UB' else '写'}：最高 {best['peakGbps']/1000:.3f}TB/s，{best['peakCores']} 核、{best['tileBytes']//1024}KiB × {best['batch']}；N95={best['n95']}，相对单核 {best['speedupAtPeak']:.2f}×。该配置从 {ps[-2]['cores']} 到 {ps[-1]['cores']} 核仍提高 {last_gain:.2f}%。")
    if not any(c['adjacentPlateau'] for c in large):
        lines+=['','所有大工作集组合均未确认相邻点平台。已经测到当前设备的全部可用 AIV；本实验回答“64 核仍有增益”，尚不能给出“多少核已用满硬件带宽”的肯定阈值。N95=64 仅相对于本次观测最高值。']
    lines+=['','4KiB 的命令粒度也限制吞吐；同一 tile、同一 64 核、同一工作集，batch 1 与 8 的完成等待方式不同：','',
        '| 请求工作集 | 方向 | 4KiB × 1 GB/s | 4KiB × 8 GB/s | batch 8 / 1 |',
        '| --- | --- | --- | --- | --- |']
    for ring in [1<<30,2<<30]:
        for direction in ['GM_UB','UB_GM']:
            rs={r['batch']:r for r in rows if not r['control'] and not r['sharedRead'] and r['requestedRing']==ring and r['direction']==direction and r['tileBytes']==4096 and r['cores']==db['environment']['aiv_count']}
            lines.append(f"| {ring/2**30:g} GiB | {direction} | {rs[1]['gbps']:.2f} | {rs[8]['gbps']:.2f} | {rs[8]['gbps']/rs[1]['gbps']:.2f}× |")
    lines+=['',
        '## 是否已观察到平台','',
        '表中 N95 是已测档位中达到该曲线最高有效带宽 95% 的最少核数。相邻后续点也达到阈值才标记“相邻点平台”。若最大可用核数仍增长或没有后续点，不宣称硬件带宽已饱和。单位为单向有效 GB/s，不是 HBM 物理事务计数。','',
        '| 请求工作集 | 方向 | tile × batch | 观测最高 GB/s | 最高点 AIV | N95 | 相邻点平台 | 相对单核 |',
        '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for c in large:
        lines.append(f"| {c['requestedRing']/2**30:g} GiB | {c['direction']} | {c['tileBytes']//1024} KiB × {c['batch']} | {c['peakGbps']:.2f} | {c['peakCores']} | {c['n95']} | {'是' if c['adjacentPlateau'] else '未确认'} | {c['speedupAtPeak']:.2f}× |")
    lines+=['','首阶段 1GiB 曲线到高核数仍增长，因此追加 2GiB 地址覆盖、4GiB 有效搬运量的两轮验证。全部 tile/batch 组合均保留，不只挑最优实现。该追加阶段没有改变被测 C++ 二进制。','',
        '## 每个核数点','',
        '以下 32KiB × 2 的共同区间与吞吐为两轮 p50 的中位数。4MiB 请求工作集按每核两组 UB 的粒度取整，实际最大 8MiB；1/2GiB 的取整差异更小，但始终按真实有效字节计算。','',
        '| 工作集 | 方向 | AIV | 实际 GM MiB | 有效搬运 GiB | 共同 p50 μs | 聚合 GB/s | 平均每核 GB/s |',
        '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for ring in [4<<20,1<<30,2<<30]:
        for direction in ['GM_UB','UB_GM']:
            rs=sorted([r for r in rows if not r['control'] and not r['sharedRead'] and r['requestedRing']==ring and r['direction']==direction and r['tileBytes']==32768 and r['batch']==2],key=lambda r:r['cores'])
            for r in rs:lines.append(f"| {ring/2**20:g} MiB | {direction} | {r['cores']} | {r['actualRing']/2**20:.3f} | {r['movedBytes']/2**30:.4f} | {r['p50Us']:.3f} | {r['gbps']:.2f} | {r['gbps']/r['cores']:.2f} |")
    repeat=db['evidence']['repeatability']
    lines+=['','## 实验与证据','',
        'uint32 原样 DataCopy count 重载；所有地址/长度 32B 对齐。各核独立 UB 两组窗口，复用前等旧 DMA，batch 连续发射后设置完成事件，结束排空全部窗口。核数 1/2/4/8/12/16/20/24/28/32/40/48/56/64 来自预定矩阵，最大值以运行时查询为准。','',
        '聚合吞吐使用同一 stream 的 ACL Event begin/end 整 kernel 共同区间，包含调度、UB 初始化、起止 SyncAll、DMA、完成等待与少量结果导出；不含 Host 上传、输出下载或 oracle。原始值，不减空对照。每核 SYS_CNT 差值仅用于核内区间和均衡分析，不用跨核绝对起点拼接，不相加各核独立峰值。','',
        '分区读写互不重叠。同址只读重复逻辑请求，避免了多写冲突，也不能将这条曲线的字节数理解为物理 HBM 流量。4MiB/128KiB 对照用于观察小工作集复用。1GiB/2GiB 请求工作集分别为平台配置 L2 容量的 8/16 倍；未使用缓存计数器或强制旁路，不将有效 GM 吞吐当作硬件理论 HBM 带宽。','',
        '每次 launch 逐元素校验全部写目标（每核 pattern 随 launch 变化），或所有核最后两组读入结果；128B GM 保护区及每核提交记录全部验证。读中间 tile 未逐项导出，避免计时主体混入处理负载。每条曲线各核数在同一进程复用 GM 分配；两轮曲线和核数独立随机次序。','',
        f"每配置 2 预热 + 12 计时。两轮 p50 相对差异中位数 {repeat['medianRelativePct']:.4f}%，最大 {repeat['maxRelativePct']:.4f}%。此为重复性观察，不是置信区间。",'',
        db['evidence']['isolation'],'',
        db['evidence']['platformMetadata'].get('note','同版本 SoC 配置原文与 SHA256 已核对。'),'',
        '[代码与 SOP](https://github.com/Kirrito-k423/ascend-kernel-lab/tree/codex/a5-alignment-simt/examples/a5_bandwidth) · [交互页面](https://kirrito-k423.github.io/micro-benchmark-lab-web/?lab=bandwidth)','',
        '网站数据保留原始 ACL 毫秒样本、每核 SYS_CNT 差值、真实工作集/有效字节以及构建/manifest 哈希；完整原始 start/end、设备和占用日志留在私有归档。','',
        '```bash','python3 scripts/import-a5-bandwidth.py --runs /absolute/private/raw --environment /absolute/environment.json --platform-config /absolute/platform-config.ini --akl-root /absolute/akl --output public/data/a5-bandwidth.json',
        'python3 scripts/report-a5-bandwidth.py --data public/data/a5-bandwidth.json --report reports/a5-bandwidth-20261009.md --figures public/figures','```','']
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text('\n'.join(lines))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'svg.hashsalt':'a5-bandwidth'})
    fig,axes=plt.subplots(2,3,figsize=(16,9),layout='constrained')
    for i,direction in enumerate(['GM_UB','UB_GM']):
        for j,ring in enumerate([4<<20,1<<30,2<<30]):
            ax=axes[i,j]
            for (tile,batch),color in zip([(4096,1),(4096,8),(32768,2),(65536,1)],['#8a9db0','#875aa6','#16756b','#e77d42']):
                rs=sorted([r for r in rows if not r['control'] and not r['sharedRead'] and r['direction']==direction and r['requestedRing']==ring and r['tileBytes']==tile and r['batch']==batch],key=lambda r:r['cores'])
                ax.plot([r['cores'] for r in rs],[r['gbps'] for r in rs],marker='o',label=f'{tile//1024} KiB x {batch}',color=color)
            ax.set_title(f'{"GM -> UB" if i==0 else "UB -> GM"} / {ring/2**20:g} MiB requested ring')
            ax.set_xlabel('Active AIV cores');ax.set_ylabel('Aggregate effective GB/s');ax.grid(alpha=.2);ax.set_xlim(1,db['environment']['aiv_count'])
    handles,labels=axes[0,0].get_legend_handles_labels();fig.legend(handles,labels,loc='outside lower center',ncol=4)
    fig.suptitle('Measured A5 / Ascend950DT_9582 / CANN 9.1.0 / one device\nCommon ACL Event interval; no empty-control subtraction; all launches verified',fontsize=15)
    a.figures.mkdir(parents=True,exist_ok=True);fig.savefig(a.figures/'a5-bandwidth.png',dpi=160)
    svg=a.figures/'a5-bandwidth.svg';fig.savefig(svg);plt.close(fig)
    svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines())+'\n')
    print('report / PNG / SVG generated from validated data')
if __name__=='__main__':main()
