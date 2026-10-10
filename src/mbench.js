import {mountPageRetest} from './page-retest.js';
import {applyLabShell} from './lab-shell.js';
import * as echarts from 'echarts';
import './mbench.css';
import {showMeasurementCode, codeLink} from './measurement-code.js';
import { mountSimd } from './simd.js';
import { mountBandwidth } from './bandwidth.js';
import { mountNetwork } from './network.js';
import { mountStoreTail } from './store-tail.js';
import { mountWorkset } from './workset.js';
import { mountPeerCopy } from './peer-copy.js';

const labels={alignment:'DataCopy 对齐',simt:'SIMT 算术',overhead:'SIMT 调用开销'};
const ops=['加法','减法','乘法','除法'];
const implementations=['Scalar','SIMT','SIMD','VF · 每线程写出','无 VF 对照'];
const median=xs=>{const a=[...xs].sort((x,y)=>x-y);return(a[Math.floor((a.length-1)/2)]+a[Math.ceil((a.length-1)/2)])/2;};
const fmt=(n,d=3)=>Number(n).toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d});
const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export async function mountMbench(initial){
  if(initial==='page-retest')return mountPageRetest();
  if(initial==='peer-copy')return mountPeerCopy();
  if(initial==='workset')return mountWorkset();
  if(initial==='store-tail')return mountStoreTail();
  if(initial==='network')return mountNetwork();
  if(initial==='bandwidth')return mountBandwidth();
  if(initial==='simd')return mountSimd();
  const db=await fetch(`${import.meta.env.BASE_URL}data/a5-mbench.json`).then(r=>{if(!r.ok)throw new Error('测量数据尚未发布');return r.json();});
  const state={view:labels[initial]?initial:'alignment',alignmentSource:db.alignmentPaired?.length?'fixed':'sweep',dtype:'uint8',direction:'GM_UB',windows:1,offset:0,
    metric:'p50',op:0,elements:2048,steps:128,baseline:0,calls:128,selected:null,round:'all'};
  const root=document.querySelector('#app');
  document.body.dataset.variant='A';
  let chart,samples;
  const select=(key,label,items)=>`<label class="lab-field">${label}<select id="lab-${key}" data-filter="${key}">${items.map(([v,t])=>`<option value="${v}" ${String(state[key])===String(v)?'selected':''}>${t}</option>`).join('')}</select></label>`;
  function matching(){
    const rows=state.view==='alignment'?(state.alignmentSource==='fixed'?db.alignmentPaired:db.alignment):db.simt;
    return rows.filter(r=>(state.round==='all'||r.round===Number(state.round))&&
      (state.view==='alignment'?r.dtype===state.dtype&&r.direction===state.direction&&r.windows===state.windows&&r.gmOffset===state.offset:
       state.view==='simt'?r.impl<=2&&r.op===state.op&&r.elements===state.elements&&r.steps===state.steps:
       r.impl>=3&&r.vf_calls===state.calls));
  }
  function groups(){
    const map=new Map();
    for(const r of matching()){
      const key=state.view==='alignment'?`${r.api}/${r.elements}`:`${r.impl}/${r.threads}`;
      if(!map.has(key))map.set(key,[]);map.get(key).push(r);
    }
    return [...map.values()].map(rs=>({...rs[0],id:rs[0].id,p50:median(rs.map(r=>r.p50)),p95:median(rs.map(r=>r.p95)),members:rs}))
      .sort((a,b)=>state.view==='alignment'?a.elements-b.elements:a.threads-b.threads);
  }
  function controls(){
    const available=[...new Set((state.view==='alignment'?db.alignment:db.simt).map(r=>r.round))].sort();
    const round=select('round','测量轮次',[['all',db.evidence.receiverValidation==='passed'?'两轮中位数':'已完成轮次'],...available.map(n=>[n,`第 ${n} 轮`])]);
    if(state.view==='alignment')return select('alignmentSource','测量方式',[['sweep','完整 131 长度扫描'],...(db.alignmentPaired?.length?[['fixed','固定 GM 缓冲 · 边界复验']]:[])])+
      select('dtype','元素类型',[['uint8','uint8 · 1 B / 元素'],['float32','FP32 · 4 B / 元素']])+
      select('direction','搬运方向',[['GM_UB','GM → UB'],['UB_GM','UB → GM']])+
      select('windows','同步方式',[[1,'单窗口 · 完成等待'],...(state.alignmentSource==='sweep'?[[2,'双窗口 · 复用等待']]:[])])+
      select('offset','GM 起点偏移',[[0,'0 B · 地址对齐'],...(state.alignmentSource==='sweep'?[1,31,127].map(n=>[n*(state.dtype==='uint8'?1:4),`${n*(state.dtype==='uint8'?1:4)} B`]):[])])+
      select('metric','纵轴',[['p50','每调用完成耗时 / μs'],['gbps','有效 payload / GB/s']])+round;
    if(state.view==='simt')return select('op','运算',ops.map((s,i)=>[i,s]))+
      select('elements','同一工作量 · 元素数',[32,128,512,2048,8192].map(n=>[n,n]))+
      select('steps','每元素依赖链',[1,16,128].map(n=>[n,`${n} 次运算`]))+
      select('baseline','速度比参照',[[0,'Scalar'],[2,'SIMD']])+
      select('metric','纵轴',[['p50','总完成耗时 / μs'],['speedup','同工作量速度比']])+round;
    return select('calls','连续 VF 调用数',[1,16,64,128].map(n=>[n,n]))+
      select('metric','纵轴',[['p50','每次 VF 完成耗时 / μs'],['increment','相对无 VF 循环的增量 / μs']])+round;
  }
  function render(){
    document.title=`Micro Benchmark Lab · ${labels[state.view]}`;
    const viewport={x:scrollX,y:scrollY,h:root.style.minHeight};
    const active=document.activeElement?.id;
    root.style.minHeight=`${root.offsetHeight}px`;
    chart?.dispose();samples?.dispose();
    const rows=groups();
    const repeat=db.evidence.repeatability?.[state.view==='alignment'?(state.alignmentSource==='fixed'?'alignmentPaired':'alignment'):'simt'];
    if(!rows.some(r=>r.members.some(m=>m.id===state.selected)))state.selected=rows.find(r=>state.view==='alignment'?r.elements===192:r.impl===1&&r.threads===256)?.members[0].id||rows[0]?.id;
    const baseline=rows.find(r=>r.impl===state.baseline);
    const note=state.view==='alignment'?`${state.alignmentSource==='fixed'?'边界复验在同一进程里复用同一组存活 GM 分配，控制缓冲地址变化；只比较 DataCopyPad。':'完整扫描覆盖 131 个长度，各 case 单独分配缓冲；小幅差异需结合轮间波动和固定分配复验判断。DataCopyPad 与 DataCopy(params) 各自成线。'}元素数与字节数同时显示。${state.windows===2?'双窗口展示区间平均耗时，不代表独立请求尾延迟。':''}`:
      state.view==='simt'?'相同 FP32 输入、元素数与依赖链长度。SIMT 在寄存器中执行依赖链；SIMD Tensor API 每轮读写 UB 并同步。计时含计算调用与完成等待，不含 GM 准备和导出；速度比包括实现方式差异。':
      '最小线程体为每线程一次可观察 UB 写出。计时包含 VF 调用、线程体与完成同步；不能拆解成硬件线程创建的独立精确时间。';
    root.innerHTML=`<header class="topbar"><a class="brand" href="?variant=A">microbench<small>AKL MEASUREMENT LAB</small></a><div class="top-right">真实 A5 测量 · ${escape(db.environment.cann)}</div></header>
      <main class="lab-main"><nav class="lab-tabs"><a href="?variant=A">DataCopy 容量</a><a href="?lab=bandwidth">DataCopy 多核带宽</a><a href="?lab=peer-copy">大页 / 普通页对照</a><a href="?lab=workset">工作集拐点</a><a href="?lab=store-tail">纯写同步对照</a><a href="?lab=network">FullMesh / URMA</a><a href="?lab=simd">SIMD ↔ SIMT</a>${Object.entries(labels).map(([v,t])=>`<a href="?lab=${v}" class="${state.view===v?'active':''}">${t}</a>`).join('')}</nav>
      <div class="lab-heading"><div class="eyebrow">A5 / SINGLE AIV / RAW EVIDENCE</div><h1>${labels[state.view]}</h1><p>${note}</p></div>
      <div class="lab-env">${escape(db.environment.soc)} · ${escape(db.environment.cann)} · 单 AIV · SYS_CNT ${fmt(db.environment.clockHz/1e6,0)} MHz · ${escape(db.measuredDate)} · ${rows.length} 个配置点${db.evidence.receiverValidation==='passed'?'':' · 首批实测，本地验收中'}</div>
      ${repeat?`<p class="lab-caption">本组全部配置的两轮 p50 相对差异：中位数 ${fmt(repeat.medianRelativePct,3)}%，最大 ${fmt(repeat.maxRelativePct,3)}%。这是重复性观察，不是置信界；微小差异需结合波动判断。</p>`:''}
      <section class="panel lab-controls">${controls()}</section>
      <div class="lab-grid"><section class="panel"><div class="panel-head"><h2>${state.view==='alignment'?(state.alignmentSource==='fixed'?'15 个边界长度的固定缓冲复验':'127–257 个元素的长度扫描'):state.view==='simt'?'线程数与同工作量性能':'线程数与每次 VF 完成耗时'}</h2><button id="lab-export" class="quiet">CSV</button></div><div id="lab-chart"></div>
      <p class="lab-caption">拖动缩放 · 点击实测点查看原始样本。${state.round==='all'?'各轮 p50/p95 分别取中位数。':''}${state.view==='alignment'?'纵轴按数据范围缩放。':state.view==='simt'&&state.metric==='p50'?'耗时纵轴为对数轴，以同时看到三种实现。':state.view==='overhead'&&state.metric==='increment'?'增量 =（VF 总区间 p50 − 无 VF 同步循环 p50）/ 调用数；原始总耗时保留在表格与样本中。':''}</p></section>
      <aside class="panel lab-inspector" id="lab-detail"></aside></div>
      <section class="panel lab-table"><div class="panel-head"><h2>当前筛选的实测点</h2><span class="subtle">点击行更新证据</span></div><div class="table-scroll"><table><thead><tr><th>实现 / API</th><th>${state.view==='alignment'?'元素数 / 字节':'VF 线程数'}</th><th>p50 / μs</th><th>p95 / μs</th><th>${state.view==='alignment'?'GB/s':state.view==='simt'?'速度比':'μs / 次'}</th><th>轮次</th></tr></thead><tbody>${rows.map(r=>`<tr tabindex="0" data-point="${escape(r.id)}" class="${r.members.some(m=>m.id===state.selected)?'chosen':''}"><td>${escape(state.view==='alignment'?r.api:implementations[r.impl])}</td><td>${state.view==='alignment'?`${r.elements} / ${r.payload} B`:([1,3].includes(r.impl)?r.threads:'—')}</td><td class="mono">${fmt(r.p50,5)}</td><td class="mono">${fmt(r.p95,5)}</td><td class="mono">${state.view==='alignment'?fmt(r.payload/r.p50/1000):state.view==='simt'&&baseline?`${fmt(baseline.p50/r.p50)}×`:state.view==='overhead'?fmt(r.p50/r.vf_calls,5):'—'}</td><td>${r.members.length}</td></tr>`).join('')||'<tr><td colspan="6">当前组合没有已完成的测量。</td></tr>'}</tbody></table></div></section>
      <footer class="lab-footer"><a href="https://github.com/Kirrito-k423/ascend-kernel-lab/tree/codex/a5-alignment-simt" target="_blank" rel="noreferrer">测量代码与 SOP ↗</a> · <a href="https://github.com/Kirrito-k423/micro-benchmark-lab-web/blob/codex/a5-mbench-results/reports/a5-mbench-20261009.md" target="_blank" rel="noreferrer">实测汇总报告 ↗</a>${db.evidence.receiverValidation==='passed'?` · <a href="${import.meta.env.BASE_URL}figures/a5-${state.view==='alignment'&&state.alignmentSource==='sweep'?'alignment-sweep':state.view}.png" download>汇总图 PNG</a> · <a href="${import.meta.env.BASE_URL}figures/a5-${state.view==='alignment'&&state.alignmentSource==='sweep'?'alignment-sweep':state.view}.svg" download>SVG</a>`:''}<p>原始样本包含在本站数据中。完整设备日志和机器地址未公开；运行前后占用证据及构建哈希保留在归档中。</p><details><summary>证据与测量口径</summary><pre>${escape(JSON.stringify(db.evidence,null,2))}</pre></details></footer></main>`;
    mountChart(rows,baseline);detail(rows);
    root.querySelectorAll('[data-filter]').forEach(el=>el.onchange=()=>{const k=el.dataset.filter;
      state[k]=['windows','offset','op','elements','steps','baseline','calls'].includes(k)?Number(el.value):el.value;
      if(k==='dtype')state.offset=0;
      if(k==='alignmentSource'){state.offset=0;state.windows=1;}
      render();});
    root.querySelectorAll('[data-point]').forEach(el=>{el.onclick=()=>{state.selected=el.dataset.point;detail(rows);
      root.querySelectorAll('[data-point]').forEach(row=>row.classList.toggle('chosen',row.dataset.point===state.selected));};el.onkeydown=e=>{if(e.key==='Enter')el.click();};});
    document.querySelector('#lab-export').onclick=()=>{
      const fields=['implementation','dtype','direction','api','elements','payload_bytes','gm_offset_bytes','windows','loops','batch','slots','threads','op','steps','repeat_count','simt_vf_calls','p50_us','p95_us','round_ids','clock_hz','cann'];
      const csv=[fields.join(','),...rows.map(r=>[r.api||implementations[r.impl],r.dtype,r.direction||'',r.api||'',r.elements,r.payload??'',r.gmOffset??'',r.windows??'',r.loops??'',r.batch??'',r.slots??'',[1,3].includes(r.impl)?r.threads:'',r.op??'',r.steps??'',r.vf_calls??'',r.actualSimtVfCalls??'',r.p50,r.p95,r.members.map(m=>m.round).join('|'),db.environment.clockHz,db.environment.cann].map(v=>`"${String(v).replaceAll('"','""')}"`).join(','))].join('\n');
      const url=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=`a5-${state.view}.csv`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    };
    if(active)document.getElementById(active)?.focus({preventScroll:true});
    root.style.minHeight=viewport.h;window.scrollTo({left:viewport.x,top:viewport.y,behavior:'instant'});
  }
  function mountChart(rows,baseline){
    applyLabShell(root,state.view);
  chart=echarts.init(document.querySelector('#lab-chart'),null,{renderer:'svg'});
    let series=[];
    if(state.view==='alignment'){
      for(const api of ['DataCopyPad_params','DataCopy_params']){
        const values=rows.filter(r=>r.api===api);
        if(values.length)series.push({name:api,type:'line',symbolSize:5,smooth:false,data:values.map(r=>({value:[r.elements,state.metric==='gbps'?r.payload/r.p50/1000:r.p50],id:r.id})),lineStyle:{type:api==='DataCopy_params'?'dashed':'solid'}});
      }
    }else if(state.view==='simt'){
      series=[{name:'SIMT',type:'line',symbolSize:7,data:(state.metric==='speedup'&&!baseline?[]:rows.filter(r=>r.impl===1)).map(r=>({value:[r.threads,state.metric==='speedup'?baseline.p50/r.p50:r.p50],id:r.id}))}];
      if(state.metric==='p50')for(const impl of [0,2]){const r=rows.find(r=>r.impl===impl);if(r)series.push({name:implementations[impl],type:'line',symbol:'none',lineStyle:{type:'dashed'},data:[[1,r.p50],[2048,r.p50]]});}
    }else {
      const control=rows.find(r=>r.impl===4);
      series=[{name:state.metric==='increment'?'VF 增量（含每线程 UB 写出）':'VF + 最小线程体 + 完成等待',type:'line',symbolSize:7,
        data:(state.metric==='increment'&&!control?[]:rows.filter(r=>r.impl===3)).map(r=>({value:[r.threads,(r.p50-(state.metric==='increment'?control.p50:0))/r.vf_calls],id:r.id}))}];
      if(control&&state.metric==='p50')series.push({name:'无 VF · 同步循环 / 次',type:'line',symbol:'none',lineStyle:{type:'dashed'},data:[[1,control.p50/control.vf_calls],[2048,control.p50/control.vf_calls]]});
    }
    chart.setOption({animation:false,color:['#15756c','#e47c44','#7894b6'],legend:{top:10},grid:{left:72,right:30,top:60,bottom:75},
      tooltip:{trigger:'item',formatter:p=>`${escape(p.seriesName)}<br>${state.view==='alignment'?'元素':'线程'}：${p.value[0]}<br>${fmt(p.value[1],5)} ${state.metric==='speedup'?'×':state.metric==='gbps'?'GB/s':'μs'}`},
      xAxis:{type:state.view==='alignment'?'value':'log',logBase:2,name:state.view==='alignment'?'元素数（127–257）':'实际线程数 / launch bound',nameLocation:'middle',nameGap:30,min:state.view==='alignment'?127:1,max:state.view==='alignment'?257:2048},
      yAxis:{type:state.view==='simt'&&state.metric==='p50'?'log':'value',logBase:10,name:state.view==='overhead'?'μs / VF':state.metric==='speedup'?'速度比':state.metric==='gbps'?'GB/s':'μs',scale:state.view==='alignment'},
      dataZoom:[{type:'inside',filterMode:'none'},{type:'slider',height:16,bottom:8}],series});
    chart.on('click',p=>{if(p.data?.id){state.selected=p.data.id;detail(rows);
      root.querySelectorAll('tr[data-point]').forEach(el=>el.classList.toggle('chosen',el.dataset.point===p.data.id));}});
  }
  function detail(rows){
    samples?.dispose();
    const g=rows.find(r=>r.members.some(m=>m.id===state.selected));
    const el=document.querySelector('#lab-detail');
    if(!g){el.innerHTML='<p class="empty">暂无匹配样本</p>';showMeasurementCode(state.view,null,db);return;}
    const r=g.members.find(r=>r.id===state.selected)||g.members[0];
    el.innerHTML=`${codeLink}<div class="eyebrow">RAW SAMPLE INSPECTOR</div><h2>一个点，完整计时</h2><label class="lab-field">测量轮次<select id="lab-sample-round">${g.members.map(m=>`<option value="${escape(m.id)}" ${m.id===r.id?'selected':''}>第 ${m.round} 轮</option>`).join('')}</select></label>
      <div class="lab-point-value">${fmt(r.p50,5)}<small> μs · p50</small></div><p>${state.view==='alignment'?`${r.api} · ${r.dtype} · ${r.elements} 元素 / ${r.payload} B`:`${implementations[r.impl]} · FP32 · ${r.elements} 元素${[1,3].includes(r.impl)?` · ${r.threads} 线程`:''}`}</p>
      <div id="lab-samples"></div><dl><dt>p95</dt><dd>${fmt(r.p95,5)} μs</dd><dt>计时样本</dt><dd>${r.rawTicks.length}</dd><dt>${state.view==='alignment'?'循环 × batch':state.view==='simt'?'依赖链 / SIMT VF 次数':'循环 / SIMT VF 次数'}</dt><dd>${state.view==='alignment'?`${r.loops} × ${r.batch}`:`${state.view==='simt'?r.steps:r.vf_calls} / ${r.actualSimtVfCalls??(r.impl===1?1:r.impl===3?r.vf_calls:0)}`}</dd><dt>输出校验</dt><dd>全部通过</dd></dl>
      <details><summary>原始 tick 与参数</summary><pre>${escape(JSON.stringify(r,null,2))}</pre></details>`;
    showMeasurementCode(state.view,r,db);
    samples=echarts.init(document.querySelector('#lab-samples'),null,{renderer:'svg'});
    const calls=state.view==='alignment'?r.loops*r.batch:1;
    samples.setOption({animation:false,grid:{left:50,right:12,top:22,bottom:26},tooltip:{trigger:'axis'},xAxis:{type:'category',data:r.rawTicks.map((_,i)=>i+1)},yAxis:{type:'value',scale:true},series:[{type:'line',symbolSize:4,data:r.rawTicks.map(t=>Number(t)*1e6/db.environment.clockHz/calls),itemStyle:{color:'#15756c'}}]});
    document.querySelector('#lab-sample-round').onchange=e=>{state.selected=e.target.value;detail(rows);};
  }
  window.addEventListener('resize',()=>{chart?.resize();samples?.resize();});
  render();
}
