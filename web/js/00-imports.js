import * as Y from '/vendor/yjs-13.6.27-232b4982bc3f.js'
import { WebsocketProvider } from '/vendor/y-websocket-1.5.0-8a98fc0aad78.js'
import * as CMV from './vendor-cm.js?v=6' // bundled locally: single instance, no CDN risk
const { EditorView, minimalSetup, Compartment, EditorState, StateField, StateEffect, RangeSet, Prec, hoverTooltip, keymap, Decoration, WidgetType, lineNumbers, gutterLineClass, GutterMarker, autocompletion, startCompletion, acceptCompletion, currentCompletions, closeCompletion, moveCompletionSelection, closeBrackets, snippetCompletion, nextSnippetField, prevSnippetField, indentMore, indentLess, foldGutter, foldKeymap, bracketMatching, indentUnit, typst_lezer, typstBuiltinSignatures, typstGlobalCompletions, typstMathCompletions, typstParser, typstTags, syntaxHighlighting, HighlightStyle, tags, linter, lintGutter, setDiagnostics, forEachDiagnostic } = CMV // must match vendor build (cache-busted via ?v=6)
// self-hosted vendor bundle (see vendor/manifest.json): versions pinned, no SRI overhead
// TODO(modules/): split this inline script into modules/ (api.js, sidebar.js, comments.js, preview.js, dialogs.js)
//   once the backend refactor lands — kept inline + unminified for reviewability in this run.

if (window.pdfjsLib) pdfjsLib.GlobalWorkerOptions.workerSrc = '/vendor/pdf-worker-3.11.174-feabdf309770.min.js' // pinned as above
setTimeout(() => { try { if (window.pdfjsLib && !pdfjsLib.GlobalWorkerOptions.workerSrc) pdfjsLib.GlobalWorkerOptions.workerSrc = '/vendor/pdf-worker-3.11.174-feabdf309770.min.js' } catch (e) {} }, 2000) // defer race: set worker late if needed
const $ = id => document.getElementById(id)
let toastT = 0
let lastToastM = '', lastToastT = 0
const TOAST_DUP_MS = 2000 // same text within this window: show once (F24)
function toast(m, retry, label, ms) { if (!retry && m === lastToastM && Date.now() - lastToastT < TOAST_DUP_MS) return; lastToastM = m; lastToastT = Date.now(); let box = $('toast'); if (!box) { box = document.createElement('div'); box.id = 'toast'; document.body.appendChild(box) } box.setAttribute('role', retry ? 'alert' : 'status'); box.setAttribute('aria-live', retry ? 'assertive' : 'polite'); box.replaceChildren(); box.appendChild(document.createTextNode(m)); if (retry) { const b = document.createElement('button'); b.textContent = label || t('common.retry'); b.onclick = () => { box.style.display = 'none'; retry() }; box.appendChild(b) } box.style.opacity = '1'; box.style.display = 'block'; clearTimeout(toastT); toastT = setTimeout(() => { box.style.opacity = '0'; setTimeout(() => box.style.display = 'none', 400) }, ms || (retry ? 5000 : 3500)) }
const sleep = ms => new Promise(r => setTimeout(r, ms))
async function api(m, url, body, tries = 3) { // Error carries .status/.detail; GET auto-retries 503 with backoff (idempotent only, never 429: a limit hit must surface, not re-hit the bucket)
  let lastErr = null
  const n = m === 'GET' ? tries : 1
  if (m !== 'GET' && /\/files(\/|$)/.test(url)) filesDirty = true // any file write: next render refetches the list
  for (let a = 0; a < n; a++) {
    const r = await fetch(url, { method: m, headers: { 'Content-Type': 'application/json' }, body: body && JSON.stringify(body) })
    if (r.status === 204) return null
    if (r.status === 503 && a < n - 1) { lastErr = new Error(t('common.busyRetry')); lastErr.status = r.status; await sleep(500 * (a + 1)); continue }
    const txt = await r.text()
    let j = null; try { j = txt ? JSON.parse(txt) : null } catch (e) { j = null } // HTML error page: no crash
    if (!r.ok) { const e = new Error((j && j.detail) || r.statusText || ('HTTP ' + r.status)); e.status = r.status; e.detail = (j && j.detail) || ''; throw e }
    return j
  }
  throw lastErr || new Error(t('common.requestFailed'))
}
function lsSet(k, v) { // quota: drop oldest pending stash, retry once, else smaller stash + toast (never silent)
  try { localStorage.setItem(k, v); return true }
  catch (e) {
    try {
      const olds = []
      for (let i = 0; i < localStorage.length; i++) { const kk = localStorage.key(i); if (kk && kk.startsWith('typst-pending-')) olds.push(kk) }
      olds.slice(0, Math.max(1, olds.length - 1)).forEach(kk => localStorage.removeItem(kk)) // keep newest draft only
      localStorage.setItem(k, v); return true
    } catch (e2) {}
    try { toast(t('common.storageFull')) } catch (_) {}
    return false
  }
}

let lastC = '' // last comment state, poll renders only on change
let user = '', docId = '', docRole = '', ydoc = null, prov = null, ytext = null, shadow = '', saveT = 0, tplT = 0 // separate timers: doc vs template save (no race)
let filesDirty = true, filesAt = 0, shadowSig = '' // file list cache (no GET per keystroke) + mapped shadow signature (no remap per keystroke)
const FILES_TTL = 15000 // collaborators' uploads show up within this window
const SAVE_MS = 2500, RENDER_MS = 300, POLL_MS = 5000, SYNC_MS = 150, CLICK_PX = 130, SYNC_PX = 40 // debounce/intervals + click radius (canvas px) + scroll quiet (px)
const SEARCH_MS = 350, DIFF_MAX = 400, DIFF_OUT = 120 // search debounce, diff line caps
function clampSplit(w) { return Math.max(SPLIT_MIN, Math.min(SPLIT_MAX, w)) } // fn not const: top init runs first (TDZ fix)
const QUOTE_MAX = 120, AV_SIZE = 64 // comment quote, avatar px
const SPLIT_MIN = 25, SPLIT_MAX = 85 // editor width in %
const ED_MIN = 10, ED_MAX = 24, ED_STEP = 1 // editor font
const PV_MIN = 30, PV_MAX = 400, PV_STEP = 10 // preview zoom (400: zoom may exceed container, preview scrolls)
const SIDE_MIN = 200, SIDE_MAX = 420 // sidebar width in px
let edSize = 14, pvZoom = 110 // editor font + preview zoom
let tabW = 2 // F25: tab width (persisted below); wrap always on, no compile-delay option
try { const e = +localStorage.getItem('typst_ed'); if (e >= ED_MIN && e <= ED_MAX) edSize = e } catch (err) {}
try { const z = +localStorage.getItem('typst_pv'); if (z >= PV_MIN && z <= PV_MAX) pvZoom = z } catch (err) {}
try { const t = +localStorage.getItem('typst_tab'); if ([2, 4, 8].includes(t)) tabW = t } catch (err) {}
const saveSet = () => { lsSet('typst_ed', edSize); lsSet('typst_pv', pvZoom) }

