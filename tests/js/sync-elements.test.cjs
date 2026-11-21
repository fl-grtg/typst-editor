const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const { loadMap, useDoc } = require('./sync-map-ctx.cjs')
const read = name => fs.readFileSync('web/js/' + name, 'utf8')
const settings = read('90-settings.js')
const preview = read('50-preview.js')
const slice = (src, a, b) => {
  const i = src.indexOf(a), j = src.indexOf(b)
  assert.ok(i >= 0 && j > i, 'missing slice ' + a)
  return src.slice(i, j)
}
const posOfLine = (t, ln) => { let p = 0; for (let i = 1; i < ln; i++) p = t.indexOf('\n', p) + 1; return p }
const page = texts => texts.map((s, y) => ({ s, y: y * 20, vh: 800 }))

function syncCtx() {
  const c = vm.createContext({ posOfLine })
  vm.runInContext(slice(preview, 'function srcMask', 'function pvSecAt'), c)
  vm.runInContext(slice(settings, 'const SRC_MATH', 'function srcObjs'), c)
  vm.runInContext(slice(settings, 'function syncText', 'function syncToPv'), c)
  vm.runInContext(slice(settings, 'function srcLineWords', 'function pvCaretIndex') + slice(settings, 'function srcAfter', 'function pvViewWords'), c)
  loadMap(c)
  c.anchor = (lines, line, pages) => { useDoc(c, lines, pages); return c.syncAnchor(lines, line) }
  return c
}

test('argument lines of a multi-line call never anchor to body text with the same words', () => {
  const c = syncCtx()
  const lines = ['#figure(', '  image("chart.png", width: 80%),', '  caption: [Width of the chart],', ')', '', 'The chart png width is shown at 80 percent.']
  const pages = [page(['Figure 1: Width of the chart', 'The chart png width is shown at 80 percent.'])]
  assert.equal(c.anchor(lines, 2, pages), null) // "chart png width 80" is code, not the paragraph below
  assert.equal(c.anchor(lines, 3, pages).it.s, 'Figure 1: Width of the chart')
  const table = ['#table(', '  columns: (1fr, 2fr),', '  [Columns], [Value],', ')']
  assert.equal(c.anchor(table, 2, [page(['Columns Value'])]), null)
})

test('statements and code blocks have no words on paper; their content does', () => {
  const c = syncCtx()
  const lines = ['#if true [', '  Conditional paragraph text here.', '] else [', '  Other branch.', ']', '#let title = [Conditional paragraph text here]']
  const pages = [page(['Conditional paragraph text here.'])]
  assert.equal(c.anchor(lines, 2, pages).it.s, 'Conditional paragraph text here.')
  assert.equal(c.anchor(lines, 6, pages), null) // a definition renders where it is used, not here
})

test('localized figure supplements are cut from caption needles', () => {
  const c = vm.createContext({})
  vm.runInContext(slice(settings, 'function pvCaptionCut', 'function pvBlockLines'), c)
  for (const [s, rest] of [['Tableau 2 : Données', 'Données'], ['Figura 3. Mapa', 'Mapa'], ['Abbildung A.1: Aufbau', 'Aufbau'], ['図 1: 構成', '構成'], ['Table II: Z', 'Z']]) {
    assert.equal(s.slice(c.pvCaptionCut(s)), rest)
  }
  for (const s of ['Figured out how', 'Figure 10 shows the trend', 'Tables are nice']) assert.equal(c.pvCaptionCut(s), 0)
})

test('a numbered display formula is still a display formula', () => {
  const c = vm.createContext({})
  vm.runInContext(slice(settings, 'function pvMathNorm', 'function pvSrcMath'), c)
  const g = (s, x0, fam = 'NewCMMath-Book') => ({ s, x0, w: 10, h: 14, y: 100, vw: 600, vh: 800, rot: false, fam })
  const row = [g('a', 200), g('=', 210), g('b', 220), g('(1)', 540, 'NewCM10-Regular')]
  assert.equal(c.pvMathLines(row).length, 1) // the equation number sits in the body font beside it
  assert.equal(c.pvMathLines(row)[0].s, 'a=b')
  const inline = [g('Let', 20, 'NewCM10-Regular'), g('x', 60), g('be large.', 80, 'NewCM10-Regular')]
  assert.equal(c.pvMathLines(inline).length, 0) // real prose beside it: inline math
})

