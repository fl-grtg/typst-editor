// --- Settings: click on user box (font/zoom, profile, password, account) ---
document.body.appendChild($('setPop'))
$('userMain').onclick = e => {
  e.stopPropagation()
  if (showPop('setPop')) { apiKeys = null; sessList = null; renderSettings() }
}
kb($('userMain'), () => $('userMain').click())
let apiKeys = null, apiKeysLoading = false, lastKeySecret = ''
let settingsCategory = 'account'
const settingsError = message => toast(message || t('common.requestFailed'), null, null, 5000, 'error')
const AGENT_PROMPT = 'Install the Typst Editor skill from https://raw.githubusercontent.com/fl-grtg/typst-editor/main/skills/typst-editor/SKILL.md and follow its section 0 to connect to my Typst server. Ask me for server URL and API key if missing.'
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
  window.Present?.relabel()
  try { if (user && typeof sidebar === 'function') sidebar().catch(() => {}) } catch (e) {}
}
function setLang(lang) {
  if (lang !== 'de' && lang !== 'en') return
  langCur = lang
  try { window.I18N_LANG = langCur } catch (e) {}
  lsSet(LANG_KEY, langCur)
  refreshLang()
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
  top.append(title, close)
  card.append(top, el('p', 'keySecretHint', t('settings.keyOnceHint')), value, copy)
  overlay.appendChild(card); document.body.appendChild(overlay); modalInert(true)
  const done = () => { lastKeySecret = ''; modalInert(false); overlay.remove(); if (prev && document.contains(prev)) prev.focus() }
  close.onclick = done
  overlay.addEventListener('keydown', e => {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); return }
    if (e.key !== 'Tab') return
    const focusable = [close, value, copy], i = focusable.indexOf(document.activeElement)
    if (e.shiftKey && i <= 0) { e.preventDefault(); focusable[focusable.length - 1].focus() }
    else if (!e.shiftKey && (i < 0 || i === focusable.length - 1)) { e.preventDefault(); focusable[0].focus() }
  })
  setTimeout(() => { value.focus(); value.select() }, 30)
}
function renderSettings() {
  const p = $('setPop')
  const fieldValues = new Map([...p.querySelectorAll('[data-setting-field]')].map(input => [input.dataset.settingField, input.value]))
  p.replaceChildren()
  const sec = (...kids) => { const d = el('div', 'sec'); kids.forEach(k => d.appendChild(k)); return d }
  const grp = (title, ...secs) => { const w = el('div', 'grp'); w.appendChild(el('h4', null, title)); secs.forEach(s => w.appendChild(s)); return w }
  const keepField = (input, key) => {
    input.dataset.settingField = key
    if (fieldValues.has(key)) input.value = fieldValues.get(key)
    return input
  }
  const categories = [
    ['account', 'settings.navAccount'], ['editor', 'settings.navEditor'], ['sessions', 'settings.navSessions'],
    ['api', 'settings.navApi'], ['storage', 'settings.navStorage']
  ]
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
    b.onclick = () => activateSettingsCategory(id)
    buttons[id] = b; nav.appendChild(b); content.appendChild(views[id])
  })
  rail.appendChild(nav); layout.append(rail, content); p.appendChild(layout)
  const activateSettingsCategory = id => {
    settingsCategory = id
    categories.forEach(([key]) => {
      buttons[key].classList.toggle('active', key === id)
      buttons[key].setAttribute('aria-current', key === id ? 'page' : 'false')
      views[key].classList.toggle('active', key === id)
    })
  }
  activateSettingsCategory(settingsCategory)
  const fr = el('div', 'row settingRow'); fr.append(el('label', null, t('settings.editorFontSize')))
  const fm = el('button', 'step', '−'); fm.title = t('settings.fontMinus'); fm.setAttribute('aria-label', fm.title); fm.disabled = edSize <= ED_MIN
  fm.onclick = e => { e.stopPropagation(); stepEd(-ED_STEP); renderSettings() }
  const fontControls = el('div', 'settingControlGroup settingStepper')
  fontControls.append(fm, el('span', 'val', edSize + 'px'))
  const fp = el('button', 'step', '+'); fp.title = t('settings.fontPlus'); fp.setAttribute('aria-label', fp.title); fp.disabled = edSize >= ED_MAX
  fp.onclick = e => { e.stopPropagation(); stepEd(ED_STEP); renderSettings() }
  fontControls.appendChild(fp); fr.appendChild(fontControls)
  const zr = el('div', 'row settingRow'); zr.append(el('label', null, t('settings.previewZoom')))
  const zm = el('button', 'step', '−'); zm.title = t('settings.zoomMinus'); zm.setAttribute('aria-label', zm.title); zm.disabled = pvZoom <= PV_MIN
  zm.onclick = e => { e.stopPropagation(); stepPv(-PV_STEP); renderSettings() }
  const zoomControls = el('div', 'settingControlGroup settingStepper')
  zoomControls.append(zm, el('span', 'val', pvZoom + ' %'))
  const zp = el('button', 'step', '+'); zp.title = t('settings.zoomPlus'); zp.setAttribute('aria-label', zp.title); zp.disabled = pvZoom >= PV_MAX
  zp.onclick = e => { e.stopPropagation(); stepPv(PV_STEP); renderSettings() }
  zoomControls.appendChild(zp); zr.appendChild(zoomControls)
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
  nok.onclick = () => { if (nok.disabled) return; if (!nn.value.trim() || !npw.value) { settingsError(t('settings.needNamePw')); return } nok.disabled = true; api('POST', '/api/me/name',
    { name: nn.value.trim(), password: npw.value })
    .then(d => { const spelling = spellStored(); nn.value = ''; npw.value = ''; user = d.user; loadSpell(spelling); paintMe(); sidebar(); renderSettings() })
    .catch(e => settingsError(e.message)).finally(() => nok.disabled = false) }
  nr.append(nameField, namePasswordField, nok); put('account', grp(t('settings.nameGroup'), sec(nr)))
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
  const es = el('select'); es.setAttribute('aria-label', t('settings.expiry'))
  ;[[t('settings.never'), ''], [t('settings.expDays', { n: 30 }), '30'], [t('settings.expDays', { n: 90 }), '90'], [t('settings.expDays', { n: 365 }), '365']].forEach(([label, v]) => { const o = el('option', null, label); o.value = v; es.appendChild(o) })
  const cb = el('button', null, t('common.create'))
  cb.onclick = e => {
    e.stopPropagation() // sync renderSettings below detaches e.target: without this the document outside-click closer hides setPop
    if (cb.disabled) return
    if (!kn.value.trim()) { settingsError(t('settings.needKeyName')); return }
    cb.disabled = true
    api('POST', '/api/keys', { name: kn.value.trim(), role: rs.value, expires_in_days: es.value ? +es.value : null })
      .then(d => { // no refetch: one POST per create, list updates locally (was POST+GET, 2 keys-bucket hits)
        lastKeySecret = d.key
        kn.value = ''
        apiKeys = [...(apiKeys || []), { id: d.id, name: d.name, prefix: d.prefix, role: d.role, expires_at: d.expires_at || '', last_used: '', created_at: '' }]
      })
      .catch(e => settingsError(e.message)).finally(() => { renderSettings(); showKeySecret() })
  }
  const cr = el('div', 'row keyCreateRow'); cr.append(kn, rs, es, cb)
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
      const pc = el('code', null, k.prefix || '')
      pc.style.fontSize = '11.5px'; pc.style.overflowWrap = 'anywhere'; pc.style.minWidth = '0'
      const eS = el('span', 'val', t('settings.expires', { date: shortD(k.expires_at) })); eS.title = k.expires_at || t('settings.never')
      eS.style.fontSize = '12px'
      sub.append(pc, el('span', null, t(k.role === 'editor' ? 'common.roleEditor' : 'settings.roleReviewer')), eS)
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
    if (!dpw.value) { settingsError(t('settings.needPwDel')); return }
    if (!await ask(t('settings.delAccount'), { noInput: true, ok: t('common.delete'), danger: true })) return
    if (!await ask(t('settings.delSure'), { ph: 'DELETE' }).then(v => v === 'DELETE')) return
    db.disabled = true
    api('POST', '/api/me/delete', { password: dpw.value })
      .then(() => { location.reload() })
      .catch(e => settingsError(e.message)).finally(() => db.disabled = false)
  }
  dr.append(deletePasswordField, db); put('account', grp(t('settings.deleteAccount'), sec(dr)))
}
new MutationObserver(() => {
  const open = $('setPop').style.display !== 'none'
  document.body.classList.toggle('settings-open', open)
  if (!open) $('setPop').querySelectorAll('input[type="password"]').forEach(input => { input.value = '' })
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
function stepPv(d) { pvZoom = Math.max(PV_MIN, Math.min(PV_MAX, pvZoom + d)); applyPv(); saveSet() }
function stepEd(d) { edSize = Math.max(ED_MIN, Math.min(ED_MAX, edSize + d)); applyEd(); saveSet() }
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
function queueSyncEd() { // preview scroll -> editor view: throttled, never moves the cursor
  if (!followAll || !docId || tplName || activeFile) return
  if (syncEdT) return
  syncEdT = setTimeout(() => { syncEdT = 0; syncToEd() }, SYNC_MS)
}
function syncToEd() {
  if (!followAll || !docId || tplName || activeFile) return
  const pv = $('preview')
  if (!pv.clientHeight || document.body.classList.contains('editonly')) return
  const pi = pvViewPage(pv, syncEdOff), slot = pi >= 0 ? pv.querySelectorAll('.pvPage')[pi] : null
  if (!slot) return
  if (!(pvTexts[pi] || []).length) { syncEdMiss = !pvTextDone[pi]; return } // pvTextAll retries once; a page without text is done
  syncEdMiss = false
  const pr = pv.getBoundingClientRect(), sr = slot.getBoundingClientRect()
  const frac = Math.max(0, Math.min(1, (pr.top + pv.clientHeight / 2 + syncEdOff - sr.top) / (sr.height || 1)))
  const vh = pvTexts[pi][0].vh || 1
  const line = pvPageHint(pi, cm.state.doc.lines || 1, pvTexts.length, pvSecAtY(pi, frac * vh), frac)
  const items = pvTexts[pi], vw = items[0].vw || 1
  const near = pvNearItems(items, (syncEdX >= 0 ? syncEdX : 0.5) * vw, frac * vh, 1, 1, null) // no running header/footer, no needle-less lone letters
    .filter(({ it }) => it.y >= vh * 0.05 && it.y <= vh * 0.95
      && (syncText(it.s || '').length >= 4 || pvBlockLines(items, it).length > 1)).slice(0, 3)
  for (const { it } of near) { // real text under the reading point: exact, even inside large figures
    const pos = pvHerePos(pvClickNeedles(items, it, 0), line, pi, it)
    if (pos < 0) continue
    const ln = cm.state.doc.lineAt(pos).number, sec = pvSecAtLine(ln)
    if (!sec ? pi === 0 : sec.page <= pi && pi <= sec.endPage) { smoothFollow(cm.scrollDOM, cmTop(pos)); return } // another page's text (header, repeated title): not this spot
  }
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
    const f = ((pi - at.sec.page) + f0) / Math.max(1, span)
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
function pvPosIn(txt, s, off, hint) { // exact needle first, then its words across source line breaks and markup
  const at = locateNear(txt, s, hint)
  if (at >= 0) return at + off
  const words = pvNormWords(s)
  if (!words.length) return -1
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
function pvHerePos(needles, hint, pi, anchor) { // source position of the best needle in the current file; -1: none
  const list = (needles || []).filter(n => n && n.s && n.s.trim().length >= 2)
  const cur = activeFile || ''
  for (const nd of list) {
    const s = nd.s.trim(), off = Math.max(0, Math.min(nd.off || 0, s.length)) // clicked column inside the PDF line
    if (!cur && anchor) { // heading clicks: the PDF line's own height decides between repeated titles
      const lines = getT().split('\n'), matches = []
      let pos = 0
      lines.forEach((text, i) => {
        if (/^\s*=+\s/.test(text) && syncPlain(text).includes(syncPlain(s))) {
          const hit = syncAnchor(lines, i + 1, pvTexts, pvSecAtLine(i + 1))
          if (hit && hit.pi === pi && hit.items.includes(anchor)) {
            const at = text.indexOf(s)
            matches.push({ pos: at >= 0 ? pos + at + off : pos, distance: Math.abs(hit.it.y - anchor.y) })
          }
        }
        pos += text.length + 1
      })
      matches.sort((a, b) => a.distance - b.distance)
      if (matches.length && (matches.length === 1 || matches[0].distance < matches[1].distance)) return matches[0].pos
      if (matches.length > 1) continue
    }
    const at = pvPosIn(getT(), s, off, hint)
    if (at >= 0) return at
  }
  return -1
}
function pvJumpHere(needles, hint, pi, anchor) { // current file: exact word first, then the clicked word of a reflowed run
  const pos = pvHerePos(needles, hint, pi, anchor)
  if (pos < 0) return false
  syncPage = pi
  jumpPos(pos)
  return true
}
async function pvJumpBest(needles, hint, pi, anchor) { // current file, else the unique owner, else stay
  const list = (needles || []).filter(n => n && n.s && n.s.trim().length >= 2)
  if (!list.length) return false
  if (pvJumpHere(list, hint, pi, anchor)) return true
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
      const at = pvPosIn(txt, s, off, h2)
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
      const at = pvPosIn(t, s, off, h2)
      if (at >= 0) { jumpPos(at); return true }
    }
  }
  return false
}
function pvCaptionCut(s) { // Typst adds "Figure 1: " / "Table 1: " in front of a caption that the source does not have
  const m = String(s || '').match(/^(?:figure|table|listing|algorithm|equation|diagram|chart|abbildung|tabelle|diagramm|gleichung|liste)\s+\d+(?:\.\d+)*\s*[:.]\s*/i)
  return m ? m[0].length : 0
}
function pvBlockLines(items, it) { // paragraph around the click: same left edge, same size, normal line step
  const x = it.x0 || 0, h = Math.max(1, it.h || 10)
  const same = items.filter(o => o.s && o.s.trim() && !o.rot
    && Math.abs((o.x0 || 0) - x) < 1 && Math.abs((o.h || 0) - h) < 3).sort((a, b) => a.y - b.y)
  const i = same.indexOf(it)
  if (i < 0) return [it]
  const step = (a, b) => { const dy = (b.y || 0) - (a.y || 0); return dy > 1 && dy <= h * 1.8 } // generous leading still one paragraph
  let a = i, b = i
  while (a > 0 && step(same[a - 1], same[a])) a--
  while (b < same.length - 1 && step(same[b], same[b + 1])) b++
  return same.slice(a, b + 1)
}
function pvBlockNeedle(items, it, col) { // whole paragraph: a wrapped, repeated line is ambiguous on its own
  const block = pvBlockLines(items, it)
  if (block.length < 2) return []
  return [false, true].map(drop => { // real compound first ("E-Mail"), automatic hyphenation second ("Silbentrennung")
    let s = '', off = 0, soft = false
    for (const o of block) {
      const t = String(o.s || '').trim()
      if (!t) continue
      if (s && soft && drop) s = s.slice(0, -1) // the source word continues on the next line
      const sep = s && !soft ? 1 : 0
      if (o === it) off = s.length + sep + (col || 0)
      s += (sep ? ' ' : '') + t
      soft = /[-\u2010\u00ad]$/.test(t)
    }
    const cut = pvCaptionCut(s)
    return { s: s.slice(cut), off: Math.max(0, off - cut) }
  })
}
function pvClickNeedles(items, it, col) { // clicked item first; short cells and math glyphs add their PDF line
  const out = [], seen = new Set()
  const add = (s, off) => {
    s = String(s || '').trim()
    const norm = syncText(s)
    if (norm.length < 4 || seen.has(norm)) return false
    seen.add(norm)
    out.push({ s, off: Math.max(0, Math.min(s.length, off || 0)) })
    return true
  }
  const raw = String(it.s || '').trim(), cut = pvCaptionCut(raw), body = raw.slice(cut)
  for (const blk of pvBlockNeedle(items, it, col)) add(blk.s, blk.off) // paragraph context first: prose wraps one source line over several PDF lines
  if (/\p{L}/u.test(body)) add(body, (col || 0) - cut)
  if (/\p{L}{3}/u.test(body)) return out // a real word needs no line guessing
  for (const tol of [10, 20]) { // short cells, numbers and math glyphs: the row is the context
    const line = items.filter(o => !o.rot && Math.abs(o.y - it.y) <= tol).sort((a, b) => a.x0 - b.x0)
    let s = '', off = 0
    for (const o of line) {
      const t = String(o.s || '').trim()
      if (!t) continue
      if (o === it) off = s.length + (s ? 1 : 0) + (col || 0)
      s += (s ? ' ' : '') + t
    }
    const cut2 = pvCaptionCut(s), text = s.slice(cut2)
    if (/\p{L}{3}/u.test(text) && add(text, off - cut2)) break
  }
  return out
}
function syncText(text) {
  return text.normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim() // NFKC first: 𝐸 -> E -> e
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
    const n = line.slice(i, j).normalize('NFKC').toLowerCase()
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
  if (!raw || pvCmdLine(raw)) return null // "#figure(" must never match a generated "Figure 1:" caption prefix
  const head = raw.match(/^(=+)\s+(.+)$/)
  if (head) raw = head[2] // heading: the title, not the "=" markers
  const cap = !head && /^(?:caption\s*:|#(?:figure|table|image|listing|algorithm)\b)/.test(raw) && raw.match(/caption\s*:\s*\[([^\]]*)\]/) // a real caption option, not the word in prose
  raw = cap ? cap[1] : raw.replace(/^caption\s*:\s*/, '')
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
    const text = syncText(it.s || '')
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
    const span = spans.find(s => s.to > at)
    if (span) out.push({ ...span, at, items: spans.filter(s => s.from < at + needle.length && s.to > at).map(s => s.it) })
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
function syncNearHit(lines, line, pages, sec) { // blank/command lines still move the paper: next content for a command, the text above for a blank
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
  const back = () => scan(line - 1, Math.max(1, line - 12), -1)
  const fwd = () => scan(line + 1, inFig ? end : Math.min(lines.length, line + 12), 1) // inside a figure: its own span only
  const hint = () => pvFigureHint(lines, line, pages, sec)
  const cmd = pvCmdLine(lines[line - 1]) // #pagebreak()/#figure(: the next content
  return hint() || (cmd ? (fwd() || back()) : (back() || fwd()))
}
function syncToPv(force) { // force: explicit navigation (outline/find), works even with follow off
  if ((!followAll && !force) || !docId || tplName || (activeFile && !window.changeSession)) return
  if (scrollRestore && !scrollRestore.pv) return // reopened doc: saved preview spot wins over the first follow
  const pv = $('preview')
  if (!pv.scrollHeight || document.body.classList.contains('editonly')) return
  const lines = getT().split('\n'), at = syncView >= 0 ? syncView : cm.state.selection.main.head
  const line = cm.state.doc.lineAt(Math.max(0, Math.min(cm.state.doc.length, at))).number
  syncView = -1
  const sec = pvSecAtLine(line)
  const hit = syncAnchor(lines, line, pvTexts, sec) || syncNearHit(lines, line, pvTexts, sec)
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
function pvSyncDest(dest) { // internal PDF link: the editor cursor follows the same destination
  if (!syncOn || !docId || tplName || activeFile || !dest) return // a link click is a click: the eye does not gate it
  const items = pvTexts[dest.page] || [], slot = pvSlots[dest.page]
  if (!items.length || !slot) return
  const hPt = (+slot.dataset.w || 0) * (+slot.dataset.r || 0)
  const frac = dest.top != null && hPt > 0 ? Math.max(0, Math.min(1, 1 - dest.top / hPt)) : 0
  const vh = items[0].vh || hPt
  const line = pvPageHint(dest.page, cm.state.doc.lines || 1, pvTexts.length, pvSecAtY(dest.page, Math.min(vh, frac * vh + vh * 0.02)), frac)
  jumpPos(posOfLine(getT(), line))
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
function pvPxWords(cv, it) { // word boxes from the rendered page: justified spaces are wider than any width guess
  try {
    const n = (it.s || '').trim().split(/\s+/).length, ctx = n && cv.getContext ? cv.getContext('2d') : null
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
    while (runs.length > n) { // merge the narrowest gap: a letter gap, never a word space
      let g = 0
      for (let i = 1; i < runs.length; i++) if (runs[i][0] - runs[i - 1][1] < runs[g + 1][0] - runs[g][1]) g = i - 1
      runs[g][1] = runs[g + 1][1]
      runs.splice(g + 1, 1)
    }
    return runs.map(r => [x0 + r[0], x0 + r[1]])
  } catch (e) { return null }
}
function pvClickChar(word, frac) { // fraction across a word -> the character boundary under the click
  let total = 0
  for (const c of word) total += pvCharW(c)
  const at = Math.max(0, Math.min(1, frac)) * total
  let cum = 0, i = 0
  for (const c of word) {
    const w = pvCharW(c)
    if (at < cum + w / 2) break // nearest boundary: the right half of a letter puts the caret behind it
    cum += w
    i += c.length // code units: never stop inside a surrogate pair
  }
  return i
}
function pvClickCol(it, x, cssW, baseW, cv) { // click x -> the clicked letter, not the word start
  const raw = it.s || '', body = raw.trim()
  if (!body) return 0
  const words = [...body.matchAll(/\S+/g)]
  const boxes = cv && !/[\u0590-\u08FF\uFB1D-\uFDFF\uFE70-\uFEFF]/.test(body) ? pvPxWords(cv, it) : null
  if (boxes) { // rendered pixels: exact word edges, even across justified spaces
    const at = x * (cv.width / cssW), d = boxes.map(b => at < b[0] ? b[0] - at : at > b[1] ? at - b[1] : 0)
    let best = 0
    for (let i = 1; i < d.length; i++) if (d[i] < d[best]) best = i // ties go left: the end of a word belongs to it
    const b = boxes[best], f = b[1] > b[0] ? (at - b[0]) / (b[1] - b[0]) : 1
    return words[best].index + pvClickChar(words[best][0], f)
  }
  const scale = cssW / (it.vw || baseW || 1), w = (it.w || 0) * scale
  if (w <= 0) return 0
  const lead = raw.length - raw.trimStart().length
  const at = (x - (it.x0 || 0) * scale) / w * pvTextW(raw) // estimate when the canvas was evicted
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
function pvItemDist(it, x, y, sx, sy) { // CSS distance to the text box, never to its center: long lines stay clickable everywhere
  const x0 = (it.x0 || 0) * sx, x1 = x0 + (it.w || 0) * sx
  const yc = (it.y || 0) * sy, hh = Math.max(4, (it.h || 10) * sy / 2)
  const dx = x < x0 ? x0 - x : x > x1 ? x - x1 : 0
  const dy = y < yc - hh ? yc - hh - y : y > yc + hh ? y - yc - hh : 0
  return dx * dx + dy * dy
}
function pvNearItems(items, x, y, sx, sy, skip) { // nearest readable text: a drawing without text still lands on its caption
  return items
    .filter(it => it !== skip && !it.rot && /\p{L}/u.test(it.s || '')) // single-letter words are text too; numbers and rotated runs stay out
    .map(it => ({ it, d: pvItemDist(it, x, y, sx, sy) }))
    .sort((a, b) => a.d - b.d)
    .slice(0, 8)
}
function pvOlEq(pdfText, srcTitle) { // same heading; a numbering prefix on the PDF side is fine
  const x = syncPlain(pdfText), y = syncPlain(srcTitle)
  if (!x || !y) return false
  return x === y || x.replace(/^(?:\d+(?:\s+\d+)*|[a-z]|[ivxlcdm]+)\s+/, '') === y
}
function pvOutlineClick(pi, items, x, y, sx, sy) { // blank spot in the rendered #outline(): keep the cursor at the outline, not on a heading below
  const oi = srcOutlineLine(getT()) // real #outline( only: a fenced code sample is not the outline
  if (!oi) return 0
  const heads = srcHeadings(getT()).map(h => h.title).filter(Boolean)
  const pad = 12 // one blank line around an entry still belongs to the outline
  for (const L of pvLinks[pi] || []) {
    if (!L.dest) continue // external links are not outline entries
    const mid = (L.y0 + L.y1) / 2, hh = Math.max(6, (L.y1 - L.y0) / 2 + 2)
    const entry = items.some(it => {
      if (it.x0 >= L.x1 || it.x0 + it.w <= L.x0 || Math.abs(it.y - mid) > hh) return false
      return heads.some(h => pvOlEq(it.s, h)) // exact heading, not a loose substring
    })
    if (!entry) continue
    if (x >= L.x0 * sx - pad && x <= L.x1 * sx + pad && y >= L.y0 * sy - pad && y <= L.y1 * sy + pad) return oi
  }
  return 0
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
    if (pi === 0 && items.length) { // above the first heading: the document top (#outline/title), not the first heading
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
      if (isFinite(topY) && y < topY) {
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
      if (!it.s.trim() || it.rot) continue // rotated runs have no honest horizontal box for a direct hit
      const dd = pvItemDist(it, x, y, sx, sy)
      if (dd < bd) { bd = dd; best = it }
    }
    const yv = best ? best.y : y / (r.height || 1) * vh
    at = pi >= 0 ? pvSecAtY(pi, yv) : null
    const total = cm.state.doc.lines || 1
    const hintAt = y => pvPageHint(pi, total, pvTexts.length, at, y / vh)
    const file0 = activeFile
    if (best) {
      const hint = hintAt(yv)
      const col = pvClickCol(best, x, r.width, cv.width, cv)
      if (await pvJumpBest(pvClickNeedles(items, best, col), hint, pi, best)) return
    }
    if (!best || activeFile === file0) { // clicked text missed: try the nearest readable text in this file
      for (const { it: near } of pvNearItems(items, x, y, sx, sy, best)) {
        const col = pvClickCol(near, x, r.width, cv.width, cv) // blank space above/below a line still has a word column
        if (pvJumpHere(pvClickNeedles(items, near, col), hintAt(near.y), pi, near)) return
      }
    }
    syncPage = pi >= 0 ? pi : syncPage // even without hit: next sync starts on click page
    if (activeFile !== file0) return // the jump already tried another file: no section guess
    if (activeFile) return // image/margin click in a file tab: ratio maps main layout onto file text
  } else if (activeFile) return // no canvas hit in a file tab: nowhere honest to go
  if (pvSrcList().length > 1) return // included files destroy a main-line/layout ratio
  if (at && at.sec) { // no source text within reach: the section start is the honest anchor
    jumpPos(posOfLine(getT(), at.sec.line))
    return
  }
  const r = pv.getBoundingClientRect() // fallback for a single source only
  const ratio = Math.max(0, Math.min(1, (e.clientY - r.top + pv.scrollTop) / pv.scrollHeight))
  const lines = getT().split('\n'), total = lines.length || 1
  let line = Math.max(1, Math.min(total, Math.round(ratio * total) + 1))
  while (line > 1 && !lines[line - 1].trim()) line-- // snap to paragraph start
  jumpPos(posOfLine(getT(), line))
})
$('syncBtn').onclick = () => { syncOn = !syncOn; lsSet('typst_sync', syncOn ? 1 : 0); lsSet('typst_follow_all', followAll ? 1 : 0); applySyncBtn(); try { updPos() } catch (e) {} } // also pins the eye: the legacy fallback must not leak into new sessions
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
