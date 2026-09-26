from backend import auth, db
from conftest import login, make_doc, register_user


def _old_invite(token):
    con = db.connect()
    try:
        con.execute("UPDATE invites SET created_at=? WHERE token=?",
                    ("2000-01-01T00:00:00+00:00", auth.sha(token)))
        con.commit()
    finally:
        con.close()


def test_invite_join(c):
    register_user(c, "alice")
    register_user(c, "carol")
    login(c, "alice")
    did = make_doc(c, "Einladung")
    tok = c.post(f"/api/docs/{did}/invite", json={"role": "reviewer"}).json()["token"]
    login(c, "carol")
    assert c.post(f"/api/join/{tok}").json()["id"] == did
    assert c.get(f"/api/docs/{did}").status_code == 200


def test_invite_list_hint_only(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Einladung2")
    tok = c.post(f"/api/docs/{did}/invite", json={"role": "editor"}).json()["token"]
    invites = c.get(f"/api/docs/{did}/invites").json()["invites"]
    assert len(invites) == 1
    assert invites[0]["hint"] == tok[:8]
    assert "token" not in invites[0]


def test_unshare_kills_invite(c):
    register_user(c, "alice")
    register_user(c, "bob")
    register_user(c, "carol")
    login(c, "alice")
    did = make_doc(c, "Einladung3")
    c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "editor"})
    tok = c.post(f"/api/docs/{did}/invite", json={"role": "reviewer"}).json()["token"]
    c.delete(f"/api/docs/{did}/share/bob")
    login(c, "carol")
    assert c.post(f"/api/join/{tok}").status_code == 404


def test_expired_invite_404(c):
    register_user(c, "alice")
    register_user(c, "carol")
    login(c, "alice")
    did = make_doc(c, "Einladung4")
    tok = c.post(f"/api/docs/{did}/invite", json={"role": "reviewer"}).json()["token"]
    _old_invite(tok)
    login(c, "carol")
    assert c.post(f"/api/join/{tok}").status_code == 404


def test_invite_kein_upgrade(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "Einladung5")
    assert c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "reviewer"}).status_code == 200
    tok = c.post(f"/api/docs/{did}/invite", json={"role": "editor"}).json()["token"]
    login(c, "bob")
    assert c.post(f"/api/join/{tok}").json()["id"] == did
    assert c.post(f"/api/docs/{did}/save", json={"content": "x"}).status_code == 403  # Rolle bleibt reviewer
