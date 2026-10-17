function parseCsv(text, delimiter = ',') {
  const rows = [], row = []; let value = '', quoted = false, pending = false
  for (let i = 0; i < text.length; i++) {
    const c = text[i]; pending = true
    if (c === '"') { if (quoted && text[i + 1] === '"') { value += '"'; i++ } else quoted = !quoted }
    else if (!quoted && (c === delimiter || c === '\n' || c === '\r')) {
      row.push(value); value = ''
      if (c !== delimiter) { rows.push(row.splice(0)); pending = false; if (c === '\r' && text[i + 1] === '\n') i++ }
    } else value += c
  }
  if (pending || value || row.length) { row.push(value); rows.push(row) }
  return rows.length ? rows : [['']]
}
function writeCsv(rows, delimiter = ',') {
  return rows.map(row => row.map(v => /["\r\n]/.test(v) || v.includes(delimiter) ? '"' + v.replaceAll('"', '""') + '"' : v).join(delimiter)).join('\n') + '\n'
}
function csvRectangle(a, b) {
  return { top: Math.min(a[0], b[0]), left: Math.min(a[1], b[1]), bottom: Math.max(a[0], b[0]), right: Math.max(a[1], b[1]) }
}
function csvBlock(rows, rect) {
  return Array.from({ length: rect.bottom - rect.top + 1 }, (_, r) => Array.from({ length: rect.right - rect.left + 1 }, (_, c) => rows[rect.top + r]?.[rect.left + c] || ''))
}
function csvWriteBlock(rows, block, r, c, clear = null) {
  const result = rows.map(row => row.slice())
  if (clear) for (let y = clear.top; y <= clear.bottom; y++) for (let x = clear.left; x <= clear.right; x++) {
    if (result[y]) result[y][x] = ''
  }
  block.forEach((row, dr) => row.forEach((value, dc) => { if (!result[r + dr]) result[r + dr] = []; result[r + dr][c + dc] = value }))
  return result
}
const csvGrid = el('div', 'csvEditor'); csvGrid.hidden = true; csvGrid.tabIndex = 0; $('editWrap').append(csvGrid)
let csvRaw = false, csvIdentity = '', csvSelection = [0, 0], csvAnchor = [0, 0], csvSelected = false, csvEditing = null, csvPointer = null, csvCut = null
let csvDelimiter = ',', csvSource = null, csvRows = [], csvExtent = [200, 40], csvWindow = '', csvEditable = false
const CSV_H = 30, CSV_W = 140, CSV_HEAD = 42
function csvUsed(rows) {
  let height = 0, width = 0
  rows.forEach((row, r) => row.forEach((v, c) => { if (v !== '') { height = Math.max(height, r + 1); width = Math.max(width, c + 1) } }))
  return Array.from({ length: height }, (_, r) => Array.from({ length: width }, (_, c) => rows[r]?.[c] || ''))
}
function csvSave() {
  const rows = csvUsed(csvRows), text = rows.length ? writeCsv(rows, csvDelimiter) : ''
  csvSource = text
  cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: text }, userEvent: 'input' })
}
function csvPut(r, c, value) { if (!csvRows[r]) csvRows[r] = []; csvRows[r][c] = value }
function csvColumn(c) { let label = ''; for (c++; c; c = Math.floor((c - 1) / 26)) label = String.fromCharCode(65 + (c - 1) % 26) + label; return label }
function csvRect() { return csvRectangle(csvAnchor, csvSelection) }
function csvInside(r, c, rect = csvRect()) { return r >= rect.top && r <= rect.bottom && c >= rect.left && c <= rect.right }
function csvPaintSelection() {
  for (const input of csvGrid.querySelectorAll('input[data-row]')) {
    const r = +input.dataset.row, c = +input.dataset.col
    input.parentElement.classList.toggle('csv-selected', csvInside(r, c))
    input.parentElement.classList.toggle('csv-target', !!csvPointer?.target && csvInside(r, c, csvPointer.target))
    input.setAttribute('aria-selected', String(csvInside(r, c)))
    input.parentElement.classList.toggle('csv-proposed', !!window.changeSession && sessionCellChanged(r, c))
  }
}
function csvFocus(r, c, extend = false) {
  r = Math.max(0, r); c = Math.max(0, c)
  csvEditing = null; csvSelection = [r, c]; if (!extend) csvAnchor = [r, c]; csvSelected = true
  csvExtent[0] = Math.max(csvExtent[0], r + 100); csvExtent[1] = Math.max(csvExtent[1], c + 20)
  const x = CSV_HEAD + c * CSV_W, y = CSV_H + r * CSV_H
  if (x < csvGrid.scrollLeft || x + CSV_W > csvGrid.scrollLeft + csvGrid.clientWidth) csvGrid.scrollLeft = Math.max(0, x - CSV_HEAD)
  if (y < csvGrid.scrollTop || y + CSV_H > csvGrid.scrollTop + csvGrid.clientHeight) csvGrid.scrollTop = Math.max(0, y - CSV_H)
  csvWindow = ''; csvRender(); csvGrid.focus({ preventScroll: true })
}
function csvClearSelection() {
  if (!csvEditable) return
  const rect = csvRect()
  csvRows = csvWriteBlock(csvRows, [], 0, 0, rect)
  csvSave(); csvWindow = ''; csvRender(); csvGrid.focus()
}
function csvBeginEdit(initial = null) {
  if (!csvEditable) return
  const [r, c] = csvSelection
  csvAnchor = [r, c]; csvEditing = { r, c, original: csvRows[r]?.[c] || '' }
  const input = csvGrid.querySelector('[data-row="' + r + '"][data-col="' + c + '"]')
  if (!input) return
  input.readOnly = false; input.focus()
  if (initial !== null) { input.value = initial; csvPut(r, c, initial); csvSave(); input.setSelectionRange(initial.length, initial.length) }
  csvPaintSelection()
}
function csvRender() {
  if (csvGrid.hidden) return
  const r0 = Math.max(0, Math.floor(csvGrid.scrollTop / CSV_H) - 2), c0 = Math.max(0, Math.floor(csvGrid.scrollLeft / CSV_W) - 1)
  const rn = Math.ceil((csvGrid.clientHeight || 600) / CSV_H) + 6, cn = Math.ceil((csvGrid.clientWidth || 800) / CSV_W) + 4
  csvExtent[0] = Math.max(csvExtent[0], r0 + rn + 100); csvExtent[1] = Math.max(csvExtent[1], c0 + cn + 20)
  const sig = [r0, c0, rn, cn, csvEditable].join(':')
  if (sig === csvWindow) { csvPaintSelection(); return }
  csvWindow = sig
  const focused = csvEditing && csvGrid.contains(document.activeElement) ? document.activeElement : null
  const pos = focused ? [focused.dataset.row, focused.dataset.col, focused.selectionStart, focused.selectionEnd] : null
  csvGrid.replaceChildren()
  const space = el('div', 'csvSpace'); space.style.width = CSV_HEAD + csvExtent[1] * CSV_W + 'px'; space.style.height = (csvExtent[0] + 1) * CSV_H + 'px'
  const table = el('table'); table.style.left = c0 * CSV_W + 'px'; table.style.top = r0 * CSV_H + 'px'
  const head = el('tr'); head.append(el('th', 'csvRowHead', ''))
  for (let c = c0; c < c0 + cn; c++) head.append(el('th', null, csvColumn(c)))
  table.append(head)
  for (let r = r0; r < r0 + rn; r++) {
    const tr = el('tr'); tr.append(el('th', 'csvRowHead', String(r + 1)))
    for (let c = c0; c < c0 + cn; c++) {
      const td = el('td'), input = el('input'); input.type = 'text'; input.value = csvRows[r]?.[c] || ''; input.spellcheck = false; input.tabIndex = -1
      input.readOnly = !csvEditable || !(csvEditing?.r === r && csvEditing?.c === c)
      input.dataset.row = r; input.dataset.col = c; input.setAttribute('aria-label', csvColumn(c) + (r + 1))
      input.oninput = () => { csvPut(r, c, input.value); csvSave() }
      td.append(input); tr.append(td)
    }
    table.append(tr)
  }
  space.append(table); csvGrid.append(space); csvPaintSelection()
  if (pos) { const input = csvGrid.querySelector('[data-row="' + pos[0] + '"][data-col="' + pos[1] + '"]'); if (input) { input.focus({ preventScroll: true }); input.setSelectionRange(pos[2], pos[3]) } }
}
csvGrid.addEventListener('pointerdown', e => {
  const input = e.target.closest('input[data-row]')
  if (!input || csvEditing?.r === +input.dataset.row && csvEditing?.c === +input.dataset.col) return
  const r = +input.dataset.row, c = +input.dataset.col
  e.preventDefault(); csvEditing = null; csvGrid.focus()
  const move = csvEditable && csvSelected && !e.shiftKey && csvInside(r, c)
  csvPointer = { id: e.pointerId, r, c, rect: csvRect(), move, changed: false, identity: csvIdentity }
  if (!move) { if (!e.shiftKey) csvAnchor = [r, c]; csvSelection = [r, c] }
  csvSelected = true; csvGrid.setPointerCapture(e.pointerId); csvPaintSelection()
})
csvGrid.addEventListener('pointermove', e => {
  if (!csvPointer || csvPointer.id !== e.pointerId) return
  const input = document.elementFromPoint(e.clientX, e.clientY)?.closest('input[data-row]')
  if (!input || !csvGrid.contains(input)) return
  const r = +input.dataset.row, c = +input.dataset.col
  csvPointer.changed ||= r !== csvPointer.r || c !== csvPointer.c
  if (csvPointer.move) {
    const top = Math.max(0, csvPointer.rect.top + r - csvPointer.r), left = Math.max(0, csvPointer.rect.left + c - csvPointer.c)
    csvPointer.target = { top, left, bottom: top + csvPointer.rect.bottom - csvPointer.rect.top, right: left + csvPointer.rect.right - csvPointer.rect.left }
  } else csvSelection = [r, c]
  csvPaintSelection()
})
function csvEndPointer(commit) {
  const pointer = csvPointer; csvPointer = null
  if (commit && pointer?.identity === csvIdentity && pointer.move && pointer.changed && pointer.target && csvEditable) {
    const block = csvBlock(csvRows, pointer.rect)
    csvRows = csvWriteBlock(csvRows, block, pointer.target.top, pointer.target.left, pointer.rect)
    csvAnchor = [pointer.target.top, pointer.target.left]; csvSelection = [pointer.target.bottom, pointer.target.right]; csvSave()
    csvWindow = ''; csvRender()
  }
  csvPaintSelection()
}
csvGrid.addEventListener('pointerup', () => csvEndPointer(true))
csvGrid.addEventListener('pointercancel', () => csvEndPointer(false))
csvGrid.addEventListener('dblclick', e => {
  const input = e.target.closest('input[data-row]')
  if (input) csvSelection = [+input.dataset.row, +input.dataset.col]
  else if (e.target !== csvGrid || !csvSelected) return
  // Pointer capture retargets the click to the grid after a cell selection.
  csvBeginEdit()
})
csvGrid.addEventListener('keydown', e => {
  const [r, c] = csvSelection, key = e.key.toLowerCase(), mod = e.ctrlKey || e.metaKey
  if (csvEditing && !['Enter', 'Tab', 'Escape'].includes(e.key)) return
  if (mod && ['c', 'x', 'v'].includes(key)) return
  if (mod && ['z', 'y'].includes(key)) {
    e.preventDefault(); cm.contentDOM.dispatchEvent(new KeyboardEvent('keydown', { key: e.key, ctrlKey: e.ctrlKey, metaKey: e.metaKey, shiftKey: e.shiftKey, bubbles: true }))
    csvWindow = ''; paintCsv(); csvGrid.focus(); return
  }
  if (e.key === 'Escape') {
    if (csvEditing) { csvPut(r, c, csvEditing.original); csvSave() }
    csvEditing = null; csvCut = null; csvFocus(r, c); return
  }
  const delta = { ArrowLeft: [0, -1], ArrowRight: [0, 1], ArrowUp: [-1, 0], ArrowDown: [1, 0], Enter: [e.shiftKey ? -1 : 1, 0], Tab: [0, e.shiftKey ? -1 : 1] }[e.key]
  if (delta) { e.preventDefault(); csvFocus(r + delta[0], c + delta[1], e.shiftKey && e.key.startsWith('Arrow')); return }
  if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); csvClearSelection(); return }
  if (e.key === 'F2') { e.preventDefault(); csvBeginEdit(); return }
  if (!mod && !e.altKey && e.key.length === 1) { e.preventDefault(); csvBeginEdit(e.key) }
})
for (const type of ['copy', 'cut']) csvGrid.addEventListener(type, e => {
  if (csvEditing) return
  if (type === 'cut' && !csvEditable) return
  const rect = csvRect(), block = csvBlock(csvRows, rect), text = writeCsv(block, '\t').replace(/\n$/, '')
  e.preventDefault(); e.clipboardData.setData('text/plain', text)
  csvCut = type === 'cut' ? { identity: csvIdentity, rect, text, block } : null
})
csvGrid.addEventListener('paste', e => {
  if (csvEditing || !csvEditable) return
  e.preventDefault()
  const text = e.clipboardData.getData('text/plain'), block = parseCsv(text, '\t'), rect = csvRect()
  if (block.reduce((n, row) => n + row.length, 0) > 100000) { toast(t('editor.csvPasteLarge')); return }
  const clear = csvCut?.identity === csvIdentity && csvCut.text === text && writeCsv(csvBlock(csvRows, csvCut.rect), '\t') === writeCsv(csvCut.block, '\t') ? csvCut.rect : null
  if (block.length === 1 && block[0].length === 1 && (rect.bottom > rect.top || rect.right > rect.left) && !clear) {
    for (let r = rect.top; r <= rect.bottom; r++) for (let c = rect.left; c <= rect.right; c++) csvPut(r, c, block[0][0])
    csvAnchor = [rect.top, rect.left]; csvSelection = [rect.bottom, rect.right]; csvSelected = true
  } else {
    csvRows = csvWriteBlock(csvRows, block, rect.top, rect.left, clear)
    csvAnchor = [rect.top, rect.left]; csvSelected = true
    csvSelection = [rect.top + block.length - 1, rect.left + Math.max(...block.map(row => row.length)) - 1]
  }
  csvCut = null; csvSave(); csvWindow = ''; csvRender(); csvGrid.focus()
})
function paintCsv() {
  const on = /\.(csv|tsv)$/i.test(tplName || tabName(activeFile)) && !!(docId || tplName)
  const identity = [docId, tplName, activeFile].join('/')
  if (identity !== csvIdentity) { csvIdentity = identity; csvRaw = false; csvSelection = [0, 0]; csvAnchor = [0, 0]; csvSelected = false; csvEditing = null }
  csvGrid.hidden = !on || csvRaw; $('cmWrap').hidden = on && !csvRaw
  if (!on) { csvSource = null; return }
  const source = getT(), editable = cm.state.facet(EditorView.editable)
  if (source === csvSource && csvEditable === editable) { csvPaintSelection(); return }
  csvSource = source; csvEditable = editable; csvDelimiter = /\.tsv$/i.test(tplName || tabName(activeFile)) ? '\t' : ','; csvRows = parseCsv(source, csvDelimiter); csvWindow = ''
  csvExtent = [Math.max(200, csvRows.length + 100), Math.max(40, ...csvRows.map(r => r.length + 20))]
  csvRender()
}
csvGrid.addEventListener('scroll', csvRender)
new ResizeObserver(() => { csvWindow = ''; csvRender() }).observe(csvGrid)
new MutationObserver(paintCsv).observe($('tabs'), { childList: true })
new MutationObserver(paintCsv).observe($('title'), { childList: true })
new MutationObserver(paintCsv).observe(cm.contentDOM, { attributes: true, attributeFilter: ['contenteditable'] })
paintCsv()
