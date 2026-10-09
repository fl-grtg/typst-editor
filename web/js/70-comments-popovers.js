// --- Inline comments: select -> card at line ---
const cols = ['#c2410c', '#059669', '#7c3aed', '#0369a1', '#be123c', '#a16207', '#0f766e', '#4338ca', '#b91c1c', '#15803d', '#9333ea', '#0e7490'] // AA on white + dark
const colOf = n => cols[[...n].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7) % cols.length]
const relPos = p => Y.relativePositionToJSON(Y.createRelativePositionFromTypeIndex(ytext, p)) // sticks to text, not to an index
function absPos(j) { // peer pos -> index (legacy clients send plain numbers)
  if (typeof j === 'number') return j
  if (!j || !ydoc) return null
  try { const a = Y.createAbsolutePositionFromRelativePosition(Y.createRelativePositionFromJSON(j), ydoc); return a ? a.index : null } catch (e) { return null }
}
let lastPres = ''
function pushPresence() { // u/sel always (online dot), active only on editor focus (cursor bar)
  if (!prov || !prov.awareness || !ytext) return
  const m = cm.state.selection.main
  const inMain = !activeFile && !tplName // file tab: positions would point into main.typ
  const active = inMain && cm.hasFocus && document.hasFocus()
  const st = { u: { name: user, color: colOf(user || '?') }, sel: inMain ? { a: relPos(m.anchor), h: relPos(m.head) } : null, active: !!active }
  const key = JSON.stringify(st)
  if (key === lastPres) return // no duplicate broadcasts per keystroke
  lastPres = key
  prov.awareness.setLocalState({ ...(prov.awareness.getLocalState() || {}), ...st }) // one update, not three
}
function renderPeers() { // bar only when editor active, dot for all online in doc (hover = name)
  if (!prov || !prov.awareness) return
  const rs = [], dots = $('peers')
  dots.replaceChildren()
  const mkDot = (n, c, me) => {
    const s = document.createElement('span'); s.className = 'dot'; s.setAttribute('role', 'listitem')
    s.style.background = avBg(n, c); s.title = me ? t('comments.peerSelf', { name: n }) : n; s.setAttribute('aria-label', me ? t('comments.peerSelf', { name: n }) : n)
    s.style.display = 'inline-flex'; s.style.alignItems = 'center'; s.style.justifyContent = 'center'
    s.style.fontSize = '9px'; s.style.fontWeight = '700'; s.style.color = '#fff'
    s.textContent = (n || '?').slice(0, 2).toUpperCase()
    return s
  }
  dots.appendChild(mkDot(user || '?', colOf(user || '?'), true)) // own blob first
  for (const [id, st] of prov.awareness.getStates()) {
    if (id === prov.awareness.clientID) continue
    const c = (st.u && st.u.color) || '#ff5f57', n = (st.u && st.u.name) || '?'
    dots.appendChild(mkDot(n, c, false))
    if (!st.active || !st.sel || activeFile || tplName) continue // file tab shows other text: no ghost carets
    const len = cm.state.doc.length, h = absPos(st.sel.h)
    if (h == null) continue
    const p = Math.max(0, Math.min(len, h)), an = absPos(st.sel.a)
    if (an != null && an !== h) { // peer selection: tinted range in their color
      const from = Math.max(0, Math.min(len, Math.min(an, h))), to = Math.max(0, Math.min(len, Math.max(an, h)))
      if (to > from) rs.push(Decoration.mark({ class: 'peerSel', attributes: { style: 'background-color:' + c + '2e' } }).range(from, to))
    }
    rs.push(Decoration.widget({ widget: new PeerCaret(c, n), side: 1 }).range(p))
  }
  cm.dispatch({ effects: setPeer.of(RangeSet.of(rs, true)) }) // true: CM sorts marks + widgets
}
cm.dom.addEventListener('focusin', pushPresence)
cm.dom.addEventListener('focusout', () => { pushPresence(); renderPeers() })
addEventListener('blur', pushPresence)
addEventListener('focus', () => { pushPresence(); renderPeers() })
document.addEventListener('visibilitychange', () => { pushPresence(); renderPeers() })
function ago(iso) {
  const m = Math.max(0, (Date.now() - new Date(iso)) / 60000)
  if (m < 1) return t('comments.agoNow')
  if (m < 60) return t('comments.agoMin', { n: m | 0 })
  if (m < 1440) return t('comments.agoHour', { n: m / 60 | 0 })
  const d = m / 1440 | 0; return d === 1 ? t('comments.agoDayOne') : t('comments.agoDays', { n: d })
}
const el = (tag, cls, text) => {
  const d = document.createElement(tag)
  if (cls) d.className = cls
  if (text !== undefined) d.textContent = text
  return d
}
function kb(row, fn) { // rows via keyboard: Tab in, Enter/Space opens (minis via :focus-within)
  if (!row.hasAttribute('role')) row.setAttribute('role', 'button') // folders/rows: role even if caller forgot
  row.tabIndex = 0
  row.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fn() } }
  return row
}
let askRes = null // open modal: new ask resolves old with null (no hanging promise)
function modalInert(on) { // background not focusable while dialog open (no inert attr in old browsers: fallback aria-hidden)
  const a = $('app')
  if (!a) return
  if (on) { a.setAttribute('inert', ''); a.setAttribute('aria-hidden', 'true') }
  else { a.removeAttribute('inert'); a.removeAttribute('aria-hidden') }
}
function ask(head, o = {}) { // custom modal not prompt/confirm (string|null, no input: true/false)
  const { value = '', ph = '', ok = t('common.ok'), danger = false, noInput = false } = o
  return new Promise(res => {
    if (askRes) askRes(null)
    askRes = res
    const prev = document.activeElement
    const ov = $('modal'); ov.style.display = 'flex'; modalInert(true)
    document.querySelector('#mCard .mRow').style.display = '' // show again after askPick
    $('mYes').style.display = '' // show again after askPick (Cancel stays visible there)
    $('mHead').textContent = head
    const inp = $('mInp'); inp.style.display = noInput ? 'none' : ''
    inp.value = noInput ? '' : value; inp.placeholder = ph; inp.setAttribute('aria-label', ph || head)
    if (o.maxLen) inp.setAttribute('maxlength', o.maxLen); else inp.removeAttribute('maxlength')
    const yes = $('mYes'); yes.textContent = ok
    yes.style.background = danger ? 'var(--danger)' : ''; yes.style.color = danger ? '#fff' : ''
    const done = v => { ov.style.display = 'none'; modalInert(false); askRes = null; if (prev && prev.classList && prev.classList.contains('mini')) prev.blur(); else prev?.focus?.(); res(v) }
    $('mNo').onclick = () => done(noInput ? false : null)
    yes.onclick = () => done(noInput ? true : inp.value)
    inp.onkeydown = e => { if (e.key === 'Enter') yes.onclick() }
    setTimeout(() => (noInput ? yes : inp).focus(), 30)
  })
}
const STARTERS = [ // starters: blank, report, slides for New
  '',
  '#set page(paper: "a4", margin: 2cm)\n#set text(size: 11pt)\n#set heading(numbering: "1.")\n\n= Introduction\n\nText here …\n',
  '#set page(paper: "presentation-16-9", margin: 1.5cm)\n#set text(size: 20pt)\n\n= Slide 1\n\n- First point\n- Second point\n\n= Slide 2\n\nText here …\n',
]
function askPick(head, opts) { // choice cards in modal (index|-1), opts: [title, desc]
  return new Promise(res => {
    if (askRes) askRes(null)
    const prev = document.activeElement
    const ov = $('modal'); ov.style.display = 'flex'; modalInert(true)
    const card = $('mCard')
    $('mHead').textContent = head
    const top = document.createElement('div'); top.className = 'mTop' // title + Cancel on one row
    card.insertBefore(top, $('mHead')); top.appendChild($('mHead'))
    const cx = document.createElement('button'); cx.textContent = t('common.cancel'); cx.setAttribute('aria-label', t('common.cancel'))
    top.appendChild(cx)
    $('mInp').style.display = 'none'
    const row = document.querySelector('#mCard .mRow')
    row.style.display = 'none' // Cancel lives in the header row in pick mode
    $('mYes').style.display = 'none' // no OK in pick mode: cards decide
    const box = document.createElement('div')
    const done = v => {
      ov.style.display = 'none'; modalInert(false); card.insertBefore($('mHead'), top); top.remove()
      row.style.display = ''; $('mYes').style.display = ''; box.remove(); askRes = null; if (prev && prev.classList && prev.classList.contains('mini')) prev.blur(); else prev?.focus?.(); res(v)
    }
    askRes = () => done(-1)
    opts.forEach((o, i) => {
      const b = document.createElement('button')
      b.className = 'pk'
      const tx = document.createElement('span'); tx.className = 'pkTx'
      tx.append(el('b', null, o[0]), el('span', null, o[1]))
      b.append(tx)
      b.onclick = () => done(i)
      box.appendChild(b)
    })
    $('mCard').appendChild(box)
    $('mNo').onclick = () => done(-1)
    cx.onclick = () => done(-1) // visible Cancel; mNo stays wired for Esc/outside-click
    setTimeout(() => box.querySelector('button')?.focus(), 30) // initial focus like ask(); Esc closes globally via mNo
  })
}
$('modal').onclick = e => { if (e.target === $('modal')) $('mNo').click() } // click outside = cancel
$('modal').addEventListener('keydown', e => { // minimal focus trap: Tab cycles in card
  if (e.key !== 'Tab') return
  const f = [...$('mCard').querySelectorAll('button,input,select')].filter(x => !x.disabled && x.getClientRects().length) // visible only: hidden mYes/mInp excluded
  if (!f.length) return
  const i = f.indexOf(document.activeElement)
  if (e.shiftKey && i <= 0) { e.preventDefault(); f[f.length - 1].focus() }
  else if (!e.shiftKey && (i < 0 || i === f.length - 1)) { e.preventDefault(); f[0].focus() }
})
// clean SVG icons (no emojis)
const svgI = d => `<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`
const ICO_DUP = svgI('<rect x="5.5" y="5.5" width="8" height="8" rx="1.8"/><path d="M10.5 3.5v-.2A1.8 1.8 0 0 0 8.7 1.5H3.8a1.8 1.8 0 0 0-1.8 1.8v4.9a1.8 1.8 0 0 0 1.8 1.8h.2"/>')
const ICO_EDIT = svgI('<path d="M11.5 2.5l2 2L5 13l-2.5.5L3 11z"/>')
const ICO_X = svgI('<path d="M4 4l8 8M12 4l-8 8"/>')
const ICO_UNDO = svgI('<path d="M6 3.5L3 6.5l3 3"/><path d="M3.5 6.5h5.8a3.2 3.2 0 0 1 0 6.4H7"/>')
const ICO_PLUS = svgI('<path d="M8 3v10M3 8h10"/>')
const ICO_CHECK = svgI('<path d="M3.5 8.5l3 3 6-7"/>')
const ICO_SEND = svgI('<path d="M8 13V3"/><path d="M4 7l4-4 4 4"/>')
const icoBtn = (cls, svg) => { const b = el('button', cls); b.innerHTML = svg; return b }
const ICO_TRASH = '<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 4h11"/><path d="M6.5 4V2.5h3V4"/><path d="M4 4l.7 9.5h6.6L12 4"/><path d="M6.5 6.8v3.7M9.5 6.8v3.7"/></svg>'
function paintOutline() { // collect = lines, click jumps to line
  const box = $('ol')
  if (!box) return
  box.replaceChildren()
  if (!docId || tplName) return
  getT().split('\n').forEach((ln, i) => {
    const m = ln.match(/^(=+)\s+(.+)$/)
    if (!m) return
    const line = i + 1, d = document.createElement('div')
    d.className = 'doc ol-l' + Math.min(m[1].length, 3)
    d.setAttribute('role', 'button')
    d.appendChild(el('span', 't', m[2].slice(0, 60)))
    d.title = t('docs.olLineTitle', { n: line })
    d.setAttribute('aria-label', t('docs.olGoTo', { line, text: m[2].slice(0, 60) }))
    const goL = () => {
      const p = posOfLine(getT(), line)
      cm.dispatch({ selection: { anchor: p }, effects: EditorView.scrollIntoView(p, { y: 'center' }) })
      cm.focus()
    }
    d.onclick = goL
    kb(d, goL)
    box.appendChild(d)
  })
  if (!box.hasChildNodes()) box.appendChild(el('div', 'empty', t('docs.olEmpty')))
}
function wc() { // word count for #save display
  const txt = getT().trim()
  if (!txt) return ''
  const n = txt.split(/\s+/).length
  return n === 1 ? t('docs.wordsOne') : t('docs.wordsMany', { n })
}
function updPos() { // F24 status: Ln/Col + words + sync (no aria-live: no SR spam per keystroke)
  const p = $('pos')
  if (!p) return
  let ln = 1, col = 1
  try { const l = cm.state.doc.lineAt(cm.state.selection.main.head); ln = l.number; col = cm.state.selection.main.head - l.from + 1 } catch (e) {}
  p.textContent = t('docs.posLine', { ln, col }) + (wc() || '') + t('docs.syncState', { state: syncOn ? t('docs.syncOn') : t('docs.syncOff') })
}
function openTutorial() { // help = tutorial doc (backend creates per account)
  const t = lastOwn.find(x => x.title === 'Tutorial')
  if (t) openDoc(t.id)
  else window.open('https://github.com/fl-grtg/typst-editor', '_blank', 'noopener')
}
function paintEmpty() { // onboarding card instead of pick-left note
  const card = el('div'); card.id = 'emptyCard'
  card.appendChild(el('h2', null, t('docs.emptyTitle')))
  card.appendChild(el('p', 'sub', t('docs.emptySub')))
  ;[t('docs.emptyS1'), t('docs.emptyS2'), t('docs.emptyS3')].forEach((s, i) => {
    const st = el('div', 'step')
    st.appendChild(el('span', 'n', String(i + 1)))
    st.appendChild(el('span', null, s))
    card.appendChild(st)
  })
  const cta = el('div', 'ctaRow')
  const nb = el('button', 'primary', t('docs.emptyNew')); nb.id = 'emptyNew'
  const tb = el('button', 'ghost', t('docs.emptyTut')); tb.id = 'emptyTut'
  cta.append(nb, tb); card.appendChild(cta)
  const hint = el('p', 'hint')
  hint.appendChild(el('kbd', null, '?'))
  hint.append(document.createTextNode(' ' + t('docs.emptyHintHelp') + ' · '))
  hint.appendChild(el('kbd', null, t('docs.emptyKbdFind')))
  hint.append(document.createTextNode(' ' + t('docs.emptyHintFind') + ' · '))
  hint.appendChild(el('kbd', null, t('docs.emptyKbdSave')))
  hint.append(document.createTextNode(' ' + t('docs.emptyHintSave')))
  card.appendChild(hint)
  $('preview').replaceChildren(card)
  $('emptyNew').onclick = () => $('new').click()
  const tutGone = !lastOwn.some(x => x.title === 'Tutorial')
  if (tutGone) $('emptyTut').style.display = 'none'
  $('emptyTut').onclick = openTutorial
}
const lineOf = pos => getT().slice(0, pos).split('\n').length
function gutter() { // refresh markers: CM paints numbers itself (wrap-safe), only new marks need refresh
  let m = new Set()
  if (docId && !tplName && !activeFile) m = new Set(threads.map(x => x.anchor)) // file tab/template: no main markers (Fix #5)
  let same = m.size === marks.size
  if (same) for (const x of m) if (!marks.has(x)) { same = false; break }
  if (!same) {
    marks = m
    const rs = []
    for (const line of m) {
      if (line < 1 || line > cm.state.doc.lines) continue
      rs.push(new ThreadDot().range(cm.state.doc.line(line).from))
    }
    cm.dispatch({ effects: setMarks.of(RangeSet.of(rs, true)) })
  }
}
let popFresh = false, popQuote = '', popT = 0
function openPop(anchor, fresh, quote = '') {
  popAnchor = Math.max(1, +anchor || 1); popFresh = !!fresh; popQuote = quote || ''
  popT = Date.now() // opening click must not close at once
  hidePops() // only one popover at a time
  const pp = $('pop'); pp.classList.remove('errs'); pp.style.display = ''; pp.setAttribute('role', 'dialog')
  $('cNew').setAttribute('aria-expanded', 'true'); if (!$('cNew').getAttribute('aria-controls')) $('cNew').setAttribute('aria-controls', 'pop')
  renderPop()
  movePop()
}
function closePop(force) { if (!force && $('pop').classList.contains('errs') && $('pop').style.display !== 'none') return // error list: only its x closes it
  if ($('pop').contains(document.activeElement)) try { cm.focus() } catch (e) {}; popAnchor = null; $('pop').style.display = 'none'; const c = $('cNew'); if (c) c.setAttribute('aria-expanded', 'false'); const eb = $('eBadge'); if (eb) eb.setAttribute('aria-expanded', 'false') }
