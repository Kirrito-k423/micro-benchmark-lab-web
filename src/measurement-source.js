// Pure binding and excerpt selection: an unknown receipt never falls back to latest source.
export function measurementSource(catalog, family, row, db) {
  const binding = family === 'capacity' ? catalog.capacityRuns[`${row.device}/${row.run}`] : null;
  const binary = binding?.build ?? row.libraryHash ?? row.executableHash ?? row.binaryHash ?? row.binarySha256;
  const build = catalog.builds[family==='page-retest'?`page-retest/${row.bindingKey}`:binary];
  if (!build) return null;
  if(family==='page-retest'&&build.binarySha256!==row.binaryHash)return null;
  if (binding && row.manifestHash && row.manifestHash !== binding.manifestSha256) return null;
  let hashes;
  if (family === 'alignment' || family === 'simt' || family === 'overhead') hashes = db.evidence.sources;
  if (family === 'simd' || family === 'bandwidth' || family === 'store-tail' || family === 'workset') hashes = db.evidence.sourceHashes;
  if (family === 'peer-copy') hashes = db.evidence.sourceHashesByBinary[binary];
  if (family === 'page-retest') {
    const receipt=db.evidence.sourceBindings[row.bindingKey];
    if(!receipt||receipt.binaryHash!==row.binaryHash)return null;
    hashes=receipt.sources;
  }
  if(family==='page-retest'&&!hashes)return null;
  if (family === 'network') hashes = Object.fromEntries(Object.entries(db.evidence.measurementSourceSha256ByBinary[binary] ?? {}).map(([k,v]) => [k.replace('src/', 'examples/a5_network/'),v]));
  if (family === 'capacity' && row.device === 'A5') hashes = db.provenance.a5Runs.find(r => r.run === row.run)?.sourceSha256;
  if (hashes && Object.entries(build.files).some(([path,hash]) => hashes[path] !== hash)) return null;
  if (row.sourceCommit && row.sourceCommit !== build.recordedSourceCommit) return null;
  if (family === 'store-tail' && db.evidence.sourceCommit !== build.recordedSourceCommit) return null;
  const files = Object.values(build.files).map(hash => catalog.files[hash]);
  if (files.some(f => !f)) return null;
  return {build, files, manifest: binding?.manifestSha256 ?? row.manifestHash, binding: binding?.binding};
}

