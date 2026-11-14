// --- Shortcuts: central registry (Settings > Shortcuts) + Help menu with GitHub, issues and settings ---
const SC_STORE = 'typst_shortcuts'
const SC_MAC = /Mac|iPhone|iPad/.test(navigator.platform || '')
const SC_CATS = [
  { id: 'general', label: 'shortcuts.catGeneral' },
  { id: 'editor', label: 'shortcuts.catEditor' },
  { id: 'preview', label: 'shortcuts.catPreview' },
]
const SC_KEY_LABELS = {
  space: () => t('shortcuts.keySpace'),
  enter: () => t('shortcuts.keyEnter'),
  tab: () => t('shortcuts.keyTab'),
  escape: () => t('shortcuts.keyEsc'),
  backspace: () => t('shortcuts.keyBackspace'),
  delete: () => t('shortcuts.keyDelete'),
  pagedown: () => t('shortcuts.keyPgDn'),
  pageup: () => t('shortcuts.keyPgUp'),
  home: () => t('shortcuts.keyHome'),
  end: () => t('shortcuts.keyEnd'),
  insert: () => t('shortcuts.keyInsert'),
  plus: () => t('shortcuts.keyPlus'),
  minus: () => t('shortcuts.keyMinus'),
}
const SC_KEY_SYMBOLS = {
  arrowup: '↑', arrowdown: '↓', arrowleft: '←', arrowright: '→',
  plus: '+', minus: '−', space: '␣', enter: '↵', tab: '⇥', backspace: '⌫', delete: '⌦',
}
function scKeyName(key) {
  if (SC_KEY_SYMBOLS[key]) return SC_KEY_SYMBOLS[key] // character keys show the glyph, never a word
  const label = SC_KEY_LABELS[key]
  return label ? label() : key.toUpperCase()
}
const SC_SHIFTLESS = new Set([
  '?', '!', '"', '#', '$', '%', '&', "'", '(', ')', '*', '+', ',', '-', '.', '/', ':',
  ';', '<', '=', '>', '@', '[', '\\', ']', '^', '_', '`', '{', '|', '}', '~', 'plus', 'minus',
])
const scAppOn = () => $('app').classList.contains('on')
const scInField = (target = document.activeElement) => /^(INPUT|TEXTAREA|SELECT)$/.test((target || {}).tagName || '')
const scTyping = (target = document.activeElement) => scInField(target) || !!(target && target.isContentEditable)
const scAltGr = e => !!(e.getModifierState && e.getModifierState('AltGraph')) // AltGr types characters; never record or match it
const scPlain = e => !e.ctrlKey && !e.altKey && !e.metaKey && !e.shiftKey // no modifier at all
const scModalOpen = () => { const m = $('modal'); return !!m && m.style.display !== 'none' } // shared helper: keeps .style. off the registry lines (the i18n scan skips those whole lines)

const SC_ACTIONS = [
  // General: app-wide navigation and dialogs
  { id: 'nextTab', cat: 'general', label: 'shortcuts.nextTab', def: 'mod+alt+pagedown', run: () => { if (!scAppOn()) return false; cycleTab(1); return true } },
  { id: 'prevTab', cat: 'general', label: 'shortcuts.prevTab', def: 'mod+alt+pageup', run: () => { if (!scAppOn()) return false; cycleTab(-1); return true } },
  { id: 'openHelp', cat: 'general', label: 'shortcuts.openHelp', def: '?', when: () => scAppOn() && !scInField() && !cm.hasFocus && !scModalOpen() && !$('keySecret'), run: () => { openHelp(); return true } },
  { id: 'closeLayer', cat: 'general', label: 'shortcuts.closeLayer', def: 'escape', typing: true, run: () => scCloseLayer() },
  // Editor: documents, find and formatting
  { id: 'save', cat: 'editor', label: 'shortcuts.save', def: 'mod+s', run: () => { if (!scAppOn()) return false; saveNow(); return true } },
  { id: 'find', cat: 'editor', label: 'shortcuts.find', def: 'mod+f', run: () => { if (!scAppOn()) return false; openFind(); return true } },
  { id: 'findNext', cat: 'editor', label: 'shortcuts.findNext', def: 'enter', typing: true, when: () => findOpen && (document.activeElement === $('fQ') || document.activeElement === $('fR')), run: () => { stepFind(1); return true } },
  { id: 'findPrev', cat: 'editor', label: 'shortcuts.findPrev', def: 'shift+enter', typing: true, when: () => findOpen && (document.activeElement === $('fQ') || document.activeElement === $('fR')), run: () => { stepFind(-1); return true } },
  { id: 'bold', cat: 'editor', label: 'shortcuts.bold', def: 'mod+b', typing: true, when: () => cm.hasFocus, run: () => { fmtApply('bold'); return true } },
  { id: 'italic', cat: 'editor', label: 'shortcuts.italic', def: 'mod+i', typing: true, when: () => cm.hasFocus, run: () => { fmtApply('italic'); return true } },
  { id: 'underline', cat: 'editor', label: 'shortcuts.underline', def: 'mod+u', typing: true, when: () => cm.hasFocus, run: () => { fmtApply('underline'); return true } },
  { id: 'format', cat: 'editor', label: 'shortcuts.format', def: 'alt+shift+f', when: () => scAppOn() && !scInField(), run: () => { if (!fmtEditable()) return false; formatDoc(false); return true } },
  { id: 'complete', cat: 'editor', label: 'shortcuts.complete', def: 'ctrl+space', typing: true, when: () => cm.hasFocus && !cm.state.readOnly, run: () => startCompletion(cm) },
  { id: 'accept', cat: 'editor', label: 'shortcuts.accept', def: 'tab', typing: true, when: () => cm.hasFocus && !cm.state.readOnly, run: () => scAccept() },
  { id: 'dedent', cat: 'editor', label: 'shortcuts.dedent', def: 'shift+tab', typing: true, when: () => cm.hasFocus && !cm.state.readOnly, run: () => prevSnippetField(cm) || indentLess(cm) },
  { id: 'zoomIn', cat: 'preview', label: 'shortcuts.zoomIn', def: 'mod+plus', run: () => { if (!scAppOn()) return false; stepPv(PV_STEP); return true } },
  { id: 'zoomOut', cat: 'preview', label: 'shortcuts.zoomOut', def: 'mod+minus', run: () => { if (!scAppOn()) return false; stepPv(-PV_STEP); return true } },
  { id: 'zoomReset', cat: 'preview', label: 'shortcuts.zoomReset', def: 'mod+0', run: () => {
    if (!scAppOn()) return false
    if (typeof pvModeSet === 'function') pvModeSet('pct')
    pvZoom = 110; applyPv(); saveSet()
    return true
  } },
]

