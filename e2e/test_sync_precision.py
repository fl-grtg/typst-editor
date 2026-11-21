"""Klick-Sync trifft Objekte und Buchstaben: Bilder, Formeln, Tabellen, Raw, textlose Seiten."""
import re
import struct
import zlib

from helpers import create_doc, put_source, register
from playwright.sync_api import expect

PREVIEW_TIMEOUT = 60_000
PAGES = 6

# Positions below are measured against the audited Typst 0.15.x layout. A new
# Typst version that moves text must fail this fixture loudly, not silently.
MAIN = '''#import "lib/util.typ": unused

= Alpha

Zebra marker line with the word ORANGE inside it.

#figure(image("dot.png", width: 90pt), caption: [Dot caption here])

#pagebreak()

#image("dot.png", width: 200pt)

#pagebreak()

$ sum_(i=1)^n i = (n(n+1))/2 $

#pagebreak()

#table(columns: 2, [Alpha cell], [Beta cell], [Gamma cell], [Delta cell])

#pagebreak()

```python
def marker_raw() -> int:
    return 424242
```

#pagebreak()

#include "part.typ"

= Omega

Omega tail line here.
'''
PART = '''= Chapter One

Chapter text before its image.

#image("dot.png", width: 120pt)

Chapter tail after the image.
'''
BLANK_PAGE = '''#import "lib/util.typ": unused

= Alpha

Alpha body.

#pagebreak()

#pagebreak()

= Beta

Beta tail line.
'''
LINES = MAIN.split('\n')

PAGE_IN_VIEW = """(n) => {
  const pv = document.getElementById('preview')
  const s = pv.querySelector('.pvPage[data-page="' + n + '"]')
  if (!s) return false
  const pr = pv.getBoundingClientRect(), sr = s.getBoundingClientRect()
  return sr.top >= pr.top - 5 && sr.top < pr.bottom
}"""


