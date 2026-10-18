const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')

const source = fs.readFileSync('web/js/96-login-actions.js', 'utf8')
const start = source.indexOf('const avUrl')
const helpers = source.slice(start, source.indexOf('let regMode', start))

function setup({ user, avatarV, withImage }) {
  const requested = []
  class FakeImage {
    set src(v) {
      requested.push(v)
      const ok = withImage.some(n => v.includes('/api/avatar/' + n + '?'))
      Promise.resolve().then(() => (ok ? this.onload() : this.onerror()))
    }
  }
  const context = vm.createContext({ Image: FakeImage, user, avatarV, encodeURIComponent })
  const { paintAvatar } = vm.runInContext(`${helpers}; ({ paintAvatar })`, context)
  const node = () => ({ dataset: {}, style: {}, textContent: '' })
  return { paintAvatar, node, requested }
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

test('a person without a profile picture keeps the initials on the color blob', async () => {
  const { paintAvatar, node } = setup({ user: 'alice', avatarV: 1, withImage: [] })
  const dot = node()
  paintAvatar(dot, 'carol', '#123456')
  await flush()
  assert.equal(dot.textContent, 'CA')
  assert.equal(dot.style.background, '#123456')
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
