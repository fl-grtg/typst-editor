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
  const shared = docId && (docProject || docRole !== 'owner')
  const p = $('tplPop'); p.replaceChildren()
  const tip = el('div', 'tip'); tip.textContent = t('templates.tip'); p.appendChild(tip)
  const note = el('div', 'tip'); note.textContent = t('templates.sharedResNote'); p.appendChild(note)
  const mkRow = tpl => {
    const row = el('div', 'trow')
    const b = el('button', 'go', tpl.name); b.title = t('templates.insertInto'); b.setAttribute('aria-label', b.title)
    b.onclick = () => addTpl(resLine(tpl))
    const x = icoBtn('x', ICO_X); x.title = t('templates.delRes'); x.setAttribute('aria-label', x.title)
    x.onclick = async e => {
      e.stopPropagation()
      if (!await ask(t('templates.delResConfirm', { name: tpl.name }), { noInput: true, ok: t('common.delete'), danger: true })) return
      const project = docProject, document = docId
      try {
        if (project) {
          await api('DELETE', `/api/projects/${project}/resources/${encodeURIComponent(tpl.name)}?version=${encodeURIComponent(tpl.updated_at || '')}`)
          if (docId !== document || docProject !== project) return
          if (activeFile === TPLK + tpl.name) await switchTab('', true)
          tabPins.delete(tpl.name); tabVersions.delete(TPLK + tpl.name)
          await loadDocResources(true); tabSig = ''; paintTabs(); queueRender()
        } else await api('DELETE', '/api/templates/' + encodeURIComponent(tpl.name))
        await loadTpl(); renderTpl(); sidebar()
      }
      catch (err) { toast(err.message) }
    }
    row.appendChild(b)
    if (docProject) { const edit = icoBtn('x', ICO_EDIT); edit.title = t('projects.openModule'); edit.setAttribute('aria-label', edit.title); edit.onclick = () => { tabPins.add(tpl.name); switchTab(TPLK + tpl.name); hidePops() }; row.appendChild(edit) }
    if (!shared || (docProject && !docResReadonly)) row.appendChild(x); return row
  }
  projectResources().forEach(tpl => p.appendChild(mkRow(tpl)))
  if (docProject && !docResReadonly) myTpl.forEach(tpl => {
    const row = el('div', 'trow')
    const b = el('button', 'go', tpl.name); b.title = t('projects.pullInsert'); b.setAttribute('aria-label', b.title)
    b.onclick = () => insertPersonalResource(tpl).catch(e => toast(e.message))
    row.appendChild(b); p.appendChild(row)
  })
  if (docProject && !docResReadonly) { const create = el('button', null, t('projects.newResource')); create.onclick = () => newProjectResource(docProject).catch(e => toast(e.message)); p.appendChild(create) }
  if (shared) return
  const nw = el('button')
  nw.append(el('span', 'use', t('templates.newTpl')), el('span', 'ins', t('templates.newTplSub')))
  nw.onclick = newTemplate
  p.appendChild(nw)
  const up = el('button')
  up.append(el('span', 'use', t('templates.upOwn')), el('span', 'ins', t('templates.upOwnSub')))
  up.onclick = () => $('tplPick').click()
  p.appendChild(up)
}
async function newResource(kind) {
  const ext = kind === 'resource' ? await chooseFileType() : RES_EXT[kind]
  if (!ext) return
  const selected = await askNewTpl('file' + ext, true)
  const raw = selected?.name
  if (!raw?.trim()) return
  let name = raw.trim().replace(/[^A-Za-z0-9._-]/g, '_').replace(/^\.+/, '')
  if (!TEXT_EXT.test(name)) name += ext
  await loadTpl()
  if (myTpl.some(x => x.name === name)) { toast(t('common.nameExists')); return }
  const content = fileStart(name.split('.').pop().toLowerCase())
  try {
    const r = await api('POST', '/api/templates', { name, content, folder: selected.folder })
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
    const options = projectResources().flatMap(lib => {
      if (/\.bib$/i.test(lib.name)) return parseBib(lib.content || '').filter(e => e.key).map(e => ({ key: e.key, lib }))
      if (/\.ya?ml$/i.test(lib.name)) {
        try { const entries = CMV.parseYaml(lib.content || ''); return Object.entries(entries || {}).filter(([, v]) => v && typeof v === 'object' && typeof v.type === 'string').map(([key]) => ({ key, lib })) } catch (e) {}
      }
      return []
    })
    if (!options.length) { $('tplBtn').click(); return }
    const choice = await askPick(t('editor.citeLibrary'), options.map(x => [x.key, x.lib.name]))
    if (choice == null || !options[choice] || doc !== docId || resource !== tplName || file !== activeFile || epoch !== openN || !cm.state.facet(EditorView.editable)) return
    const { key, lib } = options[choice]
    if (!(ytext?.toString() || shadow).includes('"' + lib.name + '"')) mainAppend(`#bibliography("${lib.name}")`)
    addTpl('@' + key)
  }
}
