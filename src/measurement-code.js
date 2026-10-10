import {measurementSource, sourceExcerpts, implementationContext} from './measurement-source.js';
import './measurement-code.css';

const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let catalog, loading;
const chosenBlocks=new Map();
export async function loadMeasurementCode() {
  loading ??= fetch(`${import.meta.env.BASE_URL}data/measurement-code.json`).then(r=>{
    if(!r.ok)throw Error('source catalog unavailable');return r.json();
  }).then(d=>{catalog=d;}).catch(()=>{catalog=null;});
  await loading;
}

export function showMeasurementCode(family,row,db) {
  const root=document.querySelector('#app');
  let panel=root.querySelector('#measurement-code');
  if(!panel) {
    panel=document.createElement('section');panel.id='measurement-code';panel.className='panel measurement-code';
    const anchor=root.querySelector('#ws-table')??root.querySelector('.lab-table, .prototype-state');
    if(anchor)anchor.before(panel);else root.append(panel);
  }
  if(!row){panel.innerHTML='<h2>此测量的代码与计时</h2><p>当前筛选没有已测量点。</p>';return;}
  const source=catalog&&measurementSource(catalog,family,row,db);
  if(!source){panel.innerHTML='<h2>此测量的代码与计时</h2><p>本点的源码绑定缺失或不匹配；不能用当前版本替代测量时的代码。</p>';return;}
  const blocks=sourceExcerpts(source,family,row),context=implementationContext(family,row,db);
  const viewport={x:scrollX,y:scrollY};
  const oldHeight=panel.style.minHeight;panel.style.minHeight=`${panel.offsetHeight}px`;
  panel.innerHTML=`<div class="panel-head"><div><div class="eyebrow">MEASURED IMPLEMENTATION / ${esc(family.toUpperCase())}</div><h2>此测量的代码与计时</h2></div><span class="code-verified">源码哈希匹配构建凭据</span></div>
    <div class="code-layout"><div class="code-context"><h3>当前点的运行参数</h3><dl>${context.params.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl><h3>计时边界</h3><p>${esc(context.timing)}</p><h3>实现对性能的影响</h3><ul>${context.notes.map(s=>`<li>${esc(s)}</li>`).join('')}</ul><p class="code-hint">点选曲线或表格会更新这里。参数单独列出，代码保留原文；预处理、模板和 runtime 分支由该参数选择。</p></div>
    <div class="code-view"><div class="code-toolbar"><label>代码片段<select id="code-excerpt">${blocks.map((b,i)=>`<option value="${i}">${esc(b.title)}</option>`).join('')}</select></label><button type="button" id="code-copy" class="quiet">复制片段</button><button type="button" id="code-download" class="quiet">下载完整文件</button></div><div id="code-location"></div><pre class="code-list" tabindex="0" aria-label="测量源码片段"><code id="code-text"></code></pre><p id="code-copy-status" role="status"></p>
    <details class="code-provenance"><summary>完整源码 / 构建 / 单轮证据哈希</summary><dl><dt>binary / library SHA-256</dt><dd>${esc(source.build.binarySha256)}</dd><dt>manifest SHA-256</dt><dd>${esc(source.manifest??'本公开点未记录')}</dd><dt>实验记录的源码 commit</dt><dd>${esc(source.build.recordedSourceCommit??'未记录全仓 commit；下方链接固定哈希相同的文件内容')}</dd>${source.files.map(f=>`<dt>${esc(f.path)}</dt><dd>${esc(f.sha256)}<br><a href="${esc(f.url)}" target="_blank" rel="noreferrer">固定文件内容 ${f.contentCommit.slice(0,12)} ↗</a></dd>`).join('')}</dl></details></div></div>`;
  const select=panel.querySelector('#code-excerpt');
  const previous=chosenBlocks.get(family);const index=blocks.findIndex(b=>b.title===previous);select.value=String(index<0?0:index);
  const draw=()=>{
    const b=blocks[Number(select.value)];chosenBlocks.set(family,b.title);
    panel.querySelector('#code-text').innerHTML=b.text.split('\n').map((line,i)=>`<span class="code-line"><span class="code-number" aria-hidden="true">${b.start+i}</span><span>${esc(line)||' '}</span></span>`).join('');
    panel.querySelector('#code-location').innerHTML=`<span>${esc(b.file.path)} · L${b.start}–${b.end}</span><a href="${esc(b.file.url)}#L${b.start}-L${b.end}" target="_blank" rel="noreferrer">固定版本源码 ↗</a>`;
    panel.querySelector('#code-copy-status').textContent='';
  };
  draw();select.onchange=draw;
  panel.querySelector('#code-copy').onclick=async()=>{
    try {await navigator.clipboard.writeText(blocks[Number(select.value)].text);panel.querySelector('#code-copy-status').textContent='片段已复制（不含行号）';}
    catch {panel.querySelector('#code-copy-status').textContent='浏览器未允许剪贴板写入；可以选中文本或下载完整文件。';}
  };
  panel.querySelector('#code-download').onclick=()=>{
    const f=blocks[Number(select.value)].file;
    const url=URL.createObjectURL(new Blob([f.text],{type:'text/plain;charset=utf-8'}));
    const a=document.createElement('a');a.href=url;a.download=`${f.sha256.slice(0,12)}-${f.path.split('/').at(-1)}`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  panel.style.minHeight=oldHeight;window.scrollTo({left:viewport.x,top:viewport.y,behavior:'instant'});
  root.querySelectorAll('.code-jump').forEach(b=>b.onclick=()=>panel.scrollIntoView({behavior:'smooth',block:'start'}));
}

export const codeLink='<button type="button" class="quiet code-jump">测量代码 ↓</button>';
