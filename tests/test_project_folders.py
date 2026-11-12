"""Project folders: nested paths (max 2 levels), empty folders, rename, document moves."""
import threading

from conftest import register_user

from backend import db


def make(c):
    register_user(c, "alice")
    did = c.post("/api/docs/create", json={"title": "Main", "content": "x"}).json()["id"]
    pid = c.get(f"/api/docs/{did}").json()["project_id"]
    return pid, did


def upload(c, did, name, data=b"png"):
    return c.post(f"/api/docs/{did}/files", files={"f": (name, data, "application/octet-stream")})


def test_empty_folders_persist_and_show_in_payload(c):
    pid, _ = make(c)
    assert c.post(f"/api/projects/{pid}/folders", json={"path": "img/raw"}).status_code == 200
    assert c.get(f"/api/projects/{pid}").json()["folders"] == ["img", "img/raw"]
    assert c.delete(f"/api/projects/{pid}/folders", params={"path": "img"}).status_code == 200
    assert c.get(f"/api/projects/{pid}").json()["folders"] == []


def test_depth_is_capped_for_new_names_only(c):
    pid, did = make(c)
    assert c.post(f"/api/projects/{pid}/folders", json={"path": "a/b/c"}).status_code == 400
    assert c.post(f"/api/projects/{pid}/resources", json={"name": "a/b/ok.typ", "content": ""}).status_code == 200
    assert c.post(f"/api/projects/{pid}/resources", json={"name": "a/b/c/no.typ", "content": ""}).status_code == 400
    assert upload(c, did, "a/b/pic.png").status_code == 200
    assert upload(c, did, "a/b/c/pic.png").status_code == 400
    assert c.post(f"/api/projects/{pid}/docs", json={"title": "Deep", "folder": "a/b/c"}).status_code == 400
    assert c.post(f"/api/projects/{pid}/docs", json={"title": "Fine", "folder": "a/b"}).status_code == 200


def test_rename_folder_moves_modules_files_docs_and_empty_children(c):
    pid, did = make(c)
    c.post(f"/api/projects/{pid}/resources", json={"name": "lib/util.typ", "content": "u"})
    assert upload(c, did, "lib/pic.png").status_code == 200
    other = c.post(f"/api/projects/{pid}/docs", json={"title": "Ch1", "folder": "lib"}).json()["id"]
    c.post(f"/api/projects/{pid}/folders", json={"path": "lib/empty"})
    r = c.post(f"/api/projects/{pid}/folders/rename", json={"path": "lib", "target": "parts/lib"})
    assert r.status_code == 200, r.text
    p = c.get(f"/api/projects/{pid}").json()
    assert [x["name"] for x in p["resources"]] == ["parts/lib/util.typ"]
    assert [f["name"] for f in p["files"]] == ["parts/lib/pic.png"]
    assert {d["id"]: d["folder"] for d in p["documents"]}[other] == "parts/lib"
    assert set(p["folders"]) == {"parts", "parts/lib", "parts/lib/empty"}
    assert c.get(f"/api/docs/{did}/files/parts/lib/pic.png").status_code == 200
    assert c.get(f"/api/docs/{did}/files/lib/pic.png").status_code == 404


def test_rename_folder_checks_depth_collisions_and_self_move(c):
    pid, did = make(c)
    c.post(f"/api/projects/{pid}/resources", json={"name": "a/b/x.typ", "content": ""})
    c.post(f"/api/projects/{pid}/resources", json={"name": "z/x.typ", "content": ""})
    assert c.post(f"/api/projects/{pid}/folders/rename", json={"path": "a", "target": "q/r"}).status_code == 400  # would become q/r/b/x.typ
    assert c.post(f"/api/projects/{pid}/folders/rename", json={"path": "a/b", "target": "z"}).status_code == 409  # z/x.typ exists
    assert c.post(f"/api/projects/{pid}/folders/rename", json={"path": "a", "target": "a/inner"}).status_code == 400
    assert [x["name"] for x in c.get(f"/api/projects/{pid}").json()["resources"]] == ["a/b/x.typ", "z/x.typ"]


def test_delete_folder_only_when_empty_and_document_move(c):
    pid, did = make(c)
    c.post(f"/api/projects/{pid}/resources", json={"name": "keep/m.typ", "content": ""})
    assert c.delete(f"/api/projects/{pid}/folders", params={"path": "keep"}).status_code == 409
    assert c.post(f"/api/projects/{pid}/docs/{did}/folder", json={"folder": "chapters"}).json() == {"folder": "chapters"}
    assert c.delete(f"/api/projects/{pid}/folders", params={"path": "chapters"}).status_code == 409
    assert c.post(f"/api/projects/{pid}/docs/{did}/folder", json={"folder": ""}).status_code == 200
    assert c.delete(f"/api/projects/{pid}/folders", params={"path": "chapters"}).status_code == 200


def test_viewer_cannot_touch_folders(c):
    from conftest import login
    pid, _ = make(c)
    register_user(c, "bob")
    login(c, "alice")
    c.post(f"/api/projects/{pid}/members", json={"username": "bob", "role": "reviewer"})
    login(c, "bob")
    assert c.post(f"/api/projects/{pid}/folders", json={"path": "x"}).status_code == 403
    assert c.post(f"/api/projects/{pid}/folders/rename", json={"path": "x", "target": "y"}).status_code == 403


def test_rename_folder_with_stale_snapshot_does_not_deadlock(c):
    pid, did = make(c)
    assert upload(c, did, "lib/pic.png").status_code == 200
    assert c.post(f"/api/projects/{pid}/folders", json={"path": "lib"}).status_code == 200
    con = db.connect()
    try:
        con.execute("UPDATE project_snapshots SET created_at='2020-01-01T00:00:00+00:00' WHERE project_id=?", (pid,))
        con.commit()
    finally:
        con.close()
    out = {}

    def worker():
        out["r"] = c.post(f"/api/projects/{pid}/folders/rename", json={"path": "lib", "target": "parts"})

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(5)
    assert not t.is_alive(), "folder rename deadlocked on its own upload lock"
    assert out["r"].status_code == 200, out["r"].text
    assert [f["name"] for f in c.get(f"/api/docs/{did}/files").json()["files"]] == ["parts/pic.png"]


def test_rename_folder_onto_existing_file_is_a_clean_409(c):
    pid, did = make(c)
    assert upload(c, did, "a/x.txt").status_code == 200
    assert upload(c, did, "b").status_code == 200
    r = c.post(f"/api/projects/{pid}/folders/rename", json={"path": "a", "target": "b"})
    assert r.status_code == 409, r.text
    assert [f["name"] for f in c.get(f"/api/docs/{did}/files").json()["files"]] == ["a/x.txt", "b"]


def test_folder_path_rejects_empty_aliases(c):
    pid, did = make(c)
    for raw in (".", "/", "./"):
        assert c.post(f"/api/projects/{pid}/folders", json={"path": raw}).status_code == 400
    assert c.get(f"/api/projects/{pid}").json()["folders"] == []
    assert upload(c, did, "a/x.txt").status_code == 200
    assert c.post(f"/api/projects/{pid}/folders/rename", json={"path": "a", "target": "."}).status_code == 400
    assert [f["name"] for f in c.get(f"/api/docs/{did}/files").json()["files"]] == ["a/x.txt"]
