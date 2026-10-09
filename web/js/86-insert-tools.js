// --- Symbols: search + insert at cursor ---
const SYMS = ('→ ← ↑ ↓ ⇒ ⇐ ⇔ ∀ ∃ ∅ ∈ ∉ ⊂ ⊃ ⊆ ⊇ ∪ ∩ ∧ ∨ ¬ ⊕ ⊗ ⊥ ∥ ∠ ° ′ ″ ∞ ∑ ∏ ∫ √ ∂ ∇ ≈ ≠ ≡ ≤ ≥ ≪ ≫ ± ∓ × ÷ ⋅ ⋆ ★ ☆ ♣ ♦ ♥ ♠ • ◦ ▪ ▲ ► ● ◆ ✓ ✕ ☐ ☑ § ¶ © ® ™ € £ ¥ … – — „ “ ” ‘ ’ « » † ‡ ⌘ ⏎ ⇥ ⎋ α β γ δ ε ζ η θ ι κ λ μ ν ξ π ρ σ τ υ φ χ ψ ω Γ Δ Θ Λ Ξ Π Σ Υ Φ Ψ Ω').split(' ')
const SYN = { pfeil: '→←↑↓⇒⇐⇔', euro: '€', dollar: '$', alpha: 'α', beta: 'β', pi: 'π', summe: '∑', wurzel: '√', unendlich: '∞', kreuz: '✕✓', herz: '♥', stern: '★☆', strich: '–—', anfuhr: '„“”‘’«»', para: '§¶', copyright: '©®™' } // German search keys
function renderSym(q = '') {
  const p = $('symPop'); p.replaceChildren()
  const inp = el('input'); inp.placeholder = t('symbols.searchPh'); inp.value = q; inp.setAttribute('autocomplete', 'off'); inp.setAttribute('aria-label', t('symbols.searchAria'))
  inp.oninput = () => {
    const v = inp.value
    renderSym(v)
    const ni = p.querySelector('input'); ni.focus(); ni.setSelectionRange(v.length, v.length)
  }
  p.appendChild(inp)
  const g = el('div', 'grid')
  const ql = q.toLowerCase()
  SYMS.filter(s => !q || s.includes(q) || (SYN[ql] || '').includes(s)).slice(0, 120).forEach(s => {
    const b = el('button', null, s); b.title = t('symbols.insertSym', { s }); b.setAttribute('aria-label', b.title)
    b.onclick = () => {
      const m = cm.state.selection.main
      cm.dispatch({ changes: { from: m.from, to: m.to, insert: s }, selection: { anchor: m.from + s.length } })
      cm.focus()
    }
    g.appendChild(b)
  })
  p.appendChild(g)
}
$('symBtn').onclick = e => {
  e.stopPropagation()
  if (showPop('symPop')) { renderSym(); setTimeout(() => $('symPop').querySelector('input').focus(), 30) }
}
// --- Color: wrap selection with #text(fill: rgb("..")) ---
$('colPick').onchange = () => {
  const v = $('colPick').value, m = cm.state.selection.main
  const ins = `#text(fill: rgb("${v}"))[${getT().slice(m.from, m.to) || 'Text'}]`
  cm.dispatch({ changes: { from: m.from, to: m.to, insert: ins }, selection: { anchor: m.from + ins.length } })
  cm.focus()
}
// --- @-mentions: suggest while typing, colored name in card ---
let members = []
async function loadMembers() {
  try { members = (await api('GET', `/api/docs/${docId}/members`)).members } catch (e) { members = [] }
  if (popAnchor != null && !$('pop').contains(document.activeElement)
      && ![...$('pop').querySelectorAll('input')].some(i => i.value.trim())) renderPop() // refresh @-colors, keep drafts untouched
}
function wireMentions(inp) {
  let box = null
  const close = () => { if (box) { box.remove(); box = null } }
  inp.addEventListener('input', () => {
    close()
    const m = inp.value.slice(0, inp.selectionStart).match(/@([\w-]*)$/)
    if (!m) return
    const q = m[1].toLowerCase()
    const list = members.filter(n => n.toLowerCase().startsWith(q) && n !== user).slice(0, 5)
    if (!list.length) return
    box = el('div', 'mbox')
    list.forEach(n => {
      const b = el('button', null, '@' + n)
      b.onmousedown = e => {
        e.preventDefault()
        const s = inp.selectionStart
        inp.value = inp.value.slice(0, s).replace(/@[\w-]*$/, '@' + n + ' ') + inp.value.slice(s)
        inp.focus(); close()
      }
      box.appendChild(b)
    })
    inp.parentNode.style.position = 'relative'
    inp.parentNode.appendChild(box)
  })
  inp.addEventListener('blur', () => setTimeout(close, 200))
  inp.addEventListener('keydown', e => { if (e.key === 'Escape') close() })
}
function richText(text) { // @-names colored, rest text (no user HTML)
  const p = el('p', 'tx')
  text.split(/(@[A-Za-z0-9_-]+)/g).forEach(part => {
    if (/^@[A-Za-z0-9_-]+$/.test(part) && members.includes(part.slice(1))) {
      const b = el('b', null, part)
      b.style.color = colOf(part.slice(1))
      p.appendChild(b)
    } else p.appendChild(document.createTextNode(part))
  })
  return p
}
