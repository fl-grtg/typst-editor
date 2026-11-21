"""Klick-Sync deckt die häufigen Typst-Konstrukte ab: Inline-Markup, Mathe,
Listen, Fußnoten, Spalten, Blöcke, Kopf/Fuß und rotierter Text.

Die Brüche sind gegen das gepinnte Typst-0.15.x-Layout gemessen. Ein Wechsel
der Toolchain soll hier laut scheitern, nicht still falsch klicken.
"""
import re

from helpers import create_doc, register
from playwright.sync_api import expect

PREVIEW_TIMEOUT = 60_000

INLINE = """= Inline

Plain *bold words* and _emph words_ and `code words` here.

Inline formula $x + y = z$ inside a line.

Escaped \\# hash and "smart quotes" -- dash.
"""

LISTS = """= Lists

- First bullet item here
- Second bullet with *bold words*
  - Nested bullet item here
+ First numbered item here
+ Second numbered item here
"""

NOTES = """= Notes

Body line with a note.#footnote[Footnote text lives here.]

Body line after the note.
"""

COLUMNS = """#columns(2)[
Left column marker LEFTWORD starts the line.

#colbreak()

Right column marker RIGHTWORD starts the line.
]
"""

BLOCKS = """= Blocks

#quote(block: true)[Quoted block line here.]

#box(stroke: 1pt, inset: 6pt)[Boxed text line here.]

#place(top + right, dx: -3cm, dy: 1cm)[Placed marker text]

#scale(130%, reflow: true)[Scaled words here.]

After the placed boxes.
"""

HEADER = """#set page(header: [Header marker text], footer: [Footer marker text])

= Header page

Header body line here.
"""

ROTATED = """= Rotated

Before the turn.

#place(top + left, dx: 6cm, dy: 8cm)[#rotate(20deg, reflow: true)[rotated marker words here]]

After the turn.
"""


def _fill(page, source):
    page.click("#cm .cm-content")
    page.keyboard.press("ControlOrMeta+A")
    assert page.evaluate("(t) => document.execCommand('insertText', false, t)", source)


def _ready(page):
    expect(page.locator("#preview .pvPage[data-done] canvas").first).to_be_visible(timeout=PREVIEW_TIMEOUT)
    expect(page.locator("#preview .pvPage")).to_have_count(1, timeout=PREVIEW_TIMEOUT)
    page.wait_for_timeout(700)


def _open(page, slug, title, source):
    register(page, slug)
    create_doc(page, title)
    _fill(page, source)
    _ready(page)


def _settle(page):
    page.wait_for_function(
        """() => new Promise(done => {
          const pv = document.getElementById('preview')
          let last = pv.scrollTop, calm = 0
          const tick = () => {
            if (Math.abs(pv.scrollTop - last) < 0.5) calm++
            else calm = 0
            last = pv.scrollTop
            if (calm >= 3) done(true)
            else setTimeout(tick, 80)
          }
          tick()
        })""",
        timeout=10_000,
    )


def _click(page, fx, fy):
    _settle(page)  # a link jump or follow scroll must stop before the box is measured
    slot = page.locator('#preview .pvPage[data-page="1"]')
    slot.scroll_into_view_if_needed()
    box = slot.locator("canvas").bounding_box()  # re-read: an earlier jump may have scrolled the preview
    assert box
    page.mouse.click(box["x"] + box["width"] * fx, box["y"] + box["height"] * fy)
    page.wait_for_timeout(450)


def _pos(page):
    m = re.match(r"Ln (\d+):(\d+)", page.locator("#pos").inner_text())
    assert m, "status line has no line:column"
    return int(m.group(1)), int(m.group(2))


def test_inline_markup_and_math_land_on_the_clicked_letter(page):
    _open(page, "e2e_cover_inline", "Cover inline", INLINE)

    _click(page, 0.2081, 0.1078)
    line, col = _pos(page)
    assert line == 3 and 10 <= col <= 16, f"bold word: Ln {line}:{col}"

    _click(page, 0.3350, 0.1078)
    line, col = _pos(page)
    assert line == 3 and 27 <= col <= 33, f"emph word: Ln {line}:{col}"

    _click(page, 0.4339, 0.1091)
    line, col = _pos(page)
    assert line == 3 and 42 <= col <= 47, f"raw word: Ln {line}:{col}"

    _click(page, 0.2369, 0.1324)  # the 𝑥 glyph of the inline formula
    line, col = _pos(page)
    assert line == 5 and 16 <= col <= 19, f"inline math: Ln {line}:{col}"

    _click(page, 0.2797, 0.1567)  # escaped hash line
    line, col = _pos(page)
    assert line == 7 and 15 <= col <= 35, f"escaped line: Ln {line}:{col}"


