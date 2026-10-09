// --- Docs ---
let folders = [], lastOwn = [], lastShared = [], hits = [], findQ = '', findT = 0, wantPos = -1
let shut = new Set() // collapsed folders (doc: name, tpl: "tpl:..", shared: "share:..")
try { shut = new Set(JSON.parse(localStorage.getItem('typst_shut') || '[]')) } catch (e) {}
const saveShut = () => lsSet('typst_shut', JSON.stringify([...shut]))
let secShut = new Set() // collapsed sidebar sections (header IDs)
try { secShut = new Set(JSON.parse(localStorage.getItem('typst_sec') || '[]')) } catch (e) {}
const saveSec = () => lsSet('typst_sec', JSON.stringify([...secShut]))
const SECS = [['ownH', 'own', 'docs.secDocs', 'doc'], ['tplH', 'tpls', 'docs.secTemplates', 'tpl'], ['sharedH', 'shared', 'docs.secShared'], ['olH', 'ol', 'docs.secOutline']]
function paintSecs() { // all sections collapsible, + creates folder directly
  for (const [h, box, labelKey, plus] of SECS) {
    const H = $(h), B = $(box)
    if (!H || !B) continue
    H.replaceChildren()
    const togSec = () => { secShut.has(h) ? secShut.delete(h) : secShut.add(h); saveSec(); paintSecs() }
    const l = el('span', 'lbl', t(labelKey))
    l.title = t('docs.expandCollapse')
    l.onclick = togSec
    kb(H, togSec) // h3 is the button (Enter/Space), aria-expanded see below
    H.appendChild(l)
    if (plus) {
      const p = icoBtn('mini', ICO_PLUS); p.title = plus === 'doc' ? t('docs.newFolderBtn') : t('docs.newTplFolderBtn'); p.setAttribute('aria-label', p.title)
      p.onclick = e => { e.stopPropagation(); plus === 'doc' ? newFolder() : newTplFolder() }
      H.appendChild(p)
    }
    B.style.display = secShut.has(h) ? 'none' : ''
    H.setAttribute('aria-expanded', String(!secShut.has(h)))
  }
  updNavFade() // content height changed
}
async function newFolder() {
  const n = await ask(t('docs.newFolder'), { ph: t('docs.namePh'), maxLen: 40 })
  if (n === null || !n.trim()) return
  try { await api('POST', '/api/folders', { folder: n.trim() }); sidebar() } catch (e) { toast(e.message) }
}
async function newTplFolder() {
  const n = await ask(t('docs.newTplFolder'), { ph: t('docs.namePh'), maxLen: 40 })
  if (n === null || !n.trim()) return
  try { await api('POST', '/api/tplfolders', { folder: n.trim() }); await loadTpl(); paintSecs() } catch (e) { toast(e.message) }
}
function jumpWant() { // jump to search hit (once after open)
  if (wantPos < 0) return
  const p = Math.max(0, Math.min(cm.state.doc.length, wantPos))
  wantPos = -1
  cm.dispatch({ selection: { anchor: p }, effects: EditorView.scrollIntoView(p, { y: 'center' }) })
}
let sideES = null, sideESErr = 0, sideESRearms = 0, sideESTimer = 0
function watchSidebar() { // live sidebar: external list changes (MCP, other tab) repaint without reload
  try {
    if (sideES) sideES.close()
    clearTimeout(sideESTimer)
    sideESErr = 0
    const es = sideES = new EventSource('/api/events')
    es.onopen = () => { sideESErr = 0; sideESRearms = 0 } // (re)connect resets counters
    es.addEventListener('sidebar', () => { if (!user) { if (sideES === es) sideES = null; return es.close() } sidebar().catch(() => {}) })
    es.onerror = () => {
      if (es !== sideES) return // superseded stream: ignore
      if (++sideESErr > 3) {
        es.close(); if (sideES === es) sideES = null
        if (sideESRearms++ < 3) sideESTimer = setTimeout(watchSidebar, 15000 * (sideESRearms + 1)) // capped backoff re-arm: 15/30/45s
      }
    }
  } catch (e) { console.warn('watchSidebar', e) }
}
if (!window.__sideArmed) { window.__sideArmed = true; addEventListener('online', () => { watchSidebar(); sidebar().catch(() => {}) }) } // sleep/offline: re-arm stream + catch up
let sideN = 0
async function sidebar() {
  const id = ++sideN
  let d
  try {
    d = await api('GET', '/api/docs')
    if (id !== sideN) return
    folders = (await api('GET', '/api/folders')).folders
    if (id !== sideN) return
  }
  catch (e) {
    if (id !== sideN) return
    if (/401|logged|Login/i.test(e.message)) { location.reload(); return }
    if (e.status === 429 || navigator.onLine === false) toast(t('docs.sidebarRefreshFail', { msg: e.message }), () => sidebar(), t('common.retry'))
    return // offline etc: keep old list
  }
  lastOwn = d.own; lastShared = d.shared
  paintOwn(); paintTrash(d.trash); paintShared(d.shared); paintSecs()
  paintTpls()
  const nv = $('nav'); nv.onscroll = updNavFade; updNavFade()
  if (!window.__navFadeArmed) { window.__navFadeArmed = true; addEventListener('resize', updNavFade) } // once: sidebar() runs per SSE push
}
function updNavFade() { // bottom fade only while more content below
  const n = $('nav')
  n.classList.toggle('at-end', n.scrollHeight - n.scrollTop - n.clientHeight < 8)
}
function docRow(x, shared, bare) { // row: click opens, duplicate, trash (own), drag into folder
  const div = el('div', 'doc' + (x.id === docId ? ' cur' : ''))
  div.setAttribute('role', 'button')
  div.appendChild(el('span', 't', shared && !bare ? t('docs.sharedRow', { owner: x.owner, title: x.title }) : x.title))
  const roleName = ({ owner: t('common.roleOwner'), editor: t('common.roleEditor'), reviewer: t('common.roleReader') })[x.role] || x.role
  div.title = shared ? t('docs.sharedTitle', { owner: x.owner, title: x.title, role: roleName }) : x.title
  div.onclick = () => openDoc(x.id)
  kb(div, () => openDoc(x.id)) // keyboard: Enter/Space opens
  if (!shared) {
    div.draggable = true
    div.ondragstart = e => e.dataTransfer.setData('text/plain', x.id)
    const dup = icoBtn('mini', ICO_DUP); dup.title = t('docs.duplicate'); dup.setAttribute('aria-label', dup.title)
    dup.onclick = e => { e.stopPropagation(); if (dup.disabled) return; dup.disabled = true // upBusy pattern: no double doc
      api('POST', `/api/docs/${x.id}/duplicate`).then(r => openDoc(r.id)).catch(e => toast(e.message)).finally(() => dup.disabled = false) } // openDoc repaints list itself
    div.appendChild(dup)
    const del = el('button', 'mini'); del.innerHTML = ICO_TRASH; del.title = t('docs.moveTrash'); del.setAttribute('aria-label', del.title)
    del.onclick = async e => {
      e.stopPropagation()
      if (!await ask(t('docs.moveTrashConfirm', { title: x.title }), { noInput: true, ok: t('common.ok') })) return
      try { await api('DELETE', `/api/docs/${x.id}`) } catch (err) { toast(err.message); return }
      if (x.id === docId) closeView()
      sidebar()
    }
    div.appendChild(del)
  }
  return div
}
function paintOwn() { // top-level first, then folders (A-Z); search replaces list
  const box = $('own'); box.replaceChildren()
  const qc = $('qCount')
  if (findQ.length >= 2) {
    if (qc) qc.textContent = t('docs.results', { n: hits.length })
    if (!hits.length) {
      const e = el('div', 'empty', t('docs.noHits'))
      const b = el('button', null, t('docs.clearSearch'))
      b.onclick = () => { $('q').value = ''; findQ = ''; hits = []; if (qc) qc.textContent = ''; paintOwn() }
      e.appendChild(b); box.appendChild(e)
    }
    hits.forEach(h => {
      const div = el('div', 'doc')
      div.setAttribute('role', 'button')
      div.appendChild(el('span', 't', h.title))
      div.title = (h.folder ? h.folder + '/' : '') + (h.snippet || t('docs.titleHit'))
      const openH = () => { wantPos = h.pos; $('q').value = ''; findQ = ''; if (qc) qc.textContent = ''; openDoc(h.id) }
      div.onclick = openH
      kb(div, openH)
      box.appendChild(div)
    })
    return
  }
  if (qc) qc.textContent = ''
  const byF = new Map()
  lastOwn.forEach(x => {
    if (!x.folder) box.appendChild(docRow(x))
    else { if (!byF.has(x.folder)) byF.set(x.folder, []); byF.get(x.folder).push(x) }
  })
  folders.forEach(f => { if (!byF.has(f.folder)) byF.set(f.folder, []) }) // show empty folders
  ;[...byF.keys()].sort((a, b) => a.localeCompare(b)).forEach(f => paintFolder(box, f, byF.get(f)))
  if (!box.hasChildNodes()) box.appendChild(el('div', 'empty', t('docs.noDocs')))
}
function paintShared(list) { // one folder per person; one file = user/file like VSCode
  const box = $('shared'); box.replaceChildren()
  const byO = new Map()
  list.forEach(x => { if (!byO.has(x.owner)) byO.set(x.owner, []); byO.get(x.owner).push(x) })
  ;[...byO.keys()].sort((a, b) => a.localeCompare(b)).forEach(o => {
    const docs = byO.get(o)
    if (docs.length === 1) { box.appendChild(docRow(docs[0], true)); return }
    const h = el('div', 'fhd'), k = 'share:' + o
    const hd = el('b', null, o)
    hd.title = t('docs.expandCollapse')
    hd.setAttribute('role', 'button'); hd.setAttribute('aria-expanded', String(!shut.has(k))); hd.setAttribute('aria-label', o + (shut.has(k) ? t('docs.isCollapsed') : t('docs.isExpanded')))
    const togS = () => { shut.has(k) ? shut.delete(k) : shut.add(k); saveShut(); paintShared(lastShared) }
    hd.onclick = togS
    kb(hd, togS)
    h.appendChild(hd); box.appendChild(h)
    if (!shut.has(k)) docs.forEach(x => { const r = docRow(x, true, true); r.classList.add('sub'); box.appendChild(r) })
  })
  if (!box.hasChildNodes()) box.appendChild(el('div', 'empty', t('docs.noShared')))
}
function paintFolder(box, f, docs) { // header: click collapses, rename, dissolve; drop sorts in
  const h = el('div', 'fhd')
  const hd = el('b', null, f)
  hd.title = t('docs.expandCollapse')
  hd.setAttribute('role', 'button'); hd.setAttribute('aria-expanded', String(!shut.has(f))); hd.setAttribute('aria-label', f + (shut.has(f) ? t('docs.isCollapsed') : t('docs.isExpanded')))
  const tog = () => {
    shut.has(f) ? shut.delete(f) : shut.add(f)
    saveShut()
    paintOwn()
  }
  hd.onclick = tog
  kb(hd, tog)
  const rn = icoBtn('mini', ICO_EDIT); rn.title = t('docs.renameFolder'); rn.setAttribute('aria-label', rn.title)
  rn.onclick = async e => {
    e.stopPropagation()
    const n = await ask(t('docs.renameFolder'), { value: f, maxLen: 40 })
    if (n === null || !n.trim() || n.trim() === f) return
    api('POST', '/api/folders/rename', { old: f, new: n.trim() }).then(sidebar).catch(e => toast(e.message))
  }
  const x = icoBtn('mini', ICO_X); x.title = t('docs.dissolveDocs'); x.setAttribute('aria-label', x.title)
  x.onclick = async e => {
    e.stopPropagation()
    if (await ask(t('docs.dissolveConfirm', { f }), { noInput: true, ok: t('common.ok') }))
      api('DELETE', '/api/folders/' + encodeURIComponent(f)).then(sidebar).catch(e => toast(e.message))
  }
  h.append(hd, rn, x)
  h.ondragover = e => e.preventDefault()
  h.ondrop = e => {
    e.preventDefault()
    const id = e.dataTransfer.getData('text/plain')
    if (!id || id.startsWith('tpl:')) return // templates belong in template folders
    api('POST', `/api/docs/${id}/folder`, { folder: f }).then(sidebar).catch(e => toast(e.message))
  }
  box.appendChild(h)
  if (!shut.has(f)) docs.forEach(x => { const r = docRow(x); r.classList.add('sub'); box.appendChild(r) })
}
function paintTrash(trash) { // click peeks in (trash view), restore, delete permanently
  const h = $('trashH')
  h.replaceChildren()
  const togTrash = () => { secShut.has('trashH') ? secShut.delete('trashH') : secShut.add('trashH'); saveSec(); paintTrash(trash) }
  const l = el('span', 'lbl', t('docs.trashSec'))
  l.title = t('docs.expandCollapse')
  l.onclick = togTrash
  kb(h, togTrash)
  h.setAttribute('aria-expanded', String(!secShut.has('trashH')))
  h.appendChild(l)
  $('trash').style.display = secShut.has('trashH') ? 'none' : ''
  if (!trash.length) { $('trash').replaceChildren(); $('trash').appendChild(el('div', 'empty', t('docs.trashEmpty'))); return }
  const empty = el('button', 'mini', t('docs.emptyTrashBtn')); empty.title = t('docs.emptyTrashTitle'); empty.setAttribute('aria-label', empty.title)
  empty.onclick = async () => {
    if (!await ask(trash.length === 1 ? t('docs.emptyTrashConfirmOne') : t('docs.emptyTrashConfirmMany', { n: trash.length }), { noInput: true, ok: t('common.delete'), danger: true })) return
    const errs = []
    for (const x of trash) { try { await api('DELETE', `/api/docs/${x.id}`) } catch (e) { errs.push(x.title + ': ' + e.message) } } // no break: try all
    if (errs.length) toast(errs.join('\n'))
    if (trash.some(x => x.id === docId)) closeView()
    sidebar()
  }
  h.appendChild(empty)
  const box = $('trash'); box.replaceChildren()
  box.style.display = secShut.has('trashH') ? 'none' : ''
  trash.forEach(x => {
    const div = el('div', 'doc' + (x.id === docId ? ' cur' : ''))
    div.setAttribute('role', 'button')
    div.appendChild(el('span', 't', x.title))
    div.title = x.title + t('docs.trashViewSuffix')
    div.onclick = () => openDoc(x.id)
    kb(div, () => openDoc(x.id))
    const back = icoBtn('mini', ICO_UNDO); back.title = t('docs.restore'); back.setAttribute('aria-label', back.title)
    back.onclick = e => { e.stopPropagation(); api('POST', `/api/docs/${x.id}/restore`).then(sidebar).catch(e => toast(e.message)) }
    const kill = icoBtn('mini', ICO_X); kill.title = t('docs.delPermBtn'); kill.setAttribute('aria-label', kill.title)
    kill.onclick = async e => {
      e.stopPropagation()
      if (!await ask(t('docs.delPermConfirm', { title: x.title }), { noInput: true, ok: t('common.delete'), danger: true })) return
      try { await api('DELETE', `/api/docs/${x.id}`) } catch (err) { toast(err.message); return }
      if (x.id === docId) closeView()
      sidebar()
    }
    div.append(back, kill); box.appendChild(div)
  })
}
$('q').oninput = () => { clearTimeout(findT); findT = setTimeout(runSearch, SEARCH_MS) }
$('ownH').ondragover = e => e.preventDefault()
$('ownH').ondrop = e => { // drop on Documents = move out of folder
  e.preventDefault()
  const id = e.dataTransfer.getData('text/plain')
  if (!id || id.startsWith('tpl:')) return
  api('POST', `/api/docs/${id}/folder`, { folder: '' }).then(sidebar).catch(e => toast(e.message))
}
$('tplH').ondragover = e => e.preventDefault()
$('tplH').ondrop = e => { // drop on Templates = move out of folder
  e.preventDefault()
  const id = e.dataTransfer.getData('text/plain')
  if (!id || !id.startsWith('tpl:')) return
  api('POST', '/api/templates/' + encodeURIComponent(id.slice(4)) + '/folder', { folder: '' })
    .then(() => { loadTpl() }).catch(e => toast(e.message))
}
let searchN = 0
async function runSearch() {
  findQ = $('q').value.trim()
  if (findQ.length < 2) { hits = []; paintOwn(); return }
  const n = ++searchN
  try { hits = (await api('GET', '/api/search?q=' + encodeURIComponent(findQ))).hits }
  catch (e) { hits = [] }
  if (n !== searchN) return // stale: newer search already running
  paintOwn()
}
function tplRow(tpl) { // click opens in editor, drag sorts into folder
  const div = document.createElement('div')
  div.className = 'doc' + (tpl.name === tplName ? ' cur' : '')
  div.setAttribute('role', 'button')
  div.appendChild(el('span', 't', tpl.name)); div.title = tpl.name
  div.onclick = () => openTpl(tpl.name)
  kb(div, () => openTpl(tpl.name))
  div.draggable = true
  div.ondragstart = e => e.dataTransfer.setData('text/plain', 'tpl:' + tpl.name)
  const dup = icoBtn('mini', ICO_DUP); dup.title = t('docs.duplicate'); dup.setAttribute('aria-label', dup.title)
  dup.onclick = async e => {
    e.stopPropagation()
    const n = await ask(t('templates.dupTpl'), { value: tpl.name })
    if (n === null || !n.trim()) return
    let nn = n.trim().replace(/\.typ$/i, '.typ')
    if (!nn.endsWith('.typ')) nn += '.typ'
    nn = nn.split(/[/\\]/).pop().replace(/[^A-Za-z0-9._-]/g, '_').replace(/^\.+/, '').slice(0, 100) // like backend: check matches exactly
    await loadTpl() // fresh: else upsert would silently overwrite
    const src = myTpl.find(x => x.name === tpl.name) || tpl // no stale closure: state after reload
    if (myTpl.some(x => x.name === nn)) { toast(t('common.nameExists')); return }
    try { await api('POST', '/api/templates', { name: nn, content: src.content, folder: src.folder || '' }); await loadTpl(); sidebar() }
    catch (err) { toast(err.message) }
  }
  div.appendChild(dup)
  const del = el('button', 'mini'); del.innerHTML = ICO_TRASH; del.title = t('templates.delTpl'); del.setAttribute('aria-label', del.title)
  del.onclick = async e => {
    e.stopPropagation()
    if (!await ask(t('templates.delTplConfirm', { name: tpl.name }), { noInput: true, ok: t('common.delete'), danger: true })) return
    try { await api('DELETE', '/api/templates/' + encodeURIComponent(tpl.name)) } catch (err) { toast(err.message); return }
    if (tpl.name === tplName) { clearTimeout(tplT); closeView(); $('viewSeg').style.display = '' } // open template gone: no zombie save, back to empty
    await loadTpl(); sidebar()
  }
  div.appendChild(del)
  return div
}
function paintTplFolder(box, f, docs) { // like paintFolder, for templates only
  const h = el('div', 'fhd'), k = 'tpl:' + f
  const hd = el('b', null, f)
  hd.title = t('docs.expandCollapse')
  hd.setAttribute('role', 'button'); hd.setAttribute('aria-expanded', String(!shut.has(k))); hd.setAttribute('aria-label', f + (shut.has(k) ? t('docs.isCollapsed') : t('docs.isExpanded')))
  const togT = () => { shut.has(k) ? shut.delete(k) : shut.add(k); saveShut(); paintTpls() }
  hd.onclick = togT
  kb(hd, togT)
  const rn = icoBtn('mini', ICO_EDIT); rn.title = t('docs.renameFolder'); rn.setAttribute('aria-label', rn.title)
  rn.onclick = async e => {
    e.stopPropagation()
    const n = await ask(t('docs.renameFolder'), { value: f, maxLen: 40 })
    if (n === null || !n.trim() || n.trim() === f) return
    api('POST', '/api/tplfolders/rename', { old: f, new: n.trim() }).then(loadTpl).catch(e => toast(e.message))
  }
  const x = icoBtn('mini', ICO_X); x.title = t('templates.dissolveTpls'); x.setAttribute('aria-label', x.title)
  x.onclick = async e => {
    e.stopPropagation()
    if (await ask(t('docs.dissolveConfirm', { f }), { noInput: true, ok: t('common.ok') }))
      api('DELETE', '/api/tplfolders/' + encodeURIComponent(f)).then(loadTpl).catch(e => toast(e.message))
  }
  h.append(hd, rn, x)
  h.ondragover = e => e.preventDefault()
  h.ondrop = e => {
    e.preventDefault()
    const id = e.dataTransfer.getData('text/plain')
    if (!id || !id.startsWith('tpl:')) return
    api('POST', '/api/templates/' + encodeURIComponent(id.slice(4)) + '/folder', { folder: f })
      .then(loadTpl).catch(e => toast(e.message))
  }
  box.appendChild(h)
  if (!shut.has(k)) docs.forEach(t => { const r = tplRow(t); r.classList.add('sub'); box.appendChild(r) })
}
function paintTpls() { // templates section: click opens in editor
  const box = $('tpls'); if (!box) return
  box.replaceChildren()
  const { top, byF } = groupBy(myTpl)
  top.forEach(t => box.appendChild(tplRow(t)))
  tplFolders.forEach(f => { if (!byF.has(f.folder)) byF.set(f.folder, []) })
  ;[...byF.keys()].sort((a, b) => a.localeCompare(b)).forEach(f => paintTplFolder(box, f, byF.get(f)))
  if (!box.hasChildNodes()) box.appendChild(el('div', 'empty', t('templates.noTpls'))) // create via + New above (type + folder step)
}
let tplName = '' // template in editor (no doc): preview n/a, no read mode
function leaveDoc() { // reset sync/peers/threads/media (openTpl/openDoc/del)
  wantPos = -1 // old search jump must not fire in next doc
  openedTrashed = false
  clearTimeout(saveT); clearTimeout(tplT); clearTimeout(anchorT); anchorDirty.clear() // no zombie save into next doc
  if (activeFile && docId) { // pending file save: take along silently (keepalive)
    clearTimeout(fileT)
    fetch(`/api/docs/${docId}/files/${encodeURIComponent(activeFile)}/text`, { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content: getT() }),
      keepalive: true }).catch(() => {})
  }
  prov?.destroy(); ydoc?.destroy(); prov = ydoc = ytext = null
  const wd = $('wsDot'); if (wd) { wd.style.background = '#8e8e93'; wd.title = t('docs.offline') }; const wt0 = $('wsTxt'); if (wt0) wt0.textContent = t('docs.offline')
  threads = []; marks = new Set(); syncPage = 0 // do not carry click page into next doc
  activeFile = ''; clearTimeout(fileT); bibKeys = [] // tabs closed (see paintTabs)
  $('tabs').style.display = 'none'
  fileCache.clear(); mediaNames = []; lastMedia = ''; lastFiles = []; mediaOpen = false
  filesDirty = true; filesAt = 0; shadowSig = ''; lastPres = ''; lastErrToast = '' // next doc: fresh list + full shadow remap + presence
  $('media').style.display = 'none'; closePop()
  cm.dispatch({ effects: setPeer.of(RangeSet.of([])) })
  $('peers').replaceChildren()
  $('cBadge').style.display = 'none'
  const eb = $('eBadge'); if (eb) eb.style.display = 'none'
}
async function openTpl(name) {
  const t = myTpl.find(x => x.name === name)
  if (!t) return
  autoCloseDrawer()
  leaveDoc()
  docId = ''; tplName = name; docRole = ''
  hidePops()
  setView('split') // segment hidden: reset view, else editonly sticks
  $('title').textContent = name; $('title').classList.remove('is-empty')
  $('tools').style.display = ''; $('pvTools').style.display = ''
  $('role').textContent = t('templates.roleLabel'); $('role').onclick = null; $('role').style.cursor = ''; $('role').title = ''; $('roBanner').style.display = 'none'; $('renBtn').style.display = ''
  $('viewSeg').style.display = 'none'; $('cNew').style.display = 'none'
  $('shareBtn').style.display = 'none'; $('imgBtn').style.display = 'none'; $('mediaBtn').style.display = 'none'
  $('del').style.display = ''; $('dlPdf').style.display = 'none'; $('dlPng').style.display = 'none'; $('dlSvg').style.display = 'none' // template: delete yes, export no
  $('dlTyp').style.display = ''; $('tplBtn').style.display = ''
  $('histBtn').style.display = 'none'; $('symBtn').style.display = ''; $('colWrap').hidden = false
  cm.dispatch({ effects: editableComp.reconfigure(EditorView.editable.of(true)) })
  gutter()
  setT(t.content)
  paintOutline() // clear old outline from previous doc (templates have none)
  $('preview').innerHTML = '<p class="empty">' + t('templates.previewNa') + '</p>'
  $('save').style.display = '' // template: save feedback back (dots stay hidden, no sync)
  for (const s of ['wsDot', 'wsTxt']) $(s).style.display = 'none' // template: no live sync dots by design
  $('save').textContent = ''
  sidebar()
}
function queueTplSave() {
  clearTimeout(tplT)
  $('save').textContent = '…'
  tplT = setTimeout(async () => {
    try { await api('POST', '/api/templates', { name: tplName, content: getT() }); $('save').textContent = t('docs.saved') + wc(); loadTpl() }
    catch (e) { $('save').textContent = navigator.onLine === false ? t('docs.offlineRetry') : t('docs.saveError', { msg: e.message }); toast(t('templates.saveFail', { msg: e.message }), () => queueTplSave(), t('common.retry')) }
  }, SAVE_MS)
}
let openN = 0, synced = false // sync state ready? Else no empty save to DB (Fix #2)
let openedTrashed = false // trash view: read yes, write no
async function restoreOpen() { // click Trash: restore to life, then connect live
  const id = docId
  try { await api('POST', `/api/docs/${id}/restore`, {}) } catch (e) { toast(e.message); return }
  openDoc(id)
}
function closeView() { // no doc open: buttons off, empty view in
  leaveDoc()
  docId = ''; tplName = ''; lastC = ''
  for (const b of ['shareBtn', 'histBtn', 'symBtn', 'imgBtn', 'mediaBtn', 'tplBtn', 'del', 'renBtn', 'dlTyp', 'dlPdf', 'dlPng', 'dlSvg', 'cNew']) $(b).style.display = 'none'; $('colWrap').hidden = true
  for (const s of ['wsDot', 'wsTxt', 'save']) $(s).style.display = 'none' // no doc: no status blobs
  cm.dispatch({ effects: editableComp.reconfigure(EditorView.editable.of(false)) }) // no doc: read-only
  hidePops()
  $('title').textContent = t('docs.welcome'); $('title').classList.add('is-empty'); $('role').textContent = ''; $('role').onclick = null; $('role').title = ''
  $('roBanner').style.display = 'none'
  $('tools').style.display = 'none'; $('pvTools').style.display = 'none'
  paintEmpty()
  setT(''); gutter(); paintOutline()
}
async function openDoc(id) {
  const n = ++openN, wp = wantPos // keep search jump across leaveDoc (see docRow search)
  autoCloseDrawer()
  leaveDoc()
  wantPos = wp
  if (tplName) setView('split') // only back from template: view was gone, else keep mode
  hidePops()
  let d
  try { d = await api('GET', `/api/docs/${id}`) }
  catch (e) { toast(e.message); sidebar(); return }
  if (n !== openN) return // stale: newer openDoc already running
  docId = id; docRole = d.role; tplName = ''
  openedTrashed = !!d.trashed
  const ro = d.role === 'reviewer' || openedTrashed // trash: read yes, write no
  $('title').textContent = d.title; $('title').classList.remove('is-empty')
  $('tools').style.display = ''; $('pvTools').style.display = ''
  $('renBtn').style.display = d.role === 'owner' && !openedTrashed ? '' : 'none'
  $('viewSeg').style.display = ''; $('cNew').style.display = ro ? 'none' : ''
  const rl = $('role')
  rl.textContent = openedTrashed ? t('docs.trashBadge') : ({ owner: t('common.roleOwner'), editor: t('common.roleEditor'), reviewer: t('common.roleReader') })[d.role] || d.role
  rl.title = openedTrashed ? t('docs.clickRestore') : ''
  rl.style.cursor = openedTrashed ? 'pointer' : ''
  rl.onclick = openedTrashed ? restoreOpen : null
  $('roBanner').style.display = ro ? '' : 'none'
  updCNewTip()
  $('del').style.display = d.role === 'owner' ? '' : 'none'
  $('del').title = openedTrashed ? t('docs.delPermBtn') : t('docs.moveTrash')
  $('del').setAttribute('aria-label', $('del').title)
  lastC = ''; synced = false
  cm.dispatch({ effects: editableComp.reconfigure(EditorView.editable.of(!ro)) })
  $('shareBtn').style.display = d.role === 'owner' && !openedTrashed ? '' : 'none'
  for (const s of ['wsDot', 'wsTxt', 'save']) $(s).style.display = '' // doc open: status back
  $('histBtn').style.display = ro ? 'none' : '' // history writes: reviewer/trash excluded
  $('imgBtn').style.display = ro ? 'none' : ''
  $('mediaBtn').style.display = ro ? 'none' : ''
  $('tplBtn').style.display = ro ? 'none' : ''
  $('symBtn').style.display = ro ? 'none' : ''
  $('colWrap').hidden = ro
  $('dlTyp').style.display = ''; $('dlPdf').style.display = ''; $('dlPng').style.display = ''; $('dlSvg').style.display = ''
  hidePops()
  $('leftCol').style.width = clampSplit(parseFloat($('leftCol').style.width) || 50) + '%'
  shares = d.shares
  setT(''); shadow = ''
  if (!openedTrashed) {
    const yy = new Y.Doc(), yt = yy.getText('typst') // start empty, server state arrives via sync
    const wsProto = location.protocol === 'https:' ? 'wss' : 'ws'
    const pp = new WebsocketProvider(`${wsProto}://${location.host}/ws`, id, yy, {}) // cookie is primary (HttpOnly); no ?token= in log
    if (n !== openN) { pp.destroy(); yy.destroy(); return } // superseded meanwhile
    ydoc = yy; ytext = yt; prov = pp
    ytext.observe((e, tx) => { if (tx.origin !== 'local') pullRemote(e) }) // only real remote updates touch editor (delta = exact changes)
    prov.awareness.on('change', renderPeers)
    const updWs = () => {
      const on = pp.wsconnected
      const dot = $('wsDot'); if (dot) { dot.style.background = on ? '#30d158' : '#8e8e93'; dot.title = on ? t('docs.live') : t('docs.offline') }; const wt = $('wsTxt'); if (wt) wt.textContent = on ? t('docs.live') : t('docs.offline') // dot aria-hidden: text in #wsTxt (role=status) announces
    }
    pp.on('status', updWs); pp.on('connection-close', updWs); pp.on('connection-error', updWs)
    pp.on('synced', () => { synced = true }) // initial handshake done: save may persist (also when doc stays empty)
    updWs()
    pushPresence()
  } else {
    setT(d.content || ''); shadow = d.content || ''; synced = true // no Yjs in trash: state from DB
  }
  try { // pagehide backup: keepalive misses 409, restore stashed edits here
    let pend = null; const raw = localStorage.getItem('typst-pending-' + id)
    if (raw) {
      try {
        const o = JSON.parse(raw)
        pend = (o && typeof o.c === 'string' && Date.now() - (o.t || 0) <= 24 * 60 * 60 * 1000) ? o.c : null
      } catch (e) { pend = raw } // legacy plain text
      if (pend === null) localStorage.removeItem('typst-pending-' + id)
    }
    if (pend !== null && pend !== (d.content || '') && !openedTrashed && docRole !== 'reviewer') {
      const iv = setInterval(() => { // wait for live sync, then restore stashed stand
        if (n !== openN || synced) {
          clearInterval(iv)
          if (n !== openN || !ytext) return
          if (!synced || pend === ytext.toString()) { localStorage.removeItem('typst-pending-' + id); return } // live WS sync already has it
          toast(t('docs.stashFound'), () => { // opt-in: others may have edited since, never overwrite silently
            if (n !== openN || !ytext) return
            localStorage.removeItem('typst-pending-' + id)
            setYText(pend); setT(pend); shadow = pend; queueSave(); queueRender(); paintOutline()
            toast(t('docs.stashRestored'))
          }, t('docs.restore'), 15000)
          setTimeout(() => { if (n === openN) localStorage.removeItem('typst-pending-' + id) }, 15000) // ignored: drop the stash
        }
      }, 400)
      setTimeout(() => clearInterval(iv), 15000)
    } else if (raw) localStorage.removeItem('typst-pending-' + id)
  } catch (e) {}
  gutter()
  $('preview').innerHTML = '<p class="empty" role="status" aria-busy="true"><span class="spin"></span>' + t('docs.preparing') + '</p>' // no stale empty text during first render
  queueRender()
  paintOutline()
  sidebar(); loadComments().catch(e => console.warn('comments failed', e)); loadMembers()
}
function queueSave() {
  clearTimeout(saveT)
  $('save').textContent = '…'
  saveT = setTimeout(saveNow, SAVE_MS)
}
async function saveNow(force) { // Ctrl+S: at once, no autosave wait; force = overwrite on 409 conflict
  clearTimeout(saveT); clearTimeout(tplT)
  if (docId && !tplName && !activeFile && !synced) { saveT = setTimeout(saveNow, SAVE_MS); return } // sync running: retry later instead of '' (Fix #2)
  const saveErr = e => navigator.onLine === false ? t('docs.offlineRetry') : t('docs.saveError', { msg: e.message })
  if (tplName) {
    try { await api('POST', '/api/templates', { name: tplName, content: getT() }); $('save').textContent = t('docs.saved') + wc() }
    catch (e) { $('save').textContent = saveErr(e); toast(t('templates.saveFail', { msg: e.message }), () => saveNow(), t('common.retry')) }
    return
  }
  if (activeFile && docId) { // file tab: save file, not main
    try {
      await api('POST', `/api/docs/${docId}/files/${encodeURIComponent(activeFile)}/text`, { content: getT() })
      fileCache.delete(activeFile)
      $('save').textContent = t('docs.saved') + wc()
      queueRender()
    } catch (e) { $('save').textContent = saveErr(e); toast(t('files.saveFail', { msg: e.message }), () => saveNow(), t('common.retry')) }
    return
  }
  if (!docId || docRole === 'reviewer' || !ytext) return
  try { await api('POST', `/api/docs/${docId}/save`, { content: ytext.toString(), ...(force ? { force: true } : {}) }); $('save').textContent = t('docs.saved') + wc() }
  catch (e) {
    if (e.status === 409 && !force && prov && prov.wsconnected && synced) return saveNow(true) // live: Y state already merges everyone's edits, safe to overwrite
    $('save').textContent = saveErr(e)
    if (e.status === 409 && !force) toast(t('docs.saveConflict'), () => saveNow(true), t('docs.forceSave'))
    else toast(t('docs.saveFail', { msg: e.message }), () => saveNow(force), t('common.retry'))
  }
}
