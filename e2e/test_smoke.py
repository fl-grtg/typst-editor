"""Six core browser paths (Wave 0C safety net for the frontend split)."""
import struct
import zlib

from helpers import create_doc, login, register, type_source
from playwright.sync_api import expect

PREVIEW_TIMEOUT = 60_000  # first compile downloads the WASM compiler


def _png_1x1() -> bytes:
    def chunk(t: bytes, d: bytes) -> bytes:
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


def test_1_register_and_login(page):
    register(page, "e2e_alice")
    page.context.clear_cookies()  # drop the session, then sign in again
    login(page, "e2e_alice")


def test_2_create_doc_and_type(page):
    register(page, "e2e_bob")
    create_doc(page, "Smoke doc")
    type_source(page, "= Hello\n\nWorld")
    expect(page.locator("#cm .cm-content")).to_contain_text("World")


def test_3_preview_renders(page):
    register(page, "e2e_carol")
    create_doc(page, "Preview doc")
    type_source(page, "= Preview\n\nSome text")
    expect(page.locator("#preview canvas").first).to_be_visible(timeout=PREVIEW_TIMEOUT)


def test_4_two_browsers_see_same_edit(browser, base_url, ctx, page):
    register(page, "e2e_dave")
    create_doc(page, "Collab doc")
    type_source(page, "shared text from A")
    ctx2 = browser.new_context(base_url=base_url)
    ctx2.set_default_timeout(15_000)
    try:
        p2 = ctx2.new_page()
        login(p2, "e2e_dave")
        p2.locator("#own .doc", has_text="Collab doc").first.click()
        expect(p2.locator("#cm .cm-content")).to_contain_text("shared text from A")
        type_source(p2, "edited in B")
        expect(page.locator("#cm .cm-content")).to_contain_text("edited in B")
    finally:
        ctx2.close()


def test_5_upload_file_and_include(page):
    register(page, "e2e_erin")
    create_doc(page, "Image doc")
    docs = page.request.get("/api/docs").json()["own"]
    doc_id = next(d["id"] for d in docs if d["title"] == "Image doc")
    r = page.request.post(
        f"/api/docs/{doc_id}/files",
        multipart={"f": {"name": "pixel.png", "mimeType": "image/png", "buffer": _png_1x1()}},
    )
    assert r.ok, r.text()
    type_source(page, '#image("pixel.png", width: 2cm)')
    expect(page.locator("#preview canvas").first).to_be_visible(timeout=PREVIEW_TIMEOUT)


def test_6_export_typ_downloads(page):
    register(page, "e2e_frank")
    create_doc(page, "Export doc")
    type_source(page, "= Export me")
    page.click("#exportBtn")
    with page.expect_download() as dl:
        page.locator("#menu").get_by_text("Download as .typ").click()
    assert dl.value.suggested_filename.endswith(".typ")
