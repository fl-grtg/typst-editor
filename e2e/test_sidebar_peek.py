"""Compact sidebar: rail actions peek over the editor and collapse on pointer leave."""
import re

from helpers import create_doc, register
from playwright.sync_api import expect


def _collapse(page):
    page.click("#navToggle")
    expect(page.locator("#side .sbRail")).to_be_visible()
    page.wait_for_function("document.querySelector('main').getBoundingClientRect().x <= 53")  # width transition done


def test_rail_section_peeks_over_editor_and_closes_on_leave(page):
    register(page, "e2e_side_peek")
    create_doc(page, "Peek doc")
    _collapse(page)
    main = page.locator("main")
    main_left = main.bounding_box()["x"]
    rail = page.locator("#side .sbRail")
    rail_box = rail.bounding_box()

    page.locator('.sbRail [data-rail="docs"]').click()
    body = page.locator("body")
    panel = page.locator("#side .sbPanel")
    new_btn = page.locator("#new")
    rail_docs = page.locator('.sbRail [data-rail="docs"]')
    new_box = new_btn.bounding_box()
    assert new_box
    expect(body).to_have_class(re.compile(r"\bnoside\b"))
    expect(body).to_have_class(re.compile(r"\bsidePeek\b"))
    expect(rail_docs).to_have_attribute("aria-expanded", "true")  # transient disclosure for screen readers
    expect(panel).to_be_visible()
    expect(panel).to_have_css("transition-property", re.compile(r"\bwidth\b"))  # grows out of the rail, collapses on leave
    expect(rail).to_have_css("display", "flex")  # stays mounted behind the panel: no icon reload on close
    expect(rail).to_have_css("opacity", "1")  # never faded or re-laid out, simply covered
    assert rail.bounding_box() == rail_box
    page.wait_for_function("document.querySelector('#side .sbPanel').getBoundingClientRect().width > 200")
    open_box = new_btn.bounding_box()
    assert open_box and open_box["width"] == new_box["width"]  # content keeps its final layout while the panel opens
    box = panel.bounding_box()
    user_box = page.locator("#side #userBox").bounding_box()
    assert box and user_box
    assert box["x"] + box["width"] > main_left  # floats over the editor column
    assert box["y"] + box["height"] - (user_box["y"] + user_box["height"]) < 16  # account box stays pinned to the bottom
    assert abs(main.bounding_box()["x"] - main_left) < 1  # peek does not shift the editor

    page.mouse.move(box["x"] + box["width"] + 80, box["y"] + 200)
    closing = page.wait_for_function("""() => {  // collapse animates, not snaps
      const p = document.querySelector('#side .sbPanel')
      if (!document.body.classList.contains('sidePeekOut')) return null
      const n = document.querySelector('#new').getBoundingClientRect()
      return { display: getComputedStyle(p).display, transition: getComputedStyle(p).transitionProperty, newWidth: n.width }
    }""").json_value()
    assert closing and closing["display"] != "none"
    assert "width" in closing["transition"]
    assert abs(closing["newWidth"] - new_box["width"]) < 0.5  # closing clips the panel, it does not reflow it
    expect(body).not_to_have_class(re.compile(r"\bsidePeek\b"))
    expect(body).not_to_have_class(re.compile(r"\bsidePeekOut\b"))
    expect(panel).not_to_be_visible()
    expect(rail).to_be_visible()
    expect(rail).to_have_css("opacity", "1")  # icons were there all along: no rebuild, no jump
    assert rail.bounding_box() == rail_box
    expect(rail_docs).to_have_attribute("aria-expanded", "false")


def test_rail_search_peeks_and_focuses_the_field(page):
    register(page, "e2e_side_peek_search")
    create_doc(page, "Peek search doc")
    _collapse(page)

    page.locator('.sbRail [data-rail="search"]').click()
    expect(page.locator("body")).to_have_class(re.compile(r"\bsidePeek\b"))
    expect(page.locator("#q")).to_be_focused()


