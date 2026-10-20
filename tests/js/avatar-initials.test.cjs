const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')

const source = fs.readFileSync('web/js/96-login-actions.js', 'utf8')
const start = source.indexOf('const avUrl')
const helpers = source.slice(start, source.indexOf('let regMode', start))

function setup({ user, avatarV, withImage, statuses, offline }) {
  const requested = []
  function FakeFetch(url) {
    requested.push(url)
    return Promise.resolve().then(() => {
      const st = statuses && requested.length <= statuses.length ? statuses[requested.length - 1]
        : withImage.some(n => url.includes('/api/avatar/' + n + '?')) ? 200 : 404
      if (st === 'reject') throw new TypeError('Failed to fetch') // same rejection a dead network gives
      return { ok: st === 200, status: st }
    })
  }
  const nav = offline ? { onLine: false } : undefined // distinct name: a bare `navigator` here is Node's own global, not the sandbox's
  const context = vm.createContext({ fetch: FakeFetch, navigator: nav, user, avatarV, encodeURIComponent })
  const { paintAvatar } = vm.runInContext(`${helpers}; ({ paintAvatar })`, context)
  const node = () => ({ dataset: {}, style: {}, textContent: '' })
  return { paintAvatar, node, requested, nav }
}
const flush = () => new Promise(r => setImmediate(r))

test('a person with a profile picture shows the picture without initials on top', async () => {
  const { paintAvatar, node } = setup({ user: 'alice', avatarV: 1, withImage: ['bob'] })
  const dot = node()
  paintAvatar(dot, 'bob', '#123456')
  assert.equal(dot.textContent, 'BO') // initials until the image is confirmed
  await flush()
  assert.equal(dot.textContent, '')
  assert.match(dot.style.background, /url\("\/api\/avatar\/bob\?v=1"\)/)
})

test('a person without a profile picture keeps the initials and is not re-probed after the 404', async () => {
  const { paintAvatar, node, requested } = setup({ user: 'alice', avatarV: 1, withImage: [] })
  const dot = node()
  paintAvatar(dot, 'carol', '#123456')
  await flush()
  assert.equal(dot.textContent, 'CA')
  assert.equal(dot.style.background, '#123456')
  paintAvatar(dot, 'carol', '#123456') // later render: the 404 was a final answer, stale entries stay out
  await flush()
  assert.equal(requested.length, 1)
})

test('own account without an image does not request one', async () => {
  const { paintAvatar, node, requested } = setup({ user: 'alice', avatarV: 0, withImage: [] })
  const dot = node()
  paintAvatar(dot, 'alice', '#123456')
  await flush()
  assert.equal(dot.textContent, 'AL')
  assert.deepEqual(requested, [])
})

test('a stale probe result does not overwrite a newer paint of the same node', async () => {
  const { paintAvatar, node } = setup({ user: 'alice', avatarV: 1, withImage: ['bob'] })
  const dot = node()
  paintAvatar(dot, 'bob', '#123456')
  paintAvatar(dot, 'dave', '#654321')
  await flush()
  assert.equal(dot.textContent, 'DA')
  assert.equal(dot.style.background, '#654321')
})

test('a probe that fell on its face (network down) is retried by a later render', async () => {
  const { paintAvatar, node, requested } = setup({ user: 'alice', avatarV: 1, withImage: ['bob'], statuses: ['reject', 200] })
  const dot = node()
  paintAvatar(dot, 'bob', '#123456')
  await flush()
  assert.equal(requested.length, 1)
  assert.equal(dot.textContent, 'BO') // unknowable for now: initials stay
  paintAvatar(dot, 'bob', '#123456')
  await flush()
  assert.equal(requested.length, 2) // failed answer was not cached
  assert.equal(dot.textContent, '')
  assert.match(dot.style.background, /url\("\/api\/avatar\/bob\?v=1"\)/)
})

test('a server hiccup (5xx, 429) is retried too, a follow-up 404 is not', async () => {
  const { paintAvatar, node, requested } = setup({ user: 'alice', avatarV: 1, withImage: [], statuses: [500, 429, 404] })
  const dot = node()
  paintAvatar(dot, 'carol', '#123456')
  await flush()
  assert.equal(requested.length, 1)
  assert.equal(dot.textContent, 'CA')
  paintAvatar(dot, 'carol', '#123456')
  await flush()
  assert.equal(requested.length, 2)
  paintAvatar(dot, 'carol', '#123456')
  await flush()
  assert.equal(requested.length, 3) // 429 recovered into the truth: no image
  paintAvatar(dot, 'carol', '#123456')
  await flush()
  assert.equal(requested.length, 3) // but the 404 itself is final
  assert.equal(dot.textContent, 'CA')
})

test('one paint storm shares one request while the probe is still in flight', async () => {
  const { paintAvatar, requested } = setup({ user: 'alice', avatarV: 1, withImage: ['bob'] })
  const dot = () => ({ dataset: {}, style: {}, textContent: '' })
  paintAvatar(dot(), 'bob', '#123456')
  paintAvatar(dot(), 'bob', '#123456') // same render, before the probe settles
  await flush()
  assert.equal(requested.length, 1)
})

test('offline tabs ask nothing, yet recover with the next render back online', async () => {
  const { paintAvatar, node, requested, nav } = setup({ user: 'alice', avatarV: 1, withImage: ['bob'], offline: true })
  const dot = node()
  paintAvatar(dot, 'bob', '#123456')
  await flush()
  assert.deepEqual(requested, [])
  assert.equal(dot.textContent, 'BO')
  nav.onLine = true
  paintAvatar(dot, 'bob', '#123456')
  await flush()
  assert.equal(requested.length, 1)
  assert.equal(dot.textContent, '')
  assert.match(dot.style.background, /url\("\/api\/avatar\/bob\?v=1"\)/)
})
