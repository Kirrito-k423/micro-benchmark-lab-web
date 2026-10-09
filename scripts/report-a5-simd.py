#!/usr/bin/env python3
"""从验收 JSON 重建同工作量表格与静态曲线，不选择单次最快样本。"""
import argparse,json,statistics
from pathlib import Path

def aggregate(db):
    grouped={}
    for r in db['rows']:
        key=(r['op'],r['elements'],r['steps'],r['impl'],r['threads'])
        grouped.setdefault(key,[]).append(r)
    return {k:dict(p50=statistics.median(r['p50'] for r in rs),
                   p95=statistics.median(r['p95'] for r in rs)) for k,rs in grouped.items()}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',type=Path,required=True)
    p.add_argument('--report',type=Path,required=True)
    p.add_argument('--figures',type=Path,required=True)
    a=p.parse_args();db=json.loads(a.data.read_text());g=aggregate(db)
    names=['Add','Sub','Mul','Div']
    def matched(op,n,steps):
        rows=[(k,v) for k,v in g.items() if k[:3]==(op,n,steps)]
        scalar={k[3]:v['p50'] for k,v in rows if k[3]!=1}
        simt=min(((k[4],v['p50']) for k,v in rows if k[3]==1),key=lambda x:x[1])
        return scalar,simt
    lines=['# A5 SIMD 与 SIMT：相同规则连续 FP32 工作量','',
      f"{db['environment']['soc']}，{db['environment']['cann']}，单 AIV、本地 UB。{db['evidence']['configsPerRound']} 配置 × 两轮，共 {db['evidence']['timedSamples']} 个计时样本。输出、尾块与 128B GM 保护区全部通过；最大绝对误差 {db['evidence']['maxAbsError']:.8g}。",'',
      'SIMT 每个线程可以循环处理多个元素。本组额外验证了 1 线程处理 129 元素的加减乘除。REG 属于 SIMD 编程；单向量包含多个 lane，4 组版本交错四条独立向量链。', '',
      '## 发现','',
      '规则批量的一次运算，以 8192 元素为例，Tensor SIMD 相对五档线程中最优 SIMT 快 4.28–4.80 倍；手写 REG 的加载、循环和分组开销在这个条件下更大。', '',
      '2048/8192 元素的 128 步加减乘依赖链，REG 4 组比最优 SIMT 快 4.08–7.55 倍；相比 Tensor API 快 2.28–4.71 倍。除法没有同样优势：8192 元素 × 128 步，Tensor / REG 4 / SIMT 分别为 23.386 / 32.328 / 30.3145 μs，Tensor 最快。', '',
      '本轮 SIMD/REG 与 SIMT 在同一新二进制内重新测量；不会拼接上一轮 SIMD/SIMT 工程的点。新增曲线是本实现的无外部进程快照基线，不是语言模式或硬件的普遍性能上限。', '',
      '## 直接对照','',
      '设备完成区间 / μs。表中每项为两轮 p50 的中位数；SIMT 从预设 32/128/512/1024/2048 线程中选该工作量最优的配置，不选择最快单样本。REG 的 1/4 组均保留。', '',
      '| 元素数 | 每元素次数 | 运算 | Tensor API | REG 1 组 | REG 4 组 | 最优 SIMT | 线程数 | SIMT / REG 4 耗时比 |',
      '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for n,steps in [(32,1),(2048,1),(8192,1),(16384,1),(2048,128),(8192,128),(8192,512)]:
        for op in range(4):
            base,(threads,simt)=matched(op,n,steps)
            lines.append(f'| {n} | {steps} | {names[op]} | {base[0]:.5f} | {base[2]:.5f} | {base[3]:.5f} | {simt:.5f} | {threads} | {simt/base[3]:.3f}× |')
    repeat=db['evidence']['repeatability']
    lines+=['','## 口径与复现','',
      '15 个 shape：1/31/32/33/63/64/65/128/256/512/1024/2048/4096/8192/16384。主矩阵 steps=1/16/128；2048/8192 增加 steps=512；10 个批量 shape 补 steps=0。每配置 2 预热 + 15 计时，两轮独立随机次序。', '',
      'Tensor API 每步读写 UB 并执行 PIPE_V barrier；REG/SIMT 在寄存器保留依赖链。4 组 REG 总计算量相同，只增加可并行的独立链。小于四组向量的尾块回退单组。', '',
      db['evidence']['boundary'], '',
      'steps=0 统一使用加法入口，保留各实现的无运算参考，不代表其他运算专属的控制开销。REG/SIMT 仍有读写/调用；Tensor 只有完成等待。不同空对照不能直接互减为硬件 ALU 指令延迟。', '',
      f"两轮 p50 相对差异：中位数 {repeat['medianRelativePct']:.4f}%，最大 {repeat['maxRelativePct']:.4f}%。只是重复性观察，不能解释为置信区间。",'',
      db['evidence']['isolation'], '',
      '吞吐为有效 FP32 元素运算 Gop/s，含加载、循环、分发、完成等待的代价。除法会被实现为多条底层指令，依然按每元素一次除法计有效运算。没有证明整芯片峰值、多核并发、分支或离散访问性能，也没有把 SIMD 胜负泛化到所有工作量。', '',
      '[AKL 代码与 SOP](https://github.com/Kirrito-k423/ascend-kernel-lab/tree/codex/a5-alignment-simt/examples/a5_simd_mbench)', '',
      '网站原始结果：`public/data/a5-simd.json`，包括计时/预热 tick、Host launch+sync、每配置误差、源码和二进制哈希。完整设备日志与占用快照保持私有。', '',
      '```bash',
      'python3 scripts/import-a5-simd.py --runs /absolute/private/raw --akl-root /absolute/akl --output public/data/a5-simd.json',
      'python3 scripts/report-a5-simd.py --data public/data/a5-simd.json --report reports/a5-simd-20261009.md --figures public/figures',
      '```','']
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text('\n'.join(lines))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    fig,axes=plt.subplots(2,4,figsize=(18,8),layout='constrained')
    shapes=[32,64,128,256,512,1024,2048,4096,8192,16384]
    for op in range(4):
        ax=axes[0,op]
        for impl,label,color in [(0,'Tensor API','#a58b40'),(2,'REG 1 group','#16756b'),(3,'REG 4 groups','#e77d42')]:
            ax.plot(shapes,[n/g[(op,n,1,impl,None)]['p50']/1000 for n in shapes],marker='o',label=label,color=color)
        simt=[matched(op,n,1)[1][1] for n in shapes]
        ax.plot(shapes,[n/t/1000 for n,t in zip(shapes,simt)],marker='s',ls='--',label='Best tested SIMT',color='#7589a5')
        ax.set_xscale('log',base=2);ax.set_title(f'{names[op]}: 1 operation / element');ax.set_xlabel('FP32 elements');ax.set_ylabel('Effective Gop/s');ax.grid(alpha=.2)
        ax=axes[1,op];steps=[1,16,128,512];n=8192
        for impl,label,color in [(0,'Tensor API','#a58b40'),(2,'REG 1 group','#16756b'),(3,'REG 4 groups','#e77d42')]:
            ax.plot(steps,[g[(op,n,k,impl,None)]['p50'] if k else g[(0,n,0,impl,None)]['p50'] for k in steps],marker='o',label=label,color=color)
        ax.plot(steps,[matched(op,n,k)[1][1] if k else matched(0,n,0)[1][1] for k in steps],marker='s',ls='--',label='Best tested SIMT',color='#7589a5')
        ax.set_title(f'{names[op]}: 8192 elements');ax.set_xlabel('Dependent operations / element');ax.set_ylabel('Completion interval (us)');ax.grid(alpha=.2)
    handles,labels=axes[0,0].get_legend_handles_labels();fig.legend(handles,labels,loc='outside lower center',ncol=4)
    fig.suptitle('Measured A5 / Ascend950DT_9582 / CANN 9.1.0 / single AIV / local UB\nTwo-round median p50; includes compute dispatch and completion; excludes GM preparation/export',fontsize=15)
    a.figures.mkdir(parents=True,exist_ok=True)
    fig.savefig(a.figures/'a5-simd.png',dpi=170);fig.savefig(a.figures/'a5-simd.svg');plt.close(fig)
    print('report / PNG / SVG rebuilt from validated data')

if __name__=='__main__':main()
