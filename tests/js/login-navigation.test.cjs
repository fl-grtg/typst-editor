const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')

const source = fs.readFileSync('web/js/96-login-actions.js', 'utf8')
const start = source.indexOf('let tokenInvalid = false') // bootSession + the /api/me boot block
const restore = source.slice(start, source.indexOf('try { (window.requestIdleCallback', start))

test('late session initialization respects an already-started document navigation', async () => {
  for (const openN of [0, 1]) {
    const opened = []
    const context = vm.createContext({
      api: async () => ({ user: 'alice' }), loadSpell() {}, paintMe() {},
      $: () => ({ style: {}, classList: { add() {} } }), cm: { measure() {} },
      openN, docId: '', tplName: '', URLSearchParams, location: { search: '' },
      sidebar: async () => {}, watchSidebar() {}, loadInbox: async () => {}, loadTpl: async () => {}, checkJoin: async () => false,
      lastOwn: [{ id: 'tutorial', title: 'Tutorial' }], lastShared: [], openDoc: id => opened.push(id),
      console,
    })
    await vm.runInContext(restore, context)
    assert.deepEqual(opened, openN === 0 ? ['tutorial'] : [])
  }
})

test('boot exchanges a URL token and reports an invalid one after the session check', async () => {
  const nodes = {
    login: { style: {} },
    app: { classList: { add() {} } },
    err: { textContent: '' },
  }
  const bootContext = extra => vm.createContext({
    api: async () => ({ user: 'alice' }), loadSpell() {}, paintMe() {},
    $: id => nodes[id] || { style: {}, classList: { add() {} } }, cm: { measure() {} },
    sidebar: async () => {}, watchSidebar() {}, loadInbox: async () => {}, loadTpl: async () => {},
    checkJoin: async () => false, lastOwn: [], lastShared: [], openDoc() {},
    openN: 1, docId: '', tplName: '', URLSearchParams, location: { search: '', hash: '' }, console,
    hadOidcErr: false, hadInvite: false, t: k => k, loadAuthConfig: async () => {},
    ...extra,
  })

  // A token is exchanged first; the normal /api/me call then boots the app.
  // The fragment is canonical: browsers do not send it to the server.
  const calls = []
  const ctx = bootContext({
    location: { search: '', hash: '#token=tpl_abc' },
    api: async (method, path, body) => {
      calls.push([method, path, body])
      return { user: 'alice' }
    },
  })
  await vm.runInContext(restore, ctx)
  assert.equal(calls.length, 2)
  assert.deepEqual(calls[0].slice(0, 2), ['POST', '/api/login/token'])
  assert.equal(calls[0][2].token, 'tpl_abc')
  assert.deepEqual(calls[1].slice(0, 2), ['GET', '/api/me'])
  assert.equal(ctx.user, 'alice')
  assert.equal(nodes.login.style.display, 'none')

  // A rejected exchange still lets the cookie session decide; if both fail,
  // the login view explains that the link is gone.
  let authConfig = 0, authArgs = null
  const bad = bootContext({
    location: { search: '', hash: '#token=tpl_dead' },
    api: async () => { throw { status: 401 } },
    loadAuthConfig: async (...args) => { authConfig++; authArgs = args },
  })
  await vm.runInContext(restore, bad)
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(authConfig, 1)
  // badToken=true keeps OIDC auto-redirect from hiding the error.
  assert.equal(authArgs[3], true)
  assert.equal(nodes.err.textContent, 'login.linkInvalid')
})

const oidcStart = source.indexOf('function oidcErrMsg(code)')
const oidcEnd = source.indexOf('const hadOidcErr = checkOidcError()')
const oidcHelpers = source.slice(oidcStart, oidcEnd)

