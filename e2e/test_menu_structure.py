"""Menubar: grouped submenus keep File, Edit, View and Help compact."""
from helpers import create_doc, register
from playwright.sync_api import expect


def _labels(page, panel="#menu"):
    return page.locator(f"{panel} button .lb, {panel} a .lb").all_text_contents()


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
        "New project", "Upload file", "Rename", "Share", "Version history", "Save now", "Export", "Move to trash",
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
    assert _labels(page) == ["View mode", "Preview options", "Toggle sidebar", "Appearance", "Editor font size"]
    menu.locator("button").filter(has_text="View mode").click()
    expect(page.locator("#submenu")).to_be_visible()
    assert _labels(page, "#submenu") == [
        "Editor only", "Editor and preview", "Preview only", "Start presentation",
    ]
    present = page.locator("#submenu button").filter(has_text="Start presentation")
    expect(present.locator(".chk")).to_have_count(0)
    assert present.get_attribute("aria-checked") is None
    _close(page)

    page.locator('#menubar [data-menu="view"]').click()
    menu.locator("button").filter(has_text="Editor font size").click()
    expect(page.locator("#submenu")).to_be_visible()
    expect(page.locator("#submenu .mRange .lb")).to_have_text("Size")
    _close(page)

    page.locator('#menubar [data-menu="help"]').click()
    expect(menu).to_be_visible()
    assert _labels(page) == [
        "Keyboard shortcuts", "Connect AI agent", "GitHub repository", "Report an issue",
    ]
    source = menu.locator("a").filter(has_text="GitHub repository")
    expect(source).to_have_attribute("href", "https://github.com/fl-grtg/typst-editor")
    expect(source).to_have_attribute("target", "_blank")
    issues = menu.locator("a").filter(has_text="Report an issue")
    expect(issues).to_have_attribute("href", "https://github.com/fl-grtg/typst-editor/issues")
    expect(issues).to_have_attribute("target", "_blank")
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


def test_menubar_menus_share_one_width(page):
    register(page, "e2e_menu_width")
    create_doc(page, "Menu width")
    menu = page.locator("#menu")
    widths = []

    for name in ("file", "edit", "view", "help"):
        page.locator(f'#menubar [data-menu="{name}"]').click()
        expect(menu).to_be_visible()
        widths.append(round(menu.bounding_box()["width"]))
        if name == "view":
            menu.locator("button").filter(has_text="View mode").click()
            expect(page.locator("#submenu")).to_be_visible()
            assert round(page.locator("#submenu").bounding_box()["width"]) < widths[-1]  # submenus stay compact
        _close(page)

    assert len(set(widths)) == 1
    assert widths[0] < 300  # the shared width follows the longest menu, not a fixed panel width


def test_checkable_rows_keep_the_menu_open(page):
    register(page, "e2e_menu_keep_open")
    create_doc(page, "Menu keep open")
    menu = page.locator("#menu")
    sub = page.locator("#submenu")

    page.locator('#menubar [data-menu="view"]').click()
    menu.locator("button").filter(has_text="View mode").click()
    expect(sub).to_be_visible()
    page.evaluate("window.__modeRow = [...document.querySelectorAll('#menu button')].find(b => b.textContent.trim() === 'View mode')")
    sub.get_by_role("menuitemcheckbox", name="Editor only").click()
    expect(menu).to_be_visible()
    expect(sub).to_be_visible()
    expect(sub.get_by_role("menuitemcheckbox", name="Editor only")).to_have_attribute("aria-checked", "true")
    assert page.evaluate("window.__modeRow === [...document.querySelectorAll('#menu button')].find(b => b.textContent.trim() === 'View mode')")
    assert page.evaluate("window.__modeRow.classList.contains('sub-open')")

    sub.get_by_role("menuitemcheckbox", name="Editor and preview").click()
    expect(sub).to_be_visible()
    expect(sub.get_by_role("menuitemcheckbox", name="Editor and preview")).to_have_attribute("aria-checked", "true")

    # A programmatic click does not focus the row (Safari leaves focus on body): ticks must still follow the panel.
    page.evaluate("document.activeElement && document.activeElement.blur()")
    sub.get_by_role("menuitemcheckbox", name="Editor only").evaluate("el => el.click()")
    expect(sub.get_by_role("menuitemcheckbox", name="Editor only")).to_have_attribute("aria-checked", "true")
    expect(sub.get_by_role("menuitemcheckbox", name="Editor and preview")).to_have_attribute("aria-checked", "false")
    expect(menu).to_be_visible()
    expect(sub).to_be_visible()
    expect(menu.locator("button").filter(has_text="Preview options")).to_be_disabled()  # parent row follows the new mode
    sub.get_by_role("menuitemcheckbox", name="Editor and preview").evaluate("el => el.click()")  # split keeps preview rows enabled below
    expect(sub.get_by_role("menuitemcheckbox", name="Editor and preview")).to_have_attribute("aria-checked", "true")
    expect(menu.locator("button").filter(has_text="Preview options")).to_be_enabled()
    _close(page)

    page.locator('#menubar [data-menu="view"]').click()
    menu.locator("button").filter(has_text="Preview options").click()
    expect(sub).to_be_visible()
    follow = sub.get_by_role("menuitemcheckbox", name="Follow cursor and scrolling")
    expect(follow).to_have_attribute("aria-checked", "true")
    follow.click()
    expect(menu).to_be_visible()
    expect(sub).to_be_visible()
    expect(follow).to_have_attribute("aria-checked", "false")
    _close(page)

    page.locator('#menubar [data-menu="view"]').click()
    menu.locator("button").filter(has_text="Appearance").click()
    expect(sub).to_be_visible()
    sub.get_by_role("menuitemcheckbox", name="Dark theme").click()
    expect(menu).to_be_visible()
    expect(sub).to_be_visible()
    expect(sub.get_by_role("menuitemcheckbox", name="Dark theme")).to_have_attribute("aria-checked", "true")
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")


