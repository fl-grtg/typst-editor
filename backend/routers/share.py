"""Sharing, members and invite routes."""
from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request

from backend import auth, db, deps, sync
from backend.constants import INVITE_SECONDS
from backend.schemas import InviteNew, JoinBody, Share
from backend.services.sidebar import notify_sidebar

log = logging.getLogger("typst.main")

router = APIRouter()


@router.post("/api/docs/{doc_id}/share")
async def share_doc(doc_id: str, b: Share, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "share")
    if deps.need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Only owner can invite")
    if b.role not in ("editor", "reviewer"):
        raise HTTPException(400, "role must be editor or reviewer")
    downgraded = False
    # B5: single tx with the owner check on the tx connection (the outer
    # need_access is a fast-path only); invite/share writes commit atomically.
    with db.tx() as con:
        if deps._tx_role(con, user, doc_id) != "owner":
            raise HTTPException(403, "Only owner can invite")
        if not con.execute("SELECT 1 FROM users WHERE name=?", (b.username,)).fetchone():
            raise HTTPException(400, "Sharing failed")
        prev = con.execute("SELECT role FROM shares WHERE doc_id=? AND username=?",
                           (doc_id, b.username)).fetchone()
        con.execute("INSERT INTO shares (doc_id, username, role) VALUES (?,?,?) "
                    "ON CONFLICT (doc_id, username) DO UPDATE SET role=excluded.role",
                    (doc_id, b.username, b.role))
        if prev and prev["role"] != b.role:
            if b.role == "reviewer" and prev["role"] == "editor":
                downgraded = True
                # invites carry no username (token -> doc + role), so per-user delete
                # is impossible without migration; wipe editor links fail-closed.
                con.execute("DELETE FROM invites WHERE doc_id=? AND role='editor'",
                            (doc_id,))
    sync.drop_role_cache(b.username)
    if downgraded:
        await sync.kick_user(doc_id, b.username)
    notify_sidebar(b.username)  # sharee's list changed
    return {"ok": True}


@router.delete("/api/docs/{doc_id}/share/{username}")
async def unshare_doc(doc_id: str, username: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "share")
    if deps.need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Only owner can remove")
    # B5+B24: single tx with the owner check on the tx connection (the outer
    # need_access is a fast-path only). B24: only wipe invites when a share
    # row was actually removed — unsharing a never-shared username must not
    # nuke every pending link (fail-closed wipe stays for real removals, and
    # per-invite attribution would need a migration, which is out of scope).
    with db.tx() as con:
        if deps._tx_role(con, user, doc_id) != "owner":
            raise HTTPException(403, "Only owner can remove")
        cur = con.execute("DELETE FROM shares WHERE doc_id=? AND username=?", (doc_id, username))
        if cur.rowcount == 0:
            raise HTTPException(404, "Not shared")
        # invites carry no username (token -> doc + role), so per-user delete is
        # impossible without migration; wipe all links fail-closed (no rejoin).
        con.execute("DELETE FROM invites WHERE doc_id=?", (doc_id,))
    await sync.kick_user(doc_id, username)
    notify_sidebar(username)  # ex-sharee's list changed
    return {"ok": True}


@router.post("/api/docs/{doc_id}/invite")
def make_invite(doc_id: str, b: InviteNew, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "invite")
    if deps.need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Only owner can invite")
    if b.role not in ("editor", "reviewer"):
        raise HTTPException(400, "role must be editor or reviewer")
    tok = db.new_id("")
    # hint is an independent random id for listing/deleting invites: it must
    # NOT derive from the token (tok[:8] would leak 48 bits and help guessing).
    hint = secrets.token_hex(4)
    con = db.connect()
    try:
        cut = (datetime.now(UTC) - timedelta(seconds=INVITE_SECONDS)).isoformat()
        if con.execute("SELECT COUNT(*) AS n FROM invites WHERE doc_id=? AND created_at>?",
                       (doc_id, cut)).fetchone()["n"] >= 20:
            raise HTTPException(400, "Too many invites")
        con.execute("INSERT INTO invites (token, doc_id, role, hint, created_at) VALUES (?,?,?,?,?)",
                    (auth.sha(tok), doc_id, b.role, hint, db.now_iso()))
        con.commit()
        # Link invites are intentionally multi-use: redeeming does NOT delete
        # the invite (see _redeem_invite); owners revoke via DELETE invites.
        return {"token": tok}
    finally:
        con.close()


