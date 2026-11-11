"""Klick-Sync: Preview -> Editor trifft die Sektion, auch ohne exakten Worttreffer."""
import re

from helpers import create_doc, register, type_source
from playwright.sync_api import expect

from backend.services.tutorial import TUTORIAL

PREVIEW_TIMEOUT = 60_000

# The seeded tutorial fits on one page; force the diagram onto page 2 so the
# chart coordinates stay stable (same layout as the manual sync test doc).
CHART_SOURCE = TUTORIAL.replace("\n\n// Centered bar diagram", "\n#pagebreak()\n// Centered bar diagram")

PAGE_IN_VIEW = """(n) => {
  const pv = document.getElementById('preview')
  const s = pv.querySelector('.pvPage[data-page="' + n + '"]')
  if (!s) return false
  const pr = pv.getBoundingClientRect(), sr = s.getBoundingClientRect()
  return sr.top >= pr.top - 5 && sr.top < pr.bottom
}"""

SOURCE = """= Alpha

Alpha body line.

#pagebreak()

= Beta

Beta tail line.
"""

LINKED = """= Alpha

To beta: #link(<b>)[go there]

#pagebreak()

= Beta <b>

Beta tail line.
"""


def _line(page) -> int:
    m = re.match(r"Ln (\d+):", page.locator("#pos").inner_text())
    assert m, "status line has no line number"
    return int(m.group(1))


def _col(page) -> int:
    m = re.match(r"Ln \d+:(\d+)", page.locator("#pos").inner_text())
    assert m, "status line has no column"
    return int(m.group(1))


def _ready(page, headings: int) -> None:
    expect(page.locator("#preview .pvPage[data-done] canvas").first).to_be_visible(timeout=PREVIEW_TIMEOUT)
    expect(page.locator("#ol .pg")).to_have_count(headings, timeout=PREVIEW_TIMEOUT)  # anchor chain + links ready
    expect(page.locator("#preview .pvPage")).to_have_count(headings)


def _reader_top(page) -> None:
    # A real reader input stops a running follow/jump even when that glide
    # writes the same spot. Then park the view exactly on the page top.
    pv = page.locator("#preview")
    box = pv.bounding_box()
    assert box
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.wheel(0, -4000)
    page.evaluate("() => { document.getElementById('preview').scrollTop = 0 }")


PAGE_ONE_AT_TOP = """() => {
  const pv = document.getElementById('preview'), cv = pv.querySelector('.pvPage[data-page="1"] canvas')
  if (!cv) return false
  const d = cv.getBoundingClientRect().top - pv.getBoundingClientRect().top
  return d >= -2 && d < 40
}"""


def _assert_pv_top(page) -> None:
    assert page.evaluate(PAGE_ONE_AT_TOP), "a late sync moved the preview away from the document top"


def test_click_preview_lands_in_the_clicked_section(page):
    register(page, "e2e_click_sec")
    create_doc(page, "Click section doc")
    type_source(page, SOURCE)
    _ready(page, 2)

    body = page.locator('.pvPage[data-page="2"] canvas')
    body.click(position={"x": 300, "y": 110})  # beta heading / first body line
    page.wait_for_function("() => /^Ln [789]:/.test(document.getElementById('pos').textContent)", timeout=PREVIEW_TIMEOUT)
    assert 7 <= _line(page) <= 9

    body.click(position={"x": 400, "y": 500})  # blank second page: nearest readable text stays in the section
    page.wait_for_function("() => /^Ln [789]:/.test(document.getElementById('pos').textContent)", timeout=PREVIEW_TIMEOUT)
    assert 7 <= _line(page) <= 9


