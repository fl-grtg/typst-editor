// --- Spellcheck language per document: browser dictionary via lang + spellcheck attrs ---
// (the select lives in Settings, not the toolbar: underlines come from the
// browser dictionary, see settings.spellHint)
const SPELL_OPTS = [['auto', 'editor.spellAuto'], ['de', 'editor.spellGerman'], ['en', 'editor.spellEnglish'], ['off', 'editor.spellOff']]
const spellStored = () => { try { return localStorage.getItem('typst_spell_' + docId) || 'auto' } catch (e) { return 'auto' } }
function applySpell() { // dictionary follows the open document (attribute on the editable node, not global)
  const v = docId ? spellStored() : 'auto', dom = cm.contentDOM
  if (v === 'off') { dom.setAttribute('spellcheck', 'false'); dom.removeAttribute('lang') }
  else {
    dom.setAttribute('spellcheck', 'true')
    if (v === 'auto') dom.removeAttribute('lang'); else dom.setAttribute('lang', v)
  }
  const sel = $('spellSel')
  if (sel && sel.value !== v) sel.value = v
}
function spellSettingsSec() { // settings group section: per-doc language + browser-dictionary hint
  const sec = document.createElement('div'); sec.className = 'sec'
  const row = document.createElement('div'); row.className = 'row'
  const lab = document.createElement('label'); lab.textContent = t('editor.spell'); lab.setAttribute('for', 'spellSel')
  const sel = document.createElement('select')
  sel.id = 'spellSel'
  sel.setAttribute('aria-label', t('editor.spell'))
  for (const [v, key] of SPELL_OPTS) {
    const o = document.createElement('option'); o.value = v; o.textContent = t(key)
    sel.appendChild(o)
  }
  sel.value = docId ? spellStored() : 'auto'
  sel.onchange = () => { if (docId) { try { localStorage.setItem('typst_spell_' + docId, sel.value) } catch (e) {} } applySpell(); cm.focus() }
  row.append(lab, sel)
  const hint = document.createElement('div'); hint.textContent = t('settings.spellHint')
  hint.style.cssText = 'font-size:12px;color:var(--sub);line-height:1.45;margin-top:6px'
  sec.append(row, hint)
  return sec
}
new MutationObserver(applySpell).observe($('title'), { childList: true, characterData: true, subtree: true })
applySpell()
