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
  b.onclick = e => { e.stopPropagation(); Promise.resolve().then(() => run(e)).catch(e => toast(e.message)) }
  host.appendChild(b); return b
}
function sidebarLiveHost(host, key) { // row actions can outlive a sidebar repaint (open menu, then a remote change)
  if (!host || host.isConnected) return host
  if (!key && host.dataset.folderPath) { // folder row: same project, same path
    const pid = host.closest('[data-project-id]')?.dataset.projectId
    const group = pid && [...document.querySelectorAll('[data-project-id]')].find(g => g.dataset.projectId === pid)
    const row = group && [...group.querySelectorAll('.fhd.folder')].find(r => r.dataset.folderPath === host.dataset.folderPath)
    if (row) return row
  }
  return key ? [...document.querySelectorAll('[data-package-key]')].find(row => row.dataset.packageKey === key) || host : host
}
const SIDEBAR_MENU = {
  rename: ['menu.renameShort', 'menu.renameHint'],
  duplicate: ['menu.duplicateShort', 'menu.duplicateHint'],
  copy: ['menu.copyTo', 'menu.copyToHint'],
  move: ['menu.moveTo', 'menu.moveToHint'],
  useInProject: ['menu.useInProject', 'menu.useInProjectHint'],
  trash: ['menu.actionTrash', 'menu.trashHint'],
}
const MENU_WHAT = { file: 'menu.whatFile', folder: 'menu.whatFolder', document: 'menu.whatDocument', module: 'menu.whatModule', project: 'menu.whatProject' }
function menuWhat(what) { return what && MENU_WHAT[what] ? t(MENU_WHAT[what]) : '' }
function sidebarMenuItem(key, run, extra = {}) {
  const { what, ...rest } = extra
  const [label, title] = SIDEBAR_MENU[key]
  return { label: t(label), title: t(title, { what: menuWhat(what) }), danger: key === 'trash', run, ...rest }
}
function menuButtonItem(button, what) {
  const hint = button.dataset.menuHint
  return {
    label: button.dataset.menuLabel || button.title,
    title: hint ? t(hint, { what: menuWhat(what) }) : button.title,
    danger: button.dataset.menuDanger !== undefined,
    disabled: button.disabled,
    run: () => button.click(),
  }
}
function personalModuleMenu(actions) {
  const by = key => actions.find(button => button.dataset.menuKey === key)
  return [
    by('rename') && menuButtonItem(by('rename'), 'module'),
    by('duplicate') && menuButtonItem(by('duplicate'), 'module'),
    by('use') && menuButtonItem(by('use'), 'module'),
    by('trash') && menuButtonItem(by('trash'), 'module'),
  ].filter(Boolean)
}
function compactSidebarActions(host, keep = 0, decorate = null) {
  const actions = [...host.children].filter(node => node.matches('button.mini') && node.dataset.menuSkip === undefined).slice(keep)
  if (!actions.length && !decorate) return // a decorated menu can offer actions without row buttons (read-only members still copy out)
  actions.forEach(button => button.remove()) // only the three-dot stays: no hidden icons stealing clicks
  const more = icoBtn('mini', ICO_MORE)
  more.title = t('shell.menuMore'); more.setAttribute('aria-label', more.title)
  more.setAttribute('aria-haspopup', 'menu'); more.setAttribute('aria-expanded', 'false')
  more.dataset.sideMenu = '' // ui-layer opens the dropdown below the button
  more.sideMenuItems = () => {
    const s = window.changeSession
    const staged = s && host.closest('.project-group')?.dataset.projectId === s.project ? s.files.get(host.dataset.packageKey) : null
    if (staged?.action === 'delete') return [{ label: t('packages.discardFile'), danger: true, run: () => discardSessionFile(staged).catch(e => toast(e.message)) }]
    return decorate ? decorate(actions) : actions.map(menuButtonItem)
  }
  if (!more.sideMenuItems().length) return // e.g. folder row in a change/suggestion session: no dead three-dot
  host.appendChild(more)
}
function nameStemStart(name) { // path inputs select only the name, never the folder part
  return String(name).lastIndexOf('/') + 1
}
function nameStemEnd(name) { // file name without extension: selection ends before the last dot
  const dot = String(name).lastIndexOf('.')
  return dot > String(name).lastIndexOf('/') + 1 ? dot : String(name).length
}
function sidebarInlineRename(host, label, value, opts = {}) { // rename in place: Enter/blur saves, Esc cancels
  const input = el('input', 'renameInput')
  input.value = value; input.maxLength = opts.maxLen || 240
  input.setAttribute('aria-label', opts.label || t('shell.rename'))
  input.spellcheck = false
  const wasDraggable = host.draggable // dragging the row would swallow text selection
  host.draggable = false
  label.replaceWith(input)
  host.classList.add('renaming')
  return new Promise(resolve => {
    let done = false
    const finish = (save, refocus = false) => {
      if (done) return
      done = true
      const next = input.value.trim()
      const deferred = window.__sidebarDeferred
      input.replaceWith(label)
      host.draggable = wasDraggable
      host.classList.remove('renaming')
      if (refocus) { // Esc/Enter keep keyboard context: label or row, whichever is focusable
        const target = label.hasAttribute('tabindex') ? label : host
        try { target.focus({ preventScroll: true }) } catch (e) {}
      }
      resolve(save && next && next !== value ? next : null)
      if (deferred && !document.querySelector('aside input.renameInput')) {
        window.__sidebarDeferred = false
        setTimeout(() => sidebar(), 0)
      }
    }
    input.onclick = e => e.stopPropagation()
    input.ondblclick = e => e.stopPropagation()
    input.ondragstart = e => e.preventDefault() // dragging the auto-selected text must extend the selection, not start a text drag
    input.onmousedown = () => { if (input.selectionStart !== input.selectionEnd) input.setSelectionRange(input.selectionStart, input.selectionStart) } // drop the auto-selection before the browser starts a text drag
    input.onkeydown = e => {
      if (e.key === 'Enter') { e.preventDefault(); finish(true, true) }
      else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); finish(false, true) }
    }
    input.onblur = () => finish(true)
    setTimeout(() => { input.focus(); input.setSelectionRange(opts.stem ? nameStemStart(value) : 0, opts.stem ? nameStemEnd(value) : value.length) }, 0)
  })
}
const projectEntryFlights = new Map()
function openProjectEntry(p, document, name, resource) {
  const key = JSON.stringify([p.id, document, name, resource])
  if (projectEntryFlights.has(key)) return projectEntryFlights.get(key)
  const flight = openProjectEntryOnce(p, document, name, resource).finally(() => projectEntryFlights.delete(key))
  projectEntryFlights.set(key, flight)
  return flight
}
async function openProjectEntryOnce(p, document, name, resource) {
  if (!document) {
    toast(t('projects.needsDocument'))
    document = await newProjectDoc(p.id)
    if (!document) return
  }
  if (docId !== document) await openDoc(document)
  if (docId !== document || docProject !== p.id) return
  if (name) {
    if (activeFile === (resource ? TPLK + name : name)) return
    if (resource && !window.changeSession) {
      const epoch = openN
      let loaded = false
      for (let attempt = 0; attempt < 3 && !loaded; attempt++) { // a poll may supersede the list load; retry while the doc is unchanged
        loaded = await loadDocResources(true)
        if (docId !== document || docProject !== p.id || openN !== epoch) return
      }
      if (!loaded) return
      tabPins.add(name)
    }
    await switchTab(resource ? TPLK + name : name)
  }
}
const FOLDER_LEVELS = 2 // folder levels inside a project (a/b/file); deeper legacy paths fold into the last level
function splitEntryPath(name) { // 'a/b/x.typ' -> { dir: 'a/b', base: 'x.typ' }, clamped to FOLDER_LEVELS
  const parts = String(name).split('/').filter(Boolean), dirs = parts.slice(0, -1).slice(0, FOLDER_LEVELS)
  return { dir: dirs.join('/'), base: parts.slice(dirs.length).join('/') }
}
const folderParents = path => { const parts = path.split('/'); return parts.map((_, i) => parts.slice(0, i + 1).join('/')) }
function projectTree(p, entries) { // folders (explicit + implied by paths) and the entries inside each one
  const items = [
    ...entries.documents.map(d => ({ kind: 'document', dir: String(d.folder || '').split('/').filter(Boolean).slice(0, FOLDER_LEVELS).join('/'), label: d.title, d })),
    ...entries.resources.map(r => ({ kind: 'resource', resource: true, name: r.name, document: entries.documents.find(d => d.id === docId)?.id || entries.documents[0]?.id, ...(x => ({ dir: x.dir, label: x.base }))(splitEntryPath(r.name)) })),
    ...entries.files.map(f => ({ kind: 'file', resource: false, name: f.name, document: f.doc_id, ...(x => ({ dir: x.dir, label: x.base }))(splitEntryPath(f.name)) })),
  ]
  const known = new Set()
  for (const f of (p.folders || [])) folderParents(f.split('/').slice(0, FOLDER_LEVELS).join('/')).forEach(x => known.add(x))
  for (const it of items) if (it.dir) folderParents(it.dir).forEach(x => known.add(x))
  const sorted = [...known].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }))
  return {
    folders: dir => sorted.filter(f => f.includes('/') ? f.slice(0, f.lastIndexOf('/')) === dir : dir === ''),
    items: dir => items.filter(i => i.dir === dir),
    all: sorted,
    dirOf(entry) { // folder an entry sits in (for reveal / drop)
      return items.find(i => i.kind === entry.kind && (entry.kind === 'document' ? i.d.id === entry.doc_id : i.name === entry.name && (i.kind === 'resource' || i.document === entry.doc_id)))?.dir || ''
    },
  }
}
let lastReveal = ''
function revealActiveFolder(p, tree) { // opening a file shows its folder: unfold once per change of the active file
  if (docProject !== p.id) return
  const entry = activeFile ? (isTplKey(activeFile) ? { kind: 'resource', name: tabName(activeFile) } : { kind: 'file', name: activeFile, doc_id: docId }) : { kind: 'document', doc_id: docId }
  const key = p.id + '\u0001' + docId + '\u0001' + activeFile
  if (key === lastReveal) return
  lastReveal = key
  const dir = tree.dirOf(entry)
  if (dir) { for (const f of folderParents(dir)) shut.delete('folder:' + p.id + ':' + f); saveShut() }
}
function paintProjects(box, shared) {
  projects.filter(p => (p.role !== 'owner') === shared).forEach(p => {
    const entries = projectEntries(p), group = el('div', 'project-group')
    group.dataset.projectId = p.id // anchor for session draft placement (paintSessionSidebar)
    box.appendChild(group)
    const h = el('div', 'fhd project'), key = 'project:' + p.id
    const title = el('b', null, p.title)
    title.title = p.title; title.setAttribute('role', 'button')
    title.setAttribute('aria-expanded', String(!shut.has(key)))
    const toggle = async () => {
      const opening = shut.has(key)
      opening ? shut.delete(key) : shut.add(key); saveShut(); paintOwn(); paintShared(lastShared)
      if (opening && !docId && !tplName && entries.documents[0]) await openDoc(entries.documents[0].id)
    }
    title.onclick = toggle; kb(title, toggle); h.appendChild(title)
    if (projectEditable(p)) {
      const add = projectAction(h, ICO_PLUS, t('docs.newPick'), () => projectMenu(p, '', add))
      add.setAttribute('aria-haspopup', 'menu'); add.setAttribute('aria-expanded', 'false')
    }
    const wl = watchLevels[p.id] || WATCH_DEFAULT
    const bell = projectAction(h, watchIcon(wl), t('inbox.watchBtn', { level: watchLabel(wl) }), () => openWatchBox(p, bell))
    bell.setAttribute('aria-haspopup', 'menu'); bell.setAttribute('aria-expanded', 'false'); bell.dataset.watchBtn = ''; bell.dataset.menuLabel = t('inbox.watchMenu')
    if (p.role === 'owner') {
      const rename = projectAction(h, ICO_EDIT, t('projects.rename'), () => renameProject(p, h))
      rename.dataset.menuLabel = t('menu.renameShort'); rename.dataset.menuHint = 'menu.renameHint'
      const trash = projectAction(h, ICO_TRASH, t('projects.moveProjectTrash'), () => deleteProject(p))
      trash.dataset.menuDanger = ''; trash.dataset.menuLabel = t('menu.actionTrash'); trash.dataset.menuHint = 'menu.trashHint'
    }
    compactSidebarActions(h, projectEditable(p) ? 2 : 1, actions => actions.map(button => menuButtonItem(button, 'project')))
    projectDropTarget(h, p) // header = project root; only this row lights up, not the whole group
    group.appendChild(h)
    if (shut.has(key)) return
    const tree = projectTree(p, entries)
    group.classList.toggle('with-folders', tree.all.length > 0)
    const folderRows = new Map() // a drop anywhere inside a folder lights up its header, not the whole group
    const dropVisual = folder => (folder && folderRows.get(folder)) || h
    const entryRow = (item, level, folder) => {
      const { name, document, resource } = item
      const row = el('div', 'doc sub' + ((resource ? docProject === p.id && activeFile === TPLK + name : docId === document && activeFile === name) ? ' cur' : '')); row.appendChild(el('span', 't', item.label)); row.title = name
      row.style.setProperty('--lv', level)
      row.dataset.packageKey = [resource ? 'resource' : 'file', resource ? '' : document, name].join(':')
      const open = () => {
        return openProjectEntry(p, document, name, resource)
      }
      row.onclick = open; kb(row, open)
      const entry = { kind: resource ? 'resource' : 'file', doc_id: document, name }
      if (projectEditable(p)) {
        const rename = projectAction(row, ICO_EDIT, t('files.renameHead'), () => renameProjectEntry(p, name, document, resource, row))
        rename.dataset.menuKey = 'rename'; rename.dataset.menuLabel = t('menu.renameShort'); rename.dataset.menuHint = 'menu.renameHint'
      }
      projectDrag(row, p, { ...entry, folder: name.split('/').slice(0, -1).join('/') })
      projectDropTarget(row, p, folder, dropVisual(folder)) // dropping on a file targets the folder it lives in
      if (projectEditable(p) || canStageProjectDelete(p.id)) {
        const trash = projectAction(row, ICO_TRASH, t('docs.moveTrash'), () => deleteProjectEntry(p, name, document, resource))
        trash.dataset.menuDanger = ''; trash.dataset.menuKey = 'trash'; trash.dataset.menuLabel = t('menu.actionTrash'); trash.dataset.menuHint = 'menu.trashHint'
      }
      compactSidebarActions(row, 0, actions => entryMenuItems(p, entry, actions))
      group.appendChild(row)
    }
    const documentRow = (d, level, folder) => {
      const row = docRow({ ...d, project_id: p.id, role: d.role || p.role }, shared, true)
      row.dataset.packageKey = ['document', d.id, 'main.typ'].join(':')
      row.classList.add('sub'); row.classList.toggle('cur', d.id === docId && !activeFile); row.style.setProperty('--lv', level)
      const first = row.querySelector('button.mini')
      if (projectEditable(p)) {
        const rename = projectAction(row, ICO_EDIT, t('docs.renameDoc'), () => renameProjectDocument(d, row))
        rename.dataset.menuKey = 'rename'; rename.dataset.menuLabel = t('menu.renameShort'); rename.dataset.menuHint = 'menu.renameHint'
        row.insertBefore(rename, first)
      }
      const trash = row.querySelector('button[data-menu-danger]')
      if (trash) { trash.dataset.menuKey = 'trash'; trash.dataset.menuLabel = t('menu.actionTrash'); trash.dataset.menuHint = 'menu.trashHint' }
      compactSidebarActions(row, 0, actions => entryMenuItems(p, { kind: 'document', doc_id: d.id, name: d.title, folder: d.folder || '' }, actions))
      projectDropTarget(row, p, folder, dropVisual(folder)) // dropping on a document targets the folder it lives in
      projectDrag(row, p, { kind: 'document', doc_id: d.id, name: d.title, folder: d.folder || '' }); group.appendChild(row)
    }
    const folderRow = (path, level) => {
      const fkey = 'folder:' + p.id + ':' + path, base = path.split('/').pop()
      const row = el('div', 'fhd folder'), label = el('b', null, base)
      row.style.setProperty('--lv', level); row.dataset.folderPath = path
      folderRows.set(path, row)
      label.title = path; label.setAttribute('role', 'button'); label.setAttribute('aria-expanded', String(!shut.has(fkey)))
      const toggle = () => { shut.has(fkey) ? shut.delete(fkey) : shut.add(fkey); saveShut(); paintOwn(); paintShared(lastShared) }
      label.onclick = toggle; kb(label, toggle); row.appendChild(label)
      if (projectEditable(p)) {
        const add = projectAction(row, ICO_PLUS, t('docs.newPick'), () => projectMenu(p, path, add))
        add.setAttribute('aria-haspopup', 'menu'); add.setAttribute('aria-expanded', 'false')
        const rename = projectAction(row, ICO_EDIT, t('projects.renameFolder'), () => renameFolder(p, path, row))
        rename.dataset.menuKey = 'rename'; rename.dataset.menuLabel = t('menu.renameShort'); rename.dataset.menuHint = 'menu.renameHint'
        const trash = projectAction(row, ICO_TRASH, t('projects.deleteFolder'), () => deleteFolder(p, path))
        trash.dataset.menuDanger = ''; trash.dataset.menuKey = 'trash'; trash.dataset.menuLabel = t('menu.actionTrash'); trash.dataset.menuHint = 'menu.trashHint'
      }
      compactSidebarActions(row, 1, actions => folderMenuItems(p, path, actions))
      projectDrag(row, p, { kind: 'folder', name: path }) // folders move/copy like entries; the drop target rejects descendants
      projectDropTarget(row, p, path)
      group.appendChild(row)
      return !shut.has(fkey)
    }
    const paintDir = (dir, level) => {
      for (const f of tree.folders(dir)) {
        if (!folderRow(f, level)) continue
        paintDir(f, level + 1)
        if (!tree.folders(f).length && !tree.items(f).length) {
          const empty = el('div', 'folderEmpty', t('docs.folderEmpty'))
          empty.style.setProperty('--lv', level + 1)
          projectDropTarget(empty, p, f, dropVisual(f)) // the empty hint is a drop area for that folder
          group.appendChild(empty)
        }
      }
      for (const item of tree.items(dir)) item.kind === 'document' ? documentRow(item.d, level, dir) : entryRow(item, level, dir)
    }
    revealActiveFolder(p, tree)
    paintDir('', 0)
  })
}
async function newProjectDoc(id, folder = '') {
  const choice = await askNewDoc()
  if (!choice?.title?.trim()) return
  const r = await api('POST', `/api/projects/${id}/docs`, { title: choice.title.trim(), content: galleryContent(choice.tpl), folder })
  shut.delete('project:' + id); saveShut()
  await openDoc(r.id)
  return r.id
}
async function newProjectResource(id, folder = '', chosenExt = '') {
  const ext = chosenExt || await chooseFileType()
  if (!ext) return
  // Start with "file.<ext>" and keep only the stem selected: typing replaces
  // the suggested name and the extension stays in place.
  const raw = await ask(t('files.newFileHead'), { value: 'file' + ext, ph: t('files.newFilePh', { ext: ext.slice(1) }), maxLen: 240, stem: true })
  if (!raw?.trim()) return
  const typed = raw.trim().replace(/^\/+/, ''), file = typed.toLowerCase().endsWith(ext) ? typed : typed + ext
  const name = folder ? folder + '/' + file : file
  const result = await api('POST', `/api/projects/${id}/resources`, { name: name.trim(), content: fileStart(name.split('.').pop().toLowerCase()) })
  await sidebarFresh() // the pending refresh may have started before the module existed
  const project = projects.find(p => p.id === id) || await api('GET', `/api/projects/${id}`)
  const documents = projectEntries(project).documents
  const document = documents.find(d => d.id === docId)?.id || documents[0]?.id
  await openProjectEntry(project, document, result.name, true)
}
async function pullLibrary(source, target, targetFolder = '') {
  const document = docId, project = docProject, epoch = openN
  const current = () => docId === document && docProject === project && openN === epoch
  if (!await flushTab() || !await flushTpl() || !current()) return null
  const base = source.source.split('/').pop()
  // Personal modules keep their collection folder, and a drop on a project
  // folder (or the folder's + menu) wins over it. Project targets otherwise
  // keep the source path so dependencies stay in the same relative place.
  const folder = target.scope === 'project' ? (targetFolder || source.folder || '') : ''
  const initial = target.scope === 'personal' ? base : (folder ? folder + '/' + base : source.source)
  const name = await ask(t('projects.copyName'), { value: initial, maxLen: 240, stem: true })
  if (!name?.trim() || !current()) return null
  const body = { ...source, ...target, name: name.trim(), renames: {} }
  while (current()) {
    const preview = await api('POST', '/api/library/pull-preview', body)
    if (!current()) return null
    if (preview.collisions?.length) {
      toast(t('common.nameExists'))
      const files = preview.files || [{ source: source.source, name: body.name }]
      for (const file of files.filter(f => preview.collisions.includes(f.name))) {
        const replacement = await ask(t('projects.copyConflict') + '\n' + file.source, { value: file.name, maxLen: 240, stem: true })
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
  const folder = myTpl.find(r => r.name === name)?.folder || ''
  return pullLibrary({ source_scope: 'personal', source: name }, { scope: 'project', project_id: targets[i].id }, folder)
}
async function insertPersonalResource(tpl) {
  const document = docId, project = docProject, epoch = openN, file = activeFile
  if (!project || docResReadonly) return
  const name = await pullLibrary({ source_scope: 'personal', source: tpl.name }, { scope: 'project', project_id: project }, tpl.folder || '')
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

async function uploadProjectFiles(p, files, folder = '') {
  if (!projectEditable(p)) return
  const at = n => folder ? folder + '/' + n : n // dropped on a folder: it lands there
  let attachmentDoc = projectEntries(p).documents.find(d => d.id === docId)?.id || projectEntries(p).documents[0]?.id
  try {
    for (const file of files) {
      if (/\.zip$/i.test(file.name)) {
        const title = await ask(t('docs.newDocTitle'), { value: file.name.replace(/\.zip$/i, '') })
        if (!title?.trim()) continue
        const body = new FormData(); body.append('f', file); body.append('title', title.trim()); body.append('folder', folder)
        const response = await fetch(`/api/projects/${p.id}/import-zip`, { method: 'POST', body })
        if (!response.ok) throw new Error(expMsg(await response.text()))
        attachmentDoc ||= (await response.json()).id
      } else if (/\.typ$/i.test(file.name)) {
        const choice = await askPick(file.name, [[t('docs.pickDoc'), ''], [t('projects.newResource'), t('projects.newResourceHint')]])
        if (choice === 0) {
          const created = await api('POST', `/api/projects/${p.id}/docs`, { title: file.name, content: await file.text(), folder })
          attachmentDoc ||= created.id
        } else if (choice === 1) await api('POST', `/api/projects/${p.id}/resources`, { name: at(file.name), content: await file.text() })
      } else if (TEXT_EXT.test(file.name)) await api('POST', `/api/projects/${p.id}/resources`, { name: at(file.name), content: await file.text() })
      else {
        if (!attachmentDoc) attachmentDoc = (await api('POST', `/api/projects/${p.id}/docs`, { title: t('projects.attachments'), content: '', folder })).id
        const existing = (await api('GET', `/api/docs/${attachmentDoc}/files`)).files
        const name = at(file.name.replace(/^[.]+/, '').replace(/[^A-Za-z0-9._ ()-]/g, '_').slice(0, 100))
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

function projectMenu(p, folder = '', anchor) { // the + on a project/folder opens the same compact menu style as the sidebar actions
  if (!window.showMenuAt) return
  const run = fn => () => Promise.resolve().then(fn).catch(e => toast(e.message))
  const items = [
    { label: t('docs.newDocTitle'), title: t('docs.pickDocSub'), run: run(() => newProjectDoc(p.id, folder)) },
    { label: t('projects.newResource'), title: t('projects.newResourceHint'), submenu: () => fileTypeMenuItems(ext => run(() => newProjectResource(p.id, folder, ext))()) },
  ]
  if ((folder ? folder.split('/').length : 0) < FOLDER_LEVELS) { // no deeper level below this one
    items.push({ label: t('projects.newFolder'), title: t('projects.newFolderHint'), run: run(() => newProjectFolder(p, folder)) })
  }
  items.push(
    { label: t('docs.pickUp'), title: t('docs.pickUpSub'), run: () => {
      const picker = document.createElement('input'); picker.type = 'file'; picker.multiple = true
      picker.onchange = () => uploadProjectFiles(p, [...picker.files], folder).catch(e => toast(e.message))
      picker.click()
    } },
    { label: t('projects.fromPersonal'), title: t('projects.fromPersonalHint'), run: run(async () => {
      await loadTpl()
      const j = await askPick(t('projects.fromPersonal'), myTpl.map(r => [r.name, '']))
      if (j != null && myTpl[j]) return pullLibrary({ source_scope: 'personal', source: myTpl[j].name }, { scope: 'project', project_id: p.id }, folder)
    }) },
  )
  window.showMenuAt(anchor, items, 'left')
}
async function newProjectFolder(p, parent = '') {
  const raw = await ask(t('projects.newFolderHead'), { ph: t('projects.newFolderPh'), maxLen: 60 })
  const name = (raw || '').trim().replace(/[\\/]+/g, '_').replace(/^\.+/, '')
  if (!name) return
  const path = parent ? parent + '/' + name : name
  if (path.split('/').length > FOLDER_LEVELS) { toast(t('projects.folderDepth', { n: FOLDER_LEVELS })); return }
  await api('POST', `/api/projects/${p.id}/folders`, { path })
  for (const f of folderParents(path)) shut.delete('folder:' + p.id + ':' + f)
  shut.delete('project:' + p.id); saveShut(); await sidebar()
}
async function deleteFolder(p, path) {
  if (window.changeSession || window.suggestionDraft) { toast(t('packages.sourceBlocked')); return }
  if (!await flushTab() || !await flushTpl()) return
  if (!await ask(t('projects.folderTrashConfirm', { name: path }), { noInput: true, danger: true })) return
  const fresh = await api('GET', `/api/projects/${p.id}`)
  const items = folderContents(fresh, path)
  const trashedDocs = new Set(items.documents.map(d => d.id))
  try {
    for (const d of items.documents) await api('DELETE', `/api/docs/${d.id}`)
    for (const r of items.resources) {
      await api('DELETE', `/api/projects/${p.id}/resources/${encodeURIComponent(r.name)}?version=${encodeURIComponent(r.updated_at || '')}`)
    }
    for (const f of items.files) {
      if (trashedDocs.has(f.doc_id)) continue // files travel with their trashed document
      await api('DELETE', `/api/docs/${f.doc_id}/files/${encodeURIComponent(f.name)}`)
    }
    await api('DELETE', `/api/projects/${p.id}/folders?path=${encodeURIComponent(path)}`)
  } catch (e) {
    // The backend rejects a folder that refilled concurrently; keep the
    // message local instead of leaking the raw 409 text into the UI.
    toast(e.status === 409 && /not empty/i.test(e.message) ? t('projects.folderNotEmpty') : e.message)
    await sidebar(); return
  }
  if (docId && trashedDocs.has(docId)) closeView()
  else if (activeFile && (items.resources.some(r => TPLK + r.name === activeFile) || items.files.some(f => f.name === activeFile && f.doc_id === docId))) await switchTab('', true)
  if (docId) { filesDirty = true; await loadDocResources(true); tabSig = ''; queueRender() }
  await sidebar()
}
async function afterFolderRename(p, path, target) {
  const doc = docId, epoch = openN, was = activeFile
  const inside = key => { const n = isTplKey(key) ? tabName(key) : key; return n === path || n.startsWith(path + '/') }
  const mapped = was && inside(was) ? (isTplKey(was) ? TPLK : '') + target + (isTplKey(was) ? tabName(was) : was).slice(path.length) : ''
  tabRemapPrefix(p.id, path, target)
  filesDirty = true
  if (mapped && docId === doc && openN === epoch) await switchTab('', true)
  if (docId === doc && openN === epoch && docProject === p.id) { await loadDocResources(true); tabSig = ''; queueRender() }
  await sidebar()
  if (mapped && docId === doc && openN === epoch) await switchTab(mapped)
}
async function renameFolder(p, path, host) {
  if (window.changeSession || window.suggestionDraft) { toast(t('packages.sourceBlocked')); return }
  if (!await flushTab() || !await flushTpl()) return
  host = sidebarLiveHost(host, null) || host
  const label = host?.querySelector('b')
  const parent = folderParent(path), base = folderBase(path) // path stays out of the input; typing a path can still move the folder
  const next = label ? await sidebarInlineRename(host, label, base, { label: t('projects.renameFolder'), maxLen: 120 }) : await ask(t('projects.renameFolder'), { value: base })
  const typed = (next || '').trim().replace(/^\/+|\/+$/g, '')
  if (!typed) return
  const target = typed.includes('/') ? typed : joinFolder(parent, typed)
  if (target === path) return
  if (target.split('/').length > FOLDER_LEVELS) { toast(t('projects.folderDepth', { n: FOLDER_LEVELS })); return }
  if (!folderTreeFits(folderContents(p, path), path, target)) { toast(t('projects.folderDepth', { n: FOLDER_LEVELS })); return }
  const body = el('div', 'mBody')
  body.append(el('div', 'mLabel', t('projects.newName')), el('div', 'mTarget', target), el('p', 'mNote', t('projects.folderRenameNote')))
  if (!await ask(t('projects.renameFolder'), { noInput: true, body, ok: t('projects.renameAction') })) return
  await api('POST', `/api/projects/${p.id}/folders/rename`, { path, target })
  await afterFolderRename(p, path, target)
}
async function renameProject(p, host) {
  if (host && !host.isConnected) host = [...document.querySelectorAll('.project-group')].find(group => group.dataset.projectId === p.id)?.querySelector('.fhd.project') || host
  const label = host?.querySelector('b')
  const title = label ? await sidebarInlineRename(host, label, p.title, { label: t('projects.rename') }) : await ask(t('projects.rename'), { value: p.title })
  if (title?.trim()) { await api('POST', `/api/projects/${p.id}/rename`, { title: title.trim() }); await sidebar() }
}
async function deleteProject(p) {
  if (!await flushTab() || !await flushTpl()) return
  if (!await ask(t('projects.deleteWarning'), { noInput: true, danger: true })) return
  await api('DELETE', `/api/projects/${p.id}`)
  // The whole project is gone: leave no editable zombie tab behind (saves
  // would only 410) and keep a local draft for offline main.typ edits.
  const openModule = activeFile && isTplKey(activeFile) && projectEntries(p).resources.some(r => r.name === tabName(activeFile))
  if (docProject === p.id || openModule) closeView()
  await sidebar()
}
async function renameProjectDocument(d, host) {
  host = sidebarLiveHost(host, ['document', d.id, 'main.typ'].join(':'))
  const label = host?.querySelector('.t')
  const title = label ? await sidebarInlineRename(host, label, d.title, { label: t('docs.renameDoc') }) : await ask(t('docs.renameDoc'), { value: d.title })
  if (!title?.trim()) return
  await api('POST', `/api/docs/${d.id}/rename`, { title: title.trim() })
  if (docId === d.id) { $('title').textContent = title.trim(); docTitle = title.trim(); tabSig = ''; paintTabs() }
  await sidebar()
}
async function renameProjectEntry(p, name, document, resource, host) {
  if (!p) { toast(t('projects.contextGone')); return }
  host = sidebarLiveHost(host, [resource ? 'resource' : 'file', resource ? '' : document, name].join(':'))
  if (!await flushTab() || !await flushTpl()) return
  const label = host?.querySelector('.t')
  const dir = folderParent(name), base = folderBase(name) // the row shows only the name; the folder path stays hidden while renaming
  const next = label ? await sidebarInlineRename(host, label, base, { label: t('docs.renameDoc'), maxLen: 240, stem: true }) : await ask(t('projects.renameWarning'), { value: base, maxLen: 240, stem: true })
  const typed = next?.trim().replace(/^\/+|\/+$/g, '')
  if (!typed) return
  const target = typed.includes('/') ? typed : joinFolder(dir, typed) // typing a path still moves as before
  if (target === name) return
  await applyEntryRename(p, name, document, resource, target)
}
function renameBody(name, references) { // structured rename dialog: target first, then references, then the warning
  const body = el('div', 'mBody')
  body.append(el('div', 'mLabel', t('projects.newName')))
  const target = el('div', 'mTarget', name); body.append(target)
  body.append(el('div', 'mLabel', t('projects.referencesTitle')))
  if (references.length) {
    const list = el('div', 'mRefs')
    references.forEach(ref => list.append(el('code', null, ref)))
    body.append(list)
  } else body.append(el('p', 'mText', t('projects.noReferences')))
  body.append(el('p', 'mNote', t('projects.dynamicReferences')))
  return body
}
async function applyEntryRename(p, name, document, resource, target, confirm = true) { // rename or move (a new path = a new folder): references are listed, never rewritten
  if (!await flushTab() || !await flushTpl()) return
  const doc = docId, epoch = openN
  const body = { name, target, doc_id: resource ? '' : document }
  const preview = await api('POST', `/api/projects/${p.id}/rename-entry-preview`, body)
  if (doc !== docId || epoch !== openN) return
  if (confirm && !await ask(t('files.renameHead'), { noInput: true, body: renameBody(preview.name, preview.references), ok: t('projects.renameAction') })) return
  if (doc !== docId || epoch !== openN) return
  const result = await api('POST', `/api/projects/${p.id}/rename-entry`, { ...body, target: preview.name, version: preview.version })
  tabRemapEntry(p.id, resource ? 'r:' + name : 'f:' + document + '/' + name, resource ? 'r:' + result.name : 'f:' + document + '/' + result.name)
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
  toast(confirm ? t('files.renamed', { name: result.name }) : t('files.moved', { name: result.name }))
}
async function moveEntryToFolder(p, entry, folder) { // drag onto a folder (or the project): same project only
  if (folder && folder.split('/').length > FOLDER_LEVELS) { toast(t('projects.folderDepth', { n: FOLDER_LEVELS })); return }
  if (entry.kind === 'document') {
    const current = projectEntries(p).documents.find(d => d.id === entry.doc_id)
    if (!current || (current.folder || '') === folder) return
    await api('POST', `/api/projects/${p.id}/docs/${entry.doc_id}/folder`, { folder })
    await sidebar(); return
  }
  const base = entry.name.split('/').pop(), next = folder ? folder + '/' + base : base
  if (next === entry.name) return
  await applyEntryRename(p, entry.name, entry.doc_id, entry.kind === 'resource', next, false) // drag = just move, no dialog
}
async function folderTransferTo(source, path, target, parent, move) { // drag a folder onto a folder header or the project root
  if ((parent ? parent.split('/').length : 0) + 1 > FOLDER_LEVELS) { toast(t('projects.folderDepth', { n: FOLDER_LEVELS })); return null }
  if (source.id === target.id) {
    const fresh = await api('GET', `/api/projects/${source.id}`)
    if (move) {
      let next = joinFolder(parent, folderBase(path))
      if (next === path) return null
      if (folderIsUsed(fresh, next)) {
        const name = await targetFolderName(fresh, parent, folderBase(path), false)
        if (!name) return null
        next = joinFolder(parent, name)
      }
      if (next.split('/').length > FOLDER_LEVELS) { toast(t('projects.folderDepth', { n: FOLDER_LEVELS })); return null }
      if (!folderTreeFits(folderContents(fresh, path), path, next)) { toast(t('projects.folderDepth', { n: FOLDER_LEVELS })); return null }
      await api('POST', `/api/projects/${source.id}/folders/rename`, { path, target: next })
      await afterFolderRename(source, path, next)
      return next
    }
    const name = await targetFolderName(fresh, parent, folderBase(path), true)
    return name ? copyFolderTree(source, path, fresh, parent, name, false) : null
  }
  const fresh = await api('GET', `/api/projects/${target.id}`)
  const name = await targetFolderName(fresh, parent, folderBase(path), !move)
  return name ? copyFolderTree(source, path, fresh, parent, name, move) : null
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

function projectFolderPaths(p) { return projectTree(p, projectEntries(p)).all }
const folderBase = path => path.split('/').pop()
const folderParent = path => path.split('/').slice(0, -1).join('/')
const joinFolder = (parent, name) => parent ? parent + '/' + name : name
const insideFolder = (path, folder) => path === folder || path.startsWith(folder + '/')
function cleanFolderName(raw) { return String(raw || '').trim().replace(/[\\/]+/g, '_').replace(/^\.+/, '').slice(0, 100) }
function folderIsUsed(p, path) {
  if (projectFolderPaths(p).includes(path)) return true
  const entries = projectEntries(p)
  return entries.documents.some(d => (d.folder || '') === path) || entries.resources.some(r => r.name === path) || entries.files.some(f => f.name === path)
}
async function targetFolderName(p, parent, base, copy) {
  if (!folderIsUsed(p, joinFolder(parent, base))) return base
  if (copy) {
    for (let n = 1; ; n++) {
      const candidate = t(n === 1 ? 'projects.copyOne' : 'projects.copyMany', { name: base, n })
      if (!folderIsUsed(p, joinFolder(parent, candidate))) return candidate
    }
  }
  const answer = await ask(t('projects.folderNameConflict'), { value: base, maxLen: 100, selectAll: true })
  const cleaned = cleanFolderName(answer)
  if (!cleaned) return null
  if (cleaned === base) return null
  return targetFolderName(p, parent, cleaned, false)
}
function folderContents(p, path) {
  const entries = projectEntries(p)
  return {
    documents: entries.documents.filter(d => insideFolder(d.folder || '', path)),
    resources: entries.resources.filter(r => insideFolder(r.name, path)),
    files: entries.files.filter(f => insideFolder(f.name, path)),
    folders: (p.folders || []).filter(f => insideFolder(f, path)),
  }
}
function folderTreeFits(items, path, targetPath) { // never start a copy/move that must fail halfway on depth
  const tooDeep = p => p.split('/').filter(Boolean).length > FOLDER_LEVELS
  const rel = p => p === path ? '' : p.slice(path.length)
  if (tooDeep(targetPath)) return false
  if (items.folders.some(f => tooDeep(targetPath + rel(f)))) return false
  if (items.documents.some(d => tooDeep(targetPath + rel(d.folder || '')))) return false
  if (items.resources.some(r => tooDeep(folderParent(targetPath + rel(r.name))))) return false
  if (items.files.some(f => tooDeep(folderParent(targetPath + rel(f.name))))) return false
  return true
}
function projectCopyName(name, n = 1) {
  const dot = name.lastIndexOf('.')
  const ext = dot > name.lastIndexOf('/') + 1 ? name.slice(dot) : ''
  const stem = ext ? name.slice(0, dot) : name
  return t(n === 1 ? 'projects.copyOne' : 'projects.copyMany', { name: stem, n }) + ext
}
function uniqueDocTitle(used, title) {
  if (!used.has(title.toLowerCase())) return title
  for (let n = 1; ; n++) {
    const candidate = projectCopyName(title, n)
    if (!used.has(candidate.toLowerCase())) return candidate
  }
}
async function attachmentsDoc(p) {
  const docs = projectEntries(p).documents
  if (docs.length) return docs[0].id
  for (let n = 1; ; n++) {
    const title = n === 1 ? t('projects.attachments') : `${t('projects.attachments')} ${n}`
    try {
      const r = await api('POST', `/api/projects/${p.id}/docs`, { title, content: '' })
      p.documents = [...(p.documents || []), { id: r.id, title, folder: '' }]
      return r.id
    } catch (e) {
      if (e.status !== 409) throw e
    }
  }
}
async function pickTargetFolder(p, head, exclude = '', reserve = 0) {
  // reserve is the depth the moved entry adds itself: a folder needs one level,
  // files/documents none. Both allowed levels stay selectable for entries.
  const max = FOLDER_LEVELS - reserve
  const paths = projectFolderPaths(p).filter(f => f.split('/').length <= max && (!exclude || !insideFolder(f, exclude)))
  const values = ['', ...paths]
  const i = await askPick(head, values.map(f => [f || t('menu.projectRoot'), '']))
  return i == null || i < 0 ? null : values[i]
}
async function transferEntryTo(p, entry, target, folder, move, opts = {}) {
  if (!await flushTab() || !await flushTpl()) return null
  if (folder && folder.split('/').length > FOLDER_LEVELS) { toast(t('projects.folderDepth', { n: FOLDER_LEVELS })); return null }
  const same = p.id === target.id
  if (same && move && entry.kind === 'document' && (entry.folder || '') === folder) return null
  if (same && move && entry.kind !== 'document' && entryFolder(entry) === folder) return null
  // Silent cross-project transfers (drop on the project row, trash restore)
  // keep the existing folder path. Choosing a target folder explicitly wins.
  const keep = !!opts.keepPath && !folder
  const destFolder = entry.kind === 'document' ? (keep ? (entry.folder || '') : folder) : folder
  let targetDoc = opts.targetDoc || ''
  if (entry.kind === 'file' && !targetDoc) {
    const docs = projectEntries(target).documents
    if (!docs.length) { toast(t('projects.uploadNeedsDoc')); return null }
    targetDoc = docs.find(d => d.id === entry.doc_id)?.id || docs.find(d => d.id === docId)?.id || docs[0].id
  }
  let name = opts.name || (entry.kind === 'document' ? entry.name : keep ? entry.name : entry.name.split('/').pop())
  let askName = opts.askName !== false
  let duplicate = !!opts.duplicate
  while (true) {
    if (askName) {
      const dir = entry.kind !== 'document' && name.includes('/') ? name.slice(0, name.lastIndexOf('/') + 1) : '' // a kept path survives the conflict prompt
      const input = await ask(t('projects.copyName'), { value: entry.kind === 'document' ? name : name.split('/').pop(), maxLen: entry.kind === 'document' ? 100 : 240, stem: entry.kind !== 'document' })
      if (input == null || !input.trim()) return null
      name = input.trim()
      if (dir && !name.includes('/')) name = dir + name
    }
    const targetName = entry.kind === 'document' || name.includes('/') ? name : (destFolder ? destFolder + '/' + name : name)
    if (entry.kind !== 'document' && targetName.split('/').length - 1 > FOLDER_LEVELS) { toast(t('projects.folderDepth', { n: FOLDER_LEVELS })); return null }
    const body = { kind: entry.kind, doc_id: entry.doc_id || '', name: entry.name, target_project_id: target.id, target_doc_id: targetDoc, target_name: targetName, move }
    if (entry.kind === 'document') body.target_folder = destFolder
    if (duplicate) body.duplicate = true
    try {
      const result = await api('POST', `/api/projects/${p.id}/transfer`, body)
      if (opts.refresh !== false) {
        await sidebar(); filesDirty = true
        if (docId) { await loadDocResources(true); tabSig = ''; queueRender() }
      }
      if (entry.kind === 'document' && move && docId === entry.doc_id) await openDoc(result.doc_id)
      return result
    } catch (e) {
      if (e.status !== 409) throw e
      toast(e.message)
      if (opts.strict) throw e
      askName = true; duplicate = false
    }
  }
}
function entryMenuItems(p, entry, actions) {
  const what = entry.kind === 'document' ? 'document' : entry.kind === 'resource' ? 'module' : 'file'
  const rename = actions.find(b => b.dataset.menuKey === 'rename')
  const trash = actions.find(b => b.dataset.menuKey === 'trash')
  const session = !!window.changeSession
  const writable = projectEditable(p) && !session
  return [
    rename && menuButtonItem(rename, what),
    writable && sidebarMenuItem('duplicate', () => transferEntryTo(p, entry, p, entryFolder(entry), false, { askName: false, duplicate: true }), { what }),
    !session && sidebarMenuItem('copy', null, { what, submenu: () => entryDestinationItems(p, entry, false, writable) }),
    writable && sidebarMenuItem('move', null, { what, submenu: () => entryDestinationItems(p, entry, true) }),
    trash && menuButtonItem(trash, what),
  ].filter(Boolean)
}
function entryDestinationItems(p, entry, move, within = true) {
  const what = entry.kind === 'document' ? 'document' : entry.kind === 'resource' ? 'module' : 'file'
  const items = []
  if (within) items.push(sidebarMenuItem('copy', () => transferEntryWithin(p, entry, move), { what, label: t('menu.copyHere'), title: t('menu.copyHereHint') }))
  items.push(sidebarMenuItem('copy', () => transferEntryOther(p, entry, move), { what, label: t('menu.copyOther'), title: t('menu.copyOtherHint') }))
  if (!move && (entry.kind === 'resource' || (entry.kind === 'file' && TEXT_EXT.test(entry.name)))) {
    items.push(sidebarMenuItem('copy', () => copyEntryGlobal(p, entry), { what, label: t('menu.copyGlobal'), title: t('menu.copyGlobalHint') }))
  }
  return items
}
function copyEntryGlobal(p, entry) {
  if (entry.kind === 'resource') return pullLibrary({ source_scope: 'project', source_project_id: p.id, source: entry.name }, { scope: 'personal' })
  return copyToLibrary(entry.name, entry.doc_id, { scope: 'personal' })
}
async function transferEntryWithin(p, entry, move) {
  const folder = await pickTargetFolder(p, t('menu.copyHere'))
  if (folder == null) return
  // Documents may share a title across folders, but not within one; a copy into the same folder needs a new title.
  return transferEntryTo(p, entry, p, folder, move, { askName: false, duplicate: !move && entry.kind === 'document' && (entry.folder || '') === folder })
}
async function transferEntryOther(p, entry, move) {
  const targets = projects.filter(x => x.id !== p.id && projectEditable(x))
  if (!targets.length) { toast(t('projects.noOtherProject')); return }
  const i = await askPick(t('menu.copyOther'), targets.map(x => [x.title, '']))
  if (i == null || !targets[i]) return
  let target
  try { target = await api('GET', `/api/projects/${targets[i].id}`) } catch (e) { toast(e.message); return }
  const folder = await pickTargetFolder(target, t('menu.targetFolder', { project: target.title }))
  if (folder == null) return
  return transferEntryTo(p, entry, target, folder, move)
}
async function projectEntryMenu(p, entry, anchor) {
  const what = entry.kind === 'document' ? 'document' : entry.kind === 'resource' ? 'module' : 'file'
  const items = [
    sidebarMenuItem('copy', null, { what, submenu: () => entryDestinationItems(p, entry, false) }),
    sidebarMenuItem('move', null, { what, submenu: () => entryDestinationItems(p, entry, true) }),
  ]
  if (anchor && window.showMenuAt) { window.showMenuAt(anchor, items, 'left'); return }
  const i = await askPick(entry.name, [[t('menu.copyTo'), t('menu.copyToHint', { what: menuWhat(what) })], [t('menu.moveTo'), t('menu.moveToHint', { what: menuWhat(what) })]])
  if (i == null || i < 0) return
  const destinations = entryDestinationItems(p, entry, i === 1)
  const j = await askPick(i === 1 ? t('menu.moveTo') : t('menu.copyTo'), destinations.map(d => [d.label, d.title]))
  if (j == null || j < 0 || !destinations[j]) return
  return destinations[j].run()
}
async function duplicateFolder(p, path) {
  const fresh = await api('GET', `/api/projects/${p.id}`)
  const parent = folderParent(path)
  const name = await targetFolderName(fresh, parent, folderBase(path), true)
  if (name) await copyFolderTree(p, path, fresh, parent, name, false)
}
async function transferFolderWithin(p, path, move) {
  const fresh = await api('GET', `/api/projects/${p.id}`)
  const parent = await pickTargetFolder(fresh, t('menu.copyHere'), path, 1)
  if (parent == null) return
  if (move) {
    let target = joinFolder(parent, folderBase(path))
    if (target === path) return
    if (folderIsUsed(fresh, target)) {
      const name = await targetFolderName(fresh, parent, folderBase(path), false)
      if (!name) return
      target = joinFolder(parent, name)
    }
    if (!folderTreeFits(folderContents(fresh, path), path, target)) { toast(t('projects.folderDepth', { n: FOLDER_LEVELS })); return }
    await api('POST', `/api/projects/${p.id}/folders/rename`, { path, target })
    await afterFolderRename(p, path, target)
    return
  }
  const name = await targetFolderName(fresh, parent, folderBase(path), true)
  if (name) await copyFolderTree(p, path, fresh, parent, name, false)
}
async function transferFolderOther(p, path, move) {
  const targets = projects.filter(x => x.id !== p.id && projectEditable(x))
  if (!targets.length) { toast(t('projects.noOtherProject')); return }
  const i = await askPick(t('menu.copyOther'), targets.map(x => [x.title, '']))
  if (i == null || !targets[i]) return
  let target
  try { target = await api('GET', `/api/projects/${targets[i].id}`) } catch (e) { toast(e.message); return }
  const parent = await pickTargetFolder(target, t('menu.targetFolder', { project: target.title }), '', 1)
  if (parent == null) return
  const name = await targetFolderName(target, parent, folderBase(path), !move)
  if (name) await copyFolderTree(p, path, target, parent, name, move)
}
async function copyFolderTree(source, path, target, parent, name, move) {
  const src = await api('GET', `/api/projects/${source.id}`)
  const tgt = target.id === source.id ? src : await api('GET', `/api/projects/${target.id}`)
  const targetPath = joinFolder(parent, name)
  const items = folderContents(src, path)
  if (!folderTreeFits(items, path, targetPath)) { toast(t('projects.folderDepth', { n: FOLDER_LEVELS })); return null }
  // Every entry is its own request. Keep an undo step per finished entry so a
  // conflict half-way (quota, a dependency module, a permission) rolls the
  // whole folder back instead of leaving a half-transferred tree behind.
  const done = [], created = []
  const known = new Set(projectFolderPaths(tgt))
  const back = body => () => api('POST', `/api/projects/${target.id}/transfer`, body) // a move is undone by moving it home again
  const undoCopiedResource = to => async () => {
    const fresh = await api('GET', `/api/projects/${target.id}`)
    const r = (fresh.resources || []).find(x => x.name === to)
    if (r) await api('DELETE', `/api/projects/${target.id}/resources/${encodeURIComponent(to)}?version=${encodeURIComponent(r.updated_at || '')}`)
  }
  const makeFolder = async p => {
    await api('POST', `/api/projects/${target.id}/folders`, { path: p })
    if (!known.has(p)) { known.add(p); created.push(p) }
  }
  try {
    for (const p of folderParents(targetPath)) await makeFolder(p)
    for (const f of items.folders) await makeFolder(f === path ? targetPath : targetPath + '/' + f.slice(path.length + 1))
    const usedByFolder = new Map() // titles are unique per folder, so a copied folder keeps document names unless its target folder already has them
    const usedIn = folder => {
      if (!usedByFolder.has(folder)) usedByFolder.set(folder, new Set(projectEntries(tgt).documents.filter(d => (d.folder || '') === folder).map(d => d.title.toLowerCase())))
      return usedByFolder.get(folder)
    }
    const docMap = new Map()
    for (const d of items.documents) {
      const rel = d.folder && d.folder !== path ? d.folder.slice(path.length + 1) : ''
      const folder = rel ? targetPath + '/' + rel : targetPath
      const used = usedIn(folder)
      const suggested = uniqueDocTitle(used, d.title)
      used.add(suggested.toLowerCase())
      const result = await transferEntryTo(source, { kind: 'document', doc_id: d.id, name: d.title, folder: d.folder || '' }, tgt, folder, move, {
        askName: false, name: suggested, strict: true, refresh: false,
      })
      if (!result) continue
      docMap.set(d.id, result.doc_id)
      done.push(move
        ? back({ kind: 'document', doc_id: d.id, name: suggested, target_project_id: source.id, target_doc_id: '', target_name: d.title, target_folder: d.folder || '', move: true })
        : () => api('DELETE', `/api/docs/${result.doc_id}`))
    }
    for (const r of items.resources) {
      const to = targetPath + '/' + r.name.slice(path.length).replace(/^\/+/, '')
      const result = await transferEntryTo(source, { kind: 'resource', doc_id: '', name: r.name }, tgt, '', move, {
        askName: false, name: to, strict: true, refresh: false,
      })
      if (!result) continue
      done.push(move
        ? back({ kind: 'resource', doc_id: '', name: to, target_project_id: source.id, target_doc_id: '', target_name: r.name, move: true })
        : undoCopiedResource(to))
    }
    let attachDoc = ''
    for (const f of items.files) {
      if (docMap.has(f.doc_id)) continue // files travel with their copied or moved document
      let targetDoc = target.id === source.id ? f.doc_id : ''
      if (!targetDoc) {
        if (!attachDoc) attachDoc = await attachmentsDoc(tgt)
        targetDoc = attachDoc
      }
      const to = targetPath + '/' + f.name.slice(path.length).replace(/^\/+/, '')
      const result = await transferEntryTo(source, { kind: 'file', doc_id: f.doc_id, name: f.name }, tgt, '', move, {
        askName: false, name: to, targetDoc, strict: true, refresh: false,
      })
      if (!result) continue
      done.push(move
        ? back({ kind: 'file', doc_id: targetDoc, name: to, target_project_id: source.id, target_doc_id: f.doc_id, target_name: f.name, move: true })
        : () => api('DELETE', `/api/docs/${targetDoc}/files/${encodeURIComponent(to)}`))
    }
  } catch (e) {
    let stuck = 0
    for (const undo of done.reverse()) { try { await undo() } catch (err) { stuck++ } }
    for (const p of created.sort((a, b) => b.split('/').length - a.split('/').length)) { // deepest first; a folder that is not empty stays
      try { await api('DELETE', `/api/projects/${target.id}/folders?path=${encodeURIComponent(p)}`) } catch (err) {}
    }
    try { await sidebar(); filesDirty = true; if (docId) { await loadDocResources(true); tabSig = ''; queueRender() } } catch (err) {}
    const failure = new Error(t(stuck ? 'projects.folderTransferPartial' : 'projects.folderTransferUndone', { reason: e.message }))
    failure.status = e.status
    throw failure
  }
  if (move && target.id !== source.id) {
    try { await api('DELETE', `/api/projects/${source.id}/folders?path=${encodeURIComponent(path)}`) }
    catch (e) { if (e.status !== 409) throw e }
  }
  await sidebar(); filesDirty = true
  if (docId) { await loadDocResources(true); tabSig = ''; queueRender() }
  return targetPath
}
function folderMenuItems(p, path, actions) {
  const rename = actions.find(b => b.dataset.menuKey === 'rename')
  const trash = actions.find(b => b.dataset.menuKey === 'trash')
  const session = !!window.changeSession || !!window.suggestionDraft
  const writable = projectEditable(p) && !session
  return [
    rename && !session && menuButtonItem(rename, 'folder'),
    writable && sidebarMenuItem('duplicate', () => duplicateFolder(p, path), { what: 'folder' }),
    !session && sidebarMenuItem('copy', null, { what: 'folder', submenu: () => folderDestinationItems(p, path, false, writable) }),
    writable && sidebarMenuItem('move', null, { what: 'folder', submenu: () => folderDestinationItems(p, path, true) }),
    trash && !session && menuButtonItem(trash, 'folder'),
  ].filter(Boolean)
}
function folderDestinationItems(p, path, move, within = true) {
  const items = []
  if (within) items.push(sidebarMenuItem('copy', () => transferFolderWithin(p, path, move), { what: 'folder', label: t('menu.copyHere'), title: t('menu.copyHereHint') }))
  items.push(sidebarMenuItem('copy', () => transferFolderOther(p, path, move), { what: 'folder', label: t('menu.copyOther'), title: t('menu.copyOtherHint') }))
  return items
}
async function transferProjectEntry(p, entry, move, selectedTarget, direct = false, folder = '') {
  let target = selectedTarget
  if (!target) {
    const targets = projects.filter(projectEditable)
    const i = await askPick(t(move ? 'menu.moveTo' : 'menu.copyTo'), targets.map(x => [x.title, '']))
    if (i == null || !targets[i]) return
    target = targets[i]
  }
  if (direct && p.id === target.id && move) return
  return transferEntryTo(p, entry, target, folder, move, { askName: !direct, keepPath: p.id !== target.id })
}
function projectDrag(row, p, entry) {
  sidebarDrag(row, { project: p.id, entry }, projectEditable(p) ? 'copyMove' : 'copy')
}
function projectDropTarget(row, target, folder = '', visual = row) {
  if (!projectEditable(target)) return
  const invalidDrop = data => {
    if (!data || data.trashed || data.personal) return false
    if (data.project === target.id && entryFolder(data.entry) === folder) return true // already here: no target, no drop
    return data.entry.kind === 'folder' && insideFolder(folder, data.entry.name) // never into itself or a descendant
  }
  row.ondragover = e => {
    if (!e.dataTransfer.types.includes('Files') && !e.dataTransfer.types.includes('application/x-typst-project-entry')) return
    const data = sidebarDragData
    if (invalidDrop(data)) { markDropTarget(null); return }
    e.preventDefault(); e.stopPropagation(); markDropTarget(visual)
    e.dataTransfer.dropEffect = e.dataTransfer.types.includes('Files') || sidebarDragData?.personal || e.ctrlKey || e.metaKey ? 'copy' : 'move'
  }
  row.ondragenter = row.ondragover // highlight on entry; a stationary cursor may not produce another dragover
  row.ondrop = async e => {
    if (!e.dataTransfer.files.length && !e.dataTransfer.types.includes('application/x-typst-project-entry')) return
    e.preventDefault(); e.stopPropagation(); visual.classList.remove('drop-target')
    try {
      if (e.dataTransfer.files.length) { await uploadProjectFiles(target, [...e.dataTransfer.files], folder); return }
      const data = JSON.parse(e.dataTransfer.getData('application/x-typst-project-entry'))
      if (invalidDrop(data)) return
      if (data.trashed) { await restoreSidebarDocument(data, target); return }
      if (data.personal) { await pullLibrary({ source_scope: 'personal', source: data.entry.name, folder: data.entry.folder || '' }, { scope: 'project', project_id: target.id }, folder); return }
      const source = projects.find(p => p.id === data.project)
      if (!source) return
      if (data.entry.kind === 'folder') {
        await folderTransferTo(source, data.entry.name, target, folder, projectEditable(source) && !e.ctrlKey && !e.metaKey)
        return
      }
      if (source.id === target.id && projectEditable(source) && !e.ctrlKey && !e.metaKey) await moveEntryToFolder(source, data.entry, folder)
      else await transferProjectEntry(source, data.entry, projectEditable(source) && !e.ctrlKey && !e.metaKey, target, true, folder)
    } catch (error) { toast(error.message) }
  }
}

async function renamePersonalResource(name, host) {
  const editing = tplName === name
  if (editing && !await flushTpl()) return
  if (host && !host.isConnected) host = [...document.querySelectorAll('.private-module')].find(row => row.querySelector('.t')?.textContent === name) || host
  const label = host?.querySelector('.t')
  const target = label ? await sidebarInlineRename(host, label, name, { label: t('templates.renameTpl'), maxLen: 100, stem: true }) : await ask(t('templates.renameTpl'), { value: name, maxLen: 100, stem: true })
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
