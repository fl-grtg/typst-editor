"""Named checkpoints and the change screen (green/red diff in a blurred overlay)."""
from playwright.sync_api import expect

from e2e.helpers import register


def _setup(page, name):
    register(page, name)
    page.request.post("/api/docs/create", data={"title": "Main", "content": "\n".join(f"line {i} of the document" for i in range(1, 21))})
    doc = page.request.get("/api/docs").json()["own"][0]
    pid = doc["project_id"]
    assert page.request.post(f"/api/projects/{pid}/resources", data={"name": "lib.typ", "content": "#let a = 1"}).ok
    page.reload()
    page.wait_for_function("window.__booted === true")
    page.locator("aside .doc.sub", has_text="Main").first.click()
    return doc["id"], pid


def test_name_checkpoint_rename_compare_and_delete(page):
    did, pid = _setup(page, "versions_user")
    assert page.request.post(f"/api/projects/{pid}/snapshots", data={}).ok
    page.click("#histBtn")
    page.click("#histPop .save")
    page.fill("#mInp", "Draft one")
    page.click("#mYes")
    expect(page.locator("#histPop .srow", has_text="Draft one")).to_have_count(1)
    row = page.locator("#histPop .srow", has_text="Draft one")
    row.get_by_role("button", name="Menu").click()
    page.get_by_role("menuitem", name="Rename snapshot").click()
    page.fill("#mInp", "Release")
    page.click("#mYes")
    expect(page.locator("#histPop .srow", has_text="Release")).to_have_count(1)
    if not page.locator("#histPop").is_visible():
        page.click("#histBtn")
    page.wait_for_timeout(300)
    # change something, then compare the checkpoint with the current project
    page.click("#cm .cm-content")
    page.keyboard.press("Control+Home")
    page.keyboard.press("End")
    page.keyboard.type(" EDITED")
    page.keyboard.press("Control+End")
    page.keyboard.type("\nline 21 appended")
    page.wait_for_timeout(1200)
    page.click("#histBtn")
    page.locator("#histPop .srow", has_text="Release").get_by_role("button", name="Show changes vs current").click()
    card = page.locator(".chgCard")
    expect(card).to_be_visible()
    expect(card.locator(".chgFile", has_text="Main.typ")).to_have_count(1)  # sidebar path, never main.typ
    expect(card.locator(".chgLine.add", has_text="line 21 appended")).to_have_count(1)
    expect(card.locator(".chgLine.add mark", has_text="EDITED")).to_have_count(1)  # word-level highlight
    expect(card.locator(".chgLine.add .sg").first).to_have_text("+")
    expect(card.locator(".chgSum")).to_contain_text("+2")
    fold = card.locator(".chgFold")
    expect(fold).to_have_count(1)
    fold.click()  # hidden context opens
    expect(card.locator(".chgFold")).to_have_count(0)
    expect(card.locator(".chgLine.ctx", has_text="line 10 of")).to_have_count(1)
    page.keyboard.press("Escape")
    expect(page.locator(".chgOverlay")).to_have_count(0)
    if not page.locator("#histPop").is_visible():
        page.click("#histBtn")
    # delete again
    page.locator("#histPop .srow", has_text="Release").get_by_role("button", name="Menu").click()
    page.get_by_role("menuitem", name="Delete snapshot").click()
    page.click("#mYes")
    expect(page.locator("#histPop .srow", has_text="Release")).to_have_count(0)
