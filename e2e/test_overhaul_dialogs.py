"""Late UI responses stay attached to the document that requested them."""
from playwright.sync_api import expect

from e2e.helpers import register


def _docs(page, username):
    register(page, username)
    ids = []
    for title, content in [("Audit first", "= First\nOriginal first text"),
                           ("Audit second", "= Second\nUntouched second text")]:
        response = page.request.post("/api/docs/create", data={"title": title, "content": content})
        assert response.ok, response.text()
        ids.append(response.json()["id"])
    page.reload()
    page.wait_for_function("window.__booted === true")
    expect(page.locator("#own .doc").filter(has_text="Audit first")).to_be_visible()
    return ids


def _open(page, title):
    page.locator("#own .doc .t").filter(has_text=title).click()
    expect(page.locator("#title")).to_have_text(title)
    expect(page.locator("#cm .cm-content")).to_contain_text("Original" if title.endswith("first") else "Untouched")


def test_late_comments_do_not_leak_to_next_document(page):
    first, _ = _docs(page, "audit_comments")
    pending = []
    page.route(f"**/api/docs/{first}/comments", lambda route: pending.append(route))
    _open(page, "Audit first")
    page.wait_for_timeout(150)
    assert pending
    _open(page, "Audit second")
    for route in pending:
        route.fulfill(json={"comments": [{"id": "old", "anchor": 1, "text": "Old comment",
                                         "username": "audit_comments", "author": "audit_comments",
                                         "created_at": "2026-10-14T10:00:00Z", "resolved": False,
                                         "quote": "First", "replies": []}]})
    page.wait_for_timeout(250)
    expect(page.locator("#cBadge")).not_to_be_visible()
    expect(page.locator("#title")).to_have_text("Audit second")


def test_formatter_does_not_replace_a_document_opened_during_load(page):
    _docs(page, "audit_formatter")
    _open(page, "Audit first")
    pending = []
    page.route("**/vendor/typstyle-wasm-glue-*.js", lambda route: pending.append(route))
    page.click("#fmtDoc")
    page.wait_for_timeout(150)
    assert pending, "formatter import must remain pending for the race"
    _open(page, "Audit second")
    for route in pending:
        route.continue_()
    page.wait_for_timeout(600)
    expect(page.locator("#cm .cm-content")).to_contain_text("Untouched second text")
    expect(page.locator("#cm .cm-content")).not_to_contain_text("Original first text")


def test_keyboard_on_nested_document_action_runs_that_action(page):
    _docs(page, "audit_keyboard")
    _open(page, "Audit first")
    before = len(page.request.get("/api/docs").json()["own"])
    row = page.locator("#own .doc").filter(has_text="Audit first")
    row.get_by_role("button", name="Rename document", exact=True).press("Enter")
    expect(page.locator('#modal')).to_be_visible()
    page.fill('#mInp', 'Audit renamed')
    page.click('#mYes')
    expect(page.locator("#title")).to_have_text("Audit renamed")
    page.wait_for_timeout(250)
    after = len(page.request.get("/api/docs").json()["own"])
    assert after == before


def test_history_diff_compares_main_when_attachment_tab_is_open(page):
    first, _ = _docs(page, "audit_history")
    assert page.request.post(f"/api/docs/{first}/files/other.typ/text",
                             data={"content": "Completely different attachment"}).ok
    project = page.request.get(f'/api/docs/{first}').json()['project_id']
    assert page.request.post(f'/api/projects/{project}/snapshots', data={}).ok
    _open(page, "Audit first")
    expect(page.locator("#tabs button.tab").filter(has_text="other.typ")).to_be_visible()
    page.locator("#tabs button.tab").filter(has_text="other.typ").click()
    expect(page.locator("#cm .cm-content")).to_contain_text("Completely different attachment")
    expect(page.locator("#histBtn")).to_be_visible()
    page.click("#histBtn")
    page.locator("#histPop .srow button").filter(has_text="Compare").first.click()
    expect(page.locator("#histPop pre.diff")).to_contain_text("Identical")
