// --- Project files: one tree per project, every document compiles against it; #image() at cursor ---
let mediaOpen = false, lastMedia = '', lastFiles = [] // lastFiles: [{path, size, version}] of the open document's project
let activeFile = '', fileT = 0, bibKeys = [] // '' = the document text (Yjs sync), else the project path of the open file
let docFolder = '' // the open document compiles as <folder>/__doc__.typ: its relative paths start in its folder
const docMain = () => '/' + (docFolder ? docFolder + '/' : '') + '__doc__.typ'
const fileUrl = (path, project = docProject) => `/api/projects/${project}/files/` + path.split('/').map(encodeURIComponent).join('/')
function refTo(path, dir = activeFile ? activeFile.split('/').slice(0, -1).join('/') : docFolder) { // quoted reference from the text in the editor: relative inside its folder, else from the project root
  return !dir ? path : path.startsWith(dir + '/') ? path.slice(dir.length + 1) : '/' + path
}
const cachedText = path => { const c = fileCache.get(path); return c ? new TextDecoder().decode(c.bytes) : '' } // text the preview already holds
async function fileRead(path) { // UTF-8 text of a project file and the version of exactly these bytes
  const r = await fetch(fileUrl(path))
  if (!r.ok) throw Object.assign(new Error(expMsg(await r.text())), { status: r.status })
  return { text: await r.text(), version: r.headers.get('X-File-Version') || '' }
}
const fileText = async path => (await fileRead(path)).text
async function putFile(url, body) { // raw PUT of a project file (?version= guards an overwrite); errors carry .status like api()
  filesDirty = true
  const r = await fetch(url, { method: 'PUT', body })
  const j = await r.json().catch(() => null)
  if (!r.ok) throw Object.assign(new Error((j && (j.detail?.message || j.detail)) || r.statusText), { status: r.status })
  return j
}
function mediaInsert(name) { // manager chip: loader matches kind (csv is data, fonts set text, rest image)
  if (FONT_EXT.test(name)) return `#set text(font: ${typstStr(projectFontByPath.get(name)?.[0] || name.split('/').pop().replace(/\.[^.]+$/, ''))})`
  name = refTo(name)
  if (/\.typ$/i.test(name)) return `#include "${name}"`
  if (/\.bib$/i.test(name)) return `#bibliography("${name}")`
  if (/\.csv$/i.test(name)) return `#csv("${name}")`
  const ext = name.split('.').pop().toLowerCase()
  const loader = { tsv: 'csv', json: 'json', yaml: 'yaml', yml: 'yaml', toml: 'toml', xml: 'xml', txt: 'read', csl: 'read' }[ext]
  if (loader) return `#let data = ${loader}("${name}"${ext === 'tsv' ? ', delimiter: "\\t"' : ''})`
  return `#image("${name}", width: 80%)`
}
function renderMediaChips(files) {
  lastFiles = files
  paintTabs() // tabs follow file list (only on change, see shadowAll)
  const bar = $('media'); bar.replaceChildren()
  if (openedTrashed) { bar.style.display = 'none'; return } // trash: no manager at all
  bar.style.display = mediaOpen ? '' : 'none'
  if (!mediaOpen) return
  const reviewer = docRole === 'reviewer' || docResReadonly // readers browse + copy to library, no upload/delete/insert
  if (!reviewer) {
    const add = el('button', null, t('files.upload'))
    add.onclick = () => $('imgPick').click()
    bar.appendChild(add)
  }
  files.forEach(f => {
    const c = el('span', 'chip')
    const n = el(reviewer ? 'span' : 'button', 'name', f.path)
    if (!reviewer) { n.title = t('files.insertAt'); n.setAttribute('aria-label', t('files.insertName', { name: f.path })) }
    if (!reviewer) n.onclick = () => {
      if (!cm.state.facet(EditorView.editable)) { toast(t('projects.readonly')); return }
      const m = cm.state.selection.main
      const ins = mediaInsert(f.path)
      cm.dispatch({ changes: { from: m.from, to: m.to, insert: ins }, selection: { anchor: m.from + ins.length } })
      cm.focus()
    }
    c.appendChild(n)
    c.appendChild(el('span', 'sz', t('files.sizeKb', { kb: Math.round(f.size / 1024) })))
    if (!reviewer) {
      const x = icoBtn(null, ICO_X); x.title = t('files.del'); x.setAttribute('aria-label', t('files.delName', { name: f.path }))
      x.onclick = () => deleteFile(f.path)
      c.appendChild(x)
      if (window.changeSession && !window.changeSession.original && !TEXT_EXT.test(f.path)) { // swap an existing image's content inside the package (add would stumble over nameExists)
        const r = icoBtn(null, ICO_DUP); r.title = t('files.replaceName', { name: f.path }); r.setAttribute('aria-label', r.title)
        r.onclick = () => { pendingReplace = f.path; $('imgPick').click() }
        c.appendChild(r)
      }
    }
    if (TEXT_EXT.test(f.path)) { const copy = icoBtn(null, ICO_DUP); copy.title = t('projects.copy'); copy.setAttribute('aria-label', copy.title); copy.onclick = () => copyFileToPersonal(docProject, f.path).catch(e => toast(e.message)); c.appendChild(copy) }
    bar.appendChild(c)
  })
}
$('mediaBtn').onclick = () => { mediaOpen = !mediaOpen; renderMediaChips(lastFiles) }
// --- Tabs: the document text and the project files opened next to it ('' = the document text, else a project path) ---
let tabName = k => k || '__doc__.typ'
const tabKind = k => !k ? 'typ' : ((/\.([a-z]+)$/i.exec(k) || [])[1] || 'typ').toLowerCase()
const tabPath = k => k ? '/' + tabName(k) : docMain() // compiler path of the tab's text (diagnostics carry it)
const TEXT_EXT = /\.(typ|bib|csv|tsv|json|yaml|yml|toml|xml|txt|csl)$/i
const tabCanEdit = k => (!k || k.startsWith('@doc/') || TEXT_EXT.test(k)) && !openedTrashed && docRole !== 'reviewer' && (!k || k.startsWith('@doc/') || !docResReadonly)
const fileStashKey = (d, k) => 'typst-filestash-' + d + '-' + encodeURIComponent(k) // pagehide stash per file tab (keepalive may fail)
let tabSeq = 0 // switch generation: a slow fetch must not write into a newer tab
const tabVersions = new Map()
let tabSaveFlight = null
let tabSig = '', tabT = 0, tabDirty = false
const tabState = new Map() // key -> {a, h, top}: cursor + scroll per tab
function projectTabEntry(key) {
  const added = [...(window.changeSession?.files.values() || [])].find(f => f.kind === 'document' && f.action === 'add' && key === sessionDocumentTab(f))
  if (added) return { document: added.doc_id, name: '' }
  if (key.startsWith('@doc/')) return { document: key.slice(5), name: '' }
  return { document: docId, name: key }
}
// Open tabs (VS Code style): the bar lists only what was opened; closing a tab never deletes anything.
// Entries are stored with stable keys ('d:<doc>', 'f:<path>') per project, in this browser only.
const OPEN_TABS_KEY = 'typst-open-tabs'
let openTabs = [], openTabsScope = '', tabPrev = ''
const tabScope = () => docProject || (docId ? 'doc:' + docId : '')
function tabAbs(k) { // key relative to the open document -> stable key
  if (!k) return 'd:' + docId
  if (k.startsWith('@doc/')) return 'd:' + k.slice(5)
  if (k.startsWith('@proposal-doc/')) return 'x:' + k
  return 'f:' + k
}
function tabRel(a) {
  const v = a.slice(2)
  if (a.startsWith('d:')) return v === docId ? '' : '@doc/' + v
  return v
}
function tabStoreRead() { try { const o = JSON.parse(localStorage.getItem(OPEN_TABS_KEY) || '{}'); return o && typeof o === 'object' ? o : {} } catch (e) { return {} } }
function tabStoreSave() {
  try {
    const all = tabStoreRead(); all[openTabsScope] = openTabs.slice(-60)
    const keys = Object.keys(all); if (keys.length > 40) delete all[keys[0]]
    localStorage.setItem(OPEN_TABS_KEY, JSON.stringify(all))
  } catch (e) {}
}
function tabEnsureOpen() { // scope switch loads that project's tabs; the active tab is always open (next to the previous one)
  const scope = tabScope()
  if (scope !== openTabsScope) {
    openTabsScope = scope; tabPrev = ''
    const stored = tabStoreRead()[scope]
    openTabs = Array.isArray(stored) ? stored.filter(x => typeof x === 'string') : []
  }
  const cur = tabAbs(activeFile)
  if (!openTabs.includes(cur)) {
    const at = openTabs.indexOf(tabPrev)
    openTabs.splice(at < 0 ? openTabs.length : at + 1, 0, cur)
    tabStoreSave()
  }
  tabPrev = cur
}
function tabRemap(scope, fn) { // renamed or moved entries keep their tab: rewrite the stored keys (memory too when it is the open project)
  const all = tabStoreRead(), list = (scope === openTabsScope ? openTabs : all[scope]) || []
  const next = list.map(fn)
  if (next.some((a, i) => a !== list[i])) {
    if (scope === openTabsScope) openTabs = next
    all[scope] = next
    try { localStorage.setItem(OPEN_TABS_KEY, JSON.stringify(all)) } catch (e) {}
    tabSig = ''
  }
}
const tabRemapEntry = (scope, from, to) => tabRemap(scope, a => a === from ? to : a)
function tabRemapPrefix(scope, from, to) { // folder rename: every tab below it follows
  tabRemap(scope, a => {
    const v = a.slice(2)
    return a.startsWith('f:') && (v === from || v.startsWith(from + '/')) ? 'f:' + to + v.slice(from.length) : a
  })
}
function tabExists(a, entries) {
  if (a.startsWith('x:')) return !!window.changeSession
  const v = a.slice(2)
  if (a.startsWith('d:')) return !entries || entries.documents.some(d => d.id === v)
  return a.startsWith('f:') && [...(entries?.files || []), ...lastFiles].some(f => f.path === v)
}
function tabItems() {
  const project = typeof projects !== 'undefined' && projects.find(p => p.id === docProject)
  const entries = project ? projectEntries(project) : null
  return [...new Set(openTabs.filter(a => tabExists(a, entries)).map(tabRel))]
}
async function closeTab(k) { // closing only hides the tab; the file stays in the project
  const a = tabAbs(k), items = tabItems()
  if (!openTabs.includes(a)) return
  if (k === activeFile) {
    const i = items.indexOf(k), next = items[i - 1] ?? items[i + 1]
    if (next === undefined) { // last tab: back to the empty view
      if (!await flushTab()) return
      openTabs = openTabs.filter(x => x !== a); tabStoreSave(); tabSig = ''; closeView(); return
    }
    if (!await switchTab(next)) return
  }
  openTabs = openTabs.filter(x => x !== a); tabStoreSave(); tabSig = ''; paintTabs()
}
async function closeOtherTabs(k) {
  if (k !== activeFile && !await switchTab(k)) return
  openTabs = openTabs.filter(x => x === tabAbs(k)); tabStoreSave(); tabSig = ''; paintTabs()
}
async function closeAllTabs() {
  if (!await flushTab()) return
  openTabs = []; tabStoreSave(); tabSig = ''; closeView()
}
function tabRun(fn) { return () => Promise.resolve().then(fn).catch(e => toast(e.message)) }
function tabMenuItems(k, name) {
  const p = typeof projects !== 'undefined' ? projects.find(x => x.id === docProject) : null
  const entry = projectTabEntry(k)
  const items = []
  const proposal = k.startsWith('@proposal-doc/')
  if (p && !proposal && !openedTrashed) {
    const doc = !entry.name ? p.documents?.find(d => d.id === entry.document) : null
    if (doc) { // document tab: title actions, exactly like the sidebar row
      if (projectEditable(p)) items.push({ label: t('docs.renameDoc'), run: tabRun(() => renameProjectDocument(doc)) })
      items.push({ label: t('projects.transfer'), run: tabRun(() => projectEntryMenu(p, { kind: 'document', doc_id: doc.id, name: doc.title })) })
      if (projectEditable(p) || canStageProjectDelete(p.id)) items.push({ label: t('docs.moveTrash'), danger: true, run: tabRun(() => moveDocToTrash(doc)) })
    } else if (entry.name) { // project file tab
      if (projectEditable(p)) items.push({ label: t('files.renameHead'), run: tabRun(() => renameProjectEntry(p, entry.name)) })
      items.push({ label: t('projects.transfer'), run: tabRun(() => projectEntryMenu(p, { kind: 'file', name: entry.name })) })
      if (projectEditable(p) || canStageProjectDelete(p.id)) items.push({ label: t('docs.moveTrash'), danger: true, run: tabRun(() => deleteProjectEntry(p, entry.name)) })
    }
  }
  if (items.length) items.push({ sep: true })
  items.push({ label: t('files.tabClose'), run: tabRun(() => closeTab(k)) })
  if (tabItems().length > 1) items.push(
    { label: t('files.tabCloseOthers'), run: tabRun(() => closeOtherTabs(k)) },
    { label: t('files.tabCloseAll'), run: tabRun(() => closeAllTabs()) }
  )
  return items
}
function tabMenu(k, name, anchor) {
  const items = tabMenuItems(k, name)
  if (window.showMenuAt) window.showMenuAt(anchor, items)
  else askPick(name, items.map(x => x.label)).then(i => { if (i != null && items[i]) items[i].run() })
}
const tabErrs = k => cmpDiags.filter(d => d && d.path === tabPath(k)).length
function scrollTabIntoView(button) { // keep the active tab fully visible without scrolling the page (review #1)
  const bar = $('tabs')
  if (!bar || !button) return
  const pad = 14, r = button.getBoundingClientRect(), br = bar.getBoundingClientRect()
  if (r.left < br.left + pad) bar.scrollLeft -= br.left + pad - r.left
  else if (r.right > br.right - pad) bar.scrollLeft += r.right - br.right + pad
}
function queueTabs() { clearTimeout(tabT); tabT = setTimeout(paintTabs, 350) } // cheap: repaints only when the set or state changed
const tabReq = key => fileUrl(key) + (tabVersions.has(key) ? '?version=' + encodeURIComponent(tabVersions.get(key)) : '') // PUT target of a file tab: the known version guards the overwrite
function paintTabs() {
  updateFileView() // the document text + text files + used templates as tabs, preview stays main
  const bar = $('tabs')
  if (!docId || tplName || openedTrashed) { bar.style.display = 'none'; tabSig = ''; return }
  tabEnsureOpen()
  let items = tabItems()
  if (activeFile && !items.includes(activeFile)) { activeFile = ''; tabDirty = false; setT(shadow); gutter(); refreshHl(); paintOutline(); tabEnsureOpen(); items = tabItems() } // deleted/removed: back to main, editor must show main again (else file text leaks into main)
  const canEdit = docRole !== 'reviewer'
  const labels = typeof projects !== 'undefined' ? projects.find(p => p.id === docProject)?.documents?.map(d => d.id + ':' + d.title).join('|') : ''
  const proposalState = [...(window.changeSession?.files.values() || [])].map(f => [f.kind, f.doc_id, f.path, f.action, f.target].join(':')).join('|')
  const sig = [docRole, activeFile, $('title').textContent, labels, proposalState, ...items.map(k => k + '\u0001' + tabErrs(k))].join('|')
  if (sig === tabSig && bar.firstChild) { bar.style.display = ''; paintSuggestionControls(); return }
  tabSig = sig
  const fk = bar.contains(document.activeElement) && document.activeElement.dataset ? (document.activeElement.dataset.k ?? null) : null // repaint drops focus: give it back below
  bar.style.display = ''
  bar.setAttribute('role', 'tablist'); bar.setAttribute('aria-label', t('files.tabsAria'))
  bar.replaceChildren()
  for (const k of items) {
    const entry = projectTabEntry(k), main = !entry.name
    const document = typeof projects !== 'undefined' && projects.find(p => p.id === docProject)?.documents?.find(d => d.id === entry.document)
    const proposed = window.changeSession?.files.get(['document', entry.document, ''].join(':'))
    const title = (!window.changeSession?.original && proposed?.target) || document?.title || (typeof docTitle !== 'undefined' && docTitle) || $('title').textContent
    const on = k === activeFile, nm = main ? title.replace(/\.typ$/i, '') + '.typ' : entry.name
    const staged = window.changeSession?.files.get(main ? ['document', entry.document, ''].join(':') : ['file', '', entry.name].join(':'))
    const deleted = staged?.action === 'delete'
    const w = el('span', 'tabw' + (on ? ' on' : ''))
    w.classList.toggle('package-deleted', deleted)
    const b = el('button', 'tab')
    b.setAttribute('role', 'tab'); b.setAttribute('aria-selected', on ? 'true' : 'false'); b.tabIndex = on ? 0 : -1; b.dataset.k = k
    const ic = el('span', 'ti'); ic.dataset.kind = tabKind(k); ic.setAttribute('aria-hidden', 'true')
    b.title = '/' + nm + (tabCanEdit(k) ? '' : ' · ' + t('projects.readonly'))
    b.append(ic, el('span', 'tn', nm.split('/').pop()))
    const ec = tabErrs(k)
    if (ec) { const e = el('span', 'te', String(ec)); e.title = t('files.tabErrors', { n: ec }); b.appendChild(e) }
    b.setAttribute('aria-label', !k ? t('files.editMain') : t('files.editTab', { name: nm }))
    b.onclick = () => switchTab(k)
    b.ondblclick = () => { if (canEdit) { const p = projects.find(p => p.id === docProject); if (main) renameProjectDocument({ id: entry.document, title }); else if (p) renameProjectEntry(p, entry.name); else toast(t('projects.contextGone')) } }
    w.appendChild(b)
    b.onauxclick = e => { if (e.button === 1) { e.preventDefault(); closeTab(k) } }
    b.oncontextmenu = e => { e.preventDefault(); tabMenu(k, nm, b) }
    const x = icoBtn('tx', deleted ? ICO_UNDO : ICO_X)
    x.title = deleted ? t('packages.discardFile') : t('files.tabCloseName', { name: nm }); x.setAttribute('aria-label', x.title); x.tabIndex = -1
    x.onclick = async e => { e.stopPropagation(); try { if (deleted) await discardSessionFile(staged); else await closeTab(k) } catch (error) { toast(error.message) } }
    w.appendChild(x)
    bar.appendChild(w)
  }
  bar.appendChild(el('span', 'tsp'))
  paintSuggestionControls()
  scrollTabIntoView(bar.querySelector('button.tab[aria-selected="true"]'))
  if (fk !== null) for (const b of bar.querySelectorAll('button.tab')) if (b.dataset.k === fk) { b.focus(); break } // focus was inside: same tab keeps it
}
function focusTab(k) { // after keyboard/proxy switches: selection and focus move together
  const tabs = [...$('tabs').querySelectorAll('button.tab')], b = tabs.find(x => x.dataset.k === k)
  if (b) { tabs.forEach(x => { x.tabIndex = x === b ? 0 : -1 }); b.focus() }
}
$('tabs').addEventListener('keydown', e => { // roving focus: arrows, Home/End move between tabs, Enter/Space activates (native), Delete removes a file
  const tabs = [...$('tabs').querySelectorAll('button.tab')], i = tabs.indexOf(document.activeElement)
  if (i < 0) return
  if (e.key === 'Delete' || e.key === 'Backspace') {
    e.preventDefault(); closeTab(document.activeElement.dataset.k)
    return
  }
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return
  e.preventDefault()
  const n = e.key === 'Home' ? 0 : e.key === 'End' ? tabs.length - 1 : (i + (e.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length
  tabs.forEach((b, j) => { b.tabIndex = j === n ? 0 : -1 }); tabs[n].focus()
})
async function cycleTab(d) {
  if (!docId || tplName || openedTrashed) return
  const items = tabItems(), i = items.indexOf(activeFile)
  const nk = items[(i + d + items.length) % items.length]
  if (await switchTab(nk)) focusTab(activeFile)
}
function tabSaveState(k) { try { const s = cm.state.selection.main; tabState.set(k, { a: s.anchor, h: s.head, top: cm.scrollDOM.scrollTop }) } catch (e) {} }
function tabRestoreState(k) {
  const s = tabState.get(k), n = cm.state.doc.length
  if (!s) { cm.scrollDOM.scrollTop = 0; pvSelfWrite(cm.scrollDOM); return }
  cm.dispatch({ selection: { anchor: Math.min(s.a, n), head: Math.min(s.h, n) } })
  requestAnimationFrame(() => { cm.scrollDOM.scrollTop = s.top; pvSelfWrite(cm.scrollDOM) })
}
async function switchTab(name, nosave, preserveView = false) { // true = switched, false = blocked/stale (caller keeps focus where it is)
  if (window.suggestionDraft && !await leaveSuggestionDraft()) return false
  if (name?.startsWith('@doc/')) {
    const entry = projectTabEntry(name), p = docProject
    if (entry.document !== docId) await openDoc(entry.document)
    if (docId !== entry.document || docProject !== p) return false
    return switchTab(entry.name, nosave, preserveView)
  }
  if (name === activeFile || !docId) return true
  const my = ++tabSeq, dk = docId, epoch = openN
  if (!nosave && !await flushTab(true)) return false // save failed: stay on the dirty tab, nothing discarded
  if (my !== tabSeq || dk !== docId) return false // superseded meanwhile
  clearTimeout(fileT) // old tab's pending timer must not fire into the new tab
  if (nosave) tabDirty = false // delete path: old text is gone by design
  tabSaveState(activeFile)
  if (!activeFile) saveDocScroll() // leaving the document text: keep its spot before the file buffer replaces it
  if (name && TEXT_EXT.test(name) || name && !lastFiles.some(f => f.path === name)) { try { await loadProjectFiles(true) } catch (e) {} } // fresh list: a new upload must not be dropped as 'deleted', a text tab starts from the current version
  if (my !== tabSeq || dk !== docId) return false
  if (!name) { activeFile = ''; setT(shadow); cm.dispatch({ effects: editableComp.reconfigure(editMode(tabCanEdit(''))) }); $('cNew').style.display = openedTrashed ? 'none' : ''; $('save').title = ''; paintTabs(); paintOwn(); paintShared(lastShared); gutter(); closePop(); paintOutline(); reanchor(); refreshHl(); tabRestoreState(''); scrollApplyEditor(); paintErr(); queueRender(); return true }
  let text
  const file = lastFiles.find(f => f.path === name)
  if (!TEXT_EXT.test(name)) {
    const kb = Math.round((file?.size || 0) / 1024)
    text = FONT_EXT.test(name)
      ? t('files.fontInfo', { name, kb, family: projectFontByPath.get(name)?.join(', ') || t('files.fontUnknown'), usage: mediaInsert(name) })
      : t('files.binaryInfo', { name, kb })
  } else {
    let version
    try { ({ text, version } = await fileRead(name)) }
    catch (e) { if (my === tabSeq && dk === docId) toast(e.message); return false }
    if (my !== tabSeq || dk !== docId) return false // late response: must not write into the newer tab
    tabVersions.set(name, version) // from the read itself: a file list refresh racing the open may still miss a new file
  }
  if (my !== tabSeq || dk !== docId || epoch !== openN || tabDirty) return false
  activeFile = name; tabDirty = false; setT(text, preserveView)
  cm.dispatch({ effects: editableComp.reconfigure(editMode(tabCanEdit(name))) })
  $('cNew').style.display = 'none'
  $('save').textContent = tabCanEdit(name) ? t('docs.saved') : ''
  $('save').title = tabCanEdit(name) ? '' : t('common.roleReader')
  tabSig = ''; paintTabs(); paintOwn(); paintShared(lastShared); gutter(); closePop(); paintOutline()
  cm.dispatch({ effects: setHl.of(RangeSet.of([])) }) // file tab: no main highlights as ghosts
  if (!preserveView) tabRestoreState(activeFile)
  if (TEXT_EXT.test(name)) offerFileStash(dk, name) // pagehide stash differs from server: opt-in restore, never silent
  paintErr()
  queueRender()
  return true
}
function offerFileStash(dk, name) { // unsent pagehide copy vs fresh server text: user decides (mirror of the the document text stash flow)
  let o = null
  try {
    const raw = localStorage.getItem(fileStashKey(dk, name))
    if (!raw) return
    o = JSON.parse(raw)
  } catch (e) { return }
  if (!o || typeof o.c !== 'string' || !(Date.now() - o.t < 86400000)) {
    try { localStorage.removeItem(fileStashKey(dk, name)) } catch (e) {}
    return
  }
  if (o.c === getT()) return
  toast(t('presentation.fileStashFound'), () => {
    if (activeFile === name && docId === dk) { setT(o.c); tabDirty = true; queueFileSave(); queueRender() }
  }, t('docs.restore'), 15000)
}
async function flushTab(allowStash = false) {
  if (window.changeSession) return true // silent save on tab switch; true = clean/saved, false = failed (caller must block the switch, edits stay)
  if (tabSaveFlight) { const ok = await tabSaveFlight; if (!ok) return false }
  if (!activeFile || !docId || !tabDirty) return true
  if (!tabCanEdit(activeFile)) {
    clearTimeout(fileT)
    $('save').textContent = t('projects.localDraft')
    $('save').title = t('projects.readonlyDraft')
    if (!allowStash) return false
    const dk = docId, key = activeFile, epoch = openN
    if (await askPick(t('projects.readonlyDraft'), [[t('projects.keepDraftLeave'), ''], [t('projects.stay'), '']]) !== 0) return false
    if (docId !== dk || activeFile !== key || openN !== epoch) return false
    try {
      const stash = JSON.stringify({ t: Date.now(), c: getT(), version: tabVersions.get(key) })
      localStorage.setItem(fileStashKey(dk, key), stash)
      if (localStorage.getItem(fileStashKey(dk, key)) !== stash) return false
    } catch (e) { toast(t('projects.draftStorageFailed')); return false }
    tabDirty = false
    return true
  }
  clearTimeout(fileT)
  const dk = docId, key = activeFile, text = getT(), epoch = openN
  tabSaveFlight = (async () => {
  try {
    const result = await putFile(tabReq(key), text)
    if (docId !== dk) return true // doc switched meanwhile: cache is gone with it
    const bytes = new TextEncoder().encode(text), row = lastFiles.find(f => f.path === key)
    tabVersions.set(key, result.version)
    if (row) { row.version = result.version; row.size = bytes.length }
    if (epoch !== openN) return false
    if (activeFile === key && getT() === text) {
      try { localStorage.removeItem(fileStashKey(dk, key)) } catch (e) {}
      tabDirty = false
      fileCache.set(key, { version: result.version, bytes }) // the saved text is the server state: no refetch
      $('save').textContent = t('docs.saved')
    } else if (activeFile === key && tabDirty) { queueFileSave(); return false }
    return true
  } catch (e) {
    if (docId === dk && activeFile === key) { // same tab: error stays visible, dirty stays set (no silent discard)
      $('save').textContent = navigator.onLine === false ? t('docs.offlineRetry') : t('docs.saveError', { msg: e.message })
      if (navigator.onLine !== false) {
        if (e.status === 409) toast(t('templates.saveConflict'), () => loadTabTheirs(dk, key), t('templates.loadTheirs'))
        else toast(t('presentation.saveBlocked', { name: tabName(key), msg: e.message }), () => { flushTab().then(ok => { if (ok) queueRender() }) }, t('common.retry'))
      }
    }
    return false
  }
  })()
  try { return await tabSaveFlight } finally { tabSaveFlight = null }
}
async function loadTabTheirs(dk, key) { // 409 escape: take the server text into the editor (mirror of loadTheirs)
  try {
    const { text, version } = await fileRead(key)
    if (docId !== dk || activeFile !== key) return
    tabVersions.set(key, version)
    tabDirty = false; setT(text)
    try { localStorage.removeItem(fileStashKey(dk, key)) } catch (e) {}
    $('save').textContent = t('docs.saved')
    gutter(); paintOutline(); paintErr(); queueRender()
  } catch (e) { toast(e.message) }
}
function tabLive() { // compiler copy follows typing: the preview updates before the save lands
  fileCache.set(activeFile, { version: fileCache.get(activeFile)?.version ?? '', bytes: new TextEncoder().encode(getT()) })
  queueRender(); queueTabs()
}
function queueFileSave() { // file/template tab: only that text + preview, no Yjs
  clearTimeout(fileT)
  if (!tabCanEdit(activeFile)) return // shared read-only: no save timer
  tabDirty = true
  $('save').textContent = t('docs.saving')
  const dk = docId, key = activeFile
  fileT = setTimeout(async () => {
    if (docId !== dk || activeFile !== key) return // switched meanwhile: the newer tab owns the editor
    if (await flushTab()) queueRender()
  }, SAVE_MS)
}
function mainAppend(line) { // add a line at the end of the document text through Yjs (editor, preview and peers follow)
  if (window.suggestionDraft) {
    const s = getT()
    cm.dispatch({ changes: { from: s.length, insert: (s && !s.endsWith('\n') ? '\n' : '') + line + '\n' } })
    return
  }
  if (!ytext || docRole === 'reviewer') return
  const s = ytext.toString()
  ydoc.transact(() => ytext.insert(s.length, (s && !s.endsWith('\n') ? '\n' : '') + line + '\n'), 'tabs')
}
const FILE_TYPES = ['typ', 'bib', 'csv', 'tsv', 'json', 'yaml', 'toml', 'xml', 'txt', 'csl']
function fileTypeMenuItems(run) {
  const labels = [t('files.type_typ'), t('files.type_bib'), t('files.type_csv'), t('files.type_tsv'), t('files.type_json'), t('files.type_yaml'), t('files.type_toml'), t('files.type_xml'), t('files.type_txt'), t('files.type_csl')]
  const hints = ['files.type_typD', 'files.type_bibD', 'files.type_csvD', 'files.type_tsvD', 'files.type_jsonD', 'files.type_yamlD', 'files.type_tomlD', 'files.type_xmlD', 'files.type_txtD', 'files.type_cslD'].map(k => t(k))
  return FILE_TYPES.map((ext, i) => ({ label: labels[i], title: hints[i], kbd: '.' + ext, run: () => run('.' + ext) }))
}
function fileStart(ext) { return ({ json: '{}\n', yaml: '{}\n', yml: '{}\n', toml: '', xml: '<data/>\n', csl: '<?xml version="1.0" encoding="utf-8"?>\n<style xmlns="http://purl.org/net/xbiblio/csl" version="1.0">\n  <info><title>Style</title><id>https://example.com/style</id></info>\n  <citation><layout><text variable="title"/></layout></citation>\n</style>\n' })[ext] || '' }
async function chooseFileType() {
  const labels = [t('files.type_typ'), t('files.type_bib'), t('files.type_csv'), t('files.type_tsv'), t('files.type_json'), t('files.type_yaml'), t('files.type_toml'), t('files.type_xml'), t('files.type_txt'), t('files.type_csl')]
  const i = await pickPop(t('files.chooseType'), FILE_TYPES.map((ext, i) => ['.' + ext, labels[i]]), document.activeElement)
  return Number.isInteger(i) && i >= 0 && i < FILE_TYPES.length ? '.' + FILE_TYPES[i] : null
}
async function deleteFile(name) { // manager chip: same trash path as the sidebar row
  return deleteProjectEntry(projects.find(p => p.id === docProject) || { id: docProject }, name)
}
let imgIns = false // only via image button, not via manager upload
let pendingReplace = '' // one-shot chip target - the next picked file replaces this file's content inside the change session
function insImage(name) { // #image() at cursor
  if (!cm.state.facet(EditorView.editable)) { toast(t('projects.readonly')); return }
  const m = cm.state.selection.main, ins = `#image("${refTo(name)}", width: 80%)`
  cm.dispatch({ changes: { from: m.from, to: m.to, insert: ins }, selection: { anchor: m.from + ins.length } })
  cm.focus()
}
const uploadName = n => n.normalize('NFC').replace(/[\\/:*?"<>|\u0000-\u001f\u007f-\u009f\u2028\u2029\u202a-\u202e\u2066-\u2069\ud800-\udfff]+/gu, '_').replace(/^\.+/, '') // what the server accepts as a path segment: any script, not the file system's delimiters
async function upFile(f) { // upload into the document's folder, returns the project path ('' on error)
  const path = (docFolder ? docFolder + '/' : '') + uploadName(f.name)
  try { return (await putFile(fileUrl(path), f)).path }
  catch (e) { toast(t('files.uploadFail', { msg: e.message }), () => upFile(f), t('common.retry')); return '' }
}
const TEXT_UP = /\.(typ|bib|csv|tsv|json|yaml|yml|toml|xml|txt|csl)$/i // text file: save + open as tab (no #image)
async function upText(f) { // text file (max 200 KB) next to the document
  if (f.size > 200 * 1024) { toast(t('files.maxText')); return '' }
  return upFile(f)
}
$('imgBtn').onclick = () => { imgIns = true; $('imgPick').click() }
$('imgPick').addEventListener('cancel', () => { pendingReplace = '' }) // picker dismissed: the one-shot swap must not leak into the next upload
$('imgPick').onchange = async () => {
  const f = $('imgPick').files[0]; $('imgPick').value = ''
  if (!f || !docId) return
  const swap = pendingReplace; pendingReplace = '' // one-shot: never leaks into the next pick
  try {
    if (swap && window.changeSession) { // chip replace swaps the content inside the package
      if (await sessionReplaceFile(swap, f)) { imgIns = false; queueRender(); return }
    }
    if (TEXT_UP.test(f.name)) { const n = await upText(f); if (n) switchTab(n) }
    else {
      const name = await upFile(f)
      if (name && FONT_EXT.test(name)) toast(t('files.fontUploaded', { name }))
      else if (name && imgIns) insImage(name)
    }
  } catch (e) { toast(e.message) }
  imgIns = false; queueRender()
}
cm.contentDOM.addEventListener('paste', async e => { // paste screenshot/image: upload + #image() at cursor
  const imgs = [...((e.clipboardData && e.clipboardData.files) || [])].filter(f => /^image\//.test(f.type))
  if (!imgs.length || !docId || tplName || openedTrashed || docRole === 'reviewer') return
  e.preventDefault()
  toast(imgs.length > 1 ? t('files.uploadingMany', { n: imgs.length }) : t('files.uploadingOne'))
  for (const f of imgs) {
    const ext = ((f.type.split('/')[1] || 'png').replace('jpeg', 'jpg').replace(/\+.*$/, '')).toLowerCase()
    const stamp = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14)
    const named = new File([f], (f.name && f.name !== 'image.png' ? uploadName(f.name) : `paste-${stamp}-${Math.random().toString(36).slice(2, 6)}.${ext}`), { type: f.type })
    try { const name = await upFile(named); if (name) insImage(name) } catch (err) { toast(err.message) }
  }
  queueRender()
})

$('tabs').addEventListener('wheel', e => {
  const bar = $('tabs')
  if (e.ctrlKey || bar.scrollWidth <= bar.clientWidth) return
  const delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY
  if (!delta) return
  e.preventDefault(); bar.scrollLeft += delta * (e.deltaMode === 1 ? 24 : e.deltaMode === 2 ? bar.clientWidth : 1)
}, { passive: false })

function updateFileView() {
  const file = !!tplName // personal module without a document: no preview; file tabs of a document keep the document preview
  const tab = !!activeFile && !!docId && !tplName
  document.body.classList.toggle('file-view', file)
  if (file) { clearTimeout(renderT); ++renderN }
  $('viewSeg').style.display = file || !docId ? 'none' : ''
  $('pvTools').style.display = file || !docId ? 'none' : ''
  const pvFor = $('pvFor')
  pvFor.classList.toggle('on', tab); pvFor.setAttribute('aria-hidden', String(!tab))
  if (tab) pvFor.textContent = t('preview.forDoc', { title: (docTitle || $('title').textContent).replace(/\.typ$/i, '') + '.typ' })
  const filename = tplName || (activeFile ? tabName(activeFile) : (docTitle || 'document').replace(/\.typ$/i, '') + '.typ')
  const extension = filename.split('.').pop().toLowerCase()
  paintImageFile(filename)
  $('fontBtn').classList.toggle('type-hidden', $('cmWrap').hidden) // font slider belongs to the source view, not the rendered files
  $('dlTyp').dataset.extension = extension
  $('dlTyp').dataset.kind = file ? 'file' : 'document'
  $('dlTyp').textContent = '.' + extension
  $('dlZip').style.display = docProject && !tplName ? '' : 'none'
  for (const id of ['dlPdf', 'dlPng', 'dlSvg']) $(id).style.display = file || !docId ? 'none' : ''
  if (docId && !openedTrashed) $('histBtn').style.display = ''
  if (!tplName && docId) { // topbar shows the active file, doc title stays in docTitle
    const want = activeFile ? tabName(activeFile) : docTitle
    if (want && $('title').textContent !== want) $('title').textContent = want
    $('renBtn').style.display = activeFile ? 'none' : (docRole === 'owner' && !openedTrashed ? '' : 'none')
  }
}
