"""Suggestion / core API correctness + concurrency (isolated tmp DB only)."""
import asyncio
import concurrent.futures
from types import SimpleNamespace

import pytest
from conftest import login, make_doc, register_user
from fastapi import HTTPException

from backend import config as backend_config
from backend import db, deps, sync
from backend import mcp_tools as t
from backend.services import suggestions


def _make_key(c, role="editor", name="agent"):
    r = c.post("/api/keys", json={"name": name, "role": role})
    assert r.status_code == 200, r.text
    return r.json()


def _doc_id(owner, title):
    con = db.connect()
    try:
        return con.execute(
            "SELECT id FROM docs WHERE owner=? AND title=?", (owner, title)
        ).fetchone()["id"]
    finally:
        con.close()


def _db_content(did):
    con = db.connect()
    try:
        r = con.execute("SELECT content, yjs FROM docs WHERE id=?", (did,)).fetchone()
        return r["content"], (bytes(r["yjs"]) if r["yjs"] is not None else None)
    finally:
        con.close()


def _status(cid):
    con = db.connect()
    try:
        r = con.execute(
            "SELECT suggestion_status, resolved FROM comments WHERE id=?", (cid,)
        ).fetchone()
        return (r["suggestion_status"], r["resolved"]) if r else (None, None)
    finally:
        con.close()


def _patch_quota(monkeypatch, cap):
    real = backend_config.load()
    monkeypatch.setattr(
        backend_config, "load", lambda: SimpleNamespace(**{**vars(real), "MAX_BYTES_PER_USER": cap})
    )


def _setup_roles(c):
    register_user(c, "alice")
    register_user(c, "bob")
    register_user(c, "carol")
    register_user(c, "dave")
    login(c, "alice")
    did = make_doc(c, "Rollen", content="alpha beta gamma")
    assert c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "reviewer"}).status_code == 200
    assert c.post(f"/api/docs/{did}/share", json={"username": "carol", "role": "editor"}).status_code == 200
    return did


# --- 1. roles: all may propose, only editor/owner accept/reject ---

def test_all_roles_may_propose(c):
    did = _setup_roles(c)
    login(c, "bob")  # reviewer
    r = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "beta", "new_string": "BETA", "text": "nit"})
    assert r.status_code == 200, r.text
    login(c, "carol")  # editor
    r = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "beta", "new_string": "BETA2"})
    assert r.status_code == 200, r.text
    login(c, "alice")  # owner
    r = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "beta", "new_string": "BETA3"})
    assert r.status_code == 200, r.text
    login(c, "dave")  # stranger: hidden
    r = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "beta", "new_string": "X"})
    assert r.status_code == 404, r.text


def test_only_editor_owner_accept_reject(c):
    did = _setup_roles(c)
    login(c, "bob")
    cid1 = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "beta", "new_string": "B1"}).json()["id"]
    cid2 = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "alpha", "new_string": "A1"}).json()["id"]
    # reviewer cannot accept/reject
    assert c.post(f"/api/docs/{did}/suggestions/{cid1}/accept").status_code == 403
    assert c.post(f"/api/docs/{did}/suggestions/{cid1}/reject").status_code == 403
    # stranger cannot even reach the role check (404 hides existence)
    login(c, "dave")
    assert c.post(f"/api/docs/{did}/suggestions/{cid1}/accept").status_code == 404
    assert c.post(f"/api/docs/{did}/suggestions/{cid1}/reject").status_code == 404
    # editor accepts, owner rejects
    login(c, "carol")
    assert c.post(f"/api/docs/{did}/suggestions/{cid1}/accept").status_code == 200
    login(c, "alice")
    assert c.post(f"/api/docs/{did}/suggestions/{cid2}/reject").status_code == 200
    assert _status(cid1)[0] == "accepted"
    assert _status(cid2)[0] == "rejected"


# --- 2. key caps: reviewer key proposes but never edits ---