const SC_RESERVED = new Set((SC_MAC
  ? ['mod+w', 'mod+t', 'mod+n', 'mod+q', 'mod+l', 'mod+r', 'mod+shift+w', 'mod+shift+t', 'mod+shift+n', 'mod+shift+r', 'mod+alt+i', 'mod+alt+j', 'mod+alt+c']
  : ['mod+w', 'mod+t', 'mod+n', 'mod+l', 'mod+r', 'mod+shift+w', 'mod+shift+t', 'mod+shift+n', 'mod+shift+r', 'mod+shift+i'])
  .concat(['alt+left', 'alt+right', 'alt+f4', 'f5', 'shift+f5', 'f11', 'f12', 'mod+pageup', 'mod+pagedown'])) // browser/OS keys a page cannot reliably override; zoom keys (mod+plus/minus/0) stay assignable because they are page-level and the defaults use them
const SC_NATIVE = new Set(['mod+c', 'mod+v', 'mod+x', 'mod+z', 'mod+y', 'mod+a', 'mod+shift+z', 'mod+shift+v']) // standard editing keys: assignable, but only after a warning (copy/paste/undo would break in the editor and in every field)

function scParse(combo) {
  if (typeof combo !== 'string' || !combo) return null
  let mod = false, ctrl = false, alt = false, shift = false, key = ''
  for (const part of combo.toLowerCase().split('+')) {
    if (part === 'mod' || part === 'cmd' || part === 'meta') mod = true
    else if (part === 'ctrl' || part === 'control') ctrl = true
    else if (part === 'alt' || part === 'option') alt = true
    else if (part === 'shift') shift = true
    else if (part && !key) key = part
    else return null
  }
  if (!key) return null
  if (!SC_MAC && ctrl) { mod = true; ctrl = false }
  return { mod, ctrl, alt, shift, key }
}
function scCanon(combo) {
  const p = scParse(combo)
  if (!p) return ''
  const mods = []
  if (p.mod) mods.push('mod')
  if (p.ctrl) mods.push('ctrl')
  if (p.alt) mods.push('alt')
  if (p.shift) mods.push('shift')
  return mods.concat(p.key === '=' ? 'plus' : p.key).join('+') // '=' and '+' are the same zoom key
}
function scComboParts(combo) {
  const p = scParse(combo)
  if (!p) return []
  const parts = []
  if (SC_MAC) {
    if (p.ctrl) parts.push('⌃')
    if (p.alt) parts.push('⌥')
    if (p.shift) parts.push('⇧')
    if (p.mod) parts.push('⌘')
  } else {
    if (p.mod) parts.push(t('shortcuts.keyCtrl'))
    if (p.alt) parts.push(t('shortcuts.keyAlt'))
    if (p.shift) parts.push(t('shortcuts.keyShift'))
  }
  parts.push(scKeyName(p.key))
  return parts
}
function scComboLabel(combo) { return scComboParts(combo).join(SC_MAC ? '' : '+') }
const SC_KEY_ICONS = {
  arrowup: [['shortcutArrow', 'arrowUp'], '<path d="M12 19V5"/><path d="m5 12 7-7 7 7"/>'],
  arrowdown: [['shortcutArrow', 'arrowDown'], '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>'],
  arrowleft: [['shortcutArrow', 'arrowLeft'], '<path d="M19 12H5"/><path d="m12 19-7-7 7-7"/>'],
  arrowright: [['shortcutArrow', 'arrowRight'], '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>'],
  enter: [['shortcutEnter'], '<path d="M20 4v7a4 4 0 0 1-4 4H4"/><path d="m9 10-5 5 5 5"/>'],
  tab: [['shortcutTab'], '<path d="M17 12H3"/><path d="m11 18 6-6-6-6"/><path d="M21 5v14"/>'],
  backspace: [['shortcutBackspace'], '<path d="M20 5H9l-7 7 7 7h11a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2Z"/><path d="m18 9-6 6"/><path d="m12 9 6 6"/>'],
  delete: [['shortcutDelete'], '<path d="M20 5H9l-7 7 7 7h11a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2Z"/><path d="m18 9-6 6"/><path d="m12 9 6 6"/>'],
  space: [['shortcutSpace'], '<path d="M4 9v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9"/>'],
  plus: [['shortcutPlus'], '<path d="M12 5v14"/><path d="M5 12h14"/>'],
  minus: [['shortcutMinus'], '<path d="M5 12h14"/>'],
}
const SC_KEY_ICON_FOR = {
  '↑': 'arrowup', '↓': 'arrowdown', '←': 'arrowleft', '→': 'arrowright',
  '↵': 'enter', '⇥': 'tab', '⌫': 'backspace', '⌦': 'delete', '␣': 'space', '+': 'plus', '−': 'minus',
}
function scIconNode(key) {
  const spec = SC_KEY_ICONS[key]
  const node = el('span', 'shortcutIcon')
  spec[0].forEach(cls => node.classList.add(cls))
  node.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">' + spec[1] + '</svg>'
  return node
}
function scKeyNode(part) {
  const node = el('span', 'shortcutKey')
  const direct = SC_KEY_ICON_FOR[part]
  if (direct) { // a key that is nothing but a symbol becomes a crisp icon
    node.classList.add('shortcutKeyWithIcon')
    node.append(scIconNode(direct), el('span', 'sr-only', part))
    return node
  }
  const pieces = part.split(/([↑↓←→])/) // page labels keep their text and only the arrow becomes an icon
  const hasArrow = pieces.some(piece => SC_KEY_ICON_FOR[piece] && SC_KEY_ICON_FOR[piece].startsWith('arrow'))
  let hasText = false
  pieces.forEach(piece => {
    if (SC_KEY_ICON_FOR[piece]) {
      node.append(scIconNode(SC_KEY_ICON_FOR[piece]), el('span', 'sr-only', piece))
    } else if (piece) {
      node.appendChild(document.createTextNode(hasArrow ? piece.trim() : piece))
      if (piece.trim()) hasText = true
    }
  })
  if (hasArrow && hasText) node.classList.add('shortcutKeyWithArrow')
  return node
}
function scComboNode(combo) { // key names stay full strength, the separator is only punctuation
  const frag = document.createDocumentFragment()
  scComboParts(combo).forEach((part, i) => {
    if (i && !SC_MAC) frag.appendChild(el('span', 'shortcutSep', '+')) // visually a faint dot; text stays canonical for copy/AT
    frag.appendChild(scKeyNode(part))
  })
  return frag
}
function scNormText(s) {
  return (s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[+·]/g, ' ').replace(/\s+/g, ' ').trim()
}
function scSearchCombo(combo) { // raw tokens + synonyms: searching "ctrl" must also find mod bindings
  if (!combo) return ''
  const p = scParse(combo)
  if (!p) return ''
  const bits = [combo, combo.replace(/\+/g, ' '), p.key, scKeyName(p.key)]
  const word = SC_KEY_LABELS[p.key] // searching the spelled-out key still works even though the UI shows its glyph
  if (word) bits.push(word())
  if (p.mod) bits.push('ctrl control cmd meta mod', t('shortcuts.keyCtrl'))
  if (p.ctrl) bits.push('ctrl control', t('shortcuts.keyCtrl'))
  if (p.alt) bits.push('alt option', t('shortcuts.keyAlt'))
  if (p.shift) bits.push('shift', t('shortcuts.keyShift')) // the visible label is localized: searching "Strg"/"Umschalt" finds the same rows
  return bits.join(' ')
}
function scKeyFromEvent(e) {
  if (scAltGr(e)) return ''
  const k = e.key
  if (!k || /^(Control|Meta|Alt|Shift|CapsLock|Dead|Unidentified|OS|Process)$/.test(k)) return ''
  if (k === ' ') return 'space'
  if (k === '+') return 'plus'
  if (k === '-') return 'minus'
  if (/^[a-z0-9]$/i.test(k)) return k.toLowerCase()
  const letter = /^Key([A-Z])$/.exec(e.code || '') // physical letter on non-Latin layouts (e.g. Alt+Shift+F)
  if (letter) return letter[1].toLowerCase()
  return k.toLowerCase()
}
function scShiftKey(key) { return !SC_SHIFTLESS.has(key) }
function scTextCombo(combo) { // the combo would type a character into the document
  const p = scParse(combo)
  if (!p || p.mod || p.ctrl || p.alt) return false
  return p.key === 'space' || p.key === 'plus' || p.key === 'minus' || p.key.length === 1
}
function scNativeKey(combo) { // the combo is needed for typing, caret movement or focus navigation
  if (scTextCombo(combo)) return true
  const p = scParse(combo)
  if (!p || p.mod || p.ctrl || p.alt) return false
  return p.key === 'enter' || p.key === 'tab' || p.key === 'escape' || p.key === 'backspace' || p.key === 'delete' ||
    p.key === 'home' || p.key === 'end' || p.key === 'pageup' || p.key === 'pagedown' || p.key.startsWith('arrow')
}
function scSearchNative(e) { // the search field keeps native clipboard, undo and caret combos
  const k = String(e.key || '').toLowerCase()
  if (k === 'backspace' || k === 'delete') return true
  if (k.startsWith('arrow') || ['home', 'end', 'insert', 'pageup', 'pagedown'].includes(k)) return !(e.altKey && (e.ctrlKey || e.metaKey)) // Ctrl+Alt turns navigation into a searchable shortcut, Alt alone stays native
  if (!(e.ctrlKey || e.metaKey) || e.altKey) return false
  if (k === 'z') return true // undo/redo stay native, with or without Shift
  return !e.shiftKey && ['c', 'v', 'x', 'a', 'y'].includes(k) // Shift+letter is a searchable combo, not a native edit
}
function scComboFromEvent(e) {
  if (scAltGr(e)) return ''
  const key = scKeyFromEvent(e)
  if (!key) return ''
  const mods = []
  if (SC_MAC) {
    if (e.ctrlKey) mods.push('ctrl')
    if (e.altKey) mods.push('alt')
    if (e.shiftKey && scShiftKey(key)) mods.push('shift')
    if (e.metaKey) mods.push('mod')
  } else {
    if (e.metaKey) return '' // Windows/Super is OS-owned: never record it as a binding
    if (e.ctrlKey) mods.push('mod')
    if (e.altKey) mods.push('alt')
    if (e.shiftKey && scShiftKey(key)) mods.push('shift')
  }
  return scCanon(mods.concat(key).join('+'))
}
function scMatch(e, combo) {
  if (scAltGr(e)) return false
  if (!SC_MAC && e.metaKey) return false // Windows/Super must never complete a binding
  const p = scParse(combo)
  if (!p) return false
  const key = scKeyFromEvent(e)
  if (key !== p.key && !(p.key === 'plus' && e.key === '=')) return false
  const mod = SC_MAC ? e.metaKey : e.ctrlKey
  if (p.mod !== !!mod) return false
  if (SC_MAC && p.ctrl !== !!e.ctrlKey) return false
  if (p.alt !== !!e.altKey) return false
  const shift = !!e.shiftKey && scShiftKey(p.key)
  return p.shift === shift
}
function scLoadCustom() {
  let raw = {}
  try { raw = JSON.parse(localStorage.getItem(SC_STORE) || '{}') } catch (e) {}
  const out = {}
  if (!raw || typeof raw !== 'object') return out
  for (const a of SC_ACTIONS) {
    if (!Object.prototype.hasOwnProperty.call(raw, a.id)) continue
    const v = raw[a.id]
    if (v === '') out[a.id] = ''
    else { const c = scCanon(v); if (c) out[a.id] = c }
  }
  return out
}
let scCustom = scLoadCustom()
let scRecordingId = '', scNotice = null, scHelpPrev = null, scQuery = '', scQueryIsCombo = false
function scBinding(id) {
  const a = SC_ACTIONS.find(x => x.id === id)
  if (!a) return ''
  const v = Object.prototype.hasOwnProperty.call(scCustom, id) ? scCustom[id] : a.def
  return v ? scCanon(v) : ''
}
function scSaveCustom() {
  try {
    if (Object.keys(scCustom).length) lsSet(SC_STORE, JSON.stringify(scCustom))
    else localStorage.removeItem(SC_STORE)
  } catch (e) {}
}
addEventListener('storage', e => { // another tab changed a binding: reload instead of overwriting it with a stale map later
  if (e.key !== SC_STORE && e.key !== null) return
  scCustom = scLoadCustom()
  if (!scRecordingId && !scNotice && $('setPop').style.display !== 'none' && typeof renderSettings === 'function') renderSettings()
  scPaintEmpty()
})
function scConflict(id, combo) {
  const c = scCanon(combo)
  if (!c) return null
  return SC_ACTIONS.find(a => a.id !== id && scBinding(a.id) === c) || null
}
function scAction(id) { return SC_ACTIONS.find(a => a.id === id) || null }
function scFocusChange(id) {
  setTimeout(() => {
    try {
      const p = $('setPop')
      if (p.style.display === 'none') return // the undo toast can outlive the settings
      p.querySelector('[data-shortcut-change="' + id + '"]')?.focus()
    } catch (e) {}
  }, 20)
}
function scFocusSearch() {
  try {
    const p = $('setPop')
    if (p.style.display !== 'none') p.querySelector('[data-shortcut-search]')?.focus()
  } catch (e) {}
}
function scPaintEmpty() { // keep the onboarding hints in sync with custom bindings
  try { if ($('emptyCard') && typeof paintEmpty === 'function') paintEmpty() } catch (e) {}
}
function scResetRecordingState() { scRecordingId = ''; scNotice = null }
function scRecordingRow(id) {
  try { return $('setPop').querySelector('[data-shortcut-row="' + id + '"]') } catch (e) { return null }
}
function scSyncRecordingRow(id) { // cancel recording in place: keep focus where the user clicked
  const row = scRecordingRow(id)
  if (!row) return
  const field = row.querySelector('[data-shortcut-change="' + id + '"]')
  if (!field) return
  const a = scAction(id), cur = scBinding(id)
  field.classList.remove('recording', 'pending', 'unset')
  field.replaceChildren()
  if (cur) field.appendChild(scComboNode(cur))
  else { field.classList.add('unset'); field.appendChild(el('span', 'shortcutUnset', t('shortcuts.unset'))) }
  field.title = t('shortcuts.changeHint')
  field.setAttribute('aria-label', t('shortcuts.changeHint') + ': ' + (a ? t(a.label) : id) + ' (' + (cur ? scComboLabel(cur) : t('shortcuts.unset')) + ')')
  row.querySelector('.shortcutHint')?.remove()
}
function scCancelRecording() {
  if (!scRecordingId) return false
  const id = scRecordingId
  scRecordingId = ''
  scNotice = null
  scSyncRecordingRow(id)
  return true
}
document.addEventListener('pointerdown', e => {
  if (!scRecordingId) return
  const row = scRecordingRow(scRecordingId)
  if (!row || !row.contains(e.target)) scCancelRecording()
}, true)
document.addEventListener('focusin', e => {
  if (!scRecordingId) return
  const row = scRecordingRow(scRecordingId)
  if (!row || !row.contains(e.target)) scCancelRecording()
})
function scStopRecording(id) {
  scRecordingId = ''
  scNotice = null
  renderSettings()
  if (id) scFocusChange(id)
}
function scApply(id, combo, mode, force) {
  const a = scAction(id), c = scCanon(combo)
  if (!a || !c) return false
  const other = scConflict(id, c)
  if (other && !force) {
    scNotice = { id, combo: c, mode, conflictId: other.id }
    scRecordingId = ''
    renderSettings()
    scFocusChange(id)
    return false
  }
  const had = Object.prototype.hasOwnProperty.call(scCustom, id)
  const prev = scCustom[id]
  const otherHad = other ? Object.prototype.hasOwnProperty.call(scCustom, other.id) : false
  const otherPrev = other ? scCustom[other.id] : ''
  if (other) scCustom[other.id] = ''
  if (c === scCanon(a.def)) delete scCustom[id]
  else scCustom[id] = c
  scSaveCustom()
  scRecordingId = ''
  scNotice = null
  toast(t(mode === 'reset' ? 'shortcuts.resetDone' : 'shortcuts.saved'), () => { // undo: put back the previous binding and any replaced one
    if (had) scCustom[id] = prev
    else delete scCustom[id]
    if (other) {
      if (otherHad) scCustom[other.id] = otherPrev
      else delete scCustom[other.id]
    }
    scSaveCustom()
    renderSettings()
    scPaintEmpty()
    scFocusChange(id)
  }, t('shortcuts.undo'), 8000)
  renderSettings()
  scPaintEmpty()
  scFocusChange(id)
  return true
}
function scClear(id) {
  if (!scAction(id)) return
  const had = Object.prototype.hasOwnProperty.call(scCustom, id)
  const prev = scCustom[id]
  scCustom[id] = ''
  scSaveCustom()
  scRecordingId = ''
  scNotice = null
  toast(t('shortcuts.clearedName', { name: t(scAction(id).label) }), () => { // undo: one click restores the previous binding
    if (had) scCustom[id] = prev
    else delete scCustom[id]
    scSaveCustom()
    renderSettings()
    scPaintEmpty()
    scFocusChange(id)
  }, t('shortcuts.undo'), 8000)
  renderSettings()
  scPaintEmpty()
  scFocusChange(id)
}
async function scResetAll() {
  if (!Object.keys(scCustom).length) return
  if (typeof ask === 'function' && !await ask(t('shortcuts.resetAllConfirm'), { noInput: true, danger: true, ok: t('shortcuts.resetAllOk') })) return
  scCustom = {}
  scSaveCustom()
  scRecordingId = ''
  scNotice = null
  toast(t('shortcuts.resetAllDone'))
  renderSettings()
  scPaintEmpty()
  scFocusSearch()
}
function scDismissNotice() {
  if (!scNotice) return false
  const id = scNotice.id
  scNotice = null
  renderSettings()
  scFocusChange(id)
  return true
}
function scCapture(e) {
  const id = scRecordingId
  if (scAltGr(e)) return // AltGr characters are text, not shortcuts
  const combo = scComboFromEvent(e)
  if (!combo) return
  if (SC_RESERVED.has(combo)) { // page cannot override browser/OS keys: warn in place, keep the attempted combo visible
    scNotice = { id, combo, mode: 'assign', reserved: true }
    scRecordingId = ''
    renderSettings()
    scFocusChange(id)
    return
  }
  const a = scAction(id)
  if (a && a.typing && scTextCombo(combo)) { toast(t('shortcuts.typingKey', { combo: scComboLabel(combo) })); return } // a bare letter would break typing
  if (SC_NATIVE.has(combo) && scBinding(id) !== combo) { // copying/pasting/undo are too central to shadow silently
    scNotice = { id, combo, mode: 'assign', native: true }
    scRecordingId = ''
    renderSettings()
    scFocusChange(id)
    return
  }
  scApply(id, combo, 'assign', false)
}
function scAccept() {
  if (nextSnippetField(cm)) return true
  const m = cm.state.selection.main
  if (!m.empty) return indentMore(cm)
  if (currentCompletions(cm.state).length) { acceptCompletion(cm); return true }
  const line = cm.state.doc.lineAt(m.head)
  if (/^\s*$/.test(line.text.slice(0, m.head - line.from))) return indentMore(cm)
  return startCompletion(cm)
}
function scEditorTab(combo) { // editor keeps Tab/Shift-Tab when the registry binding is cleared or moved away
  if (!cm.hasFocus || cm.state.readOnly) return false
  if (combo === 'tab') return scAccept()
  return prevSnippetField(cm) || indentLess(cm)
}

