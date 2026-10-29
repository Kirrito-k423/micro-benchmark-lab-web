// Static encrypted delivery. Keys and decrypted responses never enter Cache Storage.
const sessions = new Map();
const scope = new URL(self.registration.scope).pathname;
const publicPaths = new Set(["","index.html",".nojekyll","access-public/entry-B4VnhynP.js","access-public/index-hPjexdAr.css","access-public/access-runtime-BvEGl8Lx.js","access-config.json","access-worker.js"]);
async function recoverSession(clientId) {
  const documents=await self.clients.matchAll({type:'window'});
  documents.sort((a,b)=>Number(b.id===clientId)-Number(a.id===clientId));
  for(const document of documents) {
    if(!document.url.startsWith(self.registration.scope))continue;
    const stored=await new Promise(resolve=>{
      const channel=new MessageChannel(),timer=setTimeout(()=>{channel.port1.close();resolve(null);},1200);
      channel.port1.onmessage=event=>{clearTimeout(timer);channel.port1.close();resolve(event.data);};
      document.postMessage({type:'request-session'},[channel.port2]);
    });
    if(!stored || stored.expiresAt<=Date.now())continue;
    const key=await crypto.subtle.importKey('raw',stored.key,'AES-GCM',false,['decrypt']);
    const session={key,expiresAt:stored.expiresAt,files:new Map(stored.files)};
    if(clientId)sessions.set(clientId,session);
    return session;
  }
  return null;
}
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('message', event => {
  const id = event.source?.id;
  event.waitUntil((async () => {
    if(!id) return;
    if(event.data?.type === 'lock') sessions.delete(id);
    else if(event.data?.type === 'unlock') {
      const {key, expiresAt, files} = event.data;
      if(!Number.isFinite(expiresAt) || expiresAt <= Date.now() || !Array.isArray(files)) return;
      const cryptoKey=await crypto.subtle.importKey('raw', key, 'AES-GCM', false, ['decrypt']);
      sessions.set(id, {key:cryptoKey, expiresAt, files:new Map(files)});
    } else return;
    event.ports[0]?.postMessage({ok:true});
  })());
});
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if(url.origin !== location.origin || !url.pathname.startsWith(scope) || event.request.method !== 'GET') return;
  const path = decodeURIComponent(url.pathname.slice(scope.length));
  if(publicPaths.has(path) || path.startsWith('access-public/') || /^vault\/[a-f0-9]+\.bin$/.test(path)) return;
  event.respondWith((async () => {
    let session=sessions.get(event.clientId) ?? await recoverSession(event.clientId);
    if(!session || Date.now() >= session.expiresAt) {
      sessions.delete(event.clientId);
      if(event.request.mode==='navigate') return fetch(scope, {cache:'no-store'});
      return new Response('Locked', {status:401,headers:{'Cache-Control':'no-store'}});
    }
    const entry=session.files.get(path);
    if(!entry) {
      if(event.request.mode==='navigate')return fetch(scope, {cache:'no-store'});
      return new Response('Not found', {status:404});
    }
    try {
      const response=await fetch(scope+entry.file, {cache:'no-store'});
      if(!response.ok) return new Response('Encrypted resource unavailable', {status:503});
      const bytes=new Uint8Array(await response.arrayBuffer());
      const packed=await crypto.subtle.decrypt({name:'AES-GCM',iv:bytes.slice(0,12)},session.key,bytes.slice(12));
      const stream=new Blob([packed]).stream().pipeThrough(new DecompressionStream('gzip'));
      return new Response(stream,{headers:{'Content-Type':entry.type,'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});
    } catch {return new Response('Resource could not be unlocked', {status:403,headers:{'Cache-Control':'no-store'}});}
  })());
});
