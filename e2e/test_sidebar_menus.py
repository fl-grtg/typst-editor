"""Sidebar row actions open as anchored dropdowns and rename inline."""
import io
import zipfile

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
    expect(menu).to_contain_text("Rename")
    expect(menu.locator("button.danger")).to_contain_text("Move to trash")
    _assert_anchored(page, menu, more)

    menu.locator("button").filter(has_text="Rename").click()
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
    # The template list arrives after boot; checking visibility too early used to
    # toggle the section closed instead of opening it, so wait for the row first.
    expect(row).to_have_count(1)
    if page.locator("#tplH").get_attribute("aria-expanded") == "false":
        page.locator("#tplH").press("Enter")
    expect(row).to_be_visible()
    old_row = row.element_handle()
    row.hover()
    row.locator("button[data-side-menu]").click()
    menu = page.locator("#menu")
    expect(menu).to_be_visible()

    response = page.request.post("/api/docs/create", data={"title": "Refresh trigger", "content": ""})
    assert response.ok, response.text()
    expect(page.locator("#own .doc .t", has_text="Refresh trigger")).to_be_visible()
    assert page.evaluate("node => !node.isConnected", old_row)

    menu.locator("button").filter(has_text="Rename").click()
    inp = page.locator("#tpls input.renameInput")
    expect(inp).to_be_visible()
    assert inp.evaluate("el => [el.selectionStart, el.selectionEnd]") == [0, len("module")]  # extension stays out of the selection
    inp.fill("module-renamed.typ")
    inp.press("Enter")
    expect(page.locator("#tpls .doc .t", has_text="module-renamed.typ")).to_be_visible()


def test_inline_rename_survives_sidebar_refresh(page):
    register(page, "e2e_rename_refresh")
    create_doc(page, "Rename stays")
    row = page.locator("#own .doc").filter(has=page.locator(".t", has_text="Rename stays")).first
    row.hover()
    row.locator("button[data-side-menu]").click()
    page.locator("#menu button").filter(has_text="Rename").click()

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
    expect(menu).to_contain_text("Rename")
    expect(menu.locator("button.danger")).to_contain_text("Move to trash")
    _assert_anchored(page, menu, more)

    menu.locator("button").filter(has_text="Rename").click()
    expect(page.locator(".fhd.project input.renameInput")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator(".fhd.project input.renameInput")).to_have_count(0)
    expect(page.locator(".project-group .fhd.project b", has_text="Sidebar project")).to_be_visible()


def test_project_and_folder_plus_open_the_same_compact_menu(page):
    register(page, "e2e_plus_menus")
    create_doc(page, "Plus menu doc")
    group = page.locator(".project-group").filter(has=page.locator(".fhd.project b", has_text="Plus menu doc")).first
    head = group.locator(".fhd.project")
    menu = page.locator("#menu")
    entries = ("New document", "New module", "New folder", "Upload file", "Import from my modules")

    head.hover()
    head.locator("button.mini").first.click()
    expect(menu).to_be_visible()
    expect(page.locator("#modal")).to_be_hidden()
    for label in entries:
        expect(menu.locator("button").filter(has_text=label)).to_have_count(1)
    page.keyboard.press("Escape")
    expect(menu).to_be_hidden()

    head.hover()
    head.locator("button.mini").first.click()
    menu.locator("button").filter(has_text="New folder").click()
    page.fill("#mInp", "ordner")
    page.click("#mYes")
    folder = page.locator("aside .fhd.folder").filter(has=page.locator("b", has_text="ordner")).first
    folder.hover()
    folder.locator("button.mini").first.click()
    expect(menu).to_be_visible()
    for label in entries:
        expect(menu.locator("button").filter(has_text=label)).to_have_count(1)
    page.keyboard.press("Escape")