function scCloseLayer() {
  if ($('keySecret')) return true // the one-time key dialog deliberately swallows Escape
  const search = $('setPop').querySelector('[data-shortcut-search]')
  if (search && document.activeElement === search && search.value) { // Esc clears the filter before closing settings
    search.value = ''
    search.dispatchEvent(new Event('input', { bubbles: true }))
    return true
  }
  const help = $('helpOverlay')
  if (help && help.style.display !== 'none') { closeHelp(); return true }
  if ($('modal').style.display !== 'none') { $('mNo').click(); return true }
  if ($('setPop').style.display !== 'none') { hidePops(); return true }
  if (findOpen) { closeFind(); return true }
  closePop(); hidePops()
  if ($('q').value && document.activeElement === $('q')) { $('q').value = ''; findQ = ''; hits = []; paintOwn(); return true }
  if (matchMedia('(max-width:720px)').matches && !document.body.classList.contains('noside')) {
    document.body.classList.add('noside'); updScrim(); $('navToggle').setAttribute('aria-pressed', 'false')
    if ($('side').contains(document.activeElement)) $('navToggle').focus()
    return true
  }
  return false
}

function shortcutSettingsView() {
  const wrap = el('div', 'shortcutSettings')
  const search = el('div', 'shortcutSearch')
  search.setAttribute('role', 'search')
  const searchField = el('div', 'shortcutSearchField')
  const searchIco = el('span', 'shortcutSearchIco'); searchIco.innerHTML = SC_ICON_SEARCH
  const searchInput = el('input', 'shortcutSearchInput')
  searchInput.type = 'text'; searchInput.autocomplete = 'off'; searchInput.spellcheck = false
  searchInput.dataset.shortcutSearch = ''
  searchInput.placeholder = t('shortcuts.searchPlaceholder')
  searchInput.setAttribute('aria-label', searchInput.placeholder)
  searchInput.value = scQuery
  const searchClear = el('button', 'shortcutSearchClear')
  searchClear.type = 'button'; searchClear.innerHTML = ICO_X
  searchClear.title = t('shortcuts.searchClear'); searchClear.setAttribute('aria-label', searchClear.title)
  const resetAll = el('button', 'shortcutResetAll') // global reset, square next to the search
  resetAll.type = 'button'; resetAll.dataset.shortcutResetAll = ''
  resetAll.innerHTML = ICO_UNDO
  resetAll.title = t('shortcuts.resetAllHint')
  resetAll.setAttribute('aria-label', resetAll.title)
  resetAll.disabled = !Object.keys(scCustom).length
  resetAll.onclick = e => { e.stopPropagation(); scResetAll() }
  searchField.append(searchIco, searchInput, searchClear)
  search.append(searchField, resetAll)
  wrap.appendChild(search)
  for (const cat of SC_CATS) {
    const actions = SC_ACTIONS.filter(a => a.cat === cat.id)
    if (!actions.length) continue
    const grp = el('div', 'grp')
    grp.appendChild(el('h4', null, t(cat.label)))
    const sec = el('div', 'sec')
    for (const a of actions) {
      const row = el('div', 'shortcutRow')
      row.dataset.shortcutRow = a.id
      const cur = scBinding(a.id), rec = scRecordingId === a.id
      const pending = scNotice && scNotice.id === a.id ? scNotice.combo : '' // keep the attempted combo visible until it is confirmed or discarded
      const shown = pending || cur
      row.dataset.shortcutSearchText = scNormText([
        t(a.label), t(cat.label), a.id, scComboLabel(cur), scSearchCombo(cur),
        scComboLabel(a.def), scSearchCombo(a.def), cur ? '' : t('shortcuts.searchUnset'),
      ].join(' '))
      row.dataset.shortcutCombo = scNormText(cur ? cur.replace(/\+/g, ' ') : '')
      row.dataset.shortcutKeys = scNormText(cur ? scComboLabel(cur) : '')
      row.dataset.shortcutUnset = cur ? '' : '1'
      row.dataset.shortcutDefaultCombo = scNormText(a.def)
      row.dataset.shortcutDefaultKeys = scNormText(scComboLabel(a.def))
      const main = el('div', 'shortcutMain')
      const label = el('span', 'shortcutLabel', t(a.label))
      const keys = el('span', 'shortcutKeys')
      const field = el('button', 'shortcutKbd') // the shortcut itself is the edit control
      field.type = 'button'; field.dataset.shortcutChange = a.id
      if (rec) { field.classList.add('recording'); field.textContent = t('shortcuts.pressKeys') }
      else if (shown) field.appendChild(scComboNode(shown))
      else { field.classList.add('unset'); field.appendChild(el('span', 'shortcutUnset', t('shortcuts.unset'))) }
      if (pending) field.classList.add('pending')
      field.title = rec ? t('shortcuts.cancelHint') : t('shortcuts.changeHint')
      field.setAttribute('aria-label', rec ? t('shortcuts.cancelHint') : t('shortcuts.changeHint') + ': ' + t(a.label) + ' (' + (shown ? scComboLabel(shown) : t('shortcuts.unset')) + ')')
      field.onclick = e => {
        e.stopPropagation()
        if (scRecordingId === a.id) scStopRecording(a.id) // read live state: the closure may predate a focus cancel
        else { scRecordingId = a.id; scNotice = null; renderSettings(); scFocusChange(a.id) }
      }
      const reset = el('button', 'shortcutResetBtn') // left of the field: reset what the field customizes
      reset.type = 'button'; reset.dataset.shortcutReset = a.id
      reset.innerHTML = ICO_UNDO // icon only: the hover title names the action
      reset.title = t('shortcuts.resetHint') // tests and hover keep the short title
      reset.setAttribute('aria-label', reset.title + ': ' + t(a.label))
      reset.disabled = !Object.prototype.hasOwnProperty.call(scCustom, a.id)
      reset.hidden = reset.disabled // only customized shortcuts can be reset
      reset.onclick = e => { e.stopPropagation(); scApply(a.id, a.def, 'reset', false) }
      const clear = el('button', 'shortcutClearBtn') // right of the field: remove the binding entirely
      clear.type = 'button'; clear.dataset.shortcutClear = a.id
      clear.innerHTML = ICO_X
      clear.title = t('shortcuts.clearHint') // tests and hover keep the short title
      clear.setAttribute('aria-label', clear.title + ': ' + t(a.label))
      clear.disabled = !cur // stays visible but grayed out when nothing is bound
      clear.onclick = e => { e.stopPropagation(); scClear(a.id) }
      keys.append(reset, field, clear)
      main.append(label, keys)
      row.appendChild(main)
      if (rec) {
        const hint = el('div', 'shortcutHint')
        hint.setAttribute('role', 'status') // screen readers: announce the recording mode
        const hintText = el('div', 'shortcutHintText')
        hintText.append(el('b', null, t('shortcuts.recordingHint')))
        const cancel = el('button', 'btnSecondary shortcutCancel', t('common.cancel'))
        cancel.type = 'button'; cancel.dataset.shortcutCancel = ''
        cancel.onclick = e => { e.stopPropagation(); scStopRecording(a.id) }
        hint.append(hintText, cancel)
        row.appendChild(hint)
      }
      if (scNotice && scNotice.id === a.id) {
        const other = scAction(scNotice.conflictId)
        const note = el('div', 'shortcutNotice')
        note.setAttribute('role', 'alert')
        const text = el('div', 'shortcutNoticeText')
        const combo = scComboLabel(scNotice.combo)
        text.append(
          el('b', null, scNotice.native ? t('shortcuts.nativeWarn') : scNotice.reserved ? t('shortcuts.reserved', { combo }) : t('shortcuts.conflict', { combo, name: other ? t(other.label) : scNotice.conflictId })),
          el('span', null, scNotice.native ? t('shortcuts.nativeHint') : scNotice.reserved ? t('shortcuts.reservedHint') : t('shortcuts.conflictHint')),
        )
        note.appendChild(text)
        const discard = el('button', 'btnSecondary shortcutDiscard', t('shortcuts.discard'))
        discard.type = 'button'; discard.dataset.shortcutDiscard = ''
        discard.title = t('shortcuts.discardHint')
        discard.setAttribute('aria-label', discard.title)
        discard.onclick = e => { e.stopPropagation(); scDismissNotice() }
        note.appendChild(discard)
        if (!scNotice.reserved) { // a browser-owned combo has nothing to replace
          const use = el('button', 'btnSecondary', t('shortcuts.replace'))
          use.type = 'button'; use.dataset.shortcutUse = ''
          use.title = t('shortcuts.replaceHint')
          use.setAttribute('aria-label', use.title)
          use.onclick = e => { e.stopPropagation(); scApply(a.id, scNotice.combo, scNotice.mode, true) }
          note.appendChild(use)
        }
        row.appendChild(note)
      }
      sec.appendChild(row)
    }
    grp.appendChild(sec)
    wrap.appendChild(grp)
  }
  const empty = el('div', 'shortcutEmpty', t('shortcuts.searchNoResults'))
  empty.setAttribute('role', 'status')
  wrap.appendChild(empty)
  const applyFilter = () => {
    const query = scNormText(scQuery)
    const terms = query.split(' ').filter(Boolean)
    const rows = [...wrap.querySelectorAll('[data-shortcut-row]')]
    const exact = terms.length ? rows.filter(row => row.dataset.shortcutCombo === query || row.dataset.shortcutKeys === query || (scQueryIsCombo ? row.dataset.shortcutDefaultCombo === query || row.dataset.shortcutDefaultKeys === query : row.dataset.shortcutUnset === '1' && (row.dataset.shortcutDefaultCombo === query || row.dataset.shortcutDefaultKeys === query))) : []
    const exactRows = exact.length ? new Set(exact) : (scQueryIsCombo ? new Set() : null) // pressed combos only match real bindings
    let hits = 0, firstVisible = true
    wrap.querySelectorAll('.grp').forEach(group => {
      let groupHit = false
      group.querySelectorAll('[data-shortcut-row]').forEach(row => {
        const hit = exactRows ? exactRows.has(row) : (!terms.length || terms.every(term => row.dataset.shortcutSearchText.includes(term)))
        row.hidden = !hit
        if (hit) { groupHit = true; hits++ }
      })
      group.hidden = !groupHit
      group.classList.toggle('grpFirst', groupHit && firstVisible) // the top visible category has no divider above it
      if (groupHit) firstVisible = false
    })
    empty.hidden = hits > 0
    searchClear.hidden = !scQuery
  }
  const setQuery = (value, isCombo = false) => {
    scQuery = value
    scQueryIsCombo = isCombo
    searchInput.value = value
    applyFilter()
    const scroller = wrap.closest('.setContent')
    if (scroller) scroller.scrollTop = 0 // a new result list starts at its top
  }
  searchInput.addEventListener('input', () => setQuery(searchInput.value))
  searchInput.addEventListener('keydown', e => { // capture first: every combo belongs to the search while it has focus
    if (e.isComposing || scAltGr(e)) return // AltGr still types characters
    if (scSearchNative(e)) return // clipboard, undo, word delete and caret movement stay native
    if (!(e.ctrlKey || e.altKey || e.metaKey)) return
    const combo = scComboFromEvent(e)
    if (!combo) return
    e.preventDefault(); e.stopImmediatePropagation()
    setQuery(scComboLabel(combo), true)
  }, true)
  searchClear.onclick = e => { e.stopPropagation(); setQuery(''); searchInput.focus() }
  applyFilter()
  return wrap
}

