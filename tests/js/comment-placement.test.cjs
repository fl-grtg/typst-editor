const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const { pathToFileURL } = require('node:url')
const path = require('node:path')
const source = fs.readFileSync('web/js/70-comments-popovers.js', 'utf8')
function placement(top, bottom, height = 200) {
  const pop = { style: {}, scrollHeight: height, offsetWidth: 320, classList: { contains: () => false } }
  const bounds = { top: 0, bottom: 700, left: 0, width: 800 }
  const cm = { state: { selection: { main: { empty: true } } }, contentDOM: { style: {} }, scrollDOM: { getBoundingClientRect: () => bounds },
    coordsAtPos: pos => pos === 10 ? { top, bottom: top + 20, left: 100 } : { top: bottom - 20, bottom, left: 300 }, dispatch: () => {} }
  const c = vm.createContext({ window: {}, popAnchor: 1, popFresh: false, popLayoutTries: 0, popThreadId: 'c', getT: () => 'x'.repeat(100),
    threads: [{ id: 'c', a: 10, b: 50 }], threadEditorRange: th => ({ from: th.a, to: th.b }),
    cm, $: id => id === 'pop' ? pop : { getBoundingClientRect: () => bounds }, requestAnimationFrame: () => {}, EditorView: { scrollIntoView: () => ({}) } })
  vm.runInContext(source.slice(source.indexOf('function movePop()'), source.indexOf('function renderPop()')), c)
  c.movePop()
  return { pop, cm }
}
test('comment box sits fully above the entire multi-line mark', () => {
  const { pop } = placement(300, 450)
  assert.ok(parseFloat(pop.style.top) + 200 < 300)
})
test('comment box goes below the end of the mark when above is too small', () => {
  const { pop } = placement(120, 300)
  assert.ok(parseFloat(pop.style.top) > 300)
})
test('a full-height mark reserves space instead of covering the source', () => {
  const { pop, cm } = placement(10, 690)
  assert.equal(pop.style.visibility, 'hidden')
  assert.ok(parseFloat(cm.contentDOM.style.paddingTop) >= 200)
})

test('session edits remap every comment range, including popover targets keyed while a comment posts', async () => {
  const { EditorState } = await import(pathToFileURL(path.resolve('vendor-cm.js')).href)
  const pkg = fs.readFileSync('web/js/features/zz-change-packages.js', 'utf8')
  const sug = fs.readFileSync('web/js/features/suggestions.js', 'utf8')
  const sync = fs.readFileSync('web/js/40-editor-sync.js', 'utf8')
  const base = '0123456789\ndef\n'
  const cs = EditorState.create({ doc: base }).changes({ from: 1, insert: 'abc' })
  const file = { base, content: base, state: EditorState.create({ doc: base }), delta: EditorState.create({ doc: base }).changes([]), action: 'modify', id: 'f1', changes: [] }
  const commentRanges = new Map([['comment-old', { doc: 'd1', from: 2, to: 6 }], ['other-doc', { doc: 'd2', from: 2, to: 6 }]])
  const target = { doc: 'd1', from: 10, to: 14 } // newBox keeps a posting comment under the object key it stored while awaiting the POST
  commentRanges.set(target, target)
  const s = { files: new Map([['current', file]]), commentRanges, original: false, busy: false, dirty: false, previewRevision: 0 }
  const c = vm.createContext({ window: { changeSession: s }, docId: 'd1', activeFile: '', threads: [{ id: 'comment-old', package_id: 'pkg' }, { id: 'c-new', package_id: 'pkg', a: 4, b: 8 }], popAnchor: null,
    sessionKey: () => 'current', sessionCurrent: () => ({ kind: 'document', doc_id: 'd1' }),
    getT: () => cs.apply(EditorState.create({ doc: base }).doc).toString(),
    queueRender: () => {}, queueMicrotask: () => {}, sessionStash: () => {},
    sessionPaint: () => {}, paintSuggestionControls: () => {}, paintSessionSidebar: () => {}, RangeSet: { of: ranges => ranges } })
  vm.runInContext(sync.slice(sync.indexOf('function diffSpan'), sync.indexOf('const diffMap')), c)
  vm.runInContext(sug.slice(sug.indexOf('function suggestionChanges'), sug.indexOf('function draftStashKey')), c)
  vm.runInContext(sug.slice(sug.indexOf('function normalizeSuggestionChanges'), sug.indexOf('function draftRanges')), c)
  const hl = fs.readFileSync('web/js/30-highlight-theme.js', 'utf8')
  vm.runInContext(hl.slice(hl.indexOf('function commentReplacement'), hl.indexOf('function mapThreads')), c)
  vm.runInContext(pkg.slice(pkg.indexOf('function sessionRecord'), pkg.indexOf('async function sessionActivate')), c)
  c.sessionRecord(cs)
  assert.deepEqual(commentRanges.get('comment-old'), { doc: 'd1', from: 5, to: 9 })
  assert.deepEqual({ ...commentRanges.get('c-new') }, { doc: 'd1', from: 7, to: 11 })
  assert.deepEqual(commentRanges.get('other-doc'), { doc: 'd2', from: 2, to: 6 })
  assert.equal(commentRanges.get(target), target) // object-keyed entry keeps its key and its value is the same mutated object
  assert.deepEqual(commentRanges.get(target), { doc: 'd1', from: 13, to: 17 })
})

