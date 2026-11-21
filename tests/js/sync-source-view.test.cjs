const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const read = name => fs.readFileSync('web/js/' + name, 'utf8')
const settings = read('90-settings.js')
const preview = read('50-preview.js')
const srcMask = preview.slice(preview.indexOf('function srcMask'), preview.indexOf('function srcHeadings'))
const srcView = settings.slice(settings.indexOf('const SRC_MATH'), settings.indexOf('function srcObjs'))
const ctx = vm.createContext({})
const srcNorm = settings.slice(settings.indexOf('function srcLineWords'), settings.indexOf('function pvCaretIndex')) + settings.slice(settings.indexOf('function syncText'), settings.indexOf('function syncWords'))
vm.runInContext(srcMask + srcView + srcNorm, ctx)

test('a bare URL stays visible text, a real comment still ends the line', () => {
  const view = ctx.srcViewScan('See https://example.com/path for details.\nA real // comment here')
  assert.equal(view.lines[0].s, 'See https://example.com/path for details.')
  assert.equal(view.lines[1].s, 'A real')
})

test('structure regexes see a call after a bare URL, never inside a real comment', () => {
  assert.match(ctx.srcMask('See https://example.com/path #image("dot.png")'), /#image\("dot\.png"\)/)
  assert.doesNotMatch(ctx.srcMask('See // #image("dot.png")'), /#image/)
})

test('emphasis markers inside a word stay literal text, real delimiters do not', () => {
  const view = ctx.srcViewScan('Snake_case star*mid*word and *emph* text.')
  assert.equal(view.lines[0].s, 'Snake_case star*mid*word and emph text.')
})

test('only lowercase http(s) is a URL; another scheme leaves a real comment', () => {
  assert.equal(ctx.srcViewScan('a://b tail').lines[0].s, 'a:')
  assert.equal(ctx.srcViewScan('foo:// bar tail').lines[0].s, 'foo:')
  assert.equal(ctx.srcViewScan('HTTPS://example.com/x tail').lines[0].s, 'HTTPS:')
  assert.equal(ctx.srcViewScan('mailto:foo@example.com tail').lines[0].s, 'mailto:foo@example.com tail')
})

test('a URL keeps its own slashes, stars and brackets as literal text', () => {
  assert.equal(ctx.srcViewScan('Text https://example.com/x//y tail.').lines[0].s, 'Text https://example.com/x//y tail.')
  assert.equal(ctx.srcViewScan('https://x.example/*y* tail').lines[0].s, 'https://x.example/*y* tail')
  assert.equal(ctx.srcViewScan('https://x.example/a[b] tail').lines[0].s, 'https://x.example/a[b] tail')
  const view = ctx.srcViewScan('https://x.example/*y* tail\nnext line stays')
  assert.equal(view.lines[1].s, 'next line stays') // a /* inside a URL never opens a block comment
  assert.equal(ctx.srcViewScan('#box[https://x.example/*y*] tail').lines[0].s, 'https://x.example/*y* tail')
  assert.equal(ctx.srcViewScan('#box[https://x.example/a[b]] tail').lines[0].s, 'https://x.example/a[b] tail') // balanced brackets stay in the link
})

test('a real comment after a URL still ends the line, a URL after a comment stays hidden', () => {
  assert.equal(ctx.srcViewScan('See https://x.example // note').lines[0].s, 'See https://x.example')
  assert.equal(ctx.srcViewScan('// see https://x.example').lines[0].s, '')
})

test('structure scans blank a URL without letting its markup leak into the document', () => {
  assert.doesNotMatch(ctx.srcMask('a://b #image("dot.png")'), /#image/) // the comment hides the call
  assert.match(ctx.srcMask('See https://x.example//p and #image("dot.png")'), /#image\("dot\.png"\)/)
  assert.match(ctx.srcMask('https://x.example/*y*/z #image("dot.png")'), /#image\("dot\.png"\)/) // URL is not a block comment
  assert.doesNotMatch(ctx.srcMask('See https://x.example // #image("dot.png")'), /#image/) // a real comment after the URL
})

const lines = t => Array.from(ctx.srcViewScan(t).lines, l => l.s) // vm arrays: copy into this realm for deepEqual

test('multi-line call arguments are code, their [content] stays visible', () => {
  assert.deepEqual(lines('#figure(\n  image("a.png", width: 50%),\n  caption: [\n    A long caption\n  ],\n) <fig>\nAfter text.'),
    ['', '', '', 'A long caption', '', '', 'After text.'])
  assert.deepEqual(lines('#table(\n  columns: (1fr, 2fr),\n  [Name], [Value],\n)'), ['', '', 'Name Value', ''])
  assert.deepEqual(lines('#set page(\n  header: [Running head],\n  margin: 2cm,\n)\nBody.'), ['', 'Running head', '', '', 'Body.'])
})

test('code blocks, statements and declarations never show their code', () => {
  assert.deepEqual(lines('#{\n  let x = 1\n  [Shown text]\n}\nNext.'), ['', '', 'Shown text', '', 'Next.'])
  assert.deepEqual(lines('#if true [Yes text] else [No text]'), ['Yes text No text'])
  assert.deepEqual(lines('#for x in (1, 2) [Item]'), ['Item'])
  assert.deepEqual(lines('#show: template.with(title: "T")\nBody.'), ['', 'Body.'])
  assert.deepEqual(lines('#let f(x) = {\n  [Hidden def]\n}\n#let note = [Not here]\nShown.'), ['', '', '', '', 'Shown.'])
})

test('an unclosed call or formula while typing never swallows the next section', () => {
  assert.deepEqual(lines('#figure(\n  image("a.png"),\n= Next\nText.'), ['', '', 'Next', 'Text.'])
  assert.deepEqual(lines('A $ lone dollar\n\nNext paragraph.'), ['A lone dollar', '', 'Next paragraph.'])
})

test('multi-line display math is math: commands and shorthands become their glyphs', () => {
  const v = ctx.srcViewScan('$\n  sum_(i=1)^n x -> frac(a, b) <= sqrt(y)\n$\nAfter.')
  assert.equal(v.lines[1].s, '∑ (i=1) n x → (a, b) ≤ √(y)')
  assert.equal(v.lines[3].s, 'After.')
  assert.deepEqual(Array.from(v.math, m => m.line), [2])
  assert.equal(ctx.srcViewScan('$a - b$').lines[0].s, 'a − b') // the PDF shows a minus sign, not a hyphen
})

test('generated and shown text: links, symbols, references, strings, raw tags', () => {
  assert.equal(lines('See #link("https://typst.app") now.')[0], 'See https://typst.app now.')
  assert.equal(lines('Mail #link("mailto:a@b.c") me.')[0], 'Mail a@b.c me.')
  assert.equal(lines('See #link("https://typst.app")[the site] now.')[0], 'See the site now.')
  assert.equal(lines('Arrow #sym.arrow.r here.')[0], 'Arrow → here.')
  assert.equal(lines('See @fig:chart and [@key] or a@b.com.')[0], 'See and or a@b.com.')
  assert.equal(lines('#text(fill: red, "String body")')[0], 'String body')
  assert.equal(lines('#raw("code", lang: "py")')[0], 'code')
  assert.equal(lines('Use ```rust fn main()``` and `` here')[0], 'Use fn main() and here')
  assert.equal(lines('Smile \\u{1F600} now')[0], 'Smile \u{1F600} now')
})

test('every visible character keeps its raw offset', () => {
  for (const src of ['#text(fill: red, "Body")', 'A #link("https://x.io") b', 'Smile \\u{1F600} ok', '$a -> b$']) {
    const L = ctx.srcViewScan(src).lines[0]
    assert.equal(L.map.length, L.s.length, src)
    for (let k = 0; k < L.s.length; k++) if (/[A-Za-z]/.test(L.s[k])) assert.equal(src[L.map[k]], L.s[k], src + ' @' + k)
  }
})

test('statements inside content blocks and styling calls keep word boundaries', () => {
  assert.deepEqual(lines('#let note(x) = box[#if x [a] else [b]]\nShown.'), ['', 'Shown.']) // the outer ] is not eaten: later lines stay visible
  assert.deepEqual(lines('#box[#if c [x]] y\nNext.'), ['x y', 'Next.'])
  assert.deepEqual(lines('#if draft [Draft] else [Final] – see below.'), ['Draft Final – see below.']) // markup continues behind the last block
  assert.deepEqual(lines('#if a {\n  [Yes]\n} else {\n  [No]\n}\nAfter text.'), ['', 'Yes', '', 'No', '', 'After text.'])
  assert.deepEqual(lines('#underline[H]ello and #text(red)[Ge]org'), ['Hello and Georg'])
})

test('a formula line may start with "=", code in math is no glyph', () => {
  const v = ctx.srcViewScan('$ f(x)\n  = x^2 + 1 $\nAfter.')
  assert.equal(v.lines[2].s, 'After.')
  assert.equal(v.math.length, 2) // both lines are formula body, the second one is no heading
  assert.equal(ctx.srcViewScan('$ x #h(1em) y $').lines[0].s, 'x y')
})

test('footnote bodies leave the paragraph and the line view keeps CRLF out of the text', () => {
  const v = ctx.srcViewScan('Short#footnote[Note body.] here\nnext\n\nP')
  assert.equal(v.lines[0].s, 'Short here')
  assert.equal(v.lines[0].note.s, 'Note body.')
  const norm = ctx.srcViewNorm(v)
  assert.ok(norm.s.indexOf('short here') < norm.s.indexOf('next') && norm.s.indexOf('next') < norm.s.indexOf('note body')) // the note follows its paragraph, as on paper
  assert.equal(Array.from(ctx.srcViewScan('A\r\n```\r\ncode\r\n```').lines, l => l.s).join('|'), 'A||code|')
})

test('a soft hyphen shorthand is no word gap', () => {
  assert.equal(ctx.srcViewScan('Silben-?trennung ok').lines[0].s, 'Silbentrennung ok')
})