// --- Find + replace: floating panel over the editor (Ctrl+F / Ctrl+H), hits as marks, Enter = next ---
// Options: match case, whole word, regex, find in selection, preserve case on replace. Extras: overview ticks beside the
// scrollbar, a clickable list of all matches grouped by line (with a replace preview), undo for replace all,
// and a per-tab search history (Alt+Up/Down). Toggles persist across reloads.
let findOpen = false, findHits = [], findI = 0, findCase = false, findRe = false, findWord = false, findKeep = false // hits are {a,b}
let findCapped = false, findReplaceOpen = false, findListOpen = false
let findWithTimer = 0, findWithN = 0, findHistI = -1, findPaintRaf = 0, findUndo = null, findPadPx = 0
const FIND_MAX = 5000 // counted + painted; the list shows the first FIND_LIST_MAX lines
const FIND_LIST_MAX = 300
const FIND_HIST_KEY = 'findHistory'
const FIND_OPTS_KEY = 'findOpts'
const FIND_WORD_CH = /[\p{L}\p{N}_]/u
const findWordCh = c => !!c && FIND_WORD_CH.test(c)
const findEsc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

function findHist() { try { return JSON.parse(sessionStorage.getItem(FIND_HIST_KEY) || '[]') } catch (e) { return [] } }
function findHistPush(q) {
  if (!q) return
  const h = [q, ...findHist().filter(x => x !== q)].slice(0, 25)
  try { sessionStorage.setItem(FIND_HIST_KEY, JSON.stringify(h)) } catch (e) {}
  findHistI = -1
}
function findHistStep(d) { // Alt+Up = older, Alt+Down = newer; past the newest clears the field
  const h = findHist()
  if (!h.length) return
  findHistI = Math.max(-1, Math.min(h.length - 1, findHistI + d))
  $('fQ').value = findHistI < 0 ? '' : h[findHistI]
  markFind(true)
}

function findSetToggle(id, on) { $(id).classList.toggle('on', on); $(id).setAttribute('aria-pressed', String(on)) }
function findSaveOpts() { try { localStorage.setItem(FIND_OPTS_KEY, JSON.stringify({ c: findCase, w: findWord, r: findRe, k: findKeep })) } catch (e) {} }
function findLoadOpts() {
  let o = {}
  try { o = JSON.parse(localStorage.getItem(FIND_OPTS_KEY) || '{}') || {} } catch (e) {}
  findCase = !!o.c; findWord = !!o.w; findRe = !!o.r; findKeep = !!o.k
  findSetToggle('fCase', findCase); findSetToggle('fWord', findWord); findSetToggle('fRe', findRe); findSetToggle('fKeep', findKeep)
}
function findEditable() { try { return cm.state.facet(EditorView.editable) } catch (e) { return false } }
function findScope() { // current find-in-selection range (mapped through edits), or null
  const it = cm.state.field(findScopeField).iter()
  return it.value ? { from: it.from, to: it.to } : null
}
function setScope(r) {
  cm.dispatch({ effects: setFindScope.of(r && r.to > r.from ? RangeSet.of([Decoration.mark({ class: 'cm-find-scope' }).range(r.from, r.to)]) : RangeSet.of([])) })
  findSetToggle('fSel', !!findScope())
}
function setReplaceOpen(on) {
  findReplaceOpen = on && findEditable()
  $('fRepRow').hidden = !findReplaceOpen
  $('fTog').setAttribute('aria-expanded', String(findReplaceOpen))
  $('find').classList.toggle('rep', findReplaceOpen)
  if (findListOpen) findPaintList() // the list shows the replace preview only while replace is open
  findRevealCur()
}
function findCover() { // editor pixels hidden under the panel, measured from the scroller top: hits are revealed below it
  if (!findOpen) return 0
  try { return Math.max(0, $('find').getBoundingClientRect().bottom - cm.scrollDOM.getBoundingClientRect().top + 10) } catch (e) { return 0 }
}
function findPad() { // extra room above the first line while the panel is open (like VS Code): the top lines can scroll out from under it
  const want = Math.round(findCover())
  if (want === findPadPx) return
  const sc = cm.scrollDOM, d = want - findPadPx
  findPadPx = want
  $('cmWrap').style.setProperty('--find-pad', want + 'px')
  sc.scrollTop += d // the text stays exactly where it was on screen
  cm.requestMeasure()
}

