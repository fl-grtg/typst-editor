// Sidebar transfers reuse the same copy/restore actions as the menus.
const SIDEBAR_DRAG = 'application/x-typst-project-entry'
let sidebarDragData = null, sidebarDropWatch = null
function sidebarWatchDrop() { // OS-file drags: no dragend reaches our rows, drops can land outside every row
  if (sidebarDropWatch || typeof addEventListener !== 'function') return
  const clear = () => {
    sidebarDropWatch = null
    removeEventListener('drop', clear, true); removeEventListener('dragend', clear, true)
    document.querySelectorAll('.drop-target').forEach(node => node.classList.remove('drop-target'))
  }
  sidebarDropWatch = clear
  addEventListener('drop', clear, true); addEventListener('dragend', clear, true)
}
function sidebarCanDrop(data, target) {
  if (!data?.entry) return false
  if (target === 'trash') return ['document', 'resource', 'file'].includes(data.entry.kind) && !data.trashed
  if (target === 'documents') return !!data.trashed && data.entry.kind === 'document' && !data.trashId
  if (data.trashed) return !!data.trashId && (data.entry.kind !== 'file' || TEXT_EXT.test(data.entry.name))
  return !data.trashed && !data.personal && (data.entry.kind === 'resource' || data.entry.kind === 'file' && TEXT_EXT.test(data.entry.name))
}
function sidebarDrag(row, data, effect = 'copy') {
  row.draggable = true
  row.ondragstart = e => {
    if (e.target.closest('button,input')) { e.preventDefault(); return }
    e.stopPropagation(); sidebarDragData = data
    e.dataTransfer.setData(SIDEBAR_DRAG, JSON.stringify(data)); e.dataTransfer.effectAllowed = effect
  }
  row.ondragend = () => { sidebarDragData = null; document.querySelectorAll('.drop-target').forEach(node => node.classList.remove('drop-target')) }
}
function sidebarDropTarget(row, target) {
  row.ondragover = e => {
    const types = e.dataTransfer.types
    if (sidebarDragData && !sidebarCanDrop(sidebarDragData, target)) return
    if (!(types.includes(SIDEBAR_DRAG) || target !== 'trash' && types.includes('Files'))) return
    e.preventDefault(); e.stopPropagation(); row.classList.add('drop-target'); sidebarWatchDrop()
    e.dataTransfer.dropEffect = target === 'trash' || sidebarDragData?.trashed ? 'move' : 'copy'
  }
  row.ondragleave = e => { if (!row.contains(e.relatedTarget)) row.classList.remove('drop-target') }
  row.ondrop = async e => {
    if (!e.dataTransfer.types.includes(SIDEBAR_DRAG) && !e.dataTransfer.files.length) return
    e.preventDefault(); e.stopPropagation(); row.classList.remove('drop-target')
    try {
      if (e.dataTransfer.files.length) {
        if (target === 'modules') await uploadModuleFiles([...e.dataTransfer.files])
        else if (target === 'documents') await uploadToProject([...e.dataTransfer.files])
        return
      }
      const data = JSON.parse(e.dataTransfer.getData(SIDEBAR_DRAG))
      if (!sidebarCanDrop(data, target)) return
      if (target === 'trash') await trashSidebarEntry(data)
      else if (target === 'documents' && data.trashed) await restoreSidebarDocument(data)
      else if (target === 'modules' && data.trashed) await restoreSidebarDocument(data, null, true)
      else if (target === 'modules' && !data.trashed && !data.personal) {
        if (data.entry?.kind === 'resource') await pullLibrary({ source_scope: 'project', source_project_id: data.project, source: data.entry.name }, { scope: 'personal' })
        else if (data.entry?.kind === 'file' && TEXT_EXT.test(data.entry.name)) await copyToLibrary(data.entry.name, data.entry.doc_id, { scope: 'personal' })
      }
    } catch (error) { toast(error.message) }
  }
}
const TRASH_KINDS = new Set(['personal', 'resource', 'file'])
function trashEntryUrl(entry) { return (TRASH_KINDS.has(entry.kind) ? '/api/trash/' : '/api/docs/') + entry.id }
async function trashSidebarEntry(data) {
  if (data.entry.kind === 'document') return trashSidebarDocument(data.entry.doc_id)
  if (data.personal) {
    if (!await flushTpl()) return
    await api('DELETE', '/api/templates/' + encodeURIComponent(data.entry.name))
    if (tplName === data.entry.name) { clearTimeout(tplT); tplDirty = false; closeView() }
    await loadTpl(); await sidebar()
  } else {
    if (!await flushTab() || !await flushTpl()) return
    const project = projects.find(p => p.id === data.project)
    await deleteProjectEntry(project, data.entry.name, data.entry.doc_id, data.entry.kind === 'resource')
  }
}
async function trashSidebarDocument(document) {
  if (docId === document && window.suggestionDraft && !await leaveSuggestionDraft()) return
  if (!await flushTab() || !await flushTpl()) return
  await api('POST', '/api/docs/' + document + '/trash', {})
  if (docId === document) closeView()
  await sidebar()
}
async function restoreSidebarDocument(data, target = null, modules = false) {
  const document = data.entry.doc_id
  const result = await api('POST', data.trashId ? '/api/trash/' + data.trashId + '/restore' : '/api/docs/' + document + '/restore', {})
  if (data.trashId) {
    await loadTpl(); await sidebar()
    if (target && result.kind === 'personal') return pullLibrary({ source_scope: 'personal', source: result.name }, { scope: 'project', project_id: target.id })
    if (modules && result.kind === 'resource') return pullLibrary({ source_scope: 'project', source_project_id: result.project_id, source: result.name }, { scope: 'personal' })
    if (modules && result.kind === 'file') return copyToLibrary(result.name, result.doc_id, { scope: 'personal' })
    if (target && result.project_id && result.project_id !== target.id) {
      const source = projects.find(p => p.id === result.project_id)
      if (source) await transferProjectEntry(source, { kind: result.kind, name: result.name, doc_id: result.doc_id }, true, target, true)
    }
    if (docId === result.doc_id || docProject === result.project_id) { filesDirty = true; await loadDocResources(true); queueRender() }
    return
  }
  await sidebar()
  if (target) {
    const restored = lastOwn.find(d => d.id === document)
    if (restored && restored.project_id !== target.id) {
      const source = projects.find(p => p.id === restored.project_id)
      if (!source) return
      await transferProjectEntry(source, { kind: 'document', doc_id: document, name: restored.title }, true, target, true)
    }
  }
  if (docId === document && openedTrashed) await openDoc(document)
}
async function uploadModuleFiles(files) {
  try {
    for (const file of files) {
      if (!TEXT_EXT.test(file.name)) { await uploadToProject([file]); continue }
      if (file.size > 200 * 1024) { toast(t('files.maxText')); continue }
      if (/\.typ$/i.test(file.name)) {
        const choice = await askPick(file.name, [[t('docs.pickDoc'), ''], [t('projects.newResource'), t('projects.newResourceHint')]])
        if (choice !== 0 && choice !== 1) continue
        if (choice === 0) {
          const result = await api('POST', '/api/docs/create', { title: file.name.replace(/\.typ$/i, '').slice(0, 100), content: await file.text(), folder: '' })
          await openDoc(result.id); continue
        }
      }
      await loadTpl()
      let name = file.name
      while (myTpl.some(r => r.name === name)) {
        name = await ask(t('projects.copyConflict'), { value: name, maxLen: 100 })
        if (!name?.trim()) break
        name = name.trim()
      }
      if (!name?.trim()) continue
      try { await api('POST', '/api/templates', { name, content: await file.text(), folder: '' }) }
      catch (error) { toast(error.message) }
    }
  } finally { await loadTpl(); await sidebar() }
}
