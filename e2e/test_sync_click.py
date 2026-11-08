"""Klick-Sync: Preview -> Editor trifft die Sektion, auch ohne exakten Worttreffer."""
import re

from helpers import create_doc, register, type_source
from playwright.sync_api import expect

PREVIEW_TIMEOUT = 60_000

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

    body.click(position={"x": 400, "y": 500})  # blank second page: no word within reach
    page.wait_for_function("() => /^Ln 7:/.test(document.getElementById('pos').textContent)", timeout=PREVIEW_TIMEOUT)
    assert _line(page) == 7


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
