// Ctrl/Shift pick several project entries, across projects; the menu, drags and Delete then act on all of them.
const sideSel = new Map() // key -> { project, entry }, survives sidebar repaints
let sideSelAnchor = '', sideSelLone = '' // lone: the entry a plain click or arrow chose, selected without a mark
const sideSelKey = (project, entry) => [project, entry.kind, entry.kind === 'document' ? entry.doc_id : entry.name].join(':')
function sidebarSelectable(row, p, entry) {
  const key = sideSelKey(p.id, entry)
  row.dataset.selKey = key; row.sideEntry = { project: p.id, entry }
  if (sideSel.has(key)) sideSel.set(key, row.sideEntry) // a repaint brings fresh entry data
  row.classList.toggle('sel', sideSel.has(key))
}
const sideSelRows = () => [...document.querySelectorAll('aside [data-sel-key]')].filter(row => row.getClientRects().length)
const sideSelHolds = row => sideSel.size > 1 && sideSel.has(row?.dataset.selKey)
function paintSideSel() {
  const rows = [...document.querySelectorAll('aside [data-sel-key]')], marked = n => !!n?.classList.contains('sel')
  rows.forEach(row => { row.classList.toggle('sel', sideSel.has(row.dataset.selKey)); row.style.borderRadius = row.style.boxShadow = '' })
  const corner = join => join ? '0' : 'var(--r-sm)'
  rows.forEach(row => { // a run of selected rows reads as one block: shared edges lose their rounding
    if (!marked(row)) return
    const up = row.previousElementSibling, down = row.nextElementSibling
    row.style.borderRadius = [corner(marked(up)), corner(marked(up)), corner(marked(down)), corner(marked(down))].join(' ')
    if (marked(up)) return
    const run = [row]
    while (marked(run[run.length - 1].nextElementSibling)) run.push(run[run.length - 1].nextElementSibling)
    if (run.length < 2) return
    const boxes = run.map(r => r.getBoundingClientRect()), left = Math.min(...boxes.map(b => b.left)), right = Math.max(...boxes.map(b => b.right))
    run.forEach((r, i) => { // deeper rows keep their text indent; the fill reaches out to the run's outer edges
      const l = boxes[i].left - left, x = right - boxes[i].right
      r.style.boxShadow = [l && `-${l}px 0 0 0 var(--acc-soft)`, x && `${x}px 0 0 0 var(--acc-soft)`].filter(Boolean).join(', ')
    })
  })
}
function sideSelClear() {
  if (!sideSel.size) return
  sideSel.clear(); paintSideSel()
}
function sideSelPlain(key) {
  sideSelAnchor = sideSelLone = key || ''; sideSelClear()
}
function sideSelToggle(row) {
  const rows = sideSelRows()
  const seed = !sideSel.size && rows.find(r => r.dataset.selKey === sideSelLone) // the entry clicked last counts as selected, like any file explorer
  if (seed && seed !== row) sideSel.set(seed.dataset.selKey, seed.sideEntry)
  sideSelLone = ''
  const key = row.dataset.selKey
  sideSel.has(key) ? sideSel.delete(key) : sideSel.set(key, row.sideEntry)
  sideSelAnchor = key; paintSideSel()
}
function sideSelRange(row, add, from = null) {
  const rows = sideSelRows(), to = rows.indexOf(row)
  let at = rows.findIndex(r => r.dataset.selKey === sideSelAnchor)
  if (at < 0) {
    at = rows.indexOf(from && from.dataset.selKey ? from : rows.find(r => r.classList.contains('cur')) || row)
    if (at < 0) at = to
    sideSelAnchor = rows[at].dataset.selKey
  }
  if (!add) sideSel.clear()
  rows.slice(Math.min(at, to), Math.max(at, to) + 1).forEach(r => sideSel.set(r.dataset.selKey, r.sideEntry))
  paintSideSel()
}
function sideSelFocus(row) {
  const node = row.matches('[tabindex]') ? row : row.querySelector(':scope > b[tabindex]')
  try { node?.focus({ preventScroll: true }) } catch (e) {}
}
function sideSelResolve(list) { // live projects only, entries that still exist, nothing that already rides along inside a selected folder
  const items = list.map(({ project, entry }) => ({ p: projects.find(x => x.id === project), entry })).filter(({ p, entry }) => {
    if (!p) return false
    const entries = projectEntries(p)
    if (entry.kind === 'folder') return projectFolderPaths(p).includes(entry.name)
    return entry.kind === 'document' ? entries.documents.some(d => d.id === entry.doc_id) : entries.files.some(f => f.path === entry.name)
  })
  const at = ({ entry }) => entry.kind === 'document' ? entry.folder || '' : entry.name
  return items.filter(item => !items.some(other => other !== item && other.p.id === item.p.id && other.entry.kind === 'folder' &&
    insideFolder(at(item), other.entry.name) && !(item.entry.kind === 'folder' && item.entry.name === other.entry.name)))
}
function sideSelMenuItems() {
  const items = sideSelResolve([...sideSel.values()]), what = 'selection'
  const session = !!window.changeSession || !!window.suggestionDraft
  const writable = !session && items.every(item => projectEditable(item.p))
  return [
    { head: t('menu.selCount', { n: items.length }) },
    writable && sidebarMenuItem('duplicate', () => sideSelDuplicate(items), { what }),
    !session && sidebarMenuItem('copy', () => sideSelTransfer(items, false), { what }),
    writable && sidebarMenuItem('move', () => sideSelTransfer(items, true), { what }),
    writable && sidebarMenuItem('trash', () => sideSelTrash(items), { what }),
    { sep: true },
    { label: t('menu.selClear'), run: sideSelClear },
  ].filter(Boolean)
}
async function sideSelDuplicate(items) {
  for (const { p, entry } of items) {
    try {
      if (entry.kind === 'folder') await duplicateFolder(p, entry.name)
      else await transferEntryTo(p, entry, p, entryFolder(entry), false, { askName: false, duplicate: true })
    } catch (e) { toast(e.message) }
  }
  sideSelClear()
}
async function sideSelTransfer(items, move) {
  const targets = projects.filter(projectEditable).sort((a, b) => Number(b.id === docProject) - Number(a.id === docProject))
  if (!targets.length) { toast(t('projects.noOtherProject')); return }
  const anchor = document.querySelector('aside .sel') || $('own')
  const picked = await pickProjectAndFolder(targets, t(move ? 'menu.moveTo' : 'menu.copyTo'), items.some(item => item.entry.kind === 'folder') ? 1 : 0, anchor)
  if (picked) await sideSelDrop(items, picked.target, picked.folder, move)
}
async function sideSelDrop(items, target, folder, move) { // read-only sources are copied, never moved
  if (!await flushTab() || !await flushTpl()) return
  for (const { p, entry } of items) {
    const moving = move && projectEditable(p), same = p.id === target.id
    try {
      if (entry.kind === 'folder') {
        if (!same || !insideFolder(folder, entry.name)) await folderTransferTo(p, entry.name, target, folder, moving)
      } else if (same && moving) await moveEntryToFolder(p, entry, folder)
      else await transferEntryTo(p, entry, target, folder, moving, { askName: false, duplicate: same && entry.kind === 'document' && (entry.folder || '') === folder })
    } catch (e) { toast(e.message) }
  }
  sideSelClear()
}
async function sideSelTrash(items) {
  items = items.filter(item => projectEditable(item.p))
  if (items.length === 1) { // one entry keeps its own confirmation
    const [{ p, entry }] = items
    if (entry.kind === 'folder') return deleteFolder(p, entry.name)
    return entry.kind === 'document' ? moveDocToTrash({ id: entry.doc_id, title: entry.name }) : deleteProjectEntry(p, entry.name)
  }
  if (!items.length) return
  if (window.changeSession || window.suggestionDraft) { toast(t('packages.sourceBlocked')); return }
  if (!await flushTab() || !await flushTpl()) return
  if (!await ask(t('menu.selTrashConfirm', { n: items.length }), { noInput: true, danger: true, ok: t('docs.moveTrash') })) return
  const gone = new Set()
  for (const { p, entry } of items) {
    try {
      if (entry.kind === 'folder') (await api('DELETE', `/api/projects/${p.id}/folders?path=${encodeURIComponent(entry.name)}`))?.documents?.forEach(d => gone.add(d))
      else if (entry.kind === 'document') { await api('DELETE', `/api/docs/${entry.doc_id}`); gone.add(entry.doc_id) }
      else await trashFile(p.id, entry.name)
    } catch (e) { toast(e.message) }
  }
  sideSel.clear()
  if (docId && gone.has(docId)) closeView()
  else if (activeFile && items.some(({ p, entry }) => p.id === docProject && entry.kind !== 'document' && insideFolder(activeFile, entry.name))) await switchTab('', true)
  if (docId) { filesDirty = true; await loadProjectFiles(true); tabSig = ''; queueRender() }
  await sidebar()
}
function sideSelDragData(row, data) {
  return sideSelHolds(row) ? { ...data, items: [...sideSel.values()] } : null
}

