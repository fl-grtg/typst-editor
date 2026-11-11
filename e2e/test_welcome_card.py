"""Welcome card language, view mode, and create-link regressions."""
from playwright.sync_api import expect


def test_welcome_card_updates_language_view_and_create_link(page):
    page.goto("/")
    page.wait_for_function("window.__booted === true")
    response = page.request.post(
        "/api/register",
        data={"username": "e2e_welcome", "password": "pass1234pass", "invite": ""},
    )
    assert response.ok, response.text()
    page.reload()
    page.wait_for_function("window.__booted === true")

    card = page.locator("#emptyCard")
    expect(card).to_be_visible()
    expect(card.locator("h2")).to_have_text("Welcome back, e2e_welcome!")

    page.click("#who")
    settings = page.locator("#setPop")
    if not settings.is_visible():
        page.click("#who")
    expect(settings).to_be_visible()
    language = settings.locator("#langSel")

    language.select_option("de")
    expect(card.locator("h2")).to_have_text("Willkommen zurück, e2e_welcome!")
    expect(card.locator("p.sub").first).to_have_text("Gerade ist kein Dokument geöffnet.")
    expect(card.locator(".step").nth(0).locator(".createLink")).to_have_text("erstelle ein neues")
    expect(card.locator(".step").nth(1)).to_contain_text("Schreibe links und sieh rechts sofort die Vorschau.")
    expect(card.locator(".step").nth(2)).to_contain_text("Arbeite gleichzeitig mit anderen oder exportiere als PDF.")

    language.select_option("en")
    expect(card.locator("h2")).to_have_text("Welcome back, e2e_welcome!")
    expect(card.locator("p.sub").first).to_have_text("No document is open right now.")
    expect(card.locator(".step").nth(0).locator(".createLink")).to_have_text("create a new one")
    expect(card.locator(".step").nth(2)).to_contain_text("Work with others at the same time or export as PDF.")

    page.locator("#vEdit").evaluate("button => button.click()")
    expect(card.locator(".step").nth(1)).to_contain_text("Write your document in the editor.")
    page.locator("#vRead").evaluate("button => button.click()")
    expect(card.locator(".step").nth(1)).to_contain_text("View your document in the preview.")
    page.locator("#vSplit").evaluate("button => button.click()")
    expect(card.locator(".step").nth(1)).to_contain_text("Write on the left and see the preview update on the right.")

    card.locator(".createLink").click()
    expect(page.locator("#modal")).to_be_visible()
    expect(page.locator("#mHead")).to_have_text("New document")
