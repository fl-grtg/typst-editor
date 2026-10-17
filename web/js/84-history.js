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
  const p = $('histPop'); p.replaceChildren()
  const save = el('button', 'save primary', t('history.saveSnap'))
  save.onclick = async () => { if (doc !== docId || epoch !== openN) return; save.disabled = true; const old = save.textContent; save.textContent = t('history.saving'); try { if (!await flushTab() || !await flushTpl()) { save.disabled = false; return }; await api('POST', historyUrl(doc), {}); if (doc === docId && epoch === openN) renderHist() } catch (e) { toast(e.message); save.disabled = false; save.textContent = old } }
  save.hidden = !canEdit; p.appendChild(save)
  let list = []
  try { list = (await api('GET', historyUrl(doc))).snapshots }
  catch (e) { if (doc === docId && epoch === openN) p.appendChild(el('div', 'srow', t('history.loadError', { msg: e.message }))); return }
  if (doc !== docId || epoch !== openN) return
  if (!list.length) { const em = el('div', 'histEmpty'); em.textContent = t('history.autoHint'); p.appendChild(em) }
  list.forEach(s => {
    const row = el('div', 'srow')
    const kib = Math.round(s.size / 1024)
    row.appendChild(el('span', 't', ago(s.created_at) + (s.label ? ' · ' + s.label : '') + t('history.sizeKb', { kb: kib })))
    const df = el('button', null, t('history.compare')); df.title = t('history.compareTitle'); df.setAttribute('aria-label', df.title)
    df.onclick = () => showDiff(s.id, row, doc)
    const rs = el('button', null, t('docs.restore')); rs.title = t('history.restoreTitle'); rs.setAttribute('aria-label', rs.title)
    rs.hidden = !canEdit
    rs.onclick = async () => {
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
    const xx = icoBtn(null, ICO_X); xx.title = t('history.delSnap'); xx.setAttribute('aria-label', xx.title); xx.hidden = docRole !== 'owner'
    xx.onclick = async e => {
      e.stopPropagation()
      if (!await ask(t('history.delSnapConfirm'), { noInput: true, ok: t('common.delete'), danger: true })) return
      if (doc !== docId || epoch !== openN) return
      try { await api('DELETE', `${historyUrl(doc)}/${s.id}`); if (doc === docId && epoch === openN) renderHist() }
      catch (e) { toast(e.message) }
    }
    row.append(df, rs, xx); p.appendChild(row)
  })
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
