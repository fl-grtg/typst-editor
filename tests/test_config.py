from backend import config


def test_defaults():
    cfg = config.load()
    assert cfg.REGISTRATION == "invite-only"
    assert cfg.HOST == "127.0.0.1"
    assert cfg.PORT == 8978


def test_closed_403(c, monkeypatch):
    assert c.post("/api/register", json={"username": "first", "password": "pass1234"}).status_code == 200
    monkeypatch.setenv("REGISTRATION", "closed")
    assert c.post("/api/register", json={"username": "neu1", "password": "pass1234"}).status_code == 403


def test_invite_only(c, monkeypatch):
    assert c.post("/api/register", json={"username": "first", "password": "pass1234"}).status_code == 200
    monkeypatch.setenv("REGISTRATION", "invite-only")
    monkeypatch.setenv("REGISTRATION_INVITE_TOKEN", "geheim")
    b = {"username": "neu2", "password": "pass1234"}
    assert c.post("/api/register", json=b).status_code == 403
    assert c.post("/api/register", json={**b, "invite": "falsch"}).status_code == 403
    assert c.post("/api/register", json={**b, "invite": "geheim"}).status_code == 200
