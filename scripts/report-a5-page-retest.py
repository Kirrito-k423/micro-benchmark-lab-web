"""Generate figures and a reproducible report from the fully accepted A5 retest."""
import argparse
import json
import statistics
from collections import Counter
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
LABELS = {
    'power2': '单 AIV，32 B 倍增与页策略配对',
    'capacity': '旧单核容量配置',
    'alignment': '长度与地址对齐',
    'alignment-paired': '固定分配边界对照',
    'bandwidth': '多核带宽',
    'workset': '工作集加密扫描',
    'tail': '纯写窗口等待 / 末尾等待',
}


def aggregate(rows, legacy=False):
    groups = {}
    for r in rows:
        if r.get('phase', 'formal') != 'formal' or r.get('control'):
            continue
        key = (r.get('kind'), r['caseId'], r.get('allocation'), r.get('mode'))
        groups.setdefault(key, []).append(r)
    out = []
    for rs in groups.values():
        assert len(rs) == 2 and {r['round'] for r in rs} == {1, 2}, 'Two-round coverage'
        p50 = statistics.median(r['p50Us'] for r in rs)
        moved = rs[0].get('payload', rs[0].get('movedBytes'))
        out.append(rs[0] | dict(members=sorted(rs, key=lambda r: r['round']),
                               p50=p50, gbps=moved / p50 / 1000,
                               roundDifference=abs(rs[0]['p50Us'] - rs[1]['p50Us']) / p50 * 100))
    return out


def size(n):
    for unit, divisor in [('GiB', 2**30), ('MiB', 2**20), ('KiB', 2**10)]:
        if n >= divisor:
            return f'{n / divisor:g} {unit}'
    return f'{n:g} B'


def curve(points, direction, mode):
    return sorted((r for r in points if r['kind'] == 'power2'
                   and r['direction'] == direction and r['mode'] == mode
                   and r['api'] == 'DataCopy_count' and r['windows'] == r['batch'] == 1),
                  key=lambda r: (r['payload'], r['allocation']))


