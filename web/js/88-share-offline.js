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
function renderShares() {
  const p = $('sharePop'); p.replaceChildren()
  const top = el('div', 'sTop')
  const close = icoBtn(null, ICO_X); close.title = 'Close'; close.setAttribute('aria-label', close.title)
  close.onclick = e => { e.stopPropagation(); p.style.display = 'none' }
  top.append(el('b', null, 'Share'), close); p.appendChild(top)
  const row = el('div', 'row')
  const inp = el('input'); inp.placeholder = 'Username'; inp.setAttribute('aria-label', 'Username')
  const sel = el('select'); sel.setAttribute('aria-label', 'Role')
  sel.innerHTML = '<option value="reviewer">Reader</option><option value="editor">Editor</option>'
  const ok = el('button', null, 'Add')
  const go = () => { if (ok.disabled || !inp.value.trim()) return; ok.disabled = true; api('POST', `/api/docs/${docId}/share`,
    { username: inp.value.trim(), role: sel.value })
    .then(() => { inp.value = ''; loadShares() }).catch(e => toast(e.message)).finally(() => ok.disabled = false) }
  ok.onclick = go; inp.onkeydown = e => { if (e.key === 'Enter') go() }
  row.append(inp, sel, ok); p.appendChild(row)
  const list = el('div'); list.id = 'shares'
  shares.forEach(s => {
    const div = el('div')
    div.appendChild(el('span', 'who', s.username + ' '))
    const rs = el('select'); rs.setAttribute('aria-label', 'Role for ' + s.username) // role editable inline (same endpoint as invite)
    rs.innerHTML = '<option value="reviewer">Reader</option><option value="editor">Editor</option>'
    rs.value = s.role
    rs.onchange = async () => {
      if (s.role === 'editor' && rs.value === 'reviewer' && !await ask('Downgrade to Reader? This wipes all Editor invite links for the doc.', { noInput: true, danger: true, ok: 'Downgrade' })) { rs.value = s.role; return }
      api('POST', `/api/docs/${docId}/share`, { username: s.username, role: rs.value })
        .then(loadShares).catch(e => toast(e.message))
    }
    const x = icoBtn(null, ICO_X); x.title = 'Remove share'; x.setAttribute('aria-label', x.title)
    x.onclick = async () => {
      if (!await ask('Remove ' + s.username + '? This also wipes all invite links for the doc.', { noInput: true, danger: true, ok: 'Remove' })) return
      api('DELETE', `/api/docs/${docId}/share/${s.username}`).then(loadShares).catch(e => toast(e.message))
    }
    div.append(rs, x); list.appendChild(div)
  })
  p.appendChild(list)
  p.appendChild(el('b', null, 'Invite via link'))
  const hint = el('div', 'hintline'); hint.textContent = 'Anyone with this link can open the document. You can create a new link anytime.'; p.appendChild(hint)
  const irow = el('div', 'row')
  const isel = el('select'); isel.setAttribute('aria-label', 'Role')
  isel.innerHTML = '<option value="reviewer">Reader</option><option value="editor">Editor</option>'
  const ibtn = el('button', null, 'Create link')
  const ilink = el('input'); ilink.placeholder = 'No link yet — create one'; ilink.setAttribute('aria-label', 'Invite link'); ilink.readOnly = true
  ilink.onclick = () => ilink.select()
  const cbtn = el('button', null, 'Copy link'); cbtn.style.display = 'none'
  cbtn.onclick = async () => {
    try { await navigator.clipboard.writeText(ilink.value); toast('Copied') }
    catch (e) { ilink.select(); try { document.execCommand('copy') } catch (_) {} toast('Copied') }
  }
  ibtn.onclick = async () => {
    ibtn.disabled = true; const old = ibtn.textContent; ibtn.textContent = 'Creating...'
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
  if (list.length) box.appendChild(el('div', null, 'Links can only be copied when created'))
  list.forEach(t => {
    const div = el('div')
    div.appendChild(el('span', 'who', (({ owner: 'Owner', editor: 'Editor', reviewer: 'Reader' })[t.role] || t.role) + ': ' + t.hint + '… (' + (t.created_at || '').slice(0, 10) + ') '))
    const x = icoBtn(null, ICO_X); x.title = 'Revoke'; x.setAttribute('aria-label', x.title)
    x.onclick = () => api('DELETE', `/api/docs/${docId}/invites/${t.hint}`).then(loadInvites)
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
