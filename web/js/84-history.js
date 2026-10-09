// --- History: save state, view diff, restore ---
$('histBtn').onclick = e => {
  e.stopPropagation()
  if (showPop('histPop')) renderHist()
}
async function renderHist() {
  const p = $('histPop'); p.replaceChildren()
  const save = el('button', 'save primary', t('history.saveSnap'))
  save.onclick = async () => { save.disabled = true; const old = save.textContent; save.textContent = t('history.saving'); try { await api('POST', `/api/docs/${docId}/snapshots`, {}); renderHist() } catch (e) { toast(e.message); save.disabled = false; save.textContent = old } }
  p.appendChild(save)
  let list = []
  try { list = (await api('GET', `/api/docs/${docId}/snapshots`)).snapshots }
  catch (e) { p.appendChild(el('div', 'srow', t('history.loadError', { msg: e.message }))); return }
  if (!list.length) { const em = el('div', 'histEmpty'); em.textContent = t('history.autoHint'); p.appendChild(em) }
  list.forEach(s => {
    const row = el('div', 'srow')
    const kib = Math.round(s.size / 1024)
    row.appendChild(el('span', 't', ago(s.created_at) + (s.label ? ' · ' + s.label : '') + t('history.sizeKb', { kb: kib })))
    const df = el('button', null, t('history.compare')); df.title = t('history.compareTitle'); df.setAttribute('aria-label', df.title)
    df.onclick = () => showDiff(s.id, row)
    const rs = el('button', null, t('docs.restore')); rs.title = t('history.restoreTitle'); rs.setAttribute('aria-label', rs.title)
    rs.onclick = async () => {
      if (!await ask(t('history.restoreConfirm'), { noInput: true, ok: t('common.ok') })) return
      const doRestore = async force => {
        try { await api('POST', `/api/docs/${docId}/snapshots`, { label: t('history.beforeRestore') }).catch(() => {}) // auto snapshot: never restore without way back
          await api('POST', `/api/docs/${docId}/snapshots/${s.id}/restore`, { ...(force ? { force: true } : {}) }); openDoc(docId) } // reload: editor/Yjs follow, no old autosave
        catch (e) {
          if (e.status === 409 && !force) toast(t('history.conflict'), () => doRestore(true), t('history.forceRestore'))
          else toast(t('history.restoreFail', { msg: e.message }), () => doRestore(force), t('common.retry'))
        }
      }
      doRestore()
    }
    const xx = icoBtn(null, ICO_X); xx.title = t('history.delSnap'); xx.setAttribute('aria-label', xx.title)
    xx.onclick = async () => {
      if (!await ask(t('history.delSnapConfirm'), { noInput: true, ok: t('common.delete'), danger: true })) return
      try { await api('DELETE', `/api/docs/${docId}/snapshots/${s.id}`); renderHist() }
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
async function showDiff(sid, row) {
  const open = row.nextSibling && row.nextSibling.classList && row.nextSibling.classList.contains('diff')
  row.parentNode.querySelectorAll('pre.diff').forEach(x => x.remove())
  if (open) return // was open: just collapse
  let s
  try { s = await api('GET', `/api/docs/${docId}/snapshots/${sid}`) } catch (e) { toast(e.message); return }
  const d = lineDiff(s.content, getT()) // file tab: diff against file content, not main shadow
  const pre = el('pre', 'diff')
  if (!d.length) pre.appendChild(el('span', null, t('history.identical')))
  d.forEach(([k, ln]) => pre.appendChild(el('span', k, (k === 'a' ? '− ' : k === 'b' ? '+ ' : '') + ln.slice(0, 200) + '\n')))
  row.after(pre)
}
