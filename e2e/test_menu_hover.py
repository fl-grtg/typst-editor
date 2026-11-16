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
    _assert_subtle(page, menu.locator("button").filter(has_text="Rename"), hover, text)
    page.keyboard.press("Escape")

    for name in ("file", "edit", "view", "help"):
        page.locator(f"#menubar [data-menu={name}]").click()
        expect(menu).to_be_visible()
        _assert_subtle(page, menu.locator("button:not(:disabled)").first, hover, text)
        page.keyboard.press("Escape")

    page.locator("#exportBtn").click()
    expect(menu).to_be_visible()
    _assert_subtle(page, menu.locator("button:not(:disabled)").first, hover, text)


def test_hovering_another_item_closes_the_submenu_immediately(page):
    register(page, "e2e_submenu_close")
    create_doc(page, "Submenu close")
    row = page.locator("#own .doc").filter(has=page.locator(".t", has_text="Submenu close")).first
    row.hover()
    row.locator("button[data-side-menu]").click()
    menu = page.locator("#menu")
    expect(menu).to_be_visible()
    menu.locator("button").filter(has_text="Copy to").hover()
    expect(page.locator("#submenu")).to_be_visible()

    hidden = page.evaluate(
        """() => {
            const trash = [...document.querySelectorAll('#menu button')]
                .find(b => b.textContent.includes('Move to trash'))
            trash.dispatchEvent(new PointerEvent('pointerenter', { pointerType: 'mouse' }))
            return document.querySelector('#submenu').hidden
        }"""
    )
    assert hidden  # no 400 ms leftover panel over the rows below


def test_module_type_menu_explains_each_type_on_hover(page):
    register(page, "e2e_type_hints")
    head = page.locator("#tplH")
    head.hover()
    head.locator("button.mini").click()
    menu = page.locator("#menu")
    expect(menu).to_be_visible()
    buttons = menu.locator("button")
    assert buttons.count() == 10
    for i in range(buttons.count()):
        assert buttons.nth(i).get_attribute("title")
    typst = buttons.filter(has_text="Typst").first
    assert typst.get_attribute("title") == "Chapter or module, pulled in with #include"
    csv = buttons.filter(has_text="CSV").first
    assert csv.get_attribute("title") == "Table edited in the cell editor"


def test_row_actions_stay_visible_but_not_tinted_while_a_menu_is_open(page):
    register(page, "e2e_row_actions")
    create_doc(page, "Row actions")
    row = page.locator("aside .fhd.project").filter(has=page.locator("b", has_text="Row actions")).first
    row.hover()
    row.locator("button[data-side-menu]").click()
    menu = page.locator("#menu")
    expect(menu).to_be_visible()

    box = menu.bounding_box()
    assert box
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 20)  # the pointer leaves the row
    response = page.request.post("/api/docs/create", data={"title": "Row actions refresh", "content": ""})
    assert response.ok, response.text()
    expect(page.locator("#own .doc .t", has_text="Row actions refresh")).to_be_visible()  # the refresh replaced the row under the menu
    page.wait_for_timeout(200)  # background transition is .12s

    hover = _token(page, "--hover")
    buttons = row.locator("button.mini")
    assert buttons.count() >= 2
    active = row.locator('button[data-side-menu][aria-expanded="true"]')
    for i in range(buttons.count()):
        expect(buttons.nth(i)).to_be_visible()  # all row actions stay visible
    assert active.evaluate("el => getComputedStyle(el).backgroundColor") == hover["bg"]  # only the open one keeps the tint
    for i in range(buttons.count()):
        button = buttons.nth(i)
        if button.get_attribute("data-side-menu") is not None:
            continue
        assert button.evaluate("el => getComputedStyle(el).backgroundColor") == "rgba(0, 0, 0, 0)"
