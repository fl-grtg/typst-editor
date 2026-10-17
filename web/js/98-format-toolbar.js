// --- Formatting toolbar (UI layer over the editor; acts on the main selection only) ---
function fmtWrap(a, b = a) {
  const st = cm.state, doc = st.doc, { from, to } = st.selection.main
  const before = doc.sliceString(Math.max(0, from - a.length), from), after = doc.sliceString(to, Math.min(doc.length, to + b.length))
  if (before === a && after === b && (from !== to || a !== b || doc.sliceString(0, from - a.length).split(a).length % 2 === 1)) { // already wrapped: unwrap (collapsed caret only for an own empty pair: even marker count left of it; a closer|opener boundary of two spans must wrap instead, unwrapping would fuse them)
    cm.dispatch({ changes: [{ from: from - a.length, to: from }, { from: to, to: to + b.length }], selection: { anchor: from - a.length, head: to - a.length }, userEvent: 'input' })
    return
  }
  cm.dispatch({
    changes: [{ from, insert: a }, { from: to, insert: b }],
    selection: from === to ? { anchor: from + a.length } : { anchor: from + a.length, head: to + a.length }, userEvent: 'input',
  })
}
function fmtLines(prefixRe, makePrefix) { // per-line prefix: heading / lists
  const st = cm.state, doc = st.doc, { from, to } = st.selection.main
  const first = doc.lineAt(from).number
  let last = doc.lineAt(to).number
  if (to > from && doc.line(last).from === to) last-- // selection ends at start of next line: not included
  const lines = []
  for (let n = first; n <= last; n++) lines.push(doc.line(n))
  const next = makePrefix(lines)
  const oldLens = lines.map(l => { const m = prefixRe.exec(l.text); return m ? m[0].length : 0 })
  const deltas = oldLens.map(old => next.length - old)
  const total = deltas.reduce((a, b) => a + b, 0)
  const prevBeforeLast = deltas.slice(0, -1).reduce((a, b) => a + b, 0)
  const firstStart = lines[0].from, lastStart = lines[lines.length - 1].from
  const anchor = from <= firstStart + oldLens[0] ? firstStart + next.length : from + deltas[0]
  const headPos = to <= lastStart + oldLens[oldLens.length - 1]
    ? lastStart + prevBeforeLast + next.length
    : to + total
  cm.dispatch({
    changes: lines.map((l, i) => ({ from: l.from, to: l.from + oldLens[i], insert: next })),
    selection: to === from ? { anchor } : { anchor, head: headPos },
    userEvent: 'input',
  })
}
function fmtApply(kind) {
  if (!/\.typ$/i.test(tplName || tabName(activeFile))) return
  if (!cm.state.facet(EditorView.editable)) return
  if (kind === 'bold') fmtWrap('*')
  else if (kind === 'italic') fmtWrap('_')
  else if (kind === 'underline') fmtWrap('#underline[', ']')
  else if (kind === 'math') fmtWrap('$')
  else if (kind === 'code') fmtWrap('`')
  else if (kind === 'heading') fmtLines(/^=+ /, ls => { const m = /^(=+) /.exec(ls[0].text), lvl = m ? m[1].length : 0; return lvl >= 3 ? '' : '='.repeat(lvl + 1) + ' ' })
  else if (kind === 'bullets') fmtLines(/^[-+] /, ls => ls.every(l => /^- /.test(l.text)) ? '' : '- ')
  else if (kind === 'numbers') fmtLines(/^[-+] /, ls => ls.every(l => /^\+ /.test(l.text)) ? '' : '+ ')
  else if (kind === 'link') {
    const { from, to } = cm.state.selection.main
    const label = from === to ? 'link' : cm.state.doc.sliceString(from, to), pre = '#link("'
    cm.dispatch({ changes: { from, to, insert: pre + 'https://' + '")[' + label + ']' }, selection: { anchor: from + pre.length, head: from + pre.length + 8 }, userEvent: 'input' })
  }
  cm.focus()
}
document.querySelectorAll('[data-fmt]').forEach(b => {
  b.addEventListener('mousedown', e => e.preventDefault()) // keep the editor selection while clicking
  b.onclick = () => fmtApply(b.dataset.fmt)
})
cm.contentDOM.addEventListener('keydown', e => {
  if (!(e.ctrlKey || e.metaKey) || e.shiftKey || e.altKey) return
  const k = { b: 'bold', i: 'italic', u: 'underline' }[e.key.toLowerCase()]
  if (k) { e.preventDefault(); fmtApply(k) }
})
const fmtSync = () => { const on = cm.contentDOM.getAttribute('contenteditable') === 'true'; document.querySelectorAll('[data-fmt]').forEach(b => { b.disabled = !on }) }
new MutationObserver(fmtSync).observe(cm.contentDOM, { attributes: true, attributeFilter: ['contenteditable'] })
fmtSync()
