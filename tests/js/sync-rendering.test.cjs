const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const read = name => fs.readFileSync('web/js/' + name, 'utf8')
const preview = read('50-preview.js')
const sync = read('40-editor-sync.js')
const settings = read('90-settings.js')

function workerContext() {
  const src = preview.slice(preview.indexOf('const PV_WORKER_SRC = `') + 'const PV_WORKER_SRC = `'.length,
    preview.indexOf('`\nlet pvWorker'))
  const posted = [], state = { resets: 0, mapped: 0, failCompile: false, failMap: false, seen: '' }
  const comp = {
    reset: async () => { state.resets++ },
    compile: async () => {
      if (state.failCompile) return { result: null, diagnostics: [{ severity: 'error', message: 'bad' }] }
      return { result: new Uint8Array([1]), diagnostics: [] }
    }
  }
  const T = {
    resetShadow: async () => { state.mapped = 0 },
    mapShadow: async () => { if (state.failMap) throw new Error('map'); state.mapped++ },
    addSource: async (path, text) => { state.seen = String(text) },
    getCompiler: async () => comp
  }
  const c = vm.createContext({ self: {}, Uint8Array, TextEncoder, TextDecoder, setTimeout,
    postMessage: m => posted.push(m) })
  vm.runInContext(src + '\n;globalThis.__setT = v => { T = v }; globalThis.__run = onmessage;', c)
  c.__setT(T)
  return { c, posted, state }
}

async function work(c, data) {
  c.__run({ data })
  for (let i = 0; i < 5; i++) await new Promise(resolve => setImmediate(resolve))
}

const job = (id, full) => ({ cmd: 'work', id, full, main: '= Hi', files: [{ name: 'a.png', bytes: [1] }], tpl: [] })

test('a content error after the full remap still reports the shadow as mapped', async () => {
  const { c, posted, state } = workerContext()
  state.failCompile = true
  await work(c, job(1, true))
  assert.equal(posted[0].fail, 'bad')
  assert.equal(posted[0].mapped, true)
  state.failCompile = false
  await work(c, job(2, false))
  assert.equal(posted[1].mapped, true)
  assert.ok(posted[1].pdf)
})

test('a mapping failure leaves the shadow unmapped for the next render', async () => {
  const { c, posted, state } = workerContext()
  state.failMap = true
  await work(c, job(1, true))
  assert.equal(posted[0].fail, 'map')
  assert.equal(posted[0].mapped, false)
})

test('incremental compiles keep the compiler cache, a full remap resets it once', async () => {
  const { c, state } = workerContext()
  await work(c, job(1, true))
  await work(c, job(2, false))
  await work(c, job(3, false))
  assert.equal(state.resets, 1)
  assert.equal(state.mapped, 1) // one remap, not one per keystroke
  assert.equal(state.seen, '= Hi')
})

test('an older finished compile is shown while a newer render is still queued', () => {
  const line = preview.slice(preview.indexOf('const pvStale'), preview.indexOf('\n', preview.indexOf('const pvStale')))
  const c = vm.createContext({ shownN: 2, docId: 'doc', tplName: '' })
  vm.runInContext(line + '\n;globalThis.__stale = pvStale', c)
  assert.equal(c.__stale(3, 'doc', ''), false) // finished after the screen, still useful
  assert.equal(c.__stale(2, 'doc', ''), false) // exactly what is on screen
  assert.equal(c.__stale(1, 'doc', ''), true) // older than the screen
  assert.equal(c.__stale(3, 'other', ''), true) // other document
})

test('a newer prepared page state is never taken over by an older render', () => {
  const src = preview.slice(preview.indexOf('function pvMetaClaim'), preview.indexOf('async function render()'))
  const c = vm.createContext({ pvMetaGen: 0 })
  vm.runInContext(src, c)
  assert.equal(c.pvMetaClaim(2), true)
  assert.equal(c.pvMetaClaim(1), false) // older compile finished late: no page state for it
  assert.equal(c.pvMetaClaim(2), true) // the same render may reclaim on a retry
  assert.equal(c.pvMetaClaim(3), true)
  assert.equal(c.pvMetaGen, 3)
})