function openFind(withReplace = false) {
  if (!$('app').classList.contains('on')) return
  const wasOpen = findOpen
  findOpen = true; $('find').style.display = ''
  $('fTog').hidden = !findEditable() // reviewers only search
  if (withReplace || !wasOpen) setReplaceOpen(withReplace || (wasOpen && findReplaceOpen))
  const m = cm.state.selection.main
  if (!m.empty) {
    const d = cm.state.doc
    if (d.lineAt(m.from).number !== d.lineAt(m.to).number) setScope({ from: m.from, to: m.to }) // multi-line selection = search inside it
    else { $('fQ').value = getT().slice(m.from, m.to).slice(0, 200); if (findScope()) setScope(null) } // a word or phrase becomes the query
  }
  markFind(); $('fQ').focus(); $('fQ').select()
}
function findWith(q) { // sidebar content hit: wait for the freshly opened text, then find the term in it
  const n = ++findWithN
  clearTimeout(findWithTimer)
  if (!q) return
  let left = 60 // up to ~6s: the Yjs sync can trail the open by a few frames
  const run = () => {
    if (n !== findWithN) return
    if (!getT() && left-- > 0) { findWithTimer = setTimeout(run, 100); return }
    if (!$('app').classList.contains('on')) return
    scrollRestore = null // a content hit wins over the saved reading spot
    // the sidebar counts plain case-insensitive text: leftover toggles would find something else (or "bad regex")
    findCase = false; findRe = false; findWord = false
    for (const id of ['fCase', 'fRe', 'fWord']) findSetToggle(id, false)
    cm.dispatch({ selection: { anchor: cm.state.selection.main.head } }) // no selection: it would replace the query or set a scope
    setScope(null)
    openFind()
    $('fQ').value = q
    markFind(true)
    $('fQ').focus(); $('fQ').select()
  }
  run()
}
function closeFind() {
  findHistPush($('fQ').value)
  findOpen = false; $('find').style.display = 'none'
  findSetList(false)
  findPad()
  findUndo = null; findMsg('')
  cm.dispatch({ effects: [setFind.of(RangeSet.of([])), setFindScope.of(RangeSet.of([]))] })
  findSetToggle('fSel', false)
  $('fRail').replaceChildren()
  cm.focus()
}

function findCollect(text, q, from, to) { // -> {hits, err}; hits never overlap (replace-all needs disjoint changes)
  const hits = []
  let re
  try { re = new RegExp(findRe ? q : findEsc(q), findCase ? 'g' : 'gi') } catch (e) { return { hits, err: e.message.replace(/^Invalid regular expression: \/.*\/[a-z]*: /s, '') } }
  re.lastIndex = from
  let m
  try {
    while ((m = re.exec(text)) !== null) {
      if (!m[0].length) { re.lastIndex++; continue } // zero-length regex matches: skip, never hang
      const a = m.index, b = a + m[0].length
      if (b > to) break
      if (findWord && ((findWordCh(text[a - 1]) && findWordCh(text[a])) || (findWordCh(text[b - 1]) && findWordCh(text[b])))) { re.lastIndex = a + 1; continue }
      hits.push({ a, b })
      if (hits.length >= FIND_MAX) break
    }
  } catch (e) { return { hits: [], err: e.message } }
  return { hits, err: '' }
}
function findKeepCase(src, rep) { // preserve case: FOX -> WOLF, Fox -> Wolf, fox -> wolf
  if (!findKeep || !rep || src.toUpperCase() === src.toLowerCase()) return rep
  if (src === src.toUpperCase() && src.length > 1) return rep.toUpperCase()
  if (src[0] === src[0].toUpperCase() && src[0] !== src[0].toLowerCase()) return rep[0].toUpperCase() + rep.slice(1)
  if (src === src.toLowerCase()) return rep.toLowerCase()
  return rep
}
function findReplacer(txt) { // h -> replacement text, or null when the pattern cannot build one
  const q = $('fQ').value, r = $('fR').value
  if (!findRe) return h => findKeepCase(txt.slice(h.a, h.b), r)
  let one // regex replace: $1 / $<name> groups supported (lookbehind across hit edges unsupported: silent no-op)
  try { one = new RegExp('^(?:' + q + ')$', (findCase ? '' : 'i') + 's') } catch (e) { return null }
  return h => { const s = txt.slice(h.a, h.b); return findKeepCase(s, s.replace(one, r)) }
}

