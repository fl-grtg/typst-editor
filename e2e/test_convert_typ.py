"""A .typ attachment converts to a module or a document from the sidebar menu; other files have no such entry."""
from helpers import register
from playwright.sync_api import expect


def _menu(page, key_prefix, text):
    row = page.locator(f'[data-package-key^="{key_prefix}"]', has_text=text).first
    row.hover()
    row.locator("button").last.click()


def test_convert_menu_for_typ_files(page, base_url):
    register(page, "e2e_convert")
    api = page.context.request
    pid = api.post(f"{base_url}/api/projects", data={"title": "Convert"}).json()["id"]
    did = api.post(f"{base_url}/api/projects/{pid}/docs", data={"title": "Main", "content": '#include "part.typ"'}).json()["id"]
    assert api.post(f"{base_url}/api/docs/{did}/files/part.typ/text", data={"content": "Part"}).ok
    assert api.post(f"{base_url}/api/docs/{did}/files", multipart={"f": {"name": "data.csv", "mimeType": "text/csv", "buffer": b"a,b"}}).ok
    page.reload()
    page.wait_for_function("window.__booted === true")
    _menu(page, "file:", "data.csv")
    expect(page.locator("#menu")).not_to_contain_text("Convert")
    page.keyboard.press("Escape")
    _menu(page, "file:", "part.typ")
    page.locator("#menu button", has_text="Convert to").hover()
    page.locator("button", has_text="Module").last.click()
    expect(page.locator('[data-package-key="resource::part.typ"]')).to_be_visible()
    _menu(page, "resource:", "part.typ")
    page.locator("#menu button", has_text="Convert to").hover()
    page.locator("button", has_text="Document").last.click()
    expect(page.locator("#mCard")).to_contain_text("Main")  # Main still includes it
    page.click("#mYes")
    expect(page.locator("#title")).to_have_text("part")


def test_document_and_module_have_one_click_conversions(page, base_url):
    register(page, "e2e_convert2")
    api = page.context.request
    pid = api.post(f"{base_url}/api/projects", data={"title": "Convert2"}).json()["id"]
    api.post(f"{base_url}/api/projects/{pid}/docs", data={"title": "Style", "content": "#let x = 1"})
    assert api.post(f"{base_url}/api/projects/{pid}/resources", data={"name": "lib.typ", "content": "#let y = 2"}).ok
    page.reload()
    page.wait_for_function("window.__booted === true")
    _menu(page, "document:", "Style")
    page.locator("#menu button", has_text="Convert to module").click()
    expect(page.locator('[data-package-key="resource::Style.typ"]')).to_be_visible()
    _menu(page, "resource:", "lib.typ")
    menu = page.locator("#menu")
    expect(menu.locator("button", has_text="Convert to document")).to_have_count(1)
    menu.locator("button", has_text="Convert to document").click()
    expect(page.locator("#title")).to_have_text("lib")
