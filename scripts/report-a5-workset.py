"""Generate decline brackets and figures only from the complete accepted sweep."""
import argparse,importlib.util,json
from pathlib import Path
NAMES={'read':'分区读','write':'分区写','shared':'同址读'}
def interval(b):return f"{b['lowerBytes']/2**20:g}–{b['upperBytes']/2**20:g} MiB" if b else '未形成持续跨越'
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--data',type=Path,required=True);p.add_argument('--report',type=Path,required=True);p.add_argument('--figures',type=Path,required=True);a=p.parse_args()
    db=json.loads(a.data.read_text());assert db['evidence']['receiverValidation']=='passed'
    spec=importlib.util.spec_from_file_location('analysis',Path(__file__).with_name('workset-analysis.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    assert m.analyse(db['rows'])==db['analysis'];points=m.summarize(db['rows'])
    lines=['# A5 DataCopy：从高吞吐到低平台的工作集扫描','',
        '原来 128 KiB、约 5.108 TB/s 是 64 核同址读；2 GiB、约 2.1 TB/s 是各核独立分区。这两个点改变了地址共享条件，不能直接连成一条大小曲线。本轮将分区读、分区写和同址读分别扫描，固定 64 AIV、uint32 DataCopy(count)、32 KiB × 2、双 UB 窗口完成策略。','',
        f"{db['measuredDate']}，{db['environment']['soc']} / {db['environment']['cann']}；{db['evidence']['configsPerRound']} 配置 × 两轮、{db['evidence']['timedSamples']} 正式样本、{db['evidence']['warmupSamples']} 预热样本。",'',
        '![完整扫描及拐点放大](../figures/a5-workset.png)','',
        '## 下降发生在哪里','',
        '| 曲线 | 高 / 低参考 TB/s | D10 开始下降 | D50 下降一半 | D90 接近低平台 | 最大相邻降幅 | 两轮差异中位数 / 最大 |',
        '| --- | --- | --- | --- | --- | --- | --- |']
    for c in db['analysis']['curves']:
        lines.append(f"| {NAMES[c['scope']]} | {c['highGbps']/1000:.3f} / {c['lowGbps']/1000:.3f} | {interval(c['crossings'].get('10'))} | {interval(c['crossings'].get('50'))} | {interval(c['crossings'].get('90'))} | {interval(c['largestAdjacentDrop'])}、{c['largestAdjacentDrop']['relativeDropPct']:.1f}% | {c['repeatability']['medianRelativePct']:.2f}% / {c['repeatability']['maxRelativePct']:.2f}% |")
    lines+=['','高参考为预先规定的 8 / 16 / 24 / 32 MiB 带宽中位数；低参考为 512 / 768 / 1024 / 1536 / 2048 MiB。每轮独立取参考值，跨越 D10 / D50 / D90 阈值须连续两个点低于阈值，再取两轮大小区间的并集。两轮都至少下降 20% 才标出下降区间。D50 是高低差下降一半，并非带宽绝对减半。全部点保留，不插值、不拟合预期 S 形。区间为采样分辨率，不是统计置信区间。','',
        '## 同址读的高吞吐下降段','', '同址读在 128 KiB 至 4 MiB 保持约 5.2 TB/s，4→8 MiB 从约 5.126 降至 3.895 TB/s，8→16 MiB 再降至 2.717 TB/s；两个相邻区间分别下降约 24% 与 30%。128 MiB 时已约 2.054 TB/s。统一预定的 8–32 MiB 高参考已经落在这个下降段，所以不能用其约 2.617 TB/s 描述原来的 5 TB/s 高平台。','', '为对应用户指定的端点，补充描述性分析（未替换预定规则）：以 128 KiB 实测值为高参考、2 GiB 为低参考，两轮 D10 为 4–8 MiB、D50 为 8–16 MiB、D90 为 48–64 MiB。这不是新的独立实验或统计显著性检验。最大相邻陡降定位到 8–16 MiB；区间内没有再采点，不能宣称精确字节阈值。','', '## 工作集与计时口径','',
        '- 分区读写从实际 8 MiB 开始：64 核 × 每核两个 64 KiB 组，分区互不重叠。每个点逻辑搬运 4 GiB，2 GiB 工作集也完整遍历两次。',
        '- 同址读从 128 KiB 开始；每个核完整遍历 ring 至少两次。总 payload = max(4 GiB, 2 × AIV数 × 每核ring) 按组取整。2 GiB 共享工作集对应全核 256 GiB 逻辑 payload，不能用分配大小代替实际触达大小。',
        '- 每条曲线一个进程，按该曲线的最大工作集一次分配 GM，再随机扫描各点；两轮种子不同，跨曲线和轮次重新分配。',
        '- 吞吐 = 实际全核有效 payload / 同 stream ACL Event 完整 kernel 区间，保留调度、初始化、同步、DMA 和结果导出，不扣空循环。核内 SYS_CNT 单独记录，不相加核峰值。',
        '- 每点 2 次预热与 12 次计时；读逐启动校验最后两个 UB 组、保护区及核记录，写校验完整目标与保护区。每条曲线检查 Host / 容器运行前后无其他 NPU 进程；快照不能证明不存在瞬时干扰。首台机器冒烟期间出现其他训练进程，该次计时被拒收，失败原始档案保留。','',
        '## 能解释到哪一步','',
        '平台配置记录 L2 容量为 128 MiB，图中用竖线标出。下降与容量位置接近只能说明相容性；未测缓存命中率、HBM 物理事务或内存控制器利用率，不能确认因果。所有 TB/s 都是该实现的有效请求吞吐，同址重复读尤其不能等同物理 HBM 带宽。分区不重叠仍可能竞争 bank / 通道 / 缓存资源，本轮没有改变地址映射，不能据此排除或证实。','',
        '同址大 ring 的总请求量随大小增加，因此其曲线是“固定实现且完整触达”的结果，未将请求量固定为 4 GiB；分区读写则固定总搬运量。读高低平台和写高低平台各自比较，不混用端点。','',
        '## 复现','',
        '使用报告附带的固定 planner / runner，配合匹配的 AKL DataCopy 源文件；运行前确认整台 Host 与容器 NPU 都空闲，借用短窗口逐条执行。源码哈希与 binary 哈希绑定在网页点选代码和数据 evidence 中。源码文件内容匹配提交为 a9f21012ffe61afbda405842d3f54d6a5d73aa3a，不表示旧实验曾记录整个仓库提交。','',
        '```bash','source /usr/local/Ascend/cann/set_env.sh',
        'cmake -S examples/a5_bandwidth -B build-bandwidth','cmake --build build-bandwidth -j2',
        'mkdir -p tools',
        'cp scripts/prepare_bandwidth.py tools/prepare.py',
        'cp scripts/run_borrowed_batch.py tools/run_borrowed_batch.py',
        'python3 tools/prepare.py --device 1 --clock-hz 1000000000 --clock-source "CANN 9.1 GetSystemCycle: Ascend950PR/950DT SYS_CNT 1 GHz"',
        '# 将本网站 scripts/workset-plan.py 和 workset-runner.py 放到 tools/，保持哈希相同',
        'python3 tools/workset-runner.py --root . --scope read --round 1 --smoke --output results/smoke-read-new',
        'python3 tools/workset-runner.py --root . --scope write --round 1 --smoke --output results/smoke-write-new',
        'python3 tools/workset-runner.py --root . --scope shared --round 1 --smoke --output results/smoke-shared-new',
        '# 每条曲线独立短任务；轮次 1 / 2、scope read / write / shared 各执行一次',
        'python3 tools/workset-runner.py --root . --scope read --round 1 --output results/r1-read-new','```','',
        '全部原始归档与完整设备日志留在私有 results。公开数据保留原始 ACL 毫秒、核区间持续 ticks、每核遍历次数、环境摘要和构建/样本/归档绑定的 manifest 哈希；不公开地址、主机名、凭据或绝对设备时钟。','',
        '## 实测点（两轮 p50 的中位数）','',
        '| 场景 | 实际触达 MiB | 完整 p50 μs | 有效 TB/s | 每核遍历次数 | 全核 payload GiB |','| --- | --- | --- | --- | --- | --- |']
    for r in sorted(points,key=lambda p:(p['scope'],p['coveredGmBytes'])):lines.append(f"| {NAMES[r['scope']]} | {r['coveredGmBytes']/2**20:g} | {r['p50Us']:.3f} | {r['gbps']/1000:.3f} | {r['repeatsPerCore']:g} | {r['movedBytes']/2**30:g} |")
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text('\n'.join(lines)+'\n')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'axes.spines.top':False,'axes.spines.right':False,'font.size':10,'svg.hashsalt':'a5-workset'})
    fig,axes=plt.subplots(1,3,figsize=(19,5.3),layout='constrained')
    colors=['#16756b','#e77d42','#875aa6']
    for c,color in zip(db['analysis']['curves'],colors):
        rs=[r for r in points if r['scope']==c['scope']]
        for ax in axes:
            ax.plot([r['coveredGmBytes']/2**20 for r in rs],[r['gbps']/1000 for r in rs],marker='o',markersize=3,color=color,label=c['scope'])
            b=(c['endpointDecline'] if c['scope']=='shared' else c)['crossings'].get('50')
            if b:ax.axvspan(b['lowerBytes']/2**20,b['upperBytes']/2**20,alpha=.08,color=color)
    for ax in axes:
        ax.axvline(db['environment']['l2_bytes']/2**20,color='#8a9db0',ls='--',label='L2 capacity reference');ax.set(xlabel='Actual covered GM / MiB',ylabel='Effective TB/s (full kernel)');ax.grid(alpha=.15);ax.legend(fontsize=8)
    axes[0].set_xscale('log',base=2);axes[0].set(title='Full sweep: 128 KiB to 2 GiB',xlim=(.125,2048))
    axes[1].set(title='Partition decline region (D50 bands)',xlim=(32,256))
    axes[2].set(title='Shared-read early drop',xlim=(0,32))
    fig.suptitle('A5 DataCopy workset sweep / 64 AIV / 32 KiB x 2 / two rounds')
    a.figures.mkdir(parents=True,exist_ok=True)
    for ext in ['png','svg']:fig.savefig(a.figures/f'a5-workset.{ext}',dpi=170)
    plt.close(fig)
if __name__=='__main__':main()
