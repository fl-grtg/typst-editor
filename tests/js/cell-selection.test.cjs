const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const source = fs.readFileSync('web/js/features/csv.js', 'utf8')
const plain = value => JSON.parse(JSON.stringify(value))
function gridContext() {
  const handlers = new Map(), saved = []
  const grid = { hidden: true, classList: { toggle() {} }, addEventListener(type, run) { handlers.set(type, run) }, querySelectorAll: () => [], focus() {}, setPointerCapture() {}, contains: () => true }
  const c = vm.createContext({ window: {}, el: () => grid, $: () => ({ append() {} }), docId: '', tplName: '', activeFile: '', tabName: () => 'main.typ',
    ResizeObserver: class { observe() {} }, MutationObserver: class { observe() {} }, cm: { contentDOM: {}, state: { doc: { length: 0 } }, dispatch: value => saved.push(value) }, document: {} })
  vm.runInContext(source, c)
  vm.runInContext("csvEditable = true; csvIdentity = 'sheet'; csvRows = [['a','b','c'],['d','e','f'],['g','h','i']]; csvAnchor=[0,0]; csvSelection=[1,1]; csvSelected=true", c)
  return { c, handlers, saved, grid, rows: () => plain(vm.runInContext('csvRows', c)) }
}
test('rectangular copy/paste preserves quoted tabs, quotes and newlines', () => {
  const { c, handlers, rows } = gridContext()
  vm.runInContext("csvRows=[['a\\tb','quoted \"value\"'],['two\\nlines','end']]", c)
  let clipboard
  handlers.get('copy')({ preventDefault() {}, clipboardData: { setData: (_, text) => clipboard = text } })
  vm.runInContext('csvAnchor=[3,2]; csvSelection=[3,2]', c)
  handlers.get('paste')({ preventDefault() {}, clipboardData: { getData: () => clipboard } })
  assert.deepEqual(rows().slice(3).map(row => row.slice(2)), [['a\tb', 'quoted "value"'], ['two\nlines', 'end']])
})
test('Delete clears every selected cell in one editor transaction', () => {
  const { handlers, saved, rows } = gridContext()
  handlers.get('keydown')({ key: 'Delete', preventDefault() {} })
  assert.deepEqual(rows(), [['', '', 'c'], ['', '', 'f'], ['g', 'h', 'i']])
  assert.equal(saved.length, 1)
})
test('cut keeps its source until paste and overlapping moves use a snapshot', () => {
  const { c, handlers, rows } = gridContext()
  let clipboard
  handlers.get('cut')({ preventDefault() {}, clipboardData: { setData: (_, text) => clipboard = text } })
  assert.equal(rows()[0][0], 'a')
  vm.runInContext('csvAnchor=[0,1];csvSelection=[0,1]', c)
  handlers.get('paste')({ preventDefault() {}, clipboardData: { getData: () => clipboard } })
  assert.deepEqual(rows(), [['', 'a', 'b'], ['', 'd', 'e'], ['g', 'h', 'i']])
})
test('dragging inside an existing selection moves the block without requiring its border', () => {
  const { c, handlers, rows } = gridContext()
  vm.runInContext('csvSelection=[2,2]', c)
  const input = { dataset: { row: '1', col: '1' } }
  handlers.get('pointerdown')({ target: { closest: () => input }, pointerId: 1, preventDefault() {} })
  c.document.elementFromPoint = () => ({ closest: () => ({ dataset: { row: '1', col: '2' } }) })
  handlers.get('pointermove')({ pointerId: 1, clientX: 100, clientY: 100 })
  handlers.get('pointerup')()
  assert.deepEqual(rows(), [['', 'a', 'b', 'c'], ['', 'd', 'e', 'f'], ['', 'g', 'h', 'i']])
})
test('readonly sheets allow copy but reject cut, paste and deletion', () => {
  const { c, handlers, rows, saved } = gridContext()
  vm.runInContext('csvEditable=false', c)
  handlers.get('keydown')({ key: 'Delete', preventDefault() {} })
  handlers.get('paste')({ preventDefault() {}, clipboardData: { getData: () => 'replace' } })
  assert.equal(rows()[0][0], 'a'); assert.equal(saved.length, 0)
})
