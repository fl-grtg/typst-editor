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
    loadTpl(); const joined = await checkJoin()
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
  if (tplName) { // template: save new + delete old (else upsert overwrites)
    const nv = await ask(t('templates.renameTpl'), { value: tplName })
    if (nv === null || !nv.trim() || nv.trim() === tplName) return
    await loadTpl() // fresh: else guard misses foreign names
    if (myTpl.some(x => x.name === nv.trim())) { toast(t('common.nameExists')); return }
    try {
      const old = myTpl.find(x => x.name === tplName)
      const r = await api('POST', '/api/templates', { name: nv.trim(), content: getT(), folder: old && old.folder ? old.folder : '' })
      await api('DELETE', '/api/templates/' + encodeURIComponent(tplName))
      tplName = r.name; $('title').textContent = r.name
      await loadTpl(); renderTpl(); sidebar()
    } catch (e) { toast(e.message) }
    return
  }
  if (!docId || docRole !== 'owner') return
  const nt = await ask(t('docs.renameDoc'), { value: $('title').textContent })
  if (nt === null || !nt.trim()) return
  api('POST', `/api/docs/${docId}/rename`, { title: nt.trim() })
    .then(() => { $('title').textContent = nt.trim(); sidebar() })
    .catch(e => toast(e.message))
}
function askNewDoc() { // one dialog: title + folder radio + template radio (not 3 cascades)
  return new Promise(res => {
    if (askRes) askRes(null)
    const prev = document.activeElement
    const ov = $('modal'); ov.style.display = 'flex'; modalInert(true)
    $('mHead').textContent = t('docs.newDocTitle')
    const inp = $('mInp'); inp.style.display = ''; inp.value = t('docs.newDocTitle'); inp.placeholder = t('docs.titlePh'); inp.setAttribute('aria-label', t('docs.titlePh'))
    const row = document.querySelector('#mCard .mRow'); row.style.display = ''
    const yes = $('mYes'); yes.textContent = t('common.create'); yes.style.background = ''; yes.style.color = ''
    const box = document.createElement('div'); box.id = 'mExtra'
    const fl = el('label', null, t('docs.folderLabel'))
    let selF = ''
    const fgrp = el('div'); fgrp.setAttribute('role', 'radiogroup'); fgrp.setAttribute('aria-label', t('docs.folderLabel'))
    const nn = document.createElement('input'); nn.type = 'text'; nn.placeholder = t('docs.newFolderName'); nn.setAttribute('aria-label', t('docs.newFolderName')); nn.maxLength = 40; nn.style.display = 'none'
    const addF = (v, lab) => { const b = el('button', 'pk' + (v === selF ? ' on' : ''), lab); b.setAttribute('aria-pressed', v === selF); b.onclick = () => { selF = v; fgrp.querySelectorAll('.pk').forEach(x => { x.classList.remove('on'); x.setAttribute('aria-pressed', 'false') }); b.classList.add('on'); b.setAttribute('aria-pressed', 'true'); nn.style.display = v === '__new' ? '' : 'none'; if (v === '__new') nn.focus() }; fgrp.appendChild(b) }
    addF('', t('docs.noFolder'))
    folders.forEach(f => addF(f.folder, f.n === 1 ? t('docs.folderDocsOne', { f: f.folder, n: f.n }) : t('docs.folderDocsMany', { f: f.folder, n: f.n })))
    addF('__new', t('docs.newFolderOpt'))
    box.append(fl, fgrp, nn, el('label', null, t('docs.tplLabel')))
    let selT = 0
    const grp = el('div'); grp.setAttribute('role', 'radiogroup'); grp.setAttribute('aria-label', t('docs.tplLabel'))
    ;[[t('docs.stBlank'), t('docs.stBlankSub')], [t('docs.stReport'), t('docs.stReportSub')], [t('docs.stSlides'), t('docs.stSlidesSub')]].forEach((st, i) => {
      const b = el('button', 'pk' + (!i ? ' on' : ''), st[0] + ' – ' + st[1]); b.setAttribute('aria-pressed', !i)
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
    $('mHead').textContent = t('templates.newTitle')
    const inp = $('mInp'); inp.style.display = ''; inp.value = ''; inp.placeholder = t('templates.namePh'); inp.setAttribute('aria-label', t('templates.nameAria'))
    const row = document.querySelector('#mCard .mRow'); row.style.display = ''
    const yes = $('mYes'); yes.textContent = t('common.create'); yes.style.background = ''; yes.style.color = ''
    const box = document.createElement('div'); box.id = 'mExtra'
    const fl = el('label', null, t('docs.folderLabel'))
    let selF = ''
    const fgrp = el('div'); fgrp.setAttribute('role', 'radiogroup'); fgrp.setAttribute('aria-label', t('docs.folderLabel'))
    const nn = document.createElement('input'); nn.type = 'text'; nn.placeholder = t('docs.newFolderName'); nn.setAttribute('aria-label', t('docs.newFolderName')); nn.maxLength = 40; nn.style.display = 'none'
    const addF = (v, lab) => { const b = el('button', 'pk' + (v === selF ? ' on' : ''), lab); b.setAttribute('aria-pressed', v === selF); b.onclick = () => { selF = v; fgrp.querySelectorAll('.pk').forEach(x => { x.classList.remove('on'); x.setAttribute('aria-pressed', 'false') }); b.classList.add('on'); b.setAttribute('aria-pressed', 'true'); nn.style.display = v === '__new' ? '' : 'none'; if (v === '__new') nn.focus() }; fgrp.appendChild(b) }
    addF('', t('docs.noFolder'))
    tplFolders.forEach(f => addF(f.folder, f.n === 1 ? t('templates.folderTplOne', { f: f.folder, n: f.n }) : t('templates.folderTplMany', { f: f.folder, n: f.n })))
    addF('__new', t('docs.newFolderOpt'))
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
  const k = await askPick(t('docs.newPick'), [[t('docs.pickDoc'), t('docs.pickDocSub')], [t('docs.pickTpl'), t('docs.pickTplSub')], [t('docs.pickUp'), t('docs.pickUpSub')]])
  if (k === 1) { newTemplate(); return }
  if (k === 2) { $('docPick').click(); return }
  if (k !== 0) return
  const r = await askNewDoc()
  if (!r) return
  const b = $('new'), old = b.textContent; b.disabled = true; b.textContent = t('docs.creating')
  try { openDoc((await api('POST', '/api/docs/create', { title: (r.title || '').trim() || t('docs.newDocTitle'), content: STARTERS[r.tpl] || '', folder: r.folder })).id) }
  catch (e) { toast(e.message) } finally { b.disabled = false; b.textContent = old }
}
let upBusy = false // double-click: no second doc
$('upDoc').onclick = () => $('docPick').click()
$('docPick').onchange = async () => { // .typ as normal doc (not template): title from filename
  const f = $('docPick').files[0]; $('docPick').value = ''
  if (!f || upBusy) return
  if (!/\.typ$/i.test(f.name)) { toast(t('docs.onlyTyp')); return }
  if (f.size > 200 * 1024) { toast(t('docs.maxKb')); return }
  upBusy = true
  try {
    const txt = await f.text()
    if (!txt.trim()) { toast(t('common.emptyFile')); return }
    if (txt.length > 200 * 1024) { toast(t('docs.maxKb')); return }
    const ttl = f.name.replace(/\.typ$/i, '').replace(/\s+/g, ' ').trim().slice(0, 100) || t('docs.newDocTitle')
    openDoc((await api('POST', '/api/docs/create', { title: ttl, content: txt })).id)
  } catch (e) { toast(e.message) } finally { upBusy = false }
}
$('del').onclick = async () => {
  if (tplName) { // delete open template
    if (!await ask(t('templates.delTplConfirm', { name: tplName }), { noInput: true, ok: t('common.delete'), danger: true })) return
    try { await api('DELETE', '/api/templates/' + encodeURIComponent(tplName)) }
    catch (e) { toast(e.message); return }
    tplName = ''
    closeView(); $('viewSeg').style.display = '' // segment back: no doc, but view selectable
    await loadTpl(); sidebar()
    return
  }
  if (openedTrashed) {
    if (!await ask(t('docs.delGone'), { noInput: true, ok: t('common.delete'), danger: true })) return
  } else if (!await ask(t('docs.moveTrashQ'), { noInput: true, ok: t('common.ok') })) return
  api('DELETE', `/api/docs/${docId}`).then(() => { closeView(); sidebar() }).catch(e => toast(e.message))
}
setInterval(() => { if (docId) loadComments().catch(e => console.warn('comments poll failed', e)) }, POLL_MS)
const unsafeState = () => { // edits that may not have reached the server yet
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
  if ($('save').textContent.startsWith(t('docs.saved'))) { try { if (docId) localStorage.removeItem('typst-pending-' + docId) } catch (e) {} return } // saved: no stash (a stale stash would later clobber others' edits)
  try { if (docId && ytext && synced && docRole !== 'reviewer' && !live) { const c = ytext.toString(); if (c) lsSet('typst-pending-' + docId, JSON.stringify({ t: Date.now(), c })) } } catch (e) {} // offline only: keepalive may fail, openDoc offers restore
  const head = { 'Content-Type': 'application/json' }
  if (tplName)
    fetch('/api/templates', { method: 'POST', headers: head,
      body: JSON.stringify({ name: tplName, content: getT() }), keepalive: true })
  else if (docId && activeFile)
    fetch(`/api/docs/${docId}/files/${encodeURIComponent(activeFile)}/text`, { method: 'POST', headers: head,
      body: JSON.stringify({ content: getT() }), keepalive: true })
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
  loadTpl(); const joined = await checkJoin()
  if (!docId && !tplName && !hadJoin && !joined) {
    const pick = (lastOwn.find(x => x.title === 'Tutorial') || lastOwn[0] || lastShared[0])
    if (pick) openDoc(pick.id)
  }
}).catch(e => console.warn('session restore failed', e))
try { (window.requestIdleCallback || (fn => setTimeout(fn, 1500)))(() => ensureTypst().catch(() => {})) } catch (e) {} // warm compiler when idle: UI paints first
window.__booted = true // module alive: login guard in classic script stands down
document.getElementById('booterr')?.remove() // module running: remove boot error box

