// --- Login / Buttons ---
function paintMe() { // own blob in user box (image not color, missing = color)
  const bg = avBg(user || '?', colOf(user || '?'))
  const dot = $('meDot')
  dot.style.background = bg
  dot.textContent = (user || '?').slice(0, 2).toUpperCase()
  dot.title = t('login.meSelf', { name: user || '?' }) // aria-hidden: name lives in #who
  const who = $('who')
  who.innerHTML = ''
  who.appendChild(document.createTextNode(user || ''))
  const sub = document.createElement('small')
  sub.textContent = t('login.settingsLink')
  who.appendChild(sub)
}
let avatarV = 0
const avBg = (n, c) => avatarV ? `${c} url("/api/avatar/${encodeURIComponent(n)}?v=${avatarV}") center/cover` : c
let regMode = false
$('showPw').onchange = () => { $('p').type = $('showPw').checked ? 'text' : 'password' }
$('mode').onclick = e => {
  e.preventDefault(); regMode = !regMode
  $('go').textContent = regMode ? t('login.signUp') : t('login.signIn')
  $('mode').innerHTML = regMode ? t('login.haveAccount') : t('login.noAccount')
  $('inv').style.display = regMode ? '' : 'none'
  $('regHint').style.display = regMode ? '' : 'none'
  $('err').textContent = ''
}
async function login(u, p) {
  const go = $('go'), mode = $('mode'), old = go.textContent
  go.disabled = true; mode.disabled = true; go.textContent = regMode ? t('login.signingUp') : t('login.signingIn')
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
    await loadTpl(); const joined = await checkJoin()
    if (!docId && !tplName && !hadJoin && !joined) {
      const pick = (lastOwn.find(x => x.title === 'Tutorial') || lastOwn[0] || lastShared[0])
      if (pick) openDoc(pick.id)
    }
  } finally { go.disabled = false; mode.disabled = false; go.textContent = regMode ? t('login.signUp') : t('login.signIn') }
}
$('login').onsubmit = e => { e.preventDefault(); login($('u').value, $('p').value).catch(err => $('err').textContent = err.message) }
$('out').onclick = () => { try { clearTimeout(sideESTimer); sideES?.close(); sideES = null } catch (e) {}; api('POST', '/api/logout').finally(() => {
  location.reload()
}) }
$('renBtn').onclick = async () => { // pencil behind title (owner only, template too)
  const doc = docId, epoch = openN
  if (tplName) { await renamePersonalResource(tplName); return }
  if (!docId || docRole !== 'owner') return
  const nt = await ask(t('docs.renameDoc'), { value: (typeof docTitle !== 'undefined' && docTitle) || $('title').textContent })
  if (nt === null || !nt.trim()) return
  if (doc !== docId || epoch !== openN) return
  api('POST', `/api/docs/${doc}/rename`, { title: nt.trim() })
    .then(() => { if (doc === docId && epoch === openN) { $('title').textContent = nt.trim(); docTitle = nt.trim(); tabSig = ''; paintTabs() } sidebar() })
    .catch(e => toast(e.message))
}
function askNewDoc(uploadTitle) { // one dialog: title + folder radio + gallery grid (not 3 cascades)
  return new Promise(res => {
    if (askRes) askRes(null)
    const prev = document.activeElement
    const ov = $('modal'); ov.style.display = 'flex'; modalInert(true)
    $('mHead').textContent = t('docs.newDocTitle')
    const inp = $('mInp'); inp.style.display = ''; inp.value = uploadTitle || t('docs.newDocTitle'); inp.placeholder = t('docs.titlePh'); inp.setAttribute('aria-label', t('docs.titlePh'))
    const row = document.querySelector('#mCard .mRow'); row.style.display = ''
    const yes = $('mYes'); yes.disabled = false; yes.textContent = t('common.create'); yes.style.background = ''; yes.style.color = ''
    const box = document.createElement('div'); box.id = 'mExtra'
    box.appendChild(el('label', null, t('gallery.galLabel')))
    let selT = 0
    const grp = el('div'); grp.id = 'galGrid'; grp.setAttribute('role', 'radiogroup'); grp.setAttribute('aria-label', t('gallery.galLabel'))
    GALLERY.forEach((g, i) => grp.appendChild(galleryCard(g, !i, () => { selT = i; grp.querySelectorAll('.pk').forEach(x => { x.classList.remove('on'); x.setAttribute('aria-pressed', 'false') }); grp.children[i].classList.add('on'); grp.children[i].setAttribute('aria-pressed', 'true') })))
    if (!uploadTitle) box.appendChild(grp); else box.lastChild.remove()
    $('mCard').insertBefore(box, row)
    const done = v => { ov.style.display = 'none'; modalInert(false); box.remove(); askRes = null; prev?.focus?.(); res(v) }
    askRes = () => done(null)
    $('mNo').onclick = () => done(null)
    yes.onclick = () => { done({ title: inp.value, tpl: selT }) }
    inp.onkeydown = e => { if (e.key === 'Enter') yes.onclick() }
    setTimeout(() => { if (ov.style.display !== 'none') { inp.focus(); inp.select() } }, 30)
  })
}
function askNewTpl(uploadName, creating) { // one dialog: name + folder radio (like askNewDoc, not 3 cascades)
  return new Promise(res => {
    if (askRes) askRes(null)
    const prev = document.activeElement
    const ov = $('modal'); ov.style.display = 'flex'; modalInert(true)
    $('mHead').textContent = creating ? t('files.newFileHead') : uploadName ? t('files.upload') : t('templates.newTitle')
    const inp = $('mInp'); inp.style.display = ''; inp.value = uploadName || ''; inp.placeholder = t('templates.namePh'); inp.setAttribute('aria-label', t('templates.nameAria'))
    const row = document.querySelector('#mCard .mRow'); row.style.display = ''
    const yes = $('mYes'); yes.disabled = false; yes.textContent = t('common.create'); yes.style.background = ''; yes.style.color = ''
    const box = document.createElement('div'); box.id = 'mExtra'
    $('mCard').insertBefore(box, row)
    const done = v => { ov.style.display = 'none'; modalInert(false); box.remove(); askRes = null; prev?.focus?.(); res(v) }
    askRes = () => done(null)
    $('mNo').onclick = () => done(null)
    yes.onclick = () => { done({ name: inp.value, folder: '' }) }
    inp.onkeydown = e => { if (e.key === 'Enter') yes.onclick() }
    setTimeout(() => inp.focus(), 30)
  })
}
$('new').onclick = async () => {
  const k = await askPick(t('docs.newPick'), [[t('docs.pickDoc'), t('docs.pickDocSub')], [t('docs.pickUp'), t('docs.pickUpSub')]])
  if (k === 1) { $('docPick').click(); return }
  if (k !== 0) return
  const r = await askNewDoc()
  if (!r) return
  const b = $('new'); b.disabled = true
  try { openDoc((await api('POST', '/api/docs/create', { title: (r.title || '').trim() || t('projects.new'), content: galleryContent(r.tpl), folder: '' })).id) }
  catch (e) { toast(e.message) } finally { b.disabled = false }
}
let upBusy = false // double-click: no second doc
$('upDoc').onclick = () => $('docPick').click()
async function importUpload(f) {
  if (!f || upBusy) return
  if (!/\.(zip|typ|bib|csv|tsv|json|yaml|yml|toml|xml|txt|csl)$/i.test(f.name)) { toast(t('files.nameBad')); return }
  if (f.size > (/\.zip$/i.test(f.name) ? 10 * 1024 * 1024 : 200 * 1024)) { toast(t('docs.maxKb')); return }
  upBusy = true
  try {
    if (/\.zip$/i.test(f.name)) {
      const r = await askNewDoc(f.name.replace(/\.zip$/i, ''))
      if (!r) return
      const body = new FormData(); body.append('f', f); body.append('title', r.title.trim() || t('projects.new')); body.append('folder', '')
      const response = await fetch('/api/docs/import-zip', { method: 'POST', body })
      if (!response.ok) throw new Error(expMsg(await response.text()))
      await openDoc((await response.json()).id); sidebar(); return
    }
    const txt = await f.text(), isTyp = /\.typ$/i.test(f.name), doc = docId, epoch = openN
    const targets = []
    if (isTyp) targets.push(['doc', t('docs.pickDoc'), t('docs.pickDocSub')])
    targets.push(['resource', t('files.uploadResource'), t('files.uploadResourceD')])
    if (docId && docRole !== 'reviewer' && !openedTrashed) targets.push(['file', t('files.uploadLocal'), t('files.uploadLocalD')])
    const i = await askPick(t('files.uploadTarget'), targets.map(x => [x[1], x[2]]))
    if (i == null || !targets[i]) return
    const target = targets[i][0]
    if (target === 'file') { if (doc === docId && epoch === openN) await upText(f); return }
    if (target === 'resource') {
      const r = await askNewTpl(f.name)
      if (!r || !r.name.trim()) return
      await loadTpl()
      if (myTpl.some(x => x.name === r.name.trim())) { toast(t('common.nameExists')); return }
      const result = await api('POST', '/api/templates', { name: r.name.trim(), content: txt, folder: '' })
      await loadTpl(); sidebar(); openTpl(result.name || r.name.trim()); return
    }
    const ttl = f.name.replace(/\.typ$/i, '').slice(0, 100)
    const r = await askNewDoc(ttl)
    if (!r) return
    openDoc((await api('POST', '/api/docs/create', { title: r.title.trim() || ttl, content: txt, folder: '' })).id)
  } catch (e) { toast(e.message) } finally { upBusy = false }
}
$('docPick').onchange = () => { const f = $('docPick').files[0]; $('docPick').value = ''; importUpload(f) }
$('del').onclick = async () => {
  const doc = docId, resource = tplName, epoch = openN
  if (tplName) { // delete open template
    if (!await ask(t('templates.delTplConfirm', { name: tplName }), { noInput: true, ok: t('common.delete'), danger: true })) return
    if (resource !== tplName || epoch !== openN) return
    try { await api('DELETE', '/api/templates/' + encodeURIComponent(resource)) }
    catch (e) { toast(e.message); return }
    if (resource !== tplName || epoch !== openN) { loadTpl(); return }
    tplName = ''; tplDirty = false; clearTimeout(tplT)
    closeView(); $('viewSeg').style.display = '' // segment back: no doc, but view selectable
    await loadTpl(); sidebar()
    return
  }
  if (openedTrashed) {
    if (!await ask(t('docs.delGone'), { noInput: true, ok: t('common.delete'), danger: true })) return
  } else if (!await ask(t('docs.moveTrashQ'), { noInput: true, ok: t('common.ok') })) return
  if (!doc || doc !== docId || epoch !== openN) return
  api('DELETE', `/api/docs/${doc}`).then(() => { if (doc === docId) closeView(); sidebar() }).catch(e => toast(e.message))
}
setInterval(() => {
  if (!docId) return
  loadComments().catch(e => console.warn('comments poll failed', e))
  if ((docProject || docRole !== 'owner') && navigator.onLine !== false) {
    const doc = docId, before = JSON.stringify(window.docTpl)
    loadDocResources(true).then(ok => { if (ok && doc === docId && before !== JSON.stringify(window.docTpl)) queueRender() }).catch(() => {})
  }
}, POLL_MS)
const unsafeState = () => { // edits that may not have reached the server yet
  if (tplDirty || tabDirty) return true
  const s = $('save').textContent || ''
  if (!docId && !tplName) return false
  if (openedTrashed || docRole === 'reviewer') return false
  const dirtyMark = ['…', t('docs.offlineRetry'), t('docs.saveError', { msg: '' })]
  if (!dirtyMark.some(m => m && s.startsWith(m))) return false
  return !(prov && prov.wsconnected && synced && !activeFile && !tplName) // live main.typ: Yjs already carried it
}
addEventListener('beforeunload', e => { if (unsafeState()) { e.preventDefault(); e.returnValue = '' } }) // offline/failed save: browser asks before closing
addEventListener('pagehide', () => { // stash latest edits, 2s save may still be pending
  const live = !!(prov && prov.wsconnected)
  if (!tplDirty && !tabDirty && $('save').textContent.startsWith(t('docs.saved'))) { try { if (docId) localStorage.removeItem('typst-pending-' + docId) } catch (e) {} return }
  try { if (docId && ytext && synced && docRole !== 'reviewer' && !live) { const c = ytext.toString(); if (c) lsSet('typst-pending-' + docId, JSON.stringify({ t: Date.now(), c })) } } catch (e) {} // offline only: keepalive may fail, openDoc offers restore
  try { // file/template tab with unsaved edits: stash a copy (keepalive below may fail, switchTab offers restore)
    if (docId && activeFile && tabDirty && typeof fileStashKey === 'function') lsSet(fileStashKey(docId, activeFile), JSON.stringify({ t: Date.now(), c: getT() }))
  } catch (e) {}
  const head = { 'Content-Type': 'application/json' }
  if (tplName && tplDirty) {
    lsSet(resourceStashKey(tplName), JSON.stringify({ t: Date.now(), c: getT() }))
    fetch('/api/templates', { method: 'POST', headers: head,
      body: JSON.stringify({ name: tplName, content: getT(), ...(tplVer ? { version: tplVer } : {}) }), keepalive: true })
  } else if (docId && activeFile && tabDirty && tabCanEdit(activeFile)) {
    const rq = tabReq(activeFile, getT())
    fetch(rq.url, { method: 'POST', headers: head, body: JSON.stringify(rq.body), keepalive: true })
  }
  else if (docId && ytext && synced && docRole !== 'reviewer' && live)
    fetch(`/api/docs/${docId}/save`, { method: 'POST', headers: head,
      body: JSON.stringify({ content: ytext.toString(), force: live }), keepalive: true }) // live only: offline text lives in Yjs + stash, REST would fork it (double on reconnect)
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
  await loadTpl(); const joined = await checkJoin()
  if (!docId && !tplName && !hadJoin && !joined) {
    const pick = (lastOwn.find(x => x.title === 'Tutorial') || lastOwn[0] || lastShared[0])
    if (pick) openDoc(pick.id)
  }
}).catch(e => console.warn('session restore failed', e))
try { (window.requestIdleCallback || (fn => setTimeout(fn, 1500)))(() => ensureTypst().catch(() => {})) } catch (e) {} // warm compiler when idle: UI paints first
window.__booted = true // module alive: login guard in classic script stands down
document.getElementById('booterr')?.remove() // module running: remove boot error box
