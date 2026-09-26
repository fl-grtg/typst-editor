from conftest import login, make_doc, register_user


def test_share_unshare(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "Geteilt")
    assert c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "editor"}).status_code == 200
    login(c, "bob")
    assert c.get(f"/api/docs/{did}").status_code == 200
    login(c, "alice")
    assert c.delete(f"/api/docs/{did}/share/bob").status_code == 200
    login(c, "bob")
    assert c.get(f"/api/docs/{did}").status_code == 404


def test_join_via_invite(c):
    register_user(c, "alice")
    register_user(c, "carol")
    login(c, "alice")
    did = make_doc(c, "Invite")
    tok = c.post(f"/api/docs/{did}/invite", json={"role": "reviewer"}).json()["token"]
    assert tok  # Token-Laenge egal (alt kurz, neu 16B)
    login(c, "carol")
    assert c.post(f"/api/join/{tok}").json()["id"] == did
    assert c.get(f"/api/docs/{did}").status_code == 200


def test_no_access_404(c):
    register_user(c, "alice")
    register_user(c, "dave")
    login(c, "alice")
    did = make_doc(c, "Privat")
    login(c, "dave")
    assert c.get(f"/api/docs/{did}").status_code == 404
