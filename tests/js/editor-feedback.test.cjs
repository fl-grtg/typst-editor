const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const read = name => fs.readFileSync('web/js/' + name, 'utf8')
const code = read('90-settings.js')
const pvCode = read('50-preview.js')
const syncSlice = code.slice(code.indexOf('function syncText'), code.indexOf('function syncToPv'))
const pvSlice = pvCode.slice(pvCode.indexOf('function srcMask'), pvCode.indexOf('function pvSecAt'))
const outlineSlice = code.slice(code.indexOf('function pvOlEq'), code.indexOf("$('preview').addEventListener('click'"))
const ctx = vm.createContext({ posOfLine: (t, ln) => { let p = 0; for (let i = 1; i < ln; i++) p = t.indexOf('\n', p) + 1; return p } })
vm.runInContext(pvCode.slice(pvCode.indexOf('function srcMask'), pvCode.indexOf('function pvSecAt')), ctx)
vm.runInContext(syncSlice, ctx)
const page = texts => texts.map((s, y) => ({ s, y: y * 20, vh: 800 }))
function outlineCtx(extra) { // real source parser + heading matcher, not stubs
  const c = vm.createContext({ posOfLine: (t, ln) => { let p = 0; for (let i = 1; i < ln; i++) p = t.indexOf('\n', p) + 1; return p },
    renderN: 1, pvOutline: [], pvOutlineGen: 1, ...extra })
  vm.runInContext(syncSlice, c)
  vm.runInContext(pvSlice, c)
  vm.runInContext(outlineSlice, c)
  return c
}