@router.get("/api/docs/{doc_id}/invites")
def list_invites(doc_id: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list")
    deps.check_doc_id(doc_id)
    if deps.need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Only owner")
    con = db.connect()
    try:
        cut = (datetime.now(UTC) - timedelta(seconds=INVITE_SECONDS)).isoformat()
        rows = con.execute("SELECT hint, role, created_at FROM invites WHERE doc_id=? AND created_at>? "
                           "ORDER BY created_at", (doc_id, cut)).fetchall()
        return {"invites": [dict(r) for r in rows]}
    finally:
        con.close()


@router.delete("/api/docs/{doc_id}/invites/{hint}")
def drop_invite(doc_id: str, hint: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "invite")
    if deps.need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Only owner")
    con = db.connect()
    try:
        n = con.execute("SELECT COUNT(*) AS n FROM invites WHERE doc_id=? AND hint=?", (doc_id, hint)).fetchone()["n"]
        if n != 1:
            raise HTTPException(409, "Ambiguous hint - recreate invites one by one")
        con.execute("DELETE FROM invites WHERE doc_id=? AND hint=?", (doc_id, hint))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@router.post("/api/join/{token}")
def join_doc(token: str, req: Request, user: str = Depends(deps.me)) -> dict:
    raise HTTPException(410, "Use POST /api/join with body")


@router.post("/api/join")
def join_doc_body(b: JoinBody, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "join")
    return _redeem_invite(b.token.strip(), user)


def _redeem_invite(token: str, user: str) -> dict:
    # Link invites are intentionally multi-use (no delete after redeem):
    # anyone with the link joins; only expiry or owner revoke invalidates.
    con = db.connect()
    try:
        inv = con.execute("SELECT doc_id, role, created_at FROM invites WHERE token=?",
                          (auth.sha(token),)).fetchone()
        if not inv:
            inv = con.execute("SELECT doc_id, role, created_at FROM invites WHERE token=?",
                              (token,)).fetchone()
            if inv:
                log.warning("legacy plaintext invite migrated")
                try:
                    con.execute("UPDATE invites SET token=? WHERE token=?", (auth.sha(token), token))
                    con.commit()
                except Exception as e:
                    log.warning("invite migrate failed: %s", e)
        if not inv:
            raise HTTPException(404, "Invite invalid")
        cut = (datetime.now(UTC) - timedelta(seconds=INVITE_SECONDS)).isoformat()
        if (inv["created_at"] or "") < cut:
            con.execute("DELETE FROM invites WHERE token=? OR token=?",
                        (auth.sha(token), token))
            con.commit()
            raise HTTPException(404, "Invite invalid")
        d = con.execute("SELECT owner, trashed FROM docs WHERE id=?", (inv["doc_id"],)).fetchone()
        if not d:
            raise HTTPException(404, "Doc gone")
        if d["trashed"]:
            raise HTTPException(410, "In trash - restore first")
        if d["owner"] != user:
            con.execute("INSERT INTO shares (doc_id, username, role) VALUES (?,?,?) "
                        "ON CONFLICT (doc_id, username) DO NOTHING",
                        (inv["doc_id"], user, inv["role"]))
            con.commit()
            notify_sidebar(user)  # joiner's shared list changed
        return {"id": inv["doc_id"]}
    finally:
        con.close()


@router.get("/api/docs/{doc_id}/members")
def list_members(doc_id: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list")
    deps.check_doc_id(doc_id)
    deps.need_access(user, doc_id)
    con = db.connect()
    try:
        d = con.execute("SELECT owner FROM docs WHERE id=?", (doc_id,)).fetchone()
        if not d:
            raise HTTPException(404, "Doc gone")
        rows = con.execute("SELECT username FROM shares WHERE doc_id=? ORDER BY username", (doc_id,)).fetchall()
        return {"members": [d["owner"], *[r["username"] for r in rows]]}
    finally:
        con.close()
