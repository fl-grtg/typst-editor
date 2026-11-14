const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')

// Only the pure matching/recording helpers: no DOM, no CodeMirror.
const src = fs.readFileSync('web/js/features/shortcuts.js', 'utf8')
const slice = (from, to) => src.slice(src.indexOf(from), src.indexOf(to))
const helpers = [
  slice('const SC_SHIFTLESS', 'const scAppOn'),
  src.split('\n').find(line => line.startsWith('const scAltGr')),
  slice('function scParse', 'function scComboParts'),
  slice('function scKeyFromEvent', 'function scLoadCustom'),
].join('\n')

function realm(mac) {
  const c = vm.createContext({ SC_MAC: mac })
  vm.runInContext(helpers, c)
  return c
}
const ev = over => Object.assign({
  key: '', code: '', ctrlKey: false, metaKey: false, altKey: false, shiftKey: false,
  getModifierState: () => false,
}, over)

test('Meta/Win never completes a binding on non-Mac', () => {
  const w = realm(false)
  assert.equal(w.scMatch(ev({ key: 'b', metaKey: true }), 'b'), false)
  assert.equal(w.scMatch(ev({ key: 'b', metaKey: true, shiftKey: true }), 'shift+b'), false)
  assert.equal(w.scMatch(ev({ key: 'b', ctrlKey: true }), 'mod+b'), true)
})

test('Meta/Win combos are not recorded on non-Mac', () => {
  const w = realm(false)
  assert.equal(w.scComboFromEvent(ev({ key: 'F', code: 'KeyF', metaKey: true, shiftKey: true })), '')
  assert.equal(w.scComboFromEvent(ev({ key: 'F', code: 'KeyF', ctrlKey: true, shiftKey: true })), 'mod+shift+f')
})

test('Mac still records Cmd and distinguishes Ctrl', () => {
  const w = realm(true)
  assert.equal(w.scComboFromEvent(ev({ key: 'F', code: 'KeyF', metaKey: true })), 'mod+f')
  assert.equal(w.scComboFromEvent(ev({ key: 'F', code: 'KeyF', ctrlKey: true })), 'ctrl+f')
  assert.equal(w.scMatch(ev({ key: 'f', metaKey: true }), 'mod+f'), true)
  assert.equal(w.scMatch(ev({ key: 'f', ctrlKey: true }), 'mod+f'), false)
})

test('caret and focus keys count as native inside text targets', () => {
  const w = realm(false)
  for (const combo of ['enter', 'tab', 'shift+tab', 'escape', 'backspace', 'delete', 'home', 'end', 'pageup', 'pagedown', 'arrowleft', 'arrowright', 'space', 'z', '?']) {
    assert.equal(w.scNativeKey(combo), true, combo)
  }
  for (const combo of ['f3', 'mod+c', 'alt+enter', 'ctrl+tab']) {
    assert.equal(w.scNativeKey(combo), false, combo)
  }
})

test('Esc, Backspace and Delete are recordable combos', () => {
  const w = realm(false)
  assert.equal(w.scComboFromEvent(ev({ key: 'Escape' })), 'escape')
  assert.equal(w.scComboFromEvent(ev({ key: 'Backspace' })), 'backspace')
  assert.equal(w.scComboFromEvent(ev({ key: 'Delete' })), 'delete')
})

test('shiftless keys match with and without Shift', () => {
  const w = realm(false)
  assert.equal(w.scMatch(ev({ key: '?', shiftKey: true }), '?'), true)
  assert.equal(w.scMatch(ev({ key: '?', shiftKey: true }), 'shift+?'), false)
  assert.equal(w.scMatch(ev({ key: '+', ctrlKey: true, shiftKey: true }), 'mod+plus'), true)
  assert.equal(w.scCanon('mod+='), 'mod+plus')
})
