const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const read = name => fs.readFileSync('web/js/' + name, 'utf8')
const settings = read('90-settings.js'), preview = read('50-preview.js')
const cut = (src, a, b) => src.slice(src.indexOf(a), src.indexOf(b))
const ctx = vm.createContext({
  window: {}, isTplKey: k => String(k).startsWith('@tpl/'), tabName: k => String(k).replace(/^@tpl\//, '') || 'main.typ',
  pvMathMatch: () => [], pvImgMatch: () => [],
  pvClickCol: (it, x, y, cssW) => Math.max(0, Math.min(it.s.length, Math.round((x - it.x0) / (it.w / it.s.length)))), // 1 CSS px = 1 unit in these pages
})
vm.runInContext([
  cut(preview, 'function srcMask', 'function srcHeadings'),
  cut(settings, 'const SRC_MATH', 'function srcObjs'),
  cut(settings, 'function srcLineWords', 'function pvCaretIndex'),
  cut(settings, 'function syncText', 'function syncWords'),
  cut(settings, 'function srcAfter', 'function pvViewWords'),
  cut(settings, 'function pvMathNorm', 'function pvSrcMath'),
  read('89-sync-map.js'),
].join('\n'), ctx)

const W = 5 // width of one character in these test pages
function item(s, x0, y, h = 10) { return { s, x0, w: s.length * W, y, h, vw: 600, vh: 800, rot: false, fam: '' } }
function row(y, ...parts) { // "text" or [text, x0]: runs on one baseline, placed left to right with a space between
  let x = 50
  return parts.map(p => { const [s, x0] = Array.isArray(p) ? p : [p, x]; const it = item(s, x0, y); x = x0 + it.w + W; return it })
}
function build(pages, sources, links = []) { return ctx.smBuild(pages, links, Object.entries(sources).map(([key, text]) => ({ key, text }))) }
function clickOn(M, pi, s, k = 0) { // token of the item text s (first word of it) + letter k
  const ii = M.pages[pi].findIndex(it => it.s === s)
  assert.ok(ii >= 0, 'no item ' + s)
  const tk = ctx.smTokenAt(M, pi, ii, M.pages[pi][ii].s.length - M.pages[pi][ii].s.trimStart().length + k)
  return ctx.smResolve(M, tk.ti, tk.k)
}
const plain = v => JSON.parse(JSON.stringify(v)) // objects from the vm realm: compare as data

test('a word on paper lands on its own letter, markup and labels in between do not matter', () => {
  const src = '= Intro <intro>\nSome *bold* text and a #link("https://x.org")[named link] here.\n'
  const M = build([[...row(100, 'Intro'), ...row(130, 'Some', 'bold', 'text and a', 'named link', 'here.')]], { '': src })
  assert.deepEqual(plain(clickOn(M, 0, 'bold', 2)), { key: '', at: src.indexOf('bold') + 2 })
  assert.deepEqual(plain(clickOn(M, 0, 'named link', 6)), { key: '', at: src.indexOf('link]') })
})

test('generated text: lorem, a heading number, a reference and a citation map to the construct that printed them', () => {
  const src = '#set heading(numbering: "1.")\n= Intro\nSee @fig and @knuth now.\n\n#lorem(6)\n'
  const M = build([[...row(100, '1.', 'Intro'), ...row(130, 'See', 'Figure 1', 'and', '[1]', 'now.'), ...row(160, 'Lorem ipsum dolor sit amet in.')]], { '': src })
  assert.equal(clickOn(M, 0, '1.').at, src.indexOf('= Intro'))
  assert.equal(clickOn(M, 0, 'Figure 1').at, src.indexOf('@fig'))
  assert.equal(clickOn(M, 0, '[1]').at, src.indexOf('@knuth'))
  assert.equal(clickOn(M, 0, 'Lorem ipsum dolor sit amet in.', 0).at, src.indexOf('lorem'))
})

test('a lone common word of generated text never jumps to the same word elsewhere', () => {
  const src = 'Mehr in diesem Satz steht.\n\n= Teil\n#lorem(30)\n'
  const lorem = 'Lorem ipsum dolor sit amet consectetur in voluptate velit esse'
  const M = build([[...row(100, 'Mehr in diesem Satz steht.'), ...row(130, 'Teil'), ...row(160, lorem)]], { '': src })
  const ii = M.pages[0].findIndex(it => it.s === lorem), tk = ctx.smTokenAt(M, 0, ii, lorem.indexOf(' in ') + 1)
  assert.equal(M.toks[tk.ti].w, 'in')
  assert.equal(ctx.smResolve(M, tk.ti, 0).at, src.indexOf('#lorem'))
})

test('several generators in one gap: known word counts split them, the inner call wins', () => {
  const src = '= A\n#lorem(3)\n\n#columns(2)[#lorem(4)]\n\n#bibliography("refs.bib")\n'
  const M = build([[...row(100, 'A'), ...row(130, 'Lorem ipsum dolor.'), ...row(170, 'Lorem ipsum dolor sit.'), ...row(210, 'Bibliography')]], { '': src })
  assert.equal(clickOn(M, 0, 'Lorem ipsum dolor.').at, src.indexOf('lorem(3)'))
  assert.equal(clickOn(M, 0, 'Lorem ipsum dolor sit.').at, src.indexOf('lorem(4)'))
  assert.equal(clickOn(M, 0, 'Bibliography').at, src.indexOf('bibliography'))
  assert.equal(ctx.smFind(M, '', src.indexOf('#columns')).ti, M.toks.findIndex(t => t.li[0] === 2)) // cursor on the wrapper: its first printed word
})

test('a second copy (outline entry, footnote) never steals the body text', () => {
  const src = '#outline()\n= Methods\nBody text with a note#footnote[Note text here.] ends.\n'
  const page = [...row(60, 'Contents'), ...row(80, 'Methods', ['1', 500]), ...row(120, 'Methods'), ...row(150, 'Body text with a note', '1', 'ends.'), ...row(700, '1', 'Note text here.')]
  const M = build([page], { '': src })
  const heading = M.toks.findIndex((t, i) => t.w === 'methods' && M.pages[0][t.li[0]].y === 120)
  assert.ok(M.own[heading], 'the heading owns the source title')
  assert.equal(clickOn(M, 0, 'Contents').at, src.indexOf('#outline'))
  const note = ctx.smResolve(M, M.toks.findIndex(t => t.w === 'note' && M.pages[0][t.li[0]].y === 700), 0)
  assert.equal(note.at, src.indexOf('Note text'))
  const mark = M.pages[0].findIndex(it => it.s === '1' && it.y === 150), tk = ctx.smTokenAt(M, 0, mark, 0)
  assert.equal(ctx.smResolve(M, tk.ti, 0).at, src.indexOf('#footnote'))
})

test('bibliography entries open their .bib field; the label opens the entry', () => {
  const src = 'As @knuth shows.\n\n#bibliography("refs.bib")\n'
  const bib = '@book{knuth,\n  title={The TeXbook},\n  author={Knuth, Donald},\n  year={1984},\n  publisher={Addison-Wesley}\n}\n'
  const M = build([[...row(100, 'As', '[1]', 'shows.'), ...row(140, 'Bibliography'), ...row(170, '[1]', 'D. Knuth,', 'The TeXbook.', 'Addison-Wesley,', '1984.')]], { '': src, 'refs.bib': bib })
  const at = (s, k) => { const ii = M.pages[0].findIndex(it => it.s === s && it.y === 170); const tk = ctx.smTokenAt(M, 0, ii, k); return ctx.smResolve(M, tk.ti, tk.k) }
  assert.deepEqual(plain(at('The TeXbook.', 4)), { key: 'refs.bib', at: bib.indexOf('TeXbook') })
  assert.deepEqual(plain(at('D. Knuth,', 3)), { key: 'refs.bib', at: bib.indexOf('Knuth, Donald') })
  assert.deepEqual(plain(at('1984.', 0)), { key: 'refs.bib', at: bib.indexOf('1984') })
  assert.deepEqual(plain(at('[1]', 1)), { key: 'refs.bib', at: 0 })
  assert.equal(clickOn(M, 0, 'Bibliography').at, src.indexOf('bibliography'))
})

test('an included chapter is spliced in at its #include: its words open the chapter file', () => {
  const main = '= Intro\nMain text first.\n#include "chapters/a.typ"\nMain text last.\n'
  const chap = '= Chapter\nChapter body words.\n'
  const M = build([[...row(100, 'Intro'), ...row(130, 'Main text first.'), ...row(160, 'Chapter'), ...row(190, 'Chapter body words.'), ...row(220, 'Main text last.')]], { '': main, 'chapters/a.typ': chap })
  assert.deepEqual(plain(clickOn(M, 0, 'Chapter body words.', 8)), { key: 'chapters/a.typ', at: chap.indexOf('body') })
  assert.deepEqual(plain(clickOn(M, 0, 'Main text last.')), { key: '', at: main.indexOf('Main text last') })
})

test('a word hyphenated across lines is one source word', () => {
  const src = 'Die Arbeitsunfähigkeitsbescheinigung kommt morgen an.\n'
  const M = build([[...row(100, 'Die', 'Arbeitsunfä'), ...row(115, 'higkeitsbescheinigung', 'kommt morgen an.')]], { '': src })
  assert.equal(clickOn(M, 0, 'higkeitsbescheinigung', 0).at, src.indexOf('higkeits'))
})

test('a running page number belongs to the page setup', () => {
  const src = '#set page(numbering: "1")\nBody.\n'
  const M = build([[...row(100, 'Body.'), ...row(780, ['1', 300])]], { '': src })
  assert.equal(clickOn(M, 0, '1').at, src.indexOf('#set page'))
})

test('free space: right of a short line is that line, a margin row only takes margin clicks', () => {
  const page = [...row(100, 'A long first line that fills the whole text block width here.'), ...row(120, 'Short.'), ...row(780, ['7', 300])]
  const short = page.findIndex(it => it.s === 'Short.')
  assert.deepEqual(plain(ctx.smPick(0, page, 340, 121, 1, 1, 600, 800, null)), { ii: short, col: 6 }) // far right of "Short."
  assert.deepEqual(plain(ctx.smPick(0, page, 20, 121, 1, 1, 600, 800, null)), { ii: short, col: 0 }) // left margin
  assert.equal(ctx.smPick(0, page, 300, 500, 1, 1, 600, 800, null).ii, short) // blank page below the text: the last line, not the page number
  assert.equal(ctx.smPick(0, page, 300, 790, 1, 1, 600, 800, null).ii, page.length - 1) // inside the footer band: the page number
})

test('free space between two columns splits at the gutter middle', () => {
  const page = [...row(100, ['Left column words', 50], ['Right column words', 320])]
  assert.equal(ctx.smPick(0, page, 200, 100, 1, 1, 600, 800, null).ii, 0)
  assert.equal(ctx.smPick(0, page, 300, 100, 1, 1, 600, 800, null).ii, 1)
})

test('cursor follow: a word finds its letter on paper, a construct line its first printed word', () => {
  const src = '= Intro\nPlain words here.\n\n#lorem(3)\n'
  const M = build([[...row(100, 'Intro'), ...row(130, 'Plain words here.'), ...row(160, 'Lorem ipsum dolor.')]], { '': src })
  const f = ctx.smFind(M, '', src.indexOf('words') + 2)
  assert.equal(M.toks[f.ti].w, 'words')
  assert.equal(f.k, 2)
  assert.equal(M.toks[ctx.smFind(M, '', src.indexOf('#lorem')).ti].w, 'lorem')
  assert.equal(ctx.smFind(M, '', src.indexOf('\n\n') + 1), null) // a blank line prints nothing
})

test('computed values and loop output land on the expression that printed them', () => {
  const src = 'Text first.\n#let x = 5\nThe value is #x and #(x + 1) computed.\n#for p in ("Ada", "Grace") [Person #p listed. ]\n'
  const M = build([[...row(100, 'Text first.'), ...row(130, 'The value is', '5', 'and', '6', 'computed.'), ...row(160, 'Person Ada listed. Person Grace listed.')]], { '': src })
  assert.equal(clickOn(M, 0, '5').at, src.indexOf('#x'))
  assert.equal(clickOn(M, 0, '6').at, src.indexOf('#(x'))
  const loop = 'Person Ada listed. Person Grace listed.', ii = M.pages[0].findIndex(it => it.s === loop)
  const at = k => { const tk = ctx.smTokenAt(M, 0, ii, loop.indexOf(k)); return ctx.smResolve(M, tk.ti, tk.k).at }
  assert.equal(at('Ada'), src.indexOf('Ada'))
  assert.equal(at('Grace'), src.indexOf('Grace'))
})

test('an author-year citation lands on the key it names', () => {
  const src = 'As shown by @knuth today.\n'
  const M = build([[...row(100, 'As shown by', 'Knuth (1984)', 'today.')]], { '': src })
  assert.equal(clickOn(M, 0, 'Knuth (1984)', 0).at, src.indexOf('knuth'))
  assert.equal(clickOn(M, 0, 'Knuth (1984)', 7).at, src.indexOf('@knuth'))
})

test('a rotated run is a click target of its own', () => {
  const turned = { ...item('Sideways', 300, 300), rot: true, ang: Math.PI / 2 }
  const page = [...row(100, 'Body line on top.'), turned]
  ctx.pvItemDist = (it, x, y) => it === turned ? (Math.abs(x - 300) < 6 && y > 280 && y < 330 ? 0 : 1e6) : 1e6
  assert.equal(ctx.smPick(0, page, 302, 300, 1, 1, 600, 800, null).ii, page.indexOf(turned))
  delete ctx.pvItemDist
})

test('an entry number "[2]" opens its entry even when a field holds the same number', () => {
  const src = 'See @lamport.\n\n#bibliography("refs.bib")\n'
  const bib = '@article{lamport,\n  title={A Document Preparation System},\n  volume={2}\n}\n'
  const M = build([[...row(100, 'See', '[1]'), ...row(140, 'Bibliography'), ...row(170, '[2]', 'A Document Preparation System,', 'Bd.', '2.')]], { '': src, 'refs.bib': bib })
  const at = s => { const ii = M.pages[0].findIndex(it => it.s === s && it.y === 170); const tk = ctx.smTokenAt(M, 0, ii, 1); return plain(ctx.smResolve(M, tk.ti, tk.k)) }
  assert.deepEqual(at('[2]'), { key: 'refs.bib', at: 0 })
})

test('a page that only generated text still maps: every word to the call, the cursor to its output', () => {
  const src = '#lorem(8)\n'
  const M = build([[...row(100, 'Lorem ipsum dolor sit amet consectetur adipiscing elit.')]], { '': src })
  assert.equal(clickOn(M, 0, 'Lorem ipsum dolor sit amet consectetur adipiscing elit.', 0).at, src.indexOf('lorem'))
  assert.equal(ctx.smFind(M, '', 1).ti, 0)
})

test('cursor follow inside a long generated block stays linear', () => {
  const words = Array.from({ length: 6000 }, (_, i) => 'w' + (i % 50)).join(' ')
  const src = '= Start\n#lorem(6000)\n= End\n'
  const M = build([[...row(100, 'Start'), ...Array.from({ length: 300 }, (_, r) => item(words.split(' ').slice(r * 20, r * 20 + 20).join(' '), 50, 120 + r * 2)), ...row(900, 'End')]], { '': src })
  const t = Date.now()
  assert.ok(ctx.smFind(M, '', src.indexOf('#lorem')))
  assert.ok(Date.now() - t < 1000, 'smFind took ' + (Date.now() - t) + 'ms')
})

test('a one-line .bib entry still opens the clicked field', () => {
  const src = 'See @k.\n#bibliography("refs.bib")\n'
  const bib = '@book{k, title={Tiny Book}, publisher={Press}}\n'
  const M = build([[...row(100, 'See', '[1]'), ...row(140, 'Bibliography'), ...row(170, '[1]', 'Tiny Book.', 'Press.')]], { '': src, 'refs.bib': bib })
  const ii = M.pages[0].findIndex(it => it.s === 'Press.'), tk = ctx.smTokenAt(M, 0, ii, 0)
  assert.equal(M.own[tk.ti], null) // one word alone: no run owns it, the entry decides
  assert.deepEqual(plain(ctx.smResolve(M, tk.ti, tk.k)), { key: 'refs.bib', at: bib.indexOf('Press') })
})
