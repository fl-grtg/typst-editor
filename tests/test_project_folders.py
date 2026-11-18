"""Project folders: nested paths (max 2 levels), empty folders, rename, document moves."""
import threading

import pytest
from conftest import register_user
from fastapi import HTTPException

from backend import db, mcp_tools


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
    deep = "a/b/c"  # 3 levels: one above the limit
    ok = "a/b"  # 2 levels: allowed
    assert c.post(f"/api/projects/{pid}/folders", json={"path": deep}).status_code == 400
    assert c.post(f"/api/projects/{pid}/resources", json={"name": ok + "/ok.typ", "content": ""}).status_code == 200
    assert c.post(f"/api/projects/{pid}/resources", json={"name": deep + "/no.typ", "content": ""}).status_code == 400
    assert upload(c, did, ok + "/pic.png").status_code == 200
    assert upload(c, did, deep + "/pic.png").status_code == 400
    assert c.post(f"/api/projects/{pid}/docs", json={"title": "Deep", "folder": deep}).status_code == 400
    assert c.post(f"/api/projects/{pid}/docs", json={"title": "Fine", "folder": ok}).status_code == 200


def test_rename_folder_moves_modules_files_docs_and_empty_children(c):
    pid, did = make(c)
    c.post(f"/api/projects/{pid}/resources", json={"name": "lib/util.typ", "content": "u"})
    assert upload(c, did, "lib/pic.png").status_code == 200
    other = c.post(f"/api/projects/{pid}/docs", json={"title": "Ch1", "folder": "lib"}).json()["id"]
    c.post(f"/api/projects/{pid}/folders", json={"path": "lib/empty"})
    # the empty child would land on three levels: rejected before anything moves
    assert c.post(f"/api/projects/{pid}/folders/rename", json={"path": "lib", "target": "parts/lib"}).status_code == 400
    assert c.delete(f"/api/projects/{pid}/folders", params={"path": "lib/empty"}).status_code == 200
    r = c.post(f"/api/projects/{pid}/folders/rename", json={"path": "lib", "target": "parts/lib"})
    assert r.status_code == 200, r.text
    p = c.get(f"/api/projects/{pid}").json()
    assert [x["name"] for x in p["resources"]] == ["parts/lib/util.typ"]
    assert [f["name"] for f in p["files"]] == ["parts/lib/pic.png"]
    assert {d["id"]: d["folder"] for d in p["documents"]}[other] == "parts/lib"
    assert set(p["folders"]) == {"parts", "parts/lib"}
    assert c.get(f"/api/docs/{did}/files/parts/lib/pic.png").status_code == 200
    assert c.get(f"/api/docs/{did}/files/lib/pic.png").status_code == 404


def test_rename_folder_checks_depth_collisions_and_self_move(c):
    pid, did = make(c)
    c.post(f"/api/projects/{pid}/resources", json={"name": "a/b/x.typ", "content": ""})
    c.post(f"/api/projects/{pid}/resources", json={"name": "z/x.typ", "content": ""})
    assert c.post(f"/api/projects/{pid}/folders/rename", json={"path": "a", "target": "q/r"}).status_code == 400  # would become q/r/b/x.typ, 3 levels
    assert c.post(f"/api/projects/{pid}/folders/rename", json={"path": "a/b", "target": "z"}).status_code == 409  # z/x.typ exists
    assert c.post(f"/api/projects/{pid}/folders/rename", json={"path": "a", "target": "a/inner"}).status_code == 400
    assert [x["name"] for x in c.get(f"/api/projects/{pid}").json()["resources"]] == ["a/b/x.typ", "z/x.typ"]


def test_legacy_deep_folders_stay_deletable(c):
    pid, _ = make(c)
    with db.tx() as con:
        con.execute("INSERT INTO project_folders VALUES (?,?,?)", (pid, "a/b/c", db.now_iso()))
    assert c.delete(f"/api/projects/{pid}/folders", params={"path": "a/b/c"}).status_code == 200
    assert c.get(f"/api/projects/{pid}").json()["folders"] == []


