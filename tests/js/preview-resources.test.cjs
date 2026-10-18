const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')

test('queued preview jobs remap after a superseded compile changed the worker resources', async () => {
  const source = fs.readFileSync('web/js/50-preview.js', 'utf8'), sent = []
  const context = vm.createContext({
    renderN: 1, pvMapped: true, pvSentSig: 'original', pvWorkerFail: false, pvWorkerOk: true,
    pvJobs: new Map(), pvEnsureWorker: () => ({ postMessage: message => sent.push(message) }), t: key => key
  })
  vm.runInContext(source.slice(source.indexOf('let pvTail ='), source.indexOf('let typstT0 =')), context)
  const tick = () => new Promise(resolve => setImmediate(resolve))
  const job = (id, sig) => ({ id, sig, cmd: 'work', main: sig, files: [{ name: sig + '.png' }], tpl: [] })
  const first = context.pvCall(job(1, 'proposal'), 1)
  await tick()
  assert.equal(sent[0].full, true)
  context.renderN = 2
  const second = context.pvCall(job(2, 'original'), 2)
  context.pvJobs.get(1).ok({})
  await first; await tick()
  assert.equal(sent[1].full, true)
  assert.equal(sent[1].files[0].name, 'original.png')
  context.pvJobs.get(2).ok({})
  await second
  context.renderN = 3
  const third = context.pvCall(job(3, 'original'), 3)
  await tick()
  assert.equal(sent[2].full, false)
  assert.equal(sent[2].files, undefined)
  context.pvJobs.get(3).ok({})
  await third
})

function fileContext(files, cache = new Map()) {
  const source = fs.readFileSync('web/js/50-preview.js', 'utf8')
  const c = vm.createContext({ docId: 'doc', openN: 1, loadDocResources: async () => true,
    filesDirty: false, filesAt: Date.now(), FILES_TTL: 15000, lastFiles: files, fileCache: cache,
    activeFile: '', tabDirty: false, fetch: async () => ({ ok: true, arrayBuffer: async () => new Uint8Array([1]).buffer }),
    pvResTpl: () => [], pvFileSig: n => n, pvBibSig: '', bibKeys: [], TextDecoder, Uint8Array,
    t: (_key, args) => args.name + ': HTTP ' + args.status, setTimeout: fn => fn() })
  vm.runInContext(source.slice(source.indexOf('async function pvFiles()'), source.indexOf('async function shadowAll(')), c)
  return c
}

test('every render retains all 51 image inputs and prunes only deleted inputs', async () => {
  const files = Array.from({ length: 51 }, (_, i) => ({ name: `image-${i}.png`, size: 1, mtime: 1 }))
  const c = fileContext(files)
  for (let i = 0; i < 3; i++) {
    await c.pvFiles()
    assert.equal(c.fileCache.size, 51)
    assert.ok(files.every(f => c.fileCache.has(f.name)))
  }
  c.lastFiles = files.slice(1)
  await c.pvFiles()
  assert.equal(c.fileCache.size, 50)
  assert.equal(c.fileCache.has('image-0.png'), false)
})

test('loading another image cannot evict current inputs larger than 100 MB', async () => {
  const size = 60 * 1024 * 1024
  const files = [{ name: 'a.png', size, mtime: 1 }, { name: 'b.png', size, mtime: 1 }, { name: 'c.png', size: 1, mtime: 1 }]
  const cache = new Map(files.slice(0, 2).map(f => [f.name, { mtime: 1, bytes: { length: size } }]))
  const c = fileContext(files, cache)
  await c.pvFiles()
  assert.equal(cache.size, 3)
})

test('failed image downloads stop resource preparation and can recover on the next render', async () => {
  const c = fileContext([{ name: 'god-test.png', size: 1, mtime: 2 }])
  c.fileCache.set('god-test.png', { mtime: 1, bytes: new Uint8Array([0]) })
  const fetch = c.fetch
  c.fetch = async () => ({ ok: false, status: 403 })
  await assert.rejects(c.pvFiles(), /god-test.png: HTTP 403/)
  assert.equal(c.fileCache.get('god-test.png').mtime, 1)
  c.fetch = fetch
  await c.pvFiles()
  assert.equal(c.fileCache.get('god-test.png').mtime, 2)
})

test('temporary image server and network failures recover once without reloading', async () => {
  for (const network of [false, true]) {
    const c = fileContext([{ name: 'god-test.png', size: 1, mtime: 1 }])
    const success = c.fetch
    let calls = 0
    c.fetch = async (...args) => {
      if (++calls === 1) {
        if (network) throw Error('connection interrupted')
        return { ok: false, status: 503 }
      }
      return success(...args)
    }
    await c.pvFiles()
    assert.equal(calls, 2)
    assert.ok(c.fileCache.has('god-test.png'))
  }
})

test('persistent server failures stop after two attempts and retain readable diagnostics', async () => {
  const c = fileContext([{ name: 'god-test.png', size: 1, mtime: 1 }])
  let calls = 0
  c.fetch = async () => { calls++; return { ok: false, status: 503 } }
  await assert.rejects(c.pvFiles(), error => error.diags[0].message === 'god-test.png: HTTP 503')
  assert.equal(calls, 2)
})
