const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const packages = fs.readFileSync('web/js/features/zz-change-packages.js', 'utf8')
const tabs = fs.readFileSync('web/js/80-files-images.js', 'utf8')

function context() {
  const file = { kind: 'document', doc_id: 'd_new', path: 'main.typ', action: 'add', target: 'New chapter', content: 'Draft' }
  const session = { files: new Map([['document:d_new:main.typ', file]]), project: 'p_test', previewRevision: 0 }
  const c = vm.createContext({ window: { changeSession: session }, docId: 'd_existing', shadow: '', activeFile: '@proposal-doc/d_new.typ',
    isTplKey: () => false, tabName: k => k || 'main.typ', session, file })
  vm.runInContext(packages.slice(packages.indexOf('const sessionKey'), packages.indexOf('const sessionUrl')), c)
  return c
}

test('new document is a separate review tab and never aliases the source document', () => {
  const c = context()
  vm.runInContext(tabs.slice(tabs.indexOf('function projectTabEntry'), tabs.indexOf('function tabItems')), c)
  assert.equal(vm.runInContext('sessionCurrent().doc_id', c), 'd_new')
  assert.equal(vm.runInContext("projectTabEntry(activeFile).document", c), 'd_new')
  assert.equal(vm.runInContext("projectTabEntry(activeFile).name", c), '')
  vm.runInContext("activeFile = ''", c)
  assert.equal(vm.runInContext('sessionCurrent().doc_id', c), 'd_existing')
})

test('opening an added document uses the package copy without fetching a missing live document', async () => {
  const c = context()
  let live = 0, activated = 0
  Object.assign(c, { switchTab: async () => { live++; throw Error('live source called') },
    sessionActivate: async () => activated++, tabSaveState: () => {}, paintTabs: () => {} })
  vm.runInContext(packages.slice(packages.indexOf('const sessionOriginalSwitchTab'), packages.indexOf('const sessionOriginalOpenDoc')), c)
  assert.equal(await c.switchTab('@proposal-doc/d_new.typ'), true)
  assert.equal(live, 0)
  assert.equal(activated, 1)
})

test('discarding an active added document keeps the project draft and returns to its source', async () => {
  const c = context()
  let switched
  Object.assign(c, { switchTab: async name => { switched = name }, sessionStash: () => {}, paintSessionSidebar: () => {}, paintTabs: () => {} })
  vm.runInContext(packages.slice(packages.indexOf('async function discardSessionFile'), packages.indexOf('async function sessionOpenFile')), c)
  await c.discardSessionFile(c.file)
  assert.equal(switched, '')
  assert.equal(c.session.files.size, 0)
  assert.equal(c.window.changeSession, c.session)
})

test('sidebar selection follows added document and attachment tabs instead of their source document', () => {
  const c = context()
  const keys = ['document:d_existing:main.typ', 'document:d_new:main.typ', 'file:d_existing:pixel.png']
  const rows = keys.map(key => ({ dataset: { packageKey: key }, current: false,
    closest: () => ({ dataset: { projectId: 'p_test' } }),
    classList: { toggle: (_name, value) => { rows[keys.indexOf(key)].current = value } } }))
  c.document = { querySelectorAll: () => rows }
  vm.runInContext(packages.slice(packages.indexOf('function paintSessionSelection'), packages.indexOf('function paintSessionSidebar')), c)
  c.paintSessionSelection()
  assert.deepEqual(rows.map(row => row.current), [false, true, false])
  vm.runInContext("activeFile = 'pixel.png'", c)
  c.paintSessionSelection()
  assert.deepEqual(rows.map(row => row.current), [false, false, true])
  vm.runInContext("activeFile = ''", c)
  c.paintSessionSelection()
  assert.deepEqual(rows.map(row => row.current), [true, false, false])
})

