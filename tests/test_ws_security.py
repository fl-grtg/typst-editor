import pytest
from conftest import login, make_doc, register_user
from fastapi.websockets import WebSocketDisconnect
from pycrdt import Doc, Text

from backend import sync


def _step1(sv=None):
    if sv is None:
        sv = Doc().get_state()
    return sync.blob(sync.write_var(sync.MSG_SYNC), sync.write_var(sync.STEP1),
                     sync.write_var(len(sv)), sv)


def _parse(data):
    t, p = sync.read_var(data, 0)
    st, p = sync.read_var(data, p)
    ln, p = sync.read_var(data, p)
    return t, st, data[p:p + ln]


def _update_msg(doc):
    upd = doc.get_update()
    return sync.blob(sync.write_var(sync.MSG_SYNC), sync.write_var(sync.UPDATE),
                     sync.write_var(len(upd)), upd)


def test_reviewer_update_dropped(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "WS-Rev", content="basis")
    c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "reviewer"})
    login(c, "bob")
    with c.websocket_connect(f"/ws/{did}") as ws:
        ws.receive_bytes()
        rdoc = Doc()
        ws.send_bytes(_step1())
        _, _, diff = _parse(ws.receive_bytes())
        rdoc.apply_update(diff)
        rtext = rdoc.get("typst", type=Text)
        rtext += "REVIEWER-XYZ"
        ws.send_bytes(_update_msg(rdoc))
        ws.send_bytes(_step1(rdoc.get_state()))
        ws.receive_bytes()
    login(c, "alice")
    with c.websocket_connect(f"/ws/{did}") as ws:
        ws.receive_bytes()
        odoc = Doc()
        ws.send_bytes(_step1())
        _, _, diff = _parse(ws.receive_bytes())
        odoc.apply_update(diff)
    assert "REVIEWER-XYZ" not in str(odoc.get("typst", type=Text))
    assert "basis" in str(odoc.get("typst", type=Text))


def test_trash_kicks_ws(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "WS-Trash")
    with c.websocket_connect(f"/ws/{did}") as ws:
        ws.receive_bytes()
        assert c.delete(f"/api/docs/{did}").json()["trashed"] is True
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_bytes()
    assert e.value.code == 4403


def test_ws_2mb_cap_4409(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "WS-Cap")
    with c.websocket_connect(f"/ws/{did}") as ws:
        ws.receive_bytes()
        ws.send_bytes(b"\x00" * (2 * 1024 * 1024 + 1))
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_bytes()
    assert e.value.code == 4409
