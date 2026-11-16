const assert = require('node:assert/strict')
const { test } = require('node:test')
const { readFileSync } = require('node:fs')
const vm = require('node:vm')
const inbox = readFileSync('web/js/features/inbox.js', 'utf8')

function classList(node) {
  return {
    add: name => { node.className = [node.className, name].filter(Boolean).join(' ') },
    remove: name => { node.className = node.className.split(' ').filter(c => c && c !== name).join(' ') },
  }
}
class Element {
  constructor(tag) {
    this.tagName = tag
    this.children = []
    this.dataset = {}
    this.style = {}
    this.attributes = {}
    this.className = ''
    this.parentNode = null
    this.offsetWidth = 120
    this.offsetHeight = 90
  }
  get isConnected() {
    for (let n = this; n; n = n.parentNode) if (n === this.ownerDocument?.body) return true
    return false
  }
  appendChild(child) { this.children.push(child); child.parentNode = this; return child }
  append(...children) { children.forEach(c => this.appendChild(c)) }
  setAttribute(name, value) { this.attributes[name] = String(value) }
  getAttribute(name) { return this.attributes[name] ?? null }
  hasAttribute(name) { return name in this.attributes }
  removeAttribute(name) { delete this.attributes[name] }
  querySelectorAll(selector) {
    const cls = selector.startsWith('.') ? selector.slice(1) : null
    const out = []
    const walk = node => {
      for (const child of node.children) {
        if (cls && child.className.split(' ').includes(cls)) out.push(child)
        walk(child)
      }
    }
    walk(this)
    return out
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null }
  contains(node) {
    for (let n = node; n; n = n.parentNode) if (n === this) return true
    return false
  }
  closest() { return { classList: classList(this) } }
  getBoundingClientRect() { return { bottom: 10, left: 10 } }
  focus() { this.focused = true }
  blur() { this.focused = false }
  remove() {
    if (this.parentNode) this.parentNode.children = this.parentNode.children.filter(n => n !== this)
    this.parentNode = null
  }
}
function makeDom() {
  const doc = {
    listeners: { pointerdown: new Set(), keydown: new Set() },
    addEventListener: (type, fn) => doc.listeners[type]?.add(fn),
    removeEventListener: (type, fn) => doc.listeners[type]?.delete(fn),
    createElement: tag => { const n = new Element(tag); n.ownerDocument = doc; return n },
    querySelectorAll: () => [],
  }
  doc.body = new Element('body'); doc.body.ownerDocument = doc
  doc.getElementById = id => {
    const walk = node => {
      for (const child of node.children) {
        if (child.id === id) return child
        const found = walk(child)
        if (found) return found
      }
      return null
    }
    return walk(doc.body)
  }
  return doc
}
function context(doc, extra = {}) {
  const timer = []
  const stub = new Element('div'); stub.ownerDocument = doc
  const c = vm.createContext({
    document: doc, window: {}, t: key => key, api: async () => ({}), toast: () => {},
    svgI: () => '', el: (tag, cls, text) => { const n = doc.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n },
    icoBtn: () => doc.createElement('button'), $: () => stub, kb: () => {},
    setTimeout: fn => timer.push(fn), innerWidth: 1000, innerHeight: 800, ...extra,
  })
  vm.runInContext(inbox, c)
  return { c, timer }
}
function watchButton(doc) {
  const btn = doc.createElement('button')
  btn.focus = () => { // row actions are visibility:hidden until hovered, expanded or focused
    const visible = btn.className.split(' ').includes('menu-open') ||
      btn.attributes['aria-expanded'] === 'true' || btn.focused
    if (visible) btn.focused = true
  }
  doc.body.appendChild(btn)
  return btn
}

test('closing the watch menu removes its document pointer and Escape listeners', () => {
  const doc = makeDom(), { c } = context(doc), btn = watchButton(doc)
  c.openWatchBox({ id: 'p' }, btn)
  assert.ok(doc.getElementById('watchBox'))
  assert.equal(doc.listeners.pointerdown.size, 1)
  assert.equal(doc.listeners.keydown.size, 1)
  c.closeWatchBox()
  assert.equal(doc.getElementById('watchBox'), null)
  assert.equal(doc.listeners.pointerdown.size, 0)
  assert.equal(doc.listeners.keydown.size, 0)
  assert.equal(btn.attributes['aria-expanded'], 'false')
})

test('Escape closes the watch menu, restores focus and cleans up', () => {
  const doc = makeDom(), { c } = context(doc), btn = watchButton(doc)
  c.openWatchBox({ id: 'p' }, btn)
  const esc = [...doc.listeners.keydown][0]
  esc({ key: 'Escape', stopPropagation() {} })
  assert.equal(doc.getElementById('watchBox'), null)
  assert.equal(btn.focused, true)
  assert.equal(doc.listeners.keydown.size, 0)
  assert.equal(doc.listeners.pointerdown.size, 0)
})

test('a pointer outside closes the watch menu but one inside keeps it', () => {
  const doc = makeDom(), { c } = context(doc), btn = watchButton(doc)
  c.openWatchBox({ id: 'p' }, btn)
  const off = [...doc.listeners.pointerdown][0], inside = doc.getElementById('watchBox').children[0]
  off({ target: inside })
  assert.ok(doc.getElementById('watchBox'))
  off({ target: doc.body })
  assert.equal(doc.getElementById('watchBox'), null)
  assert.equal(btn.focused, false)
  assert.equal(doc.listeners.pointerdown.size, 0)
  assert.equal(doc.listeners.keydown.size, 0)
})
