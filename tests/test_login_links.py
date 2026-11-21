from conftest import register_user

from backend import auth, db


def test_cookie_name_is_port_scoped():
    assert auth.cookie_name("") == auth.COOKIE
    assert auth.cookie_name("example.com") == auth.COOKIE
    assert auth.cookie_name("example.com:80") == auth.COOKIE
    assert auth.cookie_name("example.com:443") == auth.COOKIE
    assert auth.cookie_name("example.com:8978") == auth.COOKIE + "_8978"
    assert auth.cookie_name("[::1]:8978") == auth.COOKIE + "_8978"
    assert auth.cookie_name("bad:port") == auth.COOKIE


def test_session_cookie_only_works_on_its_port(c):
    r = c.post("/api/register", json={"username": "alice", "password": "pass1234"},
               headers={"host": "testserver:8978"})
    assert r.status_code == 200, r.text
    name = auth.cookie_name("testserver:8978")
    tok = r.cookies.get(name)
    assert name == auth.COOKIE + "_8978" and tok
    c.cookies.clear()
    # Same browser cookie sent to another port on the same host: no session.
    assert c.get("/api/me", headers={"host": "testserver:8979",
                                     "cookie": f"{name}={tok}"}).status_code == 401
    assert c.get("/api/me", headers={"host": "testserver:8978",
                                     "cookie": f"{name}={tok}"}).status_code == 200


def test_pre_port_cookie_still_works(c):
    register_user(c, "alice")
    tok = c.cookies.get(auth.COOKIE)
    c.cookies.clear()
    assert c.get("/api/me", headers={"host": "testserver:8978",
                                     "cookie": f"{auth.COOKIE}={tok}"}).status_code == 200


def test_logout_clears_the_legacy_cookie_too(c):
    port_name = auth.cookie_name("testserver:8978")
    r = c.post("/api/register", json={"username": "alice", "password": "pass1234"},
               headers={"host": "testserver:8978"})
    port_tok = r.cookies.get(port_name)
    legacy_tok = auth.mint("alice")
    r = c.post("/api/logout", headers={
        "host": "testserver:8978",
        "cookie": f"{port_name}={port_tok}; {auth.COOKIE}={legacy_tok}",
    })
    cleared = [h for h in r.headers.get_list("set-cookie") if "Max-Age=0" in h]
    # Both cookies authenticated the request: leaving the shared legacy one
    # behind would sign the browser back in through the fallback.
    assert any(h.startswith(port_name + "=") for h in cleared)
    assert any(h.startswith(auth.COOKIE + "=") for h in cleared)


def test_port_login_keeps_the_legacy_cookie_for_default_ports(c):
    register_user(c, "alice")
    legacy_tok = c.cookies.get(auth.COOKIE)
    c.cookies.clear()
    port_name = auth.cookie_name("testserver:8978")
    r = c.post("/api/login", json={"username": "alice", "password": "pass1234"},
               headers={"host": "testserver:8978"})
    assert r.status_code == 200, r.text
    set_cookies = r.headers.get_list("set-cookie")
    assert any(h.startswith(port_name + "=") for h in set_cookies)
    # Signing in on a dev port must not end the session on the default port.
    assert not any(h.startswith(auth.COOKIE + "=") and "Max-Age=0" in h for h in set_cookies)
    assert c.get("/api/me", headers={"host": "testserver",
                                     "cookie": f"{auth.COOKIE}={legacy_tok}"}).status_code == 200


def test_login_link_roundtrip_and_revoke(c):
    register_user(c, "alice")
    tid, tok = auth.mint_login_token("alice")
    assert tok.startswith(auth.LOGIN_TOKEN_PREFIX)
    con = db.connect()
    try:
        row = con.execute("SELECT token_hash FROM login_tokens WHERE id=?", (tid,)).fetchone()
        assert row["token_hash"] == auth.sha(tok)
        assert con.execute("SELECT 1 FROM login_tokens WHERE token_hash=?", (tok,)).fetchone() is None
    finally:
        con.close()
    c.post("/api/logout")
    assert c.get("/api/me").status_code == 401
    assert c.post("/api/login/token", json={"token": tok}).status_code == 200
    assert c.get("/api/me").json()["user"] == "alice"
    # Reload with the same token reuses the session (no session churn).
    old = c.cookies.get(auth.COOKIE)
    assert c.post("/api/login/token", json={"token": tok}).status_code == 200
    assert c.cookies.get(auth.COOKIE) == old
    listed = auth.list_login_tokens("alice")
    assert [x["id"] for x in listed] == [tid]
    assert "token" not in listed[0]
    assert auth.revoke_login_token(tid, "bob") is False
    assert auth.revoke_login_token(tid, "alice") is True
    c.post("/api/logout")
    assert c.post("/api/login/token", json={"token": tok}).status_code == 401


def test_login_link_management_is_not_public(c):
    register_user(c, "alice")
    # The links exist for internal tooling only: no settings/API surface.
    assert c.post("/api/login/tokens").status_code == 404
    assert c.get("/api/login/tokens").status_code == 404
    assert c.delete("/api/login/tokens/lt_test").status_code == 404


def test_login_link_invalid(c):
    register_user(c, "alice")
    assert c.post("/api/login/token", json={"token": "nope"}).status_code == 401
    assert c.post("/api/login/token", json={"token": "tpl_" + "0" * 64}).status_code == 401


def test_login_link_survives_rename(c):
    register_user(c, "alice")
    tid, tok = auth.mint_login_token("alice")
    assert c.post("/api/me/name", json={"name": "alice2", "password": "pass1234"}).status_code == 200
    assert [x["id"] for x in auth.list_login_tokens("alice2")] == [tid]
    c.post("/api/logout")
    assert c.post("/api/login/token", json={"token": tok}).status_code == 200
    assert c.get("/api/me").json()["user"] == "alice2"
