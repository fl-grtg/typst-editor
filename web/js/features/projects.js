// Projects own documents and their copied resource library.
function projectEditable(p) { return p.can_edit_library ?? ['owner', 'editor'].includes(p.role) }
function canStageProjectDelete(project) {
  const s = window.changeSession
  return !!s && s.project === project && !s.original && !s.busy && (!s.package || s.package.author === user || ['owner', 'editor'].includes(docRole))
}
function projectEntries(p) {
  const documents = p.documents || [...lastOwn, ...lastShared].filter(d => d.project_id === p.id)
  return { documents, resources: p.resources || [], files: p.files || [] }
}
function projectAction(host, icon, label, run) {
  const b = icoBtn('mini', icon); b.title = label; b.setAttribute('aria-label', label)
  b.onclick = e => { e.stopPropagation(); Promise.resolve().then(run).catch(e => toast(e.message)) }
  host.appendChild(b); return b
}
function compactSidebarActions(host, keep = 0) {
  const actions = [...host.children].filter(node => node.matches('button.mini')).slice(keep)
  if (actions.length < 2) return
  actions.forEach(button => button.remove())
  projectAction(host, ICO_MORE, t('shell.menuMore'), async () => {
    const s = window.changeSession
    const staged = s && host.closest('.project-group')?.dataset.projectId === s.project ? s.files.get(host.dataset.packageKey) : null
    if (staged?.action === 'delete') {
      const choice = await askPick(host.title || host.querySelector('.t')?.textContent || '', [[t('packages.discardFile'), '']])
      if (choice === 0) await discardSessionFile(staged)
      return
    }
    const choice = await askPick(host.title || host.querySelector('.t, b')?.textContent || '', actions.map(button => [button.title, '']))
    if (choice != null && !actions[choice]?.disabled) actions[choice]?.click()
  })
}
async function openProjectEntry(p, document, name, resource) {
  if (!document) {
    toast(t('projects.needsDocument'))
    document = await newProjectDoc(p.id)
    if (!document) return
  }
  if (docId !== document) await openDoc(document)
  if (docId !== document || docProject !== p.id) return
  if (name) {
    if (resource) {
      const epoch = openN
      if (!await loadDocResources(true) || docId !== document || docProject !== p.id || openN !== epoch) return
      tabPins.add(name)
    }
    await switchTab(resource ? TPLK + name : name)
  }
}
function paintProjects(box, shared) {
  projects.filter(p => (p.role !== 'owner') === shared).forEach(p => {
    const entries = projectEntries(p), group = el('div', 'project-group')
    group.dataset.projectId = p.id // anchor for session draft placement (paintSessionSidebar)
    projectDropTarget(group, p); box.appendChild(group)
    const h = el('div', 'fhd project'), key = 'project:' + p.id
    const title = el('b', null, p.title)
    title.title = p.title; title.setAttribute('role', 'button')
    title.setAttribute('aria-expanded', String(!shut.has(key)))
    const toggle = () => {
      shut.has(key) ? shut.delete(key) : shut.add(key); saveShut(); paintOwn(); paintShared(lastShared)
    }
    title.onclick = toggle; kb(title, toggle); h.appendChild(title)
    if (projectEditable(p)) {
      projectAction(h, ICO_PLUS, t('docs.newPick'), () => projectMenu(p))
    }
    if (p.role === 'owner') {
      projectAction(h, ICO_EDIT, t('projects.rename'), () => renameProject(p))
      projectAction(h, ICO_TRASH, t('common.delete'), () => deleteProject(p))
    }
    compactSidebarActions(h, 1)
    group.appendChild(h)
    if (shut.has(key)) return
    entries.documents.forEach(d => {
      const row = docRow({ ...d, project_id: p.id, role: d.role || p.role }, shared, true)
      row.dataset.packageKey = ['document', d.id, 'main.typ'].join(':')
      row.classList.add('sub'); row.classList.toggle('cur', d.id === docId && !activeFile);
      if (projectEditable(p)) projectAction(row, ICO_EDIT, t('docs.renameDoc'), () => renameProjectDocument(d))
      projectAction(row, ICO_MOVE, t('projects.transfer'), () => projectEntryMenu(p, { kind: 'document', doc_id: d.id, name: d.title }))
      compactSidebarActions(row)
      projectDrag(row, p, { kind: 'document', doc_id: d.id, name: d.title }); group.appendChild(row)
    })
    const entryRow = (name, document, resource) => {
      const row = el('div', 'doc sub' + ((resource ? docProject === p.id && activeFile === TPLK + name : docId === document && activeFile === name) ? ' cur' : '')); row.appendChild(el('span', 't', name)); row.title = name
      row.dataset.packageKey = [resource ? 'resource' : 'file', resource ? '' : document, name].join(':')
      const open = () => {
        return openProjectEntry(p, document, name, resource)
      }
      row.onclick = open; kb(row, open)
      projectAction(row, ICO_MOVE, t('projects.transfer'), () => projectEntryMenu(p, { kind: resource ? 'resource' : 'file', doc_id: document, name }))
      projectDrag(row, p, { kind: resource ? 'resource' : 'file', doc_id: document, name })
      if (projectEditable(p)) {
        projectAction(row, ICO_EDIT, t('docs.renameDoc'), () => renameProjectEntry(p, name, document, resource))
      }
      if (projectEditable(p) || canStageProjectDelete(p.id)) {
        projectAction(row, ICO_TRASH, t('common.delete'), () => deleteProjectEntry(p, name, document, resource))
      }
      compactSidebarActions(row)
      group.appendChild(row)
    }
    entries.resources.forEach(r => entryRow(r.name, entries.documents.find(d => d.id === docId)?.id || entries.documents[0]?.id, true))
    entries.files.forEach(f => entryRow(f.name, f.doc_id, false))
  })
}
async function newProjectDoc(id) {
  const choice = await askNewDoc()
  if (!choice?.title?.trim()) return
  const r = await api('POST', `/api/projects/${id}/docs`, { title: choice.title.trim(), content: galleryContent(choice.tpl) })
  shut.delete('project:' + id); saveShut()
  await openDoc(r.id)
  return r.id
}
async function newProjectResource(id) {
  const ext = await chooseFileType()
  if (!ext) return
  const raw = await ask(t('files.newFileHead'), { ph: t('files.newFilePh', { ext: ext.slice(1) }), maxLen: 240 })
  if (!raw?.trim()) return
  const name = raw.trim().toLowerCase().endsWith(ext) ? raw.trim() : raw.trim() + ext
  const result = await api('POST', `/api/projects/${id}/resources`, { name: name.trim(), content: fileStart(name.split('.').pop().toLowerCase()) })
  await sidebar()
  const project = projects.find(p => p.id === id) || await api('GET', `/api/projects/${id}`)
  const documents = projectEntries(project).documents
  const document = documents.find(d => d.id === docId)?.id || documents[0]?.id
  await openProjectEntry(project, document, result.name, true)
}
async function pullLibrary(source, target) {
  const document = docId, project = docProject, epoch = openN
  const current = () => docId === document && docProject === project && openN === epoch
  if (!await flushTab() || !await flushTpl() || !current()) return null
  const initial = target.scope === 'personal' ? source.source.split('/').pop() : source.source
  const name = await ask(t('projects.copyName'), { value: initial, maxLen: 240 })
  if (!name?.trim() || !current()) return null
  const body = { ...source, ...target, name: name.trim(), renames: {} }
  while (current()) {
    const preview = await api('POST', '/api/library/pull-preview', body)
    if (!current()) return null
    if (preview.collisions?.length) {
      toast(t('common.nameExists'))
      const files = preview.files || [{ source: source.source, name: body.name }]
      for (const file of files.filter(f => preview.collisions.includes(f.name))) {
        const replacement = await ask(t('projects.copyConflict') + '\n' + file.source, { value: file.name, maxLen: 240 })
        if (!replacement?.trim() || !current()) return null
        if (file.source === source.source) body.name = replacement.trim()
        else body.renames[file.source] = replacement.trim()
      }
      continue
    }
    const dependencies = preview.dependencies || []
    if (dependencies.length && !await ask(t('projects.copyWithDependencies') + '\n' + dependencies.join('\n'), { noInput: true })) return null
    if (!current()) return null
    const result = await api('POST', '/api/library/pull', { ...body, preview: preview.preview })
    await loadTpl(); if (current()) await loadDocResources(true); await sidebar()
    return result.name || body.name
  }
  return null
}

