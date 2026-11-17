const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')

// Only the toast helper and its module state: no imports, no DOM.
const src = fs.readFileSync('web/js/00-imports.js', 'utf8')
const toastSrc = src.slice(src.indexOf('let toastT = 0'), src.indexOf('\nconst sleep'))

function toastRealm() {
  const box = {
    id: 'toast', style: {}, children: [],
    classList: { toggle() {} },
    setAttribute() {},
    replaceChildren() { this.children.length = 0 },
    appendChild(c) { this.children.push(c); return c },
  }
  const timers = new Map()
  let now = 0, seq = 0
  const element = tag => ({
    tag, style: {}, children: [], textContent: '',
    classList: { toggle() {} },
    setAttribute() {},
    replaceChildren() { this.children.length = 0 },
    appendChild(c) { this.children.push(c); return c },
  })
  const c = vm.createContext({
    window: {},
    $: id => id === 'toast' ? box : null,
    document: { createElement: element, body: { appendChild() {} } },
    t: key => key,
    Date: { now: () => now },
    setTimeout: (fn, ms) => { timers.set(++seq, { fn, at: now + (ms || 0) }); return seq },
    clearTimeout: id => timers.delete(id),
  })
  vm.runInContext(toastSrc, c)
  // advance(ms) runs every timer that comes due, including timers they schedule on the way.
  const advance = ms => {
    const target = now + ms
    for (;;) {
      const due = [...timers.entries()].filter(([, t]) => t.at <= target).sort((a, b) => a[1].at - b[1].at)
      if (!due.length) break
      timers.delete(due[0][0])
      now = due[0][1].at
      due[0][1].fn()
    }
    now = target
  }
  return { c, box, advance }
}

test('a replacement toast stays visible when the previous fade timer fires', () => {
  const { c, box, advance } = toastRealm()
  c.toast('Formatted', false, '', 1000)
  advance(1000) // the old toast starts fading; its 400 ms hide timer is now pending
  c.toast('Shortcut “Format document” cleared', () => {}, 'Undo', 5000)
  advance(400)
  assert.equal(box.style.display, 'flex')
  assert.equal(box.style.opacity, '1')
  assert.equal(box.children[0].textContent, 'Shortcut “Format document” cleared')
})

test('undo hides the toast without leaving a pending hide timer', () => {
  const { c, box, advance } = toastRealm()
  c.toast('Shortcut cleared', () => {}, 'Undo', 1000)
  advance(1000) // fading, the inner hide timer is pending
  box.children[1].onclick() // undo before the old toast finishes fading
  c.toast('Saved')
  advance(400)
  assert.equal(box.style.display, 'block')
})
