from conftest import make_doc, register_user

from backend import ratelimit


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


def test_search_ratelimit_429(c):
    register_user(c, "alice")
    ratelimit.clear()
    codes = set()
    for _ in range(61):
        codes.add(c.get("/api/search", params={"q": "xy"}).status_code)
    assert 429 in codes


def test_files_ratelimit_429(c):
    register_user(c, "alice")
    did = make_doc(c, "F")
    ratelimit.clear()
    codes = set()
    for _ in range(121): # list scope is 120/min (preview polls per render)
        codes.add(c.get(f"/api/docs/{did}/files").status_code)
    assert 429 in codes


def test_save_ratelimit_429(c):
    register_user(c, "alice")
    did = make_doc(c, "S", content="hi")
    ratelimit.clear()
    codes = set()
    for _ in range(31):
        codes.add(c.post(f"/api/docs/{did}/save", json={"content": "hi"}).status_code)
    assert 429 in codes


def test_file_text_save_ratelimit_429(c):
    register_user(c, "alice")
    did = make_doc(c, "T", content="hi")
    ratelimit.clear()
    codes = set()
    for _ in range(31): # same save scope as doc save (autosave cadence fits 30/min)
        codes.add(c.post(f"/api/docs/{did}/files/n.typ/text", json={"content": "hi"}).status_code)
    assert 429 in codes


def test_avatar_get_no_limit(c):
    register_user(c, "alice")
    ratelimit.clear()
    codes = set()
    for _ in range(15): # reads are cheap + auth-gated: no 429 by design (404 = no avatar yet)
        codes.add(c.get("/api/avatar/alice").status_code)
    assert 429 not in codes
