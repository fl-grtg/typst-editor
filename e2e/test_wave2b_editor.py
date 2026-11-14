"""Wave 2B (Editor): paths covering the track.

Format shortcut formats the doc, a second run is stable (idempotent), the
preview still renders a canvas, the Help button opens the link menu (GitHub,
issues, shortcut settings) and the Help menu mirrors it, the toolbar stays one
line (format-on-save + spellcheck live in Settings), spellcheck wiring is per
document, and line wrapping toggles between wrapped and horizontally scrolling
lines.
"""
import re

from helpers import create_doc, register, type_source
from playwright.sync_api import expect

PREVIEW_TIMEOUT = 60_000  # first compile loads the WASM compiler

UNFORMATTED = "#let   x=1\n#let y   =   2\n\n=   Title\n\nText."


def test_9_format_shortcut_preview_shortcuts_spell(page):
    register(page, "e2e_format")
    create_doc(page, "Format doc")
    type_source(page, UNFORMATTED)
    page.keyboard.press("Alt+Shift+F")
    for bit in ("#let x = 1", "#let y = 2", "= Title"):
        expect(page.locator("#cm .cm-content")).to_contain_text(bit)
    before = page.locator("#cm .cm-content").inner_text()
    page.keyboard.press("Alt+Shift+F")  # second run: a no-op (nothing dispatched when stable)
    assert page.locator("#cm .cm-content").inner_text() == before
    expect(page.locator("#preview canvas").first).to_be_visible(timeout=PREVIEW_TIMEOUT)
    expect(page.locator("#tools #fmtSave")).to_have_count(0)  # toolbar: format-on-save lives in Settings now
    expect(page.locator("#tools #spellSel")).to_have_count(0)  # toolbar stays one line: no spell select in it
    page.set_viewport_size({"width": 1920, "height": 900})
    assert page.locator("#tools").evaluate("n => n.getBoundingClientRect().height") < 60
    page.locator('.sbHead [data-rail="help"]').click()  # Help = rounded link menu
    help = page.locator("#helpOverlay")
    expect(help).to_be_visible()
    assert "blur(6px)" in help.evaluate("n => getComputedStyle(n).backdropFilter")  # the page behind the dialog stays softly blurred
    expect(page.locator("#helpCard")).to_contain_text("GitHub Issues")
    expect(page.locator("#helpCard")).to_contain_text("Keyboard shortcuts")
    expect(page.locator("#helpCard")).to_contain_text("Connect your agent")
    expect(page.locator("#helpCard .helpTips")).to_have_count(0)  # no keyboard tips block anymore
    github = page.locator('#helpCard a[href="https://github.com/fl-grtg/typst-editor"]')
    issues = page.locator('#helpCard a[href="https://github.com/fl-grtg/typst-editor/issues"]')
    expect(github.locator(".helpExt svg")).to_have_count(1)  # external links carry a right-edge marker
    expect(issues.locator(".helpExt svg")).to_have_count(1)
    label_box = github.locator(".helpLb").bounding_box()
    external_box = github.locator(".helpExt").bounding_box()
    assert external_box["x"] > label_box["x"] + label_box["width"]  # the marker sits on the far right
    expect(page.locator("#helpCard button.helpItem").locator(".helpExt")).to_have_count(0)  # internal links stay plain
    assert page.locator("#helpCard .helpHead button").evaluate("n => getComputedStyle(n).borderRadius") == "8px"  # square-ish hover, not a circle
    page.keyboard.press("Escape")
    expect(help).not_to_be_visible()
    page.locator('.sbHead [data-rail="help"]').click()
    page.locator("#helpCard button.helpItem").filter(has_text="Connect your agent").click()  # opens API and agent settings
    pop = page.locator("#setPop")
    expect(pop).to_be_visible()
    expect(pop.locator('.setNavItem[data-category="api"]')).to_have_class(re.compile(r"\bactive\b"))
    expect(pop.locator(".agentRow")).to_contain_text("Paste this prompt into your agent.")
    pop.locator(".sTop button").nth(0).click()
    expect(pop).not_to_be_visible()
    page.locator('#menubar [data-menu="help"]').click()  # Help menu mirrors the same links
    help_menu = page.locator("#menu")
    expect(help_menu.locator(".ext svg")).to_have_count(2)  # GitHub entries carry the external marker too
    expect(help_menu.get_by_role("button", name="Keyboard shortcuts").locator(".ext")).to_have_count(0)
    help_menu.get_by_text("Keyboard shortcuts").click()
    pop = page.locator("#setPop")
    expect(pop).to_be_visible()
    expect(pop.locator('.setNavItem[data-category="shortcuts"]')).to_have_class(re.compile(r"\bactive\b"))
    expect(pop.locator('[data-shortcut-row="format"]')).to_contain_text("Format document")
    page.locator("#who").click()  # Settings holds the shortcut editor now
    if not pop.is_visible():
        page.locator("#who").click()
    expect(pop).to_be_visible()
    expect(pop.locator('.setNavItem[data-category="shortcuts"]')).to_have_count(1)
    expect(pop.locator("#spellSel")).to_have_count(1)
    pop.locator('.setNavItem[data-category="editor"]').click()  # editor controls live in the Editor view
    pop.locator("#fmtSave").check()  # format on save on: Ctrl+S saves formatted
    expect(pop.locator("#fmtSave")).to_be_checked()
    page.locator("#who").click()  # settings overlays the editor: close before typing
    expect(pop).not_to_be_visible()
    type_source(page, UNFORMATTED)
    page.keyboard.press("ControlOrMeta+S")
    for bit in ("#let x = 1", "#let y = 2", "= Title"):
        expect(page.locator("#cm .cm-content")).to_contain_text(bit)
    page.locator("#who").click()  # typing closed the dialog: reopen for spellcheck
    pop = page.locator("#setPop")
    if not pop.is_visible():
        page.locator("#who").click()
    pop.locator('.setNavItem[data-category="editor"]').click()
    pop.locator("#spellSel").select_option("de")  # spellcheck language per document
    expect(pop.locator("#spellSel")).to_have_value("de")
    expect(page.locator('#cm .cm-content')).to_have_attribute('lang', 'de')
    assert page.eval_on_selector("#cm .cm-content", "n => n.getAttribute('spellcheck')") == "true"
    pop.locator("#spellSel").select_option("off")
    expect(page.locator('#cm .cm-content')).to_have_attribute('spellcheck', 'false')
    assert page.eval_on_selector("#cm .cm-content", "n => n.getAttribute('lang')") is None


