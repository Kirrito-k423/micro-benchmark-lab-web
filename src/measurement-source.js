// Pure binding and excerpt selection: an unknown receipt never falls back to latest source.
export function measurementSource(catalog, family, row, db) {
  const binding = family === 'capacity' ? catalog.capacityRuns[`${row.device}/${row.run}`] : null;
  const binary = binding?.build ?? row.libraryHash ?? row.executableHash ?? row.binaryHash ?? row.binarySha256;
  const build = catalog.builds[binary];
  if (!build) return null;
  if (binding && row.manifestHash && row.manifestHash !== binding.manifestSha256) return null;
  let hashes;
  if (family === 'alignment' || family === 'simt' || family === 'overhead') hashes = db.evidence.sources;
  if (family === 'simd' || family === 'bandwidth') hashes = db.evidence.sourceHashes;
  if (family === 'network') hashes = Object.fromEntries(Object.entries(db.evidence.measurementSourceSha256ByBinary[binary] ?? {}).map(([k,v]) => [k.replace('src/', 'examples/a5_network/'),v]));
  if (family === 'capacity' && row.device === 'A5') hashes = db.provenance.a5Runs.find(r => r.run === row.run)?.sourceSha256;
  if (hashes && Object.entries(build.files).some(([path,hash]) => hashes[path] !== hash)) return null;
  if (row.sourceCommit && row.sourceCommit !== build.recordedSourceCommit) return null;
  const files = Object.values(build.files).map(hash => catalog.files[hash]);
  if (files.some(f => !f)) return null;
  return {build, files, manifest: binding?.manifestSha256 ?? row.manifestHash, binding: binding?.binding};
}

export function sourceExcerpts(source, family, row) {
  const kernel = source.files.find(f => f.path.endsWith('kernel.cpp') || f.path === 'kernels/datacopy.cpp');
  const host = source.files.find(f => f.path.endsWith('main.cpp'));
  const blocks = [];
  function add(title, file, from, to, includeEnd = false) {
    const lines = file.text.split('\n');
    const first = lines.findIndex(l => l.includes(from));
    const last = lines.findIndex((l,i) => i > first && l.includes(to));
    if (first < 0 || last < 0) throw new Error(`Missing source boundary: ${file.path}: ${title}`);
    const end = last + (includeEnd ? 1 : 0);
    blocks.push({title, file, start:first + 1, end, text:lines.slice(first,end).join('\n')});
  }
  if (family === 'capacity' || family === 'alignment') {
    add('主体循环 · 起止打点与完成等待',kernel,'    trace.Mark(2);','    trace.Mark(3);',true);
    add('实际 API 重载 · DataCopy / DataCopyPad',kernel,'template<bool Store>','template<typename T, bool Store, bool Trace');
    add('UB 分配、初始化和结果导出',kernel,'template<typename T, bool Store, bool Trace',kernel.text.includes('SelectRun')?'template<typename T, bool Trace>':'template<bool Trace>');
  } else if (family === 'bandwidth') {
    add('双窗口主体循环 · SYS_CNT 核内区间',kernel,'    SyncAll();','    const uint64_t end',true);
    add('完成事件 · 每个窗口独立等待',kernel,'template<bool Store, bool Set>','template<bool Store>');
    add('UB 分配、初始化和全核结果导出',kernel,'template<bool Store>','extern "C" __global__');
    add('聚合带宽使用的 Host ACL Event 区间',host,'                AC(aclrtRecordEvent(r.begin','                float ms=',true);
  } else if (family === 'network') {
    add('提交循环 · MTE / URMA 与最终完成',kernel,'    const uint64_t start','    const uint64_t end',true);
    add('scratch 初始化、分区和 kernel 启动',kernel,'extern "C" __global__','extern "C" void launch_network');
    add('发起方 Host ACL Event 区间',host,'auto t=std::chrono::steady_clock::now();AC(aclrtRecordEvent','AC(aclrtEventElapsedTime',true);
    const cq=source.files.find(f=>f.path.endsWith('shared_cq_completion.h'));
    if (cq) blocks.push({title:'按实际 CQ 合并的完成适配器',file:cq,start:1,end:cq.text.trimEnd().split('\n').length,text:cq.text.trimEnd()});
  } else if (family === 'simd') {
    if (row.impl === 0) add('SIMD Tensor API · 每轮 UB 读写 / PIPE_V',kernel,'__aicore__ inline void TensorWork','template<int Threads, int Op>');
    else if (row.impl === 1) add('SIMT · 每线程跨步循环 / 寄存器依赖链',kernel,'__simt_vf__','__aicore__ inline void Complete()');
    else add(`REG · ${row.impl===3?4:1} 组寄存器依赖链与尾块`,kernel,'template<int Op>','template<int Threads, int Op>');
    add('VF 调度与完成事件',kernel,'__aicore__ inline void Complete()','extern "C" __global__');
    add('GM 输入、SYS_CNT 边界和结果导出',kernel,'extern "C" __global__','extern "C" void launch_arithmetic');
  } else {
    if (row.impl === 0) add('Scalar · 每元素标量依赖链',kernel,'__aicore__ inline void ScalarWork','template<int Op>');
    else if (row.impl === 2) add('SIMD Tensor API · 每轮 PIPE_V',kernel,'__aicore__ inline void SIMDWork','template<int Threads, int Op>');
    else if (row.impl === 1) add('SIMT · 每线程跨步处理多个元素',kernel,'template<int Threads, int Op>','template<int Threads>');
    else {
      add('VF 调用 / 无 VF 对照 · 每次完成等待',kernel,'__aicore__ inline void Work','extern "C" __global__');
      add('最小线程体 · 每线程可观察 UB 写出',kernel,'template<int Threads>','__aicore__ inline void VectorComplete()');
    }
    add('GM 输入、SYS_CNT 边界和结果导出',kernel,'extern "C" __global__','extern "C" void launch_arithmetic');
  }
  for(const file of source.files) blocks.push({title:`完整文件 · ${file.path.split('/').at(-1)}`,file,start:1,end:file.text.trimEnd().split('\n').length,text:file.text.trimEnd()});
  return blocks;
}

