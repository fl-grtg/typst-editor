"""Project folders in the sidebar, the open-tabs bar and the document preview beside module tabs."""
from playwright.sync_api import expect

from e2e.helpers import register


def _project(page):
    doc = page.request.get("/api/docs").json()["own"][0]
    return doc["id"], doc["project_id"]


def _setup(page, name):
    register(page, name)
    page.request.post("/api/docs/create", data={"title": "Main", "content": '#import "lib/style.typ": accent\n#text(fill: accent)[Hello]'})
    did, pid = _project(page)
    assert page.request.post(f"/api/projects/{pid}/resources", data={"name": "lib/style.typ", "content": "#let accent = red"}).ok
    assert page.request.post(f"/api/projects/{pid}/resources", data={"name": "other.typ", "content": "x"}).ok
    assert page.request.post(f"/api/projects/{pid}/folders", data={"path": "empty/inner"}).ok
    page.reload()
    page.wait_for_function("window.__booted === true")
    return did, pid


def test_sidebar_tree_and_tabs_only_list_opened_files(page):
    did, pid = _setup(page, "tree_user")
    folder = page.locator("aside .fhd.folder")
    expect(folder.filter(has_text="lib")).to_have_count(1)
    expect(folder.filter(has_text="inner")).to_have_count(1)  # empty folder, 2nd level
    expect(page.locator("aside .doc.sub", has_text="style.typ")).to_have_count(1)
    page.locator("aside .doc.sub", has_text="Main").first.click()
    expect(page.locator("#title")).to_have_text("Main")
    expect(page.locator("#tabs button.tab")).to_have_count(1)  # nothing else was opened
    page.locator("aside .doc.sub", has_text="style.typ").click()
    expect(page.locator("#tabs button.tab")).to_have_count(2)
    expect(page.locator("#tabs button.tab", has_text="other.typ")).to_have_count(0)
    # the document preview stays visible next to the module
    expect(page.locator("#rightCol")).to_be_visible()
    expect(page.locator("#pvFor")).to_have_text("Preview: Main.typ")
    expect(page.locator("#preview .pvPage").first).to_be_visible()
    # closing hides the tab only
    page.locator("#tabs .tabw", has_text="style.typ").hover()
    page.locator("#tabs .tabw", has_text="style.typ").locator("button.tx").click()
    expect(page.locator("#tabs button.tab")).to_have_count(1)
    assert [r["name"] for r in page.request.get(f"/api/projects/{pid}/resources").json()["resources"]] == ["lib/style.typ", "other.typ"]
    # no add / delete in the tab bar anymore
    expect(page.locator("#tabs .tadd")).to_have_count(0)


def test_open_tabs_survive_reload_and_module_edit_updates_preview(page):
    did, pid = _setup(page, "tabs_reload")
    page.locator("aside .doc.sub", has_text="Main").first.click()
    page.locator("aside .doc.sub", has_text="style.typ").click()
    expect(page.locator("#tabs button.tab")).to_have_count(2)
    page.reload()
    page.wait_for_function("window.__booted === true")
    page.locator("aside .doc.sub", has_text="Main").first.click()
    expect(page.locator("#tabs button.tab")).to_have_count(2)
    page.locator("#tabs button.tab", has_text="style.typ").click()
    expect(page.locator("#pvFor")).to_be_visible()
    page.click("#cm .cm-content")
    page.keyboard.press("ControlOrMeta+A")
    page.keyboard.type("#let accent = blue")
    expect(page.locator("#preview .pvPage").first).to_be_visible()
    expect(page.locator("#eBadge")).to_be_hidden()


