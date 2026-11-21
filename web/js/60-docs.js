// --- Docs ---
let folders = [], lastOwn = [], lastShared = [], lastTrash = [], findQ = '', findT = 0
let contentHits = new Map(), contentHitQ = '', searchN = 0
let searchFold = new Set() // folders collapsed during this search; the saved state stays untouched
const SEARCH_DEFAULTS = Object.freeze({ projects: true, modules: true, shared: true, trash: true, outline: false, content: false })
const SEARCH_FILTER_KEY = 'typst_search_filters'
let searchFilters = (() => {
  let saved = {}
  try { saved = JSON.parse(sessionStorage.getItem(SEARCH_FILTER_KEY) || '{}') || {} } catch (e) {}
  const next = { ...SEARCH_DEFAULTS }
  for (const k of Object.keys(SEARCH_DEFAULTS)) if (typeof saved[k] === 'boolean') next[k] = saved[k]
  return next
})()
const saveSearchFilters = () => { try { sessionStorage.setItem(SEARCH_FILTER_KEY, JSON.stringify(searchFilters)) } catch (e) {} }
const searchOn = () => findQ.length > 0
const searchText = v => String(v || '').toLowerCase()
const searchMatch = (...vals) => { const q = searchText(findQ); return vals.some(v => searchText(v).includes(q)) }
const searchContent = key => searchFilters.content && contentHitQ === findQ ? (contentHits.get(key) || 0) : 0
const searchFindQ = key => searchOn() && searchContent(key) > 0 ? findQ : ''
const searchPending = () => searchOn() && searchFilters.content && contentHitQ !== findQ
function searchFrag(text) { // labels with a <mark> around the query; DOM-built, never innerHTML
  const s = String(text ?? '')
  if (!searchOn() || !findQ) return document.createTextNode(s)
  const hay = s.toLowerCase(), needle = findQ.toLowerCase()
  if (hay.length !== s.length) return document.createTextNode(s) // locale lowercasing changed offsets: keep it plain
  const frag = document.createDocumentFragment()
  let at = 0, hit
  while ((hit = hay.indexOf(needle, at)) >= 0) {
    if (hit > at) frag.appendChild(document.createTextNode(s.slice(at, hit)))
    frag.appendChild(el('mark', 'qhit', s.slice(hit, hit + needle.length)))
    at = hit + needle.length
  }
  if (at < s.length) frag.appendChild(document.createTextNode(s.slice(at)))
  return frag
}
function searchTextEl(cls, text) {
  const span = el('span', cls)
  span.appendChild(searchFrag(text))
  return span
}
function searchHitBadge(row, key) { // content hits are an optional extra: hidden while the toggle is off
  const n = searchContent(key)
  if (!n) return
  const b = el('span', 'hitN', String(n))
  b.title = t('docs.hitCount', { n })
  b.setAttribute('aria-label', b.title)
  const first = row.querySelector('button.mini')
  if (first) row.insertBefore(b, first); else row.appendChild(b)
}
let hitBadgeRaf = 0
function positionHitBadges() { // black hit tabs: fixed to the sidebar edge, centered on their row
  const side = $('side'), nav = $('nav')
  if (!side || !nav) return
  const sr = side.getBoundingClientRect(), nr = nav.getBoundingClientRect()
  const live = $('app').classList.contains('on') && !document.body.classList.contains('noside') &&
    sr.width > 40 && nr.height > 0 && nr.right > 0
  for (const b of document.querySelectorAll('#nav .doc > .hitN')) {
    if (!live || b.getClientRects().length === 0) { b.style.visibility = 'hidden'; continue }
    const rr = b.parentElement.getBoundingClientRect()
    const mid = rr.top + rr.height / 2
    if (!rr.height || mid - 10 < nr.top || mid + 10 > nr.bottom) { b.style.visibility = 'hidden'; continue }
    b.style.left = (sr.right - 1) + 'px'
    b.style.top = mid + 'px'
    b.style.visibility = 'visible'
  }
}
function queueHitBadges() {
  if (hitBadgeRaf) return
  hitBadgeRaf = requestAnimationFrame(() => { hitBadgeRaf = 0; positionHitBadges() })
}
function watchHitBadges() { // repaints, scrolling, resizing and the sidebar drag all move the rows under the tabs
  if (window.__hitBadgesArmed) { queueHitBadges(); return }
  window.__hitBadgesArmed = true
  const nav = $('nav'), side = $('side')
  nav.addEventListener('scroll', queueHitBadges, { passive: true })
  addEventListener('resize', queueHitBadges)
  addEventListener('scroll', queueHitBadges, true)
  if (window.ResizeObserver) {
    const ro = new ResizeObserver(queueHitBadges)
    ro.observe(nav); ro.observe(side)
    window.__hitBadgeRO = ro
  }
  if (window.MutationObserver) {
    new MutationObserver(queueHitBadges).observe(nav, { childList: true, subtree: true, characterData: true })
  }
  queueHitBadges()
}
function searchEmpty() { return el('div', 'empty', t('docs.noHits')) }
function announceSearch() {
  const qc = $('qCount')
  if (!qc) return
  const searching = searchOn()
  const rows = document.querySelectorAll('#nav .doc').length
  const hits = document.querySelectorAll('#nav .doc, #nav .fhd').length // folder/project hits count too
  const areas = Object.keys(SEARCH_DEFAULTS).some(k => searchFilters[k])
  const empty = searching && areas && !hits && !searchPending()
  const se = $('searchEmpty')
  if (se) se.hidden = !empty
  const nav = $('nav')
  if (nav) nav.classList.toggle('search-empty', empty)
  if (!searching) { qc.textContent = ''; return }
  qc.textContent = t('docs.results', { n: rows })
}
function paintSidebarSearch() {
  paintOwn(); paintShared(lastShared); paintTrash(lastTrash); paintTpls(); paintSecs(); paintOutline()
}
function clearSearch(focus = false) {
  const q = $('q')
  q.value = ''
  findQ = ''
  searchFold.clear()
  ++searchN
  contentHits = new Map(); contentHitQ = ''
  $('qClear').hidden = true
  paintSidebarSearch()
  announceSearch()
  if (focus) q.focus()
}
let shut = new Set() // collapsed folders (doc: name, tpl: "tpl:..", shared: "share:..")
try { shut = new Set(JSON.parse(localStorage.getItem('typst_shut') || '[]')) } catch (e) {}
const saveShut = () => lsSet('typst_shut', JSON.stringify([...shut]))
let secShut = new Set() // collapsed sidebar sections (header IDs)
try { secShut = new Set(JSON.parse(localStorage.getItem('typst_sec') || '[]')) } catch (e) {}
const saveSec = () => lsSet('typst_sec', JSON.stringify([...secShut]))
const SECS = [['ownH', 'own', 'docs.secDocs', 'doc'], ['tplH', 'tpls', 'docs.secFiles', 'resource'], ['libH', 'libs', 'docs.secLibraries', 'library'], ['tblH', 'tbls', 'docs.secTables', 'table'], ['sharedH', 'shared', 'docs.secShared'], ['olH', 'ol', 'docs.secOutline']]
const SEARCH_SECS = { ownH: 'projects', tplH: 'modules', sharedH: 'shared', trashH: 'trash', olH: 'outline' }
function paintSecs() { // all sections collapsible, + creates folder directly
  const searching = searchOn()
  const none = searching && !Object.keys(SEARCH_DEFAULTS).some(k => searchFilters[k])
  const noneEl = $('searchNone')
  if (noneEl) noneEl.hidden = !none
  for (const [h, box, labelKey, plus] of SECS) {
    const H = $(h), B = $(box)
    if (!H || !B) continue
    if (['libH', 'tblH'].includes(h)) { H.hidden = true; B.hidden = true; continue }
    const area = SEARCH_SECS[h]
    const visible = !searching || !area || searchFilters[area]
    H.hidden = !visible
    B.hidden = !visible
    if (!visible) continue // filtered-out area: header and rows disappear
    H.replaceChildren()
    const togSec = () => {
      if (searchOn()) searchFold.has(h) ? searchFold.delete(h) : searchFold.add(h)
      else { secShut.has(h) ? secShut.delete(h) : secShut.add(h); saveSec() }
      paintSecs()
    }
    const l = el('span', 'lbl', t(labelKey))
    l.title = t('docs.expandCollapse')
    l.onclick = togSec
    kb(H, togSec) // h3 is the button (Enter/Space), aria-expanded see below
    H.appendChild(l)
    if (plus) {
      const plusTitle = plus === 'doc' ? t('shell.newDoc') : plus === 'resource' ? t('projects.newResource') : t('templates.newResource', { kind: resLabel(plus) })
      const p = icoBtn('mini', ICO_PLUS); p.title = plusTitle; p.setAttribute('aria-label', p.title)
      p.onclick = e => { e.stopPropagation(); plus === 'doc' ? openNewMenu(p) : openNewResourceMenu(p) }
      H.appendChild(p)

    }
    const expanded = searching ? !searchFold.has(h) : !secShut.has(h) // search folds per query without touching saved state
    B.style.display = expanded ? '' : 'none'
    H.setAttribute('aria-expanded', String(expanded))
    if (h === 'tplH') sidebarDropTarget($('moduleDrop'), 'modules')
    if (h === 'ownH') { sidebarDropTarget(H, 'documents'); sidebarDropTarget(B, 'documents') }
  }
  for (const [id, area] of [['moduleDrop', 'modules'], ['trashDrop', 'trash']]) {
    const w = $(id)
    if (w) w.hidden = searching && !searchFilters[area]
  }
  updNavFade() // content height changed
}
let sideES = null, sideESErr = 0, sideESRearms = 0, sideESTimer = 0
function watchSidebar() { // live sidebar: external list changes (MCP, other tab) repaint without reload
  try {
    if (sideES) sideES.close()
    clearTimeout(sideESTimer)
    sideESErr = 0
    const es = sideES = new EventSource('/api/events')
    es.onopen = () => { sideESErr = 0; sideESRearms = 0; if (user) loadInbox().catch(() => {}) } // (re)connect resets counters
    es.addEventListener('sidebar', () => { if (!user) { if (sideES === es) sideES = null; return es.close() } sideResourcesDirty = true; queueSidebar() })
    es.addEventListener('comment', e => { if (e.data === docId) loadComments().catch(() => {}) })
    es.addEventListener('notification', () => { if (user) loadInbox().catch(() => {}) })
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
  if (document.body.classList.contains('dnd-active')) { window.__sidebarDeferred = true; return Promise.resolve() } // repaint would wipe drag state; refresh after the drag
  if (document.querySelector('aside input.renameInput')) { window.__sidebarDeferred = true; return Promise.resolve() } // keep inline rename alive; refresh after it closes
  if (sidePending) { sideAgain = true; return sidePending }
  sidePending = refreshSidebar().finally(() => {
    sidePending = null
    if (sideAgain) { sideAgain = false; clearTimeout(sideRetry); sideRetry = setTimeout(() => sidebar(), 1200) }
  })
  return sidePending
}
async function sidebarFresh() { // after a write: a refresh that was already running may predate it
  if (sidePending) await sidePending
  return sidebar()
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
  if (document.body.classList.contains('dnd-active')) { window.__sidebarDeferred = true; return } // a refresh already in flight must not repaint mid-drag
  lastOwn = d.own; lastShared = d.shared; lastTrash = d.trash
  if (docId && docRole && ![...d.own, ...d.shared, ...d.trash].some(x => x.id === docId)) closeView()
  refreshDocRole(d)
  const held = sideFocusKey() // the repaint replaces the focused row action: keyboard focus moves to the same action of the new row
  paintOwn(); paintTrash(d.trash); paintShared(d.shared); paintSecs(); paintTabs()
  paintTpls()
  if (held && !held.el.isConnected) sideFocusBack(held)
  const nv = $('nav'); nv.onscroll = updNavFade; updNavFade()
  watchHitBadges()
  queueContentRefresh() // list changes (new/moved/trashed entries) change the hit set too
  if (!window.__navFadeArmed) { window.__navFadeArmed = true; addEventListener('resize', updNavFade) } // once: sidebar() runs per SSE push
}
const SIDE_ROW_KEYS = ['docId', 'packageKey', 'resourceName', 'folderPath', 'projectId']
function sideFocusKey() { // focused sidebar row action and the data key of its row (null: focus is elsewhere)
  const el = document.activeElement
  if (!el || !el.closest || !el.closest('aside') || !el.matches('[data-side-menu]')) return null
  for (const k of SIDE_ROW_KEYS) {
    const row = el.closest('[data-' + k.replace(/[A-Z]/g, c => '-' + c.toLowerCase()) + ']')
    if (row) return { el, k, v: row.dataset[k] }
  }
  return null
}
function sideFocusBack(held) {
  const attr = 'data-' + held.k.replace(/[A-Z]/g, c => '-' + c.toLowerCase())
  const row = [...document.querySelectorAll('aside [' + attr + ']')].find(r => r.dataset[held.k] === held.v)
  const btn = row && row.querySelector('[data-side-menu]')
  if (btn && (!document.activeElement || document.activeElement === document.body)) btn.focus({ preventScroll: true })
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
async function moveDocToTrash(x) { // one path for sidebar rows and tab menus: stage in review, else trash
  if (await stageDocumentDelete(x.id)) return
  if (!await ask(t('docs.moveTrashConfirm', { title: x.title }), { noInput: true, ok: t('docs.moveTrash') })) return
  try { await api('DELETE', `/api/docs/${x.id}`) } catch (err) { toast(err.message); return }
  if (x.id === docId) closeView()
  sidebar()
}
function docRow(x, shared, bare) { // row: click opens, duplicate, trash (own), drag into folder
  const div = el('div', 'doc' + (x.id === docId && !activeFile ? ' cur' : ''))
  div.dataset.docId = x.id // stable across sidebar repaints: an open row menu can refocus its new button
  div.setAttribute('role', 'button')
  div.appendChild(searchTextEl('t', shared && !bare ? t('docs.sharedRow', { owner: x.owner, title: x.title }) : x.title))
  const roleName = ({ owner: t('common.roleOwner'), editor: t('common.roleEditor'), reviewer: t('common.roleReader') })[x.role] || x.role
  div.title = shared ? t('docs.sharedTitle', { owner: x.owner, title: x.title, role: roleName }) : x.title
  const open = () => {
    const q = searchFindQ('d:' + x.id)
    return openDoc(x.id).then(() => { if (q && docId === x.id) findWith(q) })
  }
  div.onclick = open
  kb(div, open) // keyboard: Enter/Space opens
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
    const del = el('button', 'mini'); del.innerHTML = ICO_TRASH; del.title = t('docs.moveTrash'); del.setAttribute('aria-label', del.title); del.dataset.menuDanger = ''
    del.onclick = async e => {
      e.stopPropagation()
      await moveDocToTrash(x)
    }
    div.appendChild(del)
  }
  searchHitBadge(div, 'd:' + x.id)
  return div
}
function sidebarRenaming() { // an in-flight or direct repaint must not wipe the inline rename; finish() refreshes after it
  if (!document.querySelector('aside input.renameInput')) return false
  window.__sidebarDeferred = true
  return true
}
function reanchorSideMenu() { // an open row menu moves to the new row instead of hiding its actions
  if (window.reanchorSidebarMenu) window.reanchorSidebarMenu()
}
function paintOwn() { // top-level first, then folders (A-Z); search replaces list
  if (sidebarRenaming()) return
  const box = $('own'); box.replaceChildren()
  if (searchOn()) {
    if (!searchFilters.projects) return
    lastOwn.filter(x => !x.project_id && (searchMatch(x.title) || searchContent('d:' + x.id) > 0)).forEach(x => box.appendChild(docRow(x)))
    paintProjects(box, false)
    if (!box.hasChildNodes() && !searchPending()) box.appendChild(searchEmpty())
    reanchorSideMenu()
    return
  }
  lastOwn.filter(x => !x.project_id).forEach(x => box.appendChild(docRow(x)))
  paintProjects(box, false)
  if (!box.hasChildNodes()) box.appendChild(el('div', 'empty', t('docs.noDocs')))
  reanchorSideMenu()
}
function paintShared(list) { // one folder per person; one file = user/file like VSCode
  if (sidebarRenaming()) return
  const box = $('shared'); box.replaceChildren()
  if (searchOn() && !searchFilters.shared) return
  const searching = searchOn()
  const byO = new Map()
  ;[...list].filter(x => !x.project_id || !projects.some(p => p.id === x.project_id)).forEach(x => { if (!byO.has(x.owner)) byO.set(x.owner, []); byO.get(x.owner).push(x) })
  ;[...byO.keys()].sort((a, b) => a.localeCompare(b)).forEach(o => {
    const all = byO.get(o)
    const ownerHit = searching && searchMatch(o)
    const docs = (searching && !ownerHit ? all.filter(x => searchMatch(x.title) || searchContent('d:' + x.id) > 0) : all)
      .slice().sort((a, b) => a.title.localeCompare(b.title, undefined, { numeric: true, sensitivity: 'base' }))
    if (!docs.length) return
    if (docs.length === 1) { box.appendChild(docRow(docs[0], true)); return }
    const h = el('div', 'fhd'), k = 'share:' + o
    const hd = document.createElement('b')
    hd.appendChild(searchFrag(o))
    hd.title = t('docs.expandCollapse')
    const open = searching ? !searchFold.has(k) : !shut.has(k)
    hd.setAttribute('role', 'button'); hd.setAttribute('aria-expanded', String(open)); hd.setAttribute('aria-label', o + (open ? t('docs.isExpanded') : t('docs.isCollapsed')))
    const togS = () => {
      if (searchOn()) searchFold.has(k) ? searchFold.delete(k) : searchFold.add(k)
      else { shut.has(k) ? shut.delete(k) : shut.add(k); saveShut() }
      paintShared(lastShared)
    }
    hd.onclick = togS
    kb(hd, togS)
    h.appendChild(hd); box.appendChild(h)
    if (open) docs.forEach(x => { const r = docRow(x, true, true); r.classList.add('sub'); box.appendChild(r) })
  })
  if (!searching || searchFilters.shared) paintProjects(box, true)
  if (!box.hasChildNodes() && !searchPending()) box.appendChild(searching ? searchEmpty() : el('div', 'empty', t('docs.noShared')))
  reanchorSideMenu()
}
function paintTrash(trash) { // click peeks in (trash view), restore, delete permanently
  const h = $('trashH')
  const searching = searchOn()
  if (searching && !searchFilters.trash) { $('trash').replaceChildren(); return }
  h.replaceChildren()
  const open = searching ? !searchFold.has('trashH') : !secShut.has('trashH')
  const togTrash = () => {
    if (searchOn()) searchFold.has('trashH') ? searchFold.delete('trashH') : searchFold.add('trashH')
    else { secShut.has('trashH') ? secShut.delete('trashH') : secShut.add('trashH'); saveSec() }
    paintTrash(trash)
  }
  const l = el('span', 'lbl', t('docs.trashSec'))
  l.title = t('docs.expandCollapse')
  l.onclick = togTrash
  kb(h, togTrash)
  h.setAttribute('aria-expanded', String(open))
  h.appendChild(l)
  sidebarDropTarget($('trashDrop'), 'trash')
  $('trash').style.display = open ? '' : 'none'
  const rows = searching ? trash.filter(x => searchMatch(x.title) || searchContent((x.kind ? 'tr:' : 'td:') + x.id) > 0) : trash
  if (!rows.length) {
    $('trash').replaceChildren()
    if (!searchPending()) $('trash').appendChild(searching ? searchEmpty() : el('div', 'empty', t('docs.trashEmpty')))
    return
  }
  const emptyItem = async () => {
    if (!await ask(trash.length === 1 ? t('docs.emptyTrashConfirmOne') : t('docs.emptyTrashConfirmMany', { n: trash.length }), { noInput: true, ok: t('common.delete'), danger: true })) return
    const result = await api('DELETE', '/api/trash')
    if (result.documents.includes(docId)) closeView()
    await sidebar()
  }
  const empty = icoBtn('mini', ICO_MORE) // trash actions live behind the three-dot like every other section row
  empty.title = t('shell.menuMore'); empty.setAttribute('aria-label', empty.title)
  empty.setAttribute('aria-haspopup', 'menu'); empty.setAttribute('aria-expanded', 'false')
  empty.dataset.sideMenu = ''
  empty.sideMenuItems = () => [{
    label: t('docs.emptyTrashItem'), title: t('docs.emptyTrashTitle'), danger: true, run: () => emptyItem().catch(e => toast(e.message)),
  }]
  h.appendChild(empty)
  reanchorSideMenu()
  const box = $('trash'); box.replaceChildren()
  box.style.display = open ? '' : 'none'
  rows.forEach(x => {
    const div = el('div', 'doc sub' + (x.id === docId && !activeFile ? ' cur' : ''))
    div.setAttribute('role', 'button')
    div.appendChild(searchTextEl('t', x.title))
    div.title = x.title + t('docs.trashViewSuffix')
    const isEntry = x.kind === 'personal' || x.kind === 'resource' || x.kind === 'file'
    const hitKey = (isEntry ? 'tr:' : 'td:') + x.id
    sidebarDrag(div, { trashed: true, trashId: isEntry ? x.id : '', project: x.project_id || '', entry: { kind: x.kind || 'document', doc_id: x.doc_id || x.id, name: x.title } }, 'move')
    if (!isEntry) {
      const openTrash = () => {
        const q = searchFindQ(hitKey)
        return openDoc(x.id).then(() => { if (q && docId === x.id) findWith(q) })
      }
      div.onclick = openTrash; kb(div, openTrash)
    }
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
    div.append(back, kill)
    searchHitBadge(div, hitKey)
    box.appendChild(div)
  })
}
$('q').oninput = () => {
  $('qClear').hidden = !$('q').value
  clearTimeout(findT); findT = setTimeout(runSearch, SEARCH_MS)
}
$('q').onkeydown = e => {
  if (e.key !== 'Enter') return
  e.preventDefault(); clearTimeout(findT); runSearch()
}
$('qClear').onclick = () => clearSearch(true)
$('qFilter').onclick = e => {
  e.stopPropagation()
  document.getElementById('searchFilters') ? closeSearchFilters() : openSearchFilters()
}
function searchEntryKey(e) {
  const doc = e.doc_id || ''
  if (e.kind === 'doc') return 'd:' + doc
  if (e.kind === 'trash_doc') return 'td:' + doc
  if (e.kind === 'file') return 'f:' + doc + '/' + e.name
  if (e.kind === 'resource') return 'r:' + (e.project_id || '') + '/' + e.name
  if (e.kind === 'template') return 't:' + e.name
  if (e.kind === 'trash') return 'tr:' + e.id
  return ''
}
async function runSearch() {
  const prevQ = findQ
  findQ = $('q').value.trim()
  if (findQ !== prevQ) searchFold.clear() // a new query starts with every folder open
  $('qClear').hidden = !$('q').value
  const n = ++searchN
  if (!findQ) { contentHits = new Map(); contentHitQ = ''; paintSidebarSearch(); announceSearch(); return }
  paintSidebarSearch(); announceSearch()
  if (!searchFilters.content) {
    if (contentHits.size || contentHitQ) { contentHits = new Map(); contentHitQ = ''; paintSidebarSearch(); announceSearch() }
    return
  }
  try {
    const r = await api('GET', '/api/search/content?q=' + encodeURIComponent(findQ))
    if (n !== searchN) return // stale: newer query or filter already running
    const next = new Map()
    for (const e of r.entries || []) {
      const k = searchEntryKey(e)
      if (k) next.set(k, e.count)
    }
    contentHits = next; contentHitQ = findQ
  } catch (e) {
    if (n !== searchN) return
    contentHits = new Map(); contentHitQ = findQ // a failed lookup is settled: do not stay "pending"
  }
  paintSidebarSearch(); announceSearch()
}
let contentRefreshT = 0
function queueContentRefresh() { // counts follow edits: re-ask once typing and the save debounce have settled
  if (!searchOn() || !searchFilters.content) return
  clearTimeout(contentRefreshT)
  contentRefreshT = setTimeout(() => { if (searchOn() && searchFilters.content && contentHitQ === findQ) runSearch() }, 3000)
}
function searchFiltersDirty() {
  return Object.keys(SEARCH_DEFAULTS).some(k => searchFilters[k] !== SEARCH_DEFAULTS[k])
}
function updateSearchFilterButton() {
  const b = $('qFilter')
  if (!b) return
  b.classList.toggle('has-filters', searchFiltersDirty())
  b.title = t('docs.sfTitle') // keep the tooltip stable; the filled funnel shows non-default settings
}
function closeSearchFilters() {
  const box = document.getElementById('searchFilters')
  if (!box) return
  box.remove()
  $('qFilter').setAttribute('aria-expanded', 'false')
  document.removeEventListener('pointerdown', searchFiltersOutside, true)
  document.removeEventListener('keydown', searchFiltersEsc, true)
}
function searchFiltersOutside(e) {
  if ($('qFilter').contains(e.target)) return
  const box = document.getElementById('searchFilters')
  if (box && !box.contains(e.target)) closeSearchFilters()
}
function searchFiltersEsc(e) {
  if (e.key !== 'Escape') return
  e.preventDefault(); e.stopPropagation()
  closeSearchFilters(); $('qFilter').focus()
}
function toggleSearchFilter(key) {
  searchFilters[key] = !searchFilters[key]
  saveSearchFilters()
  updateSearchFilterButton()
  const b = document.querySelector(`#searchFilters [data-sf="${key}"]`)
  if (b) {
    b.setAttribute('aria-checked', String(searchFilters[key]))
    const ck = b.querySelector('.ck')
    if (ck) ck.textContent = searchFilters[key] ? '✓' : ''
  }
  if (key === 'content' && !searchFilters.content) { contentHits = new Map(); contentHitQ = '' }
  if (!searchOn()) return
  searchFold.clear() // changed filter set: show all remaining folders open
  if (key === 'content' && searchFilters.content) runSearch()
  else { paintSidebarSearch(); announceSearch() }
}
function applySearchFilters(next) {
  Object.assign(searchFilters, next)
  saveSearchFilters()
  updateSearchFilterButton()
  ++searchN // drop any content lookup that is still in flight
  contentHits = new Map(); contentHitQ = ''
  searchFold.clear()
  document.querySelectorAll('#searchFilters [data-sf]').forEach(b => {
    const on = searchFilters[b.dataset.sf]
    b.setAttribute('aria-checked', String(on))
    const ck = b.querySelector('.ck')
    if (ck) ck.textContent = on ? '✓' : ''
  })
  if (searchOn()) { paintSidebarSearch(); announceSearch() }
}
function resetSearchFilters() { applySearchFilters(SEARCH_DEFAULTS) }
function clearSearchSelection() { // uncheck every area; the query stays
  const none = {}
  for (const k of Object.keys(SEARCH_DEFAULTS)) none[k] = false
  applySearchFilters(none)
}
function openSearchFilters() {
  closeSearchFilters()
  const box = el('div'); box.id = 'searchFilters'; box.setAttribute('role', 'menu')
  box.setAttribute('aria-label', t('docs.sfTitle'))
  const head = el('div', 'mhRow')
  head.appendChild(el('div', 'mh', t('docs.sfAreas')))
  const tools = el('div', 'mhTools')
  const tool = (act, icon, label) => {
    const b = icoBtn('mhBtn', icon); b.type = 'button'; b.dataset.act = act
    b.title = label; b.setAttribute('aria-label', label)
    tools.appendChild(b)
    return b
  }
  tool('clear', ICO_X, t('docs.sfClear')).onclick = e => {
    e.stopPropagation(); clearSearchSelection()
  }
  tool('reset', ICO_RESET, t('docs.sfReset')).onclick = e => {
    e.stopPropagation(); resetSearchFilters()
  }
  head.appendChild(tools)
  box.appendChild(head)
  const addItem = (key, labelKey) => {
    const b = el('button', 'sfItem'); b.type = 'button'; b.dataset.sf = key
    b.setAttribute('role', 'menuitemcheckbox'); b.setAttribute('aria-checked', String(searchFilters[key]))
    const ck = el('i', 'ck', searchFilters[key] ? '✓' : ''); ck.setAttribute('aria-hidden', 'true')
    b.append(ck, el('span', 'ln', t(labelKey)))
    if (key === 'content') b.title = t('docs.sfContentHint')
    b.onclick = e => { e.stopPropagation(); toggleSearchFilter(key) }
    box.appendChild(b)
  }
  ;[['projects', 'docs.secDocs'], ['modules', 'docs.secFiles'], ['shared', 'docs.secShared'],
    ['trash', 'docs.trashSec'], ['outline', 'docs.secOutline']].forEach(([k, label]) => addItem(k, label))
  box.appendChild(el('hr'))
  addItem('content', 'docs.sfContent')
  document.body.appendChild(box)
  const r = $('qFilter').getBoundingClientRect(), w = box.offsetWidth, h = box.offsetHeight, gap = 6
  let left = r.right + gap // open to the right of the button, over the editor
  if (left + w > innerWidth - 8) left = Math.max(8, r.left - w - gap) // narrow viewport: flip back into the sidebar
  box.style.top = Math.max(8, Math.min(r.top, innerHeight - h - 8)) + 'px'
  box.style.left = left + 'px'
  $('qFilter').setAttribute('aria-expanded', 'true')
  setTimeout(() => {
    document.addEventListener('pointerdown', searchFiltersOutside, true)
    document.addEventListener('keydown', searchFiltersEsc, true)
  })
  box.querySelector('.sfItem')?.focus()
}
updateSearchFilterButton()
function resRow(tpl) { // click opens in editor, drag sorts into folder (all three resource kinds share this row)
  const div = document.createElement('div')
  div.className = 'doc private-module sub' + (tpl.name === tplName ? ' cur' : '')
  div.dataset.resourceName = tpl.name // stable across sidebar repaints: an open row menu can refocus its new button
  div.setAttribute('role', 'button')
  div.appendChild(searchTextEl('t', tpl.name)); div.title = tpl.name
  const open = () => {
    const q = searchFindQ('t:' + tpl.name)
    return openTpl(tpl.name).then(() => { if (q && tplName === tpl.name) findWith(q) })
  }
  div.onclick = open
  kb(div, open)
  sidebarDrag(div, { personal: true, entry: { kind: 'resource', name: tpl.name, folder: tpl.folder || '' } }, 'copyMove')
  const ren = projectAction(div, ICO_EDIT, t('templates.renameTpl'), () => renamePersonalResource(tpl.name, div))
  ren.dataset.menuKey = 'rename'; ren.dataset.menuLabel = t('menu.renameShort'); ren.dataset.menuHint = 'menu.renameHint' // key: the menu formats it with the entry type
  const dup = projectAction(div, ICO_DUP, t('docs.duplicate'), () => duplicatePersonalResource(tpl.name))
  dup.dataset.menuKey = 'duplicate'; dup.dataset.menuLabel = t('menu.duplicateShort'); dup.dataset.menuHint = 'menu.duplicateHint'
  const use = projectAction(div, ICO_SEND, t('projects.pullProject'), () => pullPersonalResource(tpl.name))
  use.dataset.menuKey = 'use'; use.dataset.menuLabel = t('menu.useInProject'); use.dataset.menuHint = 'menu.useInProjectHint'
  const del = el('button', 'mini'); del.innerHTML = ICO_TRASH; del.title = t('templates.delRes'); del.setAttribute('aria-label', del.title); del.dataset.menuDanger = ''; del.dataset.menuKey = 'trash'
  del.dataset.menuLabel = t('menu.actionTrash'); del.dataset.menuHint = 'menu.trashHint'
  del.onclick = async e => {
    e.stopPropagation()
    if (!await ask(t('templates.delResConfirm', { name: tpl.name }), { noInput: true, ok: t('docs.moveTrash'), danger: true })) return
    try { await api('DELETE', '/api/templates/' + encodeURIComponent(tpl.name)) } catch (err) { toast(err.message); return }
    if (tpl.name === tplName) { clearTimeout(tplT); tplDirty = false; closeView(); $('viewSeg').style.display = '' } // open resource gone: no zombie save, back to empty
    await loadTpl(); sidebar()
  }
  div.appendChild(del)
  compactSidebarActions(div, 0, personalModuleMenu)
  searchHitBadge(div, 't:' + tpl.name)
  return div
}
function paintKind(boxId, kind, emptyKey, key) { // one resource section (.typ/.bib/.csv) from the shared myTpl shelf
  const box = $(boxId); if (!box) return
  box.replaceChildren()
  if (searchOn() && (kind !== 'resource' || !searchFilters.modules)) return
  let rows = resOf(kind)
  if (searchOn()) rows = rows.filter(t => searchMatch(t.name) || searchContent('t:' + t.name) > 0)
  rows.forEach(t => box.appendChild(resRow(t)))
  if (!box.hasChildNodes() && !searchPending()) box.appendChild(el('div', 'empty', searchOn() ? t('docs.noHits') : t(emptyKey))) // create via + New above (type + folder step)
}
function paintTpls() { // templates + libraries + tables sections: click opens in editor
  if (sidebarRenaming()) return
  paintKind('tpls', 'resource', 'templates.noTpls', 'tpl:')
  paintKind('libs', 'library', 'templates.noLibs', 'lib:')
  paintKind('tbls', 'table', 'templates.noTbls', 'tbl:')
  reanchorSideMenu()
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
    $('save').textContent = t('docs.saved')
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
    tplDirty = false; setT(r.content || ''); $('save').textContent = t('docs.saved'); paintTpls()
  } catch (e) { toast(e.message) }
}
async function resSync() { // SSE follow-up: fresh list first, open resource follows only when clean (dirty editors never wiped)
  try { await loadTpl(); if (docProject) await loadDocResources(true) } catch (e) {}
  if (!tplName) return
  const cc = tplCached(tplName)
  if (!cc) return
  if (!tplDirty) {
    tplVer = cc.updated_at || tplVer
    if ((cc.content || '') !== getT()) { setT(cc.content || ''); $('save').textContent = t('docs.saved') }
  }
}
function leaveDoc() { // reset sync/peers/threads/media (openTpl/openDoc/del)
  clearTimeout(scrollT)
  saveDocScroll() // previous doc: remember editor + preview spot before the buffers reset
  scrollRestore = null
  try { if (docId && ytext && docRole !== 'reviewer' && !openedTrashed && (!wsLive() || !synced)) { const c = ytext.toString(); if (c) lsSet('typst-pending-' + docId, JSON.stringify({ t: Date.now(), c })) } } catch (e) {} // offline/unsynced main: Yjs dies with the provider, stash offers restore on reopen (openDoc drops it silently if converged)
  if (window.suggestionDraft && !stopSuggestionDraft(false)) stopSuggestionDraft()
  ++renderN; ++tabSeq; clearTimeout(renderT); clearTimeout(syncT); syncT = 0
  pvObs?.disconnect(); pvObs = null; pvSlots = []; pvTexts = []; pvTextDone = []; pvPageSize = null; pvLinks = []; pvOutline = []; pvOutlineGen = -1 // old PDF layer must never badge/link the next doc
  if (window.Present?.isOn()) window.Present.exit()
  window.docTpl = []; docResAt = 0
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
  threads = []; members = []; lastC = ''; marks = new Set(); syncPage = 0; syncEdOff = 0; syncEdX = -1; syncEdMiss = false // do not carry click page/reading point into next doc
  docProject = ''; docResReadonly = true
  activeFile = ''; clearTimeout(fileT); bibKeys = [] // tabs closed (see paintTabs)
  $('tabs').style.display = 'none'
  fileCache.clear(); mediaNames = []; lastMedia = ''; lastFiles = []; mediaOpen = false
  filesDirty = true; filesAt = 0; shadowSig = ''; lastPres = ''; lastErrToast = '' // next doc: fresh list + full shadow remap + presence
  $('media').style.display = 'none'; closePop()
  cm.dispatch({ effects: setPeer.of(RangeSet.of([])) })
  $('peers').replaceChildren()
  clearPeerEdges()
  $('cBadge').style.display = 'none'
  const eb = $('eBadge'); if (eb) eb.style.display = 'none'
}
async function openTpl(name) {
  if (window.suggestionDraft && !await leaveSuggestionDraft()) return
  const n = ++openN
  if (!(await flushTpl())) return // dirty resource first: failed save keeps the old view, edits preserved
  if (n !== openN || !await flushTab(true) || n !== openN) return
  let tpl = tplCached(name)
  if (!tpl) { // the list refresh can still be in flight right after a create: ask the server for this row
    try {
      const r = await api('GET', '/api/templates/' + encodeURIComponent(name))
      if (n !== openN) return
      tpl = { ...r, updated_at: r.version || '' }
      const i = myTpl.findIndex(x => x.name === name)
      if (i >= 0) myTpl[i] = tpl
      else myTpl.push(tpl)
    } catch (e) { return }
  }
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
  $('role').textContent = low.endsWith('.bib') ? t('templates.roleLibrary') : /\.(csv|tsv)$/.test(low) ? t('templates.roleTable') : t('templates.roleLabel')
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
function wsLive() { return !!(prov && prov.wsconnected) } // Yjs carries the document text; REST autosave would only 409
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
  if (sv && live && (!sv.textContent || sv.textContent === t('docs.offlineRetry'))) sv.textContent = t('docs.saved') // back from offline: Yjs already converged, drop the stale retry note quietly
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
  paintTabs() // hides the tab bar: no doc open
  paintOwn(); paintShared(lastShared) // clear the active row highlight
  setT(''); gutter(); paintOutline()
}
async function openDoc(id) {
  if (window.suggestionDraft && !await leaveSuggestionDraft()) return
  const n = ++openN
  if (!(await flushTpl())) return // dirty resource first: failed save keeps the old view, edits preserved
  if (n !== openN || !await flushTab(true) || n !== openN) return
  let d
  try { d = await api('GET', `/api/docs/${id}`) }
  catch (e) { toast(e.message); sidebar(); return }
  if (n !== openN) return // stale: newer openDoc already running
  if (tplDirty || tabDirty) return // input while loading: keep the unsaved buffer
  autoCloseDrawer()
  leaveDoc()
  if (tplName) setView('split')
  hidePops()
  docId = id; docRole = d.role; tplName = ''; docProject = d.project_id || ''
  scrollRestore = scrollRead(id)
  if (scrollRestore) scrollRestore.epoch = n
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
    scrollApplyEditor()
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
function queueSave() { // the document text: Yjs carries every keystroke (offline too: syncs on reconnect); REST would 409 or fork the text, so never autosave main
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
    if (await flushTab()) { $('save').textContent = t('docs.saved'); queueRender() }
    return
  }
  if (!docId || docRole === 'reviewer' || !ytext) return
  if (!wsLive() || navigator.onLine === false) { $('save').textContent = t('docs.offlineRetry'); return } // Yjs owns the document text: no REST off the sync path (forked text doubled on reconnect), quiet even when explicit
  if (auto) { if (!window.suggestionDraft) $('save').textContent = t('docs.saved'); paintConn(); return } // reconnect won the race: Yjs has it, no REST (2E); draft must not claim 'saved'
  try { await api('POST', `/api/docs/${docId}/save`, { content: ytext.toString(), ...(force ? { force: true } : {}) }); $('save').textContent = t('docs.saved') }
  catch (e) {
    if (e.status === 409 && !force && prov && prov.wsconnected && synced) return saveNow(true, auto) // live: Y state already merges everyone's edits, safe to overwrite
    $('save').textContent = saveErr(e)
    if (auto && (navigator.onLine === false || !wsLive())) return // quiet: status line already says it, no toast spam (2E)
    if (e.status === 409 && !force) toast(t('docs.saveConflict'), () => saveNow(true), t('docs.forceSave'))
    else toast(t('docs.saveFail', { msg: e.message }), () => saveNow(force), t('common.retry'))
  }
}
