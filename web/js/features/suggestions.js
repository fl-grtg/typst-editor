function suggestionCard(th, fresh, doc, epoch) {
  const card = el('div', 'suggestionCard')
  const status = { pending: t('comments.suggestionpending'), accepted: t('comments.suggestionaccepted'), rejected: t('comments.suggestionrejected') }
  card.appendChild(el('b', null, status[th.suggestion_status]))
  if (th.suggestion_status === 'pending') {
    const span = diffSpan(th.suggestion_old, th.replacement)
    const old = th.suggestion_old.slice(span.a, th.suggestion_old.length - span.b)
    const next = th.replacement.slice(span.a, th.replacement.length - span.b)
    if (old) card.append(el('div', 'qt suggestionDeleted', old))
    if (next) card.append(el('div', 'tx', next))
    if (th.a == null || th.conflict) card.append(el('p', null, t('comments.suggestionConflict')))
  }
  if (th.suggestion_status === 'pending' && !openedTrashed && ['owner', 'editor'].includes(docRole)) {
    const actions = el('div', 'rr')
    const button = el('button', null, t('comments.accept'))
    button.onclick = () => decideSuggestion(th, 'accept', doc, epoch)
    actions.appendChild(button)
    card.appendChild(actions)
  }
  return card
}
async function decideSuggestion(th, action, doc = docId, epoch = openN) {
  if (doc !== docId || epoch !== openN) return
  try {
    await api('POST', `/api/docs/${doc}/suggestions/${th.id}/${action}`, {})
    if (doc === docId && epoch === openN) { closePop(true); await refresh('') }
  } catch (e) { toast(e.status === 409 ? t('comments.suggestionConflict') : e.message) }
}
class SuggestionReplacement extends WidgetType {
  constructor(th) {
    super(); this.th = th
    const span = diffSpan(th.suggestion_old, th.replacement)
    this.text = th.replacement.slice(span.a, th.replacement.length - span.b)
  }
  get lineBreaks() { return this.text.split('\n').length - 1 }
  eq(other) { return other instanceof SuggestionReplacement && other.th.id === this.th.id && other.text === this.text }
  toDOM() {
    const node = el('span', 'cm-hl cm-draft-change', this.text)
    node.dataset.suggestionId = this.th.id; node.contentEditable = 'false'
    node.tabIndex = 0; node.setAttribute('role', 'button'); node.setAttribute('aria-label', t('comments.suggestMode'))
    node.onmousedown = e => { e.preventDefault(); e.stopPropagation(); openSuggestionBox(node) }
    node.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openSuggestionBox(node) } }
    return node
  }
}
class DraftDeletion extends WidgetType {
  constructor(range) { super(); this.range = range }
  get lineBreaks() { return this.range.old.split('\n').length - 1 }
  eq(other) { return other instanceof DraftDeletion && other.range.key === this.range.key && other.range.old === this.range.old }
  toDOM() {
    const node = el('span', 'cm-hl cm-suggestion suggestionDeleted', this.range.old)
    node.dataset.suggestionChange = this.range.key
    node.contentEditable = 'false'; node.tabIndex = 0; node.setAttribute('role', 'button')
    node.setAttribute('aria-label', t('comments.suggestMode'))
    node.onmousedown = e => { e.preventDefault(); e.stopPropagation(); openSuggestionBox(node) }
    node.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openSuggestionBox(node) } }
    return node
  }
}
function sourceToEditor(pos, end = false) {
  const draft = window.suggestionDraft
  if (!draft) return pos
  const basePos = diffMap(shadow, draft.base || '')(Math.min(pos, shadow.length), end) // Round5 High #2: stale pos must not overflow the changeset (empty base = changeset length 0)
  return draft.changes.mapPos(Math.max(0, Math.min(basePos, draft.changes.length)), end ? 1 : -1)
}
function editorToSource(pos, end = false) {
  const draft = window.suggestionDraft
  if (!draft) return pos
  const basePos = draft.changes.invertedDesc.mapPos(Math.max(0, Math.min(pos, draft.changes.invertedDesc.length)), end ? 1 : -1)
  return diffMap(draft.base || '', shadow)(basePos, end)
}
function threadEditorRange(th) {
  const draft = window.changeSession && !window.changeSession.original ? window.changeSession : window.suggestionDraft // the active one (session wins)
  const local = draft?.commentRanges.get(th.id)
  const length = cm.state.doc.length
  const clamp = r => ({ from: Math.max(0, Math.min(length, r.from)), to: Math.max(0, Math.min(length, r.to)) })
  if (local) return clamp(local) // Round5 High #2: stored popover targets can trail an edit - clamp them like the derived path below
  return clamp({ from: sourceToEditor(th.a ?? posOfLine(shadow, th.anchor)),
    to: sourceToEditor(th.b ?? th.a ?? posOfLine(shadow, th.anchor), true) })
}
function normalizeSuggestionChanges(base, current, changes) {
  const ranges = []
  changes.iterChanges((from, to, a, b) => {
    const old = base.doc.sliceString(from, to), next = current.slice(a, b), span = diffSpan(old, next)
    if (old !== next) ranges.push({ from: from + span.a, to: to - span.b, insert: next.slice(span.a, next.length - span.b) })
  })
  return base.changes(ranges)
}
function draftRanges(draft) {
  const ranges = [], current = getT()
  draft.changes.iterChanges((from, to, a, b) => ranges.push({ key: from + ':' + to, from, to, a, b, old: draft.base.slice(from, to), next: current.slice(a, b) }))
  return ranges
}
function paintDraftSuggestions() {
  const draft = window.suggestionDraft
  if (!draft) return
  const ranges = threadHighlights()
  for (const r of draftRanges(draft)) {
    if (r.old) ranges.push(Decoration.widget({ widget: new DraftDeletion(r), side: -1 }).range(r.a))
    if (r.b > r.a) ranges.push(Decoration.mark({ class: 'cm-hl cm-draft-change', attributes: { 'data-suggestion-change': r.key } }).range(r.a, r.b))
  }
  cm.dispatch({ effects: setHl.of(RangeSet.of(ranges, true)) })
}
function recordSuggestionEdit(changes, oldLen) {
  const draft = window.suggestionDraft
  draft.changes = normalizeSuggestionChanges(draft.baseState, getT(), draft.changes.compose(changes))
  draft.changed = !draft.changes.empty
  const len = oldLen == null ? changes.length : Math.max(0, Math.min(oldLen, changes.length)) // Round5 High #2: stale popover targets must not reach mapPos
  for (const range of draft.commentRanges.values()) { range.from = changes.mapPos(Math.max(0, Math.min(range.from, len)), -1); range.to = changes.mapPos(Math.max(0, Math.min(range.to, len)), 1) }
  closePop(true); queueRender(); paintOutline()
  queueMicrotask(() => { if (window.suggestionDraft === draft) { paintDraftSuggestions(); gutter(); paintSuggestionControls() } })
}
function openSuggestionBox(node) {
  const draft = window.suggestionDraft
  const range = draft && draftRanges(draft).find(r => r.key === node.dataset.suggestionChange)
  const th = threads.find(th => String(th.id) === node.dataset.suggestionId)
  if (!range && !th) return
  const { from, to } = range ? { from: range.a, to: range.b } : threadEditorRange(th)
  const overlaps = threads.filter(item => {
    if (item.a == null || item.resolved) return false
    const r = threadEditorRange(item)
    return r.from <= to && r.to >= from
  })
  const nodes = cm.dom ? [...cm.dom.querySelectorAll('[data-suggestion-change],[data-suggestion-id]')].filter(item =>
    range ? item.dataset.suggestionChange === range.key : item.dataset.suggestionId === String(th.id)) : [node]
  openPop(cm.state.doc.lineAt(from).number, false, '', { from, to, range, threadIds: overlaps.map(item => item.id), nodes })
}
function openLinePop(line) {
  const draft = window.suggestionDraft
  const ranges = draft ? draftRanges(draft).filter(r => cm.state.doc.lineAt(r.a).number === line) : []
  if (!ranges.length) { openPop(line, false); return }
  const keys = new Set(ranges.map(r => r.key))
  const threadIds = threads.filter(th => cm.state.doc.lineAt(threadEditorRange(th).from).number === line).map(th => th.id)
  const nodes = [...cm.dom.querySelectorAll('[data-suggestion-change]')].filter(node => keys.has(node.dataset.suggestionChange))
  openPop(line, false, '', { from: Math.min(...ranges.map(r => r.a)), to: Math.max(...ranges.map(r => r.b)), ranges, threadIds, nodes })
}
function draftSuggestionCard(range) {
  const card = el('div', 'th'), header = el('div', 'hd')
  const name = el('b', 'nm', user); name.style.color = colOf(user)
  header.append(name, el('span', 'tm', t('comments.suggestionpending')))
  const discard = icoBtn('ib', ICO_TRASH)
  discard.title = t('comments.draftDiscard'); discard.setAttribute('aria-label', discard.title); discard.style.marginLeft = 'auto'
  discard.onclick = () => {
    const draft = window.suggestionDraft
    const current = draft && draftRanges(draft).find(r => r.key === range.key)
    if (!current || draft.busy) return
    closePop(true); cm.dispatch({ changes: { from: current.a, to: current.b, insert: current.old } }); cm.focus()
  }
  if (!openedTrashed && ['owner', 'editor'].includes(docRole)) {
    const accept = icoBtn('ib', ICO_CHECK)
    accept.title = t('comments.accept'); accept.setAttribute('aria-label', accept.title)
    accept.onclick = () => acceptDraftSuggestion(range)
    header.append(accept)
  }
  header.append(discard); card.append(header)
  if (range.old) card.append(el('div', 'qt suggestionDeleted', range.old))
  if (range.next) card.append(el('div', 'tx', range.next))
  return card
}
function renderSuggestionBox(box) {
  const pop = $('pop')
  const keys = (box.ranges || (box.range ? [box.range] : [])).map(r => r.key)
  const ranges = window.suggestionDraft ? draftRanges(window.suggestionDraft).filter(r => keys.includes(r.key)) : []
  ranges.forEach(range => pop.append(draftSuggestionCard(range)))
  const list = threads.filter(th => box.threadIds.includes(th.id))
  list.forEach(th => pop.append(threadCard(th)))
  if (!ranges.length && !list.length) closePop(true)
}
async function acceptDraftSuggestion(range) {
  const draft = window.suggestionDraft, doc = docId, epoch = openN
  if (!draft || draft.busy) return
  const selected = draft.baseState.changes({ from: range.from, to: range.to, insert: range.next })
  const rest = draft.baseState.changes(draftRanges(draft).filter(r => r.key !== range.key).map(r => ({ from: r.from, to: r.to, insert: r.next })))
  const base = selected.apply(draft.baseState.doc).toString()
  const change = suggestionChanges(draft.base, base, selected)[0]
  draft.busy = true; closePop(true)
  cm.dispatch({ effects: editableComp.reconfigure(editMode(false)) }); paintSuggestionControls()
  try {
    if (!draft.pendingAccept) draft.pendingAccept = {}
    const previous = draft.pendingAccept[range.key]
    const id = previous?.old === change.old_string && previous?.next === change.new_string ? previous.id : (await api('POST', `/api/docs/${doc}/suggestions`, change)).id
    draft.pendingAccept[range.key] = { id, old: change.old_string, next: change.new_string }
    await api('POST', `/api/docs/${doc}/suggestions/${id}/accept`, {})
    if (doc !== docId || epoch !== openN || window.suggestionDraft !== draft) return
    draft.base = base; draft.baseState = EditorState.create({ doc: base }); draft.changes = rest.map(selected)
    draft.pendingAccept = {}; draft.changed = !draft.changes.empty
    await loadComments(true)
  } catch (e) { toast(e.status === 409 ? t('comments.suggestionConflict') : e.message) }
  finally {
    if (window.suggestionDraft === draft) {
      draft.busy = false; cm.dispatch({ effects: editableComp.reconfigure(editMode(true)) })
      paintDraftSuggestions(); paintSuggestionControls()
    }
  }
}
function suggestionChanges(base, current, changes) {
  const ranges = []
  changes.iterChanges((from, to) => {
    let a = from ? Math.max(0, base.lastIndexOf('\n', from - 1) + 1) : 0
    let b = base.indexOf('\n', to); b = b < 0 ? base.length : b + 1
    while (base.slice(a, b) && base.indexOf(base.slice(a, b)) !== base.lastIndexOf(base.slice(a, b)) && (a || b < base.length)) {
      a = a > 1 ? Math.max(0, base.lastIndexOf('\n', a - 2) + 1) : 0
      const next = base.indexOf('\n', b); b = next < 0 ? base.length : next + 1
    }
    const previous = ranges[ranges.length - 1]
    // strictly overlapping contexts fuse; an empty context at the previous boundary is a pure insert point belonging to that same fragment (fusing restores backend uniqueness); adjacent distinct edits never merge into one suggestion
    if (previous && (a < previous.to || (a === previous.to && (!base.slice(a, b) || !base.slice(previous.from, previous.to))))) previous.to = Math.max(previous.to, b)
    else ranges.push({ from: a, to: b })
  })
  return ranges.map(r => ({ old_string: base.slice(r.from, r.to), new_string: current.slice(changes.mapPos(r.from, -1), changes.mapPos(r.to, 1)) }))
    .filter(c => c.old_string !== c.new_string)
}
function draftStashKey() { return 'typst-suggestion-' + user + '-' + docId }
function stashSuggestionDraft() {
  const draft = window.suggestionDraft
  if (!draft) return true
  if (!draft.changed) { try { localStorage.removeItem(draftStashKey()) } catch (e) {}; try { delete (window.suggestionDraftMemory || {})[draftStashKey()] } catch (e) {}; return true }
  const snap = { base: draft.base, content: draft.view.state.doc.toString() }
  try { localStorage.setItem(draftStashKey(), JSON.stringify(snap)); return true }
  catch (e) {
    try { (window.suggestionDraftMemory ||= {})[draftStashKey()] = snap } catch (e2) {}
    toast(t('comments.draftSaveFailed')); return true
  }
}
async function startSuggestionDraft() {
  if (sessionStarting || window.changeSession || window.suggestionDraft || !docId || activeFile || tplName || openedTrashed) return
  if (!synced) { toast(t('docs.offlineRetry')); return }
  closePop(true)
  const sourceDoc = docId, epoch = openN
  let base = getT(), content = base
  try {
    const saved = JSON.parse(localStorage.getItem(draftStashKey()) || 'null')
    const mem = (window.suggestionDraftMemory || {})[draftStashKey()]
    const snap = (saved && typeof saved.base === 'string' && typeof saved.content === 'string' && saved.base !== saved.content) ? saved
      : (mem && typeof mem.base === 'string' && typeof mem.content === 'string' && mem.base !== mem.content) ? mem : null
    if (snap) {
      if (await ask(t('comments.draftRestore'), { noInput: true, ok: t('comments.draftRestoreYes') })) { base = snap.base; content = snap.content }
      else { localStorage.removeItem(draftStashKey()); try { delete window.suggestionDraftMemory[draftStashKey()] } catch (e) {} }
    }
  } catch (e) {}
  if (sessionStarting || window.changeSession || sourceDoc !== docId || epoch !== openN || activeFile || tplName || openedTrashed || window.suggestionDraft) return
  const originState = cm.state, scroll = cm.scrollDOM.scrollTop
  const baseState = EditorState.create({ doc: base })
  const draft = { base, baseState, originState, scroll, changed: false, busy: false, editable: editableComp, view: cm, commentRanges: new Map(), changes: baseState.changes([]) }
  window.suggestionDraft = draft
  setT(base)
  cm.dispatch({ effects: editableComp.reconfigure(editMode(true)) })
  document.body.classList.add('suggesting')
  if (content !== base) {
    const span = diffSpan(base, content)
    cm.dispatch({ changes: { from: span.a, to: base.length - span.b, insert: content.slice(span.a, content.length - span.b) } })
  } else if (base === originState.doc.toString()) cm.dispatch({ selection: originState.selection })
  cm.scrollDOM.scrollTop = scroll
  markStyle = ''; marks = new Set(); gutter(); paintDraftSuggestions(); renderPeers(); pushPresence(); applySpell(); fmtSync(); paintSuggestionControls(); queueRender(); cm.focus()
}
function stopSuggestionDraft(discard = true) {
  const draft = window.suggestionDraft
  if (!draft) return true
  if (discard) { try { localStorage.removeItem(draftStashKey()) } catch (e) {}; try { delete (window.suggestionDraftMemory || {})[draftStashKey()] } catch (e) {} } else if (!stashSuggestionDraft()) return false
  closePop(true); window.suggestionDraft = null
  applying = true
  try {
    cm.setState(draft.originState)
    const old = getT(), span = diffSpan(old, shadow)
    if (old !== shadow) cm.dispatch({ changes: { from: span.a, to: old.length - span.b, insert: shadow.slice(span.a, shadow.length - span.b) }, annotations: NO_HIST })
    cm.dispatch({ effects: editableComp.reconfigure(editMode(tabCanEdit(activeFile))) })
  } finally { applying = false }
  document.body.classList.remove('suggesting'); cm.scrollDOM.scrollTop = draft.scroll
  renderPeers(); pushPresence(); applySpell(); fmtSync(); initRanges(); gutter(); refreshHl(); paintOutline(); queueRender(); paintSuggestionControls(); cm.requestMeasure(); return true
}

