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


def test_unicode_project_replaces_document_folders(c):
    register_user(c, "alice")
    name = "Ünïcödé 📁"
    result = c.post("/api/projects", json={"title": name})
    assert result.status_code == 200
    pid = result.json()["id"]
    did = c.post(f"/api/projects/{pid}/docs", json={"title": "Uni"}).json()["id"]
    assert c.get(f"/api/docs/{did}").json()["project_id"] == pid
    assert c.get(f"/api/projects/{pid}").json()["title"] == name
    assert c.post(f"/api/docs/{did}/folder", json={"folder": name}).status_code == 410


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


def test_project_rename_conflict_preserves_both_projects(c):
    register_user(c, "alice")
    first = c.post("/api/projects", json={"title": "A"}).json()["id"]
    second = c.post("/api/projects", json={"title": "B"}).json()["id"]
    assert c.post(f"/api/projects/{first}/rename", json={"title": "B"}).status_code == 409
    assert c.get(f"/api/projects/{first}").json()["title"] == "A"
    assert c.get(f"/api/projects/{second}").json()["title"] == "B"
    assert c.post("/api/folders/rename", json={"old": "A", "new": "B"}).status_code == 410


def test_projects_rename_unicode(c):
    register_user(c, "alice")
    pid = c.post("/api/projects", json={"title": "Alt"}).json()["id"]
    name = "Ünïcödé Projekt"
    assert c.post(f"/api/projects/{pid}/rename", json={"title": name}).status_code == 200
    assert c.get(f"/api/projects/{pid}").json()["title"] == name


def test_projects_rename_length_matrix(c):
    register_user(c, "alice")
    pid = c.post("/api/projects", json={"title": "Kurz"}).json()["id"]
    path = f"/api/projects/{pid}/rename"
    valid = "y" * 100
    assert c.post(path, json={"title": valid}).status_code == 200
    assert c.post(path, json={"title": "x" * 101}).status_code == 400
    assert c.post(path, json={"title": valid}).status_code == 200
    assert c.post(path, json={"title": ""}).status_code == 400
    assert c.post(path, json={"title": "  "}).status_code == 400
