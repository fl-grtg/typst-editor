const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const csv = fs.readFileSync('web/js/features/csv.js', 'utf8')
const toolbar = fs.readFileSync('web/js/98-format-toolbar.js', 'utf8')
const plain = value => JSON.parse(JSON.stringify(value))
function csvContext() {
  const handlers = new Map(), toasts = []
  const grid = { hidden: true, classList: { toggle() {} }, addEventListener(type, run) { handlers.set(type, run) }, querySelectorAll: () => [], focus() {}, setPointerCapture() {}, contains: () => true }
  const c = vm.createContext({ window: {}, el: () => grid, $: () => ({ append() {} }), docId: '', tplName: '', activeFile: '', tabName: () => 'main.typ',
    t: key => key, toast: message => toasts.push(message),
    ResizeObserver: class { observe() {} }, MutationObserver: class { observe() {} }, document: {},
    cm: { contentDOM: {}, state: { doc: { length: 0 } }, dispatch() {} } })
  vm.runInContext(csv, c)
  vm.runInContext("csvEditable = true; csvIdentity = 'sheet'; csvRows = [['a','b','c'],['d','e','f'],['g','h','i']]", c)
  return { c, handlers, toasts, rows: () => plain(vm.runInContext('csvRows', c)) }
}
function toolbarSpec(text, from, to, open = '*', close = open) {
  const saved = []
  const c = vm.createContext({ tplName: 'main.typ', activeFile: '', tabName: () => 'main.typ', MutationObserver: class { observe() {} },
    document: { querySelectorAll: () => [] },
    cm: { contentDOM: { getAttribute: () => 'true', addEventListener() {} },
      state: { doc: { get length() { return text.length }, sliceString: (a, b) => text.slice(a, b) }, selection: { main: { from, to } }, facet: () => true },
      dispatch: spec => saved.push(spec), focus() {} }, EditorView: { editable: {} } })
  vm.runInContext(toolbar, c)
  vm.runInContext('fmtWrap(' + JSON.stringify(open) + ', ' + JSON.stringify(close) + ')', c)
  return plain(saved[0])
}
test('block paste re-anchors so Delete clears only the pasted block', () => {
  const { c, handlers, rows } = csvContext()
  vm.runInContext('csvAnchor=[2,2]; csvSelection=[0,0]', c) // stale anchor in the far corner
  handlers.get('paste')({ preventDefault() {}, clipboardData: { getData: () => 'x\ty\nz\tw' } })
  assert.deepEqual(rows(), [['x', 'y', 'c'], ['z', 'w', 'f'], ['g', 'h', 'i']])
  handlers.get('keydown')({ key: 'Delete', preventDefault() {} })
  assert.deepEqual(rows(), [['', '', 'c'], ['', '', 'f'], ['g', 'h', 'i']])
})
test('single-value paste fills the selection and re-anchors its top-left', () => {
  const { c, handlers, rows } = csvContext()
  vm.runInContext('csvAnchor=[2,2]; csvSelection=[0,0]', c)
  handlers.get('paste')({ preventDefault() {}, clipboardData: { getData: () => 'x' } })
  assert.deepEqual(plain(vm.runInContext('[csvAnchor, csvSelection]', c)), [[0, 0], [2, 2]])
  assert.deepEqual(rows(), [['x', 'x', 'x'], ['x', 'x', 'x'], ['x', 'x', 'x']])
})
test('oversized pastes show a hint instead of being silently dropped', () => {
  const { handlers, toasts, rows } = csvContext()
  handlers.get('paste')({ preventDefault() {}, clipboardData: { getData: () => Array(100001).fill('v').join('\t') } })
  assert.equal(toasts[0], 'editor.csvPasteLarge')
  assert.deepEqual(rows(), [['a', 'b', 'c'], ['d', 'e', 'f'], ['g', 'h', 'i']])
})
test('caret between two bold spans inserts markers instead of fusing them', () => {
  const spec = toolbarSpec('*x**y*', 3, 3)
  assert.deepEqual(spec.changes, [{ from: 3, insert: '*' }, { from: 3, insert: '*' }])
})
test('collapsed caret on an own empty pair toggles formatting off', () => {
  let spec = toolbarSpec('**', 1, 1)
  assert.deepEqual(spec.changes, [{ from: 0, to: 1 }, { from: 1, to: 2 }])
  spec = toolbarSpec('#underline[]', 11, 11, '#underline[', ']')
  assert.deepEqual(spec.changes, [{ from: 0, to: 11 }, { from: 11, to: 12 }])
})
test('non-collapsed selection still unwraps its own markers', () => {
  const spec = toolbarSpec('*x*y*', 1, 4)
  assert.deepEqual(spec.changes, [{ from: 0, to: 1 }, { from: 4, to: 5 }])
})
