from conftest import register_user


def test_register_login_me(c):
    register_user(c, "alice")
    r = c.get("/api/me")
    assert r.status_code == 200
    assert r.json()["user"] == "alice"


def test_login_wrong_password_401(c):
    register_user(c, "bob")
    c.post("/api/logout")
    r = c.post("/api/login", json={"username": "bob", "password": "falsch12"})
    assert r.status_code == 401


def test_register_duplicate_400(c):
    register_user(c, "cara")
    r = c.post("/api/register", json={"username": "cara", "password": "pass1234"})
    assert r.status_code == 400


def test_register_weak_password_400(c):
    # MIN_PW=8 (Phase-1-Fix): 7 Zeichen -> 400
    r = c.post("/api/register", json={"username": "dave", "password": "abc1234"})
    assert r.status_code == 400
