from backend import ratelimit
from conftest import register_user


def test_allow_window():
    ratelimit.clear()
    assert ratelimit.allow("k", 2, 60)
    assert ratelimit.allow("k", 2, 60)
    assert not ratelimit.allow("k", 2, 60)
    ratelimit.clear()
    assert ratelimit.allow("k", 2, 60)


def test_login_ratelimit_429(c):
    register_user(c, "alice")
    ratelimit.clear()
    codes = set()
    for _ in range(11):
        r = c.post("/api/login", json={"username": "alice", "password": "falsch123"})
        codes.add(r.status_code)
    assert 429 in codes


def test_clear_resets(c):
    register_user(c, "alice")
    ratelimit.clear()
    for _ in range(10):
        assert c.post("/api/login", json={"username": "alice", "password": "falsch123"}).status_code == 401
    assert c.post("/api/login", json={"username": "alice", "password": "falsch123"}).status_code == 429
    ratelimit.clear()
    assert c.post("/api/login", json={"username": "alice", "password": "falsch123"}).status_code == 401
