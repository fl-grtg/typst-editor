"""WS edge: broadcast, reconnect, awareness flood, corrupt Yjs, origin."""
import pytest
from conftest import login, make_doc, register_user
from fastapi.websockets import WebSocketDisconnect
from pycrdt import Doc, Text

from backend import db, sync
from backend.constants import AWARE_MAX


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


def test_broadcast_two_clients(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "BC", content="basis")
    with c.websocket_connect(f"/ws/{did}") as wa:
        wa.receive_bytes()
        with c.websocket_connect(f"/ws/{did}") as wb:
            wb.receive_bytes()
            adoc = Doc()
            wa.send_bytes(_step1())
            t, st, diff = _parse(wa.receive_bytes())
            assert (t, st) == (sync.MSG_SYNC, sync.STEP2)
            adoc.apply_update(diff)
            with adoc.transaction():
                txt = adoc.get("typst", type=Text)
                txt += "HALLO-BC"
            wa.send_bytes(_update_msg(adoc))
            t2, st2, payload = _parse(wb.receive_bytes())
            assert (t2, st2) == (sync.MSG_SYNC, sync.UPDATE)
            assert len(payload) > 0


def test_reconnect_keeps_text(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "RC", content="start")
    with c.websocket_connect(f"/ws/{did}") as ws:
        ws.receive_bytes()
        doc = Doc()
        ws.send_bytes(_step1())
        _, _, diff = _parse(ws.receive_bytes())
        doc.apply_update(diff)
        with doc.transaction():
            txt = doc.get("typst", type=Text)
            txt += "-v2"
        ws.send_bytes(_update_msg(doc))
    with c.websocket_connect(f"/ws/{did}") as ws2:
        ws2.receive_bytes()
        doc2 = Doc()
        ws2.send_bytes(_step1())
        _, _, diff2 = _parse(ws2.receive_bytes())
        doc2.apply_update(diff2)
    txt2 = str(doc2.get("typst", type=Text))
    assert "start" in txt2
    assert "-v2" in txt2


def test_awareness_flood_dropped(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "AW")
    with c.websocket_connect(f"/ws/{did}") as wa:
        wa.receive_bytes()
        with c.websocket_connect(f"/ws/{did}") as wb:
            wb.receive_bytes()
            big = sync.blob(sync.write_var(sync.MSG_AWARENESS), b"x" * (AWARE_MAX + 1))
            wa.send_bytes(big)  # huge cursor: drop instead of broadcast
            wb.send_bytes(_step1())  # B gets answer instead of flood
            t, st, _ = _parse(wb.receive_bytes())
            assert (t, st) == (sync.MSG_SYNC, sync.STEP2)
            wa.send_bytes(_step1())  # A still alive too
            t, st, _ = _parse(wa.receive_bytes())
            assert (t, st) == (sync.MSG_SYNC, sync.STEP2)


def test_corrupt_yjs_rebuild(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "KR", content="heil-text")
    con = db.connect()
    try:
        con.execute("UPDATE docs SET yjs=? WHERE id=?", (b"\x00\x01\x02kaputt", did))
        con.commit()
    finally:
        con.close()
    with c.websocket_connect(f"/ws/{did}") as ws:
        ws.receive_bytes()
        doc = Doc()
        ws.send_bytes(_step1())
        _, _, diff = _parse(ws.receive_bytes())
        doc.apply_update(diff)
    assert "heil-text" in str(doc.get("typst", type=Text))


def test_origin_rejected(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "OR")
    with c.websocket_connect(f"/ws/{did}",
                             headers={"origin": "http://evil.example"}) as ws:
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_bytes()
    assert e.value.code == 4403
    with c.websocket_connect(f"/ws/{did}",
                             headers={"origin": "http://testserver"}) as ws:
        t, st, _ = _parse(ws.receive_bytes())
        assert (t, st) == (sync.MSG_SYNC, sync.STEP1)
