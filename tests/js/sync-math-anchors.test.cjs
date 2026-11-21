const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const read = name => fs.readFileSync('web/js/' + name, 'utf8')
const settings = read('90-settings.js')
const preview = read('50-preview.js')
const slice = (src, a, b) => {
  const i = src.indexOf(a), j = src.indexOf(b)
  assert.ok(i >= 0 && j > i, 'missing slice ' + a)
  return src.slice(i, j)
}
const SOURCE = '= Math\n\n$ a + b = c $\n\n#grid(columns: 2, [$ x = 1 $], [$ y = 2 $])\n\n$ i = 5 $\n'
const code = [
  slice(settings, 'const SRC_MATH', 'function srcObjs'),
  slice(preview, 'function srcMask', 'function srcHeadings'),
  'const srcObjCache = new Map();',
  slice(settings, 'function srcObjs', 'const srcObjCache'),
  slice(settings, 'function pvMathNorm', 'function pvSrcMath'),
  slice(settings, 'function pvSrcMath', 'function pvAlign'),
  slice(settings, 'function pvAlign', 'function pvMathMatch'),
  slice(settings, 'function pvMathMatch', 'async function pvJumpSrc'),
  slice(settings, 'async function pvJumpMath', 'function pvScrollBox'),
].join('\n')

function formulaCtx(source, hint) {
  const c = vm.createContext({
    console,
    cm: { state: { doc: { lines: source.split('\n').length } } },
    activeFile: '',
    pvOutlineGen: 0,
    shownN: 0,
    getT: () => source,
    pvMainText: () => source,
    pvSrcList: () => [{ key: '', text: source }],
    pvFileAnchor: () => 0,
    pvPageHint: hint,
    pvSecAtY: () => null,
    pvJumpSrc: async (src, col) => { c.calls.push([src.line, col]); return true },
    calls: [],
  })
  vm.runInContext(code, c)
  c.srcViewOf = t => {
    if (c.__view && c.__text === t) return c.__view
    c.__text = t
    c.__view = c.srcViewScan(t)
    return c.__view
  }
  return c
}

const glyph = (s, x0, y, w = 10) => ({ s, x0, x: x0 + w / 2, w, h: 14, y: y - 7, vw: 600, vh: 800, rot: false, fam: 'NewCMMath-Book' })
const row = (y, glyphs) => glyphs.map((s, i) => glyph(s, 10 + i * 10, y))
const lineHint = (pi, total, n, at, frac) => frac < 0.1 ? 3 : frac < 0.2 ? 5 : 7

test('a formula cell in a grid keeps its own source line and letter', async () => {
  const c = formulaCtx(SOURCE, lineHint)
  c.pvTexts = [[...row(60, ['a', '+', 'b', '=', 'c']), ...row(120, ['x', '=', '1', 'y', '=', '2']), ...row(180, ['i', '=', '5'])]]

  const xHit = c.pvMathAt(0, 15, 120, 1, 1)
  assert.ok(xHit, 'no formula hit on x')
  assert.equal(xHit.src.line, 5)
  await c.pvJumpMath(xHit)
  assert.deepEqual(c.calls.at(-1), [5, SOURCE.split('\n')[4].indexOf('x')])

  const oneHit = c.pvMathAt(0, 35, 120, 1, 1)
  assert.ok(oneHit, 'no formula hit on 1')
  assert.equal(oneHit.src.line, 5)
  await c.pvJumpMath(oneHit)
  assert.deepEqual(c.calls.at(-1), [5, SOURCE.split('\n')[4].indexOf('1')])
})

test('a displayed formula with no matching source line never hijacks a click', () => {
  const source = '= Math\n\n$ a = b $\n'
  const c = formulaCtx(source, () => 3)
  c.pvTexts = [row(120, ['z', '=', '9', '+', '8'])]
  assert.equal(c.pvMathMatch().length, 0)
  assert.equal(c.pvMathAt(0, 15, 120, 1, 1), null)
})

test('every cell of a wide formula row keeps its own source line and letter', async () => {
  const source = '= Wide\n\n#grid(\n  columns: 3,\n  [$ x = 1 $],\n  [$ y = 2 $],\n  [$ z = 3 $],\n)\n'
  const c = formulaCtx(source, () => 5)
  c.pvTexts = [row(60, ['x', '=', '1', 'y', '=', '2', 'z', '=', '3'])]
  assert.equal(c.pvMathMatch().length, 1, 'the wide row lost its formula anchors')
  const lines = source.split('\n')
  for (const [glyph, line, at, x] of [['x', 5, 5, 15], ['y', 6, 5, 45], ['z', 7, 5, 75]]) {
    const hit = c.pvMathAt(0, x, 60, 1, 1)
    assert.ok(hit, 'no formula hit on ' + glyph)
    assert.equal(hit.src.line, line)
    await c.pvJumpMath(hit)
    assert.deepEqual(c.calls.at(-1), [line, lines[line - 1].indexOf(glyph)])
  }
})
