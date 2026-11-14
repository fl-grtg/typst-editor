// --- Change screen: GitHub-style unified diff of the whole project in a blurred overlay ---
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
function foldOps(ops, ctx = CHG_CONTEXT) { // collapse long unchanged runs: {k:'…', n, hidden:[ops]} (clickable in the screen)
  const keep = new Array(ops.length).fill(false)
  ops.forEach((o, i) => { if (o.k !== ' ') for (let d = -ctx; d <= ctx; d++) if (ops[i + d]) keep[i + d] = true })
  const out = []
  for (let i = 0; i < ops.length; i++) {
    if (keep[i]) { out.push(ops[i]); continue }
    let j = i
    while (j < ops.length && !keep[j]) j++
    out.push({ k: '…', n: j - i, hidden: ops.slice(i, j) }); i = j - 1
  }
  return out
}
// inside a replaced line: the changed middle part (common start and end stay plain), like GitHub's word highlight
function markInline(ops) {
  for (let i = 0; i < ops.length; i++) {
    if (ops[i].k !== 'a') continue
    let j = i
    while (j < ops.length && ops[j].k === 'a') j++
    let e = j
    while (e < ops.length && ops[e].k === 'b') e++
    const dels = j - i, adds = e - j
    for (let q = 0; q < Math.min(dels, adds); q++) {
      const x = ops[i + q], y = ops[j + q]
      let p = 0
      while (p < x.s.length && p < y.s.length && x.s[p] === y.s[p]) p++
      let s = 0
      while (s < x.s.length - p && s < y.s.length - p && x.s[x.s.length - 1 - s] === y.s[y.s.length - 1 - s]) s++
      if (p + s >= 0.3 * Math.max(x.s.length, y.s.length) && (x.s.length - s > p || y.s.length - s > p)) {
        x.hl = [p, x.s.length - s]; y.hl = [p, y.s.length - s]
      }
    }
    i = e - 1
  }
  return ops
}
function chgSizeText(n) { return n < 1024 ? t('changes.bytes', { n }) : t('history.sizeKb', { kb: Math.round(n / 1024) }).replace(/^ · /, '') }
function flyToFile(view, box) { // quick eased swoosh instead of an instant jump
  const top = box.getBoundingClientRect().top - view.getBoundingClientRect().top + view.scrollTop - 2
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) { view.scrollTop = top; return }
  const from = view.scrollTop, dist = top - from, t0 = performance.now(), dur = 260
  cancelAnimationFrame(view._fly) // a second click restarts the swoosh instead of fighting it
  const step = now => {
    const p = Math.min(1, (now - t0) / dur), e = 1 - (1 - p) ** 3
    view.scrollTop = from + dist * e
    if (p < 1) view._fly = requestAnimationFrame(step)
  }
  view._fly = requestAnimationFrame(step)
  box.classList.remove('arrive'); void box.offsetWidth; box.classList.add('arrive')
}

