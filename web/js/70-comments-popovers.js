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
  const inMain = !activeFile && !tplName && !window.suggestionDraft && !window.changeSession // file tab: positions would point into the document text
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
    s.title = me ? t('comments.peerSelf', { name: n }) : n; s.setAttribute('aria-label', me ? t('comments.peerSelf', { name: n }) : n)
    s.style.display = 'inline-flex'; s.style.alignItems = 'center'; s.style.justifyContent = 'center'
    s.style.fontSize = '9px'; s.style.fontWeight = '700'; s.style.color = '#fff'
    paintAvatar(s, n, c)
    return s
  }
  dots.appendChild(mkDot(user || '?', colOf(user || '?'), true)) // own blob first
  for (const [id, st] of prov.awareness.getStates()) {
    if (id === prov.awareness.clientID) continue
    const c = (st.u && st.u.color) || '#ff5f57', n = (st.u && st.u.name) || '?'
    dots.appendChild(mkDot(n, c, false))
    if (!st.active || !st.sel || activeFile || tplName || window.suggestionDraft || window.changeSession) continue // file tab shows other text: no ghost carets
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
  schedulePeerEdges()
}
// Off-screen collaborators: compact avatars at the editor edge while their caret is outside the viewport.
// Peers in view keep only their caret + label (no duplicate edge chip).
const EDGE_ICO = {
  top: '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 13V3"/><path d="M4 7l4-4 4 4"/></svg>',
  bottom: '<svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 3v10"/><path d="M4 9l4 4 4-4"/></svg>'
}
function edgeSide(p, rect) { // '' = same excerpt (caret visible), else the edge it sits beyond
  if (p < cm.viewport.from) return 'top' // outside the rendered range: only a clear distance counts
  if (p > cm.viewport.to) return 'bottom'
  const c = cm.coordsAtPos(p) // cheap only for the rendered range, not every peer in the room
  if (c) {
    if (c.top < rect.top - 2) return 'top'
    if (c.bottom > rect.bottom + 2) return 'bottom'
  }
  return ''
}
let edgeT = 0, edgeKey = ''
function edgeChip(box, id) { return [...box.querySelectorAll('button[data-peer]')].find(b => b.dataset.peer === String(id)) }
function clearEdge(box) { if (!box) return; for (const b of box.querySelectorAll('button[data-peer]')) b.remove(); box.style.display = 'none' }
function clearPeerEdges() { cancelAnimationFrame(edgeT); edgeT = 0; clearEdge($('peerTop')); clearEdge($('peerBottom')); edgeKey = '' }
function focusEdgeChip(id) { // keep keyboard focus on the same person across re-renders
  const btn = [...document.querySelectorAll('#peerTop button[data-peer], #peerBottom button[data-peer]')].find(b => b.dataset.peer === id)
  if (btn) { if (document.activeElement !== btn) btn.focus({ preventScroll: true }) }
  else cm.focus()
}
function renderPeerEdges() {
  edgeT = 0
  const boxes = { top: $('peerTop'), bottom: $('peerBottom') }
  const active = document.activeElement && document.activeElement.closest ? document.activeElement.closest('#peerTop button[data-peer], #peerBottom button[data-peer]') : null
  const keepFocus = active && active.dataset.peer
  if (!prov || !prov.awareness || !ytext || !docId || tplName || activeFile || openedTrashed || window.suggestionDraft || window.changeSession || $('cmWrap').hidden) { clearPeerEdges(); return }
  const len = cm.state.doc.length, lists = { top: [], bottom: [] }
  const rect = cm.scrollDOM.getBoundingClientRect() // one layout read per frame, not one per peer
  for (const [id, st] of prov.awareness.getStates()) {
    if (id === prov.awareness.clientID || !st.active || !st.sel) continue // same gate as the caret/label
    const h = absPos(st.sel.h)
    if (h == null) continue
    const p = Math.max(0, Math.min(len, h)), side = edgeSide(p, rect)
    if (!side) continue
    lists[side].push({ id, p, n: (st.u && st.u.name) || '?', c: (st.u && st.u.color) || '#ff5f57' })
  }
  lists.top.sort((a, b) => b.p - a.p) // nearest to the viewport first
  lists.bottom.sort((a, b) => a.p - b.p)
  const key = ['top', 'bottom'].map(side => side + ':' + lists[side].map(x => x.id + ':' + x.p + ':' + x.n + ':' + x.c).join(',')).join('|')
  if (key === edgeKey) return // scroll inside the same excerpt: no DOM churn
  edgeKey = key
  for (const side of ['top', 'bottom']) {
    const box = boxes[side], list = lists[side]
    if (!list.length) { clearEdge(box); continue }
    box.setAttribute('aria-label', t(side === 'top' ? 'comments.peerEdgeAbove' : 'comments.peerEdgeBelow', { names: list.map(x => x.n).join(', ') }))
    if (!box.querySelector('.dir')) { const dir = el('span', 'dir'); dir.innerHTML = EDGE_ICO[side]; box.prepend(dir) }
    const ids = new Set()
    for (const x of list) {
      ids.add(String(x.id))
      let b = edgeChip(box, x.id)
      if (!b) { b = el('button'); b.type = 'button'; b.dataset.peer = String(x.id); b.appendChild(el('span', 'av')) }
      const title = t(side === 'top' ? 'comments.peerJumpAbove' : 'comments.peerJumpBelow', { name: x.n, line: cm.state.doc.lineAt(x.p).number })
      if (b.title !== title) { b.title = title; b.setAttribute('aria-label', title) }
      const sig = x.n + '|' + x.c
      if (b.dataset.sig !== sig) { b.dataset.sig = sig; paintAvatar(b.firstChild, x.n, x.c) }
      b.onclick = () => jumpPeer(x.id)
      box.appendChild(b) // keeps DOM order and reuses the button node
    }
    for (const b of box.querySelectorAll('button[data-peer]')) if (!ids.has(b.dataset.peer)) b.remove()
    box.style.display = 'flex'
  }
  if (keepFocus) focusEdgeChip(keepFocus) // position updates must never drop keyboard focus
}
function jumpPeer(id) { // edge chip: centre that peer, own selection stays put
  const st = prov && prov.awareness.getStates().get(id), h = st && st.sel && absPos(st.sel.h)
  if (h == null) return
  const p = Math.max(0, Math.min(cm.state.doc.length, h))
  cm.dispatch({ effects: EditorView.scrollIntoView(p, { y: 'center' }) })
  cm.focus()
}
function schedulePeerEdges() { if (!edgeT) edgeT = requestAnimationFrame(renderPeerEdges) } // scroll bursts: one paint per frame
cm.scrollDOM.addEventListener('scroll', schedulePeerEdges, { passive: true })
new ResizeObserver(schedulePeerEdges).observe(cm.scrollDOM)
new ResizeObserver(schedulePeerEdges).observe(cm.contentDOM) // editor font/split changes move the excerpt without a scroll event
cm.dom.addEventListener('focusin', () => queueMicrotask(pushPresence)) // focus moves during editor updates; awareness repaints dispatch, so wait until the update is done
cm.dom.addEventListener('focusout', () => queueMicrotask(() => { pushPresence(); renderPeers() }))
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
  row.onkeydown = e => { if (e.target === row && !e.ctrlKey && !e.metaKey && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); fn() } }
  return row
}
let askRes = null // open modal: new ask resolves old with null (no hanging promise)
function modalInert(on) { // background not focusable while dialog open (no inert attr in old browsers: fallback aria-hidden)
  const a = $('app')
  if (!a) return
  if (on) { a.setAttribute('inert', ''); a.setAttribute('aria-hidden', 'true') }
  else { a.removeAttribute('inert'); a.removeAttribute('aria-hidden') }
}
function ask(head, o = {}) { // custom modal not prompt/confirm (string|null, no input: true/false, o.alt: extra button -> 'alt')
  const { value = '', ph = '', ok = t('common.ok'), danger = false, noInput = false, body = null, stem = false, selectAll = false } = o
  return new Promise(res => {
    if (askRes) askRes(null)
    askRes = res
    const prev = document.activeElement
    const ov = $('modal'); ov.style.display = 'flex'; modalInert(true)
    document.querySelectorAll('#mCard .mBody').forEach(n => n.remove()) // one structured body at a time
    document.querySelector('#mCard .mRow').style.display = '' // show again after askPick
    $('mYes').style.display = '' // show again after askPick (Cancel stays visible there)
    $('mHead').textContent = head
    const inp = $('mInp'); inp.style.display = noInput ? 'none' : ''
    inp.value = noInput ? '' : value; inp.placeholder = ph; inp.setAttribute('aria-label', ph || head)
    if (body) $('mCard').insertBefore(body, inp)
    if (o.maxLen) inp.setAttribute('maxlength', o.maxLen); else inp.removeAttribute('maxlength')
    const yes = $('mYes'); yes.textContent = ok
    yes.disabled = false
    yes.style.background = danger ? 'var(--danger)' : ''; yes.style.color = danger ? '#fff' : ''
    const alt = o.alt ? el('button', 'mAlt', o.alt) : null
    if (alt) yes.before(alt)
    const done = v => { ov.style.display = 'none'; modalInert(false); askRes = null; body?.remove(); alt?.remove(); if (prev && document.contains(prev) && prev.classList && prev.classList.contains('mini')) prev.blur(); else if (prev && document.contains(prev)) prev?.focus?.(); res(v) }
    $('mNo').onclick = () => done(noInput ? false : null)
    if (alt) alt.onclick = () => done('alt')
    yes.onclick = () => done(noInput ? true : inp.value)
    inp.onkeydown = e => { if (e.key === 'Enter') yes.onclick() }
    if (noInput) yes.focus()
    else {
      inp.focus()
      if (selectAll) inp.select()
      else if (stem && value) inp.setSelectionRange(nameStemStart(value), nameStemEnd(value))
    }
  })
}
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
      row.style.display = ''; $('mYes').style.display = ''; box.remove(); askRes = null; if (prev && document.contains(prev) && prev.classList && prev.classList.contains('mini')) prev.blur(); else if (prev && document.contains(prev)) prev?.focus?.(); res(v)
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
let pickPopClose = null
function closePickPop() { if (pickPopClose) pickPopClose(-1) }
function pickPop(head, opts, anchor = null, o = {}) { // compact menu-style anchored picker (index|-1|'back'), no fullscreen blur
  closePickPop()
  return new Promise(res => {
    const prev = document.activeElement
    const pop = el('div'); pop.id = 'pickPop'; pop.tabIndex = -1
    pop.setAttribute('role', 'menu'); pop.setAttribute('aria-label', head)
    const top = el('div', 'pkHead')
    if (o.back) {
      const bk = el('button', 'pkBack', '←'); bk.type = 'button'; bk.title = t('common.back'); bk.setAttribute('aria-label', bk.title)
      bk.onclick = () => done('back')
      top.appendChild(bk)
    }
    top.appendChild(el('b', null, head))
    const list = el('div', 'pkList')
    opts.forEach((opt, i) => {
      const b = el('button', 'pkRow'); b.type = 'button'; b.setAttribute('role', 'menuitem')
      b.appendChild(el('b', null, opt[0]))
      if (opt[1]) b.appendChild(el('span', null, opt[1]))
      b.onclick = () => done(i)
      list.appendChild(b)
    })
    pop.append(top, list)
    document.body.appendChild(pop)
    const ref = anchor && anchor.getClientRects?.().length ? anchor : null
    const w = pop.offsetWidth || 200, h = pop.offsetHeight || 160
    let left = Math.round((innerWidth - w) / 2), topY = Math.min(88, Math.max(12, Math.round((innerHeight - h) / 3)))
    if (ref) {
      const r = ref.getBoundingClientRect()
      if (ref.closest?.('aside')) {
        left = r.right + 6 + w <= innerWidth - 8 ? r.right + 6 : Math.max(8, innerWidth - w - 8)
        topY = Math.max(8, Math.min(r.top, innerHeight - h - 8))
      } else {
        left = Math.max(8, Math.min(r.left, innerWidth - w - 8))
        topY = r.bottom + 4 + h <= innerHeight - 8 ? r.bottom + 4 : Math.max(8, r.top - h - 4)
      }
    }
    pop.style.left = left + 'px'; pop.style.top = topY + 'px'
    const onDown = e => { if (!pop.contains(e.target)) done(-1) }
    const onKey = e => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); done(-1); return }
      const btns = [...list.querySelectorAll('button')]
      if (!btns.length) return
      const cur = btns.indexOf(document.activeElement)
      if (e.key === 'ArrowDown') { e.preventDefault(); btns[(cur + 1 + btns.length) % btns.length].focus() }
      else if (e.key === 'ArrowUp') { e.preventDefault(); btns[(cur < 0 ? btns.length - 1 : (cur - 1 + btns.length) % btns.length)].focus() }
    }
    let closed = false
    const done = v => {
      if (closed) return; closed = true
      pickPopClose = null
      document.removeEventListener('mousedown', onDown, true)
      document.removeEventListener('keydown', onKey, true)
      pop.remove()
      if (v === -1 && prev && document.contains(prev)) try { prev.focus() } catch (e) {}
      res(v)
    }
    pickPopClose = done
    document.addEventListener('mousedown', onDown, true)
    document.addEventListener('keydown', onKey, true)
    setTimeout(() => pop.focus({ preventScroll: true }), 10)
  })
}
$('modal').onclick = e => { if (e.target === $('modal')) $('mNo').click() } // click outside = cancel
$('modal').addEventListener('keydown', e => { // minimal focus trap: Tab cycles in card
  if (e.key !== 'Tab') return
  const f = [...$('mCard').querySelectorAll('button,input,select,textarea,[tabindex]:not([tabindex="-1"])')].filter(x => !x.disabled && x.getClientRects().length) // visible only: hidden mYes/mInp excluded
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
const ICO_RESET = svgI('<path d="M2.8 6.2a5.4 5.4 0 1 1 .3 4.1"/><path d="M2.8 2.8v3.5h3.5"/>')
const ICO_PLUS = svgI('<path d="M8 3v10M3 8h10"/>')
const ICO_CHECK = svgI('<path d="M3.5 8.5l3 3 6-7"/>')
const ICO_SEND = svgI('<path d="M8 13V3"/><path d="M4 7l4-4 4 4"/>')
const ICO_PREV = svgI('<path d="M10 3.5L5.5 8 10 12.5"/>')
const ICO_NEXT = svgI('<path d="M6 3.5L10.5 8 6 12.5"/>')
const icoBtn = (cls, svg) => { const b = el('button', cls); b.innerHTML = svg; return b }
const ICO_TRASH = '<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 4h11"/><path d="M6.5 4V2.5h3V4"/><path d="M4 4l.7 9.5h6.6L12 4"/><path d="M6.5 6.8v3.7M9.5 6.8v3.7"/></svg>'
function paintOutline() { // collect = lines, click jumps to line; page badge from the PDF outline
  const box = $('ol')
  if (!box) return
  box.replaceChildren()
  const searching = searchOn()
  if (searching && !searchFilters.outline) return // area filtered out
  if (!docId || tplName) { // modules have no source outline: still explain an empty search result
    if (searching) box.appendChild(el('div', 'empty', t('docs.noHits')))
    return
  }
  let olAt = 0
  for (const h of srcHeadings(getT())) { // raw blocks/comments never contribute headings
    const line = h.line, d = document.createElement('div')
    const text = syncShow(h.title) || h.title.trim() // labels stay in the source, never in the sidebar
    if (searching && !searchMatch(text)) continue
    d.className = 'doc ol-l' + Math.min(h.level, 3)
    d.setAttribute('role', 'button')
    d.appendChild(searchTextEl('t', text.slice(0, 60)))
    d.title = t('docs.olLineTitle', { n: line })
    const hit = pvOlMatch(h.title, olAt, true) // badges keep the last outline during a re-render (no flicker)
    if (hit >= 0) { // real page from the last render: proves the heading made it onto paper
      olAt = hit + 1
      const page = pvOutline[hit].page + 1
      d.appendChild(el('span', 'pg', String(page)))
      d.title += ' · ' + t('docs.olPage', { n: page })
    }
    d.setAttribute('aria-label', t('docs.olGoTo', { line, text: text.slice(0, 60) }))
    const goL = () => cmJump(posOfLine(getT(), line), false, true) // smooth jump; preview follows even with follow off
    d.onclick = goL
    kb(d, goL)
    box.appendChild(d)
  }
  if (!box.hasChildNodes()) box.appendChild(el('div', 'empty', searching ? t('docs.noHits') : t('docs.olEmpty')))
}
function wc() { // word count for #pos display
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
  const words = !activeFile || TEXT_EXT.test(activeFile) // binary tabs show a placeholder, never a word count
  p.textContent = t('docs.posCompact', { ln, col }) + (words ? (wc() || '') : '')
  p.title = t('docs.posLine', { ln, col }) + t('docs.syncState', { state: syncOn ? t('docs.syncOn') : t('docs.syncOff') })
}
const lineOf = pos => getT().slice(0, pos).split('\n').length
function gutter() { // refresh markers: CM paints numbers itself (wrap-safe), only new marks need refresh
  let m = new Set()
  const suggestions = new Set()
  if (docId && !tplName && !activeFile) {
    const mapped = !!(window.suggestionDraft || window.changeSession)
    for (const th of threads) {
      const line = mapped ? cm.state.doc.lineAt(threadEditorRange(th).from).number : th.anchor
      m.add(line)
      if (th.suggestion_status === 'pending') suggestions.add(line)
    }
    if (window.suggestionDraft) for (const range of draftRanges(window.suggestionDraft)) {
      const line = cm.state.doc.lineAt(range.a).number
      m.add(line); suggestions.add(line)
    }
  } // file tab/template: no main markers
  if (window.changeSession && !window.changeSession.original) {
    const f = window.changeSession.files.get(sessionKey(sessionCurrent()))
    if (f && getT() === (f.content || '')) for (const range of sessionChangeRanges(f)) {
      const line = cm.state.doc.lineAt(range.a).number
      m.add(line); suggestions.add(line)
    }
  }
  const style = [...suggestions].sort().join(',')
  let same = m.size === marks.size && style === markStyle
  if (same) for (const x of m) if (!marks.has(x)) { same = false; break }
  if (!same) {
    marks = m; markStyle = style
    const rs = []
    for (const line of m) {
      if (line < 1 || line > cm.state.doc.lines) continue
      rs.push(new ThreadDot(suggestions.has(line)).range(cm.state.doc.line(line).from))
    }
    cm.dispatch({ effects: setMarks.of(RangeSet.of(rs, true)) })
  }
}
let popFresh = false, popT = 0, popLayoutTries = 0, popThreadId = null
const popDrafts = new Map()
function paintCardView() { $('cmWrap').classList.toggle('cardOpen', $('pop').style.display !== 'none') } // open card suppresses hover previews (CSS hides .cm-tooltip-hover)
function openPop(anchor, fresh, suggestion = null, focusId = null) {
  closePop(true)
  window.suggestionPopup = suggestion
  popAnchor = Math.max(1, Math.min(cm.state.doc.lines || 1, +anchor || 1)); popFresh = !!fresh
  popThreadId = focusId ? String(focusId) : null
  popLayoutTries = 0
  popT = Date.now() // opening click must not close at once
  hidePops() // only one popover at a time
  const pp = $('pop'); pp.replaceChildren(); pp.classList.remove('errs'); pp.style.display = ''; pp.tabIndex = -1; pp.setAttribute('role', 'dialog'); pp.setAttribute('aria-labelledby', 'commentPopTitle'); paintCardView()
  $('cNew').setAttribute('aria-expanded', 'true'); if (!$('cNew').getAttribute('aria-controls')) $('cNew').setAttribute('aria-controls', 'pop')
  renderPop()
  movePop()
}
function closePop(force) { if (!force && $('pop').classList.contains('errs') && $('pop').style.display !== 'none') return // error list: only its x closes it
  if ($('pop').contains(document.activeElement)) try { cm.focus() } catch (e) {}; popAnchor = null; popThreadId = null; popDrafts.clear(); window.suggestionPopup = null; cm.contentDOM.style.paddingTop = ''; $('pop').style.display = 'none'; const c = $('cNew'); if (c) c.setAttribute('aria-expanded', 'false'); const eb = $('eBadge'); if (eb) eb.setAttribute('aria-expanded', 'false'); paintCardView() }
const popTriggers = id => document.querySelectorAll(`[aria-controls="${id}"]`)
function closeHeaderPops(inside = null) { // inside: keep the popover holding this element (a row menu opened from it)
  for (const p of ['sharePop', 'tplPop', 'histPop', 'symPop', 'setPop', 'inboxPop', 'exportPop']) { const b = $(p); if (b && b.style.display !== 'none' && !(inside && b.contains(inside))) { b.style.display = 'none'; popTriggers(p).forEach(t => t.setAttribute('aria-expanded', 'false')); const btn = $(POP_BTN[p]); if (btn && b.contains(document.activeElement)) try { btn.focus() } catch (e) {} } }
}
function hidePops() { // close all header popups (share/tpl/history/symbols/settings + export menu)
  if (window.closeMenu) window.closeMenu(false)
  closePickPop()
  closeHeaderPops()
  if (typeof closeWatchBox === 'function') closeWatchBox()
}
window.closeFloatPanels = function (keep, inside) { // one floating panel at a time: menu, popover, comment card, watch menu
  if (keep !== 'watch' && typeof closeWatchBox === 'function') closeWatchBox()
  if (keep !== 'pop') closePop(true)
  if (keep !== 'menu' && window.closeMenu) window.closeMenu(false)
  closePickPop()
  closeHeaderPops(inside)
}
const POP_BTN = { sharePop: 'shareBtn', tplPop: 'insertMore', histPop: 'histBtn', symPop: 'insertMore', setPop: 'userMain', inboxPop: 'inboxBtn', exportPop: 'exportBtn' }
function showPop(id) { // toggle one popup, close rest (one helper not 5 blocks)
  const p = $(id), open = p.style.display === 'none'
  hidePops(); closePop(true) // only one popover at a time (header or comment card)
  p.style.display = open ? '' : 'none'
  const btn = $(POP_BTN[id])
  if (btn) btn.setAttribute('aria-controls', id) // trigger may have switched popovers (insertMore)
  popTriggers(id).forEach(t => t.setAttribute('aria-expanded', String(open)))
  if (open) {
    p.setAttribute('role', 'dialog')
    if (!p.getAttribute('aria-label')) p.setAttribute('aria-label', { sharePop: t('share.title'), tplPop: t('templates.title'), histPop: t('history.title'), symPop: t('symbols.title'), setPop: t('settings.title'), inboxPop: t('inbox.title'), exportPop: t('downloads.expTitle') }[id] || id)
    anchorPop(p, id === 'setPop' ? $('who') : btn) // settings stays anchored to the name; userMain is the trigger
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
function movePop() {
  const pop = $('pop')
  if (popAnchor == null || pop.classList.contains('errs')) return
  const text = getT(), selection = cm.state.selection.main
  const thread = threads.find(th => String(th.id) === popThreadId)
  const target = window.suggestionPopup || (popFresh && !selection.empty ? selection : thread && threadEditorRange(thread))
  const from = target?.from ?? posOfLine(text, popAnchor)
  const to = target?.to ?? from
  const r = $('editWrap').getBoundingClientRect(), editor = cm.scrollDOM.getBoundingClientRect()
  const first = cm.coordsAtPos(Math.min(from, text.length)), last = cm.coordsAtPos(Math.min(to, text.length))
  const boxes = (window.suggestionPopup?.nodes || []).filter(node => node.isConnected).map(node => node.getBoundingClientRect())
  if ($('cmWrap').hidden && boxes.length) {
    const anchor = boxes[0], above = Math.max(0, anchor.top - r.top - 8), below = Math.max(0, r.bottom - anchor.bottom - 8)
    const up = above > below, available = Math.max(above, below), height = Math.min(pop.scrollHeight, 360, available)
    pop.style.visibility = ''; pop.style.maxHeight = Math.max(40, Math.min(360, available)) + 'px'
    pop.style.top = Math.max(0, up ? anchor.top - r.top - height - 8 : anchor.bottom - r.top + 8) + 'px'
    pop.style.left = Math.max(8, Math.min(anchor.left - r.left, r.width - pop.offsetWidth - 8)) + 'px'
    return
  }
  const bounds = boxes.length ? { top: Math.min(...boxes.map(r => r.top)), bottom: Math.max(...boxes.map(r => r.bottom)) } : null
  const top = Math.min(first ? first.top : editor.top, bounds ? bounds.top : Infinity)
  const bottom = Math.max(last ? last.bottom : editor.bottom, bounds ? bounds.bottom : -Infinity)
  const above = Math.max(0, top - Math.max(r.top, editor.top) - 10)
  const below = Math.max(0, Math.min(r.bottom, editor.bottom) - bottom - 10)
  const wanted = Math.min(pop.scrollHeight, 360)
  const up = above >= wanted || (below < wanted && above >= below)
  const available = up ? above : below
  if (available < 90) {
    pop.style.visibility = 'hidden'
    if (++popLayoutTries > 3) return
    const padding = Math.min(360, Math.max(160, wanted)) + 24
    if (cm.contentDOM.style.paddingTop !== padding + 'px') {
      cm.contentDOM.style.paddingTop = padding + 'px'
      cm.dispatch({ effects: EditorView.scrollIntoView(Math.min(from, text.length), { y: 'start', yMargin: padding }) })
      requestAnimationFrame(() => { pvSelfWrite(cm.scrollDOM); movePop() }) // placement, not a reader scroll
    } else if (!first || first.top < editor.top + 90) {
      cm.scrollDOM.scrollTop = Math.max(0, cm.lineBlockAt(Math.min(from, text.length)).top - padding)
      pvSelfWrite(cm.scrollDOM) // popover placement is no reader scroll
      requestAnimationFrame(movePop)
    }
    return
  }
  popLayoutTries = 0
  pop.style.visibility = ''
  pop.style.maxHeight = Math.min(360, available) + 'px'
  const height = Math.min(pop.scrollHeight, available, 360)
  pop.style.top = (up ? top - r.top - height - 10 : bottom - r.top + 10) + 'px'
  pop.style.left = Math.max(8, Math.min((first ? first.left : r.left + 56) - r.left, r.width - pop.offsetWidth - 8)) + 'px'
}
function paintPopItems(items) {
  if (!items.length) return
  const pop = $('pop')
  const idx = Math.max(0, items.findIndex(it => it.id === popThreadId))
  popThreadId = items[idx].id
  if (items.length > 1) {
    const nav = el('span', 'popNav')
    const button = (step, icon, label) => {
      const b = icoBtn('ib', icon)
      b.title = label; b.setAttribute('aria-label', label)
      b.onclick = e => {
        e.stopPropagation()
        popThreadId = items[(idx + step + items.length) % items.length].id
        renderPop()
        pop.querySelectorAll('.popNav button')[step < 0 ? 0 : 1]?.focus()
      }
      return b
    }
    nav.append(button(-1, ICO_PREV, t('comments.previousThread')), el('span', 'popStep', `${idx + 1} / ${items.length}`), button(1, ICO_NEXT, t('comments.nextThread')))
    pop.querySelector('.barActs').prepend(nav)
  }
  pop.append(items[idx].render())
}
function renderPop() {
  const pop = $('pop')
  for (const input of pop.querySelectorAll('input[data-comment-draft]')) {
    if (input.value) popDrafts.set(input.id, input.value)
    else popDrafts.delete(input.id)
  }
  pop.replaceChildren()
  if (popAnchor != null) popAnchor = Math.max(1, Math.min(cm.state.doc.lines || 1, popAnchor)) // doc shrank while open: never address a dead line
  const bar = el('div', 'bar') // fixed header: X overlaps nothing
  const title = el('span', 'barTitle'); title.id = 'commentPopTitle'
  title.append(el('b', null, window.suggestionPopup?.label || t('comments.lineHead', { n: popAnchor })))
  const barActs = el('span', 'barActs')
  const x = icoBtn('ib', ICO_X); x.title = t('common.close'); x.setAttribute('aria-label', x.title); x.onclick = closePop
  bar.append(title, barActs); pop.appendChild(bar)
  requestAnimationFrame(movePop)
  if (window.suggestionPopup) { barActs.appendChild(x); if (window.suggestionPopup.session) sessionCard(window.suggestionPopup); else renderSuggestionBox(window.suggestionPopup); return }
  const line = cm.state.doc.line(popAnchor)
  const list = threads.filter(th => {
    if (String(th.id) === popThreadId) return true
    if (th.a == null || th.b == null) return th.anchor === popAnchor
    const r = threadEditorRange(th)
    return r.to > r.from ? (r.from < line.to && r.to > line.from) : (r.from >= line.from && r.from <= line.to)
  })
  const roC = openedTrashed
  if ((popFresh || !list.length) && !roC) {
    barActs.appendChild(x)
    pop.appendChild(newBox())
    document.getElementById('popNew')?.focus()
    return
  }
  barActs.appendChild(x)
  paintPopItems(list.map(th => ({ id: String(th.id), render: () => threadCard(th) })))
}
function visibleSelectionQuote(from, to) { // reflect proposed text in quotes: deleted draft spans stay out, live pending suggestions use their replacement
  const txt = getT()
  if (window.changeSession || window.suggestionDraft) return txt.slice(from, to).slice(0, 500)
  const pending = threads.filter(th => th.suggestion_status === 'pending' && !th.conflict && th.a != null && th.b != null)
    .map(th => {
      const span = tokenSafeSpan(th.suggestion_old, diffSpan(th.suggestion_old, th.replacement))
      const a = Math.min(th.b, th.a + span.a), b = Math.max(a, th.b - span.b)
      return { a, b, next: th.replacement.slice(span.a, th.replacement.length - span.b) }
    })
    .filter(s => s.a >= from && s.b <= to)
    .sort((x, y) => x.a - y.a)
  if (!pending.length) return txt.slice(from, to).slice(0, 500)
  let out = '', cur = from
  for (const s of pending) {
    if (s.a < cur) continue
    out += txt.slice(cur, s.a) + s.next
    cur = s.b
  }
  return (out + txt.slice(cur, to)).slice(0, 500)
}
function newBox() {
  const doc = docId, epoch = openN, session = window.changeSession, suggestion = window.suggestionDraft
  const pkg = commentPackage(), draft = pkg ? session : null
  const selection = popFresh ? cm.state.selection.main : null
  const target = selection ? { from: selection.from, to: selection.to } : { from: cm.state.doc.line(popAnchor).from, to: cm.state.doc.line(popAnchor).from }
  const live = !pkg && (session || suggestion)
  const from = live ? editorToSource(target.from) : target.from
  const to = live ? editorToSource(target.to, true) : target.to
  const source = live ? shadow : getT()
  const anchor = source.slice(0, from).split('\n').length
  const quote = selection ? visibleSelectionQuote(target.from, target.to) : ''
  const anchorQuote = source.slice(from, to).slice(0, 500)
  const anchorRange = !pkg && anchorQuote.trim() ? saveCommentRange(from, to) : null
  const box = el('div', 'nw'), row = el('div', 'rr')
  if (live && !session?.original && target.to > target.from && from === to) {
    box.append(el('p', 'commentAnchorNote', t('comments.commentAfterSending')))
    return box
  }
  if (quote && quote.trim()) box.appendChild(el('div', 'qt nwQt', '"' + (quote.length > 90 ? quote.slice(0, 90) + '…' : quote) + '"'))
  const inp = el('input'); inp.id = 'popNew'; inp.maxLength = 2000; inp.placeholder = t('comments.newPh'); inp.setAttribute('aria-label', t('comments.newAria'))
  wireMentions(inp)
  const ok = icoBtn('ib', ICO_SEND); ok.title = t('comments.send'); ok.setAttribute('aria-label', ok.title)
  const post = async () => {
    if (doc !== docId || epoch !== openN || session !== window.changeSession || suggestion !== window.suggestionDraft || pkg !== commentPackage() || !inp.value.trim() || ok.disabled) return
    ok.disabled = true
    try {
      if (draft) { target.doc = doc; draft.commentRanges.set(target, target) }
      const body = { anchor, text: inp.value, quote, anchor_quote: anchorQuote.trim() ? anchorQuote : '', anchor_range: anchorRange, package_id: pkg }
      const result = draft ? await postReviewComment(draft, doc, body, target) : await api('POST', `/api/docs/${doc}/comments`, body)
      if (draft) { draft.commentRanges.delete(target); draft.commentRanges.set(result.id, target) }
      if (doc === docId && epoch === openN && pkg === commentPackage()) {
        if (inp.isConnected) closePop(true)
        await refresh('')
      }
    } catch (e) { if (draft) draft.commentRanges.delete(target); toast(e.message) } finally { ok.disabled = false }
  }
  ok.onclick = post; inp.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); post() } else if (e.key === 'Escape') closePop() }
  row.append(inp, ok); box.append(row)
  return box
}
function saveCommentChange(doc, item, text) {
  const s = window.changeSession && !window.changeSession.original ? window.changeSession : null
  if (item.package_id === 'draft') {
    if (text == null) s.draftComments = s.draftComments.filter(x => x.id !== item.id && x.parent_id !== item.id)
    else s.draftComments.find(x => x.id === item.id).text = text.trim()
    s.commentRanges.delete(item.id)
    sessionStash()
    return Promise.resolve()
  }
  if (s && !item.package_id) return postReviewComment(s, doc, { anchor: item.anchor || 1, text: text || '', deleted: text == null, replaces_id: item.id })
  return text == null ? api('DELETE', `/api/docs/${doc}/comments/${item.id}`) : api('POST', `/api/docs/${doc}/comments/${item.id}/edit`, { text })
}
function threadCard(th) {
  const doc = docId, epoch = openN
  const session = window.changeSession && !window.changeSession.original ? window.changeSession : null
  const fresh = () => { if (doc === docId && epoch === openN) return refresh(''); return Promise.resolve() }
  const d = el('div', 'th')
  const hd = el('div', 'hd')
  const author = th.author || th.username || '?'
  const av = el('span', 'av', author.slice(0, 1).toUpperCase()); av.style.background = colOf(th.username || author); av.setAttribute('aria-hidden', 'true')
  if (typeof paintAvatar === 'function' && th.username) paintAvatar(av, th.username, colOf(th.username))
  const meta = el('span', 'hdMeta')
  const nm = el('b', 'nm', author)
  meta.append(nm, el('span', 'tm', ago(th.created_at)))
  const acts = el('span', 'acts')
  hd.append(av, meta, acts)
  const roC = openedTrashed
  if (!roC && (!session || th.package_id && th.package_id !== 'draft') && !th.suggestion_status && (docRole === 'owner' || th.username === user)) {
    const fin = icoBtn('ib', th.resolved ? ICO_UNDO : ICO_CHECK); fin.title = th.resolved ? t('comments.reopen') : t('comments.done'); fin.setAttribute('aria-label', fin.title)
    fin.onclick = () => api('POST', `/api/docs/${doc}/comments/${th.id}/resolve`, { resolved: !th.resolved }).then(fresh).catch(e => toast(e.message))
    acts.appendChild(fin)
  }
  if (th.username === user && !openedTrashed) { // only author edits (owner deletes)
    const ed = icoBtn('ib', ICO_EDIT); ed.title = t('comments.edit'); ed.setAttribute('aria-label', ed.title)
    ed.onclick = async () => {
      const v = await ask(t('comments.editHead'), { value: th.text, maxLen: 2000 })
      if (doc !== docId || epoch !== openN || v === null || !v.trim()) return
      saveCommentChange(doc, th, v).then(fresh).catch(e => toast(e.message))
    }
    acts.appendChild(ed)
  }
  const pendingSug = th.suggestion_status === 'pending'
  const canDecide = pendingSug && ['owner', 'editor'].includes(docRole)
  const canDel = !roC && (pendingSug ? canDecide : (docRole === 'owner' || th.username === user))
  if (canDel) {
    const del = icoBtn('ib', ICO_TRASH); del.classList?.add('danger'); del.title = t('comments.delThread'); del.setAttribute('aria-label', del.title)
    del.onclick = () => pendingSug ? decideSuggestion(th, 'reject', doc, epoch) : saveCommentChange(doc, th, null).then(() => fresh().then(() => {
      if (doc === docId && epoch === openN && !threads.some(x => String(x.id) === String(th.id))) closePop()
    })).catch(e => toast(e.message))
    acts.appendChild(del)
  }
  d.appendChild(hd)
  if (th.suggestion_status) d.appendChild(suggestionCard(th, fresh, doc, epoch))
  else {
    const tag = el('span', 'thTag', t(th._proposedEdit ? 'comments.proposedEdit' : th.resolved ? 'comments.done' : 'comments.newAria'))
    if (th.resolved || th._proposedEdit) tag.classList.add('resolvedTag')
    meta.appendChild(tag)
    const range = th.a != null && th.b > th.a ? threadEditorRange(th) : null
    const quote = range && range.to > range.from ? cm.state.doc.sliceString(range.from, range.to) : th.quote
    if (quote) { // quoted passage first so comment + replies read as one continuous thread
      const q = el('button', 'qt', '"' + (quote.length > 80 ? quote.slice(0, 80) + '…' : quote) + '"')
      if (th.a == null) q.classList?.add('is-detached')
      q.title = t(th.a == null ? 'comments.detached' : 'comments.jumpPos')
      q.onclick = () => jumpThread(th)
      d.appendChild(q)
      if (th.a == null) d.appendChild(el('small', 'commentAnchorNote', t('comments.detached')))
    }
    if (th.text) d.appendChild(richText(th.text))
  }
  th.replies.forEach(r => {
    const rd = el('div', 'rp'), rh = el('div', 'hd')
    const rAuthor = r.author || r.username || '?'
    const rav = el('span', 'av', rAuthor.slice(0, 1).toUpperCase()); rav.style.background = colOf(r.username || rAuthor); rav.setAttribute('aria-hidden', 'true')
    if (typeof paintAvatar === 'function' && r.username) paintAvatar(rav, r.username, colOf(r.username))
    const rMeta = el('span', 'hdMeta')
    const rn = el('b', 'nm', rAuthor)
    rMeta.append(rn, el('span', 'tm', ago(r.created_at)))
    const rActs = el('span', 'acts')
    if (!roC && r.username === user) {
      const red = icoBtn('ib', ICO_EDIT); red.title = t('comments.edit'); red.setAttribute('aria-label', red.title)
      red.onclick = async () => {
        const v = await ask(t('comments.editHead'), { value: r.text, maxLen: 2000 })
        if (doc === docId && epoch === openN && v !== null && v.trim()) saveCommentChange(doc, r, v).then(fresh).catch(e => toast(e.message))
      }
      rActs.appendChild(red)
    }
    if (!roC && (docRole === 'owner' || r.username === user)) {
      const rdel = icoBtn('ib', ICO_TRASH); rdel.classList?.add('danger'); rdel.title = t('common.delete'); rdel.setAttribute('aria-label', rdel.title)
      rdel.onclick = () => saveCommentChange(doc, r, null).then(fresh).catch(e => toast(e.message))
      rActs.appendChild(rdel)
    }
    rh.append(rav, rMeta, rActs)
    rd.append(rh, richText(r.text)); d.appendChild(rd)
  })
  if (!roC) {
    const row = el('div', 'rr')
    const inp = el('input'); inp.id = 'r_' + th.id; inp.dataset.commentDraft = ''; inp.value = popDrafts.get(inp.id) || ''; inp.placeholder = t('comments.replyPh'); inp.setAttribute('aria-label', t('comments.replyAria'))
    wireMentions(inp)
    const ok = icoBtn('ib', ICO_SEND); ok.title = t('comments.send'); ok.setAttribute('aria-label', ok.title)
    const send = () => { if (doc !== docId || epoch !== openN || !inp.value.trim() || ok.disabled) return; ok.disabled = true
      const text = inp.value; inp.value = '' // clear first: else loadComments keeps it as draft and skips renderPop
      const body = { anchor: th.anchor, text, parent_id: th.id }
      ;(session ? postReviewComment(session, doc, body) : api('POST', `/api/docs/${doc}/comments`, body))
        .then(() => { if (doc === docId && epoch === openN) return refresh('r_' + th.id) }).catch(e => { inp.value = text; toast(e.message) }).finally(() => ok.disabled = false) }
    ok.onclick = send; inp.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); send() } else if (e.key === 'Escape') closePop() }
    row.append(inp, ok)
    d.appendChild(row)
  }
  return d
}
function invalidateCommentCache() { lastC = '' } // clears the poll dedupe key: the next loadComments re-derives ranges even though the comment list itself is unchanged (e.g. after a package accept)
function repaintCommentRanges() { // self-healing: threads beat the first sync text and the list never changes again - without this pass the marks stay missing while the badge counts them
  if (activeFile || !synced || !ytext || !threads.length || !threads.some(x => x.a == null)) return
  initRanges(); reanchor(); gutter(); refreshHl() // same pass as the fresh-list branch below; dedupe only skips rendering, never the range derivation
}
function proposalComments(live, items) {
  const tops = live.map(th => ({ ...th, replies: (th.replies || []).map(r => ({ ...r })) }))
  const byId = new Map(tops.flatMap(th => [[th.id, th], ...th.replies.map(r => [r.id, r])]))
  for (const item of items) if (item.replaces_id && byId.has(item.replaces_id)) {
    const target = byId.get(item.replaces_id)
    if (item.deleted) target._removed = true
    else { target.text = item.text; target._proposedEdit = true }
  }
  for (const item of items) if (item.parent_id && !item.replaces_id) byId.get(item.parent_id)?.replies.push(item)
  return [...tops.filter(th => !th._removed).map(th => ({ ...th, replies: th.replies.filter(r => !r._removed) })), ...items.filter(item => !item.parent_id && !item.replaces_id)]
}
function commentPackage() {
  const s = window.changeSession
  return s && !s.original ? s.package?.id || 'draft' : ''
}
async function loadComments(force) {
  const doc = docId, epoch = openN
  if (!doc) return
  const session = window.changeSession, pkg = commentPackage()
  const scoped = threads.filter(th => !th.package_id || th.package_id === pkg)
  if (scoped.length !== threads.length) { threads = scoped; paintBadge() }
  const url = `/api/docs/${doc}/comments`
  const liveRequest = api('GET', url)
  const [live, proposed] = await Promise.all([
    pkg === 'draft' ? liveRequest.catch(() => ({ comments: scoped.filter(th => !th.package_id) })) : liveRequest,
    pkg === 'draft' ? (session.draftComments || []).filter(th => th.doc_id === doc)
      : pkg ? api('GET', `${url}?package_id=${encodeURIComponent(pkg)}`).then(data => [...data.comments, ...(data.changes || [])]) : [],
  ])
  if (doc !== docId || epoch !== openN || session !== window.changeSession || pkg !== commentPackage()) return
  const combined = proposalComments(live.comments, proposed).filter(th => !th.suggestion_status || th.suggestion_status === 'pending')
  const s = (pkg ? pkg + ':' : '') + JSON.stringify(combined)
  if (s === lastC) { repaintCommentRanges(); return } // poll: nothing new, keep inputs untouched - but re-derive ranges the first sync skipped
  const prevById = new Map(threads.map(th => [th.id, th]))
  lastC = s; threads = combined
  for (const th of threads) {
    const docLen = (!th.package_id && (activeFile || window.suggestionDraft || session) ? shadow : getT()).length
    th.anchor = Math.max(1, +th.anchor || 1) // heal legacy anchor 0 -> 1
    const prev = prevById.get(th.id)
    if (prev && !th.suggestion_status && th.quote === prev.quote && th.anchor_quote === prev.anchor_quote) {
      if (prev._deleted) { th._deleted = true; th.a = th.b = null }
      else if (prev.a != null && prev.b != null && prev.b >= prev.a && prev.b <= docLen) { th.a = prev.a; th.b = prev.b }
    }
  }
  if (!activeFile) { initRanges(); reanchor(); gutter(); refreshHl() } // file tab: do not touch main anchors
  paintBadge()
  const draft = [...$('pop').querySelectorAll('input,textarea')].some(i => i.value.trim())
  if (popAnchor != null && !draft && (force || !$('pop').contains(document.activeElement))) renderPop()
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
  jumpThread(open[(open.findIndex(th => String(th.id) === popThreadId || 't:' + th.id === popThreadId) + 1) % open.length])
}
$('eBadge').onclick = showErrList
function reanchor() { // keep live ranges on edits; suggestions track exact unique match; deleted quotes never resurrect onto unrelated text
  const t = getT()
  if (!docId || !ytext || activeFile || window.suggestionDraft || window.changeSession) return // file tab: anchors belong to main
  let moved = !!initRanges() // capture whether first sync just derived ranges so highlights always paint after reload
  for (const th of threads) {
    const before = th.a + '|' + th.b
    const pending = th.suggestion_status === 'pending'
    const quote = pending ? th.suggestion_old : th.anchor_quote ?? th.quote
    if (pending) {
      const i = t || synced ? pendingSuggestionPos(t, th) : -1
      if (i >= 0) {
        th.conflict = false
        th.a = i; th.b = Math.min(t.length, i + quote.length)
        const line = t.slice(0, i).split('\n').length
        if (line !== th.anchor) { th.anchor = line; moved = true; dirtyAnchor(th) }
      } else {
        th.conflict = true
        th.a = th.b = null
        if (t && th.anchor <= t.split('\n').length) {
          const a = posOfLine(t, th.anchor)
          th.a = a; th.b = a + t.slice(a).split('\n')[0].length
        }
      }
    } else if (quote) {
      if (th.a != null && th.b != null && th.b > th.a) { // live mapped range: keep it across edits instead of exploding to the whole line
        const line = t.slice(0, Math.min(th.a, t.length)).split('\n').length
        if (line !== th.anchor) { th.anchor = line; moved = true; dirtyAnchor(th) }
      } else if (!th.anchor_range || !resolveCommentRange(th.anchor_range)) {
        const i = exactQuotePos(t, quote, th.anchor)
        if (i >= 0) {
          th.a = i; th.b = Math.min(t.length, i + quote.length); th._deleted = false
          const line = t.slice(0, i).split('\n').length
          if (line !== th.anchor) { th.anchor = line; moved = true; dirtyAnchor(th) }
        } else {
          th.a = th.b = null
        }
      }
    } else { // quoteless comment: anchored to its line
      th.a = th.b = null
      if (t && th.anchor <= t.split('\n').length) {
        const a = posOfLine(t, th.anchor)
        th.a = a; th.b = a + t.slice(a).split('\n')[0].length
      }
    }
    if (th.a + '|' + th.b !== before) moved = true // first real sync after empty load, or unmarking: paint at once
  }
  if (moved) { // refresh icon at once, not only on save
    gutter(); refreshHl()
    if (popAnchor != null) movePop()
  }
}
async function jumpThread(t) {
  const id = docId, epoch = openN
  if (activeFile) await switchTab('') // jump lives in main, not in file tab
  if (id !== docId || epoch !== openN || activeFile) return
  const doc = getT()
  let { from: a, to: b } = threadEditorRange(t)
  if (b < a) b = a
  b = Math.min(doc.length, b)
  cm.dispatch({ selection: { anchor: a, head: b },
    effects: EditorView.scrollIntoView(b, { y: 'center' }) })
  cm.focus()
  openPop(cm.state.doc.lineAt(a).number, false, null, t.id)
  $('pop').focus({ preventScroll: true })
}
async function refresh(focusId) {
  const doc = docId, epoch = openN
  await loadComments(true)
  if (doc !== docId || epoch !== openN) return
  if (popAnchor != null && focusId) document.getElementById(focusId)?.focus()
}
function updCNewTip() {
  const m = cm.state.selection.main
  const tip = m && !m.empty ? t('comments.tipYes') : t('comments.tipNo')
  $('cNew').title = tip; $('cNew').setAttribute('aria-label', tip)
}
$('cNew').onclick = () => {
  if (!docId || activeFile || openedTrashed) return
  const m = cm.state.selection.main // anchor at selection start so multi-line comments sit on their opening line
  openPop(lineOf(m.from), true)
}

const ICO_MORE = svgI('<circle cx="3" cy="8" r=".7"/><circle cx="8" cy="8" r=".7"/><circle cx="13" cy="8" r=".7"/>')

addEventListener('resize', () => { popLayoutTries = 0; if (popAnchor != null) movePop() })
new ResizeObserver(() => { popLayoutTries = 0; if (popAnchor != null) requestAnimationFrame(movePop) }).observe($('editWrap'))
