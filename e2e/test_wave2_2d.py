"""Wave 2D: settings language without reload + visible keyboard focus."""
from helpers import register
from playwright.sync_api import expect


def _open_settings(page):
    expect(page.locator("#cm .cm-content")).to_be_visible()
    page.click("#who")
    pop = page.locator("#setPop")
    if not pop.is_visible():  # async openDoc hidePops() won the race: toggle back open
        page.click("#who")
    expect(pop).to_be_visible()
    return pop


def test_2d_lang_switch_no_reload(page):
    register(page, "e2e_2d_lang")
    pop = _open_settings(page)
    page.evaluate("() => { window.__noReload2d = 41 }")
    lang = pop.locator("#langSel")
    expect(lang).to_be_visible()
    lang.select_option("de")
    expect(pop.locator(".sTop b")).to_have_text("Einstellungen")
    assert page.evaluate("() => window.__noReload2d") == 41  # marker survives: no reload
    assert page.evaluate("() => document.documentElement.lang") == "de"
    assert page.evaluate("() => window.curLang && window.curLang()") == "de"
    assert page.evaluate("() => localStorage.getItem('typst_lang')") == "de"
    lang.select_option("en")
    expect(pop.locator(".sTop b")).to_have_text("Settings")
    assert page.evaluate("() => window.__noReload2d") == 41
    assert page.evaluate("() => localStorage.getItem('typst_lang')") == "en"


def test_2d_sessions_theme_and_focus(page):
    register(page, "e2e_2d_focus")
    pop = _open_settings(page)
    page.evaluate("() => { window.__noReload2d = 7 }")
    # theme switch without reload
    theme = pop.locator("#themeSel")
    expect(theme).to_be_visible()
    theme.select_option("dark")
    assert page.evaluate("() => document.documentElement.getAttribute('data-theme')") == "dark"
    assert page.evaluate("() => window.__noReload2d") == 7
    theme.select_option("system")
    # sessions list shows this device (backend 1C endpoints)
    expect(pop.locator(".sessRow").first).to_be_visible(timeout=10_000)
    page.wait_for_timeout(800)  # keys fetch also re-renders: let both settle so focus sticks
    # keyboard: focus the language select, Tab moves on with a visible frame
    pop.locator("#langSel").focus()
    expect(pop.locator("#langSel")).to_be_focused()
    box = page.evaluate(
        """() => { const s = getComputedStyle(document.activeElement);
            return { outline: s.outlineWidth + ' ' + s.outlineStyle, shadow: s.boxShadow } }"""
    )
    assert box["outline"] != "0px none" or box["shadow"] != "none", box
    page.keyboard.press("Tab")
    expect(pop.locator("#themeSel")).to_be_focused()
    box2 = page.evaluate(
        """() => { const s = getComputedStyle(document.activeElement);
            return { outline: s.outlineWidth + ' ' + s.outlineStyle, shadow: s.boxShadow } }"""
    )
    assert box2["outline"] != "0px none" or box2["shadow"] != "none", box2
