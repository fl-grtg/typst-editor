// --- Change screen: whole-project line diff (green +, red −) in a blurred overlay ---
const CHG_CONTEXT = 3, CHG_CELLS = 4e6, CHG_LINES = 3000

function lineOps(a, b) { // [{k:' '|'a'|'b', s}] : ' ' equal, 'a' removed, 'b' added
  const A = a === '' ? [] : a.split('\n'), B = b === '' ? [] : b.split('\n')
  let lo = 0
  while (lo < A.length && lo < B.length && A[lo] === B[lo]) lo++
  let ea = A.length, eb = B.length
  while (ea > lo && eb > lo && A[ea - 1] === B[eb - 1]) { ea--; eb-- }
  const head = A.slice(0, lo).map(s => ({ k: ' ', s })), tail = A.slice(ea).map(s => ({ k: ' ', s }))
  const MA = A.slice(lo, ea), MB = B.slice(lo, eb), n = MA.length, m = MB.length
  const mid = []
  if (!n || !m || n * m > CHG_CELLS) { // one side empty, or too big for the table: plain replace
    MA.forEach(s => mid.push({ k: 'a', s })); MB.forEach(s => mid.push({ k: 'b', s }))
  } else {
    const dp = Array.from({ length: n + 1 }, () => new Int32Array(m + 1))
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
      dp[i][j] = MA[i] === MB[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    let i = 0, j = 0
    while (i < n && j < m) {
      if (MA[i] === MB[j]) { mid.push({ k: ' ', s: MA[i] }); i++; j++ }
      else if (dp[i + 1][j] >= dp[i][j + 1]) mid.push({ k: 'a', s: MA[i++] })
      else mid.push({ k: 'b', s: MB[j++] })
    }
    while (i < n) mid.push({ k: 'a', s: MA[i++] })
    while (j < m) mid.push({ k: 'b', s: MB[j++] })
  }
  return head.concat(mid, tail)
}
function opStats(ops) { return { add: ops.filter(o => o.k === 'b').length, del: ops.filter(o => o.k === 'a').length } }
function foldOps(ops, ctx = CHG_CONTEXT) { // collapse long unchanged runs: {k:'…', n} marks skipped lines
  const keep = new Array(ops.length).fill(false)
  ops.forEach((o, i) => { if (o.k !== ' ') for (let d = -ctx; d <= ctx; d++) if (ops[i + d]) keep[i + d] = true })
  const out = []
  for (let i = 0; i < ops.length; i++) {
    if (keep[i]) { out.push(ops[i]); continue }
    let j = i
    while (j < ops.length && !keep[j]) j++
    out.push({ k: '…', n: j - i }); i = j - 1
  }
  return out
}

// url: ".../snapshots" ; sid: checkpoint shown as "before" ; against: 'current' or another checkpoint id
async function openChanges({ url, sid, against = 'current', list = [], title = '' }) {
  if (!await flushTab() || !await flushTpl()) return
  const prev = document.activeElement
  const ov = el('div', 'chgOverlay'), card = el('div', 'chgCard')
  ov.setAttribute('role', 'dialog'); ov.setAttribute('aria-modal', 'true'); ov.setAttribute('aria-label', t('changes.title'))
  const close = () => { document.removeEventListener('keydown', onKey, true); ov.remove(); prev?.focus?.() }
  const onKey = e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close() } }
  document.addEventListener('keydown', onKey, true)
  ov.onmousedown = e => { if (e.target === ov) close() }
  const head = el('div', 'chgHead'), ttl = el('b', null, title || t('changes.title')), sum = el('span', 'chgSum')
  const sel = el('select', 'chgAgainst'); sel.setAttribute('aria-label', t('changes.against'))
  const opt = (v, txt) => { const o = el('option', null, txt); o.value = v; sel.appendChild(o) }
  opt('current', t('changes.current'))
  list.filter(s => s.id !== sid).forEach(s => opt(s.id, (s.label || ago(s.created_at)) + (s.label ? ' · ' + ago(s.created_at) : '')))
  sel.value = against
  const x = icoBtn(null, ICO_X); x.title = t('common.close'); x.setAttribute('aria-label', t('common.close')); x.onclick = close
  head.append(ttl, sum, el('span', 'chgSp'), el('span', 'chgVs', t('changes.vs')), sel, x)
  const body = el('div', 'chgBody'), files = el('div', 'chgFiles'), view = el('div', 'chgView')
  body.append(files, view); card.append(head, body); ov.appendChild(card); document.body.appendChild(ov)
  const load = async () => {
    files.replaceChildren(); view.replaceChildren(el('div', 'chgEmpty', '…'))
    let s
    try { s = await api('GET', `${url}/${sid}` + (sel.value === 'current' ? '' : `?against=${encodeURIComponent(sel.value)}`)) }
    catch (e) { view.replaceChildren(el('div', 'chgEmpty', e.message)); return }
    if (!ov.isConnected) return
    const changes = (s.changes || [{ name: '', status: 'modified', before: s.content, after: getT() }]).map(c => ({ ...c, ops: lineOps(c.before, c.after) }))
    const total = changes.reduce((a, c) => { const st = opStats(c.ops); return { add: a.add + st.add, del: a.del + st.del } }, { add: 0, del: 0 })
    sum.replaceChildren(el('span', null, t('changes.files', { n: changes.length })), el('span', 'plus', ' +' + total.add), el('span', 'minus', ' −' + total.del))
    if (!changes.length) { view.replaceChildren(el('div', 'chgEmpty', t('history.identical'))); return }
    const show = c => {
      files.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.name === c.name))
      const box = el('div', 'chgCode')
      const ops = c.ops.length > CHG_LINES ? c.ops.slice(0, CHG_LINES) : c.ops
      let a = 0, b = 0
      foldOps(ops).forEach(o => {
        if (o.k === '…') { box.appendChild(el('div', 'chgFold', t('changes.unchanged', { n: o.n }))); a += o.n; b += o.n; return }
        if (o.k !== 'b') a++
        if (o.k !== 'a') b++
        const row = el('div', 'chgLine ' + (o.k === 'a' ? 'del' : o.k === 'b' ? 'add' : 'ctx'))
        row.append(el('span', 'no', o.k === 'b' ? '' : String(a)), el('span', 'no', o.k === 'a' ? '' : String(b)),
          el('span', 'sg', o.k === 'a' ? '−' : o.k === 'b' ? '+' : ''), el('span', 'tx', o.s))
        box.appendChild(row)
      })
      if (c.ops.length > CHG_LINES) box.appendChild(el('div', 'chgFold', t('history.truncated')))
      view.replaceChildren(box)
    }
    changes.forEach(c => {
      const st = opStats(c.ops), bt = el('button', null)
      bt.dataset.name = c.name
      bt.append(el('i', 'st ' + c.status, c.status === 'added' ? '+' : c.status === 'deleted' ? '−' : '~'), el('span', 'nm', c.name ? c.name.replace(/ \[d_[^\]]*\]/, '') : t('changes.thisDoc')),
        el('span', 'cnt', ''), )
      bt.lastChild.append(el('span', 'plus', '+' + st.add), document.createTextNode(' '), el('span', 'minus', '−' + st.del))
      bt.title = c.name.replace(/ \[d_[^\]]*\]/, '')
      bt.onclick = () => show(c)
      files.appendChild(bt)
    })
    show(changes[0])
  }
  sel.onchange = load
  load()
  x.focus()
}
