"""MCP suggest/suggestions over the real Streamable-HTTP protocol (isolated tmp DB).

Uses TestClient POST /mcp JSON-RPC (initialize / tools/list / tools/call) with
Bearer API keys, plus REST accept/reject and sync.room_text for Yjs checks.
Never touches data-dev-projects or user docs: the `c` fixture isolates DB/files.
"""
import json

from conftest import login, make_doc, register_user

from backend import db, sync


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


def _db_content(doc_id):
    con = db.connect()
    try:
        return con.execute("SELECT content FROM docs WHERE id=?", (doc_id,)).fetchone()["content"]
    finally:
        con.close()


def test_initialize_and_tools_list_includes_suggest(c):
    register_user(c, "alice")
    key = _keys(c, "editor", "ed")
    j = _mcp(c, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                            "clientInfo": {"name": "t", "version": "1"}}},
              headers=_bearer(key), mid=1)
    assert j["result"]["serverInfo"]["name"] == "typst-editor", j
    assert "protocolVersion" in j["result"], j
    j2 = _mcp(c, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
              headers=_bearer(key), mid=2)
    names = {t["name"] for t in j2["result"]["tools"]}
    for want in ("ls", "read", "create", "edit", "search", "upload", "comment",
                 "suggest", "suggestions", "view", "export"):
        assert want in names, names
    sug = next(t for t in j2["result"]["tools"] if t["name"] == "suggest")
    assert set(sug["inputSchema"]["required"]) >= {"path", "old_string", "new_string"}, sug


def test_bearer_auth_required_and_no_cookie_fallback(c):
    register_user(c, "alice")
    key = _keys(c, "editor", "ed")
    # no bearer at all
    j = _mcp(c, {"jsonrpc": "2.0", "id": 11, "method": "tools/call",
                 "params": {"name": "ls", "arguments": {}}}, mid=11)
    assert j["result"]["isError"] is True
    assert "401" in j["result"]["content"][0]["text"] and "Bearer" in j["result"]["content"][0]["text"]
    # garbage key
    j = _mcp(c, {"jsonrpc": "2.0", "id": 12, "method": "tools/call",
                 "params": {"name": "ls", "arguments": {}}},
              headers={"Authorization": "Bearer tpe_deadbeef_deadbeefdeadbeefdeadbeef",
                       "Accept": "application/json, text/event-stream"}, mid=12)
    assert j["result"]["isError"] is True and "401" in j["result"]["content"][0]["text"], j
    # session cookie alone must NOT auth /mcp (bearer-only, no ambient auth)
    login(c, "alice")  # sets cookie
    j = _mcp(c, {"jsonrpc": "2.0", "id": 13, "method": "tools/call",
                 "params": {"name": "ls", "arguments": {}}}, mid=13)
    assert j["result"]["isError"] is True and "401" in j["result"]["content"][0]["text"], j
    # valid key works
    res = _call(c, key, "ls", {}, 14)
    assert res["isError"] is False, res
    # unknown tool is a protocol-level isError, still HTTP 200
    res = _call(c, key, "nope", {}, 15)
    assert res["isError"] is True, res


def test_reviewer_suggest_without_edit_and_attribution(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, title="Proto", content="hello world\nsecond line\n")
    assert c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "reviewer"}).status_code == 200
    login(c, "bob")
    bkey = _keys(c, "reviewer", "brev")
    before = _db_content(did)
    # reviewer suggests on the shared path via real MCP HTTP
    res = _call(c, bkey, "suggest",
                {"path": "/shared/alice/Proto", "old_string": "hello", "new_string": "HELLO",
                 "text": "caps"}, 21)
    sc = _ok_struct(res)
    assert sc["status"] == "pending" and sc["anchor"] == 1 and sc["id"], sc
    # suggesting never edits: DB + live room unchanged
    assert _db_content(did) == before
    assert (sync.room_text(did) or before) == before or sync.room_text(did) is None
    # attribution: account stays bob, display author is the key name
    con = db.connect()
    try:
        row = con.execute("SELECT username, author, suggestion_status FROM comments WHERE id=?",
                          (sc["id"],)).fetchone()
    finally:
        con.close()
    assert (row["username"], row["author"], row["suggestion_status"]) == ("bob", "brev", "pending")
    # reviewer edit via MCP is still forbidden
    err = _err_text(_call(c, bkey, "edit",
                          {"path": "/shared/alice/Proto", "old_string": "hello", "new_string": "X"}, 22))
    assert "403" in err and "Reviewer" in err, err
    # reviewer can list suggestions via MCP
    lst = _ok_struct(_call(c, bkey, "suggestions", {"path": "/shared/alice/Proto"}, 23))
    assert [s["id"] for s in lst["suggestions"]] == [sc["id"]]
    assert lst["suggestions"][0]["status"] == "pending"


