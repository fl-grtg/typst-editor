// --- Settings: click on user box (font/zoom, profile, password, account) ---
document.body.appendChild($('setPop'))
$('userMain').onclick = e => {
  e.stopPropagation()
  if (showPop('setPop')) { apiKeys = null; sessList = null; renderSettings() }
}
kb($('userMain'), () => $('userMain').click())
let apiKeys = null, apiKeysLoading = false, lastKeySecret = ''
let settingsCategory = 'account'
const SETTINGS_CATS = [
  ['account', 'settings.navAccount'], ['editor', 'settings.navEditor'], ['shortcuts', 'settings.navShortcuts'],
  ['sessions', 'settings.navSessions'], ['api', 'settings.navApi'], ['storage', 'settings.navStorage']
]
const settingsError = message => toast(message || t('common.requestFailed'), null, null, 5000, 'error')
const AGENT_PROMPT = 'Install the Typst Editor skill from https://raw.githubusercontent.com/fl-grtg/typst-editor/main/skills/typst-editor/SKILL.md and connect to my Typst server over MCP at ' + location.origin + '/mcp. Ask me for the API key if missing.'
// 2D: language without reload (same module as 05-i18n: shadow t, keep ?lang helper)
const LANG_KEY = 'typst_lang'
function curLangInit() {
  try { const q = new URLSearchParams(location.search).get('lang'); if (q === 'de' || q === 'en') return q } catch (e) {}
  try { const s = localStorage.getItem(LANG_KEY); if (s === 'de' || s === 'en') return s } catch (e) {}
  try { if ((navigator.language || '').toLowerCase().startsWith('de')) return 'de' } catch (e) {}
  return 'en'
}
let langCur = curLangInit()
function tLang(key, params) {
  const parts = String(key).split('.')
  const get = lang => {
    let node = null
    try { node = I18N_DATA[lang] } catch (e) { return undefined }
    if (!node) return undefined
    for (const p of parts) {
      if (node && typeof node === 'object' && Object.prototype.hasOwnProperty.call(node, p)) node = node[p]
      else return undefined
    }
    return typeof node === 'string' ? node : undefined
  }
  let s = get(langCur)
  if (s === undefined) s = get('en')
  if (s === undefined) return String(key)
  if (params) for (const [k, v] of Object.entries(params)) s = s.split('{' + k + '}').join(String(v))
  return s
}
try { t = tLang; window.t = tLang; window.I18N_LANG = langCur } catch (e) {}
function paintThemeBtn() {
  let dark = false
  try {
    const m = document.documentElement.getAttribute('data-theme')
    const mode = m === 'light' || m === 'dark' ? m : 'system'
    dark = mode !== 'system' ? mode === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches
  } catch (e) {}
  const lbl = dark ? t('menu.toLight') : t('menu.toDark')
  const sun = '<svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="8" r="2.8"/><path d="M8 1.6v1.4M8 13v1.4M1.6 8H3M13 8h1.4M3.5 3.5l1 1M11.5 11.5l1 1M3.5 12.5l1-1M11.5 4.5l1-1"/></svg>'
  const moon = '<svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13.4 9.6A5.6 5.6 0 0 1 6.4 2.6a5.6 5.6 0 1 0 7 7z"/></svg>'
  document.querySelectorAll('[data-rail="theme"]').forEach(b => { b.innerHTML = dark ? sun : moon; b.title = lbl; b.setAttribute('aria-label', lbl) })
  try { const bg = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim(); if (bg) document.querySelectorAll('meta[name="theme-color"]').forEach(m => m.setAttribute('content', bg)) } catch (e) {}
}
function refreshLang() {
  try { document.documentElement.lang = langCur } catch (e) {}
  try {
    document.querySelectorAll('[data-i18n]').forEach(n => { n.textContent = t(n.getAttribute('data-i18n')) })
    document.querySelectorAll('[data-i18n-html]').forEach(n => { n.innerHTML = t(n.getAttribute('data-i18n-html')) })
    document.querySelectorAll('[data-i18n-ph]').forEach(n => n.setAttribute('placeholder', t(n.getAttribute('data-i18n-ph'))))
    document.querySelectorAll('[data-i18n-title]').forEach(n => n.setAttribute('title', t(n.getAttribute('data-i18n-title'))))
    document.querySelectorAll('[data-i18n-aria]').forEach(n => n.setAttribute('aria-label', t(n.getAttribute('data-i18n-aria'))))
  } catch (e) {}
  try { paintThemeBtn() } catch (e) {}
  try { if (typeof paintSecs === 'function') paintSecs() } catch (e) {}
  try { if (typeof paintMe === 'function' && user) paintMe() } catch (e) {}
  try { if (typeof updPos === 'function') updPos() } catch (e) {}
  try { if (typeof paintOutline === 'function') paintOutline() } catch (e) {}
  try { if (typeof paintBadge === 'function') paintBadge() } catch (e) {}
  try { if (typeof paintEmpty === 'function' && $('emptyCard')) paintEmpty() } catch (e) {} // shortcut hints are localized too
  window.Present?.relabel()
  try { if (user && typeof sidebar === 'function') sidebar().catch(() => {}) } catch (e) {}
}
function setLang(lang) {
  if (lang !== 'de' && lang !== 'en') return
  langCur = lang
  try { window.I18N_LANG = langCur } catch (e) {}
  lsSet(LANG_KEY, langCur)
  refreshLang()
  try { scQuery = ''; scQueryIsCombo = false } catch (e) {} // localized labels change: a stale filter would match nothing
  try { renderSettings() } catch (e) {}
  try { const s = $('langSel'); if (s) s.focus() } catch (e) {}
}
// theme from settings (same storage as ui-layer classic script)
function themeMode() { const m = document.documentElement.getAttribute('data-theme'); return m === 'light' || m === 'dark' ? m : 'system' }
function setThemeMode(m) {
  try {
    if (m === 'light' || m === 'dark') { document.documentElement.setAttribute('data-theme', m); lsSet('typst_theme', m) }
    else { document.documentElement.removeAttribute('data-theme'); try { localStorage.removeItem('typst_theme') } catch (e) {} }
  } catch (e) {}
  try { paintThemeBtn() } catch (e) {}
}
let sessList = null, sessLoading = false
function loadSess() {
  if (sessLoading) return; sessLoading = true
  api('GET', '/api/sessions').then(d => { sessList = d.sessions || [] })
    .catch(e => { settingsError(e.message); sessList = [] }).finally(() => { sessLoading = false; renderSettings() })
}
window.setLang = setLang
window.curLang = () => langCur
window.setThemeMode = setThemeMode
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => { try { paintThemeBtn() } catch (e) {}
  try { if (langCur !== I18N_LANG) refreshLang() } catch (e) {} })
else { try { paintThemeBtn() } catch (e) {}
  try { if (langCur !== I18N_LANG) refreshLang() } catch (e) {} }