def test_lists_click_item_text_not_the_generated_marker(page):
    _open(page, "e2e_cover_lists", "Cover lists", LISTS)

    for fx, fy, want in (
        (0.2135, 0.1078, 3),
        (0.3258, 0.1249, 4),
        (0.2387, 0.1420, 5),
        (0.2365, 0.1663, 6),
        (0.2465, 0.1834, 7),
    ):
        _click(page, fx, fy)
        line, col = _pos(page)
        assert line == want, f"click at {fx}/{fy}: Ln {line}:{col}, want line {want}"


def test_footnote_reference_text_and_marker_all_point_at_the_note(page):
    _open(page, "e2e_cover_notes", "Cover notes", NOTES)

    _click(page, 0.2021, 0.1078)
    line, col = _pos(page)
    assert line == 3 and 10 <= col <= 30, f"body before the note: Ln {line}:{col}"

    _click(page, 0.2880, 0.1078)  # the generated superscript
    line, col = _pos(page)
    assert line == 3, f"superscript reference: Ln {line}:{col}"

    _click(page, 0.2099, 0.1321)
    line, col = _pos(page)
    assert line == 5, f"line after the note: Ln {line}:{col}"

    _click(page, 0.2174, 0.9103)  # the note body at the page bottom
    line, col = _pos(page)
    assert line == 3 and 33 <= col <= 58, f"footnote text: Ln {line}:{col}"

    _click(page, 0.1372, 0.9103)  # the generated marker before the note body
    line, col = _pos(page)
    assert line == 3, f"footnote marker: Ln {line}:{col}"


def test_two_columns_keep_their_own_source_line(page):
    _open(page, "e2e_cover_columns", "Cover columns", COLUMNS)

    _click(page, 0.2988, 0.0862)
    line, col = _pos(page)
    assert line == 2, f"left column: Ln {line}:{col}"

    _click(page, 0.6897, 0.0862)
    line, col = _pos(page)
    assert line == 6, f"right column: Ln {line}:{col}"

    _click(page, 0.5313, 0.1033)  # the wrapped tail of the right column
    line, col = _pos(page)
    assert line == 6 and col > 30, f"wrapped column tail: Ln {line}:{col}"


def test_quote_box_place_and_scale_map_to_their_own_lines(page):
    _open(page, "e2e_cover_blocks", "Cover blocks", BLOCKS)

    for fx, fy, want in (
        (0.2253, 0.1294, 3),
        (0.2065, 0.1686, 5),
        (0.6672, 0.1199, 7),
        (0.2104, 0.2007, 9),
        (0.2053, 0.2269, 11),
    ):
        _click(page, fx, fy)
        line, col = _pos(page)
        assert line == want, f"click at {fx}/{fy}: Ln {line}:{col}, want line {want}"


def test_header_and_footer_map_to_the_page_setup_line(page):
    _open(page, "e2e_cover_header", "Cover header", HEADER)

    _click(page, 0.1927, 0.0524)
    line, col = _pos(page)
    assert line == 1 and 20 <= col <= 45, f"header: Ln {line}:{col}"

    _click(page, 0.1920, 0.0868)
    line, col = _pos(page)
    assert line == 3, f"heading: Ln {line}:{col}"

    _click(page, 0.2047, 0.1078)
    line, col = _pos(page)
    assert line == 5, f"body: Ln {line}:{col}"

    _click(page, 0.1897, 0.9431)
    line, col = _pos(page)
    assert line == 1 and 50 <= col <= 70, f"footer: Ln {line}:{col}"


def test_rotated_text_is_a_click_target_with_letter_precision(page):
    _open(page, "e2e_cover_rotated", "Cover rotated", ROTATED)
    base = ROTATED.splitlines()[4].index("rotated marker words here")

    # the run's own baseline frame: 20deg, width 240.2pt, height 22pt at (481.9, 608.9)
    _click(page, 0.5027, 0.3799)  # centre of the rotated run
    line, col = _pos(page)
    assert line == 5 and base + 10 <= col <= base + 16, f"rotated centre: Ln {line}:{col}, base {base}"

    _click(page, 0.4269, 0.3604)  # near the run start
    line, col = _pos(page)
    assert line == 5 and base + 1 <= col <= base + 6, f"rotated start: Ln {line}:{col}, base {base}"

    _click(page, 0.5691, 0.3969)  # near the run end
    line, col = _pos(page)
    assert line == 5 and base + 19 <= col <= base + 24, f"rotated end: Ln {line}:{col}, base {base}"