def test_suggestions_list_status_fields(c):
    register_user(c, "alice")
    key = _keys(c, "editor", "ed")
    login(c, "alice")
    did = make_doc(c, title="L1", content="alpha beta\ngamma\n")
    res = _call(c, key, "suggest",
                {"path": "/docs/L1", "old_string": "beta", "new_string": "BETA", "text": "why"}, 31)
    sid = _ok_struct(res)["id"]
    lst = _ok_struct(_call(c, key, "suggestions", {"path": "/docs/L1"}, 32))
    assert len(lst["suggestions"]) == 1
    s = lst["suggestions"][0]
    assert (s["id"], s["quote"], s["text"], s["status"]) == (sid, "beta", "why", "pending"), s
    assert {"author", "anchor", "created_at"} <= set(s), s
    # UI-equivalent projection: internal account and full anchor/replacement
    # history stay behind the UI surface.
    assert "username" not in s and "old_string" not in s and "new_string" not in s
    assert lst["total"] == 1
    assert s["anchor"] == 1  # first line
    # suggestions on a non-document path is 400 (still HTTP 200 envelope)
    err = _err_text(_call(c, key, "suggestions", {"path": "/"}, 33))
    assert "400" in err, err
    # accept then list shows accepted
    assert c.post(f"/api/docs/{did}/suggestions/{sid}/accept").status_code == 200
    lst2 = _ok_struct(_call(c, key, "suggestions", {"path": "/docs/L1"}, 34))
    assert lst2["suggestions"][0]["status"] == "accepted", lst2


def test_suggestions_list_capped_with_total(c, monkeypatch):
    from backend import mcp_tools

    register_user(c, "alice")
    key = _keys(c, "editor", "ced")
    login(c, "alice")
    make_doc(c, title="C1", content="w1 w2 w3 w4\n")
    sids = []
    for i, (old, new) in enumerate((("w1", "W1"), ("w2", "W2"), ("w3", "W3"))):
        sids.append(_ok_struct(_call(c, key, "suggest",
                                     {"path": "/docs/C1", "old_string": old, "new_string": new}, 61 + i))["id"])
    monkeypatch.setattr(mcp_tools, "SUGGESTIONS_LIST_CAP", 2)
    lst = _ok_struct(_call(c, key, "suggestions", {"path": "/docs/C1"}, 64))
    assert lst["total"] == 3, lst
    # the 2 LATEST entries, chronological order
    assert [s["id"] for s in lst["suggestions"]] == sids[1:], lst


def test_accept_via_rest_updates_db_and_yjs(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, title="A1", content="hello world\nsecond line\n")
    assert c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "reviewer"}).status_code == 200
    login(c, "bob")
    bkey = _keys(c, "reviewer", "brev")
    sid = _ok_struct(_call(c, bkey, "suggest",
                           {"path": "/shared/alice/A1", "old_string": "hello",
                            "new_string": "HELLO"}, 41))["id"]
    # reviewer cannot accept via REST
    login(c, "bob")
    r = c.post(f"/api/docs/{did}/suggestions/{sid}/accept")
    assert r.status_code == 403, r.text
    # owner accepts via REST
    login(c, "alice")
    assert c.post(f"/api/docs/{did}/suggestions/{sid}/accept").status_code == 200
    assert _db_content(did) == "HELLO world\nsecond line\n"
    assert sync.room_text(did) == "HELLO world\nsecond line\n"
    # MCP read reflects the accepted text, live flag may be true
    login(c, "alice")
    akey = _keys(c, "editor", "aed")
    got = _ok_struct(_call(c, akey, "read", {"path": "/docs/A1"}, 42))
    assert got["content"] == "HELLO world\nsecond line\n", got


