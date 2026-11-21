// --- Sync map: every word on paper aligned to its source letters (preview clicks, cursor follow and link targets share it) ---
const SM_LCS_MAX = 250000 // LCS cells per gap: bigger gaps are split at words that are unique on both sides first
const SM_NEAR = 4 // a matched word needs a matched source neighbour this close (words) or it is a coincidence
const SM_GLUE = 0.15 // gap between two runs (share of the font size) that still makes one word: "Unter*punkt*"
const SM_CELL = 1.5 // gap (font sizes) that splits one visual row into columns, cells or a formula and its number
const SM_FOLD = 3 // a block break moves a generator boundary by at most this many words
const SM_MARGIN = 0.07 // header/footer band (share of the page height)
const SM_GRACE = 3 // CSS px around a text box that still count as on the text (glyphs reach past the em box)
const SM_SILENT = new Set(['set', 'show', 'let', 'import', 'pagebreak', 'colbreak', 'v', 'h', 'linebreak', 'parbreak', 'line', 'image', 'metadata', 'counter', 'state', 'place', 'hide', 'include']) // calls that print no words
const SM_EQNUM = /^[(\[]?\s*(?:\d+|[A-Za-z]|[ivxlcdm]+)(?:[.\-–]\d+)*[a-z]?\s*[)\]]?$/ // "(1)", "(2.3a)": equation numbers
let smMemo = null

