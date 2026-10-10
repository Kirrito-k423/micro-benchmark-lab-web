# A5 DataCopy 页策略复测

保留既有 DataCopy kernel 与 oracle，显式控制 Host 分配：native 输入与输出数据 GM 使用 normal / huge-first / huge-only；记录及参数仍用普通页。native 数据申请至少 2 MiB，让 32 B 的小请求也能在符合大页申请条件的 backing 上测量。**分配容量不等于实际工作集**。HUGE_FIRST 仍可能回退，HUGE_ONLY 冒烟只证明对应冒烟申请成功。

`plan.py` 将单 AIV 的有效 payload 从 32 B 开始逐次翻倍，依据运行时 UB 容量裁剪：单窗口 batch=1 的 count / params 至 128 KiB；双窗口或 batch=8 的上限更小。旧 DataCopyPad 的 uint16 字节 blockLen 不容纳 64 KiB，非法组合保存为 skipped。不把分块完成当作一个超大单次 API shape。

两方向、三个重载、1/2 UB 窗口、batch=1/8、小工作集和 ring 分开。ring 的实际 slots 受 ABI 限制：32 B 最多触达 2 MiB；随着 shape 增大可触达 64 MiB。每轮独立随机顺序，普通页 / 大页优先用相同参数、新分配对照，2 次预热、12 个 trace 样本及 12 个关闭 trace 的正确性对照。

旧容量、1496 个长度/地址对齐配置、60 个固定分配边界配置、多核、工作集和纯写同步配置在大页优先条件下重测。旧计时不覆盖。历史容量的 CANN 9.2.0 与本轮 9.1.0 不同，不能将其差异仅归因于页策略；单核新矩阵的普通页 / 大页对照使用同一 CANN 和 kernel。

## 执行

复制本目录到独立实验目录。先确认整台 Host 与容器空闲，以实际设备能力生成计划：

```bash
python3 plan.py --web-root /path/to/measurement-web \
  --ub-bytes 221184 --aiv-count 64 --soc Ascend950DT_9582 \
  --clock-hz 1000000000 \
  --clock-source 'CANN GetSystemCycle: Ascend950PR/950DT SYS_CNT 1 GHz' \
  --output execution-plan.json
bash build.sh
python3 run_stage.py --key power2-r1-normal-c000 --device 1 --output results/new-stage
```

示例环境参数来自本次实际设备；换芯片须重新核实 profile、arch、时钟依据与容量。每个短任务使用新的输出目录；任务 ID/命令先保存，未知结果只查询。借用预约在已知终态后释放。不结束他人进程，不修改系统、网络、驱动和功耗设置。

接收器 `scripts/import-a5-page-retest.py` 验证全部任务退出码、原始 tar 与逐文件字节、四份占用记录、精确参数与矩阵、源码/二进制、逐启动 oracle、原始 trace / ACL 时间、核记录和两轮覆盖。`--partial` 只供本地开发检查；公开发布须完整验收。

## 计时

单 AIV 使用 trace.Mark(2) → trace.Mark(3)，含提交、地址计算、窗口等待与最终排空，除以 loops × batch。UB 初始化、读出结果和 Host 比较在区间外。它是每调用平均完成成本，双窗口结果不是独立请求的尾延迟。

多核、工作集和纯写用共同 ACL Event 包围完整 kernel，保留每核循环 SYS_CNT 持续 ticks。每次启动验证完整写目标 / 最后两组完整读窗口、128 B 保护区和所有核记录。Tail / Windowed 共用一次 GM 分配并随机顺序。

有效字节吞吐不等于 HBM 物理事务。本轮没有测缓存命中、实际页表、TLB miss 或 bank / 通道映射。完整设备日志、地址、任务凭据、绝对时间和原始归档留在私有 results。
