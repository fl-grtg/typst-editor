"""Room rebuild must never duplicate content (yjs authoritative, content seed only)."""
from conftest import make_doc, register_user
from pycrdt import Doc, Text

from backend import db, sync


def _room_text(doc_id):
    return str(sync.rooms[doc_id]["doc"].get("typst", type=Text))


def _seeded_update(content):
    d = Doc()
    with d.transaction():
        t = d.get("typst", type=Text)
        t += content
    return d.get_update()


def test_rebuild_with_yjs_and_content_no_dup(c):
    register_user(c, "u1")
    did = make_doc(c, "D", "= Introduction\nhello")
    sync.rooms.pop(did, None)
    r1 = sync.room(did)
    assert _room_text(did) == "= Introduction\nhello"
    assert r1["dirty"] is False
    # Drop + rebuild (restart/evict path): must stay 1x, not 2x.
    sync.rooms.pop(did, None)
    r2 = sync.room(did)
    assert _room_text(did) == "= Introduction\nhello"
    assert r2["dirty"] is False
    sync.rooms.pop(did, None)
    sync.room(did)
    assert _room_text(did) == "= Introduction\nhello"


def test_corrupt_yjs_falls_back_to_content_once(c):
    register_user(c, "u1")
    did = make_doc(c, "D", "= Introduction\nhello")
    db.save_room(did, b"\x00\x01\x02broken", "= Introduction\nhello")
    sync.rooms.pop(did, None)
    sync.room(did)
    assert _room_text(did) == "= Introduction\nhello"


def test_persist_flush_idempotent(c):
    register_user(c, "u1")
    did = make_doc(c, "D", "= Introduction\nhello")
    sync.room(did)
    for _ in range(3):
        assert sync.persist(did) is True
    sync.flush_all()
    row = db.connect().execute(
        "SELECT content FROM docs WHERE id=?", (did,)).fetchone()
    assert row["content"] == "= Introduction\nhello"


def test_seeded_update_rebuild_no_dup(c):
    # yjs blob + content written together (as save_room does): rebuild stays 1x.
    register_user(c, "u1")
    did = make_doc(c, "D", "= Introduction\nhello")
    db.save_room(did, _seeded_update("= Introduction\nhello"),
                 "= Introduction\nhello")
    sync.rooms.pop(did, None)
    sync.room(did)
    assert _room_text(did) == "= Introduction\nhello"
