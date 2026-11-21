"""Klick-Sync für Text ohne eigene Buchstaben im Quelltext und für Link-Ziele.

Erzeugter Text (#lorem, Funktionen, Schleifen), Literaturverzeichnis-Felder,
getrennte Wörter, Überschriften mit Markup sowie Links auf Abbildung,
Gleichung, Zitat und Fußnote. Die Brüche sind gegen das Typst-0.15.1-Layout
vermessen; ein Toolchain-Wechsel soll hier laut scheitern.
"""
import re
import struct
import zlib

from helpers import create_doc, put_source, register
from playwright.sync_api import expect

PREVIEW_TIMEOUT = 60_000

MAIN = """#set text(lang: "de")
#set par(justify: true)
#set heading(numbering: "1.1")
#set math.equation(numbering: "(1)")
#let greet(name) = [Hallo #name Freund]
#outline()
= Ergebnisse *Fett* Teil
Die Rechtsschutzversicherungsgesellschaften verhandeln Arbeitsunfähigkeitsbescheinigungen täglich und schreiben lange Briefe an alle Versicherten im ganzen Land.

#greet("Wanda")

#for p in ("Ada", "Grace") [Person #p gelistet. ]

#lorem(20)

Ein Satz mit Fußnote#footnote[Der Fußnotentext steht unten.] im Absatz.
$ E = m c^2 $ <einstein>
Siehe @einstein und @fig sowie @knuth hier.
#figure(image("dot.png", width: 60pt), caption: [Punktbild klein]) <fig>
#bibliography("refs.bib")
"""
LINES = MAIN.split("\n")

BIB = b"""@book{knuth,
  title={The TeXbook},
  author={Knuth, Donald},
  year={1984},
  publisher={Addison-Wesley}
}
"""

HYPHEN = """#set text(lang: "de")
#set par(justify: true)
= Deutsche Silbentrennung
Die Donaudampfschifffahrtsgesellschaftskapitänsmütze ist ein sehr langes Wort, das in schmalen Spalten getrennt werden muss. Außerdem gibt es „Anführungszeichen" und Umlaute wie Äpfel, Öl und Übermut in dieser Zeile. Die Rechtsschutzversicherungsgesellschaften verhandeln Arbeitsunfähigkeitsbescheinigungen täglich.
"""

FORMULA_LATE = (
    "#for i in range(20) [#lorem(5) #pagebreak()]\n"
    "$ integral_0^1 x^2 dif x = 1/3 $\n"
    + "".join(f"\nTail paragraph number {i} closes the document.\n" for i in range(160))
)

PAGE_IN_VIEW = """(n) => {
  const pv = document.getElementById('preview')
  const s = pv.querySelector('.pvPage[data-page="' + n + '"]')
  if (!s) return false
  const pr = pv.getBoundingClientRect(), sr = s.getBoundingClientRect()
  return sr.bottom > pr.top + 40 && sr.top < pr.bottom - 40
}"""


def _png(w=32, h=12):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    raw = b''.join(b'\x00' + b'\x1e\x1e\x1e' * w for _ in range(h))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def _pos(page):
    m = re.match(r"Ln (\d+):(\d+)", page.locator("#pos").inner_text())
    assert m, "status line has no line:column"
    return int(m.group(1)), int(m.group(2)) - 1  # 0-based column


def _word(text, col):
    start = col
    while start > 0 and text[start - 1].isalnum():
        start -= 1
    end = col
    while end < len(text) and text[end].isalnum():
        end += 1
    return text[start:end]


def _project(page, title):
    return next(d for d in page.request.get('/api/docs').json()['own'] if d['title'] == title)


def _setup(page, slug, title, source, files=()):
    register(page, slug)
    create_doc(page, title)
    if files:
        doc = _project(page, title)
        for name, mime, data in files:
            assert page.request.post(f"/api/docs/{doc['id']}/files", multipart={
                'f': {'name': name, 'mimeType': mime, 'buffer': data}}).ok
        page.reload()
        page.wait_for_function('window.__booted === true')
        page.locator('aside .doc.sub', has_text=title).first.click()
    put_source(page, source)
    expect(page.locator('#preview .pvPage[data-done] canvas').first).to_be_visible(timeout=PREVIEW_TIMEOUT)
    page.wait_for_timeout(1500)  # text index, outline and link layer of every page


def _click(page, page_no, fx, fy):
    page.evaluate("""([n, fy]) => {
      const pv = document.getElementById('preview'), s = pv.querySelector('.pvPage[data-page="' + n + '"]')
      const sr = s.getBoundingClientRect(), pr = pv.getBoundingClientRect()
      pv.scrollTop += sr.top - pr.top + sr.height * fy - pv.clientHeight / 2
    }""", [page_no, fy])
    page.wait_for_timeout(400)
    canvas, box = page.locator(f'#preview .pvPage[data-page="{page_no}"][data-done] canvas'), None
    for _ in range(40):  # a follow-up render may swap the canvas right after it was visible
        try:
            expect(canvas).to_be_visible(timeout=PREVIEW_TIMEOUT)
            box = canvas.bounding_box(timeout=2_000)
        except Exception:
            box = None
        if box:
            break
        page.wait_for_timeout(150)
    assert box, f'page {page_no} has no box'
    page.mouse.click(box['x'] + box['width'] * fx, box['y'] + box['height'] * fy)
    page.wait_for_timeout(800)