test('package accept can force comment re-derivation: the cache helper clears the poll dedupe key', () => {
  const c = vm.createContext({ lastC: 'same' })
  vm.runInContext(source.slice(source.indexOf('function invalidateCommentCache'), source.indexOf('async function loadComments')), c)
  c.invalidateCommentCache()
  assert.equal(c.lastC, '')
})

test('hover previews never stack with an open inline card', () => {
  const comp = fs.readFileSync('web/js/20-completions.js', 'utf8')
  const line = comp.slice(comp.indexOf('const hoverAll'), comp.indexOf('\n', comp.indexOf('const hoverAll')))
  const run = (display, comment, typst) => {
    const c = vm.createContext({ commentHover: () => comment, typstHover: () => typst, $: () => ({ style: { display } }) })
    return vm.runInContext(line + '\nhoverAll', c)(null, 0)
  }
  assert.equal(run('none', 'comment', 'typst'), 'comment') // no card open: the comment preview shows
  assert.equal(run('none', null, 'typst'), 'typst') // … and command docs fill in below it
  assert.equal(run('', 'comment', 'typst'), null) // open card: no hover preview at all
  assert.equal(run('block', 'comment', 'typst'), null) // the error list card counts as an open card too
})

test('reanchor repaints highlights when first sync arrives after comments loaded on empty buffer', () => {
  const hlx = fs.readFileSync('web/js/30-highlight-theme.js', 'utf8')
  const comp = fs.readFileSync('web/js/20-completions.js', 'utf8')
  let text = '', gutters = 0, hls = 0
  const threads = [{ id: 'c1', anchor: 1, quote: 'hello world', text: 'note', resolved: false }]
  const c = vm.createContext({
    window: {}, docId: 'd1', ytext: {}, activeFile: '', popAnchor: null, shadow: '', threads,
    getT: () => text, gutter: () => { gutters++ }, refreshHl: () => { hls++ }, movePop: () => {}, dirtyAnchor: () => {},
  })
  vm.runInContext(comp.slice(comp.indexOf('const posOfLine'), comp.indexOf('function threadHighlights')), c)
  vm.runInContext(hlx.slice(hlx.indexOf('function initRanges')), c)
  vm.runInContext(source.slice(source.indexOf('function reanchor()'), source.indexOf('async function jumpThread')), c)
  // Step 1: comments arrive before WS text
  c.initRanges(); c.reanchor()
  assert.equal(threads[0].a, null)
  const beforeGutters = gutters, beforeHls = hls
  // Step 2: WS delivers text -> reanchor must derive ranges AND repaint highlights
  text = 'hello world\nsecond line'
  c.reanchor()
  assert.equal(threads[0].a, 0)
  assert.equal(threads[0].b, 11)
  assert.equal(gutters, beforeGutters + 1)
  assert.equal(hls, beforeHls + 1)
})

