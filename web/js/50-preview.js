// --- Typst preview: main file + uploads as shadow files in compiler ---
let renderN = 0, renderT = 0, oldPdf = null, pvTexts = [] // text anchors per page: click hits exact (tables too)
let pvLinks = [], pvOutline = [] // PDF layer: link boxes per page (viewport units) + outline with resolved pages
let cmpWarns = [] // compiler warnings of the last good render (shown as yellow marks, never block)
let cmpWait = 0, lastInfra = false // compiler missing / last render infra error (watchdog heals)
const typstReady = () => !!window.$typst?.resetShadow // true once lazy bundle arrived (exports only; preview compiles in the worker below)
const PV_WORKER_URL = '/vendor/typst-all-in-one-0.8.0-rc3-89646b6f5523.js' // pinned, self-hosted (see vendor/); bundles Typst 0.15.1 (= CLI 0.15.1), RC chosen deliberately for compiler parity
const PV_WORKER_WASM = '/vendor/typst-compiler-0.8.0-rc3-85a071522388.wasm' // worker compiles only: no renderer WASM needed (pdf.js draws)
// measured 10.10.: no `new Worker` anywhere in web/ â€” compile + full raster ran on the main thread, typing stalled on big docs
const PV_WORKER_SRC = `
self.window = self // typst bundle touches bare window at import time (renderer heritage): alias it, compile never needs DOM
var T = null
var enc = new TextEncoder()
function fix(v, n) {
  if (typeof v === 'bigint') return Number(v)
  if (!v || typeof v !== 'object' || n > 6) {
    if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') return v
    return null
  }
  var o, k, i
  if (Array.isArray(v)) {
    o = []
    for (i = 0; i < v.length; i++) o.push(fix(v[i], n + 1))
    return o
  }
  o = {}
  for (k in v) {
    try { o[k] = fix(v[k], n + 1) } catch (e) {}
  }
  return o
}
onmessage = function (e) {
  var j = e.data || {}
  if (j.cmd === 'init') {
    import(j.bundle).then(function (m) {
      var api = m.$typst || m.default || m
      var fonts = (m.preloadRemoteFonts || m.loadFonts)(j.fonts, { assets: false })
      api.setCompilerInitOptions({ getModule: function () { return j.compiler }, beforeBuild: [fonts] })
      T = api
      postMessage({ kind: 'ready' })
    }).catch(function (err) { postMessage({ kind: 'ready', fail: String((err && err.message) || err) }) })
    return
  }
  if (j.cmd !== 'work' || !T) { // pre-init work: fail the job (bare return would stall the pvTail queue forever)
    if (j.cmd === 'work' && j.id != null) postMessage({ kind: 'done', id: j.id, fail: 'init' })
    return
  }
  ;(async function () {
    var diags = []
    try {
      if (j.full) { // files/templates changed: full remap once, else only main.typ below (reset would wipe the shadow)
        await T.resetShadow()
        var tp = j.tpl || []
        for (var k2 = 0; k2 < tp.length; k2++) await T.mapShadow('/' + tp[k2].name, enc.encode(tp[k2].content))
        var fs = j.files || []
        for (var k = 0; k < fs.length; k++) await T.mapShadow('/' + fs[k].name, new Uint8Array(fs[k].bytes))
      } // tpl first, files win: doc-local beats global on collision (see .update-review/resource-contract.md)
      await T.addSource('/main.typ', j.main)
      var c = await T.getCompiler()
      await c.reset()
      var r = await c.compile({ mainFilePath: '/main.typ', format: 1, diagnostics: 'full' })
      var pdf = r.result
      try { diags = fix(r.diagnostics || [], 0) } catch (e2) {}
      if (pdf && pdf.length) {
        postMessage({ kind: 'done', id: j.id, pdf: pdf, diags: diags }, [pdf.buffer])
      } else { // content error: resolved without bytes â€” diags carry the positions, message tops the empty state
        var firstMsg = ''
        try { firstMsg = String((diags[0] && diags[0].message) || '') } catch (e4) {}
        postMessage({ kind: 'done', id: j.id, fail: firstMsg || 'content', diags: diags })
      }
    } catch (err) {
      var fromTry = []
      try { fromTry = fix((err && err.diagnostics) || diags || [], 0) } catch (e3) {}
      postMessage({ kind: 'done', id: j.id, fail: String((err && err.message) || err), diags: fromTry })
    }
  })()
}
`
let pvWorker = null, pvWorkerOk = false, pvWorkerFail = false, pvJobN = 0 // compile worker: null until first render, Fail sticks (fallback takes over)
let pvMapped = false, pvSentSig = '', pvBibSig = '' // worker shadow state: remap only on change (same rule as main-thread shadowSig)
let pvTextDone = [] // per-page text index state: raster fills it early, pvTextAll fills the rest
const PV_HASH_MAX = 262144 // hash files up to 256KB: live same-length edits change the sig, big binaries use mtime+length only
function pvHash(b) { // FNV-1a over bytes: cheap change detector for text files (no crypto needed)
  let h = 2166136261
  for (let i = 0; i < b.length; i++) { h ^= b[i]; h = Math.imul(h, 16777619) }
  return (h >>> 0).toString(36)
}
const pvFileSig = (n, c) => n + ':' + c.mtime + ':' + c.bytes.length + (c.bytes.length <= PV_HASH_MAX ? ':' + pvHash(c.bytes) : '')
function pvResTpl() { // resolved templates this doc reaches (see .update-review/resource-contract.md)
  try {
    if (typeof usedTpls === 'function') {
      const names = usedTpls(true) || []
      const set = new Set(names)
      if (typeof activeFile !== 'undefined' && activeFile && isTplKey(activeFile)) set.add(tabName(activeFile))
      return projectResources().filter(x => set.has(x.name))
    }
  } catch (e) {}
  return projectResources()
}
const pvJobs = new Map() // worker round-trips by job id
let pvScale = 2, pvPageSize = null, pvSlots = [], pvObs = null // virtual list: one slot per page, only visible ones rasterized
let pvZoomMode = 'pct' // pct | width | page (persisted below)
let typstPm = null // compiler loads async: UI stays clickable while WASM loads
let typstWarned = false // max 1 warning: no endless retry on blocked CDN
const typstFonts = [ // self-hosted default text set (see vendor/manifest.json): replaces the bundle's remote default
  '/vendor/font-DejaVuSansMono-Bold-bce60f1b4421.ttf', '/vendor/font-DejaVuSansMono-BoldOblique-91713a71d550.ttf',
  '/vendor/font-DejaVuSansMono-Oblique-742097840c54.ttf', '/vendor/font-DejaVuSansMono-b4a6c3e4faab.ttf',
  '/vendor/font-LibertinusSerif-Bold-0264914210ed.otf', '/vendor/font-LibertinusSerif-BoldItalic-47a665259f09.otf',
  '/vendor/font-LibertinusSerif-Italic-9a393d63d6e0.otf', '/vendor/font-LibertinusSerif-Regular-fcf06307a773.otf',
  '/vendor/font-LibertinusSerif-Semibold-a4b3f28e8588.otf', '/vendor/font-LibertinusSerif-SemiboldItalic-397f0d7aba35.otf',
  '/vendor/font-NewCM10-Bold-947931c42ca3.otf', '/vendor/font-NewCM10-BoldItalic-0ddd9bab5b7d.otf',
  '/vendor/font-NewCM10-Italic-70c9c811bb0e.otf', '/vendor/font-NewCM10-Regular-2f751e3082ce.otf',
  '/vendor/font-NewCMMath-Bold-8956f7ef6c21.otf', '/vendor/font-NewCMMath-Book-b2e655d5cae5.otf',
  '/vendor/font-NewCMMath-Regular-bfd2f9b22caa.otf']