def save_figure(fig, folder, name):
    folder.mkdir(parents=True, exist_ok=True)
    for ext in ['png', 'svg']:
        path = folder / f'{name}.{ext}'
        fig.savefig(path, dpi=170)
        if ext == 'svg':
            path.write_text('\n'.join(s.rstrip() for s in path.read_text().splitlines()) + '\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--figures', type=Path, required=True)
    a = p.parse_args()
    db = json.loads(a.data.read_text())
    ev = db['evidence']
    assert ev['receiverValidation'] == 'passed' and ev['actualCounts'] == ev['expectedCounts']
    assert len({r['id'] for r in db['rows']}) == len(db['rows']) == 7166
    assert all(len(r['sampleUs']) == 12 and r['correctness'] for r in db['rows'])
    points = aggregate(db['rows'])
    env = db['environment']
    highlights = []
    for direction in ['GM_UB', 'UB_GM']:
        pair = {r['allocation']: r for r in curve(points, direction, 'ring') if r['payload'] == 131072}
        n, h = pair['normal'], pair['huge-first']
        highlights.append(f"{direction} 为 {n['gbps']:.3f} → {h['gbps']:.3f} GB/s（{n['p50']/h['p50']:.3f}×）")
    lines = ['# A5 DataCopy：大页条件下重测单核、对齐与多核', '',
             '单核对照确认：页策略的影响随工作集变化。固定 128 KiB payload、64 MiB ring、单窗口、batch=1，普通页 → 大页优先，' + '；'.join(highlights) + '。这仍是含循环与完成等待的有效 API 吞吐，未测物理 HBM 事务。小工作集的配对单独列出，不能套用大 ring 的加速比。', '',
             f"{db['measuredDate']} / {env['soc']} / {env['cann']}，实际查询到 {env['aiv_count']} AIV、{env['ub_bytes']} B UB。完成 7,166 个配置轮次、{ev['timedSamples']:,} 个正式计时样本，全部两轮覆盖、原始归档、输出校验与计时一致性通过接收端验收。旧数据独立保留。", '',
             '[交互曲线、参数、单轮样本与实测代码](https://kirrito-k423.github.io/micro-benchmark-lab-web/?lab=page-retest)', '',
             '## 单 AIV 从 32 B 起步', '',
             'payload 为一次 API 搬运的有效字节；32、64、128 B……逐次翻倍。count / params、batch=1、单窗口有 13 个大小，至 128 KiB。三个重载、两个方向、1/2 窗口、batch=1/8、小工作集 / ring 分开扫描，受 UB 与 API 字段约束裁剪。108 个非法组合记录为 skipped，不当作慢样本。', '',
             '普通页与大页优先的新配对使用同一 CANN、kernel、shape、loops、slots 和输入模式，两个轮次分别打乱顺序，每个配置重新申请数据。2 次预热、12 次正式 trace，另有 12 次关闭 trace 的正确性启动。输入与输出数据 GM 至少申请 2 MiB，其余记录/参数使用普通页。申请容量不等于实际访问工作集。', '',
             '![单 AIV 倍增吞吐](../figures/a5-page-retest-single.png)', '',
             '![单 AIV 平均完成耗时](../figures/a5-page-retest-latency.png)', '',
             '以下表固定 uint32、DataCopy(count)、单窗口、batch=1。p50 先按每轮 12 个样本计算，再取两轮 p50 中位数；吞吐以同一个汇总 p50 计算。速度比为普通页耗时 / 大页优先耗时，不用独立 best 值。', '']
    ratios = []
    for direction in ['GM_UB', 'UB_GM']:
        for mode in ['small', 'ring']:
            selected = curve(points, direction, mode)
            by_shape = {}
            for r in selected:
                by_shape.setdefault(r['payload'], {})[r['allocation']] = r
            assert len(by_shape) == 13 and sorted(by_shape) == [32 * 2**i for i in range(13)]
            lines += [f"### {direction} / {mode}", '',
                      '| payload | 实际 GM 工作集 | loops | 普通页 μs / call | 大页优先 μs / call | 普通页 GB/s | 大页优先 GB/s | 速度比 |',
                      '| --- | --- | --- | --- | --- | --- | --- | --- |']
            for payload, pair in sorted(by_shape.items()):
                n, h = pair['normal'], pair['huge-first']
                ratio = n['p50'] / h['p50']
                ratios.append(ratio)
                lines.append(f"| {size(payload)} | {size(h['workingSet'])} | {h['loops']} | {n['p50']:.5f} | {h['p50']:.5f} | {n['gbps']:.3f} | {h['gbps']:.3f} | {ratio:.3f}× |")
            lines += ['']
    lines += ['small 会重复访问同一小工作集，ring 按 slots 遍历。ABI 最多 65,536 slots：32 B ring 实际 2 MiB、64 B 为 4 MiB，逐渐到 64 MiB。缓存策略为 API 默认，未测缓存命中，不能把这些 ring 点称为冷 HBM；小请求曲线也不能证明物理带宽峰值。', '',
              '## 复测覆盖与波动', '',
              '| 实验 | 配置轮次 | 正式样本 | 两轮 p50 相对差异中位数 |',
              '| --- | --- | --- | --- |']
    for kind, label in LABELS.items():
        rs = [r for r in points if r['kind'] == kind]
        count = ev['actualCounts'][kind]
        lines.append(f"| {label} | {count:,} | {count * 12:,} | {statistics.median(r['roundDifference'] for r in rs):.3f}% |")
    lines += ['', '每个短任务开始和结束各检查整台 Host / 容器的 NPU 进程。占用快照没有其他 NPU 进程；两次快照之间的瞬时干扰未知。所有 12 个正式样本保留，包括慢样本。小幅差异需要结合两轮波动看，不将单个最优样本当成能力上限。', '',
              '## 多核、工作集与纯写', '',
              '![原条件与大页复测的多核和工作集曲线](../figures/a5-page-retest-multi.png)', '',
              '多核横轴是共同 kernel 使用的 AIV 数，使用完整同 stream ACL Event；窗口等待、核间同步、初始化及结果导出仍在该计时内。有效搬运字节除以共同时间，不相加各核独立峰值。旧曲线与新曲线使用同一 kernel 文件内容，Host 的输入/输出分配都从普通页改为大页优先。分配容量与新得到的物理页布局还可能变化，因此该旧/新比较是完整分配条件的复验。', '',
              '| 方向 / 分区读写 | 2 GiB 工作集、32 KiB × 2、64 AIV：旧普通页 TB/s | 新大页优先 TB/s | 达到本扫描峰值 95% 的最少 AIV | 本扫描峰值 TB/s |',
              '| --- | --- | --- | --- | --- |']
    legacy_bw = aggregate(json.loads((WEB / 'public/data/a5-bandwidth.json').read_text())['rows'], True)
    for direction in ['GM_UB', 'UB_GM']:
        rs = sorted((r for r in points if r['kind'] == 'bandwidth' and not r['sharedRead']
                     and r['direction'] == direction and r['requestedRing'] == 2**31
                     and r['tileBytes'] == 32768 and r['batch'] == 2), key=lambda r: r['cores'])
        peak = max(r['gbps'] for r in rs)
        n95 = min(r['cores'] for r in rs if r['gbps'] >= .95 * peak)
        new = next(r for r in rs if r['cores'] == 64)
        old = next(r for r in legacy_bw if r['direction'] == direction and not r['sharedRead']
                   and r['requestedRing'] == 2**31 and r['tileBytes'] == 32768 and r['batch'] == 2 and r['cores'] == 64)
        lines.append(f"| {direction} | {old['gbps']/1000:.3f} | {new['gbps']/1000:.3f} | {n95} | {peak/1000:.3f} |")
    lines += ['', '95% 只指当前离散扫描的观测峰值，不能叫作芯片理论带宽的 95%。同址读的有效字节包含各核反复读取同一数据，另列为 shared_read；不能直接与分区遍历的 HBM 流量比较。', '',
              '工作集曲线仍固定 64 AIV、32 KiB × 2；128 MiB 附近按原扫描加密。大页复测没有将两端压成一个“5 → 2 TB/s”结论：图中保留每个大小及旧/新条件。写实验保留全部目标与保护区 oracle。', '',
              '| 纯写 / 64 AIV / 1 GiB | Windowed TB/s | Tail TB/s | Tail 相对速度 |', '| --- | --- | --- | --- |']
    tails = [r for r in points if r['kind'] == 'tail' and r['cores'] == 64]
    for tile, batch in sorted({(r['tileBytes'], r['batch']) for r in tails}):
        pair = {r['mode']: r for r in tails if r['tileBytes'] == tile and r['batch'] == batch}
        w, t = pair['windowed'], pair['tail']
        lines.append(f"| {size(tile)} × {batch} | {w['gbps']/1000:.3f} | {t['gbps']/1000:.3f} | {w['p50']/t['p50']:.3f}× |")
    lines += ['', 'Tail 与 Windowed 在一个配置中共用分配，每次预热和计时随机先后。Tail 只将循环中的每窗 MTE3→Scalar 等待移到末尾，UB 数据保持不变；仍等待写入完成再结束核计时，并保留完整 ACL Event，不把异步提交时间当成完成时间。', '',
              '## 页策略、同步与归因边界', '',
              '- NORMAL_ONLY 固定普通页；HUGE_FIRST 优先大页但可以回退。HUGE_ONLY 的 32 B / 128 KiB / 非对齐冒烟通过，只证明那些申请成功，不能证明所有正式 HUGE_FIRST 申请都未回退。见 [CANN 9.1 分配策略](https://www.hiascend.com/doc_center/source/en/CANNCommunityEdition/910/API/runtimeapi/aclpythondevg_01_0962.html)。',
              '- 页策略改变可以影响翻译覆盖和物理地址布局；本轮没有测 TLB miss、实际页表、bank / 通道映射或物理 HBM 事务，不能确定唯一硬件机制。核间逻辑地址不重叠也不排除共享内存资源冲突。',
              '- 旧单核容量 A5 用 CANN 9.2.0，本轮为 9.1.0，且小请求有新的申请容量下限。旧容量 / 新容量不是仅切换页策略的因果对照。新的 power2 普通页 / 大页配对才是同版本、同几何参数比较。',
              '- 单 AIV 使用 trace.Mark(2)→trace.Mark(3)，包含提交、地址计算、完成等待和排空，除以 loops × batch；初始化和导出在区间外。双窗口平均完成成本不是独立请求的尾延迟。每组 WindowEvent 等待保证目标窗口可安全复用，不能直接删掉。见 [CANN 9.1 核内同步](https://www.hiascend.com/document/detail/en/CANNCommunityEdition/910/API/ascendcopapi/docs/en/api/SIMD-API/basic_api/sync_control/intra_core_sync/intra_core_synchronization_capability_overview.md)。',
              '- 本轮是 A5 单设备本地 GM 的无其他进程快照条件；A3、跨设备/跨节点通信与真实 DeepEP 算子收益不从本轮推断。原 DataCopy、SIMD 和通信归档未覆盖。', '',
              '## 复现与接收验收', '',
              '[编译时的固定源码内容](https://github.com/Kirrito-k423/micro-benchmark-lab-web/tree/d5ba9f0/experiments/a5_page_retest) 保留原 kernel / oracle；native Host 增加分配策略参数和 2 MiB 申请下限，C++ Host 的输入/输出策略改为 HUGE_FIRST。网页逐点源代码面板绑定实测二进制与文件 SHA-256。编译后才提交源码的 Git commit 只是相同文件内容的索引，不冒充当时记录的全仓 commit。', '',
              '计划脚本曾将空对照的有效搬运字节 0 当成目标工作量，C++ 参数检查在进入 kernel 前拒绝了该批。失败归档保留；从旧记录的 groups × cores × tile × batch 恢复 56 个控制配置轮次的原工作量，控制批次采用新 key（-control）与新输出目录。所有 payload 配置、已通过的单核/对齐配置、kernel 和二进制保持不变。接收器核对两个冻结计划的全部差异，只允许这项修正；源码归档仍绑定实际编译时内容。[当前复现脚本](https://github.com/Kirrito-k423/micro-benchmark-lab-web/tree/codex/a5-mbench-results/experiments/a5_page_retest) 已修复生成规则，可以完整再生修正后的参数矩阵。', '',
              '先查实际芯片、AIV、UB 与匹配 CANN 的 SYS_CNT 频率，再生成计划。借用机器只在整台 Host 和容器无其他 NPU 进程时运行；短批次独立输出目录，未知结果只查询，不重放。', '',
              '```bash',
              'cd experiments/a5_page_retest',
              'python3 plan.py --web-root /path/to/micro-benchmark-lab-web \\',
              f"  --ub-bytes {env['ub_bytes']} --aiv-count {env['aiv_count']} --soc {env['soc']} \\",
              f"  --clock-hz {env['clockHz']} --clock-source '{env['clockSource']}' \\",
              '  --output execution-plan.json',
              'source /usr/local/Ascend/cann/set_env.sh',
              'bash build.sh',
              '# 用全新目录执行一个短批；完整计划内所有 key 各执行一次。',
              'python3 run_stage.py --device 1 --key power2-r1-normal-c000 \\',
              '  --plan execution-plan.json --output results/fresh-stage',
              '```', '',
              '接收器验证任务终态与退出码、原 tar SHA-256 与逐文件字节、四份占用记录、所有源码/二进制、精确参数和矩阵；native 重新 decode 每个原始 trace 并与样本 tick 比较，校验全部预热/trace/关闭 trace 的正确性；C++ 核对所有核记录、ACL 时间、字节覆盖与完整 oracle。核持续 ticks 不得超出完整 kernel / Host 时间。', '',
              '```bash',
              'uv run --no-project --with numpy python scripts/import-a5-page-retest.py \\',
              '  --runs /absolute/private/a5-page-retest-20261010 \\',
              '  --output public/data/a5-page-retest.json',
              'uv run --no-project --with matplotlib python scripts/report-a5-page-retest.py \\',
              '  --data public/data/a5-page-retest.json \\',
              '  --report public/reports/a5-page-retest-20261010.md --figures public/figures',
              'node scripts/check-measurement-code.mjs', '```', '',
              '`--partial` 仅本地检查，完整覆盖与正确性通过后才发布。公开 JSON 保留参数、12 个样本、持续 tick、页策略与哈希，完整日志、机器身份、地址、任务凭据及绝对时间留在私有 results。', '',
              f"计划 SHA-256：`{ev['planSha256']}`；源码打包 SHA-256：`{ev['sourceArchiveSha256']}`。", '']
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text('\n'.join(lines))

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'axes.spines.top': False, 'axes.spines.right': False,
                         'font.size': 10, 'svg.hashsalt': 'a5-page-retest'})
    for metric, name, ylabel in [('gbps', 'single', 'Effective GB/s'), ('p50', 'latency', 'Average completion us / call')]:
        fig, axes = plt.subplots(2, 2, figsize=(13, 8), layout='constrained')
        for i, direction in enumerate(['GM_UB', 'UB_GM']):
            for j, mode in enumerate(['small', 'ring']):
                ax = axes[i, j]
                for policy, color in [('normal', '#e77d42'), ('huge-first', '#16756b')]:
                    rs = [r for r in curve(points, direction, mode) if r['allocation'] == policy]
                    ax.plot([r['payload'] for r in rs], [r[metric] for r in rs], 'o-', ms=4, color=color, label=policy)
                ax.set_xscale('log', base=2)
                ax.set(title=f'{direction} / {mode} / 1 window / batch=1', xlabel='Payload bytes, doubling from 32 B', ylabel=ylabel)
                ax.grid(alpha=.18)
                ax.legend(fontsize=9)
        fig.suptitle('A5 single AIV / DataCopy(count) / uint32 / 2 rounds / minimum backing 2 MiB')
        save_figure(fig, a.figures, 'a5-page-retest-' + name)
        plt.close(fig)
    legacy_ws = aggregate(json.loads((WEB / 'public/data/a5-workset.json').read_text())['rows'], True)
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), layout='constrained')
    for i, direction in enumerate(['GM_UB', 'UB_GM']):
        for source, title, color in [(legacy_bw, 'Old normal', '#e77d42'), (points, 'New huge-first', '#16756b')]:
            rs = sorted((r for r in source if r.get('kind', 'bandwidth') == 'bandwidth'
                         and r['direction'] == direction and not r['sharedRead']
                         and r['requestedRing'] == 2**31 and r['tileBytes'] == 32768 and r['batch'] == 2), key=lambda r: r['cores'])
            axes[i, 0].plot([r['cores'] for r in rs], [r['gbps']/1000 for r in rs], 'o-', ms=4, color=color, label=title)
        for source, title, color in [(legacy_ws, 'Old normal', '#e77d42'), (points, 'New huge-first', '#16756b')]:
            rs = sorted((r for r in source if r.get('kind', 'workset') == 'workset'
                         and r['direction'] == direction and not r['sharedRead']), key=lambda r: r['actualRing'])
            axes[i, 1].plot([r['actualRing']/2**20 for r in rs], [r['gbps']/1000 for r in rs], 'o-', ms=3, color=color, label=title)
        axes[i, 0].set(title=f'{direction} / 2 GiB ring / 32 KiB x 2', xlabel='AIV cores', ylabel='Effective TB/s, complete kernel')
        axes[i, 1].set_xscale('log', base=2)
        axes[i, 1].set(title=f'{direction} / 64 AIV / 32 KiB x 2', xlabel='Actual GM working set, MiB', ylabel='Effective TB/s, complete kernel')
        for ax in axes[i]:
            ax.legend(fontsize=9)
            ax.grid(alpha=.18)
    fig.suptitle('Allocation conditions changed; kernel content and completion boundaries retained')
    save_figure(fig, a.figures, 'a5-page-retest-multi')
    plt.close(fig)
    print('Generated accepted report and 3 figures:', len(points), 'two-round payload points')


if __name__ == '__main__':
    main()
