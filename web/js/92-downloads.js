// downloads: source as .typ, preview as PDF; 2C: server options (standard/pages/ppi) with client fallback
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
  const q = new URLSearchParams({ format: fmt })
  if (o.std && o.std !== 'none') q.set('pdf_standard', o.std)
  if (o.pages) q.set('pages', o.pages)
  if (o.ppi) q.set('ppi', String(o.ppi))
  const r = await fetch('/api/docs/' + docId + '/export?' + q, { method: 'POST' })
  if (!r.ok) throw new Error(expMsg(await r.text()))
  dlBlob(new Blob([await r.blob()], { type: r.headers.get('content-type') || 'application/octet-stream' }), expName(r.headers.get('content-disposition'), dlName('.' + fmt)))
}
function expMsg(raw) { // {"detail": "..."} or {"detail": {"message": ...}} -> readable line
  try {
    const d = JSON.parse(raw).detail
    return String((d && d.message) || d || raw).slice(0, 160)
  } catch (e) { return raw.slice(0, 160) }
}
function dlPngClient() { // page currently in view, straight from canvas (no compiler API needed)
  if (!docId) return
  const cs = [...document.querySelectorAll('#preview canvas')]
  if (!cs.length) { toast(t('downloads.noRender'), () => $('dlPng').click()); return }
  const pr = $('preview').getBoundingClientRect()
  let c = cs[0], best = -Infinity
  for (const x of cs) { const r = x.getBoundingClientRect(), vis = Math.min(r.bottom, pr.bottom) - Math.max(r.top, pr.top); if (vis > best) { best = vis; c = x } }
  const n = cs.indexOf(c) + 1
  c.toBlob(b => {
    if (!b) { toast(t('downloads.pngError'), () => $('dlPng').click()); return }
    dlBlob(b, dlName(cs.length > 1 ? '-p' + n + '.png' : '.png'))
    if (cs.length > 1) toast(t('downloads.pngPage', { n, total: cs.length }))
  })
}
async function dlSvgClient() {
  if (!docId) return
  if (!typstReady()) { ensureTypst().catch(() => {}); toast(t('downloads.compilerLoading'), () => $('dlSvg').click()); return }
  try {
    if (!$typst.svg) throw new Error(t('downloads.svgUnknown'))
    await shadowAll(activeFile ? shadow : getT())
    const svg = (await $typst.svg({ mainFilePath: '/main.typ' }))
      .replace(/&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)/g, '&amp;') // raw & (text/CSV/URL) breaks XML
    dlBlob(new Blob([svg], { type: 'image/svg+xml' }), dlName('.svg'))
  } catch (e) { toast(t('downloads.svgError', { msg: e.message })) }
}
async function dlPdfClient() {
  if (!docId) return
  if (!typstReady()) { ensureTypst().catch(() => {}); toast(t('downloads.compilerLoading'), () => $('dlPdf').click()); return }
  try {
    await shadowAll(activeFile ? shadow : getT()) // same shadows as preview: images/templates land in PDF
    dlBlob(new Blob([await $typst.pdf({ mainFilePath: '/main.typ' })], { type: 'application/pdf' }), dlName('.pdf'))
  } catch (e) { toast(t('downloads.pdfError', { msg: e.message })) }
}
function openExportDlg(fmt) { // options dialog: server compile, client fallback on plain settings
  if (!docId) return
  if (askRes) askRes(null)
  const prev = document.activeElement
  const ov = $('modal'); ov.style.display = 'flex'; modalInert(true)
  $('mHead').textContent = t('downloads.expTitle')
  const inp = $('mInp'); inp.style.display = 'none'
  const row = document.querySelector('#mCard .mRow'); row.style.display = ''
  const yes = $('mYes'); yes.textContent = t('downloads.expGo'); yes.style.background = ''; yes.style.color = ''; yes.disabled = false
  const box = document.createElement('div'); box.id = 'mExtra'
  let std = 'none', ppi = 0, pages = ''
  const lbFor = (key, id) => { const lb = el('label', null, t(key)); lb.htmlFor = id; box.appendChild(lb) }
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
    box.appendChild(sel)
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
    box.appendChild(sel)
  }
  lbFor('downloads.expPages', 'expPages')
  const pg = document.createElement('input')
  pg.id = 'expPages'
  pg.type = 'text'; pg.placeholder = t('downloads.expPagesPh'); pg.setAttribute('aria-label', t('downloads.expPages')); pg.maxLength = 40
  pg.oninput = () => { pages = pg.value.trim() }
  box.appendChild(pg)
  box.appendChild(el('p', 'sub', t('downloads.expServerNote')))
  $('mCard').insertBefore(box, row)
  const done = () => { ov.style.display = 'none'; modalInert(false); box.remove(); askRes = null; prev?.focus?.() }
  askRes = done
  $('mNo').onclick = done
  const fallback = { pdf: dlPdfClient, png: dlPngClient, svg: dlSvgClient }[fmt]
  yes.onclick = async () => {
    if ((fmt !== 'pdf' || std === 'none') && !ppi && !pages) { done(); fallback(); return } // plain: instant client path, no server round-trip
    yes.disabled = true
    try {
      await expServer(fmt, { std, pages, ppi })
      done()
    } catch (e) { toast(t('downloads.expServerFail', { msg: e.message }), () => yes.onclick()); yes.disabled = false }
  }
  setTimeout(() => yes.focus(), 30)
}
$('dlPng').onclick = () => openExportDlg('png')
$('dlSvg').onclick = () => openExportDlg('svg')
$('dlTyp').onclick = () => {
  if (!docId && !tplName) return
  dlBlob(new Blob([getT()], { type: 'text/plain;charset=utf-8' }), activeFile || dlName('.typ')) // file tab: this file
}
$('dlPdf').onclick = () => openExportDlg('pdf')
setInterval(() => { // heals sets without input event (extensions, autofill): textarea -> Y.Text
  if (docId && ytext && docRole !== 'reviewer' && !activeFile && getT() !== shadow) {
  pushLocal(); queueRender(); queueSave()
  }
}, SAVE_MS)
