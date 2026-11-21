"""Per-doc export (W2-A): POST /api/docs/{id}/export + MCP export parity.

CLI is faked (no typst binary needed): _fake_run answers `typst compile`
by writing canned page files. One real-CLI test runs when typst exists
(dev server / Docker), otherwise skipped.
"""
import io
import shutil
import zipfile

import pytest
from conftest import login, make_doc, register_user

from backend import main as backend_main
from backend import render as t


class _FakeProc:
    def __init__(self, rc=0, err=b""):
        self.returncode = rc
        self.stderr = err
        self.stdout = b""


def _make_fake(pages=1, rc=0, err=b""):
    def _fake(cmd, **kw):
        from pathlib import Path

        cwd = Path(kw.get("cwd", "."))
        assert cmd[0] == "/usr/bin/typst"
        fmt = cmd[cmd.index("--format") + 1]
        if rc != 0:
            return _FakeProc(rc, err)
        if fmt == "pdf":
            (cwd / "out.pdf").write_bytes(b"%PDF-1.7-fake")
        elif fmt in ("svg", "png"):  # the output template of the command, as the real CLI writes it
            body = b"<svg>fake</svg>" if fmt == "svg" else b"\x89PNG-fake"
            for i in range(1, pages + 1):
                target = cwd / cmd[-1].replace("{p}", str(i))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(body)
        return _FakeProc(0, b"")

    return _fake


def _patch_typst(monkeypatch, pages=1, rc=0, err=b""):
    import subprocess as _sp

    monkeypatch.setattr(_sp, "run", _make_fake(pages, rc, err))
    monkeypatch.setattr(t.shutil, "which", lambda *a, **k: "/usr/bin/typst")


