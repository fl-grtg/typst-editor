const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const { pathToFileURL } = require('node:url')
const path = require('node:path')
const code = fs.readFileSync('web/js/features/suggestions.js', 'utf8')
const context = vm.createContext({})
vm.runInContext(code.slice(code.indexOf('function suggestionChanges'), code.indexOf('function draftStashKey')), context)
const plain = v => JSON.parse(JSON.stringify(v))
async function propose(base, changes) {
  const { EditorState } = await import(pathToFileURL(path.resolve('vendor-cm.js')).href)
  const state = EditorState.create({ doc: base })
  const changeSet = state.changes(changes)
  return plain(context.suggestionChanges(base, changeSet.apply(state.doc).toString(), changeSet))
}
test('separate edits become context anchored proposals', async () => {
  const base = 'First line\nMiddle line\nLast line\n'
  const changes = await propose(base, [{ from: 0, to: 5, insert: 'Changed' }, { from: 23, to: 27, insert: 'Final' }])
  assert.equal(changes.length, 2)
  assert.equal(changes[0].old_string, 'First line\n')
  assert.equal(changes[0].new_string, 'Changed line\n')
  assert.equal(changes[1].new_string, 'Final line\n')
})
test('repeated lines gain enough context and overlapping contexts merge', async () => {
  const base = 'Chapter A\nRepeated\nChapter B\nRepeated\n'
  const changes = await propose(base, [{ from: 10, to: 18, insert: 'First' }, { from: 29, to: 37, insert: 'Second' }])
  for (const c of changes) assert.equal(base.split(c.old_string).length, 2)
  let result = base
  for (const c of changes) result = result.replace(c.old_string, c.new_string)
  assert.equal(result, 'Chapter A\nFirst\nChapter B\nSecond\n')
})

test('repeated CSV rows expand context past overlapping occurrences', async () => {
  const base = 'a,b,c,d\n' + ',,,\n'.repeat(7)
  const at = base.indexOf(',,,') + 10
  const changes = await propose(base, { from: at, insert: 'changed' })
  for (const change of changes) assert.equal(base.indexOf(change.old_string), base.lastIndexOf(change.old_string))
  let result = base
  for (const change of changes) result = result.replace(change.old_string, change.new_string)
  assert.equal(result, base.slice(0, at) + 'changed' + base.slice(at))
})
test('inserting into an empty document and deleting the whole text are proposals', async () => {
  assert.deepEqual(await propose('', { from: 0, insert: 'New text' }), [{ old_string: '', new_string: 'New text' }])
  assert.deepEqual(await propose('Old text', { from: 0, to: 8 }), [{ old_string: 'Old text', new_string: '' }])
})

