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


def test_spa_root_serves_html_with_csp(c):
    # Current behaviour (backend/routers/frontend.py): GET / -> index.html, 200 text/html.
    r = c.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    assert "Content-Security-Policy" in r.headers or "content-security-policy" in r.headers
    assert b"<" in r.content  # html, not JSON


def test_spa_unknown_name_is_404_no_fallback(c):
    # Current behaviour (backend/routers/frontend.py): only FRONT_FILES are served,
    # unknown names -> 404 (no SPA fallback to /).
    assert c.get("/esgibtmichnicht123").status_code == 404
    assert c.get("/api/esgibtmichnicht123").status_code == 404
