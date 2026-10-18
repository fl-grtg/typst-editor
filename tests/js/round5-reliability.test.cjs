const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const path = require('node:path')
const { pathToFileURL } = require('node:url')

const zz = fs.readFileSync('web/js/features/zz-change-packages.js', 'utf8')
const sug = fs.readFileSync('web/js/features/suggestions.js', 'utf8')
const hlx = fs.readFileSync('web/js/30-highlight-theme.js', 'utf8')
const sync = fs.readFileSync('web/js/40-editor-sync.js', 'utf8')
const docx = fs.readFileSync('web/js/60-docs.js', 'utf8')
const files = fs.readFileSync('web/js/80-files-images.js', 'utf8')
const commentsSrc = fs.readFileSync('web/js/70-comments-popovers.js', 'utf8')

// Round 5 High #1: the comment list can equal lastC while ranges are still missing (WS sync beat the comments GET)
const evalRealm = value => JSON.parse(JSON.stringify(value)) // vm-realm arrays must cross home before deepEqual

test('loadComments dedupe-skip still repaints not-yet-derived comment ranges', async () => {
  const run = async (synced, anchors, activeFile = '') => {
    const counts = {}
    const hit = n => { counts[n] = (counts[n] || 0) + 1 }
    const c = vm.createContext({
      docId: 'd1', openN: 1, activeFile, synced, ytext: synced ? {} : null, lastC: '[]', threads: anchors,
      api: async () => ({ comments: [] }),
      initRanges: () => hit('initRanges'), reanchor: () => hit('reanchor'), gutter: () => hit('gutter'), refreshHl: () => hit('refreshHl'),
      paintBadge: () => {}, popAnchor: null, renderPop: () => {}, $: () => ({ querySelectorAll: () => [] }),
    })
    vm.runInContext(commentsSrc.slice(commentsSrc.indexOf('function repaintCommentRanges'), commentsSrc.indexOf('function paintBadge()')), c)
    await c.loadComments()
    return counts
  }
  assert.deepEqual(await run(true, [{ id: 't', a: null, b: null }]), { initRanges: 1, reanchor: 1, gutter: 1, refreshHl: 1 })
  assert.deepEqual(await run(true, [{ id: 't', a: 0, b: 3 }]), {}) // fully derived: the dedupe stays silent
  assert.deepEqual(await run(false, [{ id: 't', a: null, b: null }]), {}) // before the first sync text: no ghost ranges
  assert.deepEqual(await run(true, [{ id: 't', a: null, b: null }], 'f.typ'), {}) // file tab: main anchors untouched (Fix #4)
})

test('synced event re-runs the whole comment pass once the WS text arrives', () => {
  const line = docx.split('\n').find(l => l.includes("pp.on('synced'"))
  assert.ok(line.includes('reanchor') && line.includes('loadComments'))
  const handlers = {}
  const pp = { on: (ev, fn) => { handlers[ev] = fn } }
  const calls = []
  const c = vm.createContext({
    pp, prov: pp, synced: false, threads: [{ a: null, b: null }],
    updConn: () => calls.push('updConn'), reanchor: () => calls.push('reanchor'),
    loadComments: async () => { calls.push('loadComments') },
  })
  vm.runInContext(line, c)
  handlers.synced(false) // vendor emits synced [false] on disconnect: gates stay closed
  assert.deepEqual(calls, [])
  assert.equal(c.synced, false)
  handlers.synced(false)
  assert.equal(c.synced, false) // s !== true never un-syncs a live status
  handlers.synced(true)
  assert.equal(c.synced, true)
  assert.deepEqual(calls, ['updConn', 'reanchor', 'loadComments'])
  calls.length = 0
  c.synced = false
  c.prov = {}; handlers.synced(true) // destroyed old provider: nothing repaints
  assert.equal(c.synced, false)
  assert.deepEqual(calls, [])
  c.prov = pp; handlers.synced(true) // repeat while ranges are open: reload each time (the real loadComments dedupes the render and repaints the heal)
  assert.deepEqual(calls, ['updConn', 'reanchor', 'loadComments'])
})

