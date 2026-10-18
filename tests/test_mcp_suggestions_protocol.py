"""MCP suggest/suggestions over the real Streamable-HTTP protocol (isolated tmp DB).

Uses TestClient POST /mcp JSON-RPC (initialize / tools/list / tools/call) with
Bearer API keys, plus REST accept/reject and sync.room_text for Yjs checks.
Never touches data-dev-projects or user docs: the `c` fixture isolates DB/files.
"""
import base64
import json

import pytest
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
                 "suggest", "suggestions", "propose", "proposals", "view", "export"):
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


def _setup(c, content="hello world\nsecond line\n"):
    register_user(c, "alice")
    did = make_doc(c, title="Proto", content=content)
    project = c.get(f"/api/docs/{did}").json()["project_id"]
    register_user(c, "bob")
    login(c, "alice")
    assert c.post(f"/api/projects/{project}/members", json={"username": "bob", "role": "reviewer"}).status_code == 200
    login(c, "bob")
    return did, project, _keys(c, "reviewer", "agent")


def _accept(c, project, package, **selection):
    return c.post(f"/api/projects/{project}/proposals/{package['id']}/accept",
                  json={"revision": package["revision"], **selection})


def test_suggest_is_normal_package_with_live_text_and_partial_review(c):
    did, project, key = _setup(c)
    room = sync.room(did)
    from pycrdt import Text
    room["doc"].get("typst", type=Text).__iadd__(" liveword")
    sync._mark_dirty(did, room)
    package = _ok_struct(_call(c, key, "suggest", {"path": f"/projects/{project}/docs/Proto",
                         "old_string": "liveword", "new_string": "LIVE", "text": "Improve wording"}, 21))
    assert package["author"] == "bob" and package["title"] == "Improve wording"
    assert package["files"][0]["content"].endswith(" LIVE")
    assert sync.room_text(did).endswith(" liveword")
    with db.tx() as con:
        assert con.execute("SELECT COUNT(*) FROM comments WHERE doc_id=?", (did,)).fetchone()[0] == 0
    assert _accept(c, project, package).status_code == 403
    listed = _ok_struct(_call(c, key, "suggestions", {"path": f"/projects/{project}"}, 22))
    assert [p["id"] for p in listed["packages"]] == [package["id"]]
    login(c, "alice")
    assert c.get(f"/api/projects/{project}/proposals/{package['id']}").json() == package
    assert _accept(c, project, package).status_code == 200
    assert sync.room_text(did).endswith(" LIVE")
    assert _db_content(did) == sync.room_text(did)
    assert _accept(c, project, package).status_code == 409


def test_multi_file_package_upload_add_rename_delete_and_reference_edits(c):
    base = '#import "old.typ": value\n#value\n'
    did, project, key = _setup(c, base)
    login(c, "alice")
    assert c.post(f"/api/projects/{project}/resources", json={"name": "old.typ", "content": "#let value = 1"}).status_code == 200
    assert c.post(f"/api/docs/{did}/files", files={"f": ("unused.png", b"old")}).status_code == 200
    image = base64.b64encode(b"new image").decode()
    old_image = _ok_struct(_call(c, key, "read", {"path": f"/projects/{project}/docs/Proto/unused.png", "binary": True}, 30))["content_base64"]
    files = [
        {"kind": "document", "doc_id": did, "path": "main.typ", "action": "modify", "base": base,
         "content": base.replace("old.typ", "new.typ"), "changes": [{"old_string": '"old.typ"', "new_string": '"new.typ"'}]},
        {"kind": "resource", "path": "old.typ", "action": "rename", "target": "new.typ", "base": "#let value = 1", "content": "#let value = 2"},
        {"kind": "resource", "path": "notes.bib", "action": "add", "content": "@book{key}"},
        {"kind": "file", "doc_id": did, "path": "image.png", "action": "add", "binary": True, "content": image},
        {"kind": "file", "doc_id": did, "path": "unused.png", "action": "delete", "binary": True, "base": old_image},
    ]
    package = _ok_struct(_call(c, key, "propose", {"path": f"/projects/{project}", "title": "Update project", "files": files}, 31))
    assert _db_content(did) == base
    assert c.get(f"/api/docs/{did}/files/image.png").status_code == 404
    read = _ok_struct(_call(c, key, "proposals", {"path": f"/projects/{project}", "package_id": package["id"]}, 32))
    assert read == package
    assert len({f["id"] for f in read["files"]}) == 5
    login(c, "alice")
    # Neither half of the rename/reference pair may be applied alone.
    assert _accept(c, project, package, file_id=package["files"][1]["id"]).status_code == 409
    assert _accept(c, project, package, file_id=package["files"][0]["id"]).status_code == 409
    assert _accept(c, project, package).status_code == 200
    assert _db_content(did) == base.replace("old.typ", "new.typ")
    assert c.get(f"/api/docs/{did}/files/image.png").content == b"new image"
    assert c.get(f"/api/docs/{did}/files/unused.png").status_code == 404
    assert {r["name"] for r in c.get(f"/api/projects/{project}/resources").json()["resources"]} == {"new.typ", "notes.bib"}