def test_click_columns_stay_on_the_letters_of_a_justified_line(page):
    register(page, "e2e_click_col")
    create_doc(page, "Click column doc")
    para = ("Die erste Methode sammelt alle Werte und vergleicht sie danach mit dem "
            "gespeicherten Ergebnis der letzten Runde. ") * 3
    type_source(page, "#set par(justify: true)\n\n= Alpha\n\n" + para.strip() + "\n")
    _ready(page, 1)
    box = page.locator('#preview .pvPage[data-page="1"] canvas').bounding_box()
    assert box
    y = box["y"] + box["height"] * 0.5  # blank space below the paragraph: its lines still own the column
    maxfx = min(0.95, (page.viewport_size["width"] - box["x"] - 4) / box["width"])  # clicks must stay on screen
    assert maxfx > 0.5, "the page is mostly outside the test viewport"
    cols = []
    for fx in [maxfx * i / 6 for i in range(1, 7)]:
        page.mouse.click(box["x"] + box["width"] * fx, y)
        page.wait_for_timeout(600)
        assert _line(page) == 5, "a blank click left the paragraph"
        col = _col(page)
        assert 1 < col <= len(para) + 1 and (para[col - 2] != " " or (col <= len(para) and para[col - 1] != " ")), \
            f"click at {fx} left the words: column {col}"
        cols.append(col)
    assert len(set(cols)) >= 3, f"clicks kept one column: {cols}"
    inner = [col for col in cols if 1 < col <= len(para) and para[col - 2] != " " and para[col - 1] != " "]
    assert inner, f"every click landed on a word edge instead of a letter: {cols}"


def test_click_columns_survive_wrapped_single_letter_words(page):
    register(page, "e2e_click_letters")
    create_doc(page, "Click letter doc")
    para = " ".join(list("abcdefghij" * 24))  # 240 one-letter words on one source line
    type_source(page, "#set par(justify: true)\n\n= Alpha\n\n" + para + "\n")
    _ready(page, 1)
    box = page.locator('#preview .pvPage[data-page="1"] canvas').bounding_box()
    assert box
    fx = 0.15  # just inside the left edge of every rendered line
    cols = []
    for fy in (0.108, 0.125, 0.142, 0.159):  # the four PDF lines of the wrapped paragraph
        page.mouse.click(box["x"] + box["width"] * fx, box["y"] + box["height"] * fy)
        page.wait_for_timeout(600)
        assert _line(page) == 5, f"click on line {fy} left the paragraph"
        cols.append(_col(page))
    assert cols[0] < 20, f"the first line did not start at the paragraph: {cols}"
    for i in range(1, 4):  # every PDF line continues one source line: 62 words + 62 spaces = 124 chars
        assert abs(cols[i] - (cols[i - 1] + 124)) <= 20, f"line {i} landed on a repeated word: {cols}"
    page.mouse.click(box["x"] + box["width"] * 0.5, box["y"] + box["height"] * 0.5)  # far below the paragraph
    page.wait_for_timeout(600)
    assert _line(page) == 5 and _col(page) > 1, "a blank click fell back to the heading above"


def test_follow_toggle_keeps_the_preview_still_but_clicks_still_jump(page):
    register(page, "e2e_click_follow")
    create_doc(page, "Follow toggle doc")
    type_source(page, SOURCE)
    _ready(page, 2)

    page.click("#cm .cm-content")
    page.keyboard.press("ControlOrMeta+Home")
    page.wait_for_function(PAGE_IN_VIEW, arg=1, timeout=PREVIEW_TIMEOUT)

    page.click("#followBtn")  # follow everything -> clicks only
    expect(page.locator("#followBtn")).to_have_attribute("aria-pressed", "false")
    page.click("#cm .cm-content")
    page.keyboard.press("ControlOrMeta+End")
    page.wait_for_timeout(700)  # longer than the 40 ms sync throttle
    assert not page.evaluate(PAGE_IN_VIEW, 2)  # cursor moved, preview stayed

    body = page.locator('.pvPage[data-page="2"] canvas')
    body.click(position={"x": 300, "y": 110})  # an explicit click still finds its line
    page.wait_for_function("() => /^Ln [789]:/.test(document.getElementById('pos').textContent)", timeout=PREVIEW_TIMEOUT)


