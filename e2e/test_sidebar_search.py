"""Sidebar search: filter menu, scoped tree matches, content hits and find handoff."""
from playwright.sync_api import expect

from e2e.helpers import register


def _setup(page, name):
    register(page, name)
    created = page.request.post("/api/docs/create", data={
        "title": "Alpha doc", "content": "= Intro\n\nSome needletexte here.\n\n= Other\n\ntail"}).json()
    did = created["id"]
    doc = next(d for d in page.request.get("/api/docs").json()["own"] if d["id"] == did)
    pid = doc["project_id"]
    assert page.request.post(f"/api/projects/{pid}/resources", data={
        "name": "assets/sub/bild1.typ", "content": "#let bananaphone = 1"}).ok
    assert page.request.post(f"/api/projects/{pid}/folders", data={"path": "assets/leer"}).ok
    assert page.request.post("/api/projects", data={"title": "Beta project"}).ok
    page.reload()
    page.wait_for_function("window.__booted === true")
    return did, pid


def _open_filters(page):
    page.click("#qFilter")
    menu = page.locator("#searchFilters")
    expect(menu).to_be_visible()
    return menu


def _toggle_filter(page, key):
    menu = _open_filters(page)
    item = menu.locator(f'[data-sf="{key}"]')
    item.click()
    page.keyboard.press("Escape")
    expect(menu).to_have_count(0)


def _has_filter_dot(page):
    return page.locator("#qFilter").evaluate("n => n.classList.contains('has-filters')")


def test_filter_menu_states_and_session_persistence(page):
    _setup(page, "search_filters")
    menu = _open_filters(page)
    expect(menu.locator('[data-sf="projects"]')).to_have_attribute("aria-checked", "true")
    expect(menu.locator('[data-sf="modules"]')).to_have_attribute("aria-checked", "true")
    expect(menu.locator('[data-sf="shared"]')).to_have_attribute("aria-checked", "true")
    expect(menu.locator('[data-sf="trash"]')).to_have_attribute("aria-checked", "true")
    expect(menu.locator('[data-sf="outline"]')).to_have_attribute("aria-checked", "false")
    expect(menu.locator('[data-sf="content"]')).to_have_attribute("aria-checked", "false")
    assert not _has_filter_dot(page)
    menu.locator('[data-sf="outline"]').click()
    expect(menu.locator('[data-sf="outline"]')).to_have_attribute("aria-checked", "true")
    expect(menu.locator('[data-sf="outline"] .ck')).to_have_text("✓")
    assert _has_filter_dot(page)
    page.keyboard.press("Escape")
    expect(menu).to_have_count(0)

    page.reload()
    page.wait_for_function("window.__booted === true")
    menu = _open_filters(page)
    expect(menu.locator('[data-sf="outline"]')).to_have_attribute("aria-checked", "true")
    assert _has_filter_dot(page)
    # back to defaults: the dot disappears
    menu.locator('[data-sf="outline"]').click()
    assert not _has_filter_dot(page)


def test_filter_menu_tools_and_content_checkbox(page):
    register(page, "search_tools")
    page.fill("#q", "anything")
    menu = _open_filters(page)
    expect(menu.locator('[data-sf="content"] .sfSw')).to_have_count(0)  # same check mark as every area
    expect(menu.locator('[data-sf="content"] .ck')).to_have_text("")
    menu.locator('[data-sf="content"]').click()
    expect(menu.locator('[data-sf="content"] .ck')).to_have_text("✓")
    expect(menu.locator('[data-act="clear"]')).to_have_attribute("title", "Clear selection")
    expect(menu.locator('[data-act="reset"]')).to_have_attribute("title", "Reset filters")
    assert _has_filter_dot(page)
    # The filled funnel uses the text color while the menu is open (not muted gray).
    page.wait_for_timeout(200)  # color transition
    assert page.eval_on_selector("#qFilter", "e => getComputedStyle(e).color") == \
        page.eval_on_selector("body", "e => getComputedStyle(e).color")

    menu.locator('[data-act="reset"]').click()
    expect(menu.locator('[data-sf="content"]')).to_have_attribute("aria-checked", "false")
    expect(menu.locator('[data-sf="content"] .ck')).to_have_text("")
    expect(menu.locator('[data-sf="projects"]')).to_have_attribute("aria-checked", "true")
    assert not _has_filter_dot(page)

    menu.locator('[data-act="clear"]').click()
    expect(menu).to_be_visible()  # stays open so the cleared selection is visible
    for key in ("projects", "modules", "shared", "trash", "outline", "content"):
        expect(menu.locator(f'[data-sf="{key}"]')).to_have_attribute("aria-checked", "false")
        expect(menu.locator(f'[data-sf="{key}"] .ck')).to_have_text("")
    expect(page.locator("#q")).to_have_value("anything")  # clear drops the areas, not the query
    expect(page.locator("#searchNone")).to_be_visible()
    expect(page.locator("#searchNone")).to_have_text("No options selected")
    assert _has_filter_dot(page)

    # Re-checking an area brings the results back.
    menu.locator('[data-sf="projects"]').click()
    expect(page.locator("#searchNone")).to_be_hidden()

    # The filled funnel follows the empty one on hover: text color, not muted gray.
    page.keyboard.press("Escape")
    page.hover("#qFilter")
    page.wait_for_timeout(250)  # color transition
    assert page.eval_on_selector("#qFilter", "e => getComputedStyle(e).color") == \
        page.eval_on_selector("body", "e => getComputedStyle(e).color")


