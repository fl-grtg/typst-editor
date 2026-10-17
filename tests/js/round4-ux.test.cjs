const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const zz = fs.readFileSync('web/js/features/zz-change-packages.js', 'utf8')
const docs = fs.readFileSync('web/js/60-docs.js', 'utf8')
const hlx = fs.readFileSync('web/js/30-highlight-theme.js', 'utf8')
const files = fs.readFileSync('web/js/80-files-images.js', 'utf8')
const plain = value => JSON.parse(JSON.stringify(value))

function node(cls, text) {
  const n = {
    className: cls || '', textContent: text == null ? '' : String(text), children: [], dataset: {}, title: '', onclick: null,
    append(c) { this.children.push(c); return c },
    appendChild(c) { return this.append(c) },
    prepend(c) { this.children.unshift(c); return c },
    insertBefore(c, ref) {
      let i = ref == null ? this.children.length : this.children.indexOf(ref)
      if (i < 0) i = this.children.length
      this.children.splice(i, 0, c)
      return c
    },
    setAttribute() {},
    remove() { this.children = [] },
    querySelector(sel) { return this.children.find(c => '.' + c.className === sel) },
  }
  return n
}
function context(extra = {}) {
  const c = vm.createContext({ t: key => key, window: {}, toast: () => { throw Error('unexpected toast') }, ...extra })
  return c
}

test('proposal marks wait for their text buffer during document transitions', () => {
  let buffer = '', painted
  const f = { content: 'x'.repeat(41) }
  const c = context({
    window: { changeSession: { files: new Map([['file', f]]) } }, activeFile: '',
    sessionKey: () => 'file', sessionCurrent() {}, threadHighlights: () => [], getT: () => buffer,
    sessionChangeRanges: () => [{ old: '', a: 0, b: 41 }],
    Decoration: { mark: () => ({ range: (from, to) => ({ from, to }) }) },
    RangeSet: { of: marks => { if (marks.some(r => r.to > buffer.length)) throw RangeError('Out of range'); return marks } },
    setHl: { of: marks => marks }, cm: { dispatch: tr => { painted = tr.effects } },
    gutter() {}, csvGrid: { hidden: true },
  })
  vm.runInContext(zz.slice(zz.indexOf('function sessionPaint() {'), zz.indexOf('function sessionCellChanged')), c)
  c.sessionPaint()
  assert.equal(painted.length, 0)
  buffer = f.content
  c.sessionPaint()
  assert.equal(painted[0].to, 41)
})

// #2: kept package drafts attach inside the owning project group (own or shared), never the sidebar root
test('paintSessionSidebar places the draft group inside its project group after the header', () => {
  let removes = 0, stale = [{ remove: () => removes++ }, { remove: () => removes++ }]
  const head = node('fhd'), home = node('project-group')
  home.dataset.projectId = 'p1'
  home.appendChild(head)
  const own = node('own')
  const doc = {
    querySelectorAll(sel) {
      if (sel === '.package-files') return stale
      if (sel === '#own .project-group, #shared .project-group') return [home]
      return []
    },
  }
  const s = { project: 'p1', package: { title: 'P1' }, files: new Map(), dirty: false, busy: false }
  const c = context({
    window: { changeSession: s }, document: doc, el: (tag, cls, text) => node(cls, text), $: name => own,
    sessionFiles: () => [], sessionKey: k => JSON.stringify(k), sessionRuntime: f => ({ ...f }), sessionStash() {},
    sessionCurrent: () => null, switchTab() {}, sessionActivate() {}, sessionOpenFile() {},
    projectAction() {}, ICO_CHECK: '', ICO_TRASH: '', docRole: 'owner',
  })
  vm.runInContext(zz.slice(zz.indexOf('function paintSessionSidebar() {'), zz.indexOf('async function sessionOpenFile')), c)
  c.paintSessionSidebar()
  assert.equal(removes, 2) // previous groups were cleaned up first
  const group = home.children[1]
  assert.equal(group.className, 'package-files') // inside the project group, after its header
  assert.deepEqual(group.textContent !== 'P1' && home.children[0].className, 'fhd')
  assert.equal(group.children[0].className, 'package-caption')
  assert.equal(group.children[0].textContent, 'P1')
  assert.equal(own.children.length, 0) // nothing was prepended to the sidebar root
})

