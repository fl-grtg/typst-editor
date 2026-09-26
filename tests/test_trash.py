from conftest import login, make_doc, register_user


def test_delete_twice_gone(c):
    register_user(c, "alice")
    did = make_doc(c, "Papierkorb")
    assert c.delete(f"/api/docs/{did}").json()["trashed"] is True
    assert c.delete(f"/api/docs/{did}").json()["trashed"] is False
    assert c.get(f"/api/docs/{did}").status_code == 404


def test_trashed_410(c):
    register_user(c, "alice")
    did = make_doc(c, "Papierkorb2")
    c.delete(f"/api/docs/{did}")
    assert c.get(f"/api/docs/{did}").status_code == 410
    assert c.post(f"/api/docs/{did}/save", json={"content": "x"}).status_code == 410


def test_restore(c):
    register_user(c, "alice")
    did = make_doc(c, "Papierkorb3")
    c.delete(f"/api/docs/{did}")
    assert c.post(f"/api/docs/{did}/restore").status_code == 200
    assert c.get(f"/api/docs/{did}").status_code == 200


def test_foreign_restore_403_404(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "Papierkorb4")
    login(c, "bob")
    assert c.post(f"/api/docs/{did}/restore").status_code in (403, 404)
