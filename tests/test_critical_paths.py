from conftest import login, make_doc, register_user

from backend import auth, db
from backend import main as backend_main


def test_rename_happy(c):
    register_user(c, "alice")
    did = make_doc(c, "Meins")
    r = c.post("/api/me/name", json={"name": "alice2", "password": "pass1234"})
    assert r.status_code == 200
    assert r.json()["user"] == "alice2"
    assert c.get("/api/me").json()["user"] == "alice2"
    assert c.get(f"/api/docs/{did}").status_code == 200


def test_rename_duplicate_400(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    assert c.post("/api/me/name", json={"name": "bob", "password": "pass1234"}).status_code == 400
    assert c.get("/api/me").json()["user"] == "alice"


def test_delete_me_clears_db_and_files(c):
    register_user(c, "alice")
    did = make_doc(c, "Weg")
    assert c.post(f"/api/docs/{did}/files", files={"f": ("bild.png", b"abc")}).status_code == 200
    assert (backend_main.FILES_DIR / did).is_dir()
    assert c.post("/api/me/delete", json={"password": "pass1234"}).status_code == 200
    assert not (backend_main.FILES_DIR / did).exists()
    con = db.connect()
    try:
        assert con.execute("SELECT 1 FROM users WHERE name='alice'").fetchone() is None
        assert con.execute("SELECT 1 FROM docs WHERE id=?", (did,)).fetchone() is None
    finally:
        con.close()
    assert c.get("/api/me").status_code == 401


def test_folders_crud(c):
    register_user(c, "alice")
    did = make_doc(c, "Sortiert")
    assert c.post("/api/folders", json={"folder": "Proj"}).status_code == 200
    assert c.post(f"/api/docs/{did}/folder", json={"folder": "Proj"}).status_code == 200
    assert c.get("/api/folders").json()["folders"] == [{"folder": "Proj", "n": 1}]
    assert c.post("/api/folders/rename", json={"old": "Proj", "new": "Neu"}).status_code == 200
    assert c.get("/api/folders").json()["folders"] == [{"folder": "Neu", "n": 1}]
    assert c.delete("/api/folders/Neu").status_code == 200
    assert c.get("/api/folders").json()["folders"] == []
    assert c.get(f"/api/docs/{did}").json()["folder"] == ""


def test_templates_crud(c):
    register_user(c, "alice")
    assert c.post("/api/templates", json={"name": "brief.typ", "content": "Hallo"}).json()["name"] == "brief.typ"
    assert c.post("/api/templates", json={"name": "brief.typ", "content": "Neu"}).status_code == 200
    tpls = c.get("/api/templates").json()["templates"]
    assert [t["name"] for t in tpls] == ["brief.typ"]
    assert tpls[0]["content"] == "Neu"
    assert c.delete("/api/templates/brief.typ").status_code == 200
    assert c.get("/api/templates").json()["templates"] == []
    assert c.post("/api/templates", json={"name": "nix.txt", "content": "x"}).status_code == 400


def test_avatar_invalid_rejected(c):
    register_user(c, "alice")
    assert c.post("/api/me/avatar", json={"img": "kein-bild"}).status_code == 400
    assert c.post("/api/me/avatar", json={"img": "data:image/gif;base64,AAAA"}).status_code == 400
    assert c.get("/api/avatar/alice").status_code == 404


def _age_invite(token):
    con = db.connect()
    try:
        con.execute("UPDATE invites SET created_at=? WHERE token=?",
                    ("2000-01-01T00:00:00+00:00", auth.sha(token)))
        con.commit()
    finally:
        con.close()


def test_invite_delete_expired_trashed(c):
    register_user(c, "alice")
    register_user(c, "carol")
    login(c, "alice")
    did = make_doc(c, "Link")
    tok = c.post(f"/api/docs/{did}/invite", json={"role": "reviewer"}).json()["token"]
    hint = c.get(f"/api/docs/{did}/invites").json()["invites"][0]["hint"]
    assert hint != tok[:8]  # hint is independent randomness, not a token prefix
    assert c.delete(f"/api/docs/{did}/invites/{hint}").status_code == 200
    login(c, "carol")
    assert c.post("/api/join", json={"token": tok}).status_code == 404
    login(c, "alice")
    tok2 = c.post(f"/api/docs/{did}/invite", json={"role": "reviewer"}).json()["token"]
    assert c.delete(f"/api/docs/{did}").json()["trashed"] is True
    login(c, "carol")
    assert c.post("/api/join", json={"token": tok2}).status_code == 410
    login(c, "alice")
    assert c.post(f"/api/docs/{did}/restore").status_code == 200
    tok3 = c.post(f"/api/docs/{did}/invite", json={"role": "reviewer"}).json()["token"]
    _age_invite(tok3)
    login(c, "carol")
    assert c.post("/api/join", json={"token": tok3}).status_code == 404


def test_search_escapes_wildcards(c):
    register_user(c, "alice")
    make_doc(c, "Normal", content="hello world ruhe")
    assert c.get("/api/search", params={"q": "__"}).json()["hits"] == []
    assert c.get("/api/search", params={"q": "%%"}).json()["hits"] == []
    make_doc(c, "Prozent", content="100% sicher")
    hits = c.get("/api/search", params={"q": "100%"}).json()["hits"]
    assert [h["title"] for h in hits] == ["Prozent"]


def test_snapshot_prune_max_50(c):
    register_user(c, "alice")
    did = make_doc(c, "Verlauf")
    for i in range(55):
        assert c.post(f"/api/docs/{did}/snapshots", json={"label": f"s{i}"}).status_code == 200
    assert len(c.get(f"/api/docs/{did}/snapshots").json()["snapshots"]) == 50


def test_members_and_comment_anchor(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "Team")
    c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "reviewer"})
    assert c.get(f"/api/docs/{did}/members").json()["members"] == ["alice", "bob"]
    cid = c.post(f"/api/docs/{did}/comments", json={"anchor": 3, "text": "oben"}).json()["id"]
    assert c.post(f"/api/docs/{did}/comments/{cid}/anchor", json={"anchor": 45}).status_code == 200
    login(c, "bob")
    assert c.post(f"/api/docs/{did}/comments/{cid}/anchor", json={"anchor": 9}).status_code == 403
    assert c.post(f"/api/docs/{did}/comments/{cid}/anchor", json={"anchor": -1}).status_code == 400
