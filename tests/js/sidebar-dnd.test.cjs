const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const source = fs.readFileSync('web/js/features/sidebar-dnd.js', 'utf8')
const projectCode = fs.readFileSync('web/js/features/projects.js', 'utf8')
const plain = value => JSON.parse(JSON.stringify(value))
function context(extra = {}) {
  const { document: documentExtra, ...rest } = extra
  const document = {
    addEventListener() {}, querySelectorAll: () => [],
    body: { classList: { add() {}, remove() {} }, appendChild() {} },
    createElement: () => ({ style: {}, classList: { add() {}, remove() {} }, appendChild() {}, setAttribute() {} }),
    ...documentExtra,
  }
  const c = vm.createContext({ TEXT_EXT: /\.(typ|bib|csv|tsv|json|yaml|yml|toml|xml|txt|csl)$/i, t: key => key, window: {}, toast: message => assert.fail(message), document, ...rest })
  vm.runInContext(source, c)
  return c
}
function row() { return { classList: { add() {}, remove() {} }, contains: () => false } }
function drop(data, files = []) {
  return { preventDefault() {}, stopPropagation() {}, dataTransfer: { files, types: files.length ? ['Files'] : ['application/x-typst-project-entry'], getData: () => JSON.stringify(data), setDragImage() {} } }
}
test('private module drag permits moving into trash and restoring to modules', () => {
  const node = () => ({ appendChild() {}, setAttribute() {}, closest: () => null, dataset: {}, classList: { add() {}, remove() {} }, remove() {}, querySelector: () => null })
  const c = context({ document: { createElement: node }, el: node, tplName: '', kb() {}, projectAction: () => node(), compactSidebarActions() {}, personalModuleMenu() {}, ICO_SEND: '', ICO_EDIT: '', ICO_DUP: '', ICO_TRASH: '' })
  const docs = fs.readFileSync('web/js/60-docs.js', 'utf8')
  vm.runInContext(docs.slice(docs.indexOf('function resRow'), docs.indexOf('function paintKind')), c)
  const module = c.resRow({ name: 'module.typ' }), event = drop(null)
  event.target = module; event.dataTransfer.setData = () => {}
  module.ondragstart(event)
  const trash = row(); c.sidebarDropTarget(trash, 'trash'); trash.ondragover(event)
  assert.equal(event.dataTransfer.effectAllowed, 'copyMove')
  assert.equal(event.dataTransfer.dropEffect, 'move')
  assert.equal(c.sidebarCanDrop({ trashed: true, trashId: 'tr_1', entry: { kind: 'personal', name: 'module.typ' } }, 'modules'), true)
})
test('module drop copies a project resource to the private collection', async () => {
  let copied
  const c = context({ pullLibrary: (...args) => copied = args })
  const target = row(); c.sidebarDropTarget(target, 'modules')
  await target.ondrop(drop({ project: 'p', entry: { kind: 'resource', name: 'module.typ' } }))
  assert.deepEqual(plain(copied), [{ source_scope: 'project', source_project_id: 'p', source: 'module.typ' }, { scope: 'personal' }])
})
test('trash only accepts live documents and restoration accepts trashed documents', () => {
  const c = context()
  assert.equal(c.sidebarCanDrop({ entry: { kind: 'document' } }, 'trash'), true)
  assert.equal(c.sidebarCanDrop({ trashed: true, entry: { kind: 'document' } }, 'trash'), false)
  assert.equal(c.sidebarCanDrop({ entry: { kind: 'resource', name: 'module.typ' } }, 'trash'), true)
  assert.equal(c.sidebarCanDrop({ personal: true, entry: { kind: 'resource', name: 'module.typ' } }, 'trash'), true)
  assert.equal(c.sidebarCanDrop({ project: 'p', entry: { kind: 'file', name: 'a.typ', doc_id: 'd' } }, 'trash'), true)
  assert.equal(c.sidebarCanDrop({ trashed: true, trashId: 'tr_1', entry: { kind: 'resource', name: 'm.typ' } }, 'trash'), false)
  assert.equal(c.sidebarCanDrop({ trashed: true, entry: { kind: 'document' } }, 'documents'), true)
  assert.equal(c.sidebarCanDrop({ trashed: true, trashId: 'tr_1', entry: { kind: 'resource', name: 'm.typ' } }, 'documents'), false)
})
test('project folders accept private modules and restored documents', async () => {
  let copied, restored
  const c = context({ projectEditable: () => true, pullLibrary: (...args) => copied = args, restoreSidebarDocument: (...args) => restored = args })
  c.restoreSidebarDocument = (...args) => restored = args
  vm.runInContext(projectCode.slice(projectCode.indexOf('function projectDropTarget'), projectCode.indexOf('async function renamePersonalResource')), c)
  const target = { id: 'target' }, host = row(); c.projectDropTarget(host, target)
  await host.ondrop(drop({ personal: true, entry: { kind: 'resource', name: 'module.typ', folder: '' } }))
  assert.deepEqual(plain(copied), [{ source_scope: 'personal', source: 'module.typ', folder: '' }, { scope: 'project', project_id: 'target' }, ''])
  await host.ondrop(drop({ personal: true, entry: { kind: 'resource', name: 'module.typ', folder: 'nested' } }))
  assert.equal(copied[2], '') // project root keeps the private collection folder in the source payload
  assert.equal(copied[0].folder, 'nested')
  const folderHost = row(); c.projectDropTarget(folderHost, target, 'a/b')
  await folderHost.ondrop(drop({ personal: true, entry: { kind: 'resource', name: 'module.typ', folder: 'nested' } }))
  assert.equal(copied[2], 'a/b') // an explicit folder target wins
  await host.ondrop(drop({ trashed: true, entry: { kind: 'document', doc_id: 'd' } }))
  assert.equal(restored[1], target)
})
test('private module rows carry their collection folder into drag data', () => {
  const made = []
  const node = () => ({ appendChild() {}, setAttribute() {}, closest: () => null, dataset: {}, classList: { add() {}, remove() {} }, remove() {}, querySelector: () => null })
  const c = context({ document: { createElement: node }, el: node, tplName: '', kb() {}, projectAction: () => node(), compactSidebarActions() {}, personalModuleMenu() {}, ICO_SEND: '', ICO_EDIT: '', ICO_DUP: '', ICO_TRASH: '' })
  c.sidebarDrag = (row, data) => made.push(data)
  const docs = fs.readFileSync('web/js/60-docs.js', 'utf8')
  vm.runInContext(docs.slice(docs.indexOf('function resRow'), docs.indexOf('function paintKind')), c)
  c.resRow({ name: 'module.typ', folder: 'nested' })
  assert.deepEqual(plain(made[0]), { personal: true, entry: { kind: 'resource', name: 'module.typ', folder: 'nested' } })
})
test('drops onto a second-level folder keep the destination for copy and move', async () => {
  const calls = []
  const c = context({ projectEditable: () => true, projects: [{ id: 'source' }], transferProjectEntry: async (...args) => calls.push(args) })
  vm.runInContext(projectCode.slice(projectCode.indexOf('function projectDropTarget'), projectCode.indexOf('async function renamePersonalResource')), c)
  const target = { id: 'target' }, host = row()
  c.projectDropTarget(host, target, 'a/b')
  await host.ondrop(drop({ project: 'source', entry: { kind: 'resource', name: 'src/mod.typ' } }))
  assert.equal(calls[0][3], target)
  assert.equal(calls[0][4], true)
  assert.equal(calls[0][5], 'a/b')  // cross-project move keeps the folder row as target

  const copyCalls = []
  c.transferProjectEntry = async (...args) => copyCalls.push(args)
  const sameHost = row(); c.projectDropTarget(sameHost, { id: 'source' }, 'a/b')
  const copyEvent = drop({ project: 'source', entry: { kind: 'resource', name: 'src/mod.typ' } })
  copyEvent.ctrlKey = true
  await sameHost.ondrop(copyEvent)
  assert.equal(copyCalls[0][2], false)  // Ctrl keeps the source
  assert.equal(copyCalls[0][5], 'a/b')  // the copy still lands in the drop folder
})
test('external files reach the module uploader', async () => {
  let files
  const c = context({ uploadModuleFiles: value => files = value })
  // Replace the real uploader after its declaration.
  c.uploadModuleFiles = value => files = value
  const target = row(); c.sidebarDropTarget(target, 'modules')
  const file = { name: 'module.typ' }; await target.ondrop(drop(null, [file]))
  assert.equal(files[0], file)
})
test('a Typst file dropped on modules asks document or module and respects cancellation', async () => {
  for (const choice of [null, 0, 1]) {
    const calls = []
    const c = context({ myTpl: [], loadTpl() {}, sidebar() {}, askPick: async () => choice,
      api: async (...args) => { calls.push(args); return { id: 'new-doc' } }, openDoc: async id => calls.push(['open', id]) })
    await c.uploadModuleFiles([{ name: 'sample.typ', size: 4, text: async () => 'text' }])
    if (choice == null) assert.equal(calls.length, 0)
    else assert.equal(calls[0][1], choice === 0 ? '/api/docs/create' : '/api/templates')
  }
})
test('failed draft flush blocks dragging an open document into trash', async () => {
  const c = context({ docId: 'd', flushTab: async () => false, api: () => assert.fail('must not trash unsaved content') })
  await c.trashSidebarDocument('d')
})
test('restoration refreshes the source project before moving to the target folder', async () => {
  const calls = [], target = { id: 'target' }, original = { id: 'original' }
  const c = context({ docId: '', openedTrashed: false, lastOwn: [], projects: [], api: async (...args) => calls.push(args),
    sidebar: async () => { c.lastOwn = [{ id: 'd', title: 'Restored', folder: 'a/b', project_id: 'original' }]; c.projects = [original] },
    transferProjectEntry: async (...args) => calls.push(args) })
  await c.restoreSidebarDocument({ entry: { doc_id: 'd' } }, target)
  assert.equal(calls[0][1], '/api/docs/d/restore')
  assert.equal(calls[1][0], original)
  assert.equal(calls[1][1].folder, 'a/b')  // cross-project restore keeps the folder path
  assert.equal(calls[1][3], target)
})
