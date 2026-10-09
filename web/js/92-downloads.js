// downloads: source as .typ, preview as PDF
const dlName = ext => (($('title').textContent || t('downloads.untitled')).replace(/[^\p{L}\p{N}._-]+/gu, '_')) + ext // unicode names kept, rest _
const dlBlob = (blob, name) => {
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob); a.download = name; a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 5000)
}
$('dlPng').onclick = () => { // page currently in view, straight from canvas (no compiler API needed)
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
$('dlSvg').onclick = async () => {
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
$('dlTyp').onclick = () => {
  if (!docId && !tplName) return
  dlBlob(new Blob([getT()], { type: 'text/plain;charset=utf-8' }), activeFile || dlName('.typ')) // file tab: this file
}
$('dlPdf').onclick = async () => {
  if (!docId) return
  if (!typstReady()) { ensureTypst().catch(() => {}); toast(t('downloads.compilerLoading'), () => $('dlPdf').click()); return }
  try {
    await shadowAll(activeFile ? shadow : getT()) // same shadows as preview: images/templates land in PDF
    dlBlob(new Blob([await $typst.pdf({ mainFilePath: '/main.typ' })], { type: 'application/pdf' }), dlName('.pdf'))
  } catch (e) { toast(t('downloads.pdfError', { msg: e.message })) }
}
setInterval(() => { // heals sets without input event (extensions, autofill): textarea -> Y.Text
  if (docId && ytext && docRole !== 'reviewer' && !activeFile && getT() !== shadow) {
  pushLocal(changes, oldLen); queueRender(); queueSave()
  }
}, SAVE_MS)