async function pullPersonalResource(name) {
  const targets = projects.filter(projectEditable)
  const i = await askPick(t('projects.pullProject'), targets.map(p => [p.title, '']))
  if (i == null || i < 0 || !targets[i]) return
  return pullLibrary({ source_scope: 'personal', source: name }, { scope: 'project', project_id: targets[i].id })
}
async function insertPersonalResource(tpl) {
  const document = docId, project = docProject, epoch = openN, file = activeFile
  if (!project || docResReadonly) return
  const name = await pullLibrary({ source_scope: 'personal', source: tpl.name }, { scope: 'project', project_id: project })
  if (!name || docId !== document || docProject !== project || openN !== epoch || activeFile !== file) return
  addTpl(resLine({ name }))
}
async function copyToLibrary(source, sourceDocId = docId, targetOverride = null) {
  const document = docId, epoch = openN
  const current = () => docId === document && openN === epoch
  try {
    if (!await flushTab() || !current()) return
    const targets = [{ scope: 'personal', title: t('projects.personalLibrary') }, ...projects.filter(projectEditable).map(p => ({ scope: 'project', project_id: p.id, title: p.title }))]
    const i = targetOverride ? 0 : await askPick(t('projects.copy'), targets.map(p => [p.title, '']))
    if (i == null || i < 0 || !targets[i]) return
    if (!current()) return
    const target = targetOverride || targets[i]
    const folder = ''
    let name = target.scope === 'personal' ? source.split('/').pop() : source
    while (docId === document && openN === epoch) {
      name = await ask(t('projects.copyName'), { value: name, maxLen: 240 })
      if (!name?.trim() || !current()) return
      const body = { source, scope: target.scope, ...(target.project_id ? { project_id: target.project_id } : {}), name: name.trim(), folder: folder.trim() }
      const url = `/api/docs/${sourceDocId}/library-copy`
      const preview = await api('POST', url + '-preview', body)
      if (!current()) return
      const collisions = preview.collisions || []
      if (collisions.length || Object.keys(collisions).length) { toast(t('common.nameExists')); continue }
      const dependencies = preview.dependencies || preview.deps || []
      if (dependencies.length && !await ask(t('projects.copyWithoutDependencies') + '\n' + dependencies.join('\n'), { noInput: true })) return
      if (!current()) return
      await api('POST', url, { ...body, preview: preview.preview })
      await loadTpl(); if (current()) { await loadDocResources(true); tabSig = ''; queueRender() }
      toast(t('projects.copied')); return
    }
  } catch (e) { toast(e.message) }
}

