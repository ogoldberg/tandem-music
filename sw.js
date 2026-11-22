// The app shell is precached on install, so the studio and the capture page open with no network (MOB.2).
// FIX.6: the shell is one version. The server writes a hash of every file in ASSETS into CACHE and each file's
// SHA-256 into SUMS (`/sw.js` in tandem_backend.py), so any change to the page or a module it imports is a new
// worker. The new worker fetches the whole set past the browser's HTTP cache and keeps a file only when it is
// the one SUMS names, so an install that gets a missing or an older file fails and the old version stays whole.
// The new worker then waits: the pages show Update, which activates it and reloads. Each page is served the
// version it opened with until it reloads (VERSIONS), so a page and the modules it imports (also those imported
// later, as Tune's, and its workers') always come from one install, even with a newer version active.
const CACHE='tandem-shell-@SHELL_HASH@';
const SUMS=@SHELL_SUMS@;
// Self-hosted vendor files (Basic Pitch, instrument samples) never change at a given path, so they are
// cached the first time they are used, served from the cache first, and kept when CACHE is bumped.
const VENDOR='tandem-vendor-2';
const ASSETS=['./','./transcription.js','./polish.js','./history.js','./versions.js','./groove.js','./tap.js','./voices.js','./contour.js','./harmony.js','./phrases.js','./storage.js','./recordings.js','./samples.js','./manifest.webmanifest','./capture','./ideas.js','./bundle.js','./daw.js','./notation.js','./dawproject.js','./midi.js','./noteedit.js','./guide.js','./playhead.js','./evolution.js','./take.js','./pitch.js','./beats.js','./latency.js','./mixer.js','./layers.js','./takes.js','./sections.js','./tension.js','./drawline.js','./practice.js','./exercises.js','./lyrics.js','./genre.js','./bars.js','./placement.js','./actions.js','./beatbox.js','./tuning.js','./worldtune.js','./tuneworker.js','./capture.webmanifest','./icons/icon-192.png','./icons/icon-512.png','./icons/icon-maskable-512.png','./icons/apple-touch-icon.png'];
// VOX.4: the WORLD WebAssembly build is small (about 100 KB) and tuning on the device is what works
// with no network, so it goes into the vendor cache at install instead of on first use.
const VENDOR_ASSETS=['./vendor/world-d625e76-1/world.mjs','./vendor/world-d625e76-1/world.wasm'];
// Which version each page (and each worker a page starts) opened with, by client id, in a cache every
// version of this worker reads, so a newer worker still serves an open page its own version.
const VERSIONS='tandem-versions';
const hex=buf=>[...new Uint8Array(buf)].map(b=>b.toString(16).padStart(2,'0')).join('');
async function checked(asset){
  const r=await fetch(new Request(asset,{cache:'reload'}));
  if(!r.ok)throw Error(asset+' could not be fetched ('+r.status+')');
  const body=await r.arrayBuffer();
  if(hex(await crypto.subtle.digest('SHA-256',body))!==SUMS[asset])throw Error(asset+' is not the file of this version');
  return [asset,new Response(body,{status:r.status,statusText:r.statusText,headers:r.headers})];
}
async function installShell(){const files=await Promise.all(ASSETS.map(checked)),c=await caches.open(CACHE);await Promise.all(files.map(([a,r])=>c.put(a,r)))}
self.addEventListener('install',e=>e.waitUntil(Promise.all([installShell(),caches.open(VENDOR).then(c=>c.addAll(VENDOR_ASSETS))])));
self.addEventListener('message',e=>{if(e.data==='activate')self.skipWaiting()});
const versionKey=id=>new URL('./__version/'+encodeURIComponent(id),self.location).href;
const remember=(id,name)=>id?caches.open(VERSIONS).then(c=>c.put(versionKey(id),new Response(name))):Promise.resolve();
const versionOf=async id=>{if(!id)return null;const hit=await (await caches.open(VERSIONS)).match(versionKey(id));return hit?hit.text():null};
// A version is deleted only when no open page or worker still uses it.
async function tidy(){
  const live=new Set((await self.clients.matchAll({includeUncontrolled:true,type:'all'})).map(c=>c.id)),kept=new Set([CACHE,VENDOR,VERSIONS]),v=await caches.open(VERSIONS);
  for(const k of await v.keys()){const id=decodeURIComponent(new URL(k.url).pathname.split('/').pop());if(live.has(id))kept.add(await (await v.match(k)).text());else await v.delete(k)}
  for(const k of await caches.keys())if(!kept.has(k))await caches.delete(k);
}
self.addEventListener('activate',e=>e.waitUntil(tidy()));
const SHELL=new Set(ASSETS.map(a=>new URL(a,self.location).pathname));
// Only whole responses can be cached (a 206 range response cannot).
// A page is stored under its address without the query, so ?idea= links do not each add a copy.
const keyOf=req=>{const u=new URL(req.url);return req.mode==='navigate'&&u.search?u.origin+u.pathname:req};
const keep=(name,req,r)=>{if(r.status===200){const copy=r.clone();caches.open(name).then(c=>c.put(keyOf(req),copy)).catch(()=>{})}return r};
self.addEventListener('fetch',e=>{
  const req=e.request;
  if(req.method!=='GET'||!req.url.startsWith(self.location.origin)||req.url.includes('/api/'))return;
  if(new URL(req.url).pathname.startsWith('/vendor/')){
    e.respondWith(caches.open(VENDOR).then(c=>c.match(req,{ignoreVary:true})).then(hit=>hit||fetch(req).then(r=>keep(VENDOR,req,r))));
    return;
  }
  // Lookups ignore Vary: the server sends Vary: Origin (CORS), and a module import carries an Origin
  // header the precache request did not, which would miss every precached module offline.
  // A page opened with a query string (the studio's ?idea=) is the same cached page.
  // The shell from this worker's own set, never from the network: a deploy arrives whole as a new worker.
  // A page opens on this worker's version; a module or a worker it loads gets the page's version, looked up
  // in that version first, so a file this worker's version no longer has still comes from the page's.
  const path=new URL(req.url).pathname,nav=req.mode==='navigate',starts=req.destination==='worker'||req.destination==='sharedworker';
  e.respondWith((async()=>{
    const own=nav?null:await versionOf(e.clientId),pinned=own&&own!==CACHE&&await caches.has(own)?own:null;
    if(pinned){const hit=await (await caches.open(pinned)).match(req,{ignoreVary:true});if(hit){if(starts)e.waitUntil(remember(e.resultingClientId,pinned));return hit}}
    if(SHELL.has(path)){
      const name=pinned??CACHE;
      if(nav||starts)e.waitUntil(remember(e.resultingClientId,name));
      const hit=await (await caches.open(name)).match(req,{ignoreSearch:nav,ignoreVary:true});
      return hit||fetch(req);
    }
    // Anything else network first; offline, the cached copy.
    return fetch(req).then(r=>keep(CACHE,req,r)).catch(()=>caches.match(req,{ignoreSearch:nav,ignoreVary:true}).then(hit=>hit||Response.error()));
  })());
});
