const assert = require('node:assert/strict')
const { test } = require('node:test')
const { readFileSync } = require('node:fs')
const vm = require('node:vm')
const source = readFileSync('web/js/features/projects.js', 'utf8')
function node(tag, cls, text) { // just enough DOM for structured dialog bodies
  return { tag, cls, text: text == null ? '' : String(text), children: [], append(...kids) { this.children.push(...kids) },
    all: function () { return [this.text, ...this.children.map(k => k.all())].filter(Boolean).join(' ') } }
}
function setup(extra = {}) {
  const c = vm.createContext({ el: node, lastOwn: [], lastShared: [], docId: 'd', docProject: 'p', openN: 1, activeFile: '', docResReadonly: false,
    flushTab: async () => true, flushTpl: async () => true, loadTpl: async () => {},
    loadProjectFiles: async () => true, fileUrl: (path, project = 'p') => '/api/projects/' + project + '/files/' + path, docFolder: '',
    refTo: path => path, sidebar: async () => {}, sidebarFresh: async () => {}, t: x => x, toast: () => {}, tabRemapEntry: () => {}, tabRemapPrefix: () => {}, ...extra })
  vm.runInContext(source, c)
  return c
}

test('a new project file opens under the normalized server path', async () => {
  let opened, put
  const c = setup({ chooseFileType: async () => '.typ', ask: async () => 'Änderungen',
    fileStart: () => '', shut: new Set(), saveShut: () => {}, projects: [{ id: 'p', documents: [{ id: 'd' }] }],
    putFile: async url => { put = url; return { path: '_nderungen.typ' } } })
  c.openProjectEntry = async (_p, _doc, name) => { opened = name }
  await c.newProjectResource('p')
  assert.equal(put, '/api/projects/p/files/Änderungen.typ')
  assert.equal(opened, '_nderungen.typ')
})

test('deleting a missing file reports the race without issuing a write', async () => {
  let writes = 0, message
  const c = setup({ ask: async () => true, toast: value => { message = value },
    api: async method => { if (method !== 'GET') writes++; return { files: [] } } })
  await c.deleteProjectEntry({ id: 'p' }, 'gone.typ')
  assert.equal(writes, 0)
  assert.equal(message, 'files.tplGone')
  await c.deleteProjectEntry(undefined, 'gone.typ')
  assert.equal(message, 'projects.contextGone')
})

test('deleting a file trashes the version the list shows', async () => {
  const calls = []
  const c = setup({ ask: async () => true, queueRender: () => {}, api: async (method, url) => { calls.push([method, url]); return { files: [{ path: 'img/a.png', version: 'v7' }] } } })
  await c.deleteProjectEntry({ id: 'p' }, 'img/a.png')
  assert.deepEqual(calls.map(x => x.join(' ')), ['GET /api/projects/p/files', 'DELETE /api/projects/p/files/img/a.png?version=v7'])
})

test('rename confirmation lists references and moves with the preview version, fixing references', async () => {
  const prompts = [], writes = []
  const c = setup({ ask: async (label, opts) => { prompts.push(opts?.body ? opts.body.all() : label); return opts?.noInput ? true : 'new.typ' },
    api: async (_method, url, body) => {
      if (url.endsWith('-preview')) return { path: 'new.typ', version: 'v1', references: ['Doc/main: old.typ'], changes: [{ in: 'Doc/main', old: 'old.typ', new: 'new.typ' }] }
      writes.push([url, body]); return { path: 'new.typ' }
    }, filesDirty: false, tabSig: '', queueRender: () => {} })
  await c.renameProjectEntry({ id: 'p' }, 'old.typ')
  assert.ok(prompts[1].includes('Doc/main') && prompts[1].includes('old.typ') && prompts[1].includes('new.typ'))
  assert.equal(writes[0][0], '/api/projects/p/files-move')
  assert.equal(JSON.stringify(writes[0][1]), JSON.stringify({ path: 'old.typ', target: 'new.typ', version: 'v1', fix_refs: true }))
})