def test_10_line_wrap_setting(page):
    register(page, "e2e_wrap")
    create_doc(page, "Wrap doc")
    type_source(page, "Wort " * 400)

    scroller = "#cm .cm-scroller"

    def widths():
        return page.eval_on_selector(scroller, "n => [n.scrollWidth, n.clientWidth]")

    scroll, client = widths()
    assert scroll <= client + 1  # wrapping is on by default

    page.locator("#who").click()
    pop = page.locator("#setPop")
    pop.locator('.setNavItem[data-category="editor"]').click()
    wrap = pop.locator("#wrapSet")
    expect(wrap).to_be_checked()
    wrap.click()
    expect(wrap).not_to_be_checked()
    assert page.eval_on_selector("#cmWrap", "n => n.classList.contains('wrapOff')")
    assert page.evaluate("() => localStorage.getItem('typst_wrap')") == "0"
    scroll, client = widths()
    assert scroll > client * 2  # long lines scroll horizontally
    page.eval_on_selector(scroller, "n => n.scrollLeft = 200")
    assert page.eval_on_selector(scroller, "n => n.scrollLeft") == 200

    page.reload()
    page.wait_for_function("window.__booted === true")
    assert page.eval_on_selector("#cmWrap", "n => n.classList.contains('wrapOff')")
    assert page.evaluate("() => localStorage.getItem('typst_wrap')") == "0"

    page.locator("#who").click()
    pop = page.locator("#setPop")
    pop.locator('.setNavItem[data-category="editor"]').click()
    wrap = pop.locator("#wrapSet")
    expect(wrap).not_to_be_checked()
    wrap.click()
    expect(wrap).to_be_checked()
    assert not page.eval_on_selector("#cmWrap", "n => n.classList.contains('wrapOff')")
    assert page.evaluate("() => localStorage.getItem('typst_wrap')") == "1"