test('paintSessionSidebar keeps drafts reachable at the root when the origin project is gone', () => {
  let removes = 0, stale = [{ remove: () => removes++ }]
  const own = node('own')
  const doc = { querySelectorAll() { return false } } // no .package-files found, no home either
  const doc2 = {
    querySelectorAll(sel) {
      if (sel === '.package-files') return stale
      return []
    },
  }
  const s = { project: 'gone', package: null, files: new Map(), dirty: false, busy: false }
  const c = context({
    window: { changeSession: s }, document: doc2, el: (tag, cls, text) => node(cls, text), $: name => own,
    sessionFiles: () => [], sessionKey: k => JSON.stringify(k), sessionRuntime: f => ({ ...f }), sessionStash() {},
    sessionCurrent: () => null, switchTab() {}, sessionActivate() {}, sessionOpenFile() {},
    projectAction() {}, ICO_CHECK: '', ICO_TRASH: '', docRole: 'owner',
  })
  vm.runInContext(zz.slice(zz.indexOf('function paintSessionSidebar() {'), zz.indexOf('async function sessionOpenFile')), c)
  c.paintSessionSidebar()
  assert.equal(removes, 1)
  assert.equal(own.children.length, 1) // fallback: still reachable at the top of the sidebar
  const group = own.children[0]
  assert.equal(group.className, 'package-files')
  assert.equal(group.children[0].className, 'package-caption origin-gone') // note says where the draft came from
  assert.equal(group.children[0].textContent, 'packages.originGone')
  assert.equal(doc.querySelectorAll(), false) // housekeeping of the offline doc stub
})

test('paintOwn and paintShared keep the draft group attached after every project render', () => {
  const hooks = zz.slice(zz.indexOf('const sessionOriginalPaintOwn = paintOwn'), zz.indexOf('const sessionOriginalCloseView = closeView'))
  const calls = []
  const c = context({
    window: { changeSession: null },
    paintOwn: () => calls.push('own'), paintShared: () => calls.push('shared'),
    paintSessionSidebar: () => calls.push('sidebar'), paintSuggestionControls() {},
    addEventListener() {},
  })
  vm.runInContext(hooks, c)
  c.paintOwn(); c.paintShared()
  assert.deepEqual(calls, ['own', 'sidebar', 'shared', 'sidebar'])
})

// #3: hover-claim lights up every fragment of a thread/suggestion/patch, clears everywhere else
function frag(kind, id) {
  const e = { claims: new Set(), closest(sel) { const k = sel.slice(1, -1); return this[k] != null ? this : null }, classList: { add: names => e.claims.add(names), remove: names => e.claims.delete(names) } }
  if (kind) e[kind] = id
  e.getAttribute = key => e[key]
  return e
}
function hoverDom(elements) {
  return {
    listeners: {},
    addEventListener(type, fn) { this.listeners[type] = fn },
    querySelectorAll(sel) {
      if (sel === '.cm-hl-claim') return elements.filter(e => e.claims.has('cm-hl-claim'))
      if (sel.startsWith('[')) return elements.filter(e => e[sel.slice(1, -1)] != null)
      return []
    },
  }
}
test('claimSet claims all fragments sharing the id and clears on plain text or mouseleave', () => {
  const c1a = frag('data-comment-id', 'c1'), c1b = frag('data-comment-id', 'c1'), s1 = frag('data-suggestion-id', 's1')
  const dom = hoverDom([c1a, c1b, s1])
  const c = context({ cm: { dom } })
  vm.runInContext(hlx.slice(hlx.indexOf('const CLAIM_KINDS'), hlx.indexOf("cm.dom.addEventListener('mouseleave', clearClaim)") + "cm.dom.addEventListener('mouseleave', clearClaim)".length), c)
  c.claimSet(c1a)
  assert.equal(c1a.claims.has('cm-hl-claim'), true)
  assert.equal(c1b.claims.has('cm-hl-claim'), true) // sibling fragment lights up too
  assert.equal(s1.claims.has('cm-hl-claim'), false)
  c.claimSet(c1b) // same id: idempotent, stays claimed
  assert.equal(c1a.claims.has('cm-hl-claim'), true)
  c.claimSet(s1)
  assert.equal(s1.claims.has('cm-hl-claim'), true)
  assert.equal(c1a.claims.has('cm-hl-claim'), false) // switching ids clears the previous claim
  assert.equal(c1b.claims.has('cm-hl-claim'), false)
  c.claimSet({ closest: () => null }) // plain editor text
  assert.equal(s1.claims.has('cm-hl-claim'), false)
  c.claimSet(s1)
  dom.listeners.mouseleave()
  assert.equal(s1.claims.has('cm-hl-claim'), false) // leaving the editor clears the claim
})

