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
