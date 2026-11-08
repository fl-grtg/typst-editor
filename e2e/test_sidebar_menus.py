"""Sidebar row actions open as anchored dropdowns and rename inline."""
from helpers import create_doc, register
from playwright.sync_api import expect


def _assert_anchored(menu, button):
    button_box = button.bounding_box()
    menu_box = menu.bounding_box()
    assert menu_box["y"] >= button_box["y"] + button_box["height"] - 1
    assert menu_box["x"] < button_box["x"] + button_box["width"]
    assert menu_box["x"] + menu_box["width"] > button_box["x"]


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
    _assert_anchored(menu, more)

    menu.locator("button").filter(has_text="Rename document").click()
    inp = page.locator("#own input.renameInput")
    expect(inp).to_be_visible()
    inp.fill("Sidebar renamed doc")
    inp.press("Enter")
    expect(page.locator("#own .doc .t", has_text="Sidebar renamed doc")).to_be_visible()
    expect(page.locator("#own input.renameInput")).to_have_count(0)


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
    expect(menu.locator("button.danger")).to_contain_text("Delete")
    _assert_anchored(menu, more)

    menu.locator("button").filter(has_text="Rename project").click()
    expect(page.locator(".fhd.project input.renameInput")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator(".fhd.project input.renameInput")).to_have_count(0)
    expect(page.locator(".project-group .fhd.project b", has_text="Sidebar project")).to_be_visible()
