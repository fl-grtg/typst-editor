// --- PWA: offline bar (no service worker since 2026-10-03; plain HTTP caching) ---
const offBar = $('offline'); const updOff = () => { offBar.style.display = navigator.onLine === false ? 'block' : 'none' }
addEventListener('online', updOff); addEventListener('offline', updOff); updOff()
// --- Share as popup next to comment button (not sidebar) ---
let shares = [], shareN = 0, invN = 0
async function loadShares() {
  const id = ++shareN, doc = docId
  try { shares = (await api('GET', `/api/docs/${doc}`)).shares } catch (e) { console.warn('shares failed', e); return }
  if (id !== shareN || doc !== docId) return
  renderShares()
}
function roleSel(cur) { // Reader/Editor options, translated labels, backend values untouched
  const s = el('select')
  ;[['reviewer', t('common.roleReader')], ['editor', t('common.roleEditor')]].forEach(([v, lab]) => {
    const o = el('option', null, lab); o.value = v; if (v === cur) o.selected = true; s.appendChild(o)
  })
  return s
}
function renderShares() {
  const p = $('sharePop'); p.replaceChildren()
  const top = el('div', 'sTop')
  const close = icoBtn(null, ICO_X); close.title = t('common.close'); close.setAttribute('aria-label', close.title)
  close.onclick = e => { e.stopPropagation(); p.style.display = 'none' }
  top.append(el('b', null, t('share.title')), close); p.appendChild(top)
  const row = el('div', 'row')
  const inp = el('input'); inp.placeholder = t('share.userPh'); inp.setAttribute('aria-label', t('share.userPh'))
  const sel = roleSel('reviewer'); sel.setAttribute('aria-label', t('common.roleAria'))
  const ok = el('button', null, t('share.add'))
  const go = () => { if (ok.disabled || !inp.value.trim()) return; ok.disabled = true; api('POST', `/api/docs/${docId}/share`,
    { username: inp.value.trim(), role: sel.value })
    .then(() => { inp.value = ''; loadShares() }).catch(e => toast(e.message)).finally(() => ok.disabled = false) }
  ok.onclick = go; inp.onkeydown = e => { if (e.key === 'Enter') go() }
  row.append(inp, sel, ok); p.appendChild(row)
  const list = el('div'); list.id = 'shares'
  shares.forEach(s => {
    const div = el('div')
    div.appendChild(el('span', 'who', s.username + ' '))
    const rs = roleSel(s.role); rs.setAttribute('aria-label', t('share.roleFor', { user: s.username })) // role editable inline (same endpoint as invite)
    rs.onchange = async () => {
      if (s.role === 'editor' && rs.value === 'reviewer' && !await ask(t('share.downgradeConfirm'), { noInput: true, danger: true, ok: t('share.downgrade') })) { rs.value = s.role; return }
      api('POST', `/api/docs/${docId}/share`, { username: s.username, role: rs.value })
        .then(loadShares).catch(e => toast(e.message))
    }
    const x = icoBtn(null, ICO_X); x.title = t('share.removeShare'); x.setAttribute('aria-label', x.title)
    x.onclick = async () => {
      if (!await ask(t('share.removeConfirm', { user: s.username }), { noInput: true, danger: true, ok: t('share.remove') })) return
      api('DELETE', `/api/docs/${docId}/share/${s.username}`).then(loadShares).catch(e => toast(e.message))
    }
    div.append(rs, x); list.appendChild(div)
  })
  p.appendChild(list)
  p.appendChild(el('b', null, t('share.inviteTitle')))
  const hint = el('div', 'hintline'); hint.textContent = t('share.inviteHint'); p.appendChild(hint)
  const irow = el('div', 'row')
  const isel = roleSel('reviewer'); isel.setAttribute('aria-label', t('common.roleAria'))
  const ibtn = el('button', null, t('share.createLink'))
  const ilink = el('input'); ilink.placeholder = t('share.noLink'); ilink.setAttribute('aria-label', t('share.linkAria')); ilink.readOnly = true
  ilink.onclick = () => ilink.select()
  const cbtn = el('button', null, t('share.copyLink')); cbtn.style.display = 'none'
  cbtn.onclick = async () => {
    try { await navigator.clipboard.writeText(ilink.value); toast(t('common.copied')) }
    catch (e) { ilink.select(); try { document.execCommand('copy') } catch (_) {} toast(t('common.copied')) }
  }
  ibtn.onclick = async () => {
    ibtn.disabled = true; const old = ibtn.textContent; ibtn.textContent = t('share.creating')
    try {
      const r = await api('POST', `/api/docs/${docId}/invite`, { role: isel.value })
      ilink.value = location.origin + '/?join=' + r.token
      ilink.select()
      cbtn.style.display = ''
      loadInvites()
    } catch (e) { toast(e.message) } finally { ibtn.disabled = false; ibtn.textContent = old }
  }
  irow.append(isel, ibtn, cbtn); p.appendChild(irow)
  const lrow = el('div', 'row'); lrow.appendChild(ilink); p.appendChild(lrow)
  const inv = el('div'); inv.id = 'invList'; p.appendChild(inv)
  loadInvites(); loadMembers()
}
async function loadInvites() { // open links: display + revoke only (link only at creation)
  const box = $('invList')
  if (!box || !docId) return
  const id = ++invN, doc = docId
  let list = []
  try { list = (await api('GET', `/api/docs/${doc}/invites`)).invites } catch (e) { console.warn('invites failed', e); return }
  if (id !== invN || doc !== docId) return
  box.replaceChildren()
  if (list.length) box.appendChild(el('div', null, t('share.linksHint')))
  list.forEach(inv => {
    const div = el('div')
    const roleName = ({ owner: t('common.roleOwner'), editor: t('common.roleEditor'), reviewer: t('common.roleReader') })[inv.role] || inv.role
    div.appendChild(el('span', 'who', t('share.inviteRow', { role: roleName, hint: inv.hint, date: (inv.created_at || '').slice(0, 10) })))
    const x = icoBtn(null, ICO_X); x.title = t('share.revoke'); x.setAttribute('aria-label', x.title)
    x.onclick = () => api('DELETE', `/api/docs/${docId}/invites/${inv.hint}`).then(loadInvites)
    div.append(x); box.appendChild(div)
  })
}
async function checkJoin() { // redeem ?join=TOKEN invite link via POST body (no token in URL/logs); returns doc id or null
  const j = new URLSearchParams(location.search).get('join')
  if (!j) return null
  history.replaceState(null, '', location.pathname) // always clear: never leave token in URL/history, even on error
  try {
    const id = (await api('POST', '/api/join', { token: j })).id
    await openDoc(id)
    return id
  }
  catch (e) { toast(e.message); return null }
}
function checkInvite() { // ?invite=CODE opens registration view with code prefilled (never auto-submits, never leaves token in URL)
  const q = new URLSearchParams(location.search)
  if (!q.has('invite')) return
  const code = (q.get('invite') || '').trim()
  q.delete('invite')
  const rest = q.toString()
  history.replaceState(null, '', location.pathname + (rest ? '?' + rest : '')) // clear token, keep ?join= for checkJoin
  if (!code) return
  if (!regMode) $('mode').click()
  $('inv').value = code
}
$('shareBtn').onclick = e => {
  e.stopPropagation()
  if (showPop('sharePop')) loadShares()
}
document.addEventListener('click', e => {
  for (const [p, b] of Object.entries(POP_BTN)) { // click outside closes (one loop not 5 blocks)
    const box = $(p)
    if (box && box.style.display !== 'none' && !$(b).contains(e.target) && !box.contains(e.target))
      box.style.display = 'none'
  }
  const pop = $('pop') // click outside closes, never with text draft (highlight/tooltip opens, not closes)
  if (pop && popAnchor != null && pop.style.display !== 'none' && Date.now() - popT > 300 && !e.target.closest('#pop,.cm-gutters,#cNew,.cm-hl,.cm-tooltip')
      && ![...pop.querySelectorAll('input')].some(i => i.value.trim()))
    closePop()
})
