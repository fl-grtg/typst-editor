import pytest
from conftest import login, make_doc, register_user
from fastapi.websockets import WebSocketDisconnect
from ws_helpers import _parse, _step1

from backend import sync


def test_no_token_4403(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "WS")
    c.post("/api/logout")
    with c.websocket_connect(f"/ws/{did}") as ws:
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_bytes()
    assert e.value.code == 4403


def test_editor_step1_step2(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "WS2")
    with c.websocket_connect(f"/ws/{did}") as ws:
        t, st, _ = _parse(ws.receive_bytes())
        assert (t, st) == (sync.MSG_SYNC, sync.STEP1)
        ws.send_bytes(_step1())
        t, st, _ = _parse(ws.receive_bytes())
        assert (t, st) == (sync.MSG_SYNC, sync.STEP2)


def test_reviewer_connects(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "WS3")
    c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "reviewer"})
    login(c, "bob")
    with c.websocket_connect(f"/ws/{did}") as ws:
        t, st, _ = _parse(ws.receive_bytes())
        assert (t, st) == (sync.MSG_SYNC, sync.STEP1)