test('pending suggestion ranges use the full original rather than the truncated comment quote', () => {
  const text = 'a'.repeat(700), threads = [{ suggestion_status: 'pending', suggestion_old: text, quote: text.slice(0, 500) }]
  const c = vm.createContext({ window: {}, getT: () => text, threads })
  const source = fs.readFileSync('web/js/30-highlight-theme.js', 'utf8')
  vm.runInContext(source.slice(source.indexOf('function initRanges')), c)
  c.initRanges()
  assert.equal(threads[0].a, 0)
  assert.equal(threads[0].b, 700)
})
test('an empty buffer derives no ranges: real text must re-derive them after sync', () => {
  const threads = [{ suggestion_status: 'pending', suggestion_old: '', quote: '', anchor: 1 }, { quote: '', anchor: 1 }]
  const c = vm.createContext({ window: {}, getT: () => '', threads })
  const source = fs.readFileSync('web/js/30-highlight-theme.js', 'utf8')
  vm.runInContext(source.slice(source.indexOf('function initRanges')), c)
  c.initRanges()
  assert.ok(threads[0].a == null && threads[0].b == null) // no (0,0) ghost that a full-text insert delta would balloon to the whole doc
  assert.ok(threads[1].a == null && threads[1].b == null)
})
test('a comment with an empty quote stays unset pre-sync and derives its anchor line after the sync', () => {
  const posOfLine = (t, line) => { let p = 0; for (let l = 1; l < line; l++) { p = t.indexOf('\n', p) + 1; if (!p) return t.length } return p }
  const threads = [{ quote: '', anchor: 3 }]
  const c = vm.createContext({ window: {}, getT: () => '', threads, posOfLine })
  const source = fs.readFileSync('web/js/30-highlight-theme.js', 'utf8')
  vm.runInContext(source.slice(source.indexOf('function initRanges')), c)
  c.initRanges()
  assert.ok(threads[0].a == null) // openDoc pre-sync on '' must not cache a (0,0) range
  const text = 'one\ntwo\nthree text\nfour'
  c.getT = () => text
  c.initRanges()
  assert.equal(threads[0].a, text.indexOf('three text'))
  assert.equal(threads[0].b, text.indexOf('three text') + 'three text'.length)
})
test('two identical pending suggestions both land on their anchor lines with the conflict hint', () => {
  const posOfLine = (t, line) => { let p = 0; for (let l = 1; l < line; l++) { p = t.indexOf('\n', p) + 1; if (!p) return t.length } return p }
  const text = 'Same\nSame\n'
  const threads = [
    { suggestion_status: 'pending', suggestion_old: 'Same', quote: '', anchor: 1 },
    { suggestion_status: 'pending', suggestion_old: 'Same', quote: '', anchor: 2 },
  ] // non-overlap count says 2 occurrences: neither gets the quote, both fall back to their anchor line
  const c = vm.createContext({ window: {}, getT: () => text, threads, posOfLine })
  const source = fs.readFileSync('web/js/30-highlight-theme.js', 'utf8')
  vm.runInContext(source.slice(source.indexOf('function initRanges')), c)
  c.initRanges()
  assert.deepEqual([threads[0].a, threads[0].b], [0, 4])
  assert.deepEqual([threads[1].a, threads[1].b], [5, 9])
  assert.equal(threads[0].conflict, true)
  assert.equal(threads[1].conflict, true)
})
test('two edits on adjacent lines stay separate suggestions (no giant cross-merge)', async () => {
  const changes = await propose('alpha\nbeta\n', [{ from: 0, to: 5, insert: 'ALPHA' }, { from: 6, to: 10, insert: 'BETA' }])
  assert.equal(changes.length, 2)
  assert.deepEqual(changes.map(c => c.old_string), ['alpha\n', 'beta\n'])
  assert.deepEqual(changes.map(c => c.new_string), ['ALPHA\n', 'BETA\n'])
})
test('a clean suggestion draft removes a previously stored draft', () => {
  const removed = []
  const c = vm.createContext({ window: { suggestionDraft: { changed: false } }, localStorage: { removeItem: key => removed.push(key) }, draftStashKey: () => 'draft' })
  vm.runInContext(code.slice(code.indexOf('function stashSuggestionDraft'), code.indexOf('async function startSuggestionDraft')), c)
  assert.equal(c.stashSuggestionDraft(), true)
  assert.deepEqual(removed, ['draft'])
})

test('repeated sentences across a two-language draft fuse the document-end insert into one valid suggestion', async () => {
  const base = 'Erster Satz\nFirst sentence\nSelber Satz\nSelber Satz\n'
  const changes = await propose(base, [{ from: 27, insert: 'NEU' }, { from: base.length, insert: 'X' }])
  assert.equal(changes.length, 1) // fused: strict-overlap splitting produced two filings with a duplicate/empty old and a guaranteed 409
  assert.ok(changes.every(c => base.split(c.old_string).length === 2)) // backend create_batch accepts: every old occurs exactly once
  const [c] = changes
  assert.ok(c.new_string.includes('NEU') && c.new_string.endsWith('X'))
})

test('a draft batch that would be ambiguous refuses to send instead of a 409 storm', async () => {
  const { EditorState } = await import(pathToFileURL(path.resolve('vendor-cm.js')).href)
  const base = 'Erster Satz\nSelber Satz\nErster Satz\nSelber Satz\n'
  const state = EditorState.create({ doc: base })
  const cs = state.changes([{ from: 0, insert: 'X' }, { from: base.length, insert: 'Y' }])
  const toasts = []
  const c = vm.createContext({
    window: { suggestionDraft: { base, changed: true, busy: false, changes: cs, view: { state: { doc: { toString: () => cs.apply(state.doc).toString() } } } } },
    shadow: base, t: key => key, toast: key => toasts.push(key), api: () => { throw Error('must not hit the network') } })
  vm.runInContext(code.slice(code.indexOf('function suggestionChanges'), code.indexOf('function draftStashKey')), c)
  vm.runInContext(code.slice(code.indexOf('async function sendSuggestionDraft'), code.indexOf('async function leaveSuggestionDraft')), c)
  assert.equal(await c.sendSuggestionDraft(), false)
  assert.deepEqual(toasts, ['comments.suggestionConflict'])
  assert.equal(c.window.suggestionDraft.busy, false) // the draft stays editable: no spam of rejected POSTs
})

