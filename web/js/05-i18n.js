// --- i18n: t(key, params) over the embedded i18n-data JSON (see web/build.py) ---
// Embedded shape: {"<lang>":{"<area>":{...}}}. Language = browser default
// (navigator.language de -> de, else en); no settings switcher (Wave 2D).
// Missing web/i18n/ builds without the tag: t() then falls back to en, then key.
const I18N_DATA = (() => {
  try {
    const raw = (document.getElementById('i18n-data') || {}).textContent || ''
    return raw ? JSON.parse(raw) : {}
  } catch (e) { return {} }
})()
const I18N_LANG = (() => {
  try {
    const q = new URLSearchParams(location.search).get('lang')
    if (q === 'de' || q === 'en') return q
  } catch (e) {}
  try {
    if ((navigator.language || '').toLowerCase().startsWith('de')) return 'de'
  } catch (e) {}
  return 'en'
})()
function t(key, params) {
  const parts = String(key).split('.')
  const get = lang => {
    let node = I18N_DATA[lang]
    if (!node) return undefined
    for (const p of parts) {
      if (node && typeof node === 'object' && p in node) node = node[p]
      else return undefined
    }
    return typeof node === 'string' ? node : undefined
  }
  let s = get(I18N_LANG)
  if (s === undefined) s = get('en')
  if (s === undefined) return String(key)
  if (params) for (const [k, v] of Object.entries(params)) s = s.split('{' + k + '}').join(String(v))
  return s
}
function applyI18n() {
  try { document.documentElement.lang = I18N_LANG } catch (e) {}
  try {
    document.querySelectorAll('[data-i18n]').forEach(n => { n.textContent = t(n.getAttribute('data-i18n')) })
    document.querySelectorAll('[data-i18n-html]').forEach(n => { n.innerHTML = t(n.getAttribute('data-i18n-html')) })
    document.querySelectorAll('[data-i18n-ph]').forEach(n => n.setAttribute('placeholder', t(n.getAttribute('data-i18n-ph'))))
    document.querySelectorAll('[data-i18n-title]').forEach(n => n.setAttribute('title', t(n.getAttribute('data-i18n-title'))))
    document.querySelectorAll('[data-i18n-aria]').forEach(n => n.setAttribute('aria-label', t(n.getAttribute('data-i18n-aria'))))
  } catch (e) {}
}
window.t = t
window.I18N_LANG = I18N_LANG
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', applyI18n)
else applyI18n()