test('dependent partial acceptance includes only dependencies after confirmation and respects cancellation', async () => {
  for (const confirm of [false, true]) {
    const c = context(), calls = []
    c.session.package = { id: 'sp_test', revision: 1 }
    Object.assign(c, {
      saveSessionCorrections: async () => true, cm: { dispatch: () => {} }, editableComp: { reconfigure: () => {} }, editMode: () => {},
      paintFileExtras: () => {}, paintSuggestionControls: () => {}, sessionActivate: async () => {}, sessionUrl: () => '/proposals/sp_test',
      t: key => key, ask: async () => confirm, toast: () => {},
      api: async (_method, _url, body) => {
        calls.push(body)
        const error = new Error(calls.length === 1 ? 'Accept the referenced file and its text changes together: heading.typ' : 'test stop')
        error.status = calls.length === 1 ? 409 : 400
        error.detail = { code: calls.length === 1 ? 'proposal_dependencies' : 'other' }
        throw error
      },
    })
    vm.runInContext(packages.slice(packages.indexOf('async function acceptSessionSelection'), packages.indexOf('async function deleteSelectedPackage')), c)
    await c.acceptSessionSelection('pf_selected')
    assert.equal(calls.length, confirm ? 2 : 1)
    assert.equal(calls[0].file_id, 'pf_selected')
    if (confirm) {
      assert.equal(calls[1].file_id, 'pf_selected')
      assert.equal(calls[1].include_dependencies, true)
    }
  }
})

test('inline add and rename acceptance uses file actions instead of missing text anchors', async () => {
  const calls = []
  const c = vm.createContext({ acceptSessionSelection: async (...args) => calls.push(args), toast: () => { throw Error('false conflict') } })
  vm.runInContext(packages.slice(packages.indexOf('async function acceptSessionRange'), packages.indexOf('class PackageDeletion')), c)
  await c.acceptSessionRange({ id: 'added', action: 'add', base: null }, { from: 0, to: 4 })
  await c.acceptSessionRange({ id: 'renamed', action: 'rename', base: 'old', changes: [] }, { from: 0, to: 3 })
  assert.deepEqual(calls, [['added'], ['renamed']])
})

test('leaving an added document tab restores source without requesting a nonexistent attachment', async () => {
  const c = context()
  let text
  Object.assign(c, { sessionStashTimer: 0, clearTimeout: () => {}, packageDraft: async () => {}, sessionStashKey: () => 'draft',
    localStorage: { removeItem: () => {} }, fileCache: new Map(), shadow: 'Source document', setT: value => { text = value },
    cm: { dispatch: () => {} }, editableComp: { reconfigure: () => {} }, editMode: () => {}, tabCanEdit: () => true,
    paintTabs: () => {}, paintFileExtras: () => {}, paintOutline: () => {}, reanchor: () => {}, refreshHl: () => {}, queueRender: () => {},
    paintSuggestionControls: () => {}, sidebar: async () => {}, sessionOriginalSwitchTab: async () => { throw Error('nonexistent file requested') } })
  vm.runInContext(packages.slice(packages.indexOf('async function endChangeSession'), packages.indexOf('async function choosePackage')), c)
  assert.equal(await c.endChangeSession(true), true)
  assert.equal(c.activeFile, '')
  assert.equal(text, 'Source document')
  assert.equal(c.window.changeSession, null)
})

test('accepting a document rename refreshes the current document title immediately', async () => {
  const c = context()
  let endArgs
  c.session.package = { id: 'sp_test', revision: 1 }
  c.session.commentRanges = new Map()
  c.session.files = new Map([['document:d_existing:main.typ', { id: 'pf_doc', kind: 'document', doc_id: 'd_existing', path: 'main.typ', action: 'rename', target: 'New name' }]])
  Object.assign(c, { activeFile: '', docTitle: 'Old name', saveSessionCorrections: async () => true,
    cm: { dispatch: () => {} }, editableComp: { reconfigure: () => {} }, editMode: () => {}, paintFileExtras: () => {},
    paintSuggestionControls: () => {}, sessionUrl: () => '/proposals/sp_test', loadDocResources: async () => {}, projectResources: () => [],
    api: async () => ({ files: [], revision: 2 }), threads: [], initRanges: () => {}, invalidateCommentCache: () => {},
    fileCache: new Map(), closePop: () => {}, endChangeSession: async (...args) => { endArgs = args; c.window.changeSession = null },
    toast: message => { throw Error(message) } })
  vm.runInContext(packages.slice(packages.indexOf('async function acceptSessionSelection'), packages.indexOf('async function deleteSelectedPackage')), c)
  await c.acceptSessionSelection('pf_doc')
  assert.equal(c.docTitle, 'New name')
  assert.deepEqual(endArgs, [true, true, '']) // accepting the last proposal preserves the current view
})