def test_editor_share_can_accept_and_reject(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, title="E1", content="one two three\n")
    assert c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "editor"}).status_code == 200
    login(c, "bob")
    bkey = _keys(c, "editor", "bed")
    # deletion proposal (empty replacement) via MCP
    sid = _ok_struct(_call(c, bkey, "suggest",
                           {"path": "/shared/alice/E1", "old_string": " two", "new_string": ""}, 51))["id"]
    # editor share accepts via REST
    login(c, "bob")
    assert c.post(f"/api/docs/{did}/suggestions/{sid}/accept").status_code == 200
    assert _db_content(did) == "one three\n"
    assert sync.room_text(did) == "one three\n"
    # second suggestion rejected by the editor share
    login(c, "alice")
    akey = _keys(c, "editor", "aed")
    sid2 = _ok_struct(_call(c, akey, "suggest",
                            {"path": "/docs/E1", "old_string": "one", "new_string": "ONE"}, 52))["id"]
    login(c, "bob")
    r = c.post(f"/api/docs/{did}/suggestions/{sid2}/reject")
    assert r.status_code == 200, r.text
    assert _db_content(did) == "one three\n"  # reject never edits
    lst = _ok_struct(_call(c, bkey, "suggestions", {"path": "/shared/alice/E1"}, 53))
    by_id = {s["id"]: s["status"] for s in lst["suggestions"]}
    assert by_id == {sid: "accepted", sid2: "rejected"}, by_id


def test_unicode_suggest_accept(c):
    register_user(c, "alice")
    key = _keys(c, "editor", "ed")
    login(c, "alice")
    did = make_doc(c, title="U1", content="Grüße 👋 Welt\nzweite Zeile\n")
    sid = _ok_struct(_call(c, key, "suggest",
                           {"path": "/docs/U1", "old_string": "Grüße 👋",
                            "new_string": "Grüße 🌍"}, 61))["id"]
    assert c.post(f"/api/docs/{did}/suggestions/{sid}/accept").status_code == 200
    want = "Grüße 🌍 Welt\nzweite Zeile\n"
    assert _db_content(did) == want
    assert sync.room_text(did) == want
    got = _ok_struct(_call(c, key, "read", {"path": "/docs/U1"}, 62))
    assert got["content"] == want, got


def test_stale_and_ambiguous_anchors(c):
    register_user(c, "alice")
    key = _keys(c, "editor", "ed")
    login(c, "alice")
    did = make_doc(c, title="Amb", content="aaa\nbbb\naaa\n")
    # ambiguous anchor: 2 matches -> 409
    err = _err_text(_call(c, key, "suggest",
                          {"path": "/docs/Amb", "old_string": "aaa", "new_string": "A"}, 71))
    assert "409" in err and "exactly once" in err, err
    # valid suggestion, then the anchor is edited away -> accept is 409 stale
    sid = _ok_struct(_call(c, key, "suggest",
                           {"path": "/docs/Amb", "old_string": "bbb", "new_string": "B"}, 72))["id"]
    ok = _ok_struct(_call(c, key, "edit",
                          {"path": "/docs/Amb", "old_string": "bbb", "new_string": "XXX"}, 73))
    assert ok["ok"] is True
    r = c.post(f"/api/docs/{did}/suggestions/{sid}/accept")
    assert r.status_code == 409 and "changed or is ambiguous" in r.text, r.text
    # suggesting the gone anchor directly is also 409
    err2 = _err_text(_call(c, key, "suggest",
                           {"path": "/docs/Amb", "old_string": "bbb", "new_string": "B"}, 74))
    assert "409" in err2, err2


def test_repeat_accept_reject_and_reviewer_forbidden(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, title="R1", content="stay here\n")
    assert c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "reviewer"}).status_code == 200
    login(c, "alice")
    akey = _keys(c, "editor", "aed")
    sid = _ok_struct(_call(c, akey, "suggest",
                           {"path": "/docs/R1", "old_string": "stay", "new_string": "STAY"}, 81))["id"]
    login(c, "bob")
    assert c.post(f"/api/docs/{did}/suggestions/{sid}/accept").status_code == 403
    assert c.post(f"/api/docs/{did}/suggestions/{sid}/reject").status_code == 403
    login(c, "alice")
    assert c.post(f"/api/docs/{did}/suggestions/{sid}/accept").status_code == 200
    assert c.post(f"/api/docs/{did}/suggestions/{sid}/accept").status_code == 409
    assert c.post(f"/api/docs/{did}/suggestions/{sid}/reject").status_code == 409
    sid2 = _ok_struct(_call(c, akey, "suggest",
                            {"path": "/docs/R1", "old_string": "STAY", "new_string": "stay"}, 82))["id"]
    assert c.post(f"/api/docs/{did}/suggestions/{sid2}/reject").status_code == 200
    assert c.post(f"/api/docs/{did}/suggestions/{sid2}/reject").status_code == 409
    assert c.post(f"/api/docs/{did}/suggestions/{sid2}/accept").status_code == 409