function findCounter() {
  const q = $('fQ').value, n = findHits.length, cap = findCapped ? '+' : ''
  const el = $('fN')
  el.classList.toggle('none', !!q && !n && !findUndo) // right after replace all, "no results" is the goal, not an error
  if (!q) el.textContent = ''
  else if (!n) el.textContent = t('find.noResults')
  else el.textContent = (findI >= 0 ? (findI + 1) + '/' : '') + n + cap
  el.title = q && n ? t('find.countT', { i: findI >= 0 ? findI + 1 : '–', n: n + cap }) : ''
}
function findMsg(text, ok = false, undo = null) {
  const box = $('fMsg')
  box.hidden = !text; box.classList.toggle('ok', ok)
  box.replaceChildren(text || '')
  if (undo) {
    const b = document.createElement('button')
    b.type = 'button'; b.className = 'fUndo'; b.textContent = t('find.undo')
    b.onclick = undo
    box.append(b)
  }
}

function findReveal(h) { // bring the current hit into the uncovered part of the editor; near: glide, far: CodeMirror's own scroll (reliable over estimated heights)
  findPad()
  const sc = cm.scrollDOM, cover = findCover(), vh = sc.clientHeight
  const c = h.a >= cm.viewport.from && h.b <= cm.viewport.to ? cm.coordsAtPos(h.a) : null
  if (c) {
    const r = sc.getBoundingClientRect(), yt = c.top - r.top + sc.scrollTop, yb = c.bottom - r.top + sc.scrollTop
    if (yt >= sc.scrollTop + cover + 8 && yb <= sc.scrollTop + vh - 24) return // already visible: never move the text under the reader
    if (Math.abs(yt - sc.scrollTop) < vh * 2) { smoothFollow(sc, (yt + yb) / 2 - cover - (vh - cover) / 2); return }
  }
  smoothStop(sc)
  cm.dispatch({ effects: EditorView.scrollIntoView(h.a, { y: 'center' }) })
}

function paintFind(sel) { // hits tinted, current one strong; sel = also jump
  cm.dispatch({ effects: setFind.of(RangeSet.of(findHits.map((h, i) =>
    Decoration.mark({ class: i === findI ? 'cm-find-cur' : 'cm-find' }).range(h.a, h.b)), true)) })
  if (sel && findHits.length && findI >= 0) {
    const h = findHits[findI]
    cm.dispatch({ selection: { anchor: h.a, head: h.b } })
    findReveal(h)
  }
  findCounter()
  $('find').classList.toggle('none', !!$('fQ').value && !findHits.length && $('fMsg').hidden && !findUndo)
  for (const id of ['fPrev', 'fNext']) $(id).disabled = findHits.length < 1
  const ro = !findEditable() || !findHits.length
  $('fRep').disabled = ro; $('fAll').disabled = ro
  findPaintRail()
  if (findListOpen) findPaintList()
}

