from conftest import login, make_doc, register_user

from backend import db
from backend.mcp_fs import open_comments


def _setup(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "Kommentare")
    c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "reviewer"})
    cid = c.post(f"/api/docs/{did}/comments", json={"anchor": 3, "text": "oben"}).json()["id"]
    return did, cid


def test_create_list_reply(c):
    did, cid = _setup(c)
    rid = c.post(f"/api/docs/{did}/comments", json={"anchor": 0, "text": "antwort", "parent_id": cid}).json()["id"]
    comments = c.get(f"/api/docs/{did}/comments").json()["comments"]
    assert [t["id"] for t in comments] == [cid]
    assert [r["id"] for r in comments[0]["replies"]] == [rid]


def test_invalid_400(c):
    did, cid = _setup(c)
    assert c.post(f"/api/docs/{did}/comments", json={"anchor": 0, "text": "   "}).status_code == 400
    assert c.post(f"/api/docs/{did}/comments", json={"anchor": -1, "text": "x"}).status_code == 400
    rid = c.post(f"/api/docs/{did}/comments", json={"anchor": 0, "text": "r", "parent_id": cid}).json()["id"]
    assert c.post(f"/api/docs/{did}/comments", json={"anchor": 0, "text": "rr", "parent_id": rid}).status_code == 400


def test_edit_author_only(c):
    did, cid = _setup(c)
    login(c, "bob")
    assert c.post(f"/api/docs/{did}/comments/{cid}/edit", json={"text": "fremd"}).status_code == 403
    login(c, "alice")
    assert c.post(f"/api/docs/{did}/comments/{cid}/edit", json={"text": "neu"}).status_code == 200


def test_resolve(c):
    did, cid = _setup(c)
    assert c.post(f"/api/docs/{did}/comments/{cid}/resolve", json={"resolved": True}).status_code == 200
    login(c, "bob")
    assert c.post(f"/api/docs/{did}/comments/{cid}/resolve", json={"resolved": False}).status_code == 403
    bcid = c.post(f"/api/docs/{did}/comments", json={"anchor": 0, "text": "von bob"}).json()["id"]
    login(c, "alice")
    assert c.post(f"/api/docs/{did}/comments/{bcid}/resolve", json={"resolved": True}).status_code == 200


def test_delete_removes_replies(c):
    did, cid = _setup(c)
    c.post(f"/api/docs/{did}/comments", json={"anchor": 0, "text": "r", "parent_id": cid})
    assert c.delete(f"/api/docs/{did}/comments/{cid}").status_code == 200
    assert c.get(f"/api/docs/{did}/comments").json()["comments"] == []


def test_anchor_zero_clamped_to_one(c):
    did, cid = _setup(c)
    got = c.get(f"/api/docs/{did}/comments").json()["comments"]
    assert got[0]["anchor"] == 3
    cid0 = c.post(f"/api/docs/{did}/comments", json={"anchor": 0, "text": "top"}).json()["id"]
    got = c.get(f"/api/docs/{did}/comments").json()["comments"]
    assert [t["anchor"] for t in got if t["id"] == cid0] == [1]
    assert c.post(f"/api/docs/{did}/comments/{cid0}/anchor", json={"anchor": 0}).status_code == 200
    got = c.get(f"/api/docs/{did}/comments").json()["comments"]
    assert [t["anchor"] for t in got if t["id"] == cid0] == [1]