document.addEventListener('keydown', e => {
  if (e.defaultPrevented || e.isComposing) return
  if (scAltGr(e)) return // AltGr types characters, never fire a shortcut
  if ($('keySecret')) return // the one-time key dialog owns the modal layer, including Escape
  const help = $('helpOverlay')
  if (help && help.style.display !== 'none') { // help is modal: only a bare Escape leaves it
    if (scPlain(e) && e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeHelp() }
    return
  }
  if (scRecordingId) {
    const row = $('setPop').querySelector('[data-shortcut-row="' + scRecordingId + '"]')
    if ($('setPop').style.display === 'none' || !row || !row.getClientRects().length) { scResetRecordingState(); return }
    e.preventDefault(); e.stopPropagation()
    scCapture(e)
    return
  }
  if (scNotice && e.key === 'Escape' && $('setPop').style.display !== 'none') { // leave the conflict editor, not the settings
    e.preventDefault(); e.stopPropagation()
    scDismissNotice()
    return
  }
  const search = $('setPop').querySelector('[data-shortcut-search]')
  if (search && $('setPop').style.display !== 'none' && document.activeElement === search) {
    if (e.ctrlKey || e.altKey || e.metaKey) return // the search input owns modified combos
    if (e.key !== 'Escape') return // plain keys are text and caret input, never shortcuts
  }
  if (scPlain(e) && e.key === 'Escape' && scCloseLayer()) { // Esc is a reserved escape hatch, even if closeLayer is rebound or cleared
    e.preventDefault(); e.stopPropagation()
    return
  }
  for (const a of SC_ACTIONS) {
    const combo = scBinding(a.id)
    if (!combo || !scMatch(e, combo)) continue
    if (a.when && !a.when()) continue
    if (!a.typing && scTyping(e.target) && scNativeKey(combo)) continue // typing, caret and focus keys stay with the field
    if (a.run() !== false) { e.preventDefault(); e.stopPropagation() }
    return
  }
}, true)

