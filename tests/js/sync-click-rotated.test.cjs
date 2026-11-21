const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const vm = require('node:vm')
const src = fs.readFileSync('web/js/90-settings.js', 'utf8')
const ctx = vm.createContext({})
vm.runInContext(src.slice(src.indexOf('function pvCharW'), src.indexOf("$('preview').addEventListener('click'")), ctx)

// One rotated run as PDF.js reports it (viewport units at render scale 2):
// 20deg, baseline origin (481.9, 608.88), 240.2 wide, 22 high.
const IT = {
  s: 'rotated marker words here', rot: true, ang: 20 * Math.PI / 180,
  x0: 481.9, y0: 608.87872, w: 240.2, h: 22, vw: 1190.5512, vh: 1683.7796,
}
const CSS_W = 398.984375, CSS_H = 564.125
const sx = CSS_W / IT.vw, sy = CSS_H / IT.vh

// u along the baseline, v upward from it: the run's own coordinate frame
function pt(fu, fv) {
  const c = Math.cos(IT.ang), s = Math.sin(IT.ang)
  return [(IT.x0 + IT.w * fu * c + IT.h * fv * s) * sx, (IT.y0 + IT.w * fu * s - IT.h * fv * c) * sy]
}
const dist = (fu, fv) => ctx.pvItemDist(IT, ...pt(fu, fv), sx, sy)
const col = (fu, fv) => ctx.pvClickCol(IT, ...pt(fu, fv), CSS_W, CSS_H, 1191, null)

test('points inside the rotated band have no distance', () => {
  for (const [fu, fv] of [[0.5, 0.5], [0.05, 0.5], [0.95, 0.5], [0.5, 0.1], [0.5, 0.9]]) {
    assert.equal(dist(fu, fv), 0, `fu=${fu} fv=${fv}`)
  }
})

test('the axis-aligned centre of a rotated run is outside its band', () => {
  const x = (IT.x0 + IT.w / 2) * sx, y = (IT.y0 - IT.h / 2) * sy
  assert.ok(ctx.pvItemDist(IT, x, y, sx, sy) > 0, 'an unrotated box would swallow the click')
})

test('a click beyond either end is farther than one inside', () => {
  assert.ok(dist(-0.1, 0.5) > 0)
  assert.ok(dist(1.1, 0.5) > 0)
  assert.ok(dist(0.5, 1.8) > dist(0.5, 0.5))
})

test('a click projects onto the baseline to the clicked letter', () => {
  assert.ok(col(0.5, 0.5) >= 11 && col(0.5, 0.5) <= 15, `centre: ${col(0.5, 0.5)}`)
  assert.ok(col(0.1, 0.5) >= 1 && col(0.1, 0.5) <= 6, `start: ${col(0.1, 0.5)}`)
  assert.ok(col(0.85, 0.5) >= 19 && col(0.85, 0.5) <= 23, `end: ${col(0.85, 0.5)}`)
  assert.ok(col(0.85, 0.5) > col(0.1, 0.5))
})

test('a zero-width rotated run has no letter to land on', () => {
  assert.equal(ctx.pvClickCol({ ...IT, w: 0 }, ...pt(0.5, 0.5), CSS_W, CSS_H, 1191, null), 0)
})

test('an unrotated run still uses its horizontal box', () => {
  const flat = { s: 'plain words here', rot: false, ang: 0, x0: 100, y: 200, y0: 200, w: 120, h: 12, vw: 600, vh: 800 }
  assert.equal(ctx.pvItemDist(flat, 60, 100, 0.5, 0.5), 0)
  assert.ok(ctx.pvClickCol(flat, 60, 100, 300, 400, 600, null) > 0)
})
