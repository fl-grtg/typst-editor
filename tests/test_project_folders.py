"""Project folders: nested paths (max 2 levels), empty folders, rename and delete with their contents, document moves."""
import threading

import pytest
from conftest import put_file, register_user
from fastapi import HTTPException

from backend import db, mcp_fs
from backend.services import project_files


def make(c):
    register_user(c, "alice")
    did = c.post("/api/docs/create", json={"title": "Main", "content": "x"}).json()["id"]
    pid = c.get(f"/api/docs/{did}").json()["project_id"]
    return pid, did


def upload(c, pid, name, data=b"png"):
    return put_file(c, pid, name, data)


def paths(c, pid):
    return [f["path"] for f in c.get(f"/api/projects/{pid}").json()["files"]]


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
    assert upload(c, pid, ok + "/ok.typ", b"").status_code == 200
    assert upload(c, pid, deep + "/no.typ", b"").status_code == 400
    assert c.post(f"/api/projects/{pid}/docs", json={"title": "Deep", "folder": deep}).status_code == 400
    assert c.post(f"/api/projects/{pid}/docs", json={"title": "Fine", "folder": ok}).status_code == 200


def test_rename_folder_moves_files_docs_and_empty_children(c):
    pid, did = make(c)
    put_file(c, pid, "lib/util.typ", b"u")
    assert upload(c, pid, "lib/pic.png").status_code == 200
    other = c.post(f"/api/projects/{pid}/docs", json={"title": "Ch1", "folder": "lib"}).json()["id"]
    c.post(f"/api/projects/{pid}/folders", json={"path": "lib/empty"})
    # the empty child would land on three levels: rejected before anything moves
    assert c.post(f"/api/projects/{pid}/folders/rename", json={"path": "lib", "target": "parts/lib"}).status_code == 400
    assert c.delete(f"/api/projects/{pid}/folders", params={"path": "lib/empty"}).status_code == 200
    r = c.post(f"/api/projects/{pid}/folders/rename", json={"path": "lib", "target": "parts/lib"})
    assert r.status_code == 200, r.text
    p = c.get(f"/api/projects/{pid}").json()
    assert [f["path"] for f in p["files"]] == ["parts/lib/pic.png", "parts/lib/util.typ"]
    assert {d["id"]: d["folder"] for d in p["documents"]}[other] == "parts/lib"
    assert set(p["folders"]) == {"parts", "parts/lib"}
    assert c.get(f"/api/projects/{pid}/files/parts/lib/pic.png").status_code == 200
    assert c.get(f"/api/projects/{pid}/files/lib/pic.png").status_code == 404


def test_rename_folder_checks_depth_collisions_and_self_move(c):
    pid, did = make(c)
    put_file(c, pid, "a/b/x.typ", b"")
    put_file(c, pid, "z/x.typ", b"")
    assert c.post(f"/api/projects/{pid}/folders/rename", json={"path": "a", "target": "q/r"}).status_code == 400  # would become q/r/b/x.typ, 3 levels
    assert c.post(f"/api/projects/{pid}/folders/rename", json={"path": "a/b", "target": "z"}).status_code == 409  # z/x.typ exists
    assert c.post(f"/api/projects/{pid}/folders/rename", json={"path": "a", "target": "a/inner"}).status_code == 400
    assert paths(c, pid) == ["a/b/x.typ", "z/x.typ"]


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
    response = c.post(f"/api/projects/{pid}/import-zip", data={"folder": deep},
                      files={"f": ("source.zip", b"not a zip", "application/zip")})
    assert response.status_code == 400
    assert "levels deep" in response.text






def test_rename_keeps_legacy_deep_paths_but_never_adds_a_level(c):
    pid, did = make(c)
    with db.tx() as con:
        con.execute("UPDATE docs SET folder='a/b/c' WHERE id=?", (did,))
        project_files.put(con, pid, "a/b/c/m.typ", b"", {})
        con.execute("INSERT INTO project_folders VALUES (?,?,?)", (pid, "a/b/c", db.now_iso()))
    assert c.post(f"/api/projects/{pid}/folders/rename", json={"path": "a", "target": "z"}).status_code == 200
    payload = c.get(f"/api/projects/{pid}").json()
    assert [(d["title"], d["folder"]) for d in payload["documents"]] == [("Main", "z/b/c")]
    assert [r["path"] for r in payload["files"]] == ["z/b/c/m.typ"]
    assert "z/b/c" in payload["folders"]
    # A two-level target would push the legacy folders to four: rejected.
    assert c.post(f"/api/projects/{pid}/folders/rename", json={"path": "z", "target": "x/y"}).status_code == 400