// #6: topbar chip data flow
test('collectPackages merges and dedupes project and docs payloads, newest first', () => {
  const badge = node('pBadge')
  badge.style = {}
  const c = context({ $: name => badge, projects: [], askPick: async () => -1 })
  vm.runInContext(docs.slice(docs.indexOf('let topPackages = []'), docs.indexOf('function refreshDocRole(d) {')), c)
  const list = c.collectPackages(
    { packages: [{ project: 'p1', title: 'A', updated_at: '2026-01-02T10:00:00Z' }] },
    { packages: [{ project: 'p1', title: 'A', updated_at: '2026-01-02T10:00:00Z' }, { project: 'p2', id: '9', updated_at: '2026-01-03T10:00:00Z' }] },
  )
  assert.equal(list.length, 2)
  assert.equal(list[0].project, 'p2') // newest first
  assert.equal(list[1].title, 'A')
  vm.runInContext(`topPackages = ${JSON.stringify(list)}`, c)
  c.paintPackages()
  assert.equal(badge.style.display, '')
  assert.equal(badge.textContent, '2')
  vm.runInContext('topPackages = []', c)
  c.paintPackages()
  assert.equal(badge.style.display, 'none')
  assert.equal(badge.textContent, '')
})

test('pBadge click lists open review packages and opens the picked one', async () => {
  const badge = node('pBadge')
  let picked
  const opened = []
  const c = context({
    $: name => badge,
    projects: [{ id: 'p1', title: 'Projekt A' }],
    askPick: async (head, opts) => { picked = { head, opts }; return 0 },
  })
  c.window.openTopPackage = entry => opened.push(entry)
  vm.runInContext(docs.slice(docs.indexOf('let topPackages = []'), docs.indexOf('function refreshDocRole(d) {')), c)
  vm.runInContext('topPackages = [{ project: "p1", title: "", id: "7", author: "ana", updated_at: "2026-01-02T10:00:00Z" }, { project: "p1", title: "Fix", id: "8" }]', c)
  await badge.onclick()
  assert.equal(picked.head, 'packages.topList')
  assert.equal(picked.opts.length, 2)
  assert.equal(picked.opts[0][0], 'packages.untitled') // no title yet
  assert.equal(picked.opts[0][1].includes('Projekt A'), true)
  assert.equal(picked.opts[0][1].includes('ana'), true)
  assert.equal(picked.opts[1][0], 'Fix')
  assert.equal(opened[0].id, '7')
})

// #8a: shared standalone docs get the duplicate button for editors too (guest_copy)
test('docRow duplicate button gating covers shared editors without a project', () => {
  const shapes = []
  const c = context({
    el: (tag, cls, text) => node(cls, text), icoBtn: (cls, icon) => node(cls, icon),
    kb() {}, sidebarDrag() {}, ICO_DUP: 'dup', ICO_TRASH: 'trash', t: key => key,
    docId: '', activeFile: '', api: () => { throw Error('no network in test') }, openDoc() {}, toast() {}, ask: async () => null, sidebar() {},
  })
  vm.runInContext(docs.slice(docs.indexOf('function docRow(x, shared, bare)'), docs.indexOf('\nfunction ', docs.indexOf('function docRow(x, shared, bare)'))), c)
  const has = (x, shared, bare, marker) => { const row = c.docRow(x, shared, bare); shapes.push(marker + '=' + row.children.map(ch => ch.className).join('|')) }
  has({ id: 'd1', title: 'A', project_id: '', role: 'owner' }, false, false, 'own')
  has({ id: 'd2', title: 'B', project_id: '', role: 'editor' }, true, false, 'sharedEditorNoProject')
  has({ id: 'd3', title: 'C', project_id: '', role: 'reviewer' }, true, false, 'sharedReviewerNoProject')
  has({ id: 'd4', title: 'D', project_id: 'p1', role: 'editor' }, true, false, 'sharedEditorProject')
  assert.equal(shapes[0], 'own=t|mini|mini') // own: dup + trash
  assert.equal(shapes[1], 'sharedEditorNoProject=t|mini') // NEW: dup without trash
  assert.equal(shapes[2], 'sharedReviewerNoProject=t') // reviewer: no dup, no trash
  assert.equal(shapes[3], 'sharedEditorProject=t|mini|mini')
})

