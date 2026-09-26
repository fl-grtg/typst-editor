from conftest import login, make_doc, register_user


def _setup(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "Kommentare")
    c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "reviewer"})
    cid = c.post(f"/api/docs/{did}/comments", json={"anchor": 3, "text": "oben"}).json()["id"]
    return did, cid


def test_create_list_reply(c):
    did, cid = _setup(c)
    rid = c.post(f"/api/docs/{did}/comments", json={"anchor": 0, "text": "antwort", "parent_id": cid}).json()["id"]
    comments = c.get(f"/api/docs/{did}/comments").json()["comments"]
    assert [t["id"] for t in comments] == [cid]
    assert [r["id"] for r in comments[0]["replies"]] == [rid]


def test_invalid_400(c):
    did, cid = _setup(c)
    assert c.post(f"/api/docs/{did}/comments", json={"anchor": 0, "text": "   "}).status_code == 400
    assert c.post(f"/api/docs/{did}/comments", json={"anchor": -1, "text": "x"}).status_code in (400, 422)  # Pydantic-Bound oder Code-Check
    rid = c.post(f"/api/docs/{did}/comments", json={"anchor": 0, "text": "r", "parent_id": cid}).json()["id"]
    assert c.post(f"/api/docs/{did}/comments", json={"anchor": 0, "text": "rr", "parent_id": rid}).status_code == 400


def test_edit_author_only(c):
    did, cid = _setup(c)
    login(c, "bob")
    assert c.post(f"/api/docs/{did}/comments/{cid}/edit", json={"text": "fremd"}).status_code == 403
    login(c, "alice")
    assert c.post(f"/api/docs/{did}/comments/{cid}/edit", json={"text": "neu"}).status_code == 200


def test_resolve(c):
    did, cid = _setup(c)
    assert c.post(f"/api/docs/{did}/comments/{cid}/resolve", json={"resolved": True}).status_code == 200
    login(c, "bob")
    assert c.post(f"/api/docs/{did}/comments/{cid}/resolve", json={"resolved": False}).status_code == 403
    bcid = c.post(f"/api/docs/{did}/comments", json={"anchor": 0, "text": "von bob"}).json()["id"]
    login(c, "alice")
    assert c.post(f"/api/docs/{did}/comments/{bcid}/resolve", json={"resolved": True}).status_code == 200


def test_delete_removes_replies(c):
    did, cid = _setup(c)
    c.post(f"/api/docs/{did}/comments", json={"anchor": 0, "text": "r", "parent_id": cid})
    assert c.delete(f"/api/docs/{did}/comments/{cid}").status_code == 200
    assert c.get(f"/api/docs/{did}/comments").json()["comments"] == []
