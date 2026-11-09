"""Per-document scroll memory: editor + preview spots survive doc switches and reloads."""
from helpers import create_doc, login, register
from playwright.sync_api import expect

PREVIEW_TIMEOUT = 60_000


def _open_doc(page, title):
    row = page.locator('#own .doc').filter(has_text=title).locator('.t')
    expect(row).to_be_visible(timeout=15_000)
    row.click()
    expect(page.locator('#title')).to_have_text(title)


def test_editor_and_preview_scroll_survive_switch_and_reload(page):
    register(page, 'e2e_scroll_memory')
    create_doc(page, 'Scroll memory A')
    source = '\n\n#pagebreak()\n\n'.join(f'= Section {i}\n\nSome body text for section {i}.' for i in range(1, 31))
    page.click('#cm .cm-content')
    page.keyboard.press('ControlOrMeta+A')
    assert page.evaluate("(t) => document.execCommand('insertText', false, t)", source)
    expect(page.locator('#preview .pvPage[data-done]').first).to_be_visible(timeout=PREVIEW_TIMEOUT)
    page.click('#syncBtn')  # follow off: the saved preview spot must win on reopen

    page.locator('#cm .cm-scroller').evaluate('el => el.scrollTo(0, 1400)')
    page.locator('#preview').evaluate('el => el.scrollTo(0, 1800)')
    page.wait_for_timeout(600)  # scroll debounce
    editor_before = page.locator('#cm .cm-scroller').evaluate('el => el.scrollTop')
    preview_before = page.locator('#preview').evaluate('el => el.scrollTop')
    assert editor_before > 1000 and preview_before > 1000

    create_doc(page, 'Scroll memory B')
    expect(page.locator('#title')).to_have_text('Scroll memory B')
    _open_doc(page, 'Scroll memory A')
    expect(page.locator('#preview .pvPage').first).to_be_visible(timeout=PREVIEW_TIMEOUT)
    page.wait_for_timeout(600)  # restore runs after the first render
    editor_after = page.locator('#cm .cm-scroller').evaluate('el => el.scrollTop')
    preview_after = page.locator('#preview').evaluate('el => el.scrollTop')
    assert abs(editor_after - editor_before) < 80, f'editor scroll lost: {editor_before} -> {editor_after}'
    assert abs(preview_after - preview_before) < 120, f'preview scroll lost: {preview_before} -> {preview_after}'

    page.reload()
    page.wait_for_function('window.__booted === true')
    _open_doc(page, 'Scroll memory A')
    expect(page.locator('#preview .pvPage').first).to_be_visible(timeout=PREVIEW_TIMEOUT)
    page.wait_for_timeout(600)
    editor_reload = page.locator('#cm .cm-scroller').evaluate('el => el.scrollTop')
    preview_reload = page.locator('#preview').evaluate('el => el.scrollTop')
    assert abs(editor_reload - editor_before) < 80, f'editor scroll lost on reload: {editor_before} -> {editor_reload}'
    assert abs(preview_reload - preview_before) < 120, f'preview scroll lost on reload: {preview_before} -> {preview_reload}'


def test_scroll_memory_is_local_to_this_device(browser, base_url):
    first = browser.new_context(base_url=base_url, locale='en-US')
    first.set_default_timeout(15_000)
    page = first.new_page()
    register(page, 'e2e_scroll_devices')
    create_doc(page, 'Device scroll')
    page.click('#cm .cm-content')
    page.keyboard.press('ControlOrMeta+A')
    assert page.evaluate("(t) => document.execCommand('insertText', false, t)", '\n\n#pagebreak()\n\n'.join(f'= Section {i}\n\nBody {i}.' for i in range(1, 21)))
    expect(page.locator('#preview .pvPage[data-done]').first).to_be_visible(timeout=PREVIEW_TIMEOUT)
    page.locator('#cm .cm-scroller').evaluate('el => el.scrollTo(0, 900)')
    page.locator('#preview').evaluate('el => el.scrollTo(0, 1200)')
    page.wait_for_timeout(600)

    second = browser.new_context(base_url=base_url, locale='en-US')
    second.set_default_timeout(15_000)
    other = second.new_page()
    login(other, 'e2e_scroll_devices')
    _open_doc(other, 'Device scroll')
    expect(other.locator('#cm .cm-content')).to_contain_text('Section 20')
    expect(other.locator('#preview .pvPage[data-done]').first).to_be_visible(timeout=PREVIEW_TIMEOUT)
    other.wait_for_timeout(600)
    assert other.locator('#cm .cm-scroller').evaluate('el => el.scrollTop') < 40
    assert other.locator('#preview').evaluate('el => el.scrollTop') < 40
    first.close()
    second.close()
