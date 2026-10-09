// --- Templates: manage globally (icon), use per doc (insert line only) ---
function renderTpl() {
  const p = $('tplPop'); p.replaceChildren()
  const tip = el('div', 'tip'); tip.textContent = 'Insert saved text with one line. Manage folders in the sidebar.'; p.appendChild(tip)
  const mkRow = t => {
    const row = el('div', 'trow')
    const b = el('button', 'go', t.name); b.title = 'Insert into document'; b.setAttribute('aria-label', b.title)
    b.onclick = () => addTpl(t.line)
    const x = icoBtn('x', ICO_X); x.title = 'Delete template'; x.setAttribute('aria-label', x.title)
    x.onclick = async e => {
      e.stopPropagation()
      if (!await ask(`Delete "${t.name}"?`, { noInput: true, ok: 'Delete', danger: true })) return
      try { await api('DELETE', '/api/templates/' + encodeURIComponent(t.name)); await loadTpl(); renderTpl(); sidebar() }
      catch (err) { toast(err.message) }
    }
    row.append(b, x); return row
  }
  const { top, byF } = groupBy(myTpl)
  top.forEach(t => p.appendChild(mkRow(t)))
  tplFolders.forEach(f => { if (!byF.has(f.folder)) byF.set(f.folder, []) })
  ;[...byF.keys()].sort((a, b) => a.localeCompare(b)).forEach(f => {
    if (!byF.get(f).length) return // empty folders only in sidebar, not in insert popup
    p.appendChild(el('div', 'fh', f))
    byF.get(f).forEach(t => p.appendChild(mkRow(t)))
  })
  const nw = el('button')
  nw.append(el('span', 'use', '+ New template'), el('span', 'ins', 'Save editor text as template'))
  nw.onclick = newTemplate
  p.appendChild(nw)
  const up = el('button')
  up.append(el('span', 'use', '+ Upload own'), el('span', 'ins', 'Save .typ as template'))
  up.onclick = () => $('tplPick').click()
  p.appendChild(up)
}
async function newTemplate() { // one dialog: name + folder (like askNewDoc, not 3 cascades)
  if (!getT().trim()) { toast('Editor is empty'); return }
  await loadTpl() // fresh: else upsert overwrites foreign template
  const r = await askNewTpl()
  if (!r || !r.name || !r.name.trim()) return
  let n = r.name.trim()
  if (!n.toLowerCase().endsWith('.typ')) n += '.typ'
  if (myTpl.some(x => x.name === n)) { toast('Name already exists'); return }
  try {
    const rr = await api('POST', '/api/templates', { name: n, content: getT(), folder: r.folder || '' })
    hidePops()
    await loadTpl(); renderTpl(); sidebar(); openTpl(rr.name)
  } catch (e) { toast(e.message) }
}
function addTpl(line) { // line at cursor only: compiler knows content as shadow (see render)
  const m = cm.state.selection.main
  cm.dispatch({ changes: { from: m.from, to: m.to, insert: line + '\n' }, selection: { anchor: m.from + line.length + 1 } })
  cm.focus(); hidePops(); queueRender()
}
$('tplPick').onchange = async () => {
  const f = $('tplPick').files[0]; $('tplPick').value = ''
  if (!f) return
  const text = await f.text()
  if (!text.trim()) { toast('Empty file'); return }
  try {
    await api('POST', '/api/templates', { name: f.name, content: text })
    await loadTpl(); renderTpl(); sidebar()
  } catch (e) { toast(e.message) }
}
$('tplBtn').onclick = e => {
  e.stopPropagation()
  if (showPop('tplPop')) renderTpl()
}
