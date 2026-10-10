import './lab-shell.css';
const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const sections=[['DataCopy',[['capacity','容量与单核基线'],['page-retest','大页复测 · 32 B → 4 MiB'],['peer-copy','同事代码与页策略'],['alignment','长度与地址对齐'],['bandwidth','多核带宽'],['workset','工作集变化'],['store-tail','纯写同步对照']]],['计算与通信',[['simd','SIMD ↔ SIMT'],['simt','SIMT 算术'],['overhead','VF 调用开销'],['network','FullMesh / URMA']]]];
export function libraryHeader(note='真实 NPU 测量'){
 return `<header class="topbar"><a class="brand" href="?variant=A"><span class="brand-mark"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M4 19V5m0 14h16M8 15l4-5 4 2 4-7"/></svg></span><span>micro<span class="brand-light">bench</span><small>AKL MEASUREMENT LAB</small></span></a><nav><span class="active">测量结果</span><a href="https://github.com/Kirrito-k423/ascend-kernel-lab" target="_blank" rel="noreferrer">AKL 源码 ↗</a></nav><div class="top-right"><span class="live-dot"></span>${escape(note)}<a class="repo-link" href="https://github.com/Kirrito-k423/micro-benchmark-lab-web/tree/codex/a5-mbench-results" target="_blank" rel="noreferrer">GitHub ↗</a></div></header>`;
}
export function libraryNav(active){
 return `<nav class="library-nav" aria-label="实验目录"><div class="eyebrow">BENCHMARK LIBRARY</div>${sections.map(([heading,items])=>`<div class="library-section">${heading}</div>${items.map(([id,label])=>`<a class="library-link ${id===active?'active':''}" ${id===active?'aria-current="page"':''} href="${id==='capacity'?'?variant=A':`?lab=${id}`}">${label}</a>`).join('')}`).join('')}</nav>`;
}
export function retestNotice(){
 return '<div class="retest-notice"><span>历史测量保留；新一轮明确数据 GM 页策略，并从 32 B 逐次翻倍到 4 MiB。</span><a href="?lab=page-retest">打开大页复测与同条件对照 ↗</a></div>';
}
export function applyLabShell(root,active){
 const main=root.querySelector('.lab-main');if(!main||main.parentElement.classList.contains('lab-shell'))return;
 const header=root.querySelector('.topbar');if(header)header.outerHTML=libraryHeader(main.querySelector('.lab-env')?.textContent?.split(' · ').slice(0,2).join(' · ')||'真实 NPU 测量');
 main.querySelector('.lab-tabs')?.remove();const shell=document.createElement('div');shell.className='workbench lab-shell';const side=document.createElement('aside');side.className='sidebar';side.innerHTML=libraryNav(active);const controls=main.querySelector('.lab-controls');if(controls){const title=document.createElement('div');title.className='side-title';title.textContent='实验条件';side.append(title,controls);}
 if(['alignment','bandwidth','workset','store-tail','peer-copy'].includes(active))main.querySelector('.lab-heading')?.insertAdjacentHTML('afterend',retestNotice());
 main.replaceWith(shell);shell.append(side,main);main.classList.add('workspace');
}