def test_eye_alone_follows_the_cursor_but_never_jumps_on_clicks(page):
    register(page, "e2e_click_eye")
    create_doc(page, "Eye only doc")
    type_source(page, SOURCE)
    _ready(page, 2)

    page.click("#cm .cm-content")
    page.keyboard.press("ControlOrMeta+Home")
    page.wait_for_function(PAGE_IN_VIEW, arg=1, timeout=PREVIEW_TIMEOUT)

    page.click("#syncBtn")  # click sync off, follow stays on
    expect(page.locator("#syncBtn")).to_have_attribute("aria-pressed", "false")
    expect(page.locator("#followBtn")).to_have_attribute("aria-pressed", "true")
    page.click("#cm .cm-content")
    page.keyboard.press("ControlOrMeta+End")
    page.wait_for_function(PAGE_IN_VIEW, arg=2, timeout=PREVIEW_TIMEOUT)  # the eye alone follows the cursor

    before = page.locator("#pos").inner_text()
    page.locator('.pvPage[data-page="2"] canvas').click(position={"x": 300, "y": 30})  # beta heading
    page.wait_for_timeout(700)  # longer than the 40 ms sync throttle
    assert page.locator("#pos").inner_text() == before, "a click moved the cursor although click sync is off"


def test_sync_wins_over_a_running_jump_animation(page):
    register(page, "e2e_click_anim")
    create_doc(page, "Click animation doc")
    type_source(page, LINKED)
    _ready(page, 2)

    page.click("#cm .cm-content")
    page.keyboard.press("ControlOrMeta+Home")
    page.wait_for_function(PAGE_IN_VIEW, arg=1, timeout=PREVIEW_TIMEOUT)

    link = page.locator('.pvPage[data-page="1"] .pvLinks a[data-pv-link]').first
    expect(link).to_have_count(1)
    link.dispatch_event("click")  # animated jump towards page 2, the editor cursor follows
    page.keyboard.press("ControlOrMeta+Home")  # cursor moves: this sync must win over the animation
    page.wait_for_timeout(600)  # longer than the 320 ms animation
    page.wait_for_function(PAGE_IN_VIEW, arg=1, timeout=PREVIEW_TIMEOUT)


def test_chart_clicks_land_on_the_caption_not_on_a_heading(page):
    register(page, "e2e_click_chart")
    create_doc(page, "Chart click doc")
    page.click("#cm .cm-content")
    page.keyboard.press("ControlOrMeta+A")
    assert page.evaluate("(t) => document.execCommand('insertText', false, t)", CHART_SOURCE)
    expect(page.locator('#preview .pvPage[data-page="2"][data-done] canvas')).to_be_visible(timeout=PREVIEW_TIMEOUT)
    expect(page.locator("#ol .pg")).to_have_count(4, timeout=PREVIEW_TIMEOUT)
    page.evaluate("""() => document.querySelector('#preview .pvPage[data-page="2"]').scrollIntoView({block: 'center'})""")
    page.wait_for_timeout(1200)  # text layer for page 2 is indexed after the raster is ready
    box = page.locator('#preview .pvPage[data-page="2"] canvas').bounding_box()
    assert box
    # bar labels, values, bar bodies and the caption: all belong to the chart, not to the next heading
    for fx, fy in [(.371, .158), (.374, .089), (.377, .142), (.503, .176), (.622, .143)]:
        page.mouse.click(box["x"] + box["width"] * fx, box["y"] + box["height"] * fy)
        page.wait_for_function("() => /^Ln 104:/.test(document.getElementById('pos').textContent)", timeout=PREVIEW_TIMEOUT)


def test_click_above_the_first_heading_lands_on_the_document_top(page):
    register(page, "e2e_click_top")
    create_doc(page, "Click top doc")
    type_source(page, """#outline()

= Alpha

Alpha body.

#pagebreak()

= Beta

Beta body.
""")
    _ready(page, 2)
    _reader_top(page)  # page top in view
    page.wait_for_timeout(700)
    _assert_pv_top(page)
    box = page.locator('#preview .pvPage[data-page="1"] canvas').bounding_box()
    assert box
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + 6)  # top margin above the generated contents
    page.wait_for_function("() => /^Ln 1:/.test(document.getElementById('pos').textContent)", timeout=PREVIEW_TIMEOUT)