document.addEventListener('mousedown', e => { // Shift+click extends the selection, not the page's text selection
  if (e.shiftKey && e.target.closest('aside [data-sel-key]') && !e.target.closest('button,input')) e.preventDefault()
}, true)
document.addEventListener('click', e => { // capture: a modified click selects instead of opening or folding
  const row = e.target.closest('aside [data-sel-key]')
  if (!row || e.target.closest('button,input')) return
  const mod = e.ctrlKey || e.metaKey
  if (!mod && !e.shiftKey) { sideSelPlain(row.dataset.selKey); return }
  e.preventDefault(); e.stopPropagation()
  if (e.shiftKey) sideSelRange(row, mod)
  else sideSelToggle(row)
  sideSelFocus(row)
}, true)
document.addEventListener('contextmenu', e => {
  const row = e.target.closest('aside [data-sel-key]')
  if (!row || e.target.closest('input') || !window.showMenuAt) return
  if (!sideSel.has(row.dataset.selKey)) sideSelPlain(row.dataset.selKey)
  const more = row.querySelector('[data-side-menu]')
  const items = sideSelHolds(row) ? sideSelMenuItems() : more?.sideMenuItems?.() || []
  if (!items.length) return
  e.preventDefault()
  window.showMenuAt(more || row, items)
})
document.addEventListener('keydown', e => { // arrows walk the sidebar rows; Shift extends, Ctrl+Space toggles, Ctrl+A takes all
  if (e.defaultPrevented || e.isComposing || e.altKey) return
  const node = e.target, row = node.closest('aside .doc, aside .fhd')
  if (!row || (node !== row && node.parentElement !== row) || node.matches('button,input')) return
  const mod = e.ctrlKey || e.metaKey, key = row.dataset.selKey
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    const list = [...document.querySelectorAll('aside .doc[tabindex], aside .fhd > b[tabindex]')].filter(n => n.getClientRects().length)
    const next = list[list.indexOf(node) + (e.key === 'ArrowDown' ? 1 : -1)]
    e.preventDefault()
    if (!next) return
    next.focus(); next.scrollIntoView({ block: 'nearest' })
    const to = next.closest('aside .doc, aside .fhd')
    if (e.shiftKey && to.dataset.selKey) sideSelRange(to, mod, row)
    else if (!mod) sideSelPlain(to.dataset.selKey)
  } else if (mod && !e.shiftKey && e.key.toLowerCase() === 'a') {
    e.preventDefault()
    sideSelRows().forEach(r => sideSel.set(r.dataset.selKey, r.sideEntry)); paintSideSel()
  } else if (e.key === 'Escape' && sideSel.size) {
    e.preventDefault(); sideSelLone = ''; sideSelClear()
  } else if (key && mod && e.key === ' ') {
    e.preventDefault(); sideSelToggle(row)
  } else if (key && e.key === 'Delete') {
    e.preventDefault()
    sideSelTrash(sideSelResolve(sideSel.has(key) ? [...sideSel.values()] : [row.sideEntry])).catch(err => toast(err.message))
  }
})
