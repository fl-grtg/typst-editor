from conftest import login, make_doc, register_user, wait_for
from pycrdt import Doc, Text
from ws_helpers import _parse, _step1, _update_msg

from backend import sync


def test_snapshot_crud(c):
    register_user(c, "alice")
    did = make_doc(c, "Verlauf", content="v1")
    sid = c.post(f"/api/docs/{did}/snapshots", json={"label": "eins"}).json()["id"]
    assert c.get(f"/api/docs/{did}/snapshots").json()["snapshots"]
    assert c.get(f"/api/docs/{did}/snapshots/{sid}").json()["content"] == "v1"
    assert c.post(f"/api/docs/{did}/save", json={"content": "v2"}).status_code == 200
    assert c.post(f"/api/docs/{did}/snapshots/{sid}/restore").status_code == 200
    assert c.get(f"/api/docs/{did}").json()["content"] == "v1"
    assert c.delete(f"/api/docs/{did}/snapshots/{sid}").status_code == 200
    assert c.get(f"/api/docs/{did}/snapshots/{sid}").status_code == 404


def test_reviewer_snapshot_403(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "Verlauf2")
    sid = c.post(f"/api/docs/{did}/snapshots", json={}).json()["id"]
    c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "reviewer"})
    login(c, "bob")
    assert c.post(f"/api/docs/{did}/snapshots", json={}).status_code == 403
    assert c.post(f"/api/docs/{did}/snapshots/{sid}/restore").status_code == 403
    assert c.delete(f"/api/docs/{did}/snapshots/{sid}").status_code == 403
    assert c.get(f"/api/docs/{did}/snapshots").status_code == 200


def test_snapshot_get_single_404(c):
    register_user(c, "alice")
    did = make_doc(c, "VerlaufSnap404", content="v1")
    sid = c.post(f"/api/docs/{did}/snapshots", json={"label": "eins"}).json()["id"]
    assert c.get(f"/api/docs/{did}/snapshots/{sid}").status_code == 200
    assert c.get(f"/api/docs/{did}/snapshots/s_falsch").status_code == 404
    assert c.get(f"/api/docs/{did}/snapshots/{sid}x").status_code == 404


def test_snapshot_get_access_matrix(c):
    # IST-Matrix: reviewer darf einzelnen Snapshot lesen, Fremder bekommt 404
    # (need_access -> 404, kein 403, um Existenz zu verbergen).
    register_user(c, "alice")
    register_user(c, "bob")
    register_user(c, "carol")
    login(c, "alice")
    did = make_doc(c, "VerlaufMatrix", content="v1")
    sid = c.post(f"/api/docs/{did}/snapshots", json={}).json()["id"]
    c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "reviewer"})
    login(c, "bob")
    assert c.get(f"/api/docs/{did}/snapshots").status_code == 200
    assert c.get(f"/api/docs/{did}/snapshots/{sid}").status_code == 200
    login(c, "carol")
    assert c.get(f"/api/docs/{did}/snapshots").status_code == 404
    assert c.get(f"/api/docs/{did}/snapshots/{sid}").status_code == 404
    assert c.get(f"/api/docs/{did}/snapshots/s_falsch").status_code == 404


def test_restore_404(c):
    register_user(c, "alice")
    did = make_doc(c, "Verlauf3", content="v1")
    c.post(f"/api/docs/{did}/snapshots", json={"label": "eins"})
    assert c.post(f"/api/docs/{did}/snapshots/s_falsch/restore").status_code == 404


def test_restore_409_force(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Verlauf4", content="basis")
    sid = c.post(f"/api/docs/{did}/snapshots", json={"label": "eins"}).json()["id"]
    with c.websocket_connect(f"/ws/{did}") as ws:
        ws.receive_bytes()
        doc = Doc()
        ws.send_bytes(_step1())
        _, _, diff = _parse(ws.receive_bytes())
        doc.apply_update(diff)
        with doc.transaction():
            doc.get("typst", type=Text).__iadd__(" live1")
        ws.send_bytes(_update_msg(doc))
        wait_for(lambda: "live1" in (c.get(f"/api/docs/{did}").json().get("content") or ""),
                 msg="live1 not synced")
        with doc.transaction():
            doc.get("typst", type=Text).__iadd__(" live2")
        ws.send_bytes(_update_msg(doc))
        wait_for(lambda: (sync.room_text(did) or "").endswith(" live1 live2"),
                 msg="live2 not synced")
        assert c.post(f"/api/docs/{did}/snapshots/{sid}/restore").status_code == 409
        assert c.post(f"/api/docs/{did}/snapshots/{sid}/restore", json={"force": True}).status_code == 200
