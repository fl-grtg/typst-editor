"""Paket A: PDF-Link-Schicht im Preview (externe Links, interne Ziele, Outline-Seiten).

test_1: a `#link("…")` becomes a real anchor over the canvas; clicking it opens
    the target tab and never moves the editor cursor (link beats click-sync).
test_2: an internal `#link(<label>)` scrolls the preview to the destination page.
test_3: the sidebar outline shows the real page number from the PDF outline.
"""
from helpers import create_doc, register, type_source
from playwright.sync_api import expect

PREVIEW_TIMEOUT = 60_000
LINK_TIMEOUT = 30_000

SOURCE = """= Start

#link("LINK_URL")[External link]

#link(<second>)[Jump to second]

#pagebreak()

= Second <second>

Second page body.
"""

PAGE_TWO_IN_VIEW = """() => {
  const pv = document.getElementById('preview')
  const s = pv.querySelector('.pvPage[data-page="2"]')
  if (!s || pv.scrollTop <= 0) return false
  const pr = pv.getBoundingClientRect(), sr = s.getBoundingClientRect()
  return sr.top >= pr.top - 5 && sr.top < pr.bottom
}"""


def _source(page) -> tuple[str, str]:
    url = page.evaluate("location.origin") + "/healthz"  # same origin: the popup loads offline
    return SOURCE.replace("LINK_URL", url), url


def test_1_external_link_opens_a_tab_and_keeps_the_cursor(page):
    register(page, "e2e_pdf_link")
    create_doc(page, "PDF link doc")
    source, url = _source(page)
    type_source(page, source)
    expect(page.locator("#preview .pvPage[data-done] canvas").first).to_be_visible(timeout=PREVIEW_TIMEOUT)

    link = page.locator(f'#preview .pvLinks a[href="{url}"]')
    expect(link).to_have_count(1, timeout=LINK_TIMEOUT)

    before = page.locator("#pos").inner_text()
    with page.context.expect_page() as popup:
        link.click()
    tab = popup.value
    tab.wait_for_url(url, timeout=LINK_TIMEOUT)
    assert tab.url == url
    tab.close()
    assert page.locator("#pos").inner_text() == before, "link click must not move the editor cursor"


def test_2_internal_link_scrolls_the_preview(page):
    register(page, "e2e_pdf_dest")
    create_doc(page, "PDF destination doc")
    source, _ = _source(page)
    type_source(page, source)
    expect(page.locator("#preview .pvPage[data-done] canvas").first).to_be_visible(timeout=PREVIEW_TIMEOUT)
    expect(page.locator('.pvPage[data-page="2"] canvas')).to_have_count(1)

    jump = page.locator("#preview .pvLinks a[data-pv-link]")
    expect(jump).to_have_count(1, timeout=LINK_TIMEOUT)
    jump.click()
    page.wait_for_function(PAGE_TWO_IN_VIEW, timeout=LINK_TIMEOUT)


def test_3_outline_shows_pdf_page_numbers(page):
    register(page, "e2e_pdf_outline")
    create_doc(page, "PDF outline doc")
    source, _ = _source(page)
    type_source(page, source)
    expect(page.locator("#preview .pvPage[data-done] canvas").first).to_be_visible(timeout=PREVIEW_TIMEOUT)

    badges = page.locator("#ol .pg")
    expect(badges).to_have_count(2, timeout=LINK_TIMEOUT)
    assert badges.all_inner_texts() == ["1", "2"]
