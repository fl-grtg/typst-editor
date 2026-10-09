// --- Find + replace: bottom bar (Ctrl+F), hits as marks, Enter = next ---
let findOpen = false, findHits = [], findI = 0, findCase = false, findRe = false // F10: regex toggle; hits are {a,b} (literal: b = a + q.length)
function openFind() {
  if (!$('app').classList.contains('on')) return
  findOpen = true; $('find').style.display = ''
  const m = cm.state.selection.main
  if (!m.empty) $('fQ').value = getT().slice(m.from, m.to).split('\n')[0].slice(0, 80) // selection becomes search
  markFind(); $('fQ').focus(); $('fQ').select()
}
function closeFind() {
  findOpen = false; $('find').style.display = 'none'
  cm.dispatch({ effects: setFind.of(RangeSet.of([])) }); cm.focus()
}
function paintFind(sel) { // hits blue, current orange; sel = also jump
  cm.dispatch({ effects: setFind.of(RangeSet.of(findHits.map((h, i) =>
    Decoration.mark({ class: i === findI ? 'cm-find-cur' : 'cm-find' }).range(h.a, h.b)), true)) })
  if (sel && findHits.length) {
    const h = findHits[findI]
    cm.dispatch({ selection: { anchor: h.a, head: h.b }, effects: EditorView.scrollIntoView(h.a, { y: 'center' }) })
  }
  const q = $('fQ').value
  $('fN').textContent = findHits.length ? (findI >= 0 ? (findI + 1) + '/' + findHits.length : '' + findHits.length) : (q ? '0' : '')
}
function markFind(sel = true) { // sel=false: recount only, never steal selection/scroll (typing beside an open find)
  findHits = []; findI = -1
  const q = $('fQ').value
  if (!q) { paintFind(false); return }
  if (findRe) { // F10 regex: invalid pattern shows 'bad regex', never throws
    let re
    try { re = new RegExp(q, findCase ? 'g' : 'gi') } catch (e) { cm.dispatch({ effects: setFind.of(RangeSet.of([])) }); $('fN').textContent = t('find.badRegex'); return }
    try {
      for (const m of getT().matchAll(re)) {
        if (m[0].length && findHits.length < 500) findHits.push({ a: m.index, b: m.index + m[0].length })
      } // zero-length matches skipped (matchAll steps on by itself, no hang)
    } catch (e) { $('fN').textContent = t('find.badRegex'); return }
  } else {
    const t = findCase ? getT() : getT().toLowerCase(), n = findCase ? q : q.toLowerCase()
    let p = 0, hit
    while ((hit = t.indexOf(n, p)) >= 0 && findHits.length < 500) { findHits.push({ a: hit, b: hit + q.length }); p = hit + q.length } // no overlap: else replace-all breaks transaction
  }
  if (!findHits.length) { paintFind(false); return }
  if (!sel) { paintFind(false); return } // all blue, none current: cursor stays where the user works
  findI = findHits.findIndex(h => h.a >= cm.state.selection.main.head)
  if (findI < 0) findI = 0
  paintFind(true)
}
function stepFind(d) {
  if (!findHits.length) return
  if (findI < 0 || findI >= findHits.length) findI = d > 0 ? -1 : 0 // resume from the ends when nothing is current
  findI = (findI + d + findHits.length) % findHits.length
  paintFind(true)
}
function doRep(all) {
  if (docRole === 'reviewer' || openedTrashed) return // read yes, replace no
  const q = $('fQ').value, r = $('fR').value
  if (!q || !findHits.length) return
  if (findI < 0 || findI >= findHits.length) { const hd = cm.state.selection.main.head; findI = findHits.findIndex(h => hd >= h.a && hd <= h.b); if (findI < 0) findI = findHits.findIndex(h => h.a >= hd); if (findI < 0) findI = 0 } // deselected by click: hit under cursor first, else nearest ahead
  if (findRe) { // F10: regex replace, $1 groups supported (lookbehind across hit edges unsupported: silent no-op)
    let one
    try { one = new RegExp('^(?:' + q + ')$', (findCase ? '' : 'i') + 's') } catch (e) { return }
    const t = getT(), rep = h => t.slice(h.a, h.b).replace(one, r)
    if (all) cm.dispatch({ changes: findHits.map(h => ({ from: h.a, to: h.b, insert: rep(h) })) })
    else { const h = findHits[findI], ins = rep(h); cm.dispatch({ changes: { from: h.a, to: h.b, insert: ins }, selection: { anchor: h.a + ins.length } }) }
  } else {
    const h = findHits[findI]
    cm.dispatch(all
      ? { changes: findHits.map(x => ({ from: x.a, to: x.b, insert: r })) }
      : { changes: { from: h.a, to: h.b, insert: r }, selection: { anchor: h.a + r.length } })
  }
  markFind() // onEdit recounts anyway, here at once for counter
}
$('fQ').oninput = () => markFind(true)
$('fCase').onclick = () => { findCase = !findCase; $('fCase').classList.toggle('on', findCase); $('fCase').setAttribute('aria-pressed', findCase); markFind(); $('fQ').focus() }
$('fRe').onclick = () => { findRe = !findRe; $('fRe').classList.toggle('on', findRe); $('fRe').setAttribute('aria-pressed', findRe); markFind(); $('fQ').focus() }
$('fPrev').onclick = () => stepFind(-1)
$('fNext').onclick = () => stepFind(1)
$('fRep').onclick = () => doRep(false)
$('fAll').onclick = () => doRep(true)
$('fX').onclick = closeFind
const findKeys = e => {
  if (e.key === 'Enter') stepFind(e.shiftKey ? -1 : 1)
  if (e.key === 'Escape') closeFind()
}
$('fQ').onkeydown = $('fR').onkeydown = findKeys
addEventListener('keydown', e => { // Ctrl/Cmd+F = bar, Ctrl/Cmd+S = save now, ? = help
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'f') { e.preventDefault(); openFind() }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); saveNow() }
  if ((e.ctrlKey || e.metaKey) && (e.key === '+' || e.key === '=')) { e.preventDefault(); stepPv(PV_STEP) }
  if ((e.ctrlKey || e.metaKey) && e.key === '-') { e.preventDefault(); stepPv(-PV_STEP) }
  if ((e.ctrlKey || e.metaKey) && e.key === '0') { e.preventDefault(); pvZoom = 110; applyPv(); saveSet() }
  if (e.key === '?' && !e.ctrlKey && !e.metaKey && $('app').classList.contains('on')
    && !/INPUT|TEXTAREA|SELECT/.test((document.activeElement || {}).tagName || '') && !cm.hasFocus) openTutorial()
})
$('helpBtn').onclick = e => { if (e.shiftKey) open('https://github.com/fl-grtg/typst-editor', '_blank'); else openTutorial() }
document.querySelector('a[href="#cm"]')?.addEventListener('click', () => setTimeout(() => { try { cm.focus() } catch (e) {} }, 60)) // skip link: keyboard focus into editor, not just scroll
