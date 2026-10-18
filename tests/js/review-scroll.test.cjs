const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const { pathToFileURL } = require('node:url')
const path = require('node:path')
const packages = fs.readFileSync('web/js/features/zz-change-packages.js', 'utf8')

test('acceptance refreshes do not rebuild an unchanged review buffer', async () => {
  let resets = 0
  const replacements = []
  let text = 'unchanged'
  const s = { project: 'p' }
  const c = vm.createContext({ window: { changeSession: s }, docProject: 'p',
    sessionCurrent: () => 'document', sessionKey: value => value,
    sessionEnsure: async () => ({ content: text, action: 'modify' }), getT: () => 'unchanged',
    setT: (...args) => { resets++; replacements.push(args) }, cm: { dispatch() {} }, editableComp: { reconfigure() {} }, editMode() {},
    user: 'owner', docRole: 'owner', paintFileExtras() {}, paintCsv() {}, fmtSync() {}, sessionPaint() {},
    paintSuggestionControls() {}, paintSessionSidebar() {}, queueRender() {} })
  vm.runInContext(packages.slice(packages.indexOf('async function sessionActivate'), packages.indexOf('async function startChangeSession')), c)
  await c.sessionActivate(true)
  await c.sessionActivate(true)
  assert.equal(resets, 0)
  text = 'updated'
  await c.sessionActivate(true)
  assert.deepEqual(replacements, [['updated', true]])
  text = 'unchanged'
  await c.sessionActivate()
  assert.deepEqual(replacements[1], ['unchanged', false]) // ordinary navigation still starts a fresh buffer
})

test('replacing a review buffer maps the selection and scroll anchor through text changes', async () => {
  const { EditorState, EditorView } = await import(pathToFileURL(path.resolve('vendor-cm.js')).href)
  const source = fs.readFileSync('web/js/30-highlight-theme.js', 'utf8')
  const sync = fs.readFileSync('web/js/40-editor-sync.js', 'utf8')
  const old = 'line\n'.repeat(100), next = 'inserted\n' + old
  let effects
  const cm = { state: EditorState.create({ doc: old, selection: { anchor: 200, head: 250 } }),
    scrollSnapshot: () => EditorView.scrollIntoView(150, { y: 'start' }),
    setState(state) { this.state = state }, dispatch(spec) { effects = spec.effects } }
  const c = vm.createContext({ cm, EditorState, EditorView, cmExtensions: [], window: {},
    editableComp: { reconfigure: () => 'mode' }, tabComp: { reconfigure: () => 'tabs' },
    editMode: () => [], tabW: 2, indentUnit: { of: () => null } })
  vm.runInContext(sync.slice(sync.indexOf('function diffSpan'), sync.indexOf('const diffMap')), c)
  vm.runInContext(source.slice(source.indexOf('const getT ='), source.indexOf('function onEdit')), c)
  c.next = next
  vm.runInContext('setT(next, true)', c)
  assert.equal(cm.state.doc.toString(), next)
  assert.equal(cm.state.selection.main.anchor, 209)
  assert.equal(cm.state.selection.main.head, 259)
  assert.equal(effects[2].value.range.head, 159)
  assert.equal(c.applying, false)
})

test('late whole-document acceptance echo leaves the displayed text and selection intact', async () => {
  const { EditorState } = await import(pathToFileURL(path.resolve('vendor-cm.js')).href)
  const old = 'old\n'.repeat(100), accepted = 'new\n'.repeat(100)
  let dispatches = 0
  const cm = { state: EditorState.create({ doc: accepted, selection: { anchor: 210 } }),
    dispatch(spec) { dispatches++; this.state = this.state.update(spec).state } }
  const c = vm.createContext({ cm, shadow: old, window: {}, ytext: { toString: () => accepted },
    getT: () => cm.state.doc.toString(), threads: [], activeFile: '', NO_HIST: [],
    jumpWant() {}, reanchor() {}, paintOutline() {}, queueRender() {} })
  vm.runInContext(fs.readFileSync('web/js/40-editor-sync.js', 'utf8'), c)
  c.pullRemote({ delta: [{ delete: old.length }, { insert: accepted }] })
  assert.equal(c.shadow, accepted)
  assert.equal(cm.state.doc.toString(), accepted)
  assert.equal(cm.state.selection.main.head, 210)
  assert.equal(dispatches, 0)
})
