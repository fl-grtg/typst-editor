const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const path = require('node:path')
const root = path.resolve(__dirname, '../..')
const source = fs.readFileSync(path.join(root, 'web/js/features/file-editors.js'), 'utf8')
const context = vm.createContext({})
vm.runInContext(source.slice(source.indexOf('function parseBib'), source.indexOf('function replaceBib')), context)
const plain = value => JSON.parse(JSON.stringify(value))
const parse = text => plain(context.parseBib(text))

test('bibliography edits preserve other entries, unknown fields and nested values', () => {
  const text = '% Header\n@book{a, title = {Old {nested} title}, year = 2020, custom = {Keep me}}\n@article{b, title = "Untouched"}'
  const entries = parse(text)
  assert.equal(entries.length, 2)
  const field = entries[0].fields.find(f => f.name === 'title')
  assert.equal(field.value, 'Old {nested} title')
  const edited = text.slice(0, field.from) + '{New title}' + text.slice(field.to)
  assert.ok(edited.includes('custom = {Keep me}'))
  assert.ok(edited.endsWith('@article{b, title = "Untouched"}'))
  assert.equal(parse(edited)[0].fields.find(f => f.name === 'title').value, 'New title')
})

test('macro concatenation and special entries stay available in source mode', () => {
  const entries = parse('@string{publisher="Press"}\n@comment{Ignore @book{fake,}}\n@book{a, title={Part} # {Two}, publisher=publisher}')
  assert.equal(entries.length, 1)
  assert.equal(entries[0].fields.find(f => f.name === 'title').simple, false)
  assert.equal(entries[0].fields.find(f => f.name === 'publisher').simple, false)
  assert.equal(context.bibSimpleValue('{Part {Nested}}'), true)
  assert.equal(context.bibSimpleValue('"Part" # "Two"'), false)
})

test('parenthesized bibliography records and incomplete input are handled safely', () => {
  const entries = parse('@book(a, title={Text (with parentheses)}, year=2026)\n@book{unfinished, title={')
  assert.equal(entries[0].fields[0].value, 'Text (with parentheses)')
  assert.equal(entries[0].invalid, undefined)
  assert.equal(entries[1].invalid, true)
})

test('CSV and TSV preserve quoted tabs, line breaks and empty fields', () => {
  const csv = fs.readFileSync(path.join(root, 'web/js/features/csv.js'), 'utf8')
  const ctx = vm.createContext({})
  vm.runInContext(csv.slice(0, csv.indexOf('const csvGrid')), ctx)
  const rows = [['Name', 'Value'], ['A\tB', 'line\nnext'], ['"quoted"', '']]
  for (const delimiter of [',', '\t']) {
    const encoded = ctx.writeCsv(rows, delimiter)
    assert.deepEqual(plain(ctx.parseCsv(encoded, delimiter)), rows)
  }
})

test('bundled data parsers reject invalid JSON, YAML and TOML', async () => {
  const { pathToFileURL } = require('node:url')
  const bundle = await import(pathToFileURL(path.join(root, 'vendor-cm.js')).href)
  assert.deepEqual(bundle.parseYaml('title: Test'), { title: 'Test' })
  assert.deepEqual(plain(bundle.parseToml('title = "Test"')), { title: 'Test' })
  assert.throws(() => bundle.parseYaml('value: [unterminated'))
  assert.throws(() => bundle.parseToml('title = '))
  assert.throws(() => JSON.parse('{broken'))
})


test('canceling file type selection closes the nested creation flow', async () => {
  const files = fs.readFileSync(path.join(root, 'web/js/80-files-images.js'), 'utf8')
  const funcs = files.slice(files.indexOf('async function chooseFileType'), files.indexOf('async function deleteFile'))
  const calls = []
  const ctx = vm.createContext({ FILE_TYPES: ['typ', 'bib'], t: k => k, askPick: async () => calls.length ? -1 : (calls.push('picker'), 0), newFile: ext => calls.push(ext) })
  vm.runInContext(funcs, ctx)
  await ctx.tabAdd()
  assert.deepEqual(calls, ['picker'])
  for (const value of [-1, null, undefined, 99]) { ctx.askPick = async () => value; assert.equal(await ctx.chooseFileType(), null) }
  ctx.askPick = async () => 0
  assert.equal(await ctx.chooseFileType(), '.typ')
})


test('Typst text formatting cannot corrupt data or bibliography buffers', () => {
  const code = fs.readFileSync(path.join(root, 'web/js/98-format-toolbar.js'), 'utf8')
  let formatted = 0
  const ctx = vm.createContext({ tplName: 'data.csv', activeFile: '', tabName: () => 'main.typ', cm: { state: { facet: () => true }, focus: () => {} }, EditorView: { editable: {} }, fmtWrap: () => formatted++ })
  vm.runInContext(code.slice(code.indexOf('function fmtApply'), code.indexOf('document.querySelectorAll')), ctx)
  for (const name of ['data.csv', 'data.tsv', 'references.bib', 'data.json']) { ctx.tplName = name; ctx.fmtApply('bold') }
  assert.equal(formatted, 0)
  ctx.tplName = 'module.typ'; ctx.fmtApply('bold')
  assert.equal(formatted, 1)
})


test('empty years created by the bibliography form are removed without changing other fields', () => {
  const original = '@book{a, title={Keep}, year={}, custom={Unchanged}}\n@book{b, year={2020}}'
  const changes = plain(context.emptyBibYearChanges(original))
  assert.equal(changes.length, 1)
  let cleaned = original
  for (const change of changes.reverse()) cleaned = cleaned.slice(0, change.from) + change.insert + cleaned.slice(change.to)
  assert.ok(cleaned.includes('title={Keep}'))
  assert.ok(cleaned.includes('custom={Unchanged}'))
  assert.ok(cleaned.includes('year={2020}'))
  assert.equal(parse(cleaned)[0].fields.some(f => f.name === 'year'), false)
  assert.deepEqual(plain(context.emptyBibYearChanges(cleaned)), [])
})
