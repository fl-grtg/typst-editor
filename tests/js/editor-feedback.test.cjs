const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const read = name => fs.readFileSync('web/js/' + name, 'utf8')
const code = read('90-settings.js')
const ctx = vm.createContext({})
vm.runInContext(code.slice(code.indexOf('function syncText'), code.indexOf('function syncToPv')), ctx)
const page = texts => texts.map((s, y) => ({ s, y: y * 20, vh: 800 }))

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

test('preview heading clicks resolve the matching source section on the same page', async () => {
  const lines = ['== First section', '=== D: Beobachtung', '== Second section', '=== D: Beobachtung']
  const pages = [page(['First section', 'D: Beobachtung', 'Second section', 'D: Beobachtung'])]
  const jumps = []
  const c = vm.createContext({ activeFile: '', getT: () => lines.join('\n'), pvTexts: pages, jumpPos: pos => jumps.push(pos), syncPage: 0 })
  vm.runInContext(code.slice(code.indexOf('async function pvJumpBest'), code.indexOf('function syncToPv')), c)
  assert.equal(await c.pvJumpBest('D: Beobachtung', 1, 0, pages[0][3]), true)
  assert.deepEqual(jumps, [lines.slice(0, 3).join('\n').length + 1])
})