// Round 5 High #2: stale positions must be clamped to the changeset length BEFORE mapPos
test('editor edits map thread anchors against the pre-edit length, never past the changeset', async () => {
  const { EditorState } = await import(pathToFileURL(path.resolve('vendor-cm.js')).href)
  const c = vm.createContext({
    window: {}, ytext: {}, tplName: '', docRole: 'owner', activeFile: '', popAnchor: null,
    sessionRecord: () => { throw Error('no session here') }, recordSuggestionEdit: () => { throw Error('no draft here') },
    closePop() {}, gutter() {}, paintOutline() {}, pushLocal() {}, queueRender() {}, queueSave() {}, reanchor() {}, refreshHl() {},
    getT: () => '0123456789x', movePop() {},
  })
  vm.runInContext(hlx.slice(hlx.indexOf('function onEdit'), hlx.indexOf('function initRanges')), c)
  c.threads = [{ id: 't', quote: 'q', anchor: 1, a: 999, b: 1000, suggestion_status: 'pending' }] // stale beyond any doc
  const base = EditorState.create({ doc: '0123456789' })
  const cs = base.changes({ from: 0, insert: 'x' }) // changeset over the OLD doc (length 10)
  assert.doesNotThrow(() => c.onEdit((p, end) => cs.mapPos(p, end ? 1 : -1), cs, 10)) // 999 clamped to 10 before mapPos; the stale range lands on the old end and grows with it
  assert.equal(c.threads[0].a, 11)
  assert.equal(c.threads[0].b, 11)
  c.threads = [{ id: 't', quote: 'q', anchor: 1, a: 1, b: 2, suggestion_status: 'pending' }]
  const empty = EditorState.create({ doc: '' }).changes([])
  assert.doesNotThrow(() => c.onEdit((p, end) => empty.mapPos(p, end ? 1 : -1), empty, 0)) // empty changeset: clamp to 0, then map
  assert.equal(c.threads[0].a, 0)
  assert.equal(c.threads[0].b, 0)
})

test('sync paths hand the pre-sync document length to mapThreads', () => {
  assert.match(sync, /if \(threads\.length\) mapThreads\(map, false, old\.length\)/)
  assert.match(sync, /mapThreads\(map, true, old\.length\)/)
  assert.match(hlx, /mapThreads\(mapPos, true, oldLen\)/)
  assert.match(hlx, /sessionRecord\(changes, oldLen\)/)
  assert.match(hlx, /recordSuggestionEdit\(changes, oldLen\)/)
})

test('session mapping falls back to clamped positions on empty-base entries instead of a RangeError', () => {
  const seen = []
  const mapper = len => ({
    length: len,
    mapPos: p => { seen.push(p); if (p > len) throw new RangeError(`Position ${p} is out of range for changeset of length ${len}`); return p },
    invertedDesc: { length: len, mapPos: p => { seen.push(p); if (p > len) throw new RangeError(`inverted ${p} > ${len}`); return p } },
  })
  const f = { kind: 'file', doc_id: 'd1', path: 'pic.png', action: 'add', base: null, content: 'x', binary: false, delta: mapper(0) }
  const s = { files: new Map([['file:d1:pic.png', f]]) }
  const c = vm.createContext({
    window: { changeSession: s }, activeFile: '', shadow: '',
    sourceToEditor: () => { throw Error('original used') }, editorToSource: () => { throw Error('original used') },
    sessionCurrent: () => ({ kind: 'file', doc_id: 'd1', path: 'pic.png' }),
    sessionKey: k => [k.kind, k.doc_id || '', k.path].join(':'),
  })
  vm.runInContext(sync.slice(sync.indexOf('function diffSpan'), sync.indexOf('const deltaMap')), c)
  vm.runInContext(zz.slice(zz.indexOf('const sessionOriginalSourceMap = sourceToEditor'), zz.indexOf('const sessionSourceApi = api')), c)
  assert.equal(c.sourceToEditor(9), 0) // stale pos 9 vs changeset length 0: exactly the reported crash
  assert.equal(c.editorToSource(9), 0)
  assert.deepEqual(seen, [0, 0]) // mapPos only ever saw the clamped position
})

