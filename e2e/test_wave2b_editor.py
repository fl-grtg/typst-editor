"""Wave 2B (Editor): one new path covering the track.

Format shortcut formats the doc, a second run is stable (idempotent), the
preview still renders a canvas, the Help button opens the shortcut overview,
and the toolbar stays one line (shortcuts + spellcheck live in Settings now,
spellcheck wiring is per document).
"""
from helpers import create_doc, register, type_source
from playwright.sync_api import expect

PREVIEW_TIMEOUT = 60_000  # first compile loads the WASM compiler

UNFORMATTED = "#let   x=1\n#let y   =   2\n\n=   Title\n\nText."


def test_9_format_shortcut_preview_shortcuts_spell(page):
    register(page, "e2e_ivan")
    create_doc(page, "Format doc")
    type_source(page, UNFORMATTED)
    page.keyboard.press("Alt+Shift+F")
    for bit in ("#let x = 1", "#let y = 2", "= Title"):
        expect(page.locator("#cm .cm-content")).to_contain_text(bit)
    before = page.locator("#cm .cm-content").inner_text()
    page.keyboard.press("Alt+Shift+F")  # second run: a no-op (nothing dispatched when stable)
    assert page.locator("#cm .cm-content").inner_text() == before
    expect(page.locator("#preview canvas").first).to_be_visible(timeout=PREVIEW_TIMEOUT)
    page.locator("#fmtSave").click()  # format on save on: Ctrl+S saves formatted
    expect(page.locator("#fmtSave")).to_have_attribute("aria-pressed", "true")
    type_source(page, UNFORMATTED)
    page.keyboard.press("ControlOrMeta+S")
    for bit in ("#let x = 1", "#let y = 2", "= Title"):
        expect(page.locator("#cm .cm-content")).to_contain_text(bit)
    page.locator('.sbHead [data-rail="help"]').click()  # Help = shortcut overview
    expect(page.locator("#scOverlay")).to_be_visible()
    expect(page.locator("#scCard")).to_contain_text("Format")
    page.keyboard.press("Escape")
    expect(page.locator("#scOverlay")).not_to_be_visible()
    expect(page.locator("#tools #spellSel")).to_have_count(0)  # toolbar stays one line: no spell select in it
    page.set_viewport_size({"width": 1920, "height": 900})
    assert page.locator("#tools").evaluate("n => n.getBoundingClientRect().height") < 60
    page.locator("#who").click()  # Settings holds shortcuts + spellcheck now
    pop = page.locator("#setPop")
    if not pop.is_visible():
        page.locator("#who").click()
    expect(pop).to_be_visible()
    pop.locator("#scOpen").click()  # shortcut overview from Settings
    expect(page.locator("#scOverlay")).to_be_visible()
    expect(page.locator("#scCard")).to_contain_text("Format")
    page.keyboard.press("Escape")
    page.locator("#who").click()  # overview closed the dialog: reopen for spellcheck
    pop = page.locator("#setPop")
    if not pop.is_visible():
        page.locator("#who").click()
    pop.locator("#spellSel").select_option("de")  # spellcheck language per document
    expect(pop.locator("#spellSel")).to_have_value("de")
    assert page.eval_on_selector("#cm .cm-content", "n => n.getAttribute('lang')") == "de"
    assert page.eval_on_selector("#cm .cm-content", "n => n.getAttribute('spellcheck')") == "true"
    pop.locator("#spellSel").select_option("off")
    assert page.eval_on_selector("#cm .cm-content", "n => n.getAttribute('spellcheck')") == "false"
    assert page.eval_on_selector("#cm .cm-content", "n => n.getAttribute('lang')") is None