test('late rename completion cannot reset a different document draft', async () => {
  let finish
  const c = setup({ ask: async (_label, opts) => opts?.noInput ? true : 'new.typ',
    api: async (_method, url) => url.endsWith('-preview') ? { path: 'new.typ', version: 'v1', references: [], changes: [] } : new Promise(r => { finish = r }),
    queueRender: () => assert.fail('new document must remain untouched'), switchTab: async () => assert.fail('no switch in another document') })
  const pending = c.renameProjectEntry({ id: 'p' }, 'old.typ')
  while (!finish) await new Promise(r => setImmediate(r))
  c.docId = 'other'; c.openN = 2; c.activeFile = 'old.typ'; c.tabDirty = true
  finish({ path: 'new.typ' }); await pending
  assert.equal(c.activeFile, 'old.typ')
  assert.equal(c.tabDirty, true)
})

test('a renamed open file tab reopens under its new path', async () => {
  const switches = []
  const c = setup({ activeFile: 'old.typ', ask: async (_label, opts) => opts?.noInput ? true : 'new.typ',
    api: async (_method, url) => url.endsWith('-preview') ? { path: 'new.typ', version: 'v1', references: [], changes: [] } : { path: 'new.typ' },
    queueRender: () => {}, switchTab: async name => { switches.push(name); c.activeFile = name; return true } })
  await c.renameProjectEntry({ id: 'p' }, 'old.typ')
  assert.deepEqual(switches, ['', 'new.typ'])
})
test('legacy document fallback and library permissions exclude guests and readers', () => {
  const c = setup({ lastOwn: [{ id: 'd', project_id: 'p' }] })
  assert.equal(c.projectEntries({ id: 'p' }).documents.length, 1)
  for (const role of ['guest', 'reviewer']) assert.equal(c.projectEditable({ role }), false)
  assert.equal(c.projectEditable({ role: 'editor' }), true)
  assert.equal(c.projectEditable({ role: 'editor', can_edit_library: false }), false)
})
test('private module insertion waits for copied snapshot and uses returned name', async () => {
  let finish, inserted
  const c = setup({ ask: async (_label, options) => options?.noInput ? true : 'renamed.typ',
    api: async (_method, url) => url.endsWith('pull-preview') ? { preview: 'token' } : new Promise(r => { finish = r }),
    resLine: x => '#include "' + x.name + '"', addTpl: x => { inserted = x }, refTo: path => '../' + path, docFolder: 'Chapters' })
  const pending = c.insertPersonalResource({ name: 'private.typ' })
  while (!finish) await Promise.resolve()
  assert.equal(inserted, undefined)
  finish({ name: 'copied.typ' }); await pending
  assert.equal(inserted, '#include "../copied.typ"') // the copied file is quoted as the open text reaches it
})
test('personal pull keeps its collection folder or follows the target folder', async () => {
  let body
  const c = setup({ api: async (_m, url, sent) => {
    if (url.endsWith('pull-preview')) return { preview: 'token' }
    body = sent; return { name: sent.name }
  } })
  assert.equal(await c.pullLibrary({ source_scope: 'personal', source: 'module.typ', folder: 'MeineOrdner' }, { scope: 'project', project_id: 'p' }), 'MeineOrdner/module.typ')
  assert.equal(body.name, 'MeineOrdner/module.typ')
  assert.equal(await c.pullLibrary({ source_scope: 'personal', source: 'module.typ', folder: 'MeineOrdner' }, { scope: 'project', project_id: 'p' }, 'Ziel'), 'Ziel/module.typ')
  assert.equal(body.name, 'Ziel/module.typ')
})
test('snapshot collision only offers rename or cancel, never overwrites', async () => {
  const calls = [], answers = [null]
  const c = setup({ ask: async () => answers.shift(), api: async (_method, url, body) => {
    calls.push({ url, body }); return { collisions: ['taken.typ'] }
  } })
  assert.equal(await c.pullLibrary({ source_scope: 'personal', source: 'taken.typ' }, { scope: 'project', project_id: 'p' }), null)
  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, '/api/library/pull-preview')
  assert.equal(calls[0].body.overwrite, undefined)
})
test('copy completion cannot insert into another active file', async () => {
  const c = setup({ resLine: () => '', addTpl: () => assert.fail('wrong file') })
  c.pullLibrary = async () => { c.activeFile = 'other.typ'; return 'a.typ' }
  await c.insertPersonalResource({ name: 'a.typ' })
})
test('project share uses project membership and omits document invites', async () => {
  const share = readFileSync('web/js/88-share-offline.js', 'utf8')
  const load = share.slice(share.indexOf('async function loadShares()'), share.indexOf('function roleSel('))
  const calls = []
  const c = setup({ shareN: 0, renderShares: () => {}, api: async (_m, url) => { calls.push(url); return { role: 'owner', members: [] } } })
  vm.runInContext(load, c); await c.loadShares()
  assert.deepEqual(calls, ['/api/projects/p', '/api/docs/d'])
  c.docProject = ''; await c.loadShares()
  assert.equal(calls[2], '/api/docs/d')
  assert.match(share, /const shareUrl = project \? `\/api\/projects\/\$\{project\}\/members`/)
  assert.ok(share.indexOf('if (project) return') < share.indexOf("t('share.inviteTitle')"))
})
test('project actions use standard icons and never expose drawer membership', () => {
  const paint = source.slice(source.indexOf('function paintProjects'), source.indexOf('async function newProjectDoc'))
  assert.match(paint, /ICO_PLUS/); assert.match(paint, /ICO_EDIT/); assert.match(paint, /ICO_TRASH/); assert.doesNotMatch(paint, /ICO_MORE/); assert.match(paint, /projectMenu\(p, '', add\)/)
  assert.doesNotMatch(paint, /projectMembers|projects\.members/)
  assert.match(source, /b\.title = label; b\.setAttribute\('aria-label', label\)/)
})

