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
  const c = vm.createContext({ window: {}, popAnchor: 1, popFresh: false, popLayoutTries: 0, getT: () => 'x'.repeat(100), threads: [{ anchor: 1, a: 10, b: 50 }],
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
  const commentRanges = new Map([['comment-old', { from: 2, to: 6 }]])
  const target = { from: 10, to: 14 } // newBox keeps a posting comment under the object key it stored while awaiting the POST
  commentRanges.set(target, target)
  const s = { files: new Map([['current', file]]), commentRanges, original: false, busy: false, dirty: false, previewRevision: 0 }
  const c = vm.createContext({ window: { changeSession: s }, activeFile: '', threads: [{ id: 'comment-old' }, { id: 'c-new' }], popAnchor: null,
    sessionKey: () => 'current', sessionCurrent: () => ({ kind: 'document', doc_id: 'd1' }),
    threadEditorRange: () => ({ from: 4, to: 8 }), getT: () => cs.apply(EditorState.create({ doc: base }).doc).toString(),
    queueRender: () => {}, queueMicrotask: () => {}, sessionStash: () => {},
    sessionPaint: () => {}, paintSuggestionControls: () => {}, paintSessionSidebar: () => {}, RangeSet: { of: ranges => ranges } })
  vm.runInContext(sync.slice(sync.indexOf('function diffSpan'), sync.indexOf('const diffMap')), c)
  vm.runInContext(sug.slice(sug.indexOf('function suggestionChanges'), sug.indexOf('function draftStashKey')), c)
  vm.runInContext(sug.slice(sug.indexOf('function normalizeSuggestionChanges'), sug.indexOf('function draftRanges')), c)
  vm.runInContext(pkg.slice(pkg.indexOf('function sessionRecord'), pkg.indexOf('async function sessionActivate')), c)
  c.sessionRecord(cs)
  assert.deepEqual(commentRanges.get('comment-old'), { from: 5, to: 9 }) // thread-keyed entries still map
  assert.deepEqual(commentRanges.get('c-new'), { from: 7, to: 11 }) // fallback range derived and mapped exactly once
  assert.equal(commentRanges.get(target), target) // object-keyed entry keeps its key and its value is the same mutated object
  assert.deepEqual(commentRanges.get(target), { from: 13, to: 17 }) // the popover target maps too (was stale before fix 2)
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
  vm.runInContext(hlx.slice(hlx.indexOf('function mapThreads')), c)
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
