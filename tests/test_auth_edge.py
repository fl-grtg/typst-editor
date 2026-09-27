"""Auth edge: password change, rename edge cases, delete with shares/invites."""
from conftest import login, make_doc, register_user


def test_password_happy(c):
    register_user(c, "alice")
    assert c.post("/api/me/password", json={"old": "pass1234", "new": "neu12345"}).status_code == 200
    c.post("/api/logout")
    assert c.post("/api/login", json={"username": "alice", "password": "neu12345"}).status_code == 200


def test_password_wrong_old_401(c):
    register_user(c, "alice")
    assert c.post("/api/me/password", json={"old": "falsch123", "new": "neu12345"}).status_code == 401


def test_password_too_short_400(c):
    register_user(c, "alice")
    assert c.post("/api/me/password", json={"old": "pass1234", "new": "kurz"}).status_code == 400


def test_rename_umlaut_400(c):
    register_user(c, "alice")
    assert c.post("/api/me/name", json={"name": "Müller", "password": "pass1234"}).status_code == 400
    assert c.get("/api/me").json()["user"] == "alice"


def test_rename_spaces_trimmed(c):
    register_user(c, "alice")
    r = c.post("/api/me/name", json={"name": "  alice2  ", "password": "pass1234"})
    assert r.status_code == 200
    assert r.json()["user"] == "alice2"


def test_rename_20_chars_ok_21_rejected(c):
    register_user(c, "alice")
    assert c.post("/api/me/name", json={"name": "a" * 20, "password": "pass1234"}).status_code == 200
    assert c.post("/api/me/name", json={"name": "b" * 21, "password": "pass1234"}).status_code in (400, 422)


def test_rename_wrong_password_401(c):
    register_user(c, "alice")
    assert c.post("/api/me/name", json={"name": "alice2", "password": "falsch123"}).status_code == 401


def test_delete_me_with_shares_and_invites(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "Geteilt")
    c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "editor"})
    tok = c.post(f"/api/docs/{did}/invite", json={"role": "reviewer"}).json()["token"]
    assert c.post("/api/me/delete", json={"password": "pass1234"}).status_code == 200
    login(c, "bob")
    assert c.get(f"/api/docs/{did}").status_code == 404
    assert c.post("/api/join", json={"token": tok}).status_code == 404