def test_sidebar_row_stays_open_without_a_tick(page):
    register(page, "e2e_menu_sidebar")
    create_doc(page, "Menu sidebar")
    menu = page.locator("#menu")

    page.locator('#menubar [data-menu="view"]').click()
    row = menu.locator("button").filter(has_text="Toggle sidebar")
    expect(row).to_be_visible()
    expect(row.locator(".chk")).to_have_count(0)
    row.click()

    expect(menu).to_be_visible()
    assert page.evaluate("document.body.classList.contains('noside')")
    row = menu.locator("button").filter(has_text="Toggle sidebar")
    expect(row).to_be_visible()
    expect(row.locator(".chk")).to_have_count(0)
    row.click()

    expect(menu).to_be_visible()
    assert not page.evaluate("document.body.classList.contains('noside')")


def test_preview_zoom_is_a_slider_in_its_own_submenu(page):
    register(page, "e2e_menu_zoom")
    create_doc(page, "Menu zoom")
    page.locator('#menubar [data-menu="view"]').click()
    menu = page.locator("#menu")
    sub = page.locator("#submenu")

    menu.locator("button").filter(has_text="Preview options").click()
    expect(sub).to_be_visible()
    slider = sub.locator(".mRange input[type=range]")
    expect(sub.locator(".mRange .lb")).to_have_text("Zoom")
    expect(slider).to_have_attribute("aria-label", "Preview zoom")
    assert "Zoom in" not in _labels(page, "#submenu")
    assert "Zoom out" not in _labels(page, "#submenu")

    slider.evaluate("el => { el.value = '150'; el.dispatchEvent(new Event('input', { bubbles: true })) }")
    expect(slider).to_have_value("150")
    expect(page.locator("#zoomV")).to_have_text("150%")
    expect(menu).to_be_visible()
    expect(sub).to_be_visible()
    assert page.evaluate("localStorage.getItem('typst_pv')") == "150"


def test_font_size_is_a_slider_in_its_own_submenu(page):
    register(page, "e2e_menu_font")
    create_doc(page, "Menu font")
    page.locator('#menubar [data-menu="view"]').click()
    menu = page.locator("#menu")
    sub = page.locator("#submenu")

    expect(menu.locator(".mRange")).to_have_count(0)
    menu.locator("button").filter(has_text="Editor font size").click()
    expect(sub).to_be_visible()
    slider = sub.locator(".mRange input[type=range]")

    expect(sub.locator(".mRange .lb")).to_have_text("Size")
    expect(slider).to_have_attribute("aria-label", "Editor font size")
    expect(slider).to_have_value("14")
    slider.focus()
    page.keyboard.press("ArrowRight")
    expect(slider).to_have_value("15")
    expect(menu).to_be_visible()
    expect(sub).to_be_visible()
    assert page.evaluate("localStorage.getItem('typst_ed')") == "15"
    assert page.evaluate("getComputedStyle(document.getElementById('cmWrap')).getPropertyValue('--ed').trim()") == "15px"
    page.keyboard.press("Escape")  # back out of the submenu only, like any other submenu row
    expect(sub).to_be_hidden()
    expect(menu).to_be_visible()
