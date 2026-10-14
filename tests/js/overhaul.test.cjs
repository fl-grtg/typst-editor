const assert = require('node:assert/strict')
const { test } = require('node:test')
const { readFileSync } = require('node:fs')
const { resolve } = require('node:path')
const vm = require('node:vm')

const root = resolve(__dirname, '../..')
function part(file, start, end) {
  const source = readFileSync(resolve(root, file), 'utf8')
  const a = source.indexOf(start), b = source.indexOf(end, a + start.length)
  assert.ok(a >= 0 && b > a, 'function boundaries must exist in ' + file)
  return source.slice(a, b)
}
function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function context(extra = {}) {
  const elements = new Map()
  const c = vm.createContext({
    docId: 'document-a', docRole: 'owner', activeFile: 'chapter.typ', openN: 1,
    tplName: '', tplDirty: false, tabDirty: true, tabSaveFlight: null,
    tabVersions: new Map(), fileCache: new Map(), text: 'Draft', navigator: { onLine: true },
    tabCanEdit: () => true, isTplKey: k => k.startsWith('tpl/'), tabName: k => k,
    tabReq: (key, text) => ({ url: key, body: { content: text } }),
    toast: () => {}, t: (key, args) => key + (args?.msg || ''), wc: () => '',
    clearTimeout, fileT: null, myTpl: [], localStorage: { removeItem: () => {} },
    fileStashKey: (doc, key) => doc + key, queueFileSave: () => { c.rearmed++ }, rearmed: 0,
    $: id => { if (!elements.has(id)) elements.set(id, { style: {}, textContent: '' }); return elements.get(id) },
    ...extra,
  })
  c.getT = () => c.text
  return c
}
const saveSource = part('web/js/80-files-images.js', 'async function flushTab()', 'function tabLive()')

test('failed attachment save preserves the dirty buffer and blocks leaving it', async () => {
  const c = context({ api: async () => { throw new Error('conflict') } })
  vm.runInContext(saveSource, c)
  assert.equal(await c.flushTab(), false)
  assert.equal(c.tabDirty, true)
  assert.equal(c.text, 'Draft')
  assert.match(c.$('save').textContent, /conflict/)
})

test('typing during a save keeps new text dirty and advances its base version', async () => {
  const pending = deferred()
  const c = context({ api: () => pending.promise })
  vm.runInContext(saveSource, c)
  const saving = c.flushTab()
  c.text = 'Newer draft'
  pending.resolve({ version: 'new-base' })
  assert.equal(await saving, false)
  assert.equal(c.tabVersions.get('chapter.typ'), 'new-base')
  assert.equal(c.tabDirty, true)
  assert.equal(c.text, 'Newer draft')
  assert.equal(c.rearmed, 1)
})

test('simultaneous flushes serialize instead of posting the same base twice', async () => {
  const pending = deferred()
  let calls = 0
  const c = context({ api: () => { calls++; return pending.promise } })
  vm.runInContext(saveSource, c)
  const first = c.flushTab(), second = c.flushTab()
  assert.equal(calls, 1)
  pending.resolve({ version: 'saved' })
  assert.equal(await first, true)
  assert.equal(await second, true)
  assert.equal(calls, 1)
  assert.equal(c.tabDirty, false)
})

test('an old document save cannot clear a new document draft', async () => {
  const pending = deferred()
  const c = context({ api: () => pending.promise })
  vm.runInContext(saveSource, c)
  const saving = c.flushTab()
  c.docId = 'document-b'; c.text = 'Other document'; c.tabDirty = true
  pending.resolve({ version: 'old-version' })
  await saving
  assert.equal(c.tabDirty, true)
  assert.equal(c.text, 'Other document')
  assert.equal(c.tabVersions.size, 0)
})

test('a file read does not change the active buffer before it finishes', async () => {
  const pending = deferred()
  const c = context({ activeFile: '', tabDirty: false, tabSeq: 0,
    lastFiles: [{ name: 'chapter.typ' }], api: () => pending.promise,
    flushTab: async () => true, tabSaveState: () => {}, setT: () => { throw new Error('must not replace dirty text') },
  })
  vm.runInContext(part('web/js/80-files-images.js', 'async function switchTab(', 'function offerFileStash('), c)
  const switching = c.switchTab('chapter.typ')
  await Promise.resolve()
  assert.equal(c.activeFile, '')
  c.text = 'Typed into main while the file loads'; c.tabDirty = true
  pending.resolve({ content: 'File text', version: 'v1' })
  assert.equal(await switching, false)
  assert.equal(c.activeFile, '')
  assert.equal(c.text, 'Typed into main while the file loads')
})

test('a delayed formatter does not format a different document', async () => {
  const pending = deferred()
  let formatted = false
  const c = context({ activeFile: '', fmtEditable: () => true, fmtLoad: () => pending.promise })
  vm.runInContext(part('web/js/features/format.js', 'async function formatDoc(', 'const fmtSaveOn'), c)
  const formatting = c.formatDoc(false)
  c.docId = 'document-b'; c.openN++; c.text = 'New document'
  pending.resolve({ format: () => { formatted = true; return 'WRONG' } })
  assert.equal(await formatting, false)
  assert.equal(formatted, false)
  assert.equal(c.text, 'New document')
})