def test_search_filters_keep_the_peek_open(page):
    register(page, "e2e_side_peek_filter")
    create_doc(page, "Peek filter doc")
    _collapse(page)
    page.locator('.sbRail [data-rail="search"]').click()
    body = page.locator("body")
    expect(body).to_have_class(re.compile(r"\bsidePeek\b"))

    page.fill("#q", "peek")
    page.click("#qFilter")
    filters = page.locator("#searchFilters")
    expect(filters).to_be_visible()
    filters.locator('[data-sf="projects"]').click()
    page.wait_for_timeout(350)  # past the leave delay: the flyout belongs to the floating panel
    expect(body).to_have_class(re.compile(r"\bsidePeek\b"))
    expect(body).not_to_have_class(re.compile(r"\bsidePeekOut\b"))
    expect(filters).to_be_visible()
    assert page.locator("#side .sbPanel").bounding_box()["width"] > 200

    page.mouse.move(900, 300)  # leaving the flyout closes it and the floating panel together
    expect(filters).to_have_count(0)
    expect(body).not_to_have_class(re.compile(r"\bsidePeek\b"))


def test_peek_returns_focus_to_the_rail_when_it_closes(page):
    register(page, "e2e_side_peek_focus")
    create_doc(page, "Peek focus doc")
    _collapse(page)
    search = page.locator('.sbRail [data-rail="search"]')
    search.click()
    expect(page.locator("#q")).to_be_focused()  # focus is inside the panel when the pointer leaves

    page.mouse.move(900, 300)
    expect(page.locator("body")).not_to_have_class(re.compile(r"\bsidePeek\b"))
    expect(search).to_be_focused()  # focusing a hidden input would otherwise drop focus to the page
    expect(search).to_have_attribute("aria-expanded", "false")


def test_peek_reopens_while_the_close_animation_runs(page):
    register(page, "e2e_side_peek_reopen")
    create_doc(page, "Peek reopen doc")
    _collapse(page)
    docs = page.locator('.sbRail [data-rail="docs"]')
    docs.click()
    body = page.locator("body")
    expect(body).to_have_class(re.compile(r"\bsidePeek\b"))

    page.mouse.move(900, 300)
    expect(body).not_to_have_class(re.compile(r"\bsidePeek\b"))
    expect(body).to_have_class(re.compile(r"\bsidePeekOut\b"))
    docs.press("Enter")  # focus is back on the trigger: reopen before the old close timer fires
    expect(body).to_have_class(re.compile(r"\bsidePeek\b"))
    expect(body).not_to_have_class(re.compile(r"\bsidePeekOut\b"))
    page.wait_for_timeout(400)  # the cancelled timer must not close the new peek
    expect(body).to_have_class(re.compile(r"\bsidePeek\b"))


def test_click_outside_closes_the_peek(page):
    register(page, "e2e_side_peek_out")
    create_doc(page, "Peek outside doc")
    _collapse(page)
    page.locator('.sbRail [data-rail="docs"]').click()
    body = page.locator("body")
    expect(body).to_have_class(re.compile(r"\bsidePeek\b"))

    page.mouse.click(900, 300)  # editor: a touch tap has no pointerleave to rely on
    expect(body).not_to_have_class(re.compile(r"\bsidePeek\b"))
    expect(page.locator("body")).not_to_have_class(re.compile(r"\bsidePeekOut\b"))


