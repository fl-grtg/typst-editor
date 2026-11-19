// Welcome screen: shown instead of topbar + editor/preview split while no document is open.
// Only function declarations here: closeView() paints it during boot, before this file's top level runs.
function welcomeOn() { return document.body.classList.contains('welcome') }
function setWelcome(on) {
  document.body.classList.toggle('welcome', on)
  $('welcome').hidden = !on
  if (on) paintWelcome()
}
function welcomeIcon(path, size = 18) {
  return `<svg width="${size}" height="${size}" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${path}</svg>`
}
function welcomeGreeting() {
  const h = new Date().getHours()
  return h < 11 ? t('docs.wGreetMorning') : h < 18 ? t('docs.wGreetDay') : t('docs.wGreetEvening')
}
function welcomeButton(id, icon, label, run, extra) {
  const b = el('button', 'wBtn'); b.type = 'button'; b.id = id
  if (extra) b.classList.add(extra)
  const ic = el('span', 'wIco'); ic.innerHTML = icon
  b.append(ic, el('span', 'wLbl', label))
  b.onclick = () => Promise.resolve().then(run).catch(e => toast(e.message))
  return b
}
function welcomeRecent() { // newest first across own + shared documents (no trash)
  const seen = new Set(), all = []
  for (const x of [...lastOwn, ...lastShared]) if (!seen.has(x.id)) { seen.add(x.id); all.push(x) }
  return all.sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || ''))).slice(0, 6)
}
function welcomeRow(x) {
  const r = el('button', 'wDoc'); r.type = 'button'
  const tile = el('span', 'wTile')
  tile.innerHTML = welcomeIcon('<path d="M4 1.8h5.2L12.5 5v9.2H4z"/><path d="M9 1.8V5h3.5"/>', 15)
  const main = el('span', 'wDocMain')
  main.appendChild(el('span', 'wDocTitle', x.title))
  const p = x.project_id && projects.find(q => q.id === x.project_id)
  const meta = x.owner && x.owner !== user ? t('docs.wSharedBy', { owner: x.owner }) : (p && p.title !== x.title ? p.title : '')
  if (meta) main.appendChild(el('span', 'wDocMeta', meta))
  r.append(tile, main)
  if (x.updated_at) r.appendChild(el('span', 'wDocWhen', ago(x.updated_at)))
  r.onclick = () => openDoc(x.id)
  return r
}
function paintWelcomeBadge() {
  const n = $('wInboxN')
  if (!n) return
  let c = 0
  try { c = inboxUnread || 0 } catch (e) {} // boot: inbox.js not evaluated yet (TDZ)
  n.hidden = !c; n.textContent = c > 99 ? '99+' : String(c)
}
function paintWelcome() {
  const box = $('welcome')
  if (!box || !welcomeOn()) return
  const corner = el('div', 'wCorner')
  const nav = el('button', 'wNav'); nav.type = 'button'
  nav.title = t('shell.navToggle'); nav.setAttribute('aria-label', t('shell.navToggle'))
  nav.innerHTML = welcomeIcon('<rect x="2" y="2.5" width="12" height="11" rx="2"/><path d="M6 2.5v11"/>', 16)
  nav.onclick = () => $('navToggle').click()
  const bell = el('button', 'wBell'); bell.type = 'button'
  bell.title = t('inbox.title'); bell.setAttribute('aria-label', t('inbox.title'))
  bell.innerHTML = welcomeIcon('<path d="M8 2.2a4 4 0 0 0-4 4c0 3-1.5 4.3-1.5 4.3h11S12 9.2 12 6.2a4 4 0 0 0-4-4z"/><path d="M6.5 13a1.5 1.5 0 0 0 3 0"/>', 16)
  const n = el('span'); n.id = 'wInboxN'; n.hidden = true; bell.appendChild(n)
  bell.onclick = e => { e.stopPropagation(); $('inboxBtn').click() }
  corner.append(nav, bell)

  const inner = el('div', 'wInner')
  const hero = el('div', 'wHero')
  const name = user ? user.charAt(0).toUpperCase() + user.slice(1) : ''
  const h = el('h1', 'wTitle', name ? `${welcomeGreeting()}, ${name}` : welcomeGreeting()); h.id = 'wTitle'
  hero.append(h, el('p', 'wLead', t('docs.wLead')))
  inner.appendChild(hero)

  const actions = el('div', 'wActions')
  actions.appendChild(welcomeButton('wNew', welcomeIcon('<path d="M8 3.5v9M3.5 8h9"/>', 14), t('docs.wNew'), () => newProjectFromMenu(), 'wPrimary'))
  actions.appendChild(welcomeButton('wUp', welcomeIcon('<path d="M8 10.5V2.5"/><path d="M4.8 5.5L8 2.3l3.2 3.2"/><path d="M2.5 10v2.3c0 .8.7 1.5 1.5 1.5h8c.8 0 1.5-.7 1.5-1.5V10"/>', 14), t('docs.wUpload'), () => $('docPick').click()))
  const tut = lastOwn.find(x => x.title === 'Tutorial')
  if (tut) actions.appendChild(welcomeButton('wTut', welcomeIcon('<path d="M2 3.5c2-.8 4-.8 6 .6 2-1.4 4-1.4 6-.6v9c-2-.8-4-.8-6 .6-2-1.4-4-1.4-6-.6z"/><path d="M8 4.1v9"/>', 14), t('docs.wTutorial'), () => openDoc(tut.id)))
  const k = window.scKeyLabel ? window.scKeyLabel('openHelp') : ''
  if (k) {
    const help = welcomeButton('wHelp', welcomeIcon('<circle cx="8" cy="8" r="6"/><path d="M6.3 6.2a1.8 1.8 0 0 1 3.4.6c0 1.2-1.7 1.4-1.7 2.5"/><path d="M8 11.6v.1"/>', 14), t('docs.wShortcuts'), () => openHelp())
    help.appendChild(el('kbd', null, k))
    actions.appendChild(help)
  }
  inner.appendChild(actions)

  const recent = el('section', 'wRecent')
  recent.setAttribute('aria-labelledby', 'wRecentH')
  const rh = el('h2', null, t('docs.wRecent')); rh.id = 'wRecentH'
  recent.appendChild(rh)
  const docs = welcomeRecent()
  if (docs.length) {
    const list = el('div', 'wList')
    docs.forEach(x => list.appendChild(welcomeRow(x)))
    recent.appendChild(list)
  } else {
    recent.appendChild(el('p', 'wEmpty', t('docs.noDocs')))
  }
  inner.appendChild(recent)
  box.replaceChildren(corner, inner)
  paintWelcomeBadge()
}
