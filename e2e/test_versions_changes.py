"""Named checkpoints and the change screen (green/red diff in a blurred overlay)."""
from playwright.sync_api import expect

from e2e.helpers import register


def _setup(page, name):
    register(page, name)
    page.request.post("/api/docs/create", data={"title": "Main", "content": "line one\nline two\nline three"})
    doc = page.request.get("/api/docs").json()["own"][0]
    pid = doc["project_id"]
    assert page.request.post(f"/api/projects/{pid}/resources", data={"name": "lib.typ", "content": "#let a = 1"}).ok
    page.reload()
    page.wait_for_function("window.__booted === true")
    page.locator("aside .doc.sub", has_text="Main").first.click()
    return doc["id"], pid


def test_name_checkpoint_rename_compare_and_delete(page):
    did, pid = _setup(page, "versions_user")
    page.click("#histBtn")
    page.click("#histPop .save")
    page.fill("#mInp", "Draft one")
    page.click("#mYes")
    expect(page.locator("#histPop .srow", has_text="Draft one")).to_have_count(1)
    row = page.locator("#histPop .srow", has_text="Draft one")
    row.get_by_role("button", name="Rename snapshot").click()
    page.fill("#mInp", "Release")
    page.click("#mYes")
    expect(page.locator("#histPop .srow", has_text="Release")).to_have_count(1)
    # change something, then compare the checkpoint with the current project
    page.click("#cm .cm-content")
    page.keyboard.press("Control+End")
    page.keyboard.type("\nline four")
    page.wait_for_timeout(1200)
    page.click("#histBtn")
    page.locator("#histPop .srow", has_text="Release").get_by_role("button", name="Show changes vs current").click()
    card = page.locator(".chgCard")
    expect(card).to_be_visible()
    expect(card.locator(".chgLine.add", has_text="line four")).to_have_count(1)
    expect(card.locator(".chgLine.add .sg").first).to_have_text("+")
    expect(card.locator(".chgSum")).to_contain_text("+1")
    page.screenshot(path="/tmp/claude-1000/changes.png")
    page.keyboard.press("Escape")
    expect(page.locator(".chgOverlay")).to_have_count(0)
    if not page.locator("#histPop").is_visible():
        page.click("#histBtn")
    # delete again
    page.locator("#histPop .srow", has_text="Release").get_by_role("button", name="Delete snapshot").click()
    page.click("#mYes")
    expect(page.locator("#histPop .srow", has_text="Release")).to_have_count(0)
