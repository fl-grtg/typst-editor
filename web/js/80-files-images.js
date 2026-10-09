// --- Images: upload per doc, #image() at cursor, preview knows files ---
let mediaOpen = false, lastMedia = '', lastFiles = [], mediaNames = []
let activeFile = '', fileT = 0, bibKeys = [] // '' = main.typ (Yjs sync), else text file (.typ/.bib/.csv) from manager
function renderMediaChips(files) {
  lastFiles = files
  paintTabs() // tabs follow file list (only on change, see shadowAll)
  const bar = $('media'); bar.replaceChildren()
  if (docRole === 'reviewer' || openedTrashed) { bar.style.display = 'none'; return } // reviewer/trash: no manager
  bar.style.display = mediaOpen ? '' : 'none'
  if (!mediaOpen) return
  const add = el('button', null, '+ Upload')
  add.onclick = () => $('imgPick').click()
  bar.appendChild(add)
  files.forEach(f => {
    const c = el('span', 'chip')
    const n = el('button', 'name', f.name); n.title = 'Insert at cursor'; n.setAttribute('aria-label', 'Insert ' + f.name + ' at cursor')
    n.onclick = () => {
      const m = cm.state.selection.main
      const ins = /\.typ$/i.test(f.name) ? `#include "${f.name}"` : /\.bib$/i.test(f.name) ? `#bibliography("${f.name}")` : `#image("${f.name}", width: 80%)`
      cm.dispatch({ changes: { from: m.from, to: m.to, insert: ins }, selection: { anchor: m.from + ins.length } })
      cm.focus()
    }
    c.appendChild(n)
    c.appendChild(el('span', 'sz', Math.round(f.size / 1024) + ' KB'))
    const x = icoBtn(null, ICO_X); x.title = 'Delete'; x.setAttribute('aria-label', 'Delete ' + f.name)
    x.onclick = () => {
      const cached = fileCache.get(f.name)
      api('DELETE', `/api/docs/${docId}/files/${encodeURIComponent(f.name)}`)
        .then(() => {
          if (f.name === activeFile) switchTab('', true)
          queueRender()
          toast('File deleted', async () => {
            try {
              if (cached && cached.bytes) {
                const fd = new FormData(); fd.append('f', new Blob([cached.bytes]), f.name)
                await fetch(`/api/docs/${docId}/files`, { method: 'POST', body: fd }); filesDirty = true
              } else if (cached) {
                await api('POST', `/api/docs/${docId}/files/${encodeURIComponent(f.name)}/text`, { content: '' })
              }
              queueRender()
            } catch (e) { toast(e.message) }
          }, 'Undo')
        }).catch(e => toast(e.message))
    }
    c.appendChild(x)
    bar.appendChild(c)
  })
}
$('mediaBtn').onclick = () => { mediaOpen = !mediaOpen; renderMediaChips(lastFiles) }
function paintTabs() { // main.typ + text files as tabs, preview stays main
  const bar = $('tabs')
  if (!docId || tplName || openedTrashed) { bar.style.display = 'none'; return } // reviewer sees tabs read-only
  const files = lastFiles.filter(f => /\.(typ|bib|csv)$/i.test(f.name))
  if (!files.length && !activeFile) { bar.style.display = 'none'; return }
  if (activeFile && !files.some(f => f.name === activeFile)) { activeFile = ''; setT(shadow); gutter(); refreshHl() } // deleted: back to main, editor must show main again (else file text leaks into main)
  bar.style.display = ''
  bar.replaceChildren()
  const mk = name => {
    const b = el('button', null, name || 'main.typ')
    if ((name || '') === activeFile) b.classList.add('on')
    b.title = name ? 'Edit ' + name + ' (preview stays main.typ)' : 'Edit main.typ'
    b.onclick = () => switchTab(name)
    bar.appendChild(b)
  }
  mk('')
  files.forEach(f => mk(f.name))
}
async function switchTab(name, nosave) {
  if (name === activeFile || !docId) return
  if (!nosave) await flushTab() // save old state first (delete calls with nosave)
  if (name && !lastFiles.some(f => f.name === name)) { try { lastFiles = (await api('GET', `/api/docs/${docId}/files`)).files } catch (e) {} } // fresh list: new upload must not be dropped as 'deleted'
  activeFile = name
  if (!name) { setT(shadow); paintTabs(); gutter(); closePop(); paintOutline(); reanchor(); refreshHl(); queueRender(); return }
  try {
    setT((await api('GET', `/api/docs/${docId}/files/${encodeURIComponent(name)}/text`)).content)
  } catch (e) { toast(e.message); activeFile = ''; setT(shadow) }
  paintTabs(); gutter(); closePop(); paintOutline()
  cm.dispatch({ effects: setHl.of(RangeSet.of([])) }) // file tab: no main highlights as ghosts
  queueRender()
}
async function flushTab() { // silent save on tab switch (no display text)
  if (!activeFile || !docId || docRole === 'reviewer') return
  try { await api('POST', `/api/docs/${docId}/files/${encodeURIComponent(activeFile)}/text`, { content: getT() }) } catch (e) {}
}
function queueFileSave() { // file tab: only file + preview, no Yjs
  clearTimeout(fileT)
  $('save').textContent = '…' + wc()
  fileT = setTimeout(async () => {
    try {
      await api('POST', `/api/docs/${docId}/files/${encodeURIComponent(activeFile)}/text`, { content: getT() })
      fileCache.delete(activeFile) // bytes stale: next render refetches
      $('save').textContent = 'saved' + wc()
      queueRender()
    } catch (e) { $('save').textContent = navigator.onLine === false ? 'Offline – will retry' : 'Error: ' + e.message; toast('File save failed: ' + e.message, () => queueFileSave(), 'Retry') }
  }, SAVE_MS)
}
let imgIns = false // only via image button, not via manager upload
function insImage(name) { // #image() at cursor
  const m = cm.state.selection.main, ins = `#image("${name}", width: 80%)`
  cm.dispatch({ changes: { from: m.from, to: m.to, insert: ins }, selection: { anchor: m.from + ins.length } })
  cm.focus()
}
async function upFile(f) { // upload, returns name ('' on error)
  const fd = new FormData(); fd.append('f', f)
  const r = await fetch(`/api/docs/${docId}/files`, { method: 'POST', body: fd })
  filesDirty = true
  if (!r.ok) { const d = ((await r.json().catch(() => ({}))).detail || r.statusText); toast('Upload failed: ' + d, () => upFile(f), 'Retry'); return '' }
  return (await r.json()).name
}
const TEXT_UP = /\.(typ|bib|csv)$/i // text file: save + open as tab (no #image)
async function upText(f) { // .typ/.bib/.csv as file text (backend creates, max 200 KB)
  const txt = await f.text()
  if (txt.length > 200 * 1024) { toast('Max 200 KB as text'); return '' }
  const name = f.name.replace(/[^A-Za-z0-9._-]+/g, '_')
  await api('POST', `/api/docs/${docId}/files/${encodeURIComponent(name)}/text`, { content: txt })
  return name
}
$('imgBtn').onclick = () => { imgIns = true; $('imgPick').click() }
$('imgPick').onchange = async () => {
  const f = $('imgPick').files[0]; $('imgPick').value = ''
  if (!f || !docId) return
  try {
    if (TEXT_UP.test(f.name)) { const n = await upText(f); if (n) switchTab(n) }
    else { const name = await upFile(f); if (name && imgIns) insImage(name) }
  } catch (e) { toast(e.message) }
  imgIns = false; queueRender()
}
$('editWrap').addEventListener('dragover', e => e.preventDefault()) // drop on editor = upload like manager
$('editWrap').addEventListener('drop', async e => {
  e.preventDefault()
  if (!docId || docRole === 'reviewer' || !e.dataTransfer.files.length) return
  let last = ''
  for (const f of e.dataTransfer.files) {
    try {
      if (TEXT_UP.test(f.name)) { last = await upText(f) || last; continue }
      const name = await upFile(f)
      if (name && /\.(png|jpe?g|svg|gif|webp|pdf)$/i.test(name)) insImage(name)
    } catch (err) { toast(err.message) }
  }
  if (last) switchTab(last) // text drop: show file at once
  queueRender()
})
cm.contentDOM.addEventListener('paste', async e => { // paste screenshot/image: upload + #image() at cursor
  const imgs = [...((e.clipboardData && e.clipboardData.files) || [])].filter(f => /^image\//.test(f.type))
  if (!imgs.length || !docId || tplName || openedTrashed || docRole === 'reviewer') return
  e.preventDefault()
  toast(imgs.length > 1 ? 'Uploading ' + imgs.length + ' images…' : 'Uploading image…')
  for (const f of imgs) {
    const ext = ((f.type.split('/')[1] || 'png').replace('jpeg', 'jpg').replace(/\+.*$/, '')).toLowerCase()
    const stamp = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14)
    const named = new File([f], (f.name && f.name !== 'image.png' ? f.name.replace(/[^A-Za-z0-9._-]+/g, '_') : `paste-${stamp}-${Math.random().toString(36).slice(2, 6)}.${ext}`), { type: f.type })
    try { const name = await upFile(named); if (name) insImage(name) } catch (err) { toast(err.message) }
  }
  queueRender()
})
addEventListener('keydown', e => { // Esc: modal (ask + askPick via mNo) > pop > find > drawer
  if (e.key !== 'Escape') return
  if ($('modal').style.display !== 'none') { $('mNo').click(); return }
  closePop(); hidePops()
  if (findOpen) closeFind()
  if ($('q').value && document.activeElement === $('q')) { $('q').value = ''; findQ = ''; hits = []; paintOwn(); return }
  if (matchMedia('(max-width:720px)').matches && !document.body.classList.contains('noside')) { document.body.classList.add('noside'); updScrim(); $('navToggle').setAttribute('aria-pressed', 'false'); if ($('side').contains(document.activeElement)) $('navToggle').focus() }
})