def test_export_doc_pdf(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "Rpt", content="= Hi")
    _patch_typst(monkeypatch)
    r = c.post(f"/api/docs/{did}/export", params={"format": "pdf"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/pdf")
    assert "Rpt.pdf" in r.headers.get("content-disposition", "")
    assert r.content == b"%PDF-1.7-fake"


def test_export_doc_svg_png_single(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "Rpt", content="= Hi")
    _patch_typst(monkeypatch)
    r = c.post(f"/api/docs/{did}/export", params={"format": "svg"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert r.content == b"<svg>fake</svg>"
    r = c.post(f"/api/docs/{did}/export", params={"format": "png"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("image/png")
    assert r.content == b"\x89PNG-fake"


def test_export_doc_png_multi_is_zip(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "Rpt", content="= Hi")
    _patch_typst(monkeypatch, pages=3)
    r = c.post(f"/api/docs/{did}/export", params={"format": "png"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/zip")
    assert "Rpt-png.zip" in r.headers.get("content-disposition", "")
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert names == ["page-1.png", "page-2.png", "page-3.png"]


def test_export_doc_svg_multi_is_zip(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "Rpt", content="= Hi")
    _patch_typst(monkeypatch, pages=2)
    r = c.post(f"/api/docs/{did}/export", params={"format": "svg"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/zip")
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert names == ["page-1.svg", "page-2.svg"]


def test_export_doc_zip_source_bundle(c):
    register_user(c, "alice")
    did = make_doc(c, "Rpt", content="= Hi")
    c.post(f"/api/docs/{did}/files", files={"f": ("notes.csv", b"a,b")})
    r = c.post(f"/api/docs/{did}/export", params={"format": "zip"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/zip")
    assert "Rpt.zip" in r.headers.get("content-disposition", "")
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert z.read("Rpt.typ").decode() == "= Hi"
    assert z.read("notes.csv").decode() == "a,b"


def test_export_doc_bad_format_400(c):
    register_user(c, "alice")
    did = make_doc(c, "Rpt", content="= Hi")
    assert c.post(f"/api/docs/{did}/export", params={"format": "docx"}).status_code == 400
    assert c.post(f"/api/docs/{did}/export", params={"format": ""}).status_code == 400


def test_export_doc_404(c):
    register_user(c, "alice")
    make_doc(c, "Rpt", content="= Hi")
    assert c.post("/api/docs/d_nope/export", params={"format": "zip"}).status_code == 404
    assert c.post("/api/docs/!!!/export", params={"format": "zip"}).status_code == 404


def test_export_doc_trashed_410(c):
    register_user(c, "alice")
    did = make_doc(c, "Rpt", content="= Hi")
    assert c.delete(f"/api/docs/{did}").status_code == 200
    assert c.post(f"/api/docs/{did}/export", params={"format": "zip"}).status_code == 410


def test_export_doc_reviewer_may_export(c):
    register_user(c, "alice")
    did = make_doc(c, "Plan", content="= Hi")
    register_user(c, "bob")
    login(c, "alice")
    assert c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "reviewer"}).status_code == 200
    login(c, "bob")
    r = c.post(f"/api/docs/{did}/export", params={"format": "zip"})
    assert r.status_code == 200, r.text
    assert zipfile.ZipFile(io.BytesIO(r.content)).read("Plan.typ").decode() == "= Hi"


def test_export_doc_lock_429(c):
    register_user(c, "alice")
    did = make_doc(c, "Rpt", content="= Hi")
    lock = backend_main._export_lock("alice")
    lock.acquire()
    try:
        r = c.post(f"/api/docs/{did}/export", params={"format": "zip"})
        assert r.status_code == 429
    finally:
        lock.release()
    assert c.post(f"/api/docs/{did}/export", params={"format": "zip"}).status_code == 200


def test_export_doc_ratelimit_429(c):
    register_user(c, "alice")
    did = make_doc(c, "Rpt", content="= Hi")
    for _ in range(10):
        assert c.post(f"/api/docs/{did}/export", params={"format": "zip"}).status_code == 200
    assert c.post(f"/api/docs/{did}/export", params={"format": "zip"}).status_code == 429


def test_export_doc_isolated_from_full_export(c):
    register_user(c, "alice")
    did = make_doc(c, "Rpt", content="= Hi")
    for _ in range(5):  # exhaust the full-backup export bucket
        assert c.get("/api/export.zip").status_code == 200
    assert c.get("/api/export.zip").status_code == 429
    assert c.post(f"/api/docs/{did}/export", params={"format": "zip"}).status_code == 200


def test_export_doc_compile_error_422(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "Bad", content="#unknown-fn()")
    _patch_typst(monkeypatch, rc=1, err=b"error: unknown function\n --> main.typ:2:5\n")
    r = c.post(f"/api/docs/{did}/export", params={"format": "pdf"})
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "compile error" in detail["message"]
    assert detail["diagnostics"] and detail["diagnostics"][0]["line"] == 2


def test_export_doc_typst_missing_500(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "Rpt", content="= Hi")
    monkeypatch.setattr(t.shutil, "which", lambda *a, **k: None)
    assert c.post(f"/api/docs/{did}/export", params={"format": "pdf"}).status_code == 500




def test_full_export_zip_unbroken(c):
    register_user(c, "alice")
    make_doc(c, "Backup", content="inhalt")
    r = c.get("/api/export.zip")
    assert r.status_code == 200
    assert r.content[:2] == b"PK"


def test_real_typst_pdf(c):
    if not shutil.which("typst"):
        pytest.skip("typst CLI missing")
    register_user(c, "alice")
    did = make_doc(c, "Real", content="= Hello\nWorld")
    r = c.post(f"/api/docs/{did}/export", params={"format": "pdf"})
    assert r.status_code == 200, r.text
    assert r.content[:5] == b"%PDF-"


def test_export_doc_oversize_413(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "Big", content="x" * 100)
    monkeypatch.setattr(t, "EXPORT_MAX", 10)
    assert c.post(f"/api/docs/{did}/export", params={"format": "zip"}).status_code == 413


def test_export_doc_skipped_txt(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "Rpt", content="= Hi")
    c.post(f"/api/docs/{did}/files", files={"f": ("notes.csv", b"a,b")})
    monkeypatch.setattr(t, "UPLOAD_MAX", 1)
    r = c.post(f"/api/docs/{did}/export", params={"format": "zip"})
    assert r.status_code == 200, r.text
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert z.read("Rpt.typ").decode() == "= Hi"
    assert "notes.csv" in z.read("SKIPPED.txt").decode()


def test_export_doc_default_and_case_format(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "Rpt", content="= Hi")
    _patch_typst(monkeypatch)
    assert c.post(f"/api/docs/{did}/export").headers["content-type"].startswith("application/pdf")
    for f in ("PDF", " pdf ", "Svg"):
        r = c.post(f"/api/docs/{did}/export", params={"format": f})
        assert r.status_code == 200, (f, r.text)


def test_export_doc_filename_sanitized(c):
    register_user(c, "alice")
    did = make_doc(c, "Rpt: Demo/1", content="= Hi")
    r = c.post(f"/api/docs/{did}/export", params={"format": "zip"})
    assert r.status_code == 200, r.text
    cd = r.headers.get("content-disposition", "")
    assert 'filename="Rpt_Demo_1.zip"' in cd
    assert "\n" not in cd and "\r" not in cd






def test_export_pages_keep_page_order_and_skip_uploaded_page_files(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "Rpt", content="= Hi")
    up = c.post(f"/api/docs/{did}/files", files={"f": ("page-1.svg", b"<svg>upload</svg>")})
    assert up.status_code == 200, up.text
    _patch_typst(monkeypatch, pages=11)
    r = c.post(f"/api/docs/{did}/export", params={"format": "svg"})
    assert r.status_code == 200, r.text
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert z.namelist() == [f"page-{i}.svg" for i in range(1, 12)]  # page-10 after page-9, not after page-1
    assert z.read("page-1.svg") == b"<svg>fake</svg>"  # the rendered page, never the uploaded file of that name
    _patch_typst(monkeypatch, pages=11)
    r = c.post(f"/api/docs/{did}/export", params={"format": "png"})
    assert r.status_code == 200, r.text
    assert zipfile.ZipFile(io.BytesIO(r.content)).namelist() == [f"page-{i}.png" for i in range(1, 12)]