test('sidebar action checks accept only structural actions and leave content changes alone', async () => {
  const calls = [], row = {}
  const c = vm.createContext({ window: { changeSession: { package: {} } }, docRole: 'owner', ICO_CHECK: 'check', t: key => key,
    projectAction: (_row, _icon, _label, run) => { calls.push(run); return { classList: { add: () => {} } } },
    acceptSessionSelection: async (...args) => args })
  vm.runInContext(packages.slice(packages.indexOf('function sessionActionButton'), packages.indexOf('async function discardSessionFile')), c)
  for (const action of ['rename', 'delete', 'add', 'modify']) c.sessionActionButton(row, { id: action, action })
  assert.equal(calls.length, 3)
  for (let i = 0; i < calls.length; i++) assert.deepEqual(Array.from(await calls[i]()), [['rename', 'delete', 'add'][i], '@action'])
})


test('parallel accepts cannot submit the same revision twice', async () => {
  const c = context()
  c.session.package = { revision: 1 }
  let release, saves = 0, writes = 0
  Object.assign(c, { saveSessionCorrections: () => { saves++; return new Promise(r => { release = r }) },
    cm: { dispatch: () => {} }, editableComp: { reconfigure: () => {} }, editMode: () => {},
    paintFileExtras: () => {}, paintSuggestionControls: () => {}, sessionActivate: async () => {},
    sessionUrl: () => '/proposal', toast: () => {}, api: async () => { writes++; throw Error('stop') } })
  vm.runInContext(packages.slice(packages.indexOf('async function acceptSessionSelection'), packages.indexOf('async function deleteSelectedPackage')), c)
  const first = c.acceptSessionSelection('one')
  await c.acceptSessionSelection('two')
  assert.equal(saves, 1)
  release(true); await first
  assert.equal(writes, 1)
  assert.equal(c.session.accepting, false)
})

test('accepted revision survives a failed refresh and a rename with pending content updates the title', async () => {
  const c = context()
  c.session.package = { revision: 1 }
  c.session.files = new Map([['document:d_existing:main.typ', { id: 'doc', kind: 'document', doc_id: 'd_existing', path: 'main.typ', action: 'rename', target: 'New title' }]])
  const pending = { id: 'doc', kind: 'document', doc_id: 'd_existing', path: 'main.typ', action: 'modify' }
  Object.assign(c, { docTitle: 'Old title', activeFile: '', saveSessionCorrections: async () => true,
    cm: { dispatch: () => {} }, editableComp: { reconfigure: () => {} }, editMode: () => {},
    paintFileExtras: () => {}, paintSuggestionControls: () => {}, sessionActivate: async () => {},
    sessionUrl: () => '/proposal', toast: () => {}, sessionRuntime: f => f,
    loadDocResources: async () => { throw Error('refresh failed') }, api: async () => ({ revision: 2, files: [pending] }) })
  vm.runInContext(packages.slice(packages.indexOf('async function acceptSessionSelection'), packages.indexOf('async function deleteSelectedPackage')), c)
  await c.acceptSessionSelection('doc', '@action')
  assert.equal(c.session.package.revision, 2)
  assert.equal(c.session.files.get('document:d_existing:main.typ').action, 'modify')
  assert.equal(c.docTitle, 'New title')
  assert.equal(c.session.accepting, false)
})


