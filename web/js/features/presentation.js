// --- Presentation mode: rendered pages one at a time (distinct from read) ---
// Self-contained: builds its own button + toolbar (shell untouched, same pattern
// as pvBar), coordinates out via window CustomEvents only (never touches the
// 90-settings sync region or the 50-preview render path).
// NOTE: leading semicolon is load-bearing: the previous feature file ends
// without one, so this paren must not continue its expression statement.
;(function () {
  'use strict'
  const t = (k, p) => (window.t ? window.t(k, p) : String(k).split('.').pop())
  const $ = id => document.getElementById(id)
  const PREV_SVG = '<svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 3L5 8l5 5"/></svg>'
  const NEXT_SVG = '<svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 3l5 5-5 5"/></svg>'
  const EXIT_SVG = '<svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8"/></svg>'
  const FULL_SVG = '<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 6V2.5H6"/><path d="M10 2.5h3.5V6"/><path d="M13.5 10v3.5H10"/><path d="M6 13.5H2.5V10"/></svg>'
  let on = false, idx = 0, seen = false, prevView = 'split', prevTop = 0, bar = null, count = null, guard = false, fullscreenOwned = false, exiting = false
  const pages = () => {
    const pv = $('preview')
    if (!pv) return []
    const slots = pv.querySelectorAll('.pvPage')
    return slots.length ? [...slots] : [...pv.querySelectorAll('canvas')]
  }
  const paintCount = n => { if (count) count.textContent = t('presentation.counter', { page: idx + 1, pages: n }) }
  function show(i, announce) {
    const ps = pages()
    if (!ps.length) return false
    const n = Math.max(0, Math.min(ps.length - 1, i)), changed = !seen || n !== idx
    idx = n; seen = true
    ps.forEach((p, k) => { p.hidden = k !== n })
    fit(); paintCount(ps.length)
    if (announce !== false && changed) window.dispatchEvent(new CustomEvent('present-page', { detail: { page: idx + 1, pages: ps.length } }))
    return true
  }
  function fit() {
    if (!on || exiting) return
    const pv = $('preview'), p = pages()[idx]
    if (!p) return
    const ratio = +p.dataset.r || p.height / p.width || 1
    const width = Math.max(1, Math.min(pv.clientWidth, pv.clientHeight / ratio))
    p.style.width = width + 'px'; p.style.height = width * ratio + 'px'
  }
  addEventListener('resize', fit)
  function firstVisible() {
    const pv = $('preview')
    if (!pv) return 0
    const top = pv.getBoundingClientRect().top, ps = pages()
    for (let i = 0; i < ps.length; i++) if (ps[i].getBoundingClientRect().bottom > top + 1) return i
    return 0
  }
  function mkBtn(svg, label, fn) {
    const b = document.createElement('button')
    b.innerHTML = svg
    b.title = label; b.setAttribute('aria-label', label)
    b.onclick = fn
    return b
  }
  function buildBar() {
    if (bar) bar.remove()
    bar = document.createElement('div')
    bar.id = 'presentBar'
    bar.setAttribute('role', 'toolbar')
    bar.setAttribute('aria-label', t('presentation.toolbar'))
    const prev = mkBtn(PREV_SVG, t('presentation.prev'), () => show(idx - 1))
    prev.id = 'presentPrev'
    count = document.createElement('span')
    count.id = 'presentCount'
    count.setAttribute('role', 'status')
    count.setAttribute('aria-live', 'polite')
    const next = mkBtn(NEXT_SVG, t('presentation.next'), () => show(idx + 1))
    next.id = 'presentNext'
    const close = mkBtn(EXIT_SVG, t('presentation.exit'), exit)
    close.id = 'presentExit'
    bar.append(prev, count, next, close)
    document.body.appendChild(bar)
  }
  function relabel() { // language switch (parent calls Present.relabel from refreshLang, see ui-contract)
    const b = $('presentBtn')
    if (b) { const s = t('presentation.enter'); b.title = s; b.setAttribute('aria-label', s) }
    if (!bar) return
    bar.setAttribute('aria-label', t('presentation.toolbar'))
    const set = (id, key) => { const x = $(id); if (x) { const s = t(key); x.title = s; x.setAttribute('aria-label', s) } }
    set('presentPrev', 'presentation.prev'); set('presentNext', 'presentation.next'); set('presentExit', 'presentation.exit')
    paintCount(Math.max(1, pages().length))
  }
  function enter() {
    if (on) return false
    if (!pages().length) { toast(t('presentation.noPages')); return false }
    prevView = document.body.classList.contains('read') ? 'read' : document.body.classList.contains('editonly') ? 'editor' : 'split'
    prevTop = $('preview') ? $('preview').scrollTop : 0
    on = true; seen = false; idx = firstVisible()
    document.body.classList.add('present-switch', 'present')
    buildBar(); show(idx)
    if (!document.fullscreenElement && document.documentElement.requestFullscreen) {
      fullscreenOwned = true
      document.documentElement.requestFullscreen().then(() => { if (!on && document.fullscreenElement) return document.exitFullscreen(); fit() }).catch(() => { fullscreenOwned = false }).finally(endSwitch)
    } else endSwitch()
    window.dispatchEvent(new CustomEvent('present-enter', { detail: { page: idx + 1, pages: pages().length } }))
    const x = $('preview')
    if (x) x.focus()
    return true
  }
  function endSwitch() { requestAnimationFrame(() => requestAnimationFrame(() => document.body.classList.remove('present-switch'))) }
  function exit() {
    if (!on) return false
    document.body.classList.add('present-switch'); exiting = true
    if (fullscreenOwned && document.fullscreenElement) {
      fullscreenOwned = false
      document.exitFullscreen().then(exit, exit)
      return true
    }
    on = false; seen = false; exiting = false
    document.body.classList.remove('present')
    fullscreenOwned = false
    pages().forEach(p => { p.hidden = false })
    if (bar) { bar.remove(); bar = null; count = null }
    if ($('preview')) $('preview').scrollTop = prevTop
    const id = prevView === 'editor' ? 'vEdit' : prevView === 'read' ? 'vRead' : 'vSplit'
    const b = $(id)
    if (b && !b.classList.contains('on')) b.click() // prior mode back via existing control (no sync logic here)
    if (typeof pvRelayout === 'function') { try { pvRelayout() } catch (e) {} }
    endSwitch()
    window.dispatchEvent(new CustomEvent('present-exit'))
    return true
  }
  document.addEventListener('keydown', e => { // capture: runs before the editor Esc chain (modal still wins)
    if (!on) return
    if ($('modal') && $('modal').style.display !== 'none') return
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); exit(); return }
    const tag = (e.target && e.target.tagName) || ''
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(tag)) return
    let d = 0
    if (e.key === 'ArrowRight' || e.key === 'PageDown' || (e.key === ' ' && !e.shiftKey)) d = 1
    else if (e.key === 'ArrowLeft' || e.key === 'PageUp' || (e.key === ' ' && e.shiftKey)) d = -1
    else if (e.key === 'Home') { e.preventDefault(); show(0); return }
    else if (e.key === 'End') { e.preventDefault(); show(pages().length - 1); return }
    else return
    e.preventDefault(); e.stopPropagation()
    show(idx + d)
  }, true)
  document.addEventListener('fullscreenchange', () => { if (on && fullscreenOwned && !document.fullscreenElement) exit(); else fit() })
  document.addEventListener('mousemove', e => { if (on && bar) bar.classList.toggle('near', e.clientY > innerHeight - 100 && Math.abs(e.clientX - innerWidth / 2) < 240) })
  let tx0 = null
  document.addEventListener('touchstart', e => { if (on && e.touches.length === 1) tx0 = e.touches[0].clientX }, { passive: true })
  document.addEventListener('touchend', e => { // swipe between pages (buttons stay for a11y)
    if (!on || tx0 === null) return
    const dx = e.changedTouches[0].clientX - tx0
    tx0 = null
    if (Math.abs(dx) > 40) show(idx + (dx < 0 ? 1 : -1))
  })
  function armObserver() { // render/doc switch replaces preview children: re-pin or leave (old callbacks never drive the new view)
    const pv = $('preview')
    if (!pv) return
    new MutationObserver(() => {
      if (!on || guard) return
      guard = true
      try {
        const ps = pages()
        if (!ps.length) exit()
        else { show(Math.min(idx, ps.length - 1), false); paintCount(ps.length) }
      } finally { guard = false }
    }).observe(pv, { childList: true })
  }
  function armButton() { // entry point next to the zoom pill (no shell change, same pattern as pvBar)
    if ($('presentBtn')) return
    const tools = $('pvTools')
    if (!tools) { setTimeout(armButton, 1000); return }
    const b = document.createElement('button')
    b.id = 'presentBtn'
    b.innerHTML = '<svg width="15" height="15" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M4 2.5L13 8l-9 5.5z"/></svg>'
    const s = t('presentation.enter')
    b.title = s; b.setAttribute('aria-label', s)
    b.onclick = () => (on ? exit() : enter())
    const grp = tools.querySelector('.grp')
    if (grp) grp.appendChild(b)
    else tools.appendChild(b)
  }
  window.Present = { enter, exit, toggle: () => (on ? exit() : enter()), isOn: () => on, page: () => idx + 1, pages: () => pages().length, go: i => show(i), relabel }
  armObserver()
  armButton()
})()
