"""MCP Phase 6 (M1-M4): keys/bearer, resolver/tools, edit guards, view cache."""
import asyncio
import json
import re

import pytest
from conftest import login, make_doc, register_user
from fastapi import HTTPException

from backend import db, sync
from backend import mcp_tools as t

KEY_RE = re.compile(r"^tpe_[0-9a-f]{8}_[0-9a-f]{32}$")


def make_key(c, role="editor", expires=None, name="agent"):
    body = {"name": name, "role": role}
    if expires is not None:
        body["expires_in_days"] = expires
    r = c.post("/api/keys", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_keys_bearer_ok_and_rejected(c):
    register_user(c, "u1")
    created = make_key(c, role="editor")
    assert KEY_RE.fullmatch(created["key"])
    assert created["prefix"] in created["key"]
    # bearer ok
    r = c.get("/api/keys", headers={"Authorization": f"Bearer {created['key']}"})
    assert r.status_code == 200, r.text
    assert r.json()["keys"][0]["prefix"] == created["prefix"]
    assert all("key" not in k for k in r.json()["keys"])  # secret shown once only
    # hash only in db
    con = db.connect()
    try:
        row = con.execute("SELECT key_hash, prefix FROM api_keys WHERE id=?",
                          (created["id"],)).fetchone()
        assert row["key_hash"] != created["key"] and len(row["key_hash"]) == 64
        assert row["prefix"] == created["prefix"]
    finally:
        con.close()
    # rejected: garbage, no auth
    assert c.get("/api/keys", headers={"Authorization": "Bearer tpe_deadbeef_deadbeefdeadbeefdeadbeef"}).status_code == 401
    c.post("/api/logout")
    assert c.get("/api/keys").status_code == 401


def test_keys_revoke_and_expiry(c):
    register_user(c, "u1")
    created = make_key(c)
    hdr = {"Authorization": f"Bearer {created['key']}"}
    assert c.get("/api/keys", headers=hdr).status_code == 200
    assert c.delete(f"/api/keys/{created['id']}", headers=hdr).status_code == 200
    assert c.get("/api/keys", headers=hdr).status_code == 401  # revoked
    assert c.get("/api/keys").json()["keys"] == []  # gone from list
    # expired
    created2 = make_key(c, name="short")
    con = db.connect()
    try:
        con.execute("UPDATE api_keys SET expires_at=? WHERE id=?", ("2000-01-01T00:00:00", created2["id"]))
        con.commit()
    finally:
        con.close()
    assert c.get("/api/keys", headers={"Authorization": f"Bearer {created2['key']}"}).status_code == 401


def test_keys_role_containment(c):
    register_user(c, "u1")
    k = make_key(c, role="reviewer")
    hdr = {"Authorization": f"Bearer {k['key']}"}
    r = c.post("/api/keys", json={"name": "esc", "role": "editor"}, headers=hdr)
    assert r.status_code == 403  # reviewer key cannot mint editor keys
    r = c.post("/api/keys", json={"name": "ok", "role": "reviewer"}, headers=hdr)
    assert r.status_code == 200


def test_edit_reviewer_403_on_shared(c):
    register_user(c, "alice")
    did = make_doc(c, title="Plan", content="line1\nline2\n")
    # share with bob (register first)
    register_user(c, "bob")
    login(c, "alice")
    r = c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "reviewer"})
    assert r.status_code == 200, r.text
    login(c, "bob")
    bk = make_key(c, role="reviewer", name="bobkey")
    assert bk["role"] == "reviewer"
    with pytest.raises(HTTPException) as e:
        asyncio.run(t.op_edit("bob", "reviewer", "/shared/alice/Plan", "line1", "LINE1"))
    assert e.value.status_code == 403
    # reviewer may still comment, shown under the key name
    out = t.op_comment("bob", "reviewer", "/shared/alice/Plan", 1, "looks good", author="bobkey")
    assert out["id"]
    con = db.connect()
    try:
        got = con.execute("SELECT username, author FROM comments WHERE id=?", (out["id"],)).fetchone()
    finally:
        con.close()
    assert (got["username"], got["author"]) == ("bob", "bobkey")  # auth on account, display key name
    # owner with reviewer key is capped too (min rule)
    login(c, "alice")
    ak = make_key(c, role="reviewer", name="akey")
    assert ak["role"] == "reviewer"
    with pytest.raises(HTTPException) as e:
        asyncio.run(t.op_edit("alice", "reviewer", "/docs/Plan", "line1", "LINE1"))
    assert e.value.status_code == 403