test('editing inside commented text keeps tight range, typing outside stays out, deleting never resurrects on new text', async () => {
  const { EditorState } = await import(pathToFileURL(path.resolve('vendor-cm.js')).href)
  const hlx = fs.readFileSync('web/js/30-highlight-theme.js', 'utf8')
  const comp = fs.readFileSync('web/js/20-completions.js', 'utf8')
  let state = EditorState.create({ doc: 'start word end' })
  const threads = [{ id: 'c1', anchor: 1, quote: 'word', text: 'fix', resolved: false }]
  const c = vm.createContext({
    window: {}, docId: 'd1', ytext: {}, activeFile: '', popAnchor: null, shadow: '', threads,
    getT: () => state.doc.toString(), gutter: () => {}, refreshHl: () => {}, movePop: () => {}, dirtyAnchor: () => {},
  })
  vm.runInContext(comp.slice(comp.indexOf('const posOfLine'), comp.indexOf('function threadHighlights')), c)
  vm.runInContext(hlx.slice(hlx.indexOf('function commentReplacement')), c)
  vm.runInContext(source.slice(source.indexOf('function reanchor()'), source.indexOf('async function jumpThread')), c)
  const applyEdit = spec => {
    const oldLen = state.doc.length
    const tr = state.update({ changes: spec })
    state = tr.state
    c.mapThreads((p, end) => tr.changes.mapPos(p, end ? -1 : 1), false, oldLen)
    c.reanchor()
  }
  c.initRanges()
  assert.equal(state.doc.sliceString(threads[0].a, threads[0].b), 'word')
  // Edit inside commented short word -> stays tightly on edited word (never explodes to whole line)
  applyEdit({ from: 8, insert: 'X' })
  assert.equal(state.doc.sliceString(threads[0].a, threads[0].b), 'woXrd')
  // Type right before and right after -> stays outside the highlight
  applyEdit({ from: threads[0].a, insert: 'pre ' })
  assert.equal(state.doc.sliceString(threads[0].a, threads[0].b), 'woXrd')
  applyEdit({ from: threads[0].b, insert: ' post' })
  assert.equal(state.doc.sliceString(threads[0].a, threads[0].b), 'woXrd')
  // Delete the entire commented word -> highlight drops cleanly
  const delAt = threads[0].a
  applyEdit({ from: threads[0].a, to: threads[0].b })
  assert.equal(threads[0].a, null)
  assert.equal(threads[0].b, null)
  // Later type completely unrelated text at that spot -> highlight does NOT resurrect
  applyEdit({ from: delAt, insert: 'totally different content' })
  assert.equal(threads[0].a, null)
  assert.equal(threads[0].b, null)
  // Undo / restore the exact original quote -> highlight re-attaches
  applyEdit({ from: delAt, to: delAt + 'totally different content'.length, insert: 'word' })
  assert.equal(state.doc.sliceString(threads[0].a, threads[0].b), 'word')
})

test('exactQuotePos prefers a match on the anchored line over a closer-in-chars match on another line', () => {
  const comp = fs.readFileSync('web/js/20-completions.js', 'utf8')
  const c = vm.createContext({})
  vm.runInContext(comp.slice(comp.indexOf('const posOfLine'), comp.indexOf('function threadHighlights')), c)
  const text = 'prefix '.repeat(2) + 'same\n' + 'x'.repeat(80) + ' same\n'
  const line2Pos = text.lastIndexOf('same')
  assert.equal(c.exactQuotePos(text, 'same', 2), line2Pos)
  assert.equal(c.exactQuotePos('same\n'.repeat(25), 'same', 25), 120)
})

