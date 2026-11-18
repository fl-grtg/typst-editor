"""Wave 1B frontend mini-fixes (G5 + G6-B1 safety net).

test_7 (G5): the textarea->Y.Text heal interval in web/js/92-downloads.js must
    call pushLocal() (drift fallback via setYText), never pushLocal(changes,
    oldLen) with undeclared identifiers -> ReferenceError. Runs the real
    sources (40-editor-sync.js + the extracted interval block) with a mocked
    Y-Text and drifted editor state, no server doc needed.
test_8 (G6-B1): the font and preview zoom sliders in the settings dialog
    must not close the dialog, and their reset buttons must return the default
    value (no re-render while dragging, so the live row stays attached).
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


def test_login_does_not_reload_when_module_fails(page):
    page.route("**/vendor-cm.js*", lambda route: route.abort())
    page.goto("/")
    page.fill("#u", "test")
    page.fill("#p", "12345678")
    page.evaluate("window.__loginGuardMarker = 1")
    page.click("#go")
    expect(page.locator("#err")).to_contain_text("App still loading")
    assert page.evaluate("window.__loginGuardMarker") == 1


def test_8_settings_sliders_keep_dialog_open(page):
    register(page, "e2e_gina")
    expect(page.locator("#cm .cm-content")).to_be_visible()  # tutorial open: openDoc's hidePops() calls are done
    page.click("#who")
    pop = page.locator("#setPop")
    if not pop.is_visible():  # async openDoc hidePops() won the race: toggle back open (hidden -> click opens)
        page.click("#who")
    expect(pop).to_be_visible()
    pop.locator('.setNavItem[data-category="editor"]').click()  # sliders live in the Editor view now
    ranges = pop.locator("input.settingRangeInput")
    expect(ranges).to_have_count(2)
    font, zoom = ranges.nth(0), ranges.nth(1)
    expect(font).to_have_attribute("min", "10")
    expect(font).to_have_attribute("max", "24")
    expect(font).to_have_attribute("step", "1")
    expect(zoom).to_have_attribute("min", "30")
    expect(zoom).to_have_attribute("max", "400")
    expect(zoom).to_have_attribute("step", "5")  # preview zoom moves in 5% steps
    font_val = pop.locator(".settingRange .val").nth(0)
    zoom_val = pop.locator(".settingRange .val").nth(1)
    font_reset = pop.locator(".settingRange .settingReset").nth(0)
    zoom_reset = pop.locator(".settingRange .settingReset").nth(1)
    expect(font_reset).to_be_disabled()  # already at the 14px default
    font.press("End")  # A+: max font, dialog must stay open
    expect(pop).to_be_visible()
    expect(font_val).to_have_text("24px")
    assert page.evaluate("() => localStorage.getItem('typst_ed')") == "24"
    expect(font_reset).to_be_enabled()
    font_reset.click()  # back to the default without closing the dialog
    expect(pop).to_be_visible()
    expect(font_val).to_have_text("14px")
    expect(font_reset).to_be_disabled()
    assert page.evaluate("() => localStorage.getItem('typst_ed')") == "14"
    zoom.press("End")  # zoom+: max preview size, still open
    expect(pop).to_be_visible()
    expect(zoom_val).to_have_text("400 %")
    assert page.evaluate("() => localStorage.getItem('typst_pv')") == "400"
    expect(zoom_reset).to_be_enabled()
    zoom.press("Home")
    expect(zoom_val).to_have_text("30 %")
    zoom.press("ArrowRight")
    expect(zoom_val).to_have_text("35 %")  # 5% steps, not 1%
    assert page.evaluate("() => localStorage.getItem('typst_pv')") == "35"
    zoom_reset.click()  # reset also pins the explicit 100% default
    expect(pop).to_be_visible()
    expect(zoom_val).to_have_text("100 %")
    expect(zoom_reset).to_be_disabled()
    assert page.evaluate("() => localStorage.getItem('typst_pv')") == "100"
    assert page.evaluate("() => localStorage.getItem('typst_pv_mode')") == "pct"