function ensureTypst() {
  if (typstPm) return typstPm
  typstPm = import(PV_WORKER_URL).then(m => { // pinned, self-hosted (see vendor/); bundles Typst 0.15.1 (= CLI 0.15.1), RC chosen deliberately for compiler parity
    if (!window.$typst) window.$typst = m.$typst || m.default || m // ESM bundle sets no global: adopt it
    // bundle default points to missing WASM (404): pin explicitly (see docs example)
    const fontLoader = (m.preloadRemoteFonts || m.loadFonts)(typstFonts, { assets: false }) // local fonts, no remote fetch
    window.$typst.setCompilerInitOptions({ getModule: () => '/vendor/typst-compiler-0.8.0-rc3-85a071522388.wasm', beforeBuild: [fontLoader] })
    window.$typst.setRendererInitOptions({ getModule: () => '/vendor/typst-renderer-0.8.0-rc3-b6947e0293db.wasm', beforeBuild: [fontLoader] })
  }).catch(e => {
    typstPm = null // allow retry: watchdog retries instead of stalling
    if (!typstWarned) { typstWarned = true; console.warn('Compiler still loading - network/adblock issue.', e) }
    throw new Error(t('downloads.compilerLoading'))
  })
  return typstPm
}
setTimeout(() => {
  if (!typstReady() || !window.pdfjsLib) $('cdnLine').style.display = 'block'
  else $('cdnLine').style.display = 'none'
}, 5000)
function updExports() {
  const r = typstReady() || pvWorkerOk, tip = r ? '' : t('preview.stillLoading')
  for (const id of ['dlPdf', 'dlSvg']) { const b = $(id); if (!b) continue; b.disabled = !r; b.title = r ? b.getAttribute('aria-label') : tip }
}
const updExportsT = setInterval(() => { updExports(); if (typstReady() || pvWorkerOk) clearInterval(updExportsT) }, 2000)
function pvEnsureWorker() { // compile worker (Blob URL: no shell/backend change needed, CSP allows worker-src blob:)
  if (pvWorker || pvWorkerFail) return pvWorker
  let w = null
  try {
    w = new Worker(URL.createObjectURL(new Blob([PV_WORKER_SRC], { type: 'text/javascript' })), { type: 'module' })
  } catch (e) { pvWorkerFail = true; return null } // no Worker (exotic browser): main-thread fallback below
  pvWorker = w
  w.onmessage = e => {
    const m = e.data || {}
    if (m.kind === 'ready') {
      if (m.fail) { // bundle/WASM blocked (adblock): give up on the worker, fallback compiles on the main thread
        pvWorkerFail = true
        try { w.terminate() } catch (_) {}
        pvWorker = null; pvMapped = false
        for (const [, j] of pvJobs) j.bad(Object.assign(new Error(m.fail), { diags: m.diags }))
        pvJobs.clear()
      } else { pvWorkerOk = true; $('cdnLine').style.display = 'none'; updExports(); if (docId) render() }
      if (m.fail && docId) render() // worker dead on arrival: fall back without waiting for the watchdog
      return
    }
    if (m.kind !== 'done') return
    const j = pvJobs.get(m.id)
    if (!j) return
    pvJobs.delete(m.id)
    if (m.fail) j.bad(Object.assign(new Error(m.fail), { diags: m.diags }))
    else j.ok(m)
  }
  w.onerror = () => { // worker died: pending jobs fail into the error path, next render falls back
    pvWorkerFail = true
    try { w.terminate() } catch (_) {}
    pvWorker = null; pvWorkerOk = false; pvMapped = false
    for (const [, j] of pvJobs) j.bad(new Error(t('preview.compileFailed')))
    pvJobs.clear()
    if (docId) render()
  }
  try { w.postMessage({ cmd: 'init', bundle: location.origin + PV_WORKER_URL, compiler: location.origin + PV_WORKER_WASM, fonts: typstFonts.map(f => location.origin + f) }) } // blob workers resolve no relative/absolute paths: fully qualified or it 404s in the worker
  catch (e) { pvWorkerFail = true; try { w.terminate() } catch (_) {} pvWorker = null; return null }
  return pvWorker
}
let pvTail = Promise.resolve() // compile queue: one worker round-trip at a time (parallel resetShadow/compile races corrupt the shadow)
function pvCall(job, id) { // one compile round-trip (rejects into the render error path, keeps last good preview)
  return new Promise((ok, bad) => {
    pvTail = pvTail.then(() => new Promise(done => {
      if (id !== renderN) { done(); ok({ skip: true }); return } // stale: newer render queued, spare the worker
      const w = pvEnsureWorker()
      if (!w || pvWorkerFail || !pvWorkerOk) { done(); bad(new Error(t('preview.compileFailed'))); return }
      const message = { ...job, full: job.sig !== pvSentSig || !pvMapped }
      if (!message.full) { delete message.files; delete message.tpl }
      pvJobs.set(job.id, {
        ok: m => { pvSentSig = job.sig; pvMapped = true; done(); ok(m) },
        bad: e => { pvMapped = false; done(); bad(e) }
      })
      try { w.postMessage(message) } catch (e) { pvJobs.delete(job.id); pvMapped = false; done(); bad(e) }
    }))
  })
}
let typstT0 = 0 // load start: hint only on real stall, not on slow net
function noteCompiler(preview) { // hint instead of endless rendering note (only on stall)
  if (!typstT0) typstT0 = Date.now()
  $('cdnLine').style.display = 'block'
  if (++cmpWait >= 8 && Date.now() - typstT0 > 25000 && !preview.querySelector('.pvPage[data-done], canvas')) {
    preview.innerHTML = '<p class="empty">' + t('preview.needsInternet') + ' <button>' + t('preview.tryAgain') + '</button></p>'
    preview.querySelector('button').onclick = () => render()
  }
}
setInterval(() => { // watchdog: dead render (init race, dropped retry) heals itself
  if (docId && !tplName && lastInfra && !$('preview').querySelector('.pvPage[data-done], canvas')) render()
}, 3000)
const fileCache = new Map() // name -> {mtime, bytes}: reload binaries only on change
function queueRender() { clearTimeout(renderT); renderT = setTimeout(render, RENDER_MS) } // fixed 300ms compile debounce
async function pvFiles() { // file list + bytes + chips + bib keys (no compiler mapping: worker preview and main-thread export share it)
  const myDoc = docId, epoch = openN
  if (!myDoc) return null
  if (!await loadDocResources() || myDoc !== docId || epoch !== openN) return null
  if (filesDirty || Date.now() - filesAt > FILES_TTL) try { // list only when changed/stale, not per keystroke
    const files = (await api('GET', `/api/docs/${myDoc}/files`)).files
    if (myDoc !== docId) return null // doc switched meanwhile
    lastFiles = files // only on success: failed list keeps old cache intact
    filesDirty = false; filesAt = Date.now()
    mediaNames = files.map(f => f.name)
    const sig = files.map(f => f.name + f.size + ':' + f.mtime).join('|')
    if (sig !== lastMedia) { lastMedia = sig; renderMediaChips(files) } // manager chips only on change
  } catch (e) { console.warn('file list stale, using cache', e) } // 429/offline: reuse lastFiles below, no wipe
  if (myDoc !== docId) return null
  const files = lastFiles
  const seen = new Set()
  await Promise.all(files.map(async f => { // parallel: no serial fetch for many files
    seen.add(f.name)
    const c = fileCache.get(f.name)
    if (!c || c.mtime !== f.mtime || c.bytes.length !== f.size) {
      let rr
      for (let attempt = 0; attempt < 2; attempt++) {
        try {
          rr = await fetch(`/api/docs/${myDoc}/files/` + encodeURIComponent(f.name))
          if (rr.ok || rr.status < 500 || attempt) break
        } catch (e) { if (attempt) throw e }
        await new Promise(resolve => setTimeout(resolve, 500)) // one retry for network/server failures, never loop on denied/missing files
        if (myDoc !== docId || epoch !== openN) return
      }
      if (myDoc !== docId) return // next doc: drop, never fill its cache
      if (!rr.ok) {
        const message = t('preview.fileLoadFailed', { name: f.name, status: rr.status })
        throw Object.assign(new Error(message), { diags: [{ severity: 'error', message }] }) // never compile with a missing or outdated input
      }
      const bytes = new Uint8Array(await rr.arrayBuffer())
      if (myDoc !== docId || epoch !== openN) return
      if (f.name === activeFile && tabDirty) return // server bytes must not replace the live draft
      fileCache.set(f.name, { mtime: f.mtime, bytes })
      // All current inputs must survive until compilation; prune removed files below.
    }
  }))
  if (myDoc !== docId) return null // switched mid-fetch: no prune, no sig for the next doc
  for (const k of [...fileCache.keys()]) if (!seen.has(k)) fileCache.delete(k)
  const resTpl = pvResTpl()
  const sig = myDoc + '\u0002' + [...fileCache].map(([n, c]) => pvFileSig(n, c)).join('|') + '\u0002' + resTpl.map(t => t.name + '\u0000' + t.content).join('\u0001')
  if (sig !== pvBibSig) { // files/templates changed: recollect #cite sources once
    pvBibSig = sig
    bibKeys = []
    const bibSeen = new Set()
    const collect = txt => {
      try {
        for (const m of String(txt).matchAll(/@\w+\s*\{\s*([^,\s}]+)/g))
          if (!bibSeen.has(m[1])) { bibSeen.add(m[1]); bibKeys.push(m[1]) }
      } catch (e) {}
    }
    const dec = new TextDecoder()
    for (const [n, c] of fileCache) {
      if (!/\.bib$/i.test(n)) continue
      try { collect(dec.decode(c.bytes)) } catch (e) {}
    }
    for (const tp of resTpl) if (/\.bib$/i.test(tp.name)) collect(tp.content)
  }
  return { sig, tpl: resTpl, doc: myDoc }
}
async function shadowAll(main) { // files + templates as shadow: main-thread fallback and PDF/SVG export share it
  const id = docId, epoch = openN
  const pf = await pvFiles()
  const current = () => id === docId && epoch === openN
  if (!pf || !current()) return false
  if (pf.sig !== shadowSig) { // files/templates changed: full remap once, else only main.typ below
    shadowSig = '' // half-mapped on throw: force remap next time
    await $typst.resetShadow()
    if (!current()) return false
    for (const t of (pf.tpl || pvResTpl())) { await $typst.mapShadow('/' + t.name, new TextEncoder().encode(t.content)); if (!current()) return false }
    for (const [n, c] of fileCache) { await $typst.mapShadow('/' + n, c.bytes); if (!current()) return false }
    shadowSig = pf.sig
  }
  await $typst.addSource('/main.typ', main)
  return current()
}
const pvStale = (id, myDoc, myTplName) => id !== renderN || myDoc !== docId || myTplName !== tplName || (!!activeFile && !window.changeSession) // render epoch/doc/file guard
function pvSrcList() { // live source texts for honest cross-file anchors: [{key, text}]
  const out = []
  try {
    out.push({ key: '', text: activeFile ? shadow : getT() })
    const dec = new TextDecoder()
    for (const [n, c] of fileCache) {
      if (!/\.(typ|bib|csv)$/i.test(n) || n === activeFile) continue
      if (!c || !c.bytes || c.bytes.length > 262144) continue
      try { out.push({ key: n, text: dec.decode(c.bytes) }) } catch (e) {}
    }
    if (activeFile && !isTplKey(activeFile) && !out.some(s => s.key === activeFile)) out.push({ key: activeFile, text: getT() })
    for (const t of pvResTpl()) {
      const k = TPLK + t.name
      if (out.some(s => s.key === k)) continue
      out.push({ key: k, text: isTplKey(activeFile) && tabName(activeFile) === t.name ? getT() : (t.content || '') })
    }
  } catch (e) {}
  return out
}
async function render() {
  const id = ++renderN, preview = $('preview'), myDoc = docId, myTplName = tplName
  if (!myDoc || myTplName || (activeFile && !window.changeSession)) return
  pvBar() // zoom pill extras once (needs consts from later files)
  if (pvWorkerFail || !pvEnsureWorker()) { await renderDirect(id, preview); return } // no worker: main-thread compile
  if (!window.pdfjsLib) { $('cdnLine').style.display = 'block'; lastInfra = true; setTimeout(() => { if (docId) render() }, 3000); return } // lib blocked: retry later
  if (!pvWorkerOk) { noteCompiler(preview); lastInfra = true; return } // worker boots: ready-handler re-renders
  cmpWait = 0; typstT0 = 0; $('cdnLine').style.display = 'none'
  let wDiags = null // worker diags of this render: empty-pdf failures tag along (compile resolves, pdf.js throws)
  try {
    const main = window.changeSession ? sessionMainText() : activeFile ? shadow : getT() // file tab: preview still compiles main.typ
    const pf = await pvFiles()
    if (!pf || pvStale(id, myDoc, myTplName)) return // stale: skip wasted compile
    const job = { cmd: 'work', id: ++pvJobN, main, sig: pf.sig,
      files: [...fileCache].map(([n, c]) => ({ name: n, bytes: c.bytes })),
      tpl: (pf.tpl || []).map(x => ({ name: x.name, content: x.content })) }
    const m = await pvCall(job, id) // compile off the main thread: typing stays fluid
    if (!m || m.skip || pvStale(id, myDoc, myTplName)) return
    wDiags = m.diags
    if (pvStale(id, myDoc, myTplName)) return
    const doc = await pdfjsLib.getDocument({ data: m.pdf }).promise
    if (pvStale(id, myDoc, myTplName)) { try { doc.destroy() } catch (e) {} return }
    oldPdf?.destroy(); oldPdf = doc
    const n = doc.numPages
    pvScale = n > 60 ? 1 : n > 25 ? 1.4 : 2 // render scale by page count: 100 pages stay usable
    const sizes = []
    for (let p = 1; p <= n; p++) { // sizes only (no raster): slots keep total height, no scroll jump
      const pg = await doc.getPage(p)
      sizes.push(pg.getViewport({ scale: 1 }))
      if (pvStale(id, myDoc, myTplName)) { try { doc.destroy() } catch (e) {} return }
    }
    if (pvStale(id, myDoc, myTplName)) { try { doc.destroy() } catch (e) {} return }
    pvPageSize = sizes[0]
    pvModeApply() // width/page zoom follows current layout
    pvTexts = Array.from({ length: n }, () => []) // dense: sync math indexes by page (holes would crash it)
    pvTextDone = Array.from({ length: n }, () => false)
    pvLinks = Array.from({ length: n }, () => [])
    pvSlots = sizes.map((v, k) => {
      const s = document.createElement('div')
      s.className = 'pvPage'; s.dataset.page = k + 1; s.dataset.r = v.height / v.width; s.dataset.w = v.width
      s.style.width = pvCssW(v.width) + 'px'; s.style.height = pvCssW(v.height) + 'px'
      const c = document.createElement('canvas')
      c.width = 16; c.height = 16 // blank until rasterized: slot keeps layout, backing stays tiny
      pvBlank(c)
      s.appendChild(c)
      return s
    })
    const a0 = pvAnchorRead(preview) // rough anchor: which pages will be in view after the swap
    const first = a0.page >= 0 ? a0.page : 0, hv = Math.max(1, Math.ceil(preview.clientHeight / Math.max(1, (pvSlots[0] ? parseFloat(pvSlots[0].style.height) : 600))) + 1)
    for (let k = first; k < Math.min(pvSlots.length, first + hv + 1); k++) { // no blank flash: visible pages are ready before the old ones go
      try { await pvDraw(pvSlots[k], doc, id, true) } catch (e) {}
      if (pvStale(id, myDoc, myTplName)) { try { doc.destroy() } catch (e) {} return }
    }
    if (pvStale(id, myDoc, myTplName)) { try { doc.destroy() } catch (e) {} return } // template/closed view: never swap a stale render in
    const anchor = pvAnchorRead(preview) // at swap time: the awaits above take seconds, an early anchor goes stale
    preview.replaceChildren(...pvSlots)
    pvAnchorBack(preview, anchor)
    scrollApplyPreview() // first render of a reopened doc: back to its saved page + offset
    pvWatch(doc, id, myDoc, myTplName) // visible pages (+ buffer) rasterize, far ones evict
    pvTextAll(doc, id, myDoc, myTplName) // text index for every page: sync works past the visible window
    pvOutline = [] // old bookmarks die with the old render
    pvLoadOutline(doc, id).catch(() => {})
    clearErr() // running again: clear marks
    cmpWarns = (wDiags || []).filter(d => d && d.severity === 'warning'); if (cmpWarns.length) paintErr()
    lastInfra = false
  } catch (e) { if (!pvStale(id, myDoc, myTplName)) { // error: keep last render, red lines, never wrong empty text
    cmpDiags = ((e && e.diags) || wDiags || []).filter(d => d && d.severity === 'error'); paintErr() // worker diags only: main-thread shadows are stale here (errDiags stays in renderDirect)
    const firstMsg = (errLines[0] && errLines[0].msg || '').split('\n')[0].slice(0, 200)
    const lined = errLines.some(e => e.line)
    if (!$('preview').querySelector('.pvPage[data-done]')) {
      const p = el('p', 'empty') // real message, not generic: package errors live in other files
      p.append(document.createTextNode(firstMsg ? t('preview.couldNotRender', { msg: firstMsg }) : t('preview.couldNotRenderBare')))
      const btn = el('button', null, t('preview.tryAgain')); btn.onclick = () => render(); p.appendChild(btn)
      if (pvObs) pvObs.disconnect()
      pvSlots = []; pvPageSize = null
      $('preview').replaceChildren(p)
      if (firstMsg) { if (navigator.onLine !== false) toast(t('preview.typstError', { msg: firstMsg.slice(0, 140) })) } // offline: inline message suffices, no toast spam (2E gate, worker path)
      else if (navigator.onLine !== false) toast(t('preview.loadFailed'), () => render())
    } else if (errLines.length && !lined && errKey !== lastErrToast && navigator.onLine !== false) { lastErrToast = errKey; toast(t('preview.typstError', { msg: firstMsg.slice(0, 140) })) } // line errors: red marks + badge suffice, no toast per keystroke
    lastInfra = !errLines.length && !$('preview').querySelector('.pvPage[data-done]') // infra (not content): watchdog retries
  } }
}
function pvCssW(w) { return w * pvZoom / 100 } // css px at current zoom (backing/pvScale = true size)
function pvBlank(c) { c.style.width = '100%'; c.style.height = '100%' } // unrasterized: fill the slot (white page look)
function pvFitCanvas(c) { // CSS size from zoom, scale-aware (sizeCanvas in 90-settings assumes scale 2)
  const s = +c.dataset.s || pvScale
  c.style.width = (c.width / s * pvZoom / 100) + 'px'
  c.style.maxWidth = 'none' // none: zoom may exceed container, preview scrolls
  c.style.height = 'auto'
}
async function pvDraw(slot, doc, id, detached) { // rasterize one slot (backing freed again when far outside); detached: slot not in the DOM yet (pre-draw before the swap)
  if ((!detached && !slot.isConnected) || slot.dataset.done || slot.dataset.busy) return
  slot.dataset.busy = '1'
  try {
    const p = +slot.dataset.page
    const page = await doc.getPage(p)
    if (id !== renderN || (!detached && !slot.isConnected)) return
    const v = page.getViewport({ scale: pvScale })
    const c = slot.firstChild
    c.width = Math.ceil(v.width); c.height = Math.ceil(v.height) // backing = viewport, never touch after
    c.dataset.s = pvScale
    c.setAttribute('role', 'img'); c.setAttribute('aria-label', t('preview.pageLabel', { n: p }))
    await page.render({ canvasContext: c.getContext('2d'), viewport: v }).promise
    pvFitCanvas(c) // CSS size only, not canvas.width
    const tc = await page.getTextContent() // click anchors: each visible word knows its spot
    if (id !== renderN) return
    pvTexts[p - 1] = pvBoxes(tc, v)
    pvLinks[p - 1] = await pvPageLinks(doc, page, v)
    if (id !== renderN) return
    pvPaintLinks(slot, p - 1)
    try { pvTextDone[p - 1] = true } catch (e) {}
    slot.dataset.done = '1'
  } finally { delete slot.dataset.busy }
}
function pvEvict(slot) { // free backing of far pages (slot keeps layout, text anchors stay for sync)
  if (!slot.dataset.done || slot.dataset.busy) return
  delete slot.dataset.done
  const c = slot.firstChild
  if (c) { c.width = 16; c.height = 16; pvBlank(c) }
}
function pvSweep() {
  if (window.Present?.isOn()) return // evict rasterized slots far outside the viewport
  if (!pvSlots.length) return
  const pv = $('preview'), pr = pv.getBoundingClientRect(), pad = 2 * pr.height
  for (const s of pvSlots) {
    if (!s.dataset.done || s.dataset.busy) continue
    const r = s.getBoundingClientRect()
    if (r.bottom < pr.top - pad || r.top > pr.bottom + pad) pvEvict(s)
  }
}
function pvWatch(doc, id, myDoc, myTplName) { // draw on scroll into view (+2 viewports buffer), sweep the rest
  if (pvObs) pvObs.disconnect()
  pvObs = new IntersectionObserver(es => {
    if (id !== renderN || (myDoc !== undefined && (myDoc !== docId || myTplName !== tplName))) return
    for (const en of es) if (en.isIntersecting) pvDraw(en.target, doc, id)
    pvSweep()
  }, { root: $('preview'), rootMargin: '200% 0' + 'px' }) // string split: one literal with space+letters trips check_i18n
  for (const s of pvSlots) pvObs.observe(s)
}
function pvBoxes(tc, v) { // textContent -> click anchors in viewport px (raster-independent)
  const tr = v.transform, a = tr[0], b = tr[1], cc = tr[2], d = tr[3], ee = tr[4], ff = tr[5]
  const ax = Math.abs(a) || 1, ay = Math.abs(d) || 1
  return tc.items.map(it => {
    const w = (it.width || 0) * ax, h = (it.height || 0) * ay
    const x = a * it.transform[4] + cc * it.transform[5] + ee, y = b * it.transform[4] + d * it.transform[5] + ff
    return { s: it.str, x: x + w / 2, x0: x, w, h: h || 10, y: y - (h || 10) / 2, vw: v.width, vh: v.height }
  })
}
const PV_LINK_SCHEME = /^(https?|mailto):/i // only schemes a browser tab may open safely from a PDF
async function pvDestTarget(doc, dest) { // PDF destination (name or explicit array) -> page + top; null: unresolvable
  try {
    const d = typeof dest === 'string' ? await doc.getDestination(dest) : dest
    if (!Array.isArray(d) || !d[0]) return null
    const page = await doc.getPageIndex(d[0]) // 0-based
    const kind = String((typeof d[1] === 'string' ? d[1] : d[1] && d[1].name) || '')
    const top = kind === 'XYZ' ? d[3] : (kind === 'FitH' || kind === 'FitBH' ? d[2] : (kind === 'FitR' ? d[5] : null))
    return { page, top: typeof top === 'number' && isFinite(top) ? top : null }
  } catch (e) { return null } // broken destination: no jump, never throw into the render
}
async function pvPageLinks(doc, page, v) { // annotation layer: external URLs and internal jumps as boxes
  let anns = []
  try { anns = await page.getAnnotations() } catch (e) { return [] }
  const out = []
  for (const a of anns) {
    if (!a || a.subtype !== 'Link' || !a.rect) continue
    const r = v.convertToViewportRectangle(a.rect)
    const box = { x0: Math.min(r[0], r[2]), y0: Math.min(r[1], r[3]), x1: Math.max(r[0], r[2]), y1: Math.max(r[1], r[3]), vw: v.width, vh: v.height }
    if (box.x1 - box.x0 < 1 || box.y1 - box.y0 < 1) continue // invisible/degenerate: never a click target
    const url = a.url || a.unsafeUrl || ''
    if (url && PV_LINK_SCHEME.test(url)) { out.push({ ...box, url }); continue }
    if (a.dest) {
      const dest = await pvDestTarget(doc, a.dest)
      if (dest) out.push({ ...box, dest })
    }
  }
  return out
}
function pvPaintLinks(slot, pi) { // percent boxes: zoom and relayout need no update, browser does hit testing
  if (!slot) return
  const old = slot.querySelector('.pvLinks')
  if (old) old.remove()
  const links = pvLinks[pi] || []
  if (!links.length) return
  const box = document.createElement('div')
  box.className = 'pvLinks'
  links.forEach((L, i) => {
    const a = document.createElement('a')
    a.style.left = (L.x0 / L.vw * 100) + '%'
    a.style.top = (L.y0 / L.vh * 100) + '%'
    a.style.width = ((L.x1 - L.x0) / L.vw * 100) + '%'
    a.style.height = ((L.y1 - L.y0) / L.vh * 100) + '%'
    if (L.url) { a.href = L.url; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.title = L.url }
    else { // internal destination: click jumps the preview, never the editor
      a.href = '#'; a.title = t('preview.linkPage', { n: L.dest.page + 1 })
      a.dataset.pvLink = String(i)
    }
    a.setAttribute('aria-label', a.title)
    box.appendChild(a)
  })
  slot.appendChild(box)
}
const scrollAnims = new WeakMap() // one animation per element: a jump and a follow never fight
let pvSelfTop = -1 // last preview scrollTop this app wrote: a user scroll differs and moves the editor
function pvSelfWrite(el) { if (el && el.id === 'preview') pvSelfTop = el.scrollTop }
function smoothStop(el) {
  const a = scrollAnims.get(el)
  if (a) { cancelAnimationFrame(a.raf); scrollAnims.delete(el) }
}
function smoothScroll(el, y) { // jump: quintic in-out, one fixed duration so editor and preview arrive together
  const max = Math.max(0, el.scrollHeight - el.clientHeight)
  const target = Math.max(0, Math.min(max, y))
  const running = scrollAnims.get(el)
  if (running && running.jump && Math.abs(running.target - target) < 1) return // already flying there
  smoothStop(el)
  let calm = false
  try { calm = matchMedia('(prefers-reduced-motion: reduce)').matches } catch (e) {}
  const from = el.scrollTop, dy = target - from
  if (calm || Math.abs(dy) < 1) { el.scrollTop = target; pvSelfWrite(el); return }
  const dur = 320, t0 = performance.now(), a = { jump: true, target, raf: 0 }
  const step = now => {
    const k = Math.min(1, (now - t0) / dur)
    el.scrollTop = from + dy * k * k * k * (k * (6 * k - 15) + 10) // smootherstep: no overshoot, no hard start
    pvSelfWrite(el)
    if (k < 1) a.raf = requestAnimationFrame(step)
    else scrollAnims.delete(el)
  }
  scrollAnims.set(el, a)
  a.raf = requestAnimationFrame(step)
}
function smoothFollow(el, y) { // cursor/scroll follow: new targets keep position and speed, so nothing restarts
  const max = Math.max(0, el.scrollHeight - el.clientHeight)
  const target = Math.max(0, Math.min(max, y))
  let calm = false
  try { calm = matchMedia('(prefers-reduced-motion: reduce)').matches } catch (e) {}
  if (calm) { smoothStop(el); el.scrollTop = target; pvSelfWrite(el); return }
  let a = scrollAnims.get(el)
  if (a && a.follow) { a.target = target; return }
  smoothStop(el)
  if (Math.abs(target - el.scrollTop) < 1) { el.scrollTop = target; pvSelfWrite(el); return }
  a = { follow: true, target, v: 0, t: performance.now(), omega: 28, raf: 0 }
  const step = now => {
    const dt = Math.max(0.001, Math.min(0.05, (now - a.t) / 1000))
    a.t = now
    const x = el.scrollTop, c = x - a.target, e = Math.exp(-a.omega * dt)
    const nx = a.target + (c + (a.v + a.omega * c) * dt) * e
    a.v = (a.v - (a.v + a.omega * c) * a.omega * dt) * e
    el.scrollTop = nx
    pvSelfWrite(el)
    if (Math.abs(nx - a.target) < 0.5 && Math.abs(a.v) < 4) {
      el.scrollTop = a.target
      pvSelfWrite(el)
      scrollAnims.delete(el)
      return
    }
    a.raf = requestAnimationFrame(step)
  }
  scrollAnims.set(el, a)
  a.raf = requestAnimationFrame(step)
}
function pvScrollStop() { try { smoothStop($('preview')) } catch (e) {} } // any deliberate scroll wins over a jump still in flight
function pvScrollTo(pv, y) { smoothScroll(pv, y) }
const pvBox0 = $('preview') // guarded: unit tests slice this file with a bare $ stub
if (pvBox0 && pvBox0.addEventListener) pvBox0.addEventListener('wheel', pvScrollStop, { passive: true }) // user scroll wins over a jump animation
function pvGotoTarget(target) { // internal jump: destination page, refined by its top coordinate
  if (!target) return
  const pv = $('preview'), s = pvSlots[target.page]
  if (s) {
    const pr = pv.getBoundingClientRect(), sr = s.getBoundingClientRect()
    const hPt = +s.dataset.w * +s.dataset.r, cssH = parseFloat(s.style.height) || 0
    let y = 0
    if (target.top != null && hPt > 0 && cssH > 0) y = Math.max(0, Math.min(cssH, cssH * (1 - target.top / hPt)))
    pvScrollTo(pv, pv.scrollTop + sr.top - pr.top + y - pv.clientHeight * 0.12)
    return
  }
  const cv = pvCanvasList()[target.page] // fallback path: bare canvases, page top only
  if (!cv) return
  const pr = pv.getBoundingClientRect(), cr = cv.getBoundingClientRect()
  pvScrollTo(pv, pv.scrollTop + cr.top - pr.top - pv.clientHeight * 0.12)
}
async function pvLoadOutline(doc, id) { // bookmarks with pages: the honest anchor chain for source -> PDF
  let root = []
  try { root = await doc.getOutline() || [] } catch (e) { return }
  const out = []
  const walk = async (list, depth) => {
    for (const it of list || []) {
      if (id !== renderN) return
      const target = it && it.dest ? await pvDestTarget(doc, it.dest) : null
      if (target) out.push({ title: String((it && it.title) || ''), page: target.page, depth })
      if (it && it.items && it.items.length) await walk(it.items, depth + 1)
    }
  }
  await walk(root, 0)
  if (id !== renderN) return
  pvOutline = out
  try { paintOutline() } catch (e) {} // sidebar badges follow the PDF, not the cursor
}
function pvOlNorm(s) { return syncText(String(s).replace(/<[^>]*>/g, ' ')).replace(/^\d+(\s+\d+)*\s*/, '') } // heading text: no labels, no "1.2 "
function pvOlMatch(text, from) { // PDF bookmark index for a source heading, in document order; -1: not in the outline
  if (!pvOutline.length) return -1
  const want = pvOlNorm(text)
  if (!want) return -1
  for (let k = from; k < pvOutline.length; k++) if (pvOlNorm(pvOutline[k].title) === want) return k
  return -1
}
function pvSections() { // source heading line -> PDF page, in document order (the anchor chain)
  const out = []
  let at = 0
  getT().split('\n').forEach((ln, i) => {
    const m = ln.match(/^(=+)\s+(.+)$/)
    if (!m) return
    const k = pvOlMatch(m[2], at)
    if (k < 0) return
    at = k + 1
    out.push({ line: i + 1, page: pvOutline[k].page, title: m[2] })
  })
  return out
}
function pvSecAt(page) { // preview page -> section start + the next section (both may be null)
  const secs = pvSections()
  let i = -1
  for (let k = 0; k < secs.length && secs[k].page <= page; k++) i = k
  return { sec: i >= 0 ? secs[i] : null, next: i >= 0 ? (secs[i + 1] || null) : null }
}
function pvSecAtLine(line) { // source line -> its section with inclusive page and line bounds
  const secs = pvSections()
  let i = -1
  for (let k = 0; k < secs.length && secs[k].line <= line; k++) i = k
  if (i < 0) return null
  const sec = secs[i], next = secs[i + 1] || null
  return { ...sec, endPage: next ? next.page : Math.max(0, pvTexts.length - 1), endLine: next ? next.line - 1 : Infinity }
}
function pvSecAtY(pi, y) { // preview point -> section: several headings share a page, so their height decides
  const secs = pvSections(), lines = getT().split('\n')
  let sec = null, next = null
  for (const s of secs) {
    if (s.page > pi) { next = s; break }
    if (s.page < pi) { sec = s; continue }
    const hit = syncAnchor(lines, s.line, pvTexts, { ...s, endPage: s.page })
    if (!hit || hit.it.y <= y) sec = s
    else { next = s; break }
  }
  return { sec, next }
}
function pvPageMeta(doc, p, scale) { // one page: text anchors + link boxes (indexed past the visible window)
  return doc.getPage(p).then(async page => {
    const v = page.getViewport({ scale })
    const tc = await page.getTextContent()
    return { items: pvBoxes(tc, v), links: await pvPageLinks(doc, page, v) }
  })
}
if (pvBox0 && pvBox0.addEventListener) pvBox0.addEventListener('click', e => { // internal PDF destination: external links open natively
  const a = e.target.closest ? e.target.closest('.pvLinks a[data-pv-link]') : null
  if (!a) return
  const slot = a.closest('.pvPage'), pi = slot ? +slot.dataset.page - 1 : -1
  const L = pi >= 0 ? (pvLinks[pi] || [])[+a.dataset.pvLink] : null
  if (!L || !L.dest) return
  e.preventDefault() // hash href: keep the URL and the scroll position of the app
  pvGotoTarget(L.dest)
  pvSyncDest(L.dest) // follow mode: the editor moves to the same destination
})
async function pvTextAll(doc, id, myDoc, myTplName) { // every page gets anchors + links: sync works past the visible window
  try {
    for (let p = 1; p <= pvTexts.length; p++) {
      if (pvStale(id, myDoc, myTplName)) return
      if (pvTextDone[p - 1]) continue
      let meta
      try { meta = await pvPageMeta(doc, p, pvScale) } catch (e) { continue }
      if (pvStale(id, myDoc, myTplName)) return
      pvTexts[p - 1] = meta.items
      pvLinks[p - 1] = meta.links
      pvPaintLinks(pvSlots[p - 1], p - 1)
      try { pvTextDone[p - 1] = true } catch (e) {}
      if (p % 8 === 0) await new Promise(r => setTimeout(r, 0)) // yield: typing stays fluid on long docs
    }
  } catch (e) {}
  if (syncMiss) queueSyncPv() // a sync that ran before the new page text was indexed: retry once it is
}
function pvAnchorRead(pv) { // first visible slot + offset (scrollTop alone drifts when heights change)
  const pr = pv.getBoundingClientRect(), top = pv.scrollTop
  const slots = pv.querySelectorAll('.pvPage')
  for (let k = 0; k < slots.length; k++) {
    const r = slots[k].getBoundingClientRect()
    if (r.bottom > pr.top + 1) return { top, page: k, off: r.top - pr.top }
  }
  return { top, page: -1, off: 0 } // no slots (first render, error text): keep scrollTop below
}
function pvAnchorBack(pv, a) {
  const slots = pv.querySelectorAll('.pvPage')
  if (a && a.page >= 0 && slots.length && a.page < slots.length) {
    const r = slots[a.page].getBoundingClientRect(), pr = pv.getBoundingClientRect()
    pv.scrollTop += (r.top - pr.top) - a.off
  } else if (a) pv.scrollTop = Math.min(a.top, Math.max(0, pv.scrollHeight - pv.clientHeight))
  pvSelfWrite(pv)
}
// --- Per-document scroll memory: editor + preview spot, this browser/device only ---
const SCROLL_KEY = 'typst_scroll' // localStorage stays on this device: another machine keeps its own spots
const SCROLL_MAX = 200 // bounded store: oldest documents fall out instead of growing forever
function scrollMap() { // read at every use: another tab may have saved a different document since load
  try {
    const s = JSON.parse(localStorage.getItem(SCROLL_KEY) || '{}')
    if (s && typeof s === 'object' && !Array.isArray(s)) return s
  } catch (e) {}
  return {}
}
let scrollRestore = null // loaded on open; editor and preview apply it once their content is ready
let scrollT = 0
const scrollNum = v => Number.isFinite(+v) ? +v : 0
function scrollRead(id) { // snapshot: a later save must not change the values this open restores
  const s = scrollMap()[id]
  if (!s || typeof s !== 'object') return null
  return { doc: id, epoch: 0, l: Math.max(1, scrollNum(s.l) || 1), lo: Math.max(0, scrollNum(s.lo)), p: s.p == null ? -1 : scrollNum(s.p), po: scrollNum(s.po), pt: Math.max(0, scrollNum(s.pt)), ed: false, pv: false }
}
function saveDocScroll() { // scroll, doc switch and pagehide write the latest spot: it survives reloads
  if (!docId || tplName || openedTrashed || !synced || window.suggestionDraft || window.changeSession) return // loading/trash/review: never overwrite a good spot with another buffer
  const all = scrollMap() // merge with what another tab may have written: only this document changes below
  const prev = all[docId] && typeof all[docId] === 'object' ? all[docId] : {}
  const e = Object.assign({}, prev)
  if (!activeFile && cm.scrollDOM.clientHeight) { // file tab or hidden editor: keep the document's own main.typ spot
    const ed = cm.scrollDOM, block = cm.lineBlockAtHeight(ed.scrollTop)
    e.l = cm.state.doc.lineAt(block.from).number
    e.lo = Math.max(0, Math.round(ed.scrollTop - block.top))
  }
  const pv = $('preview')
  if (pv.clientHeight && pv.querySelector('.pvPage')) { // hidden/empty/error preview: keep the last good preview spot
    const a = pvAnchorRead(pv)
    e.p = a.page; e.po = Math.round(a.off); e.pt = Math.round(a.top)
  }
  e.t = Date.now()
  all[docId] = e
  const keys = Object.keys(all)
  if (keys.length > SCROLL_MAX) keys.sort((a, b) => scrollNum(all[a].t) - scrollNum(all[b].t)).slice(0, keys.length - SCROLL_MAX).forEach(k => delete all[k])
  try { localStorage.setItem(SCROLL_KEY, JSON.stringify(all)) } catch (e) {} // quiet: a lost scroll spot must never evict draft stashes
}
function queueDocScroll() {
  clearTimeout(scrollT)
  scrollT = setTimeout(saveDocScroll, 300) // one write after a scroll gesture, not per pixel
}
function scrollApplyEditor() { // after Yjs sync: line + offset survive edits above the saved spot
  const r = scrollRestore
  if (!r || r.doc !== docId || r.epoch !== openN || r.ed || activeFile || window.suggestionDraft || window.changeSession || (!synced && !openedTrashed)) return
  if (!cm.scrollDOM.clientHeight) return // read-only view: setView retries once the editor is visible
  r.ed = true
  const line = Math.max(1, Math.min(cm.state.doc.lines, r.l))
  const top = Math.max(0, cm.lineBlockAt(cm.state.doc.line(line).from).top + r.lo)
  requestAnimationFrame(() => {
    if (r.epoch !== openN || r.doc !== docId) return
    cm.scrollDOM.scrollTop = Math.min(top, Math.max(0, cm.scrollDOM.scrollHeight - cm.scrollDOM.clientHeight))
  })
}
function scrollApplyPreview() { // page + offset survive new page sizes and zoom changes
  const r = scrollRestore
  if (!r || r.doc !== docId || r.epoch !== openN || r.pv || window.suggestionDraft || window.changeSession) return
  const pv = $('preview')
  if (!pv.clientHeight) return // editor-only view: setView retries once the preview is visible
  const pages = pv.querySelectorAll('.pvPage').length ? pv.querySelectorAll('.pvPage') : pv.querySelectorAll('canvas')
  if (r.p >= 0) {
    if (!pages.length) return // first render still pending: keep the saved page for the next call
    const node = pages[Math.min(r.p, pages.length - 1)], nr = node.getBoundingClientRect(), pr = pv.getBoundingClientRect()
    pv.scrollTop += (nr.top - pr.top) - r.po
  } else if (r.pt) {
    if (pv.scrollHeight <= pv.clientHeight) return
    pv.scrollTop = Math.min(r.pt, pv.scrollHeight - pv.clientHeight)
  }
  pvSelfWrite(pv)
  r.pv = true
}

