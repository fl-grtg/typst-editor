"""C10: proxy/startup gates.

With TRUST_PROXY=true the app must only honor X-Forwarded-* from peers in
FORWARDED_ALLOW_IPS — otherwise any direct client can spoof its IP (rotate
rate-limit buckets) or scheme (force Secure cookies / HSTS). Startup refuses
an effectively-open allowlist combined with TRUST_PROXY=true.
"""
from types import SimpleNamespace

import pytest
from conftest import register_user

import backend.main as main
from backend import config


def _stub_req(peer="testclient", xff="", proto="http", scheme="http"):
    return SimpleNamespace(
        headers={"x-forwarded-for": xff, "x-forwarded-proto": proto},
        client=SimpleNamespace(host=peer) if peer is not None else None,
        url=SimpleNamespace(scheme=scheme),
    )


# --- allowlist parsing ---

@pytest.mark.parametrize("peer,allow,want", [
    ("127.0.0.1", "127.0.0.1,::1", True),
    ("::1", "127.0.0.1,::1", True),
    ("::1", "127.0.0.1, ::1", True),  # spaces ok
    ("172.20.0.2", "127.0.0.1,::1", False),
    ("172.20.0.2", "127.0.0.1,::1,172.16.0.0/12", True),  # compose bridge
    ("172.32.0.2", "172.16.0.0/12", False),
    ("1.2.3.4", "*", True),  # runtime matches; startup refuses the combo
    ("1.2.3.4", "", False),
    ("1.2.3.4", "garbage-entry", False),  # invalid entries never widen trust
    ("1.2.3.4", "garbage-entry, 1.2.3.4", True),  # ...but valid ones still apply
    ("::1", "[::1]", True),  # brackets normalized the same way
    ("::1", "[::1], 10.0.0.0/8", True),
    ("1.2.3.4", "[*]", True),  # runtime matches; startup refuses the combo
    ("203.0.113.7", "[0.0.0.0/0]", True),  # runtime matches; startup refuses
    ("testclient", "127.0.0.1,::1", False),  # unparseable peer never trusted
    ("", "127.0.0.1,::1", False),
])
def test_peer_allowed_matrix(peer, allow, want):
    assert main._proxy_peer_allowed(peer, allow) is want


def test_config_default_and_env(monkeypatch):
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    assert config.load().FORWARDED_ALLOW_IPS == "127.0.0.1,::1"
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "10.0.0.0/8")
    assert config.load().FORWARDED_ALLOW_IPS == "10.0.0.0/8"


# --- startup gate ---

def _cfg(trust, allow):
    return SimpleNamespace(TRUST_PROXY=trust, FORWARDED_ALLOW_IPS=allow)


@pytest.mark.parametrize("allow", ["*", "0.0.0.0/0", "::/0", "127.0.0.1, *", "[*]", "[0.0.0.0/0]", "[::/0]"])
def test_startup_refuses_open_allowlist(allow):
    with pytest.raises(SystemExit):
        main._proxy_startup_check(_cfg(True, allow))


@pytest.mark.parametrize("trust,allow", [
    (True, "127.0.0.1,::1"),
    (True, "172.16.0.0/12"),
    (True, ""),  # empty fails closed (headers ignored), warn only
    (False, "*"),  # gate inactive without TRUST_PROXY
    (False, ""),
])
def test_startup_accepts_safe_combos(trust, allow):
    main._proxy_startup_check(_cfg(trust, allow))  # must not raise


# --- request helpers honor the gate ---

def test_client_ip_ignores_spoofed_xff_by_default(c):
    assert main.client_ip(_stub_req(xff="9.9.9.9")) == "testclient"


def test_client_ip_trusted_peer_uses_xff(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY", "true")
    assert main.client_ip(_stub_req(peer="127.0.0.1", xff="9.9.9.9, 10.0.0.1")) == "9.9.9.9"


def test_client_ip_untrusted_peer_ignores_xff(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY", "true")
    assert main.client_ip(_stub_req(peer="203.0.113.7", xff="9.9.9.9")) == "203.0.113.7"


def test_cookie_secure_spoofed_proto_ignored(monkeypatch):
    monkeypatch.setenv("TRUST_PROXY", "true")
    assert main._cookie_secure(_stub_req(peer="203.0.113.7", proto="https")) is False
    assert main._cookie_secure(_stub_req(peer="127.0.0.1", proto="https")) is True


def test_hsts_not_forced_by_spoofed_proto(c, monkeypatch):
    # Untrusted peer + TRUST_PROXY=true: X-Forwarded-Proto must not trigger HSTS.
    monkeypatch.setenv("TRUST_PROXY", "true")
    r = c.get("/api/me", headers={"x-forwarded-proto": "https"})
    assert r.status_code == 401  # unauthenticated, but middleware still ran
    assert "strict-transport-security" not in r.headers


def test_ratelimit_buckets_peer_not_spoofed_xff(c, monkeypatch):
    # 10 bad logins from the same TCP peer with rotating X-Forwarded-For must
    # still trip the per-minute login bucket on the 11th (distinct usernames
    # keep the per-user bucket out of the way).
    monkeypatch.setenv("TRUST_PROXY", "true")
    register_user(c, "alice")
    for i in range(10):
        r = c.post("/api/login", json={"username": f"ghost{i}", "password": "wrongpass1"},
                   headers={"x-forwarded-for": f"10.1.2.{i}"})
        assert r.status_code == 401, (i, r.text)
    r = c.post("/api/login", json={"username": "ghostX", "password": "wrongpass1"},
               headers={"x-forwarded-for": "10.9.9.9"})
    assert r.status_code == 429, r.text  # pre-fix: 401 (fresh spoofed bucket)