function loadKeys() {
  if (apiKeysLoading) return; apiKeysLoading = true
  api('GET', '/api/keys').then(d => { apiKeys = d.keys || [] })
    .catch(e => { settingsError(e.message); apiKeys = [] }).finally(() => { apiKeysLoading = false; renderSettings() })
}
const shortD = s => {
  if (!s) return t('settings.never')
  try { return new Intl.DateTimeFormat(langCur, { dateStyle: 'medium' }).format(new Date(s)) }
  catch (e) { return String(s).slice(0, 10) }
}
const keyHint = k => {
  const pc = el('code', null, k.prefix ? `tpe_${k.prefix.slice(0, 8)}...` : 'tpe_...')
  return pc
}
function copyTxt(txt, inp) {
  const fb = () => {
    const f = inp || document.createElement('textarea')
    if (!inp) { f.value = txt; f.style.position = 'fixed'; f.style.opacity = '0'; document.body.appendChild(f) }
    f.select(); try { document.execCommand('copy'); toast(t('common.copied')) } catch (e) {}
    if (!inp) f.remove()
  }
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(txt).then(() => toast(t('common.copied'))).catch(fb)
  else fb()
}
function showKeySecret() {
  if (!lastKeySecret) return
  const prev = document.activeElement
  const overlay = el('div', 'keySecretOverlay'); overlay.id = 'keySecret'; overlay.setAttribute('role', 'dialog'); overlay.setAttribute('aria-modal', 'true'); overlay.setAttribute('aria-labelledby', 'keySecretTitle')
  overlay.onclick = e => e.stopPropagation()
  const card = el('div', 'keySecretCard')
  const top = el('div', 'keySecretTop')
  const title = el('b', null, t('settings.keyCreated')); title.id = 'keySecretTitle'
  const close = icoBtn('keySecretClose', ICO_X); close.type = 'button'; close.title = t('common.close'); close.setAttribute('aria-label', t('common.close'))
  const value = el('input', 'keySecretValue'); value.readOnly = true; value.value = lastKeySecret; value.setAttribute('aria-label', t('settings.keyOnceAria'))
  const copy = el('button', 'keySecretCopy', t('common.copy')); copy.type = 'button'; copy.onclick = () => copyTxt(lastKeySecret, value)
  const cmd = `claude mcp add --transport http typst-editor ${location.origin}/mcp --header "Authorization: Bearer ${lastKeySecret}"`
  const copyCmd = el('button', 'keySecretCopy', t('settings.connectCopy')); copyCmd.type = 'button'; copyCmd.onclick = () => copyTxt(cmd)
  top.append(title, close)
  card.append(top, el('p', 'keySecretHint', t('settings.keyOnceHint')), value, copy, copyCmd)
  overlay.appendChild(card); document.body.appendChild(overlay); modalInert(true)
  const done = () => { lastKeySecret = ''; modalInert(false); overlay.remove(); if (prev && document.contains(prev)) prev.focus() }
  close.onclick = done
  overlay.addEventListener('keydown', e => {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); return }
    if (e.key !== 'Tab') return
    const focusable = [close, value, copy, copyCmd], i = focusable.indexOf(document.activeElement)
    if (e.shiftKey && i <= 0) { e.preventDefault(); focusable[focusable.length - 1].focus() }
    else if (!e.shiftKey && (i < 0 || i === focusable.length - 1)) { e.preventDefault(); focusable[0].focus() }
  })
  setTimeout(() => { value.focus(); value.select() }, 30)
}
function settingRange(labelKey, id, min, max, def, step, get, unit, set) { // slider row: label, filled track, live value, reset
  const row = el('div', 'row settingRow settingRangeRow')
  const label = el('label', null, t(labelKey)); label.htmlFor = id
  const box = el('div', 'settingRange')
  const input = el('input', 'settingRangeInput'); input.type = 'range'; input.id = id
  input.min = min; input.max = max; input.step = step
  const val = el('span', 'val')
  const reset = icoBtn('settingReset', ICO_UNDO); reset.type = 'button'
  reset.title = t('settings.resetDefault'); reset.setAttribute('aria-label', reset.title + ': ' + label.textContent)
  const paint = () => { // no re-render while dragging: the row updates itself
    const v = Math.round(+get())
    const text = v + unit
    input.value = v; val.textContent = text; input.setAttribute('aria-valuetext', text)
    input.style.setProperty('--fill', ((v - min) / (max - min) * 100) + '%')
    reset.disabled = v === def
  }
  input.oninput = () => { set(+input.value); paint() }
  reset.onclick = e => { e.stopPropagation(); set(def); paint(); input.focus() }
  paint(); box.append(input, val, reset); row.append(label, box)
  return row
}
function renderSettings() {
  const p = $('setPop')
  const fieldValues = new Map([...p.querySelectorAll('[data-setting-field]')].map(input => [input.dataset.settingField, input.value]))
  const prevContent = p.querySelector('.setContent')
  const prevCat = p.querySelector('.setView.active')?.dataset.category
  const keepScroll = prevContent && prevCat === settingsCategory ? prevContent.scrollTop : 0 // changes re-render: stay at the same spot
  p.replaceChildren()
  const sec = (...kids) => { const d = el('div', 'sec'); kids.forEach(k => d.appendChild(k)); return d }
  const grp = (title, ...secs) => { const w = el('div', 'grp'); w.appendChild(el('h4', null, title)); secs.forEach(s => w.appendChild(s)); return w }
  const keepField = (input, key) => {
    input.dataset.settingField = key
    if (fieldValues.has(key)) input.value = fieldValues.get(key)
    return input
  }
  const categories = SETTINGS_CATS
  const views = Object.fromEntries(categories.map(([id]) => {
    const view = el('section', 'setView'); view.dataset.category = id
    return [id, view]
  }))
  const put = (id, node) => views[id].appendChild(node)
  const top = el('div', 'sTop')
  const close = icoBtn(null, ICO_X); close.title = t('common.close'); close.setAttribute('aria-label', close.title)
  close.onclick = e => { e.stopPropagation(); p.style.display = 'none'; document.body.classList.remove('settings-open') }
  top.append(el('b', null, t('settings.title')), close); p.appendChild(top)
  const layout = el('div', 'setLayout'), rail = el('aside', 'setRail')
  const nav = el('nav', 'setNav'); nav.setAttribute('aria-label', t('settings.sections'))
  const content = el('div', 'setContent')
  const buttons = {}
  categories.forEach(([id, key]) => {
    const b = el('button', 'setNavItem', t(key)); b.type = 'button'; b.dataset.category = id
    b.onclick = e => { e.stopPropagation(); activateSettingsCategory(id) } // re-render may detach this button: outside-click must not hide the panel
    buttons[id] = b; nav.appendChild(b); content.appendChild(views[id])
  })
  rail.appendChild(nav); layout.append(rail, content); p.appendChild(layout)
  put('shortcuts', typeof shortcutSettingsView === 'function' ? shortcutSettingsView() : el('div')) // feature file: never break settings if it is not loaded
  const activateSettingsCategory = id => {
    if (settingsCategory !== id) {
      content.scrollTop = 0 // a new category starts at its own top, not the previous scroll position
      const hadShortcutState = typeof window.scHasPendingState === 'function' && window.scHasPendingState() // feature file: a recording/conflict belongs to the shortcuts view
      try { scResetRecordingState() } catch (e) {} // feature file: never break the category switch
      settingsCategory = id
      if (hadShortcutState) {
        renderSettings()
        $('setPop').querySelector('.setNavItem[data-category="' + id + '"]')?.focus() // re-render replaced every nav button
        return
      }
    }
    settingsCategory = id
    categories.forEach(([key]) => {
      buttons[key].classList.toggle('active', key === id)
      if (key === id) buttons[key].setAttribute('aria-current', 'page')
      else buttons[key].removeAttribute('aria-current')
      views[key].classList.toggle('active', key === id)
    })
  }
  activateSettingsCategory(settingsCategory)
  const fr = settingRange('settings.editorFontSize', 'edSizeSet', ED_MIN, ED_MAX, ED_DEF, ED_STEP, () => edSize, 'px', setEd)
  const zr = settingRange('settings.previewZoom', 'pvZoomSet', PV_MIN, PV_MAX, PV_DEF, PV_SLIDER_STEP, () => pvZoom, ' %', setPv)
  const lr = el('div', 'row settingRow preferenceRow'); lr.append(el('label', null, t('settings.language')))
  const ls = el('select'); ls.id = 'langSel'; ls.setAttribute('aria-label', t('settings.language'))
  ;[['de', t('settings.langDe')], ['en', t('settings.langEn')]].forEach(([v, lab]) => { const o = el('option', null, lab); o.value = v; if (v === langCur) o.selected = true; ls.appendChild(o) })
  ls.onchange = () => setLang(ls.value)
  lr.append(ls)
  const hr = el('div', 'row settingRow preferenceRow'); hr.append(el('label', null, t('settings.theme')))
  const hs = el('select'); hs.id = 'themeSel'; hs.setAttribute('aria-label', t('settings.theme'))
  ;[['system', t('settings.themeSystem')], ['light', t('settings.themeLight')], ['dark', t('settings.themeDark')]].forEach(([v, lab]) => { const o = el('option', null, lab); o.value = v; if (v === themeMode()) o.selected = true; hs.appendChild(o) })
  hs.onchange = () => { setThemeMode(hs.value); renderSettings(); try { const s = $('themeSel'); if (s) s.focus() } catch (e) {} }
  hr.append(hs)
  const accountPrefs = grp(t('settings.preferences'), sec(lr, hr))
  const tr = el('div', 'row settingRow'); tr.append(el('label', null, t('settings.tabWidth')))
  const ts = el('select'); ts.setAttribute('aria-label', t('settings.tabWidth')); ts.title = t('settings.tabWidthHint')
  ;[2, 4, 8].forEach(n => { const o = el('option', null, t('settings.tabSpaces', { n })); o.value = String(n); if (n === tabW) o.selected = true; ts.appendChild(o) })
  ts.onchange = () => { tabW = +ts.value || 2; lsSet('typst_tab', tabW); cm.dispatch({ effects: tabComp.reconfigure([EditorState.tabSize.of(tabW), indentUnit.of(' '.repeat(tabW))]) }); renderSettings() }
  tr.appendChild(ts)
  const wr = el('div', 'row settingRow')
  const wl = el('label', null, t('settings.lineWrap')); wl.setAttribute('for', 'wrapSet'); wl.title = t('settings.lineWrapHint')
  const wc = el('input', 'settingSwitch'); wc.type = 'checkbox'; wc.id = 'wrapSet'; wc.setAttribute('role', 'switch'); wc.checked = wrapOn
  wc.setAttribute('aria-label', t('settings.lineWrap')); wc.title = t('settings.lineWrapHint')
  wc.onchange = () => setWrap(wc.checked)
  wr.append(wl, wc)
  const edSec = sec(fr, zr, tr, wr)
  for (const s of [formatSettingsSec(), spellSettingsSec()]) while (s.firstChild) edSec.appendChild(s.firstChild)
  put('editor', grp(t('settings.editorGroup'), edSec))
  const avatarActions = el('div', 'row avatarRow')
  const im = el('img', 'av'); im.alt = t('settings.avatarAlt'); im.style.background = colOf(user || '?')
  if (avatarV) im.src = `/api/avatar/${encodeURIComponent(user)}?v=${avatarV}`; else { im.style.display = 'none'; const fb = el('span', 'avFallback'); fb.textContent = (user || '?').slice(0, 2).toUpperCase(); fb.style.background = colOf(user || '?'); avatarActions.appendChild(fb) }
  im.onerror = () => im.style.display = 'none'
  const pick = el('button', null, t('settings.changeAvatar')); pick.onclick = e => {
    e.stopPropagation()
    const pop = $('setPop')
    $('avPick').click()
    window.addEventListener('focus', () => setTimeout(() => {
      if (pop.style.display === 'none') pop.style.display = ''
    }, 120), { once: true })
  }
  const rm = el('button', 'btnSecondary', t('settings.resetAvatar'))
  rm.disabled = !avatarV
  rm.onclick = () => api('DELETE', '/api/me/avatar')
    .then(() => { avatarV++; paintMe(); renderPeers(); renderSettings() })
    .catch(e => settingsError(e.message))
  avatarActions.append(im, pick, rm); put('account', grp(t('settings.changeAvatar'), sec(avatarActions)))
  put('account', accountPrefs)
  const storage = el('div', 'storageUsage')
  put('storage', grp(t('settings.storageTitle'), sec(storage)))
  api('GET', '/api/me').then(d => {
    if (!storage.isConnected || !d.storage) return
    const mib = bytes => new Intl.NumberFormat(langCur, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(bytes / 1048576)
    const used = Math.max(0, Number(d.storage.used) || 0), limit = Math.max(0, Number(d.storage.limit) || 0)
    const ratio = limit ? Math.min(100, used / limit * 100) : 0
    const summary = el('div', 'storageSummary')
    summary.append(el('span', 'storageLabel', t('settings.storageUsage', { used: mib(used), limit: mib(limit) })), el('span', 'storagePercent', Math.round(ratio) + '%'))
    const meter = el('div', 'storageMeter')
    meter.setAttribute('role', 'progressbar'); meter.setAttribute('aria-label', t('settings.storageTitle'))
    meter.setAttribute('aria-valuemin', '0'); meter.setAttribute('aria-valuemax', '100'); meter.setAttribute('aria-valuenow', String(Math.round(ratio)))
    const fill = el('span', 'storageMeterFill'); fill.style.width = ratio + '%'
    if (used > limit) fill.classList.add('over')
    meter.appendChild(fill); storage.replaceChildren(summary, meter)
    if (d.storage.migration_allowance) storage.appendChild(el('div', 'storageMeta', t('settings.storageAllowance', { amount: mib(d.storage.migration_allowance) })))
  }).catch(e => { if (storage.isConnected) settingsError(e.message) })
  const nr = el('div', 'accountForm')
  const nn = keepField(el('input'), 'newName'); nn.name = 'profile-label'; nn.autocomplete = 'off'; nn.readOnly = true; nn.onfocus = () => { nn.readOnly = false }; nn.placeholder = t('settings.namePlaceholder'); nn.setAttribute('aria-label', t('settings.newName'))
  const npw = keepField(el('input'), 'nameCurrentPassword'); npw.type = 'password'; npw.name = 'current-password-name-change'; npw.autocomplete = 'current-password'; npw.placeholder = t('settings.currentPasswordPlaceholder'); npw.setAttribute('aria-label', t('settings.confirmWithPassword'))
  const nameField = el('label', 'accountField'); nameField.append(el('span', null, t('settings.newName')), nn)
  const namePasswordField = el('label', 'accountField'); namePasswordField.append(el('span', null, t('settings.confirmWithPassword')), npw)
  const nok = el('button', null, t('settings.changeName'))
  nok.onclick = () => { if (nok.disabled) return; if (!nn.value.trim() || (hasPassword && !npw.value)) { settingsError(t(hasPassword ? 'settings.needNamePw' : 'settings.needName')); return } nok.disabled = true; api('POST', '/api/me/name',
    { name: nn.value.trim(), password: hasPassword ? npw.value : '' })
    .then(d => { const spelling = spellStored(); nn.value = ''; npw.value = ''; user = d.user; loadSpell(spelling); paintMe(); sidebar(); renderSettings() })
    .catch(e => settingsError(e.message)).finally(() => nok.disabled = false) }
  if (hasPassword) nr.append(nameField, namePasswordField, nok); else nr.append(nameField, nok)
  put('account', grp(t('settings.nameGroup'), sec(nr)))
  if (hasPassword) {
    const pr = el('div', 'accountForm')
    const po = keepField(el('input'), 'passwordCurrentPassword'); po.type = 'password'; po.name = 'current-password-change'; po.autocomplete = 'current-password'; po.placeholder = t('settings.currentPasswordPlaceholder'); po.setAttribute('aria-label', t('settings.confirmCurrentPassword'))
    const pn = keepField(el('input'), 'newPassword'); pn.type = 'password'; pn.name = 'account-next-secret'; pn.autocomplete = 'off'; pn.readOnly = true; pn.onfocus = () => { pn.readOnly = false }; pn.placeholder = t('settings.newPw'); pn.setAttribute('aria-label', t('settings.newPw'))
    const oldPasswordField = el('label', 'accountField'); oldPasswordField.append(el('span', null, t('settings.confirmCurrentPassword')), po)
    const newPasswordField = el('label', 'accountField'); newPasswordField.append(el('span', null, t('settings.newPw')), pn)
    const pok = el('button', null, t('settings.changePassword'))
    pok.onclick = () => { if (pok.disabled) return; if (!po.value || !pn.value) { settingsError(t('settings.needOldNew')); return } pok.disabled = true; api('POST', '/api/me/password', { old: po.value, new: pn.value })
      .then(() => { po.value = pn.value = ''; toast(t('settings.pwChanged')) })
      .catch(e => settingsError(e.message)).finally(() => pok.disabled = false) }
    pr.append(newPasswordField, oldPasswordField, pok); put('account', grp(t('settings.pwGroup'), sec(pr)))
  }
  const bk = el('div', 'row')
  const bb = el('button', 'btnSecondary', t('settings.backupBtn'))
  bb.title = t('settings.backupTitle')
  bb.onclick = () => { const a = document.createElement('a'); a.href = '/api/export.zip'; a.click() }
  bk.appendChild(bb); put('storage', grp(t('settings.backup'), sec(bk)))
  const agCp = el('button', 'agentCopyBtn'); agCp.type = 'button'; agCp.append(el('span', null, t('common.copy')))
  agCp.title = t('settings.agentCopy'); agCp.setAttribute('aria-label', t('settings.agentCopy'))
  agCp.onclick = () => copyTxt(AGENT_PROMPT)
  const agRow = el('div', 'row agentRow'); agRow.append(el('span', null, t('settings.agentHint')), agCp)
  put('api', grp(t('settings.agent'), sec(agRow)))
  const keySecs = []
  const ksec = (...kids) => sec(...kids)
  const kn = keepField(el('input'), 'keyName'); kn.placeholder = t('settings.keyName'); kn.maxLength = 40; kn.setAttribute('aria-label', t('settings.keyName'))
  const rs = el('select'); rs.setAttribute('aria-label', t('common.roleAria'))
  ;[['editor', t('common.roleEditor')], ['reviewer', t('settings.roleReviewer')]].forEach(([v, lab]) => { const o = el('option', null, lab); o.value = v; rs.appendChild(o) })
  const ms = el('select'); ms.setAttribute('aria-label', t('settings.keyMode')); ms.title = t('settings.keyMode')
  ;[['auto', t('settings.modeAuto')], ['direct', t('settings.modeDirect')], ['propose', t('settings.modePropose')]].forEach(([v, lab]) => { const o = el('option', null, lab); o.value = v; ms.appendChild(o) })
  const es = el('select'); es.setAttribute('aria-label', t('settings.expiry'))
  ;[[t('settings.never'), ''], [t('settings.expDays', { n: 30 }), '30'], [t('settings.expDays', { n: 90 }), '90'], [t('settings.expDays', { n: 365 }), '365']].forEach(([label, v]) => { const o = el('option', null, label); o.value = v; es.appendChild(o) })
  const cb = el('button', null, t('common.create'))
  cb.onclick = e => {
    e.stopPropagation() // sync renderSettings below detaches e.target: without this the document outside-click closer hides setPop
    if (cb.disabled) return
    if (!kn.value.trim()) { settingsError(t('settings.needKeyName')); return }
    cb.disabled = true
    api('POST', '/api/keys', { name: kn.value.trim(), role: rs.value, mode: ms.value, expires_in_days: es.value ? +es.value : null })
      .then(d => { // no refetch: one POST per create, list updates locally (was POST+GET, 2 keys-bucket hits)
        lastKeySecret = d.key
        kn.value = ''
        apiKeys = [...(apiKeys || []), { id: d.id, name: d.name, prefix: d.prefix, role: d.role, mode: d.mode, expires_at: d.expires_at || '', last_used: '', created_at: '' }]
      })
      .catch(e => settingsError(e.message)).finally(() => { renderSettings(); showKeySecret() })
  }
  const cr = el('div', 'row keyCreateRow'); cr.append(kn, rs, ms, es, cb)
  const createSec = ksec(cr); createSec.classList.add('keyCreateSec'); keySecs.push(createSec)
  if (apiKeys === null) {
    keySecs.push(ksec(el('div', null, apiKeysLoading ? t('settings.loading') : '')))
    if (!apiKeysLoading) loadKeys()
  } else if (!apiKeys.length) keySecs.push(ksec(el('div', null, t('settings.noKeys'))))
  else {
    const rows = apiKeys.map(k => {
      const r = el('div', 'row wrap')
      r.style.flexWrap = 'nowrap'; r.style.alignItems = 'center' // button centered across both text lines
      const left = el('div')
      left.style.flex = '1'; left.style.minWidth = '0'; left.style.display = 'flex'; left.style.flexDirection = 'column'
      const nm = el('span', null, k.name)
      nm.style.fontWeight = '650'; nm.style.fontSize = '13.5px'
      nm.style.overflow = 'hidden'; nm.style.textOverflow = 'ellipsis'; nm.style.whiteSpace = 'nowrap'
      nm.title = k.name
      const rb = el('button', 'btnSecondary', t('settings.revokeKey'))
      rb.style.flex = 'none'
      rb.onclick = () => {
        if (rb.disabled) return; rb.disabled = true
        api('DELETE', '/api/keys/' + encodeURIComponent(k.id))
          .then(() => { apiKeys = (apiKeys || []).filter(x => x.id !== k.id)
            if (lastKeySecret) lastKeySecret = '' }) // revoked secret is dead: forget it
          .catch(e => settingsError(e.message)).finally(() => renderSettings())
      }
      const sub = el('div', 'val')
      sub.style.display = 'flex'; sub.style.flexWrap = 'wrap'; sub.style.gap = '6px'; sub.style.alignItems = 'center'
      sub.style.fontSize = '12px'; sub.style.minWidth = '0'; sub.style.overflowWrap = 'anywhere'; sub.style.textAlign = 'left'
      const pc = keyHint(k)
      pc.style.fontSize = '11.5px'; pc.style.overflowWrap = 'anywhere'; pc.style.minWidth = '0'
      pc.title = k.prefix ? `tpe_${k.prefix}…` : ''
      const rsel = el('select', 'keyRoleSel') // role editable in place: PATCH keeps the secret alive
      ;[['editor', t('common.roleEditor')], ['reviewer', t('settings.roleReviewer')]].forEach(([v, lab]) => {
        const o = el('option', null, lab); o.value = v; if (v === k.role) o.selected = true; rsel.appendChild(o)
      })
      rsel.setAttribute('aria-label', t('settings.roleForKey', { name: k.name }))
      rsel.onchange = () => {
        const role = rsel.value
        if (role === k.role) return
        rsel.disabled = true
        api('PATCH', '/api/keys/' + encodeURIComponent(k.id), { role })
          .then(d => { k.role = d.role || role; toast(t('settings.roleChanged')) })
          .catch(e => { rsel.value = k.role; settingsError(e.message) })
          .finally(() => { rsel.disabled = false })
      }
      const msel = el('select', 'keyModeSel') // mode editable in place like the role
      ;[['auto', t('settings.modeAuto')], ['direct', t('settings.modeDirect')], ['propose', t('settings.modePropose')]].forEach(([v, lab]) => {
        const o = el('option', null, lab); o.value = v; if (v === (k.mode || 'auto')) o.selected = true; msel.appendChild(o)
      })
      msel.setAttribute('aria-label', t('settings.modeForKey', { name: k.name })); msel.title = t('settings.keyMode')
      msel.onchange = () => {
        const mode = msel.value
        msel.disabled = true
        api('PATCH', '/api/keys/' + encodeURIComponent(k.id), { mode })
          .then(d => { k.mode = d.mode || mode; toast(t('settings.modeChanged')) })
          .catch(e => { msel.value = k.mode || 'auto'; settingsError(e.message) })
          .finally(() => { msel.disabled = false })
      }
      const eS = el('span', 'val', t('settings.expires', { date: shortD(k.expires_at) })); eS.title = k.expires_at || t('settings.never')
      eS.style.fontSize = '12px'
      sub.append(pc, eS, rsel, msel)
      left.append(nm, sub)
      r.append(left, rb)
      return r
    })
    keySecs.push(ksec(...rows))
  }
  put('api', grp(t('settings.keys'), ...keySecs)) // keep key creation and the key list together
  const sSecs = []
  if (sessList === null) {
    sSecs.push(sec(el('div', null, sessLoading ? t('settings.loading') : '')))
    if (!sessLoading) loadSess()
  } else if (!sessList.length) sSecs.push(sec(el('div', null, t('settings.noSessions'))))
  else {
    const srows = sessList.map(s => {
      const r = el('div', 'row wrap sessRow')
      const left = el('div', 'sessLeft')
      const nm = el('span', 'sessName', s.current ? t('settings.thisDevice') : String(s.id || '').slice(0, 8))
      if (!s.current) nm.title = s.id
      const ex = el('span', 'val', t('settings.expires', { date: shortD(s.expires) }))
      ex.title = s.expires || t('settings.never')
      left.append(nm, ex)
      const rb = el('button', 'btnSecondary', t('settings.endSession'))
      rb.setAttribute('aria-label', t('settings.endSession') + ': ' + (s.current ? t('settings.thisDevice') : String(s.id || '').slice(0, 8)))
      rb.onclick = () => {
        if (rb.disabled) return; rb.disabled = true
        api('DELETE', '/api/sessions/' + encodeURIComponent(s.id))
          .then(() => { if (s.current) location.reload(); sessList = (sessList || []).filter(x => x.id !== s.id) })
          .catch(e => settingsError(e.message)).finally(() => renderSettings())
      }
      r.append(left, rb)
      return r
    })
    sSecs.push(sec(...srows))
  }
  put('sessions', grp(t('settings.sessions'), ...sSecs))
  const dr = el('div', 'accountForm accountDeleteForm')
  const dpw = keepField(el('input'), 'deleteCurrentPassword'); dpw.type = 'password'; dpw.name = 'current-password-delete-account'; dpw.autocomplete = 'current-password'; dpw.placeholder = t('settings.currentPasswordPlaceholder'); dpw.setAttribute('aria-label', t('settings.confirmWithPassword'))
  const deletePasswordField = el('label', 'accountField'); deletePasswordField.append(el('span', null, t('settings.confirmWithPassword')), dpw)
  const db = el('button', 'btnDanger', t('settings.deleteAccount'))
  db.onclick = async () => {
    if (db.disabled) return
    if (hasPassword && !dpw.value) { settingsError(t('settings.needPwDel')); return }
    if (!await ask(t('settings.delAccount'), { noInput: true, ok: t('common.delete'), danger: true })) return
    if (!await ask(t('settings.delSure'), { ph: 'DELETE' }).then(v => v === 'DELETE')) return
    db.disabled = true
    api('POST', '/api/me/delete', { password: hasPassword ? dpw.value : '', confirm: 'DELETE' })
      .then(() => { location.reload() })
      .catch(e => settingsError(e.message)).finally(() => db.disabled = false)
  }
  if (hasPassword) dr.append(deletePasswordField, db); else dr.append(db)
  put('account', grp(t('settings.deleteAccount'), sec(dr)))
  content.scrollTop = keepScroll
}
window.openSettingsCategory = id => {
  if (!SETTINGS_CATS.some(([cat]) => cat === id)) return
  settingsCategory = id
  // Deferred: the opening click may still bubble to the outside-click closer, which would hide the fresh popover.
  setTimeout(() => {
    if ($('setPop').style.display === 'none') showPop('setPop')
    renderSettings()
    try { $('setPop').querySelector('.setNavItem.active')?.focus() } catch (e) {}
  }, 0)
}
new MutationObserver(() => {
  const open = $('setPop').style.display !== 'none'
  document.body.classList.toggle('settings-open', open)
  if (!open) {
    try { scResetRecordingState() } catch (e) {}
    try { scQuery = ''; scQueryIsCombo = false } catch (e) {} // next open starts with the full shortcut list
    $('setPop').querySelectorAll('input[type="password"]').forEach(input => { input.value = '' })
  }
}).observe($('setPop'), { attributes: true, attributeFilter: ['style'] })
$('avPick').onclick = e => e.stopPropagation()
$('avPick').onchange = () => { // square, AV_SIZE, center
  const f = $('avPick').files[0]; $('avPick').value = ''
  if (!f) return
  const im = new Image()
  im.onload = () => {
    const c = document.createElement('canvas'); c.width = c.height = AV_SIZE
    const s = Math.min(im.width, im.height)
    c.getContext('2d').drawImage(im, (im.width - s) / 2, (im.height - s) / 2, s, s, 0, 0, AV_SIZE, AV_SIZE)
    api('POST', '/api/me/avatar', { img: c.toDataURL('image/png') })
      .then(() => { avatarV++; paintMe(); renderPeers(); renderSettings() })
      .catch(e => settingsError(e.message))
    URL.revokeObjectURL(im.src)
  }
  im.onerror = () => URL.revokeObjectURL(im.src)
  im.src = URL.createObjectURL(f)
}
// drag pane border (browser remembers pos)
function updSplitAria() { try { $('split').setAttribute('aria-valuenow', Math.round(parseFloat($('leftCol').style.width) || 50)) } catch (e) {} }
function updSideAria() { try { $('sideSplit').setAttribute('aria-valuenow', Math.round(sideEl.getBoundingClientRect().width)) } catch (e) {} }
function updVsplitAria() { try { $('vsplit').setAttribute('aria-valuenow', Math.round($('leftCol').getBoundingClientRect().height)) } catch (e) {} }
try { const w = +localStorage.getItem('typst_split'); if (w >= SPLIT_MIN && w <= SPLIT_MAX) $('leftCol').style.width = clampSplit(w) + '%' } catch (e) {}
$('split').addEventListener('mousedown', e => {
  e.preventDefault()
  const r0 = $('mid').getBoundingClientRect(), x0 = e.clientX, w0 = $('leftCol').getBoundingClientRect().width
  $('split').classList.add('drag')
  const mv = ev => {
    $('leftCol').style.width = clampSplit((w0 + ev.clientX - x0) / r0.width * 100) + '%'
    updSplitAria()
  }
  const up = () => {
    removeEventListener('mousemove', mv); removeEventListener('mouseup', up)
    $('split').classList.remove('drag')
    lsSet('typst_split', parseFloat($('leftCol').style.width))
  }
  addEventListener('mousemove', mv); addEventListener('mouseup', up)
})
$('split').addEventListener('pointerdown', e => {
  if (e.pointerType === 'mouse') return
  $('split').dispatchEvent(new MouseEvent('mousedown', { clientX: e.clientX }))
})
$('navToggle').onclick = () => {
  document.body.classList.toggle('noside'); updScrim()
  const open = !document.body.classList.contains('noside')
  $('navToggle').setAttribute('aria-pressed', String(open)) // pressed = sidebar open, not hidden
  $('navToggle').setAttribute('aria-expanded', String(open)) // disclose pattern for SR
  if (open && matchMedia('(max-width:720px)').matches) { // drawer opened: focus first control
    const f = $('side').querySelector('input,button')
    if (f) setTimeout(() => { try { f.focus() } catch (e) {} }, 60)
  }
}
function updScrim() {
  const mob = matchMedia('(max-width:720px)').matches
  $('scrim').style.display = mob && !document.body.classList.contains('noside') ? '' : 'none'
}
$('scrim').onclick = () => { document.body.classList.add('noside'); updScrim(); $('navToggle').setAttribute('aria-pressed', 'false'); $('navToggle').setAttribute('aria-expanded', 'false'); $('navToggle').focus() } // drawer closed: focus back to toggle
function autoCloseDrawer() { if (matchMedia('(max-width:720px)').matches) { document.body.classList.add('noside'); updScrim() } }
const sideEl = $('side') // drag sidebar width, 150-420px
try { const sw = +localStorage.getItem('typst_side'); if (sw >= SIDE_MIN && sw <= SIDE_MAX) sideEl.style.width = sw + 'px' } catch (e) {}
$('sideSplit').addEventListener('mousedown', e => {
  e.preventDefault()
  document.body.classList.add('sideDrag')
  $('sideSplit').classList.add('drag')
  const x0 = e.clientX, w0 = sideEl.getBoundingClientRect().width
  const mv = ev => { sideEl.style.width = Math.max(SIDE_MIN, Math.min(SIDE_MAX, w0 + ev.clientX - x0)) + 'px'; updSideAria() }
  const up = () => {
    removeEventListener('mousemove', mv); removeEventListener('mouseup', up)
    $('sideSplit').classList.remove('drag')
    document.body.classList.remove('sideDrag')
    lsSet('typst_side', parseFloat(sideEl.style.width))
  }
  addEventListener('mousemove', mv); addEventListener('mouseup', up)
})
function vStart(y0) { // mobile: drag editor height (mouse + touch)
  const r = $('mid').getBoundingClientRect(), h0 = $('leftCol').getBoundingClientRect().height
  const set = dy => {
    $('leftCol').style.flex = 'none'
    $('leftCol').style.height = Math.max(120, Math.min(r.height - 120, h0 + dy)) + 'px'
    updVsplitAria()
  }
  const mm = e => set(e.clientY - y0), tm = e => set(e.touches[0].clientY - y0)
  const up = () => {
    removeEventListener('mousemove', mm); removeEventListener('mouseup', up)
    removeEventListener('touchmove', tm); removeEventListener('touchend', up)
  }
  addEventListener('mousemove', mm); addEventListener('mouseup', up)
  addEventListener('touchmove', tm, { passive: true }); addEventListener('touchend', up)
}
$('vsplit').addEventListener('mousedown', e => { e.preventDefault(); vStart(e.clientY) })
$('vsplit').addEventListener('touchstart', e => vStart(e.touches[0].clientY), { passive: true })
kb($('sideSplit'), () => { document.body.classList.toggle('noside'); updScrim() }) // keyboard: like menu
$('sideSplit').addEventListener('keydown', e => { // arrows: resize sidebar width
  const cur = Math.round(sideEl.getBoundingClientRect().width)
  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
    e.preventDefault()
    sideEl.style.width = Math.max(SIDE_MIN, Math.min(SIDE_MAX, cur + (e.key === 'ArrowRight' ? 10 : -10))) + 'px'
    updSideAria()
    lsSet('typst_side', parseFloat(sideEl.style.width))
  }
})
kb($('split'), () => { $('leftCol').style.width = '50%'; updSplitAria(); lsSet('typst_split', 50) }) // keyboard: reset width
$('split').addEventListener('keydown', e => {
  const cur = parseFloat($('leftCol').style.width) || 50
  if (e.key === 'ArrowLeft') { $('leftCol').style.width = clampSplit(cur - 2) + '%'; updSplitAria(); lsSet('typst_split', parseFloat($('leftCol').style.width)); e.preventDefault() }
  if (e.key === 'ArrowRight') { $('leftCol').style.width = clampSplit(cur + 2) + '%'; updSplitAria(); lsSet('typst_split', parseFloat($('leftCol').style.width)); e.preventDefault() }
})
kb($('vsplit'), () => { $('leftCol').style.height = ''; $('leftCol').style.flex = ''; updVsplitAria() }) // keyboard: reset height
$('vsplit').addEventListener('keydown', e => { // arrows: resize editor height
  if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return
  e.preventDefault()
  const r = $('mid').getBoundingClientRect(), h = $('leftCol').getBoundingClientRect().height
  $('leftCol').style.flex = 'none'
  $('leftCol').style.height = Math.max(120, Math.min(r.height - 120, h + (e.key === 'ArrowDown' ? 20 : -20))) + 'px'
  updVsplitAria()
})
matchMedia('(max-width:720px)').addEventListener('change', m => { // back on desktop: clear fixed height
  if (!m.matches) { $('leftCol').style.height = ''; $('leftCol').style.flex = ''; document.body.classList.remove('noside') }
  else document.body.classList.add('noside')
  updScrim()
})
function setView(m) { // 3-way segment: editor | split | read (not 1 read-mode button)
  document.body.classList.toggle('read', m === 'read')
  document.body.classList.toggle('editonly', m === 'editor')
  for (const [id, on] of [['vEdit', m === 'editor'], ['vSplit', m === 'split'], ['vRead', m === 'read']]) {
    $(id).classList.toggle('on', on)
    $(id).setAttribute('aria-pressed', on)
  }
  $('leftCol').style.height = ''; $('leftCol').style.flex = '' // mobile drag height must not survive view switch
  updVsplitAria()
  if (m !== 'editor') scrollApplyPreview() // preview was hidden on open: apply the saved spot now
  if (m !== 'read') scrollApplyEditor() // editor was hidden on open: same for its saved line
  if (popAnchor != null) movePop()
}
$('vEdit').onclick = () => setView('editor')
$('vSplit').onclick = () => setView('split')
$('vRead').onclick = () => setView('read')
// editor font + preview zoom (edSize/pvZoom declared above)
function setEd(v) { edSize = Math.max(ED_MIN, Math.min(ED_MAX, Math.round(v))); applyEd(); saveSet() }
function stepEd(d) { setEd(edSize + d) }
window.editorFont = { min: ED_MIN, max: ED_MAX, step: ED_STEP, get: () => edSize, set: setEd } // View menu slider mirrors the Settings row
function setPv(v) { // explicit % leaves fit modes, slots follow at once (not via the zoomV observer only)
  if (pvZoomMode !== 'pct') pvModeSet('pct')
  pvZoom = Math.max(PV_MIN, Math.min(PV_MAX, Math.round(v)))
  applyPv(); saveSet(); pvRelayout()
}
function stepPv(d) { setPv(pvZoom + d) }
window.previewZoom = { min: PV_MIN, max: PV_MAX, step: PV_SLIDER_STEP, get: () => pvZoom, set: setPv } // View > Preview options slider mirrors the Settings row
function applyEd() {
  const lh = Math.round(edSize * 1.5)
  $('cmWrap').style.setProperty('--ed', edSize + 'px')
  $('cmWrap').style.setProperty('--lh', lh + 'px')
  $('editWrap').style.setProperty('--lh', lh + 'px')
  paintSteps()
  if (popAnchor != null) movePop()
}
function applyPv() {
  const z = $('zoomV'); if (z) z.textContent = pvZoom + '%'
  document.querySelectorAll('#preview canvas').forEach(sizeCanvas)
  paintSteps()
}
function paintSteps() { // dead clicks give no feedback: disable at the bounds (settings popover shows the value, toolbar has no readout)
  try {
    const fM = $('fMinus'), fP = $('fPlus'), zM = $('zMinus'), zP = $('zPlus')
    if (fM) fM.disabled = edSize <= ED_MIN
    if (fP) fP.disabled = edSize >= ED_MAX
    if (zM) zM.disabled = pvZoom <= PV_MIN
    if (zP) zP.disabled = pvZoom >= PV_MAX
  } catch (e) {}
}
let syncOn = true, syncT = 0, syncPage = 0, syncMiss = false, syncView = -1 // click sync preview->editor, last hit page, scroll-follow pos (-1: use cursor)
let syncEdOff = 0 // preview click point relative to the viewport center: scroll-follow starts where the reader clicked
let syncEdX = -1 // clicked column as a share of the page width: two-column previews follow that column, not the gutter
let syncEdMiss = false // follow hit a page whose text index was still being built: retry once it is done
let followAll = true // true: cursor/scroll/jumps move the preview; false: only a click syncs
try { const s = localStorage.getItem('typst_sync'); if (s === '0' || s === '1') syncOn = s === '1' } catch (e) {} // F25: follow persisted (string compare: +null === 0 would flip the default)
followAll = syncOn // before the split one flag switched both: a sync-off user stays off
try { const s = localStorage.getItem('typst_follow_all'); if (s === '0' || s === '1') followAll = s === '1' } catch (e) {}
function applySyncBtn() { const b = $('syncBtn'); if (!b) return; b.classList.toggle('on', syncOn); b.setAttribute('aria-pressed', syncOn) } // F25: button mirrors persisted state
function applyFollowBtn() { const b = $('followBtn'); if (!b) return; b.classList.toggle('on', followAll); b.setAttribute('aria-pressed', followAll) }
let syncSkip = false // our own jump selects a line: that selection is not a cursor move
let cmSelT = 0 // last cursor move: an editor scroll right after it is cursor-follow, not a reader scroll
function queueSyncPv(at) { // throttle: continuous cursor/scroll movement still updates the preview (no wait-for-idle)
  if (syncSkip) return
  if (!followAll) return
  syncView = Number.isFinite(at) ? at : -1
  if (syncT) return // a run is already scheduled and reads the latest position
  syncT = setTimeout(() => { syncT = 0; syncToPv() }, SYNC_MS)
}
try { // wheel over the editor: the preview follows what is on screen, not only the cursor
  const sc = cm.scrollDOM
  sc.addEventListener('wheel', () => smoothStop(sc), { passive: true })
  sc.addEventListener('scroll', () => {
    if (!followAll || syncSkip) return
    if (smoothWrote(sc)) return // our own glide/follow wrote it
    if (Date.now() - cmSelT < 150) return // a cursor move already synced the cursor
    smoothStop(sc) // scrollbar drag/touch/page key: the reader owns the editor view
    syncEdMiss = false // a pending follow from the preview must not pull the editor back
    try { queueSyncPv(cm.elementAtHeight(sc.scrollTop + sc.clientHeight / 2).from) } catch (e) {}
  }, { passive: true })
} catch (e) {}
let syncEdT = 0
function syncEdTab() { return !!activeFile && !window.changeSession && /.typ$/i.test(activeFile) && !isTplKey(activeFile) } // an included chapter is on the page too: its own text can follow the reading point
function queueSyncEd() { // preview scroll -> editor view: throttled, never moves the cursor
  if (!followAll || !docId || tplName || (activeFile && !syncEdTab())) return
  if (syncEdT) return
  syncEdT = setTimeout(() => { syncEdT = 0; syncToEd() }, SYNC_MS)
}
function syncToEd() {
  const fileTab = syncEdTab()
  if (!followAll || !docId || tplName || (activeFile && !fileTab)) return
  const pv = $('preview')
  if (!pv.clientHeight || document.body.classList.contains('editonly')) return
  const pi = pvViewPage(pv, syncEdOff), slot = pi >= 0 ? pv.querySelectorAll('.pvPage')[pi] : null
  if (!slot) return
  const pr = pv.getBoundingClientRect(), sr = slot.getBoundingClientRect()
  const frac = Math.max(0, Math.min(1, (pr.top + pv.clientHeight / 2 + syncEdOff - sr.top) / (sr.height || 1)))
  const items = pvTexts[pi] || []
  if (!items.length) { // page without text (full-page image, scan): section + page ratio still points at a line
    syncEdMiss = !pvTextDone[pi]
    if (syncEdMiss || fileTab) return // a file tab has no page ratio of its own
    const vh = (pvPageSize && pvPageSize.height) || 1
    const line = pvPageHint(pi, cm.state.doc.lines || 1, pvTexts.length, pvSecAtY(pi, frac * vh), frac)
    smoothFollow(cm.scrollDOM, cmTop(posOfLine(getT(), line)))
    return
  }
  syncEdMiss = false
  const vh = items[0].vh || 1, vw = items[0].vw || 1
  const at = pvSecAtY(pi, frac * vh), line = pvPageHint(pi, cm.state.doc.lines || 1, pvTexts.length, at, frac)
  const rx = (syncEdX >= 0 ? syncEdX : 0.5) * vw, ry = frac * vh
  const row = it => Math.round(Math.max(0, Math.abs(it.y - ry) - (it.h || 10) / 2) / 4) // the line at the reading point first: a short left-aligned line must not lose to the line above that spans the middle
  const near = items.filter(it => /\p{L}/u.test(it.s || '')).map(it => ({ it, d: pvItemDist(it, rx, ry, 1, 1) })).sort((a, b) => row(a.it) - row(b.it) || a.d - b.d) // no running header/footer, no needle-less lone letters
    .filter(({ it }) => it.y >= vh * 0.05 && it.y <= vh * 0.95
      && (syncText(it.s || '').length >= 4 || pvBlockLines(items, it).length > 1)).slice(0, 3)
  for (const { it } of near) { // real text under the reading point: exact, even inside large figures
    const pos = pvHerePos(pvClickNeedles(items, it, 0), line, pi, it, true) // reading follow: no guess from a lone shared word, the line estimate is better than a far-away twin
    if (pos < 0) continue
    const ln = cm.state.doc.lineAt(pos).number, sec = pvSecAtLine(ln)
    if (!sec ? (fileTab || pi === 0 || !pvSections().length) : sec.page <= pi && pi <= sec.endPage) { smoothFollow(cm.scrollDOM, cmTop(pos)); return } // no heading with a page at all: any page's text may name its line // another page's text (header, repeated title): not this spot
  }
  if (fileTab && !at.sec) return // main-document text at the reading point: the chapter tab stays where it is
  smoothFollow(cm.scrollDOM, cmTop(posOfLine(getT(), line)))
}
try { $('preview').addEventListener('wheel', () => { // a reader wheel wins over a pending sync retry
  if (syncT) { clearTimeout(syncT); syncT = 0 } // no pending cursor sync may yank the preview back
  syncMiss = false // nor the retry from a render that started before the reader scrolled
}, { passive: true }) } catch (e) {}
try { $('preview').addEventListener('scroll', () => { // reader scroll: the editor view moves along
  const pv = $('preview')
  if (Math.abs(pv.scrollTop - pvSelfTop) < 2) return // this app wrote it: follow or a jump, not the reader
  smoothStop(pv) // scrollbar drag/touch/keyboard: the reader wins over a running animation
  if (syncT) { clearTimeout(syncT); syncT = 0 } // the reader took over: no pending cursor sync may yank the preview back
  syncMiss = false // nor the retry from a render that started before the reader scrolled
  queueSyncEd()
}, { passive: true }) } catch (e) {}
function pvPageHint(pi, total, n, at, frac) { // click page -> source line: section window first, then layout ratio
  const f0 = typeof frac === 'number' && isFinite(frac) ? Math.max(0, Math.min(1, frac)) : 0.5
  if (at && at.sec) {
    const a = at.sec.line, b = at.next ? at.next.line - 1 : total
    const span = at.next ? Math.max(1, at.next.page - at.sec.page) : Math.max(1, n - at.sec.page)
    const f = Math.max(0, Math.min(1, ((pi - at.sec.page) + f0) / Math.max(1, span))) // the page of the next heading, above it: still this section, never past its last line
    return Math.max(1, Math.min(total, Math.round(a + f * Math.max(0, b - a))))
  }
  if (at && at.next) return Math.max(1, Math.min(total, at.next.line)) // above the first heading: that heading is the honest anchor
  return Math.max(1, Math.min(total, Math.round((pi + f0) / Math.max(1, n) * total) + 1))
}
function pvCanvasList() { // virtual slots first, fallback bare canvases
  const pv = $('preview')
  const sl = pv.querySelectorAll('.pvPage canvas')
  if (sl.length) return [...sl]
  return [...pv.querySelectorAll('canvas')]
}
function pvPosIn(txt, s, off, hint, strict) { // exact needle first, then its words across source line breaks and markup; strict: a lone shared word is no match
  const seen = pvViewPos(txt, s, off, hint) // visible text only: URLs, markup and raw pipes never capture the click
  if (seen >= 0) return seen
  const at = locateNear(txt, s, hint)
  if (at >= 0) return at + off
  const heard = pvViewWords(txt, s, off, hint, strict ? 2 : 0) // the clicked word with its neighbours: exact letter, even when the run differs
  if (heard >= 0) return heard
  const words = pvNormWords(s)
  if (!words.length || (strict && words.length < 3)) return -1 // two words matched across raw code ("1." of a numbering string + the heading below) prove nothing
  const o = Math.max(0, Math.min(off, s.length))
  let wi = words.length - 1, k = words[wi].text.length // past the last word: its end
  for (let i = 0; i < words.length; i++) {
    if (o <= words[i].end) { wi = i; k = words[i].map.filter(r => r < o).length; break } // normalized index under the click
  }
  const p = syncNeedleAt(txt, s, hint, wi)
  if (p < 0) return -1
  const word = (txt.slice(p).match(/^[\p{L}\p{N}\p{M}]+/u) || [''])[0]
  const nm = syncNormMap(word) // source word: NFD (a+¨) and ligatures have their own lengths
  return p + (k < nm.map.length ? nm.map[k] : word.length) // the same letter inside the matched source word
}
function pvNormWords(s) { // syncText words with their raw span: "don’t" -> don@0-3, t@4-5
  const { s: n, map } = syncNormMap(s)
  const out = []
  for (const m of n.matchAll(/[\p{L}\p{N}]+/gu)) {
    const at = m.index, end = at + m[0].length
    out.push({ start: map[at], end: end < n.length ? map[end] : s.length, text: m[0], map: map.slice(at, end) })
  }
  return out
}
function pvHerePos(needles, hint, pi, anchor, strict) { // source position of the best needle in the current file; -1: none; strict: no lone-word guess
  const list = (needles || []).filter(n => n && n.s && n.s.trim().length >= 2)
  const cur = activeFile || ''
  if (!cur && anchor) { // heading clicks: the PDF line's own height decides between repeated titles
    const lines = getT().split('\n'), matches = []
    let pos = 0
    const bare = nd => { const s = nd.s.trim(), k = pvNumCut(s); return { s: s.slice(k), off: Math.max(0, (nd.off || 0) - k) } } // "1.2 Results" on paper, "= Results" in the source
    lines.forEach((text, i) => {
      const nd = /^\s*=+\s/.test(text) ? list.map(bare).find(n => syncPlain(n.s) && syncPlain(text).includes(syncPlain(n.s))) : null
      if (nd) {
        const s = nd.s, off = Math.max(0, Math.min(nd.off, s.length))
        const hit = syncAnchor(lines, i + 1, pvTexts, pvSecAtLine(i + 1))
        if (hit && hit.pi === pi && hit.items.includes(anchor)) {
          const at = text.indexOf(s), seen = at >= 0 ? at + off : pvViewPos(text, s, off, 1) // markup inside the title ("Results *Bold* Part"): the visible letters keep the clicked column
          matches.push({ pos: seen >= 0 ? pos + seen : pos + (text.match(/^\s*=+\s*/) || [''])[0].length, distance: Math.abs(hit.it.y - anchor.y) })
        }
      }
      pos += text.length + 1
    })
    matches.sort((a, b) => a.distance - b.distance)
    if (matches.length && (matches.length === 1 || matches[0].distance < matches[1].distance)) return matches[0].pos
  }
  const total = getT()
  for (const nd of list) { // needles are ordered by confidence: paragraph context first, then the clicked run
    const s = nd.s.trim(), off = Math.max(0, Math.min(nd.off || 0, s.length))
    let at = pvViewPos(total, s, off, hint) // visible words: markup and URLs never capture the click
    if (at < 0) { const p = locateNear(total, s, hint); if (p >= 0) at = p + off }
    if (at < 0) at = pvViewWords(total, s, off, hint, strict ? 2 : 0)
    if (at < 0) at = pvPosIn(total, s, off, hint, strict) // last resort: the old word matcher
    if (at >= 0) return at
  }
  return -1
}
function pvJumpHere(needles, hint, pi, anchor, strict) { // current file: exact word first, then the clicked word of a reflowed run
  const pos = pvHerePos(needles, hint, pi, anchor, strict)
  if (pos < 0) return false
  syncPage = pi
  jumpPos(pos)
  return true
}
async function pvJumpBest(needles, hint, pi, anchor, anyWord) { // current file, else the unique owner, else stay; anyWord: no clicked letter (link destination), any unique word of the text decides
  const list = (needles || []).filter(n => n && n.s && n.s.trim().length >= 2)
  if (!list.length) return false
  if (pvJumpHere(list, hint, pi, anchor, true)) return true // strong evidence in this file first, then in the others, a lone shared word last
  const cur = activeFile || ''
  const total = cm.state.doc.lines || 1
  for (const nd of list) {
    const s = nd.s.trim(), off = Math.max(0, Math.min(nd.off || 0, s.length))
    let srcs = []
    try { srcs = pvSrcList() } catch (e) { srcs = [] }
    let found = null, dup = false
    for (const src of srcs) {
      if (!src || src.key === cur) continue
      const txt = src.text || ''
      const lines = txt ? txt.split('\n').length : 1
      const h2 = Math.max(1, Math.min(lines, Math.round(hint / Math.max(1, total) * lines)))
      const at = pvPosIn(txt, s, off, h2, true)
      if (at >= 0) {
        if (found) { dup = true; break }
        found = { key: src.key }
      }
    }
    if (found && !dup) {
      syncPage = pi
      const doc = docId, epoch = openN
      try { if (!await switchTab(found.key)) return false } catch (e) { return false }
      if (doc !== docId || epoch !== openN || activeFile !== found.key) return false
      const t = getT(), lines = cm.state.doc.lines || 1
      const h2 = Math.max(1, Math.min(lines, Math.round(hint / Math.max(1, total) * lines)))
      const at = pvPosIn(t, s, off, h2, true)
      if (at >= 0) { jumpPos(at); return true }
    }
  }
  const one = pvUniqueWord(list[0]) || (anyWord ? pvUniqueAny(list[0]) : null) // a word that exists once in all sources: a .bib field, a name in another chapter
  if (one) {
    if (one.key === cur) { syncPage = pi; jumpPos(one.at); return true }
    const doc = docId, epoch = openN
    try { if (!await switchTab(one.key)) return false } catch (e) { return false }
    if (doc !== docId || epoch !== openN || (activeFile || '') !== one.key) return false
    const again = pvUniqueWord(list[0]) || (anyWord ? pvUniqueAny(list[0]) : null)
    if (again && again.key === one.key) { syncPage = pi; jumpPos(again.at); return true }
    return false
  }
  if (pvJumpHere(list, hint, pi, anchor)) return true // nothing strong anywhere: the clicked word in this file is still the honest guess
  const code = pvCodeWord(getT(), list[0], hint) // text a function, loop or string builds: the call site or definition that holds the word
  if (code < 0) return false
  syncPage = pi
  jumpPos(code)
  return true
}
function pvClickedWord(nd) { // needle -> the normalized word under its caret, with the letter index inside it
  const nw = pvNormCaret(String(nd && nd.s || '').trim()), k = pvCaretIndex(nw, (nd && nd.off) || 0)
  for (const m of nw.s.matchAll(/[\p{L}\p{N}]+/gu)) if (k <= m.index + m[0].length) return { w: m[0], k: Math.max(0, Math.min(m[0].length - 1, k - m.index)) }
  return null
}
function pvUniqueWord(nd) { // the clicked word, when it occurs exactly once in the visible text of all sources
  const cw = pvClickedWord(nd)
  if (!cw || cw.w.length < 4 || SRC_CJK.test(cw.w)) return null
  let hit = null
  let srcs = []
  try { srcs = pvSrcList() } catch (e) { return null }
  for (const src of srcs) {
    if (!src || !src.text) continue
    for (const w of srcViewWords(srcViewOf(src.text))) {
      if (w.w !== cw.w) continue
      if (hit) return null
      hit = { key: src.key || '', at: w.map[Math.min(cw.k, w.map.length - 1)] }
    }
  }
  return hit
}
function pvUniqueAny(nd) { // the first word of the needle that is unique across all sources (a bibliography entry: title, publisher, year)
  const s = String(nd && nd.s || '').trim()
  for (const m of s.matchAll(/[\p{L}\p{N}]{4,}/gu)) {
    const hit = pvUniqueWord({ s, off: m.index })
    if (hit) return hit
  }
  return null
}
function pvCodeWord(txt, nd, hint) { // the clicked word in code or a string of this file (comments excluded), nearest to the hint line
  const cw = pvClickedWord(nd)
  if (!cw || cw.w.length < 3) return -1
  const mask = srcMask(txt), { s, map } = syncNormMap(mask), hp = posOfLine(txt, hint)
  let best = -1, bd = Infinity, p = -1
  while ((p = s.indexOf(cw.w, p + 1)) >= 0) {
    if (pvWordChar(s[p - 1]) || pvWordChar(s[p + cw.w.length])) continue
    const at = map[p], d = Math.abs(at - hp)
    if (d < bd) { bd = d; best = map[p + cw.k] }
  }
  return best
}
function pvMainText() { return activeFile ? shadow : getT() } // the document text, also while a text tab is open
function pvFileAnchor(key, main) { // main line where a text file enters the page (include first, import as weak hint)
  if (!key) return 0
  const want = tabName(key).replace(/^\.?\//, '').replace(/\.typ$/i, '')
  const mask = srcMask(main).split('\n')
  const base = want.split('/').pop()
  let weak = 0, loose = 0 // loose: same file name in another folder, only used when no full path matches anywhere
  for (let i = 0; i < mask.length; i++) {
    const m = mask[i].match(/(?:^|[#=({,;]|\blet\s+\w+\s*=)\s*(include|import)\s*\(?\s*(?:<([^>]+)>|"([^"]+)"|([^\s:,)]+))/) // #include "a.typ", #include("a.typ"), #let x = include "a.typ", #{ include "a.typ" }
    if (!m) continue
    const path = String(m[2] || m[3] || m[4] || '').replace(/^\.?\//, '').replace(/\.typ$/i, '')
    if (path === want) { if (m[1] === 'include') return i + 1; if (!weak) weak = i + 1 }
    else if (path.split('/').pop() === base && !loose) loose = m[1] === 'include' ? i + 1 : 0
  }
  return weak || loose
}
function pvSrcImages() { // image() calls that can reach the page, in render order
  const main = pvMainText(), mainN = main.split('\n').length, out = []
  let loose = 0
  for (const src of pvSrcList()) {
    if (!src || !src.text) continue
    const base = src.key ? (pvFileAnchor(src.key, main) || mainN + (++loose) * 1e5) : 0, n = src.text.split('\n').length + 1
    for (const o of srcObjs(src.text).images) out.push({ key: src.key || '', line: o.line, order: src.key ? base + o.line / n : o.line }) // a file line is a fraction of its include line: units stay main-file lines
  }
  return out.sort((a, b) => a.order - b.order)
}
function pvImgHint(b) { // the text above the image names the page's own source line best
  const items = pvTexts[b.page] || [], y = (b.y0 + b.y1) / 2
  let best = null, bd = Infinity
  for (const it of items) {
    if (it.rot || !it.s.trim() || syncText(it.s).length < 4) continue
    const d = it.y <= y ? y - it.y : (it.y - y) * 4 // text below only when nothing is above
    if (d < bd) { bd = d; best = it }
  }
  return best
}
function pvTextSrcLine(items, it, pi) { // PDF text -> the line and file that own it (cross-file images need this)
  const needles = pvClickNeedles(items, it, 0)
  const total = cm.state.doc.lines || 1
  const hint = pvPageHint(pi, total, pvTexts.length, pvSecAtY(pi, it.y), it.y / (it.vh || 1))
  const cur = activeFile || '', list = pvSrcList().slice().sort((a, b) => (a.key === cur ? -1 : b.key === cur ? 1 : 0))
  for (const src of list) {
    const txt = src.text || '', n = txt.split('\n').length
    if (!txt) continue
    const h = Math.max(1, Math.min(n, Math.round(hint / Math.max(1, total) * n)))
    for (const nd of needles) {
      const at = pvPosIn(txt, nd.s.trim(), nd.off || 0, h)
      if (at >= 0) { const ln = txt.slice(0, at).split('\n').length; return { key: src.key || '', line: ln, order: src.key ? pvFileAnchor(src.key, pvMainText()) + ln / (n + 1) : ln } }
    }
  }
  return null
}
function pvImgMatch() { // PDF image boxes -> image() lines: the closest pair wins first, so a box without a source cannot take a real image's slot
  if (!pvImgs.some(p => p && p.length)) { pvImgMemo = null; return [] } // no picture on any page: no source scan, no pairing
  const sig = pvSrcSig(), total = cm.state.doc.lines || 1, memo = pvImgMemo
  if (memo && memo.sig === sig && memo.outline === pvOutlineGen && memo.shown === shownN && memo.active === (activeFile || '') && memo.total === total
    && pvImgSame(memo.imgs, pvImgs) && pvImgSame(memo.texts, pvTexts)) return memo.out // cursor follows reuse the pairing of the same screen
  const boxes = pvImgBoxes(), srcs = pvSrcImages(), out = [], hints = []
  if (boxes.length && srcs.length) {
    for (let bi = 0; bi < boxes.length; bi++) {
      const b = boxes[bi], y = b.y0 + b.h / 2
      const near = pvImgHint(b), own = near ? pvTextSrcLine(pvTexts[b.page] || [], near, b.page) : null
      hints.push(own ? own.order : pvPageHint(b.page, total, pvTexts.length, pvSecAtY(b.page, y), y / (b.vh || 1)))
    }
    const used = new Set(), heap = [], take = bi => {
      const si = pvImgNearest(srcs, hints[bi], used)
      if (si >= 0) pvImgHeapPush(heap, [Math.abs(srcs[si].order - hints[bi]), bi, si])
    }
    for (let bi = 0; bi < boxes.length; bi++) take(bi)
    while (heap.length) { // every box offers its nearest free source: the smallest offer is the next pair of the old full sort
      const [, bi, si] = pvImgHeapPop(heap)
      if (used.has(si)) { take(bi); continue }
      used.add(si)
      out.push({ ...boxes[bi], src: srcs[si] })
    }
    out.sort((a, b) => a.page - b.page || a.y0 - b.y0 || a.x0 - b.x0) // click lookup walks the page in reading order
  }
  pvImgMemo = { sig, outline: pvOutlineGen, shown: shownN, active: activeFile || '', total, imgs: pvImgs.slice(), texts: pvTexts.slice(), out }
  return out
}
function pvImgSame(a, b) { return a.length === b.length && a.every((v, i) => v === b[i]) } // page lists fill in over the render: identity per page, not just the outer array
let pvImgMemo = null // { sig, outline, shown, active, total, imgs, texts, out }
function pvImgCmp(a, b) { return a[0] - b[0] || a[1] - b[1] || a[2] - b[2] } // distance, box, source: exactly the old pair sort
function pvImgNearest(srcs, hint, used) { // closest free source to the page hint, ties in document order
  let lo = 0, hi = srcs.length
  while (lo < hi) { const mid = (lo + hi) >> 1; if (srcs[mid].order < hint) lo = mid + 1; else hi = mid }
  let l = lo - 1, r = lo, best = -1, bd = Infinity
  while (l >= 0 || r < srcs.length) {
    const dl = l >= 0 ? Math.abs(srcs[l].order - hint) : Infinity
    const dr = r < srcs.length ? Math.abs(srcs[r].order - hint) : Infinity
    if (Math.min(dl, dr) > bd) break
    if (dl <= dr) { if (!used.has(l) && (dl < bd || (dl === bd && l < best))) { bd = dl; best = l } l-- }
    if (dr <= dl) { if (!used.has(r) && (dr < bd || (dr === bd && r < best))) { bd = dr; best = r } r++ }
  }
  return best
}
function pvImgHeapPush(h, e) {
  h.push(e)
  let i = h.length - 1
  while (i > 0) {
    const p = (i - 1) >> 1
    if (pvImgCmp(h[p], e) <= 0) break
    h[i] = h[p]; i = p
  }
  h[i] = e
}
function pvImgHeapPop(h) {
  const top = h[0], last = h.pop()
  if (!h.length) return top
  let i = 0
  for (;;) {
    const l = i * 2 + 1, r = l + 1
    if (l >= h.length) break
    const c = r < h.length && pvImgCmp(h[r], h[l]) < 0 ? r : l
    if (pvImgCmp(last, h[c]) <= 0) break
    h[i] = h[c]; i = c
  }
  h[i] = last
  return top
}
function pvImgAt(pi, x, y, sx, sy) { // click inside an image box -> that image's source line
  for (const b of pvImgMatch()) {
    if (b.page === pi && x >= b.x0 * sx - 2 && x <= b.x1 * sx + 2 && y >= b.y0 * sy - 2 && y <= b.y1 * sy + 2) return b
  }
  return null
}
function pvImgLineHit(line) { // cursor on an image/figure line -> its rendered box
  const lines = getT().split('\n'), key = activeFile || ''
  const seen = srcViewLine(lines, line), words = seen != null && syncText(seen).length >= 4 // a caption line has its own words on paper: they anchor it, not the picture above
  let best = null, bd = Infinity
  for (const b of pvImgMatch()) {
    if ((b.src.key || '') !== key || (words && line !== b.src.line)) continue
    const from = pvFigureStart(lines, b.src.line) || b.src.line
    if (line < from || line > pvCallEnd(lines, from)) continue
    const d = Math.abs(line - b.src.line)
    if (d < bd) { bd = d; best = b }
  }
  return best
}
function pvMathNorm(s) { return String(s || '').normalize('NFKC').replace(/\s+/g, '') } // 𝑛 -> n, ligatures kept short
function pvMathLines(items) { // display math: math-font runs alone on their visual line, glyphs in reading order
  const isMath = it => !it.rot && it.fam && /math/i.test(it.fam) && String(it.s || '').trim()
  if (!items.some(isMath)) return []
  const eqNum = o => /^[(\[]?\s*(?:\d+|[A-Za-z]|[ivxlcdm]+)(?:[.\-–]\d+)*[a-z]?\s*[)\]]?$/.test(String(o.s || '').trim()) // "(1)", "(2.3a)": equation numbering in the body font
  const rest = items.filter(o => !o.rot && String(o.s || '').trim() && !isMath(o) && !eqNum(o)), rows = []
  for (const it of items.filter(isMath).sort((a, b) => a.y - b.y || a.x0 - b.x0)) {
    const L = rows[rows.length - 1], h = it.h || 10
    if (!L || Math.abs(it.y - L.y) > Math.max(2, h * 0.7)) rows.push({ y: it.y, h, items: [it] })
    else L.items.push(it)
  }
  const out = []
  for (const L of rows) {
    if (rest.some(o => Math.abs(o.y - L.y) <= Math.max(o.h || 10, L.h) * 0.6)) continue // inline math: ordinary text beside it
    const iv = L.items.slice().sort((a, b) => a.x0 - b.x0)
    L.s = ''
    L.own = []
    for (const it of iv) { // one item can hold several glyphs ("123"): each gets its own slice of the box
      const cs = [...pvMathNorm(it.s)], n = cs.length
      cs.forEach((ch, k) => { L.s += ch; L.own.push(n > 1 ? { ...it, x0: it.x0 + (it.w || 0) * k / n, w: (it.w || 0) / n } : it) })
    }
    if (!L.s) continue
    L.x0 = Math.min(...iv.map(o => o.x0))
    L.x1 = Math.max(...iv.map(o => o.x0 + (o.w || 0)))
    L.y0 = Math.min(...iv.map(o => o.y - (o.h || 10) / 2))
    L.y1 = Math.max(...iv.map(o => o.y + (o.h || 10) / 2))
    L.vw = iv[0].vw
    L.vh = iv[0].vh
    out.push(L)
  }
  return out
}
function pvSrcMath() { // block formulas with their visible glyphs and a source spot for every glyph
  const sig = pvSrcSig()
  if (pvSrcMathMemo && pvSrcMathMemo.sig === sig) return pvSrcMathMemo.out
  const main = pvMainText(), mainN = main.split('\n').length, out = []
  let loose = 0
  for (const src of pvSrcList()) {
    if (!src || !src.text) continue
    const view = srcViewOf(src.text), base = src.key ? (pvFileAnchor(src.key, main) || mainN + (++loose) * 1e5) : 0
    const ord = line => src.key ? base + line / (view.lines.length + 1) : line // a file line is a fraction of its include line: units stay main-file lines
    const blocks = srcObjs(src.text).formulas
    for (const f of blocks) {
      let s = ''
      const own = []
      for (let li = f.line - 1; li < f.end && li < view.lines.length; li++) { // source lines are dense: never scan the whole file per formula
        const L = view.lines[li]
        for (const seg of L.note ? [L, L.note] : [L]) for (let i = 0; i < seg.s.length; i++) { // a formula inside a footnote lives in the note segment
          const ch = pvMathNorm(seg.s[i])
          for (const c of ch) { s += c; own.push({ line: L.line, at: seg.map[i] }) }
        }
      }
      if (s) out.push({ key: src.key || '', line: f.line, end: f.end, s, own, order: ord(f.line) })
    }
    for (const sp of view.math || []) { // inline formulas (grid/table cells, #math.equation): their own glyphs only
      if (blocks.some(f => sp.line >= f.line && sp.line <= f.end)) continue // a block formula already owns the line
      const L = view.lines[sp.line - 1]
      if (!L) continue
      let s = ''
      const own = []
      for (const seg of L.note ? [L, L.note] : [L]) for (let i = 0; i < seg.s.length; i++) {
        const at = seg.map[i]
        if (at == null || at < sp.from || at >= sp.to) continue
        const ch = pvMathNorm(seg.s[i])
        for (const c of ch) { s += c; own.push({ line: sp.line, at }) }
      }
      if (s) out.push({ key: src.key || '', line: sp.line, end: sp.line, s, own, order: ord(sp.line) })
    }
  }
  pvSrcMathMemo = { sig, out: out.sort((a, b) => a.order - b.order) }
  return pvSrcMathMemo.out
}
function pvSrcSig() { // every source text: a memo must never survive an edit
  let h = 2166136261
  const mix = s => { for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619) }
  for (const s of pvSrcList()) { mix(s.key || ''); mix(s.text || '') }
  return h >>> 0
}
let pvSrcMathMemo = null // { sig, out }
function pvAlign(a, b) { // glyphs of one PDF math line -> a formula (skips on the formula side are free: fraction parts)
  const n = a.length, m = b.length, d = Array.from({ length: n + 1 }, () => new Int16Array(m + 1)), map = new Int32Array(n).fill(-1)
  if (!n || !m) return { cost: n, map }
  for (let i = 1; i <= n; i++) d[i][0] = i
  for (let i = 1; i <= n; i++) for (let j = 1; j <= m; j++) {
    d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1], d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1))
  }
  let end = 0
  for (let j = 1; j <= m; j++) if (d[n][j] < d[n][end]) end = j
  for (let i = n, j = end; i > 0;) {
    if (j > 0 && a[i - 1] === b[j - 1] && d[i][j] === d[i - 1][j - 1]) { map[i - 1] = --j; i-- }
    else if (j > 0 && d[i][j] === d[i][j - 1]) j--
    else i--
  }
  return { cost: d[n][end], map }
}
const PV_MATH_MAX_COST = 0.5 // unmatched PDF glyphs per glyph: above this the line is not the same formula
function pvMathCands(L, hint, srcs) { // formulas that explain enough of this visual line, best first
  const out = [], n = srcs.length
  let lo = 0, hi = n
  while (lo < hi) { // srcs is in document order (pvSrcMath): start at the page hint and walk outwards
    const mid = (lo + hi) >> 1
    if (srcs[mid].order < hint) lo = mid + 1
    else hi = mid
  }
  let l = lo - 1, r = lo, best = Infinity, full = false
  while (l >= 0 || r < n) {
    const dl = l >= 0 ? Math.abs(srcs[l].order - hint) : Infinity
    const dr = r < n ? Math.abs(srcs[r].order - hint) : Infinity
    if (full && Math.min(dl, dr) > best) break // a full map owns every glyph: farther formulas can only lose the click and the line
    const ix = dl <= dr ? l-- : r++, f = srcs[ix]
    const al = pvAlign(L.s, f.s)
    let ratio = al.cost / Math.max(1, L.s.length)
    if (ratio > PV_MATH_MAX_COST) { // a wide table row holds several cells: judge the glyphs this formula really covers
      let a = -1, b = -1
      for (let i = 0; i < al.map.length; i++) if (al.map[i] >= 0) { if (a < 0) a = i; b = i }
      const win = b - a + 1
      if (win < 2) continue // a lone glyph in a longer row proves nothing
      let err = 0
      for (let i = a; i <= b; i++) if (al.map[i] < 0) err++
      ratio = err / win
      if (ratio > PV_MATH_MAX_COST) continue
      if ((win - err) / Math.max(1, f.s.length) < 1 - PV_MATH_MAX_COST) continue // the cell must be this formula, not three shared glyphs ("2+2" of a²+b²=c² inside x²+2x+1)
    }
    const score = ratio * 1000 + Math.abs(f.order - hint)
    out.push({ src: f, map: al.map, ratio, score, ix })
    full = full || al.cost === 0
    if (score < best) best = score
  }
  return out.sort((a, b) => a.score - b.score || a.ix - b.ix) // ties keep the document order, as a stable scan would
}
function pvMathMatch() { // PDF math lines -> formulas: glyph similarity first, the page position breaks ties
  const srcs = pvSrcMath(), out = []
  if (!srcs.length) return out
  const total = cm.state.doc.lines || 1, sig = pvSrcSig() // any source edit may move a section or a formula
  const memo = pvMathMemo
  if (memo && memo.sig === sig && memo.outline === pvOutlineGen && memo.shown === shownN && memo.total === total && memo.active === (activeFile || '')
    && memo.texts.length === pvTexts.length && memo.texts.every((t, i) => t === pvTexts[i])) return memo.out // the section map reads the open tab's headings
  for (let pi = 0; pi < pvTexts.length; pi++) for (const L of pvMathLines(pvTexts[pi] || [])) {
    const y = (L.y0 + L.y1) / 2
    const hint = pvPageHint(pi, total, pvTexts.length, pvSecAtY(pi, y), y / (L.vh || 1))
    const cands = pvMathCands(L, hint, srcs)
    if (cands.length) out.push({ page: pi, line: L, src: cands[0].src, map: cands[0].map, cands })
  }
  pvMathMemo = { sig, outline: pvOutlineGen, shown: shownN, total, active: activeFile || '', texts: pvTexts.slice(), out }
  return out
}
let pvMathMemo = null // { sig, outline, shown, total, texts, out }
function pvMathIndex(line, x) { // clicked x -> the glyph under it (nearest center)
  let best = 0, bd = Infinity
  for (let i = 0; i < line.own.length; i++) {
    const it = line.own[i], d = Math.abs(it.x0 + (it.w || 0) / 2 - x)
    if (d < bd) { bd = d; best = i }
  }
  return best
}
function pvMapChunk(map, i) { // contiguous glyphs this formula owns around the clicked one (two grid cells: one cell)
  if (!map || i < 0 || i >= map.length || map[i] < 0) return 0
  let a = i, b = i
  while (a > 0 && map[a - 1] >= 0) a--
  while (b + 1 < map.length && map[b + 1] >= 0) b++
  return b - a + 1
}
function pvMathAt(pi, x, y, sx, sy) { // click inside a display formula (overlapping fraction lines: nearest glyph decides)
  let best = null, bd = Infinity, bg = Infinity
  for (const m of pvMathMatch()) {
    if (m.page !== pi) continue
    const L = m.line, x0 = L.x0 * sx, x1 = L.x1 * sx, y0 = L.y0 * sy, y1 = L.y1 * sy
    const dx = x < x0 ? x0 - x : x > x1 ? x - x1 : 0
    const dy = y < y0 ? y0 - y : y > y1 ? y - y1 : 0
    const d = dx * dx + dy * dy
    if (d > 9) continue // more than 3 CSS px beside a formula: not a hit
    const i = pvMathIndex(L, x / (sx || 1)), it = L.own[i]
    const gx = (it.x0 + (it.w || 0) / 2) * sx, gy = it.y * sy
    const g = (gx - x) * (gx - x) + (gy - y) * (gy - y)
    const cands = m.cands || [{ src: m.src, map: m.map, score: 0 }]
    let pick = null // a visual row can hold two formulas: the clicked glyph says which one
    for (const a of cands) {
      const chunk = pvMapChunk(a.map, i)
      if (!chunk) continue
      if (!pick || chunk > pick.chunk || (chunk === pick.chunk && a.score < pick.score)) pick = { ...a, chunk }
    }
    if (!pick) pick = { ...cands[0], chunk: 0 } // click on whitespace: nearest formula, as before
    if (d < bd || (d === bd && (g < bg || (g === bg && pick.chunk > (best ? best.chunk : 0))))) {
      bd = d; bg = g; best = { ...m, i, src: pick.src, map: pick.map, score: pick.score, chunk: pick.chunk }
    }
  }
  return best
}
function pvMathLineHit(line) { // cursor inside a block formula -> its rendered box (all lines of it)
  const key = activeFile || ''
  let best = null
  for (const m of pvMathMatch()) {
    if (m.src.key !== key || line < m.src.line || line > m.src.end) continue
    const L = m.line
    if (!best) best = { page: m.page, x0: L.x0, x1: L.x1, y0: L.y0, y1: L.y1, h: L.y1 - L.y0, vw: L.vw, vh: L.vh }
    else {
      best.x0 = Math.min(best.x0, L.x0); best.x1 = Math.max(best.x1, L.x1)
      best.y0 = Math.min(best.y0, L.y0); best.y1 = Math.max(best.y1, L.y1)
      best.h = best.y1 - best.y0
    }
  }
  return best
}
async function pvJumpSrc(src, col) { // preview object -> its file and line/column (switch tabs only when needed)
  const doc = docId, epoch = openN, key = (src && src.key) || ''
  if (key !== activeFile) {
    try { if (!await switchTab(key)) return false } catch (e) { return false }
    if (doc !== docId || epoch !== openN || (activeFile || '') !== key) return false // a tab clicked meanwhile owns the editor now
  }
  const line = Math.max(1, Math.min(cm.state.doc.lines || 1, src.line))
  jumpPos(posOfLine(getT(), line) + Math.max(0, col || 0))
  return true
}
async function pvJumpMath(hit) { // clicked formula glyph -> the same line and letter in the source formula
  const map = hit.map || pvAlign(hit.line.s, hit.src.s).map, k = map[hit.i]
  const at = k >= 0 ? hit.src.own[k] : null
  if (!at) return false // no matching glyph: text anchoring owns the click
  return pvJumpSrc({ ...hit.src, line: at.line }, at.at)
}
function pvScrollBox(b) { // cursor on an image/formula line -> center its rendered box
  const cv = pvCanvasList()[b.page], pv = $('preview')
  if (!cv) return false
  const pr = pv.getBoundingClientRect(), cr = cv.getBoundingClientRect()
  const sy = cr.height / (b.vh || cv.height || 1)
  const want = pv.scrollTop + (cr.top - pr.top) + ((b.y0 + b.y1) / 2) * sy - pv.clientHeight / 2
  syncPage = b.page
  syncEdOff = 0
  syncEdX = -1
  const dy = want - pv.scrollTop
  if (Math.abs(dy) > 300) smoothScroll(pv, want)
  else if (Math.abs(dy) > SYNC_PX) smoothFollow(pv, want)
  return true
}
function pvCaptionCut(s) { // Typst adds "Figure 1: " / "Table 1: " in front of a caption that the source does not have
  const m = String(s || '').match(/^(?:figure|table|listing|algorithm|equation|diagram|chart|abbildung|tabelle|diagramm|gleichung|liste|figura|tabla|tabela|tabella|tableau|ecuación|équation|equazione|equação|figuur|tabel|vergelijking|figur|tabell|ekvation|ligning|rysunek|równanie|obrázek|tabulka|rovnice|kuva|taulukko|şekil|tablo|рисунок|таблица|уравнение|σχήμα|πίνακας|図|表|图|式|그림|표)\s*(?:\d+|[A-Z]|[IVXLC]+)(?:[.\-–]\d+)*\s*[:.：—–-]\s*/iu)
  return m ? m[0].length : 0
}
function pvSuppCut(s) { // a custom supplement ("Fig. 2: ", "Exhibit 3 – ", "Abb. 1. "): a short word, a number and a separator in front of the caption
  const m = String(s || '').match(/^\p{L}{2,14}\.?\s+\d+(?:[.\-–]\d+)*\s*[:.—–-]\s+(?=\p{L})/u)
  return m ? m[0].length : 0
}
function pvNumCut(s) { // "1.2 Results", "A. Anhang", "iv) item": length of a generated numbering prefix before a title (0: none)
  const m = String(s || '').match(/^(?:\d+(?:\.\d+)*\.?|[A-Z]\.|[ivxlcdm]+[.)]|[a-z]\)|\d+\))\s+(?=\p{L})/u)
  return m ? m[0].length : 0
}
function pvBlockLines(items, it) { // paragraph around the click: full visual lines, columns split, normal line step
  const h = Math.max(1, it.h || 10), tol = Math.max(1.5, h * 0.55)
  const ok = items.filter(o => o.s && o.s.trim() && !o.rot && Math.abs((o.h || 0) - h) < Math.max(1, h * 0.14)) // relative: the render scale changes with the page count
  const lines = []
  for (const o of ok.sort((a, b) => a.y - b.y || a.x0 - b.x0)) {
    const L = lines[lines.length - 1]
    if (!L || Math.abs(o.y - L.y) > tol) lines.push({ y: o.y, runs: [[o]] })
    else L.runs[L.runs.length - 1].push(o)
  }
  for (const L of lines) { // wide horizontal gap: two columns, never one paragraph
    const runs = []
    for (const o of L.runs[0].slice().sort((a, b) => a.x0 - b.x0)) {
      const r = runs[runs.length - 1], p = r && r[r.length - 1]
      if (!r || (o.x0 || 0) - ((p.x0 || 0) + (p.w || 0)) > Math.max(h * 1.5, 6)) runs.push([o]) // Typst's column gutter (4% ≈ 2.2em) is wider than any justified space
      else r.push(o)
    }
    L.runs = runs
  }
  const at = lines.findIndex(L => L.runs.some(r => r.includes(it)))
  if (at < 0) return [it]
  const range = r => [Math.min(...r.map(o => o.x0 || 0)), Math.max(...r.map(o => (o.x0 || 0) + (o.w || 0)))]
  const mine = range(lines[at].runs.find(r => r.includes(it)))
  const row = L => {
    for (const r of L.runs) {
      const b = range(r)
      if (Math.min(b[1], mine[1]) - Math.max(b[0], mine[0]) > Math.min(b[1] - b[0], mine[1] - mine[0]) * 0.5) return r
    }
    return null
  }
  let a = at, b = at
  while (a > 0 && lines[a].y - lines[a - 1].y <= h * 1.8 && row(lines[a - 1])) a--
  while (b < lines.length - 1 && lines[b + 1].y - lines[b].y <= h * 1.8 && row(lines[b + 1])) b++
  const out = []
  for (let k = a; k <= b; k++) out.push(...row(lines[k]))
  return out
}
function pvBlockNeedle(items, it, col) { // whole paragraph: a wrapped, repeated line is ambiguous on its own
  const block = pvBlockLines(items, it)
  if (block.length < 2) return []
  return [false, true].map(drop => { // real compound first ("E-Mail"), automatic hyphenation second ("Silbentrennung")
    let s = '', off = 0, soft = false, prev = null
    for (const o of block) {
      const raw = String(o.s || ''), t = raw.trim()
      if (!t) continue
      const same = prev && Math.abs((o.y || 0) - (prev.y || 0)) < Math.max(1.5, (o.h || 10) * 0.55)
      if (s && soft && drop) s = s.slice(0, -1) // the source word continues on the next line
      let sep = 0
      if (s) {
        if (soft) sep = 0
        else if (same && !/\s$/.test(String(prev.s || ''))) { // run split mid-word: no invented space
          const gap = (o.x0 || 0) - ((prev.x0 || 0) + (prev.w || 0))
          sep = gap > Math.max(1, (o.h || 10) * 0.1) ? 1 : 0
        } else sep = 1
      }
      if (o === it) off = s.length + sep + (col || 0)
      s += (sep ? ' ' : '') + t
      soft = /[-\u2010\u00ad]$/.test(t)
      prev = o
    }
    const cut = pvCaptionCut(s)
    return { s: s.slice(cut), off: Math.max(0, off - cut) }
  })
}
function pvClickNeedles(items, it, col) { // clicked item first; short cells and math glyphs add their PDF line
  const out = [], seen = new Set()
  const add = (s, off, min) => {
    s = String(s || '').trim()
    const norm = syncText(s)
    if (norm.length < (min || 4) || seen.has(norm)) return false
    seen.add(norm)
    out.push({ s, off: Math.max(0, Math.min(s.length, off || 0)) })
    return true
  }
  const raw = String(it.s || '').trim(), cut = pvCaptionCut(raw), body = raw.slice(cut)
  for (const blk of pvBlockNeedle(items, it, col)) { // paragraph context first: prose wraps one source line over several PDF lines
    add(blk.s, blk.off)
    const g = pvSuppCut(blk.s)
    if (g && blk.off >= g) add(blk.s.slice(g), blk.off - g) // the same paragraph without a custom supplement prefix
  }
  const num = pvNumCut(body) // "1.2 Results": the heading/list number is generated, the title is in the source
  if (num && (col || 0) - cut >= 0) add(body.slice(num), Math.max(0, (col || 0) - cut - num), 2)
  if (/\p{L}/u.test(body)) add(body, (col || 0) - cut, /\p{L}{3}/u.test(body) ? 2 : 4) // "Yes", "Bob", "FAQ": a three-letter cell is still its own word; "mg" needs its row
  const sup = cut ? 0 : pvSuppCut(body)
  if (sup && (col || 0) >= sup) add(body.slice(sup), (col || 0) - sup)
  if (/\p{L}{3}/u.test(body) && out.length) return out // a real word needs no line guessing
  const bare = !/\p{L}/u.test(body) // no letters: a generated marker (footnote/citation/equation number) or a number in a table cell
  const ih = Math.max(1, it.h || 10)
  for (const tol of [ih * 0.45, ih * 0.9]) { // short cells, numbers and math glyphs: the row is the context (relative to the type size, not to the render scale)
    const line = items.filter(o => !o.rot && Math.abs(o.y - it.y) <= tol).sort((a, b) => a.x0 - b.x0)
    let s = '', off = 0, rest = '', gap = 0
    for (const o of line) {
      const t = String(o.s || '').trim()
      if (!t) continue
      if (o === it) { off = s.length + (s ? 1 : 0) + (col || 0); gap = rest.length } // the marker sits in this gap of the rest
      else rest += (rest ? ' ' : '') + t
      s += (s ? ' ' : '') + t
    }
    const hs = line.filter(o => o !== it && String(o.s || '').trim()).map(o => o.h || 10).sort((a, b) => a - b)
    const cell = bare && hs.length && Math.abs((it.h || 10) - hs[hs.length >> 1]) < ih * 0.15 && !/^[(\[]/.test(body) // full-size digits beside full-size text: a table number, really in the source
    const cut2 = pvCaptionCut(s), text = s.slice(cut2)
    if (cell && /\p{L}{3}/u.test(text)) add(text, off - cut2) // "42" in "Alice 42 Berlin": the row finds the number itself
    if (bare) { // a superscript marker is not in the source: its line still is
      const cut3 = pvCaptionCut(rest), text3 = rest.slice(cut3)
      if (/\p{L}{3}/u.test(text3) && add(text3, Math.max(0, gap - cut3))) break // the caret lands where the marker stands, not at the row start
    }
    if (/\p{L}{3}/u.test(text) && add(text, off - cut2)) break
  }
  if (!out.length && /\p{L}{2}/u.test(body)) add(body, (col || 0) - cut, 2) // alone on its row: the cell itself is all there is
  return out
}
const SRC_MATH = { // visible glyphs for common Typst math commands: tokens still map to the command start
  sum: '∑', prod: '∏', int: '∫', oint: '∮', infty: '∞', infinity: '∞', oo: '∞', partial: '∂', nabla: '∇',
  alpha: 'α', beta: 'β', gamma: 'γ', delta: 'δ', epsilon: 'ε', zeta: 'ζ', eta: 'η', theta: 'θ',
  iota: 'ι', kappa: 'κ', lambda: 'λ', mu: 'μ', nu: 'ν', xi: 'ξ', pi: 'π', rho: 'ρ', sigma: 'σ',
  tau: 'τ', upsilon: 'υ', phi: 'φ', chi: 'χ', psi: 'ψ', omega: 'ω',
  Gamma: 'Γ', Delta: 'Δ', Theta: 'Θ', Lambda: 'Λ', Xi: 'Ξ', Pi: 'Π', Sigma: 'Σ', Phi: 'Φ', Psi: 'Ψ', Omega: 'Ω',
  arrow: '→', times: '×', div: '÷', plusminus: '±', minus: '−', equiv: '≡', approx: '≈', neq: '≠', in: '∈', subset: '⊂', supset: '⊃',
  'plus.minus': '±', 'minus.plus': '∓', 'arrow.r': '→', 'arrow.l': '←', 'arrow.l.r': '↔', 'arrow.r.double': '⇒', 'arrow.l.r.double': '⇔',
  'arrow.t': '↑', 'arrow.b': '↓', 'arrow.r.bar': '↦', 'in.not': '∉', 'subset.eq': '⊆', 'supset.eq': '⊇', 'eq.not': '≠', 'eq.triple': '≡',
  'epsilon.alt': 'ϵ', 'phi.alt': 'ϕ', 'theta.alt': 'ϑ', 'dot.c': '⋅', 'dot.op': '⋅', 'times.circle': '⊗', 'plus.circle': '⊕',
  dot: '⋅', dots: '…', 'dots.h': '…', 'dots.c': '⋯', 'dots.v': '⋮', ast: '∗', star: '⋆', circle: '∘', compose: '∘', prop: '∝', degree: '°',
  le: '≤', ge: '≥', lt: '<', gt: '>', ne: '≠', eq: '=', forall: '∀', exists: '∃', emptyset: '∅', nothing: '∅', not: '¬',
  and: '∧', or: '∨', union: '∪', sect: '∩', without: '∖', ell: 'ℓ', aleph: 'ℵ', hbar: 'ℏ', prime: '′',
  RR: 'ℝ', NN: 'ℕ', ZZ: 'ℤ', QQ: 'ℚ', CC: 'ℂ'
}
const SRC_MATH_FN = new Set([ // math functions: the call is layout, only its arguments are glyphs (sqrt/root draw a radical)
  'frac', 'root', 'sqrt', 'vec', 'mat', 'cases', 'binom', 'abs', 'norm', 'floor', 'ceil', 'round', 'lr', 'mid', 'attach', 'scripts', 'limits', 'op',
  'upright', 'italic', 'bold', 'cal', 'bb', 'sans', 'mono', 'frak', 'serif', 'display', 'inline', 'script', 'sscript', 'overline', 'underline',
  'overbrace', 'underbrace', 'overbracket', 'underbracket', 'hat', 'tilde', 'macron', 'breve', 'acute', 'grave', 'caron', 'diaer', 'cancel',
  'accent', 'class', 'stretch', 'primes', 'dot', 'dot.double', 'dot.triple', 'arrow', 'arrow.l', 'arrow.l.r', 'bar', 'circle'
])
const SRC_MATH_OPS = [ // math shorthands, longest first: the PDF shows the symbol, never the ASCII
  ['<==>', '⟺'], ['==>', '⟹'], ['|->', '↦'], ['<->', '↔'], ['->', '→'], ['<-', '←'], ['=>', '⇒'], ['<=', '≤'], ['>=', '≥'],
  ['!=', '≠'], ['...', '…'], [':=', '≔'], ['<<', '≪'], ['>>', '≫'], ['-', '−'], ['*', '∗']
]
const SRC_KW = new Set(['let', 'set', 'show', 'import', 'include', 'if', 'for', 'while', 'context', 'return', 'break', 'continue']) // statements run to their line end
const SRC_STR_KEYS = new Set(['caption', 'title', 'attribution', 'header', 'footer', 'body', 'subtitle']) // named string arguments that print their text (alt/description/title of #set document do not)
const SRC_BLOCKS = new Set(['if', 'for', 'while', 'context']) // statements that end with their last block, markup continues right behind it
const SRC_INLINE = new Set(['emph', 'strong', 'text', 'underline', 'overline', 'strike', 'highlight', 'sub', 'super', 'smallcaps', 'upper', 'lower', 'link']) // styling calls: their brackets sit inside a word
const SRC_HIDE = new Set(['let', 'import', 'include']) // declarations never render where they stand, not even their [content]
const SRC_STR_SHOW = new Set(['text', 'strong', 'emph', 'underline', 'overline', 'strike', 'highlight', 'smallcaps', 'upper', 'lower', 'super', 'sub', 'raw', 'heading', 'quote', 'footnote', 'block', 'box', 'align', 'pad', 'par']) // a positional string argument is the shown body
const srcViewCache = new Map() // bounded: pvSrcList alternates between open files, never rescan every call
function srcPlainView(raw) { // a data file (.bib): every line is text as written, Typst markup rules (// comments, #, $) do not apply
  const out = raw.split('\n').map((line, li) => {
    const s = line.replace(/\r$/, ''), lead = s.length - s.trimStart().length, t = s.trim()
    return { line: li + 1, s: t, map: t.split('').map((_, k) => lead + k), raw: line }
  })
  return { lines: out, math: [] }
}
function srcViewOf(text) { // visible source text with a raw offset per character (links, raw, math: no URL or markup noise)
  const raw = String(text), hit = srcViewCache.get(raw)
  if (hit) return hit
  const view = /^\s*@[A-Za-z]+\s*[{(]/.test(raw) && !/^\s*[#=]/m.test(raw) ? srcPlainView(raw) : srcViewScan(raw) // BibTeX entries start with @type{
  srcViewCache.set(raw, view)
  if (srcViewCache.size > 8) srcViewCache.delete(srcViewCache.keys().next().value)
  return view
}
function srcViewScan(raw) { // one pass over the whole text: a mode stack carries calls, code blocks, [content] and math across lines
  const lines = raw.split('\n'), out = [], mathSpans = []
  const st = [{ k: 'm' }] // m: markup (c: inside [..]), e: code after # (cl: open brackets, kw: statement), x: display math
  let block = 0, fence = 0
  const top = () => st[st.length - 1]
  const hidden = () => { for (const f of st) if (f.hide) return true; return false }
  const inNote = () => { for (const f of st) if (f.fn) return true; return false } // footnote body: printed at the page bottom, not inside the paragraph
  const wordChar = c => !!c && /[\p{L}\p{N}]/u.test(c) // emphasis between two word chars is literal text
  const mathAhead = from => { // an unclosed $: only a closing $ before the next blank line makes it a formula (a line starting with "=" is math too)
    for (let k = from; k < lines.length; k++) {
      const s = lines[k]
      if (!s.trim()) return false
      for (let j = 0; j < s.length; j++) { if (s[j] === '\\') { j++; continue } if (s[j] === '$') return true }
    }
    return false
  }
  for (let li = 0; li < lines.length; li++) {
    const line = lines[li], n = line.length, body = { s: '', map: [] }, note = { s: '', map: [] }
    const emit = (ch, at) => {
      if (!ch || ch === '\n' || hidden()) return
      const o = inNote() ? note : body
      if (/\s/.test(ch)) { if (o.s && !o.s.endsWith(' ')) { o.s += ' '; o.map.push(at) } return }
      o.s += ch
      for (let k = 0; k < ch.length; k++) o.map.push(at) // a symbol outside the BMP keeps one raw spot per code unit
    }
    const word = (w, at) => { if (hidden()) return; const o = inNote() ? note : body; for (let k = 0; k < w.length; k++) { o.s += w[k]; o.map.push(at + k) } }
    const literalMark = k => wordChar(line[k - 1]) && wordChar(line[k + 1])
    const mathSpan = (from, to) => { if (to > from && !hidden()) mathSpans.push({ line: li + 1, from, to }) } // formula body in raw line offsets
    const mathEnd = from => {
      for (let j = from; j < n; j++) {
        if (line[j] === '\\') { j++; continue }
        if (line[j] === '$') return j
      }
      return -1
    }
    const strEnd = from => { // from the opening quote: index of the closing quote (n: unclosed)
      let j = from + 1
      while (j < n && line[j] !== '"') { if (line[j] === '\\') j++; j++ }
      return Math.min(j, n)
    }
    const urlEnd = (from, content) => { // lowercase http(s) links are one literal token, Typst parses no markup inside
      if (line.slice(from, from + 8) !== 'https://' && line.slice(from, from + 7) !== 'http://') return 0
      let j = from, depth = 0
      while (j < n) {
        const c = line[j]
        if (/\s/.test(c) || c === '`' || c === '<') break
        if (c === '[') depth++
        else if (c === ']') {
          if (depth) depth--
          else if (content) break // inside [...], an unmatched ] closes the block before the link does
        }
        j++
      }
      return j
    }
    const escape = at => { // \# \$ \u{1F600}; a backslash at the line end is a line break
      const u = line.slice(at).match(/^\\u\{([0-9a-fA-F]{1,6})\}/)
      if (u) { try { emit(String.fromCodePoint(parseInt(u[1], 16)), at) } catch (e) {} return at + u[0].length }
      if (at + 1 < n) { emit(line[at + 1], at + 1); return at + 2 }
      emit(' ', at); return n
    }
    const rawInline = at => { // `raw`, ``(empty), ```lang code```: the text is visible, the language tag is not
      let r = 1; while (line[at + r] === '`') r++
      if (r === 2) return at + 2
      const close = line.indexOf('`'.repeat(r), at + r), end = close < 0 ? n : close
      if (r >= 3 && close < 0) { // a fence that continues on the next lines, also as a call argument (#figure(```py … ```, caption: [..]))
        fence = r
        const rest = line.slice(at + r), tag = rest.match(/^[A-Za-z][\w+#.-]*(?=\s|$)/)
        const from = at + r + (tag ? tag[0].length + (rest.length > tag[0].length ? 1 : 0) : 0)
        word(line.slice(from), from)
        return n
      }
      let from = at + r
      if (r >= 3) { const tag = line.slice(from, end).match(/^[A-Za-z][\w+#.-]*(?=\s)/); if (tag) from += tag[0].length + 1 }
      word(line.slice(from, end), from)
      return close < 0 ? n : close + r
    }
    const math = (from, to) => { // math source -> the glyphs the PDF shows; commands and shorthands map to their Unicode symbol
      for (let j = from; j < to;) {
        const c = line[j]
        if (c === '\\') { if (j + 1 < to) emit(line[j + 1], j + 1); j += 2; continue } // \$ escape, "\ " line break
        if (c === '"') { const e = Math.min(strEnd(j), to); word(line.slice(j + 1, e), j + 1); j = e + 1; continue } // "text" in math: upright letters
        if (/\p{L}/u.test(c)) {
          let k = j + 1
          while (k < to && /[\p{L}\p{N}.]/u.test(line[k])) k++
          while (k > j + 1 && line[k - 1] === '.') k-- // "b." at the end of a sentence: the dot is punctuation
          const tok = line.slice(j, k)
          if (line[k] === '(' && SRC_MATH_FN.has(tok)) { if (tok === 'sqrt' || tok === 'root') emit('√', j); j = k; continue } // frac(a, b): only a and b are glyphs
          const g = SRC_MATH[tok] || (tok.includes('.') ? SRC_MATH[tok.slice(0, tok.indexOf('.'))] : '')
          if (g) emit(g, j)
          else word(tok, j)
          j = k; continue
        }
        if (c === '#') { // code inside a formula (#h(1em), #f(x)): layout or computed, never the glyphs of its own source
          j++
          while (j < to && /[\p{L}\p{N}_.-]/u.test(line[j])) j++
          if (line[j] === '(' || line[j] === '[') { const open = line[j], close = open === '(' ? ')' : ']'; let d = 0; while (j < to) { if (line[j] === open) d++; else if (line[j] === close && !--d) { j++; break } j++ } }
          continue
        }
        if (c === '_' || c === '^' || c === '&') { emit(' ', j); j++; continue } // scripts keep their own tokens, & only aligns
        const op = SRC_MATH_OPS.find(([s]) => j + s.length <= to && line.startsWith(s, j))
        if (op) { emit(op[1], j); j += op[0].length; continue }
        emit(c, j); j++
      }
    }
    const openMath = at => { // at the opening $: inline on this line, or a display formula that runs over several lines
      const close = mathEnd(at + 1)
      if (close >= 0) { mathSpan(at + 1, close); emit(' ', at); math(at + 1, close); emit(' ', close); return close + 1 }
      if (!mathAhead(li + 1)) return at + 1 // a $ typed alone: the text below stays text
      mathSpan(at + 1, n); emit(' ', at); math(at + 1, n)
      st.push({ k: 'x' })
      return n
    }
    const hash = at => { // # in markup: an expression or statement starts here
      const j = at + 1, m = line.slice(j).match(/^[\p{L}_][\p{L}\p{N}_-]*/u), name = m ? m[0] : ''
      if (!name && !'([{'.includes(line[j] || '-')) return j // stray #: nothing visible
      if (name === 'sym') { // #sym.arrow.r: one visible glyph
        const t = line.slice(j).match(/^sym((?:\.[\p{L}\p{N}]+)+)/u)
        if (t) {
          const path = t[1].slice(1), g = SRC_MATH[path] || SRC_MATH[path.split('.')[0]]
          if (g) emit(g, at)
          return j + t[0].length
        }
      }
      const f = { k: 'e', cl: [], kw: SRC_KW.has(name), hide: SRC_HIDE.has(name), fn: name === 'footnote', name, url: null }
      if (f.fn) emit(' ', at) // the marker is a gap in the paragraph: a click on it or its back-link lands on the call
      st.push(f)
      if (name) return j + name.length
      if (line[j] === '(') { f.cl.push(')'); return j + 1 } // #(expr)
      if (line[j] === '{') { f.cl.push('}'); return j + 1 } // #{ code block }
      return j // #[content]: the expression loop opens it
    }
    let i = 0
    if (fence) { // raw block content: every character is visible, indentation included
      const close = line.indexOf('`'.repeat(fence))
      if (close < 0) {
        const h = hidden(), vis = line.replace(/\r$/, '') // CRLF: the carriage return is not text
        out.push({ line: li + 1, s: h ? '' : vis, map: h ? [] : vis.split('').map((_, k) => k), raw: line }); continue
      }
      word(line.slice(0, close), 0) // closing fence: code before it is still raw text
      fence = 0; i = close
      while (line[i] === '`') i++
    } else if (!block) {
      if (top().k === 'e' && /^\s*=+\s/.test(line)) st.length = 1 // an unclosed call never swallows the next section (an open display formula keeps its "= …" lines)
      if (top().k === 'm') {
        const open = line.match(/^\s*(`{3,})/)
        if (open && line.indexOf(open[1], open[0].length) < 0) { fence = open[1].length; out.push({ line: li + 1, s: '', map: [], raw: line }); continue }
        const head = line.match(/^(\s*)(=+)\s+/)
        if (head) i = head[0].length
      }
    }
    while (i < n) {
      const c = line[i], c2 = line[i + 1], f = top()
      if (block) { // /* nested */ comments: everything inside is invisible
        if (c === '*' && c2 === '/') { block--; i += 2 } else if (c === '/' && c2 === '*') { block++; i += 2 } else i++
        continue
      }
      if (f.k === 'x') { // display math continued from a line above
        const close = mathEnd(i), to = close < 0 ? n : close
        mathSpan(i, to); math(i, to)
        if (close < 0) { i = n; continue }
        emit(' ', close); st.pop(); i = close + 1; continue
      }
      if (f.k === 'e') {
        if (f.kw && f.after && !f.cl.length) { // #if/#for ended with a block: only "else" continues it, anything else is markup again
          const m = line.slice(i).match(/^\s*else\b/)
          if (m) { f.after = false; i += m[0].length; continue }
          st.pop(); continue
        }
        if ((c === ']' || c === ')' || c === '}') && !f.cl.length && st.length > 1) { st.pop(); continue } // a closer for the enclosing content block or call, not for this statement
        if (!f.cl.length && !f.kw) { // between the parts of one expression: name, .field, (args), [content]
          if (c === '(') { f.cl.push(')'); i++; continue }
          if (c === '[') { st.push({ k: 'm', c: true, d: 0, inl: SRC_INLINE.has(f.name) }); if (!SRC_INLINE.has(f.name)) emit(' ', i); i++; continue }
          if (c === '.' && /[\p{L}_]/u.test(c2 || '')) { const m = line.slice(i + 1).match(/^[\p{L}_][\p{L}\p{N}_-]*/u); f.name = m[0]; i += 1 + m[0].length; continue }
          st.pop(); continue // the expression ended: the same character is markup again
        }
        if (c === '"') {
          const e = strEnd(i)
          const key = (line.slice(Math.max(0, i - 40), i).match(/([\p{L}\p{N}_-]+)\s*:\s*$/u) || [])[1] // "caption: " in front of the string
          const pos = f.cl.length === 1 && f.cl[0] === ')' && !key // positional, not "fill: …"
          if (f.name === 'link' && pos && !f.url) f.url = { from: i + 1, to: e, li } // #link("https://…") without body shows the address
          else if ((pos && SRC_STR_SHOW.has(f.name)) || (key && f.cl.length && SRC_STR_KEYS.has(key) && (!f.kw || key === 'header' || key === 'footer'))) { emit(' ', i); word(line.slice(i + 1, e).replace(/\\(.)/g, ' $1'), i + 1); emit(' ', e) } // #text(red, "body"), #strong("x"), caption: "Plot", header: "Draft"
          i = e + 1; continue
        }
        if (c === '/' && c2 === '/') break
        if (c === '/' && c2 === '*') { block = 1; i += 2; continue }
        if (c === '`') { i = rawInline(i); continue }
        if (c === '[') { st.push({ k: 'm', c: true, d: 0, inl: SRC_INLINE.has(f.name) }); if (!SRC_INLINE.has(f.name)) emit(' ', i); i++; continue }
        if (c === '$') { i = openMath(i); continue }
        if (c === '(' || c === '{') { f.cl.push(c === '(' ? ')' : '}'); i++; continue }
        if (c === ')' || c === '}') {
          if (f.cl.length) f.cl.pop()
          i++
          if (!f.cl.length && f.url) {
            if (line[i] !== '[' && f.url.li === li) { const u = line.slice(f.url.from, f.url.to), cut = (u.match(/^(?:mailto|tel):/) || [''])[0].length; emit(' ', f.url.from); word(u.slice(cut), f.url.from + cut); emit(' ', i) } // a link whose address sits on another line has no honest offset here
            f.url = null
          }
          if (!f.cl.length && f.kw && SRC_BLOCKS.has(f.name) && c === '}') f.after = true // #if x { … }: an else may follow
          continue
        }
        if (c === ';' && !f.cl.length) { st.pop(); i++; continue }
        i++; continue // code tokens never reach the page
      }
      // markup, at the top or inside [content]
      if (c === 'h') { // lowercase http(s) is a link: slashes, stars and brackets inside stay literal text
        const u = urlEnd(i, !!f.c)
        if (u) { word(line.slice(i, u), i); i = u; continue }
      }
      if (c === '/' && c2 === '/') break // a URL was consumed above, so this is always a comment
      if (c === '/' && c2 === '*') { block = 1; i += 2; continue }
      if (c === '\\') { i = escape(i); continue }
      if (c === '-' && c2 === '?') { i += 2; continue } // soft hyphen shorthand: invisible unless the word breaks there
      if (c === '<') {
        const m = line.slice(i).match(/^<[A-Za-z_][\w:.-]*>/)
        if (m) { i += m[0].length; continue }
        emit(c, i); i++; continue
      }
      if (c === '@' && !wordChar(line[i - 1])) { // @label / @citekey: the PDF shows "Figure 1" or "[1]", never the key
        const m = line.slice(i).match(/^@[\p{L}\p{N}_][\p{L}\p{N}_:.-]*/u)
        if (m) { i += m[0].replace(/[.:-]+$/, '').length; continue }
      }
      if (c === '`') { i = rawInline(i); continue }
      if (c === '$') { i = openMath(i); continue }
      if (c === '#') { i = hash(i); continue }
      if (c === '[') { if (f.c) f.d++; emit(' ', i); i++; continue }
      if (c === ']') {
        if (!(f.c && f.inl && !f.d)) emit(' ', i) // #underline[H]ello: the bracket of a styling call is no word gap
        i++
        if (f.c) {
          if (f.d) f.d--
          else { st.pop(); const up = top(); if (up.k === 'e' && up.kw && !up.cl.length && SRC_BLOCKS.has(up.name)) up.after = true } // the content block ends: back to its call
        }
        continue
      }
      if (c === '*' || c === '_') { if (literalMark(i)) emit(c, i); i++; continue }
      emit(c, i); i++
    }
    while (st.length > 1 && top().k === 'e' && !top().cl.length) st.pop() // an expression or statement ends with its line
    const trim = o => ({ s: o.s.trim(), map: o.map.slice(o.s.length - o.s.trimStart().length, o.s.length - (o.s.length - o.s.trimEnd().length)) })
    const L = { line: li + 1, ...trim(body), raw: line }
    if (note.s.trim()) L.note = trim(note) // srcViewNorm places it after the paragraph, where the PDF has it too
    out.push(L)
  }
  return { lines: out, math: mathSpans }
}
function srcObjs(text) { // source constructs in document order: images, block formulas, tables
  const raw = String(text), hit = srcObjCache.get(raw)
  if (hit) return hit
  const src = raw, lines = src.split('\n'), mask = srcMask(src).split('\n')
  const images = [], formulas = [], tables = []
  for (let i = 0; i < lines.length; i++) {
    const m = mask[i] || ''
    if (!/^\s*#let\s+[\w-]+\s*\(/.test(m)) for (const im of m.matchAll(/(?:^|[^\w.])image(?:\.decode)?\s*\(/g)) { // every call on the line, not just the first; a "#let fig(p) = image(p)" definition draws nothing where it stands
      const at = im.index + im[0].indexOf('image'), before = m.slice(0, at).trimEnd()
      if (/(?:^|[\s#])(?:set|show)$/.test(before) || /\bimage\s*:\s*$/.test(before)) continue // #set image(…) configures, it draws nothing
      if (before && !'#(,:=[{;'.includes(before.slice(-1))) continue // "the image(s) below": a word in prose, not a call
      const path = lines[i].slice(im.index + im[0].length).match(/^\s*"([^"]*)"/) // the string right behind the opening bracket
      if (path && /\.svg$/i.test(path[1])) continue // vector art has no raster box on paper: it must not take a picture's slot
      images.push({ line: i + 1, col: at })
    }
    if (/(?:^|[^\w])table\s*\(/.test(m)) tables.push({ line: i + 1 })
    if (!/^\s*(?:[-+]\s+)?\$(?:\s|$)/.test(m)) continue // a display formula: "$ x $", also as a list item; "$x$ is …" is inline math in a paragraph
    let end = i, closed = (m.match(/(?<!\\)\$/g) || []).length % 2 === 0
    while (!closed && ++end < lines.length) closed = ((mask[end] || '').match(/(?<!\\)\$/g) || []).length % 2 === 1
    formulas.push({ line: i + 1, end: end + 1 })
    i = end
  }
  const res = { images, formulas, tables }
  srcObjCache.set(raw, res)
  if (srcObjCache.size > 8) srcObjCache.delete(srcObjCache.keys().next().value)
  return res
}
const srcObjCache = new Map() // bounded: sync asks for the same file text on every cursor move
function srcLineWords(v) { // visible line -> normalized words with their raw offset in the line
  const out = []
  for (const m of v.s.matchAll(/[\p{L}\p{N}]+/gu)) out.push({ w: syncText(m[0]), raw: m[0], at: v.map[m.index] })
  return out
}
const SRC_CJK = /[\p{sc=Han}\p{sc=Hiragana}\p{sc=Katakana}]/u // scripts without spaces: matching needs one word per character
function pvNormCaret(text) { // syncText words with the raw offset of every character (click -> exact letter)
  const { s, map } = syncNormMap(String(text))
  let out = '', om = [], gap = true
  for (let i = 0; i < s.length;) {
    const cp = s.codePointAt(i), ch = String.fromCodePoint(cp), step = ch.length
    if (/[\p{L}\p{N}]/u.test(ch)) {
      out += ch
      for (let k = 0; k < step; k++) om.push(map[i + k])
      gap = false
      if (SRC_CJK.test(ch)) { out += ' '; om.push(map[i]); gap = true } // Han/kana: one word per character, like the source view
    } else if (!gap) { out += ' '; om.push(map[i]); gap = true }
    i += step
  }
  if (out.endsWith(' ')) { out = out.slice(0, -1); om.pop() }
  return { s: out, map: om }
}
function srcViewNorm(view) { // visible document -> normalized words, single spaced, absolute raw offset per character
  if (view.norm) return view.norm
  const parts = [], map = [], notes = []
  let base = 0, gap = true
  const put = (seg, at) => { // one visible segment, normalized, every character with its absolute raw offset
    const nm = syncNormMap(seg.s)
    for (let i = 0; i < nm.s.length;) {
      const cp = nm.s.codePointAt(i), ch = String.fromCodePoint(cp), step = ch.length
      if (/[\p{L}\p{N}]/u.test(ch)) {
        parts.push(ch)
        for (let k = 0; k < step; k++) map.push(at + (seg.map[nm.map[i + k]] ?? 0))
        gap = false
        if (SRC_CJK.test(ch)) { parts.push(' '); map.push(at + (seg.map[nm.map[i]] ?? 0)); gap = true } // Han/kana: one word per character, like the PDF needle
      } else if (!gap) { parts.push(' '); map.push(at + (seg.map[nm.map[i]] ?? 0)); gap = true }
      i += step
    }
  }
  const sep = at => { if (parts.length && parts[parts.length - 1] !== ' ') { parts.push(' '); map.push(at) } gap = true } // line break keeps words apart
  const flush = () => { for (const n of notes) { put(n.seg, n.at); sep(n.at + n.len) } notes.length = 0 } // footnotes follow their paragraph, as on paper
  for (const L of view.lines) {
    const raw = L.raw || ''
    if (!raw.trim() || /^\s*=+\s/.test(raw)) flush()
    put(L, base)
    if (L.note) notes.push({ seg: L.note, at: base, len: raw.length })
    base += raw.length + 1
    sep(base - 1)
  }
  flush()
  while (parts.length && parts[parts.length - 1] === ' ') { parts.pop(); map.pop() }
  view.norm = { s: parts.join(''), map }
  return view.norm
}
function srcViewWords(view) { // visible document -> words with raw span and a raw offset for every letter
  if (view.words) return view.words
  const doc = srcViewNorm(view), out = []
  for (const m of doc.s.matchAll(/[\p{L}\p{N}]+/gu)) {
    const at = m.index
    out.push({ w: m[0], at, raw: doc.map[at], map: doc.map.slice(at, at + m[0].length) })
  }
  view.words = out
  return out
}
function pvCaretIndex(nw, off) { // click column in the PDF text -> index in the normalized needle
  let k = 0
  while (k < nw.s.length && nw.map[k] < (off || 0)) k++
  return k
}
function pvViewPos(txt, s, off, hint) { // clicked visible text -> source letter (markup, URLs, raw and math stay out of the way)
  const view = srcViewOf(txt), doc = srcViewNorm(view), nw = pvNormCaret(s)
  if (nw.s.length < 2 || !doc.s) return -1
  const hp = posOfLine(txt, hint)
  const land = at => { // matched run -> the character under the click
    const k = pvCaretIndex(nw, off)
    if (k >= nw.s.length) return srcAfter(txt, doc.map[Math.min(doc.s.length - 1, at + nw.s.length - 1)]) // right half of the last letter: caret behind it
    return doc.map[Math.max(0, Math.min(doc.s.length - 1, at + k))] // a space/boundary click keeps its own source spot
  }
  let best = -1, bd = Infinity, p = -1
  while ((p = doc.s.indexOf(nw.s, p + 1)) >= 0) {
    if ((p && doc.s[p - 1] !== ' ') || (p + nw.s.length < doc.s.length && doc.s[p + nw.s.length] !== ' ')) continue
    const d = Math.abs(doc.map[p] - hp)
    if (d < bd) { bd = d; best = p }
  }
  if (best >= 0) return land(best)
  const cn = nw.s.replace(/ /g, '')
  if (!nw.s.includes(' ') || cn.length < 12) return -1
  const cd = srcViewCompact(doc) // the PDF text layer drops a line-break hyphen ("Arbeitsunfä" + "higkeits…"): compare the letters without word gaps
  let q = -1
  while ((q = cd.s.indexOf(cn, q + 1)) >= 0) {
    const a = cd.at[q], z = cd.at[q + cn.length - 1]
    if ((a && doc.s[a - 1] !== ' ') || (z + 1 < doc.s.length && doc.s[z + 1] !== ' ')) continue // still whole words at both ends
    const d = Math.abs(doc.map[a] - hp)
    if (d < bd) { bd = d; best = q }
  }
  if (best < 0) return -1
  const k = pvCaretIndex(nw, off), c = nw.s.slice(0, k).replace(/ /g, '').length
  if (c >= cn.length || (c > 0 && nw.s[k] === ' ')) return srcAfter(txt, doc.map[cd.at[best + c - 1]]) // a click in a word gap: the caret stays behind the word before it
  return doc.map[cd.at[best + c]]
}
function srcViewCompact(doc) { // normalized document without word gaps, with the index of every letter in doc.s
  if (doc.compact) return doc.compact
  let s = ''
  const at = []
  for (let i = 0; i < doc.s.length; i++) if (doc.s[i] !== ' ') { s += doc.s[i]; at.push(i) }
  doc.compact = { s, at }
  return doc.compact
}
function srcAfter(txt, p) { // raw offset just behind the character at p (surrogate pairs and combining marks included)
  if (p == null || p < 0) return p
  let q = p + (txt.codePointAt(p) > 0xffff ? 2 : 1)
  while (q < txt.length && /\p{M}/u.test(String.fromCodePoint(txt.codePointAt(q)))) q += txt.codePointAt(q) > 0xffff ? 2 : 1
  return Math.min(q, txt.length)
}
function pvViewWords(txt, s, off, hint, minCtx) { // fallback: the clicked word, context first, then the nearest hint line; minCtx: neighbours that must agree
  const view = srcViewOf(txt), words = srcViewWords(view), nw = pvNormCaret(s)
  if (!words.length || !nw.s) return -1
  const want = []
  for (const m of nw.s.matchAll(/[\p{L}\p{N}]+/gu)) want.push({ w: m[0], at: m.index })
  if (!want.length) return -1
  const k = pvCaretIndex(nw, off)
  let wi = want.findIndex(w => k <= w.at + w.w.length)
  if (wi < 0) wi = want.length - 1
  const cw = Math.max(0, Math.min(want[wi].w.length - 1, k - want[wi].at))
  const hp = posOfLine(txt, hint)
  let best = -1, bd = Infinity, bc = 0
  for (let i = 0; i < words.length; i++) {
    if (words[i].w !== want[wi].w) continue
    let ctx = 0
    for (let d = 1; d <= 3; d++) {
      const a = want[wi - d], b = want[wi + d]
      if (a && i - d >= 0 && words[i - d].w === a.w) ctx++
      if (b && i + d < words.length && words[i + d].w === b.w) ctx++
    }
    const d = Math.abs(words[i].raw - hp) - ctx * 1e6 // context beats a far-away coincidence
    if (d < bd) { bd = d; best = i; bc = ctx }
  }
  if (best < 0 || bc < Math.min(minCtx || 0, want.length - 1)) return -1 // a lone common word ("the") in this file proves nothing about the clicked text
  const w = words[best]
  if (k >= want[wi].at + want[wi].w.length && wi === want.length - 1 && !(minCtx > 0)) return srcAfter(txt, w.map[w.map.length - 1]) // caret behind the last letter of the clicked run
  return w.map[Math.min(cw, w.map.length - 1)]
}
function syncText(text) {
  return text.normalize('NFKC').toLowerCase().replace(/[\p{sc=Han}\p{sc=Hiragana}\p{sc=Katakana}]/gu, ' $& ').replace(/[^\p{L}\p{N}]+/gu, ' ').trim() // NFKC first: 𝐸 -> E -> e; Han/kana have no spaces: every character is its own word
}
function syncPlain(text) { // source markup -> the words the PDF actually shows (best effort, no parser)
  return syncText(String(text)
    .replace(/<[A-Za-z_][\w:.-]*>/g, ' ') // labels only: "a < b" stays readable
    .replace(/#[a-zA-Z]\w*(?:\([^()]*(?:\([^()]*\)[^()]*)*\))?\[([^\]]*)\]/g, ' $1 ') // #link(..)[text], #emph[..], #grid(columns: (1fr, 1fr))[..]: keep the visible text
    .replace(/[`*_]/g, ' '))
}
function syncShow(text) { // source markup -> display text: casing kept, labels/markup dropped
  return String(text)
    .replace(/<[A-Za-z_][\w:.-]*>/g, ' ')
    .replace(/#[a-zA-Z]\w*(?:\([^()]*(?:\([^()]*\)[^()]*)*\))?\[([^\]]*)\]/g, ' $1 ')
    .replace(/[`*_]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}
function syncNormMap(line) { // normalized text + raw offset of every normalized char (math/ligatures keep their position)
  let s = '', map = []
  for (let i = 0; i < line.length;) {
    let j = i + (line.codePointAt(i) > 0xffff ? 2 : 1) // one code point …
    while (j < line.length && /\p{M}/u.test(String.fromCodePoint(line.codePointAt(j)))) j += line.codePointAt(j) > 0xffff ? 2 : 1 // … plus its marks: a+¨ -> ä
    const n = line.slice(i, j).normalize('NFKC').toLowerCase().replace(/[­​⁠﻿]/g, '') // soft hyphen / zero-width: no word gap, no letter
    for (let k = 0; k < n.length; k++) map.push(i)
    s += n
    i = j
  }
  return { s, map }
}
function syncWords(t) { // source words in document order with their raw line/offset (markup and reflow safe)
  const out = []
  t.split('\n').forEach((line, i) => {
    const plain = syncPlain(line)
    if (!plain) return
    const { s, map } = syncNormMap(line)
    let from = 0
    for (const w of plain.split(' ')) {
      if (!w) continue
      const at = s.indexOf(w, from)
      out.push({ w, ln: i + 1, at: at >= 0 && map[at] != null ? map[at] : from })
      if (at >= 0) from = at + w.length
    }
  })
  return out
}
function syncNeedleAt(t, needle, hint, wi) { // PDF text -> source pos of its wi-th word, across line breaks and markup
  const words = syncWords(t), want = syncText(needle).split(' ')
  const w0 = Math.max(0, wi || 0)
  if (!want[0]) return -1
  const soft = /[-\u2010\u00ad]$/.test(String(needle).trim()) // line-break hyphen: the source has the whole word
  let best = -1, bd = Infinity
  for (let i = 0; i < words.length; i++) {
    if (!(want.length === 1 && soft ? words[i].w.startsWith(want[0]) : words[i].w === want[0])) continue
    let n = 0
    while (n < want.length && i + n < words.length) {
      const last = n === want.length - 1
      if (!(last && soft ? words[i + n].w.startsWith(want[n]) : words[i + n].w === want[n])) break
      n++
    }
    if (n < Math.min(3, want.length) || w0 >= n) continue // the clicked word must be inside the matched run
    const d = Math.abs(words[i].ln - hint)
    if (d < bd) { bd = d; best = i }
  }
  if (best < 0) return -1
  const w = words[Math.min(words.length - 1, best + w0)]
  return posOfLine(t, w.ln) + w.at
}
function pvCmdLine(s) { // bare command (also "table(", "#set page("): no rendered words to anchor
  s = String(s || '').trim()
  return /^#[\w-]+(?:\s*(?:\([^)]*\)|[\(\[]))?$/.test(s) // #figure(, #pagebreak()
    || /^[\w-]+\s*[\(\[]$/.test(s) // bare table(
    || /^#(?:set|show|let|import|include)\b[^\[]*$/.test(s) // #set page(, #show heading.where(...): no content block
}
function syncAnchor(lines, line, pages, sec) { // source line -> word box on paper, section window first
  let raw = (lines[line - 1] || '').trim()
  if (!raw) return null
  const head = raw.match(/^(=+)\s+(.+)$/)
  const seen = srcViewLine(lines, line) // the same visible text the click side uses: call arguments, code and labels are not words
  if (seen != null ? !seen.trim() : pvCmdLine(raw)) return null // "#figure(" must never match a generated "Figure 1:" caption prefix; #strong("Hello") still has words
  if (seen != null) raw = head ? seen : seen.replace(/^caption\s*:\s*/, '') // an orphan "caption: [..]" line (opener out of reach) is still its caption
  else {
    if (head) raw = head[2] // heading: the title, not the "=" markers
    const cap = !head && /^(?:caption\s*:|#(?:figure|table|image|listing|algorithm)\b)/.test(raw) && raw.match(/caption\s*:\s*\[([^\]]*)\]/) // a real caption option, not the word in prose
    raw = cap ? cap[1] : raw.replace(/^caption\s*:\s*/, '')
  }
  const exact = syncPlain(raw)
  if (exact.length < 4) return null
  const p0 = sec ? Math.max(0, sec.page) : 0
  const p1 = sec ? Math.min(pages.length - 1, line === sec.line ? sec.page : sec.endPage) : pages.length - 1 // heading: its own page only
  const win = pvPageIndex(pages, p0, p1)
  const hit = (head && pvHeadingHit(win, exact)) || pvFindIn(win, exact)
  if (hit) return hit
  if (p0 === 0 && p1 === pages.length - 1) return pvHeadingPick(win, lines, line, exact) // no window: heading context decides
  const all = pvPageIndex(pages, 0, pages.length - 1) // stale outline: global last resort
  return pvFind(all.text, all.spans, exact) || pvHeadingPick(all, lines, line, exact) || pvRunPick(all, exact)
}
const srcViewLines = new WeakMap() // one scan per lines array: syncNearPair and pvSecAtY ask line after line
function srcViewLine(lines, line) { // visible text of one source line in its document context (null: no scanner loaded)
  if (typeof srcViewOf !== 'function' || !Array.isArray(lines)) return null
  let view = srcViewLines.get(lines)
  if (!view) { view = srcViewOf(lines.join('\n')); srcViewLines.set(lines, view) }
  const L = view.lines[line - 1]
  return L ? (L.s || (L.note ? L.note.s : '')) : null // a line inside a footnote body has only its note text
}
function pvFindIn(win, exact) { // exact whole words, else a unique 3-6 word run
  return pvFind(win.text, win.spans, exact) || pvRunPick(win, exact)
}
function pvRunPick(win, exact) {
  return pvRuns(exact).map(run => pvFind(win.text, win.spans, run)).find(Boolean) || null
}
function pvHeadingPick(win, lines, line, needle) { // repeated text: the nearest unique preceding heading decides
  const hits = []
  let at = -1
  while ((at = win.text.indexOf(needle, at + 1)) >= 0) {
    if ((at && win.text[at - 1] !== ' ') || (at + needle.length < win.text.length && win.text[at + needle.length] !== ' ')) continue
    const span = win.spans.find(s => s.to > at)
    if (span) hits.push({ ...span, at, items: win.spans.filter(s => s.from < at + needle.length && s.to > at).map(s => s.it) })
  }
  if (!hits.length) return null
  if (hits.length === 1) return hits[0]
  const headings = lines.slice(0, line - 1).filter(s => /^\s*=+\s/.test(s)).map(syncPlain).reverse()
  for (const heading of headings) {
    if (win.text.indexOf(heading) !== win.text.lastIndexOf(heading)) continue // not unique: useless as a marker
    const scored = hits.map(hit => ({ hit, d: win.text.lastIndexOf(heading, hit.at - 1) })).filter(s => s.d >= 0)
      .sort((a, b) => (a.hit.at - a.d) - (b.hit.at - b.d))
    if (scored.length && (scored.length === 1 || scored[0].hit.at - scored[0].d < scored[1].hit.at - scored[1].d)) return scored[0].hit
  }
  return null
}
function pvPageIndex(pages, p0, p1) { // flat word text of one page window + item spans
  const parts = [], spans = []
  let offset = 0
  for (let pi = p0; pi <= p1; pi++) (pages[pi] || []).forEach(it => {
    const text = it.nt != null ? it.nt : (it.nt = syncText(it.s || '')) // normalized once per item: every cursor move scans whole windows
    if (!text) return
    parts.push(text); spans.push({ from: offset, to: offset + text.length, pi, it })
    offset += text.length + 1
  })
  return { text: parts.join(' '), spans }
}
function pvHits(text, spans, needle) { // every whole-word occurrence inside the window
  const out = []
  let at = -1
  while ((at = text.indexOf(needle, at + 1)) >= 0) {
    if ((at && text[at - 1] !== ' ') || (at + needle.length < text.length && text[at + needle.length] !== ' ')) continue
    let lo = 0, hi = spans.length // spans are sorted: the first one ending behind the hit, by bisection
    while (lo < hi) { const mid = (lo + hi) >> 1; if (spans[mid].to > at) hi = mid; else lo = mid + 1 }
    const span = spans[lo]
    if (span) {
      const items = []
      for (let k = lo; k < spans.length && spans[k].from < at + needle.length; k++) items.push(spans[k].it)
      out.push({ ...span, at, items })
    }
  }
  return out
}
function pvFind(text, spans, needle) { // whole-word, unique within the window (else null)
  const hits = pvHits(text, spans, needle)
  return hits.length === 1 ? hits[0] : null
}
function pvHeadingHit(win, needle) { // heading page: the biggest type wins over the same word in the body
  const hits = pvHits(win.text, win.spans, needle)
  if (!hits.length) return null
  const top = Math.max(...hits.map(h => h.it.h || 0))
  const best = hits.filter(h => Math.abs((h.it.h || 0) - top) <= 0.5)
  return best.length === 1 ? best[0] : null
}
function pvRuns(text) { // 6..3 word runs, 12+ chars: lines with inline markup still match the paper text
  const words = text.split(' ').filter(Boolean), out = []
  for (let n = Math.min(6, words.length); n >= 3; n--)
    for (let i = 0; i + n <= words.length; i++) {
      const run = words.slice(i, i + n).join(' ')
      if (run.length >= 12) out.push(run)
    }
  return out
}
function pvViewPage(pv, off) { // page at the reading point: viewport center, shifted to the last preview click
  const pr = pv.getBoundingClientRect(), mid = pr.top + pv.clientHeight / 2 + (off || 0)
  const slots = pv.querySelectorAll('.pvPage')
  for (let k = 0; k < slots.length; k++) if (slots[k].getBoundingClientRect().bottom > mid) return k
  return -1
}
function pvCallEnd(lines, from) { // line with the closing bracket of a call opened at `from` (best effort)
  let d = 0, block = 0, str = false, raw = 0
  for (let ln = from; ln <= lines.length; ln++) {
    const s = lines[ln - 1] || ''
    if (ln > from && !block && !str && !raw && /^=+\s/.test(s.trim())) return ln - 1 // an open call never swallows the next section
    for (let i = 0; i < s.length; i++) {
      const c = s[i], n = s[i + 1]
      if (block) { // /* … */ (nested): parens inside are prose
        if (c === '/' && n === '*') { block++; i++ } else if (c === '*' && n === '/') { block--; i++ }
        continue
      }
      if (str) { if (c === '\\') i++; else if (c === '"') str = false; continue } // strings may span lines
      if (raw) { // `raw` and ```blocks```: brackets are text
        if (c === '`') {
          let r = 1
          while (s[i + r] === '`') r++
          if (r >= raw) raw = 0
          i += r - 1
        }
        continue
      }
      if (c === '\\') { i++; continue } // escaped bracket in markup: \) does not close
      if (c === '`') {
        let r = 1
        while (s[i + r] === '`') r++
        raw = r
        i += r - 1
        continue
      }
      if (c === '/' && (n === '/' || n === '*')) { // bare URLs (https://…) are not comments
        const before = s.slice(0, i)
        const url = /(?:^|\s)[a-z][a-z0-9+.-]*:$/i.test(before) || /(?:^|\s)[a-z][a-z0-9+.-]*:\/\/\S*$/i.test(before)
        if (url) { i++; continue }
        if (n === '/') break
        block = 1; i++
        continue
      }
      if (c === '"') { str = true; continue }
      d += c === '(' || c === '[' ? 1 : c === ')' || c === ']' ? -1 : 0
    }
    if (d <= 0) return ln
  }
  return lines.length
}
function pvFigureStart(lines, line) { // outermost figure/table/image call that contains `line` (0: none)
  const cand = []
  for (let ln = line; ln >= 1; ln--) {
    const s = (lines[ln - 1] || '').trim()
    if (/^=+\s/.test(s)) break
    if (/^#(?:figure|table|image)\s*\(/.test(s)) cand.push(ln)
  }
  for (let k = cand.length - 1; k >= 0; k--) if (line <= pvCallEnd(lines, cand[k])) return cand[k] // farthest open call wins
  return 0
}
function pvFigureHint(lines, line, pages, sec) { // cursor inside a figure call: its own caption names the page
  const from = pvFigureStart(lines, line)
  if (!from) return null
  const to = pvCallEnd(lines, from)
  if (line > to) return null
  let cap = 0 // inside caption: [ … ] spanning lines: its text lines are the anchor
  for (let ln = from; ln <= to; ln++) {
    const s = (lines[ln - 1] || '').trim()
    if (cap) {
      const hit = syncAnchor(lines, ln, pages, sec)
      if (hit) return hit
      if (s.includes(']')) cap = 0
      continue
    }
    if (!/(?:^|[\s,])caption\s*:/.test(s)) continue // same-line captions start on the opener itself
    if (!s.includes(']')) cap = 1
    const hit = syncAnchor(lines, ln, pages, sec)
    if (hit) return hit
  }
  return null
}
function syncNearPair(lines, line, pages, sec) { // nearest anchored content above and below (blank/command lines)
  const mask = srcMask(lines.join('\n')).split('\n') // a fenced example is text, never a real page/column break
  const scan = (from, to, dir) => {
    for (let ln = from; dir > 0 ? ln <= to : ln >= to; ln += dir) {
      const s = (lines[ln - 1] || '').trim()
      if (!s) continue
      if (/^#(?:pagebreak|colbreak)\b/.test((mask[ln - 1] || '').trim())) return null // text on one side of the break belongs to the other page/column
      const hit = syncAnchor(lines, ln, pages, sec)
      if (hit) return hit
    }
    return null
  }
  const from = pvFigureStart(lines, line)
  const end = from ? pvCallEnd(lines, from) : 0
  const inFig = from > 0 && line <= end
  return {
    back: scan(line - 1, Math.max(1, line - 12), -1),
    fwd: scan(line + 1, inFig ? end : Math.min(lines.length, line + 12), 1) // inside a figure: its own span only
  }
}
function syncNearHit(lines, line, pages, sec) { // blank/command lines still move the paper: next content for a command, the text above for a blank
  const hint = pvFigureHint(lines, line, pages, sec)
  if (hint) return hint
  const pair = syncNearPair(lines, line, pages, sec)
  return pvCmdLine(lines[line - 1]) ? (pair.fwd || pair.back) : (pair.back || pair.fwd)
}
function pvGuessBetween(pair) { // no anchor on this line: the paper space between the text above and below
  if (!pair || (!pair.back && !pair.fwd)) return null
  const b = pair.back, f = pair.fwd
  const box = (it, pi, y) => ({ page: pi, x0: it.x0 || 0, x1: (it.x0 || 0) + (it.w || 0), y0: y, y1: y, h: it.h || 10, vw: it.vw || 1, vh: it.vh || 1 })
  if (!f) return box(b.it, b.pi, b.it.y + (b.it.h || 10) / 2 + (b.it.h || 10) / 2)
  if (!b) return box(f.it, f.pi, f.it.y - (f.it.h || 10) / 2 - (f.it.h || 10) / 2)
  if (b.pi === f.pi) return box(b.it, b.pi, (b.it.y + (b.it.h || 10) / 2 + f.it.y - (f.it.h || 10) / 2) / 2)
  return box(b.it, b.pi, b.it.y + (b.it.h || 10)) // other page: just below the text above
}
function pvGuessLine(line, sec) { // no text anchor at all: proportional inside the section window, else the document
  const lines = cm.state.doc.lines || 1, n = pvTexts.length
  if (!n) return null
  let p0 = 0, p1 = n - 1, l0 = 1, l1 = lines
  if (sec) {
    p0 = Math.max(0, sec.page)
    p1 = Math.max(p0, Math.min(n - 1, sec.endPage))
    l0 = sec.line
    l1 = Math.max(l0 + 1, Math.min(lines, sec.endLine || lines))
  }
  const f = Math.max(0, Math.min(1, (line - l0) / Math.max(1, l1 - l0)))
  const page = Math.max(0, Math.min(n - 1, Math.floor(p0 + f * (p1 - p0 + 1) - 1e-9)))
  const slot = pvSlots && pvSlots[page], h = slot ? (+slot.dataset.w || 0) * (+slot.dataset.r || 0) : (pvPageSize ? pvPageSize.height : 842)
  const span = p1 - p0 + 1, within = span > 1 ? (p0 + f * span - page) : f
  return { page, x0: 0, x1: 0, y0: within * h, y1: within * h, h: 1, vw: slot ? +slot.dataset.w || h : h, vh: h }
}
function syncToPv(force) { // force: explicit navigation (outline/find), works even with follow off
  const fileTab = !!activeFile && !window.changeSession && /\.typ$/i.test(activeFile) && !isTplKey(activeFile) // an included chapter is on the page too: its text and its own headings (also in the PDF outline) anchor it
  if ((!followAll && !force) || !docId || tplName || (activeFile && !window.changeSession && !fileTab)) return
  if (scrollRestore && !scrollRestore.pv) return // reopened doc: saved preview spot wins over the first follow
  const pv = $('preview')
  if (!pv.scrollHeight || document.body.classList.contains('editonly')) return
  const lines = getT().split('\n'), at = syncView >= 0 ? syncView : cm.state.selection.main.head
  const line = cm.state.doc.lineAt(Math.max(0, Math.min(cm.state.doc.length, at))).number
  syncView = -1
  const sec = pvSecAtLine(line)
  const obj = pvImgLineHit(line) || pvMathLineHit(line) // image/formula line: its own box beats any nearby text
  if (obj) { syncMiss = false; pvScrollBox(obj); return }
  let hit = syncAnchor(lines, line, pvTexts, sec)
  if (!hit) {
    hit = pvFigureHint(lines, line, pvTexts, sec)
    if (!hit) { // blank/command line: the spot between its neighbours, else a proportional estimate
      const win0 = sec ? Math.max(0, sec.page) : 0, win1 = sec ? Math.min(pvTexts.length - 1, sec.endPage) : pvTexts.length - 1
      let pending = false // a render is still indexing its pages: no proportional jump now, the retry in pvTextAll follows with real text
      for (let k = win0; k <= win1; k++) if (!pvTextDone[k]) { pending = true; break }
      const near = pvGuessBetween(syncNearPair(lines, line, pvTexts, sec))
      const guess = near || (pending ? null : (fileTab && !sec ? null : pvGuessLine(line, sec))) // a file line has no ratio on the main document
      if (guess) { syncMiss = false; pvScrollBox(guess); return }
      if (pending) { syncMiss = true; return }
    }
  }
  if (!hit) { // no matching words: still show the section page, but never yank the preview out of it
    syncMiss = true // a render still in flight gets one retry (see pvTextAll)
    const at = pvViewPage(pv)
    if (sec && at >= 0 && (at < sec.page || at > sec.endPage)) pvGotoTarget({ page: sec.page, top: null })
    return
  }
  syncMiss = false
  const cv = pvCanvasList()[hit.pi]
  if (!cv) return
  const pr = pv.getBoundingClientRect(), cr = cv.getBoundingClientRect()
  const want = pv.scrollTop + cr.top - pr.top + hit.it.y * cr.height / (hit.it.vh || cv.height || 1) - pv.clientHeight / 2
  syncPage = hit.pi
  syncEdOff = 0 // the preview centers the cursor target: the reading point is the center again
  syncEdX = -1
  const dy = want - pv.scrollTop
  if (Math.abs(dy) > 300) smoothScroll(pv, want) // a page jump gets the long in-out handles
  else if (Math.abs(dy) > SYNC_PX) smoothFollow(pv, want) // small steps follow without ever restarting
}
async function pvSyncDest(dest) { // internal PDF link: the editor cursor follows the same destination
  if (!syncOn || !docId || tplName || activeFile || !dest) return // a link click is a click: the eye does not gate it
  const items = pvTexts[dest.page] || [], slot = pvSlots[dest.page]
  if (!items.length || !slot) return
  const hPt = (+slot.dataset.w || 0) * (+slot.dataset.r || 0)
  const vh = items[0].vh || hPt
  const y = dest.top != null ? Math.max(0, Math.min(vh, vh - dest.top * pvScale)) : 0 // dest.top is PDF points, vh viewport units
  const hint = pvPageHint(dest.page, cm.state.doc.lines || 1, pvTexts.length, pvSecAtY(dest.page, Math.min(vh, y + vh * 0.02)), y / (vh || 1))
  const lx = dest.left != null ? dest.left * pvScale : null // XYZ left: on a two-column page the column decides, not only the height
  const rank = it => { // text that starts at or below the destination first: a location marks the top of its element
    const top = it.y - (it.h || 10) / 2, d = top >= y - 2 ? top - y : (y - top) * 3
    return d + (lx != null ? Math.abs((it.x0 || 0) - lx) * 0.5 : 0) + (it.y + (it.h || 10) / 2 < y ? (it.h || 10) * 2 : 0)
  }
  const anchor = items.filter(it => it.s.trim()).sort((a, b) => rank(a) - rank(b))[0]
  try { // a figure or equation destination: the picture/formula box at that height owns the jump, not the paragraph above it
    const gap = b => !items.some(it => it.s.trim() && it.y > y && it.y < b.y0 && (lx == null || it.x0 + it.w >= b.x0 - 8)) // nothing printed between the destination and the box
    const vw = (items[0] && items[0].vw) || hPt * 0.7
    const box = pvImgMatch().filter(b => b.page === dest.page && b.y1 >= y - 4 && (b.y0 <= y + 12 || (b.y0 <= y + 60 * pvScale && gap(b))) && (lx == null || (lx >= b.x0 - vw * 0.45 && lx <= b.x1 + 8))) // a figure's location sits at its block top and left edge, the picture is centered one block gap lower
      .sort((a, b) => Math.abs(a.y0 - y) - Math.abs(b.y0 - y) || (lx == null ? 0 : Math.abs(a.x0 - lx) - Math.abs(b.x0 - lx)))[0]
    if (box) { const ok = await pvJumpSrc(box.src, 0); if (ok) { syncEdOff = -$('preview').clientHeight * 0.38; syncEdX = -1 } return }
    const eq = pvMathMatch().filter(m => m.page === dest.page && m.line.y1 >= y - 4 && m.line.y0 <= y + 60 * pvScale && gap(m.line)) // an equation destination: the formula right below it, not the paragraph after it
      .sort((a, b) => a.line.y0 - b.line.y0)[0]
    if (eq && (!anchor || anchor.y >= eq.line.y0 - 2)) {
      const at = eq.src.own && eq.src.own[0]
      const ok = await pvJumpSrc({ ...eq.src, line: at ? at.line : eq.src.line }, at ? at.at : 0)
      if (ok) { syncEdOff = -$('preview').clientHeight * 0.38; syncEdX = -1 }
      return
    }
  } catch (e) {}
  const needles = anchor ? pvClickNeedles(items, anchor, 0) : []
  const doc = docId, epoch = openN
  let ok = false // the text at the destination beats a page ratio (footnote notes, figures); a bibliography entry lives in its .bib file
  try { ok = needles.length ? await pvJumpBest(needles, hint, dest.page, anchor, true) : false } catch (e) { ok = false }
  if (doc !== docId || epoch !== openN) return
  if (!ok && !activeFile) { const gen = anchor ? pvGenLine(items, anchor, dest.page, hint) : -1; jumpPos(gen >= 0 ? gen : posOfLine(getT(), hint)) } // a generated title (bibliography, outline) belongs to its call
  syncEdOff = -$('preview').clientHeight * 0.38 // destination sits 12% below the preview top: scroll-follow starts there
  syncEdX = -1
}
function pvWordChar(c) { return !!c && /[\p{L}\p{N}]/u.test(c) } // whole words only: "pi" must never match inside "Typst"
function locateNear(t, s, hint) { // nearest whole-word hit to the hint line (short cell texts too)
  s = (s || '').trim()
  if (s.length < 2) return -1
  const hp = posOfLine(t, hint)
  let best = -1, bd = Infinity, p = -1
  while ((p = t.indexOf(s, p + 1)) >= 0) {
    if ((p && pvWordChar(t[p - 1])) || (p + s.length < t.length && pvWordChar(t[p + s.length]))) continue
    const dd = Math.abs(p - hp)
    if (dd < bd) { bd = dd; best = p }
  }
  return best
}
let syncFlashT = 0
function cmTop(pos) { // scrollTop that centers the line block under pos
  const b = cm.lineBlockAt(pos), sc = cm.scrollDOM
  return b.top + b.height / 2 - sc.clientHeight / 2
}
function cmGlide(pos) { // same rule as the preview: a real jump glides, a small step follows without restart
  try {
    const sc = cm.scrollDOM, y = cmTop(pos)
    if (Math.abs(y - sc.scrollTop) > 300) smoothScroll(sc, y)
    else smoothFollow(sc, y)
  } catch (e) {}
}
function cmJump(pos, holdPv, forcePv) { // smooth editor jump + brief line flash; holdPv: a preview click keeps the preview where it is; forcePv: explicit navigation
  if (syncT) { clearTimeout(syncT); syncT = 0 } // the jump owns the next sync, no stale cursor target
  const line = cm.state.doc.lineAt(Math.max(0, Math.min(cm.state.doc.length, pos)))
  const deco = Decoration.set([Decoration.line({ class: 'cm-syncLine' }).range(line.from)])
  syncSkip = true // this selection is the jump, not a reader cursor move
  try { cm.dispatch({ selection: { anchor: Math.max(line.from, Math.min(line.to, pos)) }, effects: [setSyncLine.of(deco)] }) } finally { syncSkip = false }
  cm.focus()
  cmGlide(pos)
  if (!holdPv) { syncView = -1; syncToPv(forcePv) } // outline/find jump: both panes start their glide in the same frame
  clearTimeout(syncFlashT)
  syncFlashT = setTimeout(() => { try { cm.dispatch({ effects: setSyncLine.of(Decoration.none) }) } catch (e) {} }, 850)
}
function jumpPos(pos) { cmJump(pos, true) } // preview click: editor glides, the preview stays put

function pvCharW(c) { // rough proportional widths: a straight character count picks the neighbour word
  if (c === ' ') return 0.25
  if ('iljtf'.includes(c)) return 0.3
  if ('mwMW'.includes(c)) return 0.8
  if (c >= 'A' && c <= 'Z') return 0.65
  if (c >= '0' && c <= '9') return 0.5
  if (".,;:!|'’".includes(c)) return 0.25
  if ('()[]'.includes(c)) return 0.33
  return 0.5
}
function pvTextW(s) { let w = 0; for (const c of s) w += pvCharW(c); return w }
function pvPxWords(cv, it, words) { // per-character boxes from rendered ink: justified spaces and real letter edges
  try {
    const n = words.length, ctx = n && cv.getContext ? cv.getContext('2d') : null
    if (!ctx) return null
    const px = cv.width / (it.vw || cv.width), py = cv.height / (it.vh || cv.height)
    const x0 = Math.max(0, Math.floor(it.x0 * px)), x1 = Math.min(cv.width, Math.ceil((it.x0 + it.w) * px))
    const y0 = Math.max(0, Math.floor((it.y - (it.h || 10) / 2) * py)), y1 = Math.min(cv.height, Math.ceil((it.y + (it.h || 10) / 2) * py))
    if (x1 - x0 < 2 || y1 - y0 < 2) return null
    const img = ctx.getImageData(x0, y0, x1 - x0, y1 - y0), W = img.width, H = img.height, d = img.data, ink = new Uint8Array(W)
    for (let x = 0; x < W; x++) for (let y = 0; y < H; y++) {
      const i = (y * W + x) * 4
      if (d[i + 3] > 24 && 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2] < 190) { ink[x] = 1; break }
    }
    const runs = []
    for (let x = 0; x < W; x++) {
      const last = runs[runs.length - 1]
      if (!ink[x]) continue
      if (last && last[1] === x - 1) last[1] = x
      else runs.push([x, x])
    }
    if (runs.length < n) return null // touching letters: no honest word boxes left
    const groups = runs.map(r => [r])
    const narrowest = () => {
      let g = 1, best = Infinity
      for (let i = 1; i < groups.length; i++) {
        const a = groups[i - 1][groups[i - 1].length - 1][1], b = groups[i][0][0]
        if (b - a < best) { best = b - a; g = i }
      }
      return g
    }
    while (groups.length > n) { // merge the narrowest gap: a letter gap, never a word space
      const g = narrowest()
      groups[g - 1] = groups[g - 1].concat(groups[g])
      groups.splice(g, 1)
    }
    return groups.map((g, wi) => pvCharBoxes(g, words[wi][0], x0))
  } catch (e) { return null }
}
function pvCharBoxes(runs, word, base) { // glyph runs -> one box per character (ligatures keep their letter count)
  const chars = [...word]
  let rs = runs.map(r => [r[0] + base, r[1] + base])
  while (rs.length > chars.length) { // i-dot, accents: merge the narrowest gap inside the glyph
    let g = 1, best = Infinity
    for (let i = 1; i < rs.length; i++) if (rs[i][0] - rs[i - 1][1] < best) { best = rs[i][0] - rs[i - 1][1]; g = i }
    rs[g - 1][1] = rs[g][1]
    rs.splice(g, 1)
  }
  if (rs.length === chars.length) return rs
  const start = rs.length ? rs[0][0] : base, end = rs.length ? rs[rs.length - 1][1] : base
  const total = chars.reduce((a, c) => a + pvCharW(c), 0) || 1
  let cum = 0
  return chars.map(c => {
    const a = start + (end - start) * cum / total
    cum += pvCharW(c)
    return [a, start + (end - start) * cum / total]
  })
}
function pvCharUnits(word, k) { // character index -> code units (never stop inside a surrogate pair)
  let i = 0
  for (const c of word) { if (!k--) break; i += c.length }
  return i
}
function pvClickChar(word, frac) { // proportional fallback when no canvas pixels are available
  let total = 0
  for (const c of word) total += pvCharW(c)
  const at = Math.max(0, Math.min(1, frac)) * total
  let cum = 0, k = 0
  for (const c of word) {
    if (at < cum + pvCharW(c) / 2) break
    cum += pvCharW(c)
    k++
  }
  return pvCharUnits(word, k)
}
function pvClickEstimate(raw, at) { // proportional column for an offset inside a run
  const lead = raw.length - raw.trimStart().length
  let cum = 0, best = 0, bd = Infinity, inside = 0
  for (let i = 0; i < raw.length;) {
    if (/\s/.test(raw[i])) { cum += pvCharW(raw[i]); i++; continue }
    const from = i, begin = cum
    while (i < raw.length && !/\s/.test(raw[i])) { cum += pvCharW(raw[i]); i++ }
    const d = at < begin ? begin - at : at > cum ? at - cum : 0
    if (d < bd) { bd = d; best = from - lead; inside = pvClickChar(raw.slice(from, i), (at - begin) / Math.max(0.01, cum - begin)) }
  }
  return best + inside
}
function pvClickCol(it, x, y, cssW, cssH, baseW, cv) { // click x -> the clicked letter, not the word start
  const raw = it.s || '', body = raw.trim()
  if (!body) return 0
  if (it.rot) { // rotated run: project the click onto its own baseline, then estimate the letter
    const sx = cssW / (it.vw || baseW || 1), sy = cssH / (it.vh || 1)
    const c = Math.cos(it.ang || 0), s = Math.sin(it.ang || 0)
    const u = (x / sx - (it.x0 || 0)) * c + (y / sy - (it.y0 || it.y || 0)) * s
    if ((it.w || 0) <= 0) return 0
    return pvClickEstimate(raw, Math.max(0, Math.min(1, u / it.w)) * pvTextW(raw))
  }
  const words = [...body.matchAll(/\S+/g)]
  const boxes = cv && !/[\u0590-\u08FF\uFB1D-\uFDFF\uFE70-\uFEFF]/.test(body) ? pvPxWords(cv, it, words) : null
  if (boxes) { // rendered pixels: real word edges and real letter boundaries, even across justified spaces
    const at = x * (cv.width / cssW), span = b => [b[0][0], b[b.length - 1][1]]
    let best = 0, bd = Infinity
    for (let i = 0; i < boxes.length; i++) {
      const b = span(boxes[i]), d = at < b[0] ? b[0] - at : at > b[1] ? at - b[1] : 0
      if (d < bd) { bd = d; best = i } // ties go left: the end of a word belongs to it
    }
    const b = boxes[best]
    let k = 0, kb = Infinity
    for (let i = 0; i <= b.length; i++) { // caret boundaries: every letter start plus the word end
      const bx = i < b.length ? b[i][0] : b[b.length - 1][1]
      const d = Math.abs(at - bx)
      if (d <= kb) { kb = d; k = i } // ties go right: the right half of a letter puts the caret behind it
    }
    return words[best].index + pvCharUnits(words[best][0], k)
  }
  const scale = cssW / (it.vw || baseW || 1), w = (it.w || 0) * scale
  if (w <= 0) return 0
  let frac = (x - (it.x0 || 0) * scale) / w
  if (/[֐-ࣿיִ-﷿ﹰ-﻿]/.test(body)) frac = 1 - frac // right-to-left run: the logical start sits on the right edge
  return pvClickEstimate(raw, frac * pvTextW(raw)) // estimate when the canvas was evicted
}
function pvItemDist(it, x, y, sx, sy) { // CSS distance to the text box, never to its center: long lines stay clickable everywhere
  if (it.rot) { // rotated run: distance in its own baseline frame, not to the axis-aligned shadow
    const c = Math.cos(it.ang || 0), s = Math.sin(it.ang || 0)
    const u = (x / sx - (it.x0 || 0)) * c + (y / sy - (it.y0 || it.y || 0)) * s
    const v = (x / sx - (it.x0 || 0)) * s - (y / sy - (it.y0 || it.y || 0)) * c
    const du = u < 0 ? -u : u > (it.w || 0) ? u - it.w : 0
    const dv = v < 0 ? -v : v > (it.h || 10) ? v - it.h : 0
    return (du * sx) * (du * sx) + (dv * sy) * (dv * sy)
  }
  const x0 = (it.x0 || 0) * sx, x1 = x0 + (it.w || 0) * sx
  const yc = (it.y || 0) * sy, hh = Math.max(4, (it.h || 10) * sy / 2)
  const dx = x < x0 ? x0 - x : x > x1 ? x - x1 : 0
  const dy = y < yc - hh ? yc - hh - y : y > yc + hh ? y - yc - hh : 0
  return dx * dx + dy * dy
}
function pvNearItems(items, x, y, sx, sy, skip, max) { // nearest readable text: a drawing without text still lands on its caption
  return items
    .filter(it => it !== skip && /\p{L}/u.test(it.s || '')) // single-letter words are text too; numbers stay out
    .map(it => ({ it, d: pvItemDist(it, x, y, sx, sy) }))
    .filter(o => !max || o.d <= max * max) // max (CSS px): text that far away is another spot, not this click
    .sort((a, b) => a.d - b.d)
    .slice(0, 8)
}
function pvGenLine(items, it, pi, hint, col) { // clicked text with no source words: the call that generated it sits between the owned text above and below
  const txt = getT(), lines = txt.split('\n'), mask = srcMask(txt).split('\n')
  if (col > 0) { // "The value is 5": the words before the click are in the source, the computed token is the expression right behind them
    const left = pvNormCaret(String(it.s || '').slice(0, col)).s.split(' ').filter(w => /\p{L}/u.test(w)).join(' ')
    const p = /\p{L}{3}/u.test(left) ? pvViewPos(txt, left, left.length, hint) : -1
    if (p >= 0) {
      const at = txt.lastIndexOf('\n', p - 1) + 1, li = txt.slice(0, at).split('\n').length - 1, m = mask[li] || ''
      for (let j = p - at; j < m.length; j++) if (m[j] === '#') return at + j
    }
  }
  const block = new Set(pvBlockLines(items, it)) // the generated paragraph itself owns nothing
  const order = items.filter(o => o === it || (o.s.trim() && !o.rot && /\p{L}{2}/u.test(o.s) && !block.has(o))).sort((a, b) => a.y - b.y || a.x0 - b.x0)
  const k = order.indexOf(it)
  if (k < 0) return -1
  const lineAt = p => txt.slice(0, p).split('\n').length
  const own = o => { const p = pvHerePos(pvClickNeedles(items, o, 0), hint, pi, null, true); return p >= 0 ? { line: lineAt(p), y: o.y } : null }
  let a = null, b = null, ia = -1, ib = order.length
  for (let i = k - 1, n = 0; i >= 0 && n < 16 && !a; i--, n++) { a = own(order[i]); if (a) ia = i }
  for (let i = k + 1, n = 0; i < order.length && n < 16 && !b; i++, n++) {
    const o = own(order[i])
    if (o && (!a || o.line > a.line)) { b = o; ib = i } // a footnote at the page bottom comes from a line above: not the text below
  }
  if (!a && !b) return -1
  const from = a ? a.line + 1 : 1, to = b ? b.line - 1 : lines.length
  if (to < from) return -1 // the neighbours are adjacent source lines: the text came from inside one of them
  const calls = []
  for (let ln = from; ln <= to; ln++) {
    const s = (mask[ln - 1] || '').trim()
    if (/^#(?!set\b|show\b|let\b|import\b|include\b)[\p{L}_]/u.test(s) || /^#[({[]/.test(s)) calls.push(ln)
  }
  if (!calls.length) return -1
  const groups = [] // generated blocks between the owned neighbours, in reading order: the n-th block is the n-th call
  let mine = -1
  for (let i = ia + 1; i < ib; i++) {
    const o = order[i], last = groups[groups.length - 1]
    if (!last || !last.has(o)) groups.push(new Set(o === it ? block : pvBlockLines(items, o)))
    if (o === it) mine = groups.length - 1
  }
  let ln
  if (groups.length === calls.length && mine >= 0) ln = calls[mine]
  else if (a && b) { // several generators in the gap and no clean count: the click height picks one
    const f = Math.max(0, Math.min(0.999, (it.y - a.y) / Math.max(1, b.y - a.y)))
    ln = calls[Math.floor(f * calls.length)]
  } else ln = a ? calls[0] : calls[calls.length - 1]
  return posOfLine(txt, ln) + ((lines[ln - 1] || '').length - (lines[ln - 1] || '').trimStart().length)
}
function pvOlEq(pdfText, srcTitle) { // same heading; a numbering prefix on the PDF side is fine
  const x = syncPlain(pdfText), y = syncPlain(srcTitle)
  if (!x || !y) return false
  return x === y || x.replace(/^(?:\d+(?:\s+\d+)*|[a-z]|[ivxlcdm]+)\s+/, '') === y
}
function pvOutlineClick(pi, items, x, y, sx, sy) { // blank spot in the rendered #outline(): keep the cursor at the outline, not on a heading below
  const oi = srcOutlineLine(getT()) // real #outline( only: a fenced code sample is not the outline
  if (!oi) return 0
  const heads = []
  let srcs = [{ key: '', text: getT() }]
  try { srcs = pvSrcList() } catch (e) {}
  for (const src of srcs) if (src && src.text && (!src.key || /\.typ$/i.test(src.key))) for (const h of srcHeadings(src.text)) if (h.title) heads.push(h.title) // included chapters have outline entries too
  const pad = 12 // one blank line around an entry still belongs to the outline
  let first = null
  for (const L of pvLinks[pi] || []) {
    if (!L.dest) continue // external links are not outline entries
    const mid = (L.y0 + L.y1) / 2, hh = Math.max(6, (L.y1 - L.y0) / 2 + 2)
    const entry = items.some(it => {
      if (it.x0 >= L.x1 || it.x0 + it.w <= L.x0 || Math.abs(it.y - mid) > hh) return false
      return heads.some(h => pvOlEq(it.s, h)) // exact heading, not a loose substring
    })
    if (!entry) continue
    if (!first || L.y0 < first.y0) first = L
    if (x >= L.x0 * sx - pad && x <= L.x1 * sx + pad && y >= L.y0 * sy - pad && y <= L.y1 * sy + pad) return oi
  }
  if (!first) return 0
  const eh = Math.max(10, first.y1 - first.y0) // the outline title ("Contents") right above the first entry is generated by #outline() too
  const title = items.filter(it => it.s.trim() && !it.rot && it.y < first.y0 && first.y0 - (it.y + (it.h || 10) / 2) <= eh * 3)
    .sort((a, b) => b.y - a.y)[0]
  if (!title || heads.some(h => pvOlEq(title.s, h)) || pvItemDist(title, x, y, sx, sy) > 16) return 0
  try { if (pvHerePos(pvClickNeedles(items, title, 0), oi, pi, null, true) >= 0) return 0 } catch (e) {} // a title the source spells out (#outline(title: [..])) maps to its own words
  return oi
}
$('preview').addEventListener('click', async e => { // preview -> editor: text anchors first (tables!), then nearest text, else section
  if (e.target.closest && e.target.closest('.pvLinks a')) return // PDF link: native open or internal jump, never source sync
  if (window.Present?.isOn()) return // slides: a preview click must not move the hidden editor
  if (!syncOn || !docId || tplName) return
  const pv = $('preview')
  smoothStop(pv) // an explicit click wins over a jump or follow still in flight
  const cv = e.target.closest ? e.target.closest('canvas') : null
  const pi = cv && pvTexts.length ? pvCanvasList().indexOf(cv) : -1 // canvas only, ignore .empty divs
  let at = null
  if (cv && pvTexts.length) {
    const items = pi >= 0 ? (pvTexts[pi] || []) : []
    if (!items.length && !pvTextDone[pi]) return // render between reset and swap: the old canvas has no anchors yet
    const r = cv.getBoundingClientRect()
    const x = e.clientX - r.left, y = e.clientY - r.top
    const vw = (items[0] && items[0].vw) || cv.width || 1
    const vh = (items[0] && items[0].vh) || cv.height || 1
    const sx = r.width / vw, sy = r.height / vh
    syncEdOff = Math.max(1 - pv.clientHeight / 2, Math.min(pv.clientHeight / 2 - 1, e.clientY - (pv.getBoundingClientRect().top + pv.clientHeight / 2)))
    syncEdX = x / (r.width || 1) // the clicked column keeps owning follow on two-column pages
    if (pi === 0 && items.length && !activeFile) { // above the first heading: the document top (#outline/title), not the first heading (page 1 belongs to the document text)
      const first = srcHeadings(getT())[0]
      let topY = Infinity
      if (first) {
        const pre = srcMask(getT()).split('\n').slice(0, first.line - 1).some(l => { // comments/labels/statements are not visible text
          const s = l.trim()
          return !!s && !pvCmdLine(s) && !/^#(?:set|show|let|import|include)\b/.test(s) && !!syncShow(s).trim()
        })
        if (!pre) {
          const h = syncAnchor(getT().split('\n'), first.line, pvTexts, pvSecAtLine(first.line))
          if (h && h.pi === 0) topY = (h.it.y - (h.it.h || 10) / 2) * sy
          else { // first heading on a later page: page 1 is the generated outline, its first entry is the boundary
            const links = (pvLinks[0] || []).filter(L => L.dest)
            if (links.length) topY = Math.min(...links.map(L => L.y0)) * sy
          }
        }
      } else for (const it of items) if (!it.rot && it.s.trim()) topY = Math.min(topY, (it.y - (it.h || 10) / 2) * sy) // no heading: only the margin above all text
      const onText = items.some(it => it.s.trim() && pvItemDist(it, x, y, sx, sy) <= 4) // a page header is text, not the margin above the heading
      if (!onText && isFinite(topY) && y < topY) {
        const lines = getT().split('\n')
        let ln = 1
        while (ln < lines.length && !lines[ln - 1].trim()) ln++
        syncPage = 0
        jumpPos(posOfLine(getT(), ln))
        return
      }
    }
    const ol = pvOutlineClick(pi, items, x, y, sx, sy)
    if (ol) { syncPage = pi; jumpPos(posOfLine(getT(), ol)); return } // beside an outline entry: stay at the outline line
    const rr = CLICK_PX / 2 // CSS pixels, independent of zoom and render scale
    let best = null, bd = rr * rr
    for (const it of items) {
      if (!it.s.trim()) continue // rotated runs carry their own baseline angle
      const dd = pvItemDist(it, x, y, sx, sy)
      if (dd < bd) { bd = dd; best = it }
    }
    const yv = best ? best.y : y / (r.height || 1) * vh
    at = pi >= 0 ? pvSecAtY(pi, yv) : null
    const total = cm.state.doc.lines || 1
    const hintAt = y => pvPageHint(pi, total, pvTexts.length, at, y / vh)
    const file0 = activeFile
    const mh = pvMathAt(pi, x, y, sx, sy) // display formula: its source line beats glyph needles
    if (mh && await pvJumpMath(mh)) return
    const ih = pvImgAt(pi, x, y, sx, sy)
    const onText = best && bd <= 4 // really on the glyphs, not merely near them (a caption below a figure)
    if (ih && !onText) { if (await pvJumpSrc(ih.src, 0)) return } // inside the image: the image call owns the click
    if (best) {
      const hint = hintAt(yv)
      const col = pvClickCol(best, x, y, r.width, r.height, cv.width, cv)
      if (await pvJumpBest(pvClickNeedles(items, best, col), hint, pi, best)) return
    }
    if (ih && await pvJumpSrc(ih.src, 0)) return
    if (!activeFile && !ih && best && bd <= 4 && !/\p{L}/u.test(best.s) && (yv < vh * 0.07 || yv > vh * 0.93)) { // a click on a generated page number in the margin: the page setup owns it, not the last paragraph (text near the margin keeps its own line)
      const set = srcMask(getT()).split('\n').findIndex(l => /#set\s+page\s*\(/.test(l))
      if (set >= 0) { syncPage = pi; jumpPos(posOfLine(getT(), set + 1)); return }
    }
    if (onText && activeFile === file0 && yv > vh * 0.07 && yv < vh * 0.93 && /\p{L}{3}/u.test(best.s)) { // generated prose (#lorem, a function, a package): the code line between the text above and below that the source owns; a chart label ("A", "40") keeps its caption
      const gen = pvGenLine(items, best, pi, hintAt(yv), pvClickCol(best, x, y, r.width, r.height, cv.width, cv))
      if (gen >= 0) { syncPage = pi; jumpPos(gen); return }
    }
    if (!best || activeFile === file0) { // no text under the click: nearby readable text still owns the spot
      const cap = pvImgHit(pi, x, y, sx, sy) ? CLICK_PX * 1.5 : 0 // inside a picture: no far paragraph as stand-in for its missing source
      for (const { it: near } of pvNearItems(items, x, y, sx, sy, best, cap)) {
        const col = pvClickCol(near, x, y, r.width, r.height, cv.width, cv) // blank space above/below a line still has a word column
        if (pvJumpHere(pvClickNeedles(items, near, col), hintAt(near.y), pi, near)) return
      }
    }
    syncPage = pi >= 0 ? pi : syncPage // even without hit: next sync starts on click page
    if (activeFile !== file0) return // the jump already tried another file: no section guess
    if (activeFile) return // image/margin click in a file tab: ratio maps main layout onto file text
  } else if (activeFile) return // no canvas hit in a file tab: nowhere honest to go
  if (at && at.sec) { // no source text within reach: the section start is the honest anchor
    jumpPos(posOfLine(getT(), at.sec.line))
    return
  }
  if (pvSrcList().length > 1) return // included files destroy a main-line/layout ratio
  const r = pv.getBoundingClientRect() // fallback for a single source only
  const ratio = Math.max(0, Math.min(1, (e.clientY - r.top + pv.scrollTop) / pv.scrollHeight))
  const lines = getT().split('\n'), total = lines.length || 1
  let line = Math.max(1, Math.min(total, Math.round(ratio * total) + 1))
  while (line > 1 && !lines[line - 1].trim()) line-- // snap to paragraph start
  jumpPos(posOfLine(getT(), line))
})
$('syncBtn').onclick = () => { syncOn = !syncOn; lsSet('typst_follow_all', followAll ? 1 : 0); lsSet('typst_sync', syncOn ? 1 : 0); applySyncBtn(); try { updPos() } catch (e) {} } // eye first: a dropped second write must not re-arm the legacy fallback
$('followBtn').onclick = () => { followAll = !followAll; lsSet('typst_follow_all', followAll ? 1 : 0); applyFollowBtn() }
applySyncBtn() // F25: persisted follow state on boot
applyFollowBtn()
try { updPos() } catch (e) {} // F24: status filled before first keystroke
function fitPv() { // fit paper exactly to preview width, centered via margin
  const c = document.querySelector('#preview canvas')
  const avail = $('preview').clientWidth - 32
  if (c && avail > 0) {
    pvZoom = Math.max(PV_MIN, Math.min(PV_MAX, Math.round(avail / (c.width / 2) * 100)))
    applyPv(); saveSet()
  }
}
function sizeCanvas(c) { // CSS width from zoom only, never touch backing (canvas.width)
  if (c.closest('.pvPage')) { if (c.closest('.pvPage').dataset.done) pvFitCanvas(c); return }
  c.style.width = (c.width / (+c.dataset.s || 2) * pvZoom / 100) + 'px'
  c.style.maxWidth = document.body.classList.contains('read') ? (8.2 * pvZoom) + 'px' : 'none' // none: zoom may exceed container, preview scrolls
  c.style.height = 'auto'
}
$('fMinus').onclick = () => stepEd(-ED_STEP)
$('fPlus').onclick = () => stepEd(ED_STEP)
$('zMinus').onclick = () => stepPv(-PV_STEP)
$('zPlus').onclick = () => stepPv(PV_STEP)
$('fitBtn').onclick = fitPv
applyEd() // apply saved font at once
applyPv()
updExports()
closeView() // boot with no doc: onboarding card, no blobs, no comment button, read-only
try { if (matchMedia('(max-width:720px)').matches) document.body.classList.add('noside') } catch (e) {} // mobile: sidebar closed
updScrim()
