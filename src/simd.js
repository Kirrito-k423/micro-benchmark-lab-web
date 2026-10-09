import * as echarts from 'echarts';
import './mbench.css';
const ops=['加法','减法','乘法','除法'];
const bulk=[32,64,128,256,512,1024,2048,4096,8192,16384];
const median=xs=>{const a=[...xs].sort((x,y)=>x-y);return(a[Math.floor((a.length-1)/2)]+a[Math.ceil((a.length-1)/2)])/2;};
const fmt=(n,d=3)=>Number(n).toLocaleString('en-US',{maximumFractionDigits:d,minimumFractionDigits:d});
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export async function mountSimd(){
  const db=await fetch(`${import.meta.env.BASE_URL}data/a5-simd.json`).then(r=>{if(!r.ok)throw new Error('SIMD 实测数据尚未发布');return r.json();});
  const root=document.querySelector('#app');
  const s={op:0,axis:'elements',steps:1,elements:2048,range:'bulk',round:'all',metric:'p50',selected:null};
  let chart,samples;
  let selectedLegend={};
  document.body.dataset.variant='A';document.title='Micro Benchmark Lab · SIMD ↔ SIMT';
  const name=r=>r.impl===1?`SIMT · ${r.threads} 线程`:db.implementations[r.impl];
  const key=r=>`${r.impl}/${r.threads??0}`;
  const select=(k,label,items)=>`<label class="lab-field">${label}<select id="simd-${k}" data-filter="${k}">${items.map(([v,t])=>`<option value="${v}" ${String(v)===String(s[k])?'selected':''}>${t}</option>`).join('')}</select></label>`;
  function groups(){
    const map=new Map();
    for(const r of db.rows){
      if((r.steps!==0&&r.op!==s.op)||(r.impl===1&&r.threads===1)||(s.round!=='all'&&r.round!==Number(s.round)))continue;
      if(s.axis==='elements'&&(r.steps!==s.steps||(s.range==='bulk'&&!bulk.includes(r.elements))))continue;
      if(s.axis==='steps'&&r.elements!==s.elements)continue;
      const k=`${key(r)}/${r.elements}/${r.steps}`;
      if(!map.has(k))map.set(k,[]);map.get(k).push(r);
    }
    for(const rs of map.values())rs.sort((a,b)=>a.round-b.round);
    return [...map.values()].map(rs=>({...rs[0],p50:median(rs.map(r=>r.p50)),p95:median(rs.map(r=>r.p95)),members:rs}))
      .sort((a,b)=>(s.axis==='elements'?a.elements-b.elements:a.steps-b.steps)||a.impl-b.impl||(a.threads??0)-(b.threads??0));
  }
  function value(r,rows){
    if(s.metric==='gops')return r.elements*r.steps/r.p50/1000;
    if(s.metric==='speedup'){
      const base=rows.find(b=>b.impl===0&&b.elements===r.elements&&b.steps===r.steps);
      return base?base.p50/r.p50:null;
    }
    return r.p50;
  }
  function render(){
    const viewport={x:scrollX,y:scrollY};const active=document.activeElement?.id;
    const oldHeight=root.style.minHeight;root.style.minHeight=`${root.offsetHeight}px`;
    chart?.dispose();samples?.dispose();const rows=groups();
    if(!rows.some(r=>r.id===s.selected))s.selected=rows.find(r=>r.impl===3&&(s.axis==='elements'?r.elements===2048:r.steps===128))?.id||rows[0]?.id;
    const repeat=db.evidence.repeatability;
    const controls=select('op','FP32 运算',ops.map((v,i)=>[i,v]))+
      select('axis','横轴',[['elements','输入元素数 · 批量曲线'],['steps','每元素依赖链 · 计算曲线']])+
      (s.axis==='elements'?select('steps','每元素运算次数',[0,1,16,128,512].map(n=>[n,n===0?'0 · 空计算对照':`${n} 次`]))+
        select('range','shape 范围',[['bulk','10 个批量 shape'],['all','含 1/31/33/63/65 尾块']]):select('elements','固定元素数',bulk.map(n=>[n,n])))+
      select('metric','纵轴',[['p50','完成耗时 / μs'],['gops','有效元素运算 / Gop/s'],['speedup','相对 Tensor API 的速度比']])+
      select('round','测量轮次',[['all','两轮 p50 / p95 中位数'],[1,'第 1 轮'],[2,'第 2 轮']]);
    root.innerHTML=`<header class="topbar"><a class="brand" href="?variant=A">microbench<small>AKL MEASUREMENT LAB</small></a><div class="top-right">真实 A5 测量 · ${esc(db.environment.cann)}</div></header>
      <main class="lab-main"><nav class="lab-tabs"><a href="?variant=A">DataCopy 容量</a><a href="?lab=bandwidth">DataCopy 多核带宽</a><a href="?lab=network">FullMesh / URMA</a><a href="?lab=alignment">DataCopy 对齐</a><a href="?lab=simd" class="active">SIMD ↔ SIMT</a><a href="?lab=simt">原始算术对照</a><a href="?lab=overhead">SIMT 调用开销</a></nav>
      <div class="lab-heading"><div class="eyebrow">A5 / SAME WORKLOAD / SIMD & SIMT</div><h1>规则批量计算，哪种实现更快？</h1><p>同一 FP32 输入与每元素计算量。Tensor API 每步读写 UB；REG SIMD 与 SIMT 将依赖链保留在寄存器。REG 是 SIMD 编程；4 组版交错四条独立向量链，未增加有效计算量。</p></div>
      <div class="lab-env">${esc(db.environment.soc)} · ${esc(db.environment.cann)} · 单 AIV · 本地 UB · SYS_CNT ${fmt(db.environment.clockHz/1e6,0)} MHz · ${esc(db.measuredDate)}</div>
      <p class="lab-caption">${fmt(db.evidence.configsPerRound,0)} 配置 × 2 轮 · ${fmt(db.evidence.timedSamples,0)} 计时样本 · 全输出/尾块/保护区校验通过。两轮 p50 相对差异中位数 ${fmt(repeat.medianRelativePct)}%，最大 ${fmt(repeat.maxRelativePct)}%；不是置信区间。</p>
      <section class="panel lab-controls">${controls}</section><div class="lab-grid"><section class="panel"><div class="panel-head"><h2>${ops[s.op]} · ${s.axis==='elements'?'shape 与性能':'依赖链与性能'}</h2><button id="simd-export" class="quiet">CSV</button></div><div id="lab-chart"></div>
      <p class="lab-caption">点击图例开关曲线 · 拖动缩放 · 点击点查看样本。计时含分发与完成等待，不含 GM 准备/导出。Gop/s = 元素数 × 运算次数 / 完成时间，含实现开销，不代表芯片峰值。${s.steps===512&&s.axis==='elements'?'512 步只测 2048/8192 两个 shape。':''}</p></section><aside class="panel lab-inspector" id="lab-detail"></aside></div>
      <section class="panel lab-table simd-results"><div class="panel-head"><h2>同工作量对照表</h2><span class="subtle">点击行查看证据</span></div><div class="table-scroll"><table><thead><tr><th>实现</th><th>元素数</th><th>每元素次数</th><th>p50 / μs</th><th>p95 / μs</th><th>有效 Gop/s</th><th>轮次</th></tr></thead><tbody>${rows.map(r=>`<tr tabindex="0" data-point="${r.id}" class="${r.id===s.selected?'chosen':''}"><td>${name(r)}</td><td>${r.elements}</td><td>${r.steps}</td><td class="mono">${fmt(r.p50,5)}</td><td class="mono">${fmt(r.p95,5)}</td><td class="mono">${fmt(r.elements*r.steps/r.p50/1000)}</td><td>${r.members.length}</td></tr>`).join('')}</tbody></table></div></section>
      <section class="panel" style="padding:24px"><h2>如何读这些曲线</h2><p>SIMT 线程可以循环处理多个元素；1 线程处理 129 元素的四种运算已通过完整输出验证。SIMD 一条向量指令可计算多个 lane；胜负还取决于 shape、寄存器依赖、调度与访存。连续规整输入是本组条件，未测分支、离散访问和多 AIV 并发。</p><p>steps=0 统一使用加法入口，是各实现的无运算参考；不是其他运算专属的控制开销，REG/SIMT 仍有读写与调用；Tensor 只有完成等待。显示原始耗时，不跨实现相减。REG 4 组在不足四组向量时回退 1 组。短 shape 或小幅差异需结合原始样本与轮间变化。</p></section>
      <footer class="lab-footer"><a href="https://github.com/Kirrito-k423/ascend-kernel-lab/tree/codex/a5-alignment-simt/examples/a5_simd_mbench" target="_blank" rel="noreferrer">代码与复现 SOP ↗</a> · <a href="https://github.com/Kirrito-k423/micro-benchmark-lab-web/blob/codex/a5-mbench-results/reports/a5-simd-20261009.md" target="_blank" rel="noreferrer">实测报告 ↗</a> · <a href="${import.meta.env.BASE_URL}figures/a5-simd.png" download>PNG</a> · <a href="${import.meta.env.BASE_URL}figures/a5-simd.svg" download>SVG</a><p>公开原始 tick、预热、Host launch 与校验误差。设备日志与机器地址保留在私有归档。前后占用快照无法证明采样间每一瞬间都无外部活动。</p><details><summary>证据与计时口径</summary><pre>${esc(JSON.stringify(db.evidence,null,2))}</pre></details></footer></main>`;
    const series=[...new Set(rows.map(key))].map(k=>{const rs=rows.filter(r=>key(r)===k);return{name:name(rs[0]),type:'line',symbolSize:6,smooth:false,lineStyle:{type:rs[0].impl===1?'dashed':'solid'},itemStyle:{color:rs[0].impl===0?'#a58b40':rs[0].impl===2?'#16756b':rs[0].impl===3?'#e77d42':({'32':'#8a9db0','128':'#5274a2','512':'#875aa6','1024':'#b87586','2048':'#7589a5'}[rs[0].threads])},data:rs.map(r=>({value:[s.axis==='elements'?r.elements:r.steps,value(r,rows)],id:r.id}))};});
    chart=echarts.init(root.querySelector('#lab-chart'),null,{renderer:'svg'});
    chart.setOption({animation:false,color:['#ac934f','#8a9db0','#5274a2','#875aa6','#b87586','#15756c','#e47c44','#314f49'],legend:{top:8,type:'plain',selected:selectedLegend},
      tooltip:{trigger:'item',formatter:p=>`${esc(p.seriesName)}<br>${s.axis==='elements'?'元素数':'每元素运算次数'}：${p.value[0]}<br>${fmt(p.value[1],5)} ${s.metric==='p50'?'μs':s.metric==='gops'?'Gop/s':'×'}`},
      grid:{left:76,right:28,top:94,bottom:78},xAxis:{type:s.axis==='elements'?'log':'value',logBase:2,name:s.axis==='elements'?'有效元素数':'每元素运算次数',nameLocation:'middle',nameGap:32,min:s.axis==='elements'?undefined:0},
      yAxis:{type:s.metric==='p50'?'log':'value',name:s.metric==='p50'?'μs':s.metric==='gops'?'Gop/s':'Tensor / 当前实现',scale:true},dataZoom:[{type:'inside',filterMode:'none'},{type:'slider',height:16,bottom:8}],series});
    chart.on('legendselectchanged',e=>{selectedLegend={...e.selected};});
    chart.on('click',p=>{if(p.data?.id){s.selected=p.data.id;detail(rows);mark();}});
    root.querySelectorAll('[data-filter]').forEach(el=>el.onchange=()=>{const k=el.dataset.filter;s[k]=['op','steps','elements'].includes(k)?Number(el.value):el.value;render();});
    root.querySelectorAll('[data-point]').forEach(el=>{el.onclick=()=>{s.selected=el.dataset.point;detail(rows);mark();};el.onkeydown=e=>{if(e.key==='Enter')el.click();};});
    root.querySelector('#simd-export').onclick=()=>{
      const csv=['op,dtype,cann,clock_hz,implementation,elements,steps,threads,p50_us,p95_us,effective_gops,rounds,binary_sha256',...rows.map(r=>[['add','sub','mul','div'][r.op],r.dtype,db.environment.cann,db.environment.clockHz,name(r),r.elements,r.steps,r.threads??'',r.p50,r.p95,r.elements*r.steps/r.p50/1000,r.members.map(m=>m.round).join('|'),r.binaryHash].join(','))].join('\n');
      const url=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='a5-simd.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    };
    detail(rows);if(active)document.getElementById(active)?.focus({preventScroll:true});root.style.minHeight=oldHeight;window.scrollTo({left:viewport.x,top:viewport.y,behavior:'instant'});
  }
  function mark(){root.querySelectorAll('[data-point]').forEach(el=>el.classList.toggle('chosen',el.dataset.point===s.selected));}
  function detail(rows){
    samples?.dispose();const g=rows.find(r=>r.id===s.selected);const el=root.querySelector('#lab-detail');
    if(!g){el.innerHTML='<p>该组合没有测量。</p>';return;}
    el.innerHTML=`<div class="eyebrow">RAW SAMPLE INSPECTOR</div><h2>${name(g)}</h2><div class="lab-point-value">${fmt(g.p50,5)}<small> μs · ${g.members.length===2?'两轮 p50 中位数':'p50'}</small></div><p>${g.elements} 元素 · 每元素 ${g.steps} 次 · ${g.threads??'—'} SIMT 线程</p><label class="lab-field">原始样本轮次<select id="simd-sample-round">${g.members.map((r,i)=>`<option value="${i}">第 ${r.round} 轮</option>`).join('')}</select></label><div id="lab-samples"></div><dl><dt>完整输出与边界</dt><dd>全部通过</dd><dt>最大绝对误差</dt><dd>${Math.max(...g.members.map(r=>r.maxAbsError))}</dd><dt>有效运算数</dt><dd>${g.elements*g.steps}</dd></dl><details><summary>原始参数 / tick / 构建哈希</summary><pre>${esc(JSON.stringify(g.members,null,2))}</pre></details>`;
    samples=echarts.init(root.querySelector('#lab-samples'),null,{renderer:'svg'});
    const draw=r=>samples.setOption({animation:false,grid:{left:50,right:12,top:24,bottom:24},tooltip:{trigger:'axis'},xAxis:{type:'category',data:r.rawTicks.map((_,i)=>i+1)},yAxis:{type:'value',scale:true,name:'μs'},series:[{type:'line',symbolSize:4,data:r.rawTicks.map(t=>Number(t)*1e6/db.environment.clockHz),itemStyle:{color:'#15756c'}}]});
    draw(g.members[0]);root.querySelector('#simd-sample-round').onchange=e=>draw(g.members[Number(e.target.value)]);
  }
  window.addEventListener('resize',()=>{chart?.resize();samples?.resize();});render();
}