test('sync uses the complete heading rather than a shared word', () => {
  const pages = [page(['A: Ziel', 'B: Materialien & Chemikalien', 'D: Beobachtung', 'E: Erklärung & Auswertung'])]
  assert.equal(ctx.syncAnchor(['=== E: Erklärung & Auswertung'], 1, pages).it.s, 'E: Erklärung & Auswertung')
  assert.equal(ctx.syncAnchor(['=== B: Materialien & Chemikalien'], 1, pages).it.s, 'B: Materialien & Chemikalien')
})
test('repeated headings resolve within their preceding section', () => {
  const lines = ['== 1. GOD-Probe', '=== A: Ziel', '=== D: Beobachtung', '== 2. Betaisodona-Probe', '=== A: Ziel', '=== D: Beobachtung']
  const pages = [page(['1. GOD-Probe', 'A: Ziel', 'D: Beobachtung']), page(['2. Betaisodona-Probe', 'A: Ziel', 'D: Beobachtung'])]
  assert.equal(ctx.syncAnchor(lines, 3, pages).pi, 0)
  assert.equal(ctx.syncAnchor(lines, 6, pages).pi, 1)
})
test('split PDF text matches a heading and ambiguous or unfinished input stays still', () => {
  assert.equal(ctx.syncAnchor(['=== Materialien & Chemikalien'], 1, [page(['Materialien', '& Chemikalien'])]).it.s, 'Materialien')
  assert.equal(ctx.syncAnchor(['=== Ziel'], 1, [page(['Ziel', 'Ziel'])]), null)
  assert.equal(ctx.syncAnchor(['#grid(columns: (50%, 50%))'], 1, [page(['columns'])]), null)
  assert.equal(ctx.syncAnchor(['unfinished typing'], 1, [page(['Other text'])]), null)
})
test('command lines never anchor to a generated caption prefix', () => {
  const lines = ['= Table and Diagram', '#figure(', '  table(', '    [Name], [Value],', '  caption: [Fundamental constants.],', ')', '#pagebreak()', '#figure(', '  chart body', ')']
  const pages = [page(['Table and Diagram', 'Name Value', 'Fundamental constants.']), page(['Figure 1: Diagram'])]
  assert.equal(ctx.syncAnchor(lines, 2, pages), null)
  assert.equal(ctx.syncAnchor(lines, 3, pages), null)
  assert.equal(ctx.syncNearHit(lines, 2, pages).pi, 0)
})
test('a figure caption further down still names the page of its call', () => {
  const body = Array.from({ length: 20 }, (_, i) => `  #let n${i} = ${i}`)
  const lines = ['= Chart', '#figure(', ...body, '  caption: [Simple bar diagram.],', ')']
  const pages = [page(['Chart']), page(['Figure 1: Simple bar diagram.', '4. Conclusion'])]
  assert.equal(ctx.syncAnchor(['#figure('], 1, pages), null)
  assert.equal(ctx.syncNearHit(lines, 2, pages).pi, 1)
})
test('lines inside a figure call stay on the caption page', () => {
  const lines = ['= Chart', '#figure(', '  align(center)[', '    #let data = (', '      ("A", 40),', '    )', '  ],', '  caption: [Simple bar diagram.],', ')', '', '= Next']
  const pages = [page(['Chart']), page(['Figure 1: Simple bar diagram.', 'Next'])]
  assert.equal(ctx.syncAnchor(lines, 4, pages), null)
  assert.equal(ctx.syncNearHit(lines, 4, pages, { page: 0, endPage: 1, endLine: 10 }).pi, 1)
})
test('blank clicks around a rendered outline keep the outline line', () => {
  const c = outlineCtx({
    pvLinks: [[{ x0: 10, y0: 100, x1: 300, y1: 116, dest: { page: 1 } }]],
    getT: () => '#outline()\n\n= Alpha\n\nText\n\n#pagebreak()\n\n= Beta\n',
  })
  const items = [{ s: 'Alpha', x0: 20, y: 108, w: 40 }]
  assert.equal(c.pvOutlineClick(0, items, 30, 124, 1, 1), 1) // one blank line below the entry
  assert.equal(c.pvOutlineClick(0, items, 30, 160, 1, 1), 0) // body text below the block
  assert.equal(c.pvOutlineClick(0, items, 400, 124, 1, 1), 0) // beside the page, not the entry
  assert.equal(c.pvOutlineClick(1, items, 30, 124, 1, 1), 0) // page without outline links
})
test('an outline test per entry never covers the blank space up to a body link', () => {
  const c = outlineCtx({
    pvLinks: [[
      { x0: 10, y0: 100, x1: 300, y1: 116, dest: { page: 0 } }, // outline entry
      { x0: 10, y0: 400, x1: 300, y1: 416, dest: { page: 1 } }, // body link with the same title
    ]],
    getT: () => '#outline()\n\n= Alpha\n\n#link(<alpha>)[Alpha]\n',
  })
  const entry = [{ s: 'Alpha', x0: 20, y: 108, w: 40 }]
  const body = [{ s: 'Alpha', x0: 20, y: 408, w: 40 }]
  assert.equal(c.pvOutlineClick(0, entry, 30, 124, 1, 1), 1) // blank line under the outline entry
  assert.equal(c.pvOutlineClick(0, body, 30, 300, 1, 1), 0) // between outline and body link: no union
})
test('a body link sharing only a word with a heading is not an outline entry', () => {
  const c = outlineCtx({
    pvLinks: [[{ x0: 10, y0: 400, x1: 300, y1: 416, dest: { page: 1 } }]],
    getT: () => '#outline()\n\n= Introduction\n\n#link(<x>)[Intro]\n',
  })
  assert.equal(c.pvOutlineClick(0, [{ s: 'Intro', x0: 20, y: 408, w: 40 }], 30, 402, 1, 1), 0)
})
test('outline detection ignores fenced code and comments', () => {
  const c = outlineCtx({})
  const t = ['```typst', '#outline()', '= Fake heading', '```', '', '/* #outline()', '= Also fake */', '', '= Real heading', '', '#outline()'].join('\n')
  assert.deepEqual(Array.from(c.srcHeadings(t), h => [h.line, h.title]), [[9, 'Real heading']])
  assert.equal(c.srcOutlineLine(t), 11)
})
test('brackets inside block comments or strings do not end a figure early', () => {
  const lines = ['#figure(', '  /* ) ] /* still */ ) */', '  "a ) string",', '  box[rect()],', '  caption: [Panel layout note.],', ')']
  assert.equal(ctx.pvCallEnd(lines, 1), 6)
  const pages = [page(['Figure 1: Panel layout note.'])]
  assert.equal(ctx.pvFigureHint(lines, 4, pages).pi, 0)
  assert.equal(ctx.syncNearHit(lines, 4, pages).pi, 0)
})
test('URLs do not start a comment that swallows the closing bracket', () => {
  const lines = ['#figure(', '  image("x.png"),', '  caption: [See https://example.com],', ')', '', '#pagebreak()', '', '= Next page', 'Body.']
  assert.equal(ctx.pvCallEnd(lines, 1), 4)
  const pages = [page(['Figure 1: See https://example.com']), page(['Next page', 'Body.'])]
  assert.equal(ctx.syncNearHit(lines, 6, pages).pi, 1)
})
test('a blank line after a pagebreak follows the next page', () => {
  const lines = ['= Alpha', 'Alpha body.', '#pagebreak()', '', 'Beta body.']
  const pages = [page(['Alpha', 'Alpha body.']), page(['Beta body.'])]
  assert.equal(ctx.syncNearHit(lines, 4, pages).pi, 1) // the pagebreak wins over the text above
})
test('a blank line before a pagebreak stays on the page above', () => {
  assert.equal(ctx.syncNearHit(['', '#pagebreak()', 'Beta body.'], 1, [page([]), page(['Beta body.'])]), null) // page 2 is below the break
  assert.equal(ctx.syncNearHit(['Alpha body.', '', '#pagebreak()', 'Beta body.'], 2, [page(['Alpha body.']), page(['Beta body.'])]).it.s, 'Alpha body.')
})
test('a column break separates the two columns like a pagebreak', () => {
  const lines = ['Left column text.', '', '#colbreak()', '', 'Right column text.']
  const pages = [page(['Left column text.', 'Right column text.'])]
  assert.equal(ctx.syncNearHit(lines, 4, pages).it.s, 'Right column text.')
})
test('a pagebreak inside a fenced example is not a page boundary', () => {
  const lines = ['= Alpha', '```typst', '#pagebreak()', '```', '', 'Body text.']
  const pages = [page(['Alpha']), page(['Body text.'])]
  assert.equal(ctx.syncNearHit(lines, 5, pages).it.s, 'Alpha') // the example renders right here, not on page 2
})
test('raw text and escapes stay text inside a call', () => {
  const raw = ['#figure(', '  image("x.png"),', '  body: [`a ) b`],', '  caption: [Bars],', ')']
  assert.equal(ctx.pvCallEnd(raw, 1), 5)
  const esc = ['#figure(', '  box[escaped \\) bracket],', '  caption: [Escaped.],', ')']
  assert.equal(ctx.pvCallEnd(esc, 1), 4)
  const pages = [page(['Figure 1: Bars'])]
  assert.equal(ctx.pvFigureHint(raw, 3, pages).pi, 0)
})
test('a short caption on the figure opener still names its page', () => {
  const lines = ['= Chart', '#pagebreak()', '#figure(image("x.png"), caption: [Bars])']
  const pages = [page(['Chart']), page(['Figure 1: Bars'])]
  assert.equal(ctx.syncNearHit(lines, 3, pages).pi, 1)
})
test('caption text on its own line names the figure page', () => {
  const lines = ['#figure(', '  box[rect()],', '  caption: [', '    Bars chart.', '  ],', ')']
  const pages = [page(['Figure 1: Bars chart.'])]
  assert.equal(ctx.pvFigureHint(lines, 2, pages).pi, 0)
})
test('the outermost open figure owns a nested table', () => {
  const lines = ['#figure(', '  table(', '    [A], [B],', '    caption: [Inner table.],', '  ),', '  caption: [Outer figure.],', ')']
  assert.equal(ctx.pvFigureStart(lines, 3), 1)
  assert.equal(ctx.pvCallEnd(lines, 1), 7)
})
test('comparisons survive label stripping while real labels disappear', () => {
  assert.equal(ctx.syncPlain('if a < b and c > d then'), 'if a b and c d then')
  assert.equal(ctx.syncPlain('$a < b > c$'), 'a b c')
  assert.equal(ctx.syncPlain('see <fig:chart> and <tab:x>'), 'see and')
})
test('source headings skip raw blocks, comments and inline markup', () => {
  const c = outlineCtx({})
  const t = ['= #link("x")[Quelle]', '', '```typst', '= Fake', '```', '', '/* = Also fake */', '= **Bold** real'].join('\n')
  assert.deepEqual(Array.from(c.srcHeadings(t), h => h.title), ['#link("x")[Quelle]', '**Bold** real'])
  assert.equal(c.syncShow('**Bold** real'), 'Bold real')
})
test('outline matching tolerates template numbering and inline markup', () => {
  const c = outlineCtx({ pvOutline: [{ title: '1.2 Einleitung', page: 0 }, { title: 'A. Anhang', page: 1 }, { title: 'A Brief History', page: 2 }] })
  assert.equal(c.pvOlMatch('Einleitung', 0), 0)
  assert.equal(c.pvOlMatch('Anhang', 1), 1)
  assert.equal(c.pvOlMatch('A Brief History', 2), 2)
  assert.equal(c.pvOlMatch('#link("x")[Quelle]', 0), -1)
  c.pvOutlineGen = 0 // outline of an older render: no pages it could honestly give
  assert.equal(c.pvOlMatch('Einleitung', 0), -1)
})
test('section interpolation reaches the next heading at the last page', () => {
  const c = vm.createContext({})
  vm.runInContext(code.slice(code.indexOf('function pvPageHint'), code.indexOf('function pvCanvasList')), c)
  assert.equal(c.pvPageHint(1, 21, 3, { sec: { line: 1, page: 0 }, next: { line: 21, page: 2 } }, 1), 20) // last line before the next heading
  assert.equal(c.pvPageHint(0, 11, 2, { sec: { line: 1, page: 0 }, next: { line: 11, page: 1 } }, 1), 10)
})
test('word offsets follow NFKC-normalized math glyphs', () => {
  const words = ctx.syncWords('$𝐸 = mc^2$ text here')
  assert.equal(words.find(w => w.w === 'e').at, 1) // the math variable, not the e in "text"
})
test('a line-break hyphen still finds its source word', () => {
  const t = 'Hyphenation is long.'
  assert.equal(ctx.syncNeedleAt(t, 'Hyphen-', 1, 0), 0)
})
test('multi-line set/show commands are commands, not text anchors', () => {
  assert.equal(ctx.pvCmdLine('#set page('), true)
  assert.equal(ctx.pvCmdLine('#set page(margin: 2cm)'), true)
  assert.equal(ctx.pvCmdLine('#let x = 1'), true)
  assert.equal(ctx.pvCmdLine('#show heading.where(level: 1): it => [Hi]'), false)
  assert.equal(ctx.pvCmdLine('normal prose'), false)
})
test('a figure without a caption never borrows the next caption', () => {
  const lines = ['= Chart', '#figure(', '  box[rect()],', ')', '', '#figure(', '  box[circle()],', '  caption: [Next figure.],', ')']
  const pages = [page(['Chart']), page(['Figure 1: Next figure.'])]
  assert.equal(ctx.syncNearHit(lines, 2, pages).pi, 0) // its own frame has no text: the heading above wins
})
test('a figure command anchors to its own caption before its table cells', () => {
  const lines = ['#figure(', '  table(', '    [Name], [Value],', '  ),', '  caption: [Fundamental constants.],', ')']
  const pages = [page(['Name', 'Value']), page(['Table 1: Fundamental constants.'])]
  assert.equal(ctx.syncNearHit(lines, 1, pages).pi, 1)
})
test('inline commands with one nested bracket level keep their visible text', () => {
  assert.equal(ctx.syncPlain('#grid(columns: (1fr, 1fr))[hidden]'), 'hidden')
  assert.equal(ctx.syncPlain('#link("a b")[Label]'), 'label')
})
test('prefiltered completion results are recomputed after typing', () => {
  const src = read('20-completions.js')
  const start = src.indexOf('const T_KW')
  const end = src.indexOf('function typstHover')
  const c = vm.createContext({ window: {}, snippetCompletion: (_s, c) => c, typstGlobalCompletions: [], typstMathCompletions: [], tplName: '', activeFile: '', tabName: () => 'main.typ' })
  vm.runInContext(src.slice(start, end), c)
  const complete = text => c.typstComplete({ pos: text.length, state: { doc: { sliceString: () => text } } })
  assert.ok(complete('#').options.some(o => o.label === '#set'))
  assert.equal(complete('#').validFor, undefined)
  assert.equal(complete('#ali'), null)
  assert.deepEqual(Array.from(complete('#sho').options, o => o.label), ['#show'])
})

