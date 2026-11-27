function historyUrl(doc = docId) {
  const project = projects.find(p => p.id === docProject)
  return docProject && project?.role !== 'guest' ? `/api/projects/${docProject}/snapshots` : `/api/docs/${doc}/snapshots`
}
// --- History: save state, view diff, restore ---
$('histBtn').onclick = e => {
  e.stopPropagation()
  if (showPop('histPop')) renderHist()
}
async function renderHist() {
  const doc = docId, epoch = openN, project = docProject
  if (!doc) return
  const canEdit = ['owner', 'editor'].includes(projects.find(p => p.id === project)?.role || docRole)
  const isOwner = projects.find(p => p.id === project)?.role === 'owner'
  const p = $('histPop'); p.replaceChildren(); hideVerCard()
  p.onscroll = hideVerCard
  const top = el('div', 'histTop'), save = el('button', 'save primary', t('history.saveSnap'))
  const doSave = async label => {
    if (doc !== docId || epoch !== openN) return
    save.disabled = true; const old = save.textContent; save.textContent = t('history.saving')
    try { if (!await flushTab() || !await flushTpl()) { save.disabled = false; save.textContent = old; return }; await api('POST', historyUrl(doc), label ? { label } : {}); if (doc === docId && epoch === openN) renderHist() }
    catch (e) { toast(e.message); save.disabled = false; save.textContent = old }
  }
  save.onclick = () => {
    if (doc !== docId || epoch !== openN) return
    if (!historyUrl(doc).includes('/projects/')) { doSave(''); return }
    const existing = p.querySelector('.histSaveRow')
    if (existing) { existing.querySelector('input')?.focus(); return }
    const bar = el('div', 'histSaveRow')
    const inp = el('input'); inp.placeholder = t('history.namePh'); inp.setAttribute('aria-label', t('history.saveSnap')); inp.maxLength = 100
    const go = el('button', 'primary', t('common.save')); go.type = 'button'
    const cx = icoBtn(null, ICO_X); cx.type = 'button'; cx.title = t('common.cancel'); cx.setAttribute('aria-label', t('common.cancel'))
    const submit = () => { const v = inp.value.trim(); bar.remove(); doSave(v) }
    go.onclick = submit
    cx.onclick = () => { bar.remove(); save.focus() }
    inp.onkeydown = e => {
      if (e.key === 'Enter') { e.preventDefault(); submit() }
      else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); bar.remove(); save.focus() }
    }
    bar.append(inp, go, cx)
    top.after(bar)
    setTimeout(() => inp.focus(), 0)
  }
  save.hidden = !canEdit; top.appendChild(save)
  if (historyUrl(doc).includes('/projects/') && isOwner) {
    const set = icoBtn('histSet', ICO_SLIDERS); set.classList.add('btn'); set.title = t('history.settings'); set.setAttribute('aria-label', set.title)
    set.onclick = () => versionSettings(project)
    top.appendChild(set)
  }
  if (canEdit || top.childElementCount > 1) p.appendChild(top)
  let list = [], git = { git: false, remote: false }
  try { const r = await api('GET', historyUrl(doc)); list = r.snapshots; git = { git: !!r.git, remote: !!r.remote } }
  catch (e) { if (doc === docId && epoch === openN) p.appendChild(el('div', 'srow', t('history.loadError', { msg: e.message }))); return }
  if (doc !== docId || epoch !== openN) return
  if (!list.length) { const em = el('div', 'histEmpty'); em.textContent = t('history.autoHint'); p.appendChild(em) }
  let lastDay = ''
  list.forEach(s => {
    const day = dayLabel(s.created_at)
    if (day !== lastDay) { p.appendChild(el('div', 'hDay', day)); lastDay = day }
    const projUrl = historyUrl(doc).includes('/projects/')
    const row = el('div', 'srow')
    const named = !!s.label && s.label !== 'Before restore'
    const tx = el('span', 't'); tx.append(el('span', 'nm' + (named ? '' : ' dim'), versionName(s)))
    row.appendChild(tx)
    row.onmouseenter = () => showVerCard(row, s, git)
    row.onmouseleave = hideVerCard
    const compare = () => projUrl ? openChanges({ url: historyUrl(doc), sid: s.id, list }) : showDiff(s.id, row, doc)
    const gitRun = async (action, done) => {
      try { await api('POST', `${historyUrl(doc)}/${s.id}/${action}`); toast(t(done)); if (doc === docId && epoch === openN) renderHist() }
      catch (e) { toast(e.message) }
    }
    const doRestore0 = async () => {
      if (!await ask(t('history.restoreConfirm'), { noInput: true, ok: t('common.ok') })) return
      if (doc !== docId || epoch !== openN) return
      if (!await flushTab()) return
      const doRestore = async force => {
        if (doc !== docId || epoch !== openN) return
        try { await api('POST', `${historyUrl(doc)}/${s.id}/restore`, { ...(force ? { force: true } : {}) }); if (doc === docId && epoch === openN) { await sidebar(); const p = projects.find(p => p.id === project); const next = p?.documents.find(d => d.id === doc)?.id || p?.documents[0]?.id; if (next) openDoc(next); else closeView() } } // server saves the pre-restore snapshot atomically
        catch (e) {
          if (e.status === 409 && !force) toast(t('history.conflict'), () => doRestore(true), t('history.forceRestore'))
          else toast(t('history.restoreFail', { msg: e.message }), () => doRestore(force), t('common.retry'))
        }
      }
      doRestore()
    }
    const rename = () => {
      hideVerCard()
      const nm = tx.querySelector('.nm')
      if (!nm) return
      const cur = s.label === 'Before restore' ? '' : s.label || ''
      const inp = el('input', 'renameInput')
      inp.value = cur; inp.placeholder = t('history.namePh'); inp.maxLength = 100
      inp.setAttribute('aria-label', t('history.renameSnap'))
      nm.replaceWith(inp)
      let done = false
      const finish = async apply => {
        if (done) return; done = true
        const next = inp.value.trim()
        inp.replaceWith(nm)
        if (!apply || next === cur || doc !== docId || epoch !== openN) return
        try { await api('PATCH', `${historyUrl(doc)}/${s.id}`, { label: next }); if (doc === docId && epoch === openN) renderHist() } catch (err) { toast(err.message) }
      }
      inp.onclick = e => e.stopPropagation()
      inp.onkeydown = e => {
        if (e.key === 'Enter') { e.preventDefault(); finish(true) }
        else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); finish(false) }
      }
      inp.onblur = () => finish(true)
      setTimeout(() => { inp.focus(); inp.select() }, 0)
    }
    const del = async () => {
      if (!await ask(t('history.delSnapConfirm'), { noInput: true, ok: t('common.delete'), danger: true })) return
      if (doc !== docId || epoch !== openN) return
      try { await api('DELETE', `${historyUrl(doc)}/${s.id}`); if (doc === docId && epoch === openN) renderHist() }
      catch (e) { toast(e.message) }
    }
    const canDel = projUrl ? (projects.find(p => p.id === project)?.role === 'owner' || (s.author && s.author === user)) : docRole === 'owner'
    const items = [{ label: t('history.compare'), title: t('history.compareTitle'), run: compare }]
    if (canEdit && projUrl) items.push({ label: t('history.renameSnap'), run: rename })
    if (canEdit) items.push({ label: t('docs.restore'), title: t('history.restoreTitle'), run: doRestore0 })
    if (projUrl && isOwner && git.git && !s.commit_hash) items.push({ label: t('history.commitVer'), run: () => gitRun('commit', 'history.committed') })
    if (projUrl && isOwner && git.remote && s.commit_hash && !s.pushed) items.push({ label: t('history.pushVer'), run: () => gitRun('push', 'history.setPushOk') })
    if (canDel) items.push({ label: t('history.delSnap'), danger: true, run: del })
    const more = icoBtn('histMore', ICO_MORE); more.title = t('shell.menuMore'); more.setAttribute('aria-label', versionName(s) + ': ' + more.title)
    more.setAttribute('aria-haspopup', 'menu'); more.setAttribute('aria-expanded', 'false')
    more.dataset.sideMenu = ''; more.sideMenuItems = () => items
    more.onfocus = () => showVerCard(row, s, git); more.onblur = hideVerCard
    row.appendChild(more)
    p.appendChild(row)
  })
}
const ICO_SLIDERS = svgI('<path d="M2.5 4.5h2M7.5 4.5h6M2.5 11.5h6.5M12 11.5h1.5"/><circle cx="6" cy="4.5" r="1.5"/><circle cx="10.5" cy="11.5" r="1.5"/>')
function versionTime(iso) { return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) }
function versionName(s) { return s.label === 'Before restore' ? t('history.autoRestore') : s.label || versionTime(s.created_at) } // unnamed versions go by their time (the list groups by day)
function versionInfo(s, git) { // [label key, value] rows of the hover card; document versions have no kind, editors or commit
  const rows = [['history.infoName', versionName(s)], ['history.infoWhen', new Date(s.created_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })]]
  if (s.kind) rows.push(['history.infoKind', t(s.kind === 'auto' ? 'history.autoName' : 'history.kindManual')])
  const who = [...new Set((s.editors || '').split(',').filter(Boolean))].join(', ')
  if (s.kind) rows.push(['history.infoEditors', who || t('history.nobody')])
  if (s.commit_hash) rows.push(['history.infoCommit', s.commit_hash.slice(0, 7) + (git.remote ? ' · ' + t(s.pushed ? 'history.pushed' : 'history.notPushed') : '')])
  else if (git.git && s.kind) rows.push(['history.infoCommit', t('history.notCommitted')])
  return rows
}
let verCard = null
function hideVerCard() { verCard?.remove(); verCard = null }
function showVerCard(row, s, git) { // hover card left of the popover, below the row when there is no room
  hideVerCard()
  const c = el('div', 'verCard'); c.setAttribute('role', 'tooltip')
  for (const [k, v] of versionInfo(s, git)) c.append(el('span', 'k', t(k)), el('span', 'v', v))
  document.body.appendChild(c)
  const pop = $('histPop').getBoundingClientRect(), r = row.getBoundingClientRect(), w = c.offsetWidth, h = c.offsetHeight
  let left = pop.left - w - 8, top = r.top
  if (left < 8) { left = Math.min(Math.max(8, r.left), innerWidth - w - 8); top = r.bottom + 6 }
  c.style.left = left + 'px'; c.style.top = Math.max(8, Math.min(top, innerHeight - h - 8)) + 'px'
  verCard = c
}
document.addEventListener('pointerdown', hideVerCard, true)
document.addEventListener('keydown', e => { if (e.key === 'Escape') hideVerCard() }, true)
const ICO_EYE = svgI('<path d="M1.7 8s2.3-4.2 6.3-4.2S14.3 8 14.3 8s-2.3 4.2-6.3 4.2S1.7 8 1.7 8Z"/><circle cx="8" cy="8" r="1.9"/>')
const ICO_EYE_OFF = svgI('<path d="M6.1 4a6.6 6.6 0 0 1 1.9-.2c4 0 6.3 4.2 6.3 4.2a12.6 12.6 0 0 1-2.4 3"/><path d="M4 4.9A12.8 12.8 0 0 0 1.7 8s2.3 4.2 6.3 4.2a7 7 0 0 0 2.1-.3"/><path d="M6.6 6.6a2 2 0 0 0 2.8 2.8"/><path d="M2.2 2.2l11.6 11.6"/>')
const VERSION_GAPS = [0, 5, 30, 60, 360, 1440, 4320, 10080] // minutes offered for the gap between automatic versions
function gapLabel(m) {
  if (!m) return t('history.gapNow')
  if (m % 1440 === 0) return t(m === 1440 ? 'history.gapDay' : 'history.gapDays', { n: m / 1440 })
  if (m % 60 === 0) return t(m === 60 ? 'history.gapHour' : 'history.gapHours', { n: m / 60 })
  return t('history.gapMinutes', { n: m })
}
async function versionSettings(project, draft = null) { // owner: rules for automatic versions and the Git mirror
  let s
  try { s = { ...await api('GET', `/api/projects/${project}/versioning`), ...draft } } catch (e) { toast(e.message); return }
  const body = el('div', 'mBody'), box = el('div'), gitBox = el('div'); box.id = 'mExtra'; body.appendChild(box)
  const cell = (into, key, input) => {
    const c = el('div'), lb = el('label', null, t(key)); lb.htmlFor = input.id = 'vs-' + key.split('.').pop()
    c.append(lb, input); into.appendChild(c); return input
  }
  const field = (into, key, type, value, attrs = {}) => {
    const inp = el('input'); inp.type = type; inp.value = value ?? ''
    for (const [k, v] of Object.entries(attrs)) inp.setAttribute(k, v)
    return cell(into, key, inp)
  }
  const toggle = (into, key, on) => { // same switch as in the settings
    const lb = el('label', 'vsSwitch'), sw = el('input', 'settingSwitch'); sw.type = 'checkbox'; sw.setAttribute('role', 'switch'); sw.checked = !!on
    lb.append(el('span', null, t(key)), sw); into.appendChild(lb); return sw
  }
  const grid = into => { const g = el('div', 'vsRow'); into.appendChild(g); return g }
  const secret = (into, key, value, saved) => { // the saved token never comes back: the placeholder says so, typing replaces it, X removes it
    const c = el('div'), lb = el('label', null, t(key)), wrap = el('div', 'vsSecret'), inp = el('input'), tools = el('span', 'vsTools')
    inp.type = 'password'; inp.value = value; inp.autocomplete = 'off'; inp.maxLength = 500; lb.htmlFor = inp.id = 'vs-' + key.split('.').pop()
    const eye = icoBtn('vsEye', ICO_EYE), clear = icoBtn('vsClear', ICO_X); eye.type = clear.type = 'button'
    clear.title = t('history.tokenClear'); clear.setAttribute('aria-label', clear.title)
    const show = on => { inp.type = on ? 'text' : 'password'; eye.innerHTML = on ? ICO_EYE_OFF : ICO_EYE; eye.title = t(on ? 'history.tokenHide' : 'history.tokenShow'); eye.setAttribute('aria-label', eye.title); eye.setAttribute('aria-pressed', String(on)) }
    const paint = () => { eye.hidden = !inp.value; clear.hidden = !inp.value && !saved; inp.placeholder = saved ? t('history.setTokenKept') : '' }
    eye.onclick = () => { show(inp.type === 'password'); inp.focus() }
    clear.onclick = () => { inp.forget = saved || inp.forget; saved = false; inp.value = ''; show(false); paint(); inp.focus() }
    inp.oninput = paint
    show(false); paint()
    tools.append(eye, clear); wrap.append(inp, tools); c.append(lb, wrap); into.appendChild(c); return inp
  }
  box.appendChild(el('div', 'mLabel', t('history.setAuto')))
  const auto = toggle(box, 'history.setAutoOn', s.auto)
  const autoRow = grid(box)
  const gap = el('select')
  for (const m of [...new Set([...VERSION_GAPS, s.auto_minutes])].sort((a, b) => a - b)) { const o = el('option', null, gapLabel(m)); o.value = String(m); gap.appendChild(o) }
  gap.value = String(s.auto_minutes)
  cell(autoRow, 'history.setMinutes', gap)
  const keep = field(autoRow, 'history.setKeep', 'number', s.auto_keep, { min: 1, max: 200, step: 1 })
  auto.onchange = () => { gap.disabled = keep.disabled = !auto.checked; autoRow.classList.toggle('off', !auto.checked) }
  auto.onchange()
  box.appendChild(el('hr', 'vsSep'))
  box.appendChild(el('div', 'mLabel', t('settings.gitGroup')))
  const git = toggle(box, 'history.setGit', s.git); git.disabled = !s.git_available && !s.git
  if (!s.git_available) git.parentNode.title = t('history.setNoGit')
  box.appendChild(gitBox)
  const remotePh = 'https://github.com/user/repo.git'
  const gitRow = grid(gitBox); gitRow.classList.add('vsWide')
  const remote = field(gitRow, 'history.setRemote', 'url', s.remote, { placeholder: remotePh, maxlength: 300 })
  const branch = field(gitRow, 'history.setBranch', 'text', s.branch || 'main', { maxlength: 100 })
  const token = secret(gitBox, 'history.setToken', draft?.token || '', s.has_token && draft?.token !== '')
  const push = toggle(gitBox, 'history.setPush', s.push)
  if (s.push_status) gitBox.appendChild(el('p', 'sub', t('history.setPushFail', { msg: s.push_status })))
  else if (s.pushed_at) gitBox.appendChild(el('p', 'sub', t('history.setPushed', { when: new Date(s.pushed_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) })))
  git.onchange = () => { gitBox.classList.toggle('off', !git.checked); gitBox.querySelectorAll('input, button').forEach(x => { x.disabled = !git.checked }) }
  git.onchange()
  if (!await ask(t('history.settings'), { noInput: true, body, ok: t('common.save') })) return
  const next = { auto: auto.checked, auto_minutes: +gap.value, auto_keep: Math.min(200, Math.max(1, Math.round(+keep.value) || s.auto_keep)), git: git.checked, remote: remote.value.trim(), branch: branch.value.trim() || 'main', push: push.checked }
  if (token.value.trim()) next.token = token.value.trim()
  else if (token.forget) next.token = ''
  try { await api('PUT', `/api/projects/${project}/versioning`, next) }
  catch (e) { toast(e.message); versionSettings(project, next); return } // reopen with what was typed
  if ($('histPop').style.display !== 'none') renderHist() // a lower cap prunes at once
  toast(t('history.setSaved'))
}
function dayLabel(iso) {
  const d = new Date(iso), now = new Date(), start = x => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime()
  const diff = Math.round((start(now) - start(d)) / 864e5)
  return diff <= 0 ? t('common.today') : diff === 1 ? t('common.yesterday') : d.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: d.getFullYear() === now.getFullYear() ? undefined : 'numeric' })
}
function lineDiff(a, b) { // LCS on lines (caps see above), output max DIFF_OUT lines
  const A = a.split('\n').slice(0, DIFF_MAX), B = b.split('\n').slice(0, DIFF_MAX)
  const cut = A.length === DIFF_MAX || B.length === DIFF_MAX
  const n = A.length, m = B.length
  const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
  const out = []
  let i = 0, j = 0
  while (i < n && j < m) {
    if (A[i] === B[j]) { i++; j++ }
    else if (dp[i + 1][j] >= dp[i][j + 1]) out.push(['a', A[i++]])
    else out.push(['b', B[j++]])
  }
  while (i < n) out.push(['a', A[i++]])
  while (j < m) out.push(['b', B[j++]])
  if (cut || out.length > DIFF_OUT) out.push([' ', t('history.truncated')])
  return out.slice(0, DIFF_OUT + 1)
}
async function showDiff(sid, row, doc = docId) {
  const epoch = openN
  if (!row.isConnected || doc !== docId) return
  const open = row.nextSibling && row.nextSibling.classList && row.nextSibling.classList.contains('diff')
  row.parentNode.querySelectorAll('pre.diff').forEach(x => x.remove())
  if (open) return // was open: just collapse
  if (!await flushTab() || !await flushTpl()) return
  let s
  try { s = await api('GET', `${historyUrl(doc)}/${sid}`) } catch (e) { toast(e.message); return }
  if (doc !== docId || epoch !== openN || !row.isConnected) return
  const pre = el('pre', 'diff')
  const changes = s.changes || [{ name: '', before: s.content, after: activeFile ? shadow : getT() }]
  if (!changes.length) pre.appendChild(el('span', null, t('history.identical')))
  for (const change of changes) {
    if (change.name) pre.appendChild(el('span', null, (change.status === 'added' ? '+ ' : change.status === 'deleted' ? '− ' : '') + change.name + '\n'))
    const lines = lineDiff(change.before, change.after)
    if (!lines.length) pre.appendChild(el('span', null, t('history.identical') + '\n'))
    lines.forEach(([k, ln]) => pre.appendChild(el('span', k, (k === 'a' ? '− ' : k === 'b' ? '+ ' : '') + ln.slice(0, 200) + '\n')))
  }
  row.after(pre)
}
