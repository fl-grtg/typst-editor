// --- Images: upload per doc, #image() at cursor, preview knows files ---
let mediaOpen = false, lastMedia = '', lastFiles = [], mediaNames = []
let activeFile = '', fileT = 0, bibKeys = [] // '' = main.typ (Yjs sync), else text file (.typ/.bib/.csv) from manager
function mediaInsert(name) { // manager chip: loader matches kind (csv is data, never an image)
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
  const reviewer = docRole === 'reviewer' // #8: reviewers browse + copy to library (backend allows any reader role), no upload/delete/insert
  if (!reviewer) {
    const add = el('button', null, t('files.upload'))
    add.onclick = () => $('imgPick').click()
    bar.appendChild(add)
  }
  files.forEach(f => {
    const c = el('span', 'chip')
    const n = el(reviewer ? 'span' : 'button', 'name', f.name)
    if (!reviewer) { n.title = t('files.insertAt'); n.setAttribute('aria-label', t('files.insertName', { name: f.name })) }
    if (!reviewer) n.onclick = () => {
      if (!cm.state.facet(EditorView.editable)) { toast(t('projects.readonly')); return }
      const m = cm.state.selection.main
      const ins = mediaInsert(f.name)
      cm.dispatch({ changes: { from: m.from, to: m.to, insert: ins }, selection: { anchor: m.from + ins.length } })
      cm.focus()
    }
    c.appendChild(n)
    c.appendChild(el('span', 'sz', t('files.sizeKb', { kb: Math.round(f.size / 1024) })))
    if (!reviewer) {
      const x = icoBtn(null, ICO_X); x.title = t('files.del'); x.setAttribute('aria-label', t('files.delName', { name: f.name }))
      x.onclick = () => deleteFile(f.name)
      c.appendChild(x)
      if (window.changeSession && !window.changeSession.original && !TEXT_EXT.test(f.name)) { // Round5 #4: swap an existing image's content inside the package (add would stumble over nameExists)
        const r = icoBtn(null, ICO_DUP); r.title = t('files.replaceName', { name: f.name }); r.setAttribute('aria-label', r.title)
        r.onclick = () => { pendingReplace = f.name; $('imgPick').click() }
        c.appendChild(r)
      }
    }
    if (TEXT_EXT.test(f.name)) { const copy = icoBtn(null, ICO_DUP); copy.title = t('projects.copy'); copy.setAttribute('aria-label', copy.title); copy.onclick = () => copyToLibrary(f.name); c.appendChild(copy) }
    bar.appendChild(c)
  })
}
$('mediaBtn').onclick = () => { mediaOpen = !mediaOpen; renderMediaChips(lastFiles) }
// --- Tabs: everything that belongs to the open document in one bar: main.typ, its text files, the templates it uses ---
const TPLK = '@tpl/' // @ cannot occur in sanitized local file names; '' = main.typ
const isTplKey = k => !!k && k.startsWith(TPLK)
const tabName = k => (isTplKey(k) ? k.slice(TPLK.length) : k) || 'main.typ'
const tabKind = k => !k ? 'typ' : isTplKey(k) && /\.typ$/i.test(k) ? 'tpl' : ((/\.([a-z]+)$/i.exec(k) || [])[1] || 'typ').toLowerCase()
const tabPath = k => '/' + tabName(k) // compiler path of the tab's text (diagnostics carry it)
const TEXT_EXT = /\.(typ|bib|csv|tsv|json|yaml|yml|toml|xml|txt|csl)$/i
const effTpl = projectResources
const tabCanEdit = k => (!k || isTplKey(k) || k.startsWith('@doc/') || TEXT_EXT.test(k)) && !openedTrashed && docRole !== 'reviewer' && (!isTplKey(k) || (typeof docProject !== 'undefined' && docProject ? !docResReadonly : docRole === 'owner'))
const fileStashKey = (d, k) => 'typst-filestash-' + d + '-' + encodeURIComponent(k) // pagehide stash per file tab (keepalive may fail)
let tabSeq = 0 // switch generation: a slow fetch must not write into a newer tab
const tabVersions = new Map()
let tabSaveFlight = null
let tabPins = new Set(), tabSig = '', tabT = 0, tabDirty = false // pins: templates opened by hand stay even when unreferenced
const tabState = new Map() // key -> {a, h, top}: cursor + scroll per tab
function usedTpls(preview = false) { // templates this document reaches: quoted names in main.typ + text files, followed through templates
  const src = effTpl()
  if (!src.length) return []
  const byName = new Map(src.map(x => [x.name, x])), out = [], seen = new Set(), dec = new TextDecoder()
  const local = new Map([...fileCache].map(([name, c]) => [name, /\.typ$/i.test(name) && c.bytes ? dec.decode(c.bytes) : '']))
  if (activeFile && !isTplKey(activeFile)) local.set(activeFile, getT())
  const texts = [{ path: 'main.typ', text: activeFile || (window.suggestionDraft && !preview) ? shadow : getT() }, ...[...local].filter(([n]) => /\.typ$/i.test(n)).map(([path, text]) => ({ path, text }))]
  const normalize = p => { const parts = []; for (const s of p.split('/')) { if (s === '..') parts.pop(); else if (s && s !== '.') parts.push(s) } return parts.join('/') }
  for (let i = 0; i < texts.length && i < 500; i++) {
    const { path, text } = texts[i], parent = path.includes('/') ? path.slice(0, path.lastIndexOf('/') + 1) : ''
    for (const m of text.matchAll(/"([^"\n]{1,240})"/g)) {
      const raw = m[1].replace(/\\/g, '/'), base = raw.split('/').pop()
      if ([normalize(parent + raw), normalize(raw), ...(/\s/.test(raw) ? [] : [base])].some(n => local.has(n))) continue
      const tp = [normalize(parent + raw), normalize(raw), ...(/\s/.test(raw) ? [] : [base])].map(n => byName.get(n)).find(Boolean)
      if (tp && !seen.has(tp.name)) {
        seen.add(tp.name); out.push(tp.name)
        if (/\.typ$/i.test(tp.name)) texts.push({ path: tp.name, text: tp.content || '' })
      }
    }
  }
  return out
}
function projectTabEntry(key) {
  if (key.startsWith('@doc/')) return { document: key.slice(5), name: '', resource: false }
  if (key.startsWith('@file/')) { const parts = key.slice(6).split('/'); return { document: parts.shift(), name: parts.join('/'), resource: false } }
  return { document: docId, name: key && !isTplKey(key) ? key : isTplKey(key) ? tabName(key) : '', resource: isTplKey(key) }
}
function tabItems() {
  const project = typeof projects !== 'undefined' && projects.find(p => p.id === docProject)
  if (project) {
    const entries = projectEntries(project)
    const docs = entries.documents.map(d => d.id === docId ? '' : '@doc/' + d.id)
    const files = entries.files.filter(f => f.doc_id !== docId || !lastFiles.some(x => x.name === f.name)).map(f => f.doc_id === docId ? f.name : '@file/' + f.doc_id + '/' + f.name)
    return [...new Set([...docs, ...lastFiles.map(f => f.name), ...files, ...entries.resources.map(r => TPLK + r.name)])]
  }
  return ['', ...lastFiles.map(f => f.name), ...effTpl().map(r => TPLK + r.name)]
}
const tabErrs = k => cmpDiags.filter(d => d && d.path === tabPath(k)).length
function queueTabs() { clearTimeout(tabT); tabT = setTimeout(paintTabs, 350) } // cheap: repaints only when the set or state changed
function tabReq(key, text) { // save request for a tab's text (file of this doc, or global template)
  const version = tabVersions.get(key)
  const guard = version !== undefined ? { version } : {}
  return isTplKey(key) ? { url: docProject ? `/api/projects/${docProject}/resources` : '/api/templates', body: { name: tabName(key), content: text, ...guard } }
    : { url: `/api/docs/${docId}/files/${encodeURIComponent(key)}/text`, body: { content: text, ...guard } }
}
function paintTabs() {
  updateFileView() // main.typ + text files + used templates as tabs, preview stays main
  const bar = $('tabs')
  if (!docId || tplName || openedTrashed) { bar.style.display = 'none'; tabSig = ''; return }
  let items = tabItems()
  if (activeFile && !items.includes(activeFile)) { activeFile = ''; tabDirty = false; setT(shadow); gutter(); refreshHl(); paintOutline(); items = tabItems() } // deleted/removed: back to main, editor must show main again (else file text leaks into main)
  const canEdit = docRole !== 'reviewer'
  const labels = typeof projects !== 'undefined' ? projects.find(p => p.id === docProject)?.documents?.map(d => d.id + ':' + d.title).join('|') : ''
  const sig = [docRole, activeFile, $('title').textContent, labels, ...items.map(k => k + '\u0001' + tabErrs(k))].join('|')
  if (sig === tabSig && bar.firstChild) { bar.style.display = ''; paintSuggestionControls(); return }
  tabSig = sig
  const fk = bar.contains(document.activeElement) && document.activeElement.dataset ? (document.activeElement.dataset.k ?? null) : null // repaint drops focus: give it back below
  bar.style.display = ''
  bar.setAttribute('role', 'tablist'); bar.setAttribute('aria-label', t('files.tabsAria'))
  bar.replaceChildren()
  for (const k of items) {
    const entry = projectTabEntry(k), main = !entry.name
    const document = typeof projects !== 'undefined' && projects.find(p => p.id === docProject)?.documents?.find(d => d.id === entry.document)
    const title = document?.title || (typeof docTitle !== 'undefined' && docTitle) || $('title').textContent
    const on = k === activeFile, nm = main ? title.replace(/\.typ$/i, '') + '.typ' : entry.name
    const w = el('span', 'tabw' + (on ? ' on' : ''))
    const b = el('button', 'tab')
    b.setAttribute('role', 'tab'); b.setAttribute('aria-selected', on ? 'true' : 'false'); b.tabIndex = on ? 0 : -1; b.dataset.k = k
    const ic = el('span', 'ti'); ic.dataset.kind = tabKind(k); ic.setAttribute('aria-hidden', 'true')
    b.title = '/' + nm + (tabCanEdit(k) ? '' : ' · ' + t('projects.readonly'))
    b.append(ic, el('span', 'tn', nm))
    const ec = tabErrs(k)
    if (ec) { const e = el('span', 'te', String(ec)); e.title = t('files.tabErrors', { n: ec }); b.appendChild(e) }
    b.setAttribute('aria-label', !k ? t('files.editMain') : isTplKey(k) ? t('files.tplTab', { name: nm }) : t('files.editTab', { name: nm }))
    b.onclick = () => switchTab(k)
    b.ondblclick = () => { if (canEdit) { const p = projects.find(p => p.id === docProject); if (main) renameProjectDocument({ id: entry.document, title }); else if (p) renameProjectEntry(p, entry.name, entry.document, entry.resource); else toast(t('projects.contextGone')) } }
    w.appendChild(b)
    if (canEdit) {
      const x = icoBtn('tx', ICO_X); x.title = t('files.delName', { name: nm }); x.setAttribute('aria-label', x.title); x.tabIndex = -1
      x.onclick = async e => { e.stopPropagation(); try { if (main) { if (!await ask(t('docs.moveTrashConfirm', { title }), { noInput: true })) return; await api('DELETE', `/api/docs/${entry.document}`); if (entry.document === docId) closeView(); await sidebar() } else await deleteProjectEntry(projects.find(p => p.id === docProject), entry.name, entry.document, entry.resource) } catch (error) { toast(error.message) } }
      w.appendChild(x)
    }
    bar.appendChild(w)
  }
  bar.appendChild(el('span', 'tsp'))
  if (canEdit) {
    const add = icoBtn('tadd', ICO_PLUS); add.title = t('files.tabAddTitle'); add.setAttribute('aria-label', t('files.tabAdd'))
    add.onclick = tabAdd; bar.appendChild(add)
  }
  paintSuggestionControls()
  if (fk !== null) for (const b of bar.querySelectorAll('button.tab')) if (b.dataset.k === fk) { b.focus(); break } // focus was inside: same tab keeps it
}
function focusTab(k) { // after keyboard/proxy switches: selection and focus move together
  const tabs = [...$('tabs').querySelectorAll('button.tab')], b = tabs.find(x => x.dataset.k === k)
  if (b) { tabs.forEach(x => { x.tabIndex = x === b ? 0 : -1 }); b.focus() }
}
$('tabs').addEventListener('keydown', e => { // roving focus: arrows, Home/End move between tabs, Enter/Space activates (native), Delete removes a file
  const tabs = [...$('tabs').querySelectorAll('button.tab')], i = tabs.indexOf(document.activeElement)
  if (i < 0) return
  if ((e.key === 'Delete' || e.key === 'Backspace') && docRole !== 'reviewer') {
    const k = document.activeElement.dataset.k
    e.preventDefault(); document.activeElement.closest('.tabw')?.querySelector('.tx')?.click()
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
addEventListener('keydown', e => { // Ctrl/Cmd+Alt+PageDown/PageUp: next/previous tab (browser tabs keep plain Ctrl+PageDown)
  if ((e.ctrlKey || e.metaKey) && e.altKey && (e.key === 'PageDown' || e.key === 'PageUp') && $('app').classList.contains('on')) { e.preventDefault(); cycleTab(e.key === 'PageDown' ? 1 : -1) }
})
function tabSaveState(k) { try { const s = cm.state.selection.main; tabState.set(k, { a: s.anchor, h: s.head, top: cm.scrollDOM.scrollTop }) } catch (e) {} }
function tabRestoreState(k) {
  const s = tabState.get(k), n = cm.state.doc.length
  if (!s) { cm.scrollDOM.scrollTop = 0; return }
  cm.dispatch({ selection: { anchor: Math.min(s.a, n), head: Math.min(s.h, n) } })
  requestAnimationFrame(() => { cm.scrollDOM.scrollTop = s.top })
}
async function switchTab(name, nosave) { // true = switched, false = blocked/stale (caller keeps focus where it is)
  if (window.suggestionDraft && !await leaveSuggestionDraft()) return false
  if (name?.startsWith('@doc/') || name?.startsWith('@file/')) {
    const entry = projectTabEntry(name), p = docProject
    if (entry.document !== docId) await openDoc(entry.document)
    if (docId !== entry.document || docProject !== p) return false
    return switchTab(entry.name, nosave)
  }
  if (name === activeFile || !docId) return true
  const my = ++tabSeq, dk = docId, epoch = openN
  if (!nosave && !await flushTab(true)) return false // save failed: stay on the dirty tab, nothing discarded
  if (my !== tabSeq || dk !== docId) return false // superseded meanwhile
  clearTimeout(fileT) // old tab's pending timer must not fire into the new tab
  if (nosave) tabDirty = false // delete path: old text is gone by design
  tabSaveState(activeFile)
  if (name && !isTplKey(name) && !lastFiles.some(f => f.name === name)) { try { lastFiles = (await api('GET', `/api/docs/${docId}/files`)).files } catch (e) {} } // fresh list: new upload must not be dropped as 'deleted'
  if (my !== tabSeq || dk !== docId) return false
  if (!name) { activeFile = ''; setT(shadow); cm.dispatch({ effects: editableComp.reconfigure(editMode(tabCanEdit(''))) }); $('cNew').style.display = openedTrashed ? 'none' : ''; $('save').title = ''; paintTabs(); paintOwn(); paintShared(lastShared); gutter(); closePop(); paintOutline(); reanchor(); refreshHl(); tabRestoreState(''); paintErr(); queueRender(); return true }
  let text
  if (isTplKey(name)) {
    const tp = effTpl().find(x => x.name === tabName(name))
    if (my !== tabSeq || dk !== docId) return false
    if (!tp) { toast(t('files.tplGone')); return false }
    tabPins.add(tp.name); text = tp.content || ''
    if (tp.updated_at) tabVersions.set(name, tp.updated_at)
  } else if (!TEXT_EXT.test(name)) {
    const file = lastFiles.find(f => f.name === name)
    text = t('files.binaryInfo', { name, kb: Math.round((file?.size || 0) / 1024) })
  } else {
    let txt
    try { txt = await api('GET', `/api/docs/${dk}/files/${encodeURIComponent(name)}/text`) }
    catch (e) { if (my === tabSeq && dk === docId) toast(e.message); return false }
    if (my !== tabSeq || dk !== docId) return false // late response: must not write into the newer tab
    text = txt.content
    if (txt.version) tabVersions.set(name, txt.version)
  }
  if (my !== tabSeq || dk !== docId || epoch !== openN || tabDirty) return false
  activeFile = name; tabDirty = false; setT(text)
  cm.dispatch({ effects: editableComp.reconfigure(editMode(tabCanEdit(name))) })
  $('cNew').style.display = 'none'
  const readonly = isTplKey(name) ? t('files.tplSharedNote') : t('common.roleReader')
  $('save').textContent = tabCanEdit(name) ? t('docs.saved') : ''
  $('save').title = tabCanEdit(name) ? '' : readonly
  tabSig = ''; paintTabs(); paintOwn(); paintShared(lastShared); gutter(); closePop(); paintOutline()
  cm.dispatch({ effects: setHl.of(RangeSet.of([])) }) // file tab: no main highlights as ghosts
  tabRestoreState(activeFile)
  if (name && (isTplKey(name) || TEXT_EXT.test(name))) offerFileStash(dk, name) // pagehide stash differs from server: opt-in restore, never silent
  paintErr()
  queueRender()
  return true
}
function offerFileStash(dk, name) { // unsent pagehide copy vs fresh server text: user decides (mirror of the main.typ stash flow)
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
    const rq = tabReq(key, text)
    const result = await api('POST', rq.url, rq.body)
    if (docId !== dk) return true // doc switched meanwhile: cache is gone with it
    if (result?.version) tabVersions.set(key, result.version)
    if (isTplKey(key)) { const tp = effTpl().find(x => x.name === tabName(key)); if (tp) { tp.content = text; if (result?.version) tp.updated_at = result.version } }
    if (epoch !== openN) return false
    if (activeFile === key && getT() === text) {
      try { localStorage.removeItem(fileStashKey(dk, key)) } catch (e) {}
      tabDirty = false
      if (!isTplKey(key)) fileCache.delete(key) // bytes stale: next render refetches
      $('save').textContent = t('docs.saved') + wc()
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
    if (isTplKey(key)) {
      await loadTpl(); await loadDocResources(true)
      if (docId !== dk || activeFile !== key) return
      const tp = effTpl().find(x => x.name === tabName(key))
      if (!tp) { toast(t('files.tplGone')); return }
      if (tp.updated_at) tabVersions.set(key, tp.updated_at)
      tabDirty = false; setT(tp.content || '')
    } else {
      const txt = await api('GET', `/api/docs/${dk}/files/${encodeURIComponent(key)}/text`)
      if (docId !== dk || activeFile !== key) return
      if (txt.version) tabVersions.set(key, txt.version)
      tabDirty = false; setT(txt.content)
    }
    try { localStorage.removeItem(fileStashKey(dk, key)) } catch (e) {}
    $('save').textContent = t('docs.saved') + wc()
    gutter(); paintOutline(); paintErr(); queueRender()
  } catch (e) { toast(e.message) }
}
function tabLive() { // compiler copy follows typing: the preview updates before the save lands
  const txt = getT()
  if (isTplKey(activeFile)) { const tp = effTpl().find(x => x.name === tabName(activeFile)); if (tp) tp.content = txt }
  else { const c = fileCache.get(activeFile); fileCache.set(activeFile, { mtime: c?.mtime ?? lastFiles.find(f => f.name === activeFile)?.mtime ?? 0, bytes: new TextEncoder().encode(txt) }) }
  queueRender(); queueTabs()
}
function queueFileSave() { // file/template tab: only that text + preview, no Yjs
  clearTimeout(fileT)
  if (!tabCanEdit(activeFile)) return // shared read-only: no save timer
  tabDirty = true
  $('save').textContent = '…' + wc()
  const dk = docId, key = activeFile
  fileT = setTimeout(async () => {
    if (docId !== dk || activeFile !== key) return // switched meanwhile: the newer tab owns the editor
    if (await flushTab()) queueRender()
  }, SAVE_MS)
}
const fileNameOk = (raw, ext) => { // clean name, forced text extension; '' = unusable
  let n = String(raw || '').trim().replace(/[^A-Za-z0-9._-]+/g, '_')
  if (!n) return ''
  if (!TEXT_EXT.test(n)) n += '.' + ext
  return /^[A-Za-z0-9][A-Za-z0-9._-]{0,59}$/.test(n) && n.toLowerCase() !== 'main.typ' ? n : ''
}
async function refreshFiles() { try { lastFiles = (await api('GET', `/api/docs/${docId}/files`)).files; filesAt = Date.now(); filesDirty = false } catch (e) {} }
function mainAppend(line) { // add a line at the end of main.typ through Yjs (editor, preview and peers follow)
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
const fileStart = ext => ({ json: '{}\n', yaml: '{}\n', yml: '{}\n', toml: '', xml: '<data/>\n', csl: '<?xml version="1.0" encoding="utf-8"?>\n<style xmlns="http://purl.org/net/xbiblio/csl" version="1.0">\n  <info><title>Style</title><id>https://example.com/style</id></info>\n  <citation><layout><text variable="title"/></layout></citation>\n</style>\n' })[ext] || ''
async function chooseFileType() {
  const labels = [t('files.type_typ'), t('files.type_bib'), t('files.type_csv'), t('files.type_tsv'), t('files.type_json'), t('files.type_yaml'), t('files.type_toml'), t('files.type_xml'), t('files.type_txt'), t('files.type_csl')]
  const i = await askPick(t('files.chooseType'), FILE_TYPES.map((ext, i) => ['.' + ext, labels[i]]))
  return Number.isInteger(i) && i >= 0 && i < FILE_TYPES.length ? '.' + FILE_TYPES[i] : null
}
async function tabAdd() {
  const id = docProject, doc = docId, epoch = openN
  try {
    const project = projects.find(p => p.id === id) || (id ? await api('GET', `/api/projects/${id}`) : null)
    if (docId !== doc || openN !== epoch || docProject !== id) return
    if (project && projectEditable(project)) await projectMenu(project)
    else toast(t('projects.contextGone'))
  } catch (error) { toast(error.message) }
}
async function deleteFile(name) { // undo toast keeps a way back (text: content restored; binary: from cache)
  const cached = fileCache.get(name)
  let txt = null
  if (TEXT_EXT.test(name)) { try { txt = (name === activeFile ? getT() : (await api('GET', `/api/docs/${docId}/files/${encodeURIComponent(name)}/text`)).content) } catch (e) {} }
  try {
    await api('DELETE', `/api/docs/${docId}/files/${encodeURIComponent(name)}`)
    if (name === activeFile) await switchTab('', true)
    tabSig = ''; queueRender()
    toast(t('files.deleted'), async () => {
      try {
        if (txt !== null) await api('POST', `/api/docs/${docId}/files/${encodeURIComponent(name)}/text`, { content: txt })
        else if (cached && cached.bytes) {
          const fd = new FormData(); fd.append('f', new Blob([cached.bytes]), name)
          await fetch(`/api/docs/${docId}/files`, { method: 'POST', body: fd }); filesDirty = true
        }
        tabSig = ''; queueRender()
      } catch (e) { toast(e.message) }
    }, t('files.undo'))
  } catch (e) { toast(e.message) }
}
async function askDeleteFile(name) {
  if (await ask(t('files.delConfirm', { name }), { noInput: true, ok: t('common.delete'), danger: true })) deleteFile(name)
}
let imgIns = false // only via image button, not via manager upload
let pendingReplace = '' // Round5 #4: one-shot chip target - the next picked file replaces this file's content inside the change session
function insImage(name) { // #image() at cursor
  if (!cm.state.facet(EditorView.editable)) { toast(t('projects.readonly')); return }
  const m = cm.state.selection.main, ins = `#image("${name}", width: 80%)`
  cm.dispatch({ changes: { from: m.from, to: m.to, insert: ins }, selection: { anchor: m.from + ins.length } })
  cm.focus()
}
async function upFile(f) { // upload, returns name ('' on error)
  const fd = new FormData(); fd.append('f', f)
  const r = await fetch(`/api/docs/${docId}/files`, { method: 'POST', body: fd })
  filesDirty = true
  if (!r.ok) { const d = ((await r.json().catch(() => ({}))).detail || r.statusText); toast(t('files.uploadFail', { msg: d }), () => upFile(f), t('common.retry')); return '' }
  return (await r.json()).name
}
const TEXT_UP = /\.(typ|bib|csv|tsv|json|yaml|yml|toml|xml|txt|csl)$/i // text file: save + open as tab (no #image)
async function upText(f) { // .typ/.bib/.csv as file text (backend creates, max 200 KB)
  const txt = await f.text()
  if (txt.length > 200 * 1024) { toast(t('files.maxText')); return '' }
  const name = f.name.replace(/[^A-Za-z0-9._-]+/g, '_')
  await api('POST', `/api/docs/${docId}/files/${encodeURIComponent(name)}/text`, { content: txt })
  return name
}
$('imgBtn').onclick = () => { imgIns = true; $('imgPick').click() }
$('imgPick').addEventListener('cancel', () => { pendingReplace = '' }) // picker dismissed: the one-shot swap must not leak into the next upload
$('imgPick').onchange = async () => {
  const f = $('imgPick').files[0]; $('imgPick').value = ''
  if (!f || !docId) return
  const swap = pendingReplace; pendingReplace = '' // one-shot: never leaks into the next pick
  try {
    if (swap && window.changeSession) { // Round5 #4: chip replace swaps the content inside the package
      if (await sessionReplaceFile(swap, f)) { imgIns = false; queueRender(); return }
    }
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
      if (name && /\.(png|jpe?g|svg|gif|webp|avif|bmp|ico|pdf)$/i.test(name)) insImage(name)
    } catch (err) { toast(err.message) }
  }
  if (last) switchTab(last) // text drop: show file at once
  queueRender()
})
cm.contentDOM.addEventListener('paste', async e => { // paste screenshot/image: upload + #image() at cursor
  const imgs = [...((e.clipboardData && e.clipboardData.files) || [])].filter(f => /^image\//.test(f.type))
  if (!imgs.length || !docId || tplName || openedTrashed || docRole === 'reviewer') return
  e.preventDefault()
  toast(imgs.length > 1 ? t('files.uploadingMany', { n: imgs.length }) : t('files.uploadingOne'))
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

$('tabs').addEventListener('wheel', e => {
  const bar = $('tabs')
  if (e.ctrlKey || bar.scrollWidth <= bar.clientWidth) return
  const delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY
  if (!delta) return
  e.preventDefault(); bar.scrollLeft += delta * (e.deltaMode === 1 ? 24 : e.deltaMode === 2 ? bar.clientWidth : 1)
}, { passive: false })

function updateFileView() {
  const file = !!tplName || !!activeFile
  document.body.classList.toggle('file-view', file)
  if (file) { clearTimeout(renderT); ++renderN }
  $('viewSeg').style.display = file || !docId ? 'none' : ''
  $('pvTools').style.display = file || !docId ? 'none' : ''
  const filename = tplName || (activeFile ? tabName(activeFile) : 'main.typ')
  const extension = filename.split('.').pop().toLowerCase()
  paintImageFile(filename)
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
