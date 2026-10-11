import * as echarts from './chart-layout.js';
import './mbench.css';
import { applyLabShell, libraryHeader } from './lab-shell.js';
import { loadMeasurementCode, showMeasurementCode, codeLink } from './measurement-code.js';
import { measurementGroups, plotValue } from './latency-duplex-data.js';

const policies = { normal: '普通页', 'huge-first': '大页优先' };
const modes = { read: '只读', write: '只写', duplex: '同时读写' };
const fmt = (n, d = 3) => Number(n).toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
const size = n => n >= 2 ** 30 ? `${fmt(n / 2 ** 30, 2)} GiB` : n >= 2 ** 20 ? `${fmt(n / 2 ** 20, 2)} MiB` : n >= 1024 ? `${n / 1024} KiB` : `${n} B`;
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export async function mountLatencyDuplex() {
  document.body.dataset.variant = 'A';
  document.title = 'Micro Benchmark Lab · DataCopy 延迟与双向读写';
  const root = document.querySelector('#app');
  const db = await fetch(`${import.meta.env.BASE_URL}data/a5-latency-duplex.json`)
    .then(r => r.ok ? r.json() : null).catch(() => null);
  if (!db || db.evidence.receiverValidation !== 'passed' && !import.meta.env.DEV) {
    root.innerHTML = `${libraryHeader()}<main class="lab-main"><div class="lab-heading"><div class="eyebrow">DATACOPY / LATENCY & DUPLEX</div><h1>延迟与双向同时读写</h1><p>完整两轮接收验收后发布。单请求延迟覆盖 32 B 至 4 MiB；双向读写使用独立地址和缓冲，并与同一分配上的只读、只写配对比较。</p></div><section class="panel bw-notes"><p>新测量的源码、原始计时、正确性和整机占用分别验收。已有曲线继续保留。</p></section></main>`;
    applyLabShell(root, 'latency-duplex'); return;
  }
  await loadMeasurementCode();
  const state = { kind: new URLSearchParams(location.search).get('experiment') === 'duplex' ? 'duplex' : 'latency',
    api: 'DataCopy_count', direction: 'GM_UB', windows: '1', policy: 'all', round: 'all',
    stat: 'p50', scale: 'log', ring: String(2 ** 31), tile: '32768', mode: 'all', metric: 'total', selected: null };
  let chart, samples;
  const latency = () => state.kind === 'latency';
  const unit = () => latency() || state.metric === 'us' ? 'μs' : 'TB/s';
  const choose = (key, label, options) => `<label class="lab-field">${label}<select id="ld-${key}" data-filter="${key}">${options.map(([v, t]) => `<option value="${v}" ${String(v) === state[key] ? 'selected' : ''}>${t}</option>`).join('')}</select></label>`;
  function controls() {
    let fields = choose('kind', '实验', [['latency', '单请求完成延迟'], ['duplex', '独立地址 · 双向带宽']]);
    if (latency()) fields += choose('api', 'API 重载', ['DataCopy_count', 'DataCopy_params', 'DataCopyPad_params'].map(n => [n, n])) +
      choose('direction', '方向', [['GM_UB', 'GM → UB'], ['UB_GM', 'UB → GM']]) +
      choose('windows', '每方向 UB 窗口', [['1', '1'], ['2', '2']]) +
      choose('stat', '单次请求延迟', [['p50', 'p50'], ['p95', 'p95 · 每轮 12 次观察']]) +
      choose('scale', '延迟纵轴', [['log', '对数 · 展开小请求'], ['value', '线性']]);
    else fields += choose('ring', '每方向工作集', [['small', '每核两 tile · 小范围复用'], [String(128 * 2 ** 20), '128 MiB'], [String(2 ** 31), '2 GiB']]) +
      choose('tile', '每方向 DMA tile', [['4096', '4 KiB'], ['32768', '32 KiB']]) +
      choose('mode', '同一分配上的模式', [['all', '只读 / 只写 / 同时读写'], ...Object.entries(modes)]) +
      choose('metric', '共同时间下的指标', [['total', '读写合计 · TB/s'], ['read', '读 · TB/s'], ['write', '写 · TB/s'], ['us', '完整 kernel · μs']]);
    return fields + choose('policy', '数据 GM 页策略', [['all', '两种策略'], ...Object.entries(policies)]) +
      choose('round', '测量轮次', [['all', '两轮统计值的中位数'], ['1', '第 1 轮'], ['2', '第 2 轮']]);
  }
  const seriesName = r => `${policies[r.allocation]}${latency() ? '' : ' / ' + modes[r.mode]}`;
  const pointTitle = r => latency() ? size(r.bytes) : `${r.cores} AIV · ${modes[r.mode]}`;
  function mark() { root.querySelectorAll('[data-point]').forEach(e => e.classList.toggle('chosen', e.dataset.point === state.selected)); }
  function detail(rows) {
    samples?.dispose(); samples = null;
    const r = rows.find(r => r.id === state.selected), panel = root.querySelector('#lab-detail');
    if (!r) { panel.innerHTML = '<p>当前筛选没有已验收点。</p>'; showMeasurementCode('latency-duplex', null, db); return; }
    panel.innerHTML = `${codeLink}<div class="eyebrow">POINT INSPECTOR</div><h2>${pointTitle(r)}</h2><div class="lab-point-value">${fmt(plotValue(r, state), 4)}<small> ${unit()}</small></div><p>${policies[r.allocation]}<br>${latency() ? `${size(r.tileBytes)} tile × ${r.tilesPerRequest} 次 / 完整请求<br>${r.windows} UB 窗口 · 1 个完整请求 / 启动` : `每方向工作集 ${size(r.workingSet)}<br>读 ${fmt(r.readGbps / 1000, 4)} / 写 ${fmt(r.writeGbps / 1000, 4)} TB/s<br>合计 ${fmt(r.gbps / 1000, 4)} TB/s · 同一共同时间`}</p>
      <label class="lab-field">原始样本轮次<select id="ld-sample-round">${r.members.map((m, i) => `<option value="${i}">第 ${m.round} 轮</option>`).join('')}</select></label>
      <label class="lab-field">样本计时范围<select id="ld-sample-timing"><option value="primary">${latency() ? '一次请求 · SYS_CNT' : '完整 kernel · trace-off ACL'}</option><option value="trace">完整 kernel · trace ACL</option>${latency() ? '<option value="plain">完整 kernel · trace-off ACL</option>' : ''}</select></label>
      <div id="lab-samples"></div><p>保留该轮全部 12 个正式样本。另有 12 次 trace 开 / 关配对；预热独立保存，不计入统计。</p>
      <details><summary>原始计时与完整参数</summary><pre>${esc(JSON.stringify(r.members, null, 2))}</pre></details>`;
    samples = echarts.init(panel.querySelector('#lab-samples'), null, { renderer: 'svg' });
    const draw = () => {
      const member = r.members[Number(panel.querySelector('#ld-sample-round').value)];
      const timing = panel.querySelector('#ld-sample-timing').value;
      const data = timing === 'primary' ? member.sampleUs : timing === 'plain' ? member.plainKernelSampleUs : member.kernelSampleUs || member.traceKernelSampleUs;
      showMeasurementCode('latency-duplex', member, db);
      samples.setOption({ animation: false, grid: { left: 55, right: 16, top: 22, bottom: 30 }, tooltip: { trigger: 'axis' },
        xAxis: { type: 'category', name: '正式样本', data: data.map((_, i) => i + 1) },
        yAxis: { type: 'value', scale: true, name: 'μs' },
        series: [{ type: 'line', data, itemStyle: { color: member.allocation === 'normal' ? '#e77d42' : '#16756b' } }] }, true);
    };
    draw(); panel.querySelector('#ld-sample-round').onchange = draw; panel.querySelector('#ld-sample-timing').onchange = draw;
  }
  function render() {
    const viewport = { x: scrollX, y: scrollY }, active = document.activeElement?.id;
    root.style.minHeight = `${root.offsetHeight}px`; chart?.dispose(); samples?.dispose(); samples = null;
    const fields = controls(), rows = measurementGroups(db, state);
    if (!rows.some(r => r.id === state.selected)) state.selected = rows[0]?.id;
    root.innerHTML = `${libraryHeader()}<main class="lab-main"><div class="lab-heading"><div class="eyebrow">DATACOPY / ${latency() ? 'ONE COMPLETE REQUEST' : 'INDEPENDENT READ & WRITE'}</div><h1>${latency() ? '单请求完成延迟' : '独立地址 · 双向同时读写'}</h1><p>${latency() ? '32 B 开始，每次翻倍到 4 MiB。每个启动只执行一次完整请求，包含最后一次 DMA 完成等待。' : '读取与写入在同一个 kernel 内先提交、再分别等待；使用独立 GM 地址和 UB 缓冲。只读、只写、同时读写在同一分配上随机配对。'}普通页与大页优先各两轮实测。</p></div>
      <div class="lab-env">${esc(db.environment.soc)} · ${esc(db.environment.cann)} · ${db.measuredDate} · ${db.evidence.configurationRounds.toLocaleString()} 配置轮次（含空协议对照） · ${db.evidence.receiverValidation === 'passed' ? '接收验收通过' : '本地部分数据预览'}</div>
      <section class="panel lab-controls">${fields}</section>
      <div class="lab-grid"><section class="panel"><div class="panel-head"><h2>${latency() ? '完整请求大小与完成延迟' : '并发 AIV 与共同时间吞吐'}</h2><button id="ld-export" class="quiet">CSV</button></div><div id="lab-chart"></div>
      <p class="lab-caption">${latency() ? '18 个倍增点完整覆盖；横轴是请求总字节，大请求由多个 tile 构成。p50 / p95 来自每轮 12 次独立启动；选择两轮时取两轮统计值的中位数。' : '读、写、合计均除以同一个 trace-off 完整 kernel 时间。没有相加只读 / 只写峰值或不同核的峰值。每方向 4 GiB 有效请求量；所选工作集是每方向 GM 范围。'}点选曲线或表格查看对应样本、完整参数与固定版本源码。</p></section><aside class="panel lab-inspector" id="lab-detail"></aside></div>
      <section class="panel lab-table" id="ld-table"><div class="panel-head"><h2>实际测量点 · ${rows.length}</h2><span class="subtle">${latency() ? '请求大小与 DMA tile 分列' : '同一共同时间分列读与写'}</span></div><div class="table-scroll"><table><thead><tr><th>${latency() ? '完整请求' : 'AIV / 模式'}</th><th>页策略</th><th>${latency() ? '请求 p50 / p95 μs' : '读 / 写 / 合计 TB/s'}</th><th>${latency() ? 'tile × 次数' : '完整 kernel p50 μs'}</th><th>实际工作集</th><th>轮次</th></tr></thead><tbody>${rows.map(r => `<tr tabindex="0" data-point="${r.id}" class="${r.id === state.selected ? 'chosen' : ''}"><td>${pointTitle(r)}</td><td>${policies[r.allocation]}</td><td>${latency() ? `${fmt(r.p50, 4)} / ${fmt(r.p95, 4)}` : `${fmt(r.readGbps / 1000, 4)} / ${fmt(r.writeGbps / 1000, 4)} / ${fmt(r.gbps / 1000, 4)}`}</td><td>${latency() ? `${size(r.tileBytes)} × ${r.tilesPerRequest}` : fmt(r.p50, 3)}</td><td>${size(r.workingSet)}${latency() ? '' : ' / 方向'}</td><td>${r.members.map(m => m.round).join(' / ')}</td></tr>`).join('')}</tbody></table></div></section>
      <section class="panel bw-notes"><h2>测量范围与实现</h2><p>${latency() ? '单请求 SYS_CNT 从 Vector 初始化完成之后开始，结束于最后 DMA 完成。与原来的“重复请求平均耗时”分开保留。count / params 的 tile 最大 64 KiB，Pad 最大 32 KiB；4 MiB 不表示 UB 中一次 API 的 shape。' : '每个 AIV 使用读、写各两个 UB 窗口；每方向 4 KiB / 32 KiB tile。复用前等待相应 MTE2_S / MTE3_S，末尾排空两个方向。聚合时间包含初始化、核间同步和保留读窗口导出；核内完成观测戳不能作为独立方向带宽的分母。'}</p><p>每个启动校验完整写目标或未改写目标、完整保留读窗口和 128 B 保护区；全部读 tile 使用独立的功能启动校验。默认 L2，HUGE_FIRST 可以回退；未采集实际页表、TLB、bank / 通道或物理 HBM 事务。独立地址也不能排除共享资源竞争。</p><p>空提交 / 完成协议对照和预热样本另存，不从延迟或吞吐中扣除。正式样本全部保留；有限的 12 次观察不能代表生产负载的长期 p95。</p></section>
      <footer class="lab-footer"><a href="${import.meta.env.BASE_URL}reports/a5-latency-duplex-20261011.md" download>实验报告与复现步骤</a> · <a href="${import.meta.env.BASE_URL}data/a5-latency-duplex.json" download>全部数据与对照</a> · <a href="https://github.com/Kirrito-k423/micro-benchmark-lab-web/tree/${db.evidence.sourceCommit}/experiments/a5_latency_duplex" target="_blank" rel="noreferrer">固定源码 ↗</a><details><summary>接收验收与覆盖</summary><pre>${esc(JSON.stringify({ ...db.evidence, sourceBindings: undefined }, null, 2))}</pre></details></footer></main>`;
    applyLabShell(root, 'latency-duplex');
    chart = echarts.init(root.querySelector('#lab-chart'), null, { renderer: 'svg' });
    const lines = [...new Set(rows.map(seriesName))];
    chart.setOption({ animation: false, legend: { type: 'scroll', top: 8, textStyle: { fontSize: 10 } },
      grid: { left: 65, right: 22, top: 70, bottom: 75 },
      tooltip: { trigger: 'item', formatter: p => `${esc(p.seriesName)}<br>${latency() ? size(p.value[0]) : p.value[0] + ' AIV'}<br>${fmt(p.value[1], 4)} ${unit()}` },
      xAxis: { type: latency() ? 'log' : 'value', logBase: 2, name: latency() ? '完整请求 / B' : 'AIV',
        min: Math.min(...rows.map(r => r.x)), max: Math.max(...rows.map(r => r.x)),
        axisLabel: { fontSize: 9, formatter: v => latency() ? size(v) : v } },
      yAxis: { type: latency() ? state.scale : 'value', logBase: 10, name: unit() },
      dataZoom: [{ type: 'inside', filterMode: 'none' }, { type: 'slider', height: 16, bottom: 15 }],
      series: lines.map(name => ({ name, type: 'line', symbolSize: 7, connectNulls: false,
        itemStyle: { color: name.startsWith(policies.normal) ? '#e77d42' : '#16756b' },
        symbol: name.includes('只写') ? 'rect' : name.includes('同时读写') ? 'diamond' : 'circle',
        lineStyle: { type: name.includes('只写') ? 'dotted' : name.includes('只读') ? 'dashed' : 'solid' },
        data: rows.filter(r => seriesName(r) === name).map(r => ({ value: [r.x, plotValue(r, state)], id: r.id })) })) });
    chart.on('click', p => { if (p.data?.id) { state.selected = p.data.id; detail(rows); mark(); } });
    root.querySelectorAll('[data-filter]').forEach(e => e.onchange = () => { state[e.dataset.filter] = e.value; render(); });
    root.querySelectorAll('[data-point]').forEach(e => { e.onclick = () => { state.selected = e.dataset.point; detail(rows); mark(); }; e.onkeydown = key => { if (key.key === 'Enter') e.click(); }; });
    root.querySelector('#ld-export').onclick = () => {
      const fields = ['id', 'kind', 'round', 'allocation', 'api', 'direction', 'mode', 'cores', 'bytes', 'tileBytes', 'windows', 'tilesPerRequest', 'workingSet', 'readBytes', 'writeBytes', 'movedBytes', 'p50', 'p95', 'readGbps', 'writeGbps', 'binaryHash'];
      const csv = [fields.join(','), ...rows.flatMap(r => r.members).map(r => fields.map(k => r[k] ?? '').join(','))].join('\n');
      const u = URL.createObjectURL(new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' }));
      const a = document.createElement('a'); a.href = u; a.download = 'a5-latency-duplex.csv'; a.click(); setTimeout(() => URL.revokeObjectURL(u), 1000);
    };
    detail(rows); document.getElementById(active)?.focus({ preventScroll: true });
    root.style.minHeight = ''; scrollTo({ left: viewport.x, top: viewport.y, behavior: 'instant' });
  }
  render();
}