test('project completions requery every prefiltered context', () => {
  const src = read('20-completions.js')
  const files = Array.from({ length: 60 }, (_, i) => ({ name: `module-${i}.typ` }))
  const c = vm.createContext({ window: {}, snippetCompletion: (_s, c) => c,
    typstGlobalCompletions: [{ label: 'alpha' }], typstMathCompletions: [],
    typstBuiltinSignatures: { page: [['paper', 2, ['value:"a3"', 'value:"a4"']]] },
    tplName: '', activeFile: '', tabName: () => 'main.typ', t: k => k,
    projectResources: () => files, mediaNames: [], bibKeys: ['alpha', 'beta'],
    getT: () => '<alpha> <beta>',
    typstParser: { parse: () => ({ resolveInner: () => ({ name: 'Error' }) }) },
  })
  vm.runInContext(src.slice(src.indexOf('const T_KW'), src.indexOf('function typstHover')), c)
  const complete = text => c.typstComplete({ pos: text.length, explicit: true,
    state: { doc: { length: text.length, sliceString: () => text } },
    matchBefore: () => ({ from: 0, text }),
  })
  for (const text of ['#include "', '#ref(<', '#cite("', '#set page(', '#set page(paper: "', '#', '#alp', 'module']) {
    const result = complete(text)
    assert.ok(result?.options.length, text)
    assert.equal(result.filter, false, text)
    assert.equal(result.validFor, undefined, text)
  }
  assert.equal(complete('#include "').options.length, 50)
  assert.deepEqual(Array.from(complete('#include "module-59').options, o => o.label), ['module-59.typ'])
  assert.deepEqual(Array.from(complete('#ref(<alp').options, o => o.label), ['<alpha>'])
  assert.deepEqual(Array.from(complete('#cite("bet').options, o => o.label), ['beta'])
})

