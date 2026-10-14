"""2C: gallery creation (desktop) + tour."""
from helpers import register
from playwright.sync_api import expect


def _skip_tour(page, name):
    register(page, name)
    expect(page.locator("#tourCard")).to_be_visible(timeout=20_000)  # fresh account: auto tour
    page.locator("#tourCard button.ghost").click()  # Skip
    expect(page.locator("#tourCard")).to_be_hidden()


def _new_from_gallery(page, card_text, title):
    page.click("#new")
    page.locator("#modal button.pk").first.click()  # askPick: Document
    expect(page.locator("#mHead")).to_have_text("New document")
    page.locator("#galGrid .pk", has_text=card_text).first.click()
    page.fill("#mInp", title)
    page.click("#mYes")
    expect(page.locator("#title")).to_have_text(title)


def test_gallery_paper_under_30s(page):
    _skip_tour(page, "e2e_gallery")
    _new_from_gallery(page, "Paper", "Gal Paper")
    expect(page.locator("#cm .cm-content")).to_contain_text("A Short Paper")


def test_gallery_dialog_wide_and_scrollable(page):
    _skip_tour(page, "e2e_galwide")
    page.click("#new")
    page.locator("#modal button.pk").first.click()  # askPick: Document
    expect(page.locator("#mHead")).to_have_text("New document")
    grid = page.locator("#galGrid")
    expect(grid).to_be_visible()
    assert grid.locator(".pk").count() == 7, "gallery shows all 7 templates"
    w = page.evaluate("document.getElementById('mCard').getBoundingClientRect().width")
    assert w >= 600, f"gallery dialog too narrow: {w}"
    overflow = page.evaluate("getComputedStyle(document.getElementById('galGrid')).overflowY")
    assert overflow == "auto", f"galGrid must scroll as fallback: {overflow}"
    box = page.evaluate("""const r=document.getElementById('mCard').getBoundingClientRect();
        ({x:r.x,y:r.y,w:r.width,h:r.height,iw:innerWidth,ih:innerHeight})""")
    assert box["x"] >= 0 and box["x"] + box["w"] <= box["iw"] + 1, f"dialog overflows horizontally: {box}"
    assert box["y"] >= 0 and box["y"] + box["h"] <= box["ih"] + 1, f"dialog overflows vertically: {box}"
    page.click("#mNo")  # close without creating
    expect(page.locator("#modal")).to_be_hidden()


def test_gallery_blank_and_thesis(page):
    _skip_tour(page, "e2e_galbt")
    _new_from_gallery(page, "Blank", "Gal Blank")
    expect(page.locator("#cm .cm-content")).to_be_visible()
    _new_from_gallery(page, "Thesis", "Gal Thesis")
    expect(page.locator("#cm .cm-content")).to_contain_text("Thesis Title")