test('live ranges survive a shortened document, edited quotes and a fresh Yjs client', async () => {
  const Y = await import(pathToFileURL(path.resolve('vendor/yjs-13.6.27-232b4982bc3f.js')).href)
  const hl = fs.readFileSync('web/js/30-highlight-theme.js', 'utf8')
  const ydoc = new Y.Doc(), ytext = ydoc.getText('typst')
  ytext.insert(0, '0123456789 word')
  const c = vm.createContext({ Y, ydoc, ytext, synced: true, btoa, atob, window: {}, activeFile: '', getT: () => c.ytext.toString() })
  vm.runInContext(hl.slice(hl.indexOf('function commentReplacement')), c)
  let anchor = c.saveCommentRange(11, 15)
  c.threads = [{ a: 11, b: 15, quote: 'word', anchor_range: anchor, anchor: 1 }]
  ytext.delete(0, 11)
  c.mapThreads(p => Math.max(0, p - 11), false, 15)
  assert.deepEqual([c.threads[0].a, c.threads[0].b], [0, 4])
  ytext.insert(2, 'X')

  const reloaded = new Y.Doc()
  Y.applyUpdate(reloaded, Y.encodeStateAsUpdate(ydoc))
  c.ydoc = reloaded; c.ytext = reloaded.getText('typst')
  c.threads = [{ quote: 'word', anchor_range: anchor }]
  c.initRanges()
  assert.equal(c.ytext.toString().slice(c.threads[0].a, c.threads[0].b), 'woXrd')

  c.dirtyAnchor = (thread, before) => {
    assert.equal(before, anchor)
    anchor = thread.anchor_range
  }
  reloaded.transact(() => { c.ytext.delete(0, 5); c.ytext.insert(0, 'replacement') })
  c.mapThreads((_pos, end) => end ? 0 : 11, false, 5, fn => fn(0, 5, 0, 11))
  assert.deepEqual([c.threads[0].a, c.threads[0].b], [0, 11])
  c.threads = [{ quote: 'word', anchor_range: anchor }]
  c.initRanges()
  assert.deepEqual([c.threads[0].a, c.threads[0].b], [0, 11])

  c.ytext.delete(0, c.ytext.length)
  c.ytext.insert(0, 'word in a new paragraph')
  c.threads = [{ quote: 'word', anchor_range: anchor }]
  c.initRanges()
  assert.equal(c.threads[0].a, undefined)
  assert.equal(c.threads[0]._deleted, true)
  ydoc.destroy(); reloaded.destroy()
})

test('a discussion on a deletion attaches to the patch, not identical surviving text', () => {
  const hl = fs.readFileSync('web/js/30-highlight-theme.js', 'utf8')
  const file = {}, thread = { package_id: 'pkg', anchor: 1, anchor_quote: '', quote: 'word' }
  const c = vm.createContext({
    window: { changeSession: { files: new Map([['doc', file]]) } }, threads: [thread],
    getT: () => 'word remains', sessionCurrent: () => 'doc', sessionKey: key => key,
    sessionChangeRanges: () => [{ a: 6, old: 'word', next: '' }], lineOf: () => 1,
  })
  vm.runInContext(hl.slice(hl.indexOf('function initRanges')), c)
  c.initRanges()
  assert.deepEqual([thread.a, thread.b], [6, 6])
})

test('review comments are stashed locally and publish the latest text at their draft position', async () => {
  const pkg = fs.readFileSync('web/js/features/zz-change-packages.js', 'utf8')
  const session = { files: new Map([['d1', { content: 'Header\nbefore revised text after' }]]) }
  let stashed = 0
  const c = vm.createContext({ user: 'author', crypto: { randomUUID: () => 'test' },
    api: () => assert.fail('an unsent comment must not call the live comment API'),
    sessionStash: () => stashed++, paintSuggestionControls() {}, sessionKey: f => f.doc_id })
  vm.runInContext(pkg.slice(pkg.indexOf('async function postReviewComment'), pkg.indexOf('function sessionRecord')), c)
  await c.postReviewComment(session, 'd1', { anchor: 1, quote: 'before original text', anchor_quote: 'before original text', text: '  Note  ' }, { from: 7, to: 26 })
  assert.equal(stashed, 1)
  const payload = c.sessionDraftComments(session)[0]
  assert.deepEqual({ ...payload }, { client_id: 'draft-comment-test', doc_id: 'd1', anchor: 2, quote: 'before original text',
    anchor_quote: 'before revised text', text: 'Note', parent_id: undefined, replaces_id: undefined, deleted: false, resolved: false })
})