async function uploadProjectFiles(p, files) {
  if (!projectEditable(p)) return
  let attachmentDoc = projectEntries(p).documents.find(d => d.id === docId)?.id || projectEntries(p).documents[0]?.id
  try {
    for (const file of files) {
      if (/\.zip$/i.test(file.name)) {
        const title = await ask(t('docs.newDocTitle'), { value: file.name.replace(/\.zip$/i, '') })
        if (!title?.trim()) continue
        const body = new FormData(); body.append('f', file); body.append('title', title.trim())
        const response = await fetch(`/api/projects/${p.id}/import-zip`, { method: 'POST', body })
        if (!response.ok) throw new Error(expMsg(await response.text()))
        attachmentDoc ||= (await response.json()).id
      } else if (/\.typ$/i.test(file.name)) {
        const choice = await askPick(file.name, [[t('docs.pickDoc'), ''], [t('projects.newResource'), t('projects.newResourceHint')]])
        if (choice === 0) {
          const created = await api('POST', `/api/projects/${p.id}/docs`, { title: file.name, content: await file.text() })
          attachmentDoc ||= created.id
        } else if (choice === 1) await api('POST', `/api/projects/${p.id}/resources`, { name: file.name, content: await file.text() })
      } else if (TEXT_EXT.test(file.name)) await api('POST', `/api/projects/${p.id}/resources`, { name: file.name, content: await file.text() })
      else {
        if (!attachmentDoc) attachmentDoc = (await api('POST', `/api/projects/${p.id}/docs`, { title: t('projects.attachments'), content: '' })).id
        const existing = (await api('GET', `/api/docs/${attachmentDoc}/files`)).files
        const name = file.name.replace(/^[.]+/, '').replace(/[^A-Za-z0-9._ ()-]/g, '_').slice(0, 100)
        if (existing.some(f => f.name === name)) throw new Error(t('common.nameExists'))
        const body = new FormData(); body.append('f', file, name)
        const response = await fetch(`/api/docs/${attachmentDoc}/files`, { method: 'POST', body })
        if (!response.ok) throw new Error(expMsg(await response.text()))
      }
    }
  } finally {
    shut.delete('project:' + p.id); saveShut(); await sidebar()
    if (docProject === p.id && docId) {
      filesDirty = true
      lastFiles = (await api('GET', `/api/docs/${docId}/files`)).files
      mediaNames = lastFiles.map(f => f.name); renderMediaChips(lastFiles)
      await loadDocResources(true); queueRender()
    }
  }
}
async function uploadToProject(files) {
  const choices = projects.filter(projectEditable).slice().sort((a, b) => Number(b.id === docProject) - Number(a.id === docProject))
  const i = await askPick(t('files.uploadTarget'), [...choices.map(p => [p.title, '']), [t('projects.new'), '']])
  if (i == null || i < 0) return
  let project = choices[i]
  if (!project) {
    const title = await ask(t('projects.new'), { value: files[0].name.replace(/\.[^.]*$/, '') })
    if (!title?.trim()) return
    const created = await api('POST', '/api/projects', { title: title.trim() })
    await sidebar(); project = projects.find(p => p.id === created.id)
  }
  if (project) await uploadProjectFiles(project, files)
}

