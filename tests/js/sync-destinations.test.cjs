const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const read = name => fs.readFileSync('web/js/' + name, 'utf8')
const settings = read('90-settings.js')
const preview = read('50-preview.js')
const slice = (src, a, b) => {
  const i = src.indexOf(a), j = src.indexOf(b, i)
  assert.ok(i >= 0 && j > i, 'missing slice ' + a)
  return src.slice(i, j)
}
const posOfLine = (t, ln) => { let p = 0; for (let i = 1; i < ln; i++) p = t.indexOf('\n', p) + 1; return p }
const item = (s, x0, y, w = 400, h = 22) => ({ s, x0, y, w, h, vw: 1190, vh: 1684, rot: false })

function destCtx({ text, items, imgs = [], maths = [], found = {} }) {
  const log = []
  const c = vm.createContext({ posOfLine, log, Math, items, imgs, maths, found, text })
  vm.runInContext(`
    let syncOn = true, docId = 'd', tplName = '', activeFile = '', openN = 1, pvScale = 2, syncEdOff = 0, syncEdX = -1
    const pvTexts = [items], pvSlots = [{ dataset: { w: 595, r: 1684 / 1190 } }]
    const cm = { state: { doc: { lines: text.split('\\n').length } } }
    function $() { return { clientHeight: 800 } }
    function getT() { return text }
    function pvPageHint() { return 1 }
    function pvSecAtY() { return {} }
    function pvImgMatch() { return imgs }
    function pvMathMatch() { return maths }
    function smMap() { return {} }
    function smTokenAt(M, pi, ii) { return { ti: ii, k: 0 } }
    function smResolve(M, ti) { const p = found[items[ti].s]; return p == null ? null : { key: '', at: p } }
    async function smGo(res) { log.push(['jump', res.at]); return true }
    async function pvJumpSrc(src, col) { log.push(['src', src.key || '', src.line, col]); return true }
    function jumpPos(p) { log.push(['jump', p]) }
  `, c)
  vm.runInContext(slice(settings, 'async function pvSyncDest', 'function pvWordChar'), c)
  return c
}

test('a figure destination at its block top finds the centered picture one block gap below', async () => {
  const text = '= Images\nText before the image paragraph.\n\n#figure(\n  image("img.png", width: 40%),\n  caption: [A small test picture],\n)'
  const items = [item('Text before the image paragraph.', 141, 181), item('Figure 1: A small test picture', 466, 509)]
  const imgs = [{ page: 0, x0: 413, x1: 776, y0: 218, y1: 491, src: { key: '', line: 5 } }]
  const c = destCtx({ text, items, imgs, found: { 'Text before the image paragraph.': 9 } })
  await c.pvSyncDest({ page: 0, top: 742.4, left: 70.87 }) // XYZ: the figure's left margin, 19 px above the picture
  assert.deepEqual(JSON.parse(JSON.stringify(c.log)), [['src', '', 5, 0]])
})

test('a picture with text between it and the destination is not the target', async () => {
  const items = [item('Heading text above', 141, 210), item('Some paragraph', 141, 240)]
  const imgs = [{ page: 0, x0: 413, x1: 776, y0: 300, y1: 500, src: { key: '', line: 9 } }]
  const c = destCtx({ text: 'a\nb', items, imgs, found: { 'Heading text above': 0 } })
  await c.pvSyncDest({ page: 0, top: (1684 - 195) / 2, left: 70 })
  assert.deepEqual(JSON.parse(JSON.stringify(c.log)), [['jump', 0]])
})

test('a bibliography destination anchors to the entry that starts there, not the heading above', async () => {
  const items = [item('Bibliography', 141, 236.6, 182, 30.8), item('[1]', 141, 272), item('D. Knuth,', 182, 272)]
  const c = destCtx({ text: 'x', items, found: { '[1]': 42, Bibliography: 7 } })
  await c.pvSyncDest({ page: 0, top: 717.6, left: 70.87 }) // y = 248.5: inside the heading's lower half, right above the entry
  assert.deepEqual(JSON.parse(JSON.stringify(c.log)), [['jump', 42]])
})