// #8b: reviewers keep the media manager (browse + copy only), trash hides it entirely
test('renderMediaChips hides upload and delete for reviewers but keeps copy chips', () => {
  const bar = { style: {}, children: [], replaceChildren() { bar.children = [] }, appendChild(c) { bar.children.push(c); return c } }
  let copied = null
  const c = context({
    $: name => bar, docRole: 'reviewer', openedTrashed: false, mediaOpen: true, paintTabs() {},
    el: (tag, cls, text) => node(cls, text), icoBtn: (cls, icon) => node(cls, icon),
    TEXT_EXT: /\.(typ|bib|csv|tsv|json|yaml|yml|toml|xml|txt|csl)$/i, ICO_DUP: 'dup', ICO_X: 'x',
    deleteFile: () => { throw Error('reviewer must not delete') },
    copyToLibrary: name => { copied = name },
    mediaInsert: () => '', cm: { state: { facet: () => true, selection: { main: { from: 0, to: 0 } } }, dispatch() {}, focus() {} },
    toast() {},
  })
  vm.runInContext(files.slice(files.indexOf('function renderMediaChips(files)'), files.indexOf("$('mediaBtn').onclick")), c)
  c.renderMediaChips([{ name: 'pic.png', size: 2000 }])
  assert.equal(bar.style.display, '')
  const chip = bar.children[0]
  assert.equal(chip.children.some(x => x.onclick && (x.onclick === null)), false)
  assert.equal(bar.children.length, 1) // no upload button
  assert.equal(chip.children.length, 2) // name + size, no delete X
  assert.equal(chip.children[0].onclick, null) // insert is blocked for reviewers
  assert.equal(chip.children[1].className, 'sz')
  c.renderMediaChips([{ name: 'module.typ', size: 20 }])
  const textChip = bar.children[0]
  assert.equal(textChip.children.length, 3) // name + size + copy
  textChip.children[2].onclick()
  assert.equal(copied, 'module.typ') // backend allows library-copy for any reader role
  // owner keeps the full set
  bar.replaceChildren(); c.docRole = 'owner'
  c.renderMediaChips([{ name: 'a.typ', size: 10 }])
  assert.equal(bar.children.length, 2) // upload button + one chip
  const ochip = bar.children[1]
  assert.equal(ochip.children.length, 4) // name (clickable) + size + delete X + copy
  assert.notEqual(ochip.children[0].onclick, null)
  // trash hides the whole manager again
  bar.replaceChildren(); c.openedTrashed = true
  c.renderMediaChips([{ name: 'a.typ', size: 10 }])
  assert.equal(bar.style.display, 'none')
  assert.equal(bar.children.length, 0)
})

// #6 opener: open the project document first, then start (or fall back to picker)
test('openTopPackage routes to the document, loads the proposal and avoids double sessions', async () => {
  const calls = [], started = [], toasts = [], picked = []
  const c = context({
    window: {}, docProject: 'p1', lastOwn: [{ id: 'd1', project_id: 'p1' }], lastShared: [],
    t: key => key, toast: msg => toasts.push(msg), sidebar: async () => {}, endChangeSession: async () => true,
    choosePackage: async () => picked.push(true), startChangeSession: async p => started.push(p),
    api: async (method, url) => { calls.push([method, url]); return { id: url.slice(url.lastIndexOf('/') + 1), title: 'P', files: [] } },
  })
  c.openDoc = async id => { calls.push(['openDoc', id]); c.docProject = id.indexOf('p2') >= 0 ? 'p2' : 'p1' }
  vm.runInContext(zz.slice(zz.indexOf('// #6: topbar chip opener - entry'), zz.indexOf('window.openTopPackage = openTopPackage') + 'window.openTopPackage = openTopPackage'.length), c)
  // current project already open: load proposal directly
  await c.openTopPackage({ project: 'p1', id: '7' })
  assert.deepEqual(calls.pop(), ['GET', '/api/projects/p1/proposals/7'])
  assert.equal(started[0].id, '7')
  calls.length = 0
  // other project: open one of its documents first (shared list order: own then shared)
  c.lastShared = [{ id: 'd9p2', project_id: 'p2' }]
  await c.openTopPackage({ project: 'p2', id: '8' })
  assert.deepEqual(calls[0], ['openDoc', 'd9p2'])
  assert.deepEqual(calls[1], ['GET', '/api/projects/p2/proposals/8'])
  assert.equal(started[1].id, '8')
  calls.length = 0
  // entry without id: picker fallback
  await c.openTopPackage({ project: 'p1' })
  assert.deepEqual(picked, [true])
  assert.deepEqual(calls.map(x => x[1]), ['d1']) // case 2 left p2 active, so d1 was reopened first
  // duplicate open guard
  c.window.changeSession = { package: { id: '7' } }; calls.length = 0
  await c.openTopPackage({ project: 'p1', id: '7' })
  assert.equal(calls.length, 0)
  c.window.changeSession = null
  // unknown project: hint + sidebar refresh, no navigation
  await c.openTopPackage({ project: 'pX', id: '3' })
  assert.deepEqual(toasts, ['projects.openLinkedDoc'])
  // blocked session close aborts
  calls.length = 0; toasts.length = 0
  c.window.changeSession = { package: null }
  c.endChangeSession = async () => false
  await c.openTopPackage({ project: 'p1', id: '7' })
  assert.equal(calls.length, 0)
  c.endChangeSession = async () => true
  // no visible document anywhere: hint + refresh
  c.lastOwn = []; c.lastShared = []
  await c.openTopPackage({ project: 'pX', id: '3' })
  assert.deepEqual(toasts, ['projects.openLinkedDoc'])
  assert.deepEqual(picked, [true])
})
