import pytest


@pytest.mark.parametrize("path", ["/backend/main.py", "/data/app.db", "/.git/HEAD"])
def test_static_leak_404(c, path):
    assert c.get(path).status_code == 404
