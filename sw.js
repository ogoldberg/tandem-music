// The app shell is precached on install, so the studio and the capture page open with no network (MOB.2).
// Bump CACHE when a precached file changes in a way that matters before the network copy is fetched.
const CACHE='tandem-v36';
// Self-hosted vendor files (Basic Pitch, instrument samples) never change at a given path, so they are
// cached the first time they are used, served from the cache first, and kept when CACHE is bumped.
const VENDOR='tandem-vendor-1';
const ASSETS=['./','./history.js','./versions.js','./groove.js','./voices.js','./contour.js','./harmony.js','./phrases.js','./storage.js','./recordings.js','./samples.js','./manifest.webmanifest','./capture','./ideas.js','./bundle.js','./daw.js','./notation.js','./dawproject.js','./midi.js','./noteedit.js','./tuning.js','./worldtune.js','./tuneworker.js','./capture.webmanifest','./icons/icon-192.png','./icons/icon-512.png','./icons/icon-maskable-512.png','./icons/apple-touch-icon.png'];
// VOX.4: the WORLD WebAssembly build is small (about 100 KB) and tuning on the device is what works
// with no network, so it goes into the vendor cache at install instead of on first use.
const VENDOR_ASSETS=['./vendor/world-d625e76-1/world.mjs','./vendor/world-d625e76-1/world.wasm'];
self.addEventListener('install',e=>e.waitUntil(Promise.all([caches.open(CACHE).then(c=>c.addAll(ASSETS)),caches.open(VENDOR).then(c=>c.addAll(VENDOR_ASSETS))])));
self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE&&k!==VENDOR).map(k=>caches.delete(k))))));
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
  // Network first, so a deploy shows at once; offline, the cached copy. A page opened with a query
  // string (the studio's ?idea=) is the same cached page.
  e.respondWith(fetch(req).then(r=>keep(CACHE,req,r)).catch(()=>caches.match(req,{ignoreSearch:req.mode==='navigate',ignoreVary:true}).then(hit=>hit||Response.error())));
});
