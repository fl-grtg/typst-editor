const assert = require('node:assert/strict')
const { test } = require('node:test')
const { readFileSync } = require('node:fs')
const vm = require('node:vm')
const projects = readFileSync('web/js/features/projects.js', 'utf8')
const files = readFileSync('web/js/80-files-images.js', 'utf8')
const tabsCode = files.slice(files.indexOf('const OPEN_TABS_KEY'), files.indexOf('const tabErrs'))

function projectCtx(extra = {}) {
  const c = vm.createContext({ docId: 'd', docProject: 'p', openN: 1, activeFile: '', t: (k, v) => k + (v ? JSON.stringify(v) : ''), toast: () => {}, flushTab: async () => true, flushTpl: async () => true,
    sidebar: async () => {}, sidebarFresh: async () => {}, shut: new Set(), saveShut: () => {}, tabRemapEntry: () => {}, tabRemapPrefix: () => {}, tabName: k => k, lastOwn: [], lastShared: [], ...extra })
  vm.runInContext(projects, c)
  return c
}

test('sidebar tree: one tree of documents and files, implied and empty folders, two levels, deeper legacy paths folded', () => {
  const c = projectCtx()
  const p = { id: 'p', folders: ['empty/inner'] }
  const entries = {
    documents: [{ id: 'd', title: 'Main', folder: '' }, { id: 'e', title: 'Ch1', folder: 'chapters' }],
    files: [{ path: 'lib/style.typ' }, { path: 'top.typ' }, { path: 'a/b/deep.typ' }, { path: 'a/b/c/legacy.typ' }, { path: 'img/raw/x.png' }, { path: 'chapters/part.typ' }],
  }
  const tree = c.projectTree(p, entries)
  assert.deepEqual(Array.from(tree.folders('')), ['a', 'chapters', 'empty', 'img', 'lib'])
  assert.deepEqual(Array.from(tree.folders('empty')), ['empty/inner'])
  assert.deepEqual(Array.from(tree.folders('img')), ['img/raw'])
  assert.deepEqual(Array.from(tree.items('')).map(i => i.label), ['Main', 'top.typ'])
  assert.deepEqual(Array.from(tree.items('chapters')).map(i => [i.kind, i.label]), [['document', 'Ch1'], ['file', 'part.typ']])
  assert.equal(tree.dirOf({ kind: 'file', name: 'img/raw/x.png' }), 'img/raw')
  assert.deepEqual(Array.from(tree.items('lib')).map(i => i.label), ['style.typ'])
  assert.deepEqual(Array.from(tree.folders('a')), ['a/b'])
  // older three-level paths stay readable but are shown in the second level
  assert.deepEqual(Array.from(tree.items('a/b')).map(i => i.label), ['deep.typ', 'c/legacy.typ'])
  assert.deepEqual(Array.from(tree.folders('a/b')), [])
})

test('moving into a folder renames the path; documents use the folder endpoint', async () => {
  const calls = []
  const c = projectCtx({ api: async (method, url, body) => {
    if (url.endsWith('-preview')) return { changes: [] } // nothing quotes the document: no dialog
    calls.push([method, url, body]); return { name: 'lib/x.typ', version: 'v' }
  } })
  const p = { id: 'p', documents: [{ id: 'd', folder: '', title: 'Doc' }] }
  c.projectEntries = () => ({ documents: p.documents })
  c.applyEntryRename = async (...args) => calls.push(['rename', ...args])
  await c.moveEntryToFolder(p, { kind: 'file', name: 'x.typ' }, 'lib')
  await c.moveEntryToFolder(p, { kind: 'file', name: 'lib/x.typ' }, 'lib') // already there: nothing
  await c.moveEntryToFolder(p, { kind: 'file', name: 'a/pic.png' }, '')
  await c.moveEntryToFolder(p, { kind: 'document', doc_id: 'd' }, 'chapters')
  assert.deepEqual(calls[0].slice(0, 3), ['rename', p, 'x.typ'])
  assert.equal(calls[0][3], 'lib/x.typ')
  assert.equal(calls[0][4], true) // a drag is a move: the dialog says move
  assert.equal(calls[1][3], 'pic.png')
  assert.equal(JSON.stringify(calls[2]), JSON.stringify(['POST', '/api/projects/p/docs/d/folder', { folder: 'chapters', fix_refs: true }]))
  assert.equal(calls.length, 3)
})

