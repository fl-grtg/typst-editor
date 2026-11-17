const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')

const source = fs.readFileSync('web/js/20-completions.js', 'utf8')
const complete = source.slice(source.indexOf('function typstComplete'), source.indexOf('function typstHover'))

function completionContext(bibKeys, parser) {
  const c = vm.createContext({
    window: {}, tplName: '', activeFile: '', tabName: () => '', bibKeys, mediaNames: [], getT: () => '',
    projectResources: () => [], t: key => key, T_KW: [], T_SNIP: [], T_BLOCKED: new Set(['LineComment', 'Str', 'Label', 'Ref']),
    typstParser: parser, typstBuiltinSignatures: undefined, pcDoc: null, pcTree: null,
  })
  vm.runInContext(complete, c)
  return c
}

function editor(text, pos = text.length) {
  return {
    pos,
    explicit: false,
    state: { doc: { length: text.length, sliceString: (from, to) => text.slice(from, to), toString: () => text } },
    matchBefore: () => null,
  }
}

test('@ offers bibliography keys alongside the vendor document labels', () => {
  const c = completionContext(['smith2020', 'doe2021'])
  const result = c.typstComplete(editor('@'))
  assert.equal(result.from, 1)
  assert.deepEqual(result.options.map(o => o.label), ['smith2020', 'doe2021'])
  assert.equal(c.typstComplete(editor('@doe')).options[0].label, 'doe2021')
})

test('@ stays quiet without bibliography keys or inside comments', () => {
  assert.equal(completionContext([]).typstComplete(editor('@')), null)
  const tree = text => ({ resolveInner: () => ({ name: text, parent: null }) })
  assert.equal(completionContext(['smith2020'], { parse: () => tree('LineComment') }).typstComplete(editor('// @')), null)
})

test('#cite(< completes a label and consumes an existing closing angle bracket', () => {
  const c = completionContext(['smith2020'])
  const result = c.typstComplete(editor('#cite(<smi'))
  assert.equal(result.from, 7)
  assert.equal(result.options[0].label, 'smith2020')

  const changes = []
  const view = { state: { sliceDoc: (from, to) => '#cite(<smi>'.slice(from, to) }, dispatch: tr => changes.push(tr) }
  result.options[0].apply(view, result.options[0], result.from, 10)
  assert.equal(changes.length, 1)
  assert.deepEqual(JSON.parse(JSON.stringify(changes[0])), { changes: { from: 7, to: 11, insert: 'smith2020>' }, selection: { anchor: 17 }, userEvent: 'input.complete' })
})

test('#cite(" does not offer bibliography keys for the invalid string form', () => {
  assert.equal(completionContext(['smith2020']).typstComplete(editor('#cite("smi')), null)
})
