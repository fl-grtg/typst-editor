// App shell offline: own static only, API/WS always network (no stale risk).
// Bump V on shell changes (index.html, vendor-cm.js), else clients never see the update.
// theme_color light #f5f5f7 / dark #1d1d1f: see index.html meta + manifest.json theme_color
const V = 'typst-24'
const SHELL = ['./', './index.html', './vendor-cm.js', './manifest.json', './icon.svg', './icon-192.png', './icon-512.png', './screenshot.png']
self.addEventListener('install', e => {
  e.waitUntil(caches.open(V).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()).catch(e => console.warn('sw install', e)))
})
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => k !== V).map(k => caches.delete(k))))
    .then(() => self.clients.claim()))
})
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url)
  if (e.request.method !== 'GET' || u.origin !== location.origin) return
  if (u.pathname.startsWith('/api') || u.pathname.startsWith('/ws')) return
  e.respondWith(caches.match(e.request, { ignoreSearch: true }).then(r => r || fetch(e.request).then(res => {
    const cp = res.clone()
    if (!u.search) caches.open(V).then(c => c.put(e.request, cp).catch(() => {})) // never cache ?join= (token URL)
    return res
  }).catch(err => { if (e.request.mode === 'navigate') return caches.match('./index.html'); throw err })))
})
