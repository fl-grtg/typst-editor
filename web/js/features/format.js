// --- Document formatter: typstyle WASM (self-hosted, lazy) + optional format on save ---
const TYPSTYLE_WASM_URL = '@@typstyle-wasm@@'
const TYPSTYLE_GLUE_URL = '@@typstyle-glue@@'
let fmtLoading = null
async function fmtLoad() { // glue as ESM (no imports of its own), wasm instantiated by hand (bundler target needs no bundler this way)
  if (!fmtLoading) fmtLoading = (async () => {
    const bg = await import(TYPSTYLE_GLUE_URL)
    const res = await fetch(TYPSTYLE_WASM_URL)
    if (!res.ok) throw new Error('HTTP ' + res.status)
    const { instance } = await WebAssembly.instantiate(await res.arrayBuffer(), { './typstyle_wasm_bg.js': bg })
    bg.__wbg_set_wasm(instance.exports)
    return bg
  })().catch(e => { fmtLoading = null; throw e })
  return fmtLoading
}
const fmtEditable = () => docId && !activeFile && cm.state.facet(EditorView.editable)
async function formatDoc(quiet) { // whole doc, one undo step; never throws (save path must survive a dead formatter)
  if (!fmtEditable()) return false
  const cur = getT()
  if (!cur.trim()) return false // blank stays blank (typstyle would add a newline)
  let bg
  try { bg = await fmtLoad() } catch (e) { if (!quiet) toast(t('editor.formatFail', { msg: e.message })); return false }
  let out
  try { out = bg.format(cur, {}) } catch (e) { if (!quiet) toast(t('editor.formatFail', { msg: e.message })); return false }
  if (out === cur) { if (!quiet) toast(t('editor.formatClean')); return true }
  const m = diffMap(cur, out), sel = cm.state.selection.main // cursor follows its text (same mapper as remote sync)
  cm.dispatch({ changes: { from: 0, to: cur.length, insert: out }, userEvent: 'input',
    selection: { anchor: Math.min(m(sel.anchor, false), out.length), head: Math.min(m(sel.head, true), out.length) } })
  cm.focus()
  if (!quiet) toast(t('editor.formatDone'))
  return true
}
const fmtSaveOn = () => { try { return localStorage.getItem('typst_fmt_save') === '1' } catch (e) { return false } }
function formatSettingsSec() { // settings group section: format on save (toolbar keeps the once-button only)
  const sec = document.createElement('div'); sec.className = 'sec'
  const row = document.createElement('div'); row.className = 'row'
  const cb = document.createElement('input'); cb.type = 'checkbox'; cb.id = 'fmtSave'
  cb.checked = fmtSaveOn()
  cb.setAttribute('aria-label', t('editor.formatSave')); cb.title = t('editor.formatSaveT')
  cb.onchange = () => { try { localStorage.setItem('typst_fmt_save', cb.checked ? '1' : '0') } catch (e) {} }
  const lab = document.createElement('label'); lab.textContent = t('editor.formatSave'); lab.setAttribute('for', 'fmtSave')
  lab.title = t('editor.formatSaveT')
  cb.style.marginLeft = 'auto' // text left, box right
  row.append(lab, cb)
  sec.appendChild(row)
  return sec
}
{
  const tools = $('tools'), tsp = tools.querySelector('.tsp')
  const grp = document.createElement('span')
  grp.className = 'fmt'; grp.setAttribute('role', 'group'); grp.setAttribute('aria-label', t('editor.formatDoc'))
  const fb = document.createElement('button')
  fb.id = 'fmtDoc'
  fb.setAttribute('aria-label', t('editor.formatDoc')); fb.title = t('editor.formatDocT')
  fb.innerHTML = '<svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" aria-hidden="true"><path d="M2.5 4h11M5.5 8h8M2.5 12h11"/></svg>'
  fb.onclick = () => formatDoc(false)
  grp.append(fb)
  tools.insertBefore(grp, tsp)
  const sync = () => { const on = cm.contentDOM.getAttribute('contenteditable') === 'true'; fb.disabled = !on }
  new MutationObserver(sync).observe(cm.contentDOM, { attributes: true, attributeFilter: ['contenteditable'] })
  sync()
}
addEventListener('keydown', e => { // Alt+Shift+F like VS Code: format once (save toggle above covers every save)
  if (!e.altKey || !e.shiftKey || e.ctrlKey || e.metaKey) return
  if (e.code !== 'KeyF' && (e.key || '').toLowerCase() !== 'f') return
  if (/INPUT|TEXTAREA|SELECT/.test((e.target || {}).tagName || '')) return
  if (!$('app').classList.contains('on')) return
  e.preventDefault()
  formatDoc(false)
})
{
  const inner = saveNow // format on save: format first, then the regular save (failure still saves unformatted)
  saveNow = async (force, auto) => {
    if (fmtSaveOn() && docId && !tplName && !activeFile && docRole !== 'reviewer' && !openedTrashed) {
      try { await formatDoc(true) } catch (e) {}
    }
    return inner(force, auto) // forward 2E quiet flag: autosave errors stay toast-free
  }
}