def _fixture(page, slug):
    _setup(page, slug, 'Fallback sync doc', MAIN, files=(
        ('dot.png', 'image/png', _png()),
        ('refs.bib', 'text/plain', BIB),
    ))


def test_generated_text_lands_on_the_call_that_built_it(page):
    _fixture(page, 'e2e_sync_generated')

    _click(page, 1, 0.1927, 0.2200)  # "Wanda" in the text #greet("Wanda") built
    line, col = _pos(page)
    assert line == 10 and _word(LINES[9], col) == 'Wanda', f"function argument: Ln {line}:{col}"

    _click(page, 1, 0.1819, 0.2443)  # "Ada" from the #for loop
    line, col = _pos(page)
    assert line == 12 and _word(LINES[11], col) == 'Ada', f"loop value: Ln {line}:{col}"

    _click(page, 1, 0.3000, 0.2686)  # the first #lorem row: no word of it is in the source
    line, col = _pos(page)
    assert line == 14, f"lorem: Ln {line}:{col}"

    _click(page, 1, 0.1800, 0.4530)  # the generated "Bibliografie" title
    line, col = _pos(page)
    assert line == 20, f"bibliography title: Ln {line}:{col}"

    _click(page, 1, 0.2000, 0.0868)  # the generated outline title
    line, col = _pos(page)
    assert line == 6, f"outline title: Ln {line}:{col}"


def test_a_heading_with_markup_keeps_the_clicked_word(page):
    _fixture(page, 'e2e_sync_head_mark')

    _click(page, 1, 0.2950, 0.1576)  # "Fett" inside "= Ergebnisse *Fett* Teil"
    line, col = _pos(page)
    assert line == 7 and _word(LINES[6], col) == 'Fett', f"heading word: Ln {line}:{col}"


def test_reference_links_jump_to_their_target(page):
    _fixture(page, 'e2e_sync_links')

    _click(page, 1, 0.3400, 0.3609)  # "Abbildung 1" -> the figure, not the paragraph above it
    line, col = _pos(page)
    assert line == 19, f"figure link: Ln {line}:{col}"

    _click(page, 1, 0.2100, 0.3609)  # "Gleichung 1" -> the formula, not the paragraph after it
    line, col = _pos(page)
    assert line == 17, f"equation link: Ln {line}:{col}"

    _click(page, 1, 0.1371, 0.9103)  # footnote back-link: beside its #footnote call
    line, col = _pos(page)
    assert line == 16 and abs(col - LINES[15].index('#footnote')) <= 1, f"footnote back-link: Ln {line}:{col}"

    _click(page, 1, 0.4496, 0.3609)  # "[1]" -> the entry in refs.bib
    expect(page.locator('#tabs button.tab[aria-selected="true"]')).to_have_text(re.compile(r'refs\.bib'))
    line, col = _pos(page)
    assert 1 <= line <= 6, f"citation link: Ln {line}:{col}"


def test_a_bibliography_entry_opens_its_field_in_the_bib_file(page):
    _fixture(page, 'e2e_sync_bib_field')

    _click(page, 1, 0.3627, 0.4741)  # "Addison" of ". Addison-Wesley, 1984."
    expect(page.locator('#tabs button.tab[aria-selected="true"]')).to_have_text(re.compile(r'refs\.bib'))
    line, col = _pos(page)
    assert line == 5, f"publisher field: Ln {line}:{col}"


def test_a_word_split_by_hyphenation_maps_to_the_whole_source_word(page):
    _setup(page, 'e2e_sync_hyphen', 'Hyphen sync doc', HYPHEN)
    lines = HYPHEN.split("\n")

    _click(page, 1, 0.1862, 0.1591)  # "higkeitsbescheinigungen": the PDF text drops the hyphen
    line, col = _pos(page)
    assert line == 4 and _word(lines[3], col) == 'Arbeitsunfähigkeitsbescheinigungen', f"second half: Ln {line}:{col}"

    _click(page, 1, 0.8442, 0.1420)  # "Arbeitsunfä" at the end of the line above
    line, col = _pos(page)
    assert line == 4 and _word(lines[3], col) == 'Arbeitsunfähigkeitsbescheinigungen', f"first half: Ln {line}:{col}"


def test_cursor_on_a_formula_far_below_shows_its_page(page):
    _setup(page, 'e2e_sync_late_math', 'Late formula doc', FORMULA_LATE)
    page.wait_for_timeout(3000)  # every page indexed, most of them never drawn
    pages = page.locator('#preview .pvPage').count()
    assert pages >= 24, pages

    page.click('#cm .cm-content')
    page.keyboard.press('ControlOrMeta+Home')
    page.keyboard.press('ArrowDown')  # line 2: the display formula
    page.wait_for_timeout(1500)
    line, _ = _pos(page)
    assert line == 2, line
    assert page.evaluate(PAGE_IN_VIEW, 21), 'cursor on the formula did not show the formula page'
