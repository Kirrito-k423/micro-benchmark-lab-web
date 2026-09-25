// PROTOTYPE — three structurally different DataCopy explorers on /prototype/datacopy/?variant=A|B|C.
// Design question: chart-first workspace, table-first explorer, or evidence-first report?
import * as echarts from 'echarts';
import './style.css';

const db = await fetch(`${import.meta.env.BASE_URL}data/datacopy.json`).then(r => r.json());
const params = new URLSearchParams(location.search);
const state = { variant: ['A','B','C'].includes(params.get('variant')) ? params.get('variant') : 'A',
  direction:'GM_UB', mode:'small', windows:2, batch:1, metric:'gbps', device:'both', timing:'long',
  zoom:[0,100], query:'', sort:'bytes', descending:false, selected:null, page:0 };
const variants = { A:'性能工作台', B:'数据浏览器', C:'实验报告' };
const colors = { A3:'#15756c', A5:'#e47c44' };
const charts=[];
const fmt=(n,d=2)=>Number(n).toLocaleString('en-US',{maximumFractionDigits:d,minimumFractionDigits:d});
const bytes=n=>n>=1048576 ? `${fmt(n/1048576,1)} MiB` : n>=1024 ? `${fmt(n/1024,n%1024?2:0)} KiB` : `${n} B`;
const arrow=d=>d==='GM_UB'?'GM → UB':'UB → GM';
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const median=a=>{a=[...a].sort((a,b)=>a-b);return (a[Math.floor((a.length-1)/2)]+a[Math.ceil((a.length-1)/2)])/2;};
const icon=(name)=>{
  const paths={chart:'M4 19V5m0 14h16M8 15l4-5 4 2 4-7',grid:'M3 3h7v7H3zm11 0h7v7h-7zM3 14h7v7H3zm11 0h7v7h-7z',
    download:'M12 3v12m-5-5 5 5 5-5M5 17v4h14v-4',filter:'M3 5h18M6 12h12M9 19h6',chevron:'m9 5 7 7-7 7',
    check:'m5 12 4 4L19 6',external:'M14 3h7v7m0-7L10 14M10 3H3v18h18v-7',file:'M14 2H4v20h16V8zm0 0v6h6M8 13h8M8 17h6',
    search:'M20 20l-5-5M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0',chip:'M7 7h10v10H7zM9 2v5m6-5v5M9 17v5m6-5v5M2 9h5m-5 6h5m10-6h5m-5 6h5'};
  return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[name]||paths.chart}"/></svg>`;
};
function filtered(){return db.rows.filter(r=>r.direction===state.direction && r.mode===state.mode && r.windows===state.windows && r.batch===state.batch &&
  (state.device==='both'||r.device===state.device) && (state.timing==='all'||r.loops>=8192) &&
  (!state.query||`${r.device} ${r.bytes} ${bytes(r.bytes)} ${r.run}`.toLowerCase().includes(state.query.toLowerCase())));}