def test_copy_submenu_can_be_reached_with_the_mouse(page):
    register(page, "e2e_submenu_reach")
    create_doc(page, "Submenu doc")
    row = page.locator("#own .doc").filter(has=page.locator(".t", has_text="Submenu doc")).first
    row.hover()
    row.locator("button[data-side-menu]").click()
    copy = page.locator("#menu button").filter(has_text="Copy to").first
    copy.hover()
    sub = page.locator("#submenu")
    expect(sub).to_be_visible()
    expect(sub.locator("button").first).to_contain_text("In this project")

    box = copy.bounding_box()
    assert box
    page.mouse.move(box["x"] + box["width"] - 10, box["y"] + box["height"] / 2)
    page.wait_for_timeout(150)
    page.mouse.move(box["x"] + box["width"] + 24, box["y"] + box["height"] / 2 + 12, steps=6)
    page.wait_for_timeout(450)  # longer than the old instant-close window
    expect(sub).to_be_visible()

    sub.locator("button").first.click()
    expect(page.locator("#modal")).to_be_visible()
    expect(page.locator("#mHead")).to_have_text("In this project")
    page.locator("#mCard .mTop button").click()
    expect(page.locator("#modal")).to_be_hidden()


def test_copy_to_another_folder_keeps_the_document_title(page):
    register(page, "e2e_copy_keeps_title")
    create_doc(page, "Keep title")
    pid = next(d["project_id"] for d in page.request.get("/api/docs").json()["own"] if d["title"] == "Keep title")
    assert page.request.post(f"/api/projects/{pid}/folders", data={"path": "target"}).ok
    page.reload()
    page.wait_for_function("window.__booted === true")

    row = page.locator("#own .doc").filter(has=page.locator(".t", has_text="Keep title")).first
    row.hover()
    row.locator("button[data-side-menu]").click()
    page.locator("#menu button").filter(has_text="Copy to").first.hover()
    page.locator("#submenu button").filter(has_text="In this project").click()
    expect(page.locator("#mHead")).to_have_text("In this project")
    page.locator("#modal button").filter(has_text="target").first.click()
    expect(page.locator("#modal")).to_be_hidden()

    expect(page.locator("#own .doc .t", has_text="Keep title")).to_have_count(2)
    docs = page.request.get(f"/api/projects/{pid}").json()["documents"]
    assert sorted((d["title"], d["folder"]) for d in docs) == [("Keep title", ""), ("Keep title", "target")]


def test_folder_module_submenu_skips_the_type_picker(page):
    register(page, "e2e_folder_module")
    create_doc(page, "Folder module")
    pid = next(d["project_id"] for d in page.request.get("/api/docs").json()["own"] if d["title"] == "Folder module")
    assert page.request.post(f"/api/projects/{pid}/folders", data={"path": "sub"}).ok
    page.reload()
    page.wait_for_function("window.__booted === true")

    folder = page.locator("aside .fhd.folder").filter(has=page.locator("b", has_text="sub")).first
    folder.hover()
    folder.locator("button.mini").first.click()
    page.locator("#menu button").filter(has_text="New module").first.hover()
    sub = page.locator("#submenu")
    expect(sub).to_be_visible()
    sub.locator("button").filter(has_text=".typ").first.click()

    expect(page.locator("#mHead")).to_have_text("New file")  # name prompt, not the type picker again
    inp = page.locator("#mInp")
    expect(inp).to_have_value("file.typ")  # suggested name with the chosen extension
    assert inp.evaluate("el => [el.selectionStart, el.selectionEnd]") == [0, 4]  # only "file" is selected
    page.fill("#mInp", "mod")
    page.click("#mYes")
    expect(page.locator("#modal")).to_be_hidden()
    resources = page.request.get(f"/api/projects/{pid}/resources").json()["resources"]
    assert "sub/mod.typ" in [r["name"] for r in resources]


def test_module_suggestion_selects_only_the_name(page):
    register(page, "e2e_mod_suggest")
    head = page.locator("#tplH")
    head.hover()
    head.locator("button.mini").click()
    page.locator("#menu button").filter(has_text="Typst").first.click()

    expect(page.locator("#mHead")).to_have_text("New module")
    inp = page.locator("#mInp")
    expect(inp).to_have_value("file.typ")
    page.wait_for_timeout(50)
    assert inp.evaluate("el => [el.selectionStart, el.selectionEnd]") == [0, 4]
    page.fill("#mInp", "quick")
    page.click("#mYes")
    expect(page.locator("#tpls .doc .t", has_text="quick.typ")).to_be_visible()


