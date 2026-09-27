from conftest import make_doc, register_user


def test_tplfolders_create_list(c):
    register_user(c, "alice")
    assert c.post("/api/tplfolders", json={"folder": "Briefe"}).status_code == 200
    folders = c.get("/api/tplfolders").json()["folders"]
    assert {"folder": "Briefe", "n": 0} in folders


def test_templates_save_move_folder(c):
    register_user(c, "alice")
    assert c.post("/api/tplfolders", json={"folder": "A"}).status_code == 200
    assert c.post("/api/tplfolders", json={"folder": "B"}).status_code == 200
    assert c.post("/api/templates", json={"name": "a.typ", "content": "Hallo", "folder": "A"}).status_code == 200
    assert c.post("/api/templates/a.typ/folder", json={"folder": "B"}).status_code == 200
    tpls = c.get("/api/templates").json()["templates"]
    assert [t["name"] for t in tpls] == ["a.typ"]
    assert tpls[0]["folder"] == "B"
    folders = {f["folder"]: f["n"] for f in c.get("/api/tplfolders").json()["folders"]}
    assert folders.get("B") == 1


def test_tplfolders_rename_drop(c):
    register_user(c, "alice")
    make_doc(c, "x")
    assert c.post("/api/tplfolders", json={"folder": "Alt"}).status_code == 200
    assert c.post("/api/templates", json={"name": "b.typ", "content": "Hi", "folder": "Alt"}).status_code == 200
    assert c.post("/api/tplfolders/rename", json={"old": "Alt", "new": "Neu"}).status_code == 200
    tpls = c.get("/api/templates").json()["templates"]
    assert tpls[0]["folder"] == "Neu"
    assert c.delete("/api/tplfolders/Neu").status_code == 200
    assert c.get("/api/tplfolders").json()["folders"] == []
    assert c.get("/api/templates").json()["templates"][0]["folder"] == ""