test('project share preserves document-only guests without granting project membership', async () => {
  const share = readFileSync('web/js/88-share-offline.js', 'utf8')
  const load = share.slice(share.indexOf('async function loadShares()'), share.indexOf('function roleSel('))
  const c = setup({ shareN: 0, renderShares: () => {}, api: async (_m, url) => url.includes('/projects/')
    ? { role: 'owner', members: [{ username: 'member', role: 'editor' }] }
    : { shares: [{ username: 'member', role: 'reviewer' }, { username: 'guest', role: 'reviewer' }] } })
  vm.runInContext(load, c); await c.loadShares()
  assert.equal(c.shares.length, 2)
  assert.equal(c.shares[0].doc_id, undefined)
  assert.equal(c.shares[1].username, 'guest')
  assert.equal(c.shares[1].doc_id, 'd')
  assert.match(share, /s\.doc_id \? `\/api\/docs\/\$\{s\.doc_id\}\/share` : shareUrl/)
})

test('pull retries every colliding source mapping and submits refreshed preview', async () => {
  const calls = [], answers = ['root-new.typ', 'left.typ', 'right.typ', true]
  const c = setup({ ask: async () => answers.shift(), api: async (_m, url, body) => {
    calls.push({ url, body: JSON.parse(JSON.stringify(body)) })
    if (calls.length === 1) return { files: [{ source: 'dir/root.typ', name: 'root.typ' }, { source: 'a/shared.typ', name: 'shared.typ' }, { source: 'b/shared.typ', name: 'shared.typ' }], collisions: ['root.typ', 'shared.typ'] }
    return url.endsWith('pull-preview') ? { collisions: [], preview: 'fresh' } : { name: body.name }
  } })
  assert.equal(await c.pullLibrary({ source_scope: 'project', source: 'dir/root.typ' }, { scope: 'personal' }), 'root-new.typ')
  assert.equal(calls[1].body.name, 'root-new.typ')
  assert.deepEqual(calls[1].body.renames, { 'a/shared.typ': 'left.typ', 'b/shared.typ': 'right.typ' })
  assert.equal(calls[2].body.preview, 'fresh')
  assert.equal(calls[2].body.overwrite, undefined)
})

