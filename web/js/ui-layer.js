/* UI layer: menubar, export menu, rail. Pure proxies to existing controls – no app logic lives here. */
(function () {
  'use strict'
  function t(k, p) { return window.t ? window.t(k, p) : String(k).split('.').pop() } // module (05-i18n.js) owns t(); this classic script only delegates (labels render on click, after the module ran)
  var $ = function (id) { return document.getElementById(id) }
  var menu = $('menu'), submenu = $('submenu'), body = document.body
  var mac = /Mac|iPhone|iPad/.test(navigator.platform || '')
  var M = mac ? '\u2318' : 'Ctrl+'
  var openFor = null, items = [], idx = -1, openAlign = 'left', menuAction = false
  var subFor = null, subItems = [], subIdx = -1, subTimer = null

  function click(id) { var b = $(id); if (b) b.click() }
  function shown(id) { var b = $(id); return !!b && b.style.display !== 'none' && !b.disabled && !b.hidden && !b.classList.contains('type-hidden') }
  function pressed(id) { var b = $(id); return !!b && (b.getAttribute('aria-pressed') === 'true' || b.classList.contains('on')) }
  function scKey(id, fallback) { try { if (window.scKeyUnbound && window.scKeyUnbound(id)) return ''; return (window.scKeyLabel && window.scKeyLabel(id)) || fallback } catch (e) { return fallback } } // live binding: settings may have changed it
  function scRun(id) { try { return !!(window.scRunShortcut && window.scRunShortcut(id)) } catch (e) { return false } } // same handler as the key itself
  function fmt(kind) { var b = document.querySelector('[data-fmt="' + kind + '"]'); if (b && !b.disabled) b.click() }
  function fmtOn(kind) { var b = document.querySelector('[data-fmt="' + kind + '"]'); return !!b && !b.disabled }
  function it(label, run, o) { o = o || {}; return Object.assign({ label: label, run: run, on: o.on !== false }, o) }
  var EXT_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/></svg>'
  var ARROW_ICON = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3.5 10.5 8 6 12.5"/></svg>'
  var SEP = { sep: true }
  function head(t) { return { head: t } }

  function exportItems() {
    var download = $('dlTyp'), file = download && download.dataset.kind === 'file'
    var first = it(t('menu.dlFile', { ext: '.' + (download && download.dataset.extension || 'typ') }), function () { click('dlTyp') }, { on: shown('dlTyp') })
    if (file) return [first, it(t('menu.dlZip'), function () { click('dlZip') }, { on: shown('dlZip') })]
    return [first,
      it(t('menu.dlPdf'), function () { click('dlPdf') }, { on: shown('dlPdf') }),
      it(t('menu.dlPng'), function () { click('dlPng') }, { on: shown('dlPng') }),
      it(t('menu.dlSvg'), function () { click('dlSvg') }, { on: shown('dlSvg') }),
      it(t('menu.dlZip'), function () { click('dlZip') }, { on: shown('dlZip') })
    ]
  }
  function formatItems() {
    return [
      it(t('menu.bold'), function () { fmt('bold') }, { kbd: scKey('bold', M + 'B'), on: fmtOn('bold') }),
      it(t('menu.italic'), function () { fmt('italic') }, { kbd: scKey('italic', M + 'I'), on: fmtOn('italic') }),
      it(t('menu.underline'), function () { fmt('underline') }, { kbd: scKey('underline', M + 'U'), on: fmtOn('underline') }),
      SEP,
      it(t('shell.fmtHead'), function () { fmt('heading') }, { on: fmtOn('heading') }),
      it(t('shell.fmtBul'), function () { fmt('bullets') }, { on: fmtOn('bullets') }),
      it(t('shell.fmtNum'), function () { fmt('numbers') }, { on: fmtOn('numbers') }),
      it(t('shell.fmtMath'), function () { fmt('math') }, { on: fmtOn('math') }),
      it(t('shell.fmtCode'), function () { fmt('code') }, { on: fmtOn('code') }),
      it(t('shell.fmtLink'), function () { fmt('link') }, { on: fmtOn('link') }),
      SEP,
      it(t('editor.formatDoc'), function () { click('fmtDoc') }, { kbd: scKey('format', 'Alt+Shift+F'), on: shown('fmtDoc') })
    ]
  }
  function insertItems() {
    return [
      it(t('menu.addPic'), function () { click('imgBtn') }, { on: shown('imgBtn') }),
      it(t('menu.addTpl'), function () { click('tplBtn') }, { on: shown('tplBtn') }),
      it(t('menu.addSym'), function () { click('symBtn') }, { on: shown('symBtn') })
    ]
  }
  function viewModeItems() {
    var edit = pressed('vEdit'), read = pressed('vRead')
    return [
      it(t('menu.edOnly'), function () { click('vEdit') }, { checked: edit }),
      it(t('menu.edSplit'), function () { click('vSplit') }, { checked: !edit && !read }),
      it(t('menu.pvOnly'), function () { click('vRead') }, { checked: read }),
      SEP,
      it(t('presentation.enter'), function () { if (window.Present) window.Present.toggle() }, { on: shown('dlPdf'), close: true })
    ]
  }
  function zoomItem() { // same range row as the font slider, backed by the settings zoom
    var zoom = window.previewZoom || {}
    return {
      slider: { id: 'menuPreviewZoom', label: t('menu.zoom'), aria: t('settings.previewZoom'), min: zoom.min, max: zoom.max, step: zoom.step, unit: '%',
        get: function () { return zoom.get ? zoom.get() : 100 }, set: function (v) { if (zoom.set) zoom.set(v) } },
      on: !pressed('vEdit')
    }
  }
  function previewItems() {
    var edit = pressed('vEdit'), read = pressed('vRead')
    return [
      it(t('menu.follow'), function () { click('followBtn') }, { checked: pressed('followBtn'), on: !edit && !read }),
      it(t('menu.clickSync'), function () { click('syncBtn') }, { checked: pressed('syncBtn'), on: !edit && !read }),
      SEP,
      zoomItem(),
      it(t('menu.fitPage'), function () { click('fitPageBtn') }, { on: !edit }),
      it(t('menu.resetZoom'), function () { scRun('zoomReset') }, { kbd: scKey('zoomReset', M + '0'), on: !edit })
    ]
  }
  function themeItems() {
    return [
      it(t('menu.sysTheme'), function () { setTheme('system') }, { checked: themeMode() === 'system' }),
      it(t('menu.light'), function () { setTheme('light') }, { checked: themeMode() === 'light' }),
      it(t('menu.dark'), function () { setTheme('dark') }, { checked: themeMode() === 'dark' })
    ]
  }
  function fontItem() { // same range row as Settings: the editor module owns the value
    var font = window.editorFont || {}
    return {
      slider: { id: 'menuFontSize', label: t('menu.fontSizeShort'), aria: t('menu.fontSize'), min: font.min, max: font.max, step: font.step, unit: 'px',
        get: function () { return font.get ? font.get() : 14 }, set: function (v) { if (font.set) font.set(v) } },
      on: !pressed('vRead')
    }
  }
  function fontItems() { return [fontItem()] }
  var DEF = {
    insert: function () {
      return insertItems().concat([
        it(t('editor.citeLibrary'), function () { click('citeLibrary') }, { on: shown('citeLibrary') }),
        it(t('shell.colWrap'), function () { click('colPick') }, { on: shown('colWrap') })
      ])
    },
    file: function () {
      return [
        it(t('menu.newDoc'), function () { if (window.newProjectFromMenu) newProjectFromMenu(); else click('new') }),
        it(t('menu.upload'), function () { click('upDoc') }, { title: t('docs.pickUpSub') }),
        SEP,
        it(t('menu.rename'), function () { click('renBtn') }, { on: shown('renBtn') }),
        it(t('menu.share'), function () { click('shareBtn') }, { on: shown('shareBtn') }),
        it(t('menu.history'), function () { click('histBtn') }, { on: shown('histBtn') }),
        it(t('menu.saveNow'), function () { scRun('save') }, { kbd: scKey('save', M + 'S') }),
        SEP,
        it(t('menu.export'), null, { submenu: exportItems, on: shown('dlTyp') }),
        SEP,
        it(t('menu.moveTrash'), function () { click('del') }, { on: shown('del'), danger: true })
      ]
    },
    edit: function () {
      var formats = formatItems(), inserts = insertItems()
      return [
        it(t('menu.find'), function () { scRun('find') }, { kbd: scKey('find', M + 'F') }),
        SEP,
        it(t('menu.formatting'), null, { submenu: formatItems, on: formats.some(function (d) { return !d.sep && d.on !== false }) }),
        it(t('shell.fmtIns'), null, { submenu: insertItems, on: inserts.some(function (d) { return d.on !== false }) }),
        SEP,
        it(t('menu.comment'), function () { click('cNew') }, { on: shown('cNew') })
      ]
    },
    view: function () {
      var modes = viewModeItems(), previews = previewItems()
      return [
        it(t('menu.viewMode'), null, { submenu: viewModeItems, on: modes.some(function (d) { return !d.sep && d.on !== false }) }),
        it(t('menu.preview'), null, { submenu: previewItems, on: previews.some(function (d) { return !d.sep && d.on !== false }) }),
        SEP,
        it(t('menu.toggleSidebar'), function () { click('navToggle') }, { keepOpen: true }),
        SEP,
        it(t('menu.appearance'), null, { submenu: themeItems }),
        it(t('menu.fontSize'), null, { submenu: fontItems, on: !pressed('vRead') })
      ]
    },
    help: function () {
      return [
        it(t('menu.shortcuts'), function () { if (window.openShortcutSettings) window.openShortcutSettings(); else click('helpBtn') }),
        it(t('menu.agent'), function () { if (window.openSettingsCategory) window.openSettingsCategory('api'); else click('userMain') }),
        SEP,
        it(t('menu.source'), null, { href: 'https://github.com/fl-grtg/typst-editor', ext: true }),
        it(t('menu.issues'), null, { href: 'https://github.com/fl-grtg/typst-editor/issues', ext: true })
      ]
    },
    export: function () { return [head(t($('dlTyp').dataset.kind === 'file' ? 'menu.dlFileHead' : 'menu.dlHead'))].concat(exportItems()) },
    all: function () {
      return [head(t('menu.fileH'))].concat(DEF.file(), [head(t('menu.editH'))], DEF.edit(), [head(t('menu.viewH'))], DEF.view(), [head(t('menu.helpH'))], DEF.help())
    }
  }

  function liveAnchor(f) { // a sidebar repaint may replace the row under an open menu: focus the same row again
    if (f.isConnected) return f
    var row = f.closest && f.closest('[data-package-key],[data-doc-id]'), key = row && row.dataset.packageKey, doc = row && row.dataset.docId
    var now = doc ? Array.prototype.slice.call(document.querySelectorAll('[data-doc-id]')).filter(function (r) { return r.dataset.docId === doc })[0]
      : key ? Array.prototype.slice.call(document.querySelectorAll('[data-package-key]')).filter(function (r) { return r.dataset.packageKey === key })[0] : null
    if (now) return now.querySelector('[data-side-menu]') || f
    var resRow = f.closest && f.closest('[data-resource-name]'), res = resRow && resRow.dataset.resourceName
    var nowRes = res && Array.prototype.slice.call(document.querySelectorAll('[data-resource-name]')).filter(function (r) { return r.dataset.resourceName === res })[0]
    if (nowRes) return nowRes.querySelector('[data-side-menu]') || f
    var folderRow = f.closest && f.closest('[data-folder-path]'), folder = folderRow && folderRow.dataset.folderPath
    var nowFolder = folder && Array.prototype.slice.call(document.querySelectorAll('[data-folder-path]')).filter(function (r) { return r.dataset.folderPath === folder })[0]
    if (nowFolder) return nowFolder.querySelector('[data-side-menu]') || f
    var group = f.closest && f.closest('[data-project-id]'), id = group && group.dataset.projectId
    var again = id && Array.prototype.slice.call(document.querySelectorAll('[data-project-id]')).filter(function (g) { return g.dataset.projectId === id })[0]
    if (again) return again.querySelector('.fhd.project [data-side-menu]') || f
    var head = f.closest && f.closest('aside h3'), hid = head && head.id
    var nowHead = hid && document.getElementById(hid)
    return nowHead ? nowHead.querySelector('[data-side-menu]') || f : f
  }
  window.reanchorSidebarMenu = function () { // a repaint replaces the row under an open menu: move the state to the new button
    if (!openFor || openFor.isConnected) return
    var next = liveAnchor(openFor)
    if (!next || !next.isConnected) return // no stable row to move to: leave the open menu alone
    next.setAttribute('aria-expanded', 'true')
    var row = next.closest && next.closest('aside .doc, aside .fhd, aside h3')
    if (row) row.classList.add('menu-open')
    openFor = next
  }
  function cancelSubClose() {
    if (subTimer) { clearTimeout(subTimer); subTimer = null }
  }
  function scheduleSubClose() { // forgiving hover: crossing the gap to the submenu must not close it
    cancelSubClose()
    subTimer = setTimeout(function () { subTimer = null; closeSub(false) }, 400)
  }
  function closeSub(refocus) {
    cancelSubClose()
    if (!subFor) return
    var b = subFor
    subFor = null; subItems = []; subIdx = -1
    b.classList.remove('sub-open')
    b.setAttribute('aria-expanded', 'false')
    submenu.hidden = true; submenu.replaceChildren()
    if (refocus && b && b.isConnected) b.focus()
  }
  function close(refocus) {
    if (!openFor) return
    closeSub(false)
    openFor.setAttribute('aria-expanded', 'false')
    var f = openFor
    // Focus first: the row actions become visibility:hidden once menu-open is
    // gone, and a hidden button cannot take focus.
    if (refocus && f) {
      var back = liveAnchor(f), backRow = back.closest && back.closest('aside .doc, aside .fhd, aside h3')
      if (backRow) backRow.classList.add('menu-open') // a repaint may have replaced the row before it was re-anchored: its action button must be visible to take focus
      back.focus()
    }
    document.querySelectorAll('aside .menu-open').forEach(function (row) { row.classList.remove('menu-open') })
    openFor = null; items = []; idx = -1
    menu.hidden = true; menu.replaceChildren()
  }
  window.closeMenu = close // header pops live in module scope, close the menu through this
  function focusPanel(panel, i) {
    var rows = panel.querySelectorAll('button:not(:disabled), a[href], input[type=range]:not(:disabled)')
    if (!rows.length) return
    if (panel === submenu) {
      subIdx = (i + rows.length) % rows.length
      rows[subIdx].focus()
    } else {
      idx = (i + rows.length) % rows.length
      rows[idx].focus()
    }
  }
  function focusItem(i) { focusPanel(menu, i) }
  function submenuList(d) {
    if (!d.submenu) return []
    try { return typeof d.submenu === 'function' ? d.submenu() : d.submenu } catch (e) { return [] }
  }
  function openSub(parent, button, d, focus) {
    var list = submenuList(d)
    if (!list || !list.length) { closeSub(false); return }
    closeSub(false)
    submenu.replaceChildren()
    submenu.dataset.name = menu.dataset.name || ''
    list.forEach(function (item) { paintMenuItem(submenu, item) })
    subItems = list
    submenu.hidden = false
    submenu.style.width = 'max-content'
    var natural = submenu.getBoundingClientRect().width
    submenu.style.width = Math.ceil(natural + 10) + 'px' // each submenu gets 10px past its longest row
    var r = button.getBoundingClientRect()
    var w = submenu.offsetWidth, h2 = submenu.offsetHeight
    var left = r.right + 3
    if (left + w > window.innerWidth - 8) left = r.left - w - 3
    left = Math.max(8, Math.min(left, window.innerWidth - w - 8))
    var top = r.top - 4
    if (top + h2 > window.innerHeight - 8) top = Math.max(8, window.innerHeight - h2 - 8)
    submenu.style.left = left + 'px'; submenu.style.top = top + 'px'
    button.setAttribute('aria-expanded', 'true')
    button.classList.add('sub-open')
    subFor = button
    if (focus) focusPanel(submenu, 0)
  }
  function runMenuItem(d) { // async actions used to reject silently: surface the same toast row actions show
    setTimeout(function () {
      if (typeof d.run !== 'function') return
      menuAction = true // proxy clicks (view mode, sidebar, ...) bubble to the same document handler and must not close the menu
      try {
        var out = d.run()
        if (out && typeof out.catch === 'function') out.catch(function (e) {
          if (window.toast) window.toast((e && e.message) || String(e))
        })
      } catch (e) {
        if (window.toast) window.toast((e && e.message) || String(e))
      } finally { menuAction = false }
    }, 0)
  }
  function focusRow(panel, row) { // keep keyboard position on the clicked row: some browsers do not focus buttons on click
    if (!row || !row.isConnected || row.disabled) return
    var rows = Array.prototype.slice.call(panel.querySelectorAll('button:not(:disabled), a[href], input[type=range]:not(:disabled)'))
    var at = rows.indexOf(row)
    if (at < 0) return
    if (panel === submenu) subIdx = at
    else idx = at
    row.focus()
  }
  function syncPanel(panel, list) { // update ticks in place: rebuilding the row would drop the parent's hover/sub-open state
    Array.prototype.forEach.call(panel.querySelectorAll('button, a[href]'), function (b) {
      var d = b._menuItem, fresh = null
      if (!d || d.sep || d.head || d.slider) return
      for (var i = 0; i < list.length; i++) {
        var x = list[i]
        if (!x.sep && !x.head && !x.slider && x.label === d.label) { fresh = x; break }
      }
      if (!fresh) return
      b._menuItem = fresh
      if (fresh.checked !== undefined) {
        b.setAttribute('aria-checked', String(!!fresh.checked))
        var c = b.querySelector('.chk')
        if (c) c.textContent = fresh.checked ? '\u2713' : ''
      }
      if (b.tagName === 'BUTTON') b.disabled = fresh.on === false || !!fresh.disabled
    })
  }
  function refreshOpen(panel, row) { // checkable rows keep the menu open: sync state without replacing the submenu-opening button
    if (!openFor || !openFor.closest('#menubar')) return
    var name = menu.dataset.name
    if (!DEF[name]) return
    var inSub = panel === submenu
    if (inSub && !subFor) return
    var top = DEF[name]() || []
    var list = inSub ? submenuList(subFor._menuItem) : top
    if (!list) return
    if (inSub) subItems = list
    syncPanel(panel, list)
    if (inSub) syncPanel(menu, top) // parent availability follows the new mode without closing the menu
    focusRow(panel, row) // the clicked row identifies its panel; activeElement is unreliable on Safari
  }
  function paintMenuRange(panel, d) {
    var s = d.slider
    var row = document.createElement('div'); row.className = 'mRange'; row.setAttribute('role', 'group')
    if (d.on === false) row.classList.add('disabled')
    var label = document.createElement('label'); label.className = 'lb'; label.htmlFor = s.id; label.textContent = s.label
    var input = document.createElement('input'); input.type = 'range'; input.id = s.id
    input.min = s.min; input.max = s.max; input.step = s.step; input.disabled = d.on === false
    if (s.aria || s.label) input.setAttribute('aria-label', s.aria || s.label)
    var val = document.createElement('span'); val.className = 'val'
    var paint = function () {
      var v = Math.round(+s.get()), text = v + (s.unit || '')
      input.value = v; val.textContent = text; input.setAttribute('aria-valuetext', text)
      input.style.setProperty('--fill', ((v - s.min) / (s.max - s.min) * 100) + '%')
    }
    input.oninput = function () { s.set(+input.value); paint() }
    paint(); row.append(label, input, val); panel.appendChild(row)
  }
  function paintMenuItem(panel, d) {
    if (d.sep) { panel.appendChild(document.createElement('hr')); return }
    if (d.head) { var h = document.createElement('div'); h.className = 'mh'; h.textContent = d.head; panel.appendChild(h); return }
    if (d.slider) { paintMenuRange(panel, d); return }
    var b = document.createElement(d.href ? 'a' : 'button')
    if (d.href) { // a real <a href>: the browser's own status bar shows the destination on hover
      b.href = d.href
      b.target = '_blank'
      b.rel = 'noopener noreferrer'
      if (d.on === false) { b.removeAttribute('href'); b.setAttribute('aria-disabled', 'true') }
    } else {
      b.type = 'button'
      b.disabled = d.on === false || !!d.disabled
    }
    b.setAttribute('role', d.checked === undefined ? 'menuitem' : 'menuitemcheckbox')
    if (d.checked !== undefined) b.setAttribute('aria-checked', String(!!d.checked))
    if (d.danger) b.className = 'danger'
    if (d.title) b.title = d.title
    if (d.label) b.setAttribute('aria-label', d.label)
    var c = document.createElement('span'); c.className = 'chk'; c.setAttribute('aria-hidden', 'true'); c.textContent = d.checked ? '\u2713' : ''
    var l = document.createElement('span'); l.className = 'lb'; l.textContent = d.label
    if (d.checked !== undefined) b.appendChild(c)
    b.appendChild(l)
    if (d.kbd) { var k = document.createElement('span'); k.className = 'kbd'; k.textContent = d.kbd; b.appendChild(k) }
    if (d.ext) { var x = document.createElement('span'); x.className = 'ext'; x.innerHTML = EXT_ICON; b.appendChild(x) } // link leaves Typst
    var hasSub = !!(d.submenu && (typeof d.submenu === 'function' || d.submenu.length))
    if (hasSub) {
      b.setAttribute('aria-haspopup', 'menu')
      b.setAttribute('aria-expanded', 'false')
      var a = document.createElement('span'); a.className = 'arrow'; a.innerHTML = ARROW_ICON; a.setAttribute('aria-hidden', 'true'); b.appendChild(a)
      b.onclick = function (e) { e.preventDefault(); e.stopPropagation(); openSub(panel, b, d, true) }
      b.addEventListener('pointerenter', function (e) {
        if (e.pointerType !== 'mouse') return
        if (subFor !== b) openSub(panel, b, d, false)
      })
    } else {
      if (d.href) b.onclick = function () { setTimeout(function () { close(false) }, 0) } // navigate first, then drop the menu
      else {
        var stay = !d.close && (d.keepOpen || (d.checked !== undefined && openFor && openFor.closest('#menubar')))
        b.onclick = function () {
          if (!stay) { close(false); runMenuItem(d); return }
          runMenuItem(d)
          if (d.checked !== undefined) setTimeout(function () { refreshOpen(panel, b) }, 0) // plain keep-open rows (sidebar) do not need a repaint
        }
      }
      b.addEventListener('pointerenter', function (e) { // hover another row: collapse the old submenu right away instead of leaving it over the list for 400 ms
        if (panel === menu && e.pointerType === 'mouse' && subFor) closeSub(false)
      })
    }
    b._menuItem = d
    panel.appendChild(b)
  }
  ;[menu, submenu].forEach(function (panel) { // grace period when the pointer crosses the gap between the panels
    panel.addEventListener('pointerenter', function (e) { if (e.pointerType === 'mouse') cancelSubClose() })
    panel.addEventListener('pointerleave', function (e) { if (e.pointerType === 'mouse' && subFor) scheduleSubClose() })
  })
  var MENUBAR = { file: 1, edit: 1, view: 1, help: 1 }
  function sharedMenubarWidth() { // all four menus take the natural width of the longest one
    var wasHidden = menu.hidden, prev = menu.style.width, max = 0
    menu.style.width = 'max-content'
    menu.hidden = false
    menu.style.visibility = 'hidden'
    try {
      Object.keys(MENUBAR).forEach(function (name) {
        if (!DEF[name]) return
        menu.replaceChildren()
        var list = null
        try { list = DEF[name]() } catch (e) { return } // one broken definition must not leave #menu in a half-open state
        if (!list) return
        list.forEach(function (d) { paintMenuItem(menu, d) })
        max = Math.max(max, menu.getBoundingClientRect().width)
      })
    } finally {
      menu.replaceChildren()
      menu.hidden = wasHidden
      menu.style.visibility = ''
      menu.style.width = prev
    }
    return max ? Math.ceil(max) + 10 : 0 // longest entry of the four plus a little air
  }
  function place(anchor, align, rect) {
    var r = rect || anchor.getBoundingClientRect(), w = menu.offsetWidth, h2 = menu.offsetHeight
    var left = align === 'right' ? r.right - w : r.left
    left = Math.max(8, Math.min(left, window.innerWidth - w - 8))
    var top = r.bottom + 6
    if (top + h2 > window.innerHeight - 8) { // rows near the bottom dock: open upwards when there is room
      var above = r.top - h2 - 6
      top = above >= 8 ? above : Math.max(8, window.innerHeight - h2 - 8)
    }
    menu.style.left = left + 'px'; menu.style.top = top + 'px'
  }
  function show(anchor, list, name, align) {
    var r = anchor.getBoundingClientRect() // before closing a parent popover: its child would otherwise measure 0x0
    close(false)
    if (window.closeFloatPanels) window.closeFloatPanels() // one floating panel at a time (popovers, watch menu, comment card)
    document.querySelectorAll('#sharePop,#setPop,#tplPop,#histPop,#symPop,#inboxPop,#watchBox').forEach(function (p) { // fallback when the module hook is not ready
      if (p.contains(anchor)) return
      if (p.id === 'watchBox') { if (typeof closeWatchBox === 'function') closeWatchBox(); else p.remove() } else p.style.display = 'none'
    })
    var width = MENUBAR[name] ? sharedMenubarWidth() : 0
    menu.replaceChildren()
    list.forEach(function (d) { paintMenuItem(menu, d) })
    menu.hidden = false
    menu.dataset.name = name
    if (width) menu.style.width = width + 'px'
    else menu.style.removeProperty('width')
    place(anchor, align, r)
    anchor.setAttribute('aria-expanded', 'true')
    var row = anchor.closest && anchor.closest('aside .doc, aside .fhd, aside h3')
    if (row) row.classList.add('menu-open') // the whole row keeps the hover while its menu is open
    openFor = anchor; items = list; openAlign = align
  }
  function open(anchor, name) {
    show(anchor, DEF[name] ? DEF[name]() : [], name, name === 'export' ? 'right' : 'left')
  }
  window.showMenuAt = function (anchor, list, align) { // anchored menu for tabs and other row-level actions
    show(anchor, list, 'anchored', align || 'left')
    focusItem(0)
  }

  document.addEventListener('click', function (e) { // capture: row clicks (open document) must not run for the menu button
    var s = e.target.closest && e.target.closest('[data-side-menu]')
    if (!s) return
    e.preventDefault(); e.stopPropagation()
    if (openFor === s) close(false)
    else {
      var list = typeof s.sideMenuItems === 'function' ? s.sideMenuItems() : []
      if (list.length) show(s, list, 'sidebar', 'left') // opens rightward from the three-dot like the header menus
    }
  }, true)
  document.addEventListener('click', function (e) {
    if (menuAction) return
    var a = e.target.closest && e.target.closest('[data-menu]')
    if (a) {
      e.preventDefault()
      if (openFor === a) close(false); else open(a, a.dataset.menu)
      return
    }
    if (openFor && !menu.contains(e.target) && !submenu.contains(e.target)) close(false)
  })
  // hover-switch between top-level menus while one is open (desktop menubar behaviour)
  document.querySelectorAll('#menubar [data-menu]').forEach(function (b) {
    b.addEventListener('pointerenter', function (e) {
      if (e.pointerType === 'mouse' && openFor && openFor !== b && openFor.closest('#menubar')) open(b, b.dataset.menu)
    })
  })
  document.addEventListener('keydown', function (e) {
    if (!openFor) {
      var s = e.target.closest && e.target.closest('[data-side-menu]')
      if (s && (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ')) {
        var list = typeof s.sideMenuItems === 'function' ? s.sideMenuItems() : []
        if (list.length) { e.preventDefault(); show(s, list, 'sidebar', 'left'); focusItem(0) }
      }
      return
    }
    if (/^(INPUT|SELECT|TEXTAREA)$/.test((e.target && e.target.tagName) || '')) { // menu slider: arrows adjust the value, Esc backs out like any submenu row
      if (e.key === 'Escape') {
        e.preventDefault(); e.stopPropagation()
        if (subFor && submenu.contains(e.target)) closeSub(true)
        else close(true)
      }
      return
    }
    var inSub = subFor && document.activeElement && submenu.contains(document.activeElement)
    if (inSub) {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); closeSub(true); return }
      if (e.key === 'ArrowLeft') { e.preventDefault(); closeSub(true); return }
      if (e.key === 'ArrowRight') { e.preventDefault(); return }
      if (e.key === 'ArrowDown') { e.preventDefault(); focusPanel(submenu, subIdx + 1); return }
      if (e.key === 'ArrowUp') { e.preventDefault(); focusPanel(submenu, subIdx < 0 ? -1 : subIdx - 1); return }
      if (e.key === 'Home') { e.preventDefault(); focusPanel(submenu, 0); return }
      if (e.key === 'End') { e.preventDefault(); focusPanel(submenu, -1); return }
      return
    }
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(true) }
    else if (e.key === 'ArrowDown') { e.preventDefault(); focusItem(idx + 1) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); focusItem(idx < 0 ? -1 : idx - 1) }
    else if (e.key === 'Home') { e.preventDefault(); focusItem(0) }
    else if (e.key === 'End') { e.preventDefault(); focusItem(-1) }
    else if (e.key === 'ArrowRight') {
      var cur = document.activeElement
      if (cur && menu.contains(cur) && cur._menuItem && cur._menuItem.submenu) { e.preventDefault(); openSub(menu, cur, cur._menuItem, true); return }
      if (openFor.closest('#menubar')) {
        var bs = Array.prototype.slice.call(document.querySelectorAll('#menubar [data-menu]'))
        var i = bs.indexOf(openFor), n = bs[(i + 1) % bs.length]
        e.preventDefault(); open(n, n.dataset.menu); n.focus(); focusItem(0)
      }
    } else if (e.key === 'ArrowLeft') {
      if (subFor) { e.preventDefault(); closeSub(true); return }
      if (openFor.closest('#menubar')) {
        var bs2 = Array.prototype.slice.call(document.querySelectorAll('#menubar [data-menu]'))
        var i2 = bs2.indexOf(openFor), n2 = bs2[(i2 - 1 + bs2.length) % bs2.length]
        e.preventDefault(); open(n2, n2.dataset.menu); n2.focus(); focusItem(0)
      }
    }
  }, true)
  addEventListener('resize', function () { close(false) })
  addEventListener('blur', function () { close(false) })
  var side = $('side')
  if (side) side.addEventListener('transitionend', function (e) { if (openFor && e.propertyName === 'width') place(openFor, openAlign) }) // sidebar toggle moved the anchor
  document.querySelectorAll('#menubar [data-menu], #exportBtn, #insertMore').forEach(function (b) {
    b.addEventListener('keydown', function (e) {
      if ((e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') && openFor !== b) { e.preventDefault(); open(b, b.dataset.menu); focusItem(0) }
    })
  })

  /* Theme: system / light / dark, persisted */
  var root = document.documentElement
  var SUN = '<svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" aria-hidden="true"><circle cx="8" cy="8" r="2.8"/><path d="M8 1.6v1.4M8 13v1.4M1.6 8H3M13 8h1.4M3.5 3.5l1 1M11.5 11.5l1 1M3.5 12.5l1-1M11.5 4.5l1-1"/></svg>'
  var MOON = '<svg width="18" height="18" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13.4 9.6A5.6 5.6 0 0 1 6.4 2.6a5.6 5.6 0 1 0 7 7z"/></svg>'
  var mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null
  function themeMode() { var t = root.getAttribute('data-theme'); return t === 'light' || t === 'dark' ? t : 'system' }
  function effective() { var m = themeMode(); return m !== 'system' ? m : (mq && mq.matches ? 'dark' : 'light') }
  function paintTheme() {
    var dark = effective() === 'dark', lbl = dark ? t('menu.toLight') : t('menu.toDark')
    document.querySelectorAll('[data-rail="theme"]').forEach(function (b) { b.innerHTML = dark ? SUN : MOON; b.title = lbl; b.setAttribute('aria-label', lbl) })
    var bg = getComputedStyle(root).getPropertyValue('--bg').trim()
    if (bg) document.querySelectorAll('meta[name="theme-color"]').forEach(function (m) { m.setAttribute('content', bg) })
  }
  function setTheme(m) {
    if (m === 'light' || m === 'dark') { root.setAttribute('data-theme', m); try { localStorage.setItem('typst_theme', m) } catch (e) {} }
    else { root.removeAttribute('data-theme'); try { localStorage.removeItem('typst_theme') } catch (e) {} }
    paintTheme()
  }
  if (mq && mq.addEventListener) mq.addEventListener('change', paintTheme)
  if (window.t) paintTheme() // module already ran (deferred): translate at once
  else document.addEventListener('DOMContentLoaded', paintTheme) // module runs before DCL: labels wait for t()

  /* Sidebar (one component: thin strip collapsed, full panel open) */
  function collapsed() { return body.classList.contains('noside') }
  function expand() { if (collapsed()) click('navToggle') }
  function section(hid) {
    expand()
    var h = $(hid)
    if (!h) return
    if (h.getAttribute('aria-expanded') === 'false') {
      var label = h.querySelector('.lbl')
      if (label) label.click(); else h.click()
    }
    setTimeout(function () { try { h.scrollIntoView({ block: 'nearest', behavior: 'smooth' }) } catch (e) {} }, 60)
  }
  var RAIL = {
    toggle: function () { click('navToggle') },
    new: function () { click('new') },
    docs: function () { section('ownH') },
    search: function () { expand(); setTimeout(function () { var q = $('q'); if (q) { q.focus(); q.select() } }, 80) },
    ol: function () { section('olH') },
    tpl: function () { section('tplH') },
    trash: function () { section('trashH') },
    theme: function () { setTheme(effective() === 'dark' ? 'light' : 'dark') },
    set: function () { click('userMain') },
    help: function () { click('helpBtn') }
  }
  document.querySelectorAll('[data-rail]').forEach(function (b) {
    b.addEventListener('click', function () {
      var f = RAIL[b.dataset.rail]; if (f) f()
    })
  })

  /* Collapsed strip shows the same avatar as the user box */
  var meDot = $('meDot'), railAv = $('railAv')
  function syncAv() { if (!meDot || !railAv) return; railAv.style.background = meDot.style.background; railAv.textContent = meDot.textContent }
  if (meDot && railAv) { new MutationObserver(syncAv).observe(meDot, { attributes: true, childList: true, characterData: true, subtree: true }); syncAv() }

  /* Text colour button mirrors the hidden native picker */
  var cp = $('colPick'), cw = $('colWrap')
  function syncCol() { if (!cp || !cw) return; cw.style.setProperty('--c', cp.value) }
  if (cp && cw) { new MutationObserver(syncCol).observe(cp, { attributes: true, attributeFilter: ['style', 'value'] }); cp.addEventListener('input', syncCol); cp.addEventListener('change', function () { syncCol(); setTimeout(function () { cp.blur() }, 0) }); syncCol() }
})()
