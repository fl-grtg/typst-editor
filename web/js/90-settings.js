// --- Settings: click on name (font/zoom, profile, password, account) ---
$('who').onclick = e => {
  e.stopPropagation()
  if (showPop('setPop')) { setMsg = ''; apiKeys = null; renderSettings() }
}
kb($('who'), () => $('who').click())
let setMsg = '' // settings error inline not browser alert
let apiKeys = null, apiKeysLoading = false, lastKeySecret = '', lastKeyName = '', lastKeyId = ''
const AGENT_PROMPT = 'Install the Typst Editor skill from https://raw.githubusercontent.com/fl-grtg/typst-editor/main/skills/typst-editor/SKILL.md and follow its section 0 to connect to my Typst server. Ask me for server URL and API key if missing.'
function loadKeys() {
  if (apiKeysLoading) return; apiKeysLoading = true
  api('GET', '/api/keys').then(d => { apiKeys = d.keys || [] })
    .catch(e => { setMsg = e.message; apiKeys = [] }).finally(() => { apiKeysLoading = false; renderSettings() })
}
const shortD = s => { try { return s ? String(s).slice(0, 10) : t('settings.never') } catch (e) { return t('settings.never') } }
function copyTxt(txt, inp) {
  const fb = () => {
    const f = inp || document.createElement('textarea')
    if (!inp) { f.value = txt; f.style.position = 'fixed'; f.style.opacity = '0'; document.body.appendChild(f) }
    f.select(); try { document.execCommand('copy'); toast(t('common.copied')) } catch (e) {}
    if (!inp) f.remove()
  }
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(txt).then(() => toast(t('common.copied'))).catch(fb)
  else fb()
}
function renderSettings() {
  const p = $('setPop'); p.replaceChildren()
  const sec = (...kids) => { const d = el('div', 'sec'); kids.forEach(k => d.appendChild(k)); return d }
  const grp = (title, ...secs) => { const w = el('div', 'grp'); w.appendChild(el('h4', null, title)); secs.forEach(s => w.appendChild(s)); return w }
  const top = el('div', 'sTop')
  const close = icoBtn(null, ICO_X); close.title = t('common.close'); close.setAttribute('aria-label', close.title)
  close.onclick = e => { e.stopPropagation(); lastKeySecret = ''; lastKeyName = ''; lastKeyId = ''; p.style.display = 'none' }
  top.append(el('b', null, t('settings.title')), close); p.appendChild(top)
  if (setMsg) { p.appendChild(el('div', 'serr', setMsg)); setMsg = '' }
  const grid = el('div', 'setGrid'), colL = el('div', 'setCol'), colR = el('div', 'setCol')
  grid.append(colL, colR); p.appendChild(grid) // deterministic 2-col grid: left = profile, right = backup + keys
  const fr = el('div', 'row'); fr.append(el('label', null, t('settings.font')))
  const fm = el('button', 'step', 'A−'); fm.title = t('settings.fontMinus'); fm.setAttribute('aria-label', fm.title)
  fm.onclick = e => { e.stopPropagation(); stepEd(-ED_STEP); renderSettings() }
  fr.append(fm, el('span', 'val', edSize + 'px'))
  const fp = el('button', 'step', 'A+'); fp.title = t('settings.fontPlus'); fp.setAttribute('aria-label', fp.title)
  fp.onclick = e => { e.stopPropagation(); stepEd(ED_STEP); renderSettings() }
  fr.appendChild(fp)
  const zr = el('div', 'row'); zr.append(el('label', null, t('settings.zoom')))
  const zm = el('button', 'step', '−'); zm.title = t('settings.zoomMinus'); zm.setAttribute('aria-label', zm.title)
  zm.onclick = e => { e.stopPropagation(); stepPv(-PV_STEP); renderSettings() }
  zr.append(zm, el('span', 'val', pvZoom + ' %'))
  const zp = el('button', 'step', '+'); zp.title = t('settings.zoomPlus'); zp.setAttribute('aria-label', zp.title)
  zp.onclick = e => { e.stopPropagation(); stepPv(PV_STEP); renderSettings() }
  zr.appendChild(zp)
  colL.appendChild(grp(t('settings.appearance'), sec(fr, zr)))
  const tr = el('div', 'row'); tr.append(el('label', null, t('settings.tabs')))
  const ts = el('select'); ts.setAttribute('aria-label', t('settings.tabWidth'))
  ;[2, 4, 8].forEach(n => { const o = el('option', null, String(n)); o.value = String(n); if (n === tabW) o.selected = true; ts.appendChild(o) })
  ts.onchange = () => { tabW = +ts.value || 2; lsSet('typst_tab', tabW); cm.dispatch({ effects: tabComp.reconfigure([EditorState.tabSize.of(tabW), indentUnit.of(' '.repeat(tabW))]) }); renderSettings() }
  tr.append(ts, el('span', 'val', t('settings.tabUnit', { n: tabW })))
  colL.appendChild(grp(t('settings.editorGroup'), sec(tr))) // wrap always on, sync lives on the preview button, no compile-delay option
  const ar = el('div', 'row avatarRow')
  const im = el('img', 'av'); im.alt = t('settings.avatarAlt')
  if (avatarV) im.src = `/api/avatar/${encodeURIComponent(user)}?v=${avatarV}`; else { im.style.display = 'none'; const fb = el('span', 'avFallback'); fb.textContent = (user || '?').slice(0, 2).toUpperCase(); ar.appendChild(fb) }
  im.onerror = () => im.style.display = 'none'
  const pick = el('button', null, t('settings.choose')); pick.onclick = () => $('avPick').click()
  const rm = el('button', 'btnSecondary', t('settings.remove'))
  rm.onclick = () => api('DELETE', '/api/me/avatar')
    .then(() => { avatarV++; paintMe(); renderPeers(); renderSettings() })
    .catch(e => { setMsg = e.message; renderSettings() })
  ar.append(im, pick, rm); colL.appendChild(grp(t('settings.avatar'), sec(ar)))
  const nr = el('div', 'row')
  const nn = el('input'); nn.placeholder = t('settings.newName'); nn.setAttribute('aria-label', t('settings.newName')); nn.value = user
  const npw = el('input'); npw.type = 'password'; npw.placeholder = t('settings.pwGroup'); npw.setAttribute('aria-label', t('settings.pwForName'))
  const nok = el('button', null, t('common.ok'))
  nok.onclick = () => { if (nok.disabled) return; if (!nn.value.trim() || !npw.value) { setMsg = t('settings.needNamePw'); renderSettings(); return } nok.disabled = true; api('POST', '/api/me/name',
    { name: nn.value.trim(), password: npw.value })
    .then(d => { user = d.user; paintMe(); sidebar(); renderSettings() })
    .catch(e => { setMsg = e.message; renderSettings() }).finally(() => nok.disabled = false) }
  nr.append(nn, npw, nok); colL.appendChild(grp(t('settings.nameGroup'), sec(nr)))
  const pr = el('div', 'row')
  const po = el('input'); po.type = 'password'; po.placeholder = t('settings.oldPw'); po.setAttribute('aria-label', t('settings.oldPw'))
  const pn = el('input'); pn.type = 'password'; pn.placeholder = t('settings.newPw'); pn.setAttribute('aria-label', t('settings.newPw'))
  const pok = el('button', null, t('common.ok'))
  pok.onclick = () => { if (pok.disabled) return; if (!po.value || !pn.value) { setMsg = t('settings.needOldNew'); renderSettings(); return } pok.disabled = true; api('POST', '/api/me/password', { old: po.value, new: pn.value })
    .then(() => { po.value = pn.value = ''; toast(t('settings.pwChanged')) })
    .catch(e => { setMsg = e.message; renderSettings() }).finally(() => pok.disabled = false) }
  pr.append(po, pn, pok); colL.appendChild(grp(t('settings.pwGroup'), sec(pr)))
  const bk = el('div', 'row')
  const bb = el('button', 'btnSecondary', t('settings.backupBtn'))
  bb.title = t('settings.backupTitle')
  bb.onclick = () => { const a = document.createElement('a'); a.href = '/api/export.zip'; a.click() }
  bk.appendChild(bb); colR.appendChild(grp(t('settings.backup'), sec(bk)))
  const agCp = icoBtn(null, ICO_DUP); agCp.title = t('settings.agentCopy'); agCp.setAttribute('aria-label', t('settings.agentCopy'))
  agCp.onclick = () => copyTxt(AGENT_PROMPT)
  const agRow = el('div', 'row'); agRow.append(el('span', null, t('settings.agentHint')), agCp)
  colR.appendChild(grp(t('settings.agent'), sec(agRow)))
  const keySecs = []
  const ksec = (...kids) => { const d = sec(...kids); d.style.padding = '6px 10px 8px'; d.style.marginBottom = '6px'
    kids.forEach(k => { if (k.classList && k.classList.contains('row')) k.style.marginTop = '6px' }); return d }
  if (lastKeySecret) {
    const si = el('input'); si.readOnly = true; si.value = lastKeySecret; si.setAttribute('aria-label', t('settings.keyOnceAria'))
    const cp = el('button', null, t('common.copy')); cp.onclick = () => copyTxt(lastKeySecret, si)
    const cx = el('button', 'btnSecondary', t('common.close')); cx.onclick = e => { e.stopPropagation(); lastKeySecret = ''; lastKeyName = ''; lastKeyId = ''; renderSettings() }
    const sr = el('div', 'row wrap'); sr.append(si, cp, cx)
    keySecs.push(ksec(el('div', null, t('settings.shownOnce', { name: lastKeyName || t('settings.keys') })), sr))
  }
  const kn = el('input'); kn.placeholder = t('settings.keyName'); kn.maxLength = 40; kn.setAttribute('aria-label', t('settings.keyName'))
  const rs = el('select'); rs.setAttribute('aria-label', t('common.roleAria'))
  ;[['editor', t('common.roleEditor')], ['reviewer', t('common.roleReader')]].forEach(([v, lab]) => { const o = el('option', null, lab); o.value = v; rs.appendChild(o) })
  const es = el('select'); es.setAttribute('aria-label', t('settings.expiry'))
  ;[[t('settings.never'), ''], [t('settings.expDays', { n: 30 }), '30'], [t('settings.expDays', { n: 90 }), '90'], [t('settings.expDays', { n: 365 }), '365']].forEach(([label, v]) => { const o = el('option', null, label); o.value = v; es.appendChild(o) })
  const cb = el('button', null, t('common.create'))
  cb.onclick = e => {
    e.stopPropagation() // sync renderSettings below detaches e.target: without this the document outside-click closer hides setPop
    if (cb.disabled) return
    if (!kn.value.trim()) { setMsg = t('settings.needKeyName'); renderSettings(); return }
    cb.disabled = true
    api('POST', '/api/keys', { name: kn.value.trim(), role: rs.value, expires_in_days: es.value ? +es.value : null })
      .then(d => { // no refetch: one POST per create, list updates locally (was POST+GET, 2 keys-bucket hits)
        lastKeySecret = d.key; lastKeyName = d.name || ''; lastKeyId = d.id || ''
        apiKeys = [...(apiKeys || []), { id: d.id, name: d.name, prefix: d.prefix, role: d.role, expires_at: d.expires_at || '', last_used: '', created_at: '' }]
      })
      .catch(e => { setMsg = e.message }).finally(() => renderSettings())
  }
  const cr = el('div', 'row wrap'); cr.append(kn, rs, es, cb); keySecs.push(ksec(cr))
  if (apiKeys === null) {
    keySecs.push(ksec(el('div', null, apiKeysLoading ? t('settings.loading') : '')))
    if (!apiKeysLoading) loadKeys()
  } else if (!apiKeys.length) keySecs.push(ksec(el('div', null, t('settings.noKeys'))))
  else {
    const rows = apiKeys.map(k => {
      const r = el('div', 'row wrap')
      r.style.flexWrap = 'nowrap'; r.style.alignItems = 'center' // button centered across both text lines
      const left = el('div')
      left.style.flex = '1'; left.style.minWidth = '0'; left.style.display = 'flex'; left.style.flexDirection = 'column'
      const nm = el('span', null, k.name)
      nm.style.fontWeight = '650'; nm.style.fontSize = '13.5px'
      nm.style.overflow = 'hidden'; nm.style.textOverflow = 'ellipsis'; nm.style.whiteSpace = 'nowrap'
      nm.title = k.name
      const rb = el('button', 'btnSecondary', t('settings.revoke'))
      rb.style.flex = 'none'
      rb.onclick = () => {
        if (rb.disabled) return; rb.disabled = true
        api('DELETE', '/api/keys/' + encodeURIComponent(k.id))
          .then(() => { apiKeys = (apiKeys || []).filter(x => x.id !== k.id)
            if (lastKeySecret && (!lastKeyId || lastKeyId === k.id)) { lastKeySecret = ''; lastKeyName = ''; lastKeyId = '' } }) // revoked secret is dead: drop the shown-once box
          .catch(e => { setMsg = e.message }).finally(() => renderSettings())
      }
      const sub = el('div', 'val')
      sub.style.display = 'flex'; sub.style.flexWrap = 'wrap'; sub.style.gap = '6px'; sub.style.alignItems = 'center'
      sub.style.fontSize = '12px'; sub.style.minWidth = '0'; sub.style.overflowWrap = 'anywhere'; sub.style.textAlign = 'left'
      const pc = el('code', null, k.prefix || '')
      pc.style.fontSize = '11.5px'; pc.style.overflowWrap = 'anywhere'; pc.style.minWidth = '0'
      const eS = el('span', 'val', t('settings.expires', { date: shortD(k.expires_at) })); eS.title = k.expires_at || t('settings.never')
      eS.style.fontSize = '12px'
      sub.append(pc, el('span', null, k.role), eS)
      left.append(nm, sub)
      r.append(left, rb)
      return r
    })
    keySecs.push(ksec(...rows))
  }
  colR.appendChild(grp(t('settings.keys'), ...keySecs)) // secret + create + list in one group: never fragmented
  const scRow = el('div', 'row')
  const scBtn = el('button', null, t('settings.scShow'))
  scBtn.id = 'scOpen'; scBtn.style.flex = '1'
  scBtn.onclick = () => openShortcuts() // Help keeps opening the overview too (moves here only later)
  scRow.appendChild(scBtn)
  colR.appendChild(grp(t('settings.scGroup'), sec(scRow), spellSettingsSec()))
  const dr = el('div', 'row')
  const dpw = el('input'); dpw.type = 'password'; dpw.placeholder = t('settings.pwGroup'); dpw.setAttribute('aria-label', t('settings.pwForDel'))
  const db = el('button', 'btnDanger', t('common.delete'))
  db.onclick = async () => {
    if (db.disabled) return
    if (!dpw.value) { setMsg = t('settings.needPwDel'); renderSettings(); return }
    if (!await ask(t('settings.delAccount'), { noInput: true, ok: t('common.delete'), danger: true })) return
    if (!await ask(t('settings.delSure'), { ph: 'DELETE' }).then(v => v === 'DELETE')) return
    db.disabled = true
    api('POST', '/api/me/delete', { password: dpw.value })
      .then(() => { location.reload() })
      .catch(e => { setMsg = e.message; renderSettings() })
  }
  dr.append(dpw, db); colL.appendChild(grp(t('settings.account'), sec(dr)))
}
$('avPick').onchange = () => { // square, AV_SIZE, center
  const f = $('avPick').files[0]; $('avPick').value = ''
  if (!f) return
  const im = new Image()
  im.onload = () => {
    const c = document.createElement('canvas'); c.width = c.height = AV_SIZE
    const s = Math.min(im.width, im.height)
    c.getContext('2d').drawImage(im, (im.width - s) / 2, (im.height - s) / 2, s, s, 0, 0, AV_SIZE, AV_SIZE)
    api('POST', '/api/me/avatar', { img: c.toDataURL('image/png') })
      .then(() => { avatarV++; paintMe(); renderPeers(); renderSettings() })
      .catch(e => { setMsg = e.message; renderSettings() })
    URL.revokeObjectURL(im.src)
  }
  im.onerror = () => URL.revokeObjectURL(im.src)
  im.src = URL.createObjectURL(f)
}
// drag pane border (browser remembers pos)
function updSplitAria() { try { $('split').setAttribute('aria-valuenow', Math.round(parseFloat($('leftCol').style.width) || 50)) } catch (e) {} }
function updSideAria() { try { $('sideSplit').setAttribute('aria-valuenow', Math.round(sideEl.getBoundingClientRect().width)) } catch (e) {} }
function updVsplitAria() { try { $('vsplit').setAttribute('aria-valuenow', Math.round($('leftCol').getBoundingClientRect().height)) } catch (e) {} }
try { const w = +localStorage.getItem('typst_split'); if (w >= SPLIT_MIN && w <= SPLIT_MAX) $('leftCol').style.width = clampSplit(w) + '%' } catch (e) {}
$('split').addEventListener('mousedown', e => {
  e.preventDefault()
  const r0 = $('mid').getBoundingClientRect(), x0 = e.clientX, w0 = $('leftCol').getBoundingClientRect().width
  $('split').classList.add('drag')
  const mv = ev => {
    $('leftCol').style.width = clampSplit((w0 + ev.clientX - x0) / r0.width * 100) + '%'
    updSplitAria()
  }
  const up = () => {
    removeEventListener('mousemove', mv); removeEventListener('mouseup', up)
    $('split').classList.remove('drag')
    lsSet('typst_split', parseFloat($('leftCol').style.width))
  }
  addEventListener('mousemove', mv); addEventListener('mouseup', up)
})
$('split').addEventListener('pointerdown', e => {
  if (e.pointerType === 'mouse') return
  $('split').dispatchEvent(new MouseEvent('mousedown', { clientX: e.clientX }))
})
$('navToggle').onclick = () => {
  document.body.classList.toggle('noside'); updScrim()
  const open = !document.body.classList.contains('noside')
  $('navToggle').setAttribute('aria-pressed', String(open)) // pressed = sidebar open, not hidden
  $('navToggle').setAttribute('aria-expanded', String(open)) // disclose pattern for SR
  if (open && matchMedia('(max-width:720px)').matches) { // drawer opened: focus first control
    const f = $('side').querySelector('input,button')
    if (f) setTimeout(() => { try { f.focus() } catch (e) {} }, 60)
  }
}
function updScrim() {
  const mob = matchMedia('(max-width:720px)').matches
  $('scrim').style.display = mob && !document.body.classList.contains('noside') ? '' : 'none'
}
$('scrim').onclick = () => { document.body.classList.add('noside'); updScrim(); $('navToggle').setAttribute('aria-pressed', 'false'); $('navToggle').setAttribute('aria-expanded', 'false'); $('navToggle').focus() } // drawer closed: focus back to toggle
function autoCloseDrawer() { if (matchMedia('(max-width:720px)').matches) { document.body.classList.add('noside'); updScrim() } }
const sideEl = $('side') // drag sidebar width, 150-420px
try { const sw = +localStorage.getItem('typst_side'); if (sw >= SIDE_MIN && sw <= SIDE_MAX) sideEl.style.width = sw + 'px' } catch (e) {}
$('sideSplit').addEventListener('mousedown', e => {
  e.preventDefault()
  document.body.classList.add('sideDrag')
  $('sideSplit').classList.add('drag')
  const x0 = e.clientX, w0 = sideEl.getBoundingClientRect().width
  const mv = ev => { sideEl.style.width = Math.max(SIDE_MIN, Math.min(SIDE_MAX, w0 + ev.clientX - x0)) + 'px'; updSideAria() }
  const up = () => {
    removeEventListener('mousemove', mv); removeEventListener('mouseup', up)
    $('sideSplit').classList.remove('drag')
    document.body.classList.remove('sideDrag')
    lsSet('typst_side', parseFloat(sideEl.style.width))
  }
  addEventListener('mousemove', mv); addEventListener('mouseup', up)
})
function vStart(y0) { // mobile: drag editor height (mouse + touch)
  const r = $('mid').getBoundingClientRect(), h0 = $('leftCol').getBoundingClientRect().height
  const set = dy => {
    $('leftCol').style.flex = 'none'
    $('leftCol').style.height = Math.max(120, Math.min(r.height - 120, h0 + dy)) + 'px'
    updVsplitAria()
  }
  const mm = e => set(e.clientY - y0), tm = e => set(e.touches[0].clientY - y0)
  const up = () => {
    removeEventListener('mousemove', mm); removeEventListener('mouseup', up)
    removeEventListener('touchmove', tm); removeEventListener('touchend', up)
  }
  addEventListener('mousemove', mm); addEventListener('mouseup', up)
  addEventListener('touchmove', tm, { passive: true }); addEventListener('touchend', up)
}
$('vsplit').addEventListener('mousedown', e => { e.preventDefault(); vStart(e.clientY) })
$('vsplit').addEventListener('touchstart', e => vStart(e.touches[0].clientY), { passive: true })
kb($('sideSplit'), () => { document.body.classList.toggle('noside'); updScrim() }) // keyboard: like menu
$('sideSplit').addEventListener('keydown', e => { // arrows: resize sidebar width
  const cur = Math.round(sideEl.getBoundingClientRect().width)
  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
    e.preventDefault()
    sideEl.style.width = Math.max(SIDE_MIN, Math.min(SIDE_MAX, cur + (e.key === 'ArrowRight' ? 10 : -10))) + 'px'
    updSideAria()
    lsSet('typst_side', parseFloat(sideEl.style.width))
  }
})
kb($('split'), () => { $('leftCol').style.width = '50%'; updSplitAria(); lsSet('typst_split', 50) }) // keyboard: reset width
$('split').addEventListener('keydown', e => {
  const cur = parseFloat($('leftCol').style.width) || 50
  if (e.key === 'ArrowLeft') { $('leftCol').style.width = clampSplit(cur - 2) + '%'; updSplitAria(); lsSet('typst_split', parseFloat($('leftCol').style.width)); e.preventDefault() }
  if (e.key === 'ArrowRight') { $('leftCol').style.width = clampSplit(cur + 2) + '%'; updSplitAria(); lsSet('typst_split', parseFloat($('leftCol').style.width)); e.preventDefault() }
})
kb($('vsplit'), () => { $('leftCol').style.height = ''; $('leftCol').style.flex = ''; updVsplitAria() }) // keyboard: reset height
$('vsplit').addEventListener('keydown', e => { // arrows: resize editor height
  if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return
  e.preventDefault()
  const r = $('mid').getBoundingClientRect(), h = $('leftCol').getBoundingClientRect().height
  $('leftCol').style.flex = 'none'
  $('leftCol').style.height = Math.max(120, Math.min(r.height - 120, h + (e.key === 'ArrowDown' ? 20 : -20))) + 'px'
  updVsplitAria()
})
matchMedia('(max-width:720px)').addEventListener('change', m => { // back on desktop: clear fixed height
  if (!m.matches) { $('leftCol').style.height = ''; $('leftCol').style.flex = ''; document.body.classList.remove('noside') }
  else document.body.classList.add('noside')
  updScrim()
})
function setView(m) { // 3-way segment: editor | split | read (not 1 read-mode button)
  document.body.classList.toggle('read', m === 'read')
  document.body.classList.toggle('editonly', m === 'editor')
  for (const [id, on] of [['vEdit', m === 'editor'], ['vSplit', m === 'split'], ['vRead', m === 'read']]) {
    $(id).classList.toggle('on', on)
    $(id).setAttribute('aria-pressed', on)
  }
  $('leftCol').style.height = ''; $('leftCol').style.flex = '' // mobile drag height must not survive view switch
  updVsplitAria()
  if (popAnchor != null) movePop()
}
$('vEdit').onclick = () => setView('editor')
$('vSplit').onclick = () => setView('split')
$('vRead').onclick = () => setView('read')
// editor font + preview zoom (edSize/pvZoom declared above)
function stepPv(d) { pvZoom = Math.max(PV_MIN, Math.min(PV_MAX, pvZoom + d)); applyPv(); saveSet() }
function stepEd(d) { edSize = Math.max(ED_MIN, Math.min(ED_MAX, edSize + d)); applyEd(); saveSet() }
function applyEd() {
  const lh = Math.round(edSize * 1.5)
  $('cmWrap').style.setProperty('--ed', edSize + 'px')
  $('cmWrap').style.setProperty('--lh', lh + 'px')
  $('editWrap').style.setProperty('--lh', lh + 'px')
  if (popAnchor != null) movePop()
}
function applyPv() {
  const z = $('zoomV'); if (z) z.textContent = pvZoom + '%'
  document.querySelectorAll('#preview canvas').forEach(sizeCanvas)
}
let syncOn = true, syncT = 0, syncPage = 0, pvT = 0 // click sync editor<->preview, last hit page
try { const s = localStorage.getItem('typst_sync'); if (s === '0' || s === '1') syncOn = s === '1' } catch (e) {} // F25: follow persisted (string compare: +null === 0 would flip the default)
function applySyncBtn() { const b = $('syncBtn'); if (!b) return; b.classList.toggle('on', syncOn); b.setAttribute('aria-pressed', syncOn) } // F25: button mirrors persisted state
function queueSyncPv() { clearTimeout(syncT); syncT = setTimeout(syncToPv, SYNC_MS) }
function syncToPv() { // editor -> preview: page with most line words, hit centered
  if (!syncOn || !docId || tplName || activeFile || Date.now() - pvT < 1000) return // preview click: paper stays put
  const pv = $('preview')
  if (!pv.scrollHeight || document.body.classList.contains('editonly')) return
  const total = cm.state.doc.lines || 1
  const line = cm.state.doc.lineAt(cm.state.selection.main.head).number
  // normalize line: trim, strip markup roughly, count long words only
  const ank = cm.state.doc.line(line).text.trim().replace(/^[=+\-*#>]+/, '').replace(/[#*`_$[\](){}<>\/\\|=]+/g, ' ').replace(/\s+/g, ' ').trim().toLowerCase()
  const words = [...new Set(ank.split(' ').filter(w => w.length >= 4))].slice(0, 6)
  const n = pvTexts.length
  if (words.length && n) {
    let bi = -1, bs = 0 // best page: most hits, tie stays on syncPage
    for (let pi = 0; pi < n; pi++) {
      const items = pvTexts[pi] || []
      let s = 0
      for (const w of words) for (const it of items) {
        if (it.s && it.s.toLowerCase().includes(w)) { s++; break }
      }
      if (s > bs || (s === bs && pi === syncPage)) { bs = s; bi = pi }
    }
    if (bi >= 0 && bs > 0) { // min one word: else fallback (no random jump)
      const items = pvTexts[bi] || []
      const long = words.slice().sort((a, b) => b.length - a.length)[0]
      for (const it of items) {
        if (it.s && it.s.toLowerCase().includes(long)) {
          const cv = pv.querySelectorAll('canvas')[bi]
          if (!cv) break
          const pr = pv.getBoundingClientRect(), cr = cv.getBoundingClientRect()
          const want = pv.scrollTop + (cr.top - pr.top) + it.y * (cr.width / cv.width) - pv.clientHeight / 2
          syncPage = bi
          if (Math.abs(want - pv.scrollTop) > SYNC_PX) pv.scrollTop = want // quiet: no flicker
          return
        }
      }
    }
  }
  const want = (line - 1) / total * (pv.scrollHeight - pv.clientHeight) // fallback: old ratio logic
  if (Math.abs(want - pv.scrollTop) > SYNC_PX) pv.scrollTop = want
}
function locateNear(t, s, hint) { // shortest hit near hint line (short cell texts too)
  s = (s || '').trim()
  if (s.length < 2) return -1
  const hp = posOfLine(t, hint)
  let best = -1, bd = 1e12, p = -1, n = 0
  while ((p = t.indexOf(s, p + 1)) >= 0 && n++ < 50) {
    const dd = Math.abs(p - hp)
    if (dd < bd) { bd = dd; best = p }
  }
  return best
}
function jumpPos(pos) { // editor jump to screen center (preview does not follow)
  pvT = Date.now()
  cm.dispatch({ selection: { anchor: pos }, effects: EditorView.scrollIntoView(pos, { y: 'center' }) })
  cm.focus()
}
$('preview').addEventListener('click', e => { // preview -> editor: text anchors first (tables!), else ratio
  if (!syncOn || !docId || tplName || activeFile) return
  const pv = $('preview')
  const cv = e.target.closest ? e.target.closest('canvas') : null
  if (cv && pvTexts.length) {
    const pi = [...pv.querySelectorAll('canvas')].indexOf(cv) // count canvas only, ignore .empty divs
    const items = pvTexts[pi] || []
    const r = cv.getBoundingClientRect(), sx = cv.width / r.width, sy = cv.height / r.height // canvas px: backing matches pvTexts
    const x = (e.clientX - r.left) * sx, y = (e.clientY - r.top) * sy
    let best = null, bd = CLICK_PX * CLICK_PX
    for (const it of items) {
      if (!it.s.trim()) continue
      const dx = it.x - x, dy = it.y - y, dd = dx * dx + dy * dy
      if (dd < bd) { bd = dd; best = it }
    }
    if (best) {
      const total = cm.state.doc.lines || 1
      let all = 0 // hint from text volume (not click height): hit ratio * lines
      for (const arr of pvTexts) all += arr.length
      let before = 0
      for (let k = 0; k < pi; k++) before += (pvTexts[k] || []).length
      const hint = Math.max(1, Math.min(total, Math.round((before + items.indexOf(best)) / Math.max(1, all) * total) + 1))
      const at = locateNear(getT(), best.s, hint)
      if (at >= 0) {
        const um = getT().slice(Math.max(0, at - 80), at + 80) // verify hit: context must contain click word
        const w = (best.s.trim().split(/\s+/).sort((a, b) => b.length - a.length)[0] || '')
        if (w.length < 4 || um.includes(w) || um.includes(best.s.trim())) { syncPage = pi; jumpPos(at); return }
      }
    }
    syncPage = pi // even without hit: next sync starts on click page
  }
  const r = pv.getBoundingClientRect() // fallback: ratio (images, margins, formulas without text)
  const ratio = Math.max(0, Math.min(1, (e.clientY - r.top + pv.scrollTop) / pv.scrollHeight))
  const lines = getT().split('\n'), total = lines.length || 1
  let line = Math.max(1, Math.min(total, Math.round(ratio * total) + 1))
  while (line > 1 && !lines[line - 1].trim()) line-- // snap to paragraph start
  jumpPos(posOfLine(getT(), line))
})
$('syncBtn').onclick = () => { syncOn = !syncOn; lsSet('typst_sync', syncOn ? 1 : 0); applySyncBtn(); try { updPos() } catch (e) {} }
applySyncBtn() // F25: persisted follow state on boot
try { updPos() } catch (e) {} // F24: status filled before first keystroke
function fitPv() { // fit paper exactly to preview width, centered via margin
  const c = document.querySelector('#preview canvas')
  const avail = $('preview').clientWidth - 32
  if (c && avail > 0) {
    pvZoom = Math.max(PV_MIN, Math.min(PV_MAX, Math.round(avail / (c.width / 2) * 100)))
    applyPv(); saveSet()
  }
}
function sizeCanvas(c) { // CSS width from zoom only, never touch backing (canvas.width)
  c.style.width = (c.width / 2 * pvZoom / 100) + 'px'
  c.style.maxWidth = document.body.classList.contains('read') ? (8.2 * pvZoom) + 'px' : 'none' // none: zoom may exceed container, preview scrolls
  c.style.height = 'auto'
}
$('fMinus').onclick = () => stepEd(-ED_STEP)
$('fPlus').onclick = () => stepEd(ED_STEP)
$('zMinus').onclick = () => stepPv(-PV_STEP)
$('zPlus').onclick = () => stepPv(PV_STEP)
$('fitBtn').onclick = fitPv
applyEd() // apply saved font at once
applyPv()
updExports()
closeView() // boot with no doc: onboarding card, no blobs, no comment button, read-only
try { if (matchMedia('(max-width:720px)').matches) document.body.classList.add('noside') } catch (e) {} // mobile: sidebar closed
updScrim()