test('image view renders a typed blob, ignores stale loads and releases its URL', async () => {
  const elements = { editWrap: { appendChild: node => { elements.imageFile = node } }, cmWrap: { hidden: false } }
  const urls = [], revoked = [], requests = []
  const c = vm.createContext({ window: {}, docId: 'd', activeFile: 'plot.svg', tplName: '',
    $: id => elements[id], el: tag => ({ tag, dataset: {}, replaceChildren(...nodes) { this.children = nodes } }),
    fetch: url => new Promise(resolve => requests.push({ url, resolve })), Blob,
    URL: { createObjectURL: blob => { urls.push(blob); return 'blob:' + urls.length }, revokeObjectURL: url => revoked.push(url) } })
  vm.runInContext(read('features/image-file.js'), c)
  const pending = c.paintImageFile('plot.svg')
  requests[0].resolve({ ok: true, arrayBuffer: async () => new ArrayBuffer(1) })
  await pending
  assert.equal(urls[0].type, 'image/svg+xml')
  assert.equal(elements.imageFile.children[0].src, 'blob:1')
  const stale = c.paintImageFile('other.png')
  c.activeFile = ''; await c.paintImageFile('main.typ')
  requests[1].resolve({ ok: true, arrayBuffer: async () => new ArrayBuffer(2) })
  await stale
  assert.equal(urls.length, 1)
  assert.deepEqual(revoked, ['blob:1'])
  assert.equal(elements.imageFile.hidden, true)
})