function smWords(s) { // normalized text -> words with their start (Han/kana: one word per character, like the source view)
  const out = []
  for (const m of s.matchAll(/[\p{L}\p{N}]+/gu)) {
    if (!SRC_CJK.test(m[0])) { out.push({ w: m[0], i: m.index }); continue }
    let run = '', at = m.index, i = m.index
    for (const ch of m[0]) {
      if (SRC_CJK.test(ch)) { if (run) out.push({ w: run, i: at }); out.push({ w: ch, i }); run = '' } else { if (!run) at = i; run += ch }
      i += ch.length
    }
    if (run) out.push({ w: run, i: at })
  }
  return out
}
function smRow(a, b) { // same visual row: the boxes share half the smaller height (a raised footnote marker too)
  const ha = a.h || 10, hb = b.h || 10
  return Math.min(a.y + ha / 2, b.y + hb / 2) - Math.max(a.y - ha / 2, b.y - hb / 2) >= Math.min(ha, hb) * 0.5
}
function smGlue(a, b) { return !a.rot && !b.rot && smRow(a, b) && Math.abs(b.x0 - (a.x0 + (a.w || 0))) <= (b.h || 10) * SM_GLUE }
function smInLink(links, it) { // run inside an internal link box (outline entry, reference, citation): generated, never a second copy of the source
  return (links || []).some(L => L.dest && it.x0 + (it.w || 0) / 2 >= L.x0 && it.x0 + (it.w || 0) / 2 <= L.x1 && it.y >= L.y0 - 1 && it.y <= L.y1 + 1)
}
function smMathItems(items) { // display formulas and their numbers: formulas map glyph by glyph (pvMathMatch), never as words
  const out = new Set()
  for (const L of pvMathLines(items || [])) {
    for (const it of L.items) out.add(it)
    for (const it of items) if (smRow(it, { y: (L.y0 + L.y1) / 2, h: L.y1 - L.y0 }) && SM_EQNUM.test(String(it.s || '').trim())) out.add(it)
  }
  return out
}
function smPdfTokens(pages, links) { // words on paper in content order; every letter keeps its item and offset
  const out = []
  pages.forEach((items, pi) => {
    let tail = -1 // item whose last word ended the token list: a touching run continues that word
    const math = smMathItems(items)
    ;(items || []).forEach((it, ii) => {
      if (math.has(it)) { tail = -1; return }
      const { s, map } = syncNormMap(String(it.s || ''))
      const ws = smWords(s)
      const link = ws.length && smInLink(links && links[pi], it)
      ws.forEach((m, k) => {
        const li = [], lo = []
        for (let j = 0; j < m.w.length; j++) { li.push(ii); lo.push(map[m.i + j]) }
        const prev = out[out.length - 1]
        const glue = k === 0 && m.i === 0 && tail >= 0 && prev && smGlue(items[tail], it) && !/^\d+$/.test(prev.w) && !/^\d+$/.test(m.w) // a footnote number touching its text stays apart
        if (glue) { prev.w += m.w; prev.li.push(...li); prev.lo.push(...lo); prev.link = prev.link || link }
        else out.push({ w: m.w, pi, li, lo, link })
      })
      const last = ws[ws.length - 1]
      tail = last && last.i + last.w.length === s.length ? ii : -1
    })
  })
  return out
}
function smJoin(base, pages, vocab) { // a word hyphenated at a line end is one source word ("Arbeitsunfä" + "higkeit"); new tokens, the cached list stays as it is
  const toks = []
  for (let i = 0; i < base.length; i++) {
    const a = base[i], b = base[i + 1], w = b ? a.w + b.w : ''
    if (!b || a.pi !== b.pi || a.w.length < 2 || b.w.length < 2 || /\d/.test(w) || vocab.has(a.w) || !vocab.has(w)
      || smRow(pages[a.pi][a.li[a.li.length - 1]], pages[b.pi][b.li[0]])) { toks.push(a); continue } // same row: a real word gap
    toks.push({ ...a, w, li: a.li.concat(b.li), lo: a.lo.concat(b.lo), link: a.link || b.link })
    i++
  }
  return toks
}
const smWordsCache = new Map() // source text -> its words (bounded like srcViewCache)
const smTokCache = { pages: null, links: null, toks: null } // paper tokens of the last page set
function smPath(dir, p) { // include path -> project file name ("../x.typ" resolved against the including file)
  const parts = []
  for (const s of ((p.startsWith('/') ? '' : dir) + p).split('/')) { if (s === '..') parts.pop(); else if (s && s !== '.') parts.push(s) }
  return parts.join('/')
}
function smIncludes(srcs, si) { // #include sites of one source in order: [{at, si}]
  const src = srcs[si], out = [], dir = src.key.includes('/') && !isTplKey(src.key) ? src.key.replace(/[^/]*$/, '') : ''
  for (const m of srcMask(src.text).matchAll(/(^|[^\w.-])include\s*\(?\s*"([^"]+)"/g)) {
    const want = smPath(dir, m[2])
    let k = srcs.findIndex(s => s.key && !isTplKey(s.key) && s.key === want) // a project file wins over a module of the same name
    if (k < 0) k = srcs.findIndex(s => s.key && tabName(s.key) === want)
    if (k >= 0) out.push({ at: m.index + m[1].length, si: k })
  }
  return out
}
function smSrcWords(text) { // visible words of a source with the raw offset of every letter; footnote bodies last (paper prints them at the page bottom)
  const body = [], notes = []
  let base = 0
  const put = (out, seg, note) => {
    if (!seg || !seg.s) return
    const { s, map } = syncNormMap(seg.s)
    for (const m of smWords(s)) {
      const lm = []
      for (let j = 0; j < m.w.length; j++) lm.push(base + (seg.map[map[m.i + j]] ?? 0))
      out.push({ w: m.w, raw: lm[0], map: lm, note })
    }
  }
  for (const L of srcViewOf(text).lines) { put(body, L, false); put(notes, L.note, true); base += (L.raw != null ? L.raw : L.s).length + 1 }
  return body.concat(notes)
}
function smStream(srcs) { // main.typ words with every included file spliced in where it is included: [[si, wi]]
  const out = [], seen = new Set()
  const walk = (si, depth) => {
    if (seen.has(si) || depth > 8) return
    seen.add(si)
    const inc = smIncludes(srcs, si)
    let k = 0
    srcs[si].words.forEach((w, wi) => {
      if (w.note) return // out of flow: pass 2 finds it at the page bottom
      while (k < inc.length && inc[k].at <= w.raw) walk(inc[k++].si, depth + 1)
      out.push([si, wi])
    })
    while (k < inc.length) walk(inc[k++].si, depth + 1)
  }
  const main = srcs.findIndex(s => !s.key)
  if (main >= 0) walk(main, 0)
  return out
}
function smLis(pairs) { // longest chain increasing in both coordinates (pairs sorted by the first)
  const tails = [], prev = new Int32Array(pairs.length)
  pairs.forEach((p, k) => {
    let lo = 0, hi = tails.length
    while (lo < hi) { const mid = (lo + hi) >> 1; if (pairs[tails[mid]][1] < p[1]) lo = mid + 1; else hi = mid }
    prev[k] = lo ? tails[lo - 1] : -1
    tails[lo] = k
  })
  const out = []
  for (let k = tails.length ? tails[tails.length - 1] : -1; k >= 0; k = prev[k]) out.push(pairs[k])
  return out.reverse()
}
function smLcs(A, B, a0, a1, b0, b1, m, W, C) { // best alignment of a small gap: every match counts W[i], continuing a run adds C[i]; equal scores keep the later match
  const n = a1 - a0, w = b1 - b0 + 1, F = new Int32Array((n + 1) * w), R = new Int32Array((n + 1) * w).fill(-1) // F: best in the prefix, R: best ending in a match here
  for (let i = 1; i <= n; i++) for (let j = 1; j < w; j++) {
    const k = i * w + j, d = k - w - 1
    if (A[a0 + i - 1] === B[b0 + j - 1]) R[k] = Math.max(F[d] + W[a0 + i - 1], R[d] >= 0 ? R[d] + W[a0 + i - 1] + C[a0 + i - 1] : -1)
    F[k] = Math.max(F[k - w], F[k - 1], R[k])
  }
  let run = false
  for (let i = n, j = w - 1; i > 0 && j > 0;) {
    const k = i * w + j, d = k - w - 1
    if (run || (R[k] >= 0 && R[k] === F[k])) { m[a0 + i - 1] = b0 + j - 1; run = R[d] >= 0 && R[k] === R[d] + W[a0 + i - 1] + C[a0 + i - 1]; i--; j-- }
    else if (F[k] === F[k - w]) i--
    else j--
  }
}
function smAlign(A, B, W, C) { // word lists -> m[i]: index in B or -1 (patience split at unique words, a run-aware LCS inside small gaps); W: weight per paper word
  const m = new Int32Array(A.length).fill(-1), todo = [[0, A.length, 0, B.length]]
  while (todo.length) {
    let [a0, a1, b0, b1] = todo.pop()
    if (a0 >= a1 || b0 >= b1) continue
    if ((a1 - a0) * (b1 - b0) <= SM_LCS_MAX) { smLcs(A, B, a0, a1, b0, b1, m, W, C); continue }
    while (a0 < a1 && b0 < b1 && A[a0] === B[b0]) m[a0++] = b0++ // big gap: equal ends are certain enough
    while (a0 < a1 && b0 < b1 && A[a1 - 1] === B[b1 - 1]) m[--a1] = --b1
    if (a0 >= a1 || b0 >= b1) continue
    const ca = new Map(), cb = new Map()
    for (let i = a0; i < a1; i++) { const c = ca.get(A[i]); ca.set(A[i], c ? [c[0] + 1, c[1]] : [1, i]) }
    for (let j = b0; j < b1; j++) { const c = cb.get(B[j]); cb.set(B[j], c ? [c[0] + 1, c[1]] : [1, j]) }
    const pairs = []
    for (const [w, c] of ca) { const d = cb.get(w); if (c[0] === 1 && d && d[0] === 1) pairs.push([c[1], d[1]]) }
    pairs.sort((p, q) => p[0] - q[0])
    let pa = a0, pb = b0
    for (const [i, j] of smLis(pairs)) { m[i] = j; todo.push([pa, i, pb, j]); pa = i + 1; pb = j + 1 }
    if (pa > a0) todo.push([pa, a1, pb, b1]) // no unique word at all: the gap stays unmatched
  }
  return m
}
function smSlide(m, A, B) { // two equal words on paper, one source word: the copy that continues a matched run owns it (body text, not an outline entry or a footnote)
  const at = []
  for (let i = 0; i < m.length; i++) if (m[i] >= 0) at.push(i)
  const run = (i, j, p, n) => (p >= 0 && p === i - 1 && m[p] === j - 1 ? 1 : 0) + (n >= 0 && n === i + 1 && m[n] === j + 1 ? 1 : 0)
  for (let k = 0; k < at.length; k++) {
    const i = at[k], j = m[i], p = k > 0 ? at[k - 1] : -1, n = k + 1 < at.length ? at[k + 1] : -1
    let best = i, score = run(i, j, p, n)
    if (score === 2) continue
    const lo = Math.max(p + 1, i - 200), hi = Math.min(n < 0 ? m.length : n, i + 200)
    for (let c = lo; c < hi; c++) if (c !== i && m[c] < 0 && A[c] === A[i]) { const sc = run(c, j, p, n); if (sc > score) { score = sc; best = c } }
    if (best !== i) { m[best] = j; m[i] = -1; at[k] = best }
  }
}
function smTrim(m, A, B) { // a match that is an island in the source (no matched source word nearby) is a shared common word, not the same text
  const ca = new Map(), cb = new Map()
  for (const w of A) ca.set(w, (ca.get(w) || 0) + 1)
  for (const w of B) cb.set(w, (cb.get(w) || 0) + 1)
  const at = []
  for (let i = 0; i < m.length; i++) if (m[i] >= 0) at.push(i)
  const drop = at.filter((i, k) => {
    if (ca.get(A[i]) === 1 && cb.get(A[i]) === 1) return false
    const p = k > 0 ? m[at[k - 1]] : -Infinity, q = k + 1 < at.length ? m[at[k + 1]] : Infinity
    return at.length > 1 && m[i] - p > SM_NEAR && q - m[i] > SM_NEAR // generated text on paper may sit between two words, the source keeps them adjacent
  })
  for (const i of drop) m[i] = -1
}
function smPass2(M) { // out-of-flow text (footnotes, floats, headers, .bib entries, modules): unique runs of two and more words
  const idx = new Map()
  M.srcs.forEach((s, si) => {
    for (let wi = 0; wi + 1 < s.words.length; wi++) {
      const k = s.words[wi].w + ' ' + s.words[wi + 1].w
      if (!idx.has(k)) idx.set(k, [])
      idx.get(k).push([si, wi])
    }
  })
  const { toks, own } = M
  const free = i => i < toks.length && !own[i] && !toks[i].link // a link text is a generated copy (outline entry, reference)
  for (let i = 0; i + 1 < toks.length;) {
    const c = free(i) && free(i + 1) && toks[i].pi === toks[i + 1].pi ? idx.get(toks[i].w + ' ' + toks[i + 1].w) : null
    if (!c) { i++; continue }
    let best = 0, hits = []
    for (const [si, wi] of c) {
      const ws = M.srcs[si].words
      let L = 2
      while (free(i + L) && toks[i + L].pi === toks[i].pi && wi + L < ws.length && ws[wi + L].w === toks[i + L].w) L++
      if (L > best) { best = L; hits = [[si, wi]] } else if (L === best) hits.push([si, wi])
    }
    if (hits.length !== 1) { i++; continue }
    for (let j = 0; j < best; j++) own[i + j] = { si: hits[0][0], wi: hits[0][1] + j, p: 2 }
    i += best
  }
}
function smBuild(pages, links, list) { // pages: pvTexts, links: pvLinks, list: [{key, text}] (main.typ has key '')
  const words = text => {
    let w = smWordsCache.get(text)
    if (!w) { w = smSrcWords(text); smWordsCache.set(text, w); if (smWordsCache.size > 8) smWordsCache.delete(smWordsCache.keys().next().value) }
    return w
  }
  const srcs = list.filter(s => s && typeof s.text === 'string').map(s => ({ key: s.key || '', text: s.text, words: words(s.text) }))
  const vocab = new Set()
  for (const s of srcs) for (const w of s.words) vocab.add(w.w)
  const C = smTokCache
  if (C.pages !== pages || C.links !== links || C.n !== pages.length || C.items.some((p, i) => p !== pages[i])) Object.assign(C, { pages, links, n: pages.length, items: pages.slice(), toks: smPdfTokens(pages, links) })
  const toks = smJoin(C.toks, pages, vocab)
  const stream = smStream(srcs)
  const A = toks.map(t => t.w), B = stream.map(([si, wi]) => srcs[si].words[wi].w)
  const W = toks.map(t => t.link ? 1 : 2) // a link text (outline entry, reference) is the weaker copy
  const R = toks.map((t, i) => i && toks[i - 1].pi === t.pi && toks[i - 1].li[toks[i - 1].li.length - 1] === t.li[0] ? 2 : 1) // words of one run on paper are one run in the source
  const m = smAlign(A, B, W, R)
  smSlide(m, A, B)
  smTrim(m, A, B)
  const own = toks.map((t, i) => m[i] >= 0 ? { si: stream[m[i]][0], wi: stream[m[i]][1], p: 1 } : null)
  const M = { pages, srcs, toks, own, gaps: new Map(), byItem: new Map(), byPos: srcs.map(() => []) }
  smPass2(M)
  toks.forEach((t, ti) => {
    for (const ii of new Set(t.li)) { const k = t.pi + ':' + ii; if (!M.byItem.has(k)) M.byItem.set(k, []); M.byItem.get(k).push(ti) }
    const o = own[ti]
    if (o) M.byPos[o.si].push([M.srcs[o.si].words[o.wi].raw, ti])
  })
  for (const a of M.byPos) a.sort((x, y) => x[0] - y[0] || x[1] - y[1])
  return M
}
function smMap() { // memo: rebuilt only when the paper or a source text changed
  const list = pvSrcList(), done = pvTextDone.filter(Boolean).length, memo = smMemo
  if (memo && memo.gen === pvMetaGen && memo.done === done && memo.pages.length === pvTexts.length && memo.pages.every((p, i) => p === pvTexts[i])
    && memo.list.length === list.length && list.every((s, i) => s.key === memo.list[i].key && s.text === memo.list[i].text)) return memo.M
  const M = smBuild(pvTexts, pvLinks, list)
  smMemo = { gen: pvMetaGen, done, pages: pvTexts.slice(), list, M }
  return M
}