test('shared resources stay read-only even when the viewer owns a same-named template', () => {
  const c = context({ docRole: 'editor', openedTrashed: false, myTpl: [{ name: 'shared.typ' }] })
  const source = readFileSync(resolve(root, 'web/js/80-files-images.js'), 'utf8')
  const line = source.split('\n').find(s => s.startsWith('const tabCanEdit ='))
  vm.runInContext(line + '\nthis.canEdit = tabCanEdit', c)
  assert.equal(c.canEdit('tpl/shared.typ'), false)
  assert.equal(c.canEdit('attachment.typ'), true)
  c.docRole = 'reviewer'
  assert.equal(c.canEdit('attachment.typ'), false)
})

test('template saves cannot mark input typed during the request as saved', async () => {
  const pending = deferred()
  const c = context({ tplName: 'layout.typ', tplDirty: true, tplVer: 'v1', tplOpenN: 1,
    tplSaving: null, tplT: null, tplCached: () => null, resourceStashKey: n => n,
    queueTplSave: () => { c.rearmed++ }, loadTpl: () => {}, api: () => pending.promise,
  })
  vm.runInContext(part('web/js/60-docs.js', 'async function flushTpl()', 'async function loadTheirs('), c)
  const saving = c.flushTpl()
  c.text = 'New template draft'
  pending.resolve({ version: 'v2' })
  assert.equal(await saving, false)
  assert.equal(c.tplVer, 'v2')
  assert.equal(c.tplDirty, true)
  assert.equal(c.rearmed, 1)
})

test('same-length source edits produce different compiler shadow signatures', () => {
  const c = context()
  vm.runInContext(part('web/js/50-preview.js', 'const PV_HASH_MAX', 'function pvResTpl()') + '\nthis.signature = pvFileSig', c)
  assert.notEqual(c.signature('part.typ', { mtime: 1, bytes: Buffer.from('Body') }),
                  c.signature('part.typ', { mtime: 1, bytes: Buffer.from('#ody') }))
})

test('nested sidebar buttons keep their native keyboard action', () => {
  const c = context()
  vm.runInContext(part('web/js/70-comments-popovers.js', 'function kb(', 'let askRes'), c)
  const row = { hasAttribute: () => true }
  let opened = false, prevented = false
  c.kb(row, () => { opened = true })
  row.onkeydown({ target: {}, key: 'Enter', preventDefault: () => { prevented = true } })
  assert.equal(opened, false)
  assert.equal(prevented, false)
  row.onkeydown({ target: row, key: 'Enter', preventDefault: () => { prevented = true } })
  assert.equal(opened, true)
})

test('nested includes resolve global dependencies while local names win', () => {
  const shelf = [{ name: 'library.typ', content: '#include "base.typ"' },
                 { name: 'base.typ', content: 'Global base' },
                 { name: 'part.typ', content: '#include "unrelated.typ"' },
                 { name: 'unrelated.typ', content: 'Must not be pulled' }]
  const c = context({ activeFile: '', text: '#include "sub/part.typ"', TextDecoder,
    fileCache: new Map([['sub/part.typ', { bytes: Buffer.from('#include "../library.typ"') }]]),
    effTpl: () => shelf,
  })
  vm.runInContext(part('web/js/80-files-images.js', 'function usedTpls()', 'function tabItems()'), c)
  assert.deepEqual(Array.from(c.usedTpls()), ['library.typ', 'base.typ'])
})

test('CSV data is a resource leaf and cannot pull a phantom dependency', () => {
  const c = context({ activeFile: '', text: '#csv("data.csv")', TextDecoder,
    effTpl: () => [{ name: 'data.csv', content: '"hidden.typ",42' }, { name: 'hidden.typ', content: 'Hidden' }],
  })
  vm.runInContext(part('web/js/80-files-images.js', 'function usedTpls()', 'function tabItems()'), c)
  assert.deepEqual(Array.from(c.usedTpls()), ['data.csv'])
})

test('the Typst formatter is unavailable for bibliography and CSV buffers', () => {
  const c = context({ docId: '', tplName: 'sources.bib', activeFile: '',
    cm: { state: { facet: () => true } }, EditorView: { editable: {} },
  })
  const source = readFileSync(resolve(root, 'web/js/features/format.js'), 'utf8')
  vm.runInContext(source.split('\n').find(s => s.startsWith('const fmtEditable =')) + '\nthis.canFormat = fmtEditable', c)
  assert.equal(c.canFormat(), false)
  c.tplName = 'data.csv'; assert.equal(c.canFormat(), false)
  c.tplName = 'layout.typ'; assert.equal(c.canFormat(), true)
})

test('late fallback diagnostics cannot paint a different document', async () => {
  const pending = deferred()
  let painted = false
  const c = context({ activeFile: '', renderN: 1, pvObs: null, window: { pdfjsLib: {} },
    typstReady: () => true, cmpDiags: [], errDiags: () => pending.promise,
    paintErr: () => { painted = true }, shadowAll: async () => { throw new Error('compile unavailable') },
  })
  c.pvStale = (id, doc, tpl) => id !== c.renderN || doc !== c.docId || tpl !== c.tplName
  vm.runInContext(part('web/js/50-preview.js', 'async function renderDirect(', 'let lastErrToast'), c)
  const rendering = c.renderDirect(1, {})
  await Promise.resolve()
  c.docId = 'document-b'
  pending.resolve([{ severity: 'error', message: 'Old error' }])
  await rendering
  assert.equal(painted, false)
  assert.equal(c.cmpDiags.length, 0)
})