function grouped(rows){
  const map=new Map();
  for(const r of rows){const k=[r.device,r.bytes,r.loops,r.case.slots].join('/');if(!map.has(k))map.set(k,[]);map.get(k).push(r);}
  return [...map.values()].map(rs=>({...rs[0], p50:median(rs.map(r=>r.p50)),p95:median(rs.map(r=>r.p95)),gbps:rs[0].bytes/median(rs.map(r=>r.p50))/1000,
    members:rs,repeats:rs.length,low:Math.min(...rs.map(r=>r.gbps)),high:Math.max(...rs.map(r=>r.gbps))})).sort((a,b)=>a.bytes-b.bytes);
}
function brand(){return `<a class="brand" href="?variant=${state.variant}"><span class="brand-mark">${icon('chart')}</span><span>micro<span class="brand-light">bench</span><small>AKL MEASUREMENT LAB</small></span></a>`;}
function topbar(){return `<header class="topbar">${brand()}<nav><span class="active">测量结果</span><a href="https://github.com/Kirrito-k423/ascend-kernel-lab" target="_blank" rel="noreferrer">AKL 源码 ${icon('external')}</a></nav><div class="top-right"><span class="live-dot"></span>真实 NPU 数据 <span class="separator">/</span> <span class="mono">2026.09.25</span><a class="repo-link" href="https://github.com/Kirrito-k423/micro-benchmark-lab-web/tree/codex/prototype-datacopy-lab" target="_blank">GitHub ↗</a></div></header>`;}
function chips(key, items){return `<div class="segmented">${items.map(([v,label])=>`<button data-key="${key}" data-value="${v}" class="${String(state[key])===String(v)?'selected':''}">${label}</button>`).join('')}</div>`;}
function select(key,items){return `<select data-select="${key}" aria-label="${key}">${items.map(([v,t])=>`<option value="${v}" ${String(state[key])===String(v)?'selected':''}>${t}</option>`).join('')}</select>`;}
function filters(vertical=false){return `<div class="filters ${vertical?'vertical':''}">
  <div class="filter-field"><label>设备</label>${chips('device',[['both','A3 + A5'],['A3','A3'],['A5','A5']])}</div>
  <div class="filter-field"><label>搬运方向</label>${chips('direction',[['GM_UB','GM → UB'],['UB_GM','UB → GM']])}</div>
  <div class="filter-field"><label>工作集</label>${select('mode',[['small','重复小工作集'],['ring','64 MiB 环形工作集']])}</div>
  <div class="filter-field"><label>UB 窗口</label>${chips('windows',[[1,'单窗口'],[2,'双窗口']])}</div>
  <div class="filter-field"><label>每批调用数</label>${select('batch',[1,2,4,8,16,32,64].map(x=>[x,`batch = ${x}`]))}</div>
  <div class="filter-field"><label>计时范围</label>${select('timing',[['long','长计时 · ≥ 8192 loops'],['all','全部 · 含早期 128 loops']])}</div>
  </div>`;}