export function sourceExcerpts(source, family, row) {
  if(family==='page-retest'){
    const single=['power2','capacity','alignment','alignment-paired'].includes(row.kind);
    const blocks=sourceExcerpts(source,single?'alignment':row.kind==='tail'?'store-tail':'bandwidth',row);
    const extra=[];
    function region(title,file,from,to){
      const lines=file.text.split('\n'),first=lines.findIndex(l=>l.includes(from)),last=lines.findIndex((l,i)=>i>first&&l.includes(to));
      if(first<0||last<0)throw new Error(`Missing allocation excerpt: ${file.path}`);
      extra.push({title,file,start:first+1,end:last,text:lines.slice(first,last).join('\n')});
    }
    if(single){
      region('Host · 页策略到 aclrtMalloc 的实际映射',source.files.find(f=>f.path.endsWith('native.py')),'    def alloc(','    def upload(');
      region('Host · 2 MiB 下限、输入/输出分配与记录缓冲',source.files.find(f=>f.path.endsWith('run_datacopy.py')),'            sizes =','            samples =');
    }else{
      const host=source.files.find(f=>f.path.endsWith('main.cpp'));
      region('Host · 本构建的数据 GM 页策略',host,'#ifndef DATA_POLICY','static uint32_t InputValue');
      region('Host · 固定 GM 容量、输入/输出与普通页核记录',host,'        size_t inputBytes','        AC(aclrtMemcpy(r.x');
    }
    return [...blocks.filter(b=>!b.title.startsWith('完整文件')), ...extra, ...blocks.filter(b=>b.title.startsWith('完整文件'))];
  }
  const kernel = source.files.find(f => f.path.endsWith('kernel.cpp') || f.path.endsWith('/datacopy.cpp') || f.path.endsWith('.asc'));
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
  if(family==='peer-copy'&&row.implementation==='peer'){
    add('DataCopy 与完成边界 · L2 hint 设置在实际切片',kernel,'template <bool BYPASS','void launch');
    add('Host 分配、输入初始化与独立 tile 校验',kernel,'    uint32_t *input','        for (int w =',false);
    add('完整 kernel 的 ACL Event、原始样本与尾部校验',kernel,'        for (int r =','        std::sort(times',false);
  } else if (family === 'capacity' || family === 'alignment') {
    add('主体循环 · 起止打点与完成等待',kernel,'    trace.Mark(2);','    trace.Mark(3);',true);
    add('实际 API 重载 · DataCopy / DataCopyPad',kernel,'template<bool Store>','template<typename T, bool Store, bool Trace');
    add('UB 分配、初始化和结果导出',kernel,'template<typename T, bool Store, bool Trace',kernel.text.includes('SelectRun')?'template<typename T, bool Trace>':'template<bool Trace>');
  } else if (family === 'bandwidth' || family === 'store-tail' || family === 'workset' || family === 'peer-copy') {
    add(family==='store-tail'?'主体循环 · 双窗口 / 仅末尾完成 · SYS_CNT':'双窗口主体循环 · SYS_CNT 核内区间',kernel,'    SyncAll();','    const uint64_t end',true);
    add('完成事件 · 每个窗口独立等待',kernel,'template<bool Store, bool Set>','__aicore__ inline void Work');
    add('UB 分配、初始化和全核结果导出',kernel,'__aicore__ inline void Work','extern "C" __global__');
    add('聚合带宽使用的 Host ACL Event 区间',host,'                AC(aclrtRecordEvent(r.begin','                float ms=',true);
    if(family==='store-tail')add('同一 GM 分配上的随机配对顺序',host,'            // 一对样本共用 GM','                AC(aclrtMemset(r.out');
    if(family==='workset')add('全曲线 GM 固定分配、输入 pattern 与逐点扫描',host,'        size_t inputBytes','            std::vector<double>',false);
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
  if(family==='page-retest'){
    const single=['power2','capacity','alignment','alignment-paired'].includes(r.kind);
    const view={...db,evidence:{...db.evidence,memoryPolicy:r.memoryPolicy,cachePolicy:{mode:'CANN API default normal'}}};
    const context=implementationContext(single?'alignment':r.kind==='tail'?'store-tail':'bandwidth',r,view);
    context.params.push(['数据 GM 输入 / 输出策略',`${r.memoryPolicy.input} / ${r.memoryPolicy.output}`]);
    if(r.memoryPolicy.capacities_bytes)context.params.push(['实际输入 / 输出申请容量',`${r.memoryPolicy.capacities_bytes[0]} / ${r.memoryPolicy.capacities_bytes[2]} B`]);
    if(r.allocationBytes)context.params.push(['输入 / 输出申请容量',`${r.allocationBytes.input} / ${r.allocationBytes.output} B`],['核记录申请容量',`${r.allocationBytes.records} B`]);
    if(r.allocationBytes)context.notes.push('上述 C++ 申请容量由当前短批全部参数和绑定的 Host 分配源码计算，区别于该点实际触达的工作集；没有查询物理分配页表。');
    if(!single&&r.kind!=='tail')context.notes[1]='有效吞吐使用本次共同 ACL Event，保留源码中的同步与导出成本；未测物理 HBM 事务。';
    if(r.kind==='workset')context.notes.push('每条方向/访问曲线在本短批共用固定 GM 分配，实际工作集按 ring 大小裁剪；各轮重新分配并随机大小顺序。');
    context.notes.push('本轮原始数据独立保留；普通页与大页优先的新单核配对使用同一 CANN、源码、shape 和循环参数。申请容量与实际触达工作集分别标注。');
    return context;
  }
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
  } else if(family==='peer-copy') {
    params.push(['方向 / AIV',`GM → UB / ${r.cores}`],['输入分配策略',r.allocation],['L2 / 输入模式',`${r.cache} / ${r.pattern}`],['完成方式',r.completion],['tile / 数据 UB',`${r.tileBytes} B / ${r.dataUbBytes} B`],['实际 GM 工作集',`${r.actualRing} B`],['全核 payload / 遍历次数',`${r.movedBytes} B / ${r.movedBytes/r.actualRing}`],['计时内读结果导出',`${r.readOutputBytes} B`]);
    timing='同 stream ACL Event 包围完整 kernel，预热、初始化输入与 Host 校验在计时外。核内 SYS_CNT 持续 ticks 单列，不相加核峰值。';
    notes=[r.implementation==='peer'?'原代码及 peer 变体：每 tile 前 32 B 独立 untimed 校验；计时循环后检查最后各 buffer 前 32 B。不是逐计时 launch 的完整输出校验。':'AKL：每个计时 launch 检查最后两组完整 UB 与 128 B 保护区，保留双窗口和 SyncAll。','分配对照只改变输入页策略；sink / records 的分配策略在各自实现内保持不变。HUGE_FIRST 可回退，HUGE_ONLY 成功表示未回退普通页。','每个配置使用新分配，轮次顺序随机；未测实际页表、TLB miss 或 HBM 物理事务。'];
  } else if(family==='bandwidth'||family==='store-tail'||family==='workset') {
    params.push(['方向 / AIV',`${r.direction} / ${r.cores}`],['tile × batch',`${r.tileBytes} B × ${r.batch}`],['UB 窗口 / 数据 UB',`2 / ${2*r.tileBytes*r.batch} B 每核`],['每核分区 / groups',`${r.perCoreRing} B / ${r.groups}`],['实际 GM 工作集',`${r.actualRing} B`],['全核有效字节',`${r.movedBytes} B`],['模式',r.control?'空循环 / 事件':r.sharedRead?'同址只读':'各核独立 GM 分区']);
    if(db.evidence.memoryPolicy)params.push(['GM 输入 / 输出分配',`${db.evidence.memoryPolicy.input} / ${db.evidence.memoryPolicy.output}`],['L2 配置',db.evidence.cachePolicy.mode]);
    timing='同 stream ACL Event 包围完整多核 kernel，包含调度、UB 初始化、两次 SyncAll、DMA、完成等待和结果导出。每核 SYS_CNT 只包围主体循环；聚合 GB/s 用共同 ACL 区间计算，不扣空对照。';
    notes=['双 UB 窗口交替，复用前等待对应 MTE2_S / MTE3_S；每组提交 batch 次 DataCopy(count)，不是无限深队列。','本点的有效 GB/s 属于这套流水、tile、batch 和计时条件；约 2.1 TB/s 不能证明物理 HBM 上限。','核内与完整 kernel 计时可以帮助定位开销；要归因实现瓶颈，仍需同条件的替代流水实测。'];
    if(family==='store-tail'){
      params.push(['完成模式 / 模板',`${r.mode} / TailOnly = ${r.mode==='tail'}`]);
      notes=[r.mode==='tail'?'源 UB 保持不变；循环内不设置或等待 MTE3_S 事件，仅末尾一次完成等待。提交速率仍受硬件队列回压约束。':'双窗口版本；每组设置信号，复用窗口前等待，最后排空两组。','同一进程、同一二进制和 GM 分配；同对样本使用相同参数和源 pattern，先后次序随机。','两种模式没有改变地址布局；本实验不能判断内存 bank / 通道冲突。'];
    }
    if(family==='workset'){
      params.push(['实际触达 / 每核遍历',`${r.coveredGmBytes} B / ${r.repeatsPerCore} 次`],['GM 分配方式','同一曲线固定分配；两轮分别随机大小顺序']);
      notes=['双窗口完成策略固定；只扫描 ring 的实际触达大小。分区场景每次共搬运 4 GiB，同址读增加请求量以保证每核完整遍历至少两次。','同址重复读的逻辑 payload 包含所有核请求；有效 TB/s 不是 HBM 物理流量。','缓存容量只是环境参照；未测缓存计数器或 bank / 通道映射，不据此归因。'];
    }
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
