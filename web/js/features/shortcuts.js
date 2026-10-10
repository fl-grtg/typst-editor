// --- Keyboard shortcut overview: small window over Help (tutorial stays one click away) ---
const SC_ROWS = [ // [combos, descKey]: combos render with Ctrl or Command per platform
  [[['mod', 'S']], 'editor.scSave'],
  [[['mod', 'F']], 'editor.scFind'],
  [[['mod', 'B'], ['mod', 'I'], ['mod', 'U']], 'editor.scBold'],
  [[['Alt', 'Shift', 'F']], 'editor.scFormat'],
  [[['Ctrl', 'Space']], 'editor.scComplete'],
  [[['Tab']], 'editor.scAccept'],
  [[['Shift', 'Tab']], 'editor.scDedent'],
  [[['mod', '+'], ['mod', '−'], ['mod', '0']], 'editor.scZoom'],
  [[['Enter'], ['Shift', 'Enter']], 'editor.scFindNext'],
  [[['Esc']], 'editor.scClose'],
  [[['?']], 'editor.scHelp'],
  [[['mod', 'Click']], 'editor.scLink'],
  [[['Up', 'Down']], 'editor.scMenu'],
  [[['Enter'], ['Space']], 'editor.scRows'],
]
function scMod() { return /Mac|iPhone|iPad/.test(navigator.platform || '') ? '⌘' : 'Ctrl' }
function openShortcuts() {
  closePop(true)
  if (window.closeMenu) window.closeMenu(false)
  let ov = $('scOverlay')
  if (!ov) {
    ov = document.createElement('div'); ov.id = 'scOverlay'
    const card = document.createElement('div'); card.id = 'scCard'
    card.setAttribute('role', 'dialog'); card.setAttribute('aria-modal', 'true')
    ov.appendChild(card)
    ov.addEventListener('mousedown', e => { if (e.target === ov) closeShortcuts() })
    document.body.appendChild(ov)
  }
  const card = ov.firstChild
  card.setAttribute('aria-label', t('editor.scTitle'))
  card.replaceChildren()
  const head = document.createElement('div'); head.className = 'scHead'
  const title = document.createElement('b'); title.textContent = t('editor.scTitle')
  const x = document.createElement('button'); x.textContent = '✕'
  x.setAttribute('aria-label', t('common.close')); x.onclick = closeShortcuts
  head.append(title, x); card.appendChild(head)
  const mod = scMod(), table = document.createElement('table'); table.className = 'scTable'
  for (const [combos, desc] of SC_ROWS) {
    const tr = document.createElement('tr')
    const kk = document.createElement('td'); kk.className = 'scKeys'
    combos.forEach((c, i) => {
      if (i) kk.appendChild(document.createTextNode(' / '))
      const kbd = document.createElement('kbd'); kbd.className = 'scKbd'
      kbd.textContent = c.map(k => k === 'mod' ? mod : k).join('+')
      kk.appendChild(kbd)
    })
    const dd = document.createElement('td'); dd.textContent = t(desc)
    tr.append(kk, dd); table.appendChild(tr)
  }
  card.appendChild(table)
  const tut = document.createElement('button'); tut.className = 'scTut'
  tut.textContent = t('editor.scTutorial')
  tut.onclick = () => { closeShortcuts(); openTutorial() }
  card.appendChild(tut)
  ov.style.display = 'flex'
  x.focus()
}
function closeShortcuts() {
  const ov = $('scOverlay')
  if (ov) ov.style.display = 'none'
  try { $('helpBtn').focus() } catch (e) {}
}
addEventListener('keydown', e => {
  if (e.key === 'Escape' && $('scOverlay') && $('scOverlay').style.display !== 'none') { e.preventDefault(); closeShortcuts() }
})
$('helpBtn').onclick = e => { // Help = shortcut overview (Shift+Click still opens the source repo)
  if (e.shiftKey) open('https://github.com/fl-grtg/typst-editor', '_blank', 'noopener')
  else openShortcuts()
}
