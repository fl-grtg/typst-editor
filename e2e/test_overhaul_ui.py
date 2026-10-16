"""Overhaul UI track: tab save races, tab-bar keyboard UI, presentation mode.

test_ui_save_failure_blocks_switch_and_keeps_dirty: a failing file-tab save
    must block the tab switch (flushTab -> False), keep the dirty text, and
    show the error instead of discarding it. After the backend recovers the
    switch succeeds and the dirty text survived.
test_ui_rapid_tab_switch_keeps_newest: two fast switches with a slow first
    fetch must leave the newest tab's text in the editor (generation guard:
    late responses never write into a newer tab).
test_ui_presentation_enter_navigate_exit: Present.enter shows one page at a
    time with a counter, arrows move, Escape exits and restores split view.
test_ui_tabs_roving_focus_and_mobile: desktop roving tabindex + arrows/Enter,
    labels not clipped, and a usable tab bar on a small viewport.
"""
import re
import time

from helpers import create_doc, register, type_source
from playwright.sync_api import expect

PREVIEW_TIMEOUT = 60_000


def _new_file_tab(page, name):
    # Local attachments still use the file save route; the plus menu now creates project modules.
    did = next(d['id'] for d in page.request.get('/api/docs').json()['own'] if d['title'].startswith('UI '))
    response = page.request.post(f'/api/docs/{did}/files/{name}.typ/text', data={'content': ''})
    assert response.ok, response.text()
    tab = page.locator('#tabs button.tab').filter(has_text=name + '.typ')
    expect(tab).to_be_visible()
    tab.click()
    expect(tab).to_have_attribute('aria-selected', 'true')


def _wait_saved(page):
    expect(page.locator("#save")).to_contain_text("saved", timeout=10_000)


def test_ui_save_failure_blocks_switch_and_keeps_dirty(page):
    register(page, "e2e_ui_tabsave")
    create_doc(page, "UI tabsave doc")
    _new_file_tab(page, "afile")
    type_source(page, "AAA one")
    _wait_saved(page)
    _new_file_tab(page, "bfile")
    type_source(page, "BBB two")
    _wait_saved(page)

    def _fail(route):
        if route.request.method == "POST":
            route.fulfill(status=500, content_type="application/json", body='{"detail":"boom"}')
        else:
            route.continue_()

    page.route("**/api/docs/**/files/**/text", _fail)
    try:
        type_source(page, "BBB two plus dirty")
        page.locator("#tabs button.tab", has_text="afile.typ").click()
        # blocked: still on bfile, dirty text intact, error shown, nothing lost
        expect(page.locator("#tabs button.tab", has_text="bfile.typ")).to_have_attribute("aria-selected", "true")
        expect(page.locator("#cm .cm-content")).to_contain_text("plus dirty")
        expect(page.locator("#save")).to_contain_text("Error", timeout=10_000)
        expect(page.locator("#toast")).to_be_visible()
        expect(page.locator("#toast")).to_contain_text("bfile.typ")
    finally:
        page.unroute("**/api/docs/**/files/**/text", _fail)
    # recovered: switch works and the dirty text survived the blocked attempt
    page.locator("#tabs button.tab", has_text="afile.typ").click()
    expect(page.locator("#cm .cm-content")).to_contain_text("AAA one")
    page.locator("#tabs button.tab", has_text="bfile.typ").click()
    expect(page.locator("#cm .cm-content")).to_contain_text("plus dirty")