test('folders drag as one entry and move into the first level with the rename endpoint', async () => {
  const calls = [], dragged = []
  let toasted = ''
  const fresh = { id: 'p', folders: ['a', 'a/b'], documents: [], files: [] }
  const c = projectCtx({
    sidebarDrag: (row, data, effect) => dragged.push([data, effect]),
    api: async (method, url, body) => { if (url.endsWith('-preview')) return { changes: [] }; calls.push([method, url, body]); return fresh },
    toast: m => { toasted = m },
  })
  c.afterFolderRename = async (...args) => calls.push(['after', ...args])
  c.projectDrag({}, { id: 'p', role: 'owner' }, { kind: 'folder', name: 'src' })
  assert.equal(JSON.stringify(dragged), JSON.stringify([[{ project: 'p', entry: { kind: 'folder', name: 'src' } }, 'copyMove']]))
  await c.folderTransferTo({ id: 'p' }, 'src', { id: 'p' }, 'a', true)
  assert.equal(calls[0][0], 'GET')
  assert.equal(calls[0][1], '/api/projects/p')
  assert.equal(calls[0][2], undefined)
  assert.equal(JSON.stringify(calls[1]), JSON.stringify(['POST', '/api/projects/p/folders/rename', { path: 'src', target: 'a/src', fix_refs: true }]))
  assert.equal(calls[2][0], 'after')
  calls.length = 0
  // a folder in a second-level folder would become three levels deep
  await c.folderTransferTo({ id: 'p' }, 'src', { id: 'p' }, 'a/b', true)
  assert.equal(calls.length, 0)
  assert.match(toasted, /folderDepth/)
})

test('new files and uploads land in the chosen folder', async () => {
  const puts = [], opened = []
  const c = projectCtx({ chooseFileType: async () => '.typ', ask: async () => 'style', fileStart: () => '', uploadName: n => n,
    fileUrl: (path, project) => project + ':' + path, putFile: async (url, body) => { puts.push([url, body]); return { path: url.split(':')[1] } },
    loadProjectFiles: async () => true, queueRender: () => {} })
  c.openProjectEntry = async (p, doc, name) => opened.push([doc, name])
  c.projects = [{ id: 'p', role: 'owner', documents: [{ id: 'd' }] }]
  await c.newProjectResource('p', 'lib/inner')
  await c.newProjectResource('p')
  assert.deepEqual(puts.map(x => x[0]), ['p:lib/inner/style.typ', 'p:style.typ'])
  assert.deepEqual(opened, [['d', 'lib/inner/style.typ'], ['d', 'style.typ']])
  puts.length = 0
  await c.uploadProjectFiles(c.projects[0], [{ name: 'logo.png' }], 'img')
  assert.deepEqual(puts.map(x => x[0]), ['p:img/logo.png']) // binary or text: a project file below the drop folder
})

test('a new folder respects the two-level limit', async () => {
  const calls = []; let toasted
  const c = projectCtx({ ask: async () => 'third', api: async (...a) => { calls.push(a); return {} }, toast: m => { toasted = m } })
  await c.newProjectFolder({ id: 'p' }, 'a/b')
  assert.equal(calls.length, 0)
  assert.match(toasted, /folderDepth/)
  await c.newProjectFolder({ id: 'p' }, 'a')
  assert.equal(calls[0][2].path, 'a/third')
})

test('path dialogs select only the file name, not the folder path', () => {
  const c = projectCtx()
  const value = 'hausaufgaben/layout/messwerte.csv'
  assert.equal(c.nameStemStart(value), 20)
  assert.equal(c.nameStemEnd(value), 29)
  assert.equal(c.nameStemStart('global.typ'), 0)
})

test('copy/move target pickers keep both levels for files and one for folders', async () => {
  let options
  const c = projectCtx({ pickPop: async (head, opts) => { options = opts; return -1 } })
  const p = { id: 'p', folders: ['a', 'a/b'], documents: [], files: [] }
  assert.equal(await c.pickTargetFolder(p, 'copy', '', 0), null)
  assert.deepEqual(Array.from(options, o => o[0]), ['menu.projectRoot', 'a', 'a/b'])
  assert.equal(await c.pickTargetFolder(p, 'move', '', 1), null)
  assert.deepEqual(Array.from(options, o => o[0]), ['menu.projectRoot', 'a'])
})

test('copying a file keeps a second-level target folder', async () => {
  const calls = []
  const p = { id: 'p', documents: [{ id: 'd' }], files: [] }
  const c = projectCtx({ api: async (method, url, body) => { calls.push([method, url, body]); return { name: body.target_name } } })
  await c.transferEntryTo(p, { kind: 'file', name: 'messwerte.csv' }, p, 'hausaufgaben/layout', false, { askName: false, refresh: false })
  assert.equal(calls[0][2].target_name, 'hausaufgaben/layout/messwerte.csv')
})