def test_create_400_on_exists_and_paths(c):
    register_user(c, "u1")
    t.op_create("u1", "owner", "/docs/Plan", "hello")
    with pytest.raises(HTTPException) as e:
        t.op_create("u1", "owner", "/docs/plan", "again")  # NOCASE
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        t.op_create("u1", "owner", "/docs/a/b/title", "x")
    assert e.value.status_code == 400  # title with / rejected
    with pytest.raises(HTTPException) as e:
        t.op_read("u1", "owner", "/nope/X")
    assert e.value.status_code == 400


def test_edit_404_missing_and_guards(c):
    register_user(c, "u1")
    with pytest.raises(HTTPException) as e:
        asyncio.run(t.op_edit("u1", "owner", "/docs/Gone", "a", "b"))
    assert e.value.status_code == 404
    t.op_create("u1", "owner", "/docs/G", "aaa\nbbb\naaa\n")
    with pytest.raises(HTTPException) as e:
        asyncio.run(t.op_edit("u1", "owner", "/docs/G", "zzz", "Z"))
    assert e.value.status_code == 409 and "anchor-gone" in e.value.detail
    with pytest.raises(HTTPException) as e:
        asyncio.run(t.op_edit("u1", "owner", "/docs/G", "aaa", "A"))
    assert e.value.status_code == 409 and "anchor-ambiguous" in e.value.detail
    with pytest.raises(HTTPException) as e:
        asyncio.run(t.op_edit("u1", "owner", "/docs/G", "", "A"))
    assert e.value.status_code == 400  # old_string required


def test_edit_replace_all_and_last_seen(c):
    register_user(c, "u1")
    t.op_create("u1", "owner", "/docs/G", "aaa\nbbb\naaa\n")
    r = t.op_read("u1", "owner", "/docs/G")
    out = asyncio.run(t.op_edit("u1", "owner", "/docs/G", "aaa", "A", replace_all=True,
                                last_seen=r["last_seen"]))
    assert out == {"ok": True, "replaced": 2, "last_seen": out["last_seen"], "stale": False}
    r2 = t.op_read("u1", "owner", "/docs/G")
    assert r2["content"] == "A\nbbb\nA\n"
    # distant foreign edit: no false alarm on stale last_seen when anchor is clean
    asyncio.run(t.op_edit("u1", "owner", "/docs/G", "bbb", "B"))
    out2 = asyncio.run(t.op_edit("u1", "owner", "/docs/G", "B\n", "Bx\n",
                                 last_seen=r["last_seen"]))  # stale marker, clean anchor
    assert out2["ok"] is True and out2["stale"] is True
    assert t.op_read("u1", "owner", "/docs/G")["content"] == "A\nBx\nA\n"


def test_edit_snapshot_before_overwrite(c):
    register_user(c, "u1")
    t.op_create("u1", "owner", "/docs/S", "v1 content")
    asyncio.run(t.op_edit("u1", "owner", "/docs/S", "v1", "v2"))
    con = db.connect()
    try:
        rows = con.execute("SELECT content, label FROM snapshots").fetchall()
    finally:
        con.close()
    assert any(r["content"] == "v1 content" for r in rows)


def test_edit_live_room_propagation(c):
    register_user(c, "u1")
    t.op_create("u1", "owner", "/docs/L", "old text here")
    con = db.connect()
    try:
        did = con.execute("SELECT id FROM docs WHERE owner='u1' AND title='L'").fetchone()["id"]
    finally:
        con.close()
    sync.room(did)  # open live room
    assert sync.room_text(did) == "old text here"
    asyncio.run(t.op_edit("u1", "owner", "/docs/L", "old text", "new text"))
    assert sync.room_text(did) == "new text here"


