// The app shell is precached on install, so the studio and the capture page open with no network (MOB.2).
// FIX.6: the shell is one version. The server writes a hash of every file in ASSETS into CACHE (`/sw.js` in
// tandem_backend.py), so any change to the page or a module it imports is a new worker; the new worker fetches
// the whole set past the browser's HTTP cache, and an install that cannot fetch every file fails, leaving the
// old version whole. The new worker then waits: the pages show Update, which activates it and reloads, so a
// page and the modules it imports (also those imported later, as Tune's) always come from one install.
const CACHE='tandem-shell-@SHELL_HASH@';
// Self-hosted vendor files (Basic Pitch, instrument samples) never change at a given path, so they are
// cached the first time they are used, served from the cache first, and kept when CACHE is bumped.
const VENDOR='tandem-vendor-2';
const ASSETS=['./','./transcription.js','./polish.js','./history.js','./versions.js','./groove.js','./voices.js','./contour.js','./harmony.js','./phrases.js','./storage.js','./recordings.js','./samples.js','./manifest.webmanifest','./capture','./ideas.js','./bundle.js','./daw.js','./notation.js','./dawproject.js','./midi.js','./noteedit.js','./guide.js','./playhead.js','./evolution.js','./take.js','./pitch.js','./beats.js','./latency.js','./mixer.js','./layers.js','./takes.js','./sections.js','./tension.js','./drawline.js','./practice.js','./exercises.js','./lyrics.js','./genre.js','./beatbox.js','./tuning.js','./worldtune.js','./tuneworker.js','./capture.webmanifest','./icons/icon-192.png','./icons/icon-512.png','./icons/icon-maskable-512.png','./icons/apple-touch-icon.png'];
// VOX.4: the WORLD WebAssembly build is small (about 100 KB) and tuning on the device is what works
// with no network, so it goes into the vendor cache at install instead of on first use.
const VENDOR_ASSETS=['./vendor/world-d625e76-1/world.mjs','./vendor/world-d625e76-1/world.wasm'];
const fresh=url=>new Request(url,{cache:'reload'});
self.addEventListener('install',e=>e.waitUntil(Promise.all([caches.open(CACHE).then(c=>c.addAll(ASSETS.map(fresh))),caches.open(VENDOR).then(c=>c.addAll(VENDOR_ASSETS))])));
self.addEventListener('message',e=>{if(e.data==='activate')self.skipWaiting()});
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE&&k!==VENDOR).map(k=>caches.delete(k))))));
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
  if(SHELL.has(new URL(req.url).pathname)){
    e.respondWith(caches.open(CACHE).then(c=>c.match(req,{ignoreSearch:req.mode==='navigate',ignoreVary:true})).then(hit=>hit||fetch(req)));
    return;
  }
  // Anything else network first; offline, the cached copy.
  e.respondWith(fetch(req).then(r=>keep(CACHE,req,r)).catch(()=>caches.match(req,{ignoreSearch:req.mode==='navigate',ignoreVary:true}).then(hit=>hit||Response.error())));
});
