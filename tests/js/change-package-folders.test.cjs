const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const packages = fs.readFileSync('web/js/features/zz-change-packages.js', 'utf8')
const pullWrapper = packages.slice(packages.indexOf('const sessionPullLibrary'), packages.indexOf('const sessionOriginalLinePop'))
const nameHelper = packages.slice(packages.indexOf('function sessionFileName'), packages.indexOf('async function sessionAddFile'))

function context(extra = {}) {
  const File = class { constructor(parts, name) { this.name = name; this.size = String(parts[0] || '').length; this.parts = parts } }
  const c = vm.createContext({
    File, t: key => key, sessionKey: file => file.kind + ':' + file.path, effTpl: () => [],
    pullLibrary: async (...args) => { c.baseCalls.push(args) },
    sessionAddFile: async file => { c.added.push(file.name); return file.name },
    baseCalls: [], added: [], window: { changeSession: null }, ...extra,
  })
  vm.runInContext(pullWrapper, c)
  vm.runInContext(nameHelper, c)
  return c
}

test('change-session pull keeps the personal folder or follows the target folder', async () => {
  const c = context({
    api: async () => ({ templates: [{ name: 'global.typ', folder: 'MeineOrdner', content: '#include "helper.typ"' }, { name: 'helper.typ', folder: 'MeineOrdner', content: '' }] }),
  })
  c.window.changeSession = { project: 'p', files: new Map() }
  const target = { scope: 'project', project_id: 'p' }
  assert.equal(await c.pullLibrary({ source_scope: 'personal', source: 'global.typ' }, target), 'MeineOrdner/global.typ')
  assert.deepEqual(c.added, ['MeineOrdner/global.typ', 'MeineOrdner/helper.typ'])
  c.added.length = 0
  assert.equal(await c.pullLibrary({ source_scope: 'personal', source: 'global.typ' }, target, 'Ziel'), 'Ziel/global.typ')
  assert.deepEqual(c.added, ['Ziel/global.typ', 'Ziel/helper.typ'])
})

test('outside a change session the target folder reaches the live pull', async () => {
  const c = context()
  const source = { source_scope: 'personal', source: 'global.typ' }, target = { scope: 'project', project_id: 'p' }
  await c.pullLibrary(source, target, 'Ziel')
  assert.deepEqual(JSON.parse(JSON.stringify(c.baseCalls)), [[source, target, 'Ziel']])
})

test('change-session uploads keep nested folder paths and the file extension', async () => {
  const c = context()
  const folder = 'a'.repeat(40) + '/' + 'b'.repeat(40) + '/'
  const file = 'x'.repeat(120) + '.typ'
  const name = c.sessionFileName(folder + file)
  assert.equal(name, folder + 'x'.repeat(96) + '.typ')
  assert.equal(c.sessionFileName('src/nested/helper.typ'), 'src/nested/helper.typ')
  assert.throws(() => c.sessionFileName('../escape.typ'))
})