def test_11_shortcut_settings_conflict_reset(page):
    register(page, "e2e_shortcuts")
    page.locator("#who").click()
    pop = page.locator("#setPop")
    pop.locator('.setNavItem[data-category="shortcuts"]').click()
    fmt = pop.locator('[data-shortcut-row="format"]')
    save = pop.locator('[data-shortcut-row="save"]')
    categories = page.evaluate("() => Object.fromEntries([...document.querySelectorAll('[data-shortcut-row]')].map(r => [r.dataset.shortcutRow, r.closest('.grp').querySelector('h4').textContent]))")
    assert categories == {
        "nextTab": "General", "prevTab": "General", "openHelp": "General", "closeLayer": "General",
        "save": "Editor", "find": "Editor", "findNext": "Editor", "findPrev": "Editor",
        "bold": "Editor", "italic": "Editor", "underline": "Editor", "format": "Editor",
        "complete": "Editor", "accept": "Editor", "dedent": "Editor",
        "zoomIn": "Preview", "zoomOut": "Preview", "zoomReset": "Preview",
    }  # only three categories, every action sorted by scope
    reset_all = pop.locator("[data-shortcut-reset-all]")
    expect(reset_all).to_be_visible()
    expect(reset_all).to_be_disabled()
    expect(reset_all).to_have_attribute("title", "Reset all shortcuts")
    search_box = pop.locator("[data-shortcut-search]").bounding_box()
    reset_box = reset_all.bounding_box()
    assert abs(search_box["height"] - reset_box["height"]) <= 1  # square button matches the search height
    assert reset_box["x"] >= search_box["x"] + search_box["width"] + 4  # sits right of the shortened search
    expect(fmt.locator(".shortcutKbd")).to_have_text("Alt+Shift+F")
    expect(save.locator(".shortcutKbd")).to_have_text("Ctrl+S")
    fmt_reset = fmt.locator('[data-shortcut-reset="format"]')
    expect(fmt_reset).to_have_text("")  # icon-only reset keeps hover text
    expect(fmt_reset.locator("svg")).to_have_count(1)
    expect(fmt_reset).to_have_attribute("title", "Reset to default")
    expect(fmt_reset).to_be_hidden()  # default shortcuts have nothing to reset
    fmt_clear = fmt.locator('[data-shortcut-clear="format"]')
    expect(fmt_clear).to_have_attribute("title", "Clear shortcut")
    expect(fmt_clear).to_be_visible()  # every bound shortcut can be cleared

    search = pop.locator("[data-shortcut-search]")
    search.fill("zoom")  # filter by action name
    expect(pop.locator('[data-shortcut-row="zoomReset"]')).to_be_visible()
    expect(pop.locator('[data-shortcut-row="save"]')).to_be_hidden()
    assert page.evaluate("() => { const g = [...document.querySelectorAll('#setPop .shortcutSettings .grp')].find(n => !n.hidden); return g.classList.contains('grpFirst') && getComputedStyle(g).borderTopWidth === '0px' }")  # first visible category has no divider above it
    search.fill("ctrl+s")  # filter by current key combination
    expect(pop.locator('[data-shortcut-row="save"]')).to_be_visible()
    expect(pop.locator('[data-shortcut-row="format"]')).to_be_hidden()
    search.fill("")
    search.click()
    page.keyboard.press("Control+S")  # pressing a combo in the search finds it instead of firing it
    expect(search).to_have_value("Ctrl+S")
    expect(pop.locator('[data-shortcut-row="save"]')).to_be_visible()
    expect(pop.locator('[data-shortcut-row="find"]')).to_be_hidden()
    expect(pop.locator('[data-shortcut-row="format"]')).to_be_hidden()
    search.fill("zzz-no-match")
    expect(pop.locator(".shortcutEmpty")).to_be_visible()
    search.press("Escape")  # Escape clears the filter before closing settings
    expect(search).to_have_value("")
    expect(pop).to_be_visible()
    expect(pop.locator('[data-shortcut-row="save"]')).to_be_visible()

    fmt.locator('[data-shortcut-change="format"]').click()  # leave the view while recording: state resets
    expect(fmt.locator(".shortcutKbd.recording")).to_be_visible()
    expect(fmt.locator(".shortcutKbd.recording")).to_have_attribute("title", "Click to cancel")
    expect(fmt.locator(".shortcutHint")).to_contain_text("Press the shortcut you want.")
    expect(fmt.locator("[data-shortcut-cancel]")).to_have_text("Cancel")  # the banner has its own cancel button
    pop.locator('.setNavItem[data-category="editor"]').click()
    pop.locator('.setNavItem[data-category="shortcuts"]').click()
    fmt = pop.locator('[data-shortcut-row="format"]')
    expect(fmt.locator(".shortcutKbd.recording")).to_have_count(0)
    expect(fmt.locator(".shortcutKbd")).to_have_text("Alt+Shift+F")

    fmt.locator('[data-shortcut-change="format"]').click()
    page.keyboard.press("Control+Alt+K")  # rebind and persist
    expect(fmt.locator(".shortcutKbd")).to_have_text("Ctrl+Alt+K")
    toast = page.locator("#toast")
    expect(toast.locator("button")).to_have_text("Undo")  # a changed binding can be undone
    toast.locator("button").click()  # undo keeps Settings open
    assert page.evaluate("() => !('format' in JSON.parse(localStorage.getItem('typst_shortcuts') || '{}'))")
    expect(pop).to_be_visible()
    fmt = pop.locator('[data-shortcut-row="format"]')
    expect(fmt.locator(".shortcutKbd")).to_have_text("Alt+Shift+F")
    fmt.locator('[data-shortcut-change="format"]').click()
    page.keyboard.press("Control+Alt+K")
    expect(fmt.locator(".shortcutKbd")).to_have_text("Ctrl+Alt+K")
    expect(reset_all).to_be_enabled()  # a custom binding enables the global reset
    fmt_reset = fmt.locator('[data-shortcut-reset="format"]')
    expect(fmt_reset).to_be_visible()
    assert fmt_reset.bounding_box()["x"] < fmt.locator(".shortcutKbd").bounding_box()["x"] < fmt.locator('[data-shortcut-clear="format"]').bounding_box()["x"]  # reset left, clear right of the field
    assert page.evaluate("() => { const r = document.querySelector('[data-shortcut-row=\"format\"]'); const k = r.querySelector('.shortcutKeys'); return k.firstElementChild.matches('[data-shortcut-reset]') && k.lastElementChild.matches('[data-shortcut-clear]') && k.children[1].matches('.shortcutKbd') }")
    assert page.eval_on_selector("[data-shortcut-search]", "n => getComputedStyle(n.closest('.shortcutSearch')).borderBottomWidth") == "0px"  # no line under the search
    assert page.eval_on_selector('[data-shortcut-row="format"]', "n => getComputedStyle(n).borderTopWidth") == "0px"  # rows are not divided
    assert page.evaluate("() => [...document.querySelectorAll('#setPop .shortcutSettings .grp')].slice(1).every(g => parseFloat(getComputedStyle(g).borderTopWidth) > 0)")  # categories are divided
    assert page.evaluate("() => JSON.parse(localStorage.getItem('typst_shortcuts'))['format']") == "mod+alt+k"
    page.reload()
    page.wait_for_function("window.__booted === true")
    page.locator("#who").click()
    pop = page.locator("#setPop")
    pop.locator('.setNavItem[data-category="shortcuts"]').click()
    fmt = pop.locator('[data-shortcut-row="format"]')
    save = pop.locator('[data-shortcut-row="save"]')
    expect(fmt.locator(".shortcutKbd")).to_have_text("Ctrl+Alt+K")

    fmt.locator('[data-shortcut-change="format"]').click()
    page.keyboard.press("Control+S")  # conflict with Save now
    notice = fmt.locator(".shortcutNotice")
    expect(notice).to_contain_text("Ctrl+S is already used by “Save now”.")  # the warning names the combo
    expect(notice).to_contain_text("“Use anyway” removes the other shortcut.")
    view_box = pop.locator(".shortcutSettings").bounding_box()
    note_box = notice.bounding_box()
    assert abs(note_box["x"] - view_box["x"]) <= 1  # the warning spans the list, not an extra indent
    assert abs(note_box["x"] + note_box["width"] - (view_box["x"] + view_box["width"])) <= 1
    assert 8 <= notice.locator(".shortcutNoticeText").bounding_box()["x"] - note_box["x"] <= 14  # warning text has a readable inset
    use_anyway = notice.locator("[data-shortcut-use]")
    discard = notice.locator("[data-shortcut-discard]")
    expect(use_anyway).to_have_attribute("title", "Removes the other shortcut")
    expect(discard).to_have_text("Discard")
    expect(discard).to_have_attribute("title", "Discard change")
    expect(fmt.locator(".shortcutKbd")).to_have_text("Ctrl+S")  # the attempted combo stays visible
    expect(fmt.locator(".shortcutKbd")).to_have_class(re.compile(r"\bpending\b"))
    page.keyboard.press("Escape")  # leave the conflict editor, not the settings
    expect(notice).to_have_count(0)
    expect(pop).to_be_visible()
    expect(fmt.locator(".shortcutKbd")).to_have_text("Ctrl+Alt+K")
    expect(fmt.locator(".shortcutKbd")).not_to_have_class(re.compile(r"\bpending\b"))
    fmt.locator('[data-shortcut-change="format"]').click()
    page.keyboard.press("Control+S")
    notice = fmt.locator(".shortcutNotice")
    notice.locator("[data-shortcut-discard]").click()  # discard keeps both bindings
    expect(notice).to_have_count(0)
    expect(pop).to_be_visible()
    expect(fmt.locator(".shortcutKbd")).to_have_text("Ctrl+Alt+K")
    expect(fmt.locator(".shortcutKbd")).not_to_have_class(re.compile(r"\bpending\b"))
    expect(save.locator(".shortcutKbd")).to_have_text("Ctrl+S")
    fmt.locator('[data-shortcut-change="format"]').click()
    page.keyboard.press("Control+S")
    notice = fmt.locator(".shortcutNotice")
    notice.locator("[data-shortcut-use]").click()  # use anyway: Save now is unbound
    expect(save.locator(".shortcutUnset")).to_have_text("Not set")
    expect(fmt.locator(".shortcutKbd")).to_have_text("Ctrl+S")
    toast = page.locator("#toast")
    expect(toast.locator("button")).to_have_text("Undo")
    toast.locator("button").click()  # undo restores the replaced binding too
    expect(pop).to_be_visible()  # undo never closes Settings
    fmt = pop.locator('[data-shortcut-row="format"]')
    save = pop.locator('[data-shortcut-row="save"]')
    expect(fmt.locator(".shortcutKbd")).to_have_text("Ctrl+Alt+K")
    expect(save.locator(".shortcutKbd")).to_have_text("Ctrl+S")
    fmt.locator('[data-shortcut-change="format"]').click()
    page.keyboard.press("Control+S")
    notice = fmt.locator(".shortcutNotice")
    notice.locator("[data-shortcut-use]").click()
    expect(save.locator(".shortcutUnset")).to_have_text("Not set")
    expect(fmt.locator(".shortcutKbd")).to_have_text("Ctrl+S")

    fmt.locator('[data-shortcut-reset="format"]').click()  # reset back to the default
    expect(fmt.locator(".shortcutKbd")).to_have_text("Alt+Shift+F")
    expect(fmt.locator('[data-shortcut-reset="format"]')).to_be_hidden()
    save.locator('[data-shortcut-reset="save"]').click()
    expect(save.locator(".shortcutKbd")).to_have_text("Ctrl+S")
    expect(save.locator('[data-shortcut-reset="save"]')).to_be_hidden()
    assert page.evaluate("() => localStorage.getItem('typst_shortcuts')") is None
    expect(reset_all).to_be_disabled()  # everything is default again

    fmt.locator('[data-shortcut-change="format"]').click()
    page.keyboard.press("Control+Alt+K")
    fmt.locator('[data-shortcut-reset="format"]').click()
    expect(fmt.locator(".shortcutKbd")).to_have_text("Alt+Shift+F")
    expect(page.locator("#toast button")).to_have_text("Undo")
    page.locator("#toast button").click()  # undo a reset restores the custom binding
    expect(pop).to_be_visible()  # undo keeps Settings open
    fmt = pop.locator('[data-shortcut-row="format"]')
    expect(fmt.locator(".shortcutKbd")).to_have_text("Ctrl+Alt+K")
    fmt.locator('[data-shortcut-reset="format"]').click()
    expect(fmt.locator(".shortcutKbd")).to_have_text("Alt+Shift+F")

    zoom = pop.locator('[data-shortcut-row="zoomReset"]')
    zoom.locator('[data-shortcut-change="zoomReset"]').click()
    expect(zoom.locator(".shortcutKbd.recording")).to_be_visible()
    zoom.locator('[data-shortcut-change="zoomReset"]').click()  # clicking the field cancels recording
    expect(zoom.locator(".shortcutKbd")).to_have_text("Ctrl+0")
    close_layer = pop.locator('[data-shortcut-row="closeLayer"]')
    close_layer.locator('[data-shortcut-clear="closeLayer"]').click()
    expect(close_layer.locator(".shortcutUnset")).to_have_text("Not set")
    close_layer.locator('[data-shortcut-reset="closeLayer"]').click()
    expect(close_layer.locator(".shortcutKbd")).to_have_text("Esc")
    zoom.locator('[data-shortcut-change="zoomReset"]').click()
    page.keyboard.press("Escape")  # Esc is recorded like any other key
    notice = zoom.locator(".shortcutNotice")
    expect(notice).to_contain_text("Esc is already used by “Close dialog, popover or find bar, or clear a search”.")
    notice.locator("[data-shortcut-discard]").click()
    expect(zoom.locator(".shortcutKbd")).to_have_text("Ctrl+0")
    expect(zoom.locator(".shortcutKbd.recording")).to_have_count(0)
    expect(zoom.locator(".shortcutHint")).to_have_count(0)

    zoom.locator('[data-shortcut-change="zoomReset"]').click()
    page.evaluate("() => document.dispatchEvent(new KeyboardEvent('keydown', {key: 'r', ctrlKey: true, bubbles: true, cancelable: true}))")
    notice = zoom.locator(".shortcutNotice")
    expect(notice).to_contain_text("Ctrl+R is reserved by the browser.")  # browser keys warn in place too
    expect(notice).to_contain_text("Choose a different shortcut.")
    expect(notice.locator("[data-shortcut-use]")).to_have_count(0)  # a browser key cannot be used anyway
    expect(zoom.locator(".shortcutKbd")).to_have_text("Ctrl+R")  # the attempted combo stays visible
    expect(zoom.locator(".shortcutKbd")).to_have_class(re.compile(r"\bpending\b"))
    notice.locator("[data-shortcut-discard]").click()
    expect(zoom.locator(".shortcutKbd")).to_have_text("Ctrl+0")

    zoom.locator('[data-shortcut-change="zoomReset"]').click()
    page.keyboard.press("Backspace")  # Backspace is recorded, not a clear command
    expect(zoom.locator(".shortcutKbd")).to_have_text("⌫")
    zoom_clear = zoom.locator('[data-shortcut-clear="zoomReset"]')
    expect(zoom_clear).to_be_visible()  # a bound shortcut can still be cleared
    expect(zoom_clear).to_be_enabled()
    content = pop.locator(".setContent")  # a settings change re-renders without jumping to the top
    before = content.evaluate("n => { n.scrollTop = n.scrollHeight; return n.scrollTop }")
    assert before > 0
    zoom.locator('[data-shortcut-reset="zoomReset"]').click()
    expect(zoom.locator(".shortcutKbd")).to_have_text("Ctrl+0")
    after = content.evaluate("n => n.scrollTop")
    assert abs(after - before) <= 2, (before, after)
    save.locator('[data-shortcut-change="save"]').click()
    page.keyboard.press("Alt+Shift+F")  # conflict with Format's default
    notice = save.locator(".shortcutNotice")
    expect(notice).to_contain_text("Format document")
    notice.locator("[data-shortcut-use]").click()
    expect(fmt.locator(".shortcutUnset")).to_have_text("Not set")
    fmt.locator('[data-shortcut-reset="format"]').click()  # reset conflicts with Save's custom binding
    notice = fmt.locator(".shortcutNotice")
    expect(notice).to_contain_text("Save now")
    notice.locator("[data-shortcut-use]").click()
    expect(fmt.locator(".shortcutKbd")).to_have_text("Alt+Shift+F")
    expect(save.locator(".shortcutUnset")).to_have_text("Not set")
    save.locator('[data-shortcut-reset="save"]').click()
    expect(save.locator(".shortcutKbd")).to_have_text("Ctrl+S")

    save_clear = save.locator('[data-shortcut-clear="save"]')
    expect(save_clear).to_be_visible()
    expect(save_clear).to_have_attribute("title", "Clear shortcut")
    save_clear.click()  # clear removes the binding entirely
    expect(save.locator(".shortcutUnset")).to_have_text("Not set")
    expect(save_clear).to_be_visible()  # the clear button stays, grayed out
    expect(save_clear).to_be_disabled()
    expect(save.locator('[data-shortcut-reset="save"]')).to_be_visible()
    assert page.evaluate("() => JSON.parse(localStorage.getItem('typst_shortcuts'))['save']") == ""
    search = pop.locator("[data-shortcut-search]")
    search.fill("not set")  # unset shortcuts are searchable by state
    expect(save).to_be_visible()
    expect(pop.locator('[data-shortcut-row="format"]')).to_be_hidden()
    search.fill("")
    search.click()
    page.keyboard.press("Control+Shift+X")  # any combo is accepted in the search, even an unbound one
    expect(search).to_have_value("Ctrl+Shift+X")
    expect(pop.locator(".shortcutEmpty")).to_be_visible()
    search.fill("")
    search.click()
    page.keyboard.press("Control+Alt+T")  # a modified combo stays searchable
    expect(search).to_have_value("Ctrl+Alt+T")
    expect(pop.locator(".shortcutEmpty")).to_be_visible()
    search.fill("")
    search.click()
    page.keyboard.press("Control+S")  # an unset shortcut's default combo is still findable while searching
    expect(search).to_have_value("Ctrl+S")
    expect(save).to_be_visible()
    expect(pop.locator('[data-shortcut-row="find"]')).to_be_hidden()
    search.fill("")
    save.locator('[data-shortcut-reset="save"]').click()
    expect(save.locator(".shortcutKbd")).to_have_text("Ctrl+S")

    pop.locator('.setNavItem[data-category="account"]').click()  # German key names: Strg, Umschalt, Eingabe, Bild ↑/↓
    page.select_option("#langSel", "de")
    pop.locator('.setNavItem[data-category="shortcuts"]').click()
    expect(pop.locator('[data-shortcut-row="save"] .shortcutKbd')).to_have_text("Strg+S")
    expect(pop.locator('[data-shortcut-row="findNext"] .shortcutKbd')).to_have_text("↵")  # keys show their glyph, not a word
    expect(pop.locator('[data-shortcut-row="findPrev"] .shortcutKbd')).to_have_text("Umschalt+↵")
    expect(pop.locator('[data-shortcut-row="accept"] .shortcutKbd')).to_have_text("⇥")
    expect(pop.locator('[data-shortcut-row="dedent"] .shortcutKbd')).to_have_text("Umschalt+⇥")
    expect(pop.locator('[data-shortcut-row="complete"] .shortcutKbd')).to_have_text("Strg+␣")
    next_tab = pop.locator('[data-shortcut-row="nextTab"] .shortcutKbd')
    prev_tab = pop.locator('[data-shortcut-row="prevTab"] .shortcutKbd')
    expect(next_tab).to_have_text("Strg+Alt+Bild↓")
    expect(prev_tab).to_have_text("Strg+Alt+Bild↑")
    expect(next_tab.locator(".shortcutKeyWithArrow .shortcutArrow svg")).to_have_count(1)  # the arrow is the same icon as on arrow keys
    expect(prev_tab.locator(".shortcutKeyWithArrow .shortcutArrow svg")).to_have_count(1)
    for row_id in ("findNext", "findPrev", "accept", "dedent", "complete", "zoomIn", "zoomOut"):
        expect(pop.locator(f'[data-shortcut-row="{row_id}"] .shortcutIcon svg')).to_have_count(1)
    expect(pop.locator('[data-shortcut-row="zoomIn"] .shortcutKbd')).to_have_text("Strg++")
    expect(pop.locator('[data-shortcut-row="zoomOut"] .shortcutKbd')).to_have_text("Strg+−")
    expect(pop.locator('[data-shortcut-row="zoomReset"] .shortcutKbd')).to_have_text("Strg+0")
    expect(pop.locator('[data-shortcut-row="save"] [data-shortcut-reset="save"]')).to_have_attribute("title", "Auf Standard zurücksetzen")
    search = pop.locator("[data-shortcut-search]")
    expect(search).to_have_attribute("placeholder", "Tastenkürzel oder Kombination suchen…")
    search.fill("Bild ↓")  # search matches the localized key names
    expect(pop.locator('[data-shortcut-row="nextTab"]')).to_be_visible()
    expect(pop.locator('[data-shortcut-row="save"]')).to_be_hidden()
    search.fill("Eingabe")  # spelled-out key names still find glyph bindings
    expect(pop.locator('[data-shortcut-row="findNext"]')).to_be_visible()
    expect(pop.locator('[data-shortcut-row="nextTab"]')).to_be_hidden()
    search.fill("")
    search.click()
    page.keyboard.press("Control+Alt+PageDown")  # typed combos use the localized key names
    expect(search).to_have_value("Strg+Alt+Bild ↓")
    expect(pop.locator('[data-shortcut-row="nextTab"]')).to_be_visible()
    expect(pop.locator('[data-shortcut-row="save"]')).to_be_hidden()
    search.press("Escape")
    expect(search).to_have_value("")
    expect(pop.locator('[data-shortcut-row="save"]')).to_be_visible()
    save_clear = pop.locator('[data-shortcut-row="save"] [data-shortcut-clear="save"]')
    expect(save_clear).to_have_attribute("title", "Kürzel entfernen")
    save_clear.click()
    expect(pop.locator('[data-shortcut-row="save"] .shortcutUnset')).to_have_text("Nicht belegt")
    expect(save_clear).to_be_visible()
    expect(save_clear).to_be_disabled()
    search = pop.locator("[data-shortcut-search]")
    search.fill("nicht gesetzt")  # localized unset search words
    expect(pop.locator('[data-shortcut-row="save"]')).to_be_visible()
    expect(pop.locator('[data-shortcut-row="format"]')).to_be_hidden()
    search.fill("")
    search.click()
    page.keyboard.press("Control+S")  # unset defaults use the localized key labels too
    expect(search).to_have_value("Strg+S")
    expect(pop.locator('[data-shortcut-row="save"]')).to_be_visible()
    expect(pop.locator('[data-shortcut-row="format"]')).to_be_hidden()
    search.fill("")
    pop.locator('[data-shortcut-row="save"] [data-shortcut-reset="save"]').click()
    expect(pop.locator('[data-shortcut-row="save"] .shortcutKbd')).to_have_text("Strg+S")

    reset_all = pop.locator("[data-shortcut-reset-all]")
    expect(reset_all).to_have_attribute("title", "Alle Kürzel zurücksetzen")
    expect(reset_all).to_be_disabled()  # no custom shortcuts left
    fmt = pop.locator('[data-shortcut-row="format"]')
    fmt.locator('[data-shortcut-change="format"]').click()
    page.keyboard.press("Control+Alt+K")
    expect(fmt.locator(".shortcutKbd")).to_have_text("Strg+Alt+K")
    expect(reset_all).to_be_enabled()
    fmt.locator('[data-shortcut-change="format"]').click()
    page.keyboard.press("Control+S")
    notice = fmt.locator(".shortcutNotice")
    expect(notice).to_contain_text("Strg+S ist belegt durch „Jetzt speichern“.")
    expect(notice).to_contain_text("„Trotzdem verwenden“ entfernt das andere Kürzel.")
    expect(notice.locator("[data-shortcut-discard]")).to_have_text("Verwerfen")
    expect(notice.locator("[data-shortcut-use]")).to_have_text("Trotzdem verwenden")
    page.keyboard.press("Escape")  # dismisses only the warning
    expect(notice).to_have_count(0)
    expect(pop).to_be_visible()
    expect(fmt.locator(".shortcutKbd")).to_have_text("Strg+Alt+K")
    reset_all.click()  # one click restores every default at once, after a confirmation
    expect(page.locator("#modal")).to_be_visible()
    expect(page.locator("#mHead")).to_contain_text("Alle Tastenkürzel auf die Standardwerte zurücksetzen?")
    expect(page.locator("#mYes")).to_have_text("Alle zurücksetzen")
    page.locator("#mYes").click()
    expect(fmt.locator(".shortcutKbd")).to_have_text("Alt+Umschalt+F")
    expect(reset_all).to_be_disabled()
    assert page.evaluate("() => localStorage.getItem('typst_shortcuts')") is None


