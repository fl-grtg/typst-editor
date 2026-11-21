// Shared by the sync tests: the sync map with the globals it reads (paper pages, source list) as plain test state.
const fs = require('node:fs')
const vm = require('node:vm')
const read = name => fs.readFileSync('web/js/' + name, 'utf8')
const settings = read('90-settings.js')
const MAP_SRC = settings.slice(settings.indexOf('function pvMathNorm'), settings.indexOf('function pvSrcMath')) + read('89-sync-map.js') + `
var pvTexts = [], pvLinks = [], pvTextDone = [], pvMetaGen = 0, smDocs = []
function pvSrcList() { return smDocs }
function isTplKey(k) { return String(k).startsWith('@tpl/') }
function tabName(k) { k = String(k); return (k.startsWith('@tpl/') ? k.slice(5) : k) || 'main.typ' }
function pvMathMatch() { return [] }
function pvImgMatch() { return [] }
`
function loadMap(c) { vm.runInContext(MAP_SRC, c); if (!('activeFile' in c)) vm.runInContext('var activeFile = ""', c); return c }
function useDoc(c, lines, pages, more = []) { // the open tab shows `lines`, the paper shows `pages`
  c.pvTexts = pages
  c.pvLinks = pages.map(() => [])
  c.pvTextDone = pages.map(() => true)
  c.pvMetaGen++
  c.smDocs = [{ key: '', text: Array.isArray(lines) ? lines.join('\n') : lines }, ...more]
}
module.exports = { loadMap, useDoc }
