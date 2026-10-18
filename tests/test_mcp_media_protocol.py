"""MCP edit/upload/view/export over the real Streamable-HTTP protocol (isolated tmp DB).

Covers the remaining actual POST /mcp success paths (edit, upload, view,
export). Uses the real installed Typst binary for view/export success (no
subprocess mocks); reviewer may view/export but not edit/upload.
Never touches data-dev-projects or user docs: the `c` fixture isolates DB/files.
"""
import base64
import io
import json
import shutil
import zipfile

import pytest
from conftest import login, make_doc, register_user


def _sse(text):
    for line in text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise AssertionError(f"no SSE data payload in: {text[:600]!r}")


def _mcp(c, payload, headers=None, mid=None):
    h = {"Accept": "application/json, text/event-stream"}
    if headers:
        h.update(headers)
    r = c.post("/mcp", json=payload, headers=h)
    assert r.status_code == 200, r.text
    j = _sse(r.text)
    if mid is not None:
        assert j.get("id") == mid, j
    return j


def _bearer(key):
    return {"Authorization": f"Bearer {key}", "Accept": "application/json, text/event-stream"}


def _call(c, key, name, args, mid):
    j = _mcp(c, {"jsonrpc": "2.0", "id": mid, "method": "tools/call",
                 "params": {"name": name, "arguments": args}}, headers=_bearer(key), mid=mid)
    assert "result" in j, j
    return j["result"]


def _ok_struct(res):
    assert res.get("isError") is False, res
    assert "structuredContent" in res, res
    return res["structuredContent"]


def _err_text(res):
    assert res.get("isError") is True, res
    return res["content"][0]["text"]


def _keys(c, role="editor", name="k"):
    r = c.post("/api/keys", json={"name": name, "role": role})
    assert r.status_code == 200, r.text
    return r.json()["key"]


def _need_typst():
    if not shutil.which("typst"):
        pytest.skip("typst CLI missing")


def test_edit_via_mcp_http_success(c):
    register_user(c, "alice")
    key = _keys(c, "editor", "ed")
    login(c, "alice")
    make_doc(c, title="Med", content="hello world\nsecond line\n")
    res = _call(c, key, "edit",
                {"path": "/docs/Med", "old_string": "hello", "new_string": "HELLO"}, 11)
    sc = _ok_struct(res)
    assert sc["ok"] is True and sc["replaced"] == 1 and sc["stale"] is False, sc
    assert sc["last_seen"], sc
    got = _ok_struct(_call(c, key, "read", {"path": "/docs/Med"}, 12))
    assert got["content"] == "HELLO world\nsecond line\n", got


def test_upload_via_mcp_http_roundtrip(c):
    register_user(c, "alice")
    key = _keys(c, "editor", "ed")
    login(c, "alice")
    make_doc(c, title="Up", content="= Hi")
    raw = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    b64 = base64.b64encode(raw).decode()
    sc = _ok_struct(_call(c, key, "upload",
                          {"path": "/docs/Up/pic.png", "content_base64": b64}, 21))
    assert sc["name"] == "pic.png" and sc["size"] == len(raw), sc
    listed = _ok_struct(_call(c, key, "ls", {"path": "/docs/Up"}, 22))
    assert "pic.png" in [f["name"] for f in listed["files"]], listed
    # binary read hints at view/upload (proves the file landed as binary)
    err = _err_text(_call(c, key, "read", {"path": "/docs/Up/pic.png"}, 23))
    assert "400" in err and "view" in err.lower(), err


def test_view_via_mcp_http_real_typst(c):
    _need_typst()
    from backend import mcp_tools as t

    t._VIEW_CACHE.clear()
    t._VIEW_TOTALS.clear()
    try:
        register_user(c, "alice")
        key = _keys(c, "editor", "ed")
        login(c, "alice")
        make_doc(c, title="Vw", content="= Hello\nWorld")
        res = _call(c, key, "view", {"path": "/docs/Vw", "pages": "1"}, 31)
        assert res.get("isError") is False, res
        sc = res["structuredContent"]
        assert sc["count"] == 1 and sc["total_pages"] == 1, sc
        assert sc["cache_hit"] is False and sc["pages"] == "1", sc
        assert sc["scale"] == 1.0 and sc["last_seen"], sc
        kinds = [b.get("type") for b in res["content"]]
        assert kinds[0] == "text" and kinds[1] == "image", res["content"][:1]
        img = res["content"][1]
        assert img.get("mimeType") == "image/png", img
        png = base64.b64decode(img["data"])
        assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 100, png[:16]
    finally:
        t._VIEW_CACHE.clear()
        t._VIEW_TOTALS.clear()


