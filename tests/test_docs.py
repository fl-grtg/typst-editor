from conftest import make_doc, register_user


def test_create_save_rename(c):
    register_user(c, "alice")
    did = make_doc(c, "A")
    assert c.post(f"/api/docs/{did}/save", json={"content": "neu"}).status_code == 200
    assert c.get(f"/api/docs/{did}").json()["content"] == "neu"
    assert c.post(f"/api/docs/{did}/rename", json={"title": "B"}).status_code == 200
    assert c.get(f"/api/docs/{did}").json()["title"] == "B"


def test_duplicate_title_400(c):
    register_user(c, "alice")
    make_doc(c, "Gleich")
    r = c.post("/api/docs/create", json={"title": "Gleich"})
    assert r.status_code == 400


def test_duplicate_trash_restore(c):
    register_user(c, "alice")
    did = make_doc(c, "Orig")
    nid = c.post(f"/api/docs/{did}/duplicate").json()["id"]
    assert nid != did
    assert c.delete(f"/api/docs/{did}").json()["trashed"] is True
    assert c.post(f"/api/docs/{did}/restore").status_code == 200
    assert c.get(f"/api/docs/{did}").status_code == 200


def test_save_over_limit_400(c):
    register_user(c, "alice")
    did = make_doc(c, "Gross")
    r = c.post(f"/api/docs/{did}/save", json={"content": "x" * 200_001})
    assert r.status_code == 400
