"""2C export options: pdf_standard / pages / ppi via server CLI.

CLI is faked (no typst binary needed): _fake records the argv so tests can
assert --pdf-standard/--pages/--ppi, then writes canned page files.
"""
from conftest import make_doc, register_user

from backend import mcp_tools as t

SEEN: list = []


class _FakeProc:
    def __init__(self, rc=0, err=b""):
        self.returncode = rc
        self.stderr = err
        self.stdout = b""


def _fake(cmd, **kw):
    from pathlib import Path

    SEEN.append(list(cmd))
    cwd = Path(kw.get("cwd", "."))
    fmt = cmd[cmd.index("--format") + 1]
    if fmt == "pdf":
        (cwd / "out.pdf").write_bytes(b"%PDF-1.7-fake")
    elif fmt == "svg":
        (cwd / "page-1.svg").write_bytes(b"<svg>fake</svg>")
    elif fmt == "png":
        (cwd / "page-1.png").write_bytes(b"\x89PNG-fake")
    return _FakeProc(0, b"")


def _patch(monkeypatch):
    import subprocess as _sp

    del SEEN[:]
    monkeypatch.setattr(_sp, "run", _fake)
    monkeypatch.setattr(t.shutil, "which", lambda *a, **k: "/usr/bin/typst")


def test_pdf_standard_passed_to_cli(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "Rpt", content="= Hi")
    _patch(monkeypatch)
    r = c.post(f"/api/docs/{did}/export", params={"format": "pdf", "pdf_standard": "a-2b"})
    assert r.status_code == 200, r.text
    assert "--pdf-standard" in SEEN[-1] and "a-2b" in SEEN[-1]


def test_pdf_standard_default_absent(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "Rpt", content="= Hi")
    _patch(monkeypatch)
    assert c.post(f"/api/docs/{did}/export", params={"format": "pdf"}).status_code == 200
    assert "--pdf-standard" not in SEEN[-1]


def test_pdf_standard_bad_400(c):
    register_user(c, "alice")
    did = make_doc(c, "Rpt", content="= Hi")
    assert c.post(f"/api/docs/{did}/export", params={"format": "pdf", "pdf_standard": "a-9z"}).status_code == 400
    assert c.post(f"/api/docs/{did}/export", params={"format": "svg", "pdf_standard": "a-2b"}).status_code == 400


def test_pages_passed_to_cli(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "Rpt", content="= Hi")
    _patch(monkeypatch)
    r = c.post(f"/api/docs/{did}/export", params={"format": "pdf", "pages": "1-2"})
    assert r.status_code == 200, r.text
    assert "--pages" in SEEN[-1] and "1-2" in SEEN[-1]


def test_pages_bad_400(c):
    register_user(c, "alice")
    did = make_doc(c, "Rpt", content="= Hi")
    assert c.post(f"/api/docs/{did}/export", params={"format": "pdf", "pages": "abc"}).status_code == 400
    assert c.post(f"/api/docs/{did}/export", params={"format": "pdf", "pages": "1--2"}).status_code == 400


def test_png_ppi_passed_to_cli(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "Rpt", content="= Hi")
    _patch(monkeypatch)
    r = c.post(f"/api/docs/{did}/export", params={"format": "png", "ppi": 300})
    assert r.status_code == 200, r.text
    assert "--ppi" in SEEN[-1] and "300" in SEEN[-1]


def test_png_ppi_bad_400(c):
    del SEEN[:]
    register_user(c, "alice")
    did = make_doc(c, "Rpt", content="= Hi")
    assert c.post(f"/api/docs/{did}/export", params={"format": "png", "ppi": 9999}).status_code == 400
    assert c.post(f"/api/docs/{did}/export", params={"format": "png", "ppi": 71}).status_code == 400
    assert c.post(f"/api/docs/{did}/export", params={"format": "png", "ppi": "abc"}).status_code == 400
    assert not SEEN, "400 must happen before any compile"


def test_png_ppi_bounds_ok(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "Rpt", content="= Hi")
    _patch(monkeypatch)
    assert c.post(f"/api/docs/{did}/export", params={"format": "png", "ppi": 72}).status_code == 200
    assert "--ppi" in SEEN[-1] and "72" in SEEN[-1]
    assert c.post(f"/api/docs/{did}/export", params={"format": "png", "ppi": 300}).status_code == 200


def test_option_format_mismatch_400(c):
    del SEEN[:]
    register_user(c, "alice")
    did = make_doc(c, "Rpt", content="= Hi")
    assert c.post(f"/api/docs/{did}/export", params={"format": "zip", "pdf_standard": "a-2b"}).status_code == 400
    assert c.post(f"/api/docs/{did}/export", params={"format": "zip", "pages": "1-2"}).status_code == 400
    assert c.post(f"/api/docs/{did}/export", params={"format": "pdf", "ppi": 300}).status_code == 400
    assert not SEEN, "400 must happen before any compile"


def test_pages_spaces_ok(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "Rpt", content="= Hi")
    _patch(monkeypatch)
    r = c.post(f"/api/docs/{did}/export", params={"format": "pdf", "pages": "1-2, 5"})
    assert r.status_code == 200, r.text
    assert "1-2,5" in SEEN[-1]


def test_pdf_standard_case_insensitive(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "Rpt", content="= Hi")
    _patch(monkeypatch)
    r = c.post(f"/api/docs/{did}/export", params={"format": "pdf", "pdf_standard": "A-2B"})
    assert r.status_code == 200, r.text
    assert "a-2b" in SEEN[-1]


def test_mcp_export_opts_parity(c, monkeypatch):
    """MCP op_export kennt dieselben Optionen + 400-Regeln wie REST."""
    import asyncio

    import pytest

    register_user(c, "alice")
    make_doc(c, "Rpt", content="= Hi")
    _patch(monkeypatch)
    out = asyncio.run(t.op_export("alice", "owner", "/docs/Rpt", "pdf", pdf_standard="a-2b"))
    assert out["mime"] == "application/pdf"
    assert "a-2b" in SEEN[-1]
    bad = [dict(pdf_standard="a-9z"), dict(format="svg", pdf_standard="a-2b"),
           dict(pages="abc"), dict(ppi=999), dict(format="pdf", ppi=300)]
    for kw in bad:
        with pytest.raises(Exception) as e:
            asyncio.run(t.op_export("alice", "owner", "/docs/Rpt", **kw))
        assert getattr(e.value, "status_code", 0) == 400, kw