def test_suggestion_delete_resolve_guards(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Vorschlag", content="alpha beta gamma")
    sid = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "beta", "new_string": "BETA"}).json()["id"]
    # pending: use accept/reject, not delete/resolve/move
    assert c.delete(f"/api/docs/{did}/comments/{sid}").status_code == 400
    assert c.post(f"/api/docs/{did}/comments/{sid}/resolve", json={"resolved": True}).status_code == 400
    assert c.post(f"/api/docs/{did}/comments/{sid}/anchor", json={"anchor": 42}).status_code == 400
    # foreign reviewer gets 403 (role before state), not 400
    register_user(c, "bob")
    login(c, "alice")
    assert c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "reviewer"}).status_code == 200
    login(c, "bob")
    assert c.delete(f"/api/docs/{did}/comments/{sid}").status_code == 403
    assert c.post(f"/api/docs/{did}/comments/{sid}/resolve", json={"resolved": True}).status_code == 403
    login(c, "alice")
    # decided: deletable again, resolve stays frozen, anchor move allowed
    assert c.post(f"/api/docs/{did}/suggestions/{sid}/accept").status_code == 200
    assert c.post(f"/api/docs/{did}/comments/{sid}/resolve", json={"resolved": True}).status_code == 400
    assert c.post(f"/api/docs/{did}/comments/{sid}/anchor", json={"anchor": 9}).status_code == 200
    got = next(t for t in c.get(f"/api/docs/{did}/comments").json()["comments"] if t["id"] == sid)
    assert got["anchor"] == 9
    assert c.delete(f"/api/docs/{did}/comments/{sid}").status_code == 200
    assert c.get(f"/api/docs/{did}/comments").json()["comments"] == []


def test_package_scoped_comments_isolated_and_cleaned(c):
    from conftest import project_of
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "PaketDoc", content="alpha beta")
    pid = project_of(c, did)
    pkg = c.post(f"/api/projects/{pid}/proposals", json={
        "title": "Aenderung",
        "files": [{"kind": "document", "doc_id": did, "action": "modify", "base": "alpha beta", "content": "alpha GAMMA",
                   "changes": [{"old_string": "alpha beta", "new_string": "alpha GAMMA"}]}],
    }).json()["id"]
    live_id = c.post(f"/api/docs/{did}/comments", json={
        "anchor": 1, "text": "live", "quote": "GAMMA", "anchor_quote": "beta", "anchor_range": "AQI=.AwQ=",
    }).json()["id"]
    pkg_cid = c.post(f"/api/docs/{did}/comments", json={"anchor": 1, "quote": "GAMMA", "text": "im paket", "package_id": pkg}).json()["id"]
    # replies inherit package_id automatically
    c.post(f"/api/docs/{did}/comments", json={"anchor": 1, "text": "antwort im paket", "parent_id": pkg_cid})
    # unknown package rejected
    assert c.post(f"/api/docs/{did}/comments", json={"anchor": 1, "text": "x", "package_id": "bogus"}).status_code == 404
    # live comments never include package comments, and vice versa
    live, = c.get(f"/api/docs/{did}/comments").json()["comments"]
    assert (live["id"], live["quote"], live["anchor_quote"], live["anchor_range"]) == (live_id, "GAMMA", "beta", "AQI=.AwQ=")
    assert [t["id"] for t in open_comments(did)] == [live_id]
    pkg_list = c.get(f"/api/docs/{did}/comments", params={"package_id": pkg}).json()["comments"]
    assert [t["id"] for t in pkg_list] == [pkg_cid]
    assert len(pkg_list[0]["replies"]) == 1
    package_url = f"/api/projects/{pid}/proposals/{pkg}"
    revision = c.get(package_url).json()["revision"]
    assert c.post(package_url + "/accept", json={"revision": revision}).status_code == 200
    assert c.get(f"/api/projects/{pid}/proposals").json()["packages"] == []
    assert [p["id"] for p in c.get(f"/api/projects/{pid}/proposals?include_closed=true").json()["packages"]] == [pkg]
    assert c.get(f"/api/docs/{did}/comments", params={"package_id": pkg}).json()["comments"] == pkg_list
    # deleting the package cleans up its package-scoped comments, leaving live comments untouched
    assert c.delete(package_url).status_code == 200
    assert c.get(f"/api/docs/{did}/comments", params={"package_id": pkg}).status_code == 404
    assert [t["id"] for t in c.get(f"/api/docs/{did}/comments").json()["comments"]] == [live_id]


