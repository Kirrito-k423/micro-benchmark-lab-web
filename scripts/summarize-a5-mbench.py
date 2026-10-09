#!/usr/bin/env python3
"""仅从完整且已校验的公开数据生成实验报告。"""
import argparse,json,statistics
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('--data',type=Path,default=Path('public/data/a5-mbench.json'));p.add_argument('--output',type=Path,default=Path('reports/a5-mbench-20261009.md'));a=p.parse_args()
d=json.loads(a.data.read_text())
if d['evidence']['receiverValidation']!='passed':raise ValueError('不能将首批或不完整数据写成正式报告')
def aggregate(rows,key):
    groups={}
    for r in rows:groups.setdefault(key(r),[]).append(r)
    return {k:dict(rs[0],p50=statistics.median(r['p50'] for r in rs),p95=statistics.median(r['p95'] for r in rs),members=rs) for k,rs in groups.items()}
alignment=aggregate(d['alignment'],lambda r:(r['dtype'],r['direction'],r['api'],r['windows'],r['gmOffset'],r['elements']))
simt=aggregate(d['simt'],lambda r:(r['impl'],r['op'],r['elements'],r['threads'],r['steps'],r['vf_calls']))
paired=aggregate(d['alignmentPaired'],lambda r:(r['dtype'],r['direction'],r['api'],r['windows'],r['gmOffset'],r['elements']))
def repeatability(groups):
    values=[]
    for r in groups.values():
        members=sorted(r['members'],key=lambda m:m['round'])
        if len(members)!=2:raise ValueError('轮次不完整')
        values.append(abs(members[1]['p50']/members[0]['p50']-1)*100)
    return statistics.median(values),max(values)
ar,amax=repeatability(alignment);sr,smax=repeatability(simt);pr,pmax=repeatability(paired)
lines=['# A5 DataCopy 对齐与 SIMT 微基准实测','',f"环境：{d['environment']['soc']}，{d['environment']['cann']}，单 AIV、本地 GM，{d['measuredDate']}。两类实验分别固定借用节点及设备 1；每个短批次前后检查整机 NPU 进程。发生占用的 chunk 排除，空闲后另目录补采。瞬时干扰仍不能完全排除。",'',
    'DataCopy 全量扫描：1496 配置 × 2 轮 × 12 计时样本 = 35904 个计时样本；固定分配边界复验：60 配置 × 2 轮 × 12 样本 = 1440 个计时样本。每轮每配置另有 12 个关闭计时对照与 2 次预热。SIMT：764 配置 × 2 轮 × 15 计时样本 = 22920 个计时样本，每轮每配置预热 2 次。共 60264 个正式计时样本。', '',
    '这里的汇总值是两轮 p50 的中位数，原始 tick、各轮 p50/p95 均保留在网页。GetSystemCycle 的 SYS_CNT 时钟依据记录在数据证据中。', '',
    f'逐配置两轮 p50 的绝对相对差异（以第 1 轮为分母）：DataCopy 全量扫描中位数 {ar:.3f}%、最大 {amax:.3f}%；固定分配复验中位数 {pr:.3f}%、最大 {pmax:.3f}%；SIMT 中位数 {sr:.3f}%、最大 {smax:.3f}%。这是本次重复性观察，不是误差置信界。SIMT 输出最大绝对误差为 {max(r["maxAbsError"] for r in d["simt"]):.8g}，所有样本均通过逐步 FP32 参考与保护区校验。', '',
    '## DataCopy：相同重载的长度边界','',
    '全量扫描出现明显轮间波动，因此另在同一进程里复用同一组存活 GM 分配，进行 15 个边界长度复验。下面使用固定分配结果：DataCopyPad(params)、GM 起点偏移 0、单窗口、loops=8192、batch=1，计时区间完成耗时除以调用数。百分比 =（边界后 1 元素的 p50 / 边界 p50 − 1）×100%。它是此条件下观测到的差异，不是通用的非对齐惩罚；微小差异要结合轮间波动。不同重载、地址起点或同步方式应在网页另行筛选。', '',
    '| dtype | 方向 | 元素边界 | 边界字节 | 对齐 p50 / μs | +1 元素 p50 / μs | 观测变化 |','|---|---|---:|---:|---:|---:|---:|']
for dtype,size in (('uint8',1),('float32',4)):
    for direction in ('GM_UB','UB_GM'):
        for n in (128,160,192,224,256):
            r=paired[(dtype,direction,'DataCopyPad_params',1,0,n)]
            next_=paired[(dtype,direction,'DataCopyPad_params',1,0,n+1)]
            lines.append(f"| {dtype} | {direction} | {n}→{n+1} | {n*size} B | {r['p50']:.5f} | {next_['p50']:.5f} | {(next_['p50']/r['p50']-1)*100:+.2f}% |")
