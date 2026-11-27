// --- Resources: manage globally (icon), use per doc (insert line only) ---
function resLine(tpl) { // the one line a doc needs: compiler resolves it against reachable resources (see resource-contract.md)
  const n = tpl.name || ''
  if (/\.bib$/i.test(n)) return tpl.line || `#bibliography("${n}")`
  if (/\.csv$/i.test(n)) return `#csv("${n}")`
  // Page rules inside an include revert at its end and force another page.
  // Insert page-layout templates directly so their settings continue afterwards.
  if (/^\s*#set\s+page\s*\(/m.test(tpl.content || '')) return tpl.content.trimEnd()
  if (!/\.typ$/i.test(n)) return mediaInsert(n)
  return tpl.line || `#include "${n}"`
}
function renderTpl() {
  const p = $('tplPop'); p.replaceChildren()
  const tip = el('div', 'tip'); tip.textContent = t('templates.tip'); p.appendChild(tip)
  const editable = !!docProject && !docResReadonly
  lastFiles.filter(f => TEXT_EXT.test(f.path)).forEach(f => { // the project's text files: insert the line that reaches them
    const row = el('div', 'trow')
    const b = el('button', 'go', f.path); b.title = t('templates.insertInto'); b.setAttribute('aria-label', b.title)
    b.onclick = () => addTpl(resLine({ name: refTo(f.path), content: cachedText(f.path) }))
    const edit = icoBtn('x', ICO_EDIT); edit.title = t('projects.openModule'); edit.setAttribute('aria-label', edit.title); edit.onclick = () => { hidePops(); switchTab(f.path) }
    row.append(b, edit)
    if (editable) {
      const x = icoBtn('x', ICO_X); x.title = t('templates.delRes'); x.setAttribute('aria-label', x.title)
      x.onclick = e => { e.stopPropagation(); hidePops(); deleteProjectEntry(projects.find(x => x.id === docProject), f.path).catch(err => toast(err.message)) }
      row.appendChild(x)
    }
    p.appendChild(row)
  })
  if (editable) myTpl.forEach(tpl => {
    const row = el('div', 'trow')
    const b = el('button', 'go', tpl.name); b.title = t('projects.pullInsert'); b.setAttribute('aria-label', b.title)
    b.onclick = () => insertPersonalResource(tpl).catch(e => toast(e.message))
    row.appendChild(b); p.appendChild(row)
  })
  if (editable) { const create = el('button', null, t('projects.newFile')); create.onclick = () => newProjectResource(docProject, docFolder).catch(e => toast(e.message)); p.appendChild(create) }
  if (docId) return
  const nw = el('button')
  nw.append(el('span', 'use', t('templates.newTpl')), el('span', 'ins', t('templates.newTplSub')))
  nw.onclick = newTemplate
  p.appendChild(nw)
  const up = el('button')
  up.append(el('span', 'use', t('templates.upOwn')), el('span', 'ins', t('templates.upOwnSub')))
  up.onclick = () => $('tplPick').click()
  p.appendChild(up)
}
async function newResource(kind, chosenExt) {
  const ext = chosenExt || (kind === 'resource' ? await chooseFileType() : RES_EXT[kind])
  if (!ext) return
  const list = $('tpls')
  if (list && list.classList.contains('shut')) { $('tplH').click() }
  const inline = list && list.offsetParent && typeof sidebarInlineCreate === 'function'
  const raw = inline
    ? await sidebarInlineCreate(list, 'file' + ext, { ph: t('templates.namePh'), label: t('templates.newTitle'), maxLen: 100, stem: true })
    : (await askNewTpl('file' + ext, t('templates.newTitle')))?.name
  if (!raw?.trim()) return
  let name = uploadName(raw.trim())
  if (!TEXT_EXT.test(name)) name += ext
  await loadTpl()
  if (myTpl.some(x => x.name === name)) { toast(t('common.nameExists')); return }
  const content = fileStart(name.split('.').pop().toLowerCase())
  try {
    const r = await api('POST', '/api/templates', { name, content, folder: '' })
    await loadTpl(); await openTpl(r.name)
  } catch (e) { toast(e.message) }
}
async function newTemplate() { // one dialog: name + folder (like askNewDoc, not 3 cascades)
  if (!getT().trim()) { toast(t('templates.emptyEd')); return }
  await loadTpl() // fresh: else upsert overwrites foreign template
  const r = await askNewTpl()
  if (!r || !r.name || !r.name.trim()) return
  let n = r.name.trim()
  if (!/\.(typ|bib|csv|tsv|json|yaml|yml|toml|xml|txt|csl)$/i.test(n)) n += '.typ'
  if (myTpl.some(x => x.name === n)) { toast(t('common.nameExists')); return }
  try {
    const rr = await api('POST', '/api/templates', { name: n, content: getT(), folder: r.folder || '' })
    hidePops()
    await loadTpl(); renderTpl(); sidebar(); openTpl(rr.name)
  } catch (e) { toast(e.message) }
}
function addTpl(line) { // line at cursor only: compiler knows content as shadow (see render)
  if (!cm.state.facet(EditorView.editable)) { toast(t('projects.readonly')); return }
  const m = cm.state.selection.main
  cm.dispatch({ changes: { from: m.from, to: m.to, insert: line + '\n' }, selection: { anchor: m.from + line.length + 1 } })
  cm.focus(); hidePops(); queueRender()
}
$('tplPick').onchange = () => { const f = $('tplPick').files[0]; $('tplPick').value = ''; importUpload(f) }
$('tplBtn').onclick = e => {
  e.stopPropagation()
  if (showPop('tplPop')) renderTpl()
}

{
  const button = icoBtn(null, svgI('<path d="M2 3h5a2 2 0 0 1 1 1 2 2 0 0 1 1-1h5v10H9a2 2 0 0 0-1 1 2 2 0 0 0-1-1H2zM8 4v10"/>'))
  button.id = 'citeLibrary'; button.dataset.i18nTitle = 'editor.citeLibrary'; button.dataset.i18nAria = 'editor.citeLibrary'
  button.title = t('editor.citeLibrary'); button.setAttribute('aria-label', button.title)
  $('tplBtn').parentNode.insertBefore(button, $('tplBtn'))
  const canCite = () => !!docId && /\.typ$/i.test(tabName(activeFile)) && cm.state.facet(EditorView.editable)
  const syncCite = () => { button.disabled = !canCite() }
  new MutationObserver(syncCite).observe($('tabs'), { childList: true })
  new MutationObserver(syncCite).observe($('title'), { childList: true })
  new MutationObserver(syncCite).observe(cm.contentDOM, { attributes: true, attributeFilter: ['contenteditable'] })
  syncCite()
  button.onclick = async () => {
    if (!canCite()) return
    const doc = docId, resource = tplName, file = activeFile, epoch = openN
    const options = lastFiles.flatMap(f => {
      const lib = { name: f.path, content: cachedText(f.path) }
      if (/\.bib$/i.test(lib.name)) return parseBib(lib.content).filter(e => e.key).map(e => ({ key: e.key, lib }))
      if (/\.ya?ml$/i.test(lib.name)) {
        try { const entries = CMV.parseYaml(lib.content); return Object.entries(entries || {}).filter(([, v]) => v && typeof v === 'object' && typeof v.type === 'string').map(([key]) => ({ key, lib })) } catch (e) {}
      }
      return []
    })
    if (!options.length) { $('tplBtn').click(); return }
    const choice = await pickPop(t('editor.citeLibrary'), options.map(x => [x.key, x.lib.name]), button)
    if (choice == null || !options[choice] || doc !== docId || resource !== tplName || file !== activeFile || epoch !== openN || !cm.state.facet(EditorView.editable)) return
    const { key, lib } = options[choice]
    const ref = refTo(lib.name, docFolder)
    if (!(ytext?.toString() || shadow).includes('"' + ref + '"')) mainAppend(`#bibliography("${ref}")`)
    addTpl('@' + key)
  }
}
