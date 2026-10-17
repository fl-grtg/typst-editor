const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')

const source = fs.readFileSync('web/js/96-login-actions.js', 'utf8')
const start = source.indexOf("api('GET', '/api/me').then(async d => { // session")
const restore = source.slice(start, source.indexOf('try { (window.requestIdleCallback', start))

test('late session initialization respects an already-started document navigation', async () => {
  for (const openN of [0, 1]) {
    const opened = []
    const context = vm.createContext({
      api: async () => ({ user: 'alice' }), loadSpell() {}, paintMe() {},
      $: () => ({ style: {}, classList: { add() {} } }), cm: { measure() {} },
      openN, docId: '', tplName: '', URLSearchParams, location: { search: '' },
      sidebar: async () => {}, watchSidebar() {}, loadTpl: async () => {}, checkJoin: async () => false,
      lastOwn: [{ id: 'tutorial', title: 'Tutorial' }], lastShared: [], openDoc: id => opened.push(id),
      console,
    })
    await vm.runInContext(restore, context)
    assert.deepEqual(opened, openN === 0 ? ['tutorial'] : [])
  }
})