def test_export_pdf_and_zip_via_mcp_http_real_typst(c):
    _need_typst()
    register_user(c, "alice")
    key = _keys(c, "editor", "ed")
    login(c, "alice")
    make_doc(c, title="Exp", content="= Hello\nWorld")
    _ok_struct(_call(c, key, "create",
                     {"path": "/docs/Exp/notes.csv", "content": "a,b"}, 41))
    pdf = _ok_struct(_call(c, key, "export",
                           {"path": "/docs/Exp", "format": "pdf"}, 42))
    assert pdf["mime"] == "application/pdf" and pdf["filename"] == "Exp.pdf", pdf
    payload = base64.b64decode(pdf["content_base64"])
    assert payload[:5] == b"%PDF-" and pdf["size_bytes"] == len(payload), payload[:16]
    zsc = _ok_struct(_call(c, key, "export",
                           {"path": "/docs/Exp", "format": "zip"}, 43))
    assert zsc["mime"] == "application/zip" and zsc["filename"] == "Exp.zip", zsc
    zbytes = base64.b64decode(zsc["content_base64"])
    assert zbytes[:2] == b"PK" and zsc["size_bytes"] == len(zbytes)
    z = zipfile.ZipFile(io.BytesIO(zbytes))
    assert z.read("main.typ").decode() == "= Hello\nWorld"
    assert z.read("notes.csv").decode() == "a,b"


def test_reviewer_may_view_export_but_not_edit_upload(c):
    _need_typst()
    from backend import mcp_tools as t

    t._VIEW_CACHE.clear()
    t._VIEW_TOTALS.clear()
    try:
        register_user(c, "alice")
        register_user(c, "bob")
        login(c, "alice")
        make_doc(c, title="Rvw", content="= Hello\nWorld")
        from backend import db as _db

        con = _db.connect()
        try:
            did = con.execute("SELECT id FROM docs WHERE owner=? AND title=?",
                              ("alice", "Rvw")).fetchone()["id"]
        finally:
            con.close()
        assert c.post(f"/api/docs/{did}/share",
                      json={"username": "bob", "role": "reviewer"}).status_code == 200
        login(c, "bob")
        bkey = _keys(c, "reviewer", "brev")
        vw = _call(c, bkey, "view", {"path": "/shared/alice/Rvw", "pages": "1"}, 51)
        assert vw.get("isError") is False, vw
        assert vw["structuredContent"]["count"] == 1, vw["structuredContent"]
        png = base64.b64decode(vw["content"][1]["data"])
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        ex = _ok_struct(_call(c, bkey, "export",
                              {"path": "/shared/alice/Rvw", "format": "zip"}, 52))
        assert ex["mime"] == "application/zip", ex
        zb = base64.b64decode(ex["content_base64"])
        assert zb[:2] == b"PK"
        assert zipfile.ZipFile(io.BytesIO(zb)).read("main.typ").decode() == "= Hello\nWorld"
        err = _err_text(_call(c, bkey, "edit",
                              {"path": "/shared/alice/Rvw",
                               "old_string": "Hello", "new_string": "X"}, 53))
        assert "403" in err and "Reviewer" in err, err
        raw = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10).decode()
        err2 = _err_text(_call(c, bkey, "upload",
                               {"path": "/shared/alice/Rvw/pic.png",
                                "content_base64": raw}, 54))
        assert "403" in err2 and "Reviewer" in err2, err2
    finally:
        t._VIEW_CACHE.clear()
        t._VIEW_TOTALS.clear()