def test_create_folder_module_in_folder_and_rename_folder_through_the_ui(page):
    register(page, "folder_ui")
    page.request.post("/api/docs/create", data={"title": "Main", "content": "Hello"})
    did, pid = _project(page)
    page.reload()
    page.wait_for_function("window.__booted === true")
    head = page.locator("aside .project-group").filter(has_text="Main").first.locator(".fhd.project")
    head.hover()
    head.locator("button.mini").first.click()
    page.locator("#modal button.pk", has_text="New folder").click()
    page.fill("#mInp", "chapters")
    page.click("#mYes")
    folder = page.locator("aside .fhd.folder", has_text="chapters")
    expect(folder).to_have_count(1)
    # new module inside the folder
    folder.hover()
    folder.locator("button.mini").first.click()
    page.locator("#modal button.pk", has_text="New module").click()
    page.locator("#modal button.pk", has_text=".typ").first.click()
    page.fill("#mInp", "intro")
    page.click("#mYes")
    expect(page.locator("#tabs button.tab", has_text="intro.typ")).to_have_count(1)
    assert [r["name"] for r in page.request.get(f"/api/projects/{pid}/resources").json()["resources"]] == ["chapters/intro.typ"]
    expect(page.locator("#pvFor")).to_have_text("Preview: Main.typ")
    # rename the folder: the open tab follows
    folder.hover()
    folder.locator("button.mini").nth(1).click() if folder.locator("button.mini").count() > 1 else None
    if page.locator("#menu:not([hidden])").count():
        page.locator("#menu button, #menu [role=menuitem]", has_text="Rename folder").click()
    page.locator("aside input.renameInput").fill("parts")
    page.keyboard.press("Enter")
    page.click("#mYes")
    expect(page.locator("aside .fhd.folder", has_text="parts")).to_have_count(1)
    assert [r["name"] for r in page.request.get(f"/api/projects/{pid}/resources").json()["resources"]] == ["parts/intro.typ"]
    expect(page.locator("#tabs button.tab", has_text="intro.typ")).to_have_count(1)
    expect(page.locator("#tabs button.tab[aria-selected=true]", has_text="intro.typ")).to_have_count(1)


def test_drag_entries_into_a_folder_and_back_to_the_project_root(page):
    did, pid = _setup(page, "folder_dnd")
    names = lambda: [r["name"] for r in page.request.get(f"/api/projects/{pid}/resources").json()["resources"]]  # noqa: E731
    row = page.locator("aside .doc.sub", has_text="other.typ")
    page.locator("aside .fhd.folder", has_text="lib").scroll_into_view_if_needed()
    row.drag_to(page.locator("aside .fhd.folder", has_text="lib"))
    # drag & drop is a plain move: no reference dialog to confirm
    expect(page.locator("aside .doc.sub[title='lib/other.typ']")).to_have_count(1)
    assert names() == ["lib/other.typ", "lib/style.typ"]
    page.locator("aside .doc.sub[title='lib/other.typ']").drag_to(page.locator("aside .project-group").filter(has_text="Main").first.locator(".fhd.project"))
    expect(page.locator("aside .doc.sub[title='other.typ']")).to_have_count(1)
    assert names() == ["lib/style.typ", "other.typ"]


def test_file_rows_and_empty_hints_are_drop_areas_for_their_folder(page):
    did, pid = _setup(page, "folder_drop_areas")
    for name in ("empty", "inner"):
        label = page.locator("aside .fhd.folder", has_text=name).first.locator("b")
        if label.get_attribute("aria-expanded") == "false":
            label.click()
    # the empty hint belongs to the innermost folder: dropping on it moves the file there
    page.locator("aside .doc.sub", has_text="other.typ").drag_to(page.locator("aside .folderEmpty").first)
    expect(page.locator("aside .doc.sub[title='empty/inner/other.typ']")).to_have_count(1)
    assert [r["name"] for r in page.request.get(f"/api/projects/{pid}/resources").json()["resources"]] == ["empty/inner/other.typ", "lib/style.typ"]
    # dropping on a file row targets the folder that file lives in, not the file
    page.locator("aside .doc.sub[title='lib/style.typ']").drag_to(page.locator("aside .doc.sub[title='empty/inner/other.typ']"))
    expect(page.locator("aside .doc.sub[title='empty/inner/style.typ']")).to_have_count(1)
    assert [r["name"] for r in page.request.get(f"/api/projects/{pid}/resources").json()["resources"]] == ["empty/inner/other.typ", "empty/inner/style.typ"]


def test_last_tab_closes_to_the_plain_welcome_screen(page):
    register(page, "welcome_close")
    page.request.post("/api/docs/create", data={"title": "Only", "content": "x"})
    page.reload()
    page.wait_for_function("window.__booted === true")
    if page.locator("#tabs button.tab").count() == 0:
        page.locator("aside .doc.sub", has_text="Only").first.click()
    expect(page.locator("#tabs button.tab")).to_have_count(1)
    page.locator("#tabs button.tab").last.click(button="right")
    page.locator("#menu button").filter(has_text="Close tab").click()
    expect(page.locator("#title")).to_have_text("Welcome")
    expect(page.locator("#emptyCard")).to_be_visible()
    expect(page.locator("#emptyCard .step")).to_have_count(3)
    expect(page.locator("#emptyCard #galQuick")).to_have_count(0)  # no decorative, dead template grid