test('draft mapping clamps stale positions against the draft changeset', () => {
  const seen = []
  const mapper = len => ({
    length: len,
    mapPos: p => { seen.push(p); if (p > len) throw new RangeError(`Position ${p} is out of range for changeset of length ${len}`); return p },
    invertedDesc: { length: len, mapPos: p => { seen.push(p); if (p > len) throw new RangeError(`inverted ${p} > ${len}`); return p } },
  })
  const draft = { base: '', baseState: {}, changes: mapper(0), commentRanges: new Map([['t', { from: 9, to: 12 }]]) }
  const c = vm.createContext({
    window: { suggestionDraft: draft }, shadow: '', cm: { state: { doc: { length: 4 } } }, posOfLine: () => 0,
  })
  vm.runInContext(sync.slice(sync.indexOf('function diffSpan'), sync.indexOf('const deltaMap')), c)
  vm.runInContext(sug.slice(sug.indexOf('function sourceToEditor'), sug.indexOf('function normalizeSuggestionChanges')), c)
  assert.equal(c.sourceToEditor(99), 0)
  assert.equal(c.editorToSource(99), 0)
  let r = c.threadEditorRange({ id: 't' })
  assert.deepEqual([r.from, r.to], [4, 4]) // stored popover targets clamp into the current doc
  draft.commentRanges.clear()
  r = c.threadEditorRange({ id: 't2', a: 9, b: 12 })
  assert.deepEqual([r.from, r.to], [0, 0]) // derived path clamps before the changeset sees the stale anchor
  assert.deepEqual(seen.slice(0, 4), [0, 0, 0, 0]) // mapper only ever saw clamped inputs
})

test('draft edits remap stale popover targets after clamping to the old document', async () => {
  const { EditorState } = await import(pathToFileURL(path.resolve('vendor-cm.js')).href)
  const text = 'abcdefghij'
  const base = EditorState.create({ doc: text })
  const cs = base.changes({ from: 2, insert: 'XY' }) // old length 10
  const draft = { base: text, baseState: base, changes: base.changes([]), commentRanges: new Map([['t', { from: 60, to: 5 }]]) }
  const c = vm.createContext({
    window: { suggestionDraft: draft }, getT: () => 'abXYcdefghij',
    closePop() {}, queueRender() {}, paintOutline() {}, queueMicrotask() {},
  })
  vm.runInContext(sync.slice(sync.indexOf('function diffSpan'), sync.indexOf('const diffMap')), c)
  vm.runInContext(sug.slice(sug.indexOf('function normalizeSuggestionChanges'), sug.indexOf('function draftRanges')), c)
  vm.runInContext(sug.slice(sug.indexOf('function recordSuggestionEdit'), sug.indexOf('function openSuggestionBox')), c)
  assert.doesNotThrow(() => c.recordSuggestionEdit(cs, 10)) // 60 was stale: clamped to 10 before mapPos
  assert.equal(draft.changed, true)
  assert.deepEqual(draft.commentRanges.get('t'), { from: 12, to: 7 })
})

test('corrupt null-base entries raise the conflict message, not a TypeError', () => {
  const c = vm.createContext({ t: k => k, diffSpan: () => ({ a: 0, b: 0 }), sessionSequence: 0,
    EditorState: { create: () => ({ changes: () => ({}) }) } })
  vm.runInContext(zz.slice(zz.indexOf('function sessionRuntime'), zz.indexOf('function sessionChanged')), c)
  assert.throws(() => c.sessionRuntime({ action: 'modify', base: null, content: 'x', changes: [{ old_string: 'a', new_string: 'b' }] }), /comments\.suggestionConflict/)
})