async function projectMenu(p) {
  const items = [[t('docs.newDocTitle'), t('docs.pickDocSub')], [t('projects.newResource'), t('projects.newResourceHint')], [t('docs.pickUp'), t('docs.pickUpSub')], [t('projects.fromPersonal'), t('projects.fromPersonalHint')]]
  const i = await askPick(p.title, items)
  if (i === 0) return newProjectDoc(p.id)
  if (i === 1) return newProjectResource(p.id)
  if (i === 2) {
    const picker = document.createElement('input'); picker.type = 'file'; picker.multiple = true
    picker.onchange = () => uploadProjectFiles(p, [...picker.files]).catch(e => toast(e.message))
    picker.click(); return
  }
  if (i === 3) {
    await loadTpl()
    const j = await askPick(t('projects.fromPersonal'), myTpl.map(r => [r.name, '']))
    if (j != null && myTpl[j]) return pullLibrary({ source_scope: 'personal', source: myTpl[j].name }, { scope: 'project', project_id: p.id })
  }
}
async function renameProject(p) {
  const title = await ask(t('projects.rename'), { value: p.title })
  if (title?.trim()) { await api('POST', `/api/projects/${p.id}/rename`, { title: title.trim() }); await sidebar() }
}
async function deleteProject(p) {
  if (!await ask(t('projects.deleteWarning'), { noInput: true, danger: true })) return
  await api('DELETE', `/api/projects/${p.id}`); await sidebar()
}
async function renameProjectDocument(d) {
  const title = await ask(t('docs.renameDoc'), { value: d.title })
  if (!title?.trim()) return
  await api('POST', `/api/docs/${d.id}/rename`, { title: title.trim() })
  if (docId === d.id) { $('title').textContent = title.trim(); docTitle = title.trim(); tabSig = ''; paintTabs() }
  await sidebar()
}
async function renameProjectEntry(p, name, document, resource) {
  if (!p) { toast(t('projects.contextGone')); return }
  const doc = docId, epoch = openN
  if (!await flushTab() || !await flushTpl()) return
  const next = await ask(t('projects.renameWarning'), { value: name, maxLen: 240 })
  if (!next?.trim() || next.trim() === name) return
  const body = { name, target: next.trim(), doc_id: resource ? '' : document }
  const preview = await api('POST', `/api/projects/${p.id}/rename-entry-preview`, body)
  if (doc !== docId || epoch !== openN) return
  const details = [t('projects.renameReferences', { name: preview.name }), ...(preview.references.length ? preview.references : [t('projects.noReferences')]), t('projects.dynamicReferences')].join('\n')
  if (!await ask(details, { noInput: true }) || doc !== docId || epoch !== openN) return
  const result = await api('POST', `/api/projects/${p.id}/rename-entry`, { ...body, target: preview.name, version: preview.version })
  if (docId === doc && openN === epoch && docProject === p.id) {
    const old = resource ? TPLK + name : name, next = resource ? TPLK + result.name : result.name
    if (activeFile === old && (resource || document === docId)) {
      clearTimeout(fileT); activeFile = next
      const state = tabState.get(old); if (state) tabState.set(next, state)
      tabState.delete(old); tabVersions.delete(old); tabVersions.set(next, result.version)
      if (resource) { tabPins.delete(name); tabPins.add(result.name) }
      else { const cached = fileCache.get(old); if (cached) fileCache.set(next, cached); fileCache.delete(old) }
      if (tabDirty) queueFileSave()
    }
    filesDirty = true; await loadDocResources(true); tabSig = ''; queueRender()
  }
  await sidebar()
  toast(t('files.renamed', { name: result.name }))
}
async function deleteProjectEntry(p, name, document, resource) {
  if (!p) { toast(t('projects.contextGone')); return }
  const doc = docId, epoch = openN
  if (!await ask(t('files.delConfirm', { name }), { noInput: true, danger: true })) return
  if (resource) {
    const current = (await api('GET', `/api/projects/${p.id}/resources`)).resources.find(r => r.name === name)
    if (!current) { toast(t('files.tplGone')); await sidebar(); return }
    await api('DELETE', `/api/projects/${p.id}/resources/${encodeURIComponent(name)}?version=${encodeURIComponent((current.updated_at || current.version))}`)
  } else await api('DELETE', `/api/docs/${document}/files/${encodeURIComponent(name)}`)
  if (docId === doc && openN === epoch && docProject === p.id) {
    if (activeFile === (resource ? TPLK + name : name) && (resource || document === docId) && !tabDirty) await switchTab('', true)
    filesDirty = true; await loadDocResources(true); queueRender()
  }
  await sidebar()
}

