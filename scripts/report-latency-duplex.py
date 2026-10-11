"""Summarize fully received measurements; paired directions share one duration."""
import argparse, json, statistics
from pathlib import Path
WEB = Path(__file__).resolve().parents[1]
median = statistics.median
def size(n):
    for u, name in [(2**30,'GiB'),(2**20,'MiB'),(1024,'KiB')]:
        if n >= u: return f'{n/u:g} {name}'
    return f'{n} B'
def summary(rows, **filters):
    rs = [r for r in rows if not r['control'] and all(r.get(k) == v for k,v in filters.items())]
    assert len(rs) == 2 and {r['round'] for r in rs} == {1,2}, filters
    return median(r['p50'] for r in rs), median(r['p95'] for r in rs)
def report(data, output):
    assert data['evidence']['receiverValidation'] == 'passed'
    rows=data['rows']; e=data['evidence']; env=data['environment']
    assert len(rows)==1232 and e['timedSamples']==e['traceOffSamples']==14784
    text=['# A5 DataCopy：单请求完成延迟与独立地址双向带宽', '',
        f"{data['measuredDate']} · {env['soc']} · {env['cann']} · SYS_CNT {env['clockHz']/1e9:g} GHz。", '',
        '完整两轮接收验收通过：864 个单请求配置轮次、216 个只读/只写/双向配置轮次、152 个空协议对照；合计 1,232 个配置轮次，14,784 个正式 trace 样本和同量 trace-off。预热另外保存。', '',
        '## 测量定义', '',
        '- 单请求：每个启动只完成一次请求，32 B 每次翻倍至 4 MiB，共 18 点。SYS_CNT 包含提交、窗口复用与最后 DMA 完成；初始化和结果导出在区间外。完整 kernel 的 trace 开/关 ACL 时间另外保留。没有把重复请求的平均耗时标成单次延迟。',
        '- 双向：GM→UB 与 UB→GM 同一 kernel 先提交、后分别等待；两方向的 GM 和 UB 独立，每方向各两窗口。只读、只写、同时读写、空协议共用同一对 GM 分配，启动次序随机。',
        '- 双向吞吐：读字节/T、写字节/T、两者之和/T 使用同一个完整 trace-off ACL Event 时间 T。包括初始化、核间同步、排空与保留读窗口导出；不相加独立模式或不同核的峰值。',
        '- 页策略：数据输入/输出同时使用 NORMAL_ONLY 或 HUGE_FIRST。每个配置重新申请 GM；大页优先可回退，本实验没有读取物理页表。默认 L2；不能等同于冷 HBM 流量。', '',
        '以下表格取两轮各自 p50 的中位数，p95 同样先在每轮 12 次正式样本内计算再取中位数。p95 是有限样本的观察值，不能代表长期生产尾延迟。完整参数、两轮所有样本和空协议对照保存在公开 JSON。', '',
        '## 单 AIV、两窗口：一次完整请求的延迟', '',
        '![单请求延迟曲线](../figures/a5-latency-20261011.svg)', '',
        'count / params 最大 64 KiB tile，Pad 最大 32 KiB tile。4 MiB 是由多个 tile 完成的请求，不是 UB 中一次 API 的 4 MiB shape。', '']
    for api in ['DataCopy_count','DataCopy_params','DataCopyPad_params']:
        text += [f'### {api}', '', '| 完整请求 | 普通页读 μs | 大页优先读 μs | 普通页写 μs | 大页优先写 μs |', '|---|---:|---:|---:|---:|']
        for b in [1<<i for i in range(5,23)]:
            values=[summary(rows,kind='latency',api=api,bytes=b,windows=2,direction=direction,allocation=policy)[0]
                for direction in ['GM_UB','UB_GM'] for policy in ['normal','huge-first']]
            text.append('| '+size(b)+' | '+' | '.join(f'{v:.4f}' for v in values)+' |')
        text += ['']
    text += ['## 64 AIV、32 KiB tile：同一分配上的配对比较', '',
        '![独立地址双向带宽](../figures/a5-duplex-20261011.svg)', '',
        '工作集容量指每方向；读写同时打开时，读、写各请求 4 GiB，合计 8 GiB。独立模式每次请求 4 GiB。小范围模式每核保留两个 tile，共 4 MiB 每方向。', '',
        '| 每方向工作集 | 页策略 | 只读 TB/s | 只写 TB/s | 同时读 TB/s | 同时写 TB/s | 同时合计 TB/s | 同时共同 T μs |', '|---|---|---:|---:|---:|---:|---:|---:|']
    for ring in [64*2*32768,128*2**20,2**31]:
        for policy in ['normal','huge-first']:
            common=dict(kind='duplex',cores=64,tileBytes=32768,requestedWorkingSet=ring,allocation=policy)
            read=summary(rows,mode='read',**common)[0]; write=summary(rows,mode='write',**common)[0]; both=summary(rows,mode='duplex',**common)[0]
            payload=next(r['readBytes'] for r in rows if r['kind']=='duplex' and r['mode']=='duplex' and all(r[k]==v for k,v in common.items()))
            text.append(f'| {size(ring)} | {policy} | {payload/read/1e6:.4f} | {payload/write/1e6:.4f} | {payload/both/1e6:.4f} | {payload/both/1e6:.4f} | {2*payload/both/1e6:.4f} | {both:.3f} |')
    text += ['', '同时读写的读/写请求量相等，两个方向展示相同的“字节/共同完成时间”，这是该口径的定义，并不表示两方向真实精确完成时刻相同。核内 Scalar 读/写完成观察戳只作为完成上界保存，不能作为独立方向带宽分母。', '',
        '1 / 16 / 64 AIV、4 / 32 KiB tile、三种工作集、两页策略和两轮的全部对照可以在交互页面筛选。页面按同一共同时间分别列读、写、合计，并联动单轮样本和固定源码。', '',
        '## 正确性与证据边界', '',
        '每次分配有独立 untimed 全 tile 读取 oracle。每个正式启动验证完整写目标或未改写目标、最后两个完整保留读窗口和 128 B guard；早先被覆盖的 timed read tile 不逐个导出。Host 和容器整机占用在短任务前后均为空，两次快照之间的瞬时干扰未知。', '',
        '独立地址不能排除共享缓存、内存 bank / 通道或其他资源竞争。本实验没有采集 bank/TLB/cache/HBM 计数器，不把差异归因为已确认的 bank conflict，也不宣称硬件始终完全重叠。空协议保留原值、不盲目扣除。', '',
        f"SYS_CNT 换算依据匹配目标芯片与 CANN 版本的[官方 GetSystemCycle 文档]({e['clockDocumentUrl']})。核内区间与共同 ACL Event / Host 区间交叉核对；公开 ticks 是各核相对值，不拼接不同核时钟。", '',
        '## 复现与源码绑定', '',
        f"[固定源码](https://github.com/Kirrito-k423/micro-benchmark-lab-web/tree/{e['sourceCommit']}/experiments/a5_latency_duplex)；运行参数、构建步骤和 oracle 范围见目录 README。先确认整机空闲并持有自己的短预约，按固定 execution-plan.json 的四个冒烟阶段验证，再跑两轮正式短批。输出目录必须全新。", '',
        '```bash', 'python3 plan.py', 'bash build.sh', 'python3 run_stage.py --device DEVICE --key PLAN_STAGE --output FRESH_OUTPUT', '```', '',
        '接收端拒绝未知/非终态任务、缺失覆盖、归档或样本哈希不符、错配源码/构建、错误输出、非法时钟和占用。配置、计时样本、源码绑定和构建凭据全部绑定；原始归档私有保存。', '',
        f"- 源码 commit：`{e['sourceCommit']}`", f"- 源码归档 SHA-256：`{e['sourceArchiveSha256']}`", f"- 计划 SHA-256：`{e['planSha256']}`"]
    for key,b in e['sourceBindings'].items():text.append(f"- {key.split('/')[1]} 二进制 SHA-256：`{b['binaryHash']}`")
    output.parent.mkdir(parents=True,exist_ok=True); output.write_text('\n'.join(text)+'\n')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data',type=Path,default=WEB/'public/data/a5-latency-duplex.json');p.add_argument('--output',type=Path,default=WEB/'public/reports/a5-latency-duplex-20261011.md');a=p.parse_args();report(json.loads(a.data.read_text()),a.output)