test('confirmation dialog clicks do not close the history popover', () => {
  const src = read('88-share-offline.js')
  const handler = src.slice(src.indexOf("document.addEventListener('click'"), src.indexOf("document.addEventListener('click'" ) + 120)
  assert.ok(handler.includes("if (e.target.closest('#modal')) return"))
})

test('word mapping follows reflowed lines and inline markup', () => {
  const t = '= Titel\n\nEine Zeile mit #emph[hervorgehobenem] Text\nund noch etwas danach'
  assert.equal(ctx.syncNeedleAt(t, 'Eine Zeile mit hervorgehobenem Text und noch etwas danach', 3, 0), t.indexOf('Eine'))
  assert.equal(ctx.syncNeedleAt(t, 'Eine Zeile mit hervorgehobenem Text und noch etwas danach', 3, 5), t.indexOf('und'))
})
test('a cursor hint finds a late repeated word past fifty earlier hits', () => {
  const c = vm.createContext({ posOfLine: (t, ln) => { let p = 0; for (let i = 1; i < ln; i++) p = t.indexOf('\n', p) + 1; return p } })
  vm.runInContext(code.slice(code.indexOf('function pvWordChar'), code.indexOf('function cmTop')), c)
  const t = Array.from({ length: 80 }, (_, i) => `word line ${i}`).join('\n')
  const at = c.locateNear(t, 'word', 75)
  assert.equal(t.slice(0, at).split('\n').length, 75)
})
test('math italic glyphs normalize to the letters in the source', () => {
  assert.equal(ctx.syncText('𝐸'), 'e')
  const t = 'Inline math: $E = m c^2$.'
  assert.equal(ctx.syncNeedleAt(t, 'Inline math: 𝐸 = 𝑚 𝑐 2 .', 1, 0), t.indexOf('Inline'))
})
test('a short label run never jumps past the matched caption', () => {
  const t = '= Chart\n\n#figure(\n  box[rect()],\n  caption: [Simple bar diagram.],\n)\n\n= Conclusion\nText.'
  assert.equal(ctx.syncNeedleAt(t, 'Simple bar diagram. A B C D', 6, 4), -1) // clicked "A" is outside the caption run
  assert.equal(ctx.syncNeedleAt(t, 'Simple bar diagram.', 6, 0), t.indexOf('Simple'))
})
test('click column maps to the nearest letter boundary', () => {
  const c = vm.createContext({})
  vm.runInContext(code.slice(code.indexOf('function pvCharW'), code.indexOf("$('preview').addEventListener('click'")), c)
  const item = { s: 'Die erste Methode sammelt', x0: 0, w: 100, vw: 100 }
  assert.equal(c.pvClickCol(item, 5, 100, 100), 1) // inside "Die": behind the D
  assert.equal(c.pvClickCol(item, 50, 100, 100), 13) // inside "Methode": behind "Met"
  assert.equal(c.pvClickCol(item, 34, 100, 100), 9) // just past "erste": the word end, not 0
  assert.equal(c.pvClickCol(item, 36, 100, 100), 10) // just inside "Methode": its start
  assert.equal(c.pvClickCol(item, 68, 100, 100), 18) // space after "Methode": the next word, not the line start
  assert.equal(c.pvClickCol(item, 120, 100, 100), 25) // past the line end: the last word end
})
test('click column follows the rendered pixels of a justified line', () => {
  const c = vm.createContext({})
  vm.runInContext(code.slice(code.indexOf('function pvCharW'), code.indexOf("$('preview').addEventListener('click'")), c)
  const img = { width: 100, height: 10, data: new Uint8ClampedArray(100 * 10 * 4) }
  for (const [a, b] of [[2, 10], [60, 68], [90, 98]]) for (let x = a; x <= b; x++) for (let y = 0; y < 10; y++) {
    const i = (y * 100 + x) * 4
    img.data[i] = img.data[i + 1] = img.data[i + 2] = 0
    img.data[i + 3] = 255
  }
  const cv = { width: 100, height: 100, getContext: () => ({ getImageData: () => img }) }
  const item = { s: 'aa bb cc', x0: 0, w: 100, vw: 100, y: 0, h: 10, vh: 100 }
  assert.equal(c.pvClickCol(item, 4, 100, 100, cv), 1) // inside "aa": behind the first a
  assert.equal(c.pvClickCol(item, 12, 100, 100, cv), 2) // just past "aa": still "aa", its end
  assert.equal(c.pvClickCol(item, 64, 100, 100, cv), 4) // stretched space: pixels say "bb", the char guess says "cc"
  assert.equal(c.pvClickCol(item, 70, 100, 100, cv), 5) // space after "bb" closer to "bb": its end
  assert.equal(c.pvClickCol(item, 85, 100, 100, cv), 6) // wide space closer to "cc": its start
})
test('click column maps scaled canvas pixels through the item offset', () => {
  const c = vm.createContext({})
  vm.runInContext(code.slice(code.indexOf('function pvCharW'), code.indexOf("$('preview').addEventListener('click'")), c)
  const img = { width: 180, height: 10, data: new Uint8ClampedArray(180 * 10 * 4) }
  for (const [a, b] of [[0, 10], [22, 30], [34, 40], [60, 80]]) for (let x = a; x <= b; x++) for (let y = 0; y < 10; y++) {
    const i = (y * 180 + x) * 4
    img.data[i + 3] = 255
  }
  const cv = { width: 200, height: 20, getContext: () => ({ getImageData: () => img }) }
  const item = { s: 'aa bb cc', x0: 10, w: 180, vw: 200, y: 10, h: 10, vh: 20 }
  // cssW 100 for a 200 px backing: clicks arrive in CSS px, boxes in canvas px
  assert.equal(c.pvClickCol(item, 6, 100, 200, cv), 0) // "aa" at canvas 10-20, behind the first a is a tie
  assert.equal(c.pvClickCol(item, 20, 100, 200, cv), 4) // inside "bb", inner gap of "bb" merged: 32-50
  assert.equal(c.pvClickCol(item, 30, 100, 200, cv), 5) // gap tie stays left: the end of "bb"
  assert.equal(c.pvClickCol(item, 44, 100, 200, cv), 8) // inside "cc" at canvas 70-90: its end
  const blind = { width: 180, height: 10, data: new Uint8ClampedArray(180 * 10 * 4) }
  for (let x = 0; x < 180; x++) for (let y = 0; y < 10; y++) blind.data[(y * 180 + x) * 4 + 3] = x < 80 ? 255 : 0 // one run: no word boxes
  const gone = { width: 200, height: 20, getContext: () => ({ getImageData: () => blind }) }
  assert.equal(c.pvClickCol(item, 95, 100, 200, gone), 8) // estimate still lands on the last word end
})
test('rotated text runs stay out of clicks but keep their anchors', () => {
  const c = vm.createContext({})
  vm.runInContext(pvCode.slice(pvCode.indexOf('function pvBoxes'), pvCode.indexOf('const PV_LINK_SCHEME')), c)
  vm.runInContext(code.slice(code.indexOf('function pvItemDist'), code.indexOf('function pvOlEq')), c)
  const v = { transform: [1, 0, 0, 1, 0, 0], width: 600, height: 800 }
  const tc = { items: [
    { str: 'Normal', transform: [1, 0, 0, 1, 20, 30], width: 50, height: 10 },
    { str: 'Seitwärts', transform: [0, 1, -1, 0, 100, 200], width: 40, height: 10 },
    { str: 'Schräg', transform: [1, 0.005, -0.005, 1, 50, 60], width: 30, height: 10 },
    { str: 'Gedreht', transform: [0, 1, -1, 0, 20, 37], width: 30, height: 10 }, // same edge as "Normal", one line below
  ] }
  const boxes = c.pvBoxes(tc, v)
  assert.deepEqual(Array.from(boxes, b => b.s), ['Normal', 'Seitwärts', 'Schräg', 'Gedreht']) // anchors still name the rotated word
  assert.equal(boxes[0].rot, false)
  assert.equal(boxes[1].rot, true)
  assert.equal(boxes[2].rot, false) // a tiny skew still gets an honest horizontal box
  assert.equal(boxes[3].rot, true)
  assert.equal(boxes[0].x0, 20)
  assert.equal(boxes[0].w, 50)
  assert.equal(boxes[0].h, 10)
  assert.equal(boxes[0].x, 45)
  assert.equal(boxes[0].y, 25)
  assert.equal(boxes[3].x0, boxes[0].x0) // the fixture really shares the paragraph edge
  assert.equal(boxes[3].y, 32) // and sits within one normal line step below it
  vm.runInContext(code.slice(code.indexOf('function pvBlockLines'), code.indexOf('function pvBlockNeedle')), c)
  assert.deepEqual(Array.from(c.pvBlockLines(boxes, boxes[0]), b => b.s), ['Normal']) // a turned run never joins the paragraph needle
  const near = c.pvNearItems(boxes, -80, 300, 1, 1, null) // right on "Seitwärts": its box is a lie, the neighbours are not
  assert.equal(near.length, 2)
  assert.ok(near.every(({ it }) => !it.rot))
})
test('caption prefixes and table rows become needles the source can match', () => {
  const c = vm.createContext({})
  vm.runInContext(code.slice(code.indexOf('function pvCaptionCut'), code.indexOf('function syncToPv')), c)
  const item = (s, y, x0) => ({ s, y, x0, w: s.length * 5, vw: 100 })
  const cell = item('mg', 10, 80)
  const cells = [item('Alpha', 10, 0), item('12.4', 10, 40), cell]
  const row = c.pvClickNeedles(cells, cell, 0)
  assert.deepEqual(Array.from(row, n => n.s), ['Alpha 12.4 mg']) // short cells need the line context
  assert.equal(row[0].off, 11) // clicked cell "mg" starts after "Alpha 12.4 "
  const turned = { ...item('Gedreht', 10, 60), rot: true }
  assert.deepEqual(Array.from(c.pvClickNeedles([...cells, turned], cell, 0), n => n.s), ['Alpha 12.4 mg']) // a turned run never joins the row
  const capIt = item('Table 1: Fundamental constants.', 10, 0)
  const cap = c.pvClickNeedles([capIt], capIt, 9)
  assert.equal(cap[0].s, 'Fundamental constants.')
  assert.equal(cap[0].off, 0) // column follows the visible caption, not the generated prefix
  const label = item('A', 20, 0)
  assert.deepEqual(Array.from(c.pvClickNeedles([label, item('B', 20, 20)], label, 0)), []) // a lone letter has no usable needle
})
test('a wrapped paragraph gives the click its whole block as needle', () => {
  const c = vm.createContext({})
  vm.runInContext(code.slice(code.indexOf('function pvCaptionCut'), code.indexOf('function syncToPv')), c)
  const item = (s, y) => ({ s, x0: 10, w: s.length * 8, y, h: 10, vw: 100 })
  const lines = [item('aa bb cc', 100), item('dd ee ff', 112), item('gg hh', 124)]
  const nd = c.pvClickNeedles(lines, lines[2], 3) // click on "hh" of the last line
  assert.equal(nd[0].s, 'aa bb cc dd ee ff gg hh') // the paragraph repeats: the block is unique
  assert.equal(nd[0].off, 21) // prefix "aa bb cc dd ee ff " + column 3
  assert.equal(nd[1].s, 'gg hh') // the single line stays as fallback
  assert.equal(nd[1].off, 3)
  const tight = item('kk ll', 142) // 1.8*h below: generous leading is still one paragraph
  assert.equal(c.pvClickNeedles([...lines, tight], tight, 0)[0].s, 'aa bb cc dd ee ff gg hh kk ll')
  const far = item('mm nn', 143) // 1.9*h below the last line: a new paragraph
  assert.equal(c.pvClickNeedles([...lines, far], far, 3)[0].s, 'mm nn')
})
test('line-break hyphens keep both the compound and the rejoined word', () => {
  const c = vm.createContext({})
  vm.runInContext(code.slice(code.indexOf('function pvCaptionCut'), code.indexOf('function syncToPv')), c)
  const item = (s, y) => ({ s, x0: 10, w: s.length * 8, y, h: 10, vw: 100 })
  const hyphen = [item('Silben-', 100), item('trennung im Text', 112)]
  const nd = c.pvClickNeedles(hyphen, hyphen[1], 0)
  assert.deepEqual(Array.from(nd.slice(0, 2), n => [n.s, n.off]), [
    ['Silben-trennung im Text', 7], // real compound: the hyphen stays in the needle
    ['Silbentrennung im Text', 6], // automatic hyphenation: the source word is rejoined
  ])
  const compound = [item('E-', 100), item('Mail im Alltag', 112)]
  const nc = c.pvClickNeedles(compound, compound[1], 0)
  assert.deepEqual(Array.from(nc.slice(0, 2), n => [n.s, n.off]), [
    ['E-Mail im Alltag', 2], // the kept hyphen is part of the offset
    ['EMail im Alltag', 1], // stripped variant keeps its own offset
  ])
  const cap = [item('Table 1: aa', 100), item('bb cc', 112)]
  const ndc = c.pvClickNeedles(cap, cap[1], 0)
  assert.equal(ndc[0].s, 'aa bb cc') // generated prefix is not part of the source caption
  assert.equal(ndc[0].off, 3)
})
test('heading anchors pick the big heading item, not the same word in the body', () => {
  const pages = [[{ s: 'Diskussion', y: 100, h: 30 }, { s: 'Die Diskussion verbindet Methoden', y: 200, h: 22 }]]
  assert.equal(ctx.syncAnchor(['= Diskussion'], 1, pages).it.s, 'Diskussion')
})
test('preview heading clicks resolve the matching source section on the same page', async () => {
  const lines = ['== First section', '=== D: Beobachtung', '== Second section', '=== D: Beobachtung']
  const pages = [page(['First section', 'D: Beobachtung', 'Second section', 'D: Beobachtung'])]
  const jumps = []
  const c = vm.createContext({ activeFile: '', getT: () => lines.join('\n'), pvTexts: pages, jumpPos: pos => jumps.push(pos), syncPage: 0, pvSecAtLine: () => null })
  vm.runInContext(code.slice(code.indexOf('function pvPosIn'), code.indexOf('function syncToPv')), c)
  assert.equal(await c.pvJumpBest([{ s: 'D: Beobachtung', off: 0 }], 1, 0, pages[0][3]), true)
  const start = lines.slice(0, 3).join('\n').length + 1
  assert.deepEqual(jumps, [start + lines[3].indexOf('D:')]) // lands on the heading text, not the "===" markers
})
test('a wrapped paragraph in an included file is found across source line breaks', async () => {
  const main = '= Main\n\n#include "inc.typ"\n'
  const inc = '= Inc\n\nAlpha beta gamma\ndelta epsilon zeta\n'
  const c = vm.createContext({
    activeFile: 'main.typ', docId: 'd', openN: 1, syncPage: 0, jumps: [],
    getT: () => (c.activeFile === 'inc.typ' ? inc : main),
    pvSrcList: () => [{ key: 'inc.typ', text: inc }],
    switchTab: async key => { c.activeFile = key; return true },
    cm: { state: { doc: { lines: 3 } } },
    posOfLine: (t, ln) => { let p = 0; for (let i = 1; i < ln; i++) p = t.indexOf('\n', p) + 1; return p },
    jumpPos: pos => c.jumps.push(pos),
    get pvTexts() { return [page(['Alpha beta gamma delta epsilon zeta'])] },
  })
  vm.runInContext(code.slice(code.indexOf('function pvWordChar'), code.indexOf('function cmTop')), c)
  vm.runInContext(code.slice(code.indexOf('function pvPosIn'), code.indexOf('function syncToPv')), c)
  const needle = { s: 'Alpha beta gamma delta epsilon zeta', off: 0 }
  assert.equal(await c.pvJumpBest([needle], 1, 0, null), true)
  assert.equal(c.activeFile, 'inc.typ')
  assert.deepEqual(c.jumps, [inc.indexOf('Alpha')]) // the PDF line spans two source lines
})
test('a wrapped needle keeps the clicked letter across apostrophes', () => {
  const c = vm.createContext({
    posOfLine: (t, ln) => { let p = 0; for (let i = 1; i < ln; i++) p = t.indexOf('\n', p) + 1; return p },
  })
  vm.runInContext(code.slice(code.indexOf('function pvWordChar'), code.indexOf('function cmTop')), c)
  vm.runInContext(code.slice(code.indexOf('function pvPosIn'), code.indexOf('function syncToPv')), c)
  const src = 'I don’t know\nsecond line'
  const pdf = "I don't know" // smart quote in the source, straight quote in the PDF text
  assert.equal(c.pvPosIn(src, pdf, 2, 1), 2) // start of "don’t"
  assert.equal(c.pvPosIn(src, pdf, 5, 1), 5) // after "don", before the apostrophe
  assert.equal(c.pvPosIn(src, pdf, 6, 1), 6) // the t after the apostrophe, not stuck at the quote
  assert.equal(c.pvPosIn(src, pdf, 7, 1), 7) // its end
  assert.equal(c.pvPosIn(src, pdf, 8, 1), 8) // start of "know"
  const nfd = 'Ba\u0308r und Wein\nsecond line' // decomposed ä: NFD in the source, NFC in the PDF
  assert.equal(c.pvPosIn(nfd, 'Bär und Wein', 1, 1), 1) // behind the B, before the composed ä
  assert.equal(c.pvPosIn(nfd, 'Bär und Wein', 2, 1), 3) // behind the ä (raw a+mark), before the r
  assert.equal(c.pvPosIn(nfd, 'Bär und Wein', 3, 1), 4) // behind the r, before the space
})
test('click column never lands inside a surrogate pair', () => {
  const c = vm.createContext({})
  vm.runInContext(code.slice(code.indexOf('function pvCharW'), code.indexOf("$('preview').addEventListener('click'")), c)
  assert.equal(c.pvClickChar('a😀b', 0.2), 1) // before the emoji
  assert.equal(c.pvClickChar('a😀b', 0.5), 3) // behind the emoji, measured in code units
})
test('a heading-like line inside a raw block never ends the enclosing call', () => {
  const lines = ['= Chart', '#figure(', '  box[```typst', '= Fake heading', '```', '  ]', ')', '', '= Next']
  assert.equal(ctx.pvCallEnd(lines, 2), 7)
})
test('the word caption in prose or a heading is not a caption option', () => {
  const pages = [page(['The caption: Figure 2 is shown here.', 'The caption: Foo', 'Figure 2', 'Foo'])]
  const prose = 'The caption: [Figure 2] is shown here.'
  assert.equal(ctx.syncAnchor([prose], 1, pages).it.s, 'The caption: Figure 2 is shown here.')
  assert.equal(ctx.syncAnchor(['= The caption: [Foo]'], 1, pages).it.s, 'The caption: Foo')
  assert.equal(ctx.syncAnchor(['  caption: [Fundamental constants.],'], 1, [page(['Fundamental constants.'])]).it.s, 'Fundamental constants.')
})
