"""Overhaul preview navigation: include/template tabs, far pages, same-length edits, stale switches.

pv1 (include tab): with chapter.typ open in the editor the preview still compiles
    main.typ; a same-length breaking edit in the include reaches the compiler
    (error badge appears, last good preview stays). The old byte-length/mtime
    shadow signature silently kept the stale chapter.
pv2 (stale switch): a render queued for the doc must not replace the template
    view opened right after; going back to the doc recovers the preview.
pv3 (long doc): 30 pages render virtualized; a re-render keeps the deep scroll
    anchor; cursor follow reaches the first/last page through the text index.
"""
from helpers import create_doc, register
from playwright.sync_api import expect

PREVIEW_TIMEOUT = 60_000
BIG_TIMEOUT = 120_000


def _doc_id(page, title):
    docs = page.request.get("/api/docs").json()["own"]
    return next(d["id"] for d in docs if d["title"] == title)


def test_pv1_include_tab_same_length_edit_recompiles(page):
    register(page, "e2e_ov1")
    create_doc(page, "OV include doc")
    doc_id = _doc_id(page, "OV include doc")
    chap_v1 = "Body alpha one\n"
    r = page.request.post(
        f"/api/docs/{doc_id}/files/chapter.typ/text", data={"content": chap_v1}
    )
    assert r.ok, r.text()
    page.click("#cm .cm-content")
    page.keyboard.press("ControlOrMeta+A")
    page.keyboard.type('= AlphaMain\n\n#include "chapter.typ"\n\ntailword-zeta')
    expect(page.locator("#preview .pvPage[data-done] canvas").first).to_be_visible(
        timeout=PREVIEW_TIMEOUT
    )
    expect(page.locator("#eBadge")).to_be_hidden()
    page.locator("#tabs button.tab", has_text="chapter.typ").click()
    expect(page.locator("#cm .cm-content")).to_contain_text("Body alpha")
    # same byte length, new content: '#' breaks the chapter, length is unchanged
    chap_v2 = "#ody alpha one\n"
    assert len(chap_v2) == len(chap_v1), "test must keep the byte length equal"
    page.click("#cm .cm-content")
    page.keyboard.press("ControlOrMeta+A")
    page.keyboard.type(chap_v2)
    expect(page.locator("#eBadge")).to_be_visible(timeout=PREVIEW_TIMEOUT)
    expect(page.locator("#preview .pvPage[data-done]").first).to_be_visible()


def test_pv2_pending_render_does_not_replace_template_view(page):
    register(page, "e2e_ov2")
    create_doc(page, "OV stale doc")
    page.click("#cm .cm-content")
    page.keyboard.press("ControlOrMeta+A")
    page.keyboard.type("= StaleMain\n\nbefore switch")
    expect(page.locator("#preview .pvPage[data-done] canvas").first).to_be_visible(
        timeout=PREVIEW_TIMEOUT
    )
    page.click("#cm .cm-content")
    page.keyboard.press("ControlOrMeta+End")
    page.keyboard.type("!")  # queue a doc render, then leave immediately
    page.click("#tplBtn")
    page.locator("#tplPop button", has_text="New template").click()
    page.fill("#mInp", "ovstale.typ")
    page.click("#mYes")
    expect(page.locator("#title")).to_have_text("ovstale.typ")
    page.wait_for_timeout(6_000)  # a stale doc compile must not clobber this view
    assert page.locator("#preview canvas").count() == 0
    expect(page.locator("#preview")).to_contain_text(
        "Preview not available for templates."
    )
    page.locator("#own .doc", has_text="OV stale doc").first.click()
    expect(page.locator("#title")).to_have_text("OV stale doc")
    expect(page.locator("#preview .pvPage[data-done] canvas").first).to_be_visible(
        timeout=PREVIEW_TIMEOUT
    )


def test_pv3_long_doc_virtualized_anchor_and_follow(page):
    register(page, "e2e_ov3")
    create_doc(page, "OV long doc")
    big = "\n\n#pagebreak()\n\n".join(
        f"= Page {i}\n\nMarkerPage{i:02d}zz body {i}." for i in range(1, 31)
    )
    page.click("#cm .cm-content")
    page.keyboard.press("ControlOrMeta+A")
    assert page.evaluate("(t) => document.execCommand('insertText', false, t)", big)
    expect(page.locator("#cm .cm-content")).to_contain_text("MarkerPage30zz")
    slots = page.locator("#preview .pvPage")
    expect(slots).to_have_count(30, timeout=BIG_TIMEOUT)
    widths = page.locator("#preview .pvPage canvas").evaluate_all(
        "els => els.map(e => e.width)"
    )
    big_n = sum(1 for w in widths if w > 16)
    assert 1 <= big_n <= 12, f"virtualization off: {big_n} of {len(widths)} rasterized"
    old = slots.first.element_handle()
    page.click("#syncBtn")  # follow off: isolate scroll preservation
    page.locator("#preview").evaluate("el => el.scrollTo(0, el.scrollHeight)")
    page.wait_for_timeout(500)
    before = page.locator("#preview").evaluate("el => el.scrollTop")
    assert before > 1000, f"scroll did not move: {before}"
    page.click("#cm .cm-content")
    page.keyboard.press("ControlOrMeta+Home")
    page.keyboard.type("Q")
    expect(page.locator("#cm .cm-content")).to_contain_text("Q= Page 1")
    page.wait_for_function("(el) => !el.isConnected", arg=old, timeout=BIG_TIMEOUT)
    after = page.locator("#preview").evaluate("el => el.scrollTop")
    assert abs(after - before) < 600, f"scroll lost on re-render: {before} -> {after}"
    page.click("#syncBtn")  # follow on: cursor jumps move the preview
    page.click("#cm .cm-content")
    page.keyboard.press("ControlOrMeta+Home")
    page.wait_for_function(
        "(el) => el.scrollTop < 1000",
        arg=page.locator("#preview").element_handle(),
        timeout=PREVIEW_TIMEOUT,
    )
    page.keyboard.press("ControlOrMeta+End")
    page.wait_for_function(
        "(el) => el.scrollTop > 1000",
        arg=page.locator("#preview").element_handle(),
        timeout=PREVIEW_TIMEOUT,
    )
