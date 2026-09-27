from conftest import login, make_doc, register_user


def _shared(c, role):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "Rollen")
    assert c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": role}).status_code == 200
    login(c, "bob")
    return did


def test_reviewer_read_only(c):
    did = _shared(c, "reviewer")
    assert c.get(f"/api/docs/{did}").status_code == 200
    assert c.post(f"/api/docs/{did}/save", json={"content": "x"}).status_code == 403
    assert c.post(f"/api/docs/{did}/snapshots", json={}).status_code == 403
    assert c.post(f"/api/docs/{did}/rename", json={"title": "Neu"}).status_code == 403
    assert c.post(f"/api/docs/{did}/share", json={"username": "alice", "role": "editor"}).status_code == 403
    assert c.post(f"/api/docs/{did}/invite", json={"role": "reviewer"}).status_code == 403


def test_reviewer_upload_403(c):
    did = _shared(c, "reviewer")
    r = c.post(f"/api/docs/{did}/files", files={"f": ("a.png", b"x")})
    assert r.status_code == 403


def test_editor_save_200(c):
    did = _shared(c, "editor")
    assert c.post(f"/api/docs/{did}/save", json={"content": "edit"}).status_code == 200
    assert c.get(f"/api/docs/{did}").status_code == 200
