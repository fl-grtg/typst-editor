// --- Account-wide spelling preference; browser dictionaries supply the underlines. ---
// (the select lives in Settings, not the toolbar: underlines come from the browser dictionary)
const SPELL_OPTS = [['auto', 'editor.spellAuto'], ['de', 'editor.spellGerman'], ['en', 'editor.spellEnglish'], ['off', 'editor.spellOff']]
const spellStored = () => {
  if (!user) return 'auto'
  try { const value = localStorage.getItem('typst_spell_user_' + user); return SPELL_OPTS.some(o => o[0] === value) ? value : 'auto' } catch (e) { return 'auto' }
}
function loadSpell(value, who = user) {
  if (who !== user) return // response was in flight across logout/login: not this user's preference anymore
  try { localStorage.setItem('typst_spell_user_' + who, value || 'auto') } catch (e) {}
  applySpell()
}
function applySpell() { // the account preference applies to each text editor
  const v = spellStored(), dom = cm.contentDOM
  if (v === 'off') { dom.setAttribute('spellcheck', 'false'); dom.removeAttribute('lang') }
  else {
    dom.setAttribute('spellcheck', /\.typ$/i.test(tplName || tabName(activeFile)) ? 'true' : 'false')
    if (v === 'auto') dom.removeAttribute('lang'); else dom.setAttribute('lang', v)
  }
  if (window.suggestionDraft?.view) {
    const draft = window.suggestionDraft.view.contentDOM
    draft.setAttribute('spellcheck', v === 'off' ? 'false' : 'true')
    if (v === 'auto' || v === 'off') draft.removeAttribute('lang'); else draft.setAttribute('lang', v)
  }
  const sel = $('spellSel')
  if (sel && sel.value !== v) sel.value = v
}
function spellSettingsSec() { // account preference
  const sec = document.createElement('div'); sec.className = 'sec'
  const row = document.createElement('div'); row.className = 'row settingRow'
  const lab = document.createElement('label'); lab.textContent = t('editor.spell'); lab.setAttribute('for', 'spellSel')
  const sel = document.createElement('select')
  sel.id = 'spellSel'
  sel.setAttribute('aria-label', t('editor.spell'))
  for (const [v, key] of SPELL_OPTS) {
    const o = document.createElement('option'); o.value = v; o.textContent = t(key)
    sel.appendChild(o)
  }
  sel.value = spellStored()
  sel.onchange = async () => {
    const who = user; sel.disabled = true
    try { const result = await api('POST', '/api/me/preferences', { spell_language: sel.value }); loadSpell(result.spell_language, who) }
    catch (e) { sel.value = spellStored(); toast(e.message) } finally { sel.disabled = false }
  }
  row.append(lab, sel)
  sec.append(row) // no hint: kept the UI quiet per user feedback (browser-dictionary limit stays in review notes)
  return sec
}
new MutationObserver(applySpell).observe($('title'), { childList: true, characterData: true, subtree: true })
applySpell()

addEventListener('storage', e => { if (e.key === 'typst_spell_user_' + user) applySpell() })
