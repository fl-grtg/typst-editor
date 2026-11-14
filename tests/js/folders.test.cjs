const assert = require('node:assert/strict')
const { test } = require('node:test')
const { readFileSync } = require('node:fs')
const vm = require('node:vm')
const projects = readFileSync('web/js/features/projects.js', 'utf8')
const files = readFileSync('web/js/80-files-images.js', 'utf8')
const tabsCode = files.slice(files.indexOf('const OPEN_TABS_KEY'), files.indexOf('const tabErrs'))

function projectCtx(extra = {}) {
  const c = vm.createContext({ docId: 'd', docProject: 'p', openN: 1, activeFile: '', t: (k, v) => k + (v ? JSON.stringify(v) : ''), toast: () => {}, flushTab: async () => true, flushTpl: async () => true,
    sidebar: async () => {}, sidebarFresh: async () => {}, shut: new Set(), saveShut: () => {}, tabRemapEntry: () => {}, tabRemapPrefix: () => {}, TPLK: '@tpl/', isTplKey: k => k.startsWith('@tpl/'), tabName: k => k.slice(5), lastOwn: [], lastShared: [], ...extra })
  vm.runInContext(projects, c)
  return c
}

test('sidebar tree: implied and empty folders, two levels, entries grouped by folder', () => {
  const c = projectCtx()
  const p = { id: 'p', folders: ['empty/inner'] }
  const entries = {
    documents: [{ id: 'd', title: 'Main', folder: '' }, { id: 'e', title: 'Ch1', folder: 'chapters' }],
    resources: [{ name: 'lib/style.typ' }, { name: 'top.typ' }, { name: 'a/b/c/deep.typ' }],
    files: [{ doc_id: 'd', name: 'img/raw/x.png' }],
  }
  const tree = c.projectTree(p, entries)
  assert.deepEqual(Array.from(tree.folders('')), ['a', 'chapters', 'empty', 'img', 'lib'])
  assert.deepEqual(Array.from(tree.folders('empty')), ['empty/inner'])
  assert.deepEqual(Array.from(tree.folders('img')), ['img/raw'])
  assert.deepEqual(Array.from(tree.items('')).map(i => i.label), ['Main', 'top.typ'])
  assert.deepEqual(Array.from(tree.items('lib')).map(i => i.label), ['style.typ'])
  // a legacy path deeper than two levels folds into the last level instead of adding a third
  assert.deepEqual(Array.from(tree.items('a/b')).map(i => i.label), ['c/deep.typ'])
  assert.deepEqual(Array.from(tree.folders('a/b')), [])
})

test('moving into a folder renames the path; documents use the folder endpoint', async () => {
  const calls = []
  const c = projectCtx({ api: async (method, url, body) => { calls.push([method, url, body]); return { name: 'lib/x.typ', version: 'v' } } })
  const p = { id: 'p', documents: [{ id: 'd', folder: '' }] }
  c.projectEntries = () => ({ documents: p.documents })
  c.applyEntryRename = async (...args) => calls.push(['rename', ...args])
  await c.moveEntryToFolder(p, { kind: 'resource', doc_id: 'd', name: 'x.typ' }, 'lib')
  await c.moveEntryToFolder(p, { kind: 'resource', doc_id: 'd', name: 'lib/x.typ' }, 'lib') // already there: nothing
  await c.moveEntryToFolder(p, { kind: 'file', doc_id: 'd', name: 'a/pic.png' }, '')
  await c.moveEntryToFolder(p, { kind: 'document', doc_id: 'd' }, 'chapters')
  assert.deepEqual(calls[0].slice(0, 5), ['rename', p, 'x.typ', 'd', true])
  assert.equal(calls[0][5], 'lib/x.typ')
  assert.equal(calls[0][6], false) // drag = move silently, no reference dialog
  assert.equal(calls[1][5], 'pic.png')
  assert.equal(JSON.stringify(calls[2]), JSON.stringify(['POST', '/api/projects/p/docs/d/folder', { folder: 'chapters' }]))
  assert.equal(calls.length, 3)
})

