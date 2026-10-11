# A5 DataCopy 单请求延迟与独立地址双向带宽

本目录保存实验实现和固定计划；实机状态以对应公开数据的 receiverValidation 与报告为准。源码存在或构建成功本身不构成 NPU 性能结论。

单请求：32 B 每次翻倍至 4 MiB，共 18 点。count、params、Pad；读/写、1/2 个 UB 窗口；NORMAL_ONLY/HUGE_FIRST；两轮，每轮 2 次预热和 12 对 trace/plain。SYS_CNT 只覆盖一个完整请求，包含最后一次 DMA 的完成等待，不除以重复次数。大于 UB 的请求使用多个 tile；count/params 最多 64 KiB，Pad 最多 32 KiB。空提交/完成协议对照保留原值，不从延迟中扣掉。

双向：1/16/64 AIV，4/32 KiB tile，每方向两个 UB 窗口。小 ring、128 MiB、2 GiB **每方向** GM 工作集；每方向正式目标 4 GiB。每个分区至少完整遍历一次。read-only、write-only、同时 read+write、空协议在同一个进程、同一对独立分配上随机配对，两个页策略各测两轮。读取 UB 和写出 UB 不重叠；两方向提交后再执行完成等待；不把 GM→UB 的读取结果直接接到写入路径。

带宽分母使用同 stream 的完整 ACL Event 共同时间。页面分别展示 read_bytes/T、write_bytes/T 与 (read_bytes+write_bytes)/T；不相加独立运行的峰值。主吞吐取 trace-off 样本，另保留插桩样本和逐核原始 SYS_CNT。读、写完成观察 tick 是 Scalar 顺序观察的上界，不能作为独立方向的精确完成时间。

环境绑定 Ascend950DT_9582、CANN 9.1.0、dav-3510 与已验证的 1 GHz SYS_CNT 资料。运行时核对 AIV 与 UB，分配按请求/工作集推导并保留至少一半可用 GM。HUGE_FIRST 可能回退；未读取物理页表或 HBM/cache/TLB 计数器，因此只称分配策略与有效吞吐，不称冷 HBM 或真实大页映射已确认。

每次分配有独立全 tile 的未计时读取 oracle；每个正式启动验证完整写目标（或完整未改写区）、全部保留读取窗口及 128 B 保护区。早先被覆盖的 timed read tile 不逐个导出。Host 与容器整机占用前后均为空才接收；两次快照之间的瞬时干扰未知。

```bash
python3 plan.py
bash build.sh
python3 run_stage.py --device 1 --key smoke-latency-normal-v1 --output results/smoke-latency-normal-v1
```

使用与计划匹配的设备 ID；在调用前另行保存 Host 整机占用。`run_stage.py` 不负责预约，不能用它绕过中台等待单或占用检查。结果目录必须全新，源代码、两个二进制、计划、全部样本和退出/归档凭据分别绑定。采集、精度、覆盖、时钟或占用任何一项失败，都保留原始失败并停止该批结论。
