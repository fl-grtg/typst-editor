// One working copy for all files in a project; source writes stay on the normal path outside it.
window.changeSession = null
let packageList = [], packageLoad = 0, sessionSequence = 0
const sessionKey = f => [f.kind, f.doc_id || '', f.path].join(':')
const sessionCurrent = () => ({ kind: !activeFile ? 'document' : isTplKey(activeFile) ? 'resource' : 'file', doc_id: !activeFile || !isTplKey(activeFile) ? docId : '', path: activeFile ? tabName(activeFile) : 'main.typ' })
const sessionUrl = s => '/api/projects/' + s.project + '/proposals' + (s.package ? '/' + s.package.id : '')
function sessionRuntime(file) {
  const item = { ...file, id: file.id || 'draft_' + ++sessionSequence }
  if (item.action === 'modify' && item.base == null) throw Error(t('comments.suggestionConflict'))
  if (!item.binary) {
    item.state = EditorState.create({ doc: item.base || '' })
    item.delta = item.state.changes([])
    if (item.action === 'modify' && item.changes?.length && item.changes.every(c => {
      const base = item.base || '', at = base.indexOf(c.old_string)
      return at >= 0 && base.lastIndexOf(c.old_string) === at
    })) {
      const base = item.base || '' // corrupt stash/proposal with null base: the conflict error stays a clean message, not a TypeError
      const edits = item.changes.map(c => {
        const from = base.indexOf(c.old_string), span = diffSpan(c.old_string, c.new_string)
        return { from: from + span.a, to: from + c.old_string.length - span.b, insert: c.new_string.slice(span.a, c.new_string.length - span.b) }
      })
      item.delta = item.state.changes(edits)
    } else if (item.content !== item.base && item.content != null) {
      const span = diffSpan(item.base || '', item.content)
      item.delta = item.state.changes({ from: span.a, to: (item.base || '').length - span.b, insert: item.content.slice(span.a, item.content.length - span.b) })
    }
  }
  return item
}
function sessionChanged(f) { // Round5 High #3: the painted-set decision lives here alone (sidebar rows, PATCH/POST payloads, accept gating read it)
  if (f.action !== 'modify') return true // add/delete/rename always carry content
  if (f.content == null || f.content === f.base) return false
  return !String(f.id || '').startsWith('draft_') || !!(f.delta && !f.delta.empty) // server ids are backend-validated; draft entries must show a real delta (a wrong-buffer record with an empty delta is a false positive, never paint or send it)
}
function sessionFiles(s = window.changeSession) {
  if (!s) return []
  return [...s.files.values()].filter(f => sessionChanged(f)).map(f => {
    const { state, delta, csvBefore, ...plain } = f
    return plain
  })
}
const sessionStashKey = s => 'typst-package-' + user + '-' + s.project + (s.package ? '-' + s.package.id : '')
let packageDraftDb, packageDraftQueue = Promise.resolve(), sessionStashTimer = 0
function packageDraft(method, key, value) {
  const run = async () => {
    packageDraftDb ||= new Promise((resolve, reject) => {
      const request = indexedDB.open('typst-proposal-drafts', 1)
      request.onupgradeneeded = () => request.result.createObjectStore('drafts')
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
    const database = await packageDraftDb
    return new Promise((resolve, reject) => {
      const tx = database.transaction('drafts', method === 'get' ? 'readonly' : 'readwrite', { durability: method === 'get' ? 'default' : 'strict' })
      const store = tx.objectStore('drafts'), request = method === 'put' ? store.put(value, key) : store[method](key)
      tx.oncomplete = () => resolve(request.result)
      tx.onerror = tx.onabort = () => reject(tx.error)
    })
  }
  const result = packageDraftQueue.then(run)
  packageDraftQueue = result.catch(() => {})
  return result
}
async function readSessionDraft(s) {
  const key = sessionStashKey(s)
  try { const saved = await packageDraft('get', key); if (saved) return saved } catch (e) {}
  try { return JSON.parse(localStorage.getItem(key) || 'null') } catch (e) { return null }
}
function sessionStash(immediate = false) {
  const s = window.changeSession
  if (!s || s.busy) return
  clearTimeout(sessionStashTimer)
  const save = async () => {
    const key = sessionStashKey(s), value = { package: s.package && { id: s.package.id, revision: s.package.revision }, title: s.title, files: sessionFiles(s) }
    try {
      await packageDraft('put', key, value)
      try { localStorage.removeItem(key) } catch (e) {}
      s.stashFailed = false
    } catch (e) {
      try { localStorage.setItem(key, JSON.stringify(value)); s.stashFailed = false }
      catch (e) { if (!s.stashFailed) toast(t('comments.draftSaveFailed')); s.stashFailed = true }
    }
  }
  if (immediate) return save()
  sessionStashTimer = setTimeout(save, 250)
}
async function sessionEnsure(identity = sessionCurrent()) {
  const s = window.changeSession, key = sessionKey(identity)
  if (!s) return null
  if (s.files.has(key)) return s.files.get(key)
  let content
  if (identity.kind === 'document') content = identity.doc_id === docId ? shadow : (await api('GET', '/api/docs/' + identity.doc_id)).content
  else if (identity.kind === 'resource') {
    const items = (await api('GET', '/api/projects/' + s.project + '/resources')).resources
    const item = items.find(f => f.name === identity.path)
    if (!item) throw Error(t('files.tplGone'))
    content = item.content
  } else if (TEXT_EXT.test(identity.path)) content = (await api('GET', '/api/docs/' + identity.doc_id + '/files/' + encodeURIComponent(identity.path) + '/text')).content
  else {
    const response = await fetch('/api/docs/' + identity.doc_id + '/files/' + encodeURIComponent(identity.path))
    if (!response.ok) throw Error(response.statusText)
    content = bytesToBase64(new Uint8Array(await response.arrayBuffer()))
  }
  if (window.changeSession !== s) return null
  const file = sessionRuntime({ ...identity, action: 'modify', base: content, content, binary: identity.kind === 'file' && !TEXT_EXT.test(identity.path), changes: [] })
  s.files.set(key, file)
  return file
}
function bytesToBase64(bytes) { let text = ''; for (let i = 0; i < bytes.length; i += 8192) text += String.fromCharCode(...bytes.subarray(i, i + 8192)); return btoa(text) }
function sessionBytes(file, original = false) {
  const value = original ? file.base : file.content
  if (value == null) return null
  return file.binary ? Uint8Array.from(atob(value), c => c.charCodeAt(0)) : new TextEncoder().encode(value)
}
function sessionMainText() {
  const s = window.changeSession, item = s?.files.get(sessionKey({ kind: 'document', doc_id: docId, path: 'main.typ' }))
  return s && !s.original && item ? item.content : activeFile ? shadow : getT()
}
function sessionRecord(changes, oldLen) {
  const s = window.changeSession, f = s?.files.get(sessionKey(sessionCurrent()))
  if (!f || s.original || s.busy) return
  if (!activeFile) for (const th of threads) if (!s.commentRanges.has(th.id)) s.commentRanges.set(th.id, threadEditorRange(th))
  // one mapping loop for every entry (thread-id keys and pending popover targets alike), same semantics as recordSuggestionEdit
  const len = oldLen == null ? changes.length : Math.max(0, Math.min(oldLen, changes.length)) // Round5 High #2: stale popover targets beyond the changeset must not reach mapPos
  if (!activeFile) for (const range of s.commentRanges.values()) { range.from = changes.mapPos(Math.max(0, Math.min(range.from, len)), -1); range.to = changes.mapPos(Math.max(0, Math.min(range.to, len)), 1) }
  f.content = getT()
  f.delta = normalizeSuggestionChanges(f.state, f.content, f.delta.compose(changes))
  if (f.action === 'modify' || f.action === 'rename') f.changes = suggestionChanges(f.base, f.content, f.delta).map((c, i) => ({ ...c, id: f.id + '_' + i }))
  s.dirty = true; s.previewRevision++
  if (window.suggestionPopup) closePop(true)
  else if (popAnchor != null) requestAnimationFrame(movePop)
  queueRender(); sessionStash()
  queueMicrotask(() => { if (window.changeSession === s) { sessionPaint(); paintSuggestionControls(); paintSessionSidebar() } })
}
async function sessionActivate() {
  const s = window.changeSession
  if (!s || s.project !== docProject) return
  let item
  try { item = await sessionEnsure() }
  catch (e) { // Round5 High #2: a package file deleted/failed since the proposal must degrade, never crash the open
    toast(e.message)
    const identity = sessionCurrent(), key = sessionKey(identity)
    if (window.changeSession === s && identity.kind !== 'document' && s.files.has(key)) { s.files.delete(key); s.dirty = true; sessionStash(); return sessionActivate() } // drop the broken file/resource entry once, keep the rest of the session
    if (window.changeSession === s) await endChangeSession(true) // document entry unreadable: close the session without prompts and reopen the plain doc
    return
  }
  if (!item || window.changeSession !== s) return
  const text = s.original ? item.base : item.content
  if (!item.binary) setT(text || '')
  cm.dispatch({ effects: editableComp.reconfigure(editMode(!s.original && !s.busy && !item.binary && item.action !== 'delete' && (!s.package || s.package.author === user || ['owner', 'editor'].includes(docRole)))) })
  tabDirty = false; marks = new Set(); markStyle = ''
  paintFileExtras(); paintCsv(); fmtSync(); sessionPaint(); paintSuggestionControls(); paintSessionSidebar(); queueRender()
}
async function startChangeSession(proposal = null) {
  if (!docProject || openedTrashed || window.changeSession) return
  if (!synced) { toast(t('docs.offlineRetry')); return }
  if (window.suggestionDraft && !await leaveSuggestionDraft()) return
  if (window.suggestionDraft || window.changeSession) return
  if (!await flushTab() || !await flushTpl()) return
  const project = docProject
  await api('GET', '/api/projects/' + project + '/proposals') // membership, not document-only guest access
  const s = { project, files: new Map(), commentRanges: new Map(), package: proposal, title: proposal?.title || '', original: false, dirty: false, busy: false, previewRevision: ++sessionSequence }
  if (proposal) {
    proposal.files.forEach(f => s.files.set(sessionKey(f), sessionRuntime(f)))
    try {
      const saved = await readSessionDraft(s)
      if (saved?.package?.id === proposal.id && saved.package.revision === proposal.revision && saved.files?.length && await ask(t('comments.draftRestore'), { noInput: true })) {
        s.files = new Map(saved.files.map(f => [sessionKey(f), sessionRuntime(f)])); s.dirty = true
      }
    } catch (e) {}
  }
  else {
    try {
      const saved = await readSessionDraft(s)
      if (saved?.files?.length && !saved.package && await ask(t('comments.draftRestore'), { noInput: true })) {
        saved.files.forEach(f => s.files.set(sessionKey(f), sessionRuntime(f))); s.title = saved.title || ''; s.dirty = true
      }
    } catch (e) {}
  }
  if (project !== docProject || window.changeSession) return
  s.libraryBase = (await api('GET', '/api/projects/' + project + '/resources')).resources
  if (project !== docProject || window.changeSession) return
  window.changeSession = s
  await sessionActivate()
  return window.changeSession === s
}
async function saveSessionCorrections() {
  const s = window.changeSession
  if (!s?.package || !s.dirty) return true
  if (s.busy) return false
  s.busy = true; cm.dispatch({ effects: editableComp.reconfigure(editMode(false)) }); paintFileExtras(); paintSuggestionControls()
  try {
    const result = await api('PATCH', sessionUrl(s), { title: s.title, revision: s.package.revision, files: sessionFiles(s) })
    if (window.changeSession !== s) return false
    s.package = result; s.dirty = false; sessionStash(); return true
  } catch (e) { toast(e.message); return false }
  finally { s.busy = false; if (window.changeSession === s) { sessionStash(); const item = s.files.get(sessionKey(sessionCurrent())); cm.dispatch({ effects: editableComp.reconfigure(editMode(!s.original && !item?.binary && item?.action !== 'delete' && (s.package.author === user || ['owner', 'editor'].includes(docRole)))) }); paintFileExtras(); paintSuggestionControls() } }
}
async function submitChangeSession() {
  const s = window.changeSession
  if (!s || s.busy) return false
  if (s.package) return saveSessionCorrections()
  const files = sessionFiles(s)
  if (!files.length) return endChangeSession(true)
  const title = await ask(t('packages.title'), { value: s.title || docTitle, maxLen: 100 })
  if (title == null || window.changeSession !== s) return false
  s.busy = true; cm.dispatch({ effects: editableComp.reconfigure(editMode(false)) }); paintFileExtras(); paintSuggestionControls()
  try {
    await api('POST', sessionUrl(s), { title: title.trim() || t('packages.untitled'), files })
    s.dirty = false; await endChangeSession(true); toast(t('comments.draftSent')); return true
  } catch (e) { toast(e.status === 409 && /^Original (file|passage) changed/.test(e.message) ? t('packages.sourceConflict') : e.message); return false }
  finally { s.busy = false; if (window.changeSession === s) { sessionStash(); await sessionActivate() } paintSuggestionControls() }
}
async function endChangeSession(discard = false) {
  const s = window.changeSession
  if (!s) return true
  if (s.busy && !discard) return false
  if (!discard && s.package && !await saveSessionCorrections()) return false
  if (!discard && !s.package && sessionFiles(s).length) {
    const choice = await askPick(t('comments.draftLeave'), [[t('comments.draftSend'), ''], [t('comments.draftDiscard'), ''], [t('projects.stay'), '']])
    if (window.changeSession !== s || choice !== 0 && choice !== 1) return false
    if (choice === 0) return submitChangeSession()
  }
  window.changeSession = null
  clearTimeout(sessionStashTimer)
  packageDraft('delete', sessionStashKey(s)).catch(() => {})
  try { localStorage.removeItem(sessionStashKey(s)) } catch (e) {}
  filesDirty = true; fileCache.clear(); shadowSig = ''; pvSentSig = ''; pvMapped = false; tabSig = ''
  const current = docId, key = activeFile
  if (current) {
    if (key) {
      if (isTplKey(key)) { try { await loadDocResources(true) } catch (e) { toast(e.message) } }
      activeFile = ''
      if (!await sessionOriginalSwitchTab(key, true)) setT(shadow)
    }
    else setT(shadow)
    cm.dispatch({ effects: editableComp.reconfigure(editMode(tabCanEdit(activeFile))) })
    paintTabs(); paintFileExtras(); paintOutline(); reanchor(); refreshHl(); queueRender()
  }
  paintSuggestionControls(); await sidebar(); return true
}
async function choosePackage() {
  try {
    const project = docProject, epoch = ++packageLoad, previous = window.changeSession
    const response = await api('GET', '/api/projects/' + project + '/proposals')
    if (project !== docProject || epoch !== packageLoad) return
    packageList = response.packages
    const choice = await askPick(t('packages.choose'), [[t('packages.original'), ''], ...packageList.map(p => [p.title,
      t('packages.summary', { author: p.author, files: p.file_count, changes: p.change_count }) + ' · ' + new Date(p.updated_at).toLocaleString() + (p.accepted ? ' · ' + t('packages.partial') : '')])])
    if (choice == null || project !== docProject || window.changeSession !== previous) return
    if (choice === 0) {
      if (previous?.package) { previous.original = true; await sessionActivate() }
      else if (previous) await endChangeSession()
      return
    }
    const selected = packageList[choice - 1]
    if (!selected) return
    if (previous?.package?.id === selected.id) { previous.original = false; await sessionActivate(); return }
    if (previous && !await endChangeSession()) return
    const proposal = await api('GET', '/api/projects/' + project + '/proposals/' + selected.id)
    if (project === docProject) await startChangeSession(proposal)
  } catch (e) { toast(e.message) }
}
// #6: topbar chip opener - entry {project|project_id, title?, id?, author?, updated_at?}
async function openTopPackage(entry) {
  const pid = entry?.project ?? entry?.project_id
  if (!pid) return
  if (entry.id && docProject === pid && window.changeSession?.package?.id === entry.id) return // this package is already active
  if (window.changeSession && !await endChangeSession()) return // standard save/discard prompts
  if (docProject !== pid) {
    const row = [...(lastOwn || []), ...(lastShared || [])].find(x => x.project_id === pid)
    if (!row) { toast(t('projects.openLinkedDoc')); await sidebar(); return } // no visible document of that project
    await openDoc(row.id)
    if (docProject !== pid) return // open failed or raced
  }
  try {
    if (entry.id) await startChangeSession(await api('GET', '/api/projects/' + pid + '/proposals/' + entry.id))
    else await choosePackage() // entry without id: fall back to the in-project picker
  } catch (e) { toast(e.message) }
}
window.openTopPackage = openTopPackage
async function acceptSessionSelection(fileId = '', changeId = '') {
  const s = window.changeSession
  if (!s?.package || s.busy || !await saveSessionCorrections() || window.changeSession !== s) return
  s.busy = true; cm.dispatch({ effects: editableComp.reconfigure(editMode(false)) }); paintFileExtras(); paintSuggestionControls()
  try {
    const proposal = await api('POST', sessionUrl(s) + '/accept', { revision: s.package.revision, file_id: fileId, change_id: changeId })
    if (window.changeSession !== s) return
    const acceptedDocuments = [...s.files.values()].filter(f => f.kind === 'document' && !proposal.files.some(p => sessionKey(p) === sessionKey(f)))
    s.package = proposal; s.files = new Map(proposal.files.map(f => [sessionKey(f), sessionRuntime(f)]))
    if (proposal.files.length) for (const old of acceptedDocuments) {
      const current = await api('GET', '/api/docs/' + old.doc_id)
      if (window.changeSession !== s) return
      s.files.set(sessionKey(old), sessionRuntime({ ...old, action: 'modify', base: current.content, content: current.content, changes: [] }))
    }
    s.commentRanges.clear(); s.dirty = false; s.previewRevision++; s.original = false; filesDirty = true; fileCache.clear(); pvSentSig = ''; closePop(true)
    for (const th of threads) { th.a = null; th.b = null } // accepted text replaced the base: rebuild comment ranges on the fresh shadow
    initRanges(); invalidateCommentCache() // the accepted text reaches shadow via WS: the stale-ordered re-anchor must not stick behind the poll dedupe
    if (!proposal.files.length) { s.busy = false; await endChangeSession(true) }
    else { s.busy = false; await loadDocResources(true); await sessionActivate(); await sidebar() }
  } catch (e) { toast(e.message) }
  finally { s.busy = false; if (window.changeSession === s) await sessionActivate(); paintSuggestionControls() }
}
async function deleteSelectedPackage() {
  const s = window.changeSession
  if (!s?.package || s.busy || !await ask(t('packages.deleteConfirm'), { noInput: true, danger: true }) || window.changeSession !== s) return
  s.busy = true; paintSuggestionControls()
  try { await api('DELETE', sessionUrl(s)); await endChangeSession(true) } catch (e) { toast(e.message) }
  finally { s.busy = false; paintSuggestionControls() }
}
function sessionChangeRanges(file) {
  const ranges = []
  if (!file.delta) return ranges
  file.delta.iterChanges((from, to, a, b) => ranges.push({ from, to, a, b, old: (file.base || '').slice(from, to), next: (file.content || '').slice(a, b) }))
  return ranges
}
class PackageDeletion extends WidgetType {
  constructor(range, index) { super(); this.range = range; this.index = index }
  get lineBreaks() { return this.range.old.split('\n').length - 1 }
  eq(other) { return other instanceof PackageDeletion && this.range.old === other.range.old && this.index === other.index }
  toDOM() {
    const node = el('span', 'cm-hl cm-suggestion suggestionDeleted', this.range.old)
    node.contentEditable = 'false'; node.dataset.packageChange = this.index
    node.tabIndex = 0; node.setAttribute('role', 'button'); node.setAttribute('aria-label', t('comments.suggestMode'))
    node.onmousedown = e => { e.preventDefault(); e.stopPropagation(); openSessionChange(this.index) }
    node.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); e.stopPropagation(); openSessionChange(this.index) } }
    return node
  }
}
function sessionPaint() {
  const s = window.changeSession, f = s?.files.get(sessionKey(sessionCurrent()))
  if (!s) return
  const marks = !activeFile ? threadHighlights() : []
  // Opening a document briefly installs an empty buffer before its session text.
  // Decorations belong to the session buffer, never to that intermediate state.
  if (!s.original && f && !f.binary && getT() === (f.content || '')) sessionChangeRanges(f).forEach((r, i) => {
    if (r.old) marks.push(Decoration.widget({ widget: new PackageDeletion(r, i), side: -1 }).range(r.a))
    if (r.b > r.a) marks.push(Decoration.mark({ class: 'cm-hl cm-draft-change', attributes: { 'data-package-change': String(i) } }).range(r.a, r.b))
  })
  cm.dispatch({ effects: setHl.of(RangeSet.of(marks, true)) })
  gutter()
  if (!csvGrid.hidden) csvPaintSelection()
}
function sessionCellChanged(r, c) {
  const s = window.changeSession, f = s?.files.get(sessionKey(sessionCurrent()))
  if (!f || s.original || f.binary) return false
  const before = f.csvBefore ||= parseCsv(f.base || '', csvDelimiter)
  return (before[r]?.[c] || '') !== (csvRows[r]?.[c] || '')
}
function openSessionChange(index) {
  const s = window.changeSession, file = s?.files.get(sessionKey(sessionCurrent())), range = file && sessionChangeRanges(file)[index]
  if (!range || s.original) return
  const nodes = [...cm.dom.querySelectorAll('[data-package-change]')].filter(n => n.dataset.packageChange === String(index))
  openPop(cm.state.doc.lineAt(range.a).number, false, '', { session: true, index, from: range.a, to: range.b, nodes })
}
function sessionCard(box) {
  const s = window.changeSession, file = s?.files.get(sessionKey(sessionCurrent())), range = file && sessionChangeRanges(file)[box.index]
  if (!range) { closePop(true); return }
  const card = el('div', 'th'), header = el('div', 'hd')
  header.append(el('b', 'nm', s.package?.author || user), el('span', 'tm', t('comments.suggestionpending')))
  if (s.package && ['owner', 'editor'].includes(docRole)) {
    const accept = icoBtn('ib', ICO_CHECK); accept.title = t('comments.accept')
    accept.onclick = async () => {
      if (!await saveSessionCorrections()) return
      const actual = s.files.get(sessionKey(sessionCurrent()))
      const match = actual?.changes?.find(c => { const start = actual.base.indexOf(c.old_string); return start >= 0 && range.from >= start && range.to <= start + c.old_string.length })
      if (match) await acceptSessionSelection(actual.id, match.id)
      else toast(t('comments.suggestionConflict'))
    }
    header.append(accept)
  }
  const remove = icoBtn('ib', ICO_TRASH); remove.title = t('comments.draftDiscard')
  remove.onclick = () => { if (!s.busy) { closePop(true); cm.dispatch({ changes: { from: range.a, to: range.b, insert: range.old } }) } }
  if (!s.package || s.package.author === user || ['owner', 'editor'].includes(docRole)) header.append(remove)
  card.append(header)
  if (range.old) card.append(el('div', 'qt suggestionDeleted', range.old))
  if (range.next) card.append(el('div', 'tx', range.next))
  $('pop').append(card)
  if (!activeFile) threads.filter(th => { const r = threadEditorRange(th); return r.from <= range.b && r.to >= range.a }).forEach(th => $('pop').append(threadCard(th)))
}
function paintSessionSidebar() {
  const s = window.changeSession
  document.querySelectorAll('.package-files').forEach(node => node.remove())
  document.querySelectorAll('.package-modified').forEach(node => node.classList.remove('package-modified'))
  if (!s) return
  const group = el('div', 'package-files')
  group.append(el('b', 'package-caption', s.package?.title || t('packages.draft')))
  sessionFiles(s).forEach(file => {
    const existing = [...document.querySelectorAll('[data-package-key]')].find(row => row.closest('.project-group')?.dataset.projectId === s.project && row.dataset.packageKey === sessionKey(file))
    if (existing) { existing.classList.add('package-modified'); return }
    const documentTitle = file.kind === 'document' && (projects.find(p => p.id === s.project)?.documents?.find(d => d.id === file.doc_id)?.title || (file.doc_id === docId ? docTitle : ''))
    const name = documentTitle ? documentTitle.replace(/\.typ$/i, '') + '.typ' : file.path
    const row = el('div', 'doc sub package-file'), label = el('span', 't', (file.action === 'add' ? '+ ' : file.action === 'delete' ? '− ' : '') + name)
    if (file.action === 'delete' || file.action === 'rename') label.classList.add('suggestionDeleted')
    row.append(label); row.title = file.action === 'rename' ? file.path + ' → ' + file.target : name
    row.onclick = () => sessionOpenFile(file)
    if (s.package && ['owner', 'editor'].includes(docRole)) projectAction(row, ICO_CHECK, t('packages.acceptFile'), () => acceptSessionSelection(file.id))
    if (!s.package || s.package.author === user || ['owner', 'editor'].includes(docRole)) projectAction(row, ICO_TRASH, t('comments.draftDiscard'), async () => {
      if (s.busy || s.original || window.changeSession !== s) return
      if (file.action === 'add') s.files.delete(sessionKey(file))
      else s.files.set(sessionKey(file), sessionRuntime({ ...file, action: 'modify', content: file.base, changes: [], target: undefined }))
      s.dirty = true; s.previewRevision++; sessionStash(); paintSessionSidebar()
      if (file.action === 'add' && sessionKey(file) === sessionKey(sessionCurrent())) await switchTab('')
      else await sessionActivate()
    })
    group.append(row)
  })
  // kept drafts belong to the project they were made in (never the top root): attach under that project's group, own or shared
  const home = [...document.querySelectorAll('#own .project-group, #shared .project-group')].find(g => g.dataset.projectId === s.project)
  if (home) {
    const head = home.querySelector('.fhd')
    home.insertBefore(group, head?.nextSibling || null) // visible even while the group is collapsed
    return
  }
  group.prepend(el('span', 'package-caption origin-gone', t('packages.originGone'))) // project list lagging (e.g. left)/project gone: keep the draft reachable, say where it came from
  $('own').prepend(group)
}
async function sessionOpenFile(file) {
  if (file.doc_id && file.doc_id !== docId) { await openDoc(file.doc_id); if (docId !== file.doc_id) return }
  await switchTab(file.kind === 'document' ? '' : file.kind === 'resource' ? TPLK + file.path : file.path)
}
async function sessionAddFile(file, resource = false) {
  const s = window.changeSession
  if (!s || s.original || s.busy) return ''
  if (file.size > (TEXT_EXT.test(file.name) ? 200 * 1024 : 10 * 1024 * 1024)) throw Error(t('docs.maxKb'))
  const name = file.name.replace(/^[.]+/, '').replace(/[^A-Za-z0-9._ ()-]/g, '_').slice(0, resource ? 100 : 240)
  const identity = { kind: resource ? 'resource' : 'file', doc_id: resource ? '' : docId, path: name }
  if (s.files.has(sessionKey(identity)) || (resource ? effTpl().some(f => f.name === name) : lastFiles.some(f => f.name === name))) throw Error(t('common.nameExists'))
  const binary = !TEXT_EXT.test(name), content = binary ? bytesToBase64(new Uint8Array(await file.arrayBuffer())) : await file.text()
  if (window.changeSession !== s) return ''
  s.files.set(sessionKey(identity), sessionRuntime({ ...identity, action: 'add', base: null, content, binary, changes: [] }))
  s.dirty = true; s.previewRevision++; sessionStash(); tabSig = ''; paintTabs(); paintSessionSidebar(); queueRender(); return name
}
async function sessionReplaceFile(name, file) { // Round5 #4: swap an existing file's content inside the package (backend file modify: base + content, changes [])
  const s = window.changeSession
  if (!s || s.original || s.busy) return ''
  if (file.size > 10 * 1024 * 1024) throw Error(t('docs.maxKb'))
  const identity = { kind: 'file', doc_id: docId, path: name }, key = sessionKey(identity)
  if (!s.files.has(key) && !lastFiles.some(x => x.name === name)) throw Error(t('packages.fileAbsent'))
  const had = s.files.get(key)
  const base = had?.base ?? (await sessionEnsure(identity))?.base
  if (window.changeSession !== s || base == null) return ''
  const binary = had?.binary ?? !TEXT_EXT.test(name)
  const content = binary ? bytesToBase64(new Uint8Array(await file.arrayBuffer())) : await file.text()
  if (window.changeSession !== s) return ''
  const entry = sessionRuntime({ ...identity, id: had?.id, action: 'modify', base, content, binary, changes: [] }) // keep the proposal file id: the PATCH updates the existing entry
  if (!binary) entry.changes = suggestionChanges(entry.base, entry.content, entry.delta).map((c, i) => ({ ...c, id: entry.id + '_' + i }))
  s.files.set(key, entry)
  s.dirty = true; s.previewRevision++; sessionStash(); tabSig = ''; paintTabs(); paintSessionSidebar(); queueRender()
  if (activeFile === name) await sessionActivate()
  return name
}
const reviewTools = el('span', 'fmt package-tools')
const reviewButton = icoBtn('ib', svgI('<path d="M3 3h10v10H3zM5 6h6M5 9h3"/>'))
const originalButton = icoBtn('ib', svgI('<path d="M1 8s2-4 7-4 7 4 7 4-2 4-7 4-7-4-7-4z"/><circle cx="8" cy="8" r="2"/>'))
const acceptPackageButton = icoBtn('ib', ICO_CHECK), acceptFileButton = icoBtn('ib', svgI('<path d="M3 1h7l3 3v10H3zM5 9l2 2 4-4"/>'))
const exitPackageButton = icoBtn('ib', ICO_X), deletePackageButton = icoBtn('ib', ICO_TRASH)
const packageActions = icoBtn('ib', ICO_MORE)
const packageMode = el('span', 'package-mode sr-only')
reviewTools.append(packageMode, reviewButton, originalButton, packageActions, exitPackageButton)
packageActions.onclick = async () => {
  const s = window.changeSession
  if (!s || s.busy) return
  const actions = [acceptFileButton, acceptPackageButton, deletePackageButton].filter(button => !button.hidden && !button.disabled)
  const choice = await askPick(s.package?.title || t('packages.draft'), actions.map(button => [button.title, '']))
  if (choice != null && window.changeSession === s && !s.busy) actions[choice]?.click()
}
$('tools').insertBefore(reviewTools, $('tools').querySelector('.tsp'))
reviewButton.onclick = choosePackage
originalButton.onclick = async () => { const s = window.changeSession; if (s && !s.busy) { s.original = !s.original; await sessionActivate() } }
acceptPackageButton.onclick = () => acceptSessionSelection()
acceptFileButton.onclick = () => { const f = window.changeSession?.files.get(sessionKey(sessionCurrent())); if (f) acceptSessionSelection(f.id) }
exitPackageButton.onclick = () => endChangeSession()
deletePackageButton.onclick = deleteSelectedPackage
const oldSuggestionControls = paintSuggestionControls
paintSuggestionControls = () => {
  oldSuggestionControls()
  const s = window.changeSession, member = docRole === 'owner' || projects.some(p => p.id === docProject && p.role !== 'guest')
  const available = !!docProject && member && !window.suggestionDraft && !openedTrashed && !tplName
  reviewTools.hidden = !available
  packageMode.hidden = !s
  packageMode.textContent = s ? s.package?.title || t('packages.draft') : ''
  packageMode.title = packageMode.textContent
  const labels = [t('packages.choose'), t('packages.original'), t('packages.acceptPackage'), t('packages.acceptFile'), t('packages.delete'), t('packages.exit')]
  ;[reviewButton, originalButton, acceptPackageButton, acceptFileButton, deletePackageButton, exitPackageButton].forEach((button, i) => { button.title = labels[i]; button.setAttribute('aria-label', labels[i]); button.disabled = !!s?.busy })
  packageActions.title = t('shell.menuMore'); packageActions.setAttribute('aria-label', packageActions.title); packageActions.disabled = !!s?.busy
  packageActions.hidden = !s?.package || !['owner', 'editor'].includes(docRole) && s.package.author !== user
  reviewButton.classList.toggle('on', !!s?.package); reviewButton.title = s?.package?.title || labels[0]
  originalButton.hidden = !s?.package; originalButton.classList.toggle('on', !!s?.original); originalButton.setAttribute('aria-pressed', String(!!s?.original))
  acceptPackageButton.hidden = acceptFileButton.hidden = !s?.package || !['owner', 'editor'].includes(docRole)
  const currentFile = s?.files.get(sessionKey(sessionCurrent()))
  acceptFileButton.disabled = !!s?.busy || !currentFile || !sessionFiles(s).some(f => f.id === currentFile.id)
  deletePackageButton.hidden = !s?.package || s.package.author !== user && docRole !== 'owner'
  exitPackageButton.hidden = !s
  if (available) {
    $('suggestionToggle').hidden = !!s?.package
    $('suggestionToggle').classList.toggle('on', !!s); $('suggestionToggle').setAttribute('aria-pressed', String(!!s))
    $('suggestionToggle').onclick = () => s ? endChangeSession() : startChangeSession().catch(e => toast(e.message))
  }
}
const sessionOriginalSwitchTab = switchTab
switchTab = async (name, nosave) => {
  const s = window.changeSession
  if (!s) return sessionOriginalSwitchTab(name, nosave)
  if (s.busy) return false
  if (name?.startsWith('@doc/') || name?.startsWith('@file/')) {
    const entry = projectTabEntry(name)
    if (entry.document !== docId) await openDoc(entry.document)
    if (docId !== entry.document || window.changeSession !== s) return false
    name = entry.name
  }
  const identity = { kind: !name ? 'document' : isTplKey(name) ? 'resource' : 'file', doc_id: !name || !isTplKey(name) ? docId : '', path: name ? tabName(name) : 'main.typ' }
  if (!s.files.has(sessionKey(identity))) {
    const switched = await sessionOriginalSwitchTab(name, nosave)
    if (!switched || window.changeSession !== s) return false
  } else { tabSaveState(activeFile); activeFile = name; tabDirty = false; tabSig = '' }
  await sessionActivate(); paintTabs(); return true
}
const sessionOriginalOpenDoc = openDoc
openDoc = async id => {
  const s = window.changeSession
  if (s) {
    if (s.busy) return
    const target = await api('GET', '/api/docs/' + id)
    if (target.project_id !== s.project && !await endChangeSession()) return
  }
  await sessionOriginalOpenDoc(id)
  if (window.changeSession) await sessionActivate()
}
const sessionOriginalOpenTpl = openTpl
openTpl = async name => { if (window.changeSession && !await endChangeSession()) return; return sessionOriginalOpenTpl(name) }
const sessionOriginalRefreshHl = refreshHl
refreshHl = () => window.changeSession ? sessionPaint() : sessionOriginalRefreshHl()
const sessionOriginalTabItems = tabItems
tabItems = () => {
  const items = sessionOriginalTabItems(), s = window.changeSession
  if (!s) return items
  for (const f of s.files.values()) {
    const item = f.kind === 'document' ? f.doc_id === docId ? '' : '@doc/' + f.doc_id : f.kind === 'resource' ? TPLK + f.path : f.doc_id === docId ? f.path : '@file/' + f.doc_id + '/' + f.path
    if (!items.includes(item)) items.push(item)
  }
  return items
}
const sessionOriginalPvRes = pvResTpl
pvResTpl = () => {
  const s = window.changeSession
  if (!s) return sessionOriginalPvRes()
  const result = new Map((s.libraryBase || projectResources()).map(f => [f.name, { ...f }]))
  if (!s.original) for (const f of s.files.values()) if (f.kind === 'resource') {
    if (f.action === 'delete' || f.action === 'rename') result.delete(f.path)
    if (f.content != null && f.action !== 'delete') result.set(f.action === 'rename' ? f.target : f.path, { name: f.action === 'rename' ? f.target : f.path, content: f.content })
  }
  return [...result.values()]
}
const sessionOriginalPvFiles = pvFiles
pvFiles = async () => {
  const s = window.changeSession, pf = await sessionOriginalPvFiles()
  if (!pf || !s || s !== window.changeSession) return pf
  for (const f of s.files.values()) if (f.kind === 'file' && f.doc_id === docId) {
    const bytes = sessionBytes(f, s.original)
    if (!s.original && (f.action === 'delete' || f.action === 'rename')) fileCache.delete(f.path)
    if (bytes && (s.original || f.action !== 'delete')) fileCache.set(!s.original && f.action === 'rename' ? f.target : f.path, { bytes, mtime: 'proposal' })
  }
  pf.tpl = pvResTpl(); pf.sig += '\u0002package:' + s.previewRevision + ':' + s.original
  return pf
}
const sessionOriginalUpFile = upFile, sessionOriginalUpText = upText
const stageToPackage = async file => { // Round5 #4: suggest-mode drafts must never write the live project - offer the package flow instead
  if (!window.suggestionDraft) return false
  if (!await leaveSuggestionDraft()) return true // user keeps the draft: the upload is abandoned
  if (window.suggestionDraft || window.changeSession || !(await startChangeSession())) return true
  try { await sessionAddFile(file) } catch (e) { toast(e.message) }
  return true
}
upFile = async file => {
  if (window.changeSession) return sessionAddFile(file)
  return (await stageToPackage(file)) ? '' : sessionOriginalUpFile(file)
}
upText = async file => {
  if (window.changeSession) return sessionAddFile(file)
  return (await stageToPackage(file)) ? '' : sessionOriginalUpText(file)
}
const sessionOriginalDeleteEntry = deleteProjectEntry, sessionOriginalRenameEntry = renameProjectEntry
const originalDeleteProjectEntry = async (project, name, document, resource) => {
  const s = window.changeSession
  if (!s || s.project !== project?.id) return sessionOriginalDeleteEntry(project, name, document, resource)
  if (s.original || s.busy) return
  const f = await sessionEnsure({ kind: resource ? 'resource' : 'file', doc_id: resource ? '' : document, path: name })
  if (!f || window.changeSession !== s) return
  if (f.action === 'add') s.files.delete(sessionKey(f))
  else { f.action = 'delete'; f.content = null; f.changes = [] }
  s.dirty = true; s.previewRevision++; sessionStash(); paintSessionSidebar(); await sessionActivate()
}
deleteProjectEntry = async (project, name, document, resource) => { // Round5 #4: suggest-mode deletes stage into a package too - the suggester's trash is never touched (accept archives it in the project owner's trash)
  if (!window.changeSession && window.suggestionDraft) {
    if (!await leaveSuggestionDraft()) return
    if (window.suggestionDraft || !await startChangeSession()) return
    return deleteProjectEntry(project, name, document, resource) // session is open now: this same override stages the delete
  }
  return originalDeleteProjectEntry(project, name, document, resource)
}
const sessionOriginalDeleteFile = deleteFile
deleteFile = async name => { // Round5 #4: media-manager chip delete must stage - the plain DELETE endpoint is source-blocked in-session and would live-write in suggest mode
  if (window.changeSession || window.suggestionDraft) {
    try { await deleteProjectEntry({ id: docProject }, name, docId, false) } catch (e) { toast(e.message) }
    return
  }
  return sessionOriginalDeleteFile(name)
}
renameProjectEntry = async (project, name, document, resource) => {
  const s = window.changeSession
  if (!s || s.project !== project?.id) return sessionOriginalRenameEntry(project, name, document, resource)
  if (s.original || s.busy) return
  const target = await ask(t('projects.copyName'), { value: name, maxLen: 240 })
  if (!target?.trim() || target.trim() === name) return
  const f = await sessionEnsure({ kind: resource ? 'resource' : 'file', doc_id: resource ? '' : document, path: name })
  if (!f || window.changeSession !== s) return
  f.action = 'rename'; f.target = target.trim(); s.dirty = true; s.previewRevision++; sessionStash(); paintSessionSidebar(); queueRender()
}
const sessionOriginalNewResource = newProjectResource
newProjectResource = async project => {
  if (!window.changeSession || window.changeSession.project !== project) return sessionOriginalNewResource(project)
  const ext = await chooseFileType(); if (!ext) return
  const name = await ask(t('files.newFileHead'), { value: 'file' + ext, maxLen: 240 }); if (!name?.trim()) return
  const path = name.trim().endsWith(ext) ? name.trim() : name.trim() + ext
  const file = new File([fileStart(ext.slice(1))], path, { type: 'text/plain' })
  const added = await sessionAddFile(file, true); if (added) await switchTab(TPLK + added)
}
addEventListener('pagehide', () => sessionStash(true))
paintSuggestionControls()

