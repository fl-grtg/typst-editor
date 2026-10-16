// --- Settings: click on name (font/zoom, profile, password, account) ---
document.body.appendChild($('setPop'))
$('who').onclick = e => {
  e.stopPropagation()
  if (showPop('setPop')) { apiKeys = null; sessList = null; renderSettings() }
}
kb($('who'), () => $('who').click())
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
  p.style.display = ''
  document.body.classList.add('settings-open')
  const fr = el('div', 'row settingRow'); fr.append(el('label', null, t('settings.editorFontSize')))
  const fm = el('button', 'step', '−'); fm.title = t('settings.fontMinus'); fm.setAttribute('aria-label', fm.title)
  fm.onclick = e => { e.stopPropagation(); stepEd(-ED_STEP); renderSettings() }
  const fontControls = el('div', 'settingControlGroup settingStepper')
  fontControls.append(fm, el('span', 'val', edSize + 'px'))
  const fp = el('button', 'step', '+'); fp.title = t('settings.fontPlus'); fp.setAttribute('aria-label', fp.title)
  fp.onclick = e => { e.stopPropagation(); stepEd(ED_STEP); renderSettings() }
  fontControls.appendChild(fp); fr.appendChild(fontControls)
  const zr = el('div', 'row settingRow'); zr.append(el('label', null, t('settings.previewZoom')))
  const zm = el('button', 'step', '−'); zm.title = t('settings.zoomMinus'); zm.setAttribute('aria-label', zm.title)
  zm.onclick = e => { e.stopPropagation(); stepPv(-PV_STEP); renderSettings() }
  const zoomControls = el('div', 'settingControlGroup settingStepper')
  zoomControls.append(zm, el('span', 'val', pvZoom + ' %'))
  const zp = el('button', 'step', '+'); zp.title = t('settings.zoomPlus'); zp.setAttribute('aria-label', zp.title)
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
  const edSec = sec(fr, zr, tr)
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
    .then(() => { avatarV = 0; paintMe(); renderPeers(); renderSettings() })
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
    .then(d => { nn.value = ''; npw.value = ''; user = d.user; paintMe(); sidebar(); renderSettings() })
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
      .catch(e => settingsError(e.message))
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
  if (popAnchor != null) movePop()
}
function applyPv() {
  const z = $('zoomV'); if (z) z.textContent = pvZoom + '%'
  document.querySelectorAll('#preview canvas').forEach(sizeCanvas)
}
let syncOn = true, syncT = 0, syncPage = 0, pvT = 0 // click sync editor<->preview, last hit page
try { const s = localStorage.getItem('typst_sync'); if (s === '0' || s === '1') syncOn = s === '1' } catch (e) {} // F25: follow persisted (string compare: +null === 0 would flip the default)
function applySyncBtn() { const b = $('syncBtn'); if (!b) return; b.classList.toggle('on', syncOn); b.setAttribute('aria-pressed', syncOn) } // F25: button mirrors persisted state
function queueSyncPv() { clearTimeout(syncT); syncT = setTimeout(syncToPv, SYNC_MS) }
function pvPageHint(pi, idx, len, total, n) { // page-proportional line: layout order tracks source order
  const frac = len > 0 ? (idx + 1) / len : 0.5
  return Math.max(1, Math.min(total, Math.round((pi + frac) / Math.max(1, n) * total) + 1))
}
function pvCanvasList() { // virtual slots first, fallback bare canvases
  const pv = $('preview')
  const sl = pv.querySelectorAll('.pvPage canvas')
  if (sl.length) return [...sl]
  return [...pv.querySelectorAll('canvas')]
}
function pvVerify(t, at, s) { // context must contain the click word: longest token guards short cells
  const um = (t || '').slice(Math.max(0, at - 80), at + 80)
  const w = (s.trim().split(/\s+/).sort((a, b) => b.length - a.length)[0] || '')
  return w.length < 4 || um.includes(w) || um.includes(s.trim())
}
async function pvJumpBest(s, hint, pi) { // honest cross-file jump: current tab, else the unique owner, else stay
  const needle = (s || '').trim()
  if (needle.length < 2) return false
  const cur = activeFile || ''
  const total = cm.state.doc.lines || 1
  const atCur = locateNear(getT(), needle, hint)
  if (atCur >= 0 && pvVerify(getT(), atCur, needle)) { syncPage = pi; jumpPos(atCur); return true }
  let srcs = []
  try { srcs = pvSrcList() } catch (e) { srcs = [] }
  let found = null, dup = false
  for (const src of srcs) {
    if (!src || src.key === cur) continue
    const txt = src.text || ''
    const lines = txt ? txt.split('\n').length : 1
    const h2 = Math.max(1, Math.min(lines, Math.round(hint / Math.max(1, total) * lines)))
    const at = locateNear(txt, needle, h2)
    if (at >= 0 && pvVerify(txt, at, needle)) {
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
    const at = locateNear(t, needle, h2)
    if (at >= 0) { jumpPos(at); return true }
  }
  return false
}
function syncToPv() { // editor -> preview: page with most line words, hit centered
  if (!syncOn || !docId || tplName || Date.now() - pvT < 1000) return // preview click: paper stays put
  const pv = $('preview')
  if (!pv.scrollHeight || document.body.classList.contains('editonly')) return
  const key = activeFile || ''
  const total = cm.state.doc.lines || 1
  const line = cm.state.doc.lineAt(cm.state.selection.main.head).number
  // normalize line: trim, strip markup roughly, count long words only
  const ank = cm.state.doc.line(line).text.trim().replace(/^[=+\-*#>]+/, '').replace(/[#*`_$[\](){}<>\/\\|=]+/g, ' ').replace(/\s+/g, ' ').trim().toLowerCase()
  const words = [...new Set(ank.split(' ').filter(w => w.length >= 4))].slice(0, 6)
  const n = pvTexts.length
  if (words.length && n) {
    const exp = (line - 1) / total * n // tie-break: page nearest the cursor ratio, not the sticky click page
    let bi = -1, bs = 0, bd = Infinity
    for (let pi = 0; pi < n; pi++) {
      const items = pvTexts[pi] || []
      let s = 0
      for (const w of words) for (const it of items) {
        if (it.s && it.s.toLowerCase().includes(w)) { s++; break }
      }
      if (s > bs || (s === bs && s > 0 && Math.abs(pi - exp) < bd)) { bs = s; bi = pi; bd = Math.abs(pi - exp) }
    }
    if (bi >= 0 && bs > 0) { // min one word: else fallback (no random jump)
      const items = pvTexts[bi] || []
      const long = words.slice().sort((a, b) => b.length - a.length)[0]
      for (const it of items) {
        if (it.s && it.s.toLowerCase().includes(long)) {
          const list = pvCanvasList(), cv = list[bi]
          if (!cv) break
          const pr = pv.getBoundingClientRect(), cr = cv.getBoundingClientRect()
          const ky = cr.height / (it.vh || cv.height || 1) // indexed page size survives raster eviction
          const want = pv.scrollTop + (cr.top - pr.top) + it.y * ky - pv.clientHeight / 2
          syncPage = bi
          if (Math.abs(want - pv.scrollTop) > SYNC_PX) pv.scrollTop = want // quiet: no flicker
          return
        }
      }
    }
  }
  if (key) return // file tab with no hit: stay put, ratio maps main lines onto file text
  const want = (line - 1) / total * (pv.scrollHeight - pv.clientHeight) // fallback: main tab only
  if (Math.abs(want - pv.scrollTop) > SYNC_PX) pv.scrollTop = want
}
function locateNear(t, s, hint) { // shortest hit near hint line (short cell texts too)
  s = (s || '').trim()
  if (s.length < 2) return -1
  const hp = posOfLine(t, hint)
  let best = -1, bd = 1e12, p = -1, n = 0
  while ((p = t.indexOf(s, p + 1)) >= 0 && n++ < 50) {
    const dd = Math.abs(p - hp)
    if (dd < bd) { bd = dd; best = p }
  }
  return best
}
function jumpPos(pos) { // editor jump to screen center (preview does not follow)
  pvT = Date.now()
  cm.dispatch({ selection: { anchor: pos }, effects: EditorView.scrollIntoView(pos, { y: 'center' }) })
  cm.focus()
}
$('preview').addEventListener('click', async e => { // preview -> editor: text anchors first (tables!), else ratio
  if (!syncOn || !docId || tplName) return
  const pv = $('preview')
  const cv = e.target.closest ? e.target.closest('canvas') : null
  if (cv && pvTexts.length) {
    const list = pvCanvasList()
    const pi = list.indexOf(cv) // count canvas only, ignore .empty divs
    const items = pi >= 0 ? (pvTexts[pi] || []) : []
    const r = cv.getBoundingClientRect()
    const x = e.clientX - r.left, y = e.clientY - r.top
    const rr = CLICK_PX / 2 // CSS pixels, independent of zoom and render scale
    let best = null, bd = rr * rr
    for (const it of items) {
      if (!it.s.trim()) continue
      const dx = it.x / (it.vw || cv.width) * r.width - x, dy = it.y / (it.vh || cv.height) * r.height - y, dd = dx * dx + dy * dy
      if (dd < bd) { bd = dd; best = it }
    }
    if (best) {
      const total = cm.state.doc.lines || 1
      const hint = pvPageHint(pi, items.indexOf(best), items.length, total, pvTexts.length)
      if (await pvJumpBest(best.s, hint, pi)) return
      syncPage = pi >= 0 ? pi : syncPage
      return // ambiguous text is not a source location
    } else {
      syncPage = pi >= 0 ? pi : syncPage // even without hit: next sync starts on click page
      if (activeFile) return // image/margin click in a file tab: ratio maps main layout onto file text
    }
  } else if (activeFile) return // no canvas hit in a file tab: nowhere honest to go
  if (pvSrcList().length > 1) return // included files destroy a main-line/layout ratio
  const r = pv.getBoundingClientRect() // fallback for a single source only
  const ratio = Math.max(0, Math.min(1, (e.clientY - r.top + pv.scrollTop) / pv.scrollHeight))
  const lines = getT().split('\n'), total = lines.length || 1
  let line = Math.max(1, Math.min(total, Math.round(ratio * total) + 1))
  while (line > 1 && !lines[line - 1].trim()) line-- // snap to paragraph start
  jumpPos(posOfLine(getT(), line))
})
$('syncBtn').onclick = () => { syncOn = !syncOn; lsSet('typst_sync', syncOn ? 1 : 0); applySyncBtn(); try { updPos() } catch (e) {} }
applySyncBtn() // F25: persisted follow state on boot
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