def test_row_menu_from_peek_keeps_the_panel_until_it_closes(page):
    register(page, "e2e_side_peek_menu")
    create_doc(page, "Peek menu doc")
    _collapse(page)
    page.locator('.sbRail [data-rail="docs"]').click()
    body = page.locator("body")
    panel = page.locator("#side .sbPanel")
    expect(panel).to_be_visible()

    row = page.locator("#own .doc").filter(has=page.locator(".t", has_text="Peek menu doc")).first
    row.hover()
    row.locator("button[data-side-menu]").click()
    menu = page.locator("#menu")
    expect(menu).to_be_visible()
    menu_box, panel_box = menu.bounding_box(), panel.bounding_box()
    assert menu_box and panel_box

    page.mouse.move(menu_box["x"] + menu_box["width"] - 20, menu_box["y"] + menu_box["height"] / 2)
    assert menu_box["x"] + menu_box["width"] - 20 > panel_box["x"] + panel_box["width"]  # outside the panel
    page.wait_for_timeout(300)
    expect(body).to_have_class(re.compile(r"\bsidePeek\b"))  # the open menu keeps the peek

    page.keyboard.press("Escape")
    expect(menu).to_be_hidden()
    expect(body).not_to_have_class(re.compile(r"\bsidePeek\b"))


def test_row_menu_rename_keeps_the_peek_open(page):
    register(page, "e2e_side_peek_rename")
    create_doc(page, "Peek rename doc")
    _collapse(page)
    page.locator('.sbRail [data-rail="docs"]').click()
    body = page.locator("body")
    expect(body).to_have_class(re.compile(r"\bsidePeek\b"))
    row = page.locator("#own .doc").filter(has=page.locator(".t", has_text="Peek rename doc")).first
    row.hover()
    row.locator("button[data-side-menu]").click()
    page.locator("#menu button").filter(has_text="Rename").click()

    inp = page.locator("#own input.renameInput")
    expect(inp).to_be_visible()
    page.wait_for_timeout(400)  # the menu-close timer must not hide the inline editor
    expect(body).to_have_class(re.compile(r"\bsidePeek\b"))
    page.mouse.move(120, 500)  # back over the panel
    page.mouse.move(900, 300)  # then leave: an active rename keeps the panel open
    page.wait_for_timeout(400)
    expect(body).to_have_class(re.compile(r"\bsidePeek\b"))
    expect(inp).to_be_visible()
    inp.fill("Peek renamed doc")
    inp.press("Enter")
    expect(page.locator("#own .doc .t", has_text="Peek renamed doc")).to_be_visible()
    expect(body).to_have_class(re.compile(r"\bsidePeek\b"))  # the panel stays for the next action


def test_rail_plus_opens_the_project_and_upload_menu(page):
    register(page, "e2e_side_peek_new")
    page.click("#navToggle")
    plus = page.locator('.sbRail [data-rail="new"]')
    expect(plus).to_be_visible()
    plus.click()

    menu = page.locator("#menu")
    expect(menu).to_be_visible()
    items = menu.locator("button")
    expect(items).to_have_count(2)
    expect(items.nth(0)).to_have_text("Project")
    expect(items.nth(1)).to_have_text("Upload file")
    plus_box, menu_box = plus.bounding_box(), menu.bounding_box()
    assert plus_box and menu_box
    assert menu_box["x"] >= plus_box["x"] + plus_box["width"]  # flyout to the right of the rail

    items.nth(0).click()
    expect(page.locator("#modal")).to_be_visible()
    expect(page.locator("#mHead")).to_have_text("New project")
    page.click("#mNo")


def test_sidebar_state_survives_reload(page):
    register(page, "e2e_side_state")
    body = page.locator("body")
    rail = page.locator("#side .sbRail")
    expect(body).not_to_have_class(re.compile(r"\bnoside\b"))

    page.click("#navToggle")
    expect(body).to_have_class(re.compile(r"\bnoside\b"))
    page.reload()
    page.wait_for_function("window.__booted === true")
    expect(body).to_have_class(re.compile(r"\bnoside\b"))
    expect(rail).to_be_visible()

    page.click("#navToggle")
    expect(body).not_to_have_class(re.compile(r"\bnoside\b"))
    page.reload()
    page.wait_for_function("window.__booted === true")
    expect(body).not_to_have_class(re.compile(r"\bnoside\b"))
    expect(page.locator("#side .sbPanel")).to_be_visible()