def test_suggest_validation_and_file_path_and_trash(c):
    register_user(c, "alice")
    key = _keys(c, "editor", "ed")
    login(c, "alice")
    did = make_doc(c, title="V1", content="filecontent body\n")
    assert c.post(f"/api/docs/{did}/files/note.typ/text", json={"content": "filecontent"}).status_code == 200
    # empty old_string cannot occur exactly once -> 409 with current backend
    # (schemas.SuggestionNew has no min_length; guard lives in count check).
    err = _err_text(_call(c, key, "suggest",
                          {"path": "/docs/V1", "old_string": "", "new_string": "X"}, 91))
    assert "409" in err and "exactly once" in err, err
    # no-op suggestion -> 400
    err = _err_text(_call(c, key, "suggest",
                          {"path": "/docs/V1", "old_string": "body", "new_string": "body"}, 92))
    assert "400" in err and "must change" in err, err
    # suggestions live on documents, not files
    err = _err_text(_call(c, key, "suggest",
                          {"path": "/docs/V1/note.typ", "old_string": "file", "new_string": "FILE"}, 93))
    assert "400" in err and "document" in err.lower(), err
    # trash blocks suggest/list/read via MCP with 410
    assert c.delete(f"/api/docs/{did}").status_code == 200
    err = _err_text(_call(c, key, "suggest",
                          {"path": "/docs/V1", "old_string": "body", "new_string": "BODY"}, 94))
    assert "410" in err, err
    err = _err_text(_call(c, key, "suggestions", {"path": "/docs/V1"}, 95))
    assert "410" in err, err


def test_existing_tools_smoke_via_mcp_http(c):
    register_user(c, "alice")
    key = _keys(c, "editor", "ed")
    sc = _ok_struct(_call(c, key, "create", {"path": "/docs/Smoke", "content": "launch the rocket soon"}, 101))
    assert sc["title"] == "Smoke", sc
    got = _ok_struct(_call(c, key, "read", {"path": "/docs/Smoke"}, 102))
    assert got["content"] == "launch the rocket soon" and got["total_lines"] == 1, got
    hits = _ok_struct(_call(c, key, "search", {"query": "rocket"}, 103))
    assert any(h["path"] == "/docs/Smoke" for h in hits["hits"]), hits
    assert _ok_struct(_call(c, key, "search", {"query": "x"}, 104))["hits"] == []
    cid = _ok_struct(_call(c, key, "comment",
                           {"path": "/docs/Smoke", "anchor": 1, "text": "nit: fuel"}, 105))
    assert cid["id"], cid
    root = _ok_struct(_call(c, key, "ls", {"path": "/"}, 106))
    assert "Smoke" in [d["title"] for d in root["docs"]], root


def test_suggest_uses_live_yjs_text(c):
    from pycrdt import Text as _Text

    register_user(c, "alice")
    key = _keys(c, "editor", "ed")
    login(c, "alice")
    did = make_doc(c, title="Y1", content="alpha beta\ngamma\n")
    room = sync.room(did)
    with room["doc"].transaction():
        room["doc"].get("typst", type=_Text).__iadd__(" liveword")
    room["dirty"] = True
    # live-only anchor is suggestible (proves the tool reads Yjs, not just DB)
    sid = _ok_struct(_call(c, key, "suggest",
                           {"path": "/docs/Y1", "old_string": "liveword",
                            "new_string": "LIVE"}, 111))["id"]
    assert c.post(f"/api/docs/{did}/suggestions/{sid}/accept").status_code == 200
    assert sync.room_text(did) == "alpha beta\ngamma\n LIVE"
    assert _db_content(did) == "alpha beta\ngamma\n LIVE"
