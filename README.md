# micro-benchmark-lab-web

AKL 实机测量结果的交互式浏览站点。先回答「哪个界面更适合比较带条件的接口性能」，再实现正式网站。

当前处于 UI 原型阶段，尚未选定设计。三个候选位于 `codex/prototype-datacopy-lab` 分支，主分支不包含原型实现。

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

原型用于选择信息结构，没有选定胜出方案。`npm run build` 可检查构建，生产构建隐藏方案浮条。此分支不直接作为正式站点发布；确定方向后重新整理正式实现。

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
