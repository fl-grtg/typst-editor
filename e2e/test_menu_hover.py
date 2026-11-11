"""Menu hover uses the shared subtle tint, not a solid ink fill."""
from helpers import create_doc, register, type_source
from playwright.sync_api import expect


def _token(page, name):
    return page.evaluate(
        """(name) => {
            const d = document.createElement('div')
            d.style.backgroundColor = `var(${name})`
            d.style.color = `var(${name})`
            document.body.appendChild(d)
            const cs = getComputedStyle(d)
            const out = { bg: cs.backgroundColor, color: cs.color }
            d.remove()
            return out
        }""",
        name,
    )


def _hover_style(page, item):
    item.hover()
    page.wait_for_timeout(250)  # background transition is .12s
    return item.evaluate(
        "el => { const cs = getComputedStyle(el); return { bg: cs.backgroundColor, color: cs.color } }"
    )


def _assert_subtle(page, item, hover, text):
    assert _hover_style(page, item) == hover | {"color": text["color"]}


def test_menu_hover_uses_subtle_tint(page):
    register(page, "e2e_menu_hover")
    create_doc(page, "Menu hover")
    type_source(page, "Hello")
    page.wait_for_function("!document.querySelector('#dlTyp').disabled")

    hover = _token(page, "--hover")
    text = _token(page, "--text")

    row = page.locator("#own .doc").filter(has=page.locator(".t", has_text="Menu hover")).first
    row.hover()
    row.locator("button[data-side-menu]").click()
    menu = page.locator("#menu")
    expect(menu).to_be_visible()
    _assert_subtle(page, menu.locator("button").filter(has_text="Rename document"), hover, text)
    page.keyboard.press("Escape")

    for name in ("file", "edit", "view", "help"):
        page.locator(f"#menubar [data-menu={name}]").click()
        expect(menu).to_be_visible()
        _assert_subtle(page, menu.locator("button:not(:disabled)").first, hover, text)
        page.keyboard.press("Escape")

    page.locator("#exportBtn").click()
    expect(menu).to_be_visible()
    _assert_subtle(page, menu.locator("button:not(:disabled)").first, hover, text)
