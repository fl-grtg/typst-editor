// Personal templates: global per account (API), all kinds in one list (.typ/.bib/.csv/...)
// myTpl = OWN shelf (editable). The open document compiles against its project files instead (see loadProjectFiles).
let myTpl = [], tplFolders = []
let docProject = '', docResReadonly = true
let tplLoadN = 0, tplLoadP = null
async function loadTpl() { // list only: never touches editor text (SSE-safe, dirty editors survive)
  const n = ++tplLoadN, who = user
  let p = tplLoadP = (async () => {
    try {
      const [r, f] = await Promise.all([api('GET', '/api/templates'), api('GET', '/api/tplfolders')])
      if (n !== tplLoadN || who !== user) return
      myTpl = r.templates; tplFolders = f.folders
    } catch (e) { return } // offline/error: keep the known shelf
    paintTpls()
    if (docId) queueRender()
  })()
  await p
  while (p !== tplLoadP) { p = tplLoadP; await p } // superseded: wait for the list that really lands (callers open against it)
}
const fileRefs = () => lastFiles.map(f => refTo(f.path)) // completion labels: as the open text would quote them
const RES_EXT = { template: '.typ', library: '.bib', table: '.csv', resource: '.typ', data: '.json' }
const resLabel = kind => kind === 'library' ? t('templates.kindlibrary') : kind === 'table' ? t('templates.kindtable') : t('templates.kindModule')
const resKind = t => (t && t.kind) || (((t || {}).name || '').toLowerCase().endsWith('.bib') ? 'library' : ((t || {}).name || '').toLowerCase().endsWith('.csv') ? 'table' : 'template')
const resOf = kind => (kind === 'resource' ? myTpl : myTpl.filter(t => resKind(t) === kind)).slice().sort((a, b) => a.name.localeCompare(b.name))
// Project-only completions (vendor typst_lezer handles the Typst language itself:
// builtins, params, let-scope, document labels). Returns null everywhere else so
// the vendor source answers alone. Triggers: file paths in "..." strings,
// #ref(<label>, #cite(<key>, @bib key, Ctrl-Space/Tab file fallback.
// Typst control keywords (stable language, not in vendor function data)
const T_KW = 'set show let import include context if else for while return break continue in and or not as'.split(' ')
// F10 snippets: Typst blocks with tabstops (additive to vendor completions)
const T_SNIP = [
  ['#fig', '#figure(caption: [${cap}])[${body}]'],
  ['#tbl', '#table(columns: (${cols}))[${body}]'],
  ['#img', '#image("${file}", width: ${w}%)'],
  ['#math', '$${x}$'],
  ['#head', '= ${title}'],
  ['#code', '```${lang}\n${body}\n```'],
].map(([label, template]) => snippetCompletion(template, { label, type: 'snippet', boost: 45 }))
// Functions insert with parens (cursor inside): vendor options carry no apply,
// but unique() keeps object refs, so enhancing the shared arrays affects the vendor source (no wrapper, no dupes)
const parenApply = (view, completion, from, to) => {
  const ins = completion.label, next = view.state.sliceDoc(to, to + 1)
  if (next === '(' || next === '[' || next === '{') { // already a call/content: keep the name only
    view.dispatch({ changes: { from, to, insert: ins }, selection: { anchor: from + ins.length }, userEvent: 'input.complete' })
    return
  }
  view.dispatch({ changes: { from, to, insert: ins + '()' }, selection: { anchor: from + ins.length + 1 }, userEvent: 'input.complete' })
}
for (const arr of [typstGlobalCompletions, typstMathCompletions])
  if (arr) for (const c of arr) if (c && c.type === 'function' && !c.apply) { c.apply = parenApply; delete c.commitCharacters } // no (-commit: apply already adds (); typed ( pairs via closeBrackets
