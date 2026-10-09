"""Shared selectors/flows for the browser smoke tests (ids come from web/index.shell.html)."""
from playwright.sync_api import Page, expect


def register(page: Page, name: str, pw: str = "pass1234pass") -> None:
    page.goto("/")
    page.click("#mode")  # switch "Sign in" -> "Sign up"
    page.fill("#u", name)
    page.fill("#p", pw)
    page.click("#go")
    expect(page.locator("#app")).to_be_visible()


def login(page: Page, name: str, pw: str = "pass1234pass") -> None:
    page.goto("/")
    page.fill("#u", name)
    page.fill("#p", pw)
    page.click("#go")
    expect(page.locator("#app")).to_be_visible()


def create_doc(page: Page, title: str = "New document") -> None:
    page.click("#new")
    page.locator("#modal button.pk").first.click()  # card 0 = "Document"
    expect(page.locator("#mHead")).to_have_text("New document")
    page.fill("#mInp", title)
    page.click("#mYes")
    expect(page.locator("#title")).to_have_text(title)
    expect(page.locator("#cm .cm-content")).to_be_visible()


def type_source(page: Page, text: str) -> None:
    page.click("#cm .cm-content")
    page.keyboard.press("ControlOrMeta+A")
    page.keyboard.type(text)
