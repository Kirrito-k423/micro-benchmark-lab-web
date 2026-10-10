"""Rebuild the paired completion-policy report and figures from accepted device data."""
import argparse,json,statistics
from pathlib import Path

def summarize(db):
    groups={}
    for r in db['rows']:
        if r['phase']=='formal':groups.setdefault((r['caseId'],r['mode']),[]).append(r)
    return {k:rs[0]|dict(p50Us=statistics.median(r['p50Us'] for r in rs),
        gbps=rs[0]['movedBytes']/statistics.median(r['p50Us'] for r in rs)/1000,
        samples=rs) for k,rs in groups.items()}

def paired_ratios(w,t):
    pairs=[]
    for baseline in w['samples']:
        tail=next(r for r in t['samples'] if r['round']==baseline['round'])
        pairs += [a/b for a,b in zip(baseline['eventMs'],tail['eventMs'])]
    return pairs

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',type=Path,required=True);p.add_argument('--report',type=Path,required=True);p.add_argument('--figures',type=Path,required=True)
    a=p.parse_args();db=json.loads(a.data.read_text());assert db['evidence']['receiverValidation']=='passed'
    points=summarize(db);tails=sorted([r for (_,m),r in points.items() if m=='tail'],key=lambda r:(r['requestedRing'],r['cores'],r['tileBytes'],r['batch']))
    repeat=[abs(rs[0]['p50Us']-rs[1]['p50Us'])/statistics.mean(r['p50Us'] for r in rs)*100 for rs in [r['samples'] for r in points.values()]]
    lines=['# A5 DataCopy 纯写：双窗口等待与仅末尾完成','',
        '循环内等待会限制小提交；放宽显式在途深度后，能否突破原多核纯写曲线，要按同配置逐点比较。源 UB 在循环内保持不变，两种实现共享同一进程的 GM 分配、地址、参数与源 pattern，每对样本随机先后次序。','',
        f"{db['measuredDate']}，{db['environment']['soc']} / {db['environment']['cann']}，{db['environment']['aiv_count']} 个可用 AIV。40 配置 × 两轮，960 正式计时样本、160 预热样本；另有 8 组冒烟、24 计时及 8 预热样本。每次启动校验完整写目标、128 B 保护区与各核记录。",'',
        '![同条件纯写对照](../public/figures/a5-store-tail.png)','',
        '## 同条件对照','',
        '下表 p50 为两轮各自 p50 的中位数；GB/s = 实际有效字节 / 该区间。速度比 = 双窗口 p50 / 末尾完成 p50。配对比中位数直接由同轮、同序号的 24 对原始样本计算，两种汇总口径分别标明。所有慢样本保留。','',
        '| GM 工作集 | AIV | tile × batch | 双窗口 GB/s | 末尾完成 GB/s | p50 速度比 | 配对比中位数 |',
        '| --- | --- | --- | --- | --- | --- | --- |']
    for t in tails:
        w=points[(t['caseId'],'windowed')]
        lines.append(f"| {t['actualRing']/2**30:g} GiB | {t['cores']} | {t['tileBytes']//1024} KiB × {t['batch']} | {w['gbps']:.2f} | {t['gbps']:.2f} | {w['p50Us']/t['p50Us']:.4f}× | {statistics.median(paired_ratios(w,t)):.4f}× |")
    maximum=db['environment']['aiv_count']
    lines+=['','## 对约 2 TB/s 的解释','']
    for ring in [1<<30,2<<30]:
        rs=[r for r in tails if r['requestedRing']==ring and r['cores']==maximum]
        small=next(r for r in rs if r['tileBytes']==4096 and r['batch']==1);w=points[(small['caseId'],'windowed')]
        changes=[(points[(r['caseId'],'windowed')]['p50Us']/r['p50Us']-1)*100 for r in rs if not(r['tileBytes']==4096 and r['batch']==1)]
        lines.append(f"- {ring/2**30:g} GiB 工作集，{maximum} AIV：4 KiB × 1 从 {w['gbps']/1000:.3f} 提高到 {small['gbps']/1000:.3f} TB/s（{w['p50Us']/small['p50Us']:.3f}×）。其余三组的速度变化为 {min(changes):+.2f}%～{max(changes):+.2f}%。仅末尾完成的最高观测点为 {max(r['gbps'] for r in rs)/1000:.3f} TB/s。")
    lines+=['','这验证了小提交的循环内等待成本。对于已按 32/64 KiB 成组提交的纯写路径，若两种策略吞吐接近，显式窗口等待不足以解释其与 4 TB/s 规格的差距。该实验没有测物理 HBM 事务、内存控制器利用率或 bank 冲突，不能将观测峰值称为硬件上限，也不能据此断定剩余原因。',
        '', '参考规格来自 [Atlas 950 SuperPoD](https://www.hiascend.com/hardware/cluster?tag=900ai) 的最大 4.0 TB/s 片上内存带宽；本实验是实际 Ascend950DT_9582 上 AIV 纯写有效 payload 口径，未用物理事务计数器核对利用率。',
        '',f"两轮同配置 p50 相对差异（除以两轮平均值）中位数 {statistics.median(repeat):.3f}%，最大 {max(repeat):.3f}%；这描述重复性，不是置信区间。",'',
        '## 代码与完成语义','',
        '双窗口：每组连续提交 batch 个 DataCopy(count)，设置对应 MTE3_S 事件，复用窗口前 WaitFlag，末尾排空两组。仅末尾完成：删除循环内 SetFlag 和 WaitFlag，最后一次 SetFlag/WaitFlag<MTE3_S>。不能只删 Wait 而反复设置尚未消费的同一事件。该变体只用于 UB→GM 且源 UB 已初始化、循环内不再修改；不适用于需要覆盖 UB 的读取或生产者更新源数据。',
        '', '两种模式都保留两个 UB 源窗口、地址分区与游标、起止 SyncAll、逐核 SYS_CNT 和记录导出。WindowEvent 是核内管线事件；SyncAll 才同步参与本次 launch 的 AIV。吞吐用同 stream ACL Event 包围完整 kernel，包含初始化、同步和导出；Host 重置、下载与 oracle 在区间外。未扣空循环、未相加单核峰值。',
        '', '[CANN 9.1 SetFlag/WaitFlag 语义](https://www.hiascend.com/document/detail/en/CANNCommunityEdition/910/API/ascendcopapi/docs/en/api/SIMD-API/basic_api/sync_control/intra_core_sync/SetFlag_WaitFlag_ISASI.md)：MTE3_S 的来源是 MTE3、目的为 Scalar；完成前序 MTE3 访存后置位，Scalar 等待并消费事件。',
        '', '1 GiB / 2 GiB 工作集为本机平台配置 128 MiB L2 的 8 / 16 倍，实际搬运约 2 GiB / 4 GiB。每组地址按 tile × batch 前进，各核写分区不重叠。持续提交仍受硬件队列回压限制。',
        '', '## 不重叠地址与 bank / 通道竞争','',
        '不同地址仍可能映射到同一内存 bank、控制器、通道或 L2 资源。各 AIV 的 UB 为私有存储；跨核 GM 资源竞争与单核 UB bank 冲突不是同一层问题。本轮未改变地址映射，不能定位 bank 冲突。后续需要固定搬运与提交方式，单独扫描基址偏移、核间步距、分区轮转，并结合对应芯片的映射或性能计数器验证；仅看到地址不同或带宽较低均不足以下结论。',
        '', '[950 / 架构 3510 的 UB bank 说明](https://www.hiascend.com/document/detail/en/CANNCommunityEdition/910/programug/Ascendcopdevg/docs/en/guide/operator_practice/simd_operator_optimization/memory_access/avoid_ub_bank_conflict/avoid_bank_conflict_npu_arch_3510.md)给出了不同地址落在同一 bank 的例子；这些 Vector / UB 规则不能直接当作 GM 通道映射。',
        '', '## 复现与证据','',
        f"[固定源码](https://github.com/Kirrito-k423/ascend-kernel-lab/tree/{db['evidence']['sourceCommit']}/examples/a5_store_tail) · [交互曲线、配对样本与逐点源码](https://kirrito-k423.github.io/micro-benchmark-lab-web/?lab=store-tail)",
        '', '先确认整机 Host 与容器 npu-smi 无其他 NPU 进程。两轮独立顺序，每次只跑一组 case-id；按实际占用插空，输出目录必须新建，原始失败保留。最大核数、UB、L2 由匹配环境查询；SYS_CNT 时钟依据显式提供。源码和二进制哈希、plan、原始毫秒、全输出 oracle、Host/容器占用前后与任务退出/归档哈希由接收器再次验证。占用快照不能证明瞬时干扰或整个 fabric 独占。',
        '', '```bash',
        'source /usr/local/Ascend/cann/set_env.sh',
        'cmake -S examples/a5_store_tail -B build-store-tail',
        'cmake --build build-store-tail -j2',
        'python3 examples/a5_store_tail/prepare.py --device 1 --clock-hz 1000000000 --clock-source "CANN 9.1 GetSystemCycle: Ascend950PR/950DT SYS_CNT 1 GHz"',
        'python3 examples/a5_store_tail/run.py --round 1 --smoke --warmup 1 --samples 3 --output results/smoke-new',
        '# 根据空闲窗口逐个跑 plan 中的 case-id 0..19，每轮各一次',
        'python3 examples/a5_store_tail/run.py --round 1 --case-id 0 --output results/r1-c00-new',
        'python3 examples/a5_store_tail/run.py --round 2 --case-id 0 --output results/r2-c00-new',
        '```','',
        '设备 ELF 已从实测二进制提取。当前工具对该目标指令返回 `<not available>`；因此未以反汇编确认隐式插入的同步或实际指令数，公开结论限于两种显式完成策略的同条件执行结果。','',
        '完整原始文件与日志保存在私有 results；公开 JSON 保留原始 ACL 毫秒、各核持续 tick、逐启动 oracle、配对次序与证据哈希。原始设备绝对时间、地址、主机名和日志不公开。','']
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text('\n'.join(lines))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False,'svg.hashsalt':'a5-store-tail'})
    fig,axes=plt.subplots(1,2,figsize=(14,5.3),layout='constrained')
    presets=[(4096,1),(4096,8),(32768,2),(65536,1)];colors=['#16756b','#e77d42','#875aa6','#8a9db0']
    for (tile,batch),color in zip(presets,colors):
        for mode in ['windowed','tail']:
            rs=sorted([r for r in points.values() if r['mode']==mode and r['requestedRing']==1<<30 and r['tileBytes']==tile and r['batch']==batch],key=lambda r:r['cores'])
            axes[0].plot([r['cores'] for r in rs],[r['gbps']/1000 for r in rs],color=color,linestyle='-' if mode=='tail' else '--',marker='o' if mode=='tail' else '.',label=f'{tile//1024} KiB x {batch} / {mode}')
    axes[0].set(title='1 GiB workset / ~2 GiB payload',xlabel='AIV cores',ylabel='Effective TB/s (full kernel)');axes[0].legend(fontsize=8,ncol=2);axes[0].grid(alpha=.15)
    xs=[];baseline=[];tail=[]
    for ring in [1<<30,2<<30]:
        for tile,batch in presets:
            t=next(r for r in tails if r['requestedRing']==ring and r['cores']==maximum and (r['tileBytes'],r['batch'])==(tile,batch));w=points[(t['caseId'],'windowed')]
            xs.append(f'{ring/2**30:g} GiB\n{tile//1024}K x {batch}');baseline.append(w['gbps']/1000);tail.append(t['gbps']/1000)
    x=list(range(len(xs)));axes[1].bar([v-.19 for v in x],baseline,.38,label='Windowed',color='#e77d42');axes[1].bar([v+.19 for v in x],tail,.38,label='Tail only',color='#16756b')
    axes[1].set(title=f'{maximum} AIV / paired policy comparison',ylabel='Effective TB/s (full kernel)',xticks=x,xticklabels=xs);axes[1].legend();axes[1].grid(axis='y',alpha=.15)
    fig.suptitle('A5 UB-to-GM: same addresses, different completion cadence',fontsize=14)
    a.figures.mkdir(parents=True,exist_ok=True)
    for ext in ['png','svg']:fig.savefig(a.figures/f'a5-store-tail.{ext}',dpi=170)
    plt.close(fig)

if __name__=='__main__':main()
