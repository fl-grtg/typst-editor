// --- Mobile notice: phones get a one-screen warning, tablets/desktops keep the normal UI ---
// iPadOS 13+ reports a Macintosh UA, so touch-enabled Macs count as iPads, not phones.
;(function () {
  'use strict'
  const STORE = 'typst_mobile_warn'
  const isPhone = () => {
    try {
      const ua = navigator.userAgent || ''
      if (/iPad|Tablet|PlayBook|Silk|Kindle/i.test(ua)) return false
      if (/Macintosh/i.test(ua) && navigator.maxTouchPoints > 1) return false // iPadOS desktop mode
      if (/Android/i.test(ua)) return /Mobile/i.test(ua)
      return /iPhone|iPod|Windows Phone|IEMobile|BlackBerry|BB10|Opera Mini|Opera Mobi|webOS|Mobi/i.test(ua)
    } catch (e) { return false }
  }
  try { if (localStorage.getItem(STORE) === '0') return } catch (e) {}
  if (!isPhone()) return
  const ov = document.getElementById('mobileWarn')
  if (!ov) return
  const card = document.getElementById('mwCard')
  const last = document.activeElement
  ov.hidden = false
  const done = never => {
    if (never) { try { localStorage.setItem(STORE, '0') } catch (e) {} }
    ov.hidden = true
    if (last && document.contains(last)) last.focus()
  }
  document.getElementById('mwProceed').onclick = () => done(false)
  document.getElementById('mwNever').onclick = () => done(true)
  ov.addEventListener('keydown', e => {
    if (e.key === 'Escape') { e.preventDefault(); done(false); return }
    if (e.key !== 'Tab') return
    const f = [...ov.querySelectorAll('button')].filter(b => !b.disabled)
    const i = f.indexOf(document.activeElement)
    if (e.shiftKey && i <= 0) { e.preventDefault(); f[f.length - 1].focus() }
    else if (!e.shiftKey && (i < 0 || i === f.length - 1)) { e.preventDefault(); f[0].focus() }
  })
  setTimeout(() => card.focus(), 30)
})()
