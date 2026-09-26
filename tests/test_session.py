from datetime import datetime, timedelta, timezone

from backend import auth, db
from conftest import login, register_user


def _expire(token):
    con = db.connect()
    try:
        past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        con.execute("UPDATE sessions SET expires=? WHERE token_hash=?", (past, auth.sha(token)))
        con.commit()
    finally:
        con.close()


def test_expired_session_401(c):
    tok = register_user(c, "alice")["token"]
    _expire(tok)
    assert c.get("/api/me").status_code == 401


def test_logout_401(c):
    register_user(c, "alice")
    assert c.get("/api/me").status_code == 200
    c.post("/api/logout")
    assert c.get("/api/me").status_code == 401


def test_password_change_kills_other_sessions(c):
    tok_a = register_user(c, "alice")["token"]
    login(c, "alice")
    assert c.post("/api/me/password", json={"old": "pass1234", "new": "neu12345"}).status_code == 200
    assert c.get("/api/me").status_code == 200
    c.cookies.set(auth.COOKIE, tok_a)
    assert c.get("/api/me").status_code == 401
