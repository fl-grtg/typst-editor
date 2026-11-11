"""Paket A: PDF-Link-Schicht im Preview (externe Links, interne Ziele, Outline-Seiten).

test_1: a `#link("…")` becomes a real anchor over the canvas; clicking it opens
    the target tab and never moves the editor cursor (link beats click-sync).
test_2: an internal `#link(<label>)` scrolls the preview to the destination page.
test_3: the internal jump glides through several frames instead of teleporting.
test_4: the sidebar outline shows the real page number from the PDF outline.
test_5: an internal link moves the editor cursor to the same destination.
test_6: a manual preview scroll moves the editor view, never the cursor.
test_7: the outline strips Typst labels such as `<second>`.
test_8: an outline click glides editor and preview to the same section.
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

SCROLL_SOURCE = "\n\n#pagebreak()\n\n".join(
    f"= Page {p}\n\n" + "\n\n".join(f"Body line {p} dot {i}." for i in range(1, 13))
    for p in (1, 2, 3)
)

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


def test_3_internal_link_glides_instead_of_teleporting(page):
    register(page, "e2e_pdf_glide")
    create_doc(page, "PDF glide doc")
    source, _ = _source(page)
    type_source(page, source)
    expect(page.locator("#preview .pvPage[data-done] canvas").first).to_be_visible(timeout=PREVIEW_TIMEOUT)
    jump = page.locator("#preview .pvLinks a[data-pv-link]")
    expect(jump).to_have_count(1, timeout=LINK_TIMEOUT)
    page.evaluate("() => { document.getElementById('preview').scrollTop = 0 }")  # start on page 1
    page.wait_for_timeout(150)

    page.evaluate("""() => {
      const pv = document.getElementById('preview')
      window.__pvSamples = []
      const t0 = performance.now()
      const tick = () => {
        window.__pvSamples.push(Math.round(pv.scrollTop))
        if (performance.now() - t0 < 800) requestAnimationFrame(tick)
      }
      requestAnimationFrame(tick)
    }""")
    jump.dispatch_event("click")
    page.wait_for_timeout(850)
    samples = page.evaluate("() => window.__pvSamples")
    assert len(set(samples)) >= 5, samples  # a glide has many intermediate positions
    span = samples[-1] - samples[0]
    assert span > 100, samples
    assert max(b - a for a, b in zip(samples, samples[1:], strict=False)) < span * 0.6, samples  # eased, not a teleport


def test_4_outline_shows_pdf_page_numbers(page):
    register(page, "e2e_pdf_outline")
    create_doc(page, "PDF outline doc")
    source, _ = _source(page)
    type_source(page, source)
    expect(page.locator("#preview .pvPage[data-done] canvas").first).to_be_visible(timeout=PREVIEW_TIMEOUT)

    badges = page.locator("#ol .pg")
    expect(badges).to_have_count(2, timeout=LINK_TIMEOUT)
    assert badges.all_inner_texts() == ["1", "2"]


def test_5_internal_link_moves_the_editor_with_it(page):
    register(page, "e2e_pdf_link_editor")
    create_doc(page, "PDF link editor doc")
    source, _ = _source(page)
    type_source(page, source)
    expect(page.locator("#preview .pvPage[data-done] canvas").first).to_be_visible(timeout=PREVIEW_TIMEOUT)
    jump = page.locator("#preview .pvLinks a[data-pv-link]")
    expect(jump).to_have_count(1, timeout=LINK_TIMEOUT)

    jump.click()  # link beats click-sync, but the editor follows the destination
    page.wait_for_function("() => /^Ln 9:/.test(document.getElementById('pos').textContent)", timeout=LINK_TIMEOUT)
    page.wait_for_function(PAGE_TWO_IN_VIEW, timeout=LINK_TIMEOUT)

    page.click("#followBtn")  # eye off: a link is still a click, so the source must follow
    page.click("#cm .cm-content")
    page.keyboard.press("ControlOrMeta+Home")
    page.wait_for_timeout(600)
    assert page.locator("#pos").inner_text().startswith("Ln 1:")
    jump.click()
    page.wait_for_function("() => /^Ln 9:/.test(document.getElementById('pos').textContent)", timeout=LINK_TIMEOUT)


def test_6_preview_scroll_moves_the_editor_view_not_the_cursor(page):
    register(page, "e2e_pdf_scroll")
    create_doc(page, "PDF preview scroll doc")
    type_source(page, SCROLL_SOURCE)
    expect(page.locator("#preview .pvPage[data-done] canvas").last).to_be_visible(timeout=PREVIEW_TIMEOUT)
    page.click("#cm .cm-content")
    page.keyboard.press("ControlOrMeta+Home")
    page.wait_for_timeout(700)
    assert page.locator("#pos").inner_text().startswith("Ln 1:")
    before = page.locator("#cm .cm-scroller").evaluate("el => el.scrollTop")

    page.locator("#preview").evaluate("el => { el.scrollTop = el.scrollHeight }")
    page.wait_for_function(
        "(before) => document.querySelector('#cm .cm-scroller').scrollTop > before + 300",
        arg=before,
        timeout=LINK_TIMEOUT,
    )
    assert page.locator("#pos").inner_text().startswith("Ln 1:"), "a reader scroll must not move the cursor"


def test_7_outline_shows_headings_without_typst_labels(page):
    register(page, "e2e_pdf_labels")
    create_doc(page, "PDF label doc")
    source, _ = _source(page)
    type_source(page, source)
    expect(page.locator("#preview .pvPage[data-done] canvas").first).to_be_visible(timeout=PREVIEW_TIMEOUT)

    expect(page.locator("#ol .t")).to_have_count(2, timeout=LINK_TIMEOUT)
    assert page.locator("#ol .t").all_inner_texts() == ["Start", "Second"]


def test_8_outline_click_moves_editor_and_preview_together(page):
    register(page, "e2e_pdf_outline_jump")
    create_doc(page, "PDF outline jump doc")
    source, _ = _source(page)
    type_source(page, source)
    expect(page.locator("#preview .pvPage[data-done] canvas").first).to_be_visible(timeout=PREVIEW_TIMEOUT)
    expect(page.locator("#ol .pg")).to_have_count(2, timeout=LINK_TIMEOUT)

    page.click("#cm .cm-content")
    page.keyboard.press("ControlOrMeta+Home")
    page.wait_for_timeout(700)
    page.locator("#ol .doc").nth(1).click()
    page.wait_for_function("() => /^Ln 9:/.test(document.getElementById('pos').textContent)", timeout=LINK_TIMEOUT)
    page.wait_for_function(PAGE_TWO_IN_VIEW, timeout=LINK_TIMEOUT)
