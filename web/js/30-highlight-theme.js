// Var-driven token colors: one HighlightStyle for both modes (light/dark differ only
// via --tok-*). Prec.high beats the two highlighters baked into typstSupport
// (vendor Typst style + CM default), which were designed for light backgrounds.
// heading/strong/emphasis still fall back to the CM default; link/invalid are
// intentionally overridden here (CM default: underline-only link, #f00 invalid).
const typstTheme = HighlightStyle.define([
  { tag: tags.comment, color: 'var(--tok-comment)', fontStyle: 'italic' },
  { tag: tags.monospace, color: 'var(--tok-raw)' },
  { tag: [tags.keyword, tags.atom, tags.bool, tags.null], color: 'var(--tok-keyword)' },
  { tag: tags.number, color: 'var(--tok-number)' },
  { tag: tags.string, color: 'var(--tok-string)' },
  { tag: tags.function(tags.variableName), color: 'var(--tok-func)' },
  { tag: tags.propertyName, color: 'var(--tok-prop)' },
  { tag: tags.escape, color: 'var(--tok-math)' }, // covers Label/Ref nodes too (upstream maps them to escape)
  { tag: typstTags.mathDelimiter, color: 'var(--tok-math)' },
  { tag: typstTags.listMarker, color: 'var(--tok-marker)' },
  { tag: typstTags.interpolated, color: 'var(--tok-interp)' },
  { tag: tags.link, color: 'var(--tok-link)', textDecoration: 'underline' },
  { tag: tags.invalid, color: 'var(--tok-invalid)' },
])
const cm = new EditorView({
  parent: $('cm'),
  extensions: [keymap.of([ // first: highest priority before minimalSetup defaults
      { key: 'ArrowDown', run: v => { if (currentCompletions(v.state).length) return moveCompletionSelection(true)(v); return false } }, // creator call: (forward)(view), else cursor moves along
      { key: 'ArrowUp', run: v => { if (currentCompletions(v.state).length) return moveCompletionSelection(false)(v); return false } },
      { key: 'Escape', run: v => { if (currentCompletions(v.state).length) { closeCompletion(v); return true } return false } },
      { key: 'ArrowLeft', run: v => { if (currentCompletions(v.state).length) closeCompletion(v); return false } }, // box closes, cursor moves on
      { key: 'ArrowRight', run: v => { if (currentCompletions(v.state).length) closeCompletion(v); return false } },
      { key: 'Home', run: v => { if (currentCompletions(v.state).length) closeCompletion(v); return false } },
      { key: 'End', run: v => { if (currentCompletions(v.state).length) closeCompletion(v); return false } },
      { // Tab like IDE: snippet fields first, selection/line-start indents, open box accepts, else autocomplete
      key: 'Tab',
      run: v => {
        if (v.state.readOnly) return false // reviewer/comment mode: no accept, no indent, no completion
        if (nextSnippetField(v)) return true // F10: Tab walks snippet tabstops before anything else
        const m = v.state.selection.main
        if (!m.empty) return indentMore(v)
        if (currentCompletions(v.state).length) { acceptCompletion(v); return true }
        const line = v.state.doc.lineAt(m.head)
        if (/^\s*$/.test(line.text.slice(0, m.head - line.from))) return indentMore(v)
        return startCompletion(v)
      },
      shift: v => prevSnippetField(v) || indentLess(v), // F10: Shift-Tab walks snippet fields back, else dedent
    }, { key: 'Ctrl-Space', run: startCompletion }, ...foldKeymap]), // F10: fold shortcuts alongside completion keys
    minimalSetup, typstSupport, Prec.high(syntaxHighlighting(typstTheme)), typstSupport.language.data.of({ autocomplete: typstComplete }), EditorView.lineWrapping, tabComp.of([EditorState.tabSize.of(tabW), indentUnit.of(' '.repeat(tabW))]),
    autocompletion({ defaultKeymap: false }), closeBrackets(), bracketMatching(), hoverTooltip(hoverAll), // F10 bracket-match; vendor Typst source + project source (files/labels/bib); Enter stays newline, only Tab accepts; arrows navigate
    editableComp.of(EditorView.editable.of(true)), hlComp.of(hlField), peerField, findField, errLineField,
    linter(null, { tooltipFilter: () => [] }), // F1: compiler errors only (setDiagnostics below); null source: lint never overwrites them, positions map across edits; no lint tooltip (line hover shows the message, no aim needed), no gutter lane
    markField, lineNumbers(), foldGutter({ markerDOM: open => { const s = document.createElement('span'); s.className = 'foldMk ' + (open ? 'fold-open' : 'fold-closed'); s.title = open ? t('editor.fold') : t('editor.unfold'); s.innerHTML = open ? '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 6l4.5 4.5L12.5 6"/></svg>' : '<svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 3.5L10.5 8 6 12.5"/></svg>'; return s } }), // F10 fold lane right of numbers: hover-revealed chevrons, folded stays visible
    EditorView.theme({ '&': { height: '100%' }, '.cm-scroller': { overflow: 'auto' }, '.cm-content': { padding: '12px 0' } }),
    EditorView.updateListener.of(u => {
      if (u.docChanged && !applying) onEdit((p, end) => u.changes.mapPos(p, end ? 1 : -1), u.changes, u.startState.doc.length) // start left, end right: type before stays out, inside/after highlights
      if (u.docChanged) hideLinkTip() // typing under a pinned preview invalidates it
      if (u.docChanged && findOpen) markFind(false) // recount only: typing beside an open find must not yank the cursor back to a hit
      paintErr() // compile errors via lint: key stops loops, positions map across edits (no live lint)
      if (u.docChanged || u.selectionSet) { errTipHover = null; errTipHide(); requestAnimationFrame(() => { if (!errTipHover) errTipCursor() }) } // cursor on an error line: message stays without hovering; positioned after layout so the anchor tracks exactly
      if (u.selectionSet || u.docChanged || u.focusChanged) pushPresence()
      if (u.selectionSet) try { updCNewTip() } catch (e) {}
      if (u.selectionSet || u.docChanged) queueSyncPv() // cursor follows into preview (sync on)
      if (u.selectionSet || u.docChanged) try { updPos() } catch (e) {} // F24 status: Ln/Col/words follow cursor
    })]
})
const Transaction = cm.state.update({}).constructor // vendor bundle exports no Transaction: take the class from a throwaway transaction
const NO_HIST = [Transaction.addToHistory.of(false), Transaction.remote.of(true)] // remote/programmatic text: never in own undo stack
cm.scrollDOM.addEventListener('scroll', () => {
  if (popAnchor != null) movePop()
  errTipHide() // error tooltip is error-anchored: never stale after scroll
})
$('cm').addEventListener('mousemove', errTipMove) // full-line error tooltip: any spot on a red line, no aim needed
$('cm').addEventListener('mouseleave', errTipHide)
$('cm').addEventListener('mousedown', e => { // click on line number or yellow highlight opens card
  if (findOpen && findI >= 0) { findI = -1; paintFind(false) } // manual click drops the current hit: all blue, typing stays where clicked
  const g = e.target.closest('.cm-lineNumbers .cm-gutterElement')
  if (g && marks.has(+g.textContent)) { openPop(+g.textContent, false); return }
  const hl = e.target.closest('.cm-hl') // hover tooltip too fragile to click: use position directly
  if (hl) {
    const p = cm.posAtDOM(hl)
    const th = threads.find(t => t.a != null && p >= t.a && p <= t.b)
    if (th) openPop(th.anchor, false)
  }
})
const URL_RE = /https?:\/\/[^\s<>"')\]]+/g
function urlAt(doc, p) { // web link at doc pos: {url, from, to} or null
  const line = doc.lineAt(p)
  URL_RE.lastIndex = 0
  let m
  while ((m = URL_RE.exec(line.text))) {
    const url = m[0].replace(/[.,;:!?)\]]+$/, '')
    const from = line.from + m.index
    if (p >= from && p <= from + url.length) return { url, from, to: from + url.length }
  }
  return null
}
function pointLink(x, y) { // url under client coords, else null
  const p = cm.posAtCoords({ x, y })
  if (p == null) return null
  const hit = urlAt(cm.state.doc, p)
  return hit && hit.url
}
$('cm').addEventListener('click', e => { // Ctrl/Cmd+click on a web link opens it in a new tab
  if (!e.ctrlKey && !e.metaKey) return
  const url = pointLink(e.clientX, e.clientY)
  if (url) window.open(url, '_blank', 'noopener')
})
let linkMouse = null, linkTip = null, linkShown = null, linkTimer = 0 // cursor-anchored link preview
function hideLinkTip() { clearTimeout(linkTimer); linkTimer = 0; linkShown = null; if (linkTip) { linkTip.remove(); linkTip = null } }
function showLinkTip(url, x, y) {
  if (!linkTip) {
    linkTip = el('div', 'typ-hover')
    linkTip.style.position = 'fixed'; linkTip.style.zIndex = '500'; linkTip.style.pointerEvents = 'none'
    linkTip.style.background = 'var(--card)'; linkTip.style.border = '1px solid var(--line-2)'
    linkTip.style.borderRadius = 'var(--r-md)'; linkTip.style.boxShadow = 'var(--sh-pop)'
    linkTip.style.maxWidth = '240px'; linkTip.style.padding = '4px 9px'; linkTip.style.fontSize = '12px'
    linkTip.style.whiteSpace = 'nowrap'; linkTip.style.overflow = 'hidden'; linkTip.style.textOverflow = 'ellipsis'
    document.body.appendChild(linkTip)
  }
  linkTip.textContent = url.length > 60 ? url.slice(0, 60) + '…' : url
  const w = linkTip.offsetWidth || 240
  linkTip.style.left = Math.max(8, Math.min(x - w / 2, innerWidth - w - 8)) + 'px'
  linkTip.style.top = Math.max(8, y - (linkTip.offsetHeight || 32) - 10) + 'px'
}
function linkHoverMove(e) { // preview after short delay, pinned above cursor until the link range is left
  if (e.ctrlKey || e.metaKey) { hideLinkTip(); return }
  const p = cm.posAtCoords({ x: e.clientX, y: e.clientY })
  const hit = p == null ? null : urlAt(cm.state.doc, p)
  if (!hit) { hideLinkTip(); return }
  if (linkShown && p >= linkShown.from && p <= linkShown.to) return
  hideLinkTip()
  const x = e.clientX, y = e.clientY
  linkTimer = setTimeout(() => { linkTimer = 0; linkShown = { from: hit.from, to: hit.to }; showLinkTip(hit.url, x, y) }, 400)
}
function linkCursor(e) { // finger cursor only over links while ctrl/cmd is held
  cm.contentDOM.style.cursor = (pointLink(e.clientX, e.clientY) && (e.ctrlKey || e.metaKey)) ? 'pointer' : ''
}
$('cm').addEventListener('mousemove', e => { linkMouse = { x: e.clientX, y: e.clientY }; linkHoverMove(e); linkCursor(e) })
$('cm').addEventListener('mouseleave', () => { linkMouse = null; hideLinkTip(); cm.contentDOM.style.cursor = '' })
$('cm').addEventListener('mousedown', () => { hideLinkTip(); cm.contentDOM.style.cursor = '' })
cm.scrollDOM.addEventListener('scroll', () => { linkMouse = null; hideLinkTip(); cm.contentDOM.style.cursor = '' })
addEventListener('keydown', e => { // ctrl pressed: hide preview, finger without moving the mouse
  if ((e.key === 'Control' || e.key === 'Meta') && linkMouse) { hideLinkTip(); linkCursor({ clientX: linkMouse.x, clientY: linkMouse.y, ctrlKey: e.key === 'Control', metaKey: e.key === 'Meta' }) }
})
addEventListener('keyup', e => { if (e.key === 'Control' || e.key === 'Meta') cm.contentDOM.style.cursor = '' })
addEventListener('blur', () => { hideLinkTip(); cm.contentDOM.style.cursor = '' })
const getT = () => cm.state.doc.toString()
const setT = v => { applying = true; try { cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: v }, annotations: NO_HIST }) } finally { applying = false } } // doc/tab switch: Ctrl+Z must not bring back the previous doc
function onEdit(mapPos, changes, oldLen) {
  gutter()
  if (tplName) { queueTplSave(); return } // template: save directly, no sync/render
  if (docRole === 'reviewer' || !ytext) return
  paintOutline()
  if (activeFile) { queueFileSave(); return } // file tab: only file + preview, no Yjs
  pushLocal(); queueRender(); queueSave()
  if (mapPos) mapThreads(mapPos)
  reanchor()
  if (threads.length) refreshHl()
}
let anchorT = 0
const anchorDirty = new Map()
function dirtyAnchor(th) { // batch anchor saves: typing makes one request, not many
  anchorDirty.set(th.id, { doc: docId, anchor: th.anchor })
  clearTimeout(anchorT)
  anchorT = setTimeout(() => {
    for (const [id, s] of anchorDirty) {
      const t = threads.find(x => x.id === id)
      if (t && s.doc) api('POST', `/api/docs/${s.doc}/comments/${t.id}/anchor`, { anchor: s.anchor }).catch(e => console.warn('anchor save failed', e))
    }
    anchorDirty.clear()
  }, SAVE_MS)
}
function mapThreads(mapPos, paint = true) { // start left, end right: typing before stays out, inside/after grows
  const t = activeFile ? shadow : getT() // file tab: anchors live in main, not in file text (Fix #5)
  for (const th of threads) {
    if (th.a == null || th.b == null) continue
    const a = Math.max(0, Math.min(t.length, mapPos(th.a, false)))
    const b = Math.max(0, Math.min(t.length, mapPos(th.b, true)))
    th.a = Math.min(a, b); th.b = Math.max(a, b)
    const line = t.slice(0, th.a).split('\n').length
    if (line !== th.anchor) { th.anchor = line; dirtyAnchor(th) }
  }
  if (!paint) return
  gutter(); refreshHl()
  if (popAnchor != null) movePop()
}
function initRanges() { // ranges from quote (once; then mapping keeps them alive)
  const t = getT()
  if (!t) return
  for (const th of threads) {
    if (th.a != null) continue
    const i = th.quote ? locateQuote(t, th.quote, th.anchor) : -1
    if (i >= 0) { th.a = i; th.b = Math.min(t.length, i + th.quote.length) }
    else { th.a = posOfLine(t, th.anchor); th.b = th.a + t.slice(th.a).split('\n')[0].length }
  }
}