// url: ".../snapshots" ; sid: the checkpoint the diff starts from (compared with the current project)
async function openChanges({ url, sid, list = [], onClose = null }) {
  if (!await flushTab() || !await flushTpl()) return
  const prev = document.activeElement
  const ov = el('div', 'chgOverlay'), card = el('div', 'chgCard')
  ov.setAttribute('role', 'dialog'); ov.setAttribute('aria-modal', 'true'); ov.setAttribute('aria-label', t('changes.title'))
  const close = () => { document.removeEventListener('keydown', onKey, true); ov.remove(); prev?.focus?.(); if (onClose) onClose() }
  const onKey = e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close() } }
  document.addEventListener('keydown', onKey, true)
  ov.onmousedown = e => { if (e.target === ov) close() }
  let watch = null
  try { watch = await api('GET', url.replace(/\/snapshots$/, '/watch')) } catch (e) { /* no baseline: only checkpoints */ }
  const head = el('div', 'chgHead'), sum = el('span', 'chgSum')
  const sel = el('select', 'chgSince'); sel.setAttribute('aria-label', t('changes.since'))
  const opt = (v, txt) => { const o = el('option', null, txt); o.value = v; sel.appendChild(o) }
  const snapName = s => s.label === 'Before restore' ? t('history.autoRestore') : s.label || (s.kind === 'auto' ? t('history.autoName') : t('history.unnamed'))
  if (watch?.base) opt(watch.base, t('changes.lastSeen') + (watch.seen_at ? ' · ' + ago(watch.seen_at) : ''))
  list.filter(s => s.id !== watch?.base).forEach(s => opt(s.id, snapName(s) + ' · ' + ago(s.created_at)))
  if (![...sel.options].some(o => o.value === sid)) opt(sid, '…')
  sel.value = sid
  const x = icoBtn(null, ICO_X); x.title = t('common.close'); x.setAttribute('aria-label', t('common.close')); x.onclick = close
  head.append(el('b', null, t('changes.title')), sum, el('span', 'chgSp'), el('span', 'chgVs', t('changes.since')), sel, x)
  const body = el('div', 'chgBody'), files = el('div', 'chgFiles'), view = el('div', 'chgView')
  body.append(files, view); card.append(head, body); ov.appendChild(card); document.body.appendChild(ov)
  let loadN = 0
  const load = async () => {
    const n = ++loadN
    files.replaceChildren(); view.replaceChildren(el('div', 'chgEmpty', '…'))
    let s
    try { s = await api('GET', `${url}/${sel.value}`) }
    catch (e) { view.replaceChildren(el('div', 'chgEmpty', e.message)); return }
    if (!ov.isConnected || n !== loadN) return
    const changes = s.changes.map(c => ({ ...c, ops: c.binary ? [] : markInline(lineOps(c.before, c.after)) }))
    const total = changes.reduce((a, c) => { const st = opStats(c.ops); return { add: a.add + st.add, del: a.del + st.del } }, { add: 0, del: 0 })
    sum.replaceChildren(el('span', null, t('changes.files', { n: changes.length })), el('span', 'plus', ' +' + total.add), el('span', 'minus', ' −' + total.del))
    if (!changes.length) { view.replaceChildren(el('div', 'chgEmpty', t('changes.none'))); return }
    const cards = changes.map(c => {
      const st = opStats(c.ops), box = el('section', 'chgFile'), cut = c.name.lastIndexOf('/')
      const hd = el('button', 'chgFileHead'); hd.type = 'button'; hd.setAttribute('aria-expanded', 'true')
      const bar = el('span', 'chgBar')
      const unit = Math.max(1, st.add + st.del)
      for (let i = 0; i < 5; i++) bar.appendChild(el('i', i < Math.round(st.add / unit * 5) ? 'a' : i < Math.round(st.add / unit * 5) + Math.round(st.del / unit * 5) ? 'd' : ''))
      hd.append(el('span', 'chev', '▾'), el('span', 'dir', cut >= 0 ? c.name.slice(0, cut + 1) : ''), el('b', null, c.name.slice(cut + 1)),
        c.status === 'modified' ? el('span') : el('span', 'badge ' + c.status, t(c.status === 'added' ? 'changes.added' : 'changes.deleted')),
        el('span', 'sp'), el('span', 'plus', '+' + st.add), el('span', 'minus', '−' + st.del), bar)
      const code = el('div', 'chgCode')
      if (c.binary) code.appendChild(el('div', 'chgNote', c.status === 'added' ? t('changes.binAdded', { b: chgSizeText(c.after_size) }) : c.status === 'deleted' ? t('changes.binDeleted', { a: chgSizeText(c.before_size) }) : t('changes.binChanged', { a: chgSizeText(c.before_size), b: chgSizeText(c.after_size) })))
      else renderOps(code, c.ops)
      hd.onclick = () => { const open = hd.getAttribute('aria-expanded') !== 'true'; hd.setAttribute('aria-expanded', String(open)); code.hidden = !open; hd.querySelector('.chev').textContent = open ? '▾' : '▸' }
      box.append(hd, code)
      const item = el('button', 'chgItem'); item.type = 'button'; item.title = c.name
      item.append(el('i', 'st ' + c.status), el('span', 'nm', c.name.slice(cut + 1)), el('span', 'cnt'))
      item.lastChild.append(el('span', 'plus', '+' + st.add), document.createTextNode(' '), el('span', 'minus', '−' + st.del))
      item.onclick = () => flyToFile(view, box)
      files.appendChild(item)
      return box
    })
    view.replaceChildren(...cards)
  }
  sel.onchange = load
  load()
  x.focus()
}
function renderOps(box, all) {
  let a = 1, b = 1
  const line = (o, na, nb) => {
    const row = el('div', 'chgLine ' + (o.k === 'a' ? 'del' : o.k === 'b' ? 'add' : 'ctx'))
    const tx = el('span', 'tx')
    if (o.hl) { tx.append(o.s.slice(0, o.hl[0]), el('mark', null, o.s.slice(o.hl[0], o.hl[1])), o.s.slice(o.hl[1])) } else tx.textContent = o.s
    row.append(el('span', 'no', na === '' ? '' : String(na)), el('span', 'no', nb === '' ? '' : String(nb)), el('span', 'sg', o.k === 'a' ? '−' : o.k === 'b' ? '+' : ''), tx)
    return row
  }
  const ops = all.length > CHG_LINES ? all.slice(0, CHG_LINES) : all
  foldOps(ops).forEach(o => {
    if (o.k === '…') {
      const a0 = a, b0 = b, fold = el('button', 'chgFold'); fold.type = 'button'
      fold.append(el('span', 'ic', '↕'), el('span', null, t('changes.expand', { n: o.n })))
      fold.onclick = () => { const rows = o.hidden.map((h, i) => line(h, a0 + i, b0 + i)); fold.replaceWith(...rows) }
      box.appendChild(fold); a += o.n; b += o.n; return
    }
    box.appendChild(line(o, o.k === 'b' ? '' : a, o.k === 'a' ? '' : b))
    if (o.k !== 'b') a++
    if (o.k !== 'a') b++
  })
  if (all.length > CHG_LINES) box.appendChild(el('div', 'chgNote', t('history.truncated')))
}