def test_12_shortcut_safety_and_behavior(page):
    register(page, "e2e_shortcuts_safe")
    create_doc(page, "Shortcut safety")
    type_source(page, UNFORMATTED)

    # A repeated key is still handled (and its browser default is suppressed).
    assert page.evaluate("() => !document.dispatchEvent(new KeyboardEvent('keydown', {key: 's', ctrlKey: true, repeat: true, bubbles: true, cancelable: true}))")

    # Non-Latin layouts fall back to the physical key: Cyrillic key + code KeyF formats.
    page.evaluate("() => document.dispatchEvent(new KeyboardEvent('keydown', {key: 'а', code: 'KeyF', altKey: true, shiftKey: true, bubbles: true, cancelable: true}))")
    for bit in ("#let x = 1", "#let y = 2", "= Title"):
        expect(page.locator("#cm .cm-content")).to_contain_text(bit)

    page.locator("#who").click()
    pop = page.locator("#setPop")
    pop.locator('.setNavItem[data-category="shortcuts"]').click()
    fmt = pop.locator('[data-shortcut-row="format"]')
    search = pop.locator("[data-shortcut-search]")

    # Clicking another field cancels recording before it can swallow typed text.
    fmt.locator('[data-shortcut-change="format"]').click()
    expect(fmt.locator(".shortcutKbd.recording")).to_be_visible()
    search.click()
    page.keyboard.type("zoom")
    expect(search).to_have_value("zoom")
    expect(fmt.locator(".shortcutHint")).to_have_count(0)
    expect(fmt.locator(".shortcutKbd")).to_have_text("Alt+Shift+F")
    search.fill("")

    # Esc is recorded like any other key; the hint says so.
    fmt.locator('[data-shortcut-change="format"]').click()
    expect(fmt.locator(".shortcutHint")).to_contain_text("Press the shortcut you want.")
    page.keyboard.press("Escape")
    notice = fmt.locator(".shortcutNotice")
    expect(notice).to_contain_text("Esc is already used by “Close dialog, popover or find bar, or clear a search”.")
    notice.locator("[data-shortcut-discard]").click()
    expect(fmt.locator(".shortcutKbd.recording")).to_have_count(0)
    expect(fmt.locator(".shortcutKbd")).to_have_text("Alt+Shift+F")

    # Clearing a binding offers undo in the toast.
    fmt.locator('[data-shortcut-clear="format"]').click()
    expect(fmt.locator(".shortcutUnset")).to_have_text("Not set")
    toast = page.locator("#toast")
    expect(toast).to_be_visible()
    expect(toast.locator("button")).to_have_text("Undo")
    toast.locator("button").click()
    assert page.evaluate("() => !('format' in JSON.parse(localStorage.getItem('typst_shortcuts') || '{}'))")
    expect(pop).to_be_visible()  # undo keeps Settings open
    fmt = pop.locator('[data-shortcut-row="format"]')
    expect(fmt.locator(".shortcutKbd")).to_have_text("Alt+Shift+F")

    # '=' and '+' are the same zoom key: rebinding zoomReset to Ctrl+= conflicts with zoomIn.
    zoom = pop.locator('[data-shortcut-row="zoomReset"]')
    zoom.locator('[data-shortcut-change="zoomReset"]').click()
    page.evaluate("() => document.dispatchEvent(new KeyboardEvent('keydown', {key: '=', ctrlKey: true, bubbles: true, cancelable: true}))")
    expect(zoom.locator(".shortcutNotice")).to_contain_text("Zoom preview in")
    page.keyboard.press("Escape")
    expect(zoom.locator(".shortcutNotice")).to_have_count(0)
    expect(zoom.locator(".shortcutKbd")).to_have_text("Ctrl+0")

    find = pop.locator('[data-shortcut-row="find"]')
    find.locator('[data-shortcut-change="find"]').click()
    page.keyboard.press("Control+Alt+F")
    expect(find.locator(".shortcutKbd")).to_have_text("Ctrl+Alt+F")

    # Reset all asks first; cancelling keeps the custom binding.
    reset_all = pop.locator("[data-shortcut-reset-all]")
    reset_all.click()
    expect(page.locator("#modal")).to_be_visible()
    expect(page.locator("#mHead")).to_contain_text("Reset all shortcuts to their defaults?")
    page.locator("#mNo").click()
    expect(find.locator(".shortcutKbd")).to_have_text("Ctrl+Alt+F")
    reset_all.click()
    page.locator("#mYes").click()
    expect(find.locator(".shortcutKbd")).to_have_text("Ctrl+F")

    # A rebound shortcut really fires outside Settings.
    find.locator('[data-shortcut-change="find"]').click()
    page.keyboard.press("Control+Alt+F")
    expect(find.locator(".shortcutKbd")).to_have_text("Ctrl+Alt+F")
    page.locator(".sTop button").nth(0).click()
    expect(pop).not_to_be_visible()
    page.click("#cm .cm-content")
    page.keyboard.press("Control+Alt+F")
    expect(page.locator("#find")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator("#find")).not_to_be_visible()

    # A cleared shortcut no longer fires.
    page.locator("#who").click()
    pop.locator('.setNavItem[data-category="shortcuts"]').click()
    find = pop.locator('[data-shortcut-row="find"]')
    find.locator('[data-shortcut-clear="find"]').click()
    expect(find.locator(".shortcutUnset")).to_have_text("Not set")
    pop.locator(".sTop button").nth(0).click()
    page.click("#cm .cm-content")
    page.keyboard.press("Control+F")
    expect(page.locator("#find")).not_to_be_visible()
    page.keyboard.press("Escape")

    # A cleared binding no longer advertises its old key in the menu (undo restores it).
    page.locator("#who").click()
    pop.locator('.setNavItem[data-category="shortcuts"]').click()
    save = pop.locator('[data-shortcut-row="save"]')
    save.locator('[data-shortcut-clear="save"]').click()
    expect(save.locator(".shortcutUnset")).to_have_text("Not set")
    pop.locator(".sTop button").nth(0).click()
    page.locator('#menubar [data-menu="file"]').click()
    save_item = page.locator("#menu button").filter(has_text="Save now")
    expect(save_item).to_have_count(1)
    expect(save_item.locator(".kbd")).to_have_count(0)
    page.keyboard.press("Escape")
    expect(page.locator("#toast button")).to_be_visible()
    page.locator("#toast button").click()
    page.locator("#who").click()
    pop.locator('.setNavItem[data-category="shortcuts"]').click()
    expect(pop.locator('[data-shortcut-row="save"] .shortcutKbd')).to_have_text("Ctrl+S")
    pop.locator(".sTop button").nth(0).click()

    # Opening Help again while it is open keeps the original focus restore target.
    page.locator('.sbHead [data-rail="help"]').click()
    expect(page.locator("#helpOverlay")).to_be_visible()
    page.keyboard.press("Shift+/")
    page.wait_for_timeout(60)
    expect(page.locator("#helpOverlay")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator("#helpOverlay")).not_to_be_visible()
    assert page.evaluate("() => document.activeElement && document.activeElement.dataset.rail") == "help"

    # Switching the language clears a stale localized shortcut filter.
    page.locator("#who").click()
    pop.locator('.setNavItem[data-category="shortcuts"]').click()
    search = pop.locator("[data-shortcut-search]")
    search.fill("ctrl+s")
    expect(pop.locator('[data-shortcut-row="save"]')).to_be_visible()
    pop.locator('.setNavItem[data-category="account"]').click()
    page.select_option("#langSel", "de")
    pop.locator('.setNavItem[data-category="shortcuts"]').click()
    expect(search).to_have_value("")
    expect(pop.locator('[data-shortcut-row="save"]')).to_be_visible()
    expect(pop.locator('[data-shortcut-row="save"] .shortcutKbd')).to_have_text("Strg+S")