def test_rename_keeps_the_folder_path_out_of_the_input(page):
    register(page, "e2e_rename_path")
    create_doc(page, "Rename path")
    pid = next(d["project_id"] for d in page.request.get("/api/docs").json()["own"] if d["title"] == "Rename path")
    assert page.request.post(f"/api/projects/{pid}/resources", data={"name": "sub/notes.typ", "content": "= Notes"}).ok
    page.reload()
    page.wait_for_function("window.__booted === true")

    row = page.locator("aside .doc").filter(has=page.locator(".t", has_text="notes.typ")).first
    row.hover()
    row.locator("button[data-side-menu]").click()
    page.locator("#menu button").filter(has_text="Rename").click()
    inp = page.locator("aside input.renameInput")
    expect(inp).to_have_value("notes.typ")  # no "sub/" prefix
    page.wait_for_timeout(50)
    assert inp.evaluate("el => [el.selectionStart, el.selectionEnd]") == [0, 5]
    inp.fill("renamed.typ")
    inp.press("Enter")
    page.locator("#mYes").click()  # rename preview confirms the new path
    expect(page.locator("aside .doc .t", has_text="renamed.typ")).to_be_visible()
    names = [r["name"] for r in page.request.get(f"/api/projects/{pid}/resources").json()["resources"]]
    assert "sub/renamed.typ" in names and "sub/notes.typ" not in names


def test_duplicate_document_does_not_clone_files_in_other_folders(page):
    register(page, "e2e_duplicate_files")
    create_doc(page, "Duplicate files")
    doc = next(d for d in page.request.get("/api/docs").json()["own"] if d["title"] == "Duplicate files")
    pid = doc["project_id"]
    uploaded = page.request.post(f"/api/docs/{doc['id']}/files", multipart={
        "f": {"name": "bilder/pfeil.svg", "mimeType": "image/svg+xml", "buffer": b"<svg/>"},
    })
    assert uploaded.ok, uploaded.text()

    page.reload()
    page.wait_for_function("window.__booted === true")
    row = page.locator("#own .doc").filter(has=page.locator(".t", has_text="Duplicate files")).first
    row.hover()
    row.locator("button[data-side-menu]").click()
    page.locator("#menu button").filter(has_text="Duplicate").click()
    expect(page.locator("#own .doc .t", has_text="Duplicate files (copy)")).to_be_visible()

    project = page.request.get(f"/api/projects/{pid}").json()
    assert [f["name"] for f in project["files"]] == ["bilder/pfeil.svg"]  # the project file stays shared, not cloned
    copy = next(d for d in project["documents"] if d["title"] == "Duplicate files (copy)")
    assert page.request.get(f"/api/docs/{copy['id']}/files").json()["files"] == []


def test_folder_upload_lands_in_that_folder(page):
    register(page, "e2e_folder_upload")
    create_doc(page, "Folder upload")
    pid = next(d["project_id"] for d in page.request.get("/api/docs").json()["own"] if d["title"] == "Folder upload")
    assert page.request.post(f"/api/projects/{pid}/folders", data={"path": "sub"}).ok
    page.reload()
    page.wait_for_function("window.__booted === true")

    for name, mime, data in (("note.txt", "text/plain", b"hello"), ("pic.png", "image/png", b"\x89PNG\r\n")):
        folder = page.locator("aside .fhd.folder").filter(has=page.locator("b", has_text="sub")).first
        folder.hover()
        folder.locator("button.mini").first.click()
        with page.expect_file_chooser() as chooser:
            page.locator("#menu button").filter(has_text="Upload file").first.click()
        chooser.value.set_files({"name": name, "mimeType": mime, "buffer": data})
        expect(page.locator("aside .doc .t", has_text=name)).to_be_visible()

    project = page.request.get(f"/api/projects/{pid}").json()
    assert "sub/note.txt" in [r["name"] for r in project["resources"]]
    assert "sub/pic.png" in [f["name"] for f in project["files"]]

    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w") as z:
        z.writestr("main.typ", "= Imported")
    folder = page.locator("aside .fhd.folder").filter(has=page.locator("b", has_text="sub")).first
    folder.hover()
    folder.locator("button.mini").first.click()
    with page.expect_file_chooser() as chooser:
        page.locator("#menu button").filter(has_text="Upload file").first.click()
    chooser.value.set_files({"name": "bundle.zip", "mimeType": "application/zip", "buffer": bundle.getvalue()})
    expect(page.locator("#mHead")).to_have_text("New document")
    page.fill("#mInp", "Zip folder doc")
    page.click("#mYes")
    expect(page.locator("aside .doc .t", has_text="Zip folder doc")).to_be_visible()
    project = page.request.get(f"/api/projects/{pid}").json()
    assert any(d["title"] == "Zip folder doc" and d["folder"] == "sub" for d in project["documents"])  # ZIP import keeps the folder


