const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const settings = fs.readFileSync('web/js/90-settings.js', 'utf8')
const alignSrc = settings.slice(settings.indexOf('function pvAlign'), settings.indexOf('const PV_MATH_MAX_COST'))
const candsSrc = settings.slice(settings.indexOf('const PV_MATH_MAX_COST'), settings.indexOf('function pvMathMatch'))
const REFERENCE = `
function refCands(L, hint, srcs) {
  const out = []
  for (const f of srcs) {
    const al = __align(L.s, f.s)
    let ratio = al.cost / Math.max(1, L.s.length)
    if (ratio > PV_MATH_MAX_COST) {
      let a = -1, b = -1
      for (let i = 0; i < al.map.length; i++) if (al.map[i] >= 0) { if (a < 0) a = i; b = i }
      const win = b - a + 1
      if (win < 2) continue
      let err = 0
      for (let i = a; i <= b; i++) if (al.map[i] < 0) err++
      ratio = err / win
      if (ratio > PV_MATH_MAX_COST) continue
      if ((win - err) / Math.max(1, f.s.length) < 1 - PV_MATH_MAX_COST) continue
    }
    out.push({ src: f, map: al.map, ratio, score: ratio * 1000 + Math.abs(f.order - hint) })
  }
  return out.sort((a, b) => a.score - b.score)
}
`

function context() {
  const state = { aligns: 0 }
  const c = vm.createContext({ console, state })
  vm.runInContext(alignSrc, c)
  const real = c.pvAlign
  const count = (a, b) => { state.aligns++; return real(a, b) }
  c.__align = count
  c.pvAlign = count
  vm.runInContext(candsSrc + REFERENCE, c)
  return { c, state }
}

function chunk(map, i) {
  if (!map || i < 0 || i >= map.length || map[i] < 0) return 0
  let a = i, b = i
  while (a > 0 && map[a - 1] >= 0) a--
  while (b + 1 < map.length && map[b + 1] >= 0) b++
  return b - a + 1
}
function pick(cands, i) { // the same choice pvMathAt makes for a clicked glyph
  let best = null
  for (const a of cands) {
    const n = chunk(a.map, i)
    if (!n) continue
    if (!best || n > best.n || (n === best.n && a.score < best.score)) best = { n, score: a.score, order: a.src.order }
  }
  if (!best) return cands.length ? [cands[0].src.order, 0] : null
  return [best.order, best.n]
}
function top(cands) {
  if (!cands.length) return null
  const a = cands[0]
  return [a.src.order, a.ratio, a.score, String(a.map)]
}
function visible(rows, candsOf, c) { // cands[0] decides the line box; every glyph decides the click
  return rows.map(row => {
    const cands = candsOf(c, row.line, row.hint, row.srcs)
    return {
      top: top(cands),
      picks: Array.from({ length: row.line.s.length }, (_, i) => pick(cands, i)),
    }
  })
}

const letters = 'abcdefghijklmnopqrstuvwxyz'
function formula(i) {
  const a = letters[i % 26], b = letters[(i * 7 + 5) % 26], n = i % 9
  if (i % 3 === 0) return `${a}${n}+${b}${n}=${a}${n}${b}${n}`
  if (i % 3 === 1) return `(${a}${n}+${b}${n})/${n + 1}`
  return `${a}${n}^2+${b}${n}_${n}`
}
function corpus(count, kind, seed) {
  const srcs = Array.from({ length: count }, (_, i) => ({ key: '', line: i * 4 + 2, end: i * 4 + 2, s: formula(i), own: [], order: i * 4 + 2 }))
  let x = seed >>> 0
  const rnd = k => { x = (Math.imul(x, 1664525) + 1013904223) >>> 0; return x % k }
  const rows = []
  for (let i = 0; i < count; i++) {
    const f = srcs[i]
    let s = f.s
    if (kind === 'subsequence') s = f.s.replace(/[/^_]/g, '')
    else if (kind === 'extra') s = f.s + '√'
    else if (kind === 'wide') {
      s = srcs[i].s + srcs[(i + 1) % count].s + srcs[(i + 2) % count].s
    }
    const line = { s, own: [], x0: 0, x1: 100, y: 50, y0: 40, y1: 60, vw: 600, vh: 800 }
    rows.push({ line, hint: f.order + (kind === 'wide' ? 0 : rnd(9) - 4), srcs })
  }
  return rows
}

test('the hint window returns the same line match and the same glyph pick as the full scan', () => {
  for (const kind of ['exact', 'subsequence', 'extra', 'wide']) {
    const { c } = context()
    const rows = corpus(48, kind, 7)
    const want = visible(rows, (ctx, line, hint, srcs) => ctx.refCands(line, hint, srcs), c)
    const got = visible(rows, (ctx, line, hint, srcs) => ctx.pvMathCands(line, hint, srcs), c)
    assert.deepEqual(got, want, kind + ': observable match changed')
  }
})

test('a far page hint still finds the full match before it stops', () => {
  const { c } = context()
  const srcs = Array.from({ length: 30 }, (_, i) => ({ key: '', line: i + 1, end: i + 1, s: `x${i}+y${i}`, own: [], order: i + 1 }))
  const line = { s: 'x3+y3', own: [], x0: 0, x1: 10, y: 0, y0: 0, y1: 1, vw: 1, vh: 1 }
  const want = c.refCands(line, 1, srcs), got = c.pvMathCands(line, 1, srcs)
  assert.deepEqual(top(got), top(want))
  assert.equal(top(got)[0], 4)
  for (let i = 0; i < line.s.length; i++) assert.deepEqual(pick(got, i), pick(want, i))
})

test('identical formulas keep the closest one, equal distance keeps document order', () => {
  const { c } = context()
  const srcs = ['x+y', 'x+y', 'x+y'].map((s, i) => ({ key: '', line: i + 1, end: i + 1, s, own: [], order: i + 1 }))
  const line = { s: 'x+y', own: [], x0: 0, x1: 10, y: 0, y0: 0, y1: 1, vw: 1, vh: 1 }
  const got = c.pvMathCands(line, 2, srcs), want = c.refCands(line, 2, srcs)
  assert.deepEqual(top(got), top(want))
  assert.deepEqual(pick(got, 1), pick(want, 1))
  assert.equal(top(got)[0], 2)
})

test('the window cuts the alignments on a formula-heavy document', () => {
  const { c, state } = context()
  const rows = corpus(120, 'exact', 11)
  state.aligns = 0
  for (const row of rows) c.pvMathCands(row.line, row.hint, row.srcs)
  const windowed = state.aligns
  state.aligns = 0
  for (const row of rows) c.refCands(row.line, row.hint, row.srcs)
  const exhaustive = state.aligns
  assert.equal(exhaustive, rows.length * rows[0].srcs.length)
  assert.ok(windowed <= rows.length * 12, 'still scanning ' + windowed + ' of ' + exhaustive + ' pairs')
  assert.ok(windowed < exhaustive / 10, 'window saved too little: ' + windowed + ' of ' + exhaustive)
})

test('without a full match the scan stays exhaustive', () => {
  const { c, state } = context()
  const rows = corpus(40, 'extra', 3)
  state.aligns = 0
  for (const row of rows) c.pvMathCands(row.line, row.hint, row.srcs)
  assert.equal(state.aligns, rows.length * rows[0].srcs.length)
})