async function renderDirect(id, preview) { // fallback: no worker (exotic browser, blocked bundle) â€” same output, main thread
  let cmp = null // single compile: error path reuses its diagnostics (no second compile)
  const myDoc = docId, myTplName = tplName
  if (!myDoc || myTplName || (activeFile && !window.changeSession)) return
  if (pvObs) pvObs.disconnect()
  pvSlots = []; pvPageSize = null // bare canvases below: drop slot state (zoom clicks size them directly)
  if (!typstReady()) { noteCompiler(preview); lastInfra = true; ensureTypst().then(() => { if (docId) render() }).catch(() => {}); return } // loads in background, renders after
  if (!window.pdfjsLib) { $('cdnLine').style.display = 'block'; lastInfra = true; setTimeout(() => { if (docId) render() }, 3000); return } // lib blocked: retry later
  cmpWait = 0; typstT0 = 0; $('cdnLine').style.display = 'none'
  try {
    await shadowAll(window.changeSession ? sessionMainText() : activeFile ? shadow : getT()) // file tab: preview still compiles main.typ
    if (pvStale(id, myDoc, myTplName)) return // stale: skip wasted full compile
    const compiler = await $typst.getCompiler()
    await compiler.reset() // same reset $typst.pdf() did before compiling
    cmp = await compiler.compile({ mainFilePath: '/main.typ', format: 1, diagnostics: 'full' }) // 1 = pdf: bytes + diagnostics in one compile
    if (pvStale(id, myDoc, myTplName)) return // stale: skip wasted pdfjs work
    const doc = await pdfjsLib.getDocument({ data: cmp.result }).promise
    if (pvStale(id, myDoc, myTplName)) { doc.destroy(); return }
    oldPdf?.destroy(); oldPdf = doc
    const pages = [], texts = [] // double buffer: old pages stay visible until all new ones are ready (no flicker/scroll jump)
    for (let p = 1; p <= doc.numPages; p++) {
      const page = await doc.getPage(p), v = page.getViewport({ scale: 2 }), c = document.createElement('canvas')
      if (p === 1) pvPageSize = page.getViewport({ scale: 1 }) // width/page zoom works in the fallback too
      c.width = v.width; c.height = v.height // backing = viewport (scale 2), never touch
      c.setAttribute('role', 'img'); c.setAttribute('aria-label', t('preview.pageLabel', { n: p }))
      await page.render({ canvasContext: c.getContext('2d'), viewport: v }).promise
      sizeCanvas(c) // CSS width only, not canvas.width
      const tc = await page.getTextContent() // click anchors: each visible word knows its spot
      if (pvStale(id, myDoc, myTplName)) return
      texts.push(pvBoxes(tc, v))
      pages.push(c)
    }
    if (pvStale(id, myDoc, myTplName)) return
    pvModeApply() // width/page zoom follows the fallback layout too
    for (const c of pages) sizeCanvas(c) // pvZoom just changed above: resize the new pages, not the old ones in the DOM
    if (pvStale(id, myDoc, myTplName)) return // template/closed view: never swap a stale render in
    const st = preview.scrollTop // read at swap time: follow-scroll during render is kept
    preview.replaceChildren(...pages)
    pvTexts = texts
    pvLinks = texts.map(() => []) // fallback: no annotation overlay (bare canvases)
    try { pvTextDone = texts.map(() => true) } catch (e) {}
    preview.scrollTop = st
    pvSelfWrite(preview)
    scrollApplyPreview() // fallback render of a reopened doc: back to its saved page + offset
    pvOutline = []
    pvLoadOutline(doc, id).catch(() => {})
    clearErr() // running again: clear marks
    lastInfra = false
  } catch (e) { if (!pvStale(id, myDoc, myTplName)) { // error: keep last render, red lines, never wrong empty text
    const diags = cmp ? (cmp.diagnostics || []).filter(d => d.severity === 'error') : e.diags || await errDiags()
    if (pvStale(id, myDoc, myTplName)) return
    cmpDiags = diags; paintErr()
    const firstMsg = (errLines[0] && errLines[0].msg || '').split('\n')[0].slice(0, 200)
    const lined = errLines.some(e => e.line)
    if (!$('preview').querySelector('canvas')) {
      const p = el('p', 'empty') // real message, not generic: package errors live in other files
      p.append(document.createTextNode(firstMsg ? t('preview.couldNotRender', { msg: firstMsg }) : t('preview.couldNotRenderBare')))
      const btn = el('button', null, t('preview.tryAgain')); btn.onclick = () => render(); p.appendChild(btn)
      $('preview').replaceChildren(p)
      if (firstMsg) { if (navigator.onLine !== false) toast(t('preview.typstError', { msg: firstMsg.slice(0, 140) })) } // offline: inline message suffices, no toast spam
      else if (navigator.onLine !== false) toast(t('preview.loadFailed'), () => render())
    } else if (errLines.length && !lined && errKey !== lastErrToast && navigator.onLine !== false) { lastErrToast = errKey; toast(t('preview.typstError', { msg: firstMsg.slice(0, 140) })) } // line errors: red marks + badge suffice, no toast per keystroke
    lastInfra = !errLines.length && !$('preview').querySelector('canvas') // infra (not content): watchdog retries
  } }
}
let lastErrToast = '' // same non-line error: toast once, not per render
let errKey = '', errLines = [], cmpDiags = [] // compiler errors: lint renders ranges (F1+F20), badge keeps one row per line
function keyForPath(path) { // compiler path -> tab key (null: package or unknown file, nowhere to jump)
  const n = String(path || '').replace(/^\//, '')
  if (!n || n === 'main.typ') return n ? '' : null
  if (lastFiles.some(x => x.name === n)) return n
  if (projectResources().some(x => x.name === n)) return TPLK + n
  return null
}
function clearErr() { errKey = ''; errLines = []; cmpDiags = []; errTipHide(); cm.dispatch({ effects: setErrLine.of(RangeSet.of([])) }); cm.dispatch(setDiagnostics(cm.state, [])); updErrBadge() }
async function errDiags() { // fallback only: pre-compile failure (render reuses its own compile)
  if (!typstReady()) return []
  try {
    const r = await (await $typst.getCompiler()).compile({ mainFilePath: '/main.typ', diagnostics: 'full' }) // vector default is fine here, diagnostics is what matters
    return (r.diagnostics || []).filter(d => d.severity === 'error')
  } catch (err) { return [{ severity: 'error', message: String((err && err.message) || err || t('preview.compileFailed')) }] }
}
// <diagRange>
function diagRange(d, doc) { // F20: real column ranges from compiler diagnostics (0-based) -> doc offsets; null = no position in this doc
  if (!d || !doc || doc.lines < 1) return null
  let sl = -1, sc = 0, el = -1, ec = 0, explicit = true
  const raw = d.range != null ? d.range : (d.span != null ? d.span : d.location)
  if (typeof raw === 'string') {
    let m = raw.match(/(\d+)\s*:\s*(\d+)\s*[-â€“;]\s*(\d+)\s*:\s*(\d+)/) // "sl:sc-el:ec"
    if (m) { sl = +m[1]; sc = +m[2]; el = +m[3]; ec = +m[4] }
    else if ((m = raw.match(/(\d+)\s*:\s*(\d+)/))) { sl = +m[1]; sc = +m[2]; el = sl; ec = sc } // point: "sl:sc"
    else if ((m = raw.match(/(\d+)/))) { sl = +m[1]; sc = 0; el = sl; ec = -1; explicit = false } // line only: whole line (legacy)
  } else if (raw && typeof raw === 'object') {
    const num = v => { const n = +v; return Number.isFinite(n) ? n : null }
    const s = raw.start != null ? raw.start : raw, e = raw.end != null ? raw.end : raw
    const so = s && typeof s === 'object' ? s : null, eo = e && typeof e === 'object' ? e : null
    if (so && (num(so.line) != null)) {
      sl = num(so.line); sc = num(so.column != null ? so.column : so.col) || 0
      el = eo && num(eo.line) != null ? num(eo.line) : sl; ec = eo && (num(eo.column != null ? eo.column : eo.col) != null) ? num(eo.column != null ? eo.column : eo.col) : sc
    } else if (num(raw.startLine) != null || num(raw.line) != null) {
      sl = num(raw.startLine) != null ? num(raw.startLine) : num(raw.line)
      sc = num(raw.startColumn) != null ? num(raw.startColumn) : (num(raw.startCol) != null ? num(raw.startCol) : (num(raw.column) != null ? num(raw.column) : (num(raw.col) || 0)))
      el = num(raw.endLine) != null ? num(raw.endLine) : sl
      ec = num(raw.endColumn) != null ? num(raw.endColumn) : (num(raw.endCol) != null ? num(raw.endCol) : (raw.end != null && typeof raw.end !== 'object' && num(raw.end) != null ? num(raw.end) : sc))
    } else if (num(raw.from) != null && num(raw.to) != null && raw.line == null) {
      const bf = Math.max(0, Math.min(doc.length, num(raw.from))), bt = Math.max(0, Math.min(doc.length, Math.max(bf + 1, num(raw.to)))), bl = doc.lineAt(bf)
      return { from: bf, to: bt, line: bl.number, col: bf - bl.from + 1, explicit: true } // bare offsets: line/col from the doc, not hardcoded
    } else if (num(raw.line) != null) { sl = num(raw.line); sc = 0; el = sl; ec = -1; explicit = false }
  } else if (typeof d.line === 'number') { sl = d.line; sc = typeof d.column === 'number' ? d.column : (typeof d.col === 'number' ? d.col : 0); el = typeof d.endLine === 'number' ? d.endLine : sl; ec = typeof d.endColumn === 'number' ? d.endColumn : (typeof d.endCol === 'number' ? d.endCol : sc) } // top-level line/col shape
  if (sl < 0) return null
  const last = doc.lines - 1
  sl = Math.max(0, Math.min(last, sl)); el = Math.max(0, Math.min(last, el < 0 ? sl : el))
  if (el < sl || (el === sl && ec < sc && ec >= 0)) { const tl = sl; sl = el; el = tl; const tc = sc; sc = ec < 0 ? 0 : ec; ec = tc } // reversed: normalize
  const sLine = doc.line(sl + 1), eLine = doc.line(el + 1)
  const sLen = sLine.to - sLine.from, eLen = eLine.to - eLine.from
  sc = Math.max(0, Math.min(sLen, sc))
  let from = sLine.from + sc, to
  if (ec < 0) to = eLine.to // whole line (legacy): no column info
  else to = eLine.from + Math.max(0, Math.min(eLen, ec))
  if (to <= from) { to = Math.min(sLine.to, from + 1); if (to <= from) to = Math.min(doc.length, from + 1) } // point/empty: widen to 1 char
  if (to <= from) {
    if (doc.length < 1 || from < doc.length) return null // empty doc edge: nothing to mark
    from = doc.length - 1; to = doc.length // empty span at EOF (e.g. lone `#` with no trailing newline): anchor on the last char instead of dropping the mark
    const bl = doc.lineAt(from); sl = bl.number - 1; sc = from - bl.from
  }
  return { from, to, line: sl + 1, col: sc + 1, explicit }
}
// </diagRange>
function paintErr() { // compile errors via lint (F1): every column range renders (F20), badge keeps one row per line
  const doc = cm.state.doc, diags = [], byLine = new Map(), general = []
  for (const d of cmpDiags) {
    const msg = (d && d.message) || t('preview.typstErrorBare')
    const r = d && d.path === tabPath(activeFile) ? diagRange(d, doc) : null // marks for the text in the editor (main.typ or the open tab)
    if (r) {
      diags.push({ from: r.from, to: r.to, severity: 'error', message: msg + (d.hints && d.hints.length ? '\n' + d.hints.map(h => 'â†’ ' + h).join('\n') : ''), source: 'typst' })
      if (!byLine.has(r.line)) byLine.set(r.line, { line: r.line, col: r.explicit ? r.col : 0, from: r.from, to: r.to, raw: msg, msg: msg + t('preview.lineSuffix', { line: r.line, col: r.explicit ? ':' + r.col : '' }) })
    } else { // foreign file (package) or no position: no mark possible, but never drop it
      let where = (d && d.package ? d.package + ' ' : '') + (d && d.path && d.path !== '/main.typ' ? d.path : '')
      const at = String((d && (d.range || d.span || d.location)) || '').match(/(\d+)/)
      if (where && at) where += ':' + (+at[1] + 1)
      const full = (where ? where + ' Â· ' : '') + msg
      if (!general.some(g => g.msg === full)) general.push({ line: 0, col: 0, from: -1, raw: msg, msg: full, tab: keyForPath(d && d.path), jl: at ? +at[1] + 1 : 0 })
    }
  }
  const keyOf = d => { // stable across compiles: object ranges need JSON (String() collapses them to "[object Object]")
    let r = ''
    try { const v = d && (d.range != null ? d.range : (d.span != null ? d.span : d.location)); r = v != null && typeof v === 'object' ? JSON.stringify(v) : String(v || '') } catch (_) { r = '[unserializable]' }
    const p = d ? [d.line, d.column, d.col, d.endLine, d.endColumn, d.endCol].map(v => v != null ? v : '').join(',') : ''
    return ((d && d.path) || '') + '|' + r + '|' + String(p) + '|' + ((d && d.message) || '')
  }
  const key = activeFile + '\u0003' + cmpDiags.map(keyOf).join('\n') + '\u0004' + cmpWarns.map(keyOf).join('\n')
  if (key === errKey) return // nothing new: no dispatch, no loop (lint maps positions across edits)
  errKey = key
  for (const d of cmpWarns) { // warnings: only for the text in the editor, yellow squiggle + message on hover
    const r = d && d.path === tabPath(activeFile) ? diagRange(d, doc) : null
    if (r) diags.push({ from: r.from, to: r.to, severity: 'warning', message: (d.message || '') + (d.hints && d.hints.length ? '\n' + d.hints.map(h => 'â†’ ' + h).join('\n') : ''), source: 'typst' })
  }
  errLines = [...byLine].map(([, e]) => e).sort((a, b) => a.line - b.line).concat(general)
  const lineDeco = []
  for (const [, e] of byLine) { try {
    const ln = doc.line(e.line)
    lineDeco.push(Decoration.line({ class: 'cm-errLine' }).range(ln.from))
    if (ln.to > ln.from) lineDeco.push(Decoration.mark({ class: 'cm-errMark', attributes: { 'data-err': e.msg, 'data-line': String(e.line) } }).range(ln.from, Math.max(e.to || ln.from, ln.from + 1))) // trigger carrier: line start through error end (hover fires anywhere on the line)
    else if (ln.from < doc.length) lineDeco.push(Decoration.mark({ class: 'cm-errMark', attributes: { 'data-err': e.msg, 'data-line': String(e.line) } }).range(ln.from, ln.from + 1)) // empty error line: carrier on the newline keeps hover + cursor tooltip working
  } catch (_) {} }
  cm.dispatch({ effects: setErrLine.of(RangeSet.of(lineDeco, true)) })
  cm.dispatch(setDiagnostics(cm.state, diags))
  updErrBadge()
} // no cursor steal: typing stays put
function errLivePos(e) { // lint maps ranges across edits: jump to the live spot, fall back to the stored one
  if (e.from < 0) return -1
  let best = e.from, bestD = Infinity
  try { forEachDiagnostic(cm.state, (d, from) => { if (d.message !== e.raw) return; const dd = Math.abs(from - e.from); if (dd < bestD) { bestD = dd; best = from } }) } catch (_) {}
  return best
}
function updErrBadge() { // error counter in header: touch-friendly, hover not needed
  queueTabs() // per-tab error counts follow the compiler
  const b = $('eBadge')
  if (!b) return
  if (!errLines.length) { b.style.display = 'none'; if ($('pop').classList.contains('errs')) closePop(true); return }
  b.style.display = ''
  b.textContent = errLines.length === 1 ? t('preview.badgeOne', { n: errLines.length }) : t('preview.badgeMany', { n: errLines.length })
  b.title = t('preview.showErrors', { list: errLines.map(e => e.line ? t('preview.lineRef', { line: e.line, col: e.col ? ':' + e.col : '' }) : e.msg.split('\n')[0].slice(0, 60)).join(', ') })
  b.setAttribute('aria-label', b.title)
  const ep = $('pop'); if (ep.classList.contains('errs') && ep.style.display !== 'none') showErrList() // live: list follows the compiler
}
function showErrList() { // click badge: list errors, click row jumps to the exact spot
  if (!errLines.length) return
  hidePops(); errTipHide() // only one error surface at a time
  const eb = $('eBadge'); if (eb) { eb.setAttribute('aria-expanded', 'true'); if (!eb.getAttribute('aria-controls')) eb.setAttribute('aria-controls', 'pop') }
  const box = $('pop')
  box.replaceChildren()
  const hd = el('div', 'eh'); hd.appendChild(el('b', null, errLines.length === 1 ? t('preview.badgeOne', { n: errLines.length }) : t('preview.badgeMany', { n: errLines.length })))
  const cx = icoBtn('ib', ICO_X); cx.title = t('common.close'); cx.setAttribute('aria-label', t('common.close')); cx.onclick = () => closePop(true); hd.appendChild(cx)
  box.appendChild(hd)
  errLines.forEach(e => { // no line (package error): text row, nowhere to jump
    const r = el(e.line || e.tab != null ? 'button' : 'div', 'er')
    if (e.line) r.appendChild(el('span', 'ln', t('preview.errRow', { line: e.line, col: e.col ? ':' + e.col : '' })))
    r.appendChild(el('span', 'em', e.msg.split('\n')[0].replace(/ Â· (line|Zeile) \d+(:\d+)?$/, '')))
    if (!e.line && e.tab != null) r.onclick = async () => { await switchTab(e.tab); if (e.jl && e.jl <= cm.state.doc.lines) { const p = cm.state.doc.line(e.jl).from; cm.dispatch({ selection: { anchor: p } }); cmGlide(p); cm.focus() } }
    if (e.line) r.onclick = () => { const p = errLivePos(e); cm.dispatch({ selection: { anchor: Math.max(0, Math.min(cm.state.doc.length, p)) } }); cmGlide(p); cm.focus() } // list stays open: only the x closes it
    box.appendChild(r)
  })
  box.classList.add('errs')
  const hb = document.querySelector('header').getBoundingClientRect().bottom // always below the top bar, never over the title
  if (eb) { const rc = eb.getBoundingClientRect(); box.style.setProperty('--eTop', Math.round(hb + 8) + 'px'); box.style.setProperty('--eLeft', Math.round(Math.max(16, Math.min(rc.right - Math.min(440, innerWidth - 32), innerWidth - Math.min(440, innerWidth - 32) - 16))) + 'px') }
  box.style.display = 'block'; paintCardView()
}
document.addEventListener('pointerdown', e => { const p = $('pop'); if (p.classList.contains('errs') && p.style.display !== 'none' && !p.contains(e.target) && !e.target.closest('#eBadge')) closePop(true) }) // error list: x or outside click
try { const m = localStorage.getItem('typst_pv_mode'); if (m === 'width' || m === 'page') pvZoomMode = m } catch (e) {} // persisted zoom mode (string compare like typst_sync)
function pvModeSet(m) { pvZoomMode = m; lsSet('typst_pv_mode', m); pvModePaint() } // explicit % (stepPv/Ctrl+0) always leaves fit modes
function pvModePaint() {
  const w = $('fitBtn'), p = $('fitPageBtn')
  if (w) w.classList.toggle('on', pvZoomMode === 'width')
  if (p) { p.classList.toggle('on', pvZoomMode === 'page'); p.setAttribute('aria-pressed', pvZoomMode === 'page' ? 'true' : 'false') }
}
function pvModeApply() { // width/page zoom follows layout (render + resize); % mode keeps pvZoom
  if (pvZoomMode === 'pct' || !pvPageSize) { pvModePaint(); return }
  const pv = $('preview')
  if (!pv) return
  if (pvZoomMode === 'width') {
    const avail = pv.clientWidth - 32
    if (avail > 0) pvZoom = Math.max(PV_MIN, Math.min(PV_MAX, Math.round(avail / pvPageSize.width * 100)))
  } else {
    const avail = pv.clientHeight - 128, width = pv.clientWidth - 32
    if (avail > 0 && width > 0) pvZoom = Math.max(PV_MIN, Math.min(PV_MAX, Math.floor(Math.min(avail / pvPageSize.height, width / pvPageSize.width) * 100)))
  }
  applyPv(); saveSet(); pvModePaint()
}
function pvRelayout() {
  if (window.Present?.isOn()) return // any zoom change (pill, settings, Ctrl+0): slots follow, done canvases rescale
  if (!pvSlots.length || !pvPageSize) return
  for (const s of pvSlots) {
    const w = pvCssW(+s.dataset.w || pvPageSize.width)
    s.style.width = w + 'px'; s.style.height = (w * +s.dataset.r) + 'px'
    const c = s.firstChild
    if (c && s.dataset.done) pvFitCanvas(c) // sizeCanvas above assumed scale 2: corrected here
  }
}
let pvBarDone = false
function pvBar() { // page-fit button next to fit-width (shell untouched: button built here)
  if (pvBarDone) return
  pvBarDone = true
  const f = $('fitBtn')
  if (!f) return
  const b = document.createElement('button')
  b.id = 'fitPageBtn'
  b.innerHTML = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="4.5" y="2" width="7" height="12" rx="1"/><path d="M1.5 5.5v5M1.5 5.5l1.3 1.3M1.5 5.5L.2 6.8M14.5 10.5v-5M14.5 10.5l1.3-1.3M14.5 10.5l-1.3-1.3"/></svg>'
  const tip = t('preview.zoomPage')
  b.title = tip; b.setAttribute('aria-label', tip); b.setAttribute('aria-pressed', 'false')
  b.setAttribute('data-i18n-title', 'preview.zoomPage'); b.setAttribute('data-i18n-aria', 'preview.zoomPage') // future language switch (2D) picks it up via applyI18n
  b.onclick = () => { pvModeSet('page'); pvModeApply(); pvRelayout() }
  f.after(b)
  f.onclick = () => { pvModeSet('width'); pvModeApply(); pvRelayout() } // replaces scale-2 fitPv: exact at any pvScale, immediate (no wait for next render)
  $('zMinus').addEventListener('click', () => pvModeSet('pct'))
  $('zPlus').addEventListener('click', () => pvModeSet('pct'))
  pvModePaint()
}
const pvStepPv = stepPv // hoisting: single module script, so function stepPv (90-settings) exists before this line runs
stepPv = d => { if (pvZoomMode !== 'pct') pvModeSet('pct'); pvStepPv(d); pvRelayout() } // explicit % leaves fit modes, slots follow at once (not via the zoomV observer only)
addEventListener('keydown', e => { if ((e.ctrlKey || e.metaKey) && e.key === '0') pvModeSet('pct') }) // window: real keys bubble here and the menu reset dispatches here (a document-capture listener would miss it)
new MutationObserver(() => pvRelayout()).observe($('zoomV'), { childList: true, characterData: true, subtree: true }) // any zoom change relayouts slots
addEventListener('resize', () => { if (!window.Present?.isOn() && pvZoomMode !== 'pct' && pvPageSize) { pvModeApply(); pvRelayout() } })
new ResizeObserver(() => { if (pvZoomMode !== 'pct' && pvPageSize && !window.Present?.isOn()) { pvModeApply(); pvRelayout() } }).observe($('preview'))
cm.scrollDOM.addEventListener('scroll', queueDocScroll)
$('preview').addEventListener('scroll', queueDocScroll)
addEventListener('pagehide', () => { clearTimeout(scrollT); saveDocScroll() }) // reload/close: drop the pending debounce, keep the spot
addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') { clearTimeout(scrollT); saveDocScroll() } })