def test_expanded_new_button_opens_the_dialog_directly(page):
    register(page, "e2e_new_direct")
    page.click("#new")
    expect(page.locator("#menu")).to_be_hidden()  # no project/upload detour in the expanded sidebar
    expect(page.locator("#modal")).to_be_visible()
    expect(page.locator("#mHead")).to_have_text("New project")
    page.click("#mNo")


def test_peeked_new_button_opens_the_dialog_directly(page):
    register(page, "e2e_new_peek_direct")
    page.click("#navToggle")
    page.locator('.sbRail [data-rail="docs"]').click()
    expect(page.locator("body")).to_have_class(re.compile(r"\bsidePeek\b"))

    page.click("#new")  # the visible panel + behaves like the expanded one, not like the rail +
    expect(page.locator("#menu")).to_be_hidden()
    expect(page.locator("#modal")).to_be_visible()
    expect(page.locator("#mHead")).to_have_text("New project")
    page.click("#mNo")


def test_escape_closes_the_peek_and_returns_focus(page):
    register(page, "e2e_side_peek_keys")
    create_doc(page, "Peek keys doc")
    _collapse(page)
    rail = page.locator('.sbRail [data-rail="docs"]')
    expect(rail).to_have_attribute("aria-expanded", "false")
    rail.focus()
    rail.press("Enter")
    body = page.locator("body")
    expect(body).to_have_class(re.compile(r"\bsidePeek\b"))
    expect(rail).to_have_attribute("aria-expanded", "true")

    page.keyboard.press("Escape")
    expect(body).not_to_have_class(re.compile(r"\bsidePeek\b"))
    expect(rail).to_be_focused()
    expect(rail).to_have_attribute("aria-expanded", "false")


def test_peek_logo_pins_the_sidebar_open(page):
    register(page, "e2e_side_peek_pin")
    create_doc(page, "Peek pin doc")
    _collapse(page)
    page.locator('.sbRail [data-rail="docs"]').click()
    body = page.locator("body")
    expect(body).to_have_class(re.compile(r"\bsidePeek\b"))

    page.locator("#side .sbHead [data-rail=toggle]").click()
    expect(body).not_to_have_class(re.compile(r"\bnoside\b"))
    expect(body).not_to_have_class(re.compile(r"\bsidePeek\b"))
    expect(page.locator("#side .sbPanel")).to_be_visible()
    expect(page.locator("#side .sbRail")).to_be_hidden()


def test_manual_collapse_keeps_the_panel_in_flow(page):
    register(page, "e2e_side_manual")
    panel = page.locator("#side .sbPanel")
    inner = page.locator("#side .sbInner")
    expect(panel).to_have_css("position", "relative")

    page.click("#navToggle")
    expect(page.locator("body")).to_have_class(re.compile(r"\bnoside\b"))
    expect(panel).to_have_css("position", "relative")  # the peek overlay must not hijack the manual animation
    assert page.evaluate("parseFloat(getComputedStyle(document.querySelector('#side')).getPropertyValue('--side-w'))") > 200
    expect(inner).to_have_css("flex", "1 0 auto")  # clipped at the last open width instead of reflowing
    expect(page.locator("#side .sbRail")).to_be_visible()


def test_logo_does_not_move_between_rail_and_panel(page):
    register(page, "e2e_side_logo")
    head_logo = page.locator("#side .sbHead .mark")
    rail_logo = page.locator("#side .sbRail .mark")
    head_box = head_logo.bounding_box()
    assert head_box

    def same_box(other):
        assert other
        for key in ("x", "y", "width", "height"):
            assert abs(other[key] - head_box[key]) < 0.5, key  # same logo, same spot: no jump on open or close

    page.click("#navToggle")
    expect(rail_logo).to_be_visible()
    same_box(rail_logo.bounding_box())

    page.locator('.sbRail [data-rail="docs"]').click()
    expect(head_logo).to_be_visible()
    same_box(head_logo.bounding_box())


