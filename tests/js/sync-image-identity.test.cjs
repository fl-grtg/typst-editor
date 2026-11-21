const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const read = name => fs.readFileSync('web/js/' + name, 'utf8')
const preview = read('50-preview.js')
const repeatSlice = preview.slice(preview.indexOf('function pvImgRepeat'), preview.indexOf('const PV_LINK_SCHEME'))
const sigSlice = preview.slice(preview.indexOf('function pvImgSig'), preview.indexOf('function pvHasImages'))
const ctx = vm.createContext({})
vm.runInContext(repeatSlice, ctx)

const box = (sig, id) => ({ x0: 20, y0: 40, x1: 120, y1: 90, w: 100, h: 50, id, sig })

test('an image only counts as repeated when its content matches', () => {
  ctx.pvImgs = [[box('same', 'a')], [box('other', 'b')]]
  assert.equal(ctx.pvImgRepeat(0, ctx.pvImgs[0][0]), false) // two different images at the same spot
  ctx.pvImgs[1][0].sig = 'same'
  assert.equal(ctx.pvImgRepeat(0, ctx.pvImgs[0][0]), true) // the logo itself repeats
  ctx.pvImgs = [[{ ...box('', 'a'), sig: undefined }], [{ ...box('', 'b'), sig: undefined }]]
  assert.equal(ctx.pvImgRepeat(0, ctx.pvImgs[0][0]), true) // no fingerprint: keep the old geometry rule
})

test('a decoration box without a source cannot steal the first image line', () => {
  const settings = read('90-settings.js')
  const c = vm.createContext({
    cm: { state: { doc: { lines: 30 } } },
    pvTexts: [[]],
    pvImgBoxes: () => [
      { page: 0, x0: 10, y0: 20, x1: 60, y1: 40, w: 50, h: 20, id: 'deco', sig: 'deco', vh: 1000 },
      { page: 0, x0: 10, y0: 300, x1: 60, y1: 340, w: 50, h: 40, id: 'img1', sig: 'one', vh: 1000 },
      { page: 0, x0: 10, y0: 600, x1: 60, y1: 640, w: 50, h: 40, id: 'img2', sig: 'two', vh: 1000 },
    ],
    pvSrcImages: () => [{ key: '', line: 10, order: 10 }, { key: '', line: 20, order: 20 }],
    pvImgs: [[{ id: 'box' }]],
    pvSrcSig: () => 0,
    pvOutlineGen: 0,
    shownN: 0,
    activeFile: '',
    pvImgHint: () => null,
    pvTextSrcLine: () => null,
    pvPageHint: (pi, total, n, sec, frac) => Math.round(frac * total),
    pvSecAtY: () => null,
  })
  vm.runInContext(settings.slice(settings.indexOf('function pvImgMatch'), settings.indexOf('function pvImgLineHit')), c)
  assert.equal(JSON.stringify(c.pvImgMatch().map(m => [m.id, m.src.line])), JSON.stringify([['img1', 10], ['img2', 20]]))
})
test('inline images hash their own pixels and large images resolve from commonObjs', async () => {
  const OPS = { save: 1, restore: 2, transform: 3, paintFormXObjectBegin: 4, paintFormXObjectEnd: 5, paintImageXObject: 6, paintJpegXObject: 7, paintInlineImageXObject: 8, paintImageMaskXObject: 9 }
  const c = vm.createContext({ window: { pdfjsLib: { OPS } }, pdfjsLib: { OPS } })
  vm.runInContext(preview.slice(preview.indexOf('function pvMat'), preview.indexOf('const PV_LINK_SCHEME')), c)
  const view = { transform: [1, 0, 0, 1, 0, 0], width: 100, height: 100 }
  const inline = data => ({
    getOperatorList: async () => ({ fnArray: [OPS.transform, OPS.paintInlineImageXObject], argsArray: [[10, 0, 0, 10, 0, 0], [{ width: 4, height: 4, kind: 2, data }]] }),
    objs: { get: () => { throw new Error('inline images have no object store entry') } },
  })
  const one = await c.pvPageImgs(inline(new Uint8Array([1, 2, 3, 4, 5, 6])), view)
  const other = await c.pvPageImgs(inline(new Uint8Array([9, 2, 3, 4, 5, 6])), view)
  assert.equal(one.length, 1)
  assert.equal(one[0].id, 'inline')
  assert.ok(one[0].sig)
  assert.notEqual(one[0].sig, other[0].sig) // two different inline pictures are not one decoration
  c.pvImgs = [one, other]
  assert.equal(c.pvImgRepeat(0, one[0]), false) // same spot, different pixels: no repeat

  const pixels = new Uint8Array([7, 7, 7, 7])
  const large = {
    getOperatorList: async () => ({ fnArray: [OPS.transform, OPS.paintImageXObject], argsArray: [[10, 0, 0, 10, 0, 0], ['g_1']] }),
    objs: { get: () => { throw new Error('only commonObjs has it') } },
    commonObjs: { get: id => id === 'g_1' ? { width: 8, height: 8, data: pixels } : null },
  }
  const box = await c.pvPageImgs(large, view)
  assert.equal(box.length, 1)
  assert.ok(box[0].sig) // a large image is resolved from commonObjs, not dropped to geometry
})
test('rendered image boxes carry a content fingerprint', async () => {
  const OPS = { save: 1, restore: 2, transform: 3, paintFormXObjectBegin: 4, paintFormXObjectEnd: 5, paintImageXObject: 6, paintJpegXObject: 7, paintInlineImageXObject: 8, paintImageMaskXObject: 9 }
  const c = vm.createContext({ window: { pdfjsLib: { OPS } }, pdfjsLib: { OPS } })
  vm.runInContext(preview.slice(preview.indexOf('function pvMat'), preview.indexOf('function pvImgRepeat')), c)
  vm.runInContext(sigSlice, c)
  const page = data => ({
    getOperatorList: async () => ({ fnArray: [OPS.transform, OPS.paintImageXObject], argsArray: [[10, 0, 0, 10, 0, 0], ['img1']] }),
    objs: { get: () => ({ width: 32, height: 12, kind: 2, data }) },
  })
  const view = { transform: [1, 0, 0, 1, 0, 0], width: 100, height: 100 }
  const one = await c.pvPageImgs(page(new Uint8Array([1, 2, 3, 4, 5, 6])), view)
  const again = await c.pvPageImgs(page(new Uint8Array([1, 2, 3, 4, 5, 6])), view)
  const other = await c.pvPageImgs(page(new Uint8Array([1, 2, 3, 9, 5, 6])), view)
  assert.equal(one.length, 1)
  assert.ok(one[0].sig)
  assert.equal(one[0].sig, again[0].sig)
  assert.notEqual(one[0].sig, other[0].sig)
  assert.equal(c.pvImgSig({ objs: { get: () => { throw new Error('gone') } } }, 'img1'), '')
})
