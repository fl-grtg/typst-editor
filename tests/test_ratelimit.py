from conftest import make_doc, project_of, put_file, register_user

from backend import db, ratelimit
from backend.services import project_files


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


def test_search_ratelimit_429(c, monkeypatch):
    register_user(c, "alice")
    monkeypatch.setenv("RATE_SEARCH_PER_MIN", "3")
    ratelimit.clear()
    codes = set()
    for _ in range(4):
        codes.add(c.get("/api/search", params={"q": "xy"}).status_code)
    assert 429 in codes


def test_files_ratelimit_429(c, monkeypatch):
    register_user(c, "alice")
    pid = project_of(c, make_doc(c, "F"))
    monkeypatch.setenv("RATE_FILES_LIST_PER_MIN", "3")
    ratelimit.clear()
    codes = set()
    for _ in range(4):
        codes.add(c.get(f"/api/projects/{pid}/files").status_code)
    assert 429 in codes


def test_save_ratelimit_429(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "S", content="hi")
    monkeypatch.setenv("RATE_SAVE_PER_MIN", "3")
    ratelimit.clear()
    codes = set()
    for _ in range(4):
        codes.add(c.post(f"/api/docs/{did}/save", json={"content": "hi"}).status_code)
    assert 429 in codes


def test_file_text_save_ratelimit_429(c, monkeypatch):
    register_user(c, "alice")
    pid = project_of(c, make_doc(c, "T", content="hi"))
    monkeypatch.setenv("RATE_SAVE_PER_MIN", "3")
    ratelimit.clear()
    codes = set()
    for _ in range(4):
        codes.add(put_file(c, pid, "n.typ", b"hi", force=1).status_code)
    assert 429 in codes


def test_comment_anchor_does_not_consume_comments(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "C", content="line1\nline2\nline3")
    cid = c.post(f"/api/docs/{did}/comments", json={"anchor": 1, "text": "note"}).json()["id"]
    monkeypatch.setenv("RATE_COMMENTS_PER_MIN", "2")
    ratelimit.clear()
    for line in range(2, 7):
        assert c.post(f"/api/docs/{did}/comments/{cid}/anchor", json={"anchor": line}).status_code == 200
    assert c.post(f"/api/docs/{did}/comments", json={"anchor": 1, "text": "still works"}).status_code == 200


def test_avatar_get_no_limit(c):
    register_user(c, "alice")
    ratelimit.clear()
    codes = set()
    for _ in range(15): # reads are cheap + auth-gated: no 429 by design (404 = no avatar yet)
        codes.add(c.get("/api/avatar/alice").status_code)
    assert 429 not in codes


def test_rename_ratelimit_429(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "R", content="hi")
    monkeypatch.setenv("RATE_RENAME_PER_MIN", "3")
    ratelimit.clear()
    codes = set()
    for i in range(4):
        codes.add(c.post(f"/api/docs/{did}/rename", json={"title": f"R{i}"}).status_code)
    assert 429 in codes


def test_delete_ratelimit_429(c, monkeypatch):
    register_user(c, "alice")
    dids = [make_doc(c, f"D{i}", content="hi") for i in range(4)]
    monkeypatch.setenv("RATE_DELETE_PER_MIN", "3")
    ratelimit.clear()
    codes = set()
    for did in dids:
        codes.add(c.delete(f"/api/docs/{did}").status_code)
    assert 429 in codes


def test_restore_ratelimit_429(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "W", content="hi")
    assert c.delete(f"/api/docs/{did}").status_code == 200
    monkeypatch.setenv("RATE_RESTORE_PER_MIN", "3")
    ratelimit.clear()
    codes = set()
    for _ in range(4):
        codes.add(c.post(f"/api/docs/{did}/restore").status_code)
    assert 429 in codes


def test_move_ratelimit_429(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "M", content="hi")
    pid = c.get(f"/api/docs/{did}").json()["project_id"]
    monkeypatch.setenv("RATE_MOVE_PER_MIN", "3")
    ratelimit.clear()
    codes = set()
    for i in range(4): # project rename uses the move bucket
        codes.add(c.post(f"/api/projects/{pid}/rename", json={"title": f"M{i}"}).status_code)
    assert 429 in codes


def test_templates_ratelimit_429(c, monkeypatch):
    register_user(c, "alice")
    monkeypatch.setenv("RATE_TEMPLATES_PER_MIN", "3")
    ratelimit.clear()
    codes = set()
    for _ in range(4):
        codes.add(c.post("/api/templates", json={"name": "r.typ", "content": "x"}).status_code)
    assert 429 in codes


def test_tplfolders_ratelimit_429(c, monkeypatch):
    register_user(c, "alice")
    monkeypatch.setenv("RATE_TPLFOLDERS_PER_MIN", "3")
    ratelimit.clear()
    codes = set()
    for _ in range(4):
        codes.add(c.delete("/api/tplfolders/Z").status_code)
    assert 429 in codes


def test_rename_isolated_from_save(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "S", content="hi")
    monkeypatch.setenv("RATE_SAVE_PER_MIN", "3")
    ratelimit.clear()
    for _ in range(3): # exhaust the save bucket (autosave cadence)
        assert c.post(f"/api/docs/{did}/save", json={"content": "hi"}).status_code == 200
    assert c.post(f"/api/docs/{did}/save", json={"content": "hi"}).status_code == 429
    # rename has its own bucket: still works despite save exhaustion
    assert c.post(f"/api/docs/{did}/rename", json={"title": "S2"}).status_code == 200


def test_templates_isolated_from_save(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "S", content="hi")
    monkeypatch.setenv("RATE_SAVE_PER_MIN", "3")
    ratelimit.clear()
    for _ in range(3): # exhaust the save bucket
        assert c.post(f"/api/docs/{did}/save", json={"content": "hi"}).status_code == 200
    # templates have their own bucket: still works despite save exhaustion
    assert c.post("/api/templates", json={"name": "iso.typ", "content": "x"}).status_code == 200


def test_preview_download_burst_does_not_exhaust_uploads(c):
    register_user(c, 'alice')
    pid = project_of(c, make_doc(c, 'Images'))
    with db.tx() as con:
        for i in range(51):
            project_files.put(con, pid, f'image-{i}.png', b'image', {})
    for i in range(51):
        response = c.get(f'/api/projects/{pid}/files/image-{i}.png')
        assert response.status_code == 200
        assert response.content == b'image'
    assert put_file(c, pid, 'extra.png', b'new').status_code == 200


def test_file_reads_have_a_configurable_separate_limit(c, monkeypatch):
    register_user(c, 'alice')
    pid = project_of(c, make_doc(c, 'Read limit'))
    put_file(c, pid, 'image.png', b'image')
    monkeypatch.setenv('RATE_FILE_READ_PER_MIN', '2')
    for _ in range(2):
        assert c.get(f'/api/projects/{pid}/files/image.png').status_code == 200
    assert c.get(f'/api/projects/{pid}/files/image.png').status_code == 429
    assert put_file(c, pid, 'extra.png', b'new').status_code == 200