def test_document_titles_are_unique_per_folder(c):
    pid, _ = make(c)
    a = c.post(f"/api/projects/{pid}/docs", json={"title": "Chapter", "folder": "a"}).json()["id"]
    c.post(f"/api/projects/{pid}/docs", json={"title": "Chapter", "folder": "b"})
    assert c.post(f"/api/projects/{pid}/docs/{a}/folder", json={"folder": "b"}).status_code == 409  # target folder already has the title
    assert c.post(f"/api/projects/{pid}/folders/rename", json={"path": "a", "target": "b"}).status_code == 409
    assert c.post(f"/api/projects/{pid}/docs/{a}/folder", json={"folder": "c"}).status_code == 200
    assert c.get(f"/api/docs/{a}").json()["folder"] == "c"


def test_zip_import_rejects_a_target_folder_above_the_depth_limit(c):
    pid, _ = make(c)
    deep = "a/b/c"
    response = c.post(f"/api/projects/{pid}/import-zip", data={"title": "ZIP", "folder": deep},
                      files={"f": ("source.zip", b"not a zip", "application/zip")})
    assert response.status_code == 400
    assert "levels deep" in response.text


def test_mcp_project_doc_paths_resolve_folder_qualified_duplicates(c):
    pid, _ = make(c)
    a = c.post(f"/api/projects/{pid}/docs", json={"title": "Chapter", "folder": "a"}).json()["id"]
    b = c.post(f"/api/projects/{pid}/docs", json={"title": "Chapter", "folder": "b"}).json()["id"]
    with pytest.raises(HTTPException) as ambiguous:
        mcp_tools.resolve_path("alice", "owner", f"/projects/{pid}/docs/Chapter")
    assert ambiguous.value.status_code == 409
    assert mcp_tools.resolve_path("alice", "owner", f"/projects/{pid}/docs/a/Chapter")["doc_id"] == a
    resolved = mcp_tools.resolve_path("alice", "owner", f"/projects/{pid}/docs/b/Chapter/pic.png")
    assert (resolved["doc_id"], resolved["filename"]) == (b, "pic.png")


def test_mcp_folder_qualified_doc_wins_when_the_legacy_file_is_missing(c):
    pid, _ = make(c)
    assert c.post(f"/api/projects/{pid}/folders", json={"path": "A"}).status_code == 200
    nested = c.post(f"/api/projects/{pid}/docs", json={"title": "A", "folder": "A"}).json()["id"]
    resolved = mcp_tools.resolve_path("alice", "owner", f"/projects/{pid}/docs/A/A/file.typ")
    assert (resolved["doc_id"], resolved["filename"]) == (nested, "file.typ")


def test_rename_keeps_legacy_deep_paths_but_never_adds_a_level(c):
    pid, did = make(c)
    with db.tx() as con:
        con.execute("UPDATE docs SET folder='a/b/c' WHERE id=?", (did,))
        con.execute("INSERT INTO project_resources VALUES (?,?,?,?)", (pid, "a/b/c/m.typ", "", db.now_iso()))
        con.execute("INSERT INTO project_folders VALUES (?,?,?)", (pid, "a/b/c", db.now_iso()))
    assert c.post(f"/api/projects/{pid}/folders/rename", json={"path": "a", "target": "z"}).status_code == 200
    payload = c.get(f"/api/projects/{pid}").json()
    assert [(d["title"], d["folder"]) for d in payload["documents"]] == [("Main", "z/b/c")]
    assert [r["name"] for r in payload["resources"]] == ["z/b/c/m.typ"]
    assert "z/b/c" in payload["folders"]
    # A two-level target would push the legacy folders to four: rejected.
    assert c.post(f"/api/projects/{pid}/folders/rename", json={"path": "z", "target": "x/y"}).status_code == 400