test('accepting current document deletion closes review without fetching trashed resources', async () => {
  for (const tab of ['', 'style.typ']) {
    const c = context()
    c.session.package = { revision: 1 }
    c.session.commentRanges = new Map()
    c.session.files = new Map([['document:d_existing:main.typ', { id: 'deleted', kind: 'document', doc_id: 'd_existing', path: 'main.typ', action: 'delete' }]])
    let closed = 0, ended = 0
    Object.assign(c, { activeFile: tab, projects: [], saveSessionCorrections: async () => true,
      cm: { dispatch: () => {} }, editableComp: { reconfigure: () => {} }, editMode: () => {},
      paintFileExtras: () => {}, paintSuggestionControls: () => {}, sessionUrl: () => '/proposal',
      api: async () => ({ revision: 2, files: [] }), threads: [], initRanges: () => {}, invalidateCommentCache: () => {},
      fileCache: new Map(), closePop: () => {}, loadDocResources: async () => assert.fail('trashed resources requested'),
      closeView: () => closed++, endChangeSession: async () => { assert.equal(c.activeFile, ''); ended++; c.window.changeSession = null },
      toast: message => assert.fail(message) })
    vm.runInContext(packages.slice(packages.indexOf('async function acceptSessionSelection'), packages.indexOf('async function deleteSelectedPackage')), c)
    await c.acceptSessionSelection('deleted', '@action')
    assert.equal(ended, 1)
    assert.equal(closed, 1)
    assert.equal(c.session.accepting, false)
  }
})


test('bibliography entry indicators show only records with remaining field changes', () => {
  const c = context()
  const entry = { key: 'a', type: 'book', fields: [{ name: 'title', value: 'Title' }, { name: 'year', value: '2021' }] }
  const old = { ...entry, fields: [{ name: 'title', value: 'Title' }, { name: 'year', value: '2020' }] }
  c.parseBib = () => [old]
  vm.runInContext(packages.slice(packages.indexOf('function sessionBibEntryPending'), packages.indexOf('function sessionBibField')), c)
  assert.equal(c.sessionBibEntryPending({ base: 'old' }, entry), true)
  assert.equal(c.sessionBibEntryPending({ base: 'old' }, old), false)
  c.parseBib = () => [entry]
  assert.equal(c.sessionBibEntryPending({ base: 'accepted' }, entry), false)
  assert.equal(c.sessionBibEntryPending({ base: 'accepted' }, { ...entry, key: 'new' }), true)
  c.session.original = true
  assert.equal(c.sessionBibEntryPending({ base: 'old' }, entry), false)
})

test('ending acceptance preserves main and module views instead of restoring old tab positions', async () => {
  for (const key of ['', '@scrolling.typ']) {
    let restored, switched
    const c = context()
    Object.assign(c, { activeFile: key, isTplKey: value => value.startsWith('@'), sessionStashTimer: 0,
      clearTimeout() {}, packageDraft: async () => {}, sessionStashKey: () => 'draft',
      localStorage: { removeItem() {} }, fileCache: new Map(), shadow: 'Accepted source',
      setT: (...args) => { restored = args }, cm: { dispatch() {} }, editableComp: { reconfigure() {} }, editMode() {}, tabCanEdit: () => true,
      paintTabs() {}, paintFileExtras() {}, paintOutline() {}, reanchor() {}, refreshHl() {}, queueRender() {}, paintSuggestionControls() {},
      sidebar: async () => {}, loadDocResources: async () => {}, sessionOriginalSwitchTab: async (...args) => { switched = args; return true } })
    vm.runInContext(packages.slice(packages.indexOf('async function endChangeSession'), packages.indexOf('async function choosePackage')), c)
    await c.endChangeSession(true, true)
    if (key) assert.deepEqual(switched, [key, true, true])
    else assert.deepEqual(restored, ['Accepted source', true])
  }
})

