# micro-benchmark-lab-web

AKL 实机测量结果的交互式浏览站点。按实验条件比较接口完成耗时与有效吞吐，并逐点查看原始计时证据。

沿方案 A 继续迭代；B/C 保留作为布局比较。新增实验位于 `codex/a5-mbench-results` 分支，主分支不包含网页实现。

公开预览：[Micro Benchmark Lab](https://kirrito-k423.github.io/micro-benchmark-lab-web/)。默认显示方案 A，保留数据筛选、图表和样本联动；公网构建隐藏原型切换条。

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
