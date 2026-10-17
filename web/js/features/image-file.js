async function paintImageFile(name) {
  let imageFile = $('imageFile')
  if (!imageFile) { imageFile = el('div', 'imageFile'); imageFile.id = 'imageFile'; $('editWrap').appendChild(imageFile) }
  const pdf = /\.pdf$/i.test(name)
  const on = !!docId && !!activeFile && !tplName && (pdf || /\.(png|jpe?g|gif|webp|svg|avif|bmp|ico)$/i.test(name))
  imageFile.hidden = !on
  const clear = () => { if (imageFile.dataset.url) URL.revokeObjectURL(imageFile.dataset.url); delete imageFile.dataset.url; imageFile.replaceChildren() }
  if (!on) {
    if (imageFile.dataset.key && !/\.(bib|csv|tsv)$/i.test(name)) $('cmWrap').hidden = false
    imageFile.dataset.key = ''; clear(); return
  }
  const mtime = (typeof lastFiles !== 'undefined' && lastFiles) ? (lastFiles.find(f => f.name === name) || {}).mtime : ''
  const session = window.changeSession
  const proposed = session?.files.get(sessionKey({ kind: 'file', doc_id: docId, path: name }))
  const key = docId + '/' + name + '@' + (mtime || '') + (session ? ':' + session.previewRevision + ':' + session.original : '')
  if (key === imageFile.dataset.key) {
    if (imageFile.dataset.failed) { imageFile.dataset.failed = '1'; imageFile.hidden = true; $('cmWrap').hidden = false }
    else $('cmWrap').hidden = true
    return
  }
  $('cmWrap').hidden = true
  delete imageFile.dataset.failed
  clear()
  imageFile.dataset.key = key
  const view = el(pdf ? 'embed' : 'img')
  if (pdf) view.type = 'application/pdf'
  else view.alt = name
  view.onerror = () => { if (imageFile.dataset.key === key) { imageFile.dataset.failed = '1'; imageFile.hidden = true; $('cmWrap').hidden = false } }
  try {
    const staged = proposed ? sessionBytes(proposed, session.original) : null
    if (proposed && staged == null) { toast(t('packages.fileAbsent')); view.onerror(); return }
    const response = staged ? new Response(staged) : await fetch(`/api/docs/${docId}/files/${encodeURIComponent(name)}`)
    if (!response.ok) throw Error(response.status)
    const bytes = await response.arrayBuffer()
    if (imageFile.dataset.key !== key) return
    const ext = name.split('.').pop().toLowerCase()
    const type = pdf ? 'application/pdf' : ({ jpg: 'image/jpeg', jpeg: 'image/jpeg', svg: 'image/svg+xml', ico: 'image/x-icon' }[ext] || 'image/' + ext)
    imageFile.dataset.url = URL.createObjectURL(new Blob([bytes], { type }))
    view.src = imageFile.dataset.url
    imageFile.replaceChildren(view)
  } catch (e) { view.onerror() }
}