test('proposal comment edits, deletions and replies overlay live threads without changing them', () => {
  const live = [
    { id: 'edit-me', text: 'old', replies: [{ id: 'reply-delete', text: 'gone' }] },
    { id: 'delete-me', text: 'remove', replies: [] },
  ]
  const c = vm.createContext({})
  vm.runInContext(source.slice(source.indexOf('function proposalComments'), source.indexOf('function commentPackage')), c)
  const result = c.proposalComments(live, [
    { id: 'p1', replaces_id: 'edit-me', text: 'new' },
    { id: 'p2', replaces_id: 'reply-delete', deleted: true },
    { id: 'p3', replaces_id: 'delete-me', deleted: true },
    { id: 'p4', parent_id: 'edit-me', text: 'package reply' },
    { id: 'p5', text: 'package thread', replies: [] },
  ])
  assert.equal(JSON.stringify(result.map(th => [th.id, th.text, th.replies.map(r => r.id).join(',')])),
    JSON.stringify([['edit-me', 'new', 'reply-delete,p4'], ['delete-me', 'remove', ''], ['p5', 'package thread', '']]))
  assert.equal(result[0]._proposedEdit, true)
  assert.deepEqual([result[0].replies[0]._proposedDelete, result[0].replies[0]._changeId], [true, 'p2'])
  assert.deepEqual([result[1]._proposedDelete, result[1]._changeId], [true, 'p3'])
  assert.equal(live[0].text, 'old')
  assert.equal(live[0].replies[0]._proposedDelete, undefined)
})

test('submitting a comment with Enter does not reach the editor', () => {
  const pkg = fs.readFileSync('web/js/features/zz-change-packages.js', 'utf8')
  for (const code of [source, pkg]) assert.doesNotMatch(code, /if \(e\.key === 'Enter'\) (post|send)\(\)/)
})

test('loadComments preserves live edited ranges and deleted state across replies/polls', async () => {
  const liveThreads = [
    { id: 'c1', anchor: 1, quote: 'orig', text: 'note', a: 0, b: 6 },
    { id: 'c2', anchor: 2, quote: 'gone', text: 'note2', a: null, b: null, _deleted: true },
  ]
  const c = vm.createContext({
    window: {}, docId: 'd1', openN: 1, activeFile: '', synced: true, ytext: {}, lastC: 'old', shadow: 'edited\ngone',
    threads: liveThreads, getT: () => 'edited\ngone',
    api: async () => ({ comments: [
      { id: 'c1', anchor: 1, quote: 'orig', text: 'note', replies: [{ id: 'r1', text: 'reply' }] },
      { id: 'c2', anchor: 2, quote: 'gone', text: 'note2', replies: [] },
    ] }),
    initRanges: () => false, reanchor: () => {}, gutter: () => {}, refreshHl: () => {},
    paintBadge: () => {}, popAnchor: null, renderPop: () => {}, $: () => ({ querySelectorAll: () => [] }),
  })
  vm.runInContext(source.slice(source.indexOf('function repaintCommentRanges'), source.indexOf('function paintBadge()')), c)
  await c.loadComments()
  assert.deepEqual([c.threads[0].a, c.threads[0].b], [0, 6])
  assert.equal(c.threads[1]._deleted, true)
  assert.equal(c.threads[1].a, null)
})

test('proposal views project live comments onto the modified text and keep package comments separate', async () => {
  const { EditorState } = await import(pathToFileURL(path.resolve('vendor-cm.js')).href)
  const sync = fs.readFileSync('web/js/40-editor-sync.js', 'utf8')
  const hl = fs.readFileSync('web/js/30-highlight-theme.js', 'utf8')
  const comp = fs.readFileSync('web/js/20-completions.js', 'utf8')
  const sug = fs.readFileSync('web/js/features/suggestions.js', 'utf8')
  const pkg = fs.readFileSync('web/js/features/zz-change-packages.js', 'utf8')
  const base = 'first\nbefore old after', proposed = 'first\nbefore replacement after'
  const delta = EditorState.create({ doc: base }).changes({ from: 13, to: 16, insert: 'replacement' })
  const session = { files: new Map([['doc', { base, delta }]]), commentRanges: new Map(),
    draftComments: [{ id: 'draft-note', package_id: 'draft', doc_id: 'doc', anchor: 2, a: 13, b: 24 }] }
  const c = vm.createContext({
    window: { changeSession: session }, docId: 'doc', openN: 1, activeFile: '', shadow: base, threads: [], lastC: '',
    sessionKey: key => key, sessionCurrent: () => 'doc', getT: () => session.original ? base : proposed,
    api: async (_, url) => url.includes('package_id') ? { comments: [{ id: 'pkg-note', package_id: 'pkg', quote: 'replacement', anchor: 2 }] }
      : { comments: [{ id: 'live-note', quote: 'old', anchor: 2 }] },
    cm: { state: { doc: { length: proposed.length } } }, reanchor() {}, gutter() {}, refreshHl() {}, paintBadge() {},
    popAnchor: null, $: () => ({ querySelectorAll: () => [] }),
  })
  vm.runInContext(sync.slice(sync.indexOf('function diffSpan'), sync.indexOf('const deltaMap')), c)
  vm.runInContext(comp.slice(comp.indexOf('const posOfLine'), comp.indexOf('function threadHighlights')), c)
  vm.runInContext(hl.slice(hl.indexOf('function initRanges')), c)
  vm.runInContext(sug.slice(sug.indexOf('function sourceToEditor'), sug.indexOf('function normalizeSuggestionChanges')), c)
  vm.runInContext(pkg.slice(pkg.indexOf('const sessionOriginalSourceMap'), pkg.indexOf('const sessionSourceApi')), c)
  vm.runInContext(source.slice(source.indexOf('function repaintCommentRanges'), source.indexOf('function paintBadge()')), c)
  await c.loadComments()
  assert.equal(c.threads.map(th => th.id).join(','), 'live-note,draft-note')
  assert.deepEqual({ ...c.threadEditorRange(c.threads[0]) }, { from: 13, to: 24 })
  session.package = { id: 'pkg' }
  await c.loadComments()
  assert.equal(c.threads.map(th => th.id).join(','), 'live-note,pkg-note')
  assert.deepEqual({ ...c.threadEditorRange(c.threads[1]) }, { from: 13, to: 24 })
  session.original = true
  await c.loadComments()
  assert.equal(c.threads.map(th => th.id).join(','), 'live-note')
  assert.deepEqual({ ...c.threadEditorRange(c.threads[0]) }, { from: 13, to: 16 })
})