test('retyping removed text cancels the recorded change while preserving other edits', async () => {
  const { EditorState } = await import(pathToFileURL(path.resolve('vendor-cm.js')).href)
  const c = vm.createContext({})
  const sync = fs.readFileSync('web/js/40-editor-sync.js', 'utf8')
  vm.runInContext(sync.slice(sync.indexOf('function diffSpan'), sync.indexOf('const diffMap')), c)
  vm.runInContext(code.slice(code.indexOf('function normalizeSuggestionChanges'), code.indexOf('function draftRanges')), c)
  const base = EditorState.create({ doc: 'Hello world' })
  let state = base, changes = base.changes([])
  for (const edit of [{ from: 0, to: 5 }, { from: 0, insert: 'Hello' }, { from: 6, to: 11, insert: 'everyone' }]) {
    const transaction = state.update({ changes: edit })
    state = transaction.state
    changes = c.normalizeSuggestionChanges(base, state.doc.toString(), changes.compose(transaction.changes))
    if (state.doc.toString() === base.doc.toString()) assert.equal(changes.empty, true)
  }
  const ranges = []
  changes.iterChanges((from, to, a, b) => ranges.push([from, to, a, b]))
  assert.deepEqual(ranges, [[6, 11, 6, 14]])
})

test('draft edits bypass all document writes and comment anchor mutations', () => {
  const source = fs.readFileSync('web/js/30-highlight-theme.js', 'utf8')
  const calls = [], changes = {}
  const c = vm.createContext({ window: { suggestionDraft: {} }, recordSuggestionEdit: value => calls.push(value),
    gutter: () => assert.fail('must not paint source anchors'), pushLocal: () => assert.fail('must not sync draft'), queueSave: () => assert.fail('must not save draft') })
  vm.runInContext(source.slice(source.indexOf('function onEdit'), source.indexOf('let anchorT')), c)
  c.onEdit(null, changes, 0)
  assert.deepEqual(calls, [changes])
})
test('accepting one draft change preserves the text of remaining changes', async () => {
  const { EditorState } = await import(pathToFileURL(path.resolve('vendor-cm.js')).href)
  const state = EditorState.create({ doc: 'first middle last' })
  const selected = state.changes({ from: 0, to: 5, insert: 'longer first' })
  const rest = state.changes({ from: 13, to: 17, insert: 'end' })
  assert.equal(rest.map(selected).apply(selected.apply(state.doc)).toString(), 'longer first middle end')
})

test('comment navigation uses mapped draft positions', async () => {
  const source = fs.readFileSync('web/js/70-comments-popovers.js', 'utf8')
  let dispatched, opened
  const c = vm.createContext({ window: { suggestionDraft: {} }, docId: 'doc', openN: 1, activeFile: '',
    getT: () => 'draft text', threadEditorRange: () => ({ from: 2, to: 6 }),
    cm: { dispatch: value => dispatched = value, focus() {}, state: { doc: { lineAt: () => ({ number: 1 }) } } },
    EditorView: { scrollIntoView() {} }, openPop: line => opened = line })
  vm.runInContext(source.slice(source.indexOf('async function jumpThread'), source.indexOf('async function refresh(')), c)
  await c.jumpThread({ a: 1000, b: 2000 })
  assert.deepEqual(plain(dispatched.selection), { anchor: 2, head: 6 })
  assert.equal(opened, 1)
})

test('draft preview resolves new template references without adding them to source tabs', () => {
  const source = fs.readFileSync('web/js/80-files-images.js', 'utf8')
  const c = vm.createContext({ window: { suggestionDraft: {} }, activeFile: '', shadow: '',
    getT: () => '#include "new.typ"', effTpl: () => [{ name: 'new.typ', content: 'Hello' }],
    fileCache: new Map(), TextDecoder })
  vm.runInContext(source.slice(source.indexOf('function usedTpls'), source.indexOf('function projectTabEntry')), c)
  assert.deepEqual(plain(c.usedTpls()), [])
  assert.deepEqual(plain(c.usedTpls(true)), ['new.typ'])
})

