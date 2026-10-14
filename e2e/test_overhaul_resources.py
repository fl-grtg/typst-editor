"""Own/global shelves and shared-document resource permissions in the real UI."""
from playwright.sync_api import expect

from e2e.helpers import register


def test_global_library_and_table_can_be_created_and_reused(page):
    register(page, "shelf_creator")
    for header, name, title in [("libH", "sources.bib", "New library"),
                                ("tblH", "numbers.csv", "New table")]:
        page.locator(f"#{header} button").first.click()
        expect(page.locator("#mHead")).to_have_text(title)
        page.fill("#mInp", name)
        page.click("#mYes")
        expect(page.locator("#title")).to_have_text(name)
        expect(page.locator("#cm .cm-content")).not_to_be_empty()
    response = page.request.post("/api/templates", data={"name": "layout.typ", "content":
                                 '#table(columns: 2, ..csv("numbers.csv").flatten())\n'
                                 '#bibliography("sources.bib")'})
    assert response.ok, response.text()
    for title in ["Global one", "Global two"]:
        assert page.request.post("/api/docs/create", data={"title": title,
                                 "content": '#include "layout.typ"\n@reference'}).ok
    page.reload()
    page.wait_for_function("window.__booted === true")
    expect(page.locator("#libs")).to_contain_text("sources.bib")
    expect(page.locator("#tbls")).to_contain_text("numbers.csv")
    for title in ["Global one", "Global two"]:
        page.locator("#own .doc .t").filter(has_text=title).click()
        expect(page.locator("#title")).to_have_text(title)
        expect(page.locator("#preview .pvPage[data-done]").first).to_be_visible(timeout=60_000)
        expect(page.locator("#eBadge")).not_to_be_visible()
        expect(page.locator("#tabs")).to_contain_text("numbers.csv")
        expect(page.locator("#tabs")).to_contain_text("sources.bib")


def test_shared_same_name_uses_owner_copy_and_cannot_edit_it(page, browser, base_url):
    register(page, "shared_shelf_owner")
    assert page.request.post("/api/templates", data={"name": "shared.typ", "content": "Owner-only marker"}).ok
    r = page.request.post("/api/docs/create", data={"title": "Shared resource test", "content": '#include "shared.typ"'})
    did = r.json()["id"]
    other = browser.new_context(base_url=base_url, locale="en-US")
    peer = other.new_page()
    try:
        register(peer, "shared_shelf_peer")
        assert peer.request.post("/api/templates", data={"name": "shared.typ", "content": "Peer private marker"}).ok
        assert page.request.post(f"/api/docs/{did}/share", data={"username": "shared_shelf_peer", "role": "editor"}).ok
        peer.reload()
        peer.wait_for_function("window.__booted === true")
        peer.locator("#shared .doc .t").filter(has_text="Shared resource test").click()
        expect(peer.locator("#title")).to_have_text("Shared resource test")
        expect(peer.locator("#preview .pvPage[data-done]").first).to_be_visible(timeout=60_000)
        peer.locator("#tabs button.tab").filter(has_text="shared.typ").click()
        expect(peer.locator("#cm .cm-content")).to_contain_text("Owner-only marker")
        expect(peer.locator("#cm .cm-content")).to_have_attribute("contenteditable", "false")
        peer.click("#cm .cm-content")
        peer.keyboard.press("ControlOrMeta+A")
        peer.keyboard.press("Tab")
        peer.keyboard.press("Shift+Tab")
        peer.keyboard.type("Must not replace")
        expect(peer.locator("#cm .cm-content")).to_contain_text("Owner-only marker")
        assert peer.request.get("/api/templates/shared.typ").json()["content"] == "Peer private marker"
        peer.locator("#tabs button.tab").filter(has_text="main.typ").click()
        expect(peer.locator("#cm .cm-content")).to_have_attribute("contenteditable", "true")
        assert page.request.delete(f"/api/docs/{did}/share/shared_shelf_peer").ok
        expect(peer.locator("#title")).not_to_have_text("Shared resource test")
        assert peer.request.get(f"/api/docs/{did}/resources").status in (403, 404)
    finally:
        other.close()


def test_undo_does_not_import_previous_document_text(page):
    register(page, "undo_buffers")
    for title, content in [("Undo first", "First original"), ("Undo second", "Second original")]:
        assert page.request.post("/api/docs/create", data={"title": title, "content": content}).ok
    page.reload()
    page.wait_for_function("window.__booted === true")
    page.locator("#own .doc .t").filter(has_text="Undo first").click()
    expect(page.locator("#cm .cm-content")).to_contain_text("First original")
    page.click("#cm .cm-content")
    page.keyboard.press("ControlOrMeta+A")
    page.keyboard.type("First changed")
    page.locator("#own .doc .t").filter(has_text="Undo second").click()
    expect(page.locator("#cm .cm-content")).to_contain_text("Second original")
    page.click("#cm .cm-content")
    page.keyboard.press("ControlOrMeta+Z")
    expect(page.locator("#cm .cm-content")).to_contain_text("Second original")
    expect(page.locator("#cm .cm-content")).not_to_contain_text("First")