// Round 5 High #2 degrade: a package file that no longer resolves must never crash the session open
test('a broken package file degrades: entry dropped once, then a clean session close', async () => {
  const toasts = [], ended = []
  const s = { project: 'p', files: new Map(), original: false, busy: false, dirty: false, previewRevision: 0, commentRanges: new Map() }
  s.files.set('file:d1:a.typ', { kind: 'file', doc_id: 'd1', path: 'a.typ', action: 'modify', base: 'b', content: 'b', binary: false, changes: [] })
  const c = vm.createContext({
    window: { changeSession: s }, docProject: 'p', docId: 'd1', activeFile: 'a.typ',
    sessionKey: k => [k.kind, k.doc_id || '', k.path].join(':'),
    sessionCurrent: () => ({ kind: 'file', doc_id: 'd1', path: 'a.typ' }),
    sessionEnsure: async () => { throw Error('files.tplGone') },
    toast: m => toasts.push(m), sessionStash() {},
    endChangeSession: async flag => { ended.push(flag); c.window.changeSession = null; return true },
  })
  vm.runInContext(zz.slice(zz.indexOf('async function sessionActivate'), zz.indexOf('async function startChangeSession')), c)
  await c.sessionActivate()
  assert.deepEqual(toasts, ['files.tplGone', 'files.tplGone']) // surface + retry surface the same clear message
  assert.equal(s.files.size, 0) // broken entry dropped once
  assert.deepEqual(ended, [true]) // then the session closes without prompts
  // identity of kind document: never dropped (its edits are unsaved work), straight to the clean close
  toasts.length = 0
  const s2 = { project: 'p', files: new Map(), original: false, busy: false, dirty: false, previewRevision: 0, commentRanges: new Map() }
  s2.files.set('document:d1:', { kind: 'document', doc_id: 'd1', action: 'modify', base: 'b', content: 'b', binary: false, changes: [] })
  c.window.changeSession = s2
  c.sessionCurrent = () => ({ kind: 'document', doc_id: 'd1' })
  await c.sessionActivate()
  assert.deepEqual(toasts, ['files.tplGone'])
  assert.equal(s2.files.size, 1) // document entry kept
  assert.deepEqual(ended, [true, true])
})

// Round 5 High #3: the purple painted set must be exactly the files the package really carries
test('painted package set = only files the package really carries', () => {
  const c = vm.createContext({ window: { changeSession: undefined } })
  vm.runInContext(zz.slice(zz.indexOf('function sessionChanged'), zz.indexOf('const sessionStashKey')), c)
  const file = patch => ({ kind: 'file', doc_id: 'd1', path: 'x', action: 'modify', id: 7, base: 'b', content: 'b', delta: { empty: true }, ...patch })
  assert.equal(c.sessionChanged(file({ content: 'b2', id: 9 })), true) // server-level entry with a real diff
  assert.equal(c.sessionChanged(file({})), false) // untouched main.typ: never purple again
  assert.equal(c.sessionChanged(file({ id: 'draft_3', content: 'b2', delta: { empty: true } })), false) // wrong-buffer record: no delta, not painted
  assert.equal(c.sessionChanged(file({ id: 'draft_3', content: 'b2', delta: { empty: false } })), true) // real local edit: painted
  assert.equal(c.sessionChanged(file({ action: 'delete', content: null })), true)
  assert.equal(c.sessionChanged(file({ action: 'add', base: null, content: 'new' })), true)
  assert.equal(c.sessionChanged(file({ action: 'rename' })), true)
  const s = { files: new Map([['m', file({})], ['x', file({ path: 'y', content: 'b2', id: 9, state: {}, csvBefore: [1] })]]) }
  const out = c.sessionFiles(s)
  assert.deepEqual(evalRealm(out.map(f => f.path)), ['y']) // unchanged main excluded from sidebar AND payload
  assert.equal('state' in out[0] || 'delta' in out[0] || 'csvBefore' in out[0], false) // runtime fields stripped
  assert.deepEqual(evalRealm(c.sessionFiles()), [])
})