def test_file_move_keeps_legacy_deep_paths_but_never_adds_a_level(c):
    pid, did = make(c)
    with db.tx() as con:
        project_files.put(con, pid, "a/b/c/old.typ", b"x", {})
    body = {"path": "a/b/c/old.typ", "target": "a/b/c/new.typ"}
    preview = c.post(f"/api/projects/{pid}/files-move-preview", json=body)
    assert preview.status_code == 200, preview.text
    moved = c.post(f"/api/projects/{pid}/files-move", json={**body, "version": preview.json()["version"]})
    assert moved.status_code == 200, moved.text
    assert paths(c, pid) == ["a/b/c/new.typ"]
    assert c.post(f"/api/projects/{pid}/files-move-preview", json={"path": "a/b/c/new.typ", "target": "a/b/c/d/deep.typ"}).status_code == 400




def test_delete_folder_trashes_its_contents_and_document_move(c):
    pid, did = make(c)
    put_file(c, pid, "keep/m.typ", b"")
    assert c.post(f"/api/projects/{pid}/docs/{did}/folder", json={"folder": "chapters"}).json() == {"folder": "chapters", "updated_references": 0}
    deleted = c.delete(f"/api/projects/{pid}/folders", params={"path": "keep"}).json()
    assert deleted["ok"] is True and deleted["documents"] == [] and len(deleted["trash_ids"]) == 1
    assert paths(c, pid) == []
    assert c.delete(f"/api/projects/{pid}/folders", params={"path": "chapters"}).json()["documents"] == [did]
    assert c.get(f"/api/docs/{did}").status_code == 410


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
    assert upload(c, pid, "lib/pic.png").status_code == 200
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
    assert not t.is_alive(), "folder rename deadlocked on its own files lock"
    assert out["r"].status_code == 200, out["r"].text
    assert paths(c, pid) == ["parts/pic.png"]


def test_rename_folder_onto_existing_file_is_a_clean_409(c):
    pid, did = make(c)
    assert upload(c, pid, "a/x.txt").status_code == 200
    assert upload(c, pid, "b").status_code == 200
    r = c.post(f"/api/projects/{pid}/folders/rename", json={"path": "a", "target": "b"})
    assert r.status_code == 409, r.text
    assert paths(c, pid) == ["a/x.txt", "b"]


def test_folder_path_rejects_empty_aliases(c):
    pid, did = make(c)
    for raw in (".", "/", "./"):
        assert c.post(f"/api/projects/{pid}/folders", json={"path": raw}).status_code == 400
    assert c.get(f"/api/projects/{pid}").json()["folders"] == []
    assert upload(c, pid, "a/x.txt").status_code == 200
    assert c.post(f"/api/projects/{pid}/folders/rename", json={"path": "a", "target": "."}).status_code == 400
    assert paths(c, pid) == ["a/x.txt"]


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


def _title(c, pid):
    return c.get(f"/api/projects/{pid}").json()["title"]


def test_agent_paths_separate_equal_titles_by_folder(c):
    pid, _ = make(c)
    a = c.post(f"/api/projects/{pid}/docs", json={"title": "Chapter", "folder": "a"}).json()["id"]
    b = c.post(f"/api/projects/{pid}/docs", json={"title": "Chapter", "folder": "b"}).json()["id"]
    assert c.put(f"/api/projects/{pid}/files/b/pic.png", content=b"x").status_code == 200
    ctx, name = mcp_fs.Ctx("alice"), _title(c, pid)
    assert mcp_fs.resolve(ctx, f"/{name}/a/Chapter")["doc_id"] == a
    assert mcp_fs.resolve(ctx, f"/{name}/b/Chapter.typ")["doc_id"] == b
    pic = mcp_fs.resolve(ctx, f"/{name}/b/pic.png")
    assert (pic["kind"], pic["name"], pic["path"]) == ("file", "b/pic.png", f"/{name}/b/pic.png")
    with pytest.raises(HTTPException) as e:
        mcp_fs.resolve(ctx, f"/{name}/Chapter")
    assert e.value.status_code == 404


def test_agent_paths_nested_same_name_new_file_and_trashed(c):
    pid, did = make(c)
    assert c.post(f"/api/projects/{pid}/folders", json={"path": "A"}).status_code == 200
    nested = c.post(f"/api/projects/{pid}/docs", json={"title": "A", "folder": "A"}).json()["id"]
    ctx, name = mcp_fs.Ctx("alice"), _title(c, pid)
    assert mcp_fs.resolve(ctx, f"/{name}/A/A")["doc_id"] == nested
    new = mcp_fs.resolve(ctx, f"/{name}/A/A/file.typ", create=True)
    assert (new["kind"], new["name"]) == ("new_file", "A/A/file.typ")
    assert mcp_fs.resolve(ctx, f"/{name}/A/B", create=True)["kind"] == "new_doc"
    gone = c.post(f"/api/projects/{pid}/docs", json={"title": "Gone"}).json()["id"]
    assert c.delete(f"/api/docs/{gone}").status_code == 200
    with pytest.raises(HTTPException) as e:
        mcp_fs.resolve(ctx, f"/{name}/Gone")
    assert e.value.status_code == 404
    assert did