function findPaintRail() { // overview ticks next to the scrollbar: where in the document the hits are
  cancelAnimationFrame(findPaintRaf)
  findPaintRaf = requestAnimationFrame(() => {
    const rail = $('fRail')
    if (!findOpen || !findHits.length) { rail.replaceChildren(); return }
    const total = Math.max(1, cm.contentHeight), seen = new Set(), frag = document.createDocumentFragment()
    const scope = findScope()
    if (scope) {
      const a = cm.lineBlockAt(scope.from).top / total, b = cm.lineBlockAt(scope.to).bottom / total
      const s = document.createElement('i'); s.className = 'scope'
      s.style.top = (a * 100) + '%'; s.style.height = Math.max(0.4, (b - a) * 100) + '%'
      frag.append(s)
    }
    findHits.forEach((h, i) => {
      const y = Math.round(cm.lineBlockAt(h.a).top / total * 400) // dedupe at 0.25% steps
      if (i !== findI && seen.has(y)) return
      seen.add(y)
      const tick = document.createElement('i')
      if (i === findI) tick.className = 'cur'
      tick.style.top = (y / 4) + '%'
      frag.append(tick)
    })
    rail.replaceChildren(frag)
  })
}

function findPaintList() { // one row per line: every hit in it marked (current one strong), replace preview while replace is open
  const box = $('fRes'), sum = $('fSum'), doc = cm.state.doc
  box.replaceChildren()
  if (!findHits.length) { box.hidden = true; sum.hidden = true; return }
  const groups = []
  for (let i = 0; i < findHits.length; i++) {
    const line = doc.lineAt(findHits[i].a), g = groups[groups.length - 1]
    if (g && g.line.number === line.number) g.to = i
    else groups.push({ line, from: i, to: i })
  }
  sum.hidden = false
  sum.textContent = t(groups.length === 1 ? 'find.summaryOne' : 'find.summary', { n: findHits.length + (findCapped ? '+' : ''), lines: groups.length })
  const rep = findReplaceOpen && $('fR').value !== '' ? findReplacer(getT()) : null
  const frag = document.createDocumentFragment()
  for (const g of groups.slice(0, FIND_LIST_MAX)) {
    const { line } = g, on = findI >= g.from && findI <= g.to
    const row = document.createElement('div')
    row.className = 'fHit' + (on ? ' on' : '')
    row.setAttribute('role', 'option'); row.setAttribute('aria-selected', String(on))
    row.dataset.i = on ? findI : g.from
    const ln = document.createElement('span'); ln.className = 'ln'; ln.textContent = line.number
    ln.title = t('find.line', { n: line.number })
    const tx = document.createElement('span'); tx.className = 'tx'
    const lead = findHits[on ? findI : g.from].a - line.from // the row starts near its current hit (else its first), so that one is always in sight
    let start = Math.max(0, lead - 28) // a little context before it, cut at a word start
    if (start > 0) { const sp = line.text.indexOf(' ', start); start = sp >= 0 && sp < lead ? sp + 1 : start }
    let pos = start, left = 220
    if (start > 0) tx.append('…')
    for (let i = g.from; i <= g.to && left > 0; i++) {
      const h = findHits[i], a = h.a - line.from, b = Math.min(h.b, line.to) - line.from
      if (a < start) continue
      const pre = line.text.slice(pos, a)
      tx.append(pos === start ? pre.replace(/^\s+/, '') : pre)
      const mk = document.createElement('mark')
      mk.dataset.i = i
      if (i === findI) mk.className = 'cur'
      const src = line.text.slice(a, b) || '⏎'
      const to = rep ? rep(h) : null
      if (to != null && to !== src) {
        const del = document.createElement('del'); del.textContent = src
        const ins = document.createElement('ins'); ins.textContent = to
        mk.append(del, ins)
      } else mk.textContent = src
      tx.append(mk)
      pos = b; left -= pre.length + src.length
    }
    tx.append(line.text.slice(pos, pos + Math.max(40, left)))
    row.append(ln, tx)
    frag.append(row)
  }
  box.append(frag)
  if (groups.length > FIND_LIST_MAX) {
    const more = document.createElement('div'); more.className = 'fMore'
    more.textContent = t('find.moreLines', { n: groups.length - FIND_LIST_MAX })
    box.append(more)
  }
  box.hidden = false
  const cur = box.querySelector('.fHit.on')
  if (cur) cur.scrollIntoView({ block: 'nearest' })
}
function findSetList(on) {
  findListOpen = on
  findSetToggle('fList', on); $('fList').setAttribute('aria-expanded', String(on))
  if (on) findPaintList()
  else { $('fRes').hidden = true; $('fRes').replaceChildren(); $('fSum').hidden = true }
  findRevealCur()
}
function findRevealCur() { if (findOpen && findI >= 0 && findHits[findI]) findReveal(findHits[findI]) } // the panel grew or shrank: keep the current hit uncovered

