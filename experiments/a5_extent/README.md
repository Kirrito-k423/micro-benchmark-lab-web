# 单 AIV DataCopy：32 B 到 4 MiB

这是总数据量扫描。18 个点为 `2^5 … 2^22` 字节，完整覆盖 32 B 到 4 MiB。超过一个 UB 窗口时，以多个连续 DMA 搬运一份请求；不能解释为一次 API 支持 4 MiB UB Tensor。

每次请求都完成后再开始下一次请求。固定 1 AIV、uint32、连续地址、默认 L2；读写分别测量。DataCopy(count) 与 DataCopyParams 使用最大 64 KiB tile；旧 DataCopyPad(DataCopyParams) 的 uint16 字节长度使用最大 32 KiB tile。tile=min(总字节,最大 tile)，1/2 个 UB 窗口均实测。每轮每配置重新申请数据 GM，输入/输出均对比 NORMAL_ONLY 与 HUGE_FIRST，并保持至少 2 MiB 申请容量。

实际工作集是请求的总字节，循环重复访问同一份数据。该扫描回答该缓存/同步条件下的延迟与吞吐，不能当作冷 HBM 带宽。HUGE_FIRST 可以回退，未查询物理页表。超过 tile 后地址计算、逐 tile 提交和窗口等待也计入请求时间。

小请求重复以降低时钟量化误差：repeats=max(4,min(8192,16 MiB/总字节))。初始化后显式等待 V_S，确保 Vector 完成后再读取起点 SYS_CNT；请求循环前后读取系统时钟，每个请求包含最终完成等待。每请求平均耗时=总 tick / 实测时钟 / repeats；有效 GB/s=总字节/平均耗时。ACL Event 包围完整 kernel，包含初始化与导出，独立展示，不扣除空对照。

功能验证先单独启动一次不计性能的读回 kernel，导出所有 tile，检查完整数据与 128 B guard。每个正式和预热启动再次校验：写检查整个 GM 目标；读检查最后 1/2 个完整 UB 窗口与 guard。读的逐启动校验没有观察已经覆盖的早期 UB tile，完整读校验的独立启动与逐计时启动证据分开记录。

每配置 2 次预热、12 个 trace 样本和 12 个关闭 trace 的样本，采集开关顺序随机；两轮独立重新申请，配置顺序随机，所有慢样本保留。两种页策略成对采用相同源码/参数/顺序；原始结果仅存私有归档。

```bash
python3 plan.py
bash build.sh
# 完整轮次由 execution-plan.json 预声明，每次只执行一个短批；按实测空闲 device 传参数。
python3 run_stage.py --device 1 --key smoke-normal-v3 --output results/smoke-normal-v3
python3 run_stage.py --device 1 --key smoke-huge-first-v3 --output results/smoke-huge-first-v3
python3 run_stage.py --device 1 --key r1-normal-00-v3 --output results/r1-normal-00-v3
```

命令执行前后同时记录 Host/容器占用；有其他 NPU 进程时不运行。生成计划中 SoC、UB、架构与时钟属于本轮目标环境，其他环境须重新调查，不能沿用。正确性、时钟、覆盖、源码绑定或占用检查失败的批次不发布性能。
