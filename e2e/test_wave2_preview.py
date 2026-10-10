"""Wave 2A preview: zoom modes, error click-to-jump, virtualized big docs.

test_9 (A3+A5): zoom +/-/width/page controls work, then a Typst error
    shows the badge, the list jumps to the exact line on click, and the
    last good preview stays visible behind the error.
test_10 (A2+A4): a 100-page document renders one slot per page but only
    rasterizes the visible window, and the editor stays usable.
test_11 (A1): an uploaded image survives incremental compiles (worker
    keeps its shadow files, only main.typ is re-added).
"""
import re

from helpers import create_doc, register, type_source
from playwright.sync_api import expect

PREVIEW_TIMEOUT = 60_000
BIG_TIMEOUT = 120_000

# minimal 1x1 PNG (no Pillow needed)
DOT_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf"
    b"\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND"
    b"\xaeB`\x82"
)


def test_9_zoom_modes_and_error_click_jumps_to_line(page):
    register(page, "e2e_ivan")
    create_doc(page, "Preview2A doc")
    type_source(page, "= Hello\n\nSome text here")
    expect(page.locator("#preview .pvPage[data-done] canvas").first).to_be_visible(timeout=PREVIEW_TIMEOUT)
    assert page.locator("#zoomV").inner_text() == "110%"
    page.click("#zPlus")
    expect(page.locator("#zoomV")).to_have_text("120%")
    page.click("#zMinus")
    expect(page.locator("#zoomV")).to_have_text("110%")
    page.click("#fitBtn")  # width mode
    expect(page.locator("#fitBtn")).to_have_class(re.compile(r"\bon\b"))
    expect(page.locator("#zoomV")).to_have_text(re.compile(r"^\d+%$"))
    page.click("#fitPageBtn")  # page mode
    expect(page.locator("#fitPageBtn")).to_have_class(re.compile(r"\bon\b"))
    expect(page.locator("#zoomV")).to_have_text(re.compile(r"^\d+%$"))
    page.click("#zPlus")  # explicit % leaves fit modes
    expect(page.locator("#fitPageBtn")).not_to_have_class(re.compile(r"\bon\b"))
    expect(page.locator("#fitBtn")).not_to_have_class(re.compile(r"\bon\b"))
    # error with a real line: click in the list must jump the cursor there
    type_source(page, "= Hello\n\nSome text here\n\n#nosuchfn-xyz()")
    expect(page.locator("#eBadge")).to_be_visible()
    expect(page.locator("#preview .pvPage[data-done]").first).to_be_visible()  # last good preview stays
    page.click("#eBadge")
    expect(page.locator("#pop.errs")).to_be_visible()
    page.locator("#pop.errs button.er").first.click()
    page.keyboard.type("X")  # lands at the jump position: error line gets the mark
    rows = page.locator("#cm .cm-content").inner_text().splitlines()
    err_rows = [r for r in rows if "nosuchfn" in r]
    assert err_rows and all("X" in r for r in err_rows), f"jump missed the error line: {rows!r}"


def test_10_hundred_page_doc_stays_usable(page):
    register(page, "e2e_judy")
    create_doc(page, "Big doc")
    big = "\n\n#pagebreak()\n\n".join(f"= Page {i}\n\nSome body text {i}." for i in range(1, 101))
    page.click("#cm .cm-content")  # paste (not key-by-key): same input pipeline, ~90s faster
    page.keyboard.press("ControlOrMeta+A")
    assert page.evaluate("(t) => document.execCommand('insertText', false, t)", big)
    expect(page.locator("#cm .cm-content")).to_contain_text("Page 100")
    slots = page.locator("#preview .pvPage")
    expect(slots).to_have_count(100, timeout=BIG_TIMEOUT)
    old = slots.first.element_handle()  # the re-render below must swap the slots (proves it landed)
    widths = page.locator("#preview .pvPage canvas").evaluate_all("els => els.map(e => e.width)")
    big_n = sum(1 for w in widths if w > 16)
    assert 1 <= big_n <= 12, f"virtualization off: {big_n} of {len(widths)} pages rasterized"
    page.click("#syncBtn")  # follow off: isolate scroll preservation from cursor-follow
    page.locator("#preview").evaluate("el => el.scrollTo(0, el.scrollHeight)")  # deep scroll, then re-render
    page.wait_for_timeout(500)
    before = page.locator("#preview").evaluate("el => el.scrollTop")
    assert before > 1000, f"scroll did not move: {before}"
    page.click("#cm .cm-content")  # editor still responsive on a 100-page doc
    page.keyboard.press("ControlOrMeta+Home")
    page.keyboard.type("Q")
    expect(page.locator("#cm .cm-content")).to_contain_text("Q= Page 1")
    page.wait_for_function("(el) => !el.isConnected", arg=old, timeout=BIG_TIMEOUT)  # old slots detached = re-render landed
    after = page.locator("#preview").evaluate("el => el.scrollTop")
    assert abs(after - before) < 400, f"scroll lost on re-render: {before} -> {after}"


def test_11_image_survives_incremental_compile(page, tmp_path):
    png = tmp_path / "t11.png"
    png.write_bytes(DOT_PNG)
    register(page, "e2e_karl")
    create_doc(page, "Image doc")
    page.set_input_files("#imgPick", str(png))  # upload only, no #image insert yet
    type_source(page, '= Pic\n\n#image("t11.png", width: 80%)')
    expect(page.locator("#preview .pvPage[data-done]").first).to_be_visible(timeout=PREVIEW_TIMEOUT)
    expect(page.locator("#eBadge")).to_be_hidden()  # image resolved on the full remap
    old = page.locator("#preview .pvPage").first.element_handle()
    page.click("#cm .cm-content")  # one more char: same file sig, worker must keep the shadow
    page.keyboard.press("ControlOrMeta+End")
    page.keyboard.type("!")
    page.wait_for_function("(el) => !el.isConnected", arg=old, timeout=PREVIEW_TIMEOUT)  # swap = second compile landed
    page.wait_for_timeout(4_000)  # settle: a late first-compile swap must not mask the second compile's badge
    expect(page.locator("#eBadge")).to_be_hidden()  # wiped shadow would say "file not found" here