def test_ui_rapid_tab_switch_keeps_newest(page):
    register(page, "e2e_ui_tabrace")
    create_doc(page, "UI tabrace doc")
    _new_file_tab(page, "afile")
    type_source(page, "AAA one")
    _wait_saved(page)
    _new_file_tab(page, "bfile")
    type_source(page, "BBB two")
    _wait_saved(page)
    page.locator("#tabs button.tab").first.click()
    expect(page.locator("#tabs button.tab").first).to_have_attribute("aria-selected", "true")

    def _slow(route):
        if route.request.method == "GET" and "afile.typ" in route.request.url:
            time.sleep(0.8)  # first fetch resolves after the second one
        route.continue_()

    page.route("**/api/docs/**/files/**/text", _slow)
    try:
        page.locator("#tabs button.tab", has_text="afile.typ").click()
        page.locator("#tabs button.tab", has_text="bfile.typ").click()
        expect(page.locator("#cm .cm-content")).to_contain_text("BBB two", timeout=10_000)
        expect(page.locator("#tabs button.tab", has_text="bfile.typ")).to_have_attribute("aria-selected", "true")
        page.wait_for_timeout(1_200)  # late first response must not clobber
        expect(page.locator("#cm .cm-content")).to_contain_text("BBB two")
        expect(page.locator("#cm .cm-content")).not_to_contain_text("AAA one")
    finally:
        page.unroute("**/api/docs/**/files/**/text", _slow)


def test_ui_presentation_enter_navigate_exit(page):
    register(page, "e2e_ui_present")
    create_doc(page, "UI present doc")
    type_source(page, "= P1\n\n#pagebreak()\n\n= P2")
    expect(page.locator("#preview .pvPage[data-done] canvas").first).to_be_visible(timeout=PREVIEW_TIMEOUT)
    assert page.evaluate("window.Present.pages()") >= 2
    assert page.evaluate("window.Present.enter()") is True
    expect(page.locator("body")).to_have_class(re.compile(r"\bpresent\b"))
    expect(page.locator("#presentBar")).to_be_visible()
    expect(page.locator("#presentBar")).to_have_attribute("role", "toolbar")
    expect(page.locator("#presentCount")).to_have_text("1 of 2")
    page.keyboard.press("ArrowRight")
    expect(page.locator("#presentCount")).to_have_text("2 of 2")
    page.keyboard.press("ArrowLeft")
    expect(page.locator("#presentCount")).to_have_text("1 of 2")
    page.keyboard.press("Escape")
    expect(page.locator("body")).not_to_have_class(re.compile(r"\bpresent\b"))
    expect(page.locator("#presentBar")).to_be_hidden()
    expect(page.locator("#vSplit")).to_have_class(re.compile(r"\bon\b"))
    page.click("#presentBtn")
    expect(page.locator("#presentBar")).to_be_visible()
    page.mouse.move(640, 710)
    page.locator("#presentExit").focus()
    page.click("#presentExit")
    expect(page.locator("#presentBar")).not_to_be_visible()


def test_ui_tabs_roving_focus_and_mobile(page):
    register(page, "e2e_ui_tabs")
    create_doc(page, "UI tabs doc")
    _new_file_tab(page, "afile")
    tabs = page.locator("#tabs button.tab")
    # roving tabindex: only the selected tab is in the tab order
    expect(tabs.nth(1)).to_have_attribute("tabindex", "0")
    expect(tabs.nth(0)).to_have_attribute("tabindex", "-1")
    tabs.nth(1).focus()
    page.keyboard.press("ArrowLeft")
    expect(tabs.nth(0)).to_be_focused()
    page.keyboard.press("Enter")  # native activation switches back to main
    expect(tabs.nth(0)).to_have_attribute("aria-selected", "true")
    # labels not clipped (line box fits the glyphs, descenders included)
    box = page.evaluate(
        "() => { const n = document.querySelector('#tabs .tn');"
        " const cs = getComputedStyle(n);"
        " return { lh: parseFloat(cs.lineHeight), fs: parseFloat(cs.fontSize) }; }"
    )
    assert box["lh"] >= box["fs"], f"tab label line-height clips descenders: {box}"
    # small viewport: bar stays usable, touch-size tabs, delete affordance visible
    page.set_viewport_size({"width": 390, "height": 844})
    expect(page.locator("#tabs")).to_be_visible()
    h = page.evaluate("() => document.querySelector('#tabs button.tab').getBoundingClientRect().height")
    assert h >= 40, f"mobile tab hit target too small: {h}"
    page.locator("#tabs button.tab", has_text="afile.typ").click()
    expect(page.locator("#tabs .tabw.on button.tx")).to_be_visible()
