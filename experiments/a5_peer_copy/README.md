# A5 DataCopy 同条件对照源码

`datacopy_3t.asc` 原样来自 TmpCode 提交 `f4c410cb88a5ae3e0149487ddda77c8818f534dd`，文件 SHA-256 为 `09952e9372329d60e8cb570e8c48f2056ce4aeaed7b9ca08c5878697094584c4`。本目录用于固定网站实测点的源码，不替代 AKL 的正式 API。

`peer_control.asc` 保留原来的计时和 DataCopy 路径，只增加 Host 参数 `--allocation huge-first|normal|huge-only`（只改变输入分配，sink/ticks 仍用 huge-first）、`--pattern tile-uniform|indexed` 和模板选择 `--completion pipeline|scalar`。indexed 与 AKL 相同，使用 `0x13579bdf ^ (uint32(index) * 2654435761)`；输入准备在计时外。scalar 模式每组使用 MTE2_S SetFlag/WaitFlag，pipeline 模式保持 PipeBarrier<MTE2>。另用编译宏 TILE_BYTES=32768、BUFFER_COUNT=4 控制相同 128 KiB 数据 UB 的提交粒度。

两个 `akl-control-*.cpp` 来自 AKL `a9f21012ffe61afbda405842d3f54d6a5d73aa3a` 的 `examples/a5_bandwidth`。Host 增加编译宏 INPUT_POLICY 和 MAX_RING_GIB，kernel 增加 INPUT_BYPASS，只对实际输入切片设置 cache hint；原来的双窗口完成、计时、索引输入与逐启动输出/保护区校验保留。

所有公开结果保留 raw ACL 毫秒和构建哈希。原代码与控制代码仅在每个 tile 的前 32 B 做独立 untimed 验证，并在计时循环后校验最后各 UB buffer 的前 32 B；AKL 对每个计时 launch 校验完整最后两组 UB 与保护区。不能把两种 oracle 强度写成相同。

编译针对实测 CANN 9.1.0 / Ascend950DT_9582：

```bash
source /usr/local/Ascend/cann/set_env.sh
bisheng -O2 -g -xasc --npu-arch=dav-3510 datacopy_3t.asc -I"$ASCEND_HOME_PATH/include" -L"$ASCEND_HOME_PATH/lib64" -lascendcl -lruntime --cce-fatobj-link -o peer-original
bisheng -O2 -g -xasc --npu-arch=dav-3510 peer_control.asc -I"$ASCEND_HOME_PATH/include" -L"$ASCEND_HOME_PATH/lib64" -lascendcl -lruntime --cce-fatobj-link -o peer-control
./peer-original --device 1 --mib 4096 --aivs 64 --cache bypass --warmup 5 --repeats 20 --output original-r1
./peer-control --device 1 --mib 4096 --aivs 64 --cache bypass --allocation normal --pattern indexed --completion pipeline --warmup 5 --repeats 20 --output compare-r1
```

执行前后检查整台 Host 与容器的 NPU 进程；使用短暂自有预约，每个输出 PREFIX 唯一，保留失败。两轮分别随机配置顺序，每配置 5 次预热、20 次计时，不挑最快样本。原始日志与地址留在私有 results。具体结论以接收验收后的报告为准。