const sessionOriginalPaintOwn = paintOwn
paintOwn = () => { sessionOriginalPaintOwn(); paintSessionSidebar() }
const sessionOriginalPaintShared = paintShared
paintShared = list => { sessionOriginalPaintShared(list); paintSessionSidebar() } // shared projects rebuild their rows too: keep the draft group attached
const sessionOriginalCloseView = closeView
closeView = () => { if (window.changeSession) { sessionStash(true); window.changeSession = null } sessionOriginalCloseView(); paintSuggestionControls() }
const sessionOriginalSourceMap = sourceToEditor, sessionOriginalEditorMap = editorToSource
sourceToEditor = (pos, end = false) => {
  const s = window.changeSession, f = s?.files.get(sessionKey(sessionCurrent()))
  if (!s || activeFile || !f?.delta || s.original) return sessionOriginalSourceMap(pos, end)
  const basePos = diffMap(shadow, f.base || '')(Math.min(pos, shadow.length), end) // Round5 High #2: stale source pos must not overflow the changeset (add/empty-base files: changeset length 0)
  return f.delta.mapPos(Math.max(0, Math.min(basePos, f.delta.length)), end ? 1 : -1)
}
editorToSource = (pos, end = false) => {
  const s = window.changeSession, f = s?.files.get(sessionKey(sessionCurrent()))
  if (!s || activeFile || !f?.delta || s.original) return sessionOriginalEditorMap(pos, end)
  const basePos = f.delta.invertedDesc.mapPos(Math.max(0, Math.min(pos, f.delta.invertedDesc.length)), end ? 1 : -1)
  return diffMap(f.base || '', shadow)(basePos, end)
}
const sessionSourceApi = api
api = async (method, url, body, tries) => {
  if (window.changeSession && method !== 'GET' && /^\/api\/(docs|projects|templates|library)(\/|$)/.test(url)
      && !/\/proposals(?:\/|$)/.test(url) && !/\/comments(?:\/|$)/.test(url) && !/\/(render|export)(?:\/|$)/.test(url)) {
    throw Error(t('packages.sourceBlocked'))
  }
  return sessionSourceApi(method, url, body, tries)
}
const sessionUploadProject = uploadProjectFiles
uploadProjectFiles = async (project, files) => {
  if (!window.changeSession) return sessionUploadProject(project, files)
  if (window.changeSession.project !== project.id) throw Error(t('packages.sourceBlocked'))
  for (const file of files) await sessionAddFile(file, TEXT_EXT.test(file.name))
}
const sessionImportUpload = importUpload
importUpload = async file => {
  if (!window.changeSession) return sessionImportUpload(file)
  try { await sessionAddFile(file, TEXT_EXT.test(file.name)) } catch (e) { toast(e.message) }
}
const sessionPullLibrary = pullLibrary
pullLibrary = async (source, target) => {
  const s = window.changeSession
  if (!s) return sessionPullLibrary(source, target)
  if (target.scope !== 'project' || target.project_id !== s.project) throw Error(t('packages.sourceBlocked'))
  const available = source.source_scope === 'personal' ? (await api('GET', '/api/templates')).templates
    : (await api('GET', '/api/projects/' + source.source_project_id + '/resources')).resources
  const root = available.find(f => f.name === source.source)
  if (!root) throw Error(t('files.tplGone'))
  const pending = [root], seen = new Set()
  let added = ''
  while (pending.length && window.changeSession === s) {
    const item = pending.shift()
    if (seen.has(item.name)) continue
    seen.add(item.name)
    if (!s.files.has(sessionKey({ kind: 'resource', path: item.name })) && !effTpl().some(f => f.name === item.name)) {
      const name = await sessionAddFile(new File([item.content], item.name), true)
      if (item === root) added = name
    }
    for (const match of item.content.matchAll(/"([^"\n]+)"/g)) {
      const dependency = available.find(f => f.name === match[1])
      if (dependency) pending.push(dependency)
    }
  }
  return added || root.name
}

const sessionOriginalLinePop = openLinePop
openLinePop = line => {
  const s = window.changeSession, f = s?.files.get(sessionKey(sessionCurrent()))
  if (!s || s.original || !f) return sessionOriginalLinePop(line)
  const index = sessionChangeRanges(f).findIndex(r => cm.state.doc.lineAt(r.a).number === line)
  if (index >= 0) openSessionChange(index)
  else openPop(line, false)
}