test('last acceptance restores accepted text even before its websocket echo arrives', async () => {
  for (const shadow of ['old text', 'new text']) {
    const c = context()
    c.session.package = { id: 'sp_test', revision: 1 }
    c.session.commentRanges = new Map()
    c.session.files = new Map([['document:d_existing:main.typ', { id: 'pf_doc', kind: 'document', doc_id: 'd_existing', path: 'main.typ', action: 'modify', base: 'old text', content: 'new text' }]])
    let restored
    Object.assign(c, { activeFile: '', shadow, saveSessionCorrections: async () => true, cm: { dispatch() {} },
      editableComp: { reconfigure() {} }, editMode() {}, paintFileExtras() {}, paintSuggestionControls() {},
      sessionUrl: () => '/proposals/sp_test', loadDocResources: async () => {}, projectResources: () => [],
      api: async () => ({ files: [], revision: 2 }), threads: [], initRanges() {}, invalidateCommentCache() {},
      fileCache: new Map(), closePop() {}, endChangeSession: async (_discard, _preserve, text) => { restored = text; c.window.changeSession = null },
      toast: message => { throw Error(message) } })
    vm.runInContext(packages.slice(packages.indexOf('async function acceptSessionSelection'), packages.indexOf('async function deleteSelectedPackage')), c)
    await c.acceptSessionSelection('pf_doc')
    assert.equal(restored, 'new text')
  }
})

test('session tab wrapper forwards view preservation through both loaders', async () => {
  const c = context(), calls = []
  c.session.files.clear()
  Object.assign(c, { switchTab: async (...args) => { calls.push(args); return true },
    sessionActivate: async preserve => calls.push(preserve), paintTabs() {} })
  vm.runInContext(packages.slice(packages.indexOf('const sessionOriginalSwitchTab'), packages.indexOf('const sessionOriginalOpenDoc')), c)
  await c.switchTab('scrolling.typ', true, true)
  assert.deepEqual(calls, [['scrolling.typ', true, true], true])
})

test('unmodified project documents load their text before websocket sync instead of caching an empty buffer', async () => {
  const c = context(), reads = []
  c.activeFile = ''; c.synced = false; c.shadow = ''
  Object.assign(c, { sessionRuntime: file => file, api: async (_method, url) => { reads.push(url); return { content: 'Existing chapter text' } } })
  vm.runInContext(packages.slice(packages.indexOf('async function sessionEnsure'), packages.indexOf('function bytesToBase64')), c)
  const item = await c.sessionEnsure()
  assert.equal(item.base, 'Existing chapter text')
  assert.equal(item.content, 'Existing chapter text')
  assert.deepEqual(reads, ['/api/docs/d_existing'])
  assert.equal((await c.sessionEnsure()).content, 'Existing chapter text')
  assert.equal(reads.length, 1)
})

test('document loading prefers live text if websocket sync completes during the read', async () => {
  const c = context()
  c.activeFile = ''; c.synced = false; c.shadow = ''
  Object.assign(c, { sessionRuntime: file => file, api: async () => { c.synced = true; c.shadow = 'Latest live text'; return { content: 'Older saved text' } } })
  vm.runInContext(packages.slice(packages.indexOf('async function sessionEnsure'), packages.indexOf('function bytesToBase64')), c)
  assert.equal((await c.sessionEnsure()).content, 'Latest live text')
})

test('late proposal activation cannot blank a newly selected document', async () => {
  const c = context()
  let release, resets = 0
  Object.assign(c, { docProject: 'p_test', activeFile: '', sessionEnsure: () => new Promise(resolve => { release = resolve }), setT: () => resets++ })
  vm.runInContext(packages.slice(packages.indexOf('async function sessionActivate'), packages.indexOf('async function startChangeSession')), c)
  const pending = c.sessionActivate()
  c.docId = 'd_another'
  release({ content: 'Previous document' })
  await pending
  assert.equal(resets, 0)
})

test('proposal picker displays the key name with an account-name fallback', async () => {
  const labels = []
  const c = vm.createContext({ docProject: 'p', packageLoad: 0, window: {},
    api: async () => ({ packages: [{ author: 'alice', author_name: 'Review Bot' }, { author: 'bob', author_name: '' }] }),
    t: (_key, args) => { if (args) labels.push(args.author); return '' }, askPick: async () => null,
    toast: message => { throw Error(message) } })
  vm.runInContext(packages.slice(packages.indexOf('async function choosePackage'), packages.indexOf('// #6: topbar chip')), c)
  await c.choosePackage()
  assert.deepEqual(labels, ['Review Bot', 'bob'])
})