def test_upgrade_legacy_comments_database(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "app.db")
    legacy_schema = tmp_path / "legacy.sql"
    schema = db.SCHEMA_PATH.read_text(encoding="utf-8")
    legacy_schema.write_text("\n".join(
        line for line in schema.splitlines() if not line.lstrip().startswith(("package_id TEXT", "anchor_quote TEXT", "anchor_range TEXT"))
    ), encoding="utf-8")
    with monkeypatch.context() as m:
        m.setattr(db, "SCHEMA_PATH", legacy_schema)
        m.setattr(db, "_MIGRATIONS", db._MIGRATIONS[:35])
        db.init_db()
    with db.tx() as con:
        con.execute("INSERT INTO users (name,hash) VALUES ('alice','')")
        con.execute("INSERT INTO docs (id,owner,created_at,updated_at) VALUES ('d','alice','','')")
        con.execute("INSERT INTO comments (id,doc_id,username,text,created_at) VALUES ('c','d','alice','keep me','')")
    db.init_db()
    with db.tx() as con:
        row = con.execute("SELECT text,package_id,anchor_quote,anchor_range FROM comments WHERE id='c'").fetchone()
        assert tuple(row) == ("keep me", "", None, None)
        assert any(index["name"] == "idx_comments_pkg" for index in con.execute("PRAGMA index_list(comments)"))


def test_unsent_comments_are_published_with_the_package_only(c):
    from conftest import project_of
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, content="alpha beta gamma")
    url = f"/api/projects/{project_of(c, did)}/proposals"
    file = {"kind": "document", "doc_id": did, "action": "modify", "base": "alpha beta gamma", "content": "alpha BETTER gamma",
            "changes": [{"old_string": "beta", "new_string": "BETTER"}]}
    comment = {"doc_id": did, "anchor": 1, "text": "Why this change?", "quote": "alpha BETTER", "anchor_quote": "alpha BETTER"}
    invalid = c.post(url, json={"title": "Review", "files": [file], "comments": [{**comment, "doc_id": "missing"}]})
    assert invalid.status_code == 400
    assert c.get(url).json()["packages"] == []
    response = c.post(url, json={"title": "Review", "files": [file], "comments": [comment]})
    assert response.status_code == 200, response.text
    pkg = response.json()["id"]
    comment_url = f"/api/docs/{did}/comments"
    assert c.get(comment_url).json()["comments"] == []
    thread, = c.get(comment_url, params={"package_id": pkg}).json()["comments"]
    assert (thread["quote"], thread["package_id"], thread["text"]) == ("alpha BETTER", pkg, "Why this change?")



def test_proposal_comment_changes_stay_in_the_package(c):
    from conftest import project_of
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, content="alpha beta")
    live = c.post(f"/api/docs/{did}/comments", json={"anchor": 1, "quote": "alpha", "text": "live"}).json()["id"]
    reply = c.post(f"/api/docs/{did}/comments", json={"anchor": 1, "parent_id": live, "text": "live reply"}).json()["id"]
    file = {"kind": "document", "doc_id": did, "action": "modify", "base": "alpha beta", "content": "alpha BETA",
            "changes": [{"old_string": "beta", "new_string": "BETA"}]}
    pkg = c.post(f"/api/projects/{project_of(c, did)}/proposals", json={"title": "Review", "files": [file], "comments": [
        {"doc_id": did, "anchor": 1, "replaces_id": live, "text": "proposed edit"},
        {"doc_id": did, "anchor": 1, "replaces_id": reply, "deleted": True},
        {"doc_id": did, "anchor": 1, "parent_id": live, "text": "proposal reply"},
    ]}).json()["id"]
    url = f"/api/docs/{did}/comments"
    thread, = c.get(url).json()["comments"]
    assert (thread["text"], [r["text"] for r in thread["replies"]]) == ("live", ["live reply"])
    changes = c.get(url, params={"package_id": pkg}).json()["changes"]
    assert {(x["replaces_id"], x["parent_id"], x["text"], x["deleted"]) for x in changes} == {
        (live, None, "proposed edit", False), (reply, None, "", True), (None, live, "proposal reply", False),
    }
    assert c.post(url, json={"anchor": 1, "package_id": pkg, "replaces_id": live, "text": "second edit"}).status_code == 200
    assert c.get(url).json()["comments"][0]["text"] == "live"
    assert [x["text"] for x in c.get(url, params={"package_id": pkg}).json()["changes"] if x["replaces_id"] == live] == ["second edit"]