test('new module and upload land in the chosen folder', async () => {
  const calls = []
  const c = projectCtx({ chooseFileType: async () => '.typ', ask: async () => 'style', fileStart: () => '', api: async (method, url, body) => { calls.push([method, url, body]); return { name: body?.name || 'x' } } })
  c.openProjectEntry = async () => {}
  c.projects = [{ id: 'p', documents: [{ id: 'd' }] }]
  await c.newProjectResource('p', 'lib/inner')
  assert.equal(calls[0][2].name, 'lib/inner/style.typ')
  await c.newProjectResource('p')
  assert.equal(calls[1][2].name, 'style.typ')
})

test('a new folder respects the depth limit', async () => {
  const calls = []; let toasted
  const c = projectCtx({ ask: async () => 'third', api: async (...a) => { calls.push(a); return {} }, toast: m => { toasted = m } })
  await c.newProjectFolder({ id: 'p' }, 'a/b')
  assert.equal(calls.length, 0)
  assert.match(toasted, /folderDepth/)
  await c.newProjectFolder({ id: 'p' }, 'a')
  assert.equal(calls[0][2].path, 'a/third')
})

function tabsCtx(extra = {}) {
  const store = {}
  const c = vm.createContext({ docId: 'd', docProject: 'p', activeFile: '', lastFiles: [], localStorage: { getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = v } },
    TPLK: '@tpl/', isTplKey: k => k.startsWith('@tpl/'), tabName: k => k.slice(5), effTpl: () => [], projectEntries: p => p.entries, tabSig: 'x', window: {}, paintTabs: () => {}, ...extra })
  vm.runInContext(tabsCode, c)
  return c
}

test('open tab keys are stable across documents', () => {
  const c = tabsCtx()
  assert.equal(c.tabAbs(''), 'd:d')
  assert.equal(c.tabAbs('@doc/o'), 'd:o')
  assert.equal(c.tabAbs('img/x.png'), 'f:d/img/x.png')
  assert.equal(c.tabAbs('@file/o/img/x.png'), 'f:o/img/x.png')
  assert.equal(c.tabAbs('@tpl/lib/m.typ'), 'r:lib/m.typ')
  for (const k of ['', '@doc/o', 'img/x.png', '@file/o/img/x.png', '@tpl/lib/m.typ']) assert.equal(c.tabRel(c.tabAbs(k)), k)
  c.docId = 'o'
  assert.equal(c.tabRel('d:o'), '')
  assert.equal(c.tabRel('d:d'), '@doc/d')
  assert.equal(c.tabRel('f:o/img/x.png'), 'img/x.png')
})

test('closing a tab hides it and activates the left neighbour; the last tab closes the view', async () => {
  let closed = 0
  const c = tabsCtx({ projects: [{ id: 'p', entries: { documents: [{ id: 'd' }], resources: [{ name: 'a.typ' }, { name: 'b.typ' }], files: [] } }],
    flushTab: async () => true, closeView: () => { closed++ } })
  vm.runInContext("openTabs = ['d:d', 'r:a.typ', 'r:b.typ']; openTabsScope = 'p'; activeFile = '@tpl/b.typ'", c)
  const switched = []
  c.switchTab = async k => { switched.push(k); c.activeFile = k; return true }
  await c.closeTab('@tpl/b.typ')
  assert.deepEqual(switched, ['@tpl/a.typ'])
  assert.deepEqual(Array.from(vm.runInContext('openTabs', c)), ['d:d', 'r:a.typ'])
  await c.closeTab('')
  assert.deepEqual(Array.from(vm.runInContext('openTabs', c)), ['r:a.typ'])
  await c.closeTab('@tpl/a.typ') // the only one left: back to the empty view
  assert.deepEqual(Array.from(vm.runInContext('openTabs', c)), [])
  assert.equal(closed, 1)
})

test('renaming a folder keeps its tabs, in memory and in storage', () => {
  const c = tabsCtx()
  vm.runInContext("openTabs = ['d:d', 'r:lib/a.typ', 'r:libx/b.typ', 'f:d/lib/pic.png', 'f:o/lib/other.png']; openTabsScope = 'p'", c)
  c.tabRemapPrefix('p', 'lib', 'parts/lib')
  assert.deepEqual(Array.from(vm.runInContext('openTabs', c)), ['d:d', 'r:parts/lib/a.typ', 'r:libx/b.typ', 'f:d/parts/lib/pic.png', 'f:o/parts/lib/other.png'])
  vm.runInContext("tabRemapEntry('p', 'r:libx/b.typ', 'r:b.typ')", c)
  assert.ok(vm.runInContext('openTabs', c).includes('r:b.typ'))
})
