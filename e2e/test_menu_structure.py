"""Menubar: grouped submenus keep File, Edit, View and Help compact."""
from helpers import create_doc, register
from playwright.sync_api import expect


def _labels(page, panel="#menu"):
    return page.locator(f"{panel} button .lb").all_text_contents()


def _close(page):
    page.keyboard.press("Escape")
    page.keyboard.press("Escape")


def test_menubar_groups_actions_into_submenus(page):
    register(page, "e2e_menu_structure")
    create_doc(page, "Menu structure")
    menu = page.locator("#menu")

    page.locator('#menubar [data-menu="file"]').click()
    expect(menu).to_be_visible()
    assert _labels(page) == [
        "New project", "Upload file", "Rename", "Share", "Versions", "Save now", "Export", "Move to trash",
    ]
    assert all(not label.endswith("…") for label in _labels(page))
    menu.locator("button").filter(has_text="Export").click()
    expect(page.locator("#submenu")).to_be_visible()
    assert _labels(page, "#submenu")[0] == "Download as .typ"
    _close(page)

    page.locator('#menubar [data-menu="edit"]').click()
    expect(menu).to_be_visible()
    assert _labels(page) == ["Find and replace", "Formatting", "Insert", "Comment on selection"]
    menu.locator("button").filter(has_text="Formatting").click()
    expect(page.locator("#submenu")).to_be_visible()
    assert "Bold" in _labels(page, "#submenu")
    assert "Format document" in _labels(page, "#submenu")
    _close(page)

    page.locator('#menubar [data-menu="view"]').click()
    expect(menu).to_be_visible()
    assert _labels(page) == ["Mode", "Preview", "Sidebar", "Appearance", "Font size"]
    menu.locator("button").filter(has_text="Mode").click()
    expect(page.locator("#submenu")).to_be_visible()
    assert _labels(page, "#submenu") == [
        "Editor only", "Editor and preview", "Preview only", "Present",
    ]
    _close(page)

    page.locator('#menubar [data-menu="help"]').click()
    expect(menu).to_be_visible()
    assert _labels(page) == [
        "Keyboard shortcuts", "Connect AI agent", "Source code on GitHub", "GitHub Issues",
    ]
    expect(menu.locator(".ext svg")).to_have_count(2)
    _close(page)


def test_file_new_project_opens_centered_dialog(page):
    register(page, "e2e_newproj_center")
    page.locator('#menubar [data-menu="file"]').click()
    page.locator("#menu button").filter(has_text="New project").click()

    expect(page.locator("#modal")).to_be_visible()
    expect(page.locator("#mHead")).to_have_text("New project")
    box = page.locator("#mCard").bounding_box()
    width = page.viewport_size["width"]
    assert box is not None and box["x"] > 0 and box["x"] + box["width"] < width  # centered, not the sidebar popup
    expect(page.locator("#menu")).to_be_hidden()
    page.locator("#mNo").click()
    expect(page.locator("#modal")).to_be_hidden()