// Round 5 #4(b): suggest-mode uploads/deletes stage into a package, never write the live project
test('suggest-mode uploads and deletes stage into a package, never touch the live project', async () => {
  const c = vm.createContext({
    window: { suggestionDraft: { busy: false } },
    docProject: 'p', docId: 'd', activeFile: '',
    TEXT_EXT: /\.(typ|bib|csv|tsv|json|yaml|yml|toml|xml|txt|csl)$/i, lastFiles: [], effTpl: () => [],
    upFile: async () => { throw Error('plain upFile ran') }, upText: async () => { throw Error('plain upText ran') },
    deleteFile: async () => { throw Error('original deleteFile ran') },
    deleteProjectEntry: async () => { throw Error('original deleteProjectEntry ran') },
    renameProjectEntry: async () => {}, newProjectResource: async () => {},
    api: () => { throw Error('no api writes allowed') },
    t: k => k, ask: async () => true, toast: m => { throw Error('unexpected toast: ' + m) },
    sessionKey: k => JSON.stringify(k), sessionRuntime: f => ({ ...f }),
    sessionStash() {}, paintSessionSidebar() {}, paintTabs() {}, queueRender() {}, sessionActivate: async () => {},
  })
  c.staged = []; c.leaved = []
  c.sessionAddFile = async file => { c.staged.push(['add', file.name]); return file.name }
  c.leaveSuggestionDraft = async () => { c.leaved.push(1); c.window.suggestionDraft = null; return true }
  c.startChangeSession = async () => {
    c.window.changeSession = { project: 'p', files: new Map(), commentRanges: new Map(), original: false, busy: false, package: null, title: '', dirty: false, previewRevision: 0 }
    return c.window.changeSession
  }
  c.sessionEnsure = async identity => {
    const f = { ...identity, action: 'modify', base: 'b', content: 'b', binary: !/\.(typ|bib|csv|tsv|json|yaml|yml|toml|xml|txt|csl)$/i.test(identity.path), changes: [] }
    c.window.changeSession.files.set(JSON.stringify(identity), f)
    return f
  }
  const projects = fs.readFileSync('web/js/features/projects.js', 'utf8')
  vm.runInContext(projects.slice(projects.indexOf('function canStageProjectDelete('), projects.indexOf('function projectEntries(')), c)
  vm.runInContext(zz.slice(zz.indexOf('const sessionOriginalUpFile = upFile'), zz.indexOf('const sessionOriginalNewResource = newProjectResource')), c)
  const pic = { name: 'pic.png', size: 10, arrayBuffer: async () => new Uint8Array([1]).buffer }
  assert.equal(await c.upFile(pic), '') // routed: '' like every staged upload (no name, no live write)
  assert.deepEqual(c.staged, [['add', 'pic.png']])
  assert.equal(c.leaved.length, 1)
  assert.equal(c.window.suggestionDraft, null)
  await c.deleteFile('a.typ') // session open now: the chip delete stages via deleteProjectEntry
  const stagedFile = [...c.window.changeSession.files.values()][0]
  assert.equal(stagedFile.path, 'a.typ')
  assert.equal(stagedFile.action, 'delete')
  assert.equal(stagedFile.content, null)
  // user keeps the draft: the upload aborts and the live fallback never runs
  c.leaveSuggestionDraft = async () => { c.leaved.push(1); return false }
  c.window.changeSession = null; c.window.suggestionDraft = {}
  assert.equal(await c.upText({ name: 'x.typ', size: 2, text: async () => 'x' }), '')
  assert.deepEqual(c.staged, [['add', 'pic.png']])
  assert.equal(c.leaved.length, 2)
})

