"""B5: role re-checked ON the tx connection. B24: unshare role matrix.

The outer need_access/need_edit is a fast-path only: it opens its own
connection, so a grant can go stale between the check and BEGIN IMMEDIATE.
The stale-grant tests below simulate exactly that (revoke the share in the
DB, keep the outer check pinned to the old grant) and require the mutation
to fail anyway — proving the in-tx re-check is authoritative.
"""
import asyncio

import pytest
from conftest import login, make_doc, register_user
from fastapi import HTTPException

import backend.main as main
from backend import db
from backend import mcp_tools as t


def _revoke_share(did, user):
    con = db.connect()
    try:
        con.execute("DELETE FROM shares WHERE doc_id=? AND username=?", (did, user))
        con.commit()
    finally:
        con.close()


def _set_role(did, user, role):
    con = db.connect()
    try:
        con.execute("UPDATE shares SET role=? WHERE doc_id=? AND username=?", (role, did, user))
        con.commit()
    finally:
        con.close()


def _trash(did):
    con = db.connect()
    try:
        con.execute("UPDATE docs SET trashed=1 WHERE id=?", (did,))
        con.commit()
    finally:
        con.close()


def _setup_editor_doc(c):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "StaleGrant")
    assert c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "editor"}).status_code == 200
    return did


def test_tx_recheck_save_revoked(c, monkeypatch):
    did = _setup_editor_doc(c)
    _revoke_share(did, "bob")
    monkeypatch.setattr(main, "need_edit", lambda u, d: "editor")  # stale pre-tx grant
    login(c, "bob")
    assert c.post(f"/api/docs/{did}/save", json={"content": "hijack"}).status_code == 404
    assert c.get(f"/api/docs/{did}").status_code == 404  # no enumeration either way


def test_tx_recheck_save_downgraded(c, monkeypatch):
    did = _setup_editor_doc(c)
    login(c, "alice")
    assert c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "reviewer"}).status_code == 200
    monkeypatch.setattr(main, "need_edit", lambda u, d: "editor")  # stale: was editor
    login(c, "bob")
    assert c.post(f"/api/docs/{did}/save", json={"content": "hijack"}).status_code == 403


def test_tx_recheck_duplicate_revoked(c, monkeypatch):
    did = _setup_editor_doc(c)
    _revoke_share(did, "bob")
    monkeypatch.setattr(main, "need_edit", lambda u, d: "editor")
    login(c, "bob")
    assert c.post(f"/api/docs/{did}/duplicate").status_code == 404


def test_tx_recheck_duplicate_downgraded(c, monkeypatch):
    did = _setup_editor_doc(c)
    _set_role(did, "bob", "reviewer")
    monkeypatch.setattr(main, "need_edit", lambda u, d: "editor")
    login(c, "bob")
    assert c.post(f"/api/docs/{did}/duplicate").status_code == 403


def test_tx_recheck_snap_restore_revoked(c, monkeypatch):
    did = _setup_editor_doc(c)
    sid = c.post(f"/api/docs/{did}/snapshots", json={"label": "base"}).json()["id"]
    _revoke_share(did, "bob")
    monkeypatch.setattr(main, "need_edit", lambda u, d: "editor")
    login(c, "bob")
    assert c.post(f"/api/docs/{did}/snapshots/{sid}/restore").status_code == 404


def test_tx_recheck_share_after_trash(c, monkeypatch):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "TrashShare")
    _trash(did)
    monkeypatch.setattr(main, "need_access", lambda *a, **k: "owner")  # stale pre-tx grant
    assert c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "editor"}).status_code == 410


def test_tx_recheck_unshare_after_trash(c, monkeypatch):
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "TrashUnshare")
    assert c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "editor"}).status_code == 200
    _trash(did)
    monkeypatch.setattr(main, "need_access", lambda *a, **k: "owner")
    assert c.delete(f"/api/docs/{did}/share/bob").status_code == 410


# --- B24 unshare role matrix ---

def _invite(c, did, role="reviewer"):
    return c.post(f"/api/docs/{did}/invite", json={"role": role}).json()["token"]


