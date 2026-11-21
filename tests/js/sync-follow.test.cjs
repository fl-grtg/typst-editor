const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const read = name => fs.readFileSync('web/js/' + name, 'utf8')
const settings = read('90-settings.js')
const preview = read('50-preview.js')
const editorSync = read('40-editor-sync.js')
const slice = (src, a, b) => {
  const i = src.indexOf(a), j = src.indexOf(b, i)
  assert.ok(i >= 0 && j > i, 'missing slice ' + a)
  return src.slice(i, j)
}
const posOfLine = (t, ln) => { let p = 0; for (let i = 1; i < ln; i++) p = t.indexOf('\n', p) + 1; return p }
const item = (s, x0, y, w, h = 22) => ({ s, x0, y, w, h, vw: 1190, vh: 1684, rot: false })

function edCtx({ text, items, owned, active = '', secAt = {} }) {
  const log = []
  const c = vm.createContext({ posOfLine, text, items, owned, log, secAt, Math })
  vm.runInContext(`
    let followAll = true, docId = 'd', tplName = '', activeFile = ${JSON.stringify(active)}, syncEdOff = 0, syncEdX = -1, syncEdMiss = false, syncEdT = 0
    const window = {}, SYNC_MS = 60, pvTexts = [items], pvTextDone = [true], pvPageSize = { height: 842 }
    const document = { body: { classList: { contains: () => false } } }
    const slot = { getBoundingClientRect: () => ({ top: 0, height: 1684 }) }
    const pv = { clientHeight: 800, getBoundingClientRect: () => ({ top: 0 }), querySelectorAll: () => [slot] }
    function $() { return pv }
    function isTplKey(k) { return String(k).startsWith('tpl:') }
    function pvViewPage() { return 0 }
    function getT() { return text }
    const cm = { state: { doc: { lines: text.split('\\n').length, lineAt: p => ({ number: text.slice(0, p).split('\\n').length }) } }, scrollDOM: {} }
    function cmTop(p) { return p }
    function smoothFollow(el, y) { log.push(y) }
    function scrollEdge() { return 0 }
    function pvPageHint() { return 1 }
    function pvSecAtY() { return secAt }
    function pvSecAtLine() { return null }
    function pvSections() { return [] }
    function syncText(s) { return String(s).toLowerCase().replace(/[^\\p{L}\\p{N}]+/gu, ' ').trim() }
    function smMap() { return { own: items.map(it => owned[it.s] != null) } }
    function smTokenAt(M, pi, ii) { return ii >= 0 ? { ti: ii, k: 0 } : null }
    function smWordAt(M, ti) { return { key: activeFile, at: owned[items[ti].s] } }
  `, c)
  vm.runInContext(slice(settings, 'function pvItemDist', "$('preview').addEventListener('click'"), c)
  vm.runInContext(slice(settings, 'function pvBlockLines', 'function pvBlockNeedle'), c)
  vm.runInContext(slice(settings, 'function syncEdTab', "try { $('preview').addEventListener('wheel'"), c)
  return c
}

test('reading follow takes the line at the reading point, not a longer line above that spans the middle', () => {
  const text = 'Merged cell content here\nGadget\nOther'
  const items = [item('Merged cell content here', 300, 378, 600), item('Gadget', 141, 400, 70)] // the reading point: viewport middle (y 400), page middle (x 595)
  const c = edCtx({ text, items, owned: { 'Merged cell content here': 0, Gadget: text.indexOf('Gadget') } })
  c.syncToEd()
  assert.deepEqual(c.log, [text.indexOf('Gadget')])
})

test('an open chapter tab follows its own text and leaves main-document text alone', () => {
  const chap = '= Chapter\nChapter words on the page.'
  const items = [item('Chapter words on the page.', 141, 400, 300)]
  const c = edCtx({ text: chap, items, owned: { 'Chapter words on the page.': 10 }, active: 'chap.typ' })
  c.syncToEd()
  assert.deepEqual(c.log, [10])
  const c2 = edCtx({ text: chap, items: [item('Main preface words.', 141, 400, 300)], owned: {}, active: 'chap.typ' })
  c2.syncToEd()
  assert.deepEqual(c2.log, []) // no section of this file at the reading point: no ratio jump inside the chapter
  const c3 = edCtx({ text: chap, items, owned: { 'Chapter words on the page.': 10 }, active: 'tpl:letter.typ' })
  c3.syncToEd()
  assert.deepEqual(c3.log, []) // templates are not on the page
})

test('a generated marker keeps the gap it stands in, so a back-link lands beside its call', () => {
  const c = vm.createContext({})
  vm.runInContext(slice(settings, 'function pvCaptionCut', 'const SRC_MATH'), c)
  vm.runInContext(slice(settings, 'function syncText', 'function syncPlain'), c)
  const row = [item('First claim', 141, 181, 94), item('1', 236, 181, 7, 22), item('and second claim', 248, 181, 155), item('2', 403, 181, 7, 22), item('here. Third claim', 415, 181, 154), item('3', 569, 181, 7, 22), item('ends.', 581, 181, 46)]
  const out = c.pvClickNeedles(row, row[5], 0)
  const nd = out.find(n => !/3/.test(n.s)) // the row without the clicked marker
  assert.ok(nd, JSON.stringify(out))
  assert.equal(nd.s.slice(0, nd.off), 'First claim 1 and second claim 2 here. Third claim') // the third marker follows "Third claim", not the row start
  const v = vm.createContext({})
  vm.runInContext(slice(settings, 'const SRC_MATH', 'function srcObjs'), v)
  const L = v.srcViewScan('Short#footnote[Note body.] here').lines[0]
  assert.equal(L.s, 'Short here')
  assert.equal(L.map[5], 5) // the gap of the marker sits on the #footnote call
})

test('the 1:1 Yjs path repairs a start text that differed from Y', () => {
  const state = { y: 'abc', wrote: null }
  const c = vm.createContext({
    window: {}, state,
    ydoc: { transact: fn => fn() },
    ytext: { get length() { return state.y.length }, toString: () => state.y, insert: (i, s) => { state.y = state.y.slice(0, i) + s + state.y.slice(i) }, delete: (i, n) => { state.y = state.y.slice(0, i) + state.y.slice(i + n) } },
    shadow: 'abc',
    getT: () => 'xQbc', // the editor showed "xbc" (a session left it there), the reader typed Q at 1
    setYText: v => { state.wrote = v; state.y = v }
  })
  vm.runInContext(slice(editorSync, 'function pushLocal', 'function pullRemote') + ';globalThis.__push = pushLocal', c)
  c.__push({ iterChanges: cb => cb(1, 1, 1, 1, { toString: () => 'Q' }) }, 3)
  assert.equal(state.wrote, 'xQbc')
  assert.equal(state.y, 'xQbc')
  assert.equal(c.shadow, 'xQbc')
})

test('a late fallback render never takes the page state back from a newer one', () => {
  const direct = slice(preview, 'async function renderDirect', 'let lastErrToast')
  const claim = direct.indexOf('pvMetaClaim(id)'), shown = direct.indexOf('shownN = id')
  assert.ok(claim > 0 && claim < shown, 'renderDirect must claim the page state before it shows its pages')
  assert.ok(!/pvMetaGen = id/.test(direct), 'renderDirect must not overwrite pvMetaGen unconditionally')
})