function markFind(sel = true) { // sel=false: recount only, never steal selection/scroll (typing beside an open find)
  findHits = []; findI = -1; findCapped = false
  const q = $('fQ').value
  if (!findUndo || cm.state.doc !== findUndo.doc) { findUndo = null; findMsg('') } // the undo offer lives until the text changes again
  if (!q) { paintFind(false); return }
  const text = getT(), scope = findScope()
  const r = findCollect(text, q, scope ? scope.from : 0, scope ? scope.to : text.length)
  if (r.err) { // invalid pattern: say why in the panel, never throw
    cm.dispatch({ effects: setFind.of(RangeSet.of([])) })
    $('fN').textContent = '—'; $('fN').classList.add('none')
    findMsg(t('find.badRegex') + ' · ' + r.err); $('find').classList.add('none'); $('fRail').replaceChildren()
    if (findListOpen) { $('fRes').hidden = true; $('fSum').hidden = true }
    for (const id of ['fPrev', 'fNext', 'fRep', 'fAll']) $(id).disabled = true
    return
  }
  findHits = r.hits; findCapped = r.hits.length >= FIND_MAX
  if (!findHits.length || !sel) { paintFind(false); return } // !sel: all tinted, none current, cursor stays where the user works
  const head = cm.state.selection.main.from
  findI = findHits.findIndex(h => h.a >= head)
  if (findI < 0) findI = 0
  paintFind(true)
}
function stepFind(d) {
  if (!findHits.length) return
  findHistPush($('fQ').value)
  if (findI < 0 || findI >= findHits.length) { // nothing current (user clicked or typed): continue from the cursor
    const hd = cm.state.selection.main.head
    findI = d > 0 ? findHits.findIndex(h => h.a >= hd) : findHits.findLastIndex(h => h.b <= hd)
    if (findI < 0) findI = d > 0 ? 0 : findHits.length - 1
  } else findI = (findI + d + findHits.length) % findHits.length
  paintFind(true)
}
function doRep(all) {
  if (!findEditable()) return
  const q = $('fQ').value
  if (!q || !findHits.length) return
  findHistPush(q)
  if (findI < 0 || findI >= findHits.length) { const hd = cm.state.selection.main.head; findI = findHits.findIndex(h => hd >= h.a && hd <= h.b); if (findI < 0) findI = findHits.findIndex(h => h.a >= hd); if (findI < 0) findI = 0 }
  const rep = findReplacer(getT())
  if (!rep) return
  const n = findHits.length
  if (all) {
    const before = cm.state.doc, changes = cm.state.changes(findHits.map(h => ({ from: h.a, to: h.b, insert: rep(h) })))
    cm.dispatch({ changes, userEvent: 'input.replace.all' })
    findUndo = { doc: cm.state.doc, inv: changes.invert(before) }
  } else { const h = findHits[findI], ins = rep(h); cm.dispatch({ changes: { from: h.a, to: h.b, insert: ins }, selection: { anchor: h.a + ins.length }, userEvent: 'input.replace' }) }
  markFind() // onEdit recounts anyway, here at once for the counter (and to land on the next hit)
  if (all) { findMsg(t('find.replaced', { n }), true, findUndoAll); findCounter(); $('find').classList.remove('none') }
}
function findUndoAll() { // one click puts every replaced hit back (only while nothing else changed the text)
  const u = findUndo
  findUndo = null
  if (u && cm.state.doc === u.doc) cm.dispatch({ changes: u.inv, userEvent: 'undo' })
  markFind(false)
  $('fQ').focus()
}

