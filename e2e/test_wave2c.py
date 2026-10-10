"""2C: gallery creation + mobile drawer (390px, short heights)."""
from helpers import register
from playwright.sync_api import expect


def _new_from_gallery(page, card_text, title):
    page.click("#new")
    page.locator("#modal button.pk").first.click()  # askPick: Document
    expect(page.locator("#mHead")).to_have_text("New document")
    page.locator("#galGrid .pk", has_text=card_text).first.click()
    page.fill("#mInp", title)
    page.click("#mYes")
    expect(page.locator("#title")).to_have_text(title)


def test_gallery_paper_under_30s(page):
    register(page, "e2e_gallery")
    expect(page.locator("#tourCard")).to_be_visible(timeout=20_000)  # fresh account: auto tour
    page.locator("#tourCard button.ghost").click()  # Skip
    expect(page.locator("#tourCard")).to_be_hidden()
    _new_from_gallery(page, "Paper", "Gal Paper")
    expect(page.locator("#cm .cm-content")).to_contain_text("A Short Paper")


def _mobile_ctx(browser, base_url, w, h):
    mctx = browser.new_context(base_url=base_url, viewport={"width": w, "height": h})
    mctx.set_default_timeout(15_000)
    return mctx


def _drawer_assertions(mp):
    mp.click("#navToggle")  # closed drawer first: open it
    expect(mp.locator("body.drawer-open")).to_have_count(1)
    expect(mp.locator("#scrim")).to_be_visible()
    expect(mp.locator(".sbHead .mark")).to_be_visible()  # logo in sidebar
    expect(mp.locator("#who")).to_be_visible()  # settings reachable
    mp.locator("#who").click()
    expect(mp.locator("#setPop")).to_be_visible()  # bottom sheet
    mp.locator("#side .sbHead .name").click()  # outside tap dismisses the sheet
    expect(mp.locator("#setPop")).to_be_hidden()
    mp.keyboard.press("Escape")  # abort closes the drawer
    expect(mp.locator("body.drawer-open")).to_have_count(0)
    expect(mp.locator("#scrim")).to_be_hidden()
    mp.click("#navToggle")  # reopen, close via scrim tap
    expect(mp.locator("body.drawer-open")).to_have_count(1)
    mp.locator("#scrim").click(position={"x": 345, "y": 320})  # visible strip right of the drawer
    expect(mp.locator("body.drawer-open")).to_have_count(0)


def test_mobile_drawer_390_short(browser, base_url):
    mctx = _mobile_ctx(browser, base_url, 390, 700)
    try:
        mp = mctx.new_page()
        register(mp, "e2e_mob390")
        _drawer_assertions(mp)
        mp.click("#navToggle")  # reopen for doc creation
        h = mp.evaluate("document.getElementById('new').getBoundingClientRect().height")
        assert h >= 44, f"touch target too small: {h}"
        _new_from_gallery(mp, "Blank", "Mobile doc")
        expect(mp.locator("#vEdit")).to_be_visible()  # editor/preview switchable
        expect(mp.locator("#vRead")).to_be_visible()
        mp.click("#vRead")
        expect(mp.locator("#preview")).to_be_visible()
        mp.click("#vEdit")
        expect(mp.locator("#cm .cm-content")).to_be_visible()
    finally:
        mctx.close()


def test_mobile_drawer_360(browser, base_url):
    mctx = _mobile_ctx(browser, base_url, 360, 640)
    try:
        mp = mctx.new_page()
        register(mp, "e2e_mob360")
        _drawer_assertions(mp)
    finally:
        mctx.close()


def test_mobile_drawer_412(browser, base_url):
    mctx = _mobile_ctx(browser, base_url, 412, 700)
    try:
        mp = mctx.new_page()
        register(mp, "e2e_mob412")
        _drawer_assertions(mp)
    finally:
        mctx.close()