def test_view_cache_hit(c, monkeypatch):
    register_user(c, "u1")
    t.op_create("u1", "owner", "/docs/V", "= Hi\nhello")
    calls = []

    def fake(main_text, files, pages, ppi=144):
        calls.append((main_text, pages, ppi))
        return [b"png-bytes-1", b"png-bytes-2"]

    monkeypatch.setattr(t, "_compile_pngs", fake)
    monkeypatch.setattr(t, "_compile_pdf_pages", lambda *a, **k: 7)
    t._VIEW_CACHE.clear()
    t._VIEW_TOTALS.clear()
    v1 = asyncio.run(t.op_view("u1", "owner", "/docs/V"))
    v2 = asyncio.run(t.op_view("u1", "owner", "/docs/V"))
    assert v1.structured_content["count"] == 2
    assert v1.structured_content["total_pages"] == 7
    assert v1.structured_content["cache_hit"] is False
    assert v2.structured_content["cache_hit"] is True
    assert v2.structured_content["total_pages"] == 7
    assert {"count", "total_pages", "cache_hit", "last_seen"} <= set(v1.structured_content)
    assert len(v1.content) == 3 and v1.content[0].type == "text"
    assert all(getattr(b, "type", None) == "image" for b in v1.content[1:])
    assert all(getattr(b, "mime_type", None) == "image/png" for b in v1.content[1:])
    assert [b.data for b in v1.content[1:]] == [b.data for b in v2.content[1:]]
    assert len(calls) == 1  # second call served from content-hash cache
    t._VIEW_CACHE.clear()
    t._VIEW_TOTALS.clear()


def test_read_binary_hint_and_upload_roundtrip(c):
    register_user(c, "u1")
    t.op_create("u1", "owner", "/docs/B", "doc")
    import base64
    png = base64.b64encode(b"\x89PNG" + b"\0" * 100).decode()
    out = t.op_upload("u1", "owner", "/docs/B/pic.png", png)
    assert out["name"] == "pic.png"
    with pytest.raises(HTTPException) as e:
        t.op_read("u1", "owner", "/docs/B/pic.png")
    assert e.value.status_code == 400 and "view" in e.value.detail and "upload" in e.value.detail


def test_read_paging_window_and_errors(c):
    register_user(c, "u1")
    t.op_create("u1", "owner", "/docs/P", "l1\nl2\nl3\nl4\nl5")
    full = t.op_read("u1", "owner", "/docs/P")
    assert full["content"] == "l1\nl2\nl3\nl4\nl5"
    assert full["total_lines"] == 5
    assert full["offset"] == 1
    win = t.op_read("u1", "owner", "/docs/P", offset=2, limit=2)
    assert win["content"] == "l2\nl3"
    assert win["offset"] == 2
    assert win["total_lines"] == 5
    past = t.op_read("u1", "owner", "/docs/P", offset=99)
    assert past["content"] == ""
    assert past["total_lines"] == 5
    t.op_create("u1", "owner", "/docs/P/f.csv", "a\nb\nc")
    assert t.op_read("u1", "owner", "/docs/P/f.csv", offset=3)["content"] == "c"
    t.op_create("u1", "owner", "/templates/p.typ", "x\ny")
    assert t.op_read("u1", "owner", "/templates/p.typ", limit=1)["content"] == "x"
    assert t.op_read("u1", "owner", "/docs/P", limit=0)["total_lines"] == 5
    for bad in ({"offset": 0}, {"limit": -1}, {"offset": "2"}, {"limit": True}):
        with pytest.raises(HTTPException) as e:
            t.op_read("u1", "owner", "/docs/P", **bad)
        assert e.value.status_code == 400


