// --- Find + replace: floating panel over the editor (Ctrl+F / Ctrl+H), hits as marks, Enter = next ---
// Options: match case, whole word, regex, find in selection. Extras: overview ticks beside the scrollbar,
// a clickable list of all matches with line context, and a per-tab search history (Alt+Up/Down).
let findOpen = false, findHits = [], findI = 0, findCase = false, findRe = false, findWord = false // hits are {a,b}
let findCapped = false, findReplaceOpen = false, findListOpen = false
let findWithTimer = 0, findWithN = 0, findHistI = -1, findPaintRaf = 0
const FIND_MAX = 5000 // counted + painted; the list shows the first FIND_LIST_MAX
const FIND_LIST_MAX = 300
const FIND_HIST_KEY = 'findHistory'
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

function findCounter() {
  const q = $('fQ').value, n = findHits.length, cap = findCapped ? '+' : ''
  const el = $('fN')
  el.classList.toggle('none', !!q && !n)
  if (!q) el.textContent = ''
  else if (!n) el.textContent = t('find.noResults')
  else el.textContent = (findI >= 0 ? (findI + 1) + '/' : '') + n + cap
}
function findMsg(text, ok = false) { $('fMsg').hidden = !text; $('fMsg').textContent = text || ''; $('fMsg').classList.toggle('ok', ok) }

function paintFind(sel) { // hits tinted, current one strong; sel = also jump
  cm.dispatch({ effects: setFind.of(RangeSet.of(findHits.map((h, i) =>
    Decoration.mark({ class: i === findI ? 'cm-find-cur' : 'cm-find' }).range(h.a, h.b)), true)) })
  if (sel && findHits.length && findI >= 0) {
    const h = findHits[findI]
    cm.dispatch({ selection: { anchor: h.a, head: h.b } })
    cmGlide(h.a)
  }
  findCounter()
  $('find').classList.toggle('none', !!$('fQ').value && !findHits.length && $('fMsg').hidden)
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

function findPaintList() { // every match with its line number and a bit of context; current one marked
  const box = $('fRes'), doc = cm.state.doc
  box.replaceChildren()
  const n = Math.min(findHits.length, FIND_LIST_MAX)
  for (let i = 0; i < n; i++) {
    const h = findHits[i], line = doc.lineAt(h.a)
    const row = document.createElement('button')
    row.type = 'button'; row.className = 'fHit' + (i === findI ? ' on' : '')
    row.setAttribute('role', 'option'); row.setAttribute('aria-selected', String(i === findI))
    row.dataset.i = i
    const ln = document.createElement('span'); ln.className = 'ln'; ln.textContent = line.number
    ln.title = t('find.line', { n: line.number })
    const tx = document.createElement('span'); tx.className = 'tx'
    const a = h.a - line.from, b = Math.min(h.b, line.to) - line.from
    const pre = line.text.slice(Math.max(0, a - 40), a), cut = a > 40
    tx.append((cut ? '…' : '') + pre.replace(/^\s+/, ''))
    const mk = document.createElement('mark'); mk.textContent = line.text.slice(a, b) || '⏎'
    tx.append(mk, line.text.slice(b, b + 80))
    row.append(ln, tx)
    box.append(row)
  }
  if (findHits.length > n) {
    const more = document.createElement('div'); more.className = 'fMore'
    more.textContent = t('find.more', { n: findHits.length - n + (findCapped ? '+' : '') })
    box.append(more)
  }
  box.hidden = !findHits.length
  const cur = box.querySelector('.fHit.on')
  if (cur) cur.scrollIntoView({ block: 'nearest' })
}
function findSetList(on) {
  findListOpen = on
  findSetToggle('fList', on); $('fList').setAttribute('aria-expanded', String(on))
  if (on) findPaintList()
  else { $('fRes').hidden = true; $('fRes').replaceChildren() }
}

function markFind(sel = true) { // sel=false: recount only, never steal selection/scroll (typing beside an open find)
  findHits = []; findI = -1; findCapped = false
  const q = $('fQ').value
  findMsg('')
  if (!q) { paintFind(false); return }
  const text = getT(), scope = findScope()
  const r = findCollect(text, q, scope ? scope.from : 0, scope ? scope.to : text.length)
  if (r.err) { // invalid pattern: say why in the panel, never throw
    cm.dispatch({ effects: setFind.of(RangeSet.of([])) })
    $('fN').textContent = '—'; $('fN').classList.add('none')
    findMsg(t('find.badRegex') + ' · ' + r.err); $('find').classList.add('none'); $('fRail').replaceChildren()
    if (findListOpen) { $('fRes').hidden = true }
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
  const q = $('fQ').value, r = $('fR').value
  if (!q || !findHits.length) return
  findHistPush(q)
  if (findI < 0 || findI >= findHits.length) { const hd = cm.state.selection.main.head; findI = findHits.findIndex(h => hd >= h.a && hd <= h.b); if (findI < 0) findI = findHits.findIndex(h => h.a >= hd); if (findI < 0) findI = 0 }
  const txt = getT()
  let rep = () => r
  if (findRe) { // regex replace: $1 / $<name> groups supported (lookbehind across hit edges unsupported: silent no-op)
    let one
    try { one = new RegExp('^(?:' + q + ')$', (findCase ? '' : 'i') + 's') } catch (e) { return }
    rep = h => txt.slice(h.a, h.b).replace(one, r)
  }
  const n = findHits.length
  if (all) cm.dispatch({ changes: findHits.map(h => ({ from: h.a, to: h.b, insert: rep(h) })) })
  else { const h = findHits[findI], ins = rep(h); cm.dispatch({ changes: { from: h.a, to: h.b, insert: ins }, selection: { anchor: h.a + ins.length } }) }
  markFind() // onEdit recounts anyway, here at once for the counter (and to land on the next hit)
  if (all) findMsg(t('find.replaced', { n }), true)
}

// Wiring
$('fQ').oninput = () => { findHistI = -1; markFind(true) }
$('fCase').onclick = () => { findCase = !findCase; findSetToggle('fCase', findCase); markFind(); $('fQ').focus() }
$('fWord').onclick = () => { findWord = !findWord; findSetToggle('fWord', findWord); markFind(); $('fQ').focus() }
$('fRe').onclick = () => { findRe = !findRe; findSetToggle('fRe', findRe); markFind(); $('fQ').focus() }
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
  const row = e.target.closest('.fHit')
  if (!row) return
  findI = +row.dataset.i
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
  const act = { KeyC: 'fCase', KeyW: 'fWord', KeyR: 'fRe', KeyL: 'fSel' }[code]
  if (act) { e.preventDefault(); $(act).click(); return }
  if (e.target === $('fQ') && (k === 'arrowup' || k === 'arrowdown')) { e.preventDefault(); findHistStep(k === 'arrowup' ? 1 : -1) }
})
new ResizeObserver(() => { if (findOpen) findPaintRail() }).observe(cm.scrollDOM)
document.querySelector('a[href="#cm"]')?.addEventListener('click', () => setTimeout(() => { try { cm.focus() } catch (e) {} }, 60)) // skip link: keyboard focus into editor, not just scroll
