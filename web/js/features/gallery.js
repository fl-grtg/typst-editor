// 2C: gallery (askNewDoc source), onboarding tour, empty-state quick row.
const THUMBS = {
  blank: '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="150" viewBox="0 0 120 150"><rect width="120" height="150" fill="#e8e9ec"/><rect x="24" y="23" width="72" height="104" rx="3" fill="#ffffff"/></svg>',
  report: '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="150" viewBox="0 0 120 150"><rect width="120" height="150" fill="#e8e9ec"/><rect x="24" y="23" width="72" height="104" rx="3" fill="#ffffff"/><rect x="34" y="35" width="52" height="8" rx="2" fill="#4f46e5"/><rect x="34" y="51" width="52" height="4" rx="2" fill="#c3c6cd"/><rect x="34" y="60" width="52" height="4" rx="2" fill="#c3c6cd"/><rect x="34" y="69" width="44" height="4" rx="2" fill="#c3c6cd"/><rect x="34" y="78" width="52" height="4" rx="2" fill="#c3c6cd"/><rect x="34" y="87" width="38" height="4" rx="2" fill="#c3c6cd"/></svg>',
  slides: '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="110" viewBox="0 0 160 110"><rect width="160" height="110" fill="#e8e9ec"/><rect x="28" y="19" width="104" height="72" rx="3" fill="#ffffff"/><rect x="36" y="29" width="40" height="7" rx="2" fill="#4f46e5"/><rect x="36" y="43" width="60" height="4" rx="2" fill="#c3c6cd"/><rect x="36" y="52" width="52" height="4" rx="2" fill="#c3c6cd"/><rect x="36" y="61" width="64" height="4" rx="2" fill="#c3c6cd"/></svg>',
  paper: '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="150" viewBox="0 0 120 150"><rect width="120" height="150" fill="#e8e9ec"/><rect x="24" y="23" width="72" height="104" rx="3" fill="#ffffff"/><rect x="38" y="33" width="44" height="7" rx="2" fill="#4f46e5"/><rect x="34" y="49" width="52" height="4" rx="2" fill="#c3c6cd"/><rect x="34" y="58" width="52" height="4" rx="2" fill="#c3c6cd"/><rect x="34" y="67" width="30" height="4" rx="2" fill="#c3c6cd"/><rect x="34" y="76" width="52" height="4" rx="2" fill="#c3c6cd"/><rect x="34" y="85" width="46" height="4" rx="2" fill="#c3c6cd"/></svg>',
  cv: '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="150" viewBox="0 0 120 150"><rect width="120" height="150" fill="#e8e9ec"/><rect x="24" y="23" width="72" height="104" rx="3" fill="#ffffff"/><circle cx="42" cy="41" r="8" fill="#4f46e5"/><rect x="54" y="35" width="26" height="6" rx="2" fill="#4f46e5"/><rect x="34" y="59" width="52" height="4" rx="2" fill="#c3c6cd"/><rect x="34" y="68" width="52" height="4" rx="2" fill="#c3c6cd"/><rect x="34" y="77" width="42" height="4" rx="2" fill="#c3c6cd"/><rect x="34" y="86" width="52" height="4" rx="2" fill="#c3c6cd"/></svg>',
  letter: '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="150" viewBox="0 0 120 150"><rect width="120" height="150" fill="#e8e9ec"/><rect x="24" y="23" width="72" height="104" rx="3" fill="#ffffff"/><rect x="58" y="33" width="28" height="4" rx="2" fill="#c3c6cd"/><rect x="58" y="42" width="22" height="4" rx="2" fill="#c3c6cd"/><rect x="34" y="67" width="52" height="4" rx="2" fill="#c3c6cd"/><rect x="34" y="76" width="52" height="4" rx="2" fill="#c3c6cd"/><rect x="34" y="85" width="52" height="4" rx="2" fill="#c3c6cd"/><rect x="34" y="94" width="38" height="4" rx="2" fill="#c3c6cd"/></svg>',
  thesis: '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="150" viewBox="0 0 120 150"><rect width="120" height="150" fill="#e8e9ec"/><rect x="24" y="23" width="72" height="104" rx="3" fill="#ffffff"/><rect x="24" y="41" width="72" height="20" fill="#4f46e5"/><rect x="36" y="47" width="48" height="6" rx="2" fill="#fff"/><rect x="34" y="73" width="52" height="4" rx="2" fill="#c3c6cd"/><rect x="34" y="82" width="44" height="4" rx="2" fill="#c3c6cd"/><rect x="34" y="91" width="52" height="4" rx="2" fill="#c3c6cd"/></svg>',
}
const GALLERY = [
  { id: 'blank', tk: 'gallery.gBlank', sk: 'gallery.gBlankSub', src: '' },
  { id: 'report', tk: 'gallery.gReport', sk: 'gallery.gReportSub', src: '#set page(paper: "a4", margin: 2cm)\n#set text(size: 11pt)\n#set heading(numbering: "1.")\n\n= Introduction\n\nText here …\n' },
  { id: 'slides', tk: 'gallery.gSlides', sk: 'gallery.gSlidesSub', src: '#set page(paper: "presentation-16-9", margin: 1.5cm)\n#set text(size: 20pt)\n\n= Slide 1\n\n- First point\n- Second point\n\n#pagebreak()\n\n= Slide 2\n\nText here …\n' },
  { id: 'paper', tk: 'gallery.gPaper', sk: 'gallery.gPaperSub', src: '#set page(paper: "a4", margin: 2cm)\n#set text(size: 11pt)\n#set heading(numbering: "1.")\n\n= A Short Paper\n\nThis paper shows a heading, inline math $E = m c^2$ and a list:\n\n- First point\n- Second point\n' },
  { id: 'cv', tk: 'gallery.gCv', sk: 'gallery.gCvSub', src: '#set page(paper: "a4", margin: 2cm)\n#align(center)[#text(20pt, weight: "bold")[Jane Doe]]\n#align(center)[jane.doe@example.org]\n\n= Experience\n\n- 2022–now: Engineer at Sample GmbH\n- 2019–2022: Junior Developer\n\n= Education\n\n- 2019: B.Sc. Computer Science\n' },
  { id: 'letter', tk: 'gallery.gLetter', sk: 'gallery.gLetterSub', src: '#set page(paper: "a4", margin: 2.5cm)\n#align(right)[Jane Doe]\n\n#v(1cm)\nDear Ms. Miller,\n\nThank you for your letter. I confirm our meeting next week.\n\n#v(1cm)\nKind regards,\nJane Doe\n' },
  { id: 'thesis', tk: 'gallery.gThesis', sk: 'gallery.gThesisSub', src: '#set page(paper: "a4", margin: 2.5cm, numbering: "1")\n#set heading(numbering: "1.")\n#align(center)[#v(3cm)#text(22pt, weight: "bold")[Thesis Title]#v(0.5cm)Bachelor Thesis]\n#pagebreak()\n= Introduction\n\nMotivation and goals.\n\n= Method\n\nApproach and implementation.\n\n= Conclusion\n\nResults and outlook.\n' },
]
const galleryContent = i => ((+i >= 0 && +i < GALLERY.length) ? GALLERY[+i] : GALLERY[0]).src
const galleryThumb = id => 'data:image/svg+xml;utf8,' + encodeURIComponent(THUMBS[id] || THUMBS.blank)
function galleryCard(g, sel, onPick) { // thumb + title + desc, keyboard-operable
  const b = el('button', 'pk')
  b.classList.add('gal')
  if (sel) b.classList.add('on')
  b.setAttribute('aria-pressed', String(!!sel))
  const img = document.createElement('img')
  img.src = galleryThumb(g.id)
  img.alt = ''
  img.loading = 'lazy'
  const tx = document.createElement('span')
  tx.className = 'pkTx'
  tx.append(el('b', null, t(g.tk)), el('span', null, t(g.sk)))
  b.append(img, tx)
  b.onclick = onPick
  return b
}
// --- Onboarding tour: 3 steps, bottom card, abort via Skip/Esc/click-away ---
const TOUR_KEYS = ['gallery.tour1', 'gallery.tour2', 'gallery.tour3']
const TOUR_SEL = ['#side', '#leftCol', '#exportBtn']
let tourStep = -1, tourPrev = null
function tourHi(on) {
  for (const s of TOUR_SEL) {
    const n = document.querySelector(s)
    if (n) n.classList.toggle('tourHi', !!on && TOUR_SEL[tourStep] === s)
  }
}
function tourShow(i) {
  tourClear()
  tourStep = i
  if (!tourPrev) tourPrev = document.activeElement
  tourHi(true)
  const card = el('div', 'tourCard')
  card.id = 'tourCard'
  card.setAttribute('role', 'dialog')
  card.setAttribute('aria-label', t('gallery.tourStart'))
  card.appendChild(el('p', null, t(TOUR_KEYS[i])))
  const row = el('div', 'ctaRow')
  const sk = el('button', 'ghost', t(i >= TOUR_KEYS.length - 1 ? 'gallery.tourDone' : 'gallery.tourSkip'))
  sk.onclick = tourEnd
  row.appendChild(sk)
  if (i < TOUR_KEYS.length - 1) {
    const nx = el('button', 'primary', t('gallery.tourNext'))
    nx.onclick = () => tourShow(i + 1)
    row.appendChild(nx)
  }
  card.appendChild(row)
  document.body.appendChild(card)
  try { (row.querySelector('.primary') || sk).focus() } catch (e) {}
}
function tourClear() {
  tourStep = -1
  tourHi(false)
  document.getElementById('tourCard')?.remove()
}
function tourEnd() {
  tourClear()
  try { localStorage.setItem('typst_tour_done', '1') } catch (e) {}
  try { tourPrev?.focus?.() } catch (e) {}
  tourPrev = null
}
function tourDone() { // fresh account, never toured
  try { if (localStorage.getItem('typst_tour_done')) return true } catch (e) { return true }
  return false
}
function tourMaybe() { // empty view, fresh account: start once
  if (tourDone() || !document.getElementById('emptyCard')) return
  if (lastOwn.length > 1 || lastShared.length) return
  tourShow(0)
}
setTimeout(() => { // fresh account with Tutorial open: tour anyway (empty card rarely shows)
  if (tourDone() || tourStep >= 0 || !user) return
  if (lastOwn.length > 1 || lastShared.length) return
  tourShow(0)
}, 2500)
document.addEventListener('keydown', e => {
  if (e.key === 'Escape' && tourStep >= 0) tourEnd()
})
// --- Empty state: quick gallery row + tour entry (paintEmpty itself stays in 2D) ---
async function quickCreate(i) {
  const g = GALLERY[i] || GALLERY[0]
  try {
    openDoc((await api('POST', '/api/docs/create', { title: t(g.tk), content: g.src })).id)
  } catch (e) { toast(e.message) }
}
function enhanceEmpty() {
  const card = document.getElementById('emptyCard')
  if (!card || document.getElementById('galQuick')) return
  const wrap = el('div', 'galQuick')
  wrap.id = 'galQuick'
  wrap.appendChild(el('p', 'sub', t('gallery.quickTitle')))
  const grid = el('div', 'galGrid')
  GALLERY.forEach((g, i) => {
    const b = document.createElement('button')
    b.className = 'gq'
    const img = document.createElement('img')
    img.src = galleryThumb(g.id)
    img.alt = ''
    img.loading = 'lazy'
    b.append(img, document.createTextNode(t(g.tk)))
    b.setAttribute('aria-label', t(g.tk) + ' – ' + t(g.sk))
    b.onclick = () => quickCreate(i)
    grid.appendChild(b)
  })
  wrap.appendChild(grid)
  const tb = el('button', 'ghost', t('gallery.tourStart'))
  tb.onclick = () => tourShow(0)
  wrap.appendChild(tb)
  card.appendChild(wrap)
  tourMaybe()
}
new MutationObserver(enhanceEmpty).observe(document.getElementById('preview'), { childList: true })
