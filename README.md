# micro-benchmark-lab-web

AKL 实机测量结果的交互式浏览站点。按实验条件比较接口完成耗时与有效吞吐，并逐点查看原始计时证据。

沿方案 A 继续迭代；B/C 保留作为布局比较。新增实验位于 `codex/a5-mbench-results` 分支，主分支不包含网页实现。

公开预览：[Micro Benchmark Lab](https://kirrito-k423.github.io/micro-benchmark-lab-web/)。默认显示方案 A，保留数据筛选、图表和样本联动；公网构建隐藏原型切换条。

所有实验页提供「此测量的代码与计时」面板。点选曲线或表格，再选样本轮次，可查看该单轮的参数、p50、主体循环、API 重载、完成事件和计时边界。支持切换片段、复制原文、下载完整文件与固定内容的 GitHub 链接。参数和原始代码分别显示，没有把示意代码冒充实测实现。

源码由 `public/data/measurement-code.json` 按构建/库哈希绑定；覆盖现有 18,469 条配置轮次（含本轮 7,166 条大页复测）。A3 容量归档中的两个 kernel 版本逐 run 区分，恢复绑定前核对配置和全部公开 tick；通信 SDK 原生 quiet 与 CQ 合并完成版本也分别绑定。仅以文件哈希找到的 commit 表示相同文件内容，不能当作实验记录的全仓 commit。绑定缺失或不匹配会明确显示未知，不回退到最新源码。

原多核 DataCopy 的约 2.1 TB/s 属于普通页分配基线。已用同一读取实现、窗口完成策略和输入模式验证：仅改输入分配为大页优先，2 GiB ring 的有效吞吐可约为 3.9 TB/s。后续大页复测独立重测输入/输出数据页策略，不能把旧数值当作芯片上限。完整 ACL Event 保留初始化、同步及导出；没有测物理 HBM 事务。

重新导出源码目录（只读取私有归档；公开输出仅包含源码、参数索引与哈希）：

```bash
python3 scripts/export-measurement-code.py \
  --akl-root /absolute/akl-with-historical-commits \
  --network-root /absolute/akl-network \
  --private-results /absolute/private/results
node scripts/check-measurement-code.mjs
```

核验器覆盖每条测量的绑定、完整文件 SHA-256、片段原文/行号及旧版本隔离，并拒绝未知二进制、错配源码与 commit。该检查验证网站数据对应关系，不产生新的 NPU 测量。

数据来源：ascend-kernel-lab 的 A3 DataCopy 实测报告和 PR #33 的 A5 回传证据。展示有效 payload 吞吐、每调用完成耗时与原始样本；不同设备、CANN、同步方式和工作集分别标识。

## 运行原型

首次拉取后执行 `npm ci`，之后一条命令启动：

```bash
npm run prototype
```

打开 `http://127.0.0.1:5183/prototype/datacopy/?variant=A`。底部浮条或键盘左右键切换方案，URL 中的 `variant=A|B|C` 可以直接分享。输入框、下拉框聚焦时不拦截方向键。选择状态只保存在内存，刷新恢复默认；方案参数保留。

| 方案 | 首要任务 | 结构与取舍 |
|---|---|---|
| A · 性能工作台 | 日常探索吞吐曲线、定位单点 | 左侧固定条件，中间曲线与表格，右侧样本证据；桌面更高效 |
| B · 数据浏览器 | 筛选、排序、逐行核对 | 顶部查询条件，主区高密度表格，右栏曲线与选中行；更适合大量数据 |
| C · 实验报告 | 分享和解释实验结论 | 阅读顺序为问题、条件、曲线、证据，留白更多；长页面适合归档阅读 |

三个方案共用 Apache ECharts 图表与真实测量数据，支持方向、设备、工作集、窗口、batch、计时范围切换；曲线缩放、图例开关、点选、表格搜索与排序、逐轮 20 个样本、原始 tick、CSV / SVG 下载。选中表格行会更新样本面板。

原型用于验证信息结构与交互，B/C 保留作为比较参考。`npm run build` 可检查构建，生产构建隐藏方案浮条。用户要求将当前网页发布到公网，因此提供静态公开预览；正式实现仍待后续整理。

## A5 长度对齐、SIMT 算术与 VF 开销

新增三个独立入口，共用 ECharts 曲线、实测表格与原始样本联动：

- [DataCopy 对齐](https://kirrito-k423.github.io/micro-benchmark-lab-web/?lab=alignment)：默认显示固定 GM 缓冲的 15 个边界长度复验；另保留 uint8/FP32 的 127–257 元素完整扫描。方向、单/双窗口、地址偏移、延迟/吞吐和轮次分别筛选；DataCopyPad 与 DataCopy(params) 分线。
- [SIMT 算术](https://kirrito-k423.github.io/micro-benchmark-lab-web/?lab=simt)：FP32 加减乘除；32/128/512/2048/8192 元素，1/16/128 次依赖链，1–2048 的十档线程数。对照同工作量 Scalar/SIMD，切换总耗时或速度比。
- [VF 调用开销](https://kirrito-k423.github.io/micro-benchmark-lab-web/?lab=overhead)：1/16/64/128 次调用；原始每次完成时间与相对无 VF 同步循环的增量分别展示。每线程一次可观察 UB 写出仍在计时内，不能视为纯线程创建时间。

这组数据使用 CANN 9.1.0，原容量曲线的 A5 数据使用 CANN 9.2.0，两组实验条件应分别看待。双窗口平均完成耗时不等于独立请求尾延迟；SIMT 寄存器依赖链与 SIMD Tensor API 每轮 UB 读写/同步的差异包含在速度比中。

2026-10-09 完成并通过接收端校验：1496×2 个全量 DataCopy、60×2 个固定分配复验、764×2 个 SIMT 配置轮次，共 60264 个正式计时样本。[实测报告](reports/a5-mbench-20261009.md) 保留精确参数与对照数值。固定分配复验的两轮差异中位数 3.359%，全量扫描为 7.654%，SIMT 为 0.002%；小幅变化不能忽略这些波动。

接收端导入再次检查预定矩阵、两轮覆盖、样本数、正确性、短批次结束占用检查和源码/构建哈希。两个方向均保留输出保护区验证。仅接受完整三组矩阵作为正式发布；部分结果只能本地预览。

```bash
python3 scripts/import-a5-mbench.py \
  --runs /path/to/collected-formal-results \
  --setup /path/to/setup \
  --akl-root /path/to/ascend-kernel-lab \
  --output public/data/a5-mbench.json
python3 scripts/summarize-a5-mbench.py
uv run --no-project --with matplotlib==3.11.2 python scripts/plot-a5-mbench.py
```

导入器需要 NumPy 和对应 AKL Python 源码。公开 JSON 包含参数、tick、p50/p95、正确性和证据哈希；设备地址、SSH 配置和完整进程日志不公开。实验报告由完整数据生成到 `reports/a5-mbench-20261009.md`。

## 发布公开预览

运行 `npm ci` 后执行 `npm run build:pages`，生成带 `/micro-benchmark-lab-web/` 资源前缀的 `dist/`。数据请求同样使用该前缀，本地开发仍使用根路径。

GitHub Pages 使用 `gh-pages` 分支根目录作为发布源。仅将 `dist/` 的内容（包含 `.nojekyll`）提交到该分支，等待仓库的 `pages build and deployment` 成功后检查公开地址。源码保存在 `codex/a5-mbench-results`；修改源码分支不会自动发布，需重新构建并更新 `gh-pages`。

## 数据与边界

- A3：956 个配置轮次，19,120 个计时样本；来源为 AKL #39 归档。
- A5：944 个配置轮次，18,880 个计时样本；来源为 [AKL #33 回传评论](https://github.com/Kirrito-k423/ascend-kernel-lab/pull/33#issuecomment-5826300302) 的两组分片 ZIP。附件不包含评论所述额外 20 个固定 shape 基线配置，因此本页面没有将它们计入。
- 合计 1,900 行、38,000 个原始计时样本，全部 p50/p95/GBps 从 tick 重算核对。保留慢样本；默认只显示 ≥8192 loops，可切换查看早期短计时结果。
- A5 两组 ZIP 的 MD5 与评论声明一致，CRC 完整；AKL `datacopy_report.analyse` 重新验证所有运行的 manifest、占用证据哈希、正确性标志和 `.npy` 原始计时。
- 公开数据只包含测量参数、tick、芯片/CANN、证据哈希与原始公开来源链接；完整占用日志、机器地址与内部路径不入仓。

页面曲线和表格按照设备、数据量、loops、slots 等条件分组，跨轮的 p50/p95 各取中位数，吞吐从汇总 p50 计算；右侧明细始终展示选中单轮的原始值。环形工作集的 loops 随 shape 调整，图例和 tooltip 明示。单窗口与双窗口不混线；没有对不相等的 shape 插值计算加速比。

跨芯片同时跨 CANN 的对照不用于单独归因芯片差异。有效搬运吞吐不等于物理总线流量或整卡 HBM 峰值；双窗口区间耗时除以调用数也不是独立请求的尾延迟。实际 DeepEP shape hook 数据尚未接入。

导入脚本：`scripts/import-evidence.py`；静态数据：`public/data/datacopy.json`。A5 先使用同版本 AKL 解析器验证并生成 `summary.json`，再执行：

```bash
python3 scripts/import-evidence.py --a3 /path/to/points.csv --a5 /path/to/a5-web-20260925
```

数据目录包含 `a5-datacopy/` 与 `a5-datacopy-w1/` 两个解压目录。原型导入器只覆盖本次归档，不代表正式的通用上传协议。

图表实现参考 [Apache ECharts dataset 文档](https://echarts.apache.org/handbook/en/concepts/dataset/)；依赖版本由 lockfile 固定。

## A5 SIMD / REG 同工作量对照

[新页面](https://kirrito-k423.github.io/micro-benchmark-lab-web/?lab=simd) 提供 10 个批量 shape 与尾块、四种 FP32 运算、Tensor API / REG 1/4 组 / SIMT 五档线程对照。支持 shape/依赖链横轴，完成耗时/有效 Gop/s/相对 Tensor API 速度比，图例开关、原始样本联动、轮次筛选与 CSV。1588 配置 × 两轮、47640 计时样本通过验收。

[实测报告](reports/a5-simd-20261009.md) · [代码与 SOP](https://github.com/Kirrito-k423/ascend-kernel-lab/tree/codex/a5-alignment-simt/examples/a5_simd_mbench)。公开数据 `public/data/a5-simd.json` 独立保留本轮二进制；旧曲线仍在原入口。

```bash
python3 scripts/import-a5-simd.py --runs /absolute/private/raw --akl-root /absolute/akl --output public/data/a5-simd.json
python3 scripts/report-a5-simd.py --data public/data/a5-simd.json --report reports/a5-simd-20261009.md --figures public/figures
```

导入器要求完整两轮、固定矩阵、源码/构建/样本哈希、全部输出验证和短批次前后占用证据；缺失任一项就拒绝导出。报告与 PNG/SVG 均从验收 JSON 重新计算。

## A5 单卡多核 DataCopy 带宽

[多核页面](https://kirrito-k423.github.io/micro-benchmark-lab-web/?lab=bandwidth) 扫描 1/2/4/8/12/16/20/24/28/32/40/48/56/64 AIV，分区读写、小工作集、1/2GiB 大工作集、同址只读和空循环分别展示。支持 tile/batch、轮次、聚合/平均每核带宽、共同耗时与并行效率筛选；图例多选、点选原始 ACL 样本及逐核 DMA 分布、CSV、PNG/SVG。

Ascend950DT_9582 / CANN 9.1.0，378 配置 × 两轮、9072 计时样本、1512 预热样本通过验收。1GiB 工作集观测最高读 2.076TB/s、写 2.099TB/s，均为 64 AIV；相对对应单核约 54–55 倍。56→64 核仍提高约 13–14%，追加 2GiB 工作集同样未确认平台。N95=64 是已测档位相对于本次最高值的阈值，不能声称已用满物理 HBM。

聚合带宽使用同 stream ACL Event 的完整多核 kernel 共同区间，不相加单核峰值、不扣空循环。每个核独立 UB，各核写分区互不重叠；同址对照只读且包含重复逻辑请求。每次 launch 校验完整写目标/各核最后两组读入结果、保护区和核记录；源码、二进制、矩阵及占用前后凭据再次验收。两轮 p50 相对差异中位数 0.162%，最大 6.153%。

[报告](reports/a5-bandwidth-20261009.md) · [代码与运行 SOP](https://github.com/Kirrito-k423/ascend-kernel-lab/tree/codex/a5-alignment-simt/examples/a5_bandwidth)。原始共同毫秒样本、每核 SYS_CNT 差值和证据哈希保存于 `public/data/a5-bandwidth.json`；完整绝对时间与设备日志留在私有归档。

```bash
python3 scripts/import-a5-bandwidth.py --runs /absolute/private/raw --environment /absolute/environment.json --platform-config /absolute/platform-config.ini --akl-root /absolute/akl --output public/data/a5-bandwidth.json
python3 scripts/report-a5-bandwidth.py --data public/data/a5-bandwidth.json --report reports/a5-bandwidth-20261009.md --figures public/figures
```


## A5 DataCopy 纯写同步对照

[新页面](https://kirrito-k423.github.io/micro-benchmark-lab-web/?lab=store-tail) 固定地址布局，在同一个二进制与进程的 GM 分配上，配对比较双窗口等待与持续提交、仅末尾完成。覆盖 1/16/32/64 AIV 与四种 tile/batch；每对样本随机先后顺序，支持工作集、轮次、吞吐/完成耗时/速度比、图例多选、原始配对样本、逐点源码和 CSV/PNG/SVG。

40 配置 × 两轮、960 正式样本及 160 预热通过完整输出与保护区验证。64 AIV、1 GiB 工作集：4 KiB × 1 从 1.392 提高到 2.076 TB/s；其余成组提交变化 -0.19%～+0.75%，最高约 2.103 TB/s。2 GiB 工作集复验趋势相同。显式循环等待限制小提交，但无法解释成组路径与 4 TB/s 参考规格的全部差距；地址不重叠仍可能共用 bank / 通道资源，本轮没有验证其冲突。

[报告](reports/a5-store-tail-20261010.md) · [AKL 核心 PR #53](https://github.com/Kirrito-k423/ascend-kernel-lab/pull/53) · [固定源码](https://github.com/Kirrito-k423/ascend-kernel-lab/tree/7870838bc924176c3920e2061b65b9e8a10098dd/examples/a5_store_tail)。新数据 `public/data/a5-store-tail.json` 单独存放，旧 DataCopy、SIMD、通信数据原样保留。

```bash
python3 scripts/import-a5-store-tail.py --runs /absolute/private/raw --akl-root /absolute/akl --tasks-state /absolute/private/tasks-state.json --output public/data/a5-store-tail.json
uv run --with matplotlib python scripts/report-a5-store-tail.py --data public/data/a5-store-tail.json --report reports/a5-store-tail-20261010.md --figures public/figures
```

接收器验证完整两轮矩阵、每模式样本和配对次序、精确字节数、逐启动完整 oracle、Host/容器前后占用、任务真实退出/归档状态、原始归档与提取文件逐字一致，以及固定 commit 中的全部六个执行文件。生产导入拒绝不完整矩阵；`--smoke-only` 仅用于本地部分采集验收，不能作为发布完成证据。

## A5 工作集下降区间

入口 `?lab=workset`：固定 64 AIV、uint32 DataCopy(count)、32 KiB × 2、双窗口完成策略。分区读 / 分区写各 33 个大小，同址读 39 个大小，128 MiB 附近按 8 MiB 加密；每轮 105 配置、两轮 2520 正式样本。每条曲线一个进程固定 GM 分配，各大小随机顺序。

原来的 128 KiB 高吞吐点为同址读，2 GiB 低吞吐点为独立分区，不能直接连线。新横轴为实际触达 GM：每核完整遍历至少两次，尤其避免把没有遍历完的共享大 ring 算作工作集。分区每次搬运 4 GiB，同址读总请求量随工作集增加。有效吞吐不是 HBM 物理流量。

D10 / D50 / D90 按预先规定的高低参考和两个连续点越阈值定位，两轮区间取并集；不插值或拟合。页面提供全范围对数轴、32–256 MiB 分区放大与 0–32 MiB 同址陡降放大、原始样本、CSV、完整代码与 PNG/SVG。

```bash
python3 scripts/import-a5-workset.py --runs /absolute/private/raw --akl-root /absolute/akl --tasks-state /absolute/private/tasks-state.json --output public/data/a5-workset.json
uv run --no-project --with matplotlib python scripts/report-a5-workset.py --data public/data/a5-workset.json --report public/reports/a5-workset-20261010.md --figures public/figures
```

接收器核对任务退出和归档、逐文件字节、构建/runner/planner 哈希、完整矩阵、参数与实际遍历字节、逐启动 oracle、两套时钟、Host/容器占用。缺测或占用失败不得发布完整结果。复现命令及全部点在公开报告中。

## A5 同事代码复现与页分配对照

入口 `?lab=peer-copy`：原样复现 TmpCode `datacopy_3t.asc`，再用 20 个控制变量配置比较输入分配、L2 hint、索引输入、完成策略与 tile 粒度。原配置加控制变量共 21 配置、两轮 840 正式样本。默认看 7 组核心发现，可切换全部点、Peer / AKL 实现和单轮样本。

AKL 配对保留 2 GiB ring、32 KiB × 2、4 GiB 总搬运量、WindowEvent、SyncAll 与每启动完整最后两组 UB 校验，只更换输入分配策略。之前的多核、工作集及纯写同步对照已补标 NORMAL_ONLY 普通页条件，原始计时不变；当前大页结论限于 GM→UB 读取。

复现源码在 `experiments/a5_peer_copy/`，按实际二进制哈希绑定编译宏和固定文件内容；原代码与 Peer 控制版本的 32 B 抽样 oracle 和 AKL 的完整最后窗口 oracle 分别标注。所有样本由任务归档逐字节接收核验，不使用“best GB/s”替代中位数。

```bash
python3 scripts/import-a5-peer-copy.py --runs /absolute/private/results --output public/data/a5-peer-copy.json
uv run --no-project --with matplotlib python scripts/report-a5-peer-copy.py --data public/data/a5-peer-copy.json --report public/reports/a5-peer-copy-20261010.md --figures public/figures
```

## 统一工作台与 A5 大页复测

所有实验入口沿方案 A 统一页头、左侧实验目录/条件、曲线/样本、表格和逐点代码面板。旧 DataCopy 页有显式复测入口；B/C 仅保留为历史设计比较。过滤、样本轮次和代码片段均可以选择，筛选重新渲染保留滚动位置。

[Peer 代码解释](https://kirrito-k423.github.io/micro-benchmark-lab-web/?lab=peer-copy) 提供 GM / 每核 UB / 验证记录三个对象及六步执行解释。原代码的两块 64 KiB UB 在每组接收两个 tile，MTE2 PipeBarrier 约束该流水顺序，最后 MTE2→Scalar 完成后读结束 tick；它没有业务计算。独立未计时 kernel 校验每 tile 前 32 B，正式读取只导出每核尾部两块 UB 的前 32 B；核内循环与完整 ACL Event 的边界分开说明，不称全量复制 oracle。

[大页复测](https://kirrito-k423.github.io/micro-benchmark-lab-web/?lab=page-retest) 包含 7,166 配置轮次、85,992 正式计时样本，完整接收验收后发布。2026-10-10 的实际环境为 Ascend950DT_9582、64 AIV、221184 B UB、CANN 9.1.0。

| 分组 | 两轮配置轮次 | 条件 |
| --- | --- | --- |
| 单 AIV 倍增 | 2,064 | 32 B × 2ⁿ；普通页/大页优先；读/写、3 重载、1/2 窗口、batch=1/8、小工作集/ring |
| 旧容量复测 | 944 | 原完整参数，大页优先；历史 CANN 9.2.0 与本轮 9.1.0 区分 |
| 长度/地址对齐 | 2,992 | 原 uint8/FP32 的完整扫描，大页优先 |
| 固定分配边界 | 120 | 原 60 配置复验，大页优先 |
| 多核 | 756 | 原 AIV 数、tile/batch、ring 与完成边界，大页优先 |
| 工作集 | 210 | 原加密大小、访问范围、完整共同时间，大页优先 |
| 纯写同步 | 80 | 同一分配的 Windowed / Tail 随机配对，大页优先 |

单窗口 batch=1 的 count/params 共 13 个倍增大小（32 B–128 KiB），最大单次 shape 由实际 UB 裁剪；Pad 的 uint16 字节 blockLen 另有限制。108 非法组合记录为 skipped。输入/输出至少申请 2 MiB，大页优先可能回退；HUGE_ONLY 的三个边界冒烟不能代表全部正式分配都未回退。

实际工作集、backing 申请容量和单次 payload 分开。单核 ring 受 65,536 slots 上限约束：32 B 为 2 MiB，随 shape 增大至 64 MiB。默认 L2，未证明冷 HBM；loops 自适应并完整覆盖所有 slots。旧容量按 loops 分线，不混合不同摊销口径。单核是 trace 循环内每调用平均完成时间，多核为共同完整 ACL Event。

[报告与静态图](public/reports/a5-page-retest-20261010.md) 从完整接收数据生成；[可运行源码](experiments/a5_page_retest/README.md) 记录构建和分阶段执行。新数据与原 A3/A5 DataCopy、SIMD、通信数据独立存放。A3 未在本轮重测；实际页表、TLB miss、bank/通道与缓存命中未知，分配效果不归因为唯一硬件机制。

```bash
uv run --no-project --with numpy python scripts/import-a5-page-retest.py \
  --runs /absolute/private/a5-page-retest-20261010 \
  --output public/data/a5-page-retest.json
uv run --no-project --with matplotlib python scripts/report-a5-page-retest.py \
  --data public/data/a5-page-retest.json \
  --report public/reports/a5-page-retest-20261010.md --figures public/figures
node scripts/check-measurement-code.mjs
npm run build:pages
```

导入器以原始 tar 字节绑定全部文件、源码/二进制、占用与计时；逐启动 oracle 全通过、两轮覆盖完整才可发布。`--partial` 仅本地预览，生产页面拒绝未完整验收数据。源码面板也显式展示 Host 的 `aclrtMalloc` 页策略与申请容量，拒绝缺失/错配构建。

## 单 AIV 完整请求：32 B → 4 MiB

已实现“单 AIV · 32 B → 4 MiB”实验。计划的 18 个倍增点覆盖读、写、三种 API、1/2 个 UB 窗口及普通页/大页优先配对，两轮共 864 配置轮次、10,368 个计时样本，另有同量 trace-off 对照。目前已通过 A5 的 32 B / 4 MiB 边界冒烟，正式两轮因借用机器出现其他 NPU 进程而排队；完整接收验收后再发布新曲线。旧的单次 API 曲线独立保留。

4 MiB 是完整请求的总数据量，通过多个 UB tile 搬运。count / params 固定最大 64 KiB tile，旧 Pad 的字节 blockLen 使用最大 32 KiB tile；4 MiB 分别需要 64 / 128 次 API 调用。每个完整请求都包含最终完成等待再进入下一请求；网页与逐点代码面板同时显示总字节、tile、调用次数和申请容量。

独立功能启动导出并校验全部读 tile。每个计时启动检查完整写目标或最后完整 UB 窗口及 128 B guard；两种读校验的范围分别记录。工作集为重复请求的总字节，默认 L2，不声称冷 HBM 吞吐。

[源码与测量步骤](experiments/a5_extent/README.md)已保存。完整验收后由接收数据生成 18 点报告、静态图与交互页面；发布前核对原始归档、全部参数、时钟、占用、构建和 32 B–4 MiB 的完整覆盖。

```bash
python3 scripts/import-a5-extent.py /absolute/private/a5-extent-20261011 --output public/data/a5-extent.json
uv run --no-project --with matplotlib python scripts/report-a5-extent.py --data public/data/a5-extent.json --report public/reports/a5-extent-20261011.md --figures public/figures
node scripts/check-measurement-code.mjs
npm run build:pages
```
