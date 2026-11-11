const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')

test('the preview toolbar keeps both toggles and the zoom group', () => {
  const html = fs.readFileSync('web/index.shell.html', 'utf8')
  let at = -1
  for (const id of ['followBtn', 'syncBtn', 'zMinus', 'zoomV', 'zPlus', 'fitBtn']) {
    const i = html.indexOf(`id="${id}"`)
    assert.ok(i > at, `${id} is missing or out of order in the preview toolbar`)
    at = i
  }
})