test('visibleSelectionQuote excludes deleted draft text and reflects live pending replacements', () => {
  const comp = fs.readFileSync('web/js/20-completions.js', 'utf8')
  const sync = fs.readFileSync('web/js/40-editor-sync.js', 'utf8')
  const c = vm.createContext({
    window: { changeSession: {} },
    getT: () => 'Sa man',
    threads: [],
  })
  vm.runInContext(sync.slice(sync.indexOf('function diffSpan'), sync.indexOf('const diffMap')), c)
  vm.runInContext(comp.slice(comp.indexOf('function tokenCut'), comp.indexOf('function refreshHl')), c)
  vm.runInContext(source.slice(source.indexOf('function visibleSelectionQuote'), source.indexOf('function newBox()')), c)
  assert.equal(c.visibleSelectionQuote(0, 6), 'Sa man') // draft buffer already excludes deleted text
  // Live doc with pending inline suggestion
  c.window.changeSession = null
  c.getT = () => 'im Modus aendern kann.'
  c.threads = [{ id: 's1', a: 0, b: 22, conflict: false, suggestion_status: 'pending', suggestion_old: 'im Modus aendern kann.', replacement: 'im Modus ueberarbeiten kann.' }]
  assert.equal(c.visibleSelectionQuote(0, 22), 'im Modus ueberarbeiten kann.')
})

test('a draft follows accepted live text without losing its own changes or comment ranges', async () => {
  const { EditorState } = await import(pathToFileURL(path.resolve('vendor-cm.js')).href)
  const pkg = fs.readFileSync('web/js/features/zz-change-packages.js', 'utf8')
  const sug = fs.readFileSync('web/js/features/suggestions.js', 'utf8')
  const sync = fs.readFileSync('web/js/40-editor-sync.js', 'utf8')
  const base = 'alpha old omega'
  const state = EditorState.create({ doc: base })
  const delta = state.changes({ from: 0, to: 5, insert: 'ALPHA' })
  let text = 'ALPHA old omega'
  const file = { id: 'f', base, content: text, state, delta, changes: [] }
  const session = { files: new Map([['doc', file]]), commentRanges: new Map([['c', { doc: 'd', from: 6, to: 9 }]]), draftComments: [], previewRevision: 0 }
  const c = vm.createContext({ EditorState, window: { changeSession: session }, docId: 'd', activeFile: '', applying: false, NO_HIST: [],
    sessionKey: () => 'doc', sessionCurrent: () => 'doc', getT: () => text, sessionStash() {}, queueMicrotask() {},
    cm: { dispatch: tr => { text = tr.changes.apply(EditorState.create({ doc: text }).doc).toString() } } })
  vm.runInContext(sync.slice(sync.indexOf('function diffSpan'), sync.indexOf('const diffMap')), c)
  vm.runInContext(sug.slice(sug.indexOf('function normalizeSuggestionChanges'), sug.indexOf('function draftRanges')), c)
  vm.runInContext(sug.slice(sug.indexOf('function suggestionChanges'), sug.indexOf('function draftStashKey')), c)
  const hl = fs.readFileSync('web/js/30-highlight-theme.js', 'utf8')
  vm.runInContext(hl.slice(hl.indexOf('function commentReplacement'), hl.indexOf('function mapThreads')), c)
  vm.runInContext(pkg.slice(pkg.indexOf('function sessionRemote'), pkg.indexOf('function sessionRecord')), c)
  c.sessionRemote(base, 'alpha new omega', [{ retain: 6 }, { delete: 3 }, { insert: 'new' }])
  assert.equal(file.base, 'alpha new omega')
  assert.equal(file.content, 'ALPHA new omega')
  assert.equal(text, 'ALPHA new omega')
  assert.deepEqual({ ...session.commentRanges.get('c') }, { doc: 'd', from: 6, to: 9 })
})