def test_mcp_key_caps_suggest_vs_edit(c):
    register_user(c, "alice")
    register_user(c, "bob")
    t.op_create("alice", "owner", "/docs/Plan", "line1\nline2\n")
    login(c, "alice")
    did = _doc_id("alice", "Plan")
    assert c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "reviewer"}).status_code == 200
    # reviewer share + reviewer key may still propose
    out = t.op_suggest("bob", "reviewer", "/shared/alice/Plan", "line1", "LINE1", "nit")
    assert out["status"] == "pending"
    # ... but the same cap cannot edit
    with pytest.raises(HTTPException) as e:
        asyncio.run(t.op_edit("bob", "reviewer", "/shared/alice/Plan", "line2", "LINE2"))
    assert e.value.status_code == 403
    # owner capped to reviewer: suggest ok, edit blocked (min rule)
    out2 = t.op_suggest("alice", "reviewer", "/docs/Plan", "line2", "LINE2")
    assert out2["status"] == "pending"
    with pytest.raises(HTTPException) as e:
        asyncio.run(t.op_edit("alice", "reviewer", "/docs/Plan", "line2", "LINE2"))
    assert e.value.status_code == 403
    # editor key may propose
    assert t.op_suggest("alice", "editor", "/docs/Plan", "line1", "L1")["status"] == "pending"
    # stranger with any key cannot propose (no existence oracle)
    register_user(c, "mallory")
    with pytest.raises(HTTPException) as e:
        t.op_suggest("mallory", "editor", "/shared/alice/Plan", "line1", "X")
    assert e.value.status_code == 404


def test_mcp_list_requires_read(c):
    register_user(c, "alice")
    register_user(c, "bob")
    t.op_create("alice", "owner", "/docs/Geheim", "alpha beta")
    t.op_suggest("alice", "owner", "/docs/Geheim", "beta", "BETA")
    assert len(t.op_suggestions("alice", "owner", "/docs/Geheim")["suggestions"]) == 1
    with pytest.raises(HTTPException) as e:
        t.op_suggestions("bob", "reviewer", "/shared/alice/Geheim")
    assert e.value.status_code == 404


# --- 3. unicode incl. astral + umlauts ---

def test_unicode_umlaut_astral_roundtrip(c):
    register_user(c, "alice")
    content = "Gr\xfc\xdfe \U0001F600 \U0001D11E \U00010348 Zeile\nzweite Zeile \xe4\xf6\xfc"
    login(c, "alice")
    did = make_doc(c, "Unicode", content=content)
    old = "\U0001F600 \U0001D11E"
    new = " Gr\xfc\xdfe \U0001F600 neu "
    r = c.post(f"/api/docs/{did}/suggestions", json={"old_string": old, "new_string": new})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    assert c.post(f"/api/docs/{did}/suggestions/{cid}/accept").status_code == 200
    expect = content.replace(old, new)
    db_content, _ = _db_content(did)
    assert db_content == expect
    assert sync.room_text(did) == expect
    assert t.op_read("alice", "owner", "/docs/Unicode")["content"] == expect