test('personal pull defaults to basename and collision cancel never copies', async () => {
  let requested
  const c = setup({ ask: async () => null, api: async (_m, url, body) => { requested = body.name; return { collisions: [body.name] } } })
  assert.equal(await c.pullLibrary({ source: 'nested/module.typ' }, { scope: 'personal' }), null)
  assert.equal(requested, 'module.typ')
})

test('dependency rename cancellation aborts pull', async () => {
  const answers = [null], calls = []
  const c = setup({ ask: async () => answers.shift(), api: async (_m, url) => { calls.push(url); return { files: [{ source: 'dep.typ', name: 'dep.typ' }], collisions: ['dep.typ'] } } })
  assert.equal(await c.pullLibrary({ source: 'root.typ' }, { scope: 'personal' }), null)
  assert.deepEqual(calls, ['/api/library/pull-preview'])
})

test('copying a project file to the personal modules pulls it from its project under its base name', async () => {
  const calls = []
  const c = setup({ projects: [], tabSig: '', queueRender: () => {}, ask: async (_label, options) => options.noInput ? true : options.value,
    api: async (_m, url, body) => { calls.push({ url, body }); return url.endsWith('-preview') ? { preview: 'token' } : { name: body.name } } })
  await c.copyFileToPersonal('source-project', 'nested/a.typ')
  assert.deepEqual(calls.map(x => x.url), ['/api/library/pull-preview', '/api/library/pull'])
  assert.equal(calls[0].body.source_project_id, 'source-project')
  assert.equal(calls[0].body.source, 'nested/a.typ')
  assert.equal(calls[0].body.name, 'a.typ')
})

test('navigation during pull preview aborts before confirmation and copy', async () => {
  const calls = []
  const c = setup({ ask: async () => 'a.typ', api: async (_m, url) => { calls.push(url); c.openN++; return {} } })
  assert.equal(await c.pullLibrary({ source: 'a.typ' }, { scope: 'personal' }), null)
  assert.equal(calls.length, 1)
})


test('sidebar callers share one request and schedule one follow-up', async () => {
  const docs = readFileSync('web/js/60-docs.js', 'utf8')
  const wrapper = docs.slice(docs.indexOf('let sidePending'), docs.indexOf('async function refreshSidebar'))
  let release, calls = 0, renameOpen = null
  const gate = new Promise(resolve => { release = resolve }), timers = []
  const c = vm.createContext({ document: { querySelector: () => renameOpen, body: { classList: { contains: () => false } } }, window: {},
    refreshSidebar: async () => { calls++; await gate },
    setTimeout: fn => { timers.push(fn); return timers.length }, clearTimeout: () => {} })
  vm.runInContext(wrapper, c)
  const first = c.sidebar(), second = c.sidebar(), third = c.sidebar()
  assert.equal(first, second); assert.equal(second, third); assert.equal(calls, 1)
  release(); await first
  assert.equal(timers.length, 1)
  await timers[0](); assert.equal(calls, 2)
  renameOpen = {}
  await c.sidebar()
  assert.equal(c.window.__sidebarDeferred, true); assert.equal(calls, 2)
})


