const assert = require('node:assert/strict')
const { test } = require('node:test')
const { readFileSync } = require('node:fs')
const vm = require('node:vm')
const src = readFileSync('web/js/features/changes.js', 'utf8')
const code = src.slice(0, src.indexOf('// url:'))
const c = vm.createContext({})
vm.runInContext(code, c)
const J = v => JSON.parse(JSON.stringify(v))

test('lineOps marks removed and added lines, keeps equal ones', () => {
  const ops = J(c.lineOps('a\nb\nc', 'a\nB\nc\nd'))
  assert.deepEqual(ops.map(o => o.k + o.s), [' a', 'ab', 'bB', ' c', 'bd'])
  assert.deepEqual(J(c.opStats(c.lineOps('a\nb\nc', 'a\nB\nc\nd'))), { add: 2, del: 1 })
})

test('lineOps handles empty sides (added / deleted file)', () => {
  assert.deepEqual(J(c.lineOps('', 'x\ny')).map(o => o.k), ['b', 'b'])
  assert.deepEqual(J(c.lineOps('x', '')).map(o => o.k), ['a'])
  assert.deepEqual(J(c.lineOps('', '')), [])
})

test('foldOps collapses long unchanged runs but keeps context', () => {
  const a = Array.from({ length: 30 }, (_, i) => 'l' + i), b = a.slice(); b[15] = 'X'
  const folded = J(c.foldOps(c.lineOps(a.join('\n'), b.join('\n')), 3))
  assert.equal(folded.filter(o => o.k === '…').length, 2)
  assert.equal(folded.find(o => o.k === '…').n, 12)
  assert.equal(folded.length, 10) // fold, 3 context, del, add, 3 context, fold
})
