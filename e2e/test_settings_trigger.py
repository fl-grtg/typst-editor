"""Settings trigger hit area: the whole user box opens the dialog, not only the name."""
from helpers import register
from playwright.sync_api import expect


def test_settings_open_across_the_full_user_box(page):
    register(page, "e2e_settings_area")
    expect(page.locator("#cm .cm-content")).to_be_visible()
    main = page.locator("#userMain")
    pop = page.locator("#setPop")
    box, who_box, dot_box = main.bounding_box(), page.locator("#who").bounding_box(), page.locator("#meDot").bounding_box()
    assert box and who_box and dot_box
    points = [
        (dot_box["x"] + dot_box["width"] / 2, dot_box["y"] + dot_box["height"] / 2),  # avatar
        (who_box["x"] + who_box["width"] / 2, who_box["y"] + who_box["height"] / 2),  # name + "Settings"
        (who_box["x"] + who_box["width"] + 4, box["y"] + box["height"] / 2),  # empty area right of the name
        (box["x"] + 3, box["y"] + box["height"] / 2),  # left padding
    ]
    for x, y in points:
        page.mouse.click(x, y)
        if not pop.is_visible():  # async openDoc hidePops() won the race: toggle back open
            page.mouse.click(x, y)
        expect(pop).to_be_visible()
        expect(main).to_have_attribute("aria-expanded", "true")
        page.mouse.click(x, y)
        expect(pop).not_to_be_visible()
        expect(main).to_have_attribute("aria-expanded", "false")


def test_collapsed_rail_avatar_opens_settings(page):
    register(page, "e2e_settings_rail")
    expect(page.locator("#cm .cm-content")).to_be_visible()
    page.click("#navToggle")
    expect(page.locator("#railAv")).to_be_visible()
    page.click("#railAv")
    expect(page.locator("#setPop")).to_be_visible()
    page.click("#railAv")
    expect(page.locator("#setPop")).not_to_be_visible()