test('multiline deletions retain the entire old text and open the shared popup directly', () => {
  let opened
  const c = vm.createContext({ WidgetType: class {}, el: (tag, cls, text) => ({ className: cls, textContent: text, dataset: {}, setAttribute() {} }),
    t: value => value, openSuggestionBox: node => opened = node })
  vm.runInContext(code.slice(code.indexOf('class DraftDeletion'), code.indexOf('function sourceToEditor')) + ';globalThis.Deletion = DraftDeletion', c)
  const old = 'removed line\n'.repeat(100), widget = new c.Deletion({ key: '0:1300', old })
  const node = widget.toDOM()
  assert.equal(node.textContent, old)
  assert.equal(widget.lineBreaks, 100)
  assert.ok(node.className.includes('suggestionDeleted'))
  node.onmousedown({ preventDefault() {}, stopPropagation() {} })
  assert.equal(opened, node)
})
test('the sync fallback cannot publish recorded draft text', () => {
  const source = fs.readFileSync('web/js/40-editor-sync.js', 'utf8')
  const c = vm.createContext({ window: { suggestionDraft: {} }, setYText: () => assert.fail('draft leaked to source') })
  vm.runInContext(source.slice(source.indexOf('function pushLocal'), source.indexOf('function pullRemote')), c)
  c.pushLocal()
})
test('suggestion hits use the comment opener and include overlapping comments', () => {
  let opened
  const range = { key: '2:4', a: 2, b: 5 }
  const c = vm.createContext({ window: { suggestionDraft: {} }, draftRanges: () => [range],
    threads: [{ id: 'comment', a: 3, b: 6 }], threadEditorRange: th => ({ from: th.a, to: th.b }),
    cm: { state: { doc: { lineAt: () => ({ number: 1 }) } } }, openPop: (...args) => opened = args })
  vm.runInContext(code.slice(code.indexOf('function openSuggestionBox'), code.indexOf('function draftSuggestionCard')), c)
  const node = { dataset: { suggestionChange: range.key } }
  c.openSuggestionBox(node)
  assert.equal(opened[0], 1)
  assert.equal(opened[3].nodes[0], node)
  assert.deepEqual(plain(opened[3].threadIds), ['comment'])
})

test('source and draft comment positions map through replacement without changing source', async () => {
  const { EditorState } = await import(pathToFileURL(path.resolve('vendor-cm.js')).href)
  const base = EditorState.create({ doc: 'before old after' })
  const changes = base.changes({ from: 7, to: 10, insert: 'replacement' })
  const c = vm.createContext({ window: { suggestionDraft: { base: base.doc.toString(), changes } }, shadow: base.doc.toString() })
  const sync = fs.readFileSync('web/js/40-editor-sync.js', 'utf8')
  vm.runInContext(sync.slice(sync.indexOf('function diffSpan'), sync.indexOf('const deltaMap')), c)
  vm.runInContext(code.slice(code.indexOf('function sourceToEditor'), code.indexOf('function threadEditorRange')), c)
  assert.equal(c.sourceToEditor(11), 19)
  assert.equal(c.editorToSource(19), 11)
  assert.equal(c.editorToSource(8), 7)
  assert.equal(c.editorToSource(8, true), 10)
})