test('proposal mode keeps live suggestion decisions available', () => {
  const pkg = fs.readFileSync('web/js/features/zz-change-packages.js', 'utf8')
  const suggestion = fs.readFileSync('web/js/features/suggestions.js', 'utf8')
  assert.ok(pkg.includes(String.raw`suggestions\/[^/]+\/(accept|reject)`))
  assert.doesNotMatch(source, /pendingSug && !window\.changeSession/)
  assert.doesNotMatch(suggestion, /!openedTrashed && !window\.changeSession/)
})

test('a proposal line lists every change and comment as its own item', () => {
  const pkg = fs.readFileSync('web/js/features/zz-change-packages.js', 'utf8')
  const ranges = [{ a: 3, b: 5, old: 'x', next: 'yy' }, { a: 8, b: 8, old: 'gone', next: '' }]
  const card = (cls, text = '') => ({ className: cls, textContent: text, children: [], dataset: {}, style: {}, classList: { add() {} },
    append(...items) { this.children.push(...items) }, appendChild(item) { this.children.push(item) }, setAttribute() {} })
  let items
  const c = vm.createContext({ window: { changeSession: { files: new Map([['f', {}]]) } }, activeFile: '', openedTrashed: true, docRole: 'reader', user: 'u',
    sessionKey: () => 'f', sessionCurrent() {}, sessionChangeRanges: () => ranges,
    threads: [{ id: 'on-change', a: 3, b: 4 }, { id: 'on-delete', a: 8, b: 8 }, { id: 'live-suggestion', suggestion_status: 'pending', a: 10, b: 12 }, { id: 'line-comment', a: 13, b: 14 }],
    threadEditorRange: th => ({ from: th.a, to: th.b }), cm: { state: { doc: { lines: 1, line: () => ({ from: 0, to: 20 }), lineAt: () => ({ number: 1 }) } } },
    popThreadId: null, paintPopItems: list => { items = list }, el: card, icoBtn: card, colOf: () => '', paintAvatar() {}, t: key => key, ICO_TRASH: '',
    threadCard: th => card('th', th.id), visibleChange: text => text })
  vm.runInContext(pkg.slice(pkg.indexOf('function sessionRangeOnLine'), pkg.indexOf('function paintSessionSelection')), c)
  c.sessionCard({ index: 1 })
  assert.equal(JSON.stringify(items.map(item => item.id)), JSON.stringify(['s:0', 's:1', 't:on-change', 't:on-delete', 't:live-suggestion', 't:line-comment']))
  assert.equal(c.popThreadId, 's:1')
  const walk = node => [node, ...(node.children || []).flatMap(walk)]
  assert.ok(!walk(items[0].render()).some(node => node.textContent === 'on-change'))
})

