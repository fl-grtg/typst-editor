// --- Editor <-> Y.Text: exact change sets both ways (no whole-doc replace: cursor, selection and undo survive) ---
function diffSpan(old, v) { // common prefix/suffix: fallback when editor and Y drifted apart
  let a = 0; while (a < Math.min(old.length, v.length) && old[a] === v[a]) a++
  let b = 0; while (b < Math.min(old.length - a, v.length - a) && old[old.length - 1 - b] === v[v.length - 1 - b]) b++
  return { a, b }
}
const diffMap = (old, v) => { // position mapper for the diff fallback
  const { a, b } = diffSpan(old, v), d = v.length - old.length
  return (p, end) => p <= a ? p : p >= old.length - b ? p + d : end ? v.length - b : a
}
const deltaMap = delta => (p, end) => { // position mapper from a Y delta (start sticks left, end grows right)
  let o = 0, n = 0
  for (const d of delta) {
    if (d.retain) { if (p < o + d.retain) return n + (p - o); o += d.retain; n += d.retain }
    else if (d.delete) { if (p < o + d.delete) return n; o += d.delete }
    else if (d.insert != null) { if (p === o && !end) return n; n += typeof d.insert === 'string' ? d.insert.length : 1 }
  }
  return n + (p - o)
}
function setYText(v) { // replace Y content with minimal edit (never delete+reinsert everything: keeps peers' work outside the span)
  const old = ytext.toString(), { a, b } = diffSpan(old, v)
  if (a + b === old.length && a + b === v.length) return
  ydoc.transact(() => {
    if (a + b < old.length) ytext.delete(a, old.length - a - b)
    if (a + b < v.length) ytext.insert(a, v.slice(a, v.length - b))
  }, 'local')
}
function pushLocal(changes, oldLen) {
  if (changes && ytext.length === oldLen && shadow.length === oldLen) { // in sync: apply CM changes 1:1
    ydoc.transact(() => {
      let adj = 0 // later changes shift by earlier ones (iterChanges reports old-doc positions)
      changes.iterChanges((fromA, toA, _fb, _tb, ins) => {
        const s = ins.toString(), del = toA - fromA
        if (del) ytext.delete(fromA + adj, del)
        if (s) ytext.insert(fromA + adj, s)
        adj += s.length - del
      })
    }, 'local') // own edits: skip pullRemote via observer (see openDoc)
    shadow = getT()
    return
  }
  setYText(getT()) // drift: diff fallback
  shadow = getT()
}
function pullRemote(ev) {
  const v = ytext.toString()
  synced = true // server text arrived: saves now write real content
  if (v === shadow) { jumpWant(); return }
  const old = shadow, delta = ev && ev.delta
  const map = delta ? deltaMap(delta) : diffMap(old, v)
  shadow = v
  if (activeFile) { // file tab open: buffer main only, editor shows file
    if (threads.length) mapThreads(map, false) // values yes (main-relative), paint no (Fix #5)
    queueRender()
    return
  }
  applying = true
  try {
    if (delta && cm.state.doc.length === old.length) { // normal case: delta -> CM changes, selection maps on its own
      const changes = []; let pos = 0
      for (const d of delta) {
        if (d.retain) pos += d.retain
        else if (d.delete) { changes.push({ from: pos, to: pos + d.delete }); pos += d.delete }
        else if (typeof d.insert === 'string') changes.push({ from: pos, insert: d.insert })
      }
      cm.dispatch({ changes, annotations: NO_HIST })
    }
    if (getT() !== v) { // drift fallback: minimal replace, selection mapped by hand
      const sel = cm.state.selection.main, cur = getT(), { a, b } = diffSpan(cur, v), m = diffMap(cur, v)
      cm.dispatch({ changes: { from: a, to: cur.length - b, insert: v.slice(a, v.length - b) }, annotations: NO_HIST,
        selection: { anchor: Math.min(m(sel.anchor, false), v.length), head: Math.min(m(sel.head, true), v.length) } })
    }
  } finally { applying = false }
  jumpWant() // jump to search hit after open
  if (threads.length) mapThreads(map)
  reanchor()
  paintOutline()
  queueRender()
}
