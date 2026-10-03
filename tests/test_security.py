def test_csp_on_root(c):
    r = c.get("/")
    assert r.status_code == 200
    assert "default-src 'self'" in r.headers.get("content-security-policy", "")


def test_no_hsts_on_http(c):
    assert "strict-transport-security" not in c.get("/").headers


def test_healthz(c):
    assert c.get("/healthz").json() == {"ok": True}


def test_api_unknown_404(c):
    assert c.get("/api/unknown").status_code == 404


def test_source_db_git_404(c):
    for p in ("/backend/main.py", "/data/app.db", "/.git/HEAD"):
        assert c.get(p).status_code == 404


def test_cache_header_matrix(c):
    assert c.get("/").headers.get("cache-control") == "no-store"
    assert c.get("/api/me").headers.get("cache-control") == "no-store"
    assert c.get("/vendor-cm.js").headers.get("cache-control") == "public, max-age=31536000, immutable"
    assert c.get("/sw.js").status_code == 404  # worker dropped, no route serves it
    assert c.get("/manifest.json").headers.get("cache-control") == "public, max-age=31536000, immutable"
    assert c.get("/icon-192.png").headers.get("cache-control") == "public, max-age=31536000, immutable"
    assert c.get("/icon-512.png").headers.get("cache-control") == "public, max-age=31536000, immutable"
    assert c.get("/icon.svg").headers.get("cache-control") == "public, max-age=31536000, immutable"