export function implementationContext(family,r,db) {
  const env=family==='capacity'?db.environments[r.device]:db.environment;
  const params=[['测量 ID',r.id],['轮次 / 批次',r.round??r.run??r.phase],['芯片 / CANN',env?`${env.soc} / ${env.cann}`:`${r.soc} / CANN 未记录于公开点`]];
  const p50=r.p50??r.p50Us;
  const throughput=r.gbps??(r.movedBytes&&r.p50Us?r.movedBytes/r.p50Us/1000:null);
  params.push(['本轮 p50',`${Number(p50).toFixed(5)} μs · ${['capacity','alignment'].includes(family)?'每调用平均':'完整计时区间'}`]);
  if(throughput!=null)params.push(['本轮有效吞吐',`${Number(throughput).toFixed(2)} GB/s`]);
  let timing, notes;
  if (family==='capacity'||family==='alignment') {
    params.push(['方向 / API',`${r.direction} / ${r.api}`],['dtype / payload',`${r.dtype} / ${r.bytes??r.payload} B`],['AIV / UB 窗口',`1 / ${r.windows}`],['loops × batch / GM slots',`${r.loops} × ${r.batch} / ${r.case?.slots??r.slots}`],['实际 GM 工作集',`${r.workingSet} B`],['GM 基址偏移',`${r.case?.gm_offset_bytes??r.gmOffset} B`]);
    if(r.case)params.push(['块字节 × 块数',`${r.case.block_bytes} × ${r.case.blocks}`],['GM gap / UB 偏移',`${r.case.gm_gap_bytes} B / ${r.case.ub_offset_bytes} B`]);
    if(family==='alignment')params.push(['GM 分配方式',r.fixedBuffers?'固定缓冲复验':'逐 shape 分配扫描']);
    timing='trace.Mark(2) → trace.Mark(3)，总 tick 除以 loops × batch。包含地址计算、提交、完成等待与最终排空；UB 初始化和结果导出在这段计时之外。';
    notes=[r.windows===2?'双窗口交替；复用该窗口前等待其旧 DMA，另一窗口可在途。':'单窗口；每个 batch 后等待 DMA 完成，再发下一批。','有效 payload 吞吐包含循环和同步成本，工作集复用不证明 HBM 物理流量。'];
  } else if(family==='bandwidth') {
    params.push(['方向 / AIV',`${r.direction} / ${r.cores}`],['tile × batch',`${r.tileBytes} B × ${r.batch}`],['UB 窗口 / 数据 UB',`2 / ${2*r.tileBytes*r.batch} B 每核`],['每核分区 / groups',`${r.perCoreRing} B / ${r.groups}`],['实际 GM 工作集',`${r.actualRing} B`],['全核有效字节',`${r.movedBytes} B`],['模式',r.control?'空循环 / 事件':r.sharedRead?'同址只读':'各核独立 GM 分区']);
    timing='同 stream ACL Event 包围完整多核 kernel，包含调度、UB 初始化、两次 SyncAll、DMA、完成等待和结果导出。每核 SYS_CNT 只包围主体循环；聚合 GB/s 用共同 ACL 区间计算，不扣空对照。';
    notes=['双 UB 窗口交替，复用前等待对应 MTE2_S / MTE3_S；每组提交 batch 次 DataCopy(count)，不是无限深队列。','本点的有效 GB/s 属于这套流水、tile、batch 和计时条件；约 2.1 TB/s 不能证明物理 HBM 上限。','核内与完整 kernel 计时可以帮助定位开销；要归因实现瓶颈，仍需同条件的替代流水实测。'];
  } else if(family==='network') {
    params.push(['引擎 / 操作',`${r.engine.toUpperCase()} / ${r.operation.toUpperCase()}`],['AIV / 每核消息',`${r.cores} / ${r.messageBytes/r.cores} B`],['总消息 / 请求次数',`${r.messageBytes} B / ${r.operations}`],['batch / 使用·配置 QP',`${r.batch} / ${r.qps} · ${r.configuredQps}`],['实际 ring / 总有效字节',`${r.ringBytes} B / ${r.movedBytes} B`],['完成方式 / 场景',`${r.completionImpl??'sdk'} / ${r.placement}`]);
    timing='发起方 ACL Event 包围完整 kernel，包含 scratch 初始化、提交和最终完成等待；循环 SYS_CNT 差值另存，不拼接双 rank 时钟，不相加不同 rank 峰值。';
    notes=[r.engine==='mte'?'每核一个 32 KiB scratch；每请求后等 MTE3 完成才复用，属于该串行 scratch 实现。':`单 AIV 轮流提交 ${r.qps} 个使用 QP；每 ${r.batch} 次提交完成等待，末尾再排空。`,r.completionImpl==='cq-grouped'?'按实际 CQ 合并完成计数；本点绑定显式适配器版本。':'本点使用 SDK 原生 quiet；与后续 CQ 适配器版本分开。','节点间路径未确认时不标跨柜；单对设备吞吐不代表全柜能力。'];
  } else {
    const names=family==='simd'?['SIMD Tensor API','SIMT','REG 1 组','REG 4 组']:['Scalar','SIMT','SIMD Tensor API','Touch VF','无 VF 同步循环'];
    const threadsApplicable=family==='simd'?r.impl===1:[1,3].includes(r.impl);
    const operation=family==='overhead'?(r.impl===3?'UB 写出':'空同步'):['加','减','乘','除'][r.op];
    params.push(['实现 / 运算',`${names[r.impl]} / ${operation}`],['FP32 元素 / 每元素步数',`${r.elements} / ${r.steps}`],['AIV / SIMT 线程',`1 / ${threadsApplicable?r.threads:'不适用'}`]);
    if(family!=='simd')params.push(['循环调用 / 实际 SIMT VF',`${r.vf_calls} / ${r.actualSimtVfCalls}`]);
    timing='GM 输入完成后读 SYS_CNT，执行所选实现，再读 SYS_CNT。GM 输入与结果导出不在这段计时内；Vector / VF 路径的完成等待、VF 调度和实现自己的同步在内。';
    notes=[r.impl===1?'SIMT 用 i = threadIdx.x; i < n; i += Threads；一个线程可以循环处理多个元素。':family==='simd'&&r.impl>=2?(r.impl===3?'REG 在寄存器保留依赖链，每批四条独立向量链；尾部走掩码路径。':'REG 每批一条寄存器向量依赖链；尾部走掩码路径。'):r.impl===0&&family!=='simd'?'Scalar 逐元素在标量寄存器中计算，UB 读写在所选计时内。':'Tensor API 每轮读写 UB 并执行 PIPE_V。','各实现的存储和同步成本不同，速度比是该实现的完成耗时对照。'];
    if(family==='overhead')notes=['Touch VF 每线程执行一次可观察 UB 写入，每调用都等待完成；增量包含这些成本，不能解释成纯线程创建开销。'];
  }
  return {params:params.filter(([,v])=>v!==undefined),timing,notes};
}
