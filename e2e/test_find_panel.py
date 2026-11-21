"""Find panel: match list, replace preview, preserve case, undo of replace all, hits never hidden under the panel."""
from playwright.sync_api import expect

from e2e.helpers import create_doc, put_source, register

SOURCE = "\n".join(
    ["= Find demo", ""]
    + [f"Line {i}: the fox and the Fox meet a FOX near fox_den." for i in range(1, 80)]
)


def _open(page, name):
    register(page, name)
    create_doc(page, "Find panel")
    put_source(page, SOURCE)
    expect(page.locator("#cm .cm-content")).to_contain_text("Line 79")


def test_find_list_preview_and_undo(page):
    _open(page, "find_list_undo")
    page.click("#cm .cm-content")
    page.keyboard.press("Control+End")
    page.keyboard.press("Control+H")
    page.fill("#fQ", "fox")
    page.locator("#fWord").click()  # fox_den is one word: not a whole-word hit
    expect(page.locator("#fN")).to_have_text("1/237")

    page.locator("#fList").click()
    expect(page.locator("#fSum")).to_have_text("237 matches in 79 lines")
    first = page.locator("#fRes .fHit").first
    expect(first.locator(".ln")).to_have_text("3")
    expect(first.locator("mark")).to_have_count(3)

    # the current hit sits below the panel, never under it
    def cur_below_panel():
        return page.evaluate("""() => {
            const c = document.querySelector('#cm .cm-find-cur'), f = document.getElementById('find')
            return !!c && c.getBoundingClientRect().top >= f.getBoundingClientRect().bottom
        }""")
    page.wait_for_function("() => !!document.querySelector('#cm .cm-find-cur')")
    page.wait_for_timeout(500)
    assert cur_below_panel()
    page.locator("#fRes .fHit").nth(40).locator("mark").nth(1).click()
    expect(page.locator("#fN")).to_have_text("122/237")
    page.wait_for_timeout(500)
    assert cur_below_panel()

    # replace preview with preserve case: fox -> wolf, Fox -> Wolf, FOX -> WOLF
    page.fill("#fR", "wolf")
    page.locator("#fKeep").click()
    expect(first.locator("mark ins")).to_have_text(["wolf", "Wolf", "WOLF"])

    page.locator("#fAll").click()
    expect(page.locator("#fMsg")).to_contain_text("Replaced 237 occurrences")
    expect(page.locator("#cm .cm-content")).to_contain_text("the wolf and the Wolf meet a WOLF near fox_den")
    page.locator("#fMsg .fUndo").click()
    expect(page.locator("#cm .cm-content")).to_contain_text("the fox and the Fox meet a FOX near fox_den")
    expect(page.locator("#fN")).to_have_text("237")

    # options survive a reload
    assert page.evaluate("() => JSON.parse(localStorage.getItem('findOpts'))") == {"c": False, "w": True, "r": False, "k": True}
