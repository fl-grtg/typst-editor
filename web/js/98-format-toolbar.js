// --- Formatting toolbar (UI layer over the editor; acts on the main selection only) ---
function fmtWrap(a, b = a) {
  const st = cm.state, doc = st.doc, { from, to } = st.selection.main
  const before = doc.sliceString(Math.max(0, from - a.length), from), after = doc.sliceString(to, Math.min(doc.length, to + b.length))
  if (from !== to && before === a && after === b) { // already wrapped: unwrap
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
  cm.dispatch({
    changes: lines.map(l => { const m = prefixRe.exec(l.text); return { from: l.from, to: l.from + (m ? m[0].length : 0), insert: next } }),
    userEvent: 'input',
  })
}
function fmtApply(kind) {
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