lines+=['','完整长度扫描是 127–257 的每个整数元素数，共 131 个长度；uint8 对应 127–257 B，FP32 对应 508–1028 B。这是重复访问小工作集的延迟实验，不能当成整卡 HBM 吞吐上限。', '',
    '## SIMT：相同 FP32 工作量','',
    'Scalar、SIMT 和 SIMD 使用相同输入与迭代数，不开 fast-math。SIMT 在寄存器中完成每元素依赖链；SIMD Tensor API 每轮读写 UB 并同步。下表的 SIMT 是扫描线程数里的观测最短 p50，速度比同时包含实现方式与调用开销，不能直接解释为 ALU 单指令吞吐倍数。计时包含实现分派、计算调用和完成等待，不含 GM 准备与导出。', '',
    '| 运算 | 元素数 | 每元素次数 | Scalar / μs | SIMD / μs | 最短 SIMT / μs | 线程数 | 相对 Scalar | 相对 SIMD |','|---|---:|---:|---:|---:|---:|---:|---:|---:|']
for n,steps in ((32,1),(2048,1),(2048,128),(8192,1)):
    for op,label in enumerate(('加','减','乘','除')):
        scalar=simt[(0,op,n,32,steps,1)];vector=simt[(2,op,n,32,steps,1)]
        candidates=[r for r in simt.values() if r['impl']==1 and r['op']==op and r['elements']==n and r['steps']==steps]
        best=min(candidates,key=lambda r:r['p50'])
        lines.append(f"| {label} | {n} | {steps} | {scalar['p50']:.3f} | {vector['p50']:.3f} | {best['p50']:.3f} | {best['threads']} | {scalar['p50']/best['p50']:.2f}× | {vector['p50']/best['p50']:.2f}× |")
lines+=['','## VF 线程数与调用开销','',
    '最小线程体为每线程一次可观察 UB 写出，launch bound 等于实际线程数。1 次调用保留固定分派影响；128 次调用的每次值用于观察摊销后的完成开销。增量扣除同次数、同 V_S 等待的无 VF 循环，但仍包括 VF 调用、每线程写出与完成等待，不能拆成纯硬件线程创建时间。', '',
    '| 线程数 | 1 次 VF 完成 / μs | 128 次摊销 / μs·次⁻¹ | 相对无 VF 循环增量 / μs·次⁻¹ |','|---:|---:|---:|---:|']
control=simt[(4,0,32,32,1,128)]
for threads in (1,8,16,32,64,128,256,512,1024,2048):
    n=max(32,threads);one=simt[(3,0,n,threads,1,1)];many=simt[(3,0,n,threads,1,128)]
    lines.append(f"| {threads} | {one['p50']:.3f} | {many['p50']/128:.5f} | {(many['p50']-control['p50'])/128:.5f} |")
lines+=['',f"无 VF 的 128 次同步循环 p50 为 {control['p50']:.3f} μs，平均 {control['p50']/128:.5f} μs/次。网页另有 16/64 次调用，均显示实测原始值。", '',
    '## 证据和复现','',
    '- [交互页面](https://kirrito-k423.github.io/micro-benchmark-lab-web/?lab=alignment) 可切换 dtype、方向、窗口、地址偏移、轮次；算术页面可切换运算、shape、依赖链和参照实现；支持表格/图表联动、缩放与 CSV。',
    '- [AKL 测量代码与 SOP](https://github.com/Kirrito-k423/ascend-kernel-lab/tree/codex/a5-alignment-simt/examples/a5_mbench)。',
    '- 公开的 `public/data/a5-mbench.json` 包含原始 tick、参数、正确性与构建/manifest 哈希；完整机器日志留在本地忽略目录，未公开机器地址和内部路径。',
    '- 接收端 `scripts/import-a5-mbench.py` 校验矩阵配置、两轮覆盖、占用检查、构建源码哈希和样本，重新计算统计量；不接受不完整数据作为正式发布。',
    '- 在正式矩阵前修正了 SIMT 动态 UB 申请：dav-3510 TPipe 从动态 UB 区分配，启动按两个 FP32 缓冲和 32 B 计时区传入容量。故障与受扰实验未纳入本报告。',
    '- 本轮是 FP32 算术及小工作集 DataCopy；整数运算、跨卡竞争、整卡吞吐和 DeepEP E2E 性能不由这些数据证明。','']
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text('\n'.join(lines));print(a.output)