const SC_ICON_GITHUB = '<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M8 .9a7.1 7.1 0 0 0-2.3 13.8c.4.1.5-.2.5-.4v-1.4c-2 .4-2.4-1-2.4-1-.3-.8-.8-1-.8-1-.7-.5.1-.5.1-.5.8.1 1.2.8 1.2.8.7 1.2 1.8.9 2.2.7.1-.5.3-.9.5-1.1-1.6-.2-3.3-.8-3.3-3.6 0-.8.3-1.4.8-1.9-.1-.2-.3-.9.1-1.9 0 0 .6-.2 2 .7a6.9 6.9 0 0 1 3.6 0c1.4-.9 2-.7 2-.7.4 1 .2 1.7.1 1.9.5.5.8 1.1.8 1.9 0 2.8-1.7 3.4-3.3 3.6.3.2.5.7.5 1.4v2.1c0 .2.1.5.5.4A7.1 7.1 0 0 0 8 .9z"/></svg>'
const SC_ICON_ISSUE = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="8" r="6.2"/><path d="M8 4.8v3.8"/><circle cx="8" cy="11.4" r=".7" fill="currentColor" stroke="none"/></svg>'
const SC_ICON_KEYS = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" aria-hidden="true"><rect x="1.8" y="4" width="12.4" height="8" rx="1.6"/><path d="M4 6.5h.01M6.3 6.5h.01M8.6 6.5h.01M10.9 6.5h.01M4 8.8h.01M6.3 8.8h.01M8.6 8.8h.01M10.9 8.8h.01M5 10.6h6"/></svg>'
const SC_ICON_AGENT = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2.2" y="4.8" width="11.6" height="8" rx="2.2"/><path d="M8 2.4v2.4"/><circle cx="8" cy="1.6" r=".8" fill="currentColor" stroke="none"/><path d="M5.4 8h.01M8 8h.01M10.6 8h.01M5.8 10.5h4.4"/></svg>'
const SC_ICON_EXTERNAL = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>'
const SC_ICON_SEARCH = '<svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="7" cy="7" r="4.5"/><path d="M10.5 10.5L14 14"/></svg>'
function openHelp() {
  if ($('keySecret')) return // the one-time key dialog owns the modal layer
  const existing = $('helpOverlay')
  const wasOpen = !!existing && existing.style.display !== 'none'
  closePop(true)
  hidePops()
  if (window.closeMenu) window.closeMenu(false)
  if (!wasOpen) scHelpPrev = document.activeElement
  let ov = existing
  if (!ov) {
    ov = el('div'); ov.id = 'helpOverlay'
    ov.setAttribute('role', 'dialog'); ov.setAttribute('aria-modal', 'true'); ov.setAttribute('aria-label', t('menu.helpH'))
    ov.onmousedown = e => { if (e.target === ov) closeHelp() }
    ov.addEventListener('keydown', e => {
      if (e.key !== 'Tab') return
      const f = [...ov.querySelectorAll('a,button')].filter(x => !x.disabled && x.getClientRects().length)
      if (!f.length) return
      const i = f.indexOf(document.activeElement)
      if (e.shiftKey && i <= 0) { e.preventDefault(); f[f.length - 1].focus() }
      else if (!e.shiftKey && (i < 0 || i === f.length - 1)) { e.preventDefault(); f[0].focus() }
    })
    document.body.appendChild(ov)
  }
  const card = el('div'); card.id = 'helpCard'
  const head = el('div', 'helpHead')
  const title = el('b', null, t('menu.helpH'))
  const close = el('button', null, '✕')
  close.type = 'button'; close.title = t('common.close'); close.setAttribute('aria-label', t('common.close')); close.onclick = closeHelp
  head.append(title, close)
  const list = el('div', 'helpMenu')
  const icon = (svg, cls = 'helpIco') => { const s = el('span', cls); s.innerHTML = svg; return s }
  for (const [href, label, svg] of [
    ['https://github.com/fl-grtg/typst-editor', t('menu.source'), SC_ICON_GITHUB],
    ['https://github.com/fl-grtg/typst-editor/issues', t('menu.issues'), SC_ICON_ISSUE],
  ]) {
    const a = el('a', 'helpItem')
    a.href = href; a.target = '_blank'; a.rel = 'noopener'
    a.append(icon(svg), el('span', 'helpLb', label), icon(SC_ICON_EXTERNAL, 'helpExt')) // right-edge marker: this link leaves Typst
    list.appendChild(a)
  }
  const settings = el('button', 'helpItem')
  settings.type = 'button'
  settings.append(icon(SC_ICON_KEYS), el('span', 'helpLb', t('menu.shortcuts')))
  settings.onclick = () => { closeHelp(false); window.openSettingsCategory('shortcuts') }
  list.appendChild(settings)
  const agent = el('button', 'helpItem')
  agent.type = 'button'
  agent.append(icon(SC_ICON_AGENT), el('span', 'helpLb', t('settings.agent')))
  agent.onclick = () => { closeHelp(false); window.openSettingsCategory('api') }
  list.appendChild(agent)
  card.append(head, list)
  ov.replaceChildren(card)
  ov.style.display = 'flex'
  modalInert(true)
  document.querySelectorAll('[data-rail="help"]').forEach(b => b.setAttribute('aria-expanded', 'true'))
  setTimeout(() => { if (ov.style.display !== 'none') { try { list.querySelector('a,button')?.focus() } catch (e) {} } }, 20)
}
function closeHelp(focus = true) {
  const ov = $('helpOverlay')
  if (!ov || ov.style.display === 'none') return
  ov.style.display = 'none'
  if (!$('keySecret') && $('modal').style.display === 'none') modalInert(false) // another modal still owns the background
  document.querySelectorAll('[data-rail="help"]').forEach(b => b.setAttribute('aria-expanded', 'false'))
  if (focus && scHelpPrev && document.contains(scHelpPrev)) { try { scHelpPrev.focus() } catch (e) {} }
  scHelpPrev = null
}
function scOpenShortcutSettings() { closeHelp(false); window.openSettingsCategory('shortcuts') }

window.scHasPendingState = () => !!(scRecordingId || scNotice) // settings category switch: keep the feature state private
window.scKeyLabel = id => { const b = scBinding(id); return b ? scComboLabel(b) : '' }
window.scKeyUnbound = id => !!scAction(id) && !scBinding(id)
window.scRunShortcut = id => { const a = scAction(id); if (!a || (a.when && !a.when())) return false; return a.run() !== false } // menubar proxy: same handler as the key itself
window.openShortcutSettings = scOpenShortcutSettings
window.openHelp = openHelp
$('helpBtn').onclick = () => openHelp()
scPaintEmpty() // features are loaded now: the boot card can show shortcut hints
