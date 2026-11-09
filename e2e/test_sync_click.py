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


def _ready(page, headings: int) -> None:
    expect(page.locator("#preview .pvPage[data-done] canvas").first).to_be_visible(timeout=PREVIEW_TIMEOUT)
    expect(page.locator("#ol .pg")).to_have_count(headings, timeout=PREVIEW_TIMEOUT)  # anchor chain + links ready
    expect(page.locator("#preview .pvPage")).to_have_count(headings)


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
    page.wait_for_timeout(700)  # longer than the 150 ms sync throttle
    assert not page.evaluate(PAGE_IN_VIEW, 2)  # cursor moved, preview stayed

    body = page.locator('.pvPage[data-page="2"] canvas')
    body.click(position={"x": 300, "y": 110})  # an explicit click still finds its line
    page.wait_for_function("() => /^Ln [789]:/.test(document.getElementById('pos').textContent)", timeout=PREVIEW_TIMEOUT)


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
    link.dispatch_event("click")  # animated jump towards page 2, focus stays in the editor
    page.keyboard.press("End")  # cursor moves: this sync must win over the animation
    page.wait_for_timeout(400)  # longer than the 220 ms animation
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