def test_unicode_deletion_and_multibyte_insert(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Loesch", content="a \xe4 \U0001F600 b")
    # propose deletion (empty replacement)
    cid = c.post(
        f"/api/docs/{did}/suggestions", json={"old_string": "\U0001F600 ", "new_string": ""}
    ).json()["id"]
    assert c.post(f"/api/docs/{did}/suggestions/{cid}/accept").status_code == 200
    assert _db_content(did)[0] == "a \xe4 b"
    assert sync.room_text(did) == "a \xe4 b"


# --- 4. source preserved before accept + live/persisted parity ---

def test_create_never_edits_source(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Quelle", content="hello world")
    sync.room(did)
    before_live = sync.room_text(did)
    before_db, before_yjs = _db_content(did)
    cid = c.post(
        f"/api/docs/{did}/suggestions", json={"old_string": "world", "new_string": "there"}
    ).json()["id"]
    assert sync.room_text(did) == before_live == "hello world"
    assert _db_content(did)[0] == before_db == "hello world"
    assert _status(cid) == ("pending", 0)


def test_accept_live_persisted_parity_no_prior_room(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Paritaet", content="one two three")
    assert did not in sync.rooms  # no live room yet
    cid = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "two", "new_string": "2"}).json()["id"]
    assert c.post(f"/api/docs/{did}/suggestions/{cid}/accept").status_code == 200
    db_content, yjs = _db_content(did)
    assert db_content == "one 2 three"
    assert sync.room_text(did) == "one 2 three"
    # persisted yjs decodes to the same text (no split-brain)
    from pycrdt import Doc

    d = Doc()
    d.apply_update(yjs)
    from pycrdt import Text as T

    assert str(d.get("typst", type=T)) == "one 2 three"
    assert sync.rooms[did]["dirty"] is False


def test_accept_live_persisted_parity_with_dirty_room(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Schmutzig", content="persisted base")
    room = sync.room(did)
    # simulate an unflushed live edit (WS dirt): live ahead of DB
    from pycrdt import Text as T

    with sync._doc_lock(room):
        with room["doc"].transaction():
            room["doc"].get("typst", type=T).__iadd__(" +live")
    room["dirty"] = True
    assert sync.room_text(did) == "persisted base +live"
    # suggestion anchors on LIVE text, not the stale DB snapshot
    cid = c.post(
        f"/api/docs/{did}/suggestions", json={"old_string": "+live", "new_string": "+accepted"}
    ).json()["id"]
    assert c.post(f"/api/docs/{did}/suggestions/{cid}/accept").status_code == 200
    expect = "persisted base +accepted"
    assert sync.room_text(did) == expect
    assert _db_content(did)[0] == expect


# --- 5. stale / ambiguous ---

def test_create_rejects_gone_ambiguous_identical(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Anker", content="aaa\nbbb\naaa\n")
    assert c.post(f"/api/docs/{did}/suggestions", json={"old_string": "zzz", "new_string": "Z"}).status_code == 409
    assert c.post(f"/api/docs/{did}/suggestions", json={"old_string": "aaa", "new_string": "A"}).status_code == 409
    assert c.post(f"/api/docs/{did}/suggestions", json={"old_string": "bbb", "new_string": "bbb"}).status_code == 400


def test_accept_stale_gone_and_ambiguous_rollback(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Alt", content="alpha beta gamma")
    cid = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "beta", "new_string": "B"}).json()["id"]
    # foreign edit removes the anchor: accept must 409 and change nothing
    asyncio.run(t.op_edit("alice", "owner", "/docs/Alt", "alpha beta gamma", "alpha gamma"))
    assert sync.room_text(did) is None or "beta" not in (sync.room_text(did) or "")
    r = c.post(f"/api/docs/{did}/suggestions/{cid}/accept")
    assert r.status_code == 409, r.text
    assert _status(cid)[0] == "pending"
    assert _db_content(did)[0] == "alpha gamma"
    # ambiguous after edit: two copies -> 409, still pending
    did2 = make_doc(c, "Alt2", content="one X two")
    cid2 = c.post(f"/api/docs/{did2}/suggestions", json={"old_string": "X", "new_string": "Y"}).json()["id"]
    asyncio.run(t.op_edit("alice", "owner", "/docs/Alt2", "one X two", "one X X"))
    assert c.post(f"/api/docs/{did2}/suggestions/{cid2}/accept").status_code == 409
    assert _status(cid2)[0] == "pending"
    assert _db_content(did2)[0] == "one X X"


# --- 6. quota + rollback ---

def test_quota_blocks_create(c, monkeypatch):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Kontingent", content="base")
    from backend.services import quota as q

    used = q.user_bytes("alice")
    _patch_quota(monkeypatch, used + 5)
    r = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "base", "new_string": "x" * 100})
    assert r.status_code == 413, r.text
    con = db.connect()
    try:
        assert con.execute("SELECT COUNT(*) AS n FROM comments WHERE doc_id=?", (did,)).fetchone()["n"] == 0
    finally:
        con.close()


def test_quota_blocks_accept_with_rollback(c, monkeypatch):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Annahme", content="short")
    cid = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "short", "new_string": "a much longer replacement"}).json()["id"]
    live_before = sync.room_text(did)
    db_before, _ = _db_content(did)
    from backend.services import quota as q

    used = q.user_bytes("alice")
    _patch_quota(monkeypatch, used + 1)  # growth no longer fits
    r = c.post(f"/api/docs/{did}/suggestions/{cid}/accept")
    assert r.status_code == 413, r.text
    # rollback: live + persisted + status untouched
    assert _db_content(did)[0] == db_before == "short"
    assert (sync.room_text(did) or db_before) == "short"
    assert _status(cid)[0] == "pending"
    void = live_before  # live was None (no room) or base; either way unchanged
    assert void is None or void == "short"


