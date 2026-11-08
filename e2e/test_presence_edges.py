"""Off-screen collaborators get a compact chip at the editor edge."""
import re

from helpers import login, register
from playwright.sync_api import expect

TITLE = "Edge presence"


def _long_source():
    return "\n\n".join(f"= Section {i}\n\nLine {i}: shared writing. " + "Text " * 8 for i in range(1, 121))


def test_offscreen_peer_chips(page, browser, base_url):
    register(page, "edge_anna")
    created = page.request.post("/api/docs/create", data={"title": TITLE, "content": _long_source()})
    assert created.ok, created.text()
    page.locator("#own .doc", has_text=TITLE).first.click()
    expect(page.locator("#title")).to_have_text(TITLE)
    expect(page.locator("#wsTxt")).to_have_text("Live")

    peer_ctx = browser.new_context(base_url=base_url, locale="en-US")
    peer_ctx.add_init_script("document.hasFocus = () => true")
    try:
        peer = peer_ctx.new_page()
        login(peer, "edge_anna")
        peer.locator("#own .doc", has_text=TITLE).first.click()
        expect(peer.locator("#wsTxt")).to_have_text("Live")
        peer.locator("#cm .cm-content").click()
        peer.keyboard.press("ControlOrMeta+Home")
        peer.evaluate("window.__edgeKeep = setInterval(() => document.querySelector('#cm .cm-content')?.focus(), 250)")

        # Peer above the visible excerpt: top chip, hidden once both are at the top.
        page.locator("#cm .cm-content").click()
        page.keyboard.press("ControlOrMeta+End")
        expect(page.locator("#peerTop")).to_be_visible()
        expect(page.locator("#peerTop")).to_have_attribute("aria-label", re.compile("Above: edge_anna"))
        page.keyboard.press("ControlOrMeta+Home")
        expect(page.locator("#peerTop")).to_be_hidden()

        # Peer below the visible excerpt: bottom chip, click jumps to the peer.
        peer.bring_to_front()
        peer.keyboard.press("ControlOrMeta+End")
        page.bring_to_front()
        expect(page.locator("#peerBottom")).to_be_visible()
        expect(page.locator("#peerBottom")).to_have_attribute("aria-label", re.compile("Below: edge_anna"))
        before = page.locator("#cm .cm-scroller").evaluate("el => el.scrollTop")
        page.locator("#peerBottom button").first.click()
        expect(page.locator("#peerBottom")).to_be_hidden()
        after = page.locator("#cm .cm-scroller").evaluate("el => el.scrollTop")
        assert after > before

        peer.evaluate("clearInterval(window.__edgeKeep)")
    finally:
        peer_ctx.close()
