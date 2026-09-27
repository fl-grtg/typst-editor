"""Smoke: /healthz + login->create->share->export (TestClient, no browser)."""
from conftest import login, make_doc, register_user


def test_smoke(c):
    assert c.get("/healthz").json() == {"ok": True}
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "Smoke")
    assert c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "editor"}).status_code == 200
    r = c.get("/api/export.zip")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