def test_empty_trash_lives_behind_the_section_three_dot(page):
    register(page, "e2e_trash_menu")
    create_doc(page, "Trash menu doc")
    doc = next(d for d in page.request.get("/api/docs").json()["own"] if d["title"] == "Trash menu doc")
    assert page.request.delete(f"/api/docs/{doc['id']}").ok
    page.reload()
    page.wait_for_function("window.__booted === true")

    head = page.locator("#trashH")
    more = head.locator("button[data-side-menu]")
    expect(more).to_be_hidden()  # row action like every other section
    head.hover()
    expect(more).to_be_visible()
    more.click()
    menu = page.locator("#menu")
    expect(menu).to_be_visible()
    expect(menu.locator("button")).to_have_count(1)
    expect(menu.locator("button.danger")).to_have_text("Empty trash")

    menu.locator("button").click()
    expect(page.locator("#mHead")).to_have_text("1 document delete permanently?")
    page.click("#mYes")
    expect(page.locator("#trash")).to_contain_text("Trash is empty")
    expect(page.locator("#trashH button[data-side-menu]")).to_have_count(0)


def test_module_and_trash_rows_sit_close_to_their_sections(page):
    register(page, "e2e_section_indent")
    assert page.request.post("/api/templates", data={"name": "indent.typ", "content": "= Indent"}).ok
    create_doc(page, "Indent trash")
    doc = next(d for d in page.request.get("/api/docs").json()["own"] if d["title"] == "Indent trash")
    assert page.request.delete(f"/api/docs/{doc['id']}").ok
    page.reload()
    page.wait_for_function("window.__booted === true")

    assert page.locator("#tpls .doc").first.evaluate("el => getComputedStyle(el).marginLeft") == "20px"
    assert page.locator("#trash .doc").first.evaluate("el => getComputedStyle(el).marginLeft") == "20px"


def test_move_into_a_subfolder_and_copy_to_another_project(page):
    register(page, "e2e_cross_transfer")
    create_doc(page, "Transfer source")
    doc = next(d for d in page.request.get("/api/docs").json()["own"] if d["title"] == "Transfer source")
    pid = doc["project_id"]
    assert page.request.post(f"/api/projects/{pid}/folders", data={"path": "ziel"}).ok
    target_pid = page.request.post("/api/projects", data={"title": "Transfer target"}).json()["id"]
    assert page.request.post(f"/api/projects/{target_pid}/folders", data={"path": "ablage"}).ok
    page.reload()
    page.wait_for_function("window.__booted === true")

    def row():
        item = page.locator("#own .doc").filter(has=page.locator(".t", has_text="Transfer source")).first
        button = item.locator("button[data-side-menu]")
        for _ in range(10):  # a repaint after the first action swaps the row under a resting pointer: hover again
            item.hover()
            if button.is_visible():
                break
            page.wait_for_timeout(150)
        button.click()
        return page.locator("#menu")

    menu = row()
    menu.locator("button").filter(has_text="Move to").first.hover()
    page.locator("#submenu button").filter(has_text="In this project").click()
    expect(page.locator("#mHead")).to_have_text("In this project")
    page.locator("#modal button").filter(has_text="ziel").first.click()
    expect(page.locator("#modal")).to_be_hidden()
    docs = page.request.get(f"/api/projects/{pid}").json()["documents"]
    assert [(d["title"], d["folder"]) for d in docs if d["title"] == "Transfer source"] == [("Transfer source", "ziel")]

    menu = row()
    menu.locator("button").filter(has_text="Copy to").first.hover()
    page.locator("#submenu button").filter(has_text="To another project").click()
    expect(page.locator("#mHead")).to_have_text("To another project")
    page.locator("#modal button").filter(has_text="Transfer target").first.click()
    expect(page.locator("#mHead")).to_have_text("Target folder in Transfer target")
    page.locator("#modal button").filter(has_text="ablage").first.click()
    expect(page.locator("#mHead")).to_contain_text("Target path")  # copy keeps the title until a conflict needs a new one
    page.click("#mYes")
    expect(page.locator("#modal")).to_be_hidden()
    copied = page.request.get(f"/api/projects/{target_pid}").json()["documents"]
    assert [(d["title"], d["folder"]) for d in copied if d["title"] == "Transfer source"] == [("Transfer source", "ablage")]


