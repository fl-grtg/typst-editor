"""Wave 2E: REST autosave only when the WebSocket is down; calm offline/reconnect status.

test_9 (idle): typing while the socket is live must not send any
    POST /api/docs/<id>/save (Yjs already syncs); idling afterwards sends
    nothing either — the network log is the proof.
test_10 (offline cycle): browser-offline flips the status away from Live
    without toast spam; typing offline is kept, and reconnect flips back to
    Live with the text intact (exactly once — no duplication).
test_11 (offline queue): typing (and even explicit Ctrl+S) while offline must
    not send any POST /api/docs/<id>/save for main.typ — Yjs carries the
    edits on reconnect, a REST copy on top would fork the text and duplicate
    it. No toast while offline, only the calm status line.
test_12 (template offline): template autosave failures stay quiet offline
    (status line only, no toast); the typed text survives.
"""
from helpers import create_doc, register, type_source
from playwright.sync_api import expect


def _save_posts(page):
    seen = []
    page.on("request", lambda r: seen.append(r.url)
            if r.method == "POST" and "/api/docs/" in r.url and r.url.endswith("/save") else None)
    return seen


def _type_offline(page, text):
    # Slow-runner-proof offline typing: fast keyboard.type can drop a single
    # keypress under CI load (seen: "plusoffline" missing one space), and the
    # old save-only assert could not tell dropped typing from a reconnect
    # wipe. Small per-key delay + full-text assert while still offline.
    page.click("#cm .cm-content")
    page.keyboard.press("ControlOrMeta+End")
    page.keyboard.type(text, delay=30)
    expect(page.locator("#cm .cm-content")).to_contain_text(text.strip(), timeout=10_000)


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
        _type_offline(page, " plus offline")
        expect(page.locator("#save")).to_contain_text("Offline", timeout=10_000)
    finally:
        ctx.set_offline(False)
    expect(page.locator("#wsTxt")).to_have_text("Live", timeout=20_000)
    expect(page.locator("#cm .cm-content")).to_contain_text("plus offline")
    txt = page.locator("#cm .cm-content").inner_text()
    assert txt.count("plus offline") == 1, f"offline edit duplicated on reconnect: {txt[-120:]!r}"
    assert txt.count("baseline") == 1, f"baseline duplicated on reconnect: {txt[-120:]!r}"


def test_11_offline_sends_no_save_and_stays_quiet(page, ctx):
    register(page, "e2e_2e_nosave")
    create_doc(page, "2E offline doc")
    type_source(page, "baseline")
    expect(page.locator("#wsTxt")).to_have_text("Live", timeout=20_000)
    expect(page.locator("#toast")).to_be_hidden(timeout=10_000)  # drain online phase: clean slate
    saves = _save_posts(page)  # isolate the offline window below
    ctx.set_offline(True)
    try:
        expect(page.locator("#wsTxt")).not_to_have_text("Live", timeout=10_000)
        _type_offline(page, " plus offline")
        page.keyboard.press("ControlOrMeta+s")  # explicit save stays local too while offline
        seen = []
        for _ in range(8):  # >SAVE_MS: any offline saver would have fired/toasted mid-window
            page.wait_for_timeout(500)
            if page.locator("#toast").is_visible():
                seen.append(page.locator("#toast").inner_text())
        assert saves == [], f"offline sent {len(saves)} save requests: {saves[:3]}"
        expect(page.locator("#save")).to_contain_text("Offline", timeout=10_000)
        assert seen == [], f"offline showed {len(seen)} toast(s): {seen[0][:100]!r}"
    finally:
        ctx.set_offline(False)
    expect(page.locator("#wsTxt")).to_have_text("Live", timeout=20_000)
    page.wait_for_timeout(2_000)  # reconnect sync lands
    txt = page.locator("#cm .cm-content").inner_text()
    assert txt.count("plus offline") == 1, f"offline edit duplicated on reconnect: {txt[-120:]!r}"


def test_12_template_offline_stays_quiet(page, ctx):
    register(page, "e2e_2e_tploff")
    create_doc(page, "2E tpl doc")
    type_source(page, "template body")
    expect(page.locator("#wsTxt")).to_have_text("Live", timeout=20_000)
    page.click("#tplBtn")
    page.locator("#tplPop button", has_text="New template").click()
    page.fill("#mInp", "off.typ")
    page.click("#mYes")
    expect(page.locator("#title")).to_have_text("off.typ", timeout=15_000)
    expect(page.locator("#toast")).to_be_hidden(timeout=10_000)  # drain online phase: clean slate
    seen = []
    ctx.set_offline(True)
    try:
        _type_offline(page, " plus offline tpl")
        for _ in range(8):  # >SAVE_MS: autosave failure would toast mid-window (end-state asserts miss transient toasts)
            page.wait_for_timeout(500)
            if page.locator("#toast").is_visible():
                seen.append(page.locator("#toast").inner_text())
        expect(page.locator("#save")).to_contain_text("Offline", timeout=10_000)
        assert seen == [], f"offline showed {len(seen)} toast(s): {seen[0][:100]!r}"
    finally:
        ctx.set_offline(False)
    txt = page.locator("#cm .cm-content").inner_text()
    assert txt.count("plus offline tpl") == 1, f"template offline edit lost/duplicated: {txt[-120:]!r}"
