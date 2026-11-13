"""Sidebar row actions open as anchored dropdowns and rename inline."""
from helpers import create_doc, register
from playwright.sync_api import expect


def _assert_anchored(page, menu, button):
    button_box = menu_box = None
    for _ in range(50):  # a sidebar refresh can replace the anchor row between measurements
        button_box = button.bounding_box()
        menu_box = menu.bounding_box()
        if button_box and menu_box:
            break
        page.wait_for_timeout(20)
    assert button_box and menu_box
    assert menu_box["y"] >= button_box["y"] + button_box["height"] - 1
    # opens rightward from the three-dot instead of stretching to the sidebar's left edge
    assert menu_box["x"] >= button_box["x"] - 1
    assert menu_box["x"] + menu_box["width"] > button_box["x"] + button_box["width"]


def test_sidebar_doc_menu_anchors_and_renames_inline(page):
    register(page, "e2e_sidebar_doc")
    create_doc(page, "Sidebar menu doc")
    row = page.locator("#own .doc").filter(has=page.locator(".t", has_text="Sidebar menu doc")).first
    row.hover()
    more = row.locator("button[data-side-menu]")
    expect(more).to_be_visible()
    more.click()

    menu = page.locator("#menu")
    expect(menu).to_be_visible()
    expect(page.locator("#modal")).to_be_hidden()
    expect(menu).to_contain_text("Rename document")
    expect(menu.locator("button.danger")).to_contain_text("Move to trash")
    _assert_anchored(page, menu, more)

    menu.locator("button").filter(has_text="Rename document").click()
    inp = page.locator("#own input.renameInput")
    expect(inp).to_be_visible()
    inp.fill("Sidebar renamed doc")
    inp.press("Enter")
    expect(page.locator("#own .doc .t", has_text="Sidebar renamed doc")).to_be_visible()
    expect(page.locator("#own input.renameInput")).to_have_count(0)


def test_personal_resource_rename_after_sidebar_refresh(page):
    register(page, "e2e_sidebar_personal")
    response = page.request.post("/api/templates", data={"name": "module.typ", "content": "= Module"})
    assert response.ok, response.text()
    page.reload()
    page.wait_for_function("window.__booted === true")

    row = page.locator("#tpls .doc").filter(has=page.locator(".t", has_text="module.typ")).first
    if not row.is_visible():
        page.locator("#tplH").press("Enter")
    old_row = row.element_handle()
    row.hover()
    row.locator("button[data-side-menu]").click()
    menu = page.locator("#menu")
    expect(menu).to_be_visible()

    response = page.request.post("/api/docs/create", data={"title": "Refresh trigger", "content": ""})
    assert response.ok, response.text()
    expect(page.locator("#own .doc .t", has_text="Refresh trigger")).to_be_visible()
    assert page.evaluate("node => !node.isConnected", old_row)

    menu.locator("button").filter(has_text="Rename resource").click()
    inp = page.locator("#tpls input.renameInput")
    expect(inp).to_be_visible()
    inp.fill("module-renamed.typ")
    inp.press("Enter")
    expect(page.locator("#tpls .doc .t", has_text="module-renamed.typ")).to_be_visible()


def test_inline_rename_survives_sidebar_refresh(page):
    register(page, "e2e_rename_refresh")
    create_doc(page, "Rename stays")
    row = page.locator("#own .doc").filter(has=page.locator(".t", has_text="Rename stays")).first
    row.hover()
    row.locator("button[data-side-menu]").click()
    page.locator("#menu button").filter(has_text="Rename document").click()

    inp = page.locator("#own input.renameInput")
    expect(inp).to_be_visible()
    inp.fill("Rename kept")
    response = page.request.post("/api/docs/create", data={"title": "Refresh during rename", "content": ""})
    assert response.ok, response.text()
    page.wait_for_function("window.__sidebarDeferred === true")
    expect(inp).to_be_visible()
    inp.press("Enter")
    expect(page.locator("#own .doc .t", has_text="Rename kept")).to_be_visible()
    expect(page.locator("#own .doc .t", has_text="Refresh during rename")).to_be_visible()


def test_sidebar_menu_keyboard_escape_returns_focus(page):
    register(page, "e2e_sidebar_keys")
    create_doc(page, "Keyboard row")
    row = page.locator("#own .doc").filter(has=page.locator(".t", has_text="Keyboard row")).first
    row.hover()
    more = row.locator("button[data-side-menu]")
    more.focus()
    more.press("ArrowDown")
    menu = page.locator("#menu")
    expect(menu).to_be_visible()
    expect(menu.locator("button").first).to_be_focused()
    response = page.request.post("/api/docs/create", data={"title": "Keyboard refresh", "content": ""})  # repaints the sidebar under the open menu
    assert response.ok, response.text()
    expect(page.locator("#own .doc .t", has_text="Keyboard refresh")).to_be_visible()
    page.keyboard.press("Escape")
    expect(menu).to_be_hidden()
    expect(more).to_be_focused()


def test_sidebar_project_menu_opens_anchored(page):
    register(page, "e2e_sidebar_project")
    response = page.request.post("/api/projects", data={"title": "Sidebar project"})
    assert response.ok, response.text()
    page.reload()
    page.wait_for_function("window.__booted === true")

    group = page.locator(".project-group").filter(has=page.locator(".fhd.project b", has_text="Sidebar project")).first
    head = group.locator(".fhd.project")
    head.hover()
    more = head.locator("button[data-side-menu]")
    expect(more).to_be_visible()
    more.click()

    menu = page.locator("#menu")
    expect(menu).to_be_visible()
    expect(menu).to_contain_text("Rename project")
    expect(menu.locator("button.danger")).to_contain_text("Move project to trash")
    _assert_anchored(page, menu, more)

    menu.locator("button").filter(has_text="Rename project").click()
    expect(page.locator(".fhd.project input.renameInput")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator(".fhd.project input.renameInput")).to_have_count(0)
    expect(page.locator(".project-group .fhd.project b", has_text="Sidebar project")).to_be_visible()