def test_keys_survive_rename(c):
    register_user(c, "u1")
    created = make_key(c, name="keep")
    hdr = {"Authorization": f"Bearer {created['key']}"}
    r = c.post("/api/me/name", json={"name": "u1new", "password": "pass1234"})
    assert r.status_code == 200, r.text
    assert c.get("/api/keys", headers=hdr).status_code == 200  # username migrated, not cascade-deleted


def test_title_with_encoded_slash_400(c):
    register_user(c, "u1")
    with pytest.raises(HTTPException) as e:
        t.op_read("u1", "owner", "/docs/a%2Fb")
    assert e.value.status_code == 400


def test_template_reviewer_key(c):
    register_user(c, "u1")
    t.op_create("u1", "owner", "/templates/x.typ", "hello")
    assert t.op_read("u1", "reviewer", "/templates/x.typ")["content"] == "hello"
    with pytest.raises(HTTPException) as e:
        asyncio.run(t.op_edit("u1", "reviewer", "/templates/x.typ", "hello", "bye"))
    assert e.value.status_code == 403


def test_comment_author_fallback_and_key_owner_manage(c):
    register_user(c, "u1")
    did = make_doc(c, title="C", content="text")
    assert t.op_comment("u1", "owner", "/docs/C", 0, "a", author="")["id"]
    assert t.op_comment("u1", "owner", "/docs/C", 0, "b", author="   ")["id"]
    con = db.connect()
    try:
        rows = con.execute("SELECT username, author FROM comments").fetchall()
    finally:
        con.close()
    assert [(r["username"], r["author"]) for r in rows] == [("u1", ""), ("u1", "")]
    make_key(c, name="k1")
    cid = t.op_comment("u1", "owner", "/docs/C", 0, "via key", author="k1")["id"]
    # key owner manages own key-named comment through the human UI routes
    assert c.post(f"/api/docs/{did}/comments/{cid}/edit", json={"text": "via key!"}).status_code == 200
    assert c.delete(f"/api/docs/{did}/comments/{cid}").status_code == 200


def test_view_pages_validation(c):
    register_user(c, "u1")
    t.op_create("u1", "owner", "/docs/VP", "= Hi")
    for bad in ("5-1", "0", "", "0-5", "1-21", "21", "a", "1-5,",
                "1-2-3", "1-6,7-22"):
        with pytest.raises(HTTPException) as e:
            asyncio.run(t.op_view("u1", "owner", "/docs/VP", pages=bad))
        assert e.value.status_code == 400
    # valid ranges stay 400-free at validation time (compile is mocked below)
    assert t._pages_ok("1-5") and t._pages_ok("6-10") and t._pages_ok("1-20")
    assert t._pages_ok("2") and t._pages_ok("1-3,5")
    assert t._expand_pages("6-10") == list(range(6, 11))
    assert t._expand_pages("1-3,5") == [1, 2, 3, 5]


def test_key_name_required(c):
    register_user(c, "u1")
    assert c.post("/api/keys", json={"name": ""}).status_code == 400


def test_key_name_unique(c):
    register_user(c, "u1")
    assert c.post("/api/keys", json={"name": "dup"}).status_code == 200
    r = c.post("/api/keys", json={"name": "dup"})
    assert r.status_code == 400 and "already used" in r.text
    assert c.post("/api/keys", json={"name": "DUP"}).status_code == 400  # NOCASE
    assert c.post("/api/keys", json={"name": "other"}).status_code == 200


def test_mcp_throttle(c):
    register_user(c, "u1")
    key = make_key(c, name="throttle")["key"]
    hdr = {"Authorization": f"Bearer {key}", "Accept": "application/json, text/event-stream"}
    last = None
    for i in range(61):
        r = c.post("/mcp", json={"jsonrpc": "2.0", "id": i, "method": "tools/call",
                                 "params": {"name": "ls", "arguments": {}}}, headers=hdr)
        assert r.status_code == 200
        for line in r.text.splitlines():
            if line.startswith("data: "):
                last = json.loads(line[6:])
    assert last["result"]["isError"] is True and "429" in last["result"]["content"][0]["text"]