const T_BLOCKED = new Set(['Shebang', 'LineComment', 'BlockComment', 'Raw', 'Str', 'Link', 'Label', 'Ref', 'Error']) // mirror of vendor blockedNodes + Error
let pcDoc = null, pcTree = null // memoized parse for the #word branches (doc objects are persistent: same ref = same tree)
function typstComplete(ctx) {
  if (window.__booted && !/\.typ$/i.test(tplName || tabName(activeFile))) return null
  const pos = ctx.pos
  const before = ctx.state.doc.sliceString(Math.max(0, pos - 256), pos)
  const fuzzy = (q, s) => s.toLowerCase().includes(q) // substring, not prefix-only
  const imp = before.match(/(import|include|image|bibliography|read|csv|json|yaml|toml|xml)\s*[( ]"([^"]*)$/)
  if (imp) { // after import/include/#image(": global templates + manager files
    const q = imp[2].toLowerCase()
    const files = fileRefs().filter(n => fuzzy(q, n))
    return files.length ? { from: pos - imp[2].length, filter: false, options: files.slice(0, 50).map(n => ({ label: n, type: 'file' })) } : null
  }
  const rf = before.match(/#ref\s*\((<?)([^)>]*)$/)
  if (rf) { // after #ref(: labels from doc (vendor covers @label, not the #ref( form)
    const q = rf[2].toLowerCase(), out = [], seenL = new Set()
    for (const m of getT().matchAll(/<([^<>\s]+)>/g)) // labels use colons (<sec:intro>)
      if (!seenL.has(m[1]) && fuzzy(q, m[1])) {
        seenL.add(m[1])
        const ins = '<' + m[1] + '>'
        out.push({ label: ins, type: 'label', apply: (view, completion, from, to) => { // consume existing `>` instead of duplicating it
          const end = view.state.sliceDoc(to, to + 1) === '>' ? to + 1 : to
          view.dispatch({ changes: { from, to: end, insert: ins }, selection: { anchor: from + ins.length }, userEvent: 'input.complete' })
        } })
      }
    return out.length ? { from: pos - rf[2].length - rf[1].length, filter: false, options: out.slice(0, 50) } : null
  }
  const ct = before.match(/#cite\w*\(\s*<([^>\s]*)$/) // #cite(<: keys from all .bib (see shadowAll; vendor has no .bib view)
  if (ct) {
    if (!bibKeys.length) return null
    const q = ct[1].toLowerCase()
    const out = bibKeys.filter(k => fuzzy(q, k)).map(k => ({ label: k, type: 'variable', apply: (view, completion, from, to) => { // close the label, consume an existing `>`
      const end = view.state.sliceDoc(to, to + 1) === '>' ? to + 1 : to
      view.dispatch({ changes: { from, to: end, insert: k + '>' }, selection: { anchor: from + k.length + 1 }, userEvent: 'input.complete' })
    } }))
    return out.length ? { from: pos - ct[1].length, filter: false, options: out.slice(0, 50) } : null
  }
  const fc = matchFontContext(ctx.state.doc.sliceString(Math.max(0, pos - 512), pos), pos)
  const sr = (() => { // innermost unclosed `#set FUNC(` (nesting-aware; parens in strings ignored)
    const re = /#set\s+([\w.]+)\s*\(/g
    let m, last = null
    while ((m = re.exec(before))) last = m
    if (!last) return null
    const args = before.slice(last.index + last[0].length)
    const pairs = { ')': '(', ']': '[', '}': '{' }, stack = []
    for (const ch of args.replace(/"(\\.|[^"\\\n])*"?/g, '')) { // strings (escapes aware) don't count
      if (ch === '(' || ch === '[' || ch === '{') stack.push(ch)
      else if (pairs[ch]) {
        if (!stack.length) return null // call already closed
        if (stack[stack.length - 1] === pairs[ch]) stack.pop() // matched; stray closers in content ignored
      }
    }
    return { name: last[1], args } // depth >= 0: still inside (nested or not)
  })()
  const at = before.match(/@([\p{ID_Continue}_:.-]*)$/u) // @: keys from all .bib (vendor's label list is document-only)
  const kwm = before.match(/#([\p{ID_Continue}_-]*)$/u)
  let blocked = null // ancestor blocking completion (mirror of vendor blockedNodes + Error); one parse shared by the #word branches
  if ((fc || at || sr || kwm) && typeof typstParser !== 'undefined') {
    try {
      const doc = ctx.state.doc
      if (doc.length <= 100000) { // huge docs: skip check (vendor turf, no fallback) instead of frame drops
        if (pcDoc !== doc) { pcDoc = doc; pcTree = typstParser.parse(doc.toString()) }
        let n = pcTree && pcTree.resolveInner(Math.min(pos, doc.length), -1)
        for (; n; n = n.parent) if (T_BLOCKED.has(n.name)) { blocked = n.name; break }
      } else blocked = 'SizeCap' // same silence as comment/string: no keywords, no fallback in huge docs
    } catch (e) { pcDoc = null; pcTree = null }
  }
  if (blocked === 'LineComment' || blocked === 'BlockComment') return null // comments: full silence (file/label/cite ran before; keywords/params stay silent like vendor)
  if (fc && blocked !== 'Raw') {
    const fonts = availableFonts()
    if (fonts.length) {
      const q = fc.query.toLowerCase()
      const srcDetail = s => s === 'project' ? t('editor.fontProject') : s === 'server' ? t('editor.fontServer') : t('editor.fontBuiltin')
      const srcBoost = s => s === 'project' ? 2 : s === 'server' ? 1 : 0
      const out = []
      for (const f of fonts) {
        if (fc.used.has(f.family.toLowerCase())) continue
        if (q && !fuzzy(q, f.family)) continue
        const quotedVal = typstStr(f.family)
        const pre = q && f.family.toLowerCase().startsWith(q) ? 10 : 0
        out.push({
          label: f.family,
          type: 'enum',
          detail: srcDetail(f.source),
          boost: 55 + pre + srcBoost(f.source),
          apply: (view, completion, from, to) => { // auto-quote with straight quotes (Typst strings) and consume an existing closing quote
            const end = /["“”]/.test(view.state.sliceDoc(to, to + 1)) ? to + 1 : to
            view.dispatch({ changes: { from, to: end, insert: quotedVal }, selection: { anchor: from + quotedVal.length }, userEvent: 'input.complete' })
          },
        })
      }
      if (out.length) {
        out.sort((a, b) => (b.boost - a.boost) || a.label.localeCompare(b.label))
        return { from: fc.from, filter: false, options: out.slice(0, 80) }
      }
    }
  }
  if (at && (!blocked || blocked === 'Ref') && bibKeys.length) { // refs and citations share .bib keys; vendor adds the document's <labels>
    const q = at[1].toLowerCase()
    const out = bibKeys.filter(k => fuzzy(q, k)).map(k => ({ label: k, type: 'variable' }))
    if (out.length) return { from: pos - at[1].length, filter: false, options: out.slice(0, 50) }
  }
  if (sr && typeof typstBuiltinSignatures !== 'undefined') { // set-rule gaps: vendor hides non-settable flags (paper, gutter, radius...) although valid
    const sig = typstBuiltinSignatures[sr.name]
    if (Array.isArray(sig)) {
      let flat = sr.args.replace(/"(\\.|[^"\\\n])*"?/g, '""') // strings blanked: commas/colons inside don't split
      const grpRe = /\([^()]*\)|\[[^\[\]]*\]|\{[^{}]*\}/g
      for (let k = 0; k < 6; k++) { const nx = flat.replace(grpRe, ''); if (nx === flat) break; flat = nx } // nested groups stripped for analysis (positions stay original)
      const cur = flat.split(',').pop()
      const trail = (sr.args.match(/("[^"\n]*|[\p{ID_Continue}_:.-]*)$/u) || [])[1] || '' // full partial incl. `:` (vendor-token level): `a:b` matches nothing instead of corrupting via truncated `b`
      const vmName = (cur.match(/([\p{ID_Start}_][\p{ID_Continue}_-]*)\s*:[^:]*$/u) || [])[1]
      const pm = vmName && sig.find(p => p[0] === vmName && (p[1] & 16) === 0 && Array.isArray(p[2])) // gap params only: settable values come from the vendor (no dupes)
      if (pm) { // value after `name:`: paper sizes etc. (vendor shows nothing here for gap params)
        const quoted = trail.charCodeAt(0) === 34, q = (quoted ? trail.slice(1) : trail).toLowerCase(), out = []
        const quoteApply = v => (view, completion, from, to) => { // consume existing closing `"` instead of duplicating it
          const end = view.state.sliceDoc(to, to + 1) === '"' && v.endsWith('"') ? to + 1 : to
          view.dispatch({ changes: { from, to: end, insert: v }, selection: { anchor: from + v.length }, userEvent: 'input.complete' })
        }
        for (const part of pm[2]) {
          if (part.startsWith('value:')) { const v = part.slice(6); if (v.toLowerCase().includes(q)) out.push({ label: quoted ? v : v.replace(/^"([\s\S]*)"$/, '$1'), apply: quoteApply(v), type: 'enum', detail: t('editor.acceptedValue'), boost: 55 }) }
          else if (part === 'type:bool' || part === 'bool') { for (const b of ['true', 'false']) if (b.includes(q)) out.push({ label: b, type: 'constant', detail: t('editor.boolValue'), boost: 55 }) }
          else if (part === 'type:auto' || part === 'auto' || part === 'type:none' || part === 'none') { const v = part.includes('none') ? 'none' : 'auto'; if (v.includes(q)) out.push({ label: v, type: 'constant', detail: t('editor.typstValue', { v }), boost: 55 }) }
        }
        if (out.length) {
          const qn = q
          out.sort((a, b) => (b.label.replace(/^"/, '').toLowerCase().startsWith(qn) ? 1 : 0) - (a.label.replace(/^"/, '').toLowerCase().startsWith(qn) ? 1 : 0))
          return { from: pos - trail.length, filter: false, options: out.slice(0, 50) }
        }
      } else if (!cur.includes(':')) { // param name (no colon yet): only params vendor hides
        const used = new Set([...flat.matchAll(/([\p{ID_Start}_][\p{ID_Continue}_-]*)\s*:/gu)].map(m => m[1]))
        const wm = sr.args.match(/([\p{ID_Continue}_-]*)$/u), pre = (wm ? wm[1] : '').toLowerCase()
        const gap = sig.filter(p => p[0] !== 'body' && (p[1] & 2) && !(p[1] & 16) && !used.has(p[0]) && p[0].toLowerCase().includes(pre))
        if (gap.length) {
          return { from: pos - (wm ? wm[1].length : 0), filter: false, options: gap.slice(0, 20).map(p => {
            const accepts = (Array.isArray(p[2]) ? p[2] : []).map(s => s.replace(/^(?:type|value):/, '')).join(' | ')
            return { label: p[0], apply: p[0] + ': ', type: 'property', detail: accepts ? t('editor.paramWith', { accepts }) : t('editor.param'), boost: 50 }
          }) }
        }
      }
    }
  }
  if (kwm && (!blocked || blocked === 'Error')) { // keywords + snippets share one range incl. # (templates carry # or are markup)
    const q = kwm[1].toLowerCase()
    const out = T_KW.filter(k => k.includes(q)).map(k => ({ label: '#' + k, apply: '#' + k, type: 'keyword', boost: 60 }))
    for (const s of T_SNIP) if (s.label.toLowerCase().includes('#' + q) || s.label.toLowerCase().includes(q)) out.push(s) // F10 snippets alongside keywords
    if (out.length) return { from: pos - kwm[1].length - 1, filter: false, options: out.slice(0, 50) }
  }
  if (kwm && blocked === 'Error' && typeof typstGlobalCompletions !== 'undefined') {
    // broken syntax (##, unclosed forms): vendor is tree-based and silent -> text fallback from vendor data
    const q = kwm[1].toLowerCase(), out = []
    for (const c of typstGlobalCompletions) { if (out.length >= 50) break; if (c.label.toLowerCase().includes(q)) out.push(c) }
    if (out.length) return { from: pos - kwm[1].length, filter: false, options: out }
  }
  if (ctx.explicit) { // Ctrl-Space/Tab without context: files/templates only, no language noise
    if (imp || rf || ct || fc || sr) return null // context recognized but empty (no labels/keys/params): no file noise
    const w = ctx.matchBefore(/[\p{ID_Continue}.\-/]*$/u)
    const pre = (w ? w.text : '').toLowerCase()
    const files = fileRefs().filter(n => fuzzy(pre, n))
    return files.length ? { from: w ? w.from : pos, filter: false, options: files.slice(0, 50).map(n => ({ label: n, type: 'file' })) } : null
  }
  return null
}
function matchFontContext(before, pos) { // innermost unclosed text(... font: <str | tuple | (name: str)>)
  const matches = [...before.matchAll(/(?<![\p{ID_Continue}_-])text\s*\(/gu)]
  if (!matches.length) return null
  const splitTop = str => {
    const parts = []
    let start = 0, inStr = false, esc = false
    const stack = []
    const pairs = { ')': '(', ']': '[', '}': '{' }
    for (let i = 0; i < str.length; i++) {
      const ch = str[i]
      if (inStr) {
        if (esc) { esc = false; continue }
        if (ch === '\\') { esc = true; continue }
        if (ch === '"') inStr = false
        continue
      }
      if (ch === '"') { inStr = true; continue }
      if (ch === '(' || ch === '[' || ch === '{') { stack.push(ch); continue }
      if (pairs[ch]) {
        if (!stack.length) return null // enclosing parens already closed
        if (stack[stack.length - 1] === pairs[ch]) stack.pop()
        continue
      }
      if (ch === ',' && !stack.length) { parts.push(str.slice(start, i)); start = i + 1 }
    }
    parts.push(str.slice(start))
    return parts
  }
  const parseTail = s => {
    const qm = s.match(/^\s*(["„“”]([^"„“”\n\\]*))$/) // German/typographic quotes (keyboard autocorrect) count as the opening quote
    if (qm) return { trail: qm[1], query: qm[2] }
    const bm = s.match(/^\s*([\p{ID_Continue}_-]*)$/u)
    return bm ? { trail: bm[1], query: bm[1] } : null
  }
  let topArgs = null
  for (let i = matches.length - 1; i >= 0; i--) {
    const m = matches[i]
    const parts = splitTop(before.slice(m.index + m[0].length))
    if (parts) { topArgs = parts; break }
  }
  if (!topArgs) return null
  const curArg = topArgs[topArgs.length - 1]
  const fm = curArg.match(/^\s*font\s*:\s*([\s\S]*)$/)
  if (!fm) return null
  const val = fm[1], used = new Set()
  const done = s => { const tail = s == null ? null : parseTail(s); return tail ? { from: pos - tail.trail.length, query: tail.query, used } : null }
  const dictName = part => part.match(/^\s*name\s*:\s*([\s\S]*)$/)?.[1]
  if (!val.startsWith('(')) return done(val)
  const inner = splitTop(val.slice(1))
  if (!inner) return null // tuple already closed
  for (let i = 0; i < inner.length - 1; i++) {
    const s = inner[i].trim()
    const sm = s.match(/^["„“”]([^"„“”\n\\]+)["“”]$/) || s.match(/^\(\s*name\s*:\s*["„“”]([^"„“”\n\\]+)["“”]/)
    if (sm) used.add(sm[1].toLowerCase())
  }
  const last = inner[inner.length - 1], trimmed = last.trimStart()
  if (trimmed.startsWith('(')) { // nested dict in fallback array: font: ((name: "A"), (name: "B
    const dictParts = splitTop(trimmed.slice(1))
    return dictParts ? done(dictName(dictParts[dictParts.length - 1])) : null
  }
  if (splitTop(last) && /^[^"]*:/s.test(last)) return done(dictName(last)) // direct dict form: font: (name: "A", covers: ...)
  return done(last)
}
function typstHover(view, pos) {
  if (urlAt(view.state.doc, pos)) return null // words inside web links: the link preview owns the hover
  const w = view.state.wordAt(pos)
  if (!w) return null
  const d = T_DOC[view.state.doc.sliceString(w.from, w.to)]
  if (!d) return null
  return { pos: w.from, end: w.to, above: false, create: () => {
    const div = document.createElement('div'); div.className = 'typ-hover'; div.textContent = d; return { dom: div } } }
}
function docNear(view, pos, a, b) { // command docs for nearest word (also at brackets/spaces)
  for (let o = 0; o <= 8; o++) {
    for (const p of o ? [pos - o, pos + o] : [pos]) {
      if (p < a || p > b) continue
      const w = view.state.wordAt(p)
      if (w) { const d = T_DOC[view.state.doc.sliceString(w.from, w.to)]; if (d) return d }
    }
  }
  return null
}
function commentHover(view, pos) { // full comment view + command docs below, click opens card
  const list = threads.filter(th => {
    if (th.a == null || th.b == null) return false
    const r = threadEditorRange(th)
    return r.to > r.from && pos >= r.from && pos <= r.to
  })
  if (!list.length) return null
  const rs = list.map(threadEditorRange)
  const a = Math.min(...rs.map(r => r.from)), b = Math.max(...rs.map(r => r.to))
  return { pos: a, end: b, above: true, create: () => {
    const div = document.createElement('div'); div.className = 'typ-hover full'
    for (const th of list.slice(0, 3)) {
      const h = document.createElement('div'); h.style.marginBottom = '6px'
      const nm = document.createElement('b'); nm.textContent = th.author || th.username; nm.style.color = colOf(th.username)
      h.appendChild(nm); h.appendChild(document.createTextNode(' · ' + ago(th.created_at)))
      if (th.suggestion_status === 'pending') {
        const span = diffSpan(th.suggestion_old, th.replacement)
        const old = th.suggestion_old.slice(span.a, th.suggestion_old.length - span.b)
        const next = th.replacement.slice(span.a, th.replacement.length - span.b)
        const d = document.createElement('div'); d.className = 'hvSug'
        if (old) { const s = document.createElement('span'); s.className = 'suggestionDeleted'; s.textContent = old.slice(0, 60); d.appendChild(s) }
        if (old && next) d.appendChild(document.createTextNode(' → '))
        if (next) { const s = document.createElement('span'); s.className = 'hvAdd'; s.textContent = next.slice(0, 60); d.appendChild(s) }
        h.appendChild(d)
      }
      if (th.text) { const p = document.createElement('div'); p.textContent = th.text; h.appendChild(p) }
      if (th.replies && th.replies.length) {
        const r = document.createElement('div'); r.style.color = 'var(--sub)'; r.style.fontSize = '12px'
        r.textContent = th.replies.length === 1 ? t('comments.repliesOne', { n: th.replies.length }) : t('comments.repliesMany', { n: th.replies.length }); h.appendChild(r)
      }
      div.appendChild(h)
    }
    if (list.length > 3) {
      const m = document.createElement('div'); m.style.color = 'var(--sub)'; m.style.fontSize = '12px'
      m.textContent = t('comments.moreHover', { n: list.length - 3 }); div.appendChild(m)
    }
    const d = docNear(view, pos, a, b)
    if (d) {
      const s = document.createElement('div')
      s.style.borderTop = '1px solid var(--line)'; s.style.marginTop = '6px'; s.style.paddingTop = '6px'; s.style.color = 'var(--sub)'
      s.textContent = d; div.appendChild(s)
    }
    div.style.cursor = 'pointer'; div.onclick = () => openPop(view.state.doc.lineAt(a).number, false)
    return { dom: div } } }
}
let errTipEl = null // full-line error tooltip: manual div (no aim needed, works on empty line area too)
let errTipHover = null // message under the mouse, or null
function errTipHide() { if (errTipEl) { errTipEl.remove(); errTipEl = null } }
function errTipPlace(msg, x, yBottom) {
  if ($('cmWrap').hidden || !cm.hasFocus || $('pop').style.display !== 'none') { errTipHide(); return }
  if (!errTipEl) {
    errTipEl = document.createElement('div')
    errTipEl.className = 'typ-hover err'
    errTipEl.style.cssText = 'position:fixed;z-index:90;pointer-events:none;max-width:320px;background:var(--card);border:1px solid var(--line-2);border-left:3px solid var(--danger);border-radius:12px;box-shadow:var(--sh-pop)'
    document.body.appendChild(errTipEl)
  }
  if (errTipEl.textContent !== msg) errTipEl.textContent = msg
  errTipEl.style.left = Math.max(8, Math.min(x, innerWidth - 330)) + 'px'
  const top = document.querySelector('header').getBoundingClientRect().bottom + 8
  errTipEl.style.top = Math.max(top, Math.min(yBottom + 6, innerHeight - errTipEl.offsetHeight - 8)) + 'px'
}
function errTipAnchor(lineEl) { // precise error spot on a red line: lint mark/widget first (carrier opens first in DOM order), carrier as fallback
  if (!lineEl) return null
  return lineEl.querySelector('.cm-lintRange-error, .cm-lintPoint-error') || lineEl.querySelector('.cm-errMark') || null
}
function errTipCursor() {
  if ($('cmWrap').hidden || !cm.hasFocus || $('pop').style.display !== 'none') { errTipHide(); return false } // cursor sits on an error line: keep the message visible without hovering
  let ln = null
  try { ln = cm.state.doc.lineAt(cm.state.selection.main.head).number } catch (_) {}
  if (ln == null) return false
  let carrier = null
  try {
    document.querySelectorAll('#cmWrap .cm-errMark').forEach(m => {
      if (!carrier && m.dataset.line != null && +m.dataset.line === ln) carrier = m
    })
  } catch (_) {}
  if (!carrier) return false
  const a = errTipAnchor(carrier.closest('.cm-errLine'))
  if (!a) return false
  const r = a.getBoundingClientRect()
  errTipPlace(carrier.dataset.err, r.left, r.bottom)
  return true
}
function errTipMove(ev) { // any spot on a red line shows the message anchored at the error; tooltip itself never eats clicks
  const t = ev.target && ev.target.closest ? ev.target.closest('.cm-errLine') : null
  const m = t && t.querySelector('.cm-errMark')
  errTipHover = (m && m.dataset.err) || null
  if (!errTipHover) { if (!errTipCursor()) errTipHide(); return }
  const a = errTipAnchor(t) || m
  const r = a.getBoundingClientRect() // anchored at the error, not at the mouse: trigger anywhere, tip stays put
  errTipPlace(errTipHover, r.left, r.bottom)
}
const hoverAll = (v, p) => $('pop').style.display !== 'none' ? null : commentHover(v, p) || typstHover(v, p) // an open card owns the view: no hover preview next to it (errors use the manual full-line tooltip errTipMove, not CM hover)
const editableComp = new Compartment(), hlComp = new Compartment()
const tabComp = new Compartment() // F25: tab width (settings, persisted)
const setHl = StateEffect.define() // mark comment ranges, follow edits via mapping
const hlField = StateField.define({
  create: () => Decoration.none,
  update: (v, tr) => { for (const e of tr.effects) if (e.is(setHl)) v = e.value; return v.map(tr.changes) },
  provide: f => EditorView.decorations.from(f),
})
const setFind = StateEffect.define() // search hits, follow edits via mapping
const findField = StateField.define({
  create: () => Decoration.none,
  update: (v, tr) => { for (const e of tr.effects) if (e.is(setFind)) v = e.value; return v.map(tr.changes) },
  provide: f => EditorView.decorations.from(f),
})
const setErrLine = StateEffect.define() // error lines: full-line red tint (old look), follows edits via mapping
const errLineField = StateField.define({
  create: () => Decoration.none,
  update: (v, tr) => { for (const e of tr.effects) if (e.is(setErrLine)) v = e.value; return v.map(tr.changes) },
  provide: f => EditorView.decorations.from(f),
})
const setSyncLine = StateEffect.define() // preview -> editor jump: brief highlight of the target line
const syncLineField = StateField.define({
  create: () => Decoration.none,
  update: (v, tr) => { for (const e of tr.effects) if (e.is(setSyncLine)) v = e.value; return v.map(tr.changes) },
  provide: f => EditorView.decorations.from(f),
})
const setDropPreview = StateEffect.define() // editor drop: a short glow on the text a drop wrote
const dropField = StateField.define({
  create: () => Decoration.none,
  update: (v, tr) => { for (const e of tr.effects) if (e.is(setDropPreview)) v = e.value; return v.map(tr.changes) },
  provide: f => EditorView.decorations.from(f),
})
const setPeer = StateEffect.define() // remote cursor: colored bar, no blink
const peerField = StateField.define({
  create: () => Decoration.none,
  update: (v, tr) => { for (const e of tr.effects) if (e.is(setPeer)) v = e.value; return v.map(tr.changes) },
  provide: f => EditorView.decorations.from(f),
})
const setMarks = StateEffect.define() // gutter dots per comment line
const markField = StateField.define({
  create: () => RangeSet.empty,
  update: (v, tr) => { for (const e of tr.effects) if (e.is(setMarks)) v = e.value; return v.map(tr.changes) },
  provide: f => gutterLineClass.from(f),
})
class ThreadDot extends GutterMarker {
  constructor(suggestion = false) { super(); this.suggestion = suggestion }
  get elementClass() { return this.suggestion ? 'hasThread hasSuggestion' : 'hasThread' }
  eq(o) { return o instanceof ThreadDot && o.suggestion === this.suggestion }
}
class PeerCaret extends WidgetType {
  constructor(c, n) { super(); this.c = c; this.n = n }
  eq(o) { return o.c === this.c && o.n === this.n }
  toDOM() {
    const w = document.createElement('span'); w.className = 'peerW'; w.title = this.n
    const bar = document.createElement('span'); bar.className = 'peer'; bar.style.borderLeftColor = this.c
    const lab = document.createElement('span'); lab.className = 'peerName'; lab.textContent = this.n
    lab.style.color = this.c; lab.style.borderColor = this.c
    w.append(bar, lab); return w
  }
}
const posOfLine = (t, line) => { // char pos of 1-based line
  let p = 0
  for (let l = 1; l < line; l++) { p = t.indexOf('\n', p) + 1; if (!p) return t.length }
  return p
}
function exactQuotePos(t, q, hintLine) { // exact match nearest to hintLine (line distance first, then char distance), else -1
  if (!q) return -1
  const hint = posOfLine(t, hintLine)
  let p = -1, best = -1, bestL = Infinity, bestC = Infinity, n = 0
  while ((p = t.indexOf(q, p + 1)) >= 0 && n++ < 20) {
    const ld = Math.abs(t.slice(0, p).split('\n').length - hintLine), cd = Math.abs(p - hint)
    if (ld < bestL || (ld === bestL && cd < bestC)) { bestL = ld; bestC = cd; best = p }
  }
  return best
}
function locateQuote(t, q, hintLine) { // exact, else halves/prefix near old spot; -1 = not found
  if (!q) return -1
  const exact = exactQuotePos(t, q, hintLine)
  if (exact >= 0) return exact // same text twice: keep the one on the anchored line, not the first
  const hint = posOfLine(t, hintLine)
  const near = arr => arr.sort((a, b) => {
    const ld = Math.abs(t.slice(0, a).split('\n').length - hintLine) - Math.abs(t.slice(0, b).split('\n').length - hintLine)
    return ld || Math.abs(a - hint) - Math.abs(b - hint)
  })[0]
  const cands = []
  const pushAll = (sub, shift = 0) => {
    if (sub.length < 10) return
    let p = -1, n = 0
    while ((p = t.indexOf(sub, p + 1)) >= 0 && n++ < 20) cands.push(Math.max(0, p - shift))
  }
  if (q.length >= 16) { const h = q.length >> 1; pushAll(q.slice(0, h)); pushAll(q.slice(h), h) }
  else pushAll(q.slice(0, Math.min(10, q.length)))
  if (!cands.length && q.length > 10) pushAll(q.slice(0, 10))
  if (!cands.length) return -1
  return near(cands)
}
function threadHighlights() {
  const rs = []
  for (const th of threads) {
    if (th.suggestion_status && th.suggestion_status !== 'pending') continue
    if (th.a == null || th.b == null) continue
    const pending = th.suggestion_status === 'pending'
    if (pending && th.conflict) { // conflicted suggestion: mark anchor line cleanly without slicing unrelated text
      const { from: a, to: b } = threadEditorRange(th)
      if (b > a) rs.push(Decoration.mark({
        class: 'cm-hl cm-suggestion cm-suggestion-conflict',
        attributes: { 'data-suggestion-id': String(th.id) },
      }).range(a, b))
      continue
    }
    let source = th, span = null
    if (pending) {
      span = tokenSafeSpan(th.suggestion_old, diffSpan(th.suggestion_old, th.replacement)) // display trim: never cut inside a formula/raw token
      const a = Math.min(th.b, th.a + span.a)
      source = { ...th, a, b: Math.max(a, th.b - span.b) }
    }
    const { from: a, to: b } = threadEditorRange(source)
    if (b > a) rs.push(Decoration.mark({
      class: pending ? 'cm-hl cm-suggestion suggestionDeleted' : th.resolved ? 'cm-hl cm-hl-resolved' : 'cm-hl',
      attributes: pending ? { 'data-suggestion-id': String(th.id) } : { 'data-comment-id': String(th.id) },
    }).range(a, b))
    if (pending) {
      const widget = new SuggestionReplacement(th, span)
      if (widget.text) rs.push(Decoration.widget({ widget, side: 1 }).range(b))
    }
  }
  return rs
}
function tokenCut(text, cut, from) { // snap a char cut out of the strict inside of math/raw/string tokens (from: keep the token's left edge)
  try {
    let best = cut
    typstParser.parse(text).iterate({ enter(node) {
      if (node.from < cut && cut < node.to && /^(Raw|RawInline|Equation|Math|Str|String)$/.test(node.name)) best = from ? Math.min(best, node.from) : Math.max(best, node.to)
    } })
    return best
  } catch (e) { return cut } // no parser in scope (tests): plain char trim
}
function tokenSafeSpan(old, { a, b }) { // tokenCut both trim ends so a pending mark stays visually continuous over whole tokens
  if (a + b > old.length || a < 0 || b < 0) return { a, b }
  const na = a ? tokenCut(old, a, true) : a
  const nb = b ? old.length - tokenCut(old, old.length - b, false) : b
  return { a: na, b: nb }
}
function refreshHl() {
  if (window.suggestionDraft) { paintDraftSuggestions(); return }
  cm.dispatch({ effects: setHl.of(RangeSet.of(threadHighlights(), true)) })
}
let threads = [], marks = new Set(), markStyle = '', popAnchor = null // null = closed (anchors are 1-based)
let applying = false // remote sync writes: triggers no push
const typstSupport = typst_lezer() // hoisted: project completions register via .language.data below