def test_modules_and_trash_areas_drop_out_when_filtered(page):
    register(page, "search_areas")
    assert page.request.post("/api/templates", data={"name": "needle-module.typ", "content": "#let a = 1"}).ok
    trashed = page.request.post("/api/docs/create", data={"title": "Trash needle", "content": "x"}).json()
    assert page.request.delete(f"/api/docs/{trashed['id']}").ok
    page.reload()
    page.wait_for_function("window.__booted === true")

    page.fill("#q", "needle")
    expect(page.locator("#tpls .doc", has_text="needle-module.typ")).to_be_visible()
    expect(page.locator("#trash .doc", has_text="Trash needle")).to_be_visible()

    _toggle_filter(page, "modules")
    expect(page.locator("#tplH")).to_be_hidden()
    expect(page.locator("#tpls .doc")).to_have_count(0)
    _toggle_filter(page, "trash")
    expect(page.locator("#trashH")).to_be_hidden()
    expect(page.locator("#trash .doc")).to_have_count(0)
    _toggle_filter(page, "projects")
    expect(page.locator("#ownH")).to_be_hidden()
    expect(page.locator("#own .project-group")).to_have_count(0)
    page.click("#qClear")


def test_project_search_filters_entries_and_shows_full_paths(page):
    _setup(page, "search_projects")
    project = page.locator("aside .project-group").filter(has_text="Alpha doc").first
    header = project.locator(".fhd.project b")
    header.click()  # save a collapsed project: search must expand it without touching that state
    expect(header).to_have_attribute("aria-expanded", "false")

    page.fill("#q", "bild1")
    expect(project.locator(".fhd.folder", has_text="assets/sub")).to_be_visible()
    expect(project.locator(".doc.sub", has_text="assets/sub/bild1.typ")).to_be_visible()
    expect(project.locator(".doc.sub", has_text="Alpha doc")).to_have_count(0)  # non-matching doc is filtered out
    expect(header).to_have_attribute("aria-expanded", "true")
    expect(page.locator("#qClear")).to_be_visible()
    expect(page.locator("#own mark.qhit").first).to_have_text("bild1")  # the match is highlighted in the row

    # Folders stay collapsible during a search; folding does not touch the saved state.
    folder = project.locator(".fhd.folder", has_text="assets/sub")
    folder.locator("b").click()
    expect(folder.locator("b")).to_have_attribute("aria-expanded", "false")
    expect(project.locator(".doc.sub", has_text="assets/sub/bild1.typ")).to_have_count(0)
    folder.locator("b").click()
    expect(project.locator(".doc.sub", has_text="assets/sub/bild1.typ")).to_be_visible()

    page.click("#qClear")
    expect(page.locator("#q")).to_have_value("")
    expect(header).to_have_attribute("aria-expanded", "false")  # saved collapse state survived the search
    expect(project.locator(".doc.sub", has_text="assets/sub/bild1.typ")).to_have_count(0)

    page.fill("#q", "leer")  # a matching empty folder still shows up
    expect(project.locator(".fhd.folder", has_text="assets/leer")).to_be_visible()
    page.click("#qClear")