async function projectEntryMenu(p, entry) {
  const actions = ['copy'], items = [[t('projects.copyProject'), t('projects.copyProjectHint')]]
  if (projectEditable(p)) {
    actions.unshift('duplicate'); items.unshift([t('docs.duplicate'), t('projects.duplicateHint', { name: copyDisplayName(entry.name) })])
    actions.push('move'); items.push([t('projects.moveProject'), t('projects.moveProjectHint')])
  }
  if (entry.kind === 'resource' || entry.kind === 'file' && TEXT_EXT.test(entry.name)) { actions.push('global'); items.push([t('projects.pullPersonal'), t('projects.pullPersonalHint')]) }
  const i = await askPick(entry.name, items)
  if (i == null || !actions[i]) return
  if (actions[i] === 'duplicate') {
    if (!await flushTab() || !await flushTpl()) return
    await api('POST', `/api/projects/${p.id}/transfer`, { ...entry, target_project_id: p.id, target_doc_id: entry.doc_id || '', duplicate: true })
    await sidebar(); filesDirty = true; if (docId) { await loadDocResources(true); queueRender() }
    return
  }
  if (actions[i] === 'global') {
    if (entry.kind === 'resource') return pullLibrary({ source_scope: 'project', source_project_id: p.id, source: entry.name }, { scope: 'personal' })
    return copyToLibrary(entry.name, entry.doc_id, { scope: 'personal' })
  }
  return transferProjectEntry(p, entry, actions[i] === 'move')
}
async function transferProjectEntry(p, entry, move, selectedTarget, direct = false) {
  if (!await flushTab() || !await flushTpl()) return
  let target = selectedTarget
  if (!target) {
    const targets = projects.filter(projectEditable)
    const i = await askPick(t(move ? 'projects.moveProject' : 'projects.copyProject'), targets.map(p => [p.title, '']))
    if (i == null || !targets[i]) return
    target = targets[i]
  }
  let targetDoc = ''
  if (entry.kind === 'file') {
    const docs = projectEntries(target).documents
    if (!docs.length) { toast(t('projects.uploadNeedsDoc')); return }
    targetDoc = docs.find(d => d.id === entry.doc_id)?.id || docs.find(d => d.id === docId)?.id || docs[0].id
  }
  if (direct && p.id === target.id && move) return
  let name = entry.name
  while (true) {
    if (!direct) name = await ask(t('projects.copyName'), { value: name, maxLen: entry.kind === 'document' ? 100 : 240 })
    if (!name?.trim()) return
    try {
      const result = await api('POST', `/api/projects/${p.id}/transfer`, { ...entry, target_project_id: target.id, target_doc_id: targetDoc, target_name: name.trim(), move, duplicate: direct && !move && p.id === target.id })
      await sidebar(); filesDirty = true
      if (docId) { await loadDocResources(true); tabSig = ''; queueRender() }
      if (entry.kind === 'document' && move && docId === entry.doc_id) await openDoc(result.doc_id)
      return
    } catch (e) {
      if (e.status !== 409) throw e
      toast(e.message)
      direct = false
    }
  }
}
function projectDrag(row, p, entry) {
  sidebarDrag(row, { project: p.id, entry }, projectEditable(p) ? 'copyMove' : 'copy')
}
function projectDropTarget(row, target) {
  if (!projectEditable(target)) return
  row.ondragover = e => { if (e.dataTransfer.types.includes('Files') || e.dataTransfer.types.includes('application/x-typst-project-entry')) { e.preventDefault(); e.stopPropagation(); row.classList.add('drop-target'); e.dataTransfer.dropEffect = e.dataTransfer.types.includes('Files') || sidebarDragData?.personal || e.ctrlKey || e.metaKey ? 'copy' : 'move' } }
  row.ondragleave = e => { if (!row.contains(e.relatedTarget)) row.classList.remove('drop-target') }
  row.ondrop = async e => {
    if (!e.dataTransfer.files.length && !e.dataTransfer.types.includes('application/x-typst-project-entry')) return
    e.preventDefault(); e.stopPropagation(); row.classList.remove('drop-target')
    try {
      if (e.dataTransfer.files.length) { await uploadProjectFiles(target, [...e.dataTransfer.files]); return }
      const data = JSON.parse(e.dataTransfer.getData('application/x-typst-project-entry'))
      if (data.trashed) { await restoreSidebarDocument(data, target); return }
      if (data.personal) { await pullLibrary({ source_scope: 'personal', source: data.entry.name }, { scope: 'project', project_id: target.id }); return }
      const source = projects.find(p => p.id === data.project)
      if (source) await transferProjectEntry(source, data.entry, projectEditable(source) && !e.ctrlKey && !e.metaKey, target, true)
    } catch (error) { toast(error.message) }
  }
}

async function renamePersonalResource(name) {
  const editing = tplName === name
  if (editing && !await flushTpl()) return
  const target = await ask(t('templates.renameTpl'), { value: name, maxLen: 100 })
  if (!target?.trim() || target.trim() === name) return
  try {
  await loadTpl()
  const source = myTpl.find(r => r.name === name)
  if (!source) return
  const result = await api('POST', '/api/templates/' + encodeURIComponent(name) + '/rename', { name: target.trim(), version: source.updated_at })
  if (editing && tplName === name) { tplName = result.name; tplVer = result.version; $('title').textContent = result.name }
  await loadTpl(); await sidebar()
  } catch (e) { toast(e.message) }
}
async function duplicatePersonalResource(name) {
  if (tplName === name && !await flushTpl()) return
  await api('POST', '/api/templates/' + encodeURIComponent(name) + '/duplicate', {})
  await loadTpl(); await sidebar()
}

function copyDisplayName(name) {
  const dot = name.lastIndexOf('.')
  const extension = dot > name.lastIndexOf('/') + 1
  return t('projects.duplicateName', { stem: extension ? name.slice(0, dot) : name, ext: extension ? name.slice(dot) : '' })
}