function hidePops() { // close all header popups (share/tpl/history/symbols/settings + export menu)
  if (window.closeMenu) window.closeMenu(false)
  for (const p of ['sharePop', 'tplPop', 'histPop', 'symPop', 'setPop']) { const b = $(p); if (b && b.style.display !== 'none') { b.style.display = 'none'; const btn = $(POP_BTN[p]); if (btn) { btn.setAttribute('aria-expanded', 'false'); if (b.contains(document.activeElement)) try { btn.focus() } catch (e) {} } } }
}
const POP_BTN = { sharePop: 'shareBtn', tplPop: 'tplBtn', histPop: 'histBtn', symPop: 'symBtn', setPop: 'who' }
function showPop(id) { // toggle one popup, close rest (one helper not 5 blocks)
  const p = $(id), open = p.style.display === 'none'
  hidePops(); closePop(true) // only one popover at a time (header or comment card)
  p.style.display = open ? '' : 'none'
  const btn = $(POP_BTN[id])
  if (btn) { btn.setAttribute('aria-expanded', String(open)); if (!btn.getAttribute('aria-controls')) btn.setAttribute('aria-controls', id) }
  if (open) {
    p.setAttribute('role', 'dialog')
    if (!p.getAttribute('aria-label')) p.setAttribute('aria-label', { sharePop: t('share.title'), tplPop: t('templates.title'), histPop: t('history.title'), symPop: t('symbols.title'), setPop: t('settings.title') }[id] || id)
    anchorPop(p, btn) // under trigger, clamped to viewport (no fixed left:8px)
    const f = p.querySelector('input,select,textarea') || p.querySelector('button') // input first, never ✕
    if (f) setTimeout(() => { try { f.focus() } catch (e) {} }, 30)
  }
  return open
}
function anchorPop(p, btn) { // popover under its trigger: getBoundingClientRect, clamped (no framework)
  try {
    if (!btn || !p.offsetParent) return
    const r = btn.getBoundingClientRect(), pr = p.offsetParent.getBoundingClientRect()
    const w = p.offsetWidth || 300
    const left = Math.max(8, Math.min(r.left - pr.left, pr.width - w - 8))
    p.style.left = left + 'px'
    if (p.id !== 'setPop') p.style.maxHeight = '70vh' // settings never scrolls: card grows with content
  } catch (e) {}
}
function movePop() { // attach card to line (real coords, wrap-safe)
  const p = Math.min(getT().length, posOfLine(getT(), popAnchor))
  const r = cm.coordsAtPos(p), w = $('editWrap').getBoundingClientRect()
  const top = (r ? r.top - w.top : 8) + 4
  const max = $('editWrap').clientHeight - $('pop').offsetHeight - 8
  $('pop').style.top = Math.max(8, Math.min(top, Math.max(8, max))) + 'px'
}
function renderPop() {
  const pop = $('pop'); pop.replaceChildren()
  const bar = el('div', 'bar') // fixed header: X overlaps nothing
  bar.append(el('b', null, t('comments.lineHead', { n: popAnchor })))
  const x = icoBtn('ib', ICO_X); x.title = t('common.close'); x.setAttribute('aria-label', x.title); x.onclick = closePop
  bar.appendChild(x); pop.appendChild(bar)
  const list = threads.filter(t => t.anchor === popAnchor)
  const roC = docRole === 'reviewer' || openedTrashed // cNew logic: reviewer/trash read, not write
  if ((popFresh || !list.length) && !roC) {
    pop.appendChild(newBox())
    document.getElementById('popNew')?.focus()
  }
  list.forEach(t => pop.appendChild(threadCard(t)))
}
function newBox() { // only for new threads, not under done ones
  const box = el('div', 'nw'), row = el('div', 'rr')
  const inp = el('input'); inp.id = 'popNew'; inp.placeholder = t('comments.newPh'); inp.setAttribute('aria-label', t('comments.newAria'))
  wireMentions(inp)
  const ok = icoBtn('ib', ICO_SEND); ok.title = t('comments.send'); ok.setAttribute('aria-label', ok.title)
  const post = () => { if (!inp.value.trim() || ok.disabled) return; ok.disabled = true
    api('POST', `/api/docs/${docId}/comments`,
    { anchor: popAnchor, text: inp.value, quote: popQuote }).then(() => { popFresh = false; popQuote = ''; refresh(''); closePop() }).catch(e => toast(e.message)).finally(() => ok.disabled = false) }
  ok.onclick = post; inp.onkeydown = e => { if (e.key === 'Enter') post() }
  row.append(inp, ok); box.appendChild(row)
  return box
}
function threadCard(th) {
  const d = el('div', 'th')
  if (th.resolved) d.style.opacity = '.55' // done: faded, stays readable
  const hd = el('div', 'hd')
  const nm = el('b', 'nm', th.author || th.username); nm.style.color = colOf(th.username)
  hd.append(nm, el('span', 'tm', ago(th.created_at)))
  const roC = docRole === 'reviewer' || openedTrashed // cNew logic reused: reviewer gets no buttons
  if (!roC) { // trash/reviewer: no buttons, read only
    const fin = icoBtn('ib', th.resolved ? ICO_UNDO : ICO_CHECK); fin.title = th.resolved ? t('comments.reopen') : t('comments.done'); fin.setAttribute('aria-label', fin.title)
    fin.onclick = () => api('POST', `/api/docs/${docId}/comments/${th.id}/resolve`, { resolved: !th.resolved }).then(() => refresh(''))
    hd.appendChild(fin)
  }
  if (th.username === user && !openedTrashed) { // only author edits (owner deletes)
    const ed = icoBtn('ib', ICO_EDIT); ed.title = t('comments.edit'); ed.setAttribute('aria-label', ed.title)
    ed.onclick = async () => {
      const v = await ask(t('comments.editHead'), { value: th.text })
      if (v !== null && v.trim()) api('POST', `/api/docs/${docId}/comments/${th.id}/edit`, { text: v }).then(() => refresh(''))
    }
    hd.appendChild(ed)
  }
  const del = el('button', 'ib'); del.innerHTML = ICO_TRASH; del.style.marginLeft = 'auto'; del.title = t('comments.delThread'); del.setAttribute('aria-label', del.title)
  del.onclick = () => api('DELETE', `/api/docs/${docId}/comments/${th.id}`).then(() => refresh('').then(() => {
    if (!threads.some(x => x.anchor === popAnchor)) closePop()
  }))
  if (!roC) hd.appendChild(del)
  d.appendChild(hd)
  d.appendChild(richText(th.text))
  if (th.quote) { // show context, click jumps there
    const q = el('button', 'qt', '"' + (th.quote.length > 80 ? th.quote.slice(0, 80) + '…' : th.quote) + '"')
    q.title = t('comments.jumpPos')
    q.onclick = () => jumpThread(th)
    d.appendChild(q)
  }
  th.replies.forEach(r => {
    const rd = el('div', 'rp'), rh = el('div', 'hd')
    const rn = el('b', 'nm', r.author || r.username); rn.style.color = colOf(r.username)
    rh.append(rn, el('span', 'tm', ago(r.created_at)))
    rd.append(rh, richText(r.text)); d.appendChild(rd)
  })
  const row = el('div', 'rr')
  if (!roC) { // trash/reviewer: read, not write (cNew logic)
    const inp = el('input'); inp.id = 'r_' + th.id; inp.placeholder = t('comments.replyPh'); inp.setAttribute('aria-label', t('comments.replyAria'))
    wireMentions(inp)
    const ok = icoBtn('ib', ICO_SEND); ok.title = t('comments.send'); ok.setAttribute('aria-label', ok.title)
    const send = () => { if (!inp.value.trim() || ok.disabled) return; ok.disabled = true
      const text = inp.value; inp.value = '' // clear first: else loadComments keeps it as draft and skips renderPop
      api('POST', `/api/docs/${docId}/comments`,
      { anchor: th.anchor, text, parent_id: th.id }).then(() => refresh('r_' + th.id)).catch(e => { inp.value = text; toast(e.message) }).finally(() => ok.disabled = false) }
    ok.onclick = send; inp.onkeydown = e => { if (e.key === 'Enter') send() }
    row.append(inp, ok)
  }
  d.appendChild(row)
  return d
}
async function loadComments(force) {
  const d = await api('GET', `/api/docs/${docId}/comments`)
  const s = JSON.stringify(d.comments)
  if (s === lastC) return // poll: nothing new, keep inputs untouched
  lastC = s; threads = d.comments
  for (const t of threads) t.anchor = Math.max(1, +t.anchor || 1) // heal legacy anchor 0 -> 1
  if (!activeFile) { initRanges(); reanchor(); gutter(); refreshHl() } // file tab: do not touch main anchors (Fix #4/#5)
  paintBadge()
  const draft = [...$('pop').querySelectorAll('input')].some(i => i.value.trim())
  if (popAnchor != null && !draft && (force || !$('pop').contains(document.activeElement))) renderPop() // draft + blur: keep text
}
function paintBadge() { // count open threads, click jumps to next
  const b = $('cBadge'), open = threads.filter(t => !t.resolved)
  if (!docId || !open.length) { b.style.display = 'none'; return }
  b.style.display = ''
  b.textContent = t('comments.openBadge', { n: open.length })
}
$('cBadge').onclick = () => {
  const open = threads.filter(t => !t.resolved)
  if (!open.length) return
  jumpThread(open[(open.findIndex(t => t.anchor === popAnchor) + 1) % open.length])
}
$('eBadge').onclick = showErrList
function reanchor() { // find quote: moves along; not found = keep old line, no delete
  const t = getT()
  if (!docId || !ytext || !t || activeFile) return // file tab: anchors belong to main (Fix #4)
  initRanges() // after sync: add ranges missing text at load
  let moved = false
  for (const th of threads) {
    if (!th.quote) continue
    const i = locateQuote(t, th.quote, th.anchor)
    if (i < 0) continue
    if (th.a == null || th.a >= th.b) { th.a = i; th.b = Math.min(t.length, i + th.quote.length) } // collapsed: refit
    const line = t.slice(0, i).split('\n').length
    if (line !== th.anchor) {
      th.anchor = line; th.a = i; th.b = Math.min(t.length, i + th.quote.length); moved = true
      dirtyAnchor(th)
    }
  }
  if (moved) { // refresh icon at once, not only on save
    gutter(); refreshHl()
    if (popAnchor != null) movePop()
  }
}
async function jumpThread(t) {
  if (activeFile) await switchTab('') // jump lives in main, not in file tab
  const doc = getT()
  let a = t.a ?? -1, b = t.b ?? -1
  if (a < 0 || b <= a || a > doc.length) { // fallback: find quote
    a = t.quote ? locateQuote(doc, t.quote, t.anchor) : -1
    if (a < 0) return
    b = Math.min(doc.length, a + t.quote.length)
  }
  b = Math.min(doc.length, b)
  cm.dispatch({ selection: { anchor: a, head: b },
    effects: EditorView.scrollIntoView(b, { y: 'center' }) })
  cm.focus()
}
async function refresh(focusId) {
  await loadComments(true)
  if (popAnchor != null && focusId) document.getElementById(focusId)?.focus()
}
function updCNewTip() {
  const m = cm.state.selection.main
  const tip = m && !m.empty ? t('comments.tipYes') : t('comments.tipNo')
  $('cNew').title = tip; $('cNew').setAttribute('aria-label', tip)
}
$('cNew').onclick = () => {
  if (!docId) return
  const m = cm.state.selection.main // save selected spot along
  openPop(lineOf(m.head), true, getT().slice(m.from, m.to).slice(0, QUOTE_MAX))
}