def test_click_above_a_multi_page_outline_lands_on_the_document_top(page):
    register(page, "e2e_click_top_later")
    create_doc(page, "Click top later doc")
    type_source(page, """#outline()

#pagebreak()

= Chapter 1

Chapter body.
""")
    expect(page.locator("#preview .pvPage")).to_have_count(2, timeout=PREVIEW_TIMEOUT)
    expect(page.locator("#ol .pg")).to_have_count(1, timeout=PREVIEW_TIMEOUT)
    _reader_top(page)
    page.wait_for_timeout(900)
    _assert_pv_top(page)
    box = page.locator('#preview .pvPage[data-page="1"] canvas').bounding_box()
    assert box
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + 6)  # page margin above the generated contents
    page.wait_for_function("() => /^Ln 1:/.test(document.getElementById('pos').textContent)", timeout=PREVIEW_TIMEOUT)


def test_a_comment_before_the_first_heading_keeps_the_top_click_on_the_document(page):
    register(page, "e2e_click_top_note")
    create_doc(page, "Click top comment doc")
    type_source(page, """#outline()
// a note, not visible text
= Alpha

Alpha body.

#pagebreak()

= Beta

Beta body.
""")
    _ready(page, 2)
    _reader_top(page)
    page.wait_for_timeout(700)
    _assert_pv_top(page)
    box = page.locator('#preview .pvPage[data-page="1"] canvas').bounding_box()
    assert box
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + 6)
    page.wait_for_function("() => /^Ln 1:/.test(document.getElementById('pos').textContent)", timeout=PREVIEW_TIMEOUT)


def test_a_running_header_never_drags_the_editor_to_page_one(page):
    register(page, "e2e_click_header")
    create_doc(page, "Header sync doc")
    body = "\n".join(f"Body line {i} on this page." for i in range(1, 21))
    type_source(page, f"""#set page(header: [My Paper], numbering: "1")

= Alpha

{body}

#pagebreak()

= Beta

{body}

#pagebreak()

= Gamma

{body}
""")
    _ready(page, 3)
    page.click("#cm .cm-content")
    page.keyboard.press("ControlOrMeta+Home")  # editor view starts at the document top
    page.wait_for_timeout(700)
    page.evaluate("""() => {
      const pv = document.getElementById('preview')
      const p = pv.querySelector('.pvPage[data-page="3"]')
      pv.scrollTop += p.getBoundingClientRect().top - pv.getBoundingClientRect().top - pv.clientHeight / 2 + 10
    }""")
    page.wait_for_timeout(1200)  # reading point just inside page 3: the running header is the nearest text
    top = page.locator("#cm .cm-scroller").evaluate("el => el.scrollTop")
    assert top > 300, f"header text dragged the editor view back to line 1 (scrollTop {top})"


def test_scrolling_up_after_a_page_bottom_click_keeps_the_editor_view(page):
    register(page, "e2e_click_scrollup")
    create_doc(page, "Click scroll up doc")
    page.click("#cm .cm-content")
    page.keyboard.press("ControlOrMeta+A")
    assert page.evaluate("(t) => document.execCommand('insertText', false, t)", CHART_SOURCE)
    expect(page.locator('#preview .pvPage[data-page="2"][data-done] canvas')).to_be_visible(timeout=PREVIEW_TIMEOUT)
    page.evaluate("() => { document.getElementById('preview').scrollTop = 600 }")  # page 2 owns the viewport center
    page.wait_for_timeout(900)
    box = page.locator('#preview .pvPage[data-page="1"] canvas').bounding_box()
    assert box
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] - 10)  # bottom of page 1: the table caption
    page.wait_for_timeout(900)
    assert 52 <= _line(page) <= 58, "the click should land on the table caption at the end of page 1"
    before = page.locator("#cm .cm-scroller").evaluate("el => el.scrollTop")
    page.mouse.wheel(0, -100)  # reader scrolls up: the editor view must not jump down
    page.wait_for_timeout(900)
    after = page.locator("#cm .cm-scroller").evaluate("el => el.scrollTop")
    assert abs(after - before) < 250, f"one wheel tick moved the editor view too far: {before} -> {after}"
    assert 52 <= _line(page) <= 58, "the wheel tick must keep the table caption line"

