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
const csvGrid = el('div', 'csvEditor'); csvGrid.hidden = true; $('editWrap').append(csvGrid)
let csvRaw = false, csvIdentity = '', csvSelection = [0, 0]
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
function csvFocus(r, c) {
  r = Math.max(0, r); c = Math.max(0, c)
  csvExtent[0] = Math.max(csvExtent[0], r + 100); csvExtent[1] = Math.max(csvExtent[1], c + 20)
  const x = CSV_HEAD + c * CSV_W, y = CSV_H + r * CSV_H
  if (x < csvGrid.scrollLeft || x + CSV_W > csvGrid.scrollLeft + csvGrid.clientWidth) csvGrid.scrollLeft = Math.max(0, x - CSV_HEAD)
  if (y < csvGrid.scrollTop || y + CSV_H > csvGrid.scrollTop + csvGrid.clientHeight) csvGrid.scrollTop = Math.max(0, y - CSV_H)
  csvWindow = ''; csvRender()
  csvGrid.querySelector(`[data-row="${r}"][data-col="${c}"]`)?.focus()
}
function csvRender() {
  if (csvGrid.hidden) return
  const r0 = Math.max(0, Math.floor(csvGrid.scrollTop / CSV_H) - 2), c0 = Math.max(0, Math.floor(csvGrid.scrollLeft / CSV_W) - 1)
  const rn = Math.ceil((csvGrid.clientHeight || 600) / CSV_H) + 6, cn = Math.ceil((csvGrid.clientWidth || 800) / CSV_W) + 4
  csvExtent[0] = Math.max(csvExtent[0], r0 + rn + 100); csvExtent[1] = Math.max(csvExtent[1], c0 + cn + 20)
  const sig = [r0, c0, rn, cn, csvEditable].join(':')
  if (sig === csvWindow) return
  csvWindow = sig
  const focused = csvGrid.contains(document.activeElement) ? document.activeElement : null
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
      const td = el('td'), input = el('input'); input.type = 'text'; input.value = csvRows[r]?.[c] || ''; input.spellcheck = false; input.readOnly = !csvEditable
      input.dataset.row = r; input.dataset.col = c; input.setAttribute('aria-label', csvColumn(c) + (r + 1))
      input.onfocus = () => { csvSelection = [r, c] }
      input.oninput = () => { csvPut(r, c, input.value); csvSave() }
      input.onkeydown = e => {
        if (e.key === 'ArrowLeft' && input.selectionStart === 0 && input.selectionEnd === 0) { e.preventDefault(); csvFocus(r, c - 1); return }
        if (e.key === 'ArrowRight' && input.selectionStart === input.value.length) { e.preventDefault(); csvFocus(r, c + 1); return }
        const delta = { Enter: [e.shiftKey ? -1 : 1, 0], Tab: [0, e.shiftKey ? -1 : 1], ArrowUp: [-1, 0], ArrowDown: [1, 0] }[e.key]
        if (delta) { e.preventDefault(); csvFocus(r + delta[0], c + delta[1]) }
        if ((e.ctrlKey || e.metaKey) && ['z', 'y'].includes(e.key.toLowerCase())) { e.preventDefault(); cm.focus(); cm.contentDOM.dispatchEvent(new KeyboardEvent('keydown', { key: e.key, ctrlKey: e.ctrlKey, metaKey: e.metaKey, shiftKey: e.shiftKey, bubbles: true })); csvFocus(r, c) }
      }
      input.onpaste = e => {
        if (!csvEditable) return
        const text = e.clipboardData.getData('text/plain')
        if (!/[\t\n\r]/.test(text)) return
        e.preventDefault()
        const rows = text.replace(/\r\n/g, '\n').replace(/\n$/, '').split('\n').map(line => line.split('\t'))
        rows.forEach((row, dr) => row.forEach((v, dc) => csvPut(r + dr, c + dc, v)))
        csvSave(); csvWindow = ''; csvRender(); csvFocus(r, c)
      }
      td.append(input); tr.append(td)
    }
    table.append(tr)
  }
  space.append(table); csvGrid.append(space)
  if (pos) { const input = csvGrid.querySelector(`[data-row="${pos[0]}"][data-col="${pos[1]}"]`); if (input) { input.focus({ preventScroll: true }); input.setSelectionRange(pos[2], pos[3]) } }
}
function paintCsv() {
  const on = /\.(csv|tsv)$/i.test(tplName || tabName(activeFile)) && !!(docId || tplName)
  const identity = [docId, tplName, activeFile].join('/')
  if (identity !== csvIdentity) { csvIdentity = identity; csvRaw = false; csvSelection = [0, 0] }
  csvGrid.hidden = !on || csvRaw; $('cmWrap').hidden = on && !csvRaw
  if (!on) { csvSource = null; return }
  const source = getT(), editable = cm.state.facet(EditorView.editable)
  if (source === csvSource && csvEditable === editable) return
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
