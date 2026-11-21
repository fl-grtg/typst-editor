const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const settings = fs.readFileSync('web/js/90-settings.js', 'utf8')
const code = settings.slice(settings.indexOf('function pvAlign'), settings.indexOf('function pvMathMatch'))
  + settings.slice(settings.indexOf('function pvJumpMath'), settings.indexOf('function pvScrollBox'))
const ctx = vm.createContext({})
vm.runInContext(code, ctx)
const calls = []
ctx.pvJumpSrc = async (src, col) => { calls.push([src.line, col]); return true }

const formula = (line, end, s, own) => ({ key: '', line, end, s, own })

const OWN = [
  { line: 5, at: 1 }, { line: 5, at: 2 },
  { line: 6, at: 1 }, { line: 6, at: 2 },
]

test('a click on a later formula line keeps that line and its exact letter', async () => {
  const src = formula(5, 6, 'xybc', OWN)
  calls.length = 0
  assert.equal(await ctx.pvJumpMath({ src, line: { s: 'b' }, i: 0 }), true)
  assert.deepEqual(calls[0], [6, 1])
})

test('a click on the opening formula line is unchanged', async () => {
  const src = formula(5, 6, 'xybc', OWN)
  calls.length = 0
  assert.equal(await ctx.pvJumpMath({ src, line: { s: 'x' }, i: 0 }), true)
  assert.deepEqual(calls[0], [5, 1])
})