def test_entry_rename_keeps_legacy_deep_paths_but_never_adds_a_level(c):
    import hashlib
    pid, did = make(c)
    with db.tx() as con:
        con.execute("INSERT INTO project_resources VALUES (?,?,?,?)", (pid, "a/b/c/old.typ", "x", db.now_iso()))
    url = f"/api/projects/{pid}/rename-entry"
    body = {"name": "a/b/c/old.typ", "target": "a/b/c/new.typ"}
    preview = c.post(url + "-preview", json=body)
    assert preview.status_code == 200, preview.text
    renamed = c.post(url, json={**body, "version": preview.json()["version"]})
    assert renamed.status_code == 200, renamed.text
    assert [r["name"] for r in c.get(f"/api/projects/{pid}").json()["resources"]] == ["a/b/c/new.typ"]
    assert c.post(url + "-preview", json={"name": "a/b/c/new.typ", "target": "a/b/c/d/deep.typ"}).status_code == 400
    # Doc-local files use the same depth rule.
    from backend.services.docfiles import store
    store.put(did, "a/b/c/pic.png", b"png")
    with db.tx() as con:
        con.execute("INSERT INTO files(doc_id,path,size,mtime,type) VALUES (?,?,?,?,?)",
                    (did, "a/b/c/pic.png", 3, 0, "binary"))
    version = hashlib.sha256(b"png").hexdigest()
    file_body = {"name": "a/b/c/pic.png", "target": "a/b/c/photo.png", "doc_id": did}
    preview = c.post(url + "-preview", json=file_body).json()
    assert preview["version"] == version
    assert c.post(url, json={**file_body, "version": version}).status_code == 200
    assert c.post(url + "-preview", json={**file_body, "name": "a/b/c/photo.png",
                                          "target": "a/b/c/d/photo.png"}).status_code == 400


def test_mcp_folder_paths_accept_long_segments_and_missing_trashed_nested(c):
    pid, did = make(c)
    long_folder = "x" * 101  # legacy folder segment beyond the document title limit
    with db.tx() as con:
        con.execute("UPDATE docs SET title='Doc', folder=? WHERE id=?", (long_folder, did))
        con.execute("INSERT INTO project_folders VALUES (?,?,?)", (pid, long_folder, db.now_iso()))
    assert mcp_tools.resolve_path("alice", "owner", f"/projects/{pid}/docs/{long_folder}/Doc")["doc_id"] == did

    gone = c.post(f"/api/projects/{pid}/docs", json={"title": "Gone"}).json()["id"]
    assert c.delete(f"/api/docs/{gone}").status_code == 200
    with pytest.raises(HTTPException) as nested:
        mcp_tools.resolve_path("alice", "owner", f"/projects/{pid}/docs/Gone/Missing")
    assert nested.value.status_code == 404
    with pytest.raises(HTTPException) as bare:
        mcp_tools.resolve_path("alice", "owner", f"/projects/{pid}/docs/Gone")
    assert bare.value.status_code == 410


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


def test_rename_cannot_push_documents_or_empty_folders_past_the_depth_limit(c):
    pid, _ = make(c)
    c.post(f"/api/projects/{pid}/docs", json={"title": "Chapter", "folder": "a/b"})
    # a/b -> q/r/b would be three folder levels for the document
    assert c.post(f"/api/projects/{pid}/folders/rename", json={"path": "a", "target": "q/r"}).status_code == 400
    c.post(f"/api/projects/{pid}/folders", json={"path": "e/f"})
    # an empty child folder is held to the same limit
    assert c.post(f"/api/projects/{pid}/folders/rename", json={"path": "e", "target": "m/n"}).status_code == 400
    payload = c.get(f"/api/projects/{pid}").json()
    assert [d["folder"] for d in payload["documents"] if d["title"] == "Chapter"] == ["a/b"]
    assert "e/f" in payload["folders"]
