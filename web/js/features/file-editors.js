const fileLanguages = { typ: typstSupport, json: CMV.json(), yaml: CMV.yaml(), yml: CMV.yaml(), xml: CMV.xml(), csl: CMV.xml(), toml: CMV.StreamLanguage.define(CMV.toml) }
const fileStatus = el('div', 'fileStatus'); fileStatus.hidden = true; $('leftCol').insertBefore(fileStatus, $('editWrap'))
const bibPanel = el('div', 'bibEditor'); bibPanel.hidden = true; $('editWrap').append(bibPanel)
const emptyFileLanguage = []
let bibEditing = false
let bibQuery = ''
let bibSource = null, bibSelected = 0, bibRaw = false, bibIdentity = '', bibEditable = false, validationTimer = 0
function parseBib(text) {
  const entries = [], re = /@(\w+)\s*([{(])/g; let match
  while ((match = re.exec(text))) {
    const from = match.index, open = match[2], close = open === '{' ? '}' : ')', body = re.lastIndex
    let depth = 1, quote = false, braces = 0, end = body
    for (; end < text.length; end++) {
      const ch = text[end]
      if (ch === '\\') { end++; continue }
      if (ch === '"' && depth === 1) quote = !quote
      if (quote) continue
      if (open === '(') { if (ch === '{') braces++; if (ch === '}') braces--; if (braces || ch === '}') continue }
      if (ch === open) depth++
      else if (ch === close && --depth === 0) break
    }
    if (depth) { entries.push({ from, to: text.length, type: match[1], invalid: true, fields: [] }); break }
    re.lastIndex = end + 1
    if (/^(comment|string|preamble)$/i.test(match[1])) continue
    const comma = text.indexOf(',', body)
    if (comma < body || comma >= end) { entries.push({ from, to: end + 1, type: match[1], invalid: true, fields: [] }); continue }
    const entry = { from, to: end + 1, type: match[1], typeFrom: from + 1, typeTo: from + 1 + match[1].length, key: text.slice(body, comma).trim(), keyFrom: body, keyTo: comma, fields: [], end }
    let pos = comma + 1
    while (pos < end) {
      const field = /^\s*,?\s*([\w-]+)\s*=\s*/.exec(text.slice(pos, end))
      if (!field) { if (text.slice(pos, end).trim()) entry.invalid = true; break }
      const valueFrom = pos + field[0].length
      let stop = valueFrom, braces = 0, quoted = false
      for (; stop < end; stop++) {
        const ch = text[stop]
        if (ch === '\\') { stop++; continue }
        if (ch === '"' && !braces) quoted = !quoted
        if (!quoted) { if (ch === '{') braces++; else if (ch === '}') braces--; else if (ch === ',' && !braces) break }
      }
      const raw = text.slice(valueFrom, stop).trimEnd(), valueTo = valueFrom + raw.length
      const simple = bibSimpleValue(raw)
      entry.fields.push({ statementFrom: pos, statementTo: Math.min(end, stop + 1), name: field[1], from: valueFrom, to: valueTo, value: simple && (raw.startsWith('{') || raw.startsWith('"')) ? raw.slice(1, -1) : raw, simple })
      pos = stop + 1
    }
    entries.push(entry)
  }
  return entries
}
function bibSimpleValue(raw) {
  if (/^\d+$/.test(raw)) return true
  if (raw[0] !== '{' && raw[0] !== '"') return false
  let depth = 0
  for (let i = 0; i < raw.length; i++) {
    const ch = raw[i]
    if (ch === '\\') { i++; continue }
    if (raw[0] === '"') { if (i && ch === '"') return i === raw.length - 1 }
    else { if (ch === '{') depth++; if (ch === '}' && --depth === 0) return i === raw.length - 1 }
  }
  return false
}
function emptyBibYearChanges(text) {
  return parseBib(text).flatMap(e => e.invalid ? [] : e.fields.filter(f => f.name.toLowerCase() === 'year' && f.simple && !f.value.trim()).map(f => ({ from: f.statementFrom, to: f.statementTo, insert: '' })))
}
function replaceBib(from, to, text) {
  if (!cm.state.facet(EditorView.editable)) return
  if (bibEditing) bibSource = getT().slice(0, from) + text + getT().slice(to)
  cm.dispatch({ changes: { from, to, insert: text }, userEvent: 'input' })
}
function paintBib() {
  const on = /\.bib$/i.test(tplName || tabName(activeFile)) && !!(docId || tplName)
  bibPanel.hidden = !on || bibRaw
  $('cmWrap').style.paddingTop = ''
  if (!on) { bibSource = null; return }
  const identity = [docId, tplName, activeFile].join('/')
  if (identity !== bibIdentity) { bibIdentity = identity; bibSelected = 0; bibRaw = false; bibQuery = '' }
  $('cmWrap').hidden = !bibRaw
  bibPanel.hidden = bibRaw
  const source = getT(), editable = cm.state.facet(EditorView.editable)
  const emptyYears = editable ? emptyBibYearChanges(source) : []
  if (emptyYears.length) { queueMicrotask(() => { if (identity === bibIdentity && source === getT() && cm.state.facet(EditorView.editable)) cm.dispatch({ changes: emptyYears, userEvent: 'input' }) }); return }
  if (source === bibSource && editable === bibEditable) return
  const listScroll = bibPanel.querySelector('.bibList')?.scrollTop || 0
  bibSource = source; bibEditable = editable; bibPanel.replaceChildren()
  const bar = el('div', 'bibBar'), raw = el('button', 'btn', t(bibRaw ? 'editor.entries' : 'editor.source'))
  raw.onclick = () => { bibRaw = !bibRaw; bibSource = null; paintBib() }
  const add = el('button', 'btn', t('editor.newEntry')); add.disabled = !editable
  add.onclick = async () => {
    const identity = bibIdentity, key = await ask(t('editor.entryKey'), { ph: 'author2026' })
    if (!key || identity !== bibIdentity || !cm.state.facet(EditorView.editable)) return
    const clean = key.trim().replace(/[^\w:.-]/g, '_')
    if (parseBib(getT()).some(e => e.key === clean)) { toast(t('common.nameExists')); return }
    bibSelected = parseBib(getT()).length
    replaceBib(getT().length, getT().length, `\n@book{${clean},\n}\n`)
  }
  bar.append(raw, add); bibPanel.append(bar)
  if (bibRaw) { bibPanel.classList.add('sourceMode'); return }
  bibPanel.classList.remove('sourceMode')
  const entries = parseBib(source), body = el('div', 'bibBody'), list = el('div', 'bibList'), form = el('div', 'bibForm')
  bibSelected = Math.min(bibSelected, Math.max(0, entries.length - 1))
  const search = el('input'); search.type = 'search'; search.placeholder = t('editor.searchEntries'); search.setAttribute('aria-label', search.placeholder)
  search.value = bibQuery
  search.oninput = () => { bibQuery = search.value; list.querySelectorAll('button').forEach(b => { b.hidden = !b.textContent.toLowerCase().includes(bibQuery.toLowerCase()) }) }
  list.append(search)
  entries.forEach((entry, i) => {
    const b = el('button', 'bibEntry' + (i === bibSelected ? ' on' : ''))
    b.append(el('span', 'bibEntryKey', entry.key || '@' + entry.type), el('span', 'bibEntryTitle', entry.fields.find(f => f.name === 'title')?.value || entry.type))
    b.onclick = () => { bibSelected = i; bibSource = null; paintBib() }; list.append(b)
  })
  search.oninput()
  body.append(list, form); bibPanel.append(body); list.scrollTop = listScroll
  const entry = entries[bibSelected]
  if (!entry) { form.append(el('p', null, t('editor.emptyEntries'))); return }
  if (entry.invalid) { form.append(el('p', null, t('editor.bibInvalid'))); return }
  let target = form
  const metadata = el('div', 'bibMetadata'); form.append(metadata); target = metadata
  function field(label, value, save, multiline, disabled) {
    const row = el('label', 'bibField'), input = el(label === t('editor.entryType') ? 'select' : multiline ? 'textarea' : 'input')
    if (input.tagName === 'SELECT') for (const type of [...new Set([value, 'book', 'article', 'inproceedings', 'incollection', 'thesis', 'report', 'online', 'misc'])]) { const option = el('option', null, type); option.value = type; input.append(option) }
    if (multiline) input.rows = 1
    row.append(el('span', null, label)); input.value = value; input.spellcheck = false
    if (multiline) input.style.height = Math.min(134, 38 + 18 * (value.split('\n').length - 1)) + 'px'
    input.readOnly = !editable || !!disabled
    if (input.tagName === 'SELECT') input.disabled = !editable || !!disabled
    input.oninput = () => {
      if (multiline) { input.style.height = '38px'; input.style.height = Math.min(134, Math.max(38, input.scrollHeight)) + 'px' }
      const latest = parseBib(getT())[bibSelected]
      if (!latest || latest.invalid) return
      if (label === t('editor.field_year') && input.value && !/^\d{4}$/.test(input.value)) { input.setCustomValidity(t('editor.yearHint')); return }
      input.setCustomValidity('')
      bibEditing = true
      try { save(latest, input.value) } finally { bibEditing = false }
      bibSource = getT()
      const button = bibPanel.querySelectorAll('.bibList button')[bibSelected], current = parseBib(bibSource)[bibSelected]
      if (button && current) { button.querySelector('.bibEntryKey').textContent = current.key || '@' + current.type; button.querySelector('.bibEntryTitle').textContent = current.fields.find(f => f.name === 'title')?.value || current.type }
    }
    input.onchange = input.oninput
    row.append(input); target.append(row)
  }
  field(t('editor.entryKey'), entry.key, (e, value) => { if (/^[\w:.-]+$/.test(value) && !parseBib(getT()).some((x, i) => i !== bibSelected && x.key === value)) replaceBib(e.keyFrom, e.keyTo, value) })
  field(t('editor.entryType'), entry.type, (e, value) => { if (/^[a-zA-Z]+$/.test(value)) replaceBib(e.typeFrom, e.typeTo, value) })
  const mainFields = el('div', 'bibMainFields'), extras = el('details', 'bibMoreFields'); extras.append(el('summary', null, t('editor.moreFields')))
  form.append(mainFields, extras)
  const names = [...new Set(['title', 'author', 'year', 'doi', 'url', ...entry.fields.map(f => f.name), 'publisher', 'journal'])]
  const labels = { title: t('editor.field_title'), author: t('editor.field_author'), year: t('editor.field_year'), doi: t('editor.field_doi'), url: t('editor.field_url') }
  names.forEach(name => {
    const existing = entry.fields.find(f => f.name === name)
    target = labels[name] ? mainFields : extras
    field(labels[name] || name, existing?.value || '', (e, value) => {
      const f = e.fields.find(f => f.name === name)
      if (f && !f.simple) return
      // Keep macros, unknown fields and comments outside the edited value intact.
      let depth = 0
      for (const ch of value) { if (ch === '{') depth++; if (ch === '}') depth-- }
      if (depth !== 0) return
      if (!value) { if (f) replaceBib(f.statementFrom, f.statementTo, ''); return }
      const text = '{' + value + '}'
      if (f) replaceBib(f.from, f.to, text)
      else { const before = getT().slice(e.from, e.end).trimEnd(); replaceBib(e.end, e.end, (before.endsWith(',') ? '' : ',') + '\n  ' + name + ' = ' + text + ',\n') }
    }, ['title', 'author'].includes(name), existing && !existing.simple)
  })
  const remove = el('button', 'btn', t('editor.deleteEntry')); remove.disabled = !editable
  remove.onclick = async () => {
    const identity = bibIdentity, key = entry.key
    if (!await ask(t('editor.deleteEntry') + ': ' + key, { noInput: true, danger: true, ok: t('common.delete') })) return
    if (identity !== bibIdentity) return
    const latest = parseBib(getT()).find(e => e.key === key)
    if (latest) replaceBib(latest.from, latest.to, '')
  }
  const footer = el('div', 'bibFooter'); footer.append(remove); form.append(footer)
}
function paintFileExtras() {
  const name = tplName || tabName(activeFile), ext = name.split('.').pop().toLowerCase(), language = fileLanguages[ext] || emptyFileLanguage
  if (languageComp.get(cm.state) !== language) cm.dispatch({ effects: languageComp.reconfigure(language) })
  paintBib(); syncFileToolbar(ext)
  fileStatus.hidden = !['json', 'yaml', 'yml', 'toml', 'xml', 'csl'].includes(ext) || !(docId || tplName)
  clearTimeout(validationTimer)
  if (fileStatus.hidden) return
  const source = getT(), identity = [docId, tplName, activeFile].join('/')
  validationTimer = setTimeout(() => {
    if (source !== getT() || identity !== [docId, tplName, activeFile].join('/')) return
    try {
      if (source.trim()) {
        if (ext === 'json') JSON.parse(source)
        if (ext === 'yaml' || ext === 'yml') CMV.parseYaml(source)
        if (ext === 'toml') CMV.parseToml(source)
        if (ext === 'xml' || ext === 'csl') { const doc = new DOMParser().parseFromString(source, 'application/xml'); const error = doc.querySelector('parsererror'); if (error) throw Error(error.textContent) }
      }
      fileStatus.textContent = t('editor.validData'); fileStatus.classList.remove('invalid')
    } catch (e) { fileStatus.textContent = t('editor.invalidData', { msg: e.message }); fileStatus.classList.add('invalid') }
  }, 250)
}
const bibTools = el('span', 'fmt fileTools'), bibSwitch = el('button'), bibNew = el('button')
bibSwitch.onclick = () => { bibRaw = !bibRaw; bibSource = null; paintBib(); syncFileToolbar('bib') }
bibNew.onclick = () => bibPanel.querySelector('.bibBar button:nth-child(2)')?.click()
bibTools.append(bibSwitch, bibNew); $('tools').insertBefore(bibTools, $('tools').querySelector('.tsp'))
const gridTools = el('span', 'fmt fileTools gridTools'), gridSwitch = el('button'), gridClear = el('button')
gridSwitch.onclick = () => { csvRaw = !csvRaw; csvSource = null; paintCsv(); if (!csvRaw) { csvWindow = ''; csvRender() } syncFileToolbar((tplName || tabName(activeFile)).split('.').pop()) }
gridClear.onmousedown = e => e.preventDefault()
gridClear.onclick = () => { if (!cm.state.facet(EditorView.editable)) return; csvPut(csvSelection[0], csvSelection[1], ''); csvSave(); csvWindow = ''; csvRender(); csvFocus(...csvSelection) }
gridTools.append(gridSwitch, gridClear); $('tools').insertBefore(gridTools, $('tools').querySelector('.tsp'))
const TOOL_ICONS = {
  source: '<path d="M5 4L1 8l4 4M11 4l4 4-4 4M9 2L7 14"/>',
  cells: '<rect x="2" y="2" width="12" height="12" rx="1"/><path d="M2 6h12M2 10h12M6 2v12M10 2v12"/>',
  entries: '<path d="M5 4h9M5 8h9M5 12h9M2 4h.1M2 8h.1M2 12h.1"/>',
  new: '<path d="M8 3v10M3 8h10"/>',
  clear: '<path d="M6 3l7 7-3 3H6L2 9zM6 13h8"/>'
}
function toolIcon(button, key, icon) {
  if (button.dataset.icon !== icon) { button.innerHTML = svgI(TOOL_ICONS[icon]); button.dataset.icon = icon }
  const label = t(key); button.title = label; button.setAttribute('aria-label', label)
}
function syncFileToolbar(ext) {
  const typst = ext === 'typ', bib = ext === 'bib', grid = ['csv', 'tsv'].includes(ext), editable = cm.state.facet(EditorView.editable)
  for (const group of $('tools').querySelectorAll('.fmt')) {
    if (group.classList.contains('fileTools')) { group.hidden = group.classList.contains('gridTools') ? !grid : !bib; continue }
    const formatting = group.querySelector('[data-fmt]')
    group.classList.toggle('type-hidden', !!formatting && !typst)
  }
  for (const id of ['cNew', 'imgBtn', 'mediaBtn', 'tplBtn', 'symBtn', 'colWrap', 'citeLibrary']) $(id)?.classList.toggle('type-hidden', !typst)
  $('histBtn').classList.toggle('type-hidden', !docId || !!tplName)
  if (docId && !openedTrashed) $('histBtn').style.display = ''
  updateFileView()
  $('fmtDoc')?.classList.toggle('type-hidden', !['typ', 'json'].includes(ext))
  $('tools').querySelector('.grp')?.classList.toggle('type-hidden', (grid && !csvRaw) || (bib && !bibRaw))
  $('tools').dataset.format = ext
  toolIcon(gridSwitch, csvRaw ? 'editor.cells' : 'editor.source', csvRaw ? 'cells' : 'source')
  toolIcon(gridClear, 'editor.clearCell', 'clear'); gridClear.disabled = !editable; gridClear.hidden = csvRaw
  toolIcon(bibSwitch, bibRaw ? 'editor.entries' : 'editor.source', bibRaw ? 'entries' : 'source')
  toolIcon(bibNew, 'editor.newEntry', 'new'); bibNew.disabled = !editable
  const last = $('tools').querySelector('.fmt.last'); last.classList.toggle('type-hidden', ![...last.children].some(b => !b.hidden && !b.classList.contains('type-hidden') && b.style.display !== 'none'))
}
window.paintFileExtras = paintFileExtras
new MutationObserver(() => { paintCsv(); paintFileExtras() }).observe($('tabs'), { childList: true })
new MutationObserver(() => { paintCsv(); paintFileExtras() }).observe($('title'), { childList: true })
new MutationObserver(() => { paintCsv(); paintFileExtras() }).observe(cm.contentDOM, { attributes: true, attributeFilter: ['contenteditable'] })
paintFileExtras()
