/* UI layer: menubar, export menu, rail. Pure proxies to existing controls – no app logic lives here. */
(function () {
  'use strict'
  var $ = function (id) { return document.getElementById(id) }
  var menu = $('menu'), body = document.body
  var mac = /Mac|iPhone|iPad/.test(navigator.platform || '')
  var M = mac ? '\u2318' : 'Ctrl+'
  var openFor = null, items = [], idx = -1

  function click(id) { var b = $(id); if (b) b.click() }
  function shown(id) { var b = $(id); return !!b && b.style.display !== 'none' && !b.disabled && !b.hidden }
  function pressed(id) { var b = $(id); return !!b && (b.getAttribute('aria-pressed') === 'true' || b.classList.contains('on')) }
  function key(k, extra) {
    window.dispatchEvent(new KeyboardEvent('keydown', Object.assign({ key: k, ctrlKey: !mac, metaKey: mac, bubbles: true, cancelable: true }, extra || {})))
  }
  function fmt(kind) { var b = document.querySelector('[data-fmt="' + kind + '"]'); if (b && !b.disabled) b.click() }
  function fmtOn(kind) { var b = document.querySelector('[data-fmt="' + kind + '"]'); return !!b && !b.disabled }
  function it(label, run, o) { o = o || {}; return { label: label, run: run, kbd: o.kbd, on: o.on !== false, checked: o.checked } }
  var SEP = { sep: true }
  function head(t) { return { head: t } }

  function exportItems() {
    return [
      it('Download as .typ', function () { click('dlTyp') }, { on: shown('dlTyp') }),
      it('Download as PDF', function () { click('dlPdf') }, { on: shown('dlPdf') }),
      it('Page PNG', function () { click('dlPng') }, { on: shown('dlPng') }),
      it('Download as SVG', function () { click('dlSvg') }, { on: shown('dlSvg') })
    ]
  }
  var DEF = {
    file: function () {
      return [
        it('New document', function () { click('new') }),
        it('Upload .typ\u2026', function () { click('upDoc') }),
        SEP,
        it('Rename\u2026', function () { click('renBtn') }, { on: shown('renBtn') }),
        it('Share\u2026', function () { click('shareBtn') }, { on: shown('shareBtn') }),
        it('Version history\u2026', function () { click('histBtn') }, { on: shown('histBtn') }),
        it('Save now', function () { key('s') }, { kbd: M + 'S' }),
        SEP
      ].concat(exportItems(), [
        SEP,
        it('Move to trash', function () { click('del') }, { on: shown('del') }),
        it('Sign out', function () { click('out') })
      ])
    },
    edit: function () {
      return [
        it('Find and replace', function () { key('f') }, { kbd: M + 'F' }),
        SEP,
        it('Bold', function () { fmt('bold') }, { kbd: M + 'B', on: fmtOn('bold') }),
        it('Italic', function () { fmt('italic') }, { kbd: M + 'I', on: fmtOn('italic') }),
        it('Underline', function () { fmt('underline') }, { kbd: M + 'U', on: fmtOn('underline') }),
        SEP,
        it('Comment on selection', function () { click('cNew') }, { on: shown('cNew') }),
        it('Insert picture or file\u2026', function () { click('imgBtn') }, { on: shown('imgBtn') }),
        it('Insert template\u2026', function () { click('tplBtn') }, { on: shown('tplBtn') }),
        it('Insert symbol\u2026', function () { click('symBtn') }, { on: shown('symBtn') }),
        it('Media manager', function () { click('mediaBtn') }, { on: shown('mediaBtn') })
      ]
    },
    view: function () {
      var edit = pressed('vEdit'), read = pressed('vRead')
      return [
        it('Editor only', function () { click('vEdit') }, { checked: edit }),
        it('Editor and preview', function () { click('vSplit') }, { checked: !edit && !read }),
        it('Preview only', function () { click('vRead') }, { checked: read }),
        SEP,
        it('Sidebar', function () { click('navToggle') }, { checked: !body.classList.contains('noside') }),
        it('Follow between editor and preview', function () { click('syncBtn') }, { checked: pressed('syncBtn'), on: !edit && !read }),
        SEP,
        it('Zoom in', function () { click('zPlus') }, { kbd: M + '+', on: !edit }),
        it('Zoom out', function () { click('zMinus') }, { kbd: M + '\u2212', on: !edit }),
        it('Fit page to width', function () { click('fitBtn') }, { on: !edit }),
        it('Reset zoom', function () { key('0') }, { kbd: M + '0', on: !edit }),
        SEP,
        it('Larger editor text', function () { click('fPlus') }, { on: !read }),
        it('Smaller editor text', function () { click('fMinus') }, { on: !read }),
        head('Appearance'),
        it('Match system', function () { setTheme('system') }, { checked: themeMode() === 'system' }),
        it('Light', function () { setTheme('light') }, { checked: themeMode() === 'light' }),
        it('Dark', function () { setTheme('dark') }, { checked: themeMode() === 'dark' })
      ]
    },
    help: function () {
      return [
        it('Connect AI agent', function () { if ($('setPop').style.display === 'none') click('who') }),
        it('Source code on GitHub', function () { window.open('https://github.com/fl-grtg/typst-editor', '_blank', 'noopener') })
      ]
    },
    export: function () { return [head('Download current document')].concat(exportItems()) },
    all: function () {
      return [head('File')].concat(DEF.file(), [head('Edit')], DEF.edit(), [head('View')], DEF.view(), [head('Help')], DEF.help())
    }
  }

  function close(refocus) {
    if (!openFor) return
    openFor.setAttribute('aria-expanded', 'false')
    var f = openFor
    openFor = null; items = []; idx = -1
    menu.hidden = true; menu.replaceChildren()
    if (refocus && f) f.focus()
  }
  window.closeMenu = close // header pops live in module scope, close the menu through this
  function focusItem(i) {
    var btns = menu.querySelectorAll('button:not(:disabled)')
    if (!btns.length) return
    idx = (i + btns.length) % btns.length
    btns[idx].focus()
  }
  function open(anchor, name) {
    close(false)
    document.querySelectorAll('#sharePop,#setPop,#tplPop,#histPop,#symPop').forEach(function (p) { p.style.display = 'none' }) // one popover at a time
    var list = DEF[name] ? DEF[name]() : []
    menu.replaceChildren()
    list.forEach(function (d) {
      if (d.sep) { menu.appendChild(document.createElement('hr')); return }
      if (d.head) { var h = document.createElement('div'); h.className = 'mh'; h.textContent = d.head; menu.appendChild(h); return }
      var b = document.createElement('button')
      b.type = 'button'
      b.setAttribute('role', d.checked === undefined ? 'menuitem' : 'menuitemcheckbox')
      if (d.checked !== undefined) b.setAttribute('aria-checked', String(!!d.checked))
      b.disabled = !d.on
      var c = document.createElement('span'); c.className = 'chk'; c.textContent = d.checked ? '\u2713' : ''; c.setAttribute('aria-hidden', 'true')
      var l = document.createElement('span'); l.className = 'lb'; l.textContent = d.label
      b.append(c, l)
      if (d.kbd) { var k = document.createElement('span'); k.className = 'kbd'; k.textContent = d.kbd; b.appendChild(k) }
      b.onclick = function () { close(false); setTimeout(d.run, 0) }
      menu.appendChild(b)
    })
    menu.hidden = false
    var r = anchor.getBoundingClientRect(), w = menu.offsetWidth, h2 = menu.offsetHeight
    var left = name === 'export' ? r.right - w : r.left
    left = Math.max(8, Math.min(left, window.innerWidth - w - 8))
    var top = r.bottom + 6
    if (top + h2 > window.innerHeight - 8) top = Math.max(8, window.innerHeight - h2 - 8)
    menu.style.left = left + 'px'; menu.style.top = top + 'px'
    anchor.setAttribute('aria-expanded', 'true')
    openFor = anchor; items = list
    menu.dataset.name = name
  }

  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('[data-menu]')
    if (a) {
      e.preventDefault()
      if (openFor === a) close(false); else open(a, a.dataset.menu)
      return
    }
    if (openFor && !menu.contains(e.target)) close(false)
  })
  // hover-switch between top-level menus while one is open (desktop menubar behaviour)
  document.querySelectorAll('#menubar [data-menu]').forEach(function (b) {
    b.addEventListener('pointerenter', function (e) {
      if (e.pointerType === 'mouse' && openFor && openFor !== b && openFor.closest('#menubar')) open(b, b.dataset.menu)
    })
  })
  document.addEventListener('keydown', function (e) {
    if (!openFor) return
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(true) }
    else if (e.key === 'ArrowDown') { e.preventDefault(); focusItem(idx + 1) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); focusItem(idx < 0 ? -1 : idx - 1) }
    else if (e.key === 'Home') { e.preventDefault(); focusItem(0) }
    else if (e.key === 'End') { e.preventDefault(); focusItem(-1) }
    else if ((e.key === 'ArrowRight' || e.key === 'ArrowLeft') && openFor.closest('#menubar')) {
      var bs = Array.prototype.slice.call(document.querySelectorAll('#menubar [data-menu]'))
      var i = bs.indexOf(openFor), n = bs[(i + (e.key === 'ArrowRight' ? 1 : -1) + bs.length) % bs.length]
      e.preventDefault(); open(n, n.dataset.menu); n.focus(); focusItem(0)
    }
  }, true)
  addEventListener('resize', function () { close(false) })
  addEventListener('blur', function () { close(false) })
  document.querySelectorAll('#menubar [data-menu], #exportBtn').forEach(function (b) {
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
    var dark = effective() === 'dark', lbl = dark ? 'Switch to light mode' : 'Switch to dark mode'
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
  paintTheme()

  /* Sidebar (one component: thin strip collapsed, full panel open) */
  function collapsed() { return body.classList.contains('noside') }
  function expand() { if (collapsed()) click('navToggle') }
  function section(hid) {
    expand()
    var h = $(hid)
    if (!h) return
    if (h.getAttribute('aria-expanded') === 'false') h.click()
    setTimeout(function () { try { h.scrollIntoView({ block: 'nearest', behavior: 'smooth' }) } catch (e) {} }, 60)
  }
  var RAIL = {
    toggle: function () { click('navToggle') },
    new: function () { click('new') },
    docs: function () { section('ownH') },
    search: function () { expand(); setTimeout(function () { var q = $('q'); if (q) { q.focus(); q.select() } }, 80) },
    ol: function () { section('olH') },
    tpl: function () { section('tplH') },
    theme: function () { setTheme(effective() === 'dark' ? 'light' : 'dark') },
    set: function () { click('who') },
    help: function () { click('helpBtn') }
  }
  document.querySelectorAll('[data-rail]').forEach(function (b) {
    b.addEventListener('click', function (e) {
      if (b.id === 'userMain' && e.target.closest && e.target.closest('#who')) return // #who has its own handler
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
