"""Wave 1B frontend mini-fixes (G5 + G6-B1 safety net).

test_7 (G5): the textarea->Y.Text heal interval in web/js/92-downloads.js must
    call pushLocal() (drift fallback via setYText), never pushLocal(changes,
    oldLen) with undeclared identifiers -> ReferenceError. Runs the real
    sources (40-editor-sync.js + the extracted interval block) with a mocked
    Y-Text and drifted editor state, no server doc needed.
test_8 (G6-B1): the Font/Zoom steppers in the settings dialog must not close
    the dialog (outside-click closer fires after renderSettings() detaches
    e.target, so the buttons need e.stopPropagation() like the key-create
    button).
"""

from pathlib import Path

from helpers import register
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
HEAL_WANT = "hello world (typed by extension, no input event)"

_HEAL_DRIVER = (
    """({s40, heal}) => {
  var ystore = 'hello';
  var shadow = 'hello';
  var cmText = '"""
    + HEAL_WANT
    + """';
  var ytext = {
    get length() { return ystore.length; },
    toString: function() { return ystore; },
    delete: function(a, n) { ystore = ystore.slice(0, a) + ystore.slice(a + n); },
    insert: function(a, s) { ystore = ystore.slice(0, a) + s + ystore.slice(a); }
  };
  var ydoc = { transact: function(fn) { return fn(); } };
  function getT() { return cmText; }
  function queueRender() {}
  function queueSave() {}
  var docId = 'doc1', docRole = 'editor', activeFile = '';
  var SAVE_MS = 2500;
  var healCb = null;
  var setInterval = function(cb) { healCb = cb; return 0; };
  eval(s40 + '\\n' + heal);
  if (typeof healCb !== 'function') return { ok: false, error: 'heal interval not registered' };
  try {
    healCb();
  } catch (e) {
    return { ok: false, error: String((e && e.message) || e), name: e && e.name };
  }
  return { ok: true, y: ytext.toString(), shadow: shadow };
}"""
)


def _heal_block() -> tuple[str, str]:
    s40 = (ROOT / "web/js/40-editor-sync.js").read_text(encoding="utf-8")
    src92 = (ROOT / "web/js/92-downloads.js").read_text(encoding="utf-8")
    start = src92.index("setInterval(")
    end = src92.index("}, SAVE_MS)") + len("}, SAVE_MS)")
    return s40, src92[start:end]


def test_7_heal_interval_falls_back_without_reference_error(page):
    s40, heal = _heal_block()
    assert "pushLocal(" in heal  # guard: extraction found the heal branch
    res = page.evaluate(_HEAL_DRIVER, {"s40": s40, "heal": heal})
    assert res["ok"], f"heal branch threw: {res.get('name')}: {res.get('error')}"
    assert res["y"] == HEAL_WANT, "drift fallback must push editor text into Y.Text"
    assert res["shadow"] == HEAL_WANT, "fallback must re-sync shadow"


def test_8_settings_steppers_keep_dialog_open(page):
    register(page, "e2e_gina")
    expect(page.locator("#cm .cm-content")).to_be_visible()  # tutorial open: openDoc's hidePops() calls are done
    page.click("#who")
    pop = page.locator("#setPop")
    if not pop.is_visible():  # async openDoc hidePops() won the race: toggle back open (hidden -> click opens)
        page.click("#who")
    expect(pop).to_be_visible()
    steps = pop.locator("button.step")
    expect(steps).to_have_count(4)  # fm, fp, zm, zp
    font = pop.locator("span.val", has_text="px").first
    zoom = pop.locator("span.val", has_text="%").first
    font0 = int(font.inner_text().replace("px", ""))
    zoom0 = int(zoom.inner_text().replace("%", "").strip())
    steps.nth(1).click()  # A+: dialog must stay open, font grows
    expect(pop).to_be_visible()
    assert int(font.inner_text().replace("px", "")) == font0 + 1
    steps.nth(0).click()  # A-: back to start, still open
    expect(pop).to_be_visible()
    assert int(font.inner_text().replace("px", "")) == font0
    steps.nth(3).click()  # zoom+: still open, zoom grows
    expect(pop).to_be_visible()
    assert int(zoom.inner_text().replace("%", "").strip()) == zoom0 + 10
    steps.nth(2).click()  # zoom-: back to start, still open
    expect(pop).to_be_visible()
    assert int(zoom.inner_text().replace("%", "").strip()) == zoom0
