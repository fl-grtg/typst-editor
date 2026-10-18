// --- Docs ---
let folders = [], lastOwn = [], lastShared = [], hits = [], findQ = '', findT = 0, wantPos = -1
let shut = new Set() // collapsed folders (doc: name, tpl: "tpl:..", shared: "share:..")
try { shut = new Set(JSON.parse(localStorage.getItem('typst_shut') || '[]')) } catch (e) {}
const saveShut = () => lsSet('typst_shut', JSON.stringify([...shut]))
let secShut = new Set() // collapsed sidebar sections (header IDs)
try { secShut = new Set(JSON.parse(localStorage.getItem('typst_sec') || '[]')) } catch (e) {}
const saveSec = () => lsSet('typst_sec', JSON.stringify([...secShut]))
const SECS = [['ownH', 'own', 'docs.secDocs', 'doc'], ['tplH', 'tpls', 'docs.secFiles', 'resource'], ['libH', 'libs', 'docs.secLibraries', 'library'], ['tblH', 'tbls', 'docs.secTables', 'table'], ['sharedH', 'shared', 'docs.secShared'], ['olH', 'ol', 'docs.secOutline']]
function paintSecs() { // all sections collapsible, + creates folder directly
  for (const [h, box, labelKey, plus] of SECS) {
    const H = $(h), B = $(box)
    if (!H || !B) continue
    if (['libH', 'tblH'].includes(h)) { H.hidden = true; B.hidden = true; continue }
    H.replaceChildren()
    const togSec = () => { secShut.has(h) ? secShut.delete(h) : secShut.add(h); saveSec(); paintSecs() }
    const l = el('span', 'lbl', t(labelKey))
    l.title = t('docs.expandCollapse')
    l.onclick = togSec
    kb(H, togSec) // h3 is the button (Enter/Space), aria-expanded see below
    H.appendChild(l)
    if (plus) {
      const p = icoBtn('mini', ICO_PLUS); p.title = plus === 'doc' ? t('shell.newDoc') : t('templates.newResource', { kind: resLabel(plus) }); p.setAttribute('aria-label', p.title)
      p.onclick = e => { e.stopPropagation(); plus === 'doc' ? $('new').click() : newResource(plus) }
      H.appendChild(p)

    }
    B.style.display = secShut.has(h) ? 'none' : ''
    H.setAttribute('aria-expanded', String(!secShut.has(h)))
    if (h === 'tplH') sidebarDropTarget($('moduleDrop'), 'modules')
    if (h === 'ownH') { sidebarDropTarget(H, 'documents'); sidebarDropTarget(B, 'documents') }
  }
  updNavFade() // content height changed
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
    es.addEventListener('sidebar', () => { if (!user) { if (sideES === es) sideES = null; return es.close() } sideResourcesDirty = true; queueSidebar() })
    es.addEventListener('comment', e => { if (e.data === docId) loadComments().catch(() => {}) })
    es.addEventListener('member', e => { if (e.data === docId) { loadMembers(); sidebar() } })
    es.addEventListener('file', e => { if (e.data === docId) { filesDirty = true; queueRender(); queueSidebar() } })
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
let sideResourcesDirty = false
let projects = []
let sideN = 0
let sidePending = null, sideAgain = false, sideRetry = 0, sideEventTimer = 0
function queueSidebar() {
  clearTimeout(sideEventTimer)
  sideEventTimer = setTimeout(() => sidebar().catch(() => {}), 1000)
}
function sidebar() {
  if (sidePending) { sideAgain = true; return sidePending }
  sidePending = refreshSidebar().finally(() => {
    sidePending = null
    if (sideAgain) { sideAgain = false; clearTimeout(sideRetry); sideRetry = setTimeout(() => sidebar(), 1200) }
  })
  return sidePending
}
async function refreshSidebar() {
  const id = ++sideN
  let d
  try {
    d = await api('GET', '/api/docs')
    if (id !== sideN) return
    const pr = await api('GET', '/api/projects')
    if (id !== sideN) return
    projects = pr.projects
    paintSuggestionControls()
    if (id !== sideN) return
  }
  catch (e) {
    if (id !== sideN) return
    if (/401|logged|Login/i.test(e.message)) { location.reload(); return }
    if (navigator.onLine === false) return // quiet: offline bar shows it, 'online' event refreshes
    if (e.status === 429) { clearTimeout(sideRetry); sideRetry = setTimeout(() => sidebar(), 15000) }
    return // keep old list
  }
  if (sideResourcesDirty) { sideResourcesDirty = false; await resSync() }
  lastOwn = d.own; lastShared = d.shared
  if (docId && docRole && ![...d.own, ...d.shared, ...d.trash].some(x => x.id === docId)) closeView()
  refreshDocRole(d)
  paintOwn(); paintTrash(d.trash); paintShared(d.shared); paintSecs(); paintTabs()
  paintTpls()
  const nv = $('nav'); nv.onscroll = updNavFade; updNavFade()
  if (!window.__navFadeArmed) { window.__navFadeArmed = true; addEventListener('resize', updNavFade) } // once: sidebar() runs per SSE push
}
function refreshDocRole(d) {
  if (!docId) return
  const own = d.own.some(x => x.id === docId)
  const row = d.shared.find(x => x.id === docId)
  const role = own ? 'owner' : row?.role
  if (!role || role === docRole) return
  docRole = role
  const ro = openedTrashed || role === 'reviewer'
  cm.dispatch({ effects: editableComp.reconfigure(editMode(window.changeSession ? !window.changeSession.original && !window.changeSession.busy && !window.changeSession.files.get(sessionKey(sessionCurrent()))?.binary && window.changeSession.files.get(sessionKey(sessionCurrent()))?.action !== 'delete' && (!window.changeSession.package || window.changeSession.package.author === user || ['owner', 'editor'].includes(role)) && !openedTrashed : window.suggestionDraft ? !window.suggestionDraft.busy && !openedTrashed : tabCanEdit(activeFile))) })
  $('role').textContent = openedTrashed ? t('docs.trashBadge') : t(({ owner: 'common.roleOwner', editor: 'common.roleEditor', reviewer: 'common.roleReader' })[role])
  $('roBanner').style.display = ro ? '' : 'none'
  for (const id of ['renBtn', 'shareBtn', 'del']) $(id).style.display = role === 'owner' && !openedTrashed ? '' : 'none'
  for (const id of ['imgBtn', 'mediaBtn', 'tplBtn', 'symBtn']) $(id).style.display = openedTrashed ? 'none' : '' // #8: reviewer keeps the media manager (read-only, copy chips only)
  if (openedTrashed) $('mediaBtn').style.display = 'none'
  $('histBtn').style.display = openedTrashed ? 'none' : ''
  $('cNew').style.display = !activeFile && !openedTrashed ? '' : 'none'
  $('colWrap').hidden = ro
  updCNewTip(); hidePops(); refreshHl()
  tabSig = ''; queueTabs(); renderMediaChips(lastFiles)
  if (tabDirty && !tabCanEdit(activeFile)) { $('save').textContent = t('projects.localDraft'); $('save').title = t('projects.readonlyDraft') }
}
function updNavFade() { // bottom fade only while more content below
  const n = $('nav')
  n.classList.toggle('at-end', n.scrollHeight - n.scrollTop - n.clientHeight < 8)
}
function docRow(x, shared, bare) { // row: click opens, duplicate, trash (own), drag into folder
  const div = el('div', 'doc' + (x.id === docId && !activeFile ? ' cur' : ''))
  div.setAttribute('role', 'button')
  div.appendChild(el('span', 't', shared && !bare ? t('docs.sharedRow', { owner: x.owner, title: x.title }) : x.title))
  const roleName = ({ owner: t('common.roleOwner'), editor: t('common.roleEditor'), reviewer: t('common.roleReader') })[x.role] || x.role
  div.title = shared ? t('docs.sharedTitle', { owner: x.owner, title: x.title, role: roleName }) : x.title
  div.onclick = () => openDoc(x.id)
  kb(div, () => openDoc(x.id)) // keyboard: Enter/Space opens
  if (!shared) {
    sidebarDrag(div, { project: x.project_id || '', entry: { kind: 'document', doc_id: x.id, name: x.title } }, 'move')
  }
  if (!bare && (shared ? x.role === 'editor' : true)) { // #8: shared standalone docs can be duplicated by editors too (backend guest_copy)
    const dup = icoBtn('mini', ICO_DUP); dup.title = t('docs.duplicate'); dup.setAttribute('aria-label', dup.title)
    dup.onclick = e => { e.stopPropagation(); if (dup.disabled) return; dup.disabled = true // upBusy pattern: no double doc
      api('POST', `/api/docs/${x.id}/duplicate`).then(r => openDoc(r.id)).catch(e => toast(e.message)).finally(() => dup.disabled = false) } // openDoc repaints list itself
    div.appendChild(dup)
  }
  if (!shared || (x.project_id && (x.role === 'editor' || canStageProjectDelete(x.project_id)))) {
    const del = el('button', 'mini'); del.innerHTML = ICO_TRASH; del.title = t('docs.moveTrash'); del.setAttribute('aria-label', del.title)
    del.onclick = async e => {
      e.stopPropagation()
      if (await stageDocumentDelete(x.id)) return
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
  lastOwn.filter(x => !x.project_id).forEach(x => box.appendChild(docRow(x)))
  paintProjects(box, false)
  if (!box.hasChildNodes()) box.appendChild(el('div', 'empty', t('docs.noDocs')))
}
function paintShared(list) { // one folder per person; one file = user/file like VSCode
  const box = $('shared'); box.replaceChildren()
  const byO = new Map()
  ;[...list].filter(x => !x.project_id || !projects.some(p => p.id === x.project_id)).sort((a, b) => a.title.localeCompare(b.title, undefined, { numeric: true, sensitivity: 'base' })).forEach(x => { if (!byO.has(x.owner)) byO.set(x.owner, []); byO.get(x.owner).push(x) })
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
  paintProjects(box, true)
  if (!box.hasChildNodes()) box.appendChild(el('div', 'empty', t('docs.noShared')))
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
  sidebarDropTarget($('trashDrop'), 'trash')
  $('trash').style.display = secShut.has('trashH') ? 'none' : ''
  if (!trash.length) { $('trash').replaceChildren(); $('trash').appendChild(el('div', 'empty', t('docs.trashEmpty'))); return }
  const empty = el('button', 'mini trashClear', t('docs.emptyTrashBtn')); empty.title = t('docs.emptyTrashTitle'); empty.setAttribute('aria-label', empty.title)
  empty.onclick = async e => {
    e.stopPropagation()
    if (!await ask(trash.length === 1 ? t('docs.emptyTrashConfirmOne') : t('docs.emptyTrashConfirmMany', { n: trash.length }), { noInput: true, ok: t('common.delete'), danger: true })) return
    if (empty.disabled) return
    empty.disabled = true
    try {
      const result = await api('DELETE', '/api/trash')
      if (result.documents.includes(docId)) closeView()
      await sidebar()
    } catch (e) { toast(e.message) }
    finally { empty.disabled = false }
  }
  h.appendChild(empty)
  const box = $('trash'); box.replaceChildren()
  box.style.display = secShut.has('trashH') ? 'none' : ''
  trash.forEach(x => {
    const div = el('div', 'doc sub' + (x.id === docId && !activeFile ? ' cur' : ''))
    div.setAttribute('role', 'button')
    div.appendChild(el('span', 't', x.title))
    div.title = x.title + t('docs.trashViewSuffix')
    const isEntry = x.kind === 'personal' || x.kind === 'resource' || x.kind === 'file'
    sidebarDrag(div, { trashed: true, trashId: isEntry ? x.id : '', project: x.project_id || '', entry: { kind: x.kind || 'document', doc_id: x.doc_id || x.id, name: x.title } }, 'move')
    if (!isEntry) { div.onclick = () => openDoc(x.id); kb(div, () => openDoc(x.id)) }
    const back = icoBtn('mini', ICO_UNDO); back.title = t('docs.restore'); back.setAttribute('aria-label', back.title)
    back.onclick = e => { e.stopPropagation(); api('POST', trashEntryUrl(x) + '/restore').then(() => { sidebar(); if (!isEntry && x.id === docId) openDoc(x.id) }).catch(e => toast(e.message)) }
    const kill = icoBtn('mini', ICO_X); kill.title = t('docs.delPermBtn'); kill.setAttribute('aria-label', kill.title)
    kill.onclick = async e => {
      e.stopPropagation()
      if (!await ask(t('docs.delPermConfirm', { title: x.title }), { noInput: true, ok: t('common.delete'), danger: true })) return
      try { await api('DELETE', trashEntryUrl(x)) } catch (err) { toast(err.message); return }
      if (x.id === docId) closeView()
      sidebar()
    }
    div.append(back, kill); box.appendChild(div)
  })
}
$('q').oninput = () => { clearTimeout(findT); findT = setTimeout(runSearch, SEARCH_MS) }
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
function resRow(tpl) { // click opens in editor, drag sorts into folder (all three resource kinds share this row)
  const div = document.createElement('div')
  div.className = 'doc private-module sub' + (tpl.name === tplName ? ' cur' : '')
  div.setAttribute('role', 'button')
  div.appendChild(el('span', 't', tpl.name)); div.title = tpl.name
  div.onclick = () => openTpl(tpl.name)
  kb(div, () => openTpl(tpl.name))
  sidebarDrag(div, { personal: true, entry: { kind: 'resource', name: tpl.name } }, 'copyMove')
  projectAction(div, ICO_SEND, t('projects.pullProject'), () => pullPersonalResource(tpl.name))
  projectAction(div, ICO_EDIT, t('templates.renameTpl'), () => renamePersonalResource(tpl.name))
  projectAction(div, ICO_DUP, t('docs.duplicate'), () => duplicatePersonalResource(tpl.name))
  const del = el('button', 'mini'); del.innerHTML = ICO_TRASH; del.title = t('templates.delRes'); del.setAttribute('aria-label', del.title)
  del.onclick = async e => {
    e.stopPropagation()
    if (!await ask(t('templates.delResConfirm', { name: tpl.name }), { noInput: true, ok: t('common.delete'), danger: true })) return
    try { await api('DELETE', '/api/templates/' + encodeURIComponent(tpl.name)) } catch (err) { toast(err.message); return }
    if (tpl.name === tplName) { clearTimeout(tplT); tplDirty = false; closeView(); $('viewSeg').style.display = '' } // open resource gone: no zombie save, back to empty
    await loadTpl(); sidebar()
  }
  div.appendChild(del)
  compactSidebarActions(div)
  return div
}
function paintKind(boxId, kind, emptyKey, key) { // one resource section (.typ/.bib/.csv) from the shared myTpl shelf
  const box = $(boxId); if (!box) return
  box.replaceChildren()
  resOf(kind).forEach(t => box.appendChild(resRow(t)))
  if (!box.hasChildNodes()) box.appendChild(el('div', 'empty', t(emptyKey))) // create via + New above (type + folder step)
}
function paintTpls() { // templates + libraries + tables sections: click opens in editor
  paintKind('tpls', 'resource', 'templates.noTpls', 'tpl:')
  paintKind('libs', 'library', 'templates.noLibs', 'lib:')
  paintKind('tbls', 'table', 'templates.noTbls', 'tbl:')
}
let tplName = '' // resource in editor (no doc): preview n/a, no read mode
let tplDirty = false, tplVer = '', tplOpenN = 0, tplSaving = null // dirty text, base version and save in flight
const tplCached = name => myTpl.find(x => x.name === name)
const resourceStashKey = name => 'typst-resource-draft-' + user + '-' + encodeURIComponent(name)
async function flushTpl() {
  if (window.changeSession) return true // persist a dirty resource before a view switch; false = stay put, edits preserved
  if (tplSaving) { const ok = await tplSaving; if (!ok) return false }
  if (!tplName || !tplDirty) { clearTimeout(tplT); return true }
  clearTimeout(tplT)
  if (navigator.onLine === false) { $('save').textContent = t('docs.offlineRetry'); return false }
  const key = tplName, text = getT(), epoch = tplOpenN
  tplSaving = (async () => {
  try {
    const r = await api('POST', '/api/templates', { name: key, content: text, ...(tplVer ? { version: tplVer } : {}) })
    if (key !== tplName || epoch !== tplOpenN) return false
    if (r && r.version) { tplVer = r.version; const cc = tplCached(key); if (cc) { cc.content = text; cc.updated_at = r.version } }
    if (getT() !== text) { queueTplSave(); return false }
    tplDirty = false
    try { localStorage.removeItem(resourceStashKey(key)) } catch (e) {}
    $('save').textContent = t('docs.saved') + wc()
    loadTpl()
    return true
  } catch (e) {
    if (key !== tplName) return false
    if (e.status === 409) toast(t('templates.saveConflict'), () => loadTheirs(key), t('templates.loadTheirs'))
    else toast(t('templates.saveFail', { msg: e.message }), () => flushTpl(), t('common.retry'))
    $('save').textContent = navigator.onLine === false ? t('docs.offlineRetry') : t('docs.saveError', { msg: e.message })
    return false
  }
  })()
  try { return await tplSaving } finally { tplSaving = null }
}
async function loadTheirs(key) { // conflict escape: take the server text into the editor
  try {
    const r = await api('GET', '/api/templates/' + encodeURIComponent(key))
    if (key !== tplName) return
    tplVer = r.version || ''
    const cc = tplCached(key); if (cc) { cc.content = r.content || ''; cc.updated_at = tplVer }
    try { localStorage.removeItem(resourceStashKey(key)) } catch (e) {}
    tplDirty = false; setT(r.content || ''); $('save').textContent = t('docs.saved') + wc(); paintTpls()
  } catch (e) { toast(e.message) }
}
async function resSync() { // SSE follow-up: fresh list first, open resource follows only when clean (dirty editors never wiped)
  try { await loadTpl(); if (docProject) await loadDocResources(true) } catch (e) {}
  if (!tplName) return
  const cc = tplCached(tplName)
  if (!cc) return
  if (!tplDirty) {
    tplVer = cc.updated_at || tplVer
    if ((cc.content || '') !== getT()) { setT(cc.content || ''); $('save').textContent = t('docs.saved') + wc() }
  }
}
function leaveDoc() { // reset sync/peers/threads/media (openTpl/openDoc/del)
  try { if (docId && ytext && docRole !== 'reviewer' && !openedTrashed && (!wsLive() || !synced)) { const c = ytext.toString(); if (c) lsSet('typst-pending-' + docId, JSON.stringify({ t: Date.now(), c })) } } catch (e) {} // offline/unsynced main: Yjs dies with the provider, stash offers restore on reopen (openDoc drops it silently if converged)
  if (window.suggestionDraft && !stopSuggestionDraft(false)) stopSuggestionDraft()
  ++renderN; ++tabSeq; clearTimeout(renderT); clearTimeout(syncT)
  pvObs?.disconnect(); pvObs = null; pvSlots = []; pvTexts = []; pvTextDone = []; pvPageSize = null
  if (window.Present?.isOn()) window.Present.exit()
  window.docTpl = []; docResAt = 0
  wantPos = -1 // old search jump must not fire in next doc
  openedTrashed = false
  clearTimeout(saveT); clearTimeout(tplT); clearTimeout(anchorT); anchorDirty.clear() // no zombie save into next doc
  clearTimeout(connT); connT = 0 // stale disconnect paint must not fire in the next doc
  if (activeFile && docId && tabDirty) { // pending file/template save: take along silently (keepalive)
    clearTimeout(fileT)
    const rq = tabReq(activeFile, getT())
    fetch(rq.url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(rq.body), keepalive: true }).catch(() => {})
  }
  cmpWarns = []; cmpDiags = []; errKey = ''; errLines = []; tabDirty = false; tabPins = new Set(); tabState.clear(); tabVersions.clear(); tabSig = ''; clearTimeout(tabT)
  prov?.destroy(); ydoc?.destroy(); prov = ydoc = ytext = null
  const wd = $('wsDot'); if (wd) { wd.style.background = '#8e8e93'; wd.title = t('docs.offline') }; const wt0 = $('wsTxt'); if (wt0) wt0.textContent = t('docs.offline')
  threads = []; members = []; lastC = ''; marks = new Set(); syncPage = 0 // do not carry click page into next doc
  docProject = ''; docResReadonly = true
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
  if (window.suggestionDraft && !await leaveSuggestionDraft()) return
  const n = ++openN
  if (!(await flushTpl())) return // dirty resource first: failed save keeps the old view, edits preserved
  if (n !== openN || !await flushTab(true) || n !== openN) return
  const tpl = tplCached(name)
  if (!tpl) return
  ++tplOpenN
  autoCloseDrawer()
  leaveDoc()
  docId = ''; tplName = name; docRole = ''
  tplVer = tpl.updated_at || ''; tplDirty = false
  hidePops()
  setView('split') // segment hidden: reset view, else editonly sticks
  $('title').textContent = name; $('title').classList.remove('is-empty')
  $('tools').style.display = ''; $('pvTools').style.display = 'none'
  const low = tpl.name.toLowerCase()
  $('role').textContent = low.endsWith('.bib') ? t('templates.roleLibrary') : /\.(csv|tsv)$/.test(low) ? t('templates.roleTable') : low.endsWith('.typ') ? t('templates.roleLabel') : t('docs.secFiles')
  $('role').onclick = null; $('role').style.cursor = ''; $('role').title = ''; $('roBanner').style.display = 'none'; $('renBtn').style.display = ''
  $('viewSeg').style.display = 'none'; $('cNew').style.display = 'none'
  $('shareBtn').style.display = 'none'; $('imgBtn').style.display = 'none'; $('mediaBtn').style.display = 'none'
  $('del').style.display = ''; $('dlPdf').style.display = 'none'; $('dlPng').style.display = 'none'; $('dlSvg').style.display = 'none'; $('dlZip').style.display = 'none' // template: delete yes, export no
  $('dlTyp').style.display = ''; $('tplBtn').style.display = ''
  $('histBtn').style.display = 'none'; $('symBtn').style.display = ''; $('colWrap').hidden = false
  paintSuggestionControls()
  cm.dispatch({ effects: editableComp.reconfigure(editMode(true)) })
  gutter()
  setT(tpl.content)
  try {
    const draft = JSON.parse(localStorage.getItem(resourceStashKey(name)) || 'null')
    if (draft && typeof draft.c === 'string' && draft.c !== getT() && Date.now() - draft.t < 86400000) {
      toast(t('docs.stashFound'), () => { if (tplName === name) { setT(draft.c); queueTplSave() } }, t('docs.restore'), 15000)
    }
  } catch (e) {}
  paintOutline() // clear old outline from previous doc (templates have none)
  $('preview').innerHTML = '<p class="empty">' + t('templates.previewNa') + '</p>'
  $('save').style.display = '' // template: save feedback back (dots stay hidden, no sync)
  for (const s of ['wsDot', 'wsTxt']) $(s).style.display = 'none' // template: no live sync dots by design
  $('save').textContent = ''
  sidebar()
}
function queueTplSave() {
  clearTimeout(tplT)
  if (!tplName) return
  tplDirty = true
  $('save').textContent = t(navigator.onLine === false ? 'docs.offlineRetry' : 'docs.saving')
  try { localStorage.setItem(resourceStashKey(tplName), JSON.stringify({ c: getT(), t: Date.now() })) } catch (e) {}
  const key = tplName
  tplT = setTimeout(() => { if (key === tplName) flushTpl() }, SAVE_MS)
}
addEventListener('online', () => { if (tplName && tplDirty) flushTpl() })
let openN = 0, synced = false // sync state ready? Else no empty save to DB (Fix #2)
function wsLive() { return !!(prov && prov.wsconnected) } // Yjs carries main.typ; REST autosave would only 409
let connT = 0 // debounced disconnect paint: brief flaps stay invisible, no flicker
function paintConn() { // one status: Live / Offline (browser) / Getrennt (WS down); #save stays with queueSave/saveNow
  connT = 0
  const dot = $('wsDot'), wt = $('wsTxt'), sv = $('save')
  if (!dot || !wt || !docId || tplName || openedTrashed) return
  const off = navigator.onLine === false, live = wsLive()
  const key = off ? 'docs.offline' : live ? 'docs.live' : 'docs.disconnected'
  dot.style.background = live ? '#30d158' : '#8e8e93'; dot.title = t(key)
  wt.textContent = t(key) // #wsTxt has role=status: announced once, not per keystroke
  dot.classList.toggle('is-off', !live); wt.classList.toggle('is-off', !live)
  if (sv && live && (!sv.textContent || sv.textContent === t('docs.offlineRetry'))) sv.textContent = t('docs.saved') + wc() // back from offline: Yjs already converged, drop the stale retry note quietly
}
function updConn() { // calm: live/offline paint at once, getrennt after 1200ms grace (reconnect inside cancels it)
  paintSuggestionControls()
  clearTimeout(connT); connT = 0
  if (wsLive() || navigator.onLine === false) { paintConn(); return }
  connT = setTimeout(paintConn, 1200)
}
let openedTrashed = false // trash view: read yes, write no
async function restoreOpen() { // click Trash: restore to life, then connect live
  const id = docId
  try { await api('POST', `/api/docs/${id}/restore`, {}) } catch (e) { toast(e.message); return }
  openDoc(id)
}
function closeView() { // no doc open: buttons off, empty view in
  ++openN; ++tplOpenN
  if (tplName && tplDirty) { // view gone by definition: keepalive carries the bytes, failure surfaces as a toast
    clearTimeout(tplT); tplDirty = false
    try {
      fetch('/api/templates', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: tplName, content: getT(), ...(tplVer ? { version: tplVer } : {}) }),
        keepalive: true }).catch(() => toast(t('docs.offlineRetry')))
    } catch (e) { toast(t('docs.offlineRetry')) }
  }
  leaveDoc()
  docId = ''; tplName = ''; lastC = ''; docTitle = ''; paintSuggestionControls()
  for (const b of ['shareBtn', 'histBtn', 'symBtn', 'imgBtn', 'mediaBtn', 'tplBtn', 'del', 'renBtn', 'dlTyp', 'dlPdf', 'dlPng', 'dlSvg', 'dlZip', 'cNew']) $(b).style.display = 'none'; $('colWrap').hidden = true
  for (const s of ['wsDot', 'wsTxt', 'save']) $(s).style.display = 'none' // no doc: no status blobs
  cm.dispatch({ effects: editableComp.reconfigure(editMode(false)) }) // no doc: read-only
  hidePops()
  $('title').textContent = t('docs.welcome'); $('title').classList.add('is-empty'); $('role').textContent = ''; $('role').onclick = null; $('role').title = ''
  $('roBanner').style.display = 'none'
  $('tools').style.display = 'none'; $('pvTools').style.display = 'none'
  paintEmpty()
  setT(''); gutter(); paintOutline()
}
async function openDoc(id) {
  if (window.suggestionDraft && !await leaveSuggestionDraft()) return
  const n = ++openN, wp = wantPos // keep search jump across leaveDoc (see docRow search)
  if (!(await flushTpl())) return // dirty resource first: failed save keeps the old view, edits preserved
  if (n !== openN || !await flushTab(true) || n !== openN) return
  let d
  try { d = await api('GET', `/api/docs/${id}`) }
  catch (e) { toast(e.message); sidebar(); return }
  if (n !== openN) return // stale: newer openDoc already running
  if (tplDirty || tabDirty) return // input while loading: keep the unsaved buffer
  autoCloseDrawer()
  leaveDoc()
  wantPos = wp
  if (tplName) setView('split')
  hidePops()
  docId = id; docRole = d.role; tplName = ''; docProject = d.project_id || ''
  openedTrashed = !!d.trashed
  if (docProject && !openedTrashed) shut.delete('project:' + docProject)
  const ro = d.role === 'reviewer' || openedTrashed // trash: read yes, write no
  $('title').textContent = d.title; $('title').classList.remove('is-empty'); docTitle = d.title
  $('tools').style.display = ''; $('pvTools').style.display = ''
  $('renBtn').style.display = d.role === 'owner' && !openedTrashed ? '' : 'none'
  $('viewSeg').style.display = ''; $('cNew').style.display = openedTrashed ? 'none' : ''
  const rl = $('role')
  rl.textContent = openedTrashed ? t('docs.trashBadge') : ({ owner: t('common.roleOwner'), editor: t('common.roleEditor'), reviewer: t('common.roleReader') })[d.role] || d.role
  rl.title = openedTrashed ? t('docs.clickRestore') : ''
  rl.style.cursor = openedTrashed ? 'pointer' : ''
  rl.onclick = openedTrashed ? restoreOpen : null
  $('roBanner').style.display = ro ? '' : 'none'
  updCNewTip()
  $('del').style.display = !ro ? '' : 'none'
  $('del').title = openedTrashed ? t('docs.delPermBtn') : t('docs.moveTrash')
  $('del').setAttribute('aria-label', $('del').title)
  lastC = ''; synced = false
  cm.dispatch({ effects: editableComp.reconfigure(editMode(!ro)) })
  $('shareBtn').style.display = d.role === 'owner' && !openedTrashed ? '' : 'none'
  for (const s of ['wsDot', 'wsTxt', 'save']) $(s).style.display = '' // doc open: status back
  $('histBtn').style.display = openedTrashed ? 'none' : '' // project history is readable from every file
  $('imgBtn').style.display = ro ? 'none' : ''
  $('mediaBtn').style.display = openedTrashed ? 'none' : '' // #8: reviewer keeps the media manager (read-only, copy chips only)
  $('tplBtn').style.display = ro ? 'none' : ''
  $('symBtn').style.display = ro ? 'none' : ''
  $('colWrap').hidden = ro
  paintSuggestionControls()
  $('dlTyp').style.display = ''; $('dlPdf').style.display = ''; $('dlPng').style.display = ''; $('dlSvg').style.display = ''; $('dlZip').style.display = ''
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
    pp.on('status', () => { if (prov === pp) updConn() }); pp.on('connection-close', () => { if (prov === pp) updConn() }); pp.on('connection-error', () => { if (prov === pp) updConn() })
    pp.on('synced', s => { if (s !== true || prov !== pp) return; synced = true; if (prov === pp) { updConn(); if (threads.length && threads.some(x => x.a == null)) { reanchor(); loadComments().catch(() => {}) } } }) // re-hoist (Round5 High #1): WS sync can beat the comments GET, so an already-synced doc must re-run the range pass; loadComments skips the dedupe-render but still repaints missing ranges (only a real sync opens the gates; the vendor emits synced [false] on disconnect, and a destroyed old provider must not)
    updConn()
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
  paintOutline(); paintTabs()
  const fileDoc = docId
  api('GET', `/api/docs/${id}/files`).then(r => { if (fileDoc === docId && n === openN) { lastFiles = r.files; paintTabs() } }).catch(console.warn)
  sidebar(); loadComments().catch(e => console.warn('comments failed', e)); loadMembers()
  if (!d.project_id && d.role !== 'owner') noteSharedRes(id)
}
let sharedNoted = new Set() // disclosure once per doc per session: shared compiles use the owner's copies
function noteSharedRes(id) {
  if (sharedNoted.has(id)) return
  api('GET', `/api/docs/${id}/resources`).then(r => {
    if (!r || !r.resources || !Object.keys(r.resources).length || id !== docId) return
    sharedNoted.add(id)
    toast(t('templates.sharedResNote'), null, '', 8000) // paths unchanged: owner's copies compile in
  }).catch(() => {})
}
function queueSave() { // main.typ: Yjs carries every keystroke (offline too: syncs on reconnect); REST would 409 or fork the text, so never autosave main
  if (window.suggestionDraft) return // draft: an unsent suggestion is no saved doc — no autosave status while editing one
  clearTimeout(saveT)
  if (!tplName && !activeFile) {
    if (wsLive() && navigator.onLine !== false) return // live: nothing to do, status stays Live
    $('save').textContent = t('docs.offlineRetry') // calm: #wsTxt already says Offline/Getrennt, Yjs retries on reconnect
    return // no timer: no REST off the sync path (offline queue applied on top of Yjs sync doubled the text)
  }
  $('save').textContent = t('docs.saving')
  saveT = setTimeout(() => saveNow(false, true), SAVE_MS)
}
async function saveNow(force, auto) {
  if (window.changeSession) { if (!auto) await submitChangeSession(); return } // explicit (Ctrl+S/menu) saves at once; autosave passes auto=true and stays quiet on failure
  if (window.suggestionDraft && !auto) { await sendSuggestionDraft(); return }
  clearTimeout(saveT); clearTimeout(tplT)
  if (docId && !tplName && !activeFile && !synced) { saveT = setTimeout(() => saveNow(false, true), SAVE_MS); return } // sync running: retry later instead of '' (Fix #2)
  const saveErr = e => navigator.onLine === false ? t('docs.offlineRetry') : t('docs.saveError', { msg: e.message })
  if (tplName) { await flushTpl(); return } // explicit save: flushTpl carries status + conflict toasts
  if (activeFile && docId) { // file/template tab: save that text, not main
    if (await flushTab()) { $('save').textContent = t('docs.saved') + wc(); queueRender() }
    return
  }
  if (!docId || docRole === 'reviewer' || !ytext) return
  if (!wsLive() || navigator.onLine === false) { $('save').textContent = t('docs.offlineRetry'); return } // Yjs owns main.typ: no REST off the sync path (forked text doubled on reconnect), quiet even when explicit
  if (auto) { if (!window.suggestionDraft) $('save').textContent = t('docs.saved') + wc(); paintConn(); return } // reconnect won the race: Yjs has it, no REST (2E); draft must not claim 'saved'
  try { await api('POST', `/api/docs/${docId}/save`, { content: ytext.toString(), ...(force ? { force: true } : {}) }); $('save').textContent = t('docs.saved') + wc() }
  catch (e) {
    if (e.status === 409 && !force && prov && prov.wsconnected && synced) return saveNow(true, auto) // live: Y state already merges everyone's edits, safe to overwrite
    $('save').textContent = saveErr(e)
    if (auto && (navigator.onLine === false || !wsLive())) return // quiet: status line already says it, no toast spam (2E)
    if (e.status === 409 && !force) toast(t('docs.saveConflict'), () => saveNow(true), t('docs.forceSave'))
    else toast(t('docs.saveFail', { msg: e.message }), () => saveNow(force), t('common.retry'))
  }
}