test('sent proposal highlights trim context before mapping into a new draft', async () => {
  const { EditorState } = await import(pathToFileURL(path.resolve('vendor-cm.js')).href)
  const base = 'before old after'
  const changes = EditorState.create({ doc: base }).changes({ from: 0, insert: 'prefix ' })
  const highlights = fs.readFileSync('web/js/20-completions.js', 'utf8')
  const sync = fs.readFileSync('web/js/40-editor-sync.js', 'utf8')
  const c = vm.createContext({ window: {}, threads: [{ id: 's', a: 0, b: base.length, suggestion_status: 'pending', suggestion_old: base, replacement: 'before new after' }],
    threadEditorRange: th => ({ from: c.window.suggestionDraft ? changes.mapPos(th.a, -1) : th.a, to: c.window.suggestionDraft ? changes.mapPos(th.b, 1) : th.b }),
    Decoration: { mark: spec => ({ range: (from, to) => ({ from, to, spec }) }) }, SuggestionReplacement: class { constructor() { this.text = '' } } })
  vm.runInContext(sync.slice(sync.indexOf('function diffSpan'), sync.indexOf('const diffMap')), c)
  vm.runInContext(highlights.slice(highlights.indexOf('function threadHighlights'), highlights.indexOf('function refreshHl')), c)
  assert.deepEqual(plain(c.threadHighlights()).map(r => [r.from, r.to]), [[7, 10]])
  c.window.suggestionDraft = {}
  assert.deepEqual(plain(c.threadHighlights()).map(r => [r.from, r.to]), [[14, 17]])
})
test('draft gutter marks include mapped comments and new draft suggestions', () => {
  const source = fs.readFileSync('web/js/70-comments-popovers.js', 'utf8')
  let painted
  const c = vm.createContext({ window: { suggestionDraft: {} }, docId: 'doc', tplName: '', activeFile: '', marks: new Set(), markStyle: '',
    threads: [{ id: 'comment', anchor: 1 }], threadEditorRange: () => ({ from: 20 }), draftRanges: () => [{ a: 40 }],
    cm: { state: { doc: { lines: 5, lineAt: pos => ({ number: pos / 10 + 1 }), line: n => ({ from: (n - 1) * 10 }) } },
      dispatch: value => painted = value.effects },
    ThreadDot: class { range(from) { return from } }, RangeSet: { of: ranges => ranges }, setMarks: { of: ranges => ranges } })
  vm.runInContext(source.slice(source.indexOf('function gutter'), source.indexOf('let popFresh')), c)
  c.gutter()
  assert.deepEqual(Array.from(c.marks).sort(), [3, 5])
  assert.deepEqual(plain(painted), [20, 40])
})
test('gutter opens every draft change on the same line', () => {
  let box
  const c = vm.createContext({ window: { suggestionDraft: {} }, threads: [], draftRanges: () => [{ key: 'a', a: 1, b: 2 }, { key: 'b', a: 4, b: 5 }],
    cm: { state: { doc: { lineAt: () => ({ number: 1 }) } }, dom: { querySelectorAll: () => [] } },
    openPop: (...args) => box = args[3] })
  vm.runInContext(code.slice(code.indexOf('function openLinePop'), code.indexOf('function draftSuggestionCard')), c)
  c.openLinePop(1)
  assert.equal(box.ranges.length, 2)
})

test('cards label comments and keep dismissal in the trash action for editors', async () => {
  const node = (tag, cls, text) => ({ tag, className: cls, textContent: text, style: {}, children: [],
    append(...items) { this.children.push(...items) }, appendChild(item) { this.children.push(item) }, setAttribute() {} })
  const calls = []
  const c = vm.createContext({ docId: 'doc', openN: 1, docRole: 'editor', openedTrashed: false, user: 'editor',
    el: node, icoBtn: cls => node('button', cls), ICO_TRASH: 'trash', ICO_SEND: 'send', t: value => value,
    ago: () => 'now', colOf: () => 'blue', wireMentions() {}, refresh() {},
    decideSuggestion: (...args) => { calls.push(args); return Promise.resolve() } })
  const sync = fs.readFileSync('web/js/40-editor-sync.js', 'utf8')
  vm.runInContext(sync.slice(sync.indexOf('function diffSpan'), sync.indexOf('const diffMap')), c)
  vm.runInContext(code.slice(0, code.indexOf('async function decideSuggestion')), c)
  const comments = fs.readFileSync('web/js/70-comments-popovers.js', 'utf8')
  vm.runInContext(comments.slice(comments.indexOf('function threadCard'), comments.indexOf('async function loadComments')), c)
  const walk = root => [root, ...root.children.flatMap(walk)]
  const th = { id: 's', username: 'author', created_at: '', replies: [], text: '', quote: '', suggestion_status: 'pending', suggestion_old: 'abc', replacement: 'axc', a: 0 }
  const card = c.threadCard(th)
  assert.equal(walk(card).filter(n => n.textContent === 'comments.accept').length, 1)
  assert.equal(walk(card).filter(n => n.textContent === 'comments.reject').length, 0)
  await walk(card).find(n => n.title === 'comments.delThread').onclick()
  assert.equal(calls[0][1], 'reject')
  const comment = c.threadCard({ ...th, suggestion_status: null })
  assert.ok(walk(comment).some(n => n.textContent === 'comments.newAria'))
})
