"""Klick-Sync: Preview -> Editor trifft die Sektion, auch ohne exakten Worttreffer."""
import re

from helpers import create_doc, register, type_source
from playwright.sync_api import expect

PREVIEW_TIMEOUT = 60_000

SOURCE = """= Alpha

Alpha body line.

#pagebreak()

= Beta

Beta tail line.
"""


def _line(page) -> int:
    m = re.match(r"Ln (\d+):", page.locator("#pos").inner_text())
    assert m, "status line has no line number"
    return int(m.group(1))


def test_click_preview_lands_in_the_clicked_section(page):
    register(page, "e2e_click_sec")
    create_doc(page, "Click section doc")
    type_source(page, SOURCE)
    expect(page.locator("#preview .pvPage[data-done] canvas").first).to_be_visible(timeout=PREVIEW_TIMEOUT)
    expect(page.locator("#ol .pg")).to_have_count(2, timeout=PREVIEW_TIMEOUT)  # anchor chain ready
    expect(page.locator("#preview .pvPage")).to_have_count(2)

    body = page.locator('.pvPage[data-page="2"] canvas')
    body.click(position={"x": 300, "y": 110})  # beta heading / first body line
    page.wait_for_function("() => /^Ln [789]:/.test(document.getElementById('pos').textContent)", timeout=PREVIEW_TIMEOUT)
    assert 7 <= _line(page) <= 9

    body.click(position={"x": 400, "y": 500})  # blank second page: no word within reach
    page.wait_for_function("() => /^Ln 7:/.test(document.getElementById('pos').textContent)", timeout=PREVIEW_TIMEOUT)
    assert _line(page) == 7
