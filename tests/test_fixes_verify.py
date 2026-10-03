from types import SimpleNamespace

import pytest
from conftest import login, make_doc, register_user
from fastapi.websockets import WebSocketDisconnect
from pycrdt import Doc, Text
from ws_helpers import _parse, _step1, _update_msg

from backend import config as backend_config
from backend import db, ratelimit, sync
from backend import main as backend_main


def test_api_docs_lists_own(c):
    register_user(c, "alice")
    did = make_doc(c, "Listed", content="hi")
    body = c.get("/api/docs").json()
    assert did in [d["id"] for d in body["own"]]
    assert body["trash"] == []


def test_save_force_409(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Force", content="basis")
    with c.websocket_connect(f"/ws/{did}") as ws:
        ws.receive_bytes()
        doc = Doc()
        ws.send_bytes(_step1())
        _, _, diff = _parse(ws.receive_bytes())
        doc.apply_update(diff)
        with doc.transaction():
            doc.get("typst", type=Text).__iadd__(" live-extra")
        ws.send_bytes(_update_msg(doc))
        assert c.post(f"/api/docs/{did}/save", json={"content": "basis"}).status_code == 409
        assert c.post(f"/api/docs/{did}/save", json={"content": "basis", "force": True}).status_code == 200
    assert c.get(f"/api/docs/{did}").json()["content"] == "basis"


def test_search_limit_20(c):
    register_user(c, "alice")
    for i in range(21):
        if i == 15:
            ratelimit.clear()
        make_doc(c, f"Bulk{i}", content="uniquekeyword xyz")
    hits = c.get("/api/search", params={"q": "uniquekeyword"}).json()["hits"]
    assert len(hits) == 20


def test_members_forbidden(c):
    register_user(c, "alice")
    register_user(c, "bob")
    register_user(c, "eve")
    login(c, "alice")
    did = make_doc(c, "Team2")
    c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "reviewer"})
    login(c, "bob")
    assert c.get(f"/api/docs/{did}/members").status_code == 200
    login(c, "eve")
    assert c.get(f"/api/docs/{did}/members").status_code == 404  # need_access hides existence


def test_ws_auth_expiry(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "WSExp", content="basis")
    with c.websocket_connect(f"/ws/{did}") as ws:
        ws.receive_bytes()
        c.post("/api/logout")
        sync._sess_cache.clear()
        doc = Doc()
        try:
            ws.send_bytes(_step1())
            ws.send_bytes(_update_msg(doc))
        except Exception:
            pass
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_bytes()
    assert e.value.code == 4403


def test_trash_write_window(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "WSWindow", content="basis")
    with c.websocket_connect(f"/ws/{did}") as ws:
        ws.receive_bytes()
        con = db.connect()
        try:
            con.execute("UPDATE docs SET trashed=1 WHERE id=?", (did,))
            con.commit()
        finally:
            con.close()
        sync._sess_cache.clear()
        doc = Doc()
        ws.send_bytes(_step1())
        ws.send_bytes(_update_msg(doc))
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_bytes()
    assert e.value.code == 4403


def test_bootstrap_first_user(c, monkeypatch):
    monkeypatch.setenv("REGISTRATION", "invite-only")
    monkeypatch.setenv("REGISTRATION_INVITE_TOKEN", "")
    r1 = c.post("/api/register", json={"username": "first", "password": "pass1234"})
    assert r1.status_code == 403
    c.post("/api/logout")
    r2 = c.post("/api/register", json={"username": "second", "password": "pass1234"})
    assert r2.status_code == 403


def test_quota_race_serial(c, monkeypatch):
    register_user(c, "alice")
    did = make_doc(c, "Race", content="x" * 100)
    before = c.get("/api/docs").json()
    n_before = len(before["own"])
    used = backend_main.user_bytes("alice")
    real = backend_config.load()
    monkeypatch.setattr(backend_config, "load",
                        lambda: SimpleNamespace(**{**vars(real), "MAX_BYTES_PER_USER": used}))
    assert c.post(f"/api/docs/{did}/duplicate").status_code == 413
    assert c.post("/api/docs/create", json={"title": "NoRoom", "content": "y"}).status_code == 413
    after = c.get("/api/docs").json()
    assert len(after["own"]) == n_before
    assert c.get(f"/api/docs/{did}").json()["content"] == "x" * 100
