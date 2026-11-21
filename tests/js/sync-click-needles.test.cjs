const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const settings = fs.readFileSync('web/js/90-settings.js', 'utf8')
const needles = settings.slice(settings.indexOf('function pvCaptionCut'), settings.indexOf('const SRC_MATH'))
const syncText = settings.slice(settings.indexOf('function syncText'), settings.indexOf('function syncPlain'))
const ctx = vm.createContext({})
vm.runInContext(needles + syncText, ctx)

// PDF runs as Typst emits them: the generated marker is its own item on the
// same visual line as the source text it belongs to.
function item(s, x0, w, y = 100, h = 10) {
  return { s, x0, w, y, h, rot: false, vw: 600, vh: 800 }
}

test('a footnote number asks for its body line, not for the generated digit', () => {
  const items = [item('Body line with a note.', 0, 110), item('1', 112, 5)]
  const out = ctx.pvClickNeedles(items, items[1], 0)
  assert.ok(out.some(n => n.s === 'Body line with a note.'), JSON.stringify(out))
})

test('a citation marker keeps the sentence that cites it', () => {
  const items = [item('As shown before', 0, 90), item('[1]', 92, 14), item('the value holds.', 108, 80)]
  const out = ctx.pvClickNeedles(items, items[1], 0)
  assert.ok(out.some(n => n.s === 'As shown before the value holds.'), JSON.stringify(out))
})

test('an ordered-list number asks for the item text, never for the marker alone', () => {
  const items = [item('1.', 0, 10), item('First numbered item here', 14, 140)]
  const out = ctx.pvClickNeedles(items, items[0], 0)
  assert.ok(out.some(n => n.s === 'First numbered item here'), JSON.stringify(out))
})

test('a marker without any line text invents no needle', () => {
  const out = ctx.pvClickNeedles([item('1', 0, 5)], item('1', 0, 5), 0)
  assert.equal(out.length, 0)
})

test('a real word still prefers its own run over the stripped line', () => {
  const items = [item('Body line', 0, 60), item('with a note.', 62, 70)]
  const out = ctx.pvClickNeedles(items, items[1], 0)
  assert.ok(out.some(n => n.s === 'with a note.'), JSON.stringify(out))
})
