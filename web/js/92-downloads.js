// downloads: source as .typ, preview as PDF; server options (standard/pages/ppi) with client fallback
const dlName = ext => (($('title').textContent || t('downloads.untitled')).replace(/[^\p{L}\p{N}._-]+/gu, '_')) + ext // unicode names kept, rest _
const dlBlob = (blob, name) => {
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob); a.download = name; a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 5000)
}
const expName = (cd, fb) => {
  const m = (cd || '').match(/filename="([^"]+)"/)
  return m ? m[1] : fb
}
async function expServer(fmt, o) { // CLI sandbox: standards/pages/ppi (WASM cannot do them)
  const doc = docId, epoch = openN, name = dlName('.' + fmt)
  if (!await flushTab() || doc !== docId || epoch !== openN) throw new Error(t('downloads.saveBeforeExport'))
  const q = new URLSearchParams({ format: fmt })
  if (o.std && o.std !== 'none') q.set('pdf_standard', o.std)
  if (o.pages) q.set('pages', o.pages)
  if (o.ppi) q.set('ppi', String(o.ppi))
  const r = await fetch('/api/docs/' + doc + '/export?' + q, { method: 'POST' })
  if (!r.ok) throw new Error(expMsg(await r.text()))
  dlBlob(new Blob([await r.blob()], { type: r.headers.get('content-type') || 'application/octet-stream' }), expName(r.headers.get('content-disposition'), name))
}
function expMsg(raw) { // {"detail": "..."} or {"detail": {"message": ...}} -> readable line
  try {
    const d = JSON.parse(raw).detail
    return String((d && d.message) || d || raw).slice(0, 160)
  } catch (e) { return raw.slice(0, 160) }
}
async function dlPngClient() { // page currently in view, straight from canvas
  if (!docId) return
  const doc = docId, epoch = openN, renderId = renderN, filename = dlName('.png')
  const cs = [...document.querySelectorAll('#preview canvas')]
  if (!cs.length) { toast(t('downloads.noRender'), () => $('dlPng').click()); return }
  const pr = $('preview').getBoundingClientRect()
  let c = cs[0], best = -Infinity
  for (const x of cs) { const r = x.getBoundingClientRect(), vis = Math.min(r.bottom, pr.bottom) - Math.max(r.top, pr.top); if (vis > best) { best = vis; c = x } }
  const n = cs.indexOf(c) + 1
  const slot = c.closest('.pvPage')
  if (slot && !slot.dataset.done) { try { await pvDraw(slot, oldPdf, renderId) } catch (e) { toast(t('downloads.pngError')); return } }
  if (doc !== docId || epoch !== openN || renderId !== renderN || !c.isConnected || (slot && !slot.dataset.done)) return
  c.toBlob(b => {
    if (!b) { toast(t('downloads.pngError'), () => $('dlPng').click()); return }
    dlBlob(b, cs.length > 1 ? filename.replace(/\.png$/, '-p' + n + '.png') : filename)
    if (cs.length > 1) toast(t('downloads.pngPage', { n, total: cs.length }))
  })
}
async function dlSvgClient() {
  if (!docId) return
  if (!typstReady()) { ensureTypst().catch(() => {}); toast(t('downloads.compilerLoading'), () => $('dlSvg').click()); return }
  const doc = docId, epoch = openN, name = dlName('.svg')
  try {
    if (!$typst.svg) throw new Error(t('downloads.svgUnknown'))
    if (!await shadowAll(activeFile ? shadow : getT()) || doc !== docId || epoch !== openN) return
    const svg = (await $typst.svg({ mainFilePath: docMain() }))
      .replace(/&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)/g, '&amp;') // raw & (text/CSV/URL) breaks XML
    if (doc !== docId || epoch !== openN) return
    dlBlob(new Blob([svg], { type: 'image/svg+xml' }), name)
  } catch (e) { toast(t('downloads.svgError', { msg: e.message })) }
}
async function dlPdfClient() {
  if (!docId) return
  if (!typstReady()) { ensureTypst().catch(() => {}); toast(t('downloads.compilerLoading'), () => $('dlPdf').click()); return }
  const doc = docId, epoch = openN, name = dlName('.pdf')
  try {
    if (!await shadowAll(activeFile ? shadow : getT()) || doc !== docId || epoch !== openN) return
    const pdf = await $typst.pdf({ mainFilePath: docMain() })
    if (doc !== docId || epoch !== openN) return
    dlBlob(new Blob([pdf], { type: 'application/pdf' }), name)
  } catch (e) { toast(t('downloads.pdfError', { msg: e.message })) }
}
function openExportDlg(fmt) { // compact popover under Export: server compile, client fallback on plain settings
  if (!docId) return
  const p = $('exportPop')
  if (!p) return
  hidePops(); closePop(true)
  p.replaceChildren()
  const top = el('div', 'sTop')
  top.appendChild(el('b', null, t('downloads.expTitle') + ' · ' + fmt.toUpperCase()))
  const close = icoBtn(null, ICO_X); close.type = 'button'; close.title = t('common.close'); close.setAttribute('aria-label', t('common.close'))
  const done = () => { p.style.display = 'none'; popTriggers('exportPop').forEach(x => x.setAttribute('aria-expanded', 'false')) }
  close.onclick = done
  top.appendChild(close)
  p.appendChild(top)
  let std = 'none', ppi = 0, pages = ''
  const lbFor = (key, id) => { const lb = el('label', null, t(key)); lb.htmlFor = id; p.appendChild(lb) }
  if (fmt === 'pdf') {
    lbFor('downloads.expStandard', 'expStd')
    const sel = document.createElement('select')
    sel.id = 'expStd'
    sel.setAttribute('aria-label', t('downloads.expStandard'))
    for (const v of ['none', '1.7', '2.0', 'a-1b', 'a-2b', 'a-3b', 'a-2u', 'a-3u', 'ua-1']) {
      const o = document.createElement('option')
      o.value = v; o.textContent = v === 'none' ? t('downloads.expNone') : v
      sel.appendChild(o)
    }
    sel.onchange = () => { std = sel.value }
    p.appendChild(sel)
  }
  if (fmt === 'png') {
    lbFor('downloads.expPpi', 'expPpi')
    const sel = document.createElement('select')
    sel.id = 'expPpi'
    sel.setAttribute('aria-label', t('downloads.expPpi'))
    for (const v of ['', '72', '144', '200', '300']) {
      const o = document.createElement('option')
      o.value = v; o.textContent = v === '' ? t('downloads.expNone') : v
      sel.appendChild(o)
    }
    sel.onchange = () => { ppi = +sel.value || 0 }
    p.appendChild(sel)
  }
  lbFor('downloads.expPages', 'expPages')
  const pg = document.createElement('input')
  pg.id = 'expPages'
  pg.type = 'text'; pg.placeholder = t('downloads.expPagesPh'); pg.setAttribute('aria-label', t('downloads.expPages')); pg.maxLength = 40
  pg.oninput = () => { pages = pg.value.trim() }
  p.appendChild(pg)
  p.appendChild(el('p', 'sub', t('downloads.expServerNote')))
  const act = el('div', 'expAct')
  const yes = el('button', 'primary', t('downloads.expGo')); yes.type = 'button'
  const fallback = { pdf: dlPdfClient, png: dlPngClient, svg: dlSvgClient }[fmt]
  yes.onclick = async () => {
    if ((fmt !== 'pdf' || std === 'none') && !ppi && !pages) { done(); fallback(); return } // plain: instant client path, no server round-trip
    yes.disabled = true
    try {
      await expServer(fmt, { std, pages, ppi })
      done()
    } catch (e) {
      const raw = e.message || ''
      const noCli = /typst CLI missing/i.test(raw) // dev without Docker: options need the server CLI
      toast(noCli ? t('downloads.expServerNoCli') : t('downloads.expServerFail', { msg: raw }), () => yes.onclick())
      yes.disabled = false
    }
  }
  pg.onkeydown = e => { if (e.key === 'Enter') yes.onclick() }
  act.append(yes)
  p.appendChild(act)
  p.style.display = ''
  anchorPop(p, $('exportBtn'), 'right')
  p.tabIndex = -1
  setTimeout(() => p.focus({ preventScroll: true }), 10)
}
$('dlPng').onclick = e => { e?.stopPropagation?.(); openExportDlg('png') }
$('dlSvg').onclick = e => { e?.stopPropagation?.(); openExportDlg('svg') }
$('dlTyp').onclick = () => {
  if (!docId && !tplName) return
  if (docId && activeFile && !TEXT_EXT.test(activeFile)) {
    const session = window.changeSession, proposed = session?.files.get(sessionKey(sessionCurrent()))
    if (proposed) {
      const bytes = sessionBytes(proposed, session.original)
      if (bytes == null) { toast(t('packages.fileAbsent')); return }
      dlBlob(new Blob([bytes]), !session.original && proposed.action === 'rename' ? proposed.target : activeFile); return
    }
    const a = document.createElement('a'); a.href = fileUrl(activeFile); a.download = activeFile.split('/').pop(); a.click(); return
  }
  dlBlob(new Blob([getT()], { type: 'text/plain;charset=utf-8' }), (tplName || (activeFile ? tabName(activeFile) : dlName('.typ'))))
}
$('dlPdf').onclick = e => { e?.stopPropagation?.(); openExportDlg('pdf') }
setInterval(() => { // heals sets without input event (extensions, autofill): textarea -> Y.Text
  if (docId && ytext && docRole !== 'reviewer' && !activeFile && !window.suggestionDraft && !window.changeSession && getT() !== shadow) {
  pushLocal(); queueRender(); queueSave()
  }
}, SAVE_MS)

$('dlZip').onclick = async () => {
  if (!docId || tplName) return
  try {
    if (!await flushTab() || !await flushTpl()) return
    if (!docProject) return await expServer('zip', {})
    const project = docProject
    const response = await fetch(`/api/projects/${project}/export-zip`)
    if (!response.ok) throw new Error(expMsg(await response.text()))
    dlBlob(await response.blob(), (projects.find(p => p.id === project)?.title || 'project') + '.zip')
  } catch (e) { toast(e.message) }
}
