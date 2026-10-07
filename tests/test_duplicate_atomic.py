"""B9: duplicate publishes the file tree atomically (stage + os.replace).

Edge matrix: success copies content+files with no staging leftovers; a copy
failure rolls back the DB row and leaves neither dst nor staging behind; a
replace failure does the same; stale staging dirs are swept at startup;
sequential duplicates de-conflict titles.
"""
import shutil

from conftest import login, make_doc, register_user

import backend.main as main


def _files_dir():
    return main.get_files_dir()


def _list_docs(c):
    return c.get("/api/docs").json()


def test_duplicate_copies_content_and_files(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Original", content="hello dup")
    (fd := _files_dir() / did).mkdir(parents=True, exist_ok=True)
    (fd / "img.png").write_bytes(b"\x89PNG-abc")
    (fd / "notes.typ").write_text("sidecar", encoding="utf-8")
    (fd / "scratch.tmp.abc").write_text("inflight", encoding="utf-8")  # never copied
    r = c.post(f"/api/docs/{did}/duplicate")
    assert r.status_code == 200, r.text
    nid = r.json()["id"]
    assert nid != did
    got = c.get(f"/api/docs/{nid}").json()
    assert got["content"] == "hello dup"
    assert got["title"] == "Original (copy)"
    names = sorted(p.name for p in (_files_dir() / nid).iterdir() if p.is_file())
    assert names == ["img.png", "notes.typ"]
    assert (_files_dir() / nid / "img.png").read_bytes() == b"\x89PNG-abc"
    # No staging leftovers anywhere under files/.
    leftovers = [p.name for p in _files_dir().iterdir() if ".tmp.dup-" in p.name]
    assert leftovers == []


def test_duplicate_titles_deconflict(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Deconflict")
    n1 = c.post(f"/api/docs/{did}/duplicate").json()["id"]
    n2 = c.post(f"/api/docs/{did}/duplicate").json()["id"]
    t1 = c.get(f"/api/docs/{n1}").json()["title"]
    t2 = c.get(f"/api/docs/{n2}").json()["title"]
    assert (t1, t2) == ("Deconflict (copy)", "Deconflict (copy) 2")


def test_duplicate_copy_failure_rolls_back(c, monkeypatch):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "FailCopy")
    (fd := _files_dir() / did).mkdir(parents=True, exist_ok=True)
    (fd / "a.bin").write_bytes(b"x" * 64)
    before = {d["id"] for d in _list_docs(c)["own"]}

    real_copytree = shutil.copytree

    def boom(src, dst, **kw):
        real_copytree(src, dst, **kw)
        (dst / "partial.bin").write_bytes(b"partial")  # crash mid-publish
        raise OSError("disk on fire")

    monkeypatch.setattr("shutil.copytree", boom)
    r = c.post(f"/api/docs/{did}/duplicate")
    assert r.status_code == 500, r.text
    after = {d["id"] for d in _list_docs(c)["own"]}
    assert after == before  # DB row rolled back
    # Neither the final dir nor any staging dir survived.
    assert [p for p in _files_dir().iterdir()
            if p.name.startswith(".tmp.dup-")] == []
    assert len([p for p in _files_dir().iterdir() if p.is_dir() and p.name not in (did,)]) == 0


def test_duplicate_replace_failure_rolls_back(c, monkeypatch):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "FailReplace")
    (fd := _files_dir() / did).mkdir(parents=True, exist_ok=True)
    (fd / "a.bin").write_bytes(b"y")
    before = {d["id"] for d in _list_docs(c)["own"]}
    import os as _os

    def boom_replace(a, b):
        raise OSError("rename failed")

    monkeypatch.setattr(_os, "replace", boom_replace)
    r = c.post(f"/api/docs/{did}/duplicate")
    assert r.status_code == 500, r.text
    assert {d["id"] for d in _list_docs(c)["own"]} == before
    assert [p for p in _files_dir().iterdir() if ".tmp.dup-" in p.name] == []


def test_stale_staging_swept_at_startup(c):
    stale = _files_dir() / ".tmp.dup-d_stale123"
    stale.mkdir(parents=True, exist_ok=True)
    (stale / "orphan.bin").write_bytes(b"z")
    counts = main.reap_trash_dirs()
    assert counts["removed"] >= 1
    assert not stale.exists()


def test_duplicate_without_files_dir(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "NoFiles")
    assert not (_files_dir() / did).exists()
    nid = c.post(f"/api/docs/{did}/duplicate").json()["id"]
    assert c.get(f"/api/docs/{nid}").json()["content"] == "hi"
    assert not (_files_dir() / nid).exists()  # nothing staged, nothing published


def test_duplicate_reviewer_forbidden(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "NoDupReview")
    assert c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "reviewer"}).status_code == 200
    login(c, "bob")
    assert c.post(f"/api/docs/{did}/duplicate").status_code == 403
    login(c, "alice")
    assert c.post(f"/api/docs/{did}/duplicate").status_code == 200  # owner ok


def test_duplicate_nested_subdir_published_atomically(c):
    # Subdirectories ride along in the staged tree and appear only via the rename.
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Nested")
    sub = _files_dir() / did / "assets"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / "logo.svg").write_text("<svg/>", encoding="utf-8")
    nid = c.post(f"/api/docs/{did}/duplicate").json()["id"]
    assert (_files_dir() / nid / "assets" / "logo.svg").read_text(encoding="utf-8") == "<svg/>"
    assert [p for p in _files_dir().iterdir() if ".tmp.dup-" in p.name] == []


def test_duplicate_target_exists_rolls_back(c, monkeypatch):
    # A pre-existing dst (nid collision / leftover) is refused, never merged:
    # DB row rolled back, dst untouched, no staging left.
    from backend import db as _db

    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Collision")
    (fd := _files_dir() / did).mkdir(parents=True, exist_ok=True)
    (fd / "payload.bin").write_bytes(b"copy me")
    before = {d["id"] for d in _list_docs(c)["own"]}
    monkeypatch.setattr(_db, "new_id", lambda prefix="": "d_fixeddup1")
    clash = _files_dir() / "d_fixeddup1"
    clash.mkdir(parents=True, exist_ok=True)
    (clash / "sentinel.txt").write_text("not yours", encoding="utf-8")
    r = c.post(f"/api/docs/{did}/duplicate")
    assert r.status_code == 500, r.text
    assert {d["id"] for d in _list_docs(c)["own"]} == before
    assert (clash / "sentinel.txt").read_text(encoding="utf-8") == "not yours"
    assert [p for p in _files_dir().iterdir() if ".tmp.dup-" in p.name] == []