function viewCtx() {
  const c = vm.createContext({ posOfLine, tabName: k => k, srcMask: null })
  vm.runInContext(slice(preview, 'function srcMask', 'function srcHeadings'), c)
  vm.runInContext(slice(settings, 'const SRC_MATH', 'function srcObjs'), c)
  vm.runInContext('const srcObjCache = new Map();' + slice(settings, 'function srcObjs', 'const srcObjCache'), c)
  vm.runInContext(slice(settings, 'function srcLineWords', 'function syncWords'), c)
  vm.runInContext(slice(settings, 'function pvFileAnchor', 'function pvSrcImages'), c)
  return c
}

test('Chinese and Japanese text matches letter by letter across line wraps', () => {
  const c = viewCtx(), t = '这是第一行文字，这是第二行内容。\n另一段 text here.'
  assert.equal(c.pvViewPos(t, '第二行内容', 2, 1), t.indexOf('行内'))
  assert.equal(c.pvViewPos(t, '第一行文字这是第二行', 6, 1), t.indexOf('是第二')) // a wrapped line: the clicked character, not the paragraph start
  assert.equal(c.syncText('日本語のテキスト'), '日 本 語 の テ キ ス ト')
})

test('image sources are real calls: several per line, no config, no vector art, no prose', () => {
  const c = viewCtx()
  const objs = c.srcObjs('#set image(width: 50%)\n#grid(image("a.png"), image("b.png"))\n#image("v.svg")\n#image.decode("<svg/>")\nthe image(s) shown\n```\nimage("x.png")\n```')
  assert.deepEqual(Array.from(objs.images, o => o.line), [2, 2, 4])
})

test('a listing as a call argument and named strings are visible text', () => {
  const c = viewCtx()
  const lines = src => Array.from(c.srcViewScan(src).lines, l => l.s)
  assert.deepEqual(lines('#figure(\n  ```python\n  def f(x): return [x]\n  ```,\n  caption: "Plot",\n)\nAfter.'), ['', '', '  def f(x): return [x]', '', 'Plot', '', 'After.'])
  assert.deepEqual(lines('#set page(header: "Draft", margin: 2cm)\n#set document(title: "Meta")'), ['Draft', ''])
  assert.deepEqual(lines('#outline(title: "Inhalt")'), ['Inhalt'])
})

test('an include resolves by full path first and in every common form', () => {
  const c = viewCtx(), main = ['= A', '#include "appendix/intro.typ"', '#let x = include "chapters/intro.typ"', '#{ include("chapters/two.typ") }'].join('\n')
  assert.equal(c.pvFileAnchor('chapters/intro.typ', main), 3) // same file name in another folder never wins
  assert.equal(c.pvFileAnchor('chapters/two.typ', main), 4)
  assert.equal(c.pvFileAnchor('appendix/intro.typ', main), 2)
})
test('the structure mask reads left to right: raw and URLs hide comment starters, headings may be functions', () => {
  const c = vm.createContext({})
  vm.runInContext(slice(preview, 'function srcMask', 'function pvOlNorm'), c)
  const mask = c.srcMask('A `/*` b\n= H\nc `*/` d\nsee https://x.io/a//b #image("x.png") // note')
  assert.ok(mask.includes('= H') && mask.includes('#image("x.png")') && !mask.includes('note')) // "/*" inside raw opens no comment
  assert.equal(mask.length, 'A `/*` b\n= H\nc `*/` d\nsee https://x.io/a//b #image("x.png") // note'.length)
  const heads = Array.from(c.srcHeadings('= A // todo\n#heading(level: 2)[Sub *x*]\n#heading[Plain]\n=== `code` // c'), h => [h.line, h.level, h.title])
  assert.deepEqual(heads, [[1, 1, 'A'], [2, 2, 'Sub *x*'], [3, 1, 'Plain'], [4, 3, '`code`']])
})

test('a BibTeX file keeps its text: no Typst comment, code or math rules apply', () => {
  const c = viewCtx()
  const v = c.srcViewOf('@article{key,\n  title = {Deep // learning #1 $x$},\n}')
  assert.equal(v.lines[1].s, 'title = {Deep // learning #1 $x$},')
})

test('generated numbers and custom supplements are cut from the needles the source can match', () => {
  const c = vm.createContext({})
  vm.runInContext(slice(settings, 'function pvCaptionCut', 'const SRC_MATH'), c)
  assert.equal(c.pvNumCut('1.2 Results'), 4)
  assert.equal(c.pvNumCut('A. Anhang'), 3)
  assert.equal(c.pvNumCut('Plain words'), 0)
  assert.equal(c.pvSuppCut('Fig. 2: Bars'), 8)
  assert.equal(c.pvSuppCut('Exhibit 3 – Bars'), 12)
  assert.equal(c.pvSuppCut('Version 2 shipped'), 0)
})