test('a draft keeps its base when live text changed the same passage', async () => {
  const { EditorState } = await import(pathToFileURL(path.resolve('vendor-cm.js')).href)
  const pkg = fs.readFileSync('web/js/features/zz-change-packages.js', 'utf8')
  const base = 'alpha beta gamma'
  const state = EditorState.create({ doc: base })
  const file = { base, content: 'alpha BETA gamma', state, delta: state.changes({ from: 6, to: 10, insert: 'BETA' }) }
  const c = vm.createContext({ EditorState, window: { changeSession: { files: new Map([['doc', file]]) } }, docId: 'd',
    sessionKey: () => 'doc', diffSpan: () => assert.fail('the delta is used') })
  vm.runInContext(pkg.slice(pkg.indexOf('function sessionRemote'), pkg.indexOf('function sessionRecord')), c)
  c.sessionRemote(base, 'alpha replaced gamma', [{ retain: 6 }, { delete: 4 }, { insert: 'replaced' }])
  assert.equal(file.base, base)
  assert.equal(file.content, 'alpha BETA gamma')
})

test('decided suggestions leave the comment list and whitespace changes stay readable', async () => {
  const sug = fs.readFileSync('web/js/features/suggestions.js', 'utf8')
  const c = vm.createContext({ window: {}, docId: 'd', openN: 1, activeFile: 'x', shadow: '', getT: () => '', threads: [], lastC: '', paintBadge() {}, popAnchor: null,
    $: () => ({ querySelectorAll: () => [] }), api: async () => ({ comments: [
      { id: 'open', replies: [] }, { id: 'pending', suggestion_status: 'pending', replies: [] },
      { id: 'accepted', suggestion_status: 'accepted', replies: [] }, { id: 'rejected', suggestion_status: 'rejected', replies: [] },
    ] }) })
  vm.runInContext(source.slice(source.indexOf('function repaintCommentRanges'), source.indexOf('function paintBadge()')), c)
  vm.runInContext(sug.slice(sug.indexOf('function visibleChange'), sug.indexOf('function suggestionCard')), c)
  await c.loadComments()
  assert.equal(c.threads.map(th => th.id).join(','), 'open,pending')
  assert.equal(c.visibleChange(' \n'), '·↵\n')
  assert.equal(c.visibleChange('word '), 'word ')
})

test('a comment card quotes the text its mark covers now, not the text it was written on', () => {
  const card = (tag, cls, text) => ({ tag, className: cls, textContent: text, children: [], dataset: {}, style: {}, classList: { add() {} },
    append(...items) { this.children.push(...items) }, appendChild(item) { this.children.push(item) }, setAttribute() {} })
  const c = vm.createContext({ window: {}, docId: 'd', openN: 1, docRole: 'owner', openedTrashed: false, user: 'u', el: card, icoBtn: tag => card('button', tag), ICO_CHECK: '', ICO_UNDO: '', ICO_EDIT: '', ICO_TRASH: '', ICO_SEND: '',
    t: key => key, ago: () => '', colOf: () => '', paintAvatar() {}, wireMentions() {}, popDrafts: new Map(), richText: text => card('p', 'tx', text),
    threadEditorRange: th => ({ from: th.a, to: th.b }), cm: { state: { doc: { sliceString: (a, b) => 'Dies e Zele wird'.slice(a, b) } } } })
  vm.runInContext(source.slice(source.indexOf('function saveCommentChange'), source.indexOf('function invalidateCommentCache')), c)
  const walk = node => [node, ...(node.children || []).flatMap(walk)]
  const quote = th => walk(c.threadCard({ id: 'c', username: 'u', created_at: '', replies: [], text: 'note', ...th })).find(n => n.className === 'qt').textContent
  assert.equal(quote({ quote: 'Diese Zeile wird', a: 0, b: 16 }), '"Dies e Zele wird"')
  assert.equal(quote({ quote: 'gone text', a: null, b: null }), '"gone text"')
})

test('a proposed resolve flips the shown state only when it differs from the live thread', () => {
  const c = vm.createContext({})
  vm.runInContext(source.slice(source.indexOf('function proposalComments'), source.indexOf('function commentPackage')), c)
  const live = [{ id: 'open', text: 'a', resolved: 0, replies: [] }, { id: 'done', text: 'b', resolved: 1, replies: [] }]
  const [open, done] = c.proposalComments(live, [
    { id: 'p1', replaces_id: 'open', text: '', resolved: true },
    { id: 'p2', replaces_id: 'done', text: '', resolved: true },
  ])
  assert.deepEqual([open.resolved, open._proposedResolve, open._changeId], [1, true, 'p1'])
  assert.deepEqual([done.resolved, done._proposedResolve], [1, undefined])
  assert.equal(live[0].resolved, 0)
})
