"""Wave 2E: REST autosave only when the WebSocket is down; calm offline/reconnect status.

test_9 (idle): typing while the socket is live must not send any
    POST /api/docs/<id>/save (Yjs already syncs); idling afterwards sends
    nothing either — the network log is the proof.
test_10 (offline cycle): browser-offline flips the status away from Live
    without toast spam; typing offline is kept, and reconnect flips back to
    Live with the text intact.
"""
from helpers import create_doc, register, type_source
from playwright.sync_api import expect


def _save_posts(page):
    seen = []
    page.on("request", lambda r: seen.append(r.url)
            if r.method == "POST" and "/api/docs/" in r.url and r.url.endswith("/save") else None)
    return seen


def test_9_idle_sends_no_save_requests(page):
    register(page, "e2e_2e_idle")
    create_doc(page, "2E idle doc")
    saves = _save_posts(page)
    type_source(page, "= Idle\n\nNo periodic saves")
    expect(page.locator("#wsTxt")).to_have_text("Live", timeout=20_000)
    page.wait_for_timeout(7_000)  # >2x SAVE_MS: any periodic saver would have fired
    assert saves == [], f"idle sent {len(saves)} save requests: {saves[:3]}"
    expect(page.locator("#cm .cm-content")).to_contain_text("No periodic saves")


def test_10_offline_and_back_keeps_text(page, ctx):
    register(page, "e2e_2e_conn")
    create_doc(page, "2E conn doc")
    type_source(page, "baseline")
    expect(page.locator("#wsTxt")).to_have_text("Live", timeout=20_000)
    ctx.set_offline(True)
    try:
        expect(page.locator("#wsTxt")).not_to_have_text("Live", timeout=10_000)
        page.click("#cm .cm-content")
        page.keyboard.press("ControlOrMeta+End")
        page.keyboard.type(" plus offline")
        expect(page.locator("#save")).to_contain_text("Offline", timeout=10_000)
    finally:
        ctx.set_offline(False)
    expect(page.locator("#wsTxt")).to_have_text("Live", timeout=20_000)
    expect(page.locator("#cm .cm-content")).to_contain_text("plus offline")