async function sendSuggestionDraft() {
  const draft = window.suggestionDraft
  if (!draft || draft.busy) return false
  if (!draft.changed) { stopSuggestionDraft(); return true }
  const changes = suggestionChanges(draft.base, draft.view.state.doc.toString(), draft.changes)
  if (draft.base !== shadow && changes.some(c => c.old_string ? shadow.split(c.old_string).length !== 2 : shadow !== '')) {
    const choice = await askPick(t('comments.draftSourceChanged'), [[t('comments.draftKeep'), ''], [t('comments.draftCurrent'), '']])
    if (window.suggestionDraft === draft && choice === 1) { stopSuggestionDraft(false); cm.focus() }
    return false
  }
  if (changes.length > 50 || changes.some(c => c.old_string.length > 20000 || c.new_string.length > 20000)) { toast(t('comments.draftTooLarge')); return false }
  if (changes.some(c => c.old_string ? draft.base.split(c.old_string).length !== 2 : draft.base !== '')) { toast(t('comments.suggestionConflict')); return false } // backend counts every old once in the unchanged original: refuse here cleanly instead of a 409 storm
  draft.busy = true; draft.view.dispatch({ effects: draft.editable.reconfigure(editMode(false)) }); paintSuggestionControls()
  const doc = docId, epoch = openN
  try {
    await api('POST', `/api/docs/${doc}/suggestions/batch`, { changes })
    if (doc !== docId || epoch !== openN) return false
    stopSuggestionDraft(); await loadComments(true); toast(t('comments.draftSent')); return true
  } catch (e) { toast(e.status === 409 ? t('comments.suggestionConflict') : e.message); return false }
  finally { if (window.suggestionDraft === draft) { draft.busy = false; draft.view.dispatch({ effects: draft.editable.reconfigure(editMode(true)) }); paintSuggestionControls() } }
}
async function leaveSuggestionDraft() {
  const draft = window.suggestionDraft
  if (!draft) return true
  if (draft.busy) return false
  if (!draft.changed) { stopSuggestionDraft(); return true }
  const choice = await askPick(t('comments.draftLeave'), [[t('comments.draftSend'), ''], [t('comments.draftDiscard'), ''], [t('projects.stay'), '']])
  if (window.suggestionDraft !== draft) return false
  if (choice === 0) return sendSuggestionDraft()
  if (choice === 1) { stopSuggestionDraft(); return true }
  return false
}
function paintSuggestionControls() {
  const toggle = $('suggestionToggle'), draft = window.suggestionDraft
  toggle.hidden = !docId || !!activeFile || !!tplName || openedTrashed
  toggle.classList.toggle('on', !!draft); toggle.setAttribute('aria-pressed', String(!!draft))
  toggle.disabled = !!draft?.busy || !!docId && !synced && !draft
  toggle.onclick = () => window.suggestionDraft ? leaveSuggestionDraft() : startSuggestionDraft()
  if (docId && !activeFile && !tplName && !openedTrashed) {
    const editable = !!draft || docRole !== 'reviewer'
    for (const id of ['tplBtn', 'symBtn']) $(id).style.display = editable ? '' : 'none'
    $('colWrap').hidden = !editable
  }
}
addEventListener('pagehide', stashSuggestionDraft)
