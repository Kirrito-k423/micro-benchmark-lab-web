# micro-benchmark-lab-web

AKL 实机测量结果的交互式浏览站点。先回答「哪个界面更适合比较带条件的接口性能」，再实现正式网站。

当前处于 UI 原型阶段，尚未选定设计。三个候选位于 `codex/prototype-datacopy-lab` 分支，主分支不包含原型实现。

数据来源：ascend-kernel-lab 的 A3 DataCopy 实测报告和 PR #33 的 A5 回传证据。展示有效 payload 吞吐、每调用完成耗时与原始样本；不同设备、CANN、同步方式和工作集分别标识。
