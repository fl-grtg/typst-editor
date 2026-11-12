"""API key role is editable in place; the secret survives the switch."""
from helpers import register
from playwright.sync_api import expect


def _open_api_settings(page):
    register(page, "e2e_key_role")
    page.click("#who")
    pop = page.locator("#setPop")
    expect(pop).to_be_visible()
    pop.locator('.setNavItem[data-category="api"]').click()
    expect(pop.locator(".keyCreateRow")).to_be_visible()
    page.wait_for_timeout(600)  # key/session fetches re-render the settings view once
    return pop


def test_api_key_role_switch_in_place(page, base_url):
    pop = _open_api_settings(page)
    row = pop.locator(".keyCreateRow")
    row.locator("input").fill("e2e-role")
    row.locator("select").nth(0).select_option("reviewer")
    row.locator("button").click()
    overlay = page.locator("#keySecret")
    expect(overlay).to_be_visible()
    secret = overlay.locator(".keySecretValue").input_value()
    overlay.locator(".keySecretClose").click()
    expect(overlay).to_have_count(0)
    role = pop.locator(".keyRoleSel")
    expect(role).to_have_value("reviewer")
    with page.expect_response(lambda r: r.request.method == "PATCH" and "/api/keys/" in r.url) as resp:
        role.select_option("editor")
    assert resp.value.ok
    expect(role).to_have_value("editor")
    assert page.locator("#keySecret").count() == 0  # no reissue: no new secret overlay
    # the original secret is still valid and now carries the stored role
    keys = page.context.request.get(f"{base_url}/api/keys",
                                   headers={"Authorization": f"Bearer {secret}"})
    assert keys.ok
    assert next(k for k in keys.json()["keys"] if k["name"] == "e2e-role")["role"] == "editor"