test('silent cross-project transfers keep folder paths, same-project root drops still flatten', async () => {
  const calls = []
  const p = { id: 'p', documents: [{ id: 'd' }], files: [] }
  const target = { id: 'q', documents: [{ id: 'e' }], files: [] }
  const c = projectCtx({ api: async (method, url, body) => { calls.push([method, url, body]); return { name: body.target_name } },
    loadProjectFiles: async () => {}, queueRender: () => {}, openDoc: async () => {} })
  c.projects = [{ id: 'p', title: 'Source' }, target]
  // A file dropped on another project's row keeps its folder.
  await c.transferProjectEntry(p, { kind: 'file', name: 'a/b/mod.typ' }, true, target, true)
  assert.equal(calls[0][2].target_name, 'a/b/mod.typ')
  assert.equal(calls[0][2].move, true)
  // Ctrl-copy onto the own project root still flattens (existing drag behaviour).
  await c.transferProjectEntry(p, { kind: 'file', name: 'a/b/mod.typ' }, false, p, true)
  assert.equal(calls[1][2].target_name, 'mod.typ')
  // Documents carry their folder separately.
  await c.transferProjectEntry(p, { kind: 'document', doc_id: 'd', name: 'Main', folder: 'a/b' }, true, target, true)
  assert.equal(calls[2][2].target_folder, 'a/b')
})

test('copy and move menu entries follow role and change-session limits', () => {
  const c = projectCtx({ window: {} })
  const actions = [
    { dataset: { menuKey: 'rename', menuLabel: 'rename' }, title: 'rename', disabled: false },
    { dataset: { menuKey: 'trash', menuLabel: 'trash' }, title: 'trash', disabled: false },
  ]
  const labels = (p, entry = { kind: 'file', name: 'm.typ' }) => Array.from(c.entryMenuItems(p, entry, actions), item => item.label)
  assert.deepEqual(labels({ id: 'p', role: 'owner' }), ['rename', 'projects.convertToDocument', 'menu.duplicateShort', 'menu.copyTo', 'menu.moveTo', 'trash'])
  assert.deepEqual(labels({ id: 'p', role: 'reviewer' }), ['rename', 'menu.copyTo', 'trash'])
  c.window.changeSession = {}
  assert.deepEqual(labels({ id: 'p', role: 'owner' }), ['rename', 'trash'])
})

test('conversion offers only document -> .typ file and .typ file -> document', async () => {
  const calls = []
  const c = projectCtx({ window: {}, api: async (method, url, body) => { calls.push([url, body]); return url.endsWith('preview') ? { references: [] } : { path: 'a/Doc.typ' } },
    projects: [], openDoc: async () => {}, closeView: () => {} })
  const p = { id: 'p', role: 'owner', documents: [{ id: 'd', title: 'Doc', folder: 'a' }], files: [] }
  assert.equal(c.convertMenuItem(p, { kind: 'file', name: 'img/logo.png' }), null)
  assert.equal(c.convertMenuItem(p, { kind: 'file', name: 'notes.bib' }), null)
  assert.equal(c.convertMenuItem(p, { kind: 'file', name: 'a/part.typ' }).label, 'projects.convertToDocument')
  const toFile = c.convertMenuItem(p, { kind: 'document', doc_id: 'd', name: 'Doc', folder: 'a' })
  assert.equal(toFile.label, 'projects.convertToFile')
  await toFile.run()
  await c.convertMenuItem(p, { kind: 'file', name: 'a/part.typ' }).run()
  assert.equal(JSON.stringify(calls), JSON.stringify([
    ['/api/projects/p/convert', { doc_id: 'd' }],
    ['/api/projects/p/files-move-preview', { path: 'a/part.typ', target: 'a/part.typ' }],
    ['/api/projects/p/convert', { path: 'a/part.typ' }],
  ]))
})

test('folder menus and actions stay out of change and suggestion sessions', async () => {
  let toasted = '', asked = 0, called = 0
  const c = projectCtx({ window: { changeSession: {} }, toast: m => { toasted = m }, ask: async () => { asked++; return true }, api: async () => { called++; return {} } })
  const p = { id: 'p', role: 'owner', folders: ['a'], documents: [], files: [] }
  const actions = [
    { dataset: { menuKey: 'rename' }, title: 'rename' },
    { dataset: { menuKey: 'trash' }, title: 'trash' },
  ]
  const labels = Array.from(c.folderMenuItems(p, 'a', actions), item => item.label)
  assert.deepEqual(labels, []) // every folder action writes; sessions stage entries only
  await c.deleteFolder(p, 'a')
  await c.renameFolder(p, 'a')
  assert.match(toasted, /sourceBlocked/)
  assert.equal(asked, 0)
  assert.equal(called, 0)
  c.window.changeSession = null
  c.window.suggestionDraft = {}
  assert.deepEqual(Array.from(c.folderMenuItems(p, 'a', actions), item => item.label), [])
  await c.renameFolder(p, 'a')
  assert.equal(asked, 0)
})

