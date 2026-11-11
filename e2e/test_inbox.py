"""Inbox bell: mention -> jump to the comment; level "all" -> change screen; watch level via project menu."""
import sqlite3

from playwright.sync_api import expect

from e2e.helpers import register


def test_mention_and_change_notice_in_the_inbox(browser, base_url, tmp_path_factory):
    ctxs = [browser.new_context(base_url=base_url, locale="en-US") for _ in range(2)]
    try:
        alice, bob = (c.new_page() for c in ctxs)
        register(alice, "inbox_alice")
        register(bob, "inbox_bob")
        alice.request.post("/api/docs/create", data={"title": "Shared", "content": "first\nsecond\nthird"})
        doc = alice.request.get("/api/docs").json()["own"][0]
        did, pid = doc["id"], doc["project_id"]
        assert alice.request.post(f"/api/projects/{pid}/members", data={"username": "inbox_bob", "role": "editor"}).ok
        # bob follows everything in this project
        assert bob.request.put(f"/api/projects/{pid}/watch", data={"level": "all"}).ok
        bob.reload()
        bob.wait_for_function("window.__booted === true")
        expect(bob.locator("#inboxBtn")).to_be_visible()
        expect(bob.locator("#inboxN")).to_be_hidden()
        # alice mentions bob in a comment on line 2
        assert alice.request.post(f"/api/docs/{did}/comments", data={"anchor": 2, "text": "please check @inbox_bob"}).ok
        expect(bob.locator("#inboxN")).to_have_text("1")  # live via SSE
        bob.click("#inboxBtn")
        item = bob.locator("#inboxPop .inItem.unread")
        expect(item).to_have_count(1)
        expect(item).to_contain_text("inbox_alice mentioned you")
        bob.wait_for_timeout(500)
        item.click()
        expect(bob.locator("#title")).to_have_text("Shared")
        expect(bob.locator("#pop")).to_be_visible()  # the comment card on that line is open
        expect(bob.locator("#pop")).to_contain_text("please check @inbox_bob")
        expect(bob.locator("#inboxN")).to_be_hidden()
        # level "all": the change notice (written by the server after a checkpoint) opens the change screen
        assert alice.request.post(f"/api/projects/{pid}/resources", data={"name": "lib.typ", "content": "#let a = 1\nsecond line"}).ok
        db = next(tmp_path_factory.getbasetemp().glob("e2e-data*/app.db"))
        con = sqlite3.connect(str(db))
        con.execute("INSERT INTO notifications (id,recipient,type,doc_id,text,is_read,created_at,project_id,ref,actor) VALUES "
                    "('n_changes_e2e','inbox_bob','changes','','',0,'2999-01-01T00:00:00+00:00',?, '', 'inbox_alice')", (pid,))
        con.commit()
        con.close()
        bob.reload()
        bob.wait_for_function("window.__booted === true")
        expect(bob.locator("#inboxN")).to_have_text("1")
        bob.click("#inboxBtn")
        bob.locator("#inboxPop .inItem.unread").click()
        expect(bob.locator("#title")).to_have_text("Shared")  # the project is opened behind the dialog
        card = bob.locator(".chgCard")
        expect(card).to_be_visible()
        expect(card.locator(".chgFile", has_text="lib.typ")).to_have_count(1)  # path without project name
        expect(card.locator(".chgLine.add", has_text="second line")).to_have_count(1)
        bob.keyboard.press("Escape")  # closing marks everything as seen
        expect(bob.locator("#inboxN")).to_be_hidden()
        assert bob.request.get(f"/api/projects/{pid}/watch").json()["base"] != ""
    finally:
        for c in ctxs:
            c.close()


def test_watch_level_from_the_bell_on_the_project_row(page):
    register(page, "watch_menu_user")
    page.request.post("/api/docs/create", data={"title": "Doc", "content": "x"})
    pid = page.request.get("/api/docs").json()["own"][0]["project_id"]
    page.reload()
    page.wait_for_function("window.__booted === true")
    head = page.locator("aside .fhd.project", has_text="Doc")
    head.hover()
    head.get_by_role("button", name="Notifications: Mentions and suggestions").click()
    box = page.locator("#watchBox")
    expect(box.locator(".wItem[aria-checked=true]")).to_contain_text("Mentions and suggestions")
    page.wait_for_timeout(800)
    box.locator(".wItem", has_text="Everything").click()
    expect(box).to_have_count(0)
    assert page.request.get(f"/api/projects/{pid}/watch").json()["level"] == "all"
    page.reload()
    page.wait_for_function("window.__booted === true")
    head = page.locator("aside .fhd.project", has_text="Doc")
    bell = head.get_by_role("button", name="Notifications: Everything")
    expect(bell).to_be_hidden()  # hover-only, even with a non-default level
    head.hover()
    expect(bell).to_be_visible()
