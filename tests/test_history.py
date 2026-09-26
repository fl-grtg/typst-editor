from conftest import login, make_doc, register_user


def test_snapshot_crud(c):
    register_user(c, "alice")
    did = make_doc(c, "Verlauf", content="v1")
    sid = c.post(f"/api/docs/{did}/snapshots", json={"label": "eins"}).json()["id"]
    assert c.get(f"/api/docs/{did}/snapshots").json()["snapshots"]
    assert c.get(f"/api/docs/{did}/snapshots/{sid}").json()["content"] == "v1"
    assert c.post(f"/api/docs/{did}/save", json={"content": "v2"}).status_code == 200
    assert c.post(f"/api/docs/{did}/snapshots/{sid}/restore").status_code == 200
    assert c.get(f"/api/docs/{did}").json()["content"] == "v1"
    assert c.delete(f"/api/docs/{did}/snapshots/{sid}").status_code == 200
    assert c.get(f"/api/docs/{did}/snapshots/{sid}").status_code == 404


def test_reviewer_snapshot_403(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "Verlauf2")
    sid = c.post(f"/api/docs/{did}/snapshots", json={}).json()["id"]
    c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "reviewer"})
    login(c, "bob")
    assert c.post(f"/api/docs/{did}/snapshots", json={}).status_code == 403
    assert c.post(f"/api/docs/{did}/snapshots/{sid}/restore").status_code == 403
    assert c.delete(f"/api/docs/{did}/snapshots/{sid}").status_code == 403
    assert c.get(f"/api/docs/{did}/snapshots").status_code == 200
