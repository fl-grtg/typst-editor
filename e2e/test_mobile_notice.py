"""Phone-only mobile warning: phones see it, tablets and desktops never do."""
import pytest
from playwright.sync_api import expect

IPHONE_SAFARI = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                 "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
IPHONE_CHROME = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                 "AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/120.0.6099.119 Mobile/15E148 Safari/604.1")
PIXEL_CHROME = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")
ANDROID_FIREFOX = "Mozilla/5.0 (Android 13; Mobile; rv:121.0) Gecko/121.0 Firefox/121.0"
SAMSUNG_INTERNET = ("Mozilla/5.0 (Linux; Android 13; SM-S918B) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/23.0 Chrome/115.0.0.0 Mobile Safari/537.36")

IPAD_SAFARI = ("Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) "
               "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
IPAD_DESKTOP = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15")
ANDROID_TABLET = ("Mozilla/5.0 (Linux; Android 14; SM-X710) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
KINDLE_FIRE = ("Mozilla/5.0 (Linux; U; Android 9; en-us; KFONWI Build/PS7326.2979N) "
               "AppleWebKit/537.36 (KHTML, like Gecko) Silk/112.4.1 like Chrome/112.0.5615.213 Safari/537.36")
MACBOOK_SAFARI = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15")
WINDOWS_LAPTOP = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
WINDOWS_TOUCH_LAPTOP = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; Touch) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
LINUX_DESKTOP = "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0"
CHROMEBOOK = ("Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# label, user agent, viewport, touch, max touch points
PHONES = [
    ("iphone-safari", IPHONE_SAFARI, (390, 844), True, 5),
    ("iphone-chrome", IPHONE_CHROME, (390, 844), True, 5),
    ("pixel-chrome", PIXEL_CHROME, (412, 915), True, 5),
    ("android-firefox", ANDROID_FIREFOX, (412, 915), True, 5),
    ("samsung-internet", SAMSUNG_INTERNET, (360, 780), True, 5),
    ("iphone-landscape", IPHONE_SAFARI, (844, 390), True, 5),
]
NON_PHONES = [
    ("ipad-safari", IPAD_SAFARI, (820, 1180), True, 5),
    ("ipados-desktop-mode", IPAD_DESKTOP, (1024, 1366), True, 5),
    ("android-tablet", ANDROID_TABLET, (800, 1280), True, 5),
    ("kindle-fire", KINDLE_FIRE, (800, 1280), True, 5),
    ("macbook-safari", MACBOOK_SAFARI, (1512, 982), False, 0),
    ("windows-laptop", WINDOWS_LAPTOP, (1440, 900), False, 0),
    ("windows-touch-laptop", WINDOWS_TOUCH_LAPTOP, (1440, 900), True, 10),
    ("linux-desktop", LINUX_DESKTOP, (1440, 900), False, 0),
    ("chromebook", CHROMEBOOK, (1366, 768), True, 10),
]


def _open(browser, base_url, user_agent, viewport, has_touch, max_touch):
    context = browser.new_context(base_url=base_url, user_agent=user_agent, locale="en-US",
                                  viewport={"width": viewport[0], "height": viewport[1]},
                                  has_touch=has_touch)
    page = context.new_page()
    page.add_init_script(
        f"Object.defineProperty(navigator, 'maxTouchPoints', {{ get: () => {max_touch} }})")
    page.goto("/")
    page.wait_for_function("window.__booted === true")
    return context, page


@pytest.mark.parametrize("label,user_agent,viewport,touch,max_touch", PHONES, ids=[p[0] for p in PHONES])
def test_phones_get_the_warning(browser, base_url, label, user_agent, viewport, touch, max_touch):
    context, page = _open(browser, base_url, user_agent, viewport, touch, max_touch)
    try:
        expect(page.locator("#mobileWarn")).to_be_visible()
        expect(page.locator("#mwHead")).to_have_text("This editor isn't built for phones")
        expect(page.locator("#mwBody")).to_have_text(
            "A mobile version is planned. Until then, it works best on a desktop.")
    finally:
        context.close()


@pytest.mark.parametrize("label,user_agent,viewport,touch,max_touch", NON_PHONES, ids=[p[0] for p in NON_PHONES])
def test_tablets_and_desktops_get_no_warning(browser, base_url, label, user_agent, viewport, touch, max_touch):
    context, page = _open(browser, base_url, user_agent, viewport, touch, max_touch)
    try:
        expect(page.locator("#mobileWarn")).to_be_hidden()
        expect(page.locator("#login")).to_be_visible()
    finally:
        context.close()


def test_warning_is_dismissed_or_saved_in_local_storage(browser, base_url):
    context, page = _open(browser, base_url, IPHONE_SAFARI, (390, 844), True, 5)
    try:
        notice = page.locator("#mobileWarn")
        expect(notice).to_be_visible()
        page.wait_for_function("document.activeElement && document.activeElement.id === 'mwCard'")
        assert page.evaluate("getComputedStyle(document.getElementById('mwCard')).outlineStyle") == "none"

        page.click("#mwProceed")
        expect(notice).to_be_hidden()
        assert page.evaluate("localStorage.getItem('typst_mobile_warn')") is None
        page.reload()
        page.wait_for_function("window.__booted === true")
        expect(notice).to_be_visible()  # plain continue is this visit only

        page.click("#mwNever")
        expect(notice).to_be_hidden()
        assert page.evaluate("localStorage.getItem('typst_mobile_warn')") == "0"
        page.reload()
        page.wait_for_function("window.__booted === true")
        expect(notice).to_be_hidden()  # remembered in this browser
        expect(page.locator("#login")).to_be_visible()
    finally:
        context.close()
