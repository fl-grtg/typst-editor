"""Paket B: sektionsbewusster Scroll-Sync (Ankerkette über die PDF-Outline).

test_1: identical headings and body lines in three sections — the cursor in the
    third section scrolls to page 3, not to the first identical text.
test_2: a line that only matches the paper through a word run (`#emph[…]` hides
    source words) still finds its page.
"""
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

DUPLICATE_SECTIONS = """= Notes

Same body line.

#pagebreak()

= Notes

Same body line.

#pagebreak()

= Notes

Same body line.
"""

MARKUP_LINE = """= Intro

Start words here.

#pagebreak()

= Hidden

See #emph[hidden] text here please.

Tail words.
"""

HEADING_IN_BODY = """= Start

Start body text.

#pagebreak()

= Summary <summary>

The Summary wraps up the whole document.

#pagebreak()

= End

End body text.
"""


def _settle(page, headings: int) -> None:
    expect(page.locator("#preview .pvPage[data-done] canvas").first).to_be_visible(timeout=PREVIEW_TIMEOUT)
    expect(page.locator("#ol .pg")).to_have_count(headings, timeout=PREVIEW_TIMEOUT)  # outline loaded = anchor chain ready


def test_1_section_chain_beats_repeated_text(page):
    register(page, "e2e_sec_chain")
    create_doc(page, "Section chain doc")
    type_source(page, DUPLICATE_SECTIONS)
    _settle(page, 3)
    expect(page.locator("#preview .pvPage")).to_have_count(3)

    page.click("#cm .cm-content")
    page.keyboard.press("ControlOrMeta+Home")  # section 1: preview follows to page 1
    page.wait_for_function(PAGE_IN_VIEW, arg=1, timeout=PREVIEW_TIMEOUT)

    page.locator("#cm .cm-line", has_text="Same body line.").nth(2).click()
    page.wait_for_function(PAGE_IN_VIEW, arg=3, timeout=PREVIEW_TIMEOUT)


def test_2_word_run_fallback_finds_the_page(page):
    register(page, "e2e_sec_run")
    create_doc(page, "Word run doc")
    type_source(page, MARKUP_LINE)
    _settle(page, 2)
    expect(page.locator("#preview .pvPage")).to_have_count(2)

    page.wait_for_function(PAGE_IN_VIEW, arg=2, timeout=PREVIEW_TIMEOUT)  # cursor at the end: page 2
    page.keyboard.press("ControlOrMeta+Home")
    page.wait_for_function(PAGE_IN_VIEW, arg=1, timeout=PREVIEW_TIMEOUT)

    page.locator("#cm .cm-line", has_text="#emph").click()
    page.wait_for_function(PAGE_IN_VIEW, arg=2, timeout=PREVIEW_TIMEOUT)


def test_3_heading_page_wins_over_the_same_word_in_the_body(page):
    register(page, "e2e_sec_heading")
    create_doc(page, "Heading in body doc")
    type_source(page, HEADING_IN_BODY)
    _settle(page, 3)
    expect(page.locator("#preview .pvPage")).to_have_count(3)

    page.locator("#cm .cm-line", has_text="= Summary").click()  # heading word also appears in its body line
    page.wait_for_function(PAGE_IN_VIEW, arg=2, timeout=PREVIEW_TIMEOUT)