def test_failed_accept_leaves_source_intact(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "Rollback", content="keep me")
    assert c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "reviewer"}).status_code == 200
    login(c, "bob")
    cid = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "keep", "new_string": "KEEP"}).json()["id"]
    assert c.post(f"/api/docs/{did}/suggestions/{cid}/accept").status_code == 403
    assert _db_content(did)[0] == "keep me"
    assert _status(cid)[0] == "pending"


# --- 7. duplicate decisions ---

def test_duplicate_decisions_409(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Doppelt", content="a b c")
    c1 = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "a", "new_string": "A"}).json()["id"]
    assert c.post(f"/api/docs/{did}/suggestions/{c1}/accept").status_code == 200
    assert c.post(f"/api/docs/{did}/suggestions/{c1}/accept").status_code == 409
    assert c.post(f"/api/docs/{did}/suggestions/{c1}/reject").status_code == 409
    c2 = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "b", "new_string": "B"}).json()["id"]
    assert c.post(f"/api/docs/{did}/suggestions/{c2}/reject").status_code == 200
    assert c.post(f"/api/docs/{did}/suggestions/{c2}/reject").status_code == 409
    assert c.post(f"/api/docs/{did}/suggestions/{c2}/accept").status_code == 409


# --- 8. collaboration + listing parity ---

def test_collaboration_flow_and_listing(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "Team", content="launch the rocket soon")
    assert c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "reviewer"}).status_code == 200
    login(c, "bob")
    cid = c.post(
        f"/api/docs/{did}/suggestions", json={"old_string": "rocket", "new_string": "starship", "text": "nicer"}
    ).json()["id"]
    # reviewer sees own pending suggestion via both APIs
    assert t.op_suggestions("bob", "reviewer", "/shared/alice/Team")["suggestions"][0]["status"] == "pending"
    login(c, "alice")
    assert c.post(f"/api/docs/{did}/suggestions/{cid}/accept").status_code == 200
    assert _db_content(did)[0] == "launch the starship soon"
    got = t.op_suggestions("alice", "owner", "/docs/Team")["suggestions"]
    # UI-equivalent projection: quote follows the accepted text, no full anchor history
    assert [(s["quote"], s["status"]) for s in got] == [("starship", "accepted")]
    rest = c.get(f"/api/docs/{did}/comments").json()["comments"]
    assert [x["suggestion_status"] for x in rest if x["id"] == cid] == ["accepted"]


def test_multiple_suggestions_independent(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Mehrere", content="one two three")
    c1 = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "one", "new_string": "1"}).json()["id"]
    c2 = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "two", "new_string": "2"}).json()["id"]
    assert c.post(f"/api/docs/{did}/suggestions/{c1}/accept").status_code == 200
    assert _status(c2)[0] == "pending"  # sibling untouched
    assert c.post(f"/api/docs/{did}/suggestions/{c2}/reject").status_code == 200
    assert _db_content(did)[0] == "1 two three"


def test_anchor_is_one_based_line(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Zeilen", content="l1\nl2 target\nl3\n")
    cid = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "target", "new_string": "T"}).json()["id"]
    con = db.connect()
    try:
        assert con.execute("SELECT anchor FROM comments WHERE id=?", (cid,)).fetchone()["anchor"] == 2
    finally:
        con.close()


def test_trashed_blocks_suggest_decide(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Papierkorb", content="a b")
    cid = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "a", "new_string": "A"}).json()["id"]
    assert c.delete(f"/api/docs/{did}").status_code == 200
    assert c.post(f"/api/docs/{did}/suggestions", json={"old_string": "b", "new_string": "B"}).status_code == 410
    assert c.post(f"/api/docs/{did}/suggestions/{cid}/accept").status_code == 410
    assert c.post(f"/api/docs/{did}/suggestions/{cid}/reject").status_code == 410


