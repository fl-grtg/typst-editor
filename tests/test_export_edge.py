"""Export edge: too big -> 413, spam -> 429 (happy path + prune live in test_backup)."""
import io
import zipfile

from conftest import make_doc, register_user

from backend.routers import export as export_routes


def test_export_too_big_413(c, monkeypatch):
    register_user(c, "alice")
    make_doc(c, "Gross", content="x" * 100)
    monkeypatch.setattr(export_routes, "EXPORT_MAX", 10)
    assert c.get("/api/export.zip").status_code == 413


def test_export_ratelimit_429(c):
    register_user(c, "alice")
    make_doc(c, "Backup", content="inhalt")
    for _ in range(5):
        assert c.get("/api/export.zip").status_code == 200
    assert c.get("/api/export.zip").status_code == 429


def test_export_includes_templates(c):
    register_user(c, "alice")
    make_doc(c, "Backup", content="inhalt")
    r = c.post("/api/templates", json={"name": "brief.typ", "content": "vorlage"})
    assert r.status_code == 200, r.text
    r = c.get("/api/export.zip")
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert z.read("templates/brief.typ").decode() == "vorlage"
    assert any("Backup" in n for n in z.namelist())
