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