def test_same_anchor_duplicates_second_goes_stale(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Dubletten", content="hello world")
    c1 = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "world", "new_string": "W1"}).json()["id"]
    c2 = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "world", "new_string": "W2"}).json()["id"]
    assert c.post(f"/api/docs/{did}/suggestions/{c1}/accept").status_code == 200
    assert _db_content(did)[0] == "hello W1"
    r = c.post(f"/api/docs/{did}/suggestions/{c2}/accept")
    assert r.status_code == 409, r.text
    assert _status(c2)[0] == "pending"


def test_cross_doc_cid_isolated(c):
    register_user(c, "alice")
    login(c, "alice")
    a = make_doc(c, "DocA", content="alpha beta")
    b = make_doc(c, "DocB", content="alpha beta")
    cid = c.post(f"/api/docs/{a}/suggestions", json={"old_string": "beta", "new_string": "B"}).json()["id"]
    assert c.post(f"/api/docs/{b}/suggestions/{cid}/accept").status_code == 409
    assert c.post(f"/api/docs/{b}/suggestions/{cid}/reject").status_code == 409
    assert _db_content(b)[0] == "alpha beta"
    assert _status(cid)[0] == "pending"


def test_accept_over_max_txt_rolls_back(c, monkeypatch):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Gross", content="abc")
    cid = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "abc", "new_string": "x" * 50}).json()["id"]
    monkeypatch.setattr("backend.services.suggestions.MAX_TXT", 10)
    r = c.post(f"/api/docs/{did}/suggestions/{cid}/accept")
    assert r.status_code == 400, r.text
    assert _db_content(did)[0] == "abc"
    assert _status(cid)[0] == "pending"


# --- 9. concurrency: duplicate decisions collapse to one winner ---

def test_concurrent_accept_single_winner(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Rennen", content="start middle end")
    cid = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "middle", "new_string": "MID"}).json()["id"]

    def _try_accept():
        try:
            suggestions.accept("alice", did, cid)
            return "ok"
        except HTTPException as e:
            return e.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda _: _try_accept(), range(8)))
    assert results.count("ok") == 1, results
    assert all(r == 409 for r in results if r != "ok"), results
    assert _status(cid)[0] == "accepted"
    assert _db_content(did)[0] == "start MID end"
    assert sync.room_text(did) == "start MID end"


def test_concurrent_accept_vs_reject_one_winner(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Duell", content="x y z")
    cid = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "y", "new_string": "Y"}).json()["id"]

    def _accept():
        try:
            suggestions.accept("alice", did, cid)
            return "accepted"
        except HTTPException as e:
            return e.status_code

    def _reject():
        try:
            suggestions.reject("alice", did, cid)
            return "rejected"
        except HTTPException as e:
            return e.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        a = ex.submit(_accept)
        b = ex.submit(_reject)
        ra, rb = a.result(), b.result()
    assert sorted([ra, rb], key=str) == sorted(["accepted", 409], key=str) or sorted(
        [ra, rb], key=str
    ) == sorted(["rejected", 409], key=str), (ra, rb)
    assert _status(cid)[0] in ("accepted", "rejected")


def _revoke(did, user):
    con = db.connect()
    try:
        con.execute("DELETE FROM shares WHERE doc_id=? AND username=?", (did, user))
        con.commit()
    finally:
        con.close()


def test_stale_grant_accept_reject_revoked_404(c, monkeypatch):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "Stale", content="hello world")
    assert c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "editor"}).status_code == 200
    login(c, "bob")
    cid = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "world", "new_string": "W"}).json()["id"]
    _revoke(did, "bob")
    monkeypatch.setattr(deps, "need_access", lambda *a, **k: "editor")
    got_accept = c.post(f"/api/docs/{did}/suggestions/{cid}/accept").status_code
    got_reject = c.post(f"/api/docs/{did}/suggestions/{cid}/reject").status_code
    assert (got_accept, got_reject) == (404, 404), f"accept={got_accept} reject={got_reject}"


