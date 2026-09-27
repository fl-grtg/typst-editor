from datetime import UTC, datetime, timedelta

from conftest import login, register_user

from backend import auth, db


def _expire(token):
    con = db.connect()
    try:
        past = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        con.execute("UPDATE sessions SET expires=? WHERE token_hash=?", (past, auth.sha(token)))
        con.commit()
    finally:
        con.close()


def test_expired_session_401(c):
    register_user(c, "alice")
    _expire(c.cookies.get(auth.COOKIE))
    assert c.get("/api/me").status_code == 401


def test_logout_401(c):
    register_user(c, "alice")
    assert c.get("/api/me").status_code == 200
    c.post("/api/logout")
    assert c.get("/api/me").status_code == 401


def test_password_change_kills_other_sessions(c):
    register_user(c, "alice")
    old = c.cookies.get(auth.COOKIE)  # session from register (cookie, no body token)
    login(c, "alice")
    assert c.post("/api/me/password", json={"old": "pass1234", "new": "neu12345"}).status_code == 200
    assert c.get("/api/me").status_code == 200
    c.cookies.set(auth.COOKIE, old)
    assert c.get("/api/me").status_code == 401