test('an older render never reads pages or writes anchors after a newer state claimed them', async () => {
  const src = preview.slice(preview.indexOf('async function pvDraw'), preview.indexOf('function pvEvict'))
  const c = vm.createContext({ pvMetaGen: 2, shownN: 1, pvScale: 2 })
  vm.runInContext(src, c)
  const slot = { isConnected: false, dataset: { page: '1' } }
  let gets = 0
  const doc = { getPage: async () => { gets++; throw new Error('stop') } }
  await c.pvDraw(slot, doc, 1, true) // older render: blocked before page access
  assert.equal(gets, 0)
  assert.equal(slot.dataset.busy, undefined)
  await assert.rejects(c.pvDraw(slot, doc, 2, true), /stop/) // owner: proceeds
  assert.equal(gets, 1)
})

function renderContext() {
  const src = preview.slice(preview.indexOf('const pvStale'), preview.indexOf('function pvCssW'))
  const pending = new Map(), docs = {}, gates = {}, shown = []
  const el = () => ({
    style: {}, dataset: {}, children: [], firstChild: null, clientHeight: 800,
    append(c) { this.children.push(c); if (!this.firstChild) this.firstChild = c },
    appendChild(c) { this.append(c) },
    querySelector: () => null,
    replaceChildren(...c) { this.children = c },
    getBoundingClientRect: () => ({ top: 0, bottom: 800, height: 800 }),
  })
  const page = { getViewport: ({ scale }) => ({ width: 600 * scale, height: 800 * scale }) }
  const previewEl = el()
  const pdfjsLib = {
    getDocument: ({ data }) => {
      const gate = gates[data]
      const doc = {
        numPages: 1, destroyed: false,
        getPage: () => gate ? gate.then(() => page) : Promise.resolve(page),
        destroy() { this.destroyed = true },
      }
      docs[data] = doc
      return { promise: Promise.resolve(doc) }
    },
  }
  const c = vm.createContext({
    window: { pdfjsLib }, pdfjsLib, navigator: { onLine: true }, console,
    document: { createElement: el, createTextNode: () => ({}) },
    $: id => id === 'preview' ? previewEl : el(),
    t: key => key, toast() {}, el: () => el(), noteCompiler() {},
    renderN: 0, shownN: 0, pvMetaGen: 0, oldPdf: null, pvSlots: [], pvJobN: 0,
    cmpWarns: [], lastInfra: false, errLines: [], errKey: '', lastErrToast: '',
    docId: 'doc', tplName: '', openN: 1, activeFile: '', shadow: '', fileCache: new Map(),
    getT: () => 'main', pvWorkerFail: false, pvWorkerOk: true, pvEnsureWorker: () => true,
    pvBar() {}, pvFiles: async () => ({ sig: 'sig', tpl: [] }),
    pvCall: (job, id) => new Promise(resolve => pending.set(id, pdf => resolve({ pdf, diags: [] }))),
    pvScale: 2, pvZoom: 100, pvHasImages: () => false,
    pvCssW: w => w, pvBlank() {}, pvModeApply() {}, pvDraw: async () => {},
    pvAnchorRead: () => ({ page: -1 }), pvAnchorBack() {}, scrollApplyPreview() {},
    pvWatch() {}, pvTextAll() {}, pvLoadOutline: async () => {},
    clearErr() {}, paintErr: () => { c.__errors = (c.__errors || 0) + 1 },
  })
  c.__errors = 0
  vm.runInContext(src, c)
  const wait = async fn => { for (let i = 0; i < 200; i++) { if (fn()) return; await new Promise(r => setImmediate(r)) } throw new Error('timeout') }
  return {
    c, docs, previewEl, wait,
    render: () => c.render(),
    queued: id => wait(() => pending.has(id)),
    resolve: (id, pdf) => pending.get(id)(pdf),
    gate: pdf => {
      let open
      const p = new Promise(resolve => { open = resolve })
      p.open = open
      gates[pdf] = p
    },
    open: pdf => gates[pdf].open(),
  }
}

