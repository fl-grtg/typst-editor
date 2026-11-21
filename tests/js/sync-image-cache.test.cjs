const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const settings = fs.readFileSync('web/js/90-settings.js', 'utf8')
const matchSrc = settings.slice(settings.indexOf('function pvImgMatch'), settings.indexOf('function pvImgLineHit'))

function context() {
  const state = { boxes: 0, srcs: 0, sigs: 0, sig: 1, total: 30, lines: [10, 20] }
  const c = vm.createContext({
    state,
    cm: { state: { doc: { get lines() { return state.total } } } },
    pvImgs: [[{ id: 'box' }]],
    pvTexts: [[{}]],
    pvOutlineGen: 0,
    shownN: 1,
    activeFile: '',
    pvSrcSig: () => { state.sigs++; return state.sig },
    pvImgBoxes: () => {
      state.boxes++
      return state.lines.map((line, i) => ({ page: i, x0: 10, y0: line, x1: 60, y1: line + 20, w: 50, h: 20, id: 'img' + line, sig: 's' + line, vh: 1000 }))
    },
    pvSrcImages: () => { state.srcs++; return state.lines.map(line => ({ key: '', line, order: line })) },
    pvImgHint: () => null,
    pvTextSrcLine: () => null,
    pvPageHint: () => state.lines[0],
    pvSecAtY: () => null,
  })
  vm.runInContext(matchSrc, c)
  return { c, state }
}

test('a repeated cursor move reuses the image pairing', () => {
  const { c, state } = context()
  const one = c.pvImgMatch(), again = c.pvImgMatch()
  assert.equal(one, again) // same array: no pairing and no sort
  assert.equal(state.boxes, 1)
  assert.equal(state.srcs, 1)
  assert.equal(state.sigs, 2) // the source is still checked on every call
  assert.equal(JSON.stringify(one.map(m => [m.id, m.src.line])), '[["img10",10],["img20",20]]')
})

test('a source edit rebuilds the image pairing', () => {
  const { c, state } = context()
  const one = c.pvImgMatch()
  state.sig = 2
  const fresh = c.pvImgMatch()
  assert.notEqual(fresh, one)
  assert.equal(state.boxes, 2)
})

test('a render swap or a page that fills in rebuilds the image pairing', () => {
  const { c, state } = context()
  const one = c.pvImgMatch()
  c.pvImgs = [[{ id: 'box' }]] // new render: same content, new page lists
  const swapped = c.pvImgMatch()
  assert.notEqual(swapped, one)
  assert.equal(state.boxes, 2)
  c.pvImgs[0] = [{ id: 'box' }] // progressive rasterization: outer array stays, one page is replaced
  const filled = c.pvImgMatch()
  assert.notEqual(filled, swapped)
  assert.equal(state.boxes, 3)
  c.pvTexts[0] = [{}] // text anchors fill in page by page too
  const texted = c.pvImgMatch()
  assert.notEqual(texted, filled)
  assert.equal(state.boxes, 4)
})

test('a tab, outline or screen change rebuilds the image pairing', () => {
  const { c, state } = context()
  const one = c.pvImgMatch()
  c.activeFile = 'part.typ'
  const tabbed = c.pvImgMatch()
  assert.notEqual(tabbed, one)
  c.pvOutlineGen = 2
  const outlined = c.pvImgMatch()
  assert.notEqual(outlined, tabbed)
  c.shownN = 2
  const shown = c.pvImgMatch()
  assert.notEqual(shown, outlined)
  state.total = 40
  const longer = c.pvImgMatch()
  assert.notEqual(longer, shown)
  assert.equal(state.boxes, 5)
})

test('a render swap never resurrects the old screen boxes', () => {
  const { c } = context()
  const old = c.pvImgMatch()
  assert.equal(old.length, 2)
  c.pvImgs = [[], []] // slot render claimed the page state: pages are blank until drawn
  c.pvTexts = [[], []]
  c.shownN = 2
  assert.equal(c.pvImgMatch().length, 0)
  c.pvImgs[0] = [{ id: 'box' }]
  c.pvTexts[0] = [{}]
  const fresh = c.pvImgMatch()
  assert.notEqual(fresh, old)
  assert.equal(fresh.length, 2)
})

function pairContext(boxes, srcs) {
  const c = vm.createContext({
    state: {},
    cm: { state: { doc: { lines: 100 } } },
    pvImgs: [[{ id: 'box' }]],
    pvTexts: [[{}]],
    pvOutlineGen: 0,
    shownN: 1,
    activeFile: '',
    pvSrcSig: () => 1,
    pvImgBoxes: () => boxes,
    pvSrcImages: () => srcs,
    pvImgHint: () => null,
    pvTextSrcLine: () => null,
    pvPageHint: (page, total, n, sec, frac) => frac, // the box y coordinate is the hint
    pvSecAtY: () => null,
  })
  vm.runInContext(matchSrc, c)
  return c
}
function oldPairs(boxes, srcs) { // the replaced O(boxes x sources) sort, kept as the reference
  const pairs = []
  for (let bi = 0; bi < boxes.length; bi++) {
    const hint = boxes[bi].y0 + boxes[bi].h / 2
    for (let si = 0; si < srcs.length; si++) pairs.push([Math.abs(srcs[si].order - hint), bi, si])
  }
  pairs.sort((a, b) => a[0] - b[0] || a[1] - b[1] || a[2] - b[2])
  const boxUsed = new Set(), srcUsed = new Set(), out = []
  for (const [, bi, si] of pairs) {
    if (boxUsed.has(bi) || srcUsed.has(si)) continue
    boxUsed.add(bi); srcUsed.add(si)
    out.push([bi, srcs[si].si])
  }
  return out.sort((a, b) => a[0] - b[0])
}

test('the lazy nearest pairing is the same greedy pairing as the full pair sort', () => {
  let seed = 20261117
  const rnd = n => { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; return seed % n }
  for (let t = 0; t < 200; t++) {
    const B = 1 + rnd(25), S = 1 + rnd(25)
    const srcs = Array.from({ length: S }, (_, si) => ({ key: '', line: si, order: rnd(12), si: 'src' + si }))
    srcs.sort((a, b) => a.order - b.order) // pvSrcImages: document order, duplicate lines allowed
    const boxes = Array.from({ length: B }, (_, bi) => ({ page: 0, x0: 0, y0: bi * 3, y1: bi * 3 + 2, h: 2, w: 10, vh: 1, id: 'box' + bi, sig: 's' + bi }))
    const got = Array.from(pairContext(boxes, srcs).pvImgMatch(), o => [Number(o.id.slice(3)), o.src.si]).sort((a, b) => a[0] - b[0])
    assert.deepEqual(got, oldPairs(boxes, srcs), 'case ' + t + ': B=' + B + ' S=' + S)
  }
})
