// --- Inbox (bell, top right): mentions, proposals, change notices; click goes to the place ---
let inboxItems = [], inboxUnread = 0
async function loadInbox() {
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
const ICO_SLIDERS = svgI('<path d="M2.5 5h11M2.5 11h11"/><circle cx="6" cy="5" r="1.6"/><circle cx="10" cy="11" r="1.6"/>')
let inboxView = 'list'
function renderInbox() {
  if (inboxView === 'settings') return renderWatchSettings()
  const p = $('inboxPop'); p.replaceChildren()
  const top = el('div', 'sTop'), all = el('button', null, t('inbox.readAll'))
  const gear = icoBtn(null, ICO_SLIDERS); gear.title = t('inbox.watchMenu'); gear.setAttribute('aria-label', gear.title)
  gear.onclick = e => { e.stopPropagation(); inboxView = 'settings'; renderInbox() } // stop: the re-render detaches the target, the outside-click closer would shut the popover
  all.disabled = !inboxUnread
  all.onclick = async () => { try { await api('POST', '/api/notifications/read-all'); await loadInbox() } catch (e) { toast(e.message) } }
  top.append(el('b', null, t('inbox.title')), all, gear); p.appendChild(top)
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
$('inboxBtn').onclick = e => { e.stopPropagation(); if (showPop('inboxPop')) { inboxView = 'list'; renderInbox(); loadInbox().catch(() => {}) } }
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
// watch level per project: small settings view inside the bell popover
const watchLabel = l => l === 'all' ? t('inbox.lvlAll') : l === 'mentions' ? t('inbox.lvlMentions') : t('inbox.lvlProposals')
const watchSub = l => l === 'all' ? t('inbox.lvlAllSub') : l === 'mentions' ? t('inbox.lvlMentionsSub') : t('inbox.lvlProposalsSub')
async function renderWatchSettings() {
  const p = $('inboxPop'); p.replaceChildren()
  const top = el('div', 'sTop'), back = el('button', null, '‹ ' + t('inbox.title'))
  back.onclick = e => { e.stopPropagation(); inboxView = 'list'; renderInbox() }
  top.append(el('b', null, t('inbox.watchMenu')), back); p.appendChild(top)
  p.appendChild(el('div', 'histEmpty', t('inbox.watchMenuSub')))
  let list = []
  try { list = (await api('GET', '/api/watch')).projects } catch (e) { p.appendChild(el('div', 'histEmpty', e.message)); return }
  if (inboxView !== 'settings') return
  list.forEach(w => {
    const row = el('label', 'wRow'), sel = el('select')
    ;['mentions', 'proposals', 'all'].forEach(l => { const o = el('option', null, watchLabel(l)); o.value = l; o.title = watchSub(l); sel.appendChild(o) })
    sel.value = w.level
    sel.setAttribute('aria-label', w.title)
    sel.onchange = async () => {
      try { await api('PUT', `/api/projects/${w.project_id}/watch`, { level: sel.value }); w.level = sel.value }
      catch (e) { sel.value = w.level; toast(e.message) }
    }
    row.append(el('span', 'wn', w.title), sel); p.appendChild(row)
  })
}