test('project tabs list only what was opened: documents and project files', () => {
  const files = readFileSync('web/js/80-files-images.js', 'utf8')
  const fn = files.slice(files.indexOf('function projectTabEntry('), files.indexOf('const tabErrs'))
  const c = setup({ window: {}, projects: [{ id: 'p', documents: [{ id: 'd' }, { id: 'other' }],
    files: [{ path: 'image.png' }, { path: 'data/data.csv' }, { path: 'closed.png' }] }],
    lastFiles: [{ path: 'image.png' }, { path: 'closed.png' }], tabName: k => k })
  vm.runInContext(fn, c)
  vm.runInContext("openTabs = ['d:d', 'd:other', 'f:image.png', 'f:data/data.csv', 'r:unused.typ', 'f:gone.png', 'f:d/image.png']", c)
  assert.deepEqual(Array.from(c.tabItems()), ['', '@doc/other', 'image.png', 'data/data.csv'])
  assert.equal(c.projectTabEntry('data/data.csv').document, 'd')
  assert.equal(c.projectTabEntry('data/data.csv').name, 'data/data.csv')
})


test('dropping a file on another project keeps its path without any picker', async () => {
  const source = { id: 'p', role: 'owner' }, target = { id: 'target', documents: [{ id: 'first' }, { id: 'second' }] }, calls = []
  const c = setup({ docId: '', ask: () => assert.fail('no name dialog for drop'), askPick: () => assert.fail('no target document dialog'),
    api: async (_method, url, body) => { calls.push({ url, body }); return {} }, filesDirty: false })
  await c.transferProjectEntry(source, { kind: 'file', name: 'img/image.png' }, true, target, true)
  assert.equal(calls.length, 1)
  assert.equal(calls[0].body.target_doc_id, undefined)
  assert.equal(calls[0].body.target_name, 'img/image.png')
})

test('history remains project-wide for modules and read-only project members', () => {
  const history = readFileSync('web/js/84-history.js', 'utf8')
  const fn = history.slice(0, history.indexOf('// --- History'))
  const c = setup({ projects: [{ id: 'p', role: 'reviewer' }], docResReadonly: true, activeFile: 'module.typ' })
  vm.runInContext(fn, c)
  assert.equal(c.historyUrl(), '/api/projects/p/snapshots')
  c.projects[0].role = 'guest'
  assert.equal(c.historyUrl(), '/api/docs/d/snapshots')
})

test('preview keeps compiling the document beside text and binary file tabs, but not for a personal module', async () => {
  const preview = readFileSync('web/js/50-preview.js', 'utf8')
  const fn = preview.slice(preview.indexOf('async function render()'), preview.indexOf('async function renderDirect'))
  let started = 0
  const c = setup({ window: {}, tplName: '', activeFile: 'lib/module.typ', renderN: 0, $: () => ({}), pvBar: () => { started++; throw new Error('stop') } })
  vm.runInContext(fn, c)
  await assert.rejects(c.render(), /stop/)
  c.activeFile = 'image.png'
  await assert.rejects(c.render(), /stop/)
  assert.equal(started, 2)
  c.tplName = 'personal.typ'
  await c.render()
  assert.equal(started, 2)
})


test('file download menu follows the active extension and omits document exports', () => {
  const ui = readFileSync('web/js/ui-layer.js', 'utf8')
  const fn = ui.slice(ui.indexOf('  function exportItems()'), ui.indexOf('  var DEF ='))
  const button = { dataset: { extension: 'png', kind: 'file' } }
  const c = vm.createContext({ $: () => button, t: (key, params) => key + (params?.ext || ''),
    it: (label, run, options) => ({ label, run, options }), shown: () => true, click: () => {} })
  vm.runInContext(fn, c)
  assert.equal(c.exportItems().length, 2)
  assert.equal(c.exportItems()[0].label, 'menu.dlFile.png')
  button.dataset.extension = 'csv'
  assert.equal(c.exportItems()[0].label, 'menu.dlFile.csv')
  button.dataset.kind = 'document'; button.dataset.extension = 'typ'
  assert.equal(c.exportItems().length, 5)
})

