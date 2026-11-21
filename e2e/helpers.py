"""Shared selectors/flows for the browser smoke tests (ids come from web/index.shell.html)."""
from playwright.sync_api import Page, expect
from playwright.sync_api import TimeoutError as PwTimeout


def _goto_home(page: Page) -> None:
    # Ein Retry nur bei Navigation-Timeout: CI-Runner stallsen gelegentlich
    # beim Kaltaufbau frischer Kontexte (15s), lokal + App-seitig unauffällig.
    try:
        page.goto("/")
    except PwTimeout:
        page.goto("/")
    page.wait_for_function("window.__booted === true")


def register(page: Page, name: str, pw: str = "pass1234pass") -> None:
    _goto_home(page)
    page.click("#mode")  # switch "Sign in" -> "Sign up"
    page.fill("#u", name)
    page.fill("#p", pw)
    page.click("#go")
    expect(page.locator("#app")).to_be_visible()


def login(page: Page, name: str, pw: str = "pass1234pass") -> None:
    _goto_home(page)
    page.fill("#u", name)
    page.fill("#p", pw)
    page.click("#go")
    expect(page.locator("#app")).to_be_visible()


def create_doc(page: Page, title: str = "New document") -> None:
    page.click("#new")
    page.locator("#menu button").first.click()  # "Project" entry of the + menu
    expect(page.locator("#mHead")).to_have_text("New project")
    page.fill("#mInp", title)
    page.click("#mYes")
    expect(page.locator("#title")).to_have_text(title)
    expect(page.locator("#cm .cm-content")).to_be_visible()


def type_source(page: Page, text: str) -> None:
    page.click("#cm .cm-content")
    page.keyboard.press("ControlOrMeta+A")
    # Keyboard.type drops single keys when the CI runner is loaded; execCommand
    # replaces the selection through the same CodeMirror input path as typing.
    assert page.evaluate("(t) => document.execCommand('insertText', false, t)", text)


def put_source(page: Page, text: str) -> None:
    """Replace the whole source in one edit once the live connection stands.

    Typing hundreds of characters one by one races the first server sync of a
    freshly opened document on a busy runner: a remote update can land between
    two keystrokes and one of them vanishes ("=Omega", "#pgebreak()"). The
    fixtures of the sync tests are measured against the exact source, so they
    insert it atomically.
    """
    try:  # the dot says "Live" once the websocket is up; never fail on a different label
        expect(page.locator("#wsTxt")).to_contain_text("Live", timeout=15_000)
    except AssertionError:
        pass
    page.click("#cm .cm-content")
    page.keyboard.press("ControlOrMeta+A")
    assert page.evaluate("(t) => document.execCommand('insertText', false, t)", text)


def open_private_copy(page: Page, name: str) -> None:
    source = page.locator('#cm .cm-content').inner_text()
    response = page.request.post('/api/templates', data={'name': name, 'content': source})
    assert response.ok, response.text()
    row = page.locator('#tpls .doc').filter(has_text=name)
    expect(row).to_have_count(1)
    if not row.is_visible():
        page.locator('#tplH').press('Enter')
    row.locator('.t').click()
    expect(page.locator('#title')).to_have_text(name)