// Wiring
findLoadOpts()
const findOpt = flip => () => { flip(); findSaveOpts(); markFind(); $('fQ').focus() }
$('fQ').oninput = () => { findHistI = -1; markFind(true) }
$('fR').oninput = () => { if (findListOpen) findPaintList() }
$('fCase').onclick = findOpt(() => { findCase = !findCase; findSetToggle('fCase', findCase) })
$('fWord').onclick = findOpt(() => { findWord = !findWord; findSetToggle('fWord', findWord) })
$('fRe').onclick = findOpt(() => { findRe = !findRe; findSetToggle('fRe', findRe) })
$('fKeep').onclick = () => { findKeep = !findKeep; findSetToggle('fKeep', findKeep); findSaveOpts(); if (findListOpen) findPaintList(); $('fR').focus() }
$('fSel').onclick = () => {
  if (findScope()) setScope(null)
  else { const m = cm.state.selection.main; if (!m.empty) setScope({ from: m.from, to: m.to }) }
  markFind(false); $('fQ').focus()
}
$('fList').onclick = () => { findSetList(!findListOpen); $('fQ').focus() }
$('fTog').onclick = () => { setReplaceOpen(!findReplaceOpen); (findReplaceOpen ? $('fR') : $('fQ')).focus() }
$('fPrev').onclick = () => stepFind(-1)
$('fNext').onclick = () => stepFind(1)
$('fRep').onclick = () => doRep(false)
$('fAll').onclick = () => doRep(true)
$('fX').onclick = closeFind
$('fRes').addEventListener('click', e => {
  const el = e.target.closest('mark[data-i]') || e.target.closest('.fHit')
  if (!el) return
  findI = +el.dataset.i
  paintFind(true)
})
$('fRes').addEventListener('mousedown', e => e.preventDefault()) // keep focus in the query field
$('fR').addEventListener('keydown', e => {
  if (e.key !== 'Enter' || e.shiftKey || e.isComposing) return
  e.preventDefault(); e.stopPropagation()
  doRep((e.ctrlKey || e.metaKey) && e.altKey)
}, true)
$('find').addEventListener('keydown', e => {
  if (!e.altKey || e.ctrlKey || e.metaKey) return
  const k = e.key.toLowerCase(), code = e.code
  const act = { KeyC: 'fCase', KeyW: 'fWord', KeyR: 'fRe', KeyL: 'fSel', KeyP: 'fKeep' }[code]
  if (act) { e.preventDefault(); if (act !== 'fKeep' || findReplaceOpen) $(act).click(); return }
  if (e.target === $('fQ') && (k === 'arrowup' || k === 'arrowdown')) { e.preventDefault(); findHistStep(k === 'arrowup' ? 1 : -1) }
})
new ResizeObserver(() => { if (findOpen) findPaintRail() }).observe(cm.scrollDOM)
new ResizeObserver(() => { if (findOpen) findPad() }).observe($('find'))
document.querySelector('a[href="#cm"]')?.addEventListener('click', () => setTimeout(() => { try { cm.focus() } catch (e) {} }, 60)) // skip link: keyboard focus into editor, not just scroll