test('rail shortcuts open a collapsed section and never close an open one', () => {
  const ui = readFileSync('web/js/ui-layer.js', 'utf8')
  const fn = ui.slice(ui.indexOf('  function section(hid)'), ui.indexOf('  var RAIL ='))
  let expanded = false, clicks = 0, scrolls = 0
  const heading = { getAttribute: () => String(expanded), click: () => assert.fail('header is not the toggle'),
    querySelector: () => ({ click: () => { expanded = true; clicks++ } }), scrollIntoView: () => scrolls++ }
  const c = vm.createContext({ expand: () => {}, $: () => heading, setTimeout: fn => fn() })
  vm.runInContext(fn, c)
  c.section('trashH'); c.section('trashH')
  assert.equal(expanded, true); assert.equal(clicks, 1); assert.equal(scrolls, 2)
})


test('repeated CSV sidebar clicks share one pending open', async () => {
  let finish, switches = 0
  const c = setup({ window: { changeSession: {} },
    switchTab: name => { switches++; return new Promise(r => { finish = () => { c.activeFile = name; r(true) } }) } })
  const first = c.openProjectEntry({ id: 'p' }, 'd', 'data.csv')
  const second = c.openProjectEntry({ id: 'p' }, 'd', 'data.csv')
  assert.equal(first, second)
  assert.equal(switches, 1)
  finish(); await first
  await c.openProjectEntry({ id: 'p' }, 'd', 'data.csv')
  assert.equal(switches, 1)
})


test('empty trash sends one bulk request for twelve entries and never opens a document', async () => {
  const nodes = new Map(), writes = []
  const node = () => ({ style: {}, children: [], dataset: {}, setAttribute: () => {}, appendChild(n) { this.children.push(n) },
    append(...ns) { this.children.push(...ns) }, replaceChildren() { this.children = [] } })
  const c = vm.createContext({ $: id => { if (!nodes.has(id)) nodes.set(id, node()); return nodes.get(id) },
    el: node, icoBtn: node, t: key => key, kb: () => {}, sidebarDropTarget: () => {}, sidebarDrag: () => {},
    secShut: new Set(), docId: 'active', activeFile: '', ICO_UNDO: '', ICO_X: '', ICO_MORE: '',
    searchOn: () => false, searchFilters: {}, searchFold: new Set(), searchEmpty: node,
    searchMatch: () => false, searchContent: () => 0, searchTextEl: (cls, text) => node(cls, text),
    searchHitBadge: () => {}, searchFindQ: () => '', findWith: () => {},
    ask: async () => true, sidebar: async () => {}, reanchorSideMenu: () => {}, closeView: () => assert.fail('active document must stay open'),
    openDoc: () => assert.fail('deletion must not open a document'), toast: message => assert.fail(message),
    api: async (method, url) => { writes.push([method, url]); return { documents: [] } } })
  const docs = readFileSync('web/js/60-docs.js', 'utf8')
  vm.runInContext(docs.slice(docs.indexOf('function paintTrash('), docs.indexOf("$('q').oninput")), c)
  c.paintTrash(Array.from({ length: 12 }, (_, i) => ({ id: 'trash' + i, title: 'Old ' + i })))
  await nodes.get('trashH').children[1].sideMenuItems()[0].run()
  assert.deepEqual(writes, [['DELETE', '/api/trash']])
})


test('expanding a project from welcome opens its first document without replacing an open editor', async () => {
  const fn = source.slice(source.indexOf('    const toggle = async () =>'), source.indexOf('    title.onclick = toggle'))
  const opened = []
  const c = vm.createContext({ key: 'project:p', shut: new Set(['project:p']), entries: { documents: [{ id: 'first' }, { id: 'second' }] },
    searching: false, searchFold: new Set(), docId: '', tplName: '', saveShut: () => {}, paintOwn: () => {}, paintShared: () => {},
    lastShared: [], openDoc: async id => opened.push(id) })
  vm.runInContext(fn + '; globalThis.toggleProject = toggle', c)
  await c.toggleProject()
  assert.deepEqual(opened, ['first'])
  c.docId = 'already-open'; c.shut.add('project:p')
  await c.toggleProject()
  assert.deepEqual(opened, ['first'])
})