def test_package_correction_revisions_and_editor_acceptance(c):
    did, project, key = _setup(c)
    package = _ok_struct(_call(c, key, "suggest", {"path": f"/projects/{project}/docs/Proto", "old_string": "hello", "new_string": "HELLO"}, 41))
    file = package["files"][0]
    file["content"] = file["content"].replace("HELLO", "Greetings")
    file["changes"][0]["new_string"] = "Greetings"
    args = {"path": f"/projects/{project}", "title": "Revised", "files": [file], "package_id": package["id"], "revision": package["revision"]}
    revised = _ok_struct(_call(c, key, "propose", args, 42))
    assert revised["revision"] == package["revision"] + 1
    assert "409" in _err_text(_call(c, key, "propose", args, 43))
    login(c, "alice")
    register_user(c, "carol")
    login(c, "alice")
    c.post(f"/api/projects/{project}/members", json={"username": "carol", "role": "editor"})
    login(c, "carol")
    assert _accept(c, project, revised).status_code == 200
    assert _db_content(did).startswith("Greetings")


@pytest.mark.parametrize("old,new", [("absent", "X"), ("l", "X"), ("hello", "hello"), ("", "X")])
def test_invalid_suggest_never_creates_package(c, old, new):
    _, project, key = _setup(c)
    _err_text(_call(c, key, "suggest", {"path": f"/projects/{project}/docs/Proto", "old_string": old, "new_string": new}, 51))
    assert c.get(f"/api/projects/{project}/proposals").json()["packages"] == []


def test_stale_source_rejects_acceptance_atomically(c):
    did, project, key = _setup(c)
    package = _ok_struct(_call(c, key, "suggest", {"path": f"/projects/{project}/docs/Proto", "old_string": "hello", "new_string": "HELLO"}, 61))
    login(c, "alice")
    assert c.post(f"/api/docs/{did}/save", json={"content": "Different", "force": True}).status_code == 200
    assert _accept(c, project, package).status_code == 409
    assert _db_content(did) == "Different"
    assert c.get(f"/api/projects/{project}/proposals/{package['id']}").json()["revision"] == package["revision"]


def test_suggest_title_limit_is_explicit_and_does_not_create_a_package(c):
    _, project, key = _setup(c)
    args = {"path": f"/projects/{project}/docs/Proto", "old_string": "hello", "new_string": "HELLO", "text": "x" * 101}
    assert "Package title (text): max 100 chars" in _err_text(_call(c, key, "suggest", args, 65))
    assert c.get(f"/api/projects/{project}/proposals").json()["packages"] == []
    args["text"] = "x" * 100
    package = _ok_struct(_call(c, key, "suggest", args, 66))
    assert package["title"] == "x" * 100


def test_guests_and_foreign_project_files_are_not_exposed(c):
    did, project, key = _setup(c)
    login(c, "alice")
    foreign = make_doc(c, "Secret", "private")
    login(c, "bob")
    files = [{"kind": "document", "doc_id": foreign, "path": "main.typ", "action": "delete", "base": "private"}]
    assert "404" in _err_text(_call(c, key, "propose", {"path": f"/projects/{project}", "title": "Denied", "files": files}, 71))
    login(c, "alice")
    c.delete(f"/api/projects/{project}/members/bob")
    c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "reviewer"})
    assert "404" in _err_text(_call(c, key, "proposals", {"path": "/shared/alice/Proto"}, 72))


def test_empty_unicode_suggest_and_discard(c):
    did, project, key = _setup(c, "")
    package = _ok_struct(_call(c, key, "suggest", {"path": f"/projects/{project}/docs/Proto", "old_string": "", "new_string": "Grüße 🌍"}, 81))
    login(c, "alice")
    assert _accept(c, project, package).status_code == 200
    assert sync.room_text(did) == "Grüße 🌍"
    package = _ok_struct(_call(c, key, "suggest", {"path": f"/projects/{project}/docs/Proto", "old_string": " 🌍", "new_string": ""}, 82))
    assert c.delete(f"/api/projects/{project}/proposals/{package['id']}").status_code == 200
    assert sync.room_text(did) == "Grüße 🌍"