def test_read_only_member_can_still_copy_entries_out_of_a_shared_project(page, browser, base_url):
    register(page, "e2e_ro_owner")
    create_doc(page, "Shared source")
    doc = next(d for d in page.request.get("/api/docs").json()["own"] if d["title"] == "Shared source")
    pid = doc["project_id"]
    assert page.request.post(f"/api/projects/{pid}/resources", data={"name": "layout.typ", "content": "#let a = 1"}).ok
    other = browser.new_context(base_url=base_url, locale="en-US")
    try:
        peer = other.new_page()
        register(peer, "e2e_ro_reviewer")
        assert page.request.post(f"/api/projects/{pid}/members", data={"username": "e2e_ro_reviewer", "role": "reviewer"}).ok
        peer.reload()
        peer.wait_for_function("window.__booted === true")
        for name in ("Shared source", "layout.typ"):
            row = peer.locator("#shared .doc").filter(has=peer.locator(".t", has_text=name)).first
            row.hover()
            row.locator("button[data-side-menu]").click()
            menu = peer.locator("#menu")
            expect(menu.locator("button").filter(has_text="Copy to")).to_have_count(1)
            expect(menu.locator("button").filter(has_text="Move to")).to_have_count(0)
            expect(menu.locator("button").filter(has_text="Rename")).to_have_count(0)
            peer.keyboard.press("Escape")
    finally:
        other.close()


def test_folder_copy_to_another_project_is_rolled_back_when_an_entry_conflicts(page):
    register(page, "e2e_folder_rollback")
    create_doc(page, "Source doc")
    pid = next(d["project_id"] for d in page.request.get("/api/docs").json()["own"] if d["title"] == "Source doc")
    target = page.request.post("/api/projects", data={"title": "Rollback target"}).json()["id"]
    assert page.request.post(f"/api/projects/{pid}/resources", data={"name": "util.typ", "content": "source"}).ok
    assert page.request.post(f"/api/projects/{target}/resources", data={"name": "util.typ", "content": "other"}).ok
    assert page.request.post(f"/api/projects/{pid}/docs", data={"title": "A ok", "folder": "src", "content": "fine"}).ok
    assert page.request.post(f"/api/projects/{pid}/docs", data={"title": "B needs util", "folder": "src", "content": '#include "util.typ"'}).ok
    page.reload()
    page.wait_for_function("window.__booted === true")

    row = page.locator("#own .fhd.folder").filter(has=page.locator("b", has_text="src")).first
    row.hover()
    row.locator("button[data-side-menu]").click()
    page.locator("#menu button").filter(has_text="Copy to").first.hover()
    page.locator("#submenu button").filter(has_text="To another project").click()
    page.locator("#modal button").filter(has_text="Rollback target").first.click()
    expect(page.locator("#mHead")).to_contain_text("Target folder")
    page.locator("#modal button.pk").first.click()  # project root
    expect(page.locator("#toast")).to_contain_text("was not transferred")
    payload = page.request.get(f"/api/projects/{target}").json()
    assert [d["title"] for d in payload["documents"]] == []  # the finished first copy was undone
    assert "src" not in payload["folders"]
    assert [r["name"] for r in payload["resources"]] == ["util.typ"]