def _png(w=32, h=12):
    def chunk(kind, data):
        body = struct.pack('>I', len(data)) + kind + data
        return body + struct.pack('>I', zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b''.join(b'\x00' + bytes([30, 60, 90] * w) for _ in range(h))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def _line(page):
    m = re.match(r"Ln (\d+):", page.locator('#pos').inner_text())
    assert m, 'status line has no line number'
    return int(m.group(1))


def _col(page):
    m = re.match(r"Ln \d+:(\d+)", page.locator('#pos').inner_text())
    assert m, 'status line has no column'
    return int(m.group(1)) - 1  # status is 1-based, source columns are 0-based


def _word(text, col):
    start = col
    while start > 0 and text[start - 1] not in ' \t':
        start -= 1
    end = col
    while end < len(text) and text[end] not in ' \t':
        end += 1
    return text[start:end]


def _ready(page, pages=PAGES, headings=2):
    expect(page.locator('#preview .pvPage[data-done] canvas').first).to_be_visible(timeout=PREVIEW_TIMEOUT)
    expect(page.locator('#preview .pvPage')).to_have_count(pages, timeout=PREVIEW_TIMEOUT)
    expect(page.locator('#ol .pg')).to_have_count(headings, timeout=PREVIEW_TIMEOUT)


def _setup(page, slug, title, source, pages=PAGES, headings=2, resources=True, extra_typ=None):
    register(page, slug)
    create_doc(page, title)
    doc = _project(page, title)
    if resources:
        assert page.request.post(f"/api/docs/{doc['id']}/files", multipart={
            'f': {'name': 'dot.png', 'mimeType': 'image/png', 'buffer': _png()}}).ok
        assert page.request.post(f"/api/projects/{doc['project_id']}/resources",
                                 data={'name': 'lib/util.typ', 'content': '#let unused = 1'}).ok
        assert page.request.post(f"/api/projects/{doc['project_id']}/resources",
                                 data={'name': 'part.typ', 'content': PART}).ok
    if extra_typ:  # a second source file: the multi-source guard must be exercised, not bypassed
        assert page.request.post(f"/api/docs/{doc['id']}/files", multipart={
            'f': {'name': extra_typ, 'mimeType': 'text/plain', 'buffer': b'= Extra\n'}}).ok
    page.reload()
    page.wait_for_function('window.__booted === true')
    page.locator('aside .doc.sub', has_text=title).first.click()
    put_source(page, source)
    _ready(page, pages, headings)
    return doc


def _click(page, page_no, fx, fy):
    page.evaluate("""([n, fy]) => {
      const pv = document.getElementById('preview'), s = pv.querySelector('.pvPage[data-page="' + n + '"]')
      const sr = s.getBoundingClientRect(), pr = pv.getBoundingClientRect()
      pv.scrollTop += sr.top - pr.top + sr.height * fy - pv.clientHeight / 2
    }""", [page_no, fy])
    page.wait_for_timeout(400)
    canvas = page.locator(f'#preview .pvPage[data-page="{page_no}"] canvas')
    box = canvas.bounding_box()
    assert box, f'page {page_no} has no box'
    page.mouse.click(box['x'] + box['width'] * fx, box['y'] + box['height'] * fy)
    page.wait_for_timeout(700)


def _project(page, title):
    return next(d for d in page.request.get('/api/docs').json()['own'] if d['title'] == title)


def test_text_object_clicks_hit_the_exact_source_line_and_letter(page):
    _setup(page, 'e2e_sync_exact', 'Exact sync doc', MAIN)

    _click(page, 1, 0.41, 0.108)  # ORANGE in the prose line
    assert _line(page) == 5, _line(page)
    assert _word(LINES[4], _col(page)) == 'ORANGE'

    _click(page, 1, 0.545, 0.172)  # caption word, after the generated "Figure 1: "
    assert _line(page) == 7, _line(page)
    assert _word(LINES[6], _col(page)) == 'caption'

    _click(page, 3, 0.434, 0.097)  # the sum glyph of the display formula
    assert _line(page) == 15 and _col(page) == 2
    _click(page, 3, 0.527, 0.106)  # the last denominator glyph
    assert _line(page) == 15 and _col(page) == 27

    _click(page, 4, 0.148, 0.09)  # first table cell
    assert _line(page) == 19, _line(page)
    assert 20 <= _col(page) <= 24 and LINES[18][_col(page)] in 'Alpha', _col(page)

    _click(page, 5, 0.30, 0.087)  # "int" in the fenced raw block
    assert _line(page) == 24, _line(page)
    assert 20 <= _col(page) <= 22 and LINES[23][_col(page)] in 'int', _col(page)

def test_a_click_on_an_image_lands_on_its_image_call(page):
    _setup(page, 'e2e_sync_image_click', 'Image click doc', MAIN)

    _click(page, 2, 0.287, 0.128)  # the image-only page
    assert _line(page) == 11 and _col(page) == 0

    _click(page, 6, 0.22, 0.157)  # image inside the included file
    expect(page.locator('#tabs button.tab[aria-selected="true"]')).to_have_text(re.compile('part\\.typ'))
    assert _line(page) == 5 and _col(page) == 0

def test_a_click_in_blank_space_reaches_the_section_start(page):
    _setup(page, 'e2e_sync_section', 'Section fallback doc', BLANK_PAGE, pages=3, extra_typ='extra.typ')

    page.click('#cm .cm-content')
    page.keyboard.press('ControlOrMeta+Home')
    page.wait_for_timeout(700)
    _click(page, 2, 0.5, 0.5)  # empty page between Alpha and Beta
    assert _line(page) == 3, _line(page)  # section start, not the page ratio

def test_cursor_on_an_image_line_shows_its_page(page):
    _setup(page, 'e2e_sync_img_cursor', 'Image cursor doc', MAIN)

    page.click('#cm .cm-content')
    page.keyboard.press('ControlOrMeta+Home')
    page.wait_for_timeout(700)
    for _ in range(20):  # wrapped lines may need more than 10 steps
        if _line(page) >= 11:
            break
        page.keyboard.press('ArrowDown')
        page.wait_for_timeout(60)
    assert _line(page) == 11, _line(page)
    page.wait_for_timeout(900)
    assert page.evaluate(PAGE_IN_VIEW, 2), 'cursor on the image line did not show its page'

def test_a_textless_page_scrolls_the_editor_to_its_line(page):
    register(page, 'e2e_sync_textless')
    create_doc(page, 'Textless page doc')
    doc = _project(page, 'Textless page doc')
    assert page.request.post(f"/api/docs/{doc['id']}/files", multipart={
        'f': {'name': 'dot.png', 'mimeType': 'image/png', 'buffer': _png()}}).ok
    filler = '\n'.join(f'Filler line {i:03d}.' for i in range(80))
    source = filler + '\n\n#pagebreak()\n\n#image("dot.png", width: 200pt)\n\n#pagebreak()\n\nLast tail line.\n'
    page.reload()
    page.wait_for_function('window.__booted === true')
    page.locator('aside .doc.sub', has_text='Textless page doc').first.click()
    put_source(page, source)
    expect(page.locator('#preview .pvPage[data-done] canvas').first).to_be_visible(timeout=PREVIEW_TIMEOUT)
    page.wait_for_timeout(1500)

    pages = page.locator('#preview .pvPage').count()
    assert pages >= 3, pages
    page.click('#cm .cm-content')
    page.keyboard.press('ControlOrMeta+Home')
    page.wait_for_timeout(700)
    before = page.evaluate("() => document.querySelector('#cm .cm-scroller').scrollTop")

    slot = page.locator(f'#preview .pvPage[data-page="{pages - 1}"]')  # image page: tail page minus one
    slot.scroll_into_view_if_needed()
    page.wait_for_timeout(1500)  # reader scroll -> follow estimate
    after = page.evaluate("() => document.querySelector('#cm .cm-scroller').scrollTop")
    assert after > before + 200, f'textless page did not move the editor: {before} -> {after}'
    assert page.evaluate(PAGE_IN_VIEW, pages - 1)