test('OIDC login config hides password fields and auto-redirects with join token', async () => {
  const nodes = {
    err: { textContent: '' },
    oidcBtn: { textContent: '', href: '' },
    oidcBox: { style: { display: 'none' }, classList: { toggle(c, v) { this[c] = v } } },
    pwLoginFields: { style: { display: '' } },
    oidcSep: { style: { display: '' } },
    mode: { style: { display: '' } },
  }
  const assigned = []
  let replaced = ''
  const context = vm.createContext({
    $: id => nodes[id],
    t: (k, p) => (p && p.provider ? `${k}:${p.provider}` : k),
    URLSearchParams,
    regMode: false,
    console,
    history: { replaceState(_s, _t, url) { replaced = url } },
    location: {
      pathname: '/',
      search: '?oidc_error=access_denied&join=tok42',
      assign: u => assigned.push(u),
    },
    api: async () => ({
      oidc: { enabled: true, provider_name: 'Authentik', auto_redirect: true },
      password_login: false,
      registration: 'closed',
    }),
  })
  vm.runInContext(oidcHelpers, context)
  assert.equal(context.checkOidcError(), true)
  assert.equal(replaced, '/?join=tok42')
  assert.equal(nodes.err.textContent, 'login.oidcAccessDenied')

  // Suppresses auto-redirect when hadOidcErr=true, but configures button & hides password form.
  context.location.search = '?join=tok42'
  await context.loadAuthConfig(true, false)
  assert.equal(nodes.oidcBox.style.display, '')
  assert.equal(nodes.oidcBox.classList.only, true)
  assert.equal(nodes.pwLoginFields.style.display, 'none')
  assert.equal(nodes.oidcSep.style.display, 'none')
  assert.equal(nodes.oidcBtn.textContent, 'login.signInWith:Authentik')
  assert.equal(nodes.oidcBtn.href, '/api/oidc/login?join=tok42')
  assert.deepEqual(assigned, [])

  assert.equal(context.oidcErrMsg('rate_limited'), 'login.oidcRateLimited')

  // A failed login-link exchange shows its error instead of bouncing to the IdP.
  await context.loadAuthConfig(false, false, undefined, true)
  assert.deepEqual(assigned, [])

  // Auto-redirects when no error or invite is present.
  await context.loadAuthConfig(false, false)
  assert.deepEqual(assigned, ['/api/oidc/login?join=tok42'])
})

test('OIDC auto-redirect is suppressed once after sign-out and closed registration resets invite state', async () => {
  const store = { typst_logged_out: '1' }
  const sessionStorage = {
    getItem: k => (Object.hasOwn(store, k) ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v) },
    removeItem: k => { delete store[k] },
  }
  let modeClicks = 0
  const nodes = {
    err: { textContent: '' },
    oidcBtn: { textContent: '', href: '' },
    oidcBox: { style: { display: 'none' }, classList: { toggle(c, v) { this[c] = v } } },
    pwLoginFields: { style: { display: '' } },
    oidcSep: { style: { display: '' } },
    inv: { value: 'INVITE123' },
    mode: {
      style: { display: '' },
      click() {
        modeClicks++
        context.regMode = !context.regMode
      },
    },
  }
  const assigned = []
  let authCfg = {
    oidc: { enabled: true, provider_name: 'Kanidm', auto_redirect: true },
    password_login: true,
    registration: 'closed',
  }
  const context = vm.createContext({
    $: id => nodes[id],
    t: (k, p) => (p && p.provider ? `${k}:${p.provider}` : k),
    URLSearchParams,
    regMode: true,
    console,
    sessionStorage,
    history: { replaceState() {} },
    location: { pathname: '/', search: '', assign: u => assigned.push(u) },
    api: async () => authCfg,
  })
  vm.runInContext(oidcHelpers, context)

  // Sign-out suppresses auto-redirect once and clears the flag; closed registration resets invite mode.
  await context.loadAuthConfig(false, false)
  assert.deepEqual(assigned, [])
  assert.equal(store.typst_logged_out, undefined)
  assert.equal(modeClicks, 1)
  assert.equal(context.regMode, false)
  assert.equal(nodes.inv.value, '')
  assert.equal(nodes.mode.style.display, 'none')

  // Next reload without sign-out flag auto-redirects.
  await context.loadAuthConfig(false, false)
  assert.deepEqual(assigned, ['/api/oidc/login'])
})