function environmentMini(){return `<div class="env-mini"><div class="eyebrow">测量条件</div><p>DataCopy(params)<br>uint32 · 单 AIV · 本地 GM</p><div><i class="dot a3"></i><b>A3</b><span>CANN 9.1.0-beta.1</span></div><div><i class="dot a5"></i><b>A5</b><span>CANN 9.2.0</span></div><small>跨芯片与 CANN 的实验对照；曲线不等同于整卡 HBM 峰值。</small></div>`;}
function toolbar(){return `<div class="chart-toolbar">${chips('metric',[['gbps','有效吞吐'],['p50','完成耗时']])}<span class="toolbar-spacer"></span><button class="quiet" data-action="zoom-large">大 shape</button><button class="quiet" data-action="zoom-all">全部</button><button class="quiet" data-action="svg">${icon('download')} SVG</button></div>`;}
function chartPanel(id='main-chart',compact=false){return `<section class="panel chart-panel"><div class="panel-head"><div><div class="eyebrow">PAYLOAD / ${state.metric==='gbps'?'THROUGHPUT':'LATENCY'}</div><h2>${state.metric==='gbps'?'数据量与有效吞吐':'数据量与每调用完成耗时'}</h2></div><span class="subtle">${arrow(state.direction)} · ${state.windows} 个窗口</span></div>${toolbar()}<div id="${id}" class="chart ${compact?'compact':''}"></div><div class="chart-caption"><span>对数横轴 · 拖动下方滑块缩放 · 点击实测点查看样本</span><span>同配置跨轮 p50 取中位数</span></div></section>`;}
function tablePanel(rows,large=false){return `<section class="panel table-panel ${large?'large-table':''}"><div class="panel-head"><div><div class="eyebrow">MEASURED POINTS</div><h2>实测数据 <span class="count">${rows.length}</span></h2></div><div class="table-tools"><label class="search">${icon('search')}<input id="search" placeholder="搜索 shape / run" value="${esc(state.query)}" aria-label="搜索 shape 或 run"></label><button class="quiet" data-action="csv">${icon('download')} CSV</button></div></div><div id="table-body"></div></section>`;}
function detailPanel(){return `<aside class="panel detail-panel"><div class="panel-head"><div><div class="eyebrow">POINT INSPECTOR</div><h2>一个点，完整证据</h2></div><span class="evidence-dot"></span></div><div id="detail-body"></div></aside>`;}
function stats(rows){return `<div class="stats">${['A3','A5'].map(device=>{const rr=rows.filter(r=>r.device===device);const max=rr.length?Math.max(...rr.map(r=>r.gbps)):null;return `<div class="stat"><div><i class="dot ${device.toLowerCase()}"></i>${device} <span>当前筛选 · 观测最大值</span></div><strong>${max===null?'—':fmt(max,1)}<small>GB/s</small></strong><p>${rr.length} 个配置点 · ${db.environments[device].soc}</p></div>`;}).join('')}<div class="stat stats-note"><div>${icon('check')} EVIDENCE INCLUDED</div><strong>${fmt(filtered().length*20,0)}<small>样本</small></strong><p>原始 tick 可追溯 · 两轮结果均保留</p></div></div>`;}
function stateSummary(){return `<details class="prototype-state"><summary>当前探索状态 · ${variants[state.variant]} <span>查看全部条件</span></summary><pre>${esc(JSON.stringify({...state,matchedRows:filtered().length,environment:db.environments,api:'DataCopy(params)',dtype:'uint32',aivCount:1},null,2))}</pre></details>`;}
function VariantA(rows){return `${topbar()}<div class="workbench"><aside class="sidebar"><div class="eyebrow">BENCHMARK LIBRARY</div><div class="library-item">${icon('chip')}<b>DataCopy</b><span>01</span></div><div class="side-rule"></div><div class="side-title">${icon('filter')}实验条件<button class="reset" data-action="reset">重置</button></div>${filters(true)}${environmentMini()}</aside><main class="workspace"><div class="page-heading"><div><div class="breadcrumb">接口基准 <span>/</span> 内存搬运</div><h1>DataCopy<span class="tag">A3 × A5</span></h1><p>从小数据量的延迟，到持续搬运的吞吐平台。</p></div><div class="dataset-stamp">1,900<span>配置轮次 · 38,000 个样本</span></div></div>${stats(rows)}<div class="work-grid"><div>${chartPanel()}${tablePanel(rows)}</div>${detailPanel()}</div>${stateSummary()}</main></div>`;}
function VariantB(rows){return `<div class="browser-shell">${topbar()}<main class="data-browser"><div class="browser-heading"><div class="eyebrow">DATA EXPLORER / 001</div><div><h1>DataCopy<span class="outline-badge">LIVE DATASET</span></h1><p>先找到可比的数据，再展开每一个差异。</p></div><a class="source-link" href="${db.sources.A5}" target="_blank">A5 原始回传 ${icon('external')}</a></div><div class="querybar">${icon('filter')}${filters()}</div><div class="browser-status"><span><i class="live-dot"></i> ${rows.length} 个配置点 / ${filtered().length} 个轮次</span><span>uint32 · 1 AIV · ${state.mode==='small'?'小工作集':'64 MiB ring'} · ${state.windows===2?'双窗口流水':'每批等待完成'}</span><span>A3 / CANN 9.1.0-beta.1 · A5 / CANN 9.2.0</span></div><div class="browser-grid"><div>${tablePanel(rows,true)}</div><div class="browser-right">${chartPanel('main-chart',true)}${detailPanel()}</div></div>${stateSummary()}</main></div>`;}
function VariantC(rows){return `${topbar()}<main class="report-shell"><div class="report-masthead"><div class="eyebrow">MICRO BENCHMARK LAB / FIELD NOTES</div><span>实验档案 № 001 <b>2026.09</b></span></div><div class="report-hero"><div><span class="report-kicker">DATA MOVEMENT · A3 / A5</span><h1>一次搬运，<br>究竟能有多快<span>？</span></h1><p>沿着数据量，观察 DataCopy 从延迟主导到吞吐平台的变化。所有点均来自真实 NPU 测量。</p></div><aside><span class="eyebrow">本次档案</span><dl><dt>设备</dt><dd>A3 / Ascend950DT</dd><dt>测量接口</dt><dd>DataCopy(params)</dd><dt>配置轮次</dt><dd>1,900</dd><dt>原始计时样本</dt><dd>38,000</dd></dl><a href="${db.sources.A5}" target="_blank">打开 A5 回传证据 ↗</a></aside></div><div class="report-section-title"><span>01</span><h2>把条件对齐，再看曲线。</h2><small>交互式实验切片</small></div><div class="report-filters">${filters()}</div>${stats(rows)}${chartPanel()}<div class="report-note"><b>如何读这张图</b><p>每个点汇总同一设备、shape、循环数和工作集的重复测量。点选后可查看每轮 20 个原始样本。A3 与 A5 的 CANN 版本不同，曲线反映各自环境，不把差异单独归因于芯片。</p></div><div class="report-section-title"><span>02</span><h2>结论需要可以回到样本。</h2><small>记录与证据</small></div><div class="report-bottom">${tablePanel(rows)}${detailPanel()}</div><div class="report-footnotes">${environmentMini()}<div><div class="eyebrow">计时口径</div><p>循环区间总完成时间 ÷ 调用次数。包含地址计算、提交、等待与最终排空，未扣空循环；不是单个请求的尾延迟。</p><a href="${db.sources.A3}" target="_blank">A3 归档数据 ↗</a> <a href="${db.sources.A5}" target="_blank">A5 回传数据 ↗</a></div></div>${stateSummary()}</main>`;}
function switcher(){return import.meta.env.DEV?`<div class="prototype-switcher"><span class="proto-label">PROTOTYPE</span><button data-cycle="-1" aria-label="上一个方案">←</button><div><b>${state.variant}</b><span>${variants[state.variant]}</span></div><button data-cycle="1" aria-label="下一个方案">→</button><span class="proto-dots">${['A','B','C'].map(v=>`<button data-variant="${v}" class="${v===state.variant?'on':''}" aria-label="方案 ${v}"></button>`).join('')}</span></div>`:'';}
function render(){
  // 替换页面和初始化图表期间保留文档高度，防止浏览器提前压缩滚动位置。
  const root=document.querySelector('#app');
  const viewport={x:window.scrollX,y:window.scrollY,minHeight:root.style.minHeight};
  const tableScroll=document.querySelector('.table-scroll')?.scrollLeft||0;
  const openDetails=[...document.querySelectorAll('details[open]')].map(d=>d.className);
  const active=document.activeElement;
  const focusSelector=active?.id?`#${CSS.escape(active.id)}`:
    ['data-select','data-key','data-sort','data-row','data-page','data-cycle','data-variant','data-action'].filter(a=>active?.hasAttribute(a)).map(a=>`[${a}="${CSS.escape(active.getAttribute(a))}"]`).join('')+(active?.hasAttribute('data-value')?`[data-value="${CSS.escape(active.dataset.value)}"]`:'');
  root.style.minHeight=`${root.offsetHeight}px`;
  charts.splice(0).forEach(c=>c.dispose());
  document.body.dataset.variant=state.variant;
  const rows=grouped(filtered());
  if(!rows.some(r=>r.members.some(m=>m.id===state.selected)))state.selected=rows.find(r=>r.device==='A5'&&r.bytes===32768)?.members[0].id||rows.at(-1)?.members[0].id||null;
  root.innerHTML=({A:VariantA,B:VariantB,C:VariantC}[state.variant])(rows)+switcher();
  renderTable(rows);renderDetail();mountChart(rows);bind();
  document.querySelectorAll('details').forEach(d=>{d.open=openDetails.includes(d.className);});
  document.querySelector('.table-scroll').scrollLeft=tableScroll;
  if(focusSelector)document.querySelector(focusSelector)?.focus({preventScroll:true});
  root.style.minHeight=viewport.minHeight;
  window.scrollTo({left:viewport.x,top:viewport.y,behavior:'instant'});
}
function renderTable(rows){
  rows=[...rows].sort((a,b)=>(state.sort==='device'?a.device.localeCompare(b.device):a[state.sort]-b[state.sort])*(state.descending?-1:1));
  const pageSize=state.variant==='B'?16:7;const pages=Math.max(1,Math.ceil(rows.length/pageSize));state.page=Math.min(state.page,pages-1);
  const headers=[['device','设备'],['bytes','每次数据量'],['p50','p50 / μs'],['p95','p95 / μs'],['gbps','GB/s'],['repeats','轮次']];
  document.querySelector('#table-body').innerHTML=`<div class="table-scroll"><table><thead><tr>${headers.map(([k,t])=>`<th><button data-sort="${k}">${t}${state.sort===k?(state.descending?' ↓':' ↑'):''}</button></th>`).join('')}</tr></thead><tbody>${rows.slice(state.page*pageSize,(state.page+1)*pageSize).map(r=>`<tr tabindex="0" data-row="${esc(r.members[0].id)}" class="${r.members.some(m=>m.id===state.selected)?'chosen':''}"><td><span class="device-label ${r.device.toLowerCase()}">${r.device}</span></td><td><b>${bytes(r.bytes)}</b><small>${r.loops.toLocaleString()} loops</small></td><td class="mono">${fmt(r.p50,4)}</td><td class="mono">${fmt(r.p95,4)}</td><td class="mono bandwidth">${fmt(r.gbps,2)}</td><td>${r.repeats}<span class="row-arrow">↗</span></td></tr>`).join('')||'<tr><td colspan="6" class="empty">当前条件没有测量数据。试试「全部计时」或更换 batch。</td></tr>'}</tbody></table></div><div class="pagination"><span>同配置跨轮统计 · 点击列名排序</span><div><button data-page="-1" ${state.page===0?'disabled':''}>←</button><span>${state.page+1} / ${pages}</span><button data-page="1" ${state.page===pages-1?'disabled':''}>→</button></div></div>`;
}
function renderDetail(){
  const r=db.rows.find(r=>r.id===state.selected);const el=document.querySelector('#detail-body');if(!r){el.innerHTML='<p class="empty">暂无匹配样本</p>';return;}
  const matches=grouped(filtered()).find(g=>g.members.some(m=>m.id===r.id));
  const env=db.environments[r.device];const jitter=r.p95/r.p50;
  el.innerHTML=`<div class="detail-top"><span class="device-label ${r.device.toLowerCase()}">${r.device}</span><span>${arrow(r.direction)}</span><strong>${bytes(r.bytes)}</strong><p>${r.windows===2?'双窗口流水':'单窗口 · 每批完成'} · batch ${r.batch}</p></div><label class="run-select">测量轮次<select id="run-select">${matches.members.map(m=>`<option value="${esc(m.id)}" ${m.id===r.id?'selected':''}>${esc(m.run)}</option>`).join('')}</select></label><div class="detail-values"><div><span>p50 完成耗时</span><b>${fmt(r.p50,4)}<small> μs</small></b></div><div><span>有效吞吐</span><b>${fmt(r.gbps,2)}<small> GB/s</small></b></div></div><div class="sample-heading"><b>20 个原始样本</b><span>每调用 μs</span></div><div id="sample-chart"></div><div class="jitter"><span>p95 / p50</span><b class="${jitter>1.10?'warm':''}">${fmt(jitter,3)}×</b><span>${jitter>1.10?'可见波动':'≤ 1.10'}</span></div><dl class="evidence-list"><dt>工作集</dt><dd>${bytes(r.workingSet)}</dd><dt>循环 × batch</dt><dd>${r.loops.toLocaleString()} × ${r.batch}</dd><dt>芯片</dt><dd>${env.soc}</dd><dt>CANN</dt><dd>${env.cann}</dd><dt>计数频率</dt><dd>${env.clockHz/1e6} MHz</dd><dt>输出校验</dt><dd class="validated">${icon('check')} validated</dd></dl><p class="timing-note">区间总耗时 ÷ 调用次数；含等待与排空，不代表独立请求延迟。</p><details class="raw-evidence"><summary>原始 tick 与完整参数</summary><pre>${esc(JSON.stringify({case:r.case,clockHz:r.clockHz,rawTotalTicks:r.rawTicks,manifestSha256:r.manifestHash},null,2))}</pre></details><a class="evidence-link" href="${db.sources[r.device]}" target="_blank">查看来源与测量口径 ${icon('external')}</a>`;
  const dark=state.variant==='B';const chart=echarts.init(document.querySelector('#sample-chart'),null,{renderer:'svg'});charts.push(chart);
  const values=r.rawTicks.map(t=>Number(t)*1e6/r.clockHz/(r.loops*r.batch));
  chart.setOption({animation:false,grid:{left:54,right:14,top:14,bottom:22},tooltip:{trigger:'axis',valueFormatter:v=>`${fmt(v,5)} μs`},xAxis:{type:'category',data:values.map((_,i)=>i+1),axisLabel:{color:dark?'#97a9b1':'#7c8787',fontSize:10},axisLine:{show:false},axisTick:{show:false}},yAxis:{type:'value',scale:true,splitNumber:3,axisLabel:{color:dark?'#97a9b1':'#7c8787',fontSize:9,formatter:v=>fmt(v,4)},splitLine:{lineStyle:{color:dark?'#293940':'#eaf0ed'}}},series:[{type:'line',data:values,symbolSize:5,lineStyle:{width:1.5},itemStyle:{color:dark?(r.device==='A3'?'#82d6c9':'#f6ac76'):colors[r.device]},markLine:{silent:true,symbol:'none',label:{show:false},data:[{yAxis:r.p50}],lineStyle:{type:'dashed',color:'#879c9c'}}}]});
  el.querySelector('#run-select').onchange=e=>{state.selected=e.target.value;render();};
}
function mountChart(rows){
  const dark=state.variant==='B';const chart=echarts.init(document.querySelector('#main-chart'),null,{renderer:'svg'});charts.push(chart);
  const seriesMap=new Map();for(const r of rows){const key=r.mode==='ring'?`${r.device} · loops 随 shape 调整`:`${r.device} · ${r.loops.toLocaleString()} loops`;if(!seriesMap.has(key))seriesMap.set(key,[]);seriesMap.get(key).push(r);}
  const series=[...seriesMap.entries()].map(([name,rs])=>({name,type:'line',smooth:false,symbol:'circle',symbolSize:7,
    lineStyle:{width:2.5,type:rs[0].loops<8192?'dashed':'solid'},itemStyle:{color:dark?(rs[0].device==='A3'?'#82d6c9':'#f6ac76'):colors[rs[0].device]},
    emphasis:{focus:'series',scale:1.5},data:rs.map(r=>({value:[r.bytes,r[state.metric]],row:r,id:r.members[0].id}))}));
  chart.setOption({animation:false,textStyle:{fontFamily:'Inter, -apple-system, sans-serif'},legend:{top:6,left:18,itemWidth:22,itemHeight:8,textStyle:{color:dark?'#c5d3d8':'#48615d',fontSize:11}},
    tooltip:{trigger:'item',backgroundColor:dark?'#25343c':'#fff',borderColor:dark?'#40525b':'#d8e3de',textStyle:{color:dark?'#fff':'#243d38'},formatter:p=>{const r=p.data.row;return `<b>${r.device} · ${bytes(r.bytes)}</b><br>有效吞吐：${fmt(r.gbps,2)} GB/s<br>p50：${fmt(r.p50,4)} μs<br>${r.repeats} 轮 · ${r.loops} loops<br><span style="opacity:.65">点击查看 20 个原始样本</span>`;}},
    grid:{left:62,right:28,top:65,bottom:78},xAxis:{type:'log',logBase:2,min:rows.length?Math.min(...rows.map(r=>r.bytes)):32,max:rows.length?2**Math.ceil(Math.log2(Math.max(...rows.map(r=>r.bytes)))):131072,splitNumber:7,name:'每次搬运字节数',nameLocation:'middle',nameGap:29,axisLine:{lineStyle:{color:dark?'#415159':'#cdd8d4'}},axisTick:{show:false},axisLabel:{color:dark?'#9cb0ba':'#778984',fontSize:10,formatter:v=>bytes(v)},splitLine:{show:false}},
    yAxis:{type:'value',name:state.metric==='gbps'?'GB/s':'μs / call',nameTextStyle:{color:dark?'#9cb0ba':'#71857f'},axisLabel:{color:dark?'#9cb0ba':'#778984',fontSize:11},splitLine:{lineStyle:{color:dark?'#28383f':'#e9eeeb',type:'dashed'}}},
    dataZoom:[{type:'inside',xAxisIndex:0,filterMode:'none',start:state.zoom[0],end:state.zoom[1]},{type:'slider',xAxisIndex:0,start:state.zoom[0],end:state.zoom[1],height:15,bottom:8,borderColor:'transparent',backgroundColor:dark?'#1c2b32':'#f0f4f1',fillerColor:dark?'#74d6be26':'#15756c14',handleStyle:{color:dark?'#82d6c9':'#15756c'},showDetail:false}],series});
  chart.on('datazoom',e=>{const z=e.batch?.[0]||e;state.zoom=[z.start,z.end];queueMicrotask(()=>{if(!chart.isDisposed())chart.resize();});const visibleState=document.querySelector('.prototype-state pre');if(visibleState)visibleState.textContent=JSON.stringify({...state,matchedRows:filtered().length,environment:db.environments,api:'DataCopy(params)',dtype:'uint32',aivCount:1},null,2);});
  chart.on('click',p=>{if(p.data?.id){state.selected=p.data.id;render();}});
  if(!rows.length)chart.setOption({graphic:[{type:'text',left:'center',top:'middle',style:{text:'当前筛选没有数据',fill:'#839b95'}}]});
}
function bind(){
  document.querySelectorAll('[data-key]').forEach(b=>b.onclick=()=>{const k=b.dataset.key;state[k]=['batch','windows'].includes(k)?Number(b.dataset.value):b.dataset.value;state.page=0;state.zoom=[0,100];render();});
  document.querySelectorAll('[data-select]').forEach(s=>s.onchange=()=>{state[s.dataset.select]=s.dataset.select==='batch'?Number(s.value):s.value;state.page=0;state.zoom=[0,100];render();});
  document.querySelectorAll('[data-sort]').forEach(b=>b.onclick=()=>{state.descending=state.sort===b.dataset.sort?!state.descending:false;state.sort=b.dataset.sort;render();});
  document.querySelectorAll('[data-row]').forEach(b=>{b.onclick=()=>{state.selected=b.dataset.row;render();};b.onkeydown=e=>{if(e.key==='Enter')b.click();};});
  document.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>{state.page+=Number(b.dataset.page);render();});
  document.querySelectorAll('[data-cycle]').forEach(b=>b.onclick=()=>cycle(Number(b.dataset.cycle)));
  // body 也带 data-variant 用于样式，不能把它绑定成方案切换按钮。
  document.querySelectorAll('button[data-variant]').forEach(b=>b.onclick=()=>switchVariant(b.dataset.variant));
  document.querySelector('#search').oninput=e=>{const pos=e.target.selectionStart;state.query=e.target.value;state.page=0;render();const s=document.querySelector('#search');s.focus({preventScroll:true});s.setSelectionRange(pos,pos);};
  document.querySelectorAll('[data-action]').forEach(b=>b.onclick=()=>{if(b.dataset.action==='reset'){Object.assign(state,{direction:'GM_UB',mode:'small',windows:2,batch:1,metric:'gbps',device:'both',timing:'long',query:'',page:0,zoom:[0,100]});render();}if(b.dataset.action.startsWith('zoom-')){const current=filtered();const min=Math.min(...current.map(r=>r.bytes));const max=2**Math.ceil(Math.log2(Math.max(...current.map(r=>r.bytes))));state.zoom=b.dataset.action==='zoom-large'&&current.length?[Math.max(0,(Math.max(min,Math.min(8192,max/4))-min)/(max-min)*100),100]:[0,100];echarts.getInstanceByDom(document.querySelector('#main-chart')).dispatchAction({type:'dataZoom',start:state.zoom[0],end:state.zoom[1]});echarts.getInstanceByDom(document.querySelector('#main-chart')).getZr().flush();echarts.getInstanceByDom(document.querySelector('#main-chart')).resize();}if(b.dataset.action==='csv')downloadCSV();if(b.dataset.action==='svg'){const c=echarts.getInstanceByDom(document.querySelector('#main-chart'));download(c.getDataURL({type:'svg',pixelRatio:2,backgroundColor:state.variant==='B'?'#17252c':'#fff'}),'datacopy-chart.svg');}});
}
function switchVariant(v){state.variant=v;const u=new URL(location.href);u.searchParams.set('variant',v);history.replaceState(null,'',u);render();}
function cycle(delta){const keys=['A','B','C'];switchVariant(keys[(keys.indexOf(state.variant)+delta+3)%3]);}
document.addEventListener('keydown',e=>{if(!import.meta.env.DEV||e.target.closest('input,textarea,select,[contenteditable]'))return;if(e.key==='ArrowRight'){e.preventDefault();cycle(1);}if(e.key==='ArrowLeft'){e.preventDefault();cycle(-1);}});
window.addEventListener('resize',()=>charts.forEach(c=>c.resize()));
function download(url,name){const a=document.createElement('a');a.href=url;a.download=name;a.click();}
function downloadCSV(){const fields=['device','run','direction','bytes','batch','windows','loops','workingSet','p50','p95','gbps','clockHz'];const csv=[fields.join(','),...filtered().map(r=>fields.map(f=>r[f]).join(','))].join('\n');const url=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}));download(url,'datacopy-filtered-runs.csv');setTimeout(()=>URL.revokeObjectURL(url),1000);}
render();
