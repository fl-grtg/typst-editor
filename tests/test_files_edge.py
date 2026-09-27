"""Files edge: avatar happy path, idempotent delete, 200KB limit."""
from conftest import make_doc, register_user

PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQ"
       "DwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def test_avatar_upload_and_get(c):
    register_user(c, "alice")
    assert c.post("/api/me/avatar", json={"img": PNG}).status_code == 200
    assert c.get("/api/me").json()["hasAvatar"] is True
    r = c.get("/api/avatar/alice")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert len(r.content) > 0


def test_avatar_delete_then_404(c):
    register_user(c, "alice")
    assert c.post("/api/me/avatar", json={"img": PNG}).status_code == 200
    assert c.delete("/api/me/avatar").status_code == 200
    assert c.get("/api/avatar/alice").status_code == 404


def test_delete_file_idempotent(c):
    register_user(c, "alice")
    did = make_doc(c, "Dateien")
    assert c.post(f"/api/docs/{did}/files", files={"f": ("bild.png", b"abc")}).status_code == 200
    assert c.delete(f"/api/docs/{did}/files/bild.png").status_code == 200
    assert c.delete(f"/api/docs/{did}/files/bild.png").status_code == 200  # second time ok
    assert c.get(f"/api/docs/{did}/files/bild.png").status_code == 404


def test_text_save_boundary(c):
    register_user(c, "alice")
    did = make_doc(c, "Grenze")
    assert c.post(f"/api/docs/{did}/files/kurz.typ/text", json={"content": "x" * 199999}).status_code == 200
    assert c.post(f"/api/docs/{did}/files/kurz.typ/text", json={"content": "x" * 200000}).status_code == 200
    assert c.post(f"/api/docs/{did}/files/kurz.typ/text", json={"content": "x" * 200001}).status_code == 400