test('a finished render is shown although a newer one is already queued', async () => {
  const env = renderContext()
  const one = env.render()
  await env.queued(1)
  const two = env.render()
  await env.queued(2)
  env.resolve(1, 'pdf1')
  await env.wait(() => env.c.shownN === 1) // the finished compile wins over the queued one
  assert.equal(env.c.oldPdf, env.docs.pdf1)
  assert.equal(env.previewEl.children.length, 1)
  assert.equal(env.docs.pdf1.destroyed, false) // what is on screen stays alive
  env.resolve(2, 'pdf2')
  await env.wait(() => env.c.shownN === 2)
  assert.equal(env.c.oldPdf, env.docs.pdf2)
  assert.equal(env.docs.pdf1.destroyed, true) // released only at the swap
  assert.equal(env.c.__errors, 0)
  await Promise.all([one, two])
})

test('a render that lost the screen releases its pdf, the shown one stays', async () => {
  const env = renderContext()
  env.gate('pdf1')
  const one = env.render()
  await env.queued(1)
  const two = env.render()
  await env.queued(2)
  env.resolve(1, 'pdf1')
  await env.wait(() => env.docs.pdf1 && env.c.pvMetaGen === 1) // parked while reading the first page
  env.resolve(2, 'pdf2')
  await env.wait(() => env.c.shownN === 2)
  assert.equal(env.c.oldPdf, env.docs.pdf2)
  env.open('pdf1')
  await env.wait(() => env.docs.pdf1.destroyed) // older page state: released, never swapped
  assert.equal(env.c.shownN, 2)
  assert.equal(env.previewEl.children.length, 1)
  assert.equal(env.c.__errors, 0)
  await Promise.all([one, two])
})

test('block formulas read only their own source lines, never the whole file', () => {
  const src = settings.slice(settings.indexOf('function pvSrcMath'), settings.indexOf('function pvAlign'))
  const lines = [
    { line: 1, s: 'intro', map: [0, 1, 2, 3, 4] },
    { line: 2, s: 'x+1', map: [10, 11, 12] },
    { line: 3, s: '=y', map: [20, 21] },
    { line: 4, s: 'tail', map: [0, 1, 2, 3] },
  ]
  const guarded = new Proxy(lines, { get (target, prop) { // outside the formula: the old scan touched these
    if (prop === '0' || prop === '3') throw new Error('scanned a line outside the formula')
    return target[prop]
  } })
  const c = vm.createContext({
    pvMainText: () => 'main\n', pvSrcList: () => [{ key: '', text: 'src' }], pvFileAnchor: () => 0,
    srcViewOf: () => ({ lines: guarded }), srcObjs: () => ({ formulas: [{ line: 2, end: 3 }] }),
    pvMathNorm: s => s,
  })
  vm.runInContext(src, c)
  const out = c.pvSrcMath()
  assert.equal(out.length, 1)
  assert.equal(out[0].s, 'x+1=y')
  assert.equal(JSON.stringify(out[0].own.map(o => [o.line, o.at])), '[[2,10],[2,11],[2,12],[3,20],[3,21]]')
})


test('equal length drift never applies editor changes to the wrong Yjs positions', () => {
  const slice = sync.slice(sync.indexOf('function pushLocal'), sync.indexOf('function pullRemote'))
  const state = { inserted: false, wrote: '' }
  const c = vm.createContext({
    window: {},
    ydoc: { transact: fn => fn() },
    ytext: { length: 3, toString: () => 'abc', insert: () => { state.inserted = true }, delete: () => {} },
    shadow: 'xyz',
    getT: () => 'xQyz',
    setYText: v => { state.wrote = v }
  })
  vm.runInContext(slice + ';globalThis.__push = pushLocal', c)
  const changes = { iterChanges: cb => cb(1, 1, 1, 1, { toString: () => 'Q' }) }
  c.__push(changes, 3)
  assert.equal(state.inserted, false)
  assert.equal(state.wrote, 'xQyz')
  assert.equal(c.shadow, 'xQyz')
})
