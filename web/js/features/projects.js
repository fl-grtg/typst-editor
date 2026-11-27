// Projects own documents and one file tree (every other file at a project path).
function projectEditable(p) { return p.can_edit_library ?? ['owner', 'editor'].includes(p.role) }
function canStageProjectDelete(project) {
  const s = window.changeSession
  return !!s && s.project === project && !s.original && !s.busy && (!s.package || s.package.author === user || ['owner', 'editor'].includes(docRole))
}
function projectEntries(p) {
  const documents = p.documents || [...lastOwn, ...lastShared].filter(d => d.project_id === p.id)
  return { documents, files: p.files || [] }
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
const MENU_WHAT = { file: 'menu.whatFile', folder: 'menu.whatFolder', document: 'menu.whatDocument', module: 'menu.whatModule', project: 'menu.whatProject', selection: 'menu.whatSelection' }
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
    if (sideSelHolds(host)) return sideSelMenuItems()
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
function sidebarInlineCreate(container, value = '', opts = {}) { // create in place in sidebar: Enter/blur saves, Esc cancels
  if (!container || !container.offsetParent) return null
  const row = el('div', 'doc sub renaming')
  if (opts.level) row.style.setProperty('--lv', opts.level)
  const input = el('input', 'renameInput')
  input.value = value; input.placeholder = opts.ph || ''; input.maxLength = opts.maxLen || 240
  input.setAttribute('aria-label', opts.label || opts.ph || '')
  input.spellcheck = false
  row.appendChild(input)
  if (opts.after && opts.after.parentNode === container) opts.after.after(row)
  else container.prepend(row)
  row.scrollIntoView({ block: 'nearest' })
  return new Promise(resolve => {
    let done = false
    const finish = save => {
      if (done) return; done = true
      const next = input.value.trim()
      const deferred = window.__sidebarDeferred
      row.remove()
      resolve(save && next ? next : null)
      if (deferred && !document.querySelector('aside input.renameInput')) {
        window.__sidebarDeferred = false
        setTimeout(() => sidebar(), 0)
      }
    }
    input.onclick = e => e.stopPropagation()
    input.onkeydown = e => {
      if (e.key === 'Enter') { e.preventDefault(); finish(true) }
      else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); finish(false) }
    }
    input.onblur = () => finish(true)
    setTimeout(() => {
      input.focus()
      if (value) input.setSelectionRange(opts.stem ? nameStemStart(value) : 0, opts.stem ? nameStemEnd(value) : value.length)
    }, 0)
  })
}
function projectCreateTarget(projectId, folder = '') {
  if (typeof document === 'undefined' || !document.querySelector) return null
  const esc = typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(projectId) : projectId
  const group = document.querySelector(`.project-group[data-project-id="${esc}"]`)
  if (!group || !group.offsetParent) return null
  const after = folder
    ? ([...group.querySelectorAll('.fhd.folder')].find(r => r.dataset.folderPath === folder) || group.querySelector('.fhd.project'))
    : group.querySelector('.fhd.project')
  const level = folder ? folder.split('/').length : 0
  return { group, after, level }
}
const projectEntryFlights = new Map()
function openProjectEntry(p, document, name) {
  const key = JSON.stringify([p.id, document, name])
  if (projectEntryFlights.has(key)) return projectEntryFlights.get(key)
  const flight = openProjectEntryOnce(p, document, name).finally(() => projectEntryFlights.delete(key))
  projectEntryFlights.set(key, flight)
  return flight
}
async function openProjectEntryOnce(p, document, name) { // a file opens next to a document of its project (the preview compiles that document)
  if (!document) {
    toast(t('projects.needsDocument'))
    document = await newProjectDoc(p.id)
    if (!document) return
  }
  if (docId !== document) await openDoc(document)
  if (docId !== document || docProject !== p.id) return
  if (name && activeFile !== name) await switchTab(name)
}
const fileHost = (p, entries = projectEntries(p)) => docProject === p.id && entries.documents.some(d => d.id === docId) ? docId : entries.documents[0]?.id // document a file tab opens next to
const FOLDER_LEVELS = 2 // folder levels inside a project (a/b/file); deeper legacy paths fold into the last level
function splitEntryPath(name) { // 'a/b/x.typ' -> { dir: 'a/b', base: 'x.typ' }, clamped to FOLDER_LEVELS
  const parts = String(name).split('/').filter(Boolean), dirs = parts.slice(0, -1).slice(0, FOLDER_LEVELS)
  return { dir: dirs.join('/'), base: parts.slice(dirs.length).join('/') }
}
const folderParents = path => { const parts = path.split('/'); return parts.map((_, i) => parts.slice(0, i + 1).join('/')) }
function projectTree(p, entries) { // folders (explicit + implied by paths) and the entries inside each one
  const items = [
    ...entries.documents.map(d => ({ kind: 'document', dir: String(d.folder || '').split('/').filter(Boolean).slice(0, FOLDER_LEVELS).join('/'), label: d.title, d })),
    ...entries.files.map(f => ({ kind: 'file', name: f.path, ...(x => ({ dir: x.dir, label: x.base }))(splitEntryPath(f.path)) })),
  ]
  const known = new Set()
  for (const f of (p.folders || [])) folderParents(f.split('/').slice(0, FOLDER_LEVELS).join('/')).forEach(x => known.add(x))
  for (const it of items) if (it.dir) folderParents(it.dir).forEach(x => known.add(x))
  const sorted = [...known].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }))
  return {
    folders: dir => sorted.filter(f => f.includes('/') ? f.slice(0, f.lastIndexOf('/')) === dir : dir === ''),
    items: dir => items.filter(i => i.dir === dir),
    allItems: items, // flat list for search filtering
    all: sorted,
    dirOf(entry) { // folder an entry sits in (for reveal / drop)
      return items.find(i => i.kind === entry.kind && (entry.kind === 'document' ? i.d.id === entry.doc_id : i.name === entry.name))?.dir || ''
    },
  }
}
let lastReveal = ''
function revealActiveFolder(p, tree) { // opening a file shows its folder: unfold once per change of the active file
  if (docProject !== p.id) return
  const entry = activeFile ? { kind: 'file', name: activeFile } : { kind: 'document', doc_id: docId }
  const key = p.id + '\u0001' + docId + '\u0001' + activeFile
  if (key === lastReveal) return
  lastReveal = key
  const dir = tree.dirOf(entry)
  if (dir) { for (const f of folderParents(dir)) shut.delete('folder:' + p.id + ':' + f); saveShut() }
}
function paintProjects(box, shared) {
  const searching = searchOn()
  if (searching && !searchFilters[shared ? 'shared' : 'projects']) return
  projects.filter(p => (p.role !== 'owner') === shared).forEach(p => {
    const entries = projectEntries(p), tree = projectTree(p, entries)
    const titleHit = searching && searchMatch(p.title)
    const entryKey = item => item.kind === 'document' ? 'd:' + item.d.id : 'f:' + p.id + '/' + item.name
    const folderHit = path => searchMatch(path)
    const inFolderHit = dir => !!dir && folderParents(dir).some(folderHit)
    const itemHit = item => titleHit || inFolderHit(item.dir) ||
      searchMatch(item.kind === 'document' ? item.d.title : item.name) || searchContent(entryKey(item)) > 0
    const items = searching && !titleHit ? new Set(tree.allItems.filter(itemHit)) : null
    const folders = new Set()
    if (searching && !titleHit) {
      for (const item of items) folderParents(item.dir).filter(Boolean).forEach(f => folders.add(f))
      for (const f of tree.all) if (folderHit(f)) folderParents(f).filter(Boolean).forEach(x => folders.add(x))
      if (!items.size && !folders.size) return // this project has no matching entry or folder
    }
    const group = el('div', 'project-group')
    group.dataset.projectId = p.id // anchor for session draft placement (paintSessionSidebar)
    box.appendChild(group)
    const h = el('div', 'fhd project'), key = 'project:' + p.id
    const title = document.createElement('b')
    title.appendChild(searchFrag(p.title))
    title.title = p.title; title.setAttribute('role', 'button')
    const expanded = searching ? !searchFold.has(key) : !shut.has(key) // search folds per query without touching the saved state
    title.setAttribute('aria-expanded', String(expanded))
    const toggle = async () => {
      if (searching) {
        searchFold.has(key) ? searchFold.delete(key) : searchFold.add(key)
        paintOwn(); paintShared(lastShared)
        return
      }
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
    if (!expanded) return // collapsed: the header alone, folders stay folded
    group.classList.toggle('with-folders', tree.all.length > 0)
    const folderRows = new Map() // a drop anywhere inside a folder lights up its header, not the whole group
    const dropVisual = folder => (folder && folderRows.get(folder)) || h
    const entryRow = (item, level, folder) => {
      const { name } = item, hitKey = 'f:' + p.id + '/' + name
      const row = el('div', 'doc sub' + (docProject === p.id && activeFile === name ? ' cur' : '')); row.appendChild(searchTextEl('t', searching ? name : item.label)); row.title = name
      row.style.setProperty('--lv', level)
      row.dataset.packageKey = ['file', '', name].join(':')
      const open = () => {
        const q = searchFindQ(hitKey)
        return openProjectEntry(p, fileHost(p, entries), name).then(() => {
          if (q && docProject === p.id && activeFile === name) findWith(q)
        })
      }
      row.onclick = open; kb(row, open)
      const entry = { kind: 'file', name }
      if (projectEditable(p)) {
        const rename = projectAction(row, ICO_EDIT, t('files.renameHead'), () => renameProjectEntry(p, name, row))
        rename.dataset.menuKey = 'rename'; rename.dataset.menuLabel = t('menu.renameShort'); rename.dataset.menuHint = 'menu.renameHint'
      }
      projectDrag(row, p, entry); sidebarSelectable(row, p, entry)
      projectDropTarget(row, p, folder, dropVisual(folder)) // dropping on a file targets the folder it lives in
      if (projectEditable(p) || canStageProjectDelete(p.id)) {
        const trash = projectAction(row, ICO_TRASH, t('docs.moveTrash'), () => deleteProjectEntry(p, name))
        trash.dataset.menuDanger = ''; trash.dataset.menuKey = 'trash'; trash.dataset.menuLabel = t('menu.actionTrash'); trash.dataset.menuHint = 'menu.trashHint'
      }
      compactSidebarActions(row, 0, actions => entryMenuItems(p, entry, actions))
      searchHitBadge(row, hitKey)
      group.appendChild(row)
    }
    const documentRow = (d, level, folder) => {
      const row = docRow({ ...d, project_id: p.id, role: d.role || p.role }, shared, true)
      row.dataset.packageKey = ['document', d.id, ''].join(':')
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
      const entry = { kind: 'document', doc_id: d.id, name: d.title, folder: d.folder || '' }
      projectDrag(row, p, entry); sidebarSelectable(row, p, entry); group.appendChild(row)
    }
    const folderRow = (path, level) => {
      const fkey = 'folder:' + p.id + ':' + path, base = path.split('/').pop()
      const row = el('div', 'fhd folder'), label = document.createElement('b')
      label.appendChild(searchFrag(searching ? path : base))
      row.style.setProperty('--lv', level); row.dataset.folderPath = path
      folderRows.set(path, row)
      label.title = path; label.setAttribute('role', 'button')
      const open = searching ? !searchFold.has(fkey) : !shut.has(fkey) // search: fold per query, saved state untouched
      label.setAttribute('aria-expanded', String(open))
      const toggle = () => {
        if (searching) searchFold.has(fkey) ? searchFold.delete(fkey) : searchFold.add(fkey)
        else { shut.has(fkey) ? shut.delete(fkey) : shut.add(fkey); saveShut() }
        paintOwn(); paintShared(lastShared)
      }
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
      sidebarSelectable(row, p, { kind: 'folder', name: path })
      projectDropTarget(row, p, path)
      group.appendChild(row)
      return open
    }
    const paintDir = (dir, level) => {
      for (const f of tree.folders(dir)) {
        if (searching && !titleHit && !folders.has(f)) continue
        if (!folderRow(f, level)) continue
        paintDir(f, level + 1)
        if (!searching && !tree.folders(f).length && !tree.items(f).length) {
          const empty = el('div', 'folderEmpty', t('docs.folderEmpty'))
          empty.style.setProperty('--lv', level + 1)
          projectDropTarget(empty, p, f, dropVisual(f)) // the empty hint is a drop area for that folder
          group.appendChild(empty)
        }
      }
      for (const item of tree.items(dir)) {
        if (searching && !titleHit && !items.has(item)) continue
        item.kind === 'document' ? documentRow(item.d, level, dir) : entryRow(item, level, dir)
      }
    }
    if (!searching) revealActiveFolder(p, tree)
    paintDir('', 0)
  })
  if (box.querySelector('.sel')) paintSideSel() // a selected run only joins once all its rows are painted (no mark before boot ends)
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
  if (shut.has('project:' + id) || (folder && shut.has('folder:' + id + ':' + folder))) {
    shut.delete('project:' + id)
    if (folder) for (const f of folderParents(folder)) shut.delete('folder:' + id + ':' + f)
    saveShut(); await sidebar()
  }
  const host = projectCreateTarget(id, folder)
  const raw = host
    ? await sidebarInlineCreate(host.group, 'file' + ext, { after: host.after, level: host.level, ph: t('files.newFilePh', { ext: ext.slice(1) }), label: t('files.newFileHead'), maxLen: 240, stem: true })
    : await ask(t('files.newFileHead'), { value: 'file' + ext, ph: t('files.newFilePh', { ext: ext.slice(1) }), maxLen: 240, stem: true })
  if (!raw?.trim()) return
  const typed = raw.trim().replace(/^\/+/, ''), file = typed.toLowerCase().endsWith(ext) ? typed : typed + ext
  const path = folder ? folder + '/' + file : file
  const result = await putFile(fileUrl(path, id), fileStart(ext.slice(1)))
  await sidebarFresh() // the pending refresh may have started before the file existed
  const project = projects.find(p => p.id === id) || await api('GET', `/api/projects/${id}`)
  await openProjectEntry(project, fileHost(project), result.path)
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
  const body = { ...source, ...target, name: initial, renames: {} }
  while (current()) {
    const preview = await api('POST', '/api/library/pull-preview', body)
    if (!current()) return null
    if (preview.collisions?.length) {
      toast(t('common.nameExists'))
      const files = preview.files || [{ source: source.source, name: body.name }]
      const clashes = files.filter(f => preview.collisions.includes(f.name))
      if (!clashes.length) return null
      for (const file of clashes) {
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
    await loadTpl(); if (current()) await loadProjectFiles(true); await sidebar()
    return result.name || body.name
  }
  return null
}

async function pullPersonalResource(name, anchor) {
  const targets = projects.filter(projectEditable)
  const i = await pickPop(t('projects.pullProject'), targets.map(p => [p.title, '']), anchor || $('tplH'))
  if (i == null || i < 0 || !targets[i]) return
  const folder = myTpl.find(r => r.name === name)?.folder || ''
  return pullLibrary({ source_scope: 'personal', source: name }, { scope: 'project', project_id: targets[i].id }, folder)
}
async function insertPersonalResource(tpl) {
  const document = docId, project = docProject, epoch = openN, file = activeFile
  if (!project || docResReadonly) return
  const name = await pullLibrary({ source_scope: 'personal', source: tpl.name }, { scope: 'project', project_id: project }, tpl.folder || '')
  if (!name || docId !== document || docProject !== project || openN !== epoch || activeFile !== file) return
  addTpl(resLine({ name: refTo(name) }))
}
function copyFileToPersonal(project, path) { // a project text file (with what it includes) into the personal modules
  return pullLibrary({ source_scope: 'project', source_project_id: project, source: path }, { scope: 'personal' })
}

async function uploadProjectFiles(p, files, folder = '') {
  if (!projectEditable(p)) return
  const at = n => (folder ? folder + '/' : '') + uploadName(n) // dropped on a folder: it lands there
  try {
    for (const file of files) {
      if (/\.zip$/i.test(file.name)) {
        const documents = await zipDocuments(file, p.title)
        if (documents == null) continue
        const body = new FormData(); body.append('f', file); body.append('folder', folder); body.append('documents', JSON.stringify(documents))
        const response = await fetch(`/api/projects/${p.id}/import-zip`, { method: 'POST', body })
        if (!response.ok) throw new Error(expMsg(await response.text()))
      } else if (/\.typ$/i.test(file.name)) {
        const choice = await pickPop(file.name, [[t('docs.pickDoc'), ''], [t('projects.newFile'), t('projects.newResourceHint')]], $('upDoc'))
        if (choice === 0) await api('POST', `/api/projects/${p.id}/docs`, { title: file.name.replace(/\.typ$/i, ''), content: await file.text(), folder })
        else if (choice === 1) await putFile(fileUrl(at(file.name), p.id), file)
      } else await putFile(fileUrl(at(file.name), p.id), file)
    }
  } finally {
    shut.delete('project:' + p.id); saveShut(); await sidebar()
    if (docProject === p.id && docId) { await loadProjectFiles(true); queueRender() }
  }
}
async function uploadToProject(files) {
  const choices = projects.filter(projectEditable).slice().sort((a, b) => Number(b.id === docProject) - Number(a.id === docProject))
  const i = await pickPop(t('files.uploadTarget'), [...choices.map(p => [p.title, '']), [t('projects.new'), '']], $('upDoc'))
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
    { label: t('projects.newFile'), title: t('projects.newResourceHint'), submenu: () => fileTypeMenuItems(ext => run(() => newProjectResource(p.id, folder, ext))()) },
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
      const j = await pickPop(t('projects.fromPersonal'), myTpl.map(r => [r.name, '']), anchor)
      if (j != null && myTpl[j]) return pullLibrary({ source_scope: 'personal', source: myTpl[j].name }, { scope: 'project', project_id: p.id }, folder)
    }) },
  )
  window.showMenuAt(anchor, items, 'left')
}
async function newProjectFolder(p, parent = '') {
  if (shut.has('project:' + p.id) || (parent && shut.has('folder:' + p.id + ':' + parent))) {
    shut.delete('project:' + p.id)
    if (parent) for (const f of folderParents(parent)) shut.delete('folder:' + p.id + ':' + f)
    saveShut(); await sidebar()
  }
  const host = projectCreateTarget(p.id, parent)
  const raw = host
    ? await sidebarInlineCreate(host.group, '', { after: host.after, level: host.level, ph: t('projects.newFolderPh'), label: t('projects.newFolderHead'), maxLen: 60 })
    : await ask(t('projects.newFolderHead'), { ph: t('projects.newFolderPh'), maxLen: 60 })
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
  let result
  try { result = await api('DELETE', `/api/projects/${p.id}/folders?path=${encodeURIComponent(path)}`) } // documents and files below it go to the trash
  catch (e) { toast(e.message); await sidebar(); return }
  if (docId && result?.documents?.includes(docId)) closeView()
  else if (activeFile && insideFolder(activeFile, path)) await switchTab('', true)
  if (docId) { filesDirty = true; await loadProjectFiles(true); tabSig = ''; queueRender() }
  await sidebar()
  const undo = async () => {
    try {
      for (const f of (result?.folders || [path])) await api('POST', `/api/projects/${p.id}/folders`, { path: f })
      for (const did of (result?.documents || [])) await api('POST', `/api/docs/${did}/restore`, {})
      for (const tid of (result?.trash_ids || [])) await api('POST', `/api/trash/${tid}/restore`, {})
      if (docId) { filesDirty = true; await loadProjectFiles(true); queueRender() }
      await sidebar()
    } catch (e) { toast(e.message) }
  }
  toast(t('docs.moveTrash'), undo, t('docs.restore'), 8000)
}
async function afterFolderRename(p, path, target) {
  const doc = docId, epoch = openN, was = activeFile
  const mapped = was && insideFolder(was, path) ? target + was.slice(path.length) : ''
  tabRemapPrefix(p.id, path, target)
  filesDirty = true
  if (mapped && docId === doc && openN === epoch) await switchTab('', true)
  if (docId === doc && openN === epoch && docProject === p.id) { await loadProjectFiles(true); tabSig = ''; queueRender() }
  await sidebarFresh() // a refresh started before the rename still lists the old path: paintTabs would drop the mapped tab
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
  const { changes } = await api('POST', `/api/projects/${p.id}/folders/rename-preview`, { path, target })
  const choice = await confirmMove(false, t('projects.renameFolder'), path, target, changes)
  if (!choice) return
  await api('POST', `/api/projects/${p.id}/folders/rename`, { path, target, fix_refs: choice !== 'alt' })
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
  // would only 410) and keep a local draft for offline the document text edits.
  if (docProject === p.id) closeView()
  await sidebar()
}
async function renameProjectDocument(d, host) {
  host = sidebarLiveHost(host, ['document', d.id, ''].join(':'))
  const label = host?.querySelector('.t')
  const title = label ? await sidebarInlineRename(host, label, d.title, { label: t('docs.renameDoc') }) : await ask(t('docs.renameDoc'), { value: d.title })
  if (!title?.trim()) return
  await api('POST', `/api/docs/${d.id}/rename`, { title: title.trim() })
  if (docId === d.id) { $('title').textContent = title.trim(); docTitle = title.trim(); tabSig = ''; paintTabs() }
  await sidebar()
}
async function renameProjectEntry(p, name, host) {
  if (!p) { toast(t('projects.contextGone')); return }
  host = sidebarLiveHost(host, ['file', '', name].join(':'))
  if (!await flushTab() || !await flushTpl()) return
  const label = host?.querySelector('.t')
  const dir = folderParent(name), base = folderBase(name) // the row shows only the name; the folder path stays hidden while renaming
  const next = label ? await sidebarInlineRename(host, label, base, { label: t('docs.renameDoc'), maxLen: 240, stem: true }) : await ask(t('projects.renameWarning'), { value: base, maxLen: 240, stem: true })
  const typed = next?.trim().replace(/^\/+|\/+$/g, '')
  if (!typed) return
  const target = typed.includes('/') ? typed : joinFolder(dir, typed) // typing a path still moves as before
  if (target === name) return
  await applyEntryRename(p, name, target)
}
function renameBody(from, to, changes, move = false) { // old -> new path, then every quoted reference that follows it
  const body = el('div', 'mBody')
  const path = el('div', 'mTarget mMove')
  path.append(el('span', 'mOld', from), el('span', 'mArrow', '→'), el('span', null, to))
  body.append(el('div', 'mLabel', t(move ? 'projects.newPlace' : 'projects.newName')), path)
  body.append(el('div', 'mLabel', t('projects.updatesTitle', { n: changes.length })))
  const list = el('div', 'mChanges')
  changes.forEach(c => {
    const row = el('div', 'mChange'), path = el('code')
    path.append(el('span', 'mOld', c.old), el('span', 'mArrow', '→'), el('span', null, c.new))
    row.append(el('span', 'mIn', c.in), path)
    list.append(row)
  })
  body.append(list)
  return body
}
function confirmMove(move, head, from, to, changes) { // true = with references, 'alt' = entry only, false = cancelled
  if (!changes.length) return Promise.resolve(true) // nothing quotes it: no dialog
  return ask(head, { noInput: true, body: renameBody(from, to, changes, move), ok: t(move ? 'projects.moveAction' : 'projects.renameAction'),
    alt: t(move ? 'projects.moveOnly' : 'projects.renameOnly') })
}
async function applyEntryRename(p, name, target, move = false) { // rename or move (a new path = a new folder): the listed quoted references follow
  if (!await flushTab() || !await flushTpl()) return
  const doc = docId, epoch = openN
  const preview = await api('POST', `/api/projects/${p.id}/files-move-preview`, { path: name, target })
  if (doc !== docId || epoch !== openN) return
  const choice = await confirmMove(move, t(move ? 'projects.moveFile' : 'files.renameHead'), name, preview.path, preview.changes)
  if (!choice) return
  if (doc !== docId || epoch !== openN) return
  const result = await api('POST', `/api/projects/${p.id}/files-move`, { path: name, target: preview.path, version: preview.version, fix_refs: choice !== 'alt' })
  tabRemapEntry(p.id, 'f:' + name, 'f:' + result.path)
  const reopen = docId === doc && openN === epoch && docProject === p.id && activeFile === name
  if (reopen) await switchTab('', true) // the moved text may carry rewritten references: load it fresh under its new path
  if (docId === doc && openN === epoch && docProject === p.id) { filesDirty = true; await loadProjectFiles(true); tabSig = ''; queueRender() }
  await sidebarFresh()
  if (reopen && docId === doc && openN === epoch) await switchTab(result.path)
}
async function moveEntryToFolder(p, entry, folder) { // drag onto a folder (or the project): same project only
  if (folder && folder.split('/').length > FOLDER_LEVELS) { toast(t('projects.folderDepth', { n: FOLDER_LEVELS })); return }
  if (entry.kind === 'document') {
    const current = projectEntries(p).documents.find(d => d.id === entry.doc_id)
    if (!current || (current.folder || '') === folder) return
    const { changes } = await api('POST', `/api/projects/${p.id}/docs/${entry.doc_id}/folder-preview`, { folder })
    const choice = await confirmMove(true, t('projects.moveDoc'), joinFolder(current.folder || '', current.title), joinFolder(folder, current.title), changes)
    if (!choice) return
    await api('POST', `/api/projects/${p.id}/docs/${entry.doc_id}/folder`, { folder, fix_refs: choice !== 'alt' })
    await sidebar(); return
  }
  const base = entry.name.split('/').pop(), next = folder ? folder + '/' + base : base
  if (next === entry.name) return
  await applyEntryRename(p, entry.name, next, true)
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
      const { changes } = await api('POST', `/api/projects/${source.id}/folders/rename-preview`, { path, target: next })
      const choice = await confirmMove(true, t('projects.moveFolder'), path, next, changes)
      if (!choice) return null
      await api('POST', `/api/projects/${source.id}/folders/rename`, { path, target: next, fix_refs: choice !== 'alt' })
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
async function trashFile(project, path) { // a delete names the version it removes: take it from a fresh list
  const file = (await api('GET', `/api/projects/${project}/files`)).files.find(f => f.path === path)
  if (!file) throw new Error(t('files.tplGone'))
  return api('DELETE', fileUrl(path, project) + '?version=' + encodeURIComponent(file.version))
}
async function deleteProjectEntry(p, name) {
  if (!p) { toast(t('projects.contextGone')); return }
  const doc = docId, epoch = openN
  let res
  try { res = await trashFile(p.id, name) } catch (e) { toast(e.message); await sidebar(); return }
  if (docId === doc && openN === epoch && docProject === p.id) {
    if (activeFile === name && !tabDirty) await switchTab('', true)
    filesDirty = true; await loadProjectFiles(true); queueRender()
  }
  await sidebar()
  const undo = res?.trash_id ? async () => {
    try {
      await api('POST', `/api/trash/${res.trash_id}/restore`, {})
      if (docId && docProject === p.id) { filesDirty = true; await loadProjectFiles(true); queueRender() }
      await sidebar()
    } catch (e) { toast(e.message) }
  } : null
  toast(t('docs.moveTrash'), undo, t('docs.restore'), 8000)
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
  return entries.documents.some(d => (d.folder || '') === path) || entries.files.some(f => f.path === path)
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
    files: entries.files.filter(f => insideFolder(f.path, path)),
    folders: (p.folders || []).filter(f => insideFolder(f, path)),
  }
}
function folderTreeFits(items, path, targetPath) { // never start a copy/move that must fail halfway on depth
  const tooDeep = p => p.split('/').filter(Boolean).length > FOLDER_LEVELS
  const rel = p => p === path ? '' : p.slice(path.length)
  if (tooDeep(targetPath)) return false
  if (items.folders.some(f => tooDeep(targetPath + rel(f)))) return false
  if (items.documents.some(d => tooDeep(targetPath + rel(d.folder || '')))) return false
  if (items.files.some(f => tooDeep(folderParent(targetPath + rel(f.path))))) return false
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
function entryAnchor(p, entry) {
  if (typeof document === 'undefined' || !document.querySelector) return null
  const esc = v => (typeof CSS !== 'undefined' && CSS.escape ? CSS.escape(v) : v)
  const group = `.project-group[data-project-id="${esc(p.id)}"]`
  const row = (entry?.kind === 'document' && entry.doc_id && document.querySelector(`aside [data-doc-id="${esc(entry.doc_id)}"]`))
    || (entry?.kind === 'file' && entry.name && document.querySelector(`${group} [data-package-key="${esc('file::' + entry.name)}"]`))
    || (entry?.kind === 'folder' && entry.name && [...document.querySelectorAll(`${group} .fhd.folder`)].find(r => r.dataset.folderPath === entry.name))
    || document.querySelector(`${group} .fhd.project`)
  return row?.querySelector('[data-side-menu]') || row
}
async function pickTargetFolder(p, head, exclude = '', reserve = 0, anchor = null, o = {}) {
  // reserve is the depth the moved entry adds itself: a folder needs one level,
  // files/documents none. Both allowed levels stay selectable for entries.
  const max = FOLDER_LEVELS - reserve
  const paths = projectFolderPaths(p).filter(f => f.split('/').length <= max && (!exclude || !insideFolder(f, exclude)))
  const values = ['', ...paths]
  const i = await pickPop(head, values.map(f => [f ? '/' + f : t('menu.projectRoot'), '']), anchor, o)
  if (i === 'back') return 'back'
  return i == null || i < 0 ? null : values[i]
}
async function pickProjectAndFolder(targets, head, reserve = 0, anchor = null) { // project -> folder inside one anchored popover with back navigation
  const pos = typeof window !== 'undefined' && window.__menuPopOrigin && Date.now() - window.__menuPopOrigin.at < 250
    ? { left: window.__menuPopOrigin.left, top: window.__menuPopOrigin.top } : null
  while (true) {
    const i = await pickPop(head, targets.map(x => [x.title, '']), anchor, pos ? { pos } : {})
    if (i == null || i < 0 || !targets[i]) return null
    let target
    try { target = await api('GET', `/api/projects/${targets[i].id}`) } catch (e) { toast(e.message); return null }
    const folder = await pickTargetFolder(target, t('menu.targetFolder', { project: target.title }), '', reserve, anchor, pos ? { back: true, pos } : { back: true })
    if (folder === 'back') continue
    if (folder == null) return null
    return { target, folder }
  }
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
    const body = { kind: entry.kind, doc_id: entry.doc_id || '', name: entry.name, target_project_id: target.id, target_name: targetName, move }
    if (entry.kind === 'document') body.target_folder = destFolder
    if (duplicate) body.duplicate = true
    try {
      const result = await api('POST', `/api/projects/${p.id}/transfer`, body)
      if (opts.refresh !== false) {
        await sidebar(); filesDirty = true
        if (docId) { await loadProjectFiles(true); tabSig = ''; queueRender() }
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
  const what = entry.kind
  const rename = actions.find(b => b.dataset.menuKey === 'rename')
  const trash = actions.find(b => b.dataset.menuKey === 'trash')
  const session = !!window.changeSession
  const writable = projectEditable(p) && !session
  return [
    rename && menuButtonItem(rename, what),
    writable && convertMenuItem(p, entry),
    writable && sidebarMenuItem('duplicate', () => transferEntryTo(p, entry, p, entryFolder(entry), false, { askName: false, duplicate: true }), { what }),
    !session && sidebarMenuItem('copy', null, { what, submenu: () => entryDestinationItems(p, entry, false, writable) }),
    writable && sidebarMenuItem('move', null, { what, submenu: () => entryDestinationItems(p, entry, true) }),
    trash && menuButtonItem(trash, what),
  ].filter(Boolean)
}
function convertMenuItem(p, entry) { // the only conversions: document -> .typ file, .typ file -> document
  if (entry.kind === 'document') return { label: t('projects.convertToFile'), title: t('projects.convertToFileHint'), run: () => convertEntry(p, entry) }
  return /\.typ$/i.test(entry.name) ? { label: t('projects.convertToDocument'), title: t('projects.convertDocumentHint'), run: () => convertEntry(p, entry) } : null
}
async function convertEntry(p, entry) {
  try {
    const document = entry.kind === 'document'
    if (!document) { // documents cannot be #included: show who still does
      const { references } = await api('POST', `/api/projects/${p.id}/files-move-preview`, { path: entry.name, target: entry.name })
      if (references?.length && !await ask([t('projects.convertBreaks'), ...references].join('\n'), { noInput: true })) return
    }
    const shown = document ? docId === entry.doc_id && !activeFile : docProject === p.id && activeFile === entry.name // was the converted thing open?
    const r = await api('POST', `/api/projects/${p.id}/convert`, document ? { doc_id: entry.doc_id } : { path: entry.name })
    await sidebarFresh() // the new entry shows at once; the old tab drops out with its entry
    if (r.id) { await openDoc(r.id); return }
    const target = projects.find(x => x.id === p.id) || p, host = projectEntries(target).documents.find(d => d.id !== entry.doc_id)
    if (shown && host) await openProjectEntry(target, host.id, r.path)
    else if (shown) closeView()
  } catch (e) { toast(e.message) }
}
function entryDestinationItems(p, entry, move, within = true) {
  const what = entry.kind
  const items = []
  if (within) items.push(sidebarMenuItem('copy', () => transferEntryWithin(p, entry, move), { what, label: t('menu.copyHere'), title: t('menu.copyHereHint') }))
  items.push(sidebarMenuItem('copy', () => transferEntryOther(p, entry, move), { what, label: t('menu.copyOther'), title: t('menu.copyOtherHint') }))
  if (!move && entry.kind === 'file' && TEXT_EXT.test(entry.name)) {
    items.push(sidebarMenuItem('copy', () => copyFileToPersonal(p.id, entry.name), { what, label: t('menu.copyGlobal'), title: t('menu.copyGlobalHint') }))
  }
  return items
}
async function transferEntryWithin(p, entry, move) {
  const folder = await pickTargetFolder(p, t('menu.copyHere'), '', 0, entryAnchor(p, entry))
  if (folder == null) return
  if (move) return moveEntryToFolder(p, entry, folder) // same project: the references dialog, like a drag
  // Documents may share a title across folders, but not within one; a copy into the same folder needs a new title.
  return transferEntryTo(p, entry, p, folder, move, { askName: false, duplicate: !move && entry.kind === 'document' && (entry.folder || '') === folder })
}
async function transferEntryOther(p, entry, move) {
  const targets = projects.filter(x => x.id !== p.id && projectEditable(x))
  if (!targets.length) { toast(t('projects.noOtherProject')); return }
  const picked = await pickProjectAndFolder(targets, t('menu.copyOther'), 0, entryAnchor(p, entry))
  if (!picked) return
  return transferEntryTo(p, entry, picked.target, picked.folder, move)
}
async function projectEntryMenu(p, entry, anchor) {
  const what = entry.kind
  const items = [
    sidebarMenuItem('copy', null, { what, submenu: () => entryDestinationItems(p, entry, false) }),
    sidebarMenuItem('move', null, { what, submenu: () => entryDestinationItems(p, entry, true) }),
  ]
  if (anchor && window.showMenuAt) { window.showMenuAt(anchor, items, 'left'); return }
  const i = await pickPop(entry.name, [[t('menu.copyTo'), t('menu.copyToHint', { what: menuWhat(what) })], [t('menu.moveTo'), t('menu.moveToHint', { what: menuWhat(what) })]], entryAnchor(p, entry))
  if (i == null || i < 0) return
  const destinations = entryDestinationItems(p, entry, i === 1)
  const j = await pickPop(i === 1 ? t('menu.moveTo') : t('menu.copyTo'), destinations.map(d => [d.label, d.title]), entryAnchor(p, entry))
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
  const parent = await pickTargetFolder(fresh, t('menu.copyHere'), path, 1, entryAnchor(p, { kind: 'folder', name: path }))
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
  const picked = await pickProjectAndFolder(targets, t('menu.copyOther'), 1, entryAnchor(p, { kind: 'folder', name: path }))
  if (!picked) return
  const name = await targetFolderName(picked.target, picked.folder, folderBase(path), !move)
  if (name) await copyFolderTree(p, path, picked.target, picked.folder, name, move)
}
async function copyFolderTree(source, path, target, parent, name, move) {
  const src = await api('GET', `/api/projects/${source.id}`)
  const tgt = target.id === source.id ? src : await api('GET', `/api/projects/${target.id}`)
  const targetPath = joinFolder(parent, name)
  const items = folderContents(src, path)
  if (!folderTreeFits(items, path, targetPath)) { toast(t('projects.folderDepth', { n: FOLDER_LEVELS })); return null }
  // Every entry is its own request. Keep an undo step per finished entry so a
  // conflict half-way (quota, a name clash, a permission) rolls the
  // whole folder back instead of leaving a half-transferred tree behind.
  const done = [], created = []
  const known = new Set(projectFolderPaths(tgt))
  const back = body => () => api('POST', `/api/projects/${target.id}/transfer`, body) // a move is undone by moving it home again
  const makeFolder = async p => {
    await api('POST', `/api/projects/${target.id}/folders`, { path: p })
    if (!known.has(p)) { known.add(p); created.push(p) }
  }
  try {
    for (const p of folderParents(targetPath)) await makeFolder(p)
    for (const f of items.folders) await makeFolder(f === path ? targetPath : targetPath + '/' + f.slice(path.length + 1))
    for (const f of items.files) { // files first: a document copied after them finds the files it reaches already there
      const to = targetPath + '/' + f.path.slice(path.length).replace(/^\/+/, '')
      const result = await transferEntryTo(source, { kind: 'file', name: f.path }, tgt, '', move, {
        askName: false, name: to, strict: true, refresh: false,
      })
      if (!result) continue
      done.push(move
        ? back({ kind: 'file', name: to, target_project_id: source.id, target_name: f.path, move: true })
        : () => trashFile(target.id, to))
    }
    const usedByFolder = new Map() // titles are unique per folder, so a copied folder keeps document names unless its target folder already has them
    const usedIn = folder => {
      if (!usedByFolder.has(folder)) usedByFolder.set(folder, new Set(projectEntries(tgt).documents.filter(d => (d.folder || '') === folder).map(d => d.title.toLowerCase())))
      return usedByFolder.get(folder)
    }
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
      done.push(move
        ? back({ kind: 'document', doc_id: d.id, name: suggested, target_project_id: source.id, target_name: d.title, target_folder: d.folder || '', move: true })
        : () => api('DELETE', `/api/docs/${result.doc_id}`))
    }
  } catch (e) {
    let stuck = 0
    for (const undo of done.reverse()) { try { await undo() } catch (err) { stuck++ } }
    for (const p of created.sort((a, b) => b.split('/').length - a.split('/').length)) { // deepest first; a folder that is not empty stays
      try { await api('DELETE', `/api/projects/${target.id}/folders?path=${encodeURIComponent(p)}`) } catch (err) {}
    }
    try { await sidebar(); filesDirty = true; if (docId) { await loadProjectFiles(true); tabSig = ''; queueRender() } } catch (err) {}
    const failure = new Error(t(stuck ? 'projects.folderTransferPartial' : 'projects.folderTransferUndone', { reason: e.message }))
    failure.status = e.status
    throw failure
  }
  if (move && target.id !== source.id) {
    try { await api('DELETE', `/api/projects/${source.id}/folders?path=${encodeURIComponent(path)}`) }
    catch (e) { if (e.status !== 409) throw e }
  }
  await sidebar(); filesDirty = true
  if (docId) { await loadProjectFiles(true); tabSig = ''; queueRender() }
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
    const i = await pickPop(t(move ? 'menu.moveTo' : 'menu.copyTo'), targets.map(x => [x.title, '']), entryAnchor(p, entry))
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
    if (data.items) return data.items.every(x => x.project === target.id && entryFolder(x.entry) === folder) ||
      data.items.some(x => x.project === target.id && x.entry.kind === 'folder' && insideFolder(folder, x.entry.name))
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
      if (data.items) { await sideSelDrop(sideSelResolve(data.items), target, folder, !e.ctrlKey && !e.metaKey); return }
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