def test_delete_me_clears_key_author(c):
    register_user(c, "alice")
    did = make_doc(c, title="C", content="text")
    register_user(c, "u1")
    login(c, "alice")
    assert c.post(f"/api/docs/{did}/share", json={"username": "u1", "role": "reviewer"}).status_code == 200
    login(c, "u1")
    make_key(c, name="k1")
    cid = t.op_comment("u1", "reviewer", "/shared/alice/C", 0, "via key", author="k1")["id"]
    assert c.post("/api/me/delete", json={"password": "pass1234"}).status_code == 200
    con = db.connect()
    try:
        got = con.execute("SELECT username, author FROM comments WHERE id=?", (cid,)).fetchone()
    finally:
        con.close()
    assert (got["username"], got["author"]) == ("[deleted]", "")


def test_ls_search_comment_basics(c):
    register_user(c, "u1")
    t.op_create("u1", "owner", "/docs/Plan", "launch the rocket soon")
    root = t.op_ls("u1", "owner", "/")
    assert [d["title"] for d in root["docs"]] == ["Tutorial", "Plan"] or "Plan" in [d["title"] for d in root["docs"]]
    hits = t.op_search("u1", "owner", "rocket")
    assert hits["hits"] and hits["hits"][0]["path"] == "/docs/Plan"
    assert t.op_search("u1", "owner", "x")["hits"] == []
    cid = t.op_comment("u1", "owner", "/docs/Plan", 0, "nit: fuel")
    assert cid["id"]
    con = db.connect()
    try:
        assert con.execute("SELECT username FROM comments WHERE id=?", (cid["id"],)).fetchone()["username"] == "u1"
    finally:
        con.close()


def test_comment_anchor_zero_clamped_to_one(c):
    register_user(c, "u1")
    t.op_create("u1", "owner", "/docs/Plan", "line1\nline2\n")
    cid = t.op_comment("u1", "owner", "/docs/Plan", 0, "top")["id"]
    con = db.connect()
    try:
        assert con.execute("SELECT anchor FROM comments WHERE id=?", (cid,)).fetchone()["anchor"] == 1
    finally:
        con.close()


def test_migrate_v11_heals_anchor_zero(c):
    register_user(c, "u1")
    t.op_create("u1", "owner", "/docs/Plan", "line1\nline2\n")
    cid = t.op_comment("u1", "owner", "/docs/Plan", 1, "top")["id"]
    con = db.connect()
    try:
        con.execute("UPDATE comments SET anchor=0 WHERE id=?", (cid,))
        con.commit()
        db._migrate_v11(con)
        con.commit()
        assert con.execute("SELECT anchor FROM comments WHERE id=?", (cid,)).fetchone()["anchor"] == 1
    finally:
        con.close()


def test_search_parity_files_bib_live(c):
    import base64

    from backend import sync as _sync

    register_user(c, "u1")
    t.op_create("u1", "owner", "/docs/Parity", "persistierter Inhalt ohne Treffer")
    con = db.connect()
    try:
        did = con.execute("SELECT id FROM docs WHERE owner='u1' AND title='Parity'").fetchone()["id"]
    finally:
        con.close()
    png = base64.b64encode(b"binary-data").decode()
    t.op_upload("u1", "owner", "/docs/Parity/anhang-notizen.pdf", png)
    bib = base64.b64encode(b"@article{Paritaet2024schluessel, author={M}}").decode()
    t.op_upload("u1", "owner", "/docs/Parity/refs.bib", bib)
    by_file = t.op_search("u1", "owner", "anhang-notizen")
    assert by_file["hits"] and by_file["hits"][0]["path"] == "/docs/Parity"
    by_key = t.op_search("u1", "owner", "paritaet2024schluessel")
    assert by_key["hits"] and by_key["hits"][0]["path"] == "/docs/Parity"
    assert t.op_search("u1", "owner", "x")["hits"] == []
    room = _sync.room(did)
    from pycrdt import Text as _Text
    with room["doc"].transaction():
        room["doc"].get("typst", type=_Text).__iadd__(" mcp-live-sonderwort")
    room["dirty"] = True
    live = t.op_search("u1", "owner", "mcp-live-sonderwort")
    assert live["hits"] and live["hits"][0]["path"] == "/docs/Parity"


