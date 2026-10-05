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


def test_rename_ratelimit_429(c):
    register_user(c, "alice")
    did = make_doc(c, "R", content="hi")
    ratelimit.clear()
    codes = set()
    for i in range(11): # rename scope is 10/min (own bucket, no longer shares save)
        codes.add(c.post(f"/api/docs/{did}/rename", json={"title": f"R{i}"}).status_code)
    assert 429 in codes


def test_delete_ratelimit_429(c):
    register_user(c, "alice")
    dids = [make_doc(c, f"D{i}", content="hi") for i in range(11)]
    ratelimit.clear()
    codes = set()
    for did in dids: # delete scope is 10/min (own bucket, no longer shares save)
        codes.add(c.delete(f"/api/docs/{did}").status_code)
    assert 429 in codes


def test_restore_ratelimit_429(c):
    register_user(c, "alice")
    did = make_doc(c, "W", content="hi")
    assert c.delete(f"/api/docs/{did}").status_code == 200
    ratelimit.clear()
    codes = set()
    for _ in range(11): # restore scope is 10/min (own bucket, no longer shares save)
        codes.add(c.post(f"/api/docs/{did}/restore").status_code)
    assert 429 in codes


def test_move_ratelimit_429(c):
    register_user(c, "alice")
    did = make_doc(c, "M", content="hi")
    ratelimit.clear()
    codes = set()
    for _ in range(21): # move scope is 20/min (own bucket, no longer shares files)
        codes.add(c.post(f"/api/docs/{did}/folder", json={"folder": "M"}).status_code)
    assert 429 in codes


def test_templates_ratelimit_429(c):
    register_user(c, "alice")
    ratelimit.clear()
    codes = set()
    for _ in range(21): # templates scope is 20/min (own bucket, no longer shares save/files)
        codes.add(c.post("/api/templates", json={"name": "r.typ", "content": "x"}).status_code)
    assert 429 in codes


def test_tplfolders_ratelimit_429(c):
    register_user(c, "alice")
    ratelimit.clear()
    codes = set()
    for _ in range(21): # tplfolders scope is 20/min (own bucket, no longer shares files)
        codes.add(c.delete("/api/tplfolders/Z").status_code)
    assert 429 in codes


def test_rename_isolated_from_save(c):
    register_user(c, "alice")
    did = make_doc(c, "S", content="hi")
    ratelimit.clear()
    for _ in range(30): # exhaust the save bucket (autosave cadence)
        assert c.post(f"/api/docs/{did}/save", json={"content": "hi"}).status_code == 200
    assert c.post(f"/api/docs/{did}/save", json={"content": "hi"}).status_code == 429
    # rename has its own bucket: still works despite save exhaustion
    assert c.post(f"/api/docs/{did}/rename", json={"title": "S2"}).status_code == 200


def test_templates_isolated_from_save(c):
    register_user(c, "alice")
    did = make_doc(c, "S", content="hi")
    ratelimit.clear()
    for _ in range(30): # exhaust the save bucket
        assert c.post(f"/api/docs/{did}/save", json={"content": "hi"}).status_code == 200
    # templates have their own bucket: still works despite save exhaustion
    assert c.post("/api/templates", json={"name": "iso.typ", "content": "x"}).status_code == 200