def test_content_search_badges_and_opens_find_in_document(page):
    _setup(page, "search_content")
    page.fill("#q", "needletexte")
    expect(page.locator("#own .doc", has_text="Alpha doc")).to_have_count(0)  # content is opt-in
    expect(page.locator("#searchEmpty")).to_be_visible()
    expect(page.locator("#searchEmpty")).to_contain_text("Nothing found")
    expect(page.locator("#own .empty")).to_be_hidden()  # one global message, not one per area

    _toggle_filter(page, "content")
    row = page.locator("#own .doc", has_text="Alpha doc")
    expect(row).to_be_visible()
    expect(page.locator("#searchEmpty")).to_be_hidden()
    badge = row.locator(".hitN")
    expect(badge).to_have_text("1")
    expect(badge).to_be_visible()
    geo = badge.evaluate("""b => {
      const r = b.getBoundingClientRect(), row = b.parentElement.getBoundingClientRect()
      const side = document.getElementById('side'), cs = getComputedStyle(b)
      return { position: cs.position, background: cs.backgroundColor, color: cs.color,
               borderTop: cs.borderTopWidth, borderLeft: cs.borderLeftWidth,
               sideBg: getComputedStyle(side).backgroundColor, text: getComputedStyle(document.body).color,
               left: r.left, mid: r.top + r.height / 2,
               rowMid: row.top + row.height / 2, sideRight: side.getBoundingClientRect().right }
    }""")
    assert geo["position"] == "fixed"  # out of flow: the row never shifts
    assert geo["background"] == geo["sideBg"]  # seamless with the sidebar surface
    assert geo["color"] == geo["text"]  # only the number: black on light, white on dark
    assert geo["borderTop"] == "1px" and geo["borderLeft"] == "0px"  # outlined on the free sides, open at the seal
    assert abs(geo["left"] - (geo["sideRight"] - 1)) < 1.5  # fused to the sidebar edge
    assert abs(geo["mid"] - geo["rowMid"]) < 1.5  # centered on its row
    expect(badge).to_have_attribute("title", "1 content hits – click to open")
    assert badge.get_attribute("aria-label") == badge.get_attribute("title")

    # The resize splitter rises above the tabs while its blue line is visible, so it is never cut.
    page.hover("#sideSplit")
    expect(page.locator("#sideSplit")).to_have_css("z-index", "7")
    assert badge.evaluate("b => getComputedStyle(b).zIndex") == "6"
    page.mouse.move(900, 600)
    page.wait_for_timeout(200)
    expect(page.locator("#sideSplit")).to_have_css("z-index", "5")

    # Clicking the blob opens the file, just like clicking the row (the event bubbles).
    badge.click(position={"x": 15, "y": 10})
    expect(page.locator("#find")).to_be_visible()
    expect(page.locator("#fQ")).to_have_value("needletexte")
    expect(page.locator("#fN")).to_have_text("1/1")
    expect(page.locator("#cm .cm-find-cur").first).to_be_visible()

    # Leftover regex / match-case toggles must not change what a sidebar hit finds.
    page.click("#fRe")
    page.click("#fCase")
    page.fill("#q", "needle.exte")  # as a regex this would match; as plain text it must not
    expect(page.locator("#own .doc", has_text="Alpha doc")).to_have_count(0)
    page.fill("#q", "NEEDLETEXTE")
    page.locator("#own .doc", has_text="Alpha doc").click()
    expect(page.locator("#fN")).to_have_text("1/1")
    expect(page.locator("#fRe")).to_have_attribute("aria-pressed", "false")
    expect(page.locator("#fCase")).to_have_attribute("aria-pressed", "false")

    page.fill("#q", "bananaphone")
    module = page.locator("#own .doc.sub", has_text="assets/sub/bild1.typ")
    expect(module).to_be_visible()
    module_badge = module.locator(".hitN")
    expect(module_badge).to_have_text("1")
    module.click()
    expect(page.locator("#title")).to_have_text("assets/sub/bild1.typ")
    expect(page.locator("#find")).to_be_visible()
    expect(page.locator("#fQ")).to_have_value("bananaphone")
    expect(page.locator("#cm .cm-find-cur").first).to_be_visible()

    # Collapsed sidebar: the tabs leave with the panel; expanding brings them back on the edge.
    page.click('.sbHead [data-rail="toggle"]')
    expect(module_badge).to_be_hidden()
    page.click('.sbRail [data-rail="toggle"]')
    expect(module_badge).to_be_visible()


def test_outline_search_respects_its_filter_and_empty_state(page):
    _setup(page, "search_outline")
    page.locator("aside .doc.sub", has_text="Alpha doc").first.click()
    expect(page.locator("#title")).to_have_text("Alpha doc")
    expect(page.locator("#ol .doc")).to_have_count(2)

    page.fill("#q", "other")
    expect(page.locator("#olH")).to_be_hidden()  # outline area is off by default
    expect(page.locator("#ol .doc")).to_have_count(0)

    _toggle_filter(page, "outline")
    expect(page.locator("#olH")).to_be_visible()
    expect(page.locator("#ol .doc", has_text="Other")).to_be_visible()
    expect(page.locator("#ol .doc")).to_have_count(1)
    expect(page.locator("#ol mark.qhit").first).to_have_text("Other")

    page.fill("#q", "no-such-heading")
    expect(page.locator("#searchEmpty")).to_be_visible()  # one global message instead of an empty area
    expect(page.locator("#ol .empty")).to_be_hidden()
    expect(page.locator("#ol .empty button")).to_have_count(0)  # empty state has no clear-search action
    page.click("#qClear")
    expect(page.locator("#ol .doc")).to_have_count(2)  # normal outline is back

    # A module has no source outline: searching must still explain the empty area.
    page.locator("#own .doc.sub", has_text="bild1.typ").first.click()
    expect(page.locator("#title")).to_have_text("assets/sub/bild1.typ")
    page.fill("#q", "Alpha")
    expect(page.locator("#own .doc", has_text="Alpha doc")).to_be_visible()  # another hit keeps the sections visible
    expect(page.locator("#ol .empty")).to_be_visible()
    expect(page.locator("#ol .empty")).to_contain_text("Nothing found")
    page.click("#qClear")


def test_content_search_supports_a_single_character(page):
    _setup(page, "search_one_char")
    created = page.request.post("/api/docs/create", data={"title": "Gamma", "content": "quasar"}).json()
    assert created["id"]
    page.reload()
    page.wait_for_function("window.__booted === true")

    _toggle_filter(page, "content")
    page.fill("#q", "q")
    row = page.locator("#own .doc", has_text="Gamma")
    expect(row).to_be_visible()
    expect(row.locator(".hitN")).to_have_text("1")
    page.click("#qClear")
