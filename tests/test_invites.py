from conftest import login, make_doc, register_user

from backend import auth, db, ratelimit


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
    assert c.post("/api/join", json={"token": tok}).json()["id"] == did
    assert c.get(f"/api/docs/{did}").status_code == 200


def test_invite_list_hint_only(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Einladung2")
    tok = c.post(f"/api/docs/{did}/invite", json={"role": "editor"}).json()["token"]
    invites = c.get(f"/api/docs/{did}/invites").json()["invites"]
    assert len(invites) == 1
    assert len(invites[0]["hint"]) == 8
    assert invites[0]["hint"] != tok[:8]  # independent randomness, not a token prefix
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
    assert c.post("/api/join", json={"token": tok}).status_code == 404


def test_expired_invite_404(c):
    register_user(c, "alice")
    register_user(c, "carol")
    login(c, "alice")
    did = make_doc(c, "Einladung4")
    tok = c.post(f"/api/docs/{did}/invite", json={"role": "reviewer"}).json()["token"]
    _old_invite(tok)
    login(c, "carol")
    assert c.post("/api/join", json={"token": tok}).status_code == 404


def test_invite_no_upgrade(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "Einladung5")
    assert c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "reviewer"}).status_code == 200
    tok = c.post(f"/api/docs/{did}/invite", json={"role": "editor"}).json()["token"]
    login(c, "bob")
    assert c.post("/api/join", json={"token": tok}).json()["id"] == did
    assert c.post(f"/api/docs/{did}/save", json={"content": "x"}).status_code == 403  # role stays reviewer


def test_invite_limit_20(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Einladung6")
    for i in range(20):
        if i and i % 9 == 0:
            ratelimit.clear()
        assert c.post(f"/api/docs/{did}/invite", json={"role": "reviewer"}).status_code == 200
    ratelimit.clear()
    assert c.post(f"/api/docs/{did}/invite", json={"role": "reviewer"}).status_code == 400


def test_join_invalid(c):
    register_user(c, "alice")
    assert c.get("/api/join/invalid").status_code == 404
    assert c.post("/api/join", json={"token": "invalid"}).status_code == 404


def test_join_legacy_path_always_410(c):
    # Current behaviour: POST /api/join/{token} is legacy and always answers 410
    # (auch mit gueltigem Token). Token gehoert in den POST-Body.
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "LegacyJoin")
    tok = c.post(f"/api/docs/{did}/invite", json={"role": "reviewer"}).json()["token"]
    assert c.post(f"/api/join/{tok}").status_code == 410
    assert c.post("/api/join/invalidtoken123").status_code == 410
    # Unauthenticated: Depends(me) fires first -> 401 (not 410).
    c.post("/api/logout")
    assert c.post(f"/api/join/{tok}").status_code == 401


def test_expired_excluded_from_list_and_count(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Einladung7")
    toks = []
    for i in range(20):
        if i and i % 9 == 0:
            ratelimit.clear()
        toks.append(c.post(f"/api/docs/{did}/invite", json={"role": "reviewer"}).json()["token"])
    _old_invite(toks[0])
    assert len(c.get(f"/api/docs/{did}/invites").json()["invites"]) == 19
    ratelimit.clear()
    assert c.post(f"/api/docs/{did}/invite", json={"role": "reviewer"}).status_code == 200
    assert len(c.get(f"/api/docs/{did}/invites").json()["invites"]) == 20
