"""API keys: bearer auth, expiry, role and mode containment."""
import re

from conftest import register_user

from backend import db

KEY_RE = re.compile(r"^tpe_[0-9a-f]{8}_[0-9a-f]{32}$")


def make_key(c, role="editor", expires=None, name="agent"):
    body = {"name": name, "role": role}
    if expires is not None:
        body["expires_in_days"] = expires
    r = c.post("/api/keys", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_keys_bearer_ok_and_rejected(c):
    register_user(c, "u1")
    created = make_key(c, role="editor")
    assert KEY_RE.fullmatch(created["key"])
    assert created["prefix"] in created["key"]
    # bearer ok
    r = c.get("/api/keys", headers={"Authorization": f"Bearer {created['key']}"})
    assert r.status_code == 200, r.text
    assert r.json()["keys"][0]["prefix"] == created["prefix"]
    assert all("key" not in k for k in r.json()["keys"])  # secret shown once only
    # hash only in db
    con = db.connect()
    try:
        row = con.execute("SELECT key_hash, prefix FROM api_keys WHERE id=?",
                          (created["id"],)).fetchone()
        assert row["key_hash"] != created["key"] and len(row["key_hash"]) == 64
        assert row["prefix"] == created["prefix"]
    finally:
        con.close()
    # rejected: garbage, no auth
    assert c.get("/api/keys", headers={"Authorization": "Bearer tpe_deadbeef_deadbeefdeadbeefdeadbeef"}).status_code == 401
    c.post("/api/logout")
    assert c.get("/api/keys").status_code == 401


def test_keys_revoke_and_expiry(c):
    register_user(c, "u1")
    created = make_key(c)
    hdr = {"Authorization": f"Bearer {created['key']}"}
    assert c.get("/api/keys", headers=hdr).status_code == 200
    assert c.delete(f"/api/keys/{created['id']}", headers=hdr).status_code == 200
    assert c.get("/api/keys", headers=hdr).status_code == 401  # revoked
    assert c.get("/api/keys").json()["keys"] == []  # gone from list
    # expired
    created2 = make_key(c, name="short")
    con = db.connect()
    try:
        con.execute("UPDATE api_keys SET expires_at=? WHERE id=?", ("2000-01-01T00:00:00", created2["id"]))
        con.commit()
    finally:
        con.close()
    assert c.get("/api/keys", headers={"Authorization": f"Bearer {created2['key']}"}).status_code == 401


def test_keys_role_containment(c):
    register_user(c, "u1")
    k = make_key(c, role="reviewer")
    hdr = {"Authorization": f"Bearer {k['key']}"}
    r = c.post("/api/keys", json={"name": "esc", "role": "editor"}, headers=hdr)
    assert r.status_code == 403  # reviewer key cannot mint editor keys
    r = c.post("/api/keys", json={"name": "ok", "role": "reviewer"}, headers=hdr)
    assert r.status_code == 200


def test_keys_role_update_keeps_secret(c):
    register_user(c, "u1")
    k = make_key(c, role="reviewer")
    hdr = {"Authorization": f"Bearer {k['key']}"}
    assert c.post("/api/keys", json={"name": "esc", "role": "editor"}, headers=hdr).status_code == 403
    r = c.patch(f"/api/keys/{k['id']}", json={"role": "editor"})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "editor"
    # same secret, now editor: no new key, no new prefix
    listed = c.get("/api/keys", headers=hdr).json()["keys"]
    assert [(x["id"], x["prefix"], x["role"]) for x in listed] == [(k["id"], k["prefix"], "editor")]
    assert c.post("/api/keys", json={"name": "now", "role": "editor"}, headers=hdr).status_code == 200
    # and back down again: the token survives both directions
    assert c.patch(f"/api/keys/{k['id']}", json={"role": "reviewer"}).status_code == 200
    assert c.post("/api/keys", json={"name": "nope", "role": "editor"}, headers=hdr).status_code == 403


def test_keys_role_update_guards(c):
    register_user(c, "u1")
    k = make_key(c, role="reviewer")
    hdr = {"Authorization": f"Bearer {k['key']}"}
    # a reviewer key cannot promote itself or others above its own cap
    assert c.patch(f"/api/keys/{k['id']}", json={"role": "editor"}, headers=hdr).status_code == 403
    assert c.patch(f"/api/keys/{k['id']}", json={"role": "owner"}).status_code == 400
    assert c.patch("/api/keys/k_missing", json={"role": "editor"}).status_code == 404
    assert c.delete(f"/api/keys/{k['id']}").status_code == 200
    assert c.patch(f"/api/keys/{k['id']}", json={"role": "editor"}).status_code == 404


def test_key_mode_is_stored_listed_and_changeable(c):
    register_user(c, "u1")
    k = make_key(c)
    assert c.get("/api/keys").json()["keys"][0]["mode"] == "auto"
    assert c.post("/api/keys", json={"name": "careful", "role": "editor", "mode": "propose"}).json()["mode"] == "propose"
    assert c.post("/api/keys", json={"name": "bad", "role": "editor", "mode": "yolo"}).status_code == 400
    r = c.patch(f"/api/keys/{k['id']}", json={"mode": "direct"})
    assert r.status_code == 200 and r.json() == {"ok": True, "id": k["id"], "role": "editor", "mode": "direct"}
    assert c.patch(f"/api/keys/{k['id']}", json={}).status_code == 400
