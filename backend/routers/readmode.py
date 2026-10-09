"""Account-less reading via token (Wave 1D: function only, no UI).

Follow-up 3E owns the public share-link UI + routers/public.py; the
token model here (read_tokens table) is what it builds on.
"""
from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend import auth, db, deps

log = logging.getLogger("typst.main")

router = APIRouter()

READ_TOKEN_DAYS_MAX = 365


class ReadTokenNew(BaseModel):
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


def check_read_token(token: str) -> dict:
    """Validate a read token (check + expiry + trash). Raises 404/410."""
    tok = (token or "").strip()
    if not tok or len(tok) > 200:
        raise HTTPException(404, "Link invalid")
    con = db.connect()
    try:
        row = con.execute("SELECT doc_id, expires_at FROM read_tokens WHERE token_hash=?",
                          (auth.sha(tok),)).fetchone()
        if not row:
            raise HTTPException(404, "Link invalid")
        if row["expires_at"]:
            try:
                exp = datetime.fromisoformat(row["expires_at"])
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=UTC)
            except (ValueError, TypeError):
                exp = None
            if exp is None or exp < datetime.now(UTC):
                con.execute("DELETE FROM read_tokens WHERE token_hash=?", (auth.sha(tok),))
                con.commit()
                raise HTTPException(404, "Link invalid")
        d = con.execute("SELECT id, title, content, owner, updated_at, trashed FROM docs WHERE id=?",
                        (row["doc_id"],)).fetchone()
        if not d:
            raise HTTPException(404, "Doc gone")
        if d["trashed"]:
            raise HTTPException(410, "In trash")
        return {"id": d["id"], "title": d["title"], "content": d["content"],
                "owner": d["owner"], "updated_at": d["updated_at"]}
    finally:
        con.close()


@router.post("/api/docs/{doc_id}/read-token")
def make_read_token(doc_id: str, b: ReadTokenNew, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "invite")  # like other link tokens: tight bucket, exists in config
    if deps.need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Only owner can share read links")
    tok = secrets.token_urlsafe(32)
    hint = secrets.token_hex(4)
    now = db.now_iso()
    exp = ""
    if b.expires_in_days:
        exp = (datetime.now(UTC) + timedelta(days=min(b.expires_in_days, READ_TOKEN_DAYS_MAX))).isoformat()
    con = db.connect()
    try:
        con.execute("INSERT INTO read_tokens (token_hash, doc_id, hint, created_at, expires_at) "
                    "VALUES (?,?,?,?,?)", (auth.sha(tok), doc_id, hint, now, exp))
        con.commit()
        return {"token": tok, "hint": hint, "expires_at": exp}
    finally:
        con.close()


@router.get("/api/docs/{doc_id}/read-tokens")
def list_read_tokens(doc_id: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.limited(req, "files_list")
    deps.check_doc_id(doc_id)
    if deps.need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Only owner")
    con = db.connect()
    try:
        rows = con.execute("SELECT hint, created_at, expires_at FROM read_tokens WHERE doc_id=? "
                           "ORDER BY created_at", (doc_id,)).fetchall()
        return {"tokens": [dict(r) for r in rows]}
    finally:
        con.close()


@router.delete("/api/docs/{doc_id}/read-tokens/{hint}")
def drop_read_token(doc_id: str, hint: str, req: Request, user: str = Depends(deps.me)) -> dict:
    deps.check_doc_id(doc_id)
    deps.limited(req, "invite")
    if deps.need_access(user, doc_id) != "owner":
        raise HTTPException(403, "Only owner")
    con = db.connect()
    try:
        n = con.execute("SELECT COUNT(*) AS n FROM read_tokens WHERE doc_id=? AND hint=?",
                        (doc_id, hint)).fetchone()["n"]
        if n != 1:
            raise HTTPException(409, "Ambiguous hint - recreate tokens one by one")
        con.execute("DELETE FROM read_tokens WHERE doc_id=? AND hint=?", (doc_id, hint))
        con.commit()
        return {"ok": True}
    finally:
        con.close()


@router.get("/api/r/{token}")
def read_public(token: str, req: Request) -> dict:
    # No account: one charge on the IP bucket plus one on the per-token
    # bucket, so a hot link cannot starve other readers (RATE_READ_PER_MIN,
    # default 30/min, via deps.limited scope "read").
    deps.limited(req, "read", key=(token or "")[:16])
    return check_read_token(token)
