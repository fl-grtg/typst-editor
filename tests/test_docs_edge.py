"""Docs/search/trash/dup edge: empty title, unicode folder, dup with files/quota."""
from types import SimpleNamespace

from conftest import make_doc, register_user

from backend import config as backend_config
from backend import main as backend_main


def test_empty_title_400(c):
    register_user(c, "alice")
    assert c.post("/api/docs/create", json={"title": ""}).status_code == 400
    assert c.post("/api/docs/create", json={"title": "   "}).status_code == 400
    did = make_doc(c, "Ok")
    assert c.post(f"/api/docs/{did}/rename", json={"title": ""}).status_code == 400


def test_unicode_folder(c):
    register_user(c, "alice")
    name = "Ünïcödé 📁"
    assert c.post("/api/folders", json={"folder": name}).status_code == 200
    did = make_doc(c, "Uni")
    assert c.post(f"/api/docs/{did}/folder", json={"folder": name}).status_code == 200
    folders = c.get("/api/folders").json()["folders"]
    assert any(f["folder"] == name for f in folders)
    assert c.get(f"/api/docs/{did}").json()["folder"] == name


def test_duplicate_copies_files(c):
    register_user(c, "alice")
    did = make_doc(c, "MitDatei")
    assert c.post(f"/api/docs/{did}/files", files={"f": ("bild.png", b"abc")}).status_code == 200
    nid = c.post(f"/api/docs/{did}/duplicate").json()["id"]
    names = [f["name"] for f in c.get(f"/api/docs/{nid}/files").json()["files"]]
    assert "bild.png" in names


def test_duplicate_quota_413(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "Voll", content="x" * 100)
    used = backend_main.user_bytes("alice")
    real = backend_config.load()
    monkeypatch.setattr(backend_config, "load",
                        lambda: SimpleNamespace(**{**vars(real), "MAX_BYTES_PER_USER": used}))
    assert c.post(f"/api/docs/{did}/duplicate").status_code == 413


def test_folders_rename_duplicate_merges_docs(c):
    # Current behaviour: rename onto an existing name -> 200, docs are moved
    # (UPDATE OR IGNORE: the old folder entry may remain with n=0).
    register_user(c, "alice")
    did = make_doc(c, "DupRename")
    assert c.post("/api/folders", json={"folder": "A"}).status_code == 200
    assert c.post("/api/folders", json={"folder": "B"}).status_code == 200
    assert c.post(f"/api/docs/{did}/folder", json={"folder": "A"}).status_code == 200
    assert c.post("/api/folders/rename", json={"old": "A", "new": "B"}).status_code == 200
    assert c.get(f"/api/docs/{did}").json()["folder"] == "B"
    folders = {f["folder"]: f["n"] for f in c.get("/api/folders").json()["folders"]}
    assert folders.get("B") == 1


def test_folders_rename_unicode(c):
    register_user(c, "alice")
    name = "Ünïcödé Ordner"
    assert c.post("/api/folders", json={"folder": "Alt"}).status_code == 200
    assert c.post("/api/folders/rename", json={"old": "Alt", "new": name}).status_code == 200
    folders = c.get("/api/folders").json()["folders"]
    assert any(f["folder"] == name for f in folders)


def test_folders_rename_length_matrix(c):
    # FOLDER_MAX=40: exakt 40 ok, 41 -> 400 (Validation-Handler mappt auf 400),
    # leer/gleich -> 400.
    register_user(c, "alice")
    assert c.post("/api/folders", json={"folder": "Kurz"}).status_code == 200
    ok40 = "y" * 40
    assert c.post("/api/folders/rename", json={"old": "Kurz", "new": ok40}).status_code == 200
    assert c.post("/api/folders/rename", json={"old": ok40, "new": "x" * 41}).status_code == 400
    assert c.post("/api/folders/rename", json={"old": ok40, "new": ok40}).status_code == 400
    assert c.post("/api/folders/rename", json={"old": "", "new": "x"}).status_code == 400
    assert c.post("/api/folders/rename", json={"old": ok40, "new": "  "}).status_code == 400
