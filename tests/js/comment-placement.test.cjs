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
