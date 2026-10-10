import * as echarts from 'echarts';
import './mbench.css';
import {showMeasurementCode, codeLink} from './measurement-code.js';
const median=xs=>{const a=[...xs].sort((x,y)=>x-y);return(a[Math.floor((a.length-1)/2)]+a[Math.ceil((a.length-1)/2)])/2;};
const fmt=(v,d=2)=>Number(v).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const preset=r=>`${r.tileBytes}/${r.batch}`;
const label=r=>`${r.tileBytes/1024} KiB × ${r.batch}`;
export async function mountBandwidth(){
  const db=await fetch(`${import.meta.env.BASE_URL}data/a5-bandwidth.json`).then(r=>{if(!r.ok)throw new Error('多核测量数据尚未发布');return r.json();});
  const root=document.querySelector('#app');
  const state={direction:'GM_UB',scope:'1g',preset:'all',metric:'gbps',round:'all',selected:null};
  let chart,sampleChart,balanceChart;let selectedLegend={};
  document.body.dataset.variant='A';document.title='Micro Benchmark Lab · DataCopy 多核带宽';
  const select=(k,title,items)=>`<label class="lab-field">${title}<select id="bw-${k}" data-filter="${k}">${items.map(([v,t])=>`<option value="${v}" ${String(v)===String(state[k])?'selected':''}>${t}</option>`).join('')}</select></label>`;
  const scopeMatch=r=>state.scope==='shared'?r.sharedRead&&!r.control:!r.sharedRead&&r.control===(state.scope==='control')&&r.requestedRing===(state.scope==='1g'?2**30:state.scope==='2g'?2**31:2**22);
  function groups(){
    const map=new Map();
    for(const r of db.rows){
      if(r.direction!==state.direction||!scopeMatch(r)||(state.round!=='all'&&r.round!==Number(state.round))||(state.preset!=='all'&&preset(r)!==state.preset))continue;
      const k=`${preset(r)}/${r.cores}`;if(!map.has(k))map.set(k,[]);map.get(k).push(r);
    }
    for(const rs of map.values())rs.sort((a,b)=>a.round-b.round);
    return [...map.values()].map(rs=>{const p50Us=median(rs.map(r=>r.p50Us));return {...rs[0],p50Us,p95Us:median(rs.map(r=>r.p95Us)),gbps:rs[0].movedBytes/p50Us/1000,members:rs};}).sort((a,b)=>a.cores-b.cores||a.tileBytes-b.tileBytes||a.batch-b.batch);
  }
  function currentCurves(){return db.curves.filter(r=>r.direction===state.direction&&scopeMatch(r)&&(state.preset==='all'||preset(r)===state.preset));}
  function y(r,rows){
    if(state.metric==='us')return r.p50Us;
    if(state.metric==='perCore')return r.gbps/r.cores;
    if(state.metric==='efficiency'){
      const one=rows.find(p=>preset(p)===preset(r)&&p.cores===1);return one?.gbps?r.gbps/(one.gbps*r.cores)*100:null;
    }
    return r.gbps;
  }
  function render(){
    const viewport={x:scrollX,y:scrollY};const active=document.activeElement?.id;const oldHeight=root.style.minHeight;
    root.style.minHeight=`${root.offsetHeight}px`;chart?.dispose();sampleChart?.dispose();balanceChart?.dispose();
    const rows=groups(),curves=currentCurves();
    if(!rows.some(r=>r.id===state.selected))state.selected=rows.find(r=>r.tileBytes===32768&&r.cores===db.environment.aiv_count)?.id||rows[0]?.id;
    const peak=curves.filter(c=>c.peakGbps!=null).sort((a,b)=>b.peakGbps-a.peakGbps)[0];
    const presets=[...new Map(db.rows.filter(r=>r.direction===state.direction&&scopeMatch(r)).map(r=>[preset(r),label(r)])).entries()];
    const scopeItems=[['1g','1 GiB · 大工作集 GM'],['2g','2 GiB · 更大地址覆盖'],['small','4 MiB · 小工作集'],...(state.direction==='GM_UB'?[['shared','128 KiB · 同址只读']]:[]),['control','空循环 / 完成事件对照']];
    const controls=select('direction','搬运方向',[['GM_UB','GM → UB'],['UB_GM','UB → GM']])+select('scope','GM 工作集',scopeItems)+
      select('preset','单次字节 × batch',[['all','比较全部配置'],...presets])+
      select('metric','纵轴',state.scope==='control'?[['us','整任务共同耗时 / μs']]:[['gbps','整卡聚合 · 有效 GB/s'],['perCore','平均每核 · 有效 GB/s'],['us','整任务共同耗时 / μs'],['efficiency','相对单核的并行效率 / %']])+
      select('round','轮次',[['all','两轮 p50 / p95 中位数'],[1,'第 1 轮'],[2,'第 2 轮']]);
    root.innerHTML=`<header class="topbar"><a class="brand" href="?variant=A">microbench<small>AKL MEASUREMENT LAB</small></a><div class="top-right">真实 A5 测量 · ${esc(db.environment.cann)}</div></header>
      <main class="lab-main"><nav class="lab-tabs"><a href="?variant=A">DataCopy 容量</a><a href="?lab=bandwidth" class="active">DataCopy 多核带宽</a><a href="?lab=peer-copy">大页 / 普通页对照</a><a href="?lab=workset">工作集拐点</a><a href="?lab=store-tail">纯写同步对照</a><a href="?lab=network">FullMesh / URMA</a><a href="?lab=alignment">DataCopy 对齐</a><a href="?lab=simd">SIMD ↔ SIMT</a><a href="?lab=overhead">SIMT 调用开销</a></nav>
      <div class="lab-heading"><div class="eyebrow">A5 / ONE DEVICE / MULTIPLE AIV CORES</div><h1>多少核能把 DataCopy 带宽推到平台？</h1><p>各核有独立 UB，同时使用同一设备的 GM。分区读写、同址只读与不同工作集分别测量。聚合带宽用全核有效字节除以整任务共同时间，原始值不扣空循环。</p></div>
      <p class="lab-caption">本页输入与输出使用 NORMAL_ONLY 普通页分配，保留历史实测。<a href="?lab=peer-copy">查看新实验：只改变输入分配的大页对照 ↗</a></p><div class="lab-env">${esc(db.environment.soc)} · ${esc(db.environment.cann)} · 运行时 ${db.environment.aiv_count} AIV · L2 配置 ${db.environment.l2_bytes/2**20} MiB · ${esc(db.measuredDate)}</div>
      <p class="lab-caption">${fmt(db.evidence.configsPerRound,0)} 配置 × 2 轮 · ${fmt(db.evidence.timedSamples,0)} 计时样本 · 每 launch 输出与保护区验证通过。两轮 p50 相对差异中位数 ${fmt(db.evidence.repeatability.medianRelativePct,3)}%，最大 ${fmt(db.evidence.repeatability.maxRelativePct,3)}%；不是置信区间。</p>
      <section class="panel lab-controls">${controls}</section>
      ${peak?`<section class="panel bw-summary"><div><span>本工作集观测最高 · 两轮 p50</span><b>${fmt(peak.peakGbps)} <small>GB/s</small></b><p>${label(peak)} · ${peak.peakCores} 核</p></div><div><span>已测档位中达到最高值 95% 的最少核数</span><b>${peak.n95} <small>核</small></b><p>${peak.adjacentPlateau?'相邻后续点也达到阈值':'尚未确认相邻点平台'} · 观测阈值，不是硬件上限</p></div><div><span>从单核到本配置最高值</span><b>${fmt(peak.speedupAtPeak)}<small> ×</small></b><p>整卡有效吞吐 ${state.scope==='shared'?'含重复同址逻辑读取':''}</p></div></section>`:'<p class="lab-caption">空对照没有有效搬运字节，带宽为 0；查看共同耗时及报告中的开销口径。</p>'}
      <div class="lab-grid"><section class="panel"><div class="panel-head"><h2>${state.direction==='GM_UB'?'读':'写'} · 核数与${state.metric==='us'?'共同耗时':'有效带宽'}</h2><button id="bw-export" class="quiet">CSV</button></div><div id="lab-chart"></div><p class="lab-caption">点击图例开关 · 拖动缩放 · 点击点查看共同区间和核内分布。${state.scope==='control'?'空对照只有循环与完成事件，未计有效搬运字节。':state.scope==='shared'?'同址读取包含重复逻辑请求，不能当成 HBM 物理带宽。':state.scope==='small'?'小工作集包含地址复用与缓存效果；各核读写分区互不重叠。':'分区地址互不重叠。大工作集虽超过 L2 配置容量，仍没有物理流量计数器证据。'}${state.round!=='all'?'上方观测阈值始终来自完整两轮；图表当前为所选单轮。':''}</p></section><aside class="panel lab-inspector" id="lab-detail"></aside></div>
      <section class="panel lab-table simd-results"><div class="panel-head"><h2>当前筛选的核数点</h2><span class="subtle">点击行更新证据</span></div><div class="table-scroll"><table><thead><tr><th>AIV</th><th>tile × batch</th><th>实际 GM 工作集</th><th>共同 p50 / μs</th><th>共同 p95 / μs</th><th>聚合 GB/s</th><th>每核 GB/s</th></tr></thead><tbody>${rows.map(r=>`<tr tabindex="0" data-point="${r.id}" class="${r.id===state.selected?'chosen':''}"><td>${r.cores}</td><td>${label(r)}</td><td>${fmt(r.actualRing/2**20)} MiB</td><td class="mono">${fmt(r.p50Us,3)}</td><td class="mono">${fmt(r.p95Us,3)}</td><td class="mono">${fmt(r.gbps)}</td><td class="mono">${fmt(r.gbps/r.cores)}</td></tr>`).join('')}</tbody></table></div></section>
      <section class="panel bw-notes"><h2>“N95”与“用满带宽”如何区分</h2><p>N95 只回答已测档位中达到本次曲线最高值 95% 的最少核数；还要看后续点是否进入平台。若到最大可用核数仍增长，不能把最后一个点叫硬件带宽上限。tile、batch、方向和工作集都可能改变这条曲线。</p><p>ACL Event 区间包含整个多核 kernel：调度、起止全核同步、UB 初始化、DMA、完成等待与少量结果导出。Host 上传、下载和输出检查在区间之外。每核 SYS_CNT 只计算核内 DMA 差值；不相加各核峰值，不拼接未校准的跨核绝对时钟。</p><p>请求总工作集按每核两组 UB 的大小取整。各核使用独立分区；同址对照只读。每次全核有效搬运约 2 GiB；2 GiB 工作集验证阶段约 4 GiB，实际字节数保留在证据中。</p></section>
      <footer class="lab-footer"><a href="https://github.com/Kirrito-k423/ascend-kernel-lab/tree/codex/a5-alignment-simt/examples/a5_bandwidth" target="_blank" rel="noreferrer">代码与 SOP ↗</a> · <a href="https://github.com/Kirrito-k423/micro-benchmark-lab-web/blob/codex/a5-mbench-results/reports/a5-bandwidth-20261009.md" target="_blank" rel="noreferrer">完整报告 ↗</a> · <a href="${import.meta.env.BASE_URL}figures/a5-bandwidth.png" download>PNG</a> · <a href="${import.meta.env.BASE_URL}figures/a5-bandwidth.svg" download>SVG</a><p>公开原始 ACL 毫秒样本和每核 SYS_CNT 差值。完整 start/end、设备日志、占用前后快照与源码/构建凭据保留在私有归档。</p><details><summary>计时、字节与验收证据</summary><pre>${esc(JSON.stringify(db.evidence,null,2))}</pre></details></footer></main>`;
    chart=echarts.init(root.querySelector('#lab-chart'),null,{renderer:'svg'});
    const series=[...new Set(rows.map(preset))].map(k=>{const rs=rows.filter(r=>preset(r)===k);return{name:label(rs[0]),type:'line',symbolSize:7,smooth:false,data:rs.map(r=>({value:[r.cores,y(r,rows)],id:r.id}))};});
    chart.setOption({animation:false,color:['#8a9db0','#875aa6','#16756b','#e77d42'],legend:{top:8,selected:selectedLegend},grid:{left:80,right:25,top:65,bottom:77},
      tooltip:{trigger:'item',formatter:p=>`${esc(p.seriesName)}<br>${p.value[0]} AIV<br>${fmt(p.value[1],3)} ${state.metric==='us'?'μs':state.metric==='efficiency'?'%':'GB/s'}`},
      xAxis:{type:'value',min:1,max:db.environment.aiv_count,name:'并行 AIV 数',nameLocation:'middle',nameGap:32},
      yAxis:{type:'value',name:state.metric==='us'?'共同 μs':state.metric==='efficiency'?'并行效率 %':state.metric==='perCore'?'GB/s / 核':'整卡有效 GB/s',scale:true},dataZoom:[{type:'inside',filterMode:'none'},{type:'slider',height:16,bottom:8}],series});
    chart.on('legendselectchanged',e=>{selectedLegend={...e.selected};});chart.on('click',p=>{if(p.data?.id){state.selected=p.data.id;detail(rows);mark();}});
    root.querySelectorAll('[data-filter]').forEach(el=>el.onchange=()=>{const k=el.dataset.filter;state[k]=el.value;
      if(k==='direction'&&state.direction==='UB_GM'&&state.scope==='shared')state.scope='1g';
      if(k==='scope')state.preset='all';if(state.scope==='control')state.metric='us';render();});
    root.querySelectorAll('[data-point]').forEach(el=>{el.onclick=()=>{state.selected=el.dataset.point;detail(rows);mark();};el.onkeydown=e=>{if(e.key==='Enter')el.click();};});
    root.querySelector('#bw-export').onclick=()=>{
      const csv=['direction,shared_read,cores,tile_bytes,batch,requested_ring_bytes,actual_ring_bytes,moved_bytes,p50_us,p95_us,aggregate_gbps,rounds,cann,binary_sha256',...rows.map(r=>[r.direction,r.sharedRead,r.cores,r.tileBytes,r.batch,r.requestedRing,r.actualRing,r.movedBytes,r.p50Us,r.p95Us,r.gbps,r.members.map(m=>m.round).join('|'),db.environment.cann,r.binaryHash].join(','))].join('\n');
      const url=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='a5-datacopy-cores.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    };
    detail(rows);if(active)document.getElementById(active)?.focus({preventScroll:true});root.style.minHeight=oldHeight;window.scrollTo({left:viewport.x,top:viewport.y,behavior:'instant'});
  }
  function mark(){root.querySelectorAll('[data-point]').forEach(el=>el.classList.toggle('chosen',el.dataset.point===state.selected));}
  function detail(rows){
    sampleChart?.dispose();balanceChart?.dispose();const g=rows.find(r=>r.id===state.selected);const el=root.querySelector('#lab-detail');
    if(!g){el.innerHTML='<p>当前组合没有测量。</p>';showMeasurementCode('bandwidth',null,db);return;}
    el.innerHTML=`${codeLink}<div class="eyebrow">COMMON WINDOW / CORE BALANCE</div><h2>${g.cores} AIV · ${label(g)}</h2><div class="lab-point-value">${g.control?fmt(g.p50Us,3):fmt(g.gbps)}<small>${g.control?' μs · 整任务共同':' GB/s · 整卡有效'}</small></div><p>${g.sharedRead?'同址只读':'每核独立 GM 分区'} · 实际工作集 ${fmt(g.actualRing/2**20)} MiB · 全核搬运 ${fmt(g.movedBytes/2**30,4)} GiB</p><label class="lab-field">样本轮次<select id="bw-sample-round">${g.members.map((r,i)=>`<option value="${i}">第 ${r.round} 轮</option>`).join('')}</select></label><div id="lab-samples"></div><p>各 AIV 核内 ${g.control?'空循环/事件':'DMA'}区间 · p50 / μs</p><div id="bw-balance"></div><dl><dt>共同 p50</dt><dd>${fmt(g.p50Us,3)} μs</dd><dt>每轮样本</dt><dd>12 + 2 预热</dd><dt>输出与保护区</dt><dd>逐 launch 全部通过</dd></dl><details><summary>原始共同区间 / 核内差值 / 参数</summary><pre>${esc(JSON.stringify(g.members,null,2))}</pre></details>`;
    sampleChart=echarts.init(root.querySelector('#lab-samples'),null,{renderer:'svg'});balanceChart=echarts.init(root.querySelector('#bw-balance'),null,{renderer:'svg'});
    const draw=r=>{
      showMeasurementCode('bandwidth',r,db);
      sampleChart.setOption({animation:false,grid:{left:60,right:12,top:24,bottom:25},tooltip:{trigger:'axis'},xAxis:{type:'category',data:r.eventMs.map((_,i)=>i+1)},yAxis:{type:'value',scale:true,name:'共同 μs'},series:[{type:'line',symbolSize:4,data:r.eventMs.map(v=>v*1000),itemStyle:{color:'#16756b'}}]});
      balanceChart.setOption({animation:false,grid:{left:60,right:12,top:24,bottom:35},tooltip:{trigger:'axis'},xAxis:{type:'category',name:'逻辑 AIV 编号',nameLocation:'middle',nameGap:24,data:r.coreP50Us.map((_,i)=>i)},yAxis:{type:'value',scale:true,name:'核内 μs'},series:[{type:'bar',data:r.coreP50Us,itemStyle:{color:'#8a9db0'}}]});
    };draw(g.members[0]);root.querySelector('#bw-sample-round').onchange=e=>draw(g.members[Number(e.target.value)]);
  }
  window.addEventListener('resize',()=>{chart?.resize();sampleChart?.resize();balanceChart?.resize();});render();
}