test('sessionReplaceFile swaps an existing file inside the package, add-over-nameExists never blocks it', async () => {
  const data = new Uint8Array([255, 0, 99])
  const want = Buffer.from(data).toString('base64')
  const s = { project: 'p', files: new Map(), original: false, busy: false, dirty: false, commentRanges: new Map(), previewRevision: 0 }
  const c = vm.createContext({
    window: { changeSession: s }, docId: 'd', activeFile: '', lastFiles: [{ name: 'pic.png', size: 2 }],
    TEXT_EXT: /\.(typ|bib|csv|tsv|json|yaml|yml|toml|xml|txt|csl)$/i,
    sessionKey: k => [k.kind, k.doc_id || '', k.path].join(':'),
    sessionRuntime: f => ({ ...f, id: f.id || 'draft_9' }),
    bytesToBase64: bytes => { let text = ''; for (let i = 0; i < bytes.length; i += 8192) text += String.fromCharCode(...bytes.subarray(i, i + 8192)); return btoa(text) },
    btoa: value => Buffer.from(value, 'binary').toString('base64'),
    suggestionChanges: () => [],
    sessionEnsure: async identity => {
      const f = { ...identity, action: 'modify', base: want, content: want, binary: true, changes: [] }
      s.files.set(c.sessionKey(identity), f)
      return f
    },
    sessionStash() {}, paintTabs() {}, paintSessionSidebar() {}, queueRender() {}, sessionActivate: async () => {}, t: k => k,
  })
  vm.runInContext(zz.slice(zz.indexOf('async function sessionReplaceFile'), zz.indexOf('const reviewTools')), c)
  assert.equal(await c.sessionReplaceFile('pic.png', { name: 'new.png', size: data.length, arrayBuffer: async () => data.buffer }), 'pic.png')
  const entry = s.files.get('file:d:pic.png')
  assert.equal(entry.action, 'modify')
  assert.equal(entry.base, want) // base = the stored content
  assert.equal(entry.content, want) // content = the new bytes, base64 like the backend contract
  assert.deepEqual(evalRealm(entry.changes), []) // binary entries carry no change list
  assert.equal(entry.id, 'draft_9') // fresh draft id (a proposal entry keeps its server id via had?.id)
  assert.equal(s.dirty, true)
  await assert.rejects(() => c.sessionReplaceFile('ghost.png', { name: 'g', size: 1, arrayBuffer: async () => data.buffer }), /packages\.fileAbsent/)
  await assert.rejects(() => c.sessionReplaceFile('pic.png', { name: 'big', size: 11 * 1024 * 1024, arrayBuffer: async () => data.buffer }), /docs\.maxKb/)
  s.busy = true
  assert.equal(await c.sessionReplaceFile('pic.png', { name: 'n', size: 1, arrayBuffer: async () => data.buffer }), '')
})

