// --- History: save state, view diff, restore ---
$('histBtn').onclick = e => {
  e.stopPropagation()
  if (showPop('histPop')) renderHist()
}
async function renderHist() {
  const p = $('histPop'); p.replaceChildren()
  const save = el('button', 'save primary', '+ Save snapshot')
  save.onclick = async () => { save.disabled = true; const old = save.textContent; save.textContent = 'Saving...'; try { await api('POST', `/api/docs/${docId}/snapshots`, {}); renderHist() } catch (e) { toast(e.message); save.disabled = false; save.textContent = old } }
  p.appendChild(save)
  let list = []
  try { list = (await api('GET', `/api/docs/${docId}/snapshots`)).snapshots }
  catch (e) { p.appendChild(el('div', 'srow', 'Error: ' + e.message)); return }
  if (!list.length) { const em = el('div', 'histEmpty'); em.textContent = 'Snapshots appear automatically when you save.'; p.appendChild(em) }
  list.forEach(s => {
    const row = el('div', 'srow')
    const kib = Math.round(s.size / 1024)
    row.appendChild(el('span', 't', ago(s.created_at) + (s.label ? ' · ' + s.label : '') + ' · ' + kib + ' KB'))
    const df = el('button', null, 'Compare'); df.title = 'Show changes vs current'; df.setAttribute('aria-label', df.title)
    df.onclick = () => showDiff(s.id, row)
    const rs = el('button', null, 'Restore'); rs.title = 'Restore this snapshot'; rs.setAttribute('aria-label', rs.title)
    rs.onclick = async () => {
      if (!await ask('Restore this snapshot?', { noInput: true, ok: 'OK' })) return
      const doRestore = async force => {
        try { await api('POST', `/api/docs/${docId}/snapshots`, { label: 'before restore' }).catch(() => {}) // auto snapshot: never restore without way back
          await api('POST', `/api/docs/${docId}/snapshots/${s.id}/restore`, { ...(force ? { force: true } : {}) }); openDoc(docId) } // reload: editor/Yjs follow, no old autosave
        catch (e) {
          if (e.status === 409 && !force) toast('Document changed meanwhile – your text is kept', () => doRestore(true), 'Force restore')
          else toast('Restore failed: ' + e.message, () => doRestore(force), 'Retry')
        }
      }
      doRestore()
    }
    const xx = icoBtn(null, ICO_X); xx.title = 'Delete snapshot'; xx.setAttribute('aria-label', xx.title)
    xx.onclick = async () => {
      if (!await ask('Delete this snapshot?', { noInput: true, ok: 'Delete', danger: true })) return
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
  if (cut || out.length > DIFF_OUT) out.push([' ', '… (truncated)'])
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
  if (!d.length) pre.appendChild(el('span', null, 'Identical to current'))
  d.forEach(([k, ln]) => pre.appendChild(el('span', k, (k === 'a' ? '− ' : k === 'b' ? '+ ' : '') + ln.slice(0, 200) + '\n')))
  row.after(pre)
}
