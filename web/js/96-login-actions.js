// --- Login / Buttons ---
function paintMe() { // own blob in user box (image not color, missing = color)
  const bg = avBg(user || '?', colOf(user || '?'))
  const dot = $('meDot')
  dot.style.background = bg
  dot.textContent = (user || '?').slice(0, 2).toUpperCase()
  dot.title = 'me - ' + (user || '?') // aria-hidden: name lives in #who
  const who = $('who')
  who.innerHTML = ''
  who.appendChild(document.createTextNode(user || ''))
  const sub = document.createElement('small')
  sub.textContent = 'Settings'
  who.appendChild(sub)
}
let avatarV = 0
const avBg = (n, c) => avatarV ? `${c} url("/api/avatar/${encodeURIComponent(n)}?v=${avatarV}") center/cover` : c
let regMode = false
$('showPw').onchange = () => { $('p').type = $('showPw').checked ? 'text' : 'password' }
$('mode').onclick = e => {
  e.preventDefault(); regMode = !regMode
  $('go').textContent = regMode ? 'Sign up' : 'Sign in'
  $('mode').innerHTML = regMode ? 'Have an account? <b>Sign in</b>' : "Don't have an account? <b>Sign up</b>"
  $('inv').style.display = regMode ? '' : 'none'
  $('regHint').style.display = regMode ? '' : 'none'
  $('err').textContent = ''
}
async function login(u, p) {
  const go = $('go'), mode = $('mode'), old = go.textContent
  go.disabled = true; mode.disabled = true; go.textContent = regMode ? 'Signing up...' : 'Signing in...'
  try {
    const body = regMode ? { username: u, password: p, invite: $('inv').value.trim() || undefined } : { username: u, password: p }
    const d = await api('POST', regMode ? '/api/register' : '/api/login', body)
    user = d.user // session via cookie only (HttpOnly)
    $('p').value = ''; $('inv').value = ''
    try { avatarV = (await api('GET', '/api/me')).hasAvatar ? 1 : 0 } catch (e) {} // avatar must show without reload
    $('login').style.display = 'none'; $('app').classList.add('on')
    cm.measure() // built hidden (login): remeasure sync now, else cursor/clicks off
    paintMe()
    const hadJoin = !!new URLSearchParams(location.search).get('join')
    try { await sidebar(); } catch (e) {}
    watchSidebar()
    loadTpl(); const joined = await checkJoin()
    if (!docId && !tplName && !hadJoin && !joined) {
      const t = (lastOwn.find(x => x.title === 'Tutorial') || lastOwn[0] || lastShared[0])
      if (t) openDoc(t.id)
    }
  } finally { go.disabled = false; mode.disabled = false; go.textContent = regMode ? 'Sign up' : 'Sign in' }
}
$('login').onsubmit = e => { e.preventDefault(); login($('u').value, $('p').value).catch(err => $('err').textContent = err.message) }
$('out').onclick = () => { try { clearTimeout(sideESTimer); sideES?.close(); sideES = null } catch (e) {}; api('POST', '/api/logout').finally(() => {
  location.reload()
}) }
$('renBtn').onclick = async () => { // pencil behind title (owner only, template too)
  if (tplName) { // template: save new + delete old (else upsert overwrites)
    const t = await ask('Rename template', { value: tplName })
    if (t === null || !t.trim() || t.trim() === tplName) return
    await loadTpl() // fresh: else guard misses foreign names
    if (myTpl.some(x => x.name === t.trim())) { toast('Name already exists'); return }
    try {
      const old = myTpl.find(x => x.name === tplName)
      const r = await api('POST', '/api/templates', { name: t.trim(), content: getT(), folder: old && old.folder ? old.folder : '' })
      await api('DELETE', '/api/templates/' + encodeURIComponent(tplName))
      tplName = r.name; $('title').textContent = r.name
      await loadTpl(); renderTpl(); sidebar()
    } catch (e) { toast(e.message) }
    return
  }
  if (!docId || docRole !== 'owner') return
  const t = await ask('Rename document', { value: $('title').textContent })
  if (t === null || !t.trim()) return
  api('POST', `/api/docs/${docId}/rename`, { title: t.trim() })
    .then(() => { $('title').textContent = t.trim(); sidebar() })
    .catch(e => toast(e.message))
}
function askNewDoc() { // one dialog: title + folder radio + template radio (not 3 cascades)
  return new Promise(res => {
    if (askRes) askRes(null)
    const prev = document.activeElement
    const ov = $('modal'); ov.style.display = 'flex'; modalInert(true)
    $('mHead').textContent = 'New document'
    const inp = $('mInp'); inp.style.display = ''; inp.value = 'New document'; inp.placeholder = 'Title'; inp.setAttribute('aria-label', 'Title')
    const row = document.querySelector('#mCard .mRow'); row.style.display = ''
    const yes = $('mYes'); yes.textContent = 'Create'; yes.style.background = ''; yes.style.color = ''
    const box = document.createElement('div'); box.id = 'mExtra'
    const fl = el('label', null, 'Folder')
    let selF = ''
    const fgrp = el('div'); fgrp.setAttribute('role', 'radiogroup'); fgrp.setAttribute('aria-label', 'Folder')
    const nn = document.createElement('input'); nn.type = 'text'; nn.placeholder = 'New folder name'; nn.setAttribute('aria-label', 'New folder name'); nn.maxLength = 40; nn.style.display = 'none'
    const addF = (v, t) => { const b = el('button', 'pk' + (v === selF ? ' on' : ''), t); b.setAttribute('aria-pressed', v === selF); b.onclick = () => { selF = v; fgrp.querySelectorAll('.pk').forEach(x => { x.classList.remove('on'); x.setAttribute('aria-pressed', 'false') }); b.classList.add('on'); b.setAttribute('aria-pressed', 'true'); nn.style.display = v === '__new' ? '' : 'none'; if (v === '__new') nn.focus() }; fgrp.appendChild(b) }
    addF('', 'No folder (top of list)')
    folders.forEach(f => addF(f.folder, f.folder + ' (' + f.n + (f.n === 1 ? ' document)' : ' documents)')))
    addF('__new', '+ New folder …')
    box.append(fl, fgrp, nn, el('label', null, 'Template'))
    let selT = 0
    const grp = el('div'); grp.setAttribute('role', 'radiogroup'); grp.setAttribute('aria-label', 'Template')
    ;[['Blank', 'Empty page'], ['Report', 'A4 with title + intro'], ['Slides', 'Widescreen, 2 pages']].forEach((t, i) => {
      const b = el('button', 'pk' + (!i ? ' on' : ''), t[0] + ' – ' + t[1]); b.setAttribute('aria-pressed', !i)
      b.onclick = () => { selT = i; grp.querySelectorAll('.pk').forEach(x => { x.classList.remove('on'); x.setAttribute('aria-pressed', 'false') }); b.classList.add('on'); b.setAttribute('aria-pressed', 'true') }
      grp.appendChild(b)
    })
    box.appendChild(grp)
    $('mCard').insertBefore(box, row)
    const done = v => { ov.style.display = 'none'; modalInert(false); box.remove(); askRes = null; prev?.focus?.(); res(v) }
    askRes = () => done(null)
    $('mNo').onclick = () => done(null)
    yes.onclick = () => { done({ title: inp.value, folder: selF === '__new' ? nn.value.trim() : selF, tpl: selT }) }
    inp.onkeydown = e => { if (e.key === 'Enter') yes.onclick() }
    setTimeout(() => inp.focus(), 30)
  })
}
function askNewTpl() { // one dialog: name + folder radio (like askNewDoc, not 3 cascades)
  return new Promise(res => {
    if (askRes) askRes(null)
    const prev = document.activeElement
    const ov = $('modal'); ov.style.display = 'flex'; modalInert(true)
    $('mHead').textContent = 'New template'
    const inp = $('mInp'); inp.style.display = ''; inp.value = ''; inp.placeholder = 'name.typ'; inp.setAttribute('aria-label', 'Name')
    const row = document.querySelector('#mCard .mRow'); row.style.display = ''
    const yes = $('mYes'); yes.textContent = 'Create'; yes.style.background = ''; yes.style.color = ''
    const box = document.createElement('div'); box.id = 'mExtra'
    const fl = el('label', null, 'Folder')
    let selF = ''
    const fgrp = el('div'); fgrp.setAttribute('role', 'radiogroup'); fgrp.setAttribute('aria-label', 'Folder')
    const nn = document.createElement('input'); nn.type = 'text'; nn.placeholder = 'New folder name'; nn.setAttribute('aria-label', 'New folder name'); nn.maxLength = 40; nn.style.display = 'none'
    const addF = (v, t) => { const b = el('button', 'pk' + (v === selF ? ' on' : ''), t); b.setAttribute('aria-pressed', v === selF); b.onclick = () => { selF = v; fgrp.querySelectorAll('.pk').forEach(x => { x.classList.remove('on'); x.setAttribute('aria-pressed', 'false') }); b.classList.add('on'); b.setAttribute('aria-pressed', 'true'); nn.style.display = v === '__new' ? '' : 'none'; if (v === '__new') nn.focus() }; fgrp.appendChild(b) }
    addF('', 'No folder (top of list)')
    tplFolders.forEach(f => addF(f.folder, f.folder + ' (' + f.n + (f.n === 1 ? ' template)' : ' templates)')))
    addF('__new', '+ New folder …')
    box.append(fl, fgrp, nn)
    $('mCard').insertBefore(box, row)
    const done = v => { ov.style.display = 'none'; modalInert(false); box.remove(); askRes = null; prev?.focus?.(); res(v) }
    askRes = () => done(null)
    $('mNo').onclick = () => done(null)
    yes.onclick = () => { done({ name: inp.value, folder: selF === '__new' ? nn.value.trim() : selF }) }
    inp.onkeydown = e => { if (e.key === 'Enter') yes.onclick() }
    setTimeout(() => inp.focus(), 30)
  })
}
$('new').onclick = async () => {
  const k = await askPick('New', [['Document', 'Blank document, report or slides'], ['Template', 'Reuse saved text with one line'], ['Upload .typ', 'New document from a file']])
  if (k === 1) { newTemplate(); return }
  if (k === 2) { $('docPick').click(); return }
  if (k !== 0) return
  const r = await askNewDoc()
  if (!r) return
  const b = $('new'), old = b.textContent; b.disabled = true; b.textContent = 'Creating...'
  try { openDoc((await api('POST', '/api/docs/create', { title: (r.title || '').trim() || 'New document', content: STARTERS[r.tpl] || '', folder: r.folder })).id) }
  catch (e) { toast(e.message) } finally { b.disabled = false; b.textContent = old }
}
let upBusy = false // double-click: no second doc
$('upDoc').onclick = () => $('docPick').click()
$('docPick').onchange = async () => { // .typ as normal doc (not template): title from filename
  const f = $('docPick').files[0]; $('docPick').value = ''
  if (!f || upBusy) return
  if (!/\.typ$/i.test(f.name)) { toast('Only .typ'); return }
  if (f.size > 200 * 1024) { toast('Max 200 KB'); return }
  upBusy = true
  try {
    const txt = await f.text()
    if (!txt.trim()) { toast('Empty file'); return }
    if (txt.length > 200 * 1024) { toast('Max 200 KB'); return }
    const t = f.name.replace(/\.typ$/i, '').replace(/\s+/g, ' ').trim().slice(0, 100) || 'New document'
    openDoc((await api('POST', '/api/docs/create', { title: t, content: txt })).id)
  } catch (e) { toast(e.message) } finally { upBusy = false }
}
$('del').onclick = async () => {
  if (tplName) { // delete open template
    if (!await ask(`Delete template "${tplName}"?`, { noInput: true, ok: 'Delete', danger: true })) return
    try { await api('DELETE', '/api/templates/' + encodeURIComponent(tplName)) }
    catch (e) { toast(e.message); return }
    tplName = ''
    closeView(); $('viewSeg').style.display = '' // segment back: no doc, but view selectable
    await loadTpl(); sidebar()
    return
  }
  if (openedTrashed) {
    if (!await ask('Delete permanently? Gone is gone.', { noInput: true, ok: 'Delete', danger: true })) return
  } else if (!await ask('Move to trash?', { noInput: true, ok: 'OK' })) return
  api('DELETE', `/api/docs/${docId}`).then(() => { closeView(); sidebar() }).catch(e => toast(e.message))
}
setInterval(() => { if (docId) loadComments().catch(e => console.warn('comments poll failed', e)) }, POLL_MS)
const unsafeState = () => { // edits that may not have reached the server yet
  const s = $('save').textContent || ''
  if (!docId && !tplName) return false
  if (openedTrashed || docRole === 'reviewer') return false
  if (!/^(…|Error|Offline)/.test(s)) return false
  return !(prov && prov.wsconnected && synced && !activeFile && !tplName) // live main.typ: Yjs already carried it
}
addEventListener('beforeunload', e => { if (unsafeState()) { e.preventDefault(); e.returnValue = '' } }) // offline/failed save: browser asks before closing
addEventListener('pagehide', () => { // stash latest edits, 2s save may still be pending
  const live = !!(prov && prov.wsconnected)
  if ($('save').textContent.startsWith('saved')) { try { if (docId) localStorage.removeItem('typst-pending-' + docId) } catch (e) {} return } // saved: no stash (a stale stash would later clobber others' edits)
  try { if (docId && ytext && synced && docRole !== 'reviewer' && !live) { const c = ytext.toString(); if (c) lsSet('typst-pending-' + docId, JSON.stringify({ t: Date.now(), c })) } } catch (e) {} // offline only: keepalive may fail, openDoc offers restore
  const head = { 'Content-Type': 'application/json' }
  if (tplName)
    fetch('/api/templates', { method: 'POST', headers: head,
      body: JSON.stringify({ name: tplName, content: getT() }), keepalive: true })
  else if (docId && activeFile)
    fetch(`/api/docs/${docId}/files/${encodeURIComponent(activeFile)}/text`, { method: 'POST', headers: head,
      body: JSON.stringify({ content: getT() }), keepalive: true })
  else if (docId && ytext && synced && docRole !== 'reviewer')
    fetch(`/api/docs/${docId}/save`, { method: 'POST', headers: head,
      body: JSON.stringify({ content: ytext.toString(), force: live }), keepalive: true }) // offline copy may be stale: no force over others' work
})

checkInvite() // ?invite=CODE: registration view + prefilled code (join handled separately by checkJoin)
api('GET', '/api/me').then(async d => { // session via cookie only (HttpOnly)
  user = d.user; avatarV = d.hasAvatar ? 1 : 0 // persist avatar across reloads
  $('login').style.display = 'none'; $('app').classList.add('on')
  cm.measure() // see above: built hidden -> remeasure sync
  paintMe()
  const hadJoin = !!new URLSearchParams(location.search).get('join')
  try { await sidebar(); } catch (e) {}
  watchSidebar()
  loadTpl(); const joined = await checkJoin()
  if (!docId && !tplName && !hadJoin && !joined) {
    const t = (lastOwn.find(x => x.title === 'Tutorial') || lastOwn[0] || lastShared[0])
    if (t) openDoc(t.id)
  }
}).catch(e => console.warn('session restore failed', e))
try { (window.requestIdleCallback || (fn => setTimeout(fn, 1500)))(() => ensureTypst().catch(() => {})) } catch (e) {} // warm compiler when idle: UI paints first
window.__booted = true // module alive: login guard in classic script stands down
document.getElementById('booterr')?.remove() // module running: remove boot error box