test('media manager gains a replace chip for binary files only while a change session is open', () => {
  const mk = (cls, text) => ({ className: cls || '', textContent: text == null ? '' : String(text), children: [], append(x) { this.children.push(x) }, appendChild(x) { return this.append(x) }, setAttribute() {}, title: '', onclick: null, click() { this.clicked = true } })
  const bar = { style: {}, children: [], replaceChildren() { bar.children = [] }, appendChild(x) { bar.children.push(x) } }
  const input = mk('input', '')
  const c = vm.createContext({
    $: id => (id === 'media' ? bar : input), t: k => k, docRole: 'owner', openedTrashed: false, mediaOpen: true, paintTabs() {},
    window: { changeSession: { original: false } }, pendingReplace: '',
    TEXT_EXT: /\.(typ|bib|csv|tsv|json|yaml|yml|toml|xml|txt|csl)$/i, ICO_DUP: 'dup', ICO_X: 'x',
    el: (tag, cls, text) => mk(cls, text), icoBtn: (cls, icon) => mk(cls, icon),
    deleteFile: () => { throw Error('delete not expected here') }, copyToLibrary: () => {}, mediaInsert: () => 'x',
    cm: { state: { facet: () => true, selection: { main: { from: 0, to: 0 } } }, dispatch() {}, focus() {} }, toast() {},
  })
  vm.runInContext(files.slice(files.indexOf('function renderMediaChips(files)'), files.indexOf("$('mediaBtn').onclick")), c)
  c.renderMediaChips([{ name: 'pic.png', size: 2000 }])
  const chip = bar.children[1] // children[0] is the upload button, the chip follows
  assert.equal(bar.children.length, 2)
  assert.equal(chip.children.length, 4) // name + size + delete X + replace
  chip.children[3].onclick()
  assert.equal(c.pendingReplace, 'pic.png')
  assert.equal(input.clicked, true) // opens the picker directly
  c.renderMediaChips([{ name: 'a.typ', size: 10 }])
  assert.equal(bar.children[1].children.length, 4) // text file: name + size + X + copy, no replace (tab editing covers it)
  c.window.changeSession = null
  c.renderMediaChips([{ name: 'pic.png', size: 2000 }])
  assert.equal(bar.children[1].children.length, 3) // outside a session: name + size + X only
})

test('imgPick performs the one-shot swap in a session and the plain upload otherwise', async () => {
  const input = { files: [], listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn }, onchange: null, value: '' }
  let swaps, picked
  const c = vm.createContext({
    $: () => input, docId: 'd', imgIns: false, TEXT_UP: /\.(typ|bib|csv|tsv|json|yaml|yml|toml|xml|txt|csl)$/i,
    window: { changeSession: { original: false } }, pendingReplace: '',
    toast() {}, queueRender() {}, switchTab: async () => {}, insImage: () => { throw Error('no insert during swap') },
    imgPick: () => {}, sessionReplaceFile: async (n, f) => { swaps.push([n, f.name]); return n },
    upFile: async f => { picked.push(['up', f.name]); return 'x' },
    upText: async f => { picked.push(['txt', f.name]); return 'x' },
  })
  swaps = c.swaps = []; picked = c.picked = []
  vm.runInContext(files.slice(files.indexOf("$('imgPick').addEventListener('cancel',"), files.indexOf("$('editWrap').addEventListener('dragover'")), c)
  assert.equal(typeof input.onchange, 'function')
  const file = { name: 'new.png' }
  c.pendingReplace = 'pic.png'
  input.files = [file]
  await input.onchange()
  assert.deepEqual(swaps, [['pic.png', 'new.png']])
  assert.deepEqual(picked, []) // the plain upload never ran
  assert.equal(c.pendingReplace, '') // one-shot always consumed
  c.window.changeSession = null // outside a session a stale flag falls through to the plain path
  c.pendingReplace = 'stale.png'
  input.files = [{ name: 'a.typ' }]
  await input.onchange()
  assert.deepEqual(picked, [['txt', 'a.typ']])
  assert.deepEqual(swaps, [['pic.png', 'new.png']])
  c.pendingReplace = 'g.png'
  input.listeners.cancel()
  assert.equal(c.pendingReplace, '') // picker dismissed: the swap target must not leak into the next upload
})

test('the round-5 hooks exist where the report prescribes them', () => {
  assert.match(zz, /const stageToPackage/)
  assert.match(zz, /deleteFile = async name =>/)
  assert.match(zz, /async function sessionReplaceFile/)
  assert.match(zz, /function sessionChanged/)
  assert.match(commentsSrc, /function repaintCommentRanges/)
  assert.match(docx, /reanchor\(\); loadComments\(\)\.catch/)
})
