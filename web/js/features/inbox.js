// --- Inbox (bell, top right): mentions, proposals, change notices; click goes to the place ---
let inboxItems = [], inboxUnread = 0
async function loadInbox() {
  loadWatch().catch(() => {})
  const d = await api('GET', '/api/notifications')
  inboxItems = d.items; inboxUnread = d.unread
  paintInboxBadge()
  if ($('inboxPop').style.display !== 'none') renderInbox()
}
function paintInboxBadge() {
  const b = $('inboxBtn'), n = $('inboxN')
  b.hidden = !user
  n.hidden = !inboxUnread
  n.textContent = inboxUnread > 99 ? '99+' : String(inboxUnread)
  const label = t('inbox.title') + (inboxUnread ? ' (' + inboxUnread + ')' : '')
  b.title = label; b.setAttribute('aria-label', label)
}
function inboxText(it) {
  const v = { actor: it.actor, project: it.project_title || '', title: it.text }
  return it.type === 'mention' ? t('inbox.mention', v) : it.type === 'proposal' ? t('inbox.proposal', v) : it.type === 'changes' ? t('inbox.changes', v) : it.text
}
function renderInbox() {
  const p = $('inboxPop'); p.replaceChildren()
  const top = el('div', 'sTop'), all = el('button', null, t('inbox.readAll'))
  all.disabled = !inboxUnread
  all.onclick = async () => { try { await api('POST', '/api/notifications/read-all'); await loadInbox() } catch (e) { toast(e.message) } }
  top.append(el('b', null, t('inbox.title')), all); p.appendChild(top)
  if (!inboxItems.length) { p.appendChild(el('div', 'histEmpty', t('inbox.empty'))); return }
  inboxItems.forEach(it => {
    const row = el('button', 'inItem' + (it.is_read ? '' : ' unread'))
    row.type = 'button'
    const tx = el('span', 'tx'); tx.appendChild(el('span', 'ln', inboxText(it)))
    if (it.type === 'mention' && it.text) tx.appendChild(el('span', 'sub', it.text))
    tx.appendChild(el('span', 'sub', ago(it.created_at)))
    row.append(el('i', 'dot'), tx)
    row.onclick = () => goInbox(it).catch(e => toast(e.message))
    p.appendChild(row)
  })
}
$('inboxBtn').onclick = e => { e.stopPropagation(); if (showPop('inboxPop')) { renderInbox(); loadInbox().catch(() => {}) } }
async function inboxLeaveSession() { return !window.changeSession || await endChangeSession() }
async function goInbox(it) {
  hidePops()
  if (!it.is_read) { api('POST', `/api/notifications/${it.id}/read`).then(loadInbox).catch(() => {}) }
  if (it.type === 'proposal') return openTopPackage({ project: it.project_id, id: it.ref })
  if (it.type === 'mention') {
    if (!await inboxLeaveSession()) return
    if (it.doc_id !== docId) { await openDoc(it.doc_id); if (docId !== it.doc_id) return }
    if (activeFile) await switchTab('')
    await loadComments(true)
    const th = threads.find(x => x.id === it.ref)
    if (!th) { toast(t('inbox.gone')); return }
    const line = Math.max(1, Math.min(cm.state.doc.lines, th.anchor || 1))
    cm.dispatch({ selection: { anchor: cm.state.doc.line(line).from }, effects: EditorView.scrollIntoView(cm.state.doc.line(line).from, { y: 'center' }) })
    openPop(line, false)
    return
  }
  if (it.type === 'changes') return openProjectChanges(it.project_id, it.project_title)
}
async function openProjectChanges(pid, name = '') { // everything that changed since the user last looked
  if (docProject !== pid) { // show the project behind the dialog
    const row = [...(lastOwn || []), ...(lastShared || [])].find(x => x.project_id === pid)
    if (row && (!window.changeSession || await endChangeSession())) await openDoc(row.id)
  }
  const url = `/api/projects/${pid}/snapshots`
  const w = await api('GET', `/api/projects/${pid}/watch`)
  if (!w.base) { toast(t('inbox.noBase')); return }
  const list = (await api('GET', url)).snapshots
  await openChanges({ url, sid: w.base, list, title: t('inbox.changesTitle', { project: name }),
    onClose: () => api('POST', `/api/projects/${pid}/watch/seen`).then(loadInbox).catch(() => {}) })
}
// --- watch level per project: bell on the project row, small check-mark menu (like GitHub "Watch") ---
let watchLevels = {} // project id -> 'mentions' | 'proposals' | 'all' (missing = default)
const WATCH_DEFAULT = 'proposals'
const ICO_BELL = svgI('<path d="M8 2.2a4 4 0 0 0-4 4c0 3-1.5 4.3-1.5 4.3h11S12 9.2 12 6.2a4 4 0 0 0-4-4z"/><path d="M6.5 13a1.5 1.5 0 0 0 3 0"/>')
const ICO_BELL_ALL = svgI('<path d="M8 2.2a4 4 0 0 0-4 4c0 3-1.5 4.3-1.5 4.3h11S12 9.2 12 6.2a4 4 0 0 0-4-4z" fill="currentColor"/><path d="M6.5 13a1.5 1.5 0 0 0 3 0"/>')
const ICO_BELL_OFF = svgI('<path d="M8 2.2a4 4 0 0 0-4 4c0 3-1.5 4.3-1.5 4.3h11S12 9.2 12 6.2a4 4 0 0 0-4-4z"/><path d="M6.5 13a1.5 1.5 0 0 0 3 0"/><path d="M2 2l12 12"/>')
const watchIcon = l => l === 'all' ? ICO_BELL_ALL : l === 'mentions' ? ICO_BELL_OFF : ICO_BELL
const watchLabel = l => l === 'all' ? t('inbox.lvlAll') : l === 'mentions' ? t('inbox.lvlMentions') : t('inbox.lvlProposals')
const watchSub = l => l === 'all' ? t('inbox.lvlAllSub') : l === 'mentions' ? t('inbox.lvlMentionsSub') : t('inbox.lvlProposalsSub')
async function loadWatch() {
  const d = await api('GET', '/api/watch')
  const next = Object.fromEntries(d.projects.map(w => [w.project_id, w.level]))
  if (JSON.stringify(next) === JSON.stringify(watchLevels)) return // no repaint on every inbox event
  watchLevels = next
  if (!document.querySelector('aside input.renameInput')) { paintOwn(); paintShared(lastShared) }
}
function closeWatchBox() { document.getElementById('watchBox')?.remove() }
function openWatchBox(p, btn) {
  const was = document.getElementById('watchBox'); closeWatchBox()
  if (was && was.dataset.project === p.id) return // second click closes
  const box = el('div'); box.id = 'watchBox'; box.dataset.project = p.id; box.setAttribute('role', 'menu')
  box.setAttribute('aria-label', t('inbox.watchMenu'))
  const cur = watchLevels[p.id] || WATCH_DEFAULT
  ;['mentions', 'proposals', 'all'].forEach(l => {
    const row = el('button', 'wItem'); row.type = 'button'; row.setAttribute('role', 'menuitemradio'); row.setAttribute('aria-checked', String(l === cur))
    row.title = watchSub(l) // explanation on hover only
    row.append(el('i', 'ck', l === cur ? '✓' : ''), el('span', 'ln', watchLabel(l)))
    row.onclick = async e => {
      e.stopPropagation(); closeWatchBox()
      if (l === cur) return
      try { await api('PUT', `/api/projects/${p.id}/watch`, { level: l }); watchLevels[p.id] = l; paintOwn(); paintShared(lastShared) }
      catch (err) { toast(err.message) }
    }
    box.appendChild(row)
  })
  document.body.appendChild(box)
  const r = btn.getBoundingClientRect(), w = box.offsetWidth
  box.style.top = Math.min(r.bottom + 4, innerHeight - box.offsetHeight - 8) + 'px'
  box.style.left = Math.max(8, Math.min(r.left, innerWidth - w - 8)) + 'px'
  const off = e => { if (!box.contains(e.target)) { closeWatchBox(); document.removeEventListener('pointerdown', off, true); document.removeEventListener('keydown', esc, true) } }
  const esc = e => { if (e.key === 'Escape') { e.stopPropagation(); closeWatchBox(); document.removeEventListener('pointerdown', off, true); document.removeEventListener('keydown', esc, true); btn.focus() } }
  setTimeout(() => { document.addEventListener('pointerdown', off, true); document.addEventListener('keydown', esc, true) })
  box.querySelector('.wItem').focus()
}
