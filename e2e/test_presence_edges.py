"""Off-screen collaborators get a compact chip at the editor edge."""
from helpers import register
from playwright.sync_api import expect

TITLE = "Edge presence"

# Awareness-only collaborators: real WebsocketProvider clients, so the app sees
# ordinary remote state and the test never depends on window focus or timers.
PHANTOM_JS = """
async ({ docId, peers }) => {
  const Y = await import('/vendor/yjs-13.6.27-232b4982bc3f.js')
  const { WebsocketProvider } = await import('/vendor/y-websocket-1.5.0-8a98fc0aad78.js')
  const proto = location.protocol === 'https' ? 'wss' : 'ws'
  window.__phantoms = window.__phantoms || []
  for (const p of peers) {
    const doc = new Y.Doc()
    const provider = new WebsocketProvider(`${proto}://${location.host}/ws`, docId, doc)
    if (!provider.wsconnected) {
      await new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error('phantom client did not connect')), 15000)
        provider.on('status', e => { if (e.status === 'connected') { clearTimeout(timer); resolve() } })
      })
    }
    if (!provider.synced) {
      await new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error('phantom client did not sync')), 15000)
        provider.on('synced', s => { if (s === true) { clearTimeout(timer); resolve() } })
      })
    }
    provider.awareness.setLocalState({ u: { name: p.name, color: p.color }, sel: { a: p.pos, h: p.pos }, active: true })
    window.__phantoms.push({ doc, provider })
  }
}
"""


def _long_source():
    return "\n\n".join(f"= Section {i}\n\nLine {i}: shared writing. " + "Text " * 8 for i in range(1, 121))


def _add_phantoms(page, doc_id, peers):
    page.evaluate(PHANTOM_JS, {"docId": doc_id, "peers": peers})


def _set_first_peer(page, pos):
    page.evaluate(
        """pos => {
          const p = window.__phantoms[0]
          const n = pos === 'end' ? p.doc.getText('typst').length : pos === 'middle' ? Math.floor(p.doc.getText('typst').length / 2) : 0
          p.provider.awareness.setLocalStateField('sel', { a: n, h: n })
        }""",
        pos,
    )


def test_offscreen_peer_chips(page):
    register(page, "edge_anna")
    created = page.request.post("/api/docs/create", data={"title": TITLE, "content": _long_source()})
    assert created.ok, created.text()
    doc_id = created.json()["id"]
    page.reload()  # the sidebar event can fire before the page subscribes on slow runners
    page.wait_for_function("window.__booted === true")
    page.locator("#own .doc", has_text=TITLE).first.click()
    expect(page.locator("#title")).to_have_text(TITLE)
    expect(page.locator("#wsTxt")).to_have_text("Live")

    _add_phantoms(page, doc_id, [{"name": "Edge One", "color": "#0f766e", "pos": 0}])

    # Peer above the visible excerpt: top chip, hidden once both are at the top.
    page.locator("#cm .cm-content").click()
    page.keyboard.press("ControlOrMeta+End")
    expect(page.locator("#peerTop")).to_be_visible()
    expect(page.locator("#peerTop")).to_have_attribute("aria-label", "Above: Edge One")
    page.keyboard.press("ControlOrMeta+Home")
    expect(page.locator("#peerTop")).to_be_hidden()

    # Peer below the visible excerpt: bottom chip.
    _set_first_peer(page, "end")
    expect(page.locator("#peerBottom")).to_be_visible()
    expect(page.locator("#peerBottom")).to_have_attribute("aria-label", "Below: Edge One")

    # A position update re-renders the row but keeps keyboard focus on the chip.
    chip = page.locator("#peerBottom button").first
    chip.focus()
    peer_id = chip.get_attribute("data-peer")
    title = chip.get_attribute("title")
    assert peer_id and title
    _set_first_peer(page, "middle")
    expect(chip).not_to_have_attribute("title", title)
    assert page.evaluate("document.activeElement && document.activeElement.dataset.peer") == peer_id

    # Clicking the chip centres the peer.
    before = page.locator("#cm .cm-scroller").evaluate("el => el.scrollTop")
    chip.click()
    expect(page.locator("#peerBottom")).to_be_hidden()
    after = page.locator("#cm .cm-scroller").evaluate("el => el.scrollTop")
    assert after > before

    # Many off-screen peers wrap inside the editor instead of overflowing it,
    # and every chip keeps a 44px touch target.
    _set_first_peer(page, "top")
    _add_phantoms(page, doc_id, [
        {"name": f"Edge {i}", "color": "#0369a1", "pos": 0} for i in range(2, 10)
    ])
    page.set_viewport_size({"width": 340, "height": 760})
    page.locator("#cm .cm-content").click()
    page.keyboard.press("ControlOrMeta+End")
    expect(page.locator("#peerTop button")).to_have_count(9)
    wrap = page.locator("#cmWrap").bounding_box()
    box = page.locator("#peerTop").bounding_box()
    assert wrap and box
    assert box["x"] >= wrap["x"] - 0.5
    assert box["x"] + box["width"] <= wrap["x"] + wrap["width"] + 0.5
    assert box["height"] > 44, "chip row should wrap at this width"
    sizes = page.locator("#peerTop button").evaluate_all(
        "els => els.map(el => { const r = el.getBoundingClientRect(); return [r.width, r.height] })"
    )
    assert all(w >= 44 and h >= 44 for w, h in sizes)