def test_unshare_matrix(c):
    register_user(c, "alice")
    register_user(c, "bob")
    register_user(c, "carol")
    login(c, "alice")
    did = make_doc(c, "Matrix")
    assert c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "editor"}).status_code == 200
    login(c, "bob")
    assert c.delete(f"/api/docs/{did}/share/bob").status_code == 403  # editor cannot unshare
    assert c.post(f"/api/docs/{did}/share", json={"username": "carol", "role": "reviewer"}).status_code == 403
    login(c, "carol")
    assert c.delete(f"/api/docs/{did}/share/bob").status_code == 404  # stranger: no enumeration
    login(c, "alice")
    assert c.delete(f"/api/docs/{did}/share/bob").status_code == 200  # owner removes
    login(c, "bob")
    assert c.get(f"/api/docs/{did}").status_code == 404  # access gone


def test_unshare_noop_keeps_invites(c):
    # B24: unsharing a never-shared username is a 404 and must NOT wipe the
    # doc's pending invite links (previously any call nuked them all).
    register_user(c, "alice")
    register_user(c, "mallory")
    login(c, "alice")
    did = make_doc(c, "NoopUnshare")
    tok = _invite(c, did)
    assert c.delete(f"/api/docs/{did}/share/mallory").status_code == 404
    assert len(c.get(f"/api/docs/{did}/invites").json()["invites"]) == 1
    login(c, "mallory")
    assert c.post("/api/join", json={"token": tok}).json()["id"] == did  # link still valid


def test_unshare_real_removal_kills_invites(c):
    # Fail-closed wipe stays: a real removal kills every pending link (no rejoin).
    register_user(c, "alice")
    register_user(c, "bob")
    register_user(c, "carol")
    login(c, "alice")
    did = make_doc(c, "WipeUnshare")
    assert c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "editor"}).status_code == 200
    tok = _invite(c, did)
    assert c.delete(f"/api/docs/{did}/share/bob").status_code == 200
    assert c.get(f"/api/docs/{did}/invites").json()["invites"] == []
    login(c, "carol")
    assert c.post("/api/join", json={"token": tok}).status_code == 404


def test_unshare_scoped_to_doc(c):
    # Unsharing on doc A never touches doc B's invites.
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    a = make_doc(c, "DocA")
    b = make_doc(c, "DocB")
    assert c.post(f"/api/docs/{a}/share", json={"username": "bob", "role": "editor"}).status_code == 200
    tok_b = _invite(c, b)
    assert c.delete(f"/api/docs/{a}/share/bob").status_code == 200
    assert len(c.get(f"/api/docs/{b}/invites").json()["invites"]) == 1
    login(c, "bob")
    # bob holds no share on B, but the surviving link still redeems for its holder
    assert c.post("/api/join", json={"token": tok_b}).json()["id"] == b


def test_mcp_edit_stale_grant_fails(c, monkeypatch):
    # B5/F1: mcp op_edit resolves the path via db.doc_role (outer check) but
    # the tx must re-check on its own connection. Revoke the share, pin the
    # outer lookup to the stale grant: the edit must still fail and the
    # content must be unchanged (pre-fix the tx trusted the stale grant).
    register_user(c, "alice")
    register_user(c, "bob")
    login(c, "alice")
    did = make_doc(c, "McpStale", content="line1\nline2\n")
    assert c.post(f"/api/docs/{did}/share", json={"username": "bob", "role": "editor"}).status_code == 200
    _revoke_share(did, "bob")
    monkeypatch.setattr(db, "doc_role", lambda u, d: "editor")  # stale outer grant
    with pytest.raises(HTTPException) as e:
        asyncio.run(t.op_edit("bob", "editor", "/shared/alice/McpStale", "line1", "LINE1"))
    assert e.value.status_code == 403
    con = db.connect()
    try:
        got = con.execute("SELECT content FROM docs WHERE id=?", (did,)).fetchone()["content"]
    finally:
        con.close()
    assert got == "line1\nline2\n"