test('an equation destination jumps to the formula below it, not to the paragraph after it', async () => {
  const items = [item('Energy relation below.', 141, 180), item('Second relation follows.', 141, 290)]
  const maths = [{ page: 0, line: { y0: 222, y1: 260 }, src: { key: '', line: 5, own: [{ line: 5, at: 2 }] } }]
  const c = destCtx({ text: 'x', items, maths, found: { 'Second relation follows.': 99 } })
  await c.pvSyncDest({ page: 0, top: (1684 - 212) / 2, left: 70 })
  assert.deepEqual(JSON.parse(JSON.stringify(c.log)), [['src', '', 5, 2]])
})

test('a cursor on a caption line anchors to the caption, the image line to the picture', () => {
  const text = '#figure(\n  image("img.png", width: 40%),\n  caption: [A small test picture],\n)'
  const box = { page: 0, src: { key: '', line: 2 } }
  const c = vm.createContext({ posOfLine, text, box })
  vm.runInContext(slice(preview, 'function srcMask', 'function srcHeadings'), c)
  vm.runInContext(slice(settings, 'const SRC_MATH', 'function srcObjs'), c)
  vm.runInContext(slice(settings, 'function srcLineWords', 'function syncWords'), c)
  vm.runInContext(slice(settings, 'const srcViewLines', 'function pvViewPage'), c)
  vm.runInContext(slice(settings, 'function pvCallEnd', 'function pvFigureHint'), c)
  vm.runInContext('let activeFile = ""; function getT() { return text } function pvImgMatch() { return [box] }', c)
  vm.runInContext(slice(settings, 'function pvImgLineHit', 'function pvMathNorm'), c)
  assert.equal(c.pvImgLineHit(2), box)
  assert.equal(c.pvImgLineHit(1), box) // "#figure(" has no words: the picture
  assert.equal(c.pvImgLineHit(3), null) // the caption has its own words on paper
})

test('a click in a word gap of a hyphen-split paragraph keeps the caret behind the word before it', () => {
  const c = viewCtxLite()
  const src = 'Außerdem gibt es Anführungszeichen und Umlaute. Die Versicherungen verhandeln Arbeitsunfähigkeitsbescheinigungen täglich.'
  const needle = 'Außerdem gibt es Anführungszeichen und Umlaute. Die Versicherungen verhandeln Arbeitsunfä higkeitsbescheinigungen täglich.'
  assert.equal(c.pvViewPos(src, needle, needle.indexOf('gibt es') + 7, 1), src.indexOf('gibt es') + 7) // right behind "es", not on the "A" of the next word
  assert.equal(c.pvViewPos(src, needle, needle.indexOf('Anführ') + 2, 1), src.indexOf('Anführ') + 2)
})

function viewCtxLite() {
  const c = vm.createContext({ posOfLine })
  vm.runInContext(slice(settings, 'const SRC_MATH', 'function srcObjs'), c)
  vm.runInContext(slice(settings, 'function srcLineWords', 'function syncWords'), c)
  return c
}

test('two words matched across raw code are no strong match ("1." of a numbering string + the heading)', () => {
  const c = vm.createContext({ posOfLine })
  vm.runInContext(slice(settings, 'function pvWordChar', 'function cmTop'), c)
  vm.runInContext(slice(settings, 'function pvPosIn', 'function syncToPv'), c)
  const src = '#set heading(numbering: "1.")\n= Intro <intro>\nBody.'
  assert.equal(c.pvPosIn(src, '1. Intro', 0, 1, true), -1)
  assert.equal(c.pvPosIn(src, 'Intro', 0, 2, true), src.indexOf('Intro'))
})
