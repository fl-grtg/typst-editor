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

function viewCtx(srcs) {
  const c = vm.createContext({ posOfLine, srcList: srcs || [] })
  vm.runInContext(slice(preview, 'function srcMask', 'function srcHeadings'), c)
  vm.runInContext(slice(settings, 'const SRC_MATH', 'function srcObjs'), c)
  vm.runInContext(slice(settings, 'function srcLineWords', 'function syncWords'), c)
  vm.runInContext(slice(settings, 'function pvWordChar', 'function locateNear'), c)
  vm.runInContext('function pvSrcList() { return srcList }', c)
  return c
}

test('a line-break hyphen the PDF text layer drops still finds the source word and letter', () => {
  const src = 'Die Rechtsschutzversicherungsgesellschaften verhandeln Arbeitsunfähigkeitsbescheinigungen täglich.'
  const c = viewCtx()
  const needle = 'Die Rechtsschutzversicherungsgesellschaften verhandeln Arbeitsunfä higkeitsbescheinigungen täglich.' // Typst 0.15: the hyphen glyph is no text
  const off = needle.indexOf('higkeits') + 2 // the "k" of the second half
  const at = c.pvViewPos(src, needle, off, 1)
  assert.equal(at, src.indexOf('higkeits') + 2)
  assert.equal(c.pvViewPos(src, needle, needle.indexOf('Arbeits') + 1, 1), src.indexOf('Arbeits') + 1)
  assert.equal(c.pvViewPos('The therapist lineup is long enough here.', 'herapist lineup is long enoug', 0, 1), -1) // still whole words on both ends, never a word fragment
})

test('a short formula that shares three glyphs with a longer display line is no candidate', () => {
  const c = vm.createContext({})
  vm.runInContext(slice(settings, 'function pvAlign', 'function pvMathMatch'), c)
  const srcs = [
    { key: '', line: 2, end: 2, s: 'a2+b2=c2', own: [], order: 2 }, // inline math in a paragraph above
    { key: '', line: 10, end: 11, s: 'f(x)=x2+2x+1=(x+1)2', own: [], order: 10 },
  ]
  const L = { s: 'f(x)=x2+2x+1' }
  const cands = c.pvMathCands(L, 3, srcs) // the page hint sits right next to the inline formula
  assert.equal(cands[0].src.line, 10)
  assert.ok(!cands.some(k => k.src.line === 2), 'a²+b²=c² must not explain x²+2x+1')
  const wide = c.pvMathCands({ s: 'a2+b2=c2x+y' }, 2, srcs) // a real grid row: the whole cell formula is there
  assert.equal(wide[0].src.line, 2)
})

test('an undrawn page loads its fonts before math detection reads their names', () => {
  const c = vm.createContext({})
  vm.runInContext(slice(preview, 'function pvFontsMissing', 'function pvMat'), c)
  const resolved = new Set(['f1'])
  const page = { commonObjs: { get(n) { if (!resolved.has(n)) throw new Error('not resolved'); return { name: n === 'f2' ? 'NewCMMath-Book' : 'Libertinus' } } } }
  const tc = { items: [{ str: 'Text', fontName: 'f1' }, { str: '𝑥', fontName: 'f2' }, { str: ' ', fontName: 'f3' }] }
  assert.equal(c.pvFontsMissing(tc, page), true)
  assert.equal(c.pvFontName(page, 'f2'), '') // what pvBoxes would store without the operator list
  resolved.add('f2')
  assert.equal(c.pvFontsMissing(tc, page), false) // a blank run never forces an operator list
  assert.equal(c.pvFontName(page, 'f2'), 'NewCMMath-Book')
  const meta = slice(preview, 'function pvPageMeta', 'if (pvBox0')
  assert.match(meta, /pvFontsMissing\(tc, page\)\) \{ try \{ await page\.getOperatorList\(\)/)
  assert.ok(meta.indexOf('pvPageImgs(page, v)') < meta.indexOf('pvBoxes(tc, v, page)'), 'the operator list must run before the boxes read the font names')
})