// --- source side: word positions, constructs (calls, refs, math) and literal words in code ---
function smItem(M, ti) { const t = M.toks[ti]; return M.pages[t.pi][t.li[0]] }
function smWordAt(M, ti, k) { // owned token + letter -> {key, at} (k at the word length: caret behind the word)
  const o = M.own[ti], s = M.srcs[o.si], w = s.words[o.wi]
  if (k >= w.map.length) return { key: s.key, at: srcAfter(s.text, w.map[w.map.length - 1]) }
  return { key: s.key, at: w.map[Math.max(0, k)] }
}
function smLineStart(t, p) { return t.lastIndexOf('\n', p - 1) + 1 }
function smLineEnd(t, p) { const e = t.indexOf('\n', p); return e < 0 ? t.length : e }
function smGroup(t, i, open) { // index behind the bracket group that opens at i (strings in code, escapes, nesting)
  const close = { '(': ')', '[': ']', '{': '}' }, st = [close[open]]
  for (i++; i < t.length && st.length; i++) {
    const c = t[i], top = st[st.length - 1]
    if (c === '\\') { i++; continue }
    if (c === '"' && top !== ']') { while (++i < t.length && t[i] !== '"') if (t[i] === '\\') i++; continue }
    if (c === top) st.pop()
    else if (close[c]) st.push(close[c])
  }
  return i
}
function smCons(t, from, to) { // top-level constructs starting in [from, to): #calls, @refs, $math$, headings (masked text)
  const out = []
  for (let i = from; i < to; i++) {
    const c = t[i]
    if (c === '\\') { i++; continue }
    if (c === '<' && /^<[\p{L}\p{N}_][\p{L}\p{N}_:.-]*>/u.test(t.slice(i, i + 80))) { i = t.indexOf('>', i); continue } // a label prints nothing
    if (c === '=' && /^[ \t]*$/.test(t.slice(smLineStart(t, i), i)) && /[=\s]/.test(t[i + 1] || '')) { const e = smLineEnd(t, i); out.push({ at: i, end: e, name: '=', head: i + 1 }); i = e; continue }
    if (c === '$') { let e = i + 1; while (e < t.length && t[e] !== '$') e += t[e] === '\\' ? 2 : 1; out.push({ at: i, end: e + 1, name: '$', head: i + 1 }); i = e; continue }
    if (c === '@' && !/[\p{L}\p{N}_]/u.test(t[i - 1] || '')) {
      const m = t.slice(i, i + 200).match(/^@[\p{L}\p{N}_](?:[\p{L}\p{N}_:.-]*[\p{L}\p{N}_])?/u)
      if (!m) continue
      let e = i + m[0].length
      if (t[e] === '[') e = smGroup(t, e, '[')
      out.push({ at: i, end: e, name: '@', head: i + m[0].length }); i = e - 1; continue
    }
    if (c !== '#') continue
    const m = t.slice(i + 1, i + 120).match(/^[\p{L}_][\p{L}\p{N}_-]*(?:\.[\p{L}_][\p{L}\p{N}_-]*)*/u)
    if (!m && !/[({[]/.test(t[i + 1] || '')) continue
    const name = m ? m[0].split('.')[0] : '', head = i + 1 + (m ? m[0].length : 0)
    let e = head
    if (['set', 'show', 'let', 'import', 'include', 'if', 'for', 'while', 'context', 'return'].includes(name)) { // statements: to the end of their last block or line
      e = smLineEnd(t, head)
      for (let j = head; j < e; j++) if (/[({[]/.test(t[j])) { const g = smGroup(t, j, t[j]); if (g > e) e = smLineEnd(t, g); j = g - 1 }
    } else while (/[({[]/.test(t[e] || '')) e = smGroup(t, e, t[e])
    out.push({ at: i, end: e, name, head })
    i = e - 1
  }
  return out
}
function smInner(t, c) { return smCons(t, c.head, Math.min(c.end, t.length)) }
function smSize(t, c) { // words a construct prints when it is known: #lorem(n) and wrappers around it
  if (c.name === 'lorem') { const n = t.slice(c.head).match(/^\s*\(\s*(\d+)\s*\)/); return n ? +n[1] : null }
  if (['for', 'while', '$', '@', '='].includes(c.name)) return null
  const inner = smInner(t, c).filter(x => !SM_SILENT.has(x.name))
  if (!inner.length) return null
  let sum = 0
  for (const x of inner) { const n = smSize(t, x); if (n == null) return null; sum += n }
  return sum
}
function smLiteral(t, w, from, to, near, once) { // the word written in code or strings inside [from, to): nearest to `near`; once: only a unique one
  const { s, map } = syncNormMap(srcMask(t.slice(from, to)))
  let best = -1, bd = Infinity, n = 0
  for (const m of smWords(s)) {
    if (m.w !== w) continue
    if (once && n++) return -1
    const at = from + map[m.i], d = Math.abs(at - near)
    if (d < bd) { bd = d; best = at }
  }
  return best
}
function smOwnedIn(M, si, a, b) { // an owned source word inside [a, b)
  const arr = M.byPos[si]
  let lo = 0, hi = arr.length
  while (lo < hi) { const mid = (lo + hi) >> 1; if (arr[mid][0] < a) lo = mid + 1; else hi = mid }
  return lo < arr.length && arr[lo][0] < b
}

// --- generated text: the construct between the owned words around it ---
function smGapCons(M, si, from, to, right) { // printing constructs of a gap; one that holds the next owned word only opens it
  const t = srcMask(M.srcs[si].text)
  return smCons(t, from, to).filter(c => !SM_SILENT.has(c.name) && !(right != null && c.at <= right && right < c.end))
}
function smEnclosing(M, si, ls, pos) { // innermost construct on this line that holds pos ("= Title", "#figure(.., caption: [Text])")
  const t = srcMask(M.srcs[si].text)
  let best = null, list = smCons(t, ls, pos)
  for (;;) {
    const c = list.find(x => x.at < pos && pos < x.end)
    if (!c) return best
    best = c
    list = smCons(t, c.head, pos)
  }
}
function smBreaks(M, group) { // index k: a block break sits between group[k-1] and group[k]
  const out = new Set()
  for (let k = 1; k < group.length; k++) {
    const a = M.toks[group[k - 1]], b = M.toks[group[k]], ia = smItem(M, group[k - 1]), ib = smItem(M, group[k])
    const ha = ia.h || 10, hb = ib.h || 10
    if (a.pi !== b.pi || ib.y < ia.y - ha || (ib.y - hb / 2) - (ia.y + ha / 2) > Math.min(ha, hb) * 0.8) out.add(k) // new page, next column, paragraph or heading gap
  }
  return out
}
function smSnap(k, breaks, n, tol) { // move a boundary onto a block break nearby (hyphenated words add a few words on paper)
  for (let d = 0; d <= tol; d++) { if (breaks.has(k - d)) return k - d; if (breaks.has(k + d)) return k + d }
  return Math.max(0, Math.min(n, k))
}
function smAssign(M, si, group, cons) { // tokens -> construct chains (outer to inner) in order: known word counts first, else proportional, snapped to block breaks
  const out = new Map()
  if (!cons.length) return out
  const t = srcMask(M.srcs[si].text), n = group.length, breaks = smBreaks(M, group)
  const sizes = cons.map(c => smSize(t, c)), unknown = sizes.filter(x => x == null).length
  const bounds = [0]
  if (unknown <= 1 && cons.length > 1) {
    const rest = Math.max(0, n - sizes.reduce((a, x) => a + (x || 0), 0))
    for (let c = 0; c < cons.length - 1; c++) { const size = sizes[c] == null ? rest : sizes[c]; bounds.push(smSnap(bounds[c] + size, breaks, n, SM_FOLD + Math.ceil(size * 0.1))) }
  } else for (let c = 1; c < cons.length; c++) bounds.push(smSnap(Math.round(c * n / cons.length), breaks, n, SM_FOLD))
  bounds.push(n)
  for (let c = 0; c < cons.length; c++) {
    const part = group.slice(bounds[c], Math.max(bounds[c], bounds[c + 1]))
    const inner = smInner(t, cons[c]).filter(x => !SM_SILENT.has(x.name))
    const deep = inner.length && !smOwnedIn(M, si, cons[c].head, cons[c].end) ? smAssign(M, si, part, inner) : null // "#columns(2)[#lorem(100)]": the inner call printed it
    for (const ti of part) out.set(ti, [cons[c], ...((deep && deep.get(ti)) || [])])
  }
  return out
}
function smPrev(M, ti) { for (let j = ti - 1; j >= 0; j--) if (M.own[j] && M.own[j].p === 1) return j; return -1 }
function smNext(M, ti) { for (let j = ti + 1; j < M.toks.length; j++) if (M.own[j] && M.own[j].p === 1) return j; return -1 }
function smSameRow(M, a, b) { return a >= 0 && b >= 0 && M.toks[a].pi === M.toks[b].pi && smRow(smItem(M, a), smItem(M, b)) }
function smSpan(M, a, b) { // source span between two owned words, also across an #include boundary
  if (!a && !b) { const si = M.srcs.findIndex(s => !s.key); return si < 0 ? null : { si, from: 0, to: M.srcs[si].text.length, right: null } } // nothing owned at all (a #lorem-only page): the whole main file printed it
  if (a && b && a.si === b.si) return { si: a.si, from: a.at, to: b.at, right: b.at }
  const printing = (si, from, to) => smGapCons(M, si, from, to, null).length > 0
  if (a) { // leaving a's file: its text up to the include of b's file (or its end) printed the gap
    const site = b ? smIncludes(M.srcs, a.si).find(x => x.si === b.si && x.at >= a.at) : null
    const to = site ? site.at : M.srcs[a.si].text.length
    if (printing(a.si, a.at, to) || !b) return { si: a.si, from: a.at, to, right: null }
  }
  const site = a ? smIncludes(M.srcs, b.si).find(x => x.si === a.si && x.at < b.at) : null // back in the including file: right behind the include
  return { si: b.si, from: site ? smLineEnd(M.srcs[b.si].text, site.at) : 0, to: b.at, right: b.at }
}
function smGap(M, A, B) { // unowned words between two owned flow words -> {ti: {si, c, from, to, right}} (memo per gap)
  const key = A + ':' + B
  if (M.gaps.has(key)) return M.gaps.get(key)
  const res = new Map(), oa = A >= 0 ? M.own[A] : null, ob = B >= 0 ? M.own[B] : null
  const end = o => { const w = M.srcs[o.si].words[o.wi]; return srcAfter(M.srcs[o.si].text, w.map[w.map.length - 1]) }
  const a = oa ? { si: oa.si, at: end(oa) } : null, b = ob ? { si: ob.si, at: M.srcs[ob.si].words[ob.wi].raw } : null
  const free = []
  for (let j = A + 1; j < (B >= 0 ? B : M.toks.length); j++) if (!M.own[j]) free.push(j)
  const rowA = [], rowB = [], mid = []
  const inline = smSameRow(M, A, B) && a && b && a.si === b.si
  for (const j of free) {
    if (inline) mid.push(j)
    else if (smSameRow(M, A, j) && rowB.length === 0 && mid.length === 0) rowA.push(j) // text right behind A on its row
    else if (smSameRow(M, j, B)) rowB.push(j)
    else mid.push(j)
  }
  const put = (group, si, from, to, right) => {
    if (!group.length || si == null) return
    const text = M.srcs[si].text
    from = Math.max(0, Math.min(from, text.length)); to = Math.max(from, Math.min(to, text.length))
    const cons = smGapCons(M, si, from, to, right), map = smAssign(M, si, group, cons)
    for (const ti of group) { const chain = map.get(ti) || []; res.set(ti, { si, c: chain[chain.length - 1] || null, chain, from, to, right }) }
  }
  if (rowA.length) put(rowA, a.si, a.at, smLineEnd(M.srcs[a.si].text, a.at), null)
  if (rowB.length) { // generated text in front of an owned word on its row: the construct that holds that word ("1 Title", "Figure 1: Caption")
    const ls = smLineStart(M.srcs[b.si].text, b.at), c = smEnclosing(M, b.si, ls, b.at)
    for (const ti of rowB) res.set(ti, { si: b.si, c, chain: c ? [c] : [], from: ls, to: b.at, right: b.at })
  }
  if (mid.length) {
    const sp = smSpan(M, a, b)
    if (sp) put(mid, sp.si, sp.from, sp.to, sp.right)
  }
  M.gaps.set(key, res)
  return res
}
function smEntry(text, at) { // .bib entry around a position: [start of "@type{key," , start of the next entry)
  const head = /^[ \t]*@[A-Za-z]+\s*[{(]/gm
  let from = 0, to = text.length, m
  while ((m = head.exec(text))) { if (m.index <= at) from = m.index; else { to = m.index; break } }
  return { from: from + text.slice(from).match(/^\s*/)[0].length, to }
}
function smForeign(M, ti, n) { // generated text beside an out-of-flow word (a .bib entry label, a module header): stay in that file
  const o = M.own[n], s = M.srcs[o.si], w = M.toks[ti].w, near = s.words[o.wi].raw
  if (/\.bib$/i.test(s.key) || /^\s*@[A-Za-z]+\s*[{(]/.test(s.text)) {
    const e = smEntry(s.text, near), le = smLineEnd(s.text, e.from), one = !s.text.slice(le + 1, e.to).trim() // a one-line entry: its fields follow the key on the same line
    const ci = s.text.indexOf(',', e.from), body = !one ? le + 1 : ci >= 0 && ci < le ? ci + 1 : e.from // "Knuth" is the author field, not the entry key
    const label = /^\s*(?:\[\s*\d{1,4}\s*\]|\(\s*\d{1,4}\s*\)|\d{1,3}\.)\s*$/.test(String(smItem(M, ti).s)) // "[2]" in front of an entry is its number, not the volume 2
    const at = label ? -1 : smLiteral(s.text, w, body, e.to, near, w.length < 2) // a one-letter word only when the entry has it once
    return { key: s.key, at: at >= 0 ? at : e.from }
  }
  const ls = smLineStart(s.text, near), at = smLiteral(s.text, w, ls, smLineEnd(s.text, near), near)
  return { key: s.key, at: at >= 0 ? at : near }
}
function smPageSetup(M) { // a page number or running header: the page setup that prints it (main.typ first, then a module)
  for (const src of M.srcs.slice().sort((x, y) => (x.key ? 1 : 0) - (y.key ? 1 : 0))) {
    if (src.key && !/\.typ$/i.test(tabName(src.key))) continue
    const m = srcMask(src.text).match(/\bset\s+page\s*\(/)
    if (m) return { key: src.key, at: src.text[m.index - 1] === '#' ? m.index - 1 : m.index }
  }
  return null
}
function smResolve(M, ti, k) { // token + letter -> {key, at} | null: the source letter, or the construct that printed it
  if (M.own[ti]) return smWordAt(M, ti, k)
  const t = M.toks[ti], it = smItem(M, ti)
  let L = -1, R = -1 // nearest owned words on the same row
  for (let j = ti - 1; j >= 0 && smSameRow(M, j, ti) && L < 0; j--) if (M.own[j]) L = j
  for (let j = ti + 1; j < M.toks.length && smSameRow(M, j, ti) && R < 0; j++) if (M.own[j]) R = j
  const near = L >= 0 && (R < 0 || ti - L <= R - ti) ? L : R
  if (near >= 0 && M.own[near].p === 2) return smForeign(M, ti, near)
  if (L < 0 && R < 0 && (it.y < (it.vh || 1) * SM_MARGIN || it.y > (it.vh || 1) * (1 - SM_MARGIN))) { const p = smPageSetup(M); if (p) return p }
  const g = smGap(M, smPrev(M, ti), smNext(M, ti)).get(ti)
  if (!g) return null
  const s = M.srcs[g.si], c = g.c
  if (c) {
    const at = smLiteral(s.text, t.w, c.at, Math.min(c.end, s.text.length), c.at) // "Wanda" in #greet("Wanda")
    if (at >= 0) return { key: s.key, at }
  }
  const strict = t.w.length < 3 // "1" or "x": only inside the gap itself
  const lo = strict ? g.from : smLineStart(s.text, g.from), hi = strict ? g.to : smLineEnd(s.text, g.to)
  const lit = smLiteral(s.text, t.w, lo, hi, g.from) // "Ada" of #for p in ("Ada", "Grace")
  if (lit >= 0) return { key: s.key, at: lit }
  if (c) return { key: s.key, at: c.at }
  return { key: s.key, at: g.right != null ? g.right : g.from }
}

// --- paper side: token under a click and the paper spot of a source position ---
function smTokenAt(M, pi, ii, col) { // item + clicked offset -> {ti, k}; an item without words takes its row neighbour
  const list = M.byItem.get(pi + ':' + ii)
  if (list && list.length) {
    let best = null, bd = Infinity
    for (const ti of list) {
      const t = M.toks[ti], offs = []
      t.li.forEach((x, j) => { if (x === ii) offs.push([t.lo[j], j]) })
      const a = offs[0][0], z = offs[offs.length - 1][0] + 1
      const d = col < a ? a - col : col > z ? col - z : 0
      if (d < bd || (d === bd && col >= a)) {
        bd = d
        let k = offs[0][1]
        for (const [o, j] of offs) if (o < col) k = j + 1
        best = { ti, k: Math.min(k, t.w.length) }
      }
    }
    return best
  }
  const it = M.pages[pi][ii]
  let best = null, bd = Infinity
  M.toks.forEach((t, ti) => {
    if (t.pi !== pi) return
    const o = M.pages[pi][t.li[0]]
    if (!smRow(o, it)) return
    const d = Math.abs(o.x0 - it.x0)
    if (d < bd) { bd = d; best = { ti, k: o.x0 >= it.x0 ? 0 : t.w.length } }
  })
  return best
}
function smFind(M, key, pos) { // source position -> {ti, k} on paper: the word at pos, the output of the construct at pos, else the word nearby on its line
  const si = M.srcs.findIndex(s => s.key === (key || ''))
  if (si < 0) return null
  const s = M.srcs[si], arr = M.byPos[si]
  let lo = 0, hi = arr.length
  while (lo < hi) { const mid = (lo + hi) >> 1; if (arr[mid][0] <= pos) lo = mid + 1; else hi = mid }
  let k = lo - 1
  while (k > 0 && arr[k - 1][0] === arr[k][0] && M.own[arr[k][1]].p !== 1) k-- // a header or outline copy of the same word: the flow text wins
  let q = lo
  while (q + 1 < arr.length && arr[q + 1][0] === arr[q][0] && M.own[arr[q][1]].p !== 1) q++
  const prev = k >= 0 ? arr[k] : null, next = q < arr.length ? arr[q] : null
  if (prev) {
    const o = M.own[prev[1]], w = s.words[o.wi]
    if (pos <= srcAfter(s.text, w.map[w.map.length - 1])) {
      let k = 0
      while (k < w.map.length && w.map[k] < pos) k++
      return { ti: prev[1], k }
    }
  }
  const lineS = smLineStart(s.text, pos), lineE = smLineEnd(s.text, pos)
  const A = prev ? prev[1] : -1, B = next ? next[1] : M.toks.length
  let best = null // the cursor inside a construct: the first word it printed (innermost construct wins)
  const g0 = Math.min(A, B), g1 = Math.max(A, B)
  let pa = smPrev(M, g0 + 1), pb = smNext(M, g0) // flow neighbours, moved along instead of searched per word
  for (let j = g0 + 1; j < g1; j++) {
    if (M.own[j]) { if (M.own[j].p === 1) { pa = j; pb = smNext(M, j) } continue }
    const g = smGap(M, pa, pb).get(j)
    const c = g && g.si === si ? g.chain.filter(x => x.at <= pos && pos <= x.end).pop() : null
    if (c && (!best || c.at > best.at)) best = { ti: j, at: c.at }
  }
  if (best) return { ti: best.ti, k: 0 }
  if (next && next[0] <= lineE) return { ti: next[1], k: 0 }
  if (prev && prev[0] >= lineS) return { ti: prev[1], k: M.toks[prev[1]].w.length }
  return null
}

// --- click geometry: the row, formula or picture a click belongs to (free space included) ---
function smRows(items, skip) { // visual rows of one page: runs on one baseline, split at column, cell and number gaps
  const list = []
  items.forEach((it, ii) => { if (!it.rot && String(it.s || '').trim() && !skip.has(it)) list.push(ii) })
  list.sort((a, b) => items[a].y - items[b].y || items[a].x0 - items[b].x0)
  const bands = []
  for (const ii of list) {
    const B = bands[bands.length - 1]
    if (B && smRow(items[B[0]], items[ii])) B.push(ii); else bands.push([ii])
  }
  const rows = []
  for (const B of bands) {
    B.sort((a, b) => items[a].x0 - items[b].x0)
    let row = null
    for (const ii of B) {
      const it = items[ii], h = it.h || 10
      if (row && it.x0 - row.x1 <= SM_CELL * Math.max(h, row.h)) { row.ii.push(ii); row.x1 = Math.max(row.x1, it.x0 + (it.w || 0)) }
      else rows.push(row = { ii: [ii], x0: it.x0, x1: it.x0 + (it.w || 0), h })
      row.y0 = Math.min(row.y0 ?? Infinity, it.y - h / 2); row.y1 = Math.max(row.y1 ?? -Infinity, it.y + h / 2); row.h = Math.max(row.h, h)
    }
  }
  return rows
}
function smSpread(cands, items) { // every box spans the text block, like a TeX line box; a neighbour on the same band splits the gap
  let bx0 = Infinity, bx1 = -Infinity
  for (const it of items) if (!it.rot && String(it.s || '').trim()) { bx0 = Math.min(bx0, it.x0); bx1 = Math.max(bx1, it.x0 + (it.w || 0)) }
  for (const c of cands) { c.ext = { ...c.real }; if (isFinite(bx0)) { c.ext.x0 = Math.min(c.ext.x0, bx0); c.ext.x1 = Math.max(c.ext.x1, bx1) } }
  for (const c of cands) for (const q of cands) {
    if (q === c || q.real.y1 < c.real.y0 || q.real.y0 > c.real.y1) continue
    if (q.real.x0 >= c.real.x1) c.ext.x1 = Math.min(c.ext.x1, (c.real.x1 + q.real.x0) / 2)
    if (q.real.x1 <= c.real.x0) c.ext.x0 = Math.max(c.ext.x0, (q.real.x1 + c.real.x0) / 2)
  }
}
function smBoxDist(b, x, y) { // CSS px distance from a point to a box (0 inside)
  const dx = x < b.x0 ? b.x0 - x : x > b.x1 ? x - b.x1 : 0, dy = y < b.y0 ? b.y0 - y : y > b.y1 ? y - b.y1 : 0
  return Math.hypot(dx, dy)
}
function smPick(pi, items, x, y, sx, sy, cssW, cssH, cv) { // click -> {ii, col} text spot | {math, x, y, ii} | {img}
  const skip = new Set(), cands = []
  let maths = [], imgs = []
  try { maths = pvMathMatch().filter(m => m.page === pi) } catch (e) {}
  try { imgs = pvImgMatch().filter(b => b.page === pi) } catch (e) {}
  for (const m of maths) for (const it of m.line.items || []) skip.add(it)
  const rows = smRows(items, skip)
  for (const m of maths) {
    const L = m.line, box = { x0: L.x0, x1: L.x1, y0: L.y0, y1: L.y1 }
    for (const R of rows) if (!R.num && R.y1 >= L.y0 && R.y0 <= L.y1 && R.ii.every(ii => SM_EQNUM.test(String(items[ii].s).trim()))) { R.num = true; box.x0 = Math.min(box.x0, R.x0); box.x1 = Math.max(box.x1, R.x1) } // its number belongs to the formula
    cands.push({ math: m, real: box })
  }
  for (const b of imgs) cands.push({ img: b, real: { x0: b.x0, x1: b.x1, y0: b.y0, y1: b.y1 } })
  const vh = (items[0] && items[0].vh) || 1, band = v => v < vh * SM_MARGIN ? -1 : v > vh * (1 - SM_MARGIN) ? 1 : 0
  for (const R of rows) { // a running header or page number only takes clicks in its own margin: blank space below the last line stays in the text
    if (!R.num && (!band((R.y0 + R.y1) / 2) || band((R.y0 + R.y1) / 2) === band(y / sy))) cands.push({ row: R, real: { x0: R.x0, x1: R.x1, y0: R.y0, y1: R.y1 } })
  }
  smSpread(cands, items)
  const css = b => ({ x0: b.x0 * sx, x1: b.x1 * sx, y0: b.y0 * sy, y1: b.y1 * sy })
  for (const c of cands) { c.real = css(c.real); c.ext = css(c.ext) }
  items.forEach((it, ii) => { if (it.rot && String(it.s || '').trim()) cands.push({ rot: ii, d: Math.sqrt(pvItemDist(it, x, y, sx, sy)) }) }) // a turned run: distance in its own baseline frame
  let best = null, bd = Infinity, br = Infinity
  for (const c of cands) {
    const near = c.row ? SM_GRACE : 0, d = c.d ?? Math.max(0, smBoxDist(c.ext, x, y) - near), r = c.d ?? Math.max(0, smBoxDist(c.real, x, y) - near) + (c.row ? 0 : 0.01) // on (or right at) glyphs over a picture: the text wins
    if (d < bd - 1e-6 || (Math.abs(d - bd) <= 1e-6 && r < br)) { best = c; bd = d; br = r }
  }
  if (!best) return null
  if (best.img) return { img: best.img }
  if (best.rot != null) return { ii: best.rot, col: pvClickCol(items[best.rot], x, y, cssW, cssH, cv ? cv.width : cssW, cv) }
  if (best.math) {
    const L = best.math.line, own = (L.items || [])[0]
    return { math: best.math, x: Math.max(L.x0 * sx, Math.min(L.x1 * sx, x)), y: Math.max(L.y0 * sy, Math.min(L.y1 * sy, y)), ii: own ? items.indexOf(own) : -1, col: 0 }
  }
  const R = best.row, xs = x / sx, its = R.ii.map(ii => [ii, items[ii]])
  if (xs <= R.x0) { const [ii, it] = its[0]; return { ii, col: it.s.length - it.s.trimStart().length } }
  if (xs >= R.x1) { const [ii, it] = its[its.length - 1]; return { ii, col: it.s.trimEnd().length } }
  let pick = its[0], pd = Infinity
  for (const o of its) { const d = xs < o[1].x0 ? o[1].x0 - xs : xs > o[1].x0 + (o[1].w || 0) ? xs - o[1].x0 - (o[1].w || 0) : 0; if (d < pd) { pd = d; pick = o } }
  const [ii, it] = pick
  return { ii, col: pvClickCol(it, Math.max(it.x0 * sx, Math.min((it.x0 + (it.w || 0)) * sx, x)), it.y * sy, cssW, cssH, cv ? cv.width : cssW, cv) }
}
async function smGo(res) { // jump to {key, at}: switch to the file first when it is another tab
  const doc = docId, epoch = openN, key = res.key || ''
  if (key !== (activeFile || '')) {
    try { if (!await switchTab(key)) return false } catch (e) { return false }
    if (doc !== docId || epoch !== openN || (activeFile || '') !== key) return false // a tab clicked meanwhile owns the editor now
  }
  jumpPos(Math.max(0, Math.min(cm.state.doc.length, res.at)))
  return true
}
async function smClick(pi, items, x, y, sx, sy, cssW, cssH, cv) { // preview click -> editor; true when it moved
  const hit = smPick(pi, items, x, y, sx, sy, cssW, cssH, cv)
  if (!hit) return false
  if (hit.img) return pvJumpSrc(hit.img.src, 0)
  if (hit.math) { const mh = pvMathAt(pi, hit.x, hit.y, sx, sy); return (mh && await pvJumpMath(mh)) || pvJumpSrc(hit.math.src, 0) } // no glyph pair (a number, a gap): the formula itself
  if (hit.ii == null || hit.ii < 0) return false
  const M = smMap(), tk = smTokenAt(M, pi, hit.ii, hit.col), res = tk ? smResolve(M, tk.ti, tk.k) : null
  return res ? smGo(res) : false
}
function smHitAt(pos) { // cursor in the open tab -> {pi, it, items} of its word on paper (null: nothing printed for it)
  const M = smMap(), f = smFind(M, activeFile || '', pos)
  if (!f) return null
  const t = M.toks[f.ti], it = M.pages[t.pi][t.li[Math.min(f.k, t.li.length - 1)]]
  return { pi: t.pi, it, items: [it] }
}

// --- scroll link: a reader scroll in one pane moves the other in step, interpolated between anchored words ---
const SM_LINK_LINES = 60 // source lines searched up and down for an anchored neighbour
let smLinkMemo = null // { M, key, lines: Map line -> {pi, y} | null, pages: [] per page sorted anchors }
function smLinkData(M) {
  const key = activeFile || ''
  if (smLinkMemo && smLinkMemo.M === M && smLinkMemo.key === key) return smLinkMemo
  const si = M.srcs.findIndex(s => s.key === key), pages = M.pages.map(() => [])
  if (si >= 0) M.toks.forEach((t, ti) => {
    const o = M.own[ti]
    if (!o || o.si !== si || o.p !== 1) return // flow words of the open file: headers and footnotes sit out of order
    const it = M.pages[t.pi][t.li[0]]
    pages[t.pi].push({ y: it.y, pos: M.srcs[si].words[o.wi].raw, x0: it.x0, x1: it.x0 + (it.w || 0) })
  })
  for (const a of pages) a.sort((p, q) => p.y - q.y)
  return (smLinkMemo = { M, key, lines: new Map(), pages })
}
function smPageBox(pv, pi, pr) { // page -> its top in preview scroll coordinates and the CSS px per page unit
  const slot = pvSlots[pi], items = pvTexts[pi]
  if (!slot || !slot.isConnected) return null
  const r = slot.getBoundingClientRect(), vh = (items && items[0] && items[0].vh) || (+slot.dataset.w || 1) * (+slot.dataset.r || 1)
  return { top: pv.scrollTop + r.top - (pr || pv.getBoundingClientRect()).top, k: r.height / (vh || 1), vw: (items && items[0] && items[0].vw) || 0 }
}
function smPageAt(pv, y, pr) { // first page whose bottom lies below scroll coordinate y (binary search: a few layout reads per frame)
  let lo = 0, hi = pvSlots.length - 1
  while (lo < hi) {
    const mid = (lo + hi) >> 1, box = smPageBox(pv, mid, pr)
    if (box && box.top + (pvSlots[mid].getBoundingClientRect().height || 0) <= y) lo = mid + 1; else hi = mid
  }
  return lo
}
function smMapQuick() { // scroll frames: the map of this frame's paper and text without rescanning every source
  const m = smMemo, done = pvTextDone.filter(Boolean).length
  if (m && m.doc === cm.state.doc && m.active === (activeFile || '') && m.gen === pvMetaGen && m.done === done && m.seen > Date.now() - 500) return m.M
  const M = smMap()
  Object.assign(smMemo, { doc: cm.state.doc, active: activeFile || '', seen: Date.now() })
  return M
}
function smLineSpot(L, M, line) { // source line -> {pi, y} of its first word on paper (memo per map)
  if (L.lines.has(line)) return L.lines.get(line)
  const doc = cm.state.doc
  let spot = null
  if (line >= 1 && line <= doc.lines && doc.line(line).text.trim()) {
    const f = smFind(M, L.key, doc.line(line).from)
    if (f) { const t = M.toks[f.ti]; spot = { pi: t.pi, y: M.pages[t.pi][t.li[0]].y } }
  }
  L.lines.set(line, spot)
  return spot
}
function smScrollPv() { // editor middle -> preview middle (null: no anchor near, the caller falls back)
  const M = smMapQuick(), L = smLinkData(M), pv = $('preview'), sc = cm.scrollDOM, doc = cm.state.doc
  const mid = sc.scrollTop + sc.clientHeight / 2, at = cm.lineBlockAtHeight(mid), line = doc.lineAt(at.from).number
  let a = null, b = null
  for (let l = line; l >= Math.max(1, line - SM_LINK_LINES) && !a; l--) { const s = smLineSpot(L, M, l); if (s) a = { l, s } }
  for (let l = line + 1; l <= Math.min(doc.lines, line + SM_LINK_LINES) && !b; l++) { const s = smLineSpot(L, M, l); if (s) b = { l, s } }
  if (!a && !b) return null
  if ((!a || !b) && pvTextDone.some(d => !d)) return null // the other side may sit on a page that is still being indexed
  const pr = pv.getBoundingClientRect(), abs = s => { const box = smPageBox(pv, s.pi, pr); return box ? box.top + s.y * box.k : null }
  const top = l => { const blk = cm.lineBlockAt(doc.line(l).from); return blk.top + blk.height / 2 }
  const ya = a && abs(a.s), yb = b && abs(b.s)
  if (ya == null && yb == null) return null
  let y = ya != null ? ya : yb
  if (ya != null && yb != null && yb > ya) { const ta = top(a.l), tb = top(b.l); y = ya + Math.max(0, Math.min(1, (mid - ta) / Math.max(1, tb - ta))) * (yb - ya) }
  return y - pv.clientHeight / 2
}
function smScrollEd(off, share) { // preview reading point -> editor middle (null: no anchor near, the caller falls back); share: reading column as a share of the page width
  const M = smMapQuick(), L = smLinkData(M), pv = $('preview'), sc = cm.scrollDOM, pr = pv.getBoundingClientRect()
  const mid = pv.scrollTop + pv.clientHeight / 2 + (off || 0), here = smPageAt(pv, mid, pr)
  if (!pvTextDone[here]) return null // the page under the reading point is still being indexed: the page follow retries once it is
  let a = null, b = null // nearest anchors above and below the reading point, across page breaks
  for (let pi = Math.max(0, here - 3); pi <= Math.min(L.pages.length - 1, here + 3); pi++) {
    const list = L.pages[pi], box = list.length ? smPageBox(pv, pi, pr) : null
    if (!box) continue
    const rx = share != null && box.vw ? share * box.vw : null, w = box.vw * 0.04 // two columns: words of the reading column, a gutter's width of slack
    const col = rx != null ? list.filter(o => o.x0 - w <= rx && rx <= o.x1 + w) : []
    for (const o of col.length ? col : list) {
      const y = box.top + o.y * box.k
      if (y <= mid) { if (!a || y >= a.y) a = { y, pos: o.pos } } else if (!b || y < b.y) b = { y, pos: o.pos }
    }
  }
  if (!a && !b) return null
  const len = cm.state.doc.length, top = p => { const blk = cm.lineBlockAt(Math.min(p, len)); return blk.top + blk.height / 2 }
  let t = top((a || b).pos)
  if (a && b && b.y > a.y && b.pos >= a.pos) { const ta = top(a.pos), tb = top(b.pos); t = ta + (mid - a.y) / (b.y - a.y) * (tb - ta) } // source order against paper order (a float, the other column): hold the word above
  return t - sc.clientHeight / 2
}
