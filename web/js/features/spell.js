// --- Spellcheck language per document: browser dictionary via lang + spellcheck attrs ---
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
{
  const tools = $('tools'), grps = tools.querySelectorAll(':scope > .grp')
  const wrap = document.createElement('span')
  wrap.className = 'grp'
  const sel = document.createElement('select')
  sel.id = 'spellSel'
  sel.setAttribute('aria-label', t('editor.spell')); sel.title = t('editor.spell')
  for (const [v, key] of SPELL_OPTS) {
    const o = document.createElement('option'); o.value = v; o.textContent = t(key)
    sel.appendChild(o)
  }
  sel.onchange = () => { if (docId) { try { localStorage.setItem('typst_spell_' + docId, sel.value) } catch (e) {} } applySpell(); cm.focus() }
  wrap.appendChild(sel)
  tools.insertBefore(wrap, grps.length ? grps[grps.length - 1].nextSibling : null)
  new MutationObserver(applySpell).observe($('title'), { childList: true, characterData: true, subtree: true })
  applySpell()
}