def test_stale_grant_accept_downgraded_403(c, monkeypatch):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "Stale2", content="hello world")
    assert c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "editor"}).status_code == 200
    login(c, "bob")
    cid = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "world", "new_string": "W"}).json()["id"]
    con = db.connect()
    try:
        con.execute("UPDATE shares SET role='reviewer' WHERE doc_id=? AND username=?", (did, "bob"))
        con.commit()
    finally:
        con.close()
    monkeypatch.setattr(deps, "need_access", lambda *a, **k: "editor")
    assert c.post(f"/api/docs/{did}/suggestions/{cid}/accept").status_code == 403
    assert c.post(f"/api/docs/{did}/suggestions/{cid}/reject").status_code == 403


# --- 8. reviewer griefing cap on pending suggestions (owner pays quota) ---

def test_pending_suggestion_cap_per_doc(c, monkeypatch):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Spamdeckel", content="one alpha beta gamma omega")
    monkeypatch.setattr(suggestions, "MAX_PENDING_PER_DOC", 2)
    first = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "alpha", "new_string": "A"})
    assert first.status_code == 200, first.text
    second = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "beta", "new_string": "B"})
    assert second.status_code == 200, second.text
    third = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "gamma", "new_string": "G"})
    assert third.status_code == 413, third.text
    # reject frees the budget again: cap counts PENDING suggestions only
    login(c, "alice")
    assert c.post(f"/api/docs/{did}/suggestions/{second.json()['id']}/reject").status_code == 200
    again = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "omega", "new_string": "O"})
    assert again.status_code == 200, again.text


def test_pending_suggestion_bytes_cap_per_doc(c, monkeypatch):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Spambytes", content="alpha beta gamma omega delta")
    monkeypatch.setattr(suggestions, "MAX_PENDING_BYTES_PER_DOC", 80)
    big = c.post(f"/api/docs/{did}/suggestions",
                 json={"old_string": "alpha", "new_string": "x" * 40})  # 5 + 40 = 45 <= 80
    assert big.status_code == 200, big.text
    more = c.post(f"/api/docs/{did}/suggestions",
                  json={"old_string": "beta", "new_string": "y" * 46})  # + 4 + 46 = 95 > 80
    assert more.status_code == 413, more.text
    # decided suggestions free their bytes again
    assert c.post(f"/api/docs/{did}/suggestions/{big.json()['id']}/reject").status_code == 200
    free = c.post(f"/api/docs/{did}/suggestions",
                  json={"old_string": "beta", "new_string": "y" * 46})
    assert free.status_code == 200, free.text


def test_accepted_suggestion_refreshes_quote(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Ankerquote", content="alpha beta gamma")
    accepted_id = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "beta", "new_string": "BETA"}).json()["id"]
    rejected_id = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "gamma", "new_string": "GAMMA"}).json()["id"]
    assert c.post(f"/api/docs/{did}/suggestions/{accepted_id}/accept").status_code == 200
    assert c.post(f"/api/docs/{did}/suggestions/{rejected_id}/reject").status_code == 200
    con = db.connect()
    try:
        rows = {r["id"]: r for r in con.execute("SELECT id, quote, replacement, suggestion_status FROM comments WHERE doc_id=?", (did,))}
    finally:
        con.close()
    # accepted: the old text no longer exists, the quote follows the accepted text
    assert rows[accepted_id]["suggestion_status"] == "accepted"
    assert rows[accepted_id]["quote"] == "BETA" == rows[accepted_id]["replacement"]
    # rejected: the quote still matches the existing text (per design)
    assert rows[rejected_id]["suggestion_status"] == "rejected"
    assert rows[rejected_id]["quote"] == "gamma"


def test_accept_records_undo_snapshot(c):
    register_user(c, "alice")
    login(c, "alice")
    did = make_doc(c, "Undo", content="keep this line")
    cid = c.post(f"/api/docs/{did}/suggestions", json={"old_string": "keep", "new_string": "KEEP"}).json()["id"]
    assert c.post(f"/api/docs/{did}/suggestions/{cid}/accept").status_code == 200
    con = db.connect()
    try:
        snaps = con.execute("SELECT content, label FROM snapshots WHERE doc_id=? AND label='suggestion-accept'",
                            (did,)).fetchall()
    finally:
        con.close()
    assert [(s["label"], s["content"]) for s in snaps] == [("suggestion-accept", "keep this line")], snaps