def test_view_paging_ranges_and_scale(c, monkeypatch):
    register_user(c, "u1")
    t.op_create("u1", "owner", "/docs/W", "= Hi")
    seen = {}

    def fake(main_text, files, pages, ppi=144):
        seen["pages"] = pages
        seen["ppi"] = ppi
        n = len([p for p in pages.split(",") if p.strip()])
        return [f"png-{i}".encode() for i in range(n)]

    monkeypatch.setattr(t, "_compile_pngs", fake)
    monkeypatch.setattr(t, "_compile_pdf_pages", lambda *a, **k: 20)
    t._VIEW_CACHE.clear()
    t._VIEW_TOTALS.clear()
    v = asyncio.run(t.op_view("u1", "owner", "/docs/W", pages="6-10"))
    assert v.structured_content["count"] == 5
    assert v.structured_content["total_pages"] == 20
    assert v.structured_content["pages"] == "6,7,8,9,10"
    assert seen["ppi"] == 144  # default scale 1.0
    t._VIEW_CACHE.clear()
    t._VIEW_TOTALS.clear()
    v2 = asyncio.run(t.op_view("u1", "owner", "/docs/W", pages="1-20"))
    assert v2.structured_content["count"] == 20
    assert v2.structured_content["total_pages"] == 20
    # scale maps to ppi
    t._VIEW_CACHE.clear()
    t._VIEW_TOTALS.clear()
    asyncio.run(t.op_view("u1", "owner", "/docs/W", pages="1-2", scale=2.0))
    assert seen["ppi"] == 288
    for bad_scale in (0.1, 5.0, "x", True):
        with pytest.raises(HTTPException) as e:
            asyncio.run(t.op_view("u1", "owner", "/docs/W", pages="1-2", scale=bad_scale))
        assert e.value.status_code == 400
    t._VIEW_CACHE.clear()
    t._VIEW_TOTALS.clear()


def test_view_default_compatible(c, monkeypatch):
    register_user(c, "u1")
    t.op_create("u1", "owner", "/docs/D", "= Hi")
    got = {}

    def fake(main_text, files, pages, ppi=144):
        got["pages"] = pages
        got["ppi"] = ppi
        return [b"one"]

    monkeypatch.setattr(t, "_compile_pngs", fake)
    monkeypatch.setattr(t, "_compile_pdf_pages", lambda *a, **k: 3)
    t._VIEW_CACHE.clear()
    t._VIEW_TOTALS.clear()
    v = asyncio.run(t.op_view("u1", "owner", "/docs/D"))
    assert got == {"pages": "1,2,3,4,5", "ppi": 144}
    assert v.structured_content["count"] == 1
    assert v.structured_content["total_pages"] == 3
    assert v.structured_content["last_seen"]
    t._VIEW_CACHE.clear()
    t._VIEW_TOTALS.clear()


def test_view_compile_diagnostics_422(c, monkeypatch):
    import subprocess as _sp

    register_user(c, "u1")
    t.op_create("u1", "owner", "/docs/E", "= Hi #unknown-fn()")

    class _P:
        returncode = 1
        stderr = b"error: unknown function\n --> main.typ:2:5\n |\n"

    monkeypatch.setattr(_sp, "run", lambda *a, **k: _P())
    monkeypatch.setattr(t.shutil, "which", lambda *a, **k: "/usr/bin/typst")
    t._VIEW_CACHE.clear()
    t._VIEW_TOTALS.clear()
    with pytest.raises(HTTPException) as e:
        asyncio.run(t.op_view("u1", "owner", "/docs/E", pages="1-2"))
    assert e.value.status_code == 422
    detail = e.value.detail
    assert isinstance(detail, dict) and "diagnostics" in detail
    assert detail["diagnostics"] and detail["diagnostics"][0]["line"] == 2
    assert "compile error" in detail["message"]
    # unit-level parser fallback without position
    diags = t._parse_typst_diagnostics("error: something broke")
    assert diags[0]["line"] is None and "something broke" in diags[0]["message"]
    t._VIEW_CACHE.clear()
    t._VIEW_TOTALS.clear()