def test_13_shortcut_fallbacks_and_recorded_tab(page):
    register(page, "e2e_sc_fallback")
    create_doc(page, "Shortcut fallbacks")
    type_source(page, "abc")

    # Tab is a recordable shortcut now; it no longer only cancels recording.
    page.locator("#who").click()
    pop = page.locator("#setPop")
    pop.locator('.setNavItem[data-category="shortcuts"]').click()
    zoom = pop.locator('[data-shortcut-row="zoomReset"]')
    zoom.locator('[data-shortcut-change="zoomReset"]').click()
    page.keyboard.press("Tab")
    notice = zoom.locator(".shortcutNotice")
    expect(notice).to_contain_text("Accept completion or indent")
    notice.locator("[data-shortcut-discard]").click()
    expect(zoom.locator(".shortcutKbd")).to_have_text("Ctrl+0")

    # Clearing accept/dedent still keeps the editor's Tab fallback.
    for row in ("accept", "dedent"):
        pop.locator(f'[data-shortcut-clear="{row}"]').click()
        expect(pop.locator(f'[data-shortcut-row="{row}"] .shortcutUnset')).to_have_text("Not set")
    page.locator(".sTop button").nth(0).click()
    page.click("#cm .cm-content")
    page.keyboard.press("Control+Home")
    page.keyboard.press("Tab")
    assert page.evaluate("() => /^\\s+abc/.test(document.querySelector('#cm .cm-line').textContent)")
    assert page.evaluate("() => document.querySelector('#cm').contains(document.activeElement)")
    page.keyboard.press("Shift+Tab")
    assert page.evaluate("() => /^abc/.test(document.querySelector('#cm .cm-line').textContent)")

    # A modifier-less F-key works inside the editor; it is not mistaken for typing.
    page.locator("#who").click()
    pop = page.locator("#setPop")
    if not pop.is_visible():
        page.locator("#who").click()
    pop.locator('.setNavItem[data-category="shortcuts"]').click()
    fmt = pop.locator('[data-shortcut-row="format"]')
    fmt.locator('[data-shortcut-change="format"]').click()
    page.keyboard.press("F3")
    expect(fmt.locator(".shortcutKbd")).to_have_text("F3")
    page.locator(".sTop button").nth(0).click()
    type_source(page, UNFORMATTED)
    page.keyboard.press("F3")
    for bit in ("#let x = 1", "#let y = 2", "= Title"):
        expect(page.locator("#cm .cm-content")).to_contain_text(bit)

    # Escape closes a layer even when closeLayer has been cleared.
    page.locator("#who").click()
    pop = page.locator("#setPop")
    if not pop.is_visible():
        page.locator("#who").click()
    pop.locator('.setNavItem[data-category="shortcuts"]').click()
    close_layer = pop.locator('[data-shortcut-row="closeLayer"]')
    close_layer.locator('[data-shortcut-clear="closeLayer"]').click()
    expect(close_layer.locator(".shortcutUnset")).to_have_text("Not set")
    page.keyboard.press("Escape")
    expect(pop).not_to_be_visible()

    # The menubar proxy respects context guards instead of running blindly.
    page.click("#cm .cm-content")
    assert page.evaluate("() => window.scRunShortcut('openHelp')") is False
    expect(page.locator("#helpOverlay")).not_to_be_visible()
