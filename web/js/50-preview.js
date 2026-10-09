// --- Typst preview: main file + uploads as shadow files in compiler ---
let renderN = 0, renderT = 0, oldPdf = null, pvTexts = [] // text anchors per page: click hits exact (tables too)
let cmpWait = 0, lastInfra = false // compiler missing / last render infra error (watchdog heals)
const typstReady = () => !!window.$typst?.resetShadow // true once lazy bundle arrived
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
  typstPm = import('/vendor/typst-all-in-one-0.8.0-rc3-89646b6f5523.js').then(m => { // pinned, self-hosted (see vendor/); bundles Typst 0.15.1 (= CLI 0.15.1), RC chosen deliberately for compiler parity
    if (!window.$typst) window.$typst = m.$typst || m.default || m // ESM bundle sets no global: adopt it
    // bundle default points to missing WASM (404): pin explicitly (see docs example)
    const fontLoader = (m.preloadRemoteFonts || m.loadFonts)(typstFonts, { assets: false }) // local fonts, no remote fetch
    window.$typst.setCompilerInitOptions({ getModule: () => '/vendor/typst-compiler-0.8.0-rc3-85a071522388.wasm', beforeBuild: [fontLoader] })
    window.$typst.setRendererInitOptions({ getModule: () => '/vendor/typst-renderer-0.8.0-rc3-b6947e0293db.wasm', beforeBuild: [fontLoader] })
  }).catch(e => {
    typstPm = null // allow retry: watchdog retries instead of stalling
    if (!typstWarned) { typstWarned = true; console.warn('Compiler still loading - network/adblock issue.', e) }
    throw new Error('Compiler still loading')
  })
  return typstPm
}
setTimeout(() => {
  if (!typstReady() || !window.pdfjsLib) $('cdnLine').style.display = 'block'
  else $('cdnLine').style.display = 'none'
}, 5000)
function updExports() {
  const r = typstReady(), t = r ? '' : 'Preview still loading'
  for (const id of ['dlPdf', 'dlSvg']) { const b = $(id); if (!b) continue; b.disabled = !r; b.title = r ? b.getAttribute('aria-label') : t }
}
const updExportsT = setInterval(() => { updExports(); if (typstReady()) clearInterval(updExportsT) }, 2000)
let typstQueued = false // one catch-up render: no compile queue while typing
function queueTypstRender() {
  if (typstQueued) return
  typstQueued = true
  ensureTypst().then(() => { typstQueued = false; $('cdnLine').style.display = 'none'; updExports(); if (typstReady() && docId) render() }).catch(() => { typstQueued = false })
}
let typstT0 = 0 // load start: hint only on real stall, not on slow net
function noteCompiler(preview) { // hint instead of endless rendering note (only on stall)
  if (!typstT0) typstT0 = Date.now()
  $('cdnLine').style.display = 'block'
  if (++cmpWait >= 8 && Date.now() - typstT0 > 25000 && !preview.querySelector('canvas')) {
    preview.innerHTML = '<p class="empty">Preview not loading — needs internet. <button>Try again</button></p>'
    preview.querySelector('button').onclick = () => render()
  }
}
setInterval(() => { // watchdog: dead render (init race, dropped retry) heals itself
  if (docId && !tplName && lastInfra && !$('preview').querySelector('canvas')) render()
}, 3000)
const fileCache = new Map() // name -> {mtime, bytes}: reload binaries only on change
function queueRender() { clearTimeout(renderT); renderT = setTimeout(render, RENDER_MS) } // fixed 300ms compile debounce
async function shadowAll(main) { // files + templates as shadow: preview and PDF export share it
  if (filesDirty || Date.now() - filesAt > FILES_TTL) try { // list only when changed/stale, not per keystroke
    const forDoc = docId
    const files = (await api('GET', `/api/docs/${docId}/files`)).files
    if (forDoc !== docId) return // doc switched meanwhile
    lastFiles = files // only on success: failed list keeps old cache intact
    filesDirty = false; filesAt = Date.now()
    mediaNames = files.map(f => f.name)
    const sig = files.map(f => f.name + f.size + ':' + f.mtime).join('|')
    if (sig !== lastMedia) { lastMedia = sig; renderMediaChips(files) } // manager chips only on change
  } catch (e) { console.warn('file list stale, using cache', e) } // 429/offline: reuse lastFiles below, no wipe
  const files = lastFiles
  const seen = new Set()
  await Promise.all(files.map(async f => { // parallel: no serial fetch for many files
    seen.add(f.name)
    const c = fileCache.get(f.name)
    if (!c || c.mtime !== f.mtime) {
      const rr = await fetch(`/api/docs/${docId}/files/` + encodeURIComponent(f.name))
      if (!rr.ok) return // gone or 403: keep old shadow, no error blob
      fileCache.set(f.name, { mtime: f.mtime, bytes: new Uint8Array(await rr.arrayBuffer()) })
      while (fileCache.size > 50 || [...fileCache.values()].reduce((a, c) => a + (c.bytes ? c.bytes.length : 0), 0) > 100 * 1024 * 1024) {
        const k = fileCache.keys().next().value
        if (k === f.name) break // single huge file: keep it, cap the rest
        fileCache.delete(k)
      } // FIFO cap: 50 files or 100MB, oldest-inserted out (no recency on hit)
    }
  }))
  for (const k of [...fileCache.keys()]) if (!seen.has(k)) fileCache.delete(k)
  const sig = docId + '\u0002' + [...fileCache].map(([n, c]) => n + ':' + c.mtime + ':' + c.bytes.length).join('|') + '\u0002' + myTpl.map(t => t.name + '\u0000' + t.content).join('\u0001')
  if (sig !== shadowSig) { // files/templates changed: full remap once, else only main.typ below
    bibKeys = [] // recollect #cite sources from all .bib
    for (const [n, c] of fileCache) {
      if (!/\.bib$/i.test(n)) continue
      try {
        for (const m of new TextDecoder().decode(c.bytes).matchAll(/@\w+\s*\{\s*([^,\s}]+)/g))
          if (!bibKeys.includes(m[1])) bibKeys.push(m[1])
      } catch (e) {}
    }
    shadowSig = '' // half-mapped on throw: force remap next time
    await $typst.resetShadow()
    for (const t of myTpl) await $typst.mapShadow('/' + t.name, new TextEncoder().encode(t.content)) // templates global, not in manager
    for (const [n, c] of fileCache) await $typst.mapShadow('/' + n, c.bytes)
    shadowSig = sig
  }
  await $typst.addSource('/main.typ', main)
}
async function render() {
  const id = ++renderN, preview = $('preview')
  let cmp = null // single compile: error path reuses its diagnostics (no second compile)
  if (!docId) return
  if (!typstReady()) { noteCompiler(preview); lastInfra = true; queueTypstRender(); return } // loads in background, renders after
  if (!window.pdfjsLib) { $('cdnLine').style.display = 'block'; lastInfra = true; setTimeout(() => { if (docId) render() }, 3000); return } // lib blocked: retry later
  cmpWait = 0; typstT0 = 0; $('cdnLine').style.display = 'none'
  try {
    await shadowAll(activeFile ? shadow : getT()) // file tab: preview still compiles main.typ
    if (id !== renderN) return // stale: skip wasted full compile
    const compiler = await $typst.getCompiler()
    await compiler.reset() // same reset $typst.pdf() did before compiling
    cmp = await compiler.compile({ mainFilePath: '/main.typ', format: 1, diagnostics: 'full' }) // 1 = pdf: bytes + diagnostics in one compile
    if (id !== renderN) return // stale: skip wasted pdfjs work
    const doc = await pdfjsLib.getDocument({ data: cmp.result }).promise
    if (id !== renderN) { doc.destroy(); return }
    oldPdf?.destroy(); oldPdf = doc
    const pages = [], texts = [] // double buffer: old pages stay visible until all new ones are ready (no flicker/scroll jump)
    for (let p = 1; p <= doc.numPages; p++) {
      const page = await doc.getPage(p), v = page.getViewport({ scale: 2 }), c = document.createElement('canvas')
      c.width = v.width; c.height = v.height // backing = viewport (scale 2), never touch
      c.setAttribute('role', 'img'); c.setAttribute('aria-label', 'Preview page ' + p)
      await page.render({ canvasContext: c.getContext('2d'), viewport: v }).promise
      sizeCanvas(c) // CSS width only, not canvas.width
      const tc = await page.getTextContent() // click anchors: each visible word knows its spot
      if (id !== renderN) return
      const [a, b, cc, d, ee, ff] = v.transform // text space -> canvas px
      const ax = Math.abs(a) || 1, ay = Math.abs(d) || 1
      texts.push(tc.items.map(it => {
        const w = (it.width || 0) * ax, h = (it.height || 0) * ay
        const x = a * it.transform[4] + cc * it.transform[5] + ee, y = b * it.transform[4] + d * it.transform[5] + ff
        return { s: it.str, x: x + w / 2, y: y - (h || 10) / 2 }
      }))
      pages.push(c)
    }
    if (id !== renderN) return
    const st = preview.scrollTop // read at swap time: follow-scroll during render is kept
    preview.replaceChildren(...pages)
    pvTexts = texts
    preview.scrollTop = st
    clearErr() // running again: clear marks
    lastInfra = false
  } catch (e) { if (id === renderN) { // error: keep last render, red lines, never wrong empty text
    cmpDiags = cmp ? (cmp.diagnostics || []).filter(d => d.severity === 'error') : await errDiags(); paintErr()
    const firstMsg = (errLines[0] && errLines[0].msg || '').split('\n')[0].slice(0, 200)
    const lined = errLines.some(e => e.line)
    if (!$('preview').querySelector('canvas')) {
      const p = el('p', 'empty') // real message, not generic: package errors live in other files
      p.append(document.createTextNode(firstMsg ? 'Could not render: ' + firstMsg : 'Could not render. '))
      const btn = el('button', null, 'Try again'); btn.onclick = () => render(); p.appendChild(btn)
      $('preview').replaceChildren(p)
      if (firstMsg) toast('Typst error: ' + firstMsg.slice(0, 140))
      else toast('Preview failed to load — needs internet', () => render())
    } else if (errLines.length && !lined && errKey !== lastErrToast) { lastErrToast = errKey; toast('Typst error: ' + firstMsg.slice(0, 140)) } // line errors: red marks + badge suffice, no toast per keystroke
    lastInfra = !errLines.length && !$('preview').querySelector('canvas') // infra (not content): watchdog retries
  } }
}
let lastErrToast = '' // same non-line error: toast once, not per render
let errKey = '', errLines = [], cmpDiags = [] // compiler errors: lint renders ranges (F1+F20), badge keeps one row per line
function clearErr() { errKey = ''; errLines = []; cmpDiags = []; errTipHide(); cm.dispatch({ effects: setErrLine.of(RangeSet.of([])) }); cm.dispatch(setDiagnostics(cm.state, [])); updErrBadge() }
async function errDiags() { // fallback only: pre-compile failure (render reuses its own compile)
  if (!typstReady()) return []
  try {
    const r = await (await $typst.getCompiler()).compile({ mainFilePath: '/main.typ', diagnostics: 'full' }) // vector default is fine here, diagnostics is what matters
    return (r.diagnostics || []).filter(d => d.severity === 'error')
  } catch (err) { return [{ severity: 'error', message: String((err && err.message) || err || 'Compile failed') }] }
}
// <diagRange>
function diagRange(d, doc) { // F20: real column ranges from compiler diagnostics (0-based) -> doc offsets; null = no position in this doc
  if (!d || !doc || doc.lines < 1) return null
  let sl = -1, sc = 0, el = -1, ec = 0, explicit = true
  const raw = d.range != null ? d.range : (d.span != null ? d.span : d.location)
  if (typeof raw === 'string') {
    let m = raw.match(/(\d+)\s*:\s*(\d+)\s*[-–;]\s*(\d+)\s*:\s*(\d+)/) // "sl:sc-el:ec"
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
    const msg = (d && d.message) || 'Typst error'
    const r = d && d.path === '/main.typ' ? diagRange(d, doc) : null
    if (r) {
      diags.push({ from: r.from, to: r.to, severity: 'error', message: msg, source: 'typst' })
      if (!byLine.has(r.line)) byLine.set(r.line, { line: r.line, col: r.explicit ? r.col : 0, from: r.from, to: r.to, raw: msg, msg: msg + ' · line ' + r.line + (r.explicit ? ':' + r.col : '') })
    } else { // foreign file (package) or no position: no mark possible, but never drop it
      let where = (d && d.package ? d.package + ' ' : '') + (d && d.path && d.path !== '/main.typ' ? d.path : '')
      const at = String((d && (d.range || d.span || d.location)) || '').match(/(\d+)/)
      if (where && at) where += ':' + (+at[1] + 1)
      const full = (where ? where + ' · ' : '') + msg
      if (!general.some(g => g.msg === full)) general.push({ line: 0, col: 0, from: -1, raw: msg, msg: full })
    }
  }
  const keyOf = d => { // stable across compiles: object ranges need JSON (String() collapses them to "[object Object]")
    let r = ''
    try { const v = d && (d.range != null ? d.range : (d.span != null ? d.span : d.location)); r = v != null && typeof v === 'object' ? JSON.stringify(v) : String(v || '') } catch (_) { r = '[unserializable]' }
    const p = d ? [d.line, d.column, d.col, d.endLine, d.endColumn, d.endCol].map(v => v != null ? v : '').join(',') : ''
    return ((d && d.path) || '') + '|' + r + '|' + String(p) + '|' + ((d && d.message) || '')
  }
  const key = cmpDiags.map(keyOf).join('\n')
  if (key === errKey) return // nothing new: no dispatch, no loop (lint maps positions across edits)
  errKey = key
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
  const b = $('eBadge')
  if (!b) return
  if (!errLines.length) { b.style.display = 'none'; if ($('pop').classList.contains('errs')) closePop(true); return }
  b.style.display = ''
  b.textContent = errLines.length + (errLines.length === 1 ? ' error' : ' errors')
  b.title = 'Show errors: ' + errLines.map(e => e.line ? 'line ' + e.line + (e.col ? ':' + e.col : '') : e.msg.split('\n')[0].slice(0, 60)).join(', ')
  b.setAttribute('aria-label', b.title)
  const ep = $('pop'); if (ep.classList.contains('errs') && ep.style.display !== 'none') showErrList() // live: list follows the compiler
}
function showErrList() { // click badge: list errors, click row jumps to the exact spot
  if (!errLines.length) return
  hidePops() // only one popover at a time
  const eb = $('eBadge'); if (eb) { eb.setAttribute('aria-expanded', 'true'); if (!eb.getAttribute('aria-controls')) eb.setAttribute('aria-controls', 'pop') }
  const box = $('pop')
  box.replaceChildren()
  const hd = el('div', 'eh'); hd.appendChild(el('b', null, errLines.length + (errLines.length === 1 ? ' error' : ' errors')))
  const cx = icoBtn('ib', ICO_X); cx.title = 'Close'; cx.setAttribute('aria-label', 'Close'); cx.onclick = () => closePop(true); hd.appendChild(cx)
  box.appendChild(hd)
  errLines.forEach(e => { // no line (package error): text row, nowhere to jump
    const r = el(e.line ? 'button' : 'div', 'er')
    if (e.line) r.appendChild(el('span', 'ln', 'Line ' + e.line + (e.col ? ':' + e.col : '')))
    r.appendChild(el('span', 'em', e.msg.split('\n')[0].replace(/ · line \d+(:\d+)?$/, '')))
    if (e.line) r.onclick = () => { const p = errLivePos(e); cm.dispatch({ selection: { anchor: Math.max(0, Math.min(cm.state.doc.length, p)) }, scrollIntoView: true }); cm.focus() } // list stays open: only the x closes it
    box.appendChild(r)
  })
  box.classList.add('errs')
  const hb = document.querySelector('header').getBoundingClientRect().bottom // always below the top bar, never over the title
  if (eb) { const rc = eb.getBoundingClientRect(); box.style.setProperty('--eTop', Math.round(hb + 8) + 'px'); box.style.setProperty('--eLeft', Math.round(Math.max(8, Math.min(rc.left + rc.width / 2 - 190, innerWidth - 388))) + 'px') }
  box.style.display = 'block'
}
document.addEventListener('pointerdown', e => { const p = $('pop'); if (p.classList.contains('errs') && p.style.display !== 'none' && !p.contains(e.target) && !e.target.closest('#eBadge')) closePop(true) }) // error list: x or outside click