def test_view_typst_missing_500(c, monkeypatch):
    register_user(c, "u1")
    t.op_create("u1", "owner", "/docs/M", "= Hi")
    monkeypatch.setattr(t.shutil, "which", lambda *a, **k: None)
    t._VIEW_CACHE.clear()
    t._VIEW_TOTALS.clear()
    with pytest.raises(HTTPException) as e:
        asyncio.run(t.op_view("u1", "owner", "/docs/M"))
    assert e.value.status_code == 500 and "typst" in e.value.detail.lower()
    t._VIEW_CACHE.clear()
    t._VIEW_TOTALS.clear()


def test_search_20_cap(c):
    register_user(c, "u1")
    for i in range(25):
        t.op_create("u1", "owner", f"/docs/Cap{i:02d}", "capkeyword same body")
    out = t.op_search("u1", "owner", "capkeyword")
    assert len(out["hits"]) == 20


def test_pdf_page_count_parser():
    pdf = (b"%PDF-1.7\n1 0 obj<</Type /Pages /Count 3>>endobj\n"
           b"2 0 obj<</Type /Page /Parent 1 0 R>>endobj\n"
           b"3 0 obj<</Type /Page /Parent 1 0 R>>endobj\n")
    assert t._pdf_page_count(pdf) == 2
    assert t._pdf_page_count(b"not a pdf") is None
    # /Pages must not count, trailing /Page at buffer end must count
    assert t._pdf_page_count(b"<</Type /Pages>>") is None
    assert t._pdf_page_count(b"<</Type /Page>>") == 1


def test_view_scale_edges_and_pages_guard(c, monkeypatch):
    register_user(c, "u1")
    t.op_create("u1", "owner", "/docs/SE", "= Hi")
    monkeypatch.setattr(t, "_compile_pngs", lambda *a, **k: [b"x"])
    monkeypatch.setattr(t, "_compile_pdf_pages", lambda *a, **k: 4)
    t._VIEW_CACHE.clear()
    t._VIEW_TOTALS.clear()
    for ok in (0.5, 1.0, 3.0):
        t._VIEW_CACHE.clear()
        t._VIEW_TOTALS.clear()
        v = asyncio.run(t.op_view("u1", "owner", "/docs/SE", pages="1-2", scale=ok))
        assert v.structured_content["scale"] == ok
    with pytest.raises(HTTPException) as e:
        asyncio.run(t.op_view("u1", "owner", "/docs/SE", pages="1," * 100 + "2"))
    assert e.value.status_code == 400
    t._VIEW_CACHE.clear()
    t._VIEW_TOTALS.clear()


def test_view_totals_cache_no_poison(c, monkeypatch):
    register_user(c, "u1")
    t.op_create("u1", "owner", "/docs/TP", "= Hi")
    monkeypatch.setattr(t, "_compile_pngs", lambda *a, **k: [b"x"])
    calls = {"n": 0}

    def _pdf_fail(*a, **k):
        calls["n"] += 1
        return None

    monkeypatch.setattr(t, "_compile_pdf_pages", _pdf_fail)
    t._VIEW_CACHE.clear()
    t._VIEW_TOTALS.clear()
    v1 = asyncio.run(t.op_view("u1", "owner", "/docs/TP", pages="1-5"))
    assert v1.structured_content["total_pages"] == 5  # fallback, not cached
    assert t._VIEW_TOTALS == {}
    monkeypatch.setattr(t, "_compile_pdf_pages", lambda *a, **k: 12)
    t._VIEW_CACHE.clear()
    v2 = asyncio.run(t.op_view("u1", "owner", "/docs/TP", pages="6-10"))
    assert v2.structured_content["total_pages"] == 12
    t._VIEW_CACHE.clear()
    t._VIEW_TOTALS.clear()