test('folder tree preflight catches nested entries that would exceed the depth cap', () => {
  const c = projectCtx()
  const deep = { folders: ['src/inner'], documents: [{ folder: 'src' }], files: [{ path: 'src/lib/x.typ' }, { path: 'src/pic.png' }] }
  assert.equal(c.folderTreeFits(deep, 'src', 'a/src'), false) // src/inner would become three levels
  assert.equal(c.folderTreeFits(deep, 'src', 'a/b/src'), false)
  const leaf = { folders: [], documents: [{ folder: 'src' }], files: [{ path: 'src/x.typ' }, { path: 'src/pic.png' }] }
  assert.equal(c.folderTreeFits(leaf, 'src', 'a/src'), true)
  assert.equal(c.folderTreeFits(leaf, 'src', 'a/b/src'), false)
  assert.equal(c.folderTreeFits({ folders: [], documents: [], files: [] }, 'src', 'a/src'), true)
})

function tabsCtx(extra = {}) {
  const store = {}
  const c = vm.createContext({ docId: 'd', docProject: 'p', activeFile: '', lastFiles: [], localStorage: { getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = v } },
    tabName: k => k, projectEntries: p => p.entries, tabSig: 'x', window: {}, paintTabs: () => {}, ...extra })
  vm.runInContext(tabsCode, c)
  return c
}

test('open tab keys are stable across documents', () => {
  const c = tabsCtx()
  assert.equal(c.tabAbs(''), 'd:d')
  assert.equal(c.tabAbs('@doc/o'), 'd:o')
  assert.equal(c.tabAbs('img/x.png'), 'f:img/x.png')
  for (const k of ['', '@doc/o', 'img/x.png']) assert.equal(c.tabRel(c.tabAbs(k)), k)
  c.docId = 'o'
  assert.equal(c.tabRel('d:o'), '')
  assert.equal(c.tabRel('d:d'), '@doc/d')
  assert.equal(c.tabRel('f:img/x.png'), 'img/x.png') // project files keep their tab whichever document is open
})

test('closing a tab hides it and activates the left neighbour; the last tab closes the view', async () => {
  let closed = 0
  const c = tabsCtx({ projects: [{ id: 'p', entries: { documents: [{ id: 'd' }], files: [{ path: 'a.typ' }, { path: 'b.typ' }] } }],
    flushTab: async () => true, closeView: () => { closed++ } })
  vm.runInContext("openTabs = ['d:d', 'f:a.typ', 'f:b.typ', 'r:old-module.typ']; openTabsScope = 'p'; activeFile = 'b.typ'", c)
  assert.deepEqual(Array.from(c.tabItems()), ['', 'a.typ', 'b.typ']) // stale keys of the old model drop out
  const switched = []
  c.switchTab = async k => { switched.push(k); c.activeFile = k; return true }
  await c.closeTab('b.typ')
  assert.deepEqual(switched, ['a.typ'])
  assert.deepEqual(Array.from(vm.runInContext('openTabs', c)), ['d:d', 'f:a.typ', 'r:old-module.typ'])
  await c.closeTab('')
  assert.deepEqual(Array.from(vm.runInContext('openTabs', c)), ['f:a.typ', 'r:old-module.typ'])
  await c.closeTab('a.typ') // the only one left: back to the empty view
  assert.deepEqual(Array.from(vm.runInContext('openTabs', c)), ['r:old-module.typ'])
  assert.equal(closed, 1)
})

test('renaming a folder keeps its tabs, in memory and in storage', () => {
  const c = tabsCtx()
  vm.runInContext("openTabs = ['d:d', 'f:lib/a.typ', 'f:libx/b.typ', 'f:lib/pic.png']; openTabsScope = 'p'", c)
  c.tabRemapPrefix('p', 'lib', 'parts/lib')
  assert.deepEqual(Array.from(vm.runInContext('openTabs', c)), ['d:d', 'f:parts/lib/a.typ', 'f:libx/b.typ', 'f:parts/lib/pic.png'])
  vm.runInContext("tabRemapEntry('p', 'f:libx/b.typ', 'f:b.typ')", c)
  assert.ok(vm.runInContext('openTabs', c).includes('f:b.typ'))
})